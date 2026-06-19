#!/usr/bin/env python3
"""
Enhance landmark buildings in viewer/scene.json with authoritative data.

Priority chain (first source that yields a value per field wins):
  1. Wikidata facts  — P2048 height, P149 arch_style, P571 era, P84 architect,
                       P1435 heritage, P18 image  (authoritative, beats everything)
  2. OSM tags        — height / building:levels
  3. VLM features    — keyword-inferred prior from visual_description
  4. MANUAL_OVERRIDES — last-resort escape hatch, shrinks as Wikidata grows
  5. plain extrusion — unchanged default
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")
DEFAULT_OUTPUT_DIR = str(_REPO_ROOT / "viewer")

METERS_PER_DEG_LAT = 111320.0

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WDQS_UA = (
    "pearl-st-3d/1.0 "
    "(https://github.com/zephr-xyz/pearl-st-3d; sean.gorman@zephr.xyz)"
)

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
    "Q1268134": "richardsonian_romanesque",
    "Q12720942": "art_deco",
    "Q186363":  "gothic_revival",
    "Q3947":    "house",
}

_OSM_EXTRA_TAGS = (
    "wikidata", "wikipedia", "start_date",
    "architect", "heritage", "architect:wikidata",
)


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


def _commons_thumb(filename: str, width: int = 800) -> str:
    """Convert a Wikimedia Commons filename to a thumbnail URL."""
    import hashlib
    fname = filename.replace(" ", "_")
    md5 = hashlib.md5(fname.encode("utf-8")).hexdigest()
    enc = urllib.parse.quote(fname, safe="")
    return (f"https://upload.wikimedia.org/wikipedia/commons/thumb/"
            f"{md5[0]}/{md5[:2]}/{enc}/{width}px-{enc}")


def load_osm_buildings(bbox, cache_path: str, force_refresh: bool = False) -> list:
    if not force_refresh and cache_path and os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    s, w, n, e = bbox
    query = (
        f'[out:json][timeout:30];'
        f'(way["building"]({s},{w},{n},{e});'
        f'relation["building"]({s},{w},{n},{e}););'
        f'out center tags;'
    )
    params = urllib.parse.urlencode({"data": query})
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=params.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    result = json.loads(urllib.request.urlopen(req, timeout=60).read())

    buildings = []
    for el in result["elements"]:
        tags = el.get("tags", {})
        center = el.get("center", {})
        lat, lon = center.get("lat", 0), center.get("lon", 0)
        if lat == 0:
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


def _fetch_entity(qid: str, cache_dir: str) -> dict:
    path = os.path.join(cache_dir, f"{qid}.json")
    if os.path.exists(path):
        data = json.load(open(path))
        # Re-fetch if cached before P18 image support was added
        if "image_fetched" not in data:
            os.remove(path)
        else:
            return data

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
    facts = {"image_fetched": True}

    facts["aliases"] = [a["value"] for a in entity.get("aliases", {}).get("en", [])]

    # P2048 height
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

    # P571 inception year → era
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

    # P149 architectural style
    for snak in claims.get("P149", []):
        try:
            style_q = snak["mainsnak"]["datavalue"]["value"]["id"]
            facts["arch_style"] = _STYLE_QID.get(style_q, style_q)
            break
        except (KeyError, TypeError):
            pass

    # P84 architect QIDs
    arch_qs = []
    for snak in claims.get("P84", []):
        try:
            arch_qs.append(snak["mainsnak"]["datavalue"]["value"]["id"])
        except (KeyError, TypeError):
            pass
    if arch_qs:
        facts["architect_qids"] = arch_qs

    # P1435 heritage designation
    for snak in claims.get("P1435", []):
        try:
            facts["heritage_qid"] = snak["mainsnak"]["datavalue"]["value"]["id"]
            break
        except (KeyError, TypeError):
            pass

    # P18 image (Wikimedia Commons)
    for snak in claims.get("P18", []):
        try:
            fname = snak["mainsnak"]["datavalue"]["value"]
            facts["image_commons"] = fname
            facts["image_url"] = _commons_thumb(fname, 800)
            break
        except (KeyError, TypeError):
            pass

    # P625 coord
    for snak in claims.get("P625", []):
        try:
            v = snak["mainsnak"]["datavalue"]["value"]
            facts["coord"] = {"lat": v["latitude"], "lon": v["longitude"]}
            break
        except (KeyError, TypeError):
            pass

    # P4896 3D model stub
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
    results = {}
    for qid in qids:
        facts = _fetch_entity(qid, cache_dir)
        results[qid] = facts
        print(f"  {qid}: h={facts.get('height_m','?')}m  "
              f"style={facts.get('arch_style', '-')}  era={facts.get('era', '-')}  "
              f"image={'image_url' in facts}")
    return results


def _fetch_wikidata_candidates(bld_latlons: dict, cache_dir: str) -> dict:
    cache_path = os.path.join(cache_dir, "_candidates.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    lats = [ll[0] for ll in bld_latlons.values()]
    lons = [ll[1] for ll in bld_latlons.values()]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)
    dlat = (max(lats) - min(lats)) * 111.32
    dlon = (max(lons) - min(lons)) * 111.32 * math.cos(math.radians(center_lat))
    radius_km = min(1.0, math.sqrt(dlat**2 + dlon**2) / 2 + 0.3)

    sparql = f"""
