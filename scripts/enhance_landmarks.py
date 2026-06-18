#!/usr/bin/env python3
"""
Enhance landmark buildings in viewer/scene.json with authoritative data.

Priority chain (first source that yields a value per field wins):
  1. Wikidata facts  — P2048 height, P149 arch_style, P571 era, P84 architect,
                       P1435 heritage  (authoritative, beats everything)
  2. OSM tags        — height / building:levels
  3. VLM features    — keyword-inferred prior from visual_description
  4. MANUAL_OVERRIDES — last-resort escape hatch, shrinks as Wikidata grows
  5. plain extrusion — unchanged default

RUN ORDER (strictly enforced by documentation — do not reorder):
  1. generate_scene_v3.py        → viewer/scene.json  (raw geometry)
  2. enhance_landmarks.py        → this script        (height + metadata)
  3. facade_projection.py        → Mapillary UV projection
  4. apply_facade_params.py      → VLM facade params → scene.json
  5. apply_textures_to_scene.py  → PBR texture paths  → scene.json

Running this script AFTER step 3 will stretch Mapillary UV coordinates
because vertex Y positions are rescaled to match corrected heights.

New fields added to scene.json buildings (viewer-additive, no renames):
  wikidata_qid, wikidata_tier, wikidata_composite, wikidata_facts
  style.arch_style, style.era, style.architect_qids, style.heritage_qid
  style.landmark_features, style.model_3d_suppressed
  base_height  (internal idempotency anchor, not rendered)
"""
import argparse
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo-relative path defaults
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")
DEFAULT_OUTPUT_DIR = str(_REPO_ROOT / "viewer")

METERS_PER_DEG_LAT = 111320.0

# ---------------------------------------------------------------------------
# Wikidata constants
# ---------------------------------------------------------------------------
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WDQS_UA = (
    "pearl-st-3d/1.0 "
    "(https://github.com/zephr-xyz/pearl-st-3d; sean.gorman@zephr.xyz)"
)

# Architecture style QID → string (subset relevant to Boulder / CO)
_STYLE_QID = {
    "Q152095":  "romanesque_revival",
    "Q604600":  "art_deco",
    "Q32465":   "gothic_revival",
    "Q1122677": "neoclassical",
    "Q211606":  "victorian",
    "Q1079694": "beaux_arts",
    "Q131285":  "tudor_revival",
    "Q5322082": "craftsman",
    "Q179872":  "italianate",
    "Q3947":    "house",  # avoid mapping residences to arch styles
}

