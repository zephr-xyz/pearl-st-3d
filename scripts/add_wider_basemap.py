#!/usr/bin/env python3
"""
Query Overpass for roads, parks, and landuse in the full scene bbox
and merge them into scene.json alongside the existing Pearl St core data.

Usage:
  python3 scripts/add_wider_basemap.py
  python3 scripts/add_wider_basemap.py --force   # re-download Overpass data
"""

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BBOX = (40.014, -105.2805, 40.026, -105.2710)  # S,W,N,E — matches building bbox
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_FILE = Path("output/overpass_basemap.json")

HIGHWAY_TO_CLASS = {
    "primary": "primary", "primary_link": "primary",
    "secondary": "tertiary", "secondary_link": "tertiary",
    "tertiary": "tertiary", "tertiary_link": "tertiary",
    "unclassified": "residential", "residential": "residential",
    "living_street": "residential",
    "service": "service",
    "footway": "footway", "path": "footway", "cycleway": "footway",
    "pedestrian": "pedestrian", "steps": "footway",
    "track": "service",
}
SKIP_HIGHWAY = {"motorway", "trunk", "motorway_link", "trunk_link", "construction", "proposed"}

LANDUSE_TO_SUBTYPE = {
    "park": "park", "recreation_ground": "recreation",
    "grass": "grass", "meadow": "managed", "village_green": "park",
    "allotments": "horticulture", "garden": "horticulture",
    "forest": "forest", "cemetery": "religious",
    "education": "education", "institutional": "education",
    "religious": "religious",
}
LEISURE_TO_SUBTYPE = {
    "park": "park", "recreation_ground": "recreation",
    "garden": "horticulture", "pitch": "recreation",
    "playground": "recreation", "nature_reserve": "protected",
    "dog_park": "park", "common": "park",
}
NATURAL_TO_SUBTYPE = {
    "grassland": "grass", "scrub": "managed", "wood": "forest",
    "heath": "managed",
}
# landuse types we skip (background context, not meaningful polygons)
SKIP_LANDUSE = {"commercial", "retail", "residential", "industrial", "mixed",
                "construction", "brownfield", "greenfield"}


def overpass_query(bbox):
    s, w, n, e = bbox
    bb = f"{s},{w},{n},{e}"
    query = f"""[out:json][timeout:60];
(
  way[highway]({bb});
  way[landuse]({bb});
  way[leisure]({bb});
  way[natural]({bb});
);
(._;>;);
out body;
"""
    print(f"Querying Overpass for bbox {bb}...")
    encoded = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        OVERPASS_URL, data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "pearl-st-3d/1.0"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read())


def to_scene_coords(lat, lon, ref_lat, ref_lon):
    m_lat = 111320
    m_lon = 111320 * math.cos(ref_lat * math.pi / 180)
    x = (lon - ref_lon) * m_lon
    z = (lat - ref_lat) * m_lat
    return x, z


def poly_area(pts):
    n = len(pts)
    a = 0
    for i in range(n):
        j = (i + 1) % n
        a += pts[i][0] * pts[j][1]
        a -= pts[j][0] * pts[i][1]
    return abs(a) / 2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="Re-download Overpass data")
    ap.add_argument("--scene", default="viewer/scene.json")
    args = ap.parse_args()

    # Load or download Overpass data
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_FILE.exists() and not args.force:
        print(f"Using cached Overpass data from {CACHE_FILE}")
        raw = json.loads(CACHE_FILE.read_text())
    else:
        raw = overpass_query(BBOX)
        CACHE_FILE.write_text(json.dumps(raw))
        print(f"Cached to {CACHE_FILE}")

    # Build node lookup
    nodes = {el["id"]: el for el in raw["elements"] if el["type"] == "node"}
    ways = [el for el in raw["elements"] if el["type"] == "way"]
    print(f"Overpass: {len(nodes)} nodes, {len(ways)} ways")

    # Load scene
    with open(args.scene) as f:
        scene = json.load(f)
    ref_lat = scene["ref_lat"]
    ref_lon = scene["ref_lon"]

    # Collect existing OSM IDs to avoid duplication (if stored)
    existing_osm_ids = set()
    for r in scene.get("roads", []):
        if "osm_id" in r:
            existing_osm_ids.add(r["osm_id"])
    for gf in scene.get("ground_features", []):
        if "osm_id" in gf:
            existing_osm_ids.add(gf["osm_id"])

    new_roads = []
    new_ground_features = []
    skipped_highway = 0
    skipped_dedup = 0
    skipped_landuse = 0

    for way in ways:
        tags = way.get("tags", {})
        osm_id = way["id"]
        if osm_id in existing_osm_ids:
            skipped_dedup += 1
            continue

        node_ids = way.get("nodes", [])
        # Resolve node lat/lon → scene [x, z]
        pts = []
        for nid in node_ids:
            nd = nodes.get(nid)
            if nd:
                x, z = to_scene_coords(nd["lat"], nd["lon"], ref_lat, ref_lon)
                pts.append([x, z])

        if len(pts) < 2:
            continue

        # --- HIGHWAY ---
        hw = tags.get("highway")
        if hw:
            if hw in SKIP_HIGHWAY:
                skipped_highway += 1
                continue
            cls = HIGHWAY_TO_CLASS.get(hw, "service")
            new_roads.append({
                "osm_id": osm_id,
                "name": tags.get("name", ""),
                "class": cls,
                "subclass": tags.get("service", ""),
                "points": pts,
            })
            continue

        # --- LANDUSE / LEISURE / NATURAL → ground_feature ---
        subtype = None
        lu = tags.get("landuse")
        if lu:
            if lu in SKIP_LANDUSE:
                skipped_landuse += 1
                continue
            subtype = LANDUSE_TO_SUBTYPE.get(lu)

        if subtype is None:
            ls = tags.get("leisure")
            if ls:
                subtype = LEISURE_TO_SUBTYPE.get(ls)

        if subtype is None:
            nat = tags.get("natural")
            if nat:
                subtype = NATURAL_TO_SUBTYPE.get(nat)

        if subtype is None:
            continue

        if len(pts) < 3:
            continue

        area = poly_area(pts)
        if area < 25:
            continue

        new_ground_features.append({
            "osm_id": osm_id,
            "subtype": subtype,
            "points": pts,
            "area": area,
        })

    print(f"\nNew roads: {len(new_roads)}")
    print(f"New ground_features: {len(new_ground_features)}")
    print(f"Skipped (dedup): {skipped_dedup}, (skip_highway): {skipped_highway}, (skip_landuse): {skipped_landuse}")

    # Road class breakdown
    cls_counts = {}
    for r in new_roads:
        cls_counts[r["class"]] = cls_counts.get(r["class"], 0) + 1
    print("Road classes:", cls_counts)

    subtype_counts = {}
    for gf in new_ground_features:
        subtype_counts[gf["subtype"]] = subtype_counts.get(gf["subtype"], 0) + 1
    print("Ground feature subtypes:", subtype_counts)

    # Merge into scene
    scene["roads"] = scene.get("roads", []) + new_roads
    scene["ground_features"] = scene.get("ground_features", []) + new_ground_features

    with open(args.scene, "w") as f:
        json.dump(scene, f, separators=(",", ":"))

    print(f"\nDone. scene.json now has {len(scene['roads'])} roads, "
          f"{len(scene['ground_features'])} ground_features")


if __name__ == "__main__":
    main()