SELECT DISTINCT ?item ?itemLabel ?coord WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({center_lon:.5f} {center_lat:.5f})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius_km:.2f}" .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 200
"""
    params = urllib.parse.urlencode({"query": sparql, "format": "json"})
    req = urllib.request.Request(
        f"{WDQS_ENDPOINT}?{params}",
        headers={"User-Agent": WDQS_UA, "Accept": "application/sparql-results+json"},
    )
    candidates = {}
    try:
        resp = urllib.request.urlopen(req, timeout=60)
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

    print(f"  Enriching {len(candidates)} candidates with aliases…")
    for qid, ent in candidates.items():
        facts = _fetch_entity(qid, cache_dir)
        ent["aliases"] = facts.get("aliases", [])
        if facts.get("coord") and not ent["coord"]:
            ent["coord"] = facts["coord"]

    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(candidates, f, indent=2)
    return candidates


def _norm(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _name_score(bld_names: list, wd_names: list) -> float:
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
) -> tuple:
    OSM_MATCH_R = 20.0
    TIER2_R = 100.0   # increased from 30m — large block buildings (Boulderado) need more slack
    W_DIST, W_NAME, W_IDENT = 0.45, 0.45, 0.10
    THRESHOLD = 0.55

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

    qid_map: dict = {}
    used_qids: set = set()
    for bld in scene_buildings:
        bid = bld["id"]
        qid = osm_by_bid.get(bid, {}).get("wikidata")
        if qid:
            qid_map[bid] = {"qid": qid, "tier": 1, "composite": 1.0}
            used_qids.add(qid)

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
                    ds = 0.5

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
# VLM landmark feature extractor (fallback tier)
# ---------------------------------------------------------------------------
def extract_landmark_features(desc: str) -> dict:
    if not desc:
        return {}
    dl = desc.lower()
    f: dict = {}
    if "multi-tiered" in dl or "tiered" in dl: f["tiered"] = True
    if "tower" in dl or "central tower" in dl:  f["tower"] = True
    if "clock" in dl:                            f["clock"] = True
    if "dome" in dl or "cupola" in dl:           f["dome"] = True
    if "spire" in dl or "steeple" in dl:         f["spire"] = True
    if "turret" in dl:                           f["turret"] = True
    if "art deco" in dl:                         f["style"] = "art_deco"
    elif "romanesque" in dl:                     f["style"] = "romanesque"
    elif "victorian" in dl:                      f["style"] = "victorian"
    elif "neoclassical" in dl or "neo-classical" in dl: f["style"] = "neoclassical"
    elif "gothic" in dl:                         f["style"] = "gothic"
    if "marquee" in dl or "neon" in dl:          f["marquee"] = True
    if "bas-relief" in dl or "relief sculpture" in dl: f["bas_relief"] = True
    if "column" in dl or "pilaster" in dl:       f["columns"] = True
    if "pediment" in dl or "gable" in dl:        f["pediment"] = True
    if "cornice" in dl or "dentil" in dl:        f["cornice"] = True
    if "symmetrical" in dl:                      f["symmetrical"] = True
    m = re.search(r"(\d+)[- ]stor(?:y|ey|ied)", dl)
    if m:
        f["stories_from_desc"] = int(m.group(1))
    if "multi-story" in dl or "multi-tiered" in dl: f["min_stories"] = 3
    if "grand" in dl: f["grand"] = True
    return f


# ---------------------------------------------------------------------------
# Awning extraction from VLM description (VD-based awning pass)
# ---------------------------------------------------------------------------
_AWNING_COLORS = [
    ("yellow",     "#ccaa00"),
    ("gold",       "#ccaa00"),
    ("dark brown", "#3a1a0a"),
    ("dark metal", "#333333"),
    ("dark grey",  "#333333"),
    ("dark gray",  "#333333"),
    ("dark blue",  "#1a237e"),
    ("brown",      "#5c3a1a"),
    ("grey",       "#555555"),
    ("gray",       "#555555"),
    ("teal",       "#1a7a6a"),
    ("sage",       "#5a7a5a"),
    ("purple",     "#6a2a7a"),
    ("maroon",     "#6b1a1a"),
    ("burgundy",   "#6b1a1a"),
    ("navy",       "#1a237e"),
    ("blue",       "#1a3a6a"),
    ("green",      "#2a6a2a"),
    ("red",        "#cc2222"),
    ("black",      "#2a2a2a"),
    ("white",      "#e0e0e0"),
    ("cream",      "#d4c8a0"),
    ("orange",     "#cc6622"),
    ("dark",       "#333333"),
]


def _extract_awning_from_desc(desc: str):
    dl = desc.lower()
    if "awning" not in dl and "canopy" not in dl:
        return None
    style = "flat"
    _p = 50
    stripe_pat = (rf"(?:stripe|striped)[^.]{{0,{_p}}}(?:awning|canopy)"
                  rf"|(?:awning|canopy)[^.]{{0,{_p}}}(?:stripe|striped)")
    if re.search(stripe_pat, dl):
        style = "striped"
    elif re.search(r"\bslop|angled|slanted", dl):
        style = "slope"
    color = "#3a3a3a"
    for word, hex_color in _AWNING_COLORS:
        pat = (rf"(?:{re.escape(word)}[^.]{{0,50}}(?:awning|canopy)"
               rf"|(?:awning|canopy)[^.]{{0,50}}{re.escape(word)})")
        if re.search(pat, dl):
            color = hex_color
            break
    result = {"style": style, "color": color}
    if style == "striped":
        result["stripe_color"] = "rgba(255,255,255,0.45)"
    return result


# ---------------------------------------------------------------------------
# Manual overrides (last-resort escape hatch)
# ---------------------------------------------------------------------------
MANUAL_OVERRIDES = {
    "Boulder County Government":           {"height": 20.0, "stories": 4},
    "Boulder Theater":                     {"height": 14.0, "stories": 3},
    "Hotel Boulderado":                    {"height": 18.0, "stories": 5,
                                            "awning": {"color": "#2d6a2d", "style": "flat"},
                                            "accent": "#4a2e14"},
    "Wells Fargo Advisors":                {"height": 12.0, "stories": 3},
    "Independent Order of Odd Fellows":    {"height": 14.0, "stories": 3},
    "Free People":                         {"height": 12.0, "stories": 3},
}


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


def rescale_geometry(bld):
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


def _parse_args():
    p = argparse.ArgumentParser(
        description="Enhance scene.json with Wikidata/OSM/VLM priority chain.",
    )
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-wikidata", action="store_true")
    p.add_argument("--refresh-osm", action="store_true")
    return p.parse_args()


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

    desc_by_bld: dict = {}
    for wp in tile["waypoints"]:
        bid = wp.get("overture_building_id", "")
        desc = wp.get("visual_description", "")
        if bid and desc and len(desc) > len(desc_by_bld.get(bid, "")):
            desc_by_bld[bid] = desc

    bld_latlons: dict = {}
    for bld in scene["buildings"]:
        cx, cz = bld["centroid_m"]
        bld_latlons[bld["id"]] = (
            cz / METERS_PER_DEG_LAT + ref_lat,
            cx / m_lon + ref_lon,
        )

    for bld in scene["buildings"]:
        if "base_height" not in bld:
            bld["base_height"] = bld["height"]

    lats = [ll[0] for ll in bld_latlons.values()]
    lons = [ll[1] for ll in bld_latlons.values()]
    bbox = (min(lats) - 0.001, min(lons) - 0.001, max(lats) + 0.001, max(lons) + 0.001)
    osm_cache = os.path.join(data_dir, "osm_buildings.json")

    print("Loading OSM buildings…")
    osm_buildings = load_osm_buildings(bbox, osm_cache, force_refresh=args.refresh_osm)
    n_h = sum(1 for b in osm_buildings if b.get("height"))
    n_wd = sum(1 for b in osm_buildings if b.get("wikidata"))
    print(f"  total={len(osm_buildings)}  with_height={n_h}  with_wikidata_tag={n_wd}")

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
        qid_map, wd_facts = {}, {}
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

    print("\nApplying priority chain…")
    all_decisions: dict = {}

    for bld in scene["buildings"]:
        bid = bld["id"]
        style = bld.get("style", {})
        sty_src: dict = {}
        log: dict = {}
        pois = bld.get("pois", [])

        # ── Wikidata ──────────────────────────────────────────────────────
        q_entry = qid_map.get(bid)
        if q_entry:
            qid = q_entry["qid"]
            facts = wd_facts.get(qid, {})
            bld["wikidata_qid"] = qid
            bld["wikidata_tier"] = q_entry["tier"]
            bld["wikidata_composite"] = round(q_entry["composite"], 3)
            bld["wikidata_facts"] = {k: v for k, v in facts.items()
                                     if k not in ("aliases", "image_fetched")}

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
            if facts.get("image_url"):
                style["wikidata_image_url"] = facts["image_url"]
                style["wikidata_image_commons"] = facts.get("image_commons", "")
                log["image"] = "wikidata"
            if facts.get("model_3d_suppressed"):
                style["model_3d_suppressed"] = True

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
        for poi in pois:
            ov = MANUAL_OVERRIDES.get(poi)
            if ov:
                _set_height(bld, ov["height"], "manual", log)
                if bld.get("_h_src") == "manual":
                    style["stories"] = ov["stories"]
                if "awning" in ov:
                    style["awning"] = ov["awning"]
                if "accent" in ov:
                    style["accent"] = ov["accent"]
                break

        # ── VD-based awning pass (runs after manual overrides) ────────────
        if not any(MANUAL_OVERRIDES.get(p, {}).get("awning") for p in pois):
            if desc:
                vd_awning = _extract_awning_from_desc(desc)
                if vd_awning:
                    style["awning"] = vd_awning

        bld["style"] = style
        all_decisions[bid] = {
            "name":       (pois or [bid[:12]])[0],
            "height":     bld["height"],
            "base_height": bld.get("base_height"),
            "height_src": bld.get("_h_src", "default"),
            "decisions":  log,
            "qid":        q_entry["qid"] if q_entry else None,
            "tier":       q_entry["tier"] if q_entry else None,
            "composite":  q_entry["composite"] if q_entry else None,
        }

        rescale_geometry(bld)

    print("\n=== Priority-chain decisions (Wikidata matches) ===")
    for info in all_decisions.values():
        if not info["qid"]:
            continue
        qid_str = f"QID={info['qid']} T{info['tier']} {info['composite']:.2f}"
        dec = ", ".join(f"{k}:{v}" for k, v in info["decisions"].items()) or "—"
        print(f"  {info['name'][:35]:35s}  h={info['height']:5.1f}m "
              f"[{info['height_src']:8s}]  {qid_str}  [{dec}]")

    if args.dry_run:
        print("\n[dry-run] scene.json NOT written.")
        return

    for bld in scene["buildings"]:
        bld.pop("_h_src", None)

    out_path = os.path.join(output_dir, "scene.json")
    with open(out_path, "w") as f:
        json.dump(scene, f)

    n_qid = sum(1 for b in scene["buildings"] if b.get("wikidata_qid"))
    n_img = sum(1 for b in scene["buildings"]
                if b.get("style", {}).get("wikidata_image_url"))
    print(f"\nWrote {out_path}")
    print(f"  Buildings with Wikidata QID   : {n_qid} / {len(scene['buildings'])}")
    print(f"  Buildings with Wikidata image : {n_img}")
    print(f"  Heights corrected from base   : "
          f"{sum(1 for b in scene['buildings'] if b.get('base_height') != b['height'])}")


if __name__ == "__main__":
    main()
