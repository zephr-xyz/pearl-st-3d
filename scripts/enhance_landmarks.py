#!/usr/bin/env python3
"""
Enhance landmark buildings with better height estimates and architectural features.

Sources:
1. OSM building:levels / height tags (matched by centroid proximity)
2. VLM visual descriptions parsed for landmark features (towers, clocks, tiers, etc.)
3. Manual overrides for iconic buildings where all sources fail

Updates scene.json with corrected heights, stories, and landmark features that
drive enhanced procedural rendering in the viewer.
"""
import json
import math
import re
import urllib.request
import urllib.parse

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def dist_m(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * METERS_PER_DEG_LAT
    dx = (lon2 - lon1) * m_lng_at(lat1)
    return math.sqrt(dx * dx + dy * dy)


def fetch_osm_buildings(bbox):
    """Fetch all OSM buildings with height/levels in bbox."""
    import subprocess
    s, w, n, e = bbox
    query = f'[out:json][timeout:25];(way["building"]({s},{w},{n},{e});relation["building"]({s},{w},{n},{e}););out center tags;'
    cmd = ["curl", "-s", "https://overpass-api.de/api/interpreter", "--data-urlencode", f"data={query}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    result = json.loads(proc.stdout)

    buildings = []
    for el in result["elements"]:
        tags = el.get("tags", {})
        center = el.get("center", {})
        lat = center.get("lat", 0)
        lon = center.get("lon", 0)
        if lat == 0:
            continue

        height = None
        if tags.get("height"):
            try:
                height = float(tags["height"].replace("m", "").strip())
            except ValueError:
                pass
        if height is None and tags.get("building:levels"):
            try:
                height = float(tags["building:levels"]) * 3.5
            except ValueError:
                pass

        buildings.append({
            "name": tags.get("name", ""),
            "lat": lat,
            "lon": lon,
            "height": height,
            "levels": tags.get("building:levels"),
            "building_type": tags.get("building", "yes"),
        })

    return buildings


def extract_landmark_features(desc):
    """Extract architectural landmark features from VLM description."""
    if not desc:
        return {}

    dl = desc.lower()
    features = {}

    # Height indicators
    if "multi-tiered" in dl or "tiered" in dl:
        features["tiered"] = True
    if "tower" in dl or "central tower" in dl:
        features["tower"] = True
    if "clock" in dl:
        features["clock"] = True
    if "dome" in dl or "cupola" in dl:
        features["dome"] = True
    if "spire" in dl or "steeple" in dl:
        features["spire"] = True
    if "turret" in dl:
        features["turret"] = True

    # Style indicators
    if "art deco" in dl:
        features["style"] = "art_deco"
    elif "romanesque" in dl:
        features["style"] = "romanesque"
    elif "victorian" in dl:
        features["style"] = "victorian"
    elif "neoclassical" in dl or "neo-classical" in dl:
        features["style"] = "neoclassical"
    elif "gothic" in dl:
        features["style"] = "gothic"

    # Facade details
    if "marquee" in dl or "neon" in dl:
        features["marquee"] = True
    if "bas-relief" in dl or "relief sculpture" in dl:
        features["bas_relief"] = True
    if "column" in dl or "pilaster" in dl or "corinthian" in dl or "doric" in dl:
        features["columns"] = True
    if "pediment" in dl or "gable" in dl or "stepped gable" in dl:
        features["pediment"] = True
    if "cornice" in dl or "dentil" in dl:
        features["cornice"] = True
    if "symmetrical" in dl:
        features["symmetrical"] = True

    # Height estimates from description
    story_match = re.search(r"(\d+)[- ]stor(?:y|ey|ied)", dl)
    if story_match:
        features["stories_from_desc"] = int(story_match.group(1))
    if "multi-story" in dl or "multi-tiered" in dl:
        features["min_stories"] = 3
    if "grand" in dl:
        features["grand"] = True

    return features


# Ordered list: most-specific multi-word phrases first, then single words.
# Proximity match: color within 60 chars of awning/canopy in either direction.
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


def _extract_awning_from_desc(desc):
    """Return awning dict from a visual description, or None if no awning mentioned."""
    dl = desc.lower()
    if "awning" not in dl and "canopy" not in dl:
        return None
    style = "flat"
    _p = 50
    stripe_prox = (rf"(?:stripe|striped)[^.]{{0,{_p}}}(?:awning|canopy)"
                   rf"|(?:awning|canopy)[^.]{{0,{_p}}}(?:stripe|striped)")
    if re.search(stripe_prox, dl):
        style = "striped"
    elif re.search(r"\bslop|angled|slanted", dl):
        style = "slope"
    color = "#3a3a3a"
    for word, hex_color in _AWNING_COLORS:
        # [^.] blocks cross-sentence false positives (e.g. "maroon trim. Black awnings")
        pat = (rf"(?:{re.escape(word)}[^.]{{0,50}}(?:awning|canopy)"
               rf"|(?:awning|canopy)[^.]{{0,50}}{re.escape(word)})")
        if re.search(pat, dl):
            color = hex_color
            break
    result = {"style": style, "color": color}
    if style == "striped":
        result["stripe_color"] = "rgba(255,255,255,0.45)"
    return result


# Known heights/styles for iconic buildings where OSM is missing data
MANUAL_OVERRIDES = {
    "Boulder County Government": {"height": 20.0, "stories": 4},
    "Boulder Theater":           {"height": 14.0, "stories": 3},
    "Hotel Boulderado":          {"height": 18.0, "stories": 5,
                                  "awning": {"color": "#2d6a2d", "style": "flat"},
                                  "accent": "#4a2e14"},  # dark wood eaves; VD says white-framed but real building has brown trim
    "Wells Fargo Advisors":      {"height": 12.0, "stories": 3},
    "Independent Order of Odd Fellows": {"height": 14.0, "stories": 3},
    "Free People":               {"height": 12.0, "stories": 3},
}


def main():
    with open(f"{OUTPUT_DIR}/scene.json") as f:
        scene = json.load(f)

    with open(f"{DATA_DIR}/tile_x3400_y6201.json") as f:
        tile = json.load(f)

    ref_lat = scene["ref_lat"]
    ref_lon = scene["ref_lon"]
    m_lon = m_lng_at(ref_lat)

    # Build POI-to-building description map
    desc_by_bld = {}
    name_by_bld = {}
    for w in tile["waypoints"]:
        bid = w.get("overture_building_id", "")
        desc = w.get("visual_description", "")
        if bid and desc:
            if bid not in desc_by_bld or len(desc) > len(desc_by_bld[bid]):
                desc_by_bld[bid] = desc
                name_by_bld[bid] = w["name"]

    # Get building centroids in lat/lon
    bld_latlons = {}
    for bld in scene["buildings"]:
        cx = bld["centroid_m"][0]
        cz = bld["centroid_m"][1]
        lat = cz / METERS_PER_DEG_LAT + ref_lat
        lon = cx / m_lon + ref_lon
        bld_latlons[bld["id"]] = (lat, lon)

    # Fetch OSM buildings
    lats = [ll[0] for ll in bld_latlons.values()]
    lons = [ll[1] for ll in bld_latlons.values()]
    bbox = (min(lats) - 0.001, min(lons) - 0.001, max(lats) + 0.001, max(lons) + 0.001)

    print("Fetching OSM building data...")
    osm_buildings = fetch_osm_buildings(bbox)
    osm_with_height = [b for b in osm_buildings if b["height"]]
    print(f"  OSM buildings total: {len(osm_buildings)}")
    print(f"  With height/levels: {len(osm_with_height)}")

    # Match OSM buildings to our buildings by proximity
    osm_matches = {}
    for bld in scene["buildings"]:
        blat, blon = bld_latlons[bld["id"]]
        best_dist = 20  # max match distance in meters
        best_osm = None
        for osm_b in osm_with_height:
            d = dist_m(blat, blon, osm_b["lat"], osm_b["lon"])
            if d < best_dist:
                best_dist = d
                best_osm = osm_b
        if best_osm:
            osm_matches[bld["id"]] = best_osm

    print(f"  Matched to our buildings: {len(osm_matches)}")

    # Apply corrections
    height_corrected = 0
    landmarks_enhanced = 0

    for bld in scene["buildings"]:
        bid = bld["id"]
        style = bld.get("style", {})
        original_height = bld["height"]

        # 1. OSM height correction
        if bid in osm_matches:
            osm = osm_matches[bid]
            if osm["height"] and abs(osm["height"] - original_height) > 2:
                bld["height"] = osm["height"]
                style["stories"] = max(1, round(osm["height"] / 3.5))
                height_corrected += 1

        # 2. Manual overrides for iconic buildings
        pois = bld.get("pois", [])
        for poi_name in pois:
            if poi_name in MANUAL_OVERRIDES:
                override = MANUAL_OVERRIDES[poi_name]
                bld["height"] = override["height"]
                style["stories"] = override["stories"]
                if "awning" in override:
                    style["awning"] = override["awning"]
                if "accent" in override:
                    style["accent"] = override["accent"]
                height_corrected += 1

        # 2b. VD-based awning color correction (runs after manual overrides but
        #     only updates buildings not already pinned by MANUAL_OVERRIDES)
        if not any(poi in MANUAL_OVERRIDES and "awning" in MANUAL_OVERRIDES[poi]
                   for poi in pois):
            desc_vd = desc_by_bld.get(bid, "")
            if desc_vd:
                vd_awning = _extract_awning_from_desc(desc_vd)
                if vd_awning:
                    style["awning"] = vd_awning

        # 3. VLM landmark features
        desc = desc_by_bld.get(bid, "")
        if desc:
            features = extract_landmark_features(desc)
            if features:
                style["landmark_features"] = features
                landmarks_enhanced += 1

                # Correct height from description if it seems too low
                if features.get("tower") and bld["height"] < 15:
                    bld["height"] = max(bld["height"], 18.0)
                    style["stories"] = max(style.get("stories", 2), 4)
                elif features.get("grand") and bld["height"] < 10:
                    bld["height"] = max(bld["height"], 12.0)
                    style["stories"] = max(style.get("stories", 2), 3)
                elif features.get("min_stories") and style.get("stories", 2) < features["min_stories"]:
                    style["stories"] = features["min_stories"]
                    bld["height"] = max(bld["height"], features["min_stories"] * 3.5)

                # Apply architectural style override
                if features.get("style"):
                    style["arch_style"] = features["style"]

        # Recompute wall heights to match corrected building height
        if bld["height"] != original_height:
            ratio = bld["height"] / original_height if original_height > 0 else 1
            for wall in bld["walls"]:
                wall["height"] = bld["height"]
                # Scale Y coordinates of vertices
                for i, v in enumerate(wall["vertices"]):
                    if v[1] > 0:  # Non-ground vertices
                        wall["vertices"][i] = [v[0], v[1] * ratio, v[2]]
            # Scale roof vertices
            for tri in bld.get("roof", []):
                for i, v in enumerate(tri):
                    tri[i] = [v[0], v[1] * ratio, v[2]]
            # Scale roof features
            for feat in bld.get("roof_features", []):
                pass  # These are relative, no scaling needed

        bld["style"] = style

    # Save
    with open(f"{OUTPUT_DIR}/scene.json", "w") as f:
        json.dump(scene, f)

    print(f"\nResults:")
    print(f"  Heights corrected: {height_corrected}")
    print(f"  Landmarks enhanced: {landmarks_enhanced}")

    # Report notable corrections
    print("\nNotable height corrections:")
    for bld in scene["buildings"]:
        pois = bld.get("pois", [])
        if pois and bld.get("style", {}).get("landmark_features"):
            feats = bld["style"]["landmark_features"]
            feat_str = ", ".join(k for k in feats if k not in ("style", "stories_from_desc", "min_stories"))
            if feat_str:
                print(f"  {pois[0]}: {bld['height']:.0f}m, {bld['style'].get('stories',0)} stories — {feat_str}")


if __name__ == "__main__":
    main()