# OSM tags to capture beyond height/levels
_OSM_EXTRA_TAGS = (
    "wikidata", "wikipedia", "start_date",
    "architect", "heritage", "architect:wikidata",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _m_lng(lat: float) -> float:
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    dy = (lat2 - lat1) * METERS_PER_DEG_LAT
    dx = (lon2 - lon1) * _m_lng(lat1)
    return math.sqrt(dx * dx + dy * dy)


def _era(year: int) -> str:
    if year < 1850: return "antebellum"
    if year < 1900: return "victorian"
    if year < 1920: return "edwardian"
    if year < 1945: return "interwar"
    if year < 1965: return "mid_century"
    if year < 1985: return "late_modern"
    return "contemporary"


# ---------------------------------------------------------------------------
# OSM fetch — persists full tag set as cache
# ---------------------------------------------------------------------------
def load_osm_buildings(bbox, cache_path: str, force_refresh: bool = False) -> list:
    """
    Load OSM buildings in bbox.  Writes cache_path on first fetch so reruns
    are deterministic and offline-friendly.
    """
    if not force_refresh and cache_path and os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    import subprocess
    s, w, n, e = bbox
    query = (
        f'[out:json][timeout:30];'
        f'(way["building"]({s},{w},{n},{e});'
        f'relation["building"]({s},{w},{n},{e}););'
        f'out center tags;'
    )
    cmd = [
        "curl", "-s", "https://overpass-api.de/api/interpreter",
        "--data-urlencode", f"data={query}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    elements = json.loads(proc.stdout).get("elements", [])

    buildings = []
    for el in elements:
        tags = el.get("tags", {})
        center = el.get("center", {})
        lat, lon = center.get("lat", 0), center.get("lon", 0)
        if not lat:
            continue

        height = None
        raw_h = tags.get("height", "")
        if raw_h:
            try:
                height = float(raw_h.split()[0].replace("m", "").strip())
            except ValueError:
                pass
        if height is None:
            raw_lvl = tags.get("building:levels", "")
            if raw_lvl:
                try:
                    height = float(raw_lvl.strip()) * 3.5
                except ValueError:
                    pass

        entry = {
            "name": tags.get("name", ""),
            "lat": lat, "lon": lon,
            "height": height,
            "levels": tags.get("building:levels"),
            "building_type": tags.get("building", "yes"),
        }
        for tag in _OSM_EXTRA_TAGS:
            if tags.get(tag):
                entry[tag] = tags[tag]
        buildings.append(entry)

    if cache_path:
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(buildings, f, indent=2)

    return buildings


# ---------------------------------------------------------------------------
# Wikidata entity facts (entity data API, per-QID cache)
# ---------------------------------------------------------------------------
def _fetch_entity(qid: str, cache_dir: str) -> dict:
    """Fetch structured facts for one QID; returns cached result if present."""
    path = os.path.join(cache_dir, f"{qid}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    req = urllib.request.Request(url, headers={"User-Agent": WDQS_UA})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw = json.loads(resp.read())
    except Exception as exc:
        print(f"  WARN: entity fetch {qid}: {exc}")
        return {}

    entity = raw.get("entities", {}).get(qid, {})
    claims = entity.get("claims", {})
    facts = {}

    # English altLabels (aliases) — critical for Tier-2 name matching
    facts["aliases"] = [a["value"] for a in entity.get("aliases", {}).get("en", [])]

    # P2048 height in metres (handles feet too)
    for snak in claims.get("P2048", []):
        try:
            v = snak["mainsnak"]["datavalue"]["value"]
            amount = abs(float(v["amount"].lstrip("+")))
            unit = v.get("unit", "")
            if "foot" in unit or "Q3710" in unit:
                amount *= 0.3048
            facts["height_m"] = round(amount, 1)
            break
        except (KeyError, ValueError, TypeError):
            pass

    # P571 inception year → era label
    for snak in claims.get("P571", []):
        try:
            t = snak["mainsnak"]["datavalue"]["value"]["time"]
            m = re.match(r"\+?(\d{4})", t)
            if m:
                yr = int(m.group(1))
                facts["inception_year"] = yr
                facts["era"] = _era(yr)
                break
        except (KeyError, TypeError):
            pass

    # P149 architectural style (first; QID → string via lookup)
    for snak in claims.get("P149", []):
        try:
            style_q = snak["mainsnak"]["datavalue"]["value"]["id"]
            facts["arch_style"] = _STYLE_QID.get(style_q, style_q)
            break
        except (KeyError, TypeError):
            pass

    # P84 architect (QIDs; label resolution would need extra fetch, omit)
    arch_qs = []
    for snak in claims.get("P84", []):
        try:
            arch_qs.append(snak["mainsnak"]["datavalue"]["value"]["id"])
        except (KeyError, TypeError):
            pass
    if arch_qs:
        facts["architect_qids"] = arch_qs

    # P1435 heritage designation (QID)
    for snak in claims.get("P1435", []):
        try:
            facts["heritage_qid"] = snak["mainsnak"]["datavalue"]["value"]["id"]
            break
        except (KeyError, TypeError):
            pass

    # P625 coord (for Tier-2 spatial cross-check)
    for snak in claims.get("P625", []):
        try:
            v = snak["mainsnak"]["datavalue"]["value"]
            facts["coord"] = {"lat": v["latitude"], "lon": v["longitude"]}
            break
        except (KeyError, TypeError):
            pass

    # P4896 3D model — stub only; photoreal repo means Commons STL is a downgrade
    for snak in claims.get("P4896", []):
        try:
            facts["model_3d_url"] = snak["mainsnak"]["datavalue"]["value"]
            facts["model_3d_suppressed"] = True
            break
        except (KeyError, TypeError):
            pass

    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump(facts, f, indent=2)

    time.sleep(0.1)
    return facts


def fetch_wikidata_facts(qids: list, cache_dir: str) -> dict:
    """Fetch facts for all QIDs; {qid: facts}."""
    results = {}
    for qid in qids:
        facts = _fetch_entity(qid, cache_dir)
        results[qid] = facts
        print(f"  {qid}: h={facts.get('height_m','?')}m  "
              f"style={facts.get('arch_style', '-')}  era={facts.get('era', '-')}")
    return results


# ---------------------------------------------------------------------------
# Wikidata candidate discovery (SPARQL bbox query, cached)
# ---------------------------------------------------------------------------
def _fetch_wikidata_candidates(bld_latlons: dict, cache_dir: str) -> dict:
    """
    SPARQL query for building-type entities in the scene bbox.
    Also fetches entity data per candidate (for aliases) — cached to <QID>.json.
    Returns {QID: {label, coord, aliases}}.
    """
    cache_path = os.path.join(cache_dir, "_candidates.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    lats = [ll[0] for ll in bld_latlons.values()]
    lons = [ll[1] for ll in bld_latlons.values()]
    s, n = min(lats) - 0.003, max(lats) + 0.003
    w, e = min(lons) - 0.003, max(lons) + 0.003

    sparql = f"""
SELECT DISTINCT ?item ?itemLabel ?coord WHERE {{
  ?item wdt:P625 ?coord ;
        wdt:P31/wdt:P279* wd:Q41176 .
  FILTER(geof:latitude(?coord) > {s} && geof:latitude(?coord) < {n}
      && geof:longitude(?coord) > {w} && geof:longitude(?coord) < {e})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 300
"""
    params = urllib.parse.urlencode({"query": sparql, "format": "json"})
    req = urllib.request.Request(
        f"{WDQS_ENDPOINT}?{params}",
        headers={"User-Agent": WDQS_UA, "Accept": "application/sparql-results+json"},
    )
    candidates = {}
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        for row in json.loads(resp.read()).get("results", {}).get("bindings", []):
            qid = row["item"]["value"].split("/")[-1]
            label = row.get("itemLabel", {}).get("value", "")
            coord_str = row.get("coord", {}).get("value", "")
            coord = None
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", coord_str)
            if m:
                coord = {"lon": float(m.group(1)), "lat": float(m.group(2))}
            candidates[qid] = {"label": label, "coord": coord, "aliases": []}
    except Exception as exc:
        print(f"  WARN: Wikidata SPARQL candidates failed: {exc}")

    # Enrich with aliases via entity data API (also pre-populates QID fact cache)
    print(f"  Enriching {len(candidates)} candidates with aliases…")
    for qid, ent in candidates.items():
        facts = _fetch_entity(qid, cache_dir)  # caches to <QID>.json
        ent["aliases"] = facts.get("aliases", [])
        if facts.get("coord") and not ent["coord"]:
            ent["coord"] = facts["coord"]

    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(candidates, f, indent=2)

    return candidates


# ---------------------------------------------------------------------------
# Two-tier QID resolver  (~55 lines, no conflation-package dependency)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _name_score(bld_names: list, wd_names: list) -> float:
    """Max token_set_ratio across all bld×wd pairings. 0.5 (neutral) if either empty."""
    if not bld_names or not wd_names:
        return 0.5
    from rapidfuzz import fuzz
    best = 0.0
    for a in bld_names:
        for b in wd_names:
            s = fuzz.token_set_ratio(_norm(a), _norm(b)) / 100.0
            if s > best:
                best = s
    return best


def resolve_qids(
    scene_buildings: list, osm_buildings: list, bld_latlons: dict, data_dir: str
) -> tuple[dict, dict]:
    """
    Returns (qid_map, osm_by_bid).

    qid_map   {building_id: {qid, tier, composite}}
    osm_by_bid {building_id: best OSM entry within 20m}

    Tier 1: OSM wikidata=* tag on the spatially-matched OSM building (trusted).
    Tier 2: composite = 0.45*dist_score + 0.45*name_score + 0.10*0.5 (neutral ID)
            Greedy one-to-one assignment above threshold 0.55; radius 30m.
    """
    OSM_MATCH_R = 20.0   # metres — OSM→Overture proximity
    TIER2_R = 30.0       # metres — Wikidata candidate radius
    W_DIST, W_NAME, W_IDENT = 0.45, 0.45, 0.10
    THRESHOLD = 0.55

    # Spatial match each building to nearest OSM entry
    osm_by_bid: dict = {}
    for bld in scene_buildings:
        bid = bld["id"]
        blat, blon = bld_latlons[bid]
        best_d, best_osm = OSM_MATCH_R, None
        for osm in osm_buildings:
            d = _dist_m(blat, blon, osm["lat"], osm["lon"])
            if d < best_d:
                best_d, best_osm = d, osm
        if best_osm:
            osm_by_bid[bid] = best_osm

    # Tier 1 — direct OSM wikidata tag
    qid_map: dict = {}
    used_qids: set = set()
    for bld in scene_buildings:
        bid = bld["id"]
        qid = osm_by_bid.get(bid, {}).get("wikidata")
        if qid:
            qid_map[bid] = {"qid": qid, "tier": 1, "composite": 1.0}
            used_qids.add(qid)

    # Tier 2 — fuzzy name + spatial composite against WDQS bbox candidates
    wd_cache = os.path.join(data_dir, "wikidata_cache")
    candidates = _fetch_wikidata_candidates(bld_latlons, wd_cache)
    avail = {q: c for q, c in candidates.items() if q not in used_qids}
    unmatched = [b for b in scene_buildings if b["id"] not in qid_map]

    if unmatched and avail:
        scored = []
        for bld in unmatched:
            bid = bld["id"]
            blat, blon = bld_latlons[bid]
            bld_names = list(bld.get("pois", []))
            osm_name = osm_by_bid.get(bid, {}).get("name", "")
            if osm_name:
                bld_names.append(osm_name)

            for qid, ent in avail.items():
                ent_coord = ent.get("coord")
                if ent_coord:
                    d = _dist_m(blat, blon, ent_coord["lat"], ent_coord["lon"])
                    if d > TIER2_R:
                        continue
                    ds = max(0.0, 1.0 - d / TIER2_R)
                else:
                    ds = 0.5  # neutral-on-null

                wd_names = [ent.get("label", "")] + ent.get("aliases", [])
                ns = _name_score(bld_names, wd_names)
                composite = W_DIST * ds + W_NAME * ns + W_IDENT * 0.5

                if composite >= THRESHOLD:
                    scored.append((composite, bid, qid))

        scored.sort(key=lambda x: -x[0])
        assigned_blds = set(qid_map)
        assigned_qids = set(used_qids)
        for composite, bid, qid in scored:
            if bid not in assigned_blds and qid not in assigned_qids:
                qid_map[bid] = {"qid": qid, "tier": 2, "composite": composite}
                assigned_blds.add(bid)
                assigned_qids.add(qid)

    return qid_map, osm_by_bid


# ---------------------------------------------------------------------------
# VLM feature extractor (demoted to fallback tier; unchanged logic)
# ---------------------------------------------------------------------------
def extract_landmark_features(desc: str) -> dict:
    if not desc:
        return {}
    dl = desc.lower()
    f: dict = {}
    if "multi-tiered" in dl or "tiered" in dl:   f["tiered"] = True
    if "tower" in dl or "central tower" in dl:    f["tower"] = True
    if "clock" in dl:                             f["clock"] = True
    if "dome" in dl or "cupola" in dl:            f["dome"] = True
    if "spire" in dl or "steeple" in dl:          f["spire"] = True
    if "turret" in dl:                            f["turret"] = True
    if "marquee" in dl or "neon" in dl:           f["marquee"] = True
    if "bas-relief" in dl or "relief sculpture" in dl: f["bas_relief"] = True
    if "column" in dl or "pilaster" in dl or "corinthian" in dl or "doric" in dl:
        f["columns"] = True
    if "pediment" in dl or "gable" in dl or "stepped gable" in dl: f["pediment"] = True
    if "cornice" in dl or "dentil" in dl:         f["cornice"] = True
    if "symmetrical" in dl:                       f["symmetrical"] = True
    if "art deco" in dl:              f["style"] = "art_deco"
    elif "romanesque" in dl:          f["style"] = "romanesque"
    elif "victorian" in dl:           f["style"] = "victorian"
    elif "neoclassical" in dl or "neo-classical" in dl: f["style"] = "neoclassical"
    elif "gothic" in dl:              f["style"] = "gothic"
    m = re.search(r"(\d+)[- ]stor(?:y|ey|ied)", dl)
    if m:
        f["stories_from_desc"] = int(m.group(1))
    if "multi-story" in dl or "multi-tiered" in dl:
        f["min_stories"] = 3
    if "grand" in dl:
        f["grand"] = True
    return f


# ---------------------------------------------------------------------------
# Manual overrides — last-resort escape hatch
# ---------------------------------------------------------------------------
MANUAL_OVERRIDES = {
    "Boulder County Government":          {"height": 20.0, "stories": 4},
    "Boulder Theater":                    {"height": 14.0, "stories": 3},
    "Hotel Boulderado":                   {"height": 18.0, "stories": 5},
    "Wells Fargo Advisors":               {"height": 12.0, "stories": 3},
    "Independent Order of Odd Fellows":   {"height": 14.0, "stories": 3},
    "Free People":                        {"height": 12.0, "stories": 3},
}

# ---------------------------------------------------------------------------
# Priority-chain helpers
# ---------------------------------------------------------------------------
_PRI = {"wikidata": 0, "osm": 1, "vlm": 2, "manual": 3, "default": 4}


def _set_height(bld, h, source, log):
    cur = bld.get("_h_src", "default")
    if _PRI.get(source, 9) < _PRI.get(cur, 9):
        bld["height"] = h
        bld["_h_src"] = source
        log["height"] = source
        return True
    return False


def _set_style(style, key, val, source, src_map, log):
    cur = src_map.get(key, "default")
    if _PRI.get(source, 9) < _PRI.get(cur, 9):
        style[key] = val
        src_map[key] = source
        log[key] = source
        return True
    return False


# ---------------------------------------------------------------------------
# Geometry rescaling — idempotent via base_height
# ---------------------------------------------------------------------------
def rescale_geometry(bld):
    """
    Rescale wall/roof vertices from base_height to current height.
    base_height is stamped on first run and never overwritten, so repeated
    runs always rescale from the original generator height — not from the
    previously corrected height.  This makes the operation idempotent.
    """
    base = bld.get("base_height", bld["height"])
    target = bld["height"]
    if abs(target - base) < 0.01:
        return
    ratio = target / base if base > 0 else 1.0
    for wall in bld.get("walls", []):
        wall["height"] = target
        for i, v in enumerate(wall["vertices"]):
            if v[1] > 0:
                wall["vertices"][i] = [v[0], v[1] * ratio, v[2]]
    for tri in bld.get("roof", []):
        for i, v in enumerate(tri):
            tri[i] = [v[0], v[1] * ratio, v[2]]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args():
    p = argparse.ArgumentParser(
        description="Enhance scene.json with Wikidata/OSM/VLM priority chain.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                   help="data/ directory (default: repo-relative)")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                   help="viewer/ directory containing scene.json")
    p.add_argument("--dry-run", action="store_true",
                   help="Print priority decisions without writing scene.json")
    p.add_argument("--no-wikidata", action="store_true",
                   help="Skip Wikidata fetch (OSM + VLM + overrides only)")
    p.add_argument("--refresh-osm", action="store_true",
                   help="Re-query Overpass even if osm_buildings.json exists")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = _parse_args()
    data_dir = args.data_dir
    output_dir = args.output_dir
    wd_cache_dir = os.path.join(data_dir, "wikidata_cache")

    with open(os.path.join(output_dir, "scene.json")) as f:
        scene = json.load(f)

    with open(os.path.join(data_dir, "tile_x3400_y6201.json")) as f:
        tile = json.load(f)

    ref_lat = scene["ref_lat"]
    ref_lon = scene["ref_lon"]
    m_lon = _m_lng(ref_lat)

    # Longest VLM description per building
    desc_by_bld: dict = {}
    for wp in tile["waypoints"]:
        bid = wp.get("overture_building_id", "")
        desc = wp.get("visual_description", "")
        if bid and desc and len(desc) > len(desc_by_bld.get(bid, "")):
            desc_by_bld[bid] = desc

    # Building centroid → lat/lon
    bld_latlons: dict = {}
    for bld in scene["buildings"]:
        cx, cz = bld["centroid_m"]
        bld_latlons[bld["id"]] = (
            cz / METERS_PER_DEG_LAT + ref_lat,
            cx / m_lon + ref_lon,
        )

    # Stamp base_height (first run only — idempotency anchor)
    for bld in scene["buildings"]:
        if "base_height" not in bld:
            bld["base_height"] = bld["height"]

    # OSM
    lats = [ll[0] for ll in bld_latlons.values()]
    lons = [ll[1] for ll in bld_latlons.values()]
    bbox = (min(lats) - 0.001, min(lons) - 0.001, max(lats) + 0.001, max(lons) + 0.001)
    osm_cache = os.path.join(data_dir, "osm_buildings.json")

    print("Loading OSM buildings…")
    osm_buildings = load_osm_buildings(bbox, osm_cache, force_refresh=args.refresh_osm)
    n_h = sum(1 for b in osm_buildings if b.get("height"))
    n_wd = sum(1 for b in osm_buildings if b.get("wikidata"))
    print(f"  total={len(osm_buildings)}  with_height={n_h}  with_wikidata_tag={n_wd}")

    # Wikidata QID resolution + fact fetch
    if not args.no_wikidata:
        print("\nResolving Wikidata QIDs…")
        qid_map, osm_by_bid = resolve_qids(
            scene["buildings"], osm_buildings, bld_latlons, data_dir
        )
        t1 = sum(1 for v in qid_map.values() if v["tier"] == 1)
        t2 = sum(1 for v in qid_map.values() if v["tier"] == 2)
        print(f"  resolved={len(qid_map)}  tier1(OSM tag)={t1}  tier2(fuzzy)={t2}")

        all_qids = list({v["qid"] for v in qid_map.values()})
        print(f"\nFetching Wikidata facts for {len(all_qids)} QIDs…")
        wd_facts = fetch_wikidata_facts(all_qids, wd_cache_dir)
    else:
        qid_map: dict = {}
        wd_facts: dict = {}
        # Still do OSM spatial match for height-only mode
        osm_by_bid = {}
        for bld in scene["buildings"]:
            bid = bld["id"]
            blat, blon = bld_latlons[bid]
            best_d, best = 20.0, None
            for osm in osm_buildings:
                d = _dist_m(blat, blon, osm["lat"], osm["lon"])
                if d < best_d:
                    best_d, best = d, osm
            if best:
                osm_by_bid[bid] = best

    # Priority chain
    print("\nApplying priority chain…")
    all_decisions: dict = {}

    for bld in scene["buildings"]:
        bid = bld["id"]
        style = bld.get("style", {})
        sty_src: dict = {}   # style-key → winning source
        log: dict = {}       # field → winning source (for report)

        # ── Wikidata ──────────────────────────────────────────────────────
        q_entry = qid_map.get(bid)
        if q_entry:
            qid = q_entry["qid"]
            facts = wd_facts.get(qid, {})
            bld["wikidata_qid"] = qid
            bld["wikidata_tier"] = q_entry["tier"]
            bld["wikidata_composite"] = round(q_entry["composite"], 3)
            bld["wikidata_facts"] = {k: v for k, v in facts.items() if k != "aliases"}

            if facts.get("height_m"):
                _set_height(bld, facts["height_m"], "wikidata", log)
                style["stories"] = max(1, round(facts["height_m"] / 3.5))
            if facts.get("arch_style"):
                _set_style(style, "arch_style", facts["arch_style"],
                           "wikidata", sty_src, log)
            if facts.get("era"):
                _set_style(style, "era", facts["era"], "wikidata", sty_src, log)
            if facts.get("architect_qids"):
                style["architect_qids"] = facts["architect_qids"]
                log["architect"] = "wikidata"
            if facts.get("heritage_qid"):
                style["heritage_qid"] = facts["heritage_qid"]
                log["heritage"] = "wikidata"
            if facts.get("model_3d_suppressed"):
                style["model_3d_suppressed"] = True  # stub; not rendered

        # ── OSM ───────────────────────────────────────────────────────────
        osm = osm_by_bid.get(bid, {})
        if osm.get("height"):
            _set_height(bld, osm["height"], "osm", log)
        if bld.get("_h_src") == "osm":
            style.setdefault("stories", max(1, round(bld["height"] / 3.5)))

        # ── VLM ───────────────────────────────────────────────────────────
        desc = desc_by_bld.get(bid, "")
        vlm = extract_landmark_features(desc)
        if vlm:
            style["landmark_features"] = vlm
            if vlm.get("style"):
                _set_style(style, "arch_style", vlm["style"], "vlm", sty_src, log)
            h_src = bld.get("_h_src", "default")
            if h_src not in ("wikidata", "osm"):
                if vlm.get("tower") and bld["height"] < 15:
                    _set_height(bld, max(bld["height"], 18.0), "vlm", log)
                    style["stories"] = max(style.get("stories", 2), 4)
                elif vlm.get("grand") and bld["height"] < 10:
                    _set_height(bld, max(bld["height"], 12.0), "vlm", log)
                    style["stories"] = max(style.get("stories", 2), 3)
                elif vlm.get("min_stories", 0) > style.get("stories", 2):
                    style["stories"] = vlm["min_stories"]
                    _set_height(bld, max(bld["height"], vlm["min_stories"] * 3.5),
                                "vlm", log)

        # ── Manual overrides ─────────────────────────────────────────────
        for poi in bld.get("pois", []):
            ov = MANUAL_OVERRIDES.get(poi)
            if ov:
                _set_height(bld, ov["height"], "manual", log)
                if bld.get("_h_src") == "manual":
                    style["stories"] = ov["stories"]
                break

        bld["style"] = style
        all_decisions[bid] = {
            "name":       bld.get("pois", [bid[:12]])[0],
            "height":     bld["height"],
            "base_height": bld.get("base_height"),
            "height_src": bld.get("_h_src", "default"),
            "decisions":  log,
            "qid":        q_entry["qid"] if q_entry else None,
            "tier":       q_entry["tier"] if q_entry else None,
            "composite":  q_entry["composite"] if q_entry else None,
        }

        rescale_geometry(bld)

    # Report (always printed, even without --dry-run)
    print("\n=== Priority-chain decisions ===")
    for info in all_decisions.values():
        if info["qid"]:
            qid_str = f"QID={info['qid']} T{info['tier']} {info['composite']:.2f}"
        else:
            qid_str = "no QID"
        dec = ", ".join(f"{k}:{v}" for k, v in info["decisions"].items()) or "—"
        print(f"  {info['name'][:35]:35s}  h={info['height']:5.1f}m "
              f"[{info['height_src']:8s}]  {qid_str}  [{dec}]")

    if args.dry_run:
        print("\n[dry-run] scene.json NOT written.")
        return

    # Strip internal tracking field before serialising
    for bld in scene["buildings"]:
        bld.pop("_h_src", None)

    out_path = os.path.join(output_dir, "scene.json")
    with open(out_path, "w") as f:
        json.dump(scene, f)

    n_qid = sum(1 for b in scene["buildings"] if b.get("wikidata_qid"))
    print(f"\nWrote {out_path}")
    print(f"  Buildings with Wikidata QID : {n_qid} / {len(scene['buildings'])}")
    print(f"  Heights corrected from base : "
          f"{sum(1 for b in scene['buildings'] if b.get('base_height') != b['height'])}")


if __name__ == "__main__":
    main()
