#!/usr/bin/env python3
"""
Add surrounding residential / mixed-use buildings to scene.json.

Queries Overpass for all buildings in a wider bbox (2 blocks N/S of Pearl St),
skips those already in the scene (centroid proximity check), generates wall
geometry, and appends with style defaults based on OSM building type.

Usage:
  python3 scripts/add_surrounding_buildings.py --dry-run
  python3 scripts/add_surrounding_buildings.py
  python3 scripts/add_surrounding_buildings.py --bbox 40.015,-105.282,40.025,-105.270
"""

import argparse
import json
import math
import random
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

METERS_PER_DEG_LAT = 111320.0

# Skip these building types — not visually interesting or too small
SKIP_TYPES = {"garage", "garages", "shed", "parking", "roof", "kiosk"}

# Minimum footprint area (m²) — skip tiny outbuildings
MIN_AREA_M2 = 25.0

# How close (m) to an existing building centroid = already in scene
DUPLICATE_RADIUS_M = 10.0

# Default bbox: 2 blocks N/S of current Pearl St scene, same E/W extent
DEFAULT_BBOX = "40.014,-105.2805,40.026,-105.2710"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ── coordinate helpers ────────────────────────────────────────────────────────

def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def latlon_to_m(lat, lon, ref_lat, ref_lon):
    cx = (lon - ref_lon) * m_lng_at(ref_lat)
    cz = (lat - ref_lat) * METERS_PER_DEG_LAT
    return cx, cz


def polygon_area_signed(pts):
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0


def polygon_area_m2(pts_m):
    return abs(polygon_area_signed(pts_m))


def polygon_centroid(pts_m):
    n = len(pts_m)
    if n == 0:
        return 0.0, 0.0
    cx = sum(p[0] for p in pts_m) / n
    cz = sum(p[1] for p in pts_m) / n
    return cx, cz


def point_in_triangle(px, py, ax, ay, bx, by, cx, cy):
    denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denom) < 1e-12:
        return False
    u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denom
    v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denom
    return u >= -1e-10 and v >= -1e-10 and (1 - u - v) >= -1e-10


def triangulate(pts):
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]
    indices = list(range(n))
    if polygon_area_signed(pts) < 0:
        indices.reverse()
    tris = []
    remaining = list(indices)
    max_iter = n * n
    for _ in range(max_iter):
        if len(remaining) < 3:
            break
        nr = len(remaining)
        found = False
        for i in range(nr):
            pi = remaining[(i - 1) % nr]
            ci = remaining[i]
            ni = remaining[(i + 1) % nr]
            ax, ay = pts[pi]
            bx, by = pts[ci]
            cx, cy = pts[ni]
            if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) <= 0:
                continue
            ear = all(
                not point_in_triangle(pts[remaining[j]][0], pts[remaining[j]][1],
                                      ax, ay, bx, by, cx, cy)
                for j in range(nr)
                if remaining[j] not in (pi, ci, ni)
            )
            if ear:
                tris.append((pi, ci, ni))
                remaining.pop(i)
                found = True
                break
        if not found:
            break
    return tris


def edge_bearing(pts_m, i, cx, cz):
    n = len(pts_m)
    x0, z0 = pts_m[i]
    x1, z1 = pts_m[(i + 1) % n]
    dx, dz = x1 - x0, z1 - z0
    bearing = math.degrees(math.atan2(dx, dz)) % 360
    mid_x = (x0 + x1) / 2
    mid_z = (z0 + z1) / 2
    nx = math.sin(math.radians(bearing))
    nz = math.cos(math.radians(bearing))
    dot = (mid_x - cx) * nx + (mid_z - cz) * nz
    if dot < 0:
        bearing = (bearing + 180) % 360
    return bearing


def make_wall(p0, p1, h, idx, bearing):
    x0, z0 = p0
    x1, z1 = p1
    return {
        "vertices": [
            [x0, 0, z0], [x1, 0, z1], [x1, h, z1],
            [x0, 0, z0], [x1, h, z1], [x0, h, z0],
        ],
        "uvs": [
            [0, 0], [1, 0], [1, 1],
            [0, 0], [1, 1], [0, 1],
        ],
        "length": math.hypot(x1 - x0, z1 - z0),
        "height": h,
        "bearing": bearing,
        "is_exterior": True,
        "edge_index": idx,
        "entrances": [],
    }


# ── style defaults by building type ──────────────────────────────────────────

# Deterministic color variation seeded by OSM id
def _hash(s):
    h = 5381
    for c in s:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return h


def _vary(base_hex, seed, rng=12):
    h = _hash(seed)
    r = int(base_hex[1:3], 16)
    g = int(base_hex[3:5], 16)
    b = int(base_hex[5:7], 16)

    def v(ch, shift):
        delta = (((_hash(seed + str(shift)) >> 4) & 0xFF) / 255.0 - 0.5) * 2 * rng
        return max(0, min(255, int(ch + delta)))

    return "#{:02x}{:02x}{:02x}".format(v(r, 0), v(g, 1), v(b, 2))


STYLE_DEFAULTS = {
    "house": {
        "material": "brick", "base_color": "#b5895a",
        "stories": 1, "ground_floor": "residential",
        "windows": "standard", "roof_type": "pitched",
    },
    "semidetached_house": {
        "material": "brick", "base_color": "#b09070",
        "stories": 2, "ground_floor": "residential",
        "windows": "standard", "roof_type": "pitched",
    },
    "residential": {
        "material": "brick", "base_color": "#b08860",
        "stories": 2, "ground_floor": "residential",
        "windows": "standard", "roof_type": "flat",
    },
    "apartments": {
        "material": "brick", "base_color": "#c0956a",
        "stories": 3, "ground_floor": "residential",
        "windows": "standard", "roof_type": "flat",
    },
    "commercial": {
        "material": "brick", "base_color": "#9a8a78",
        "stories": 2, "ground_floor": "storefront",
        "windows": "commercial_small", "roof_type": "flat",
    },
    "retail": {
        "material": "brick", "base_color": "#9a8878",
        "stories": 1, "ground_floor": "storefront",
        "windows": "commercial_small", "roof_type": "flat",
    },
    "office": {
        "material": "concrete", "base_color": "#a0a8a8",
        "stories": 3, "ground_floor": "glass",
        "windows": "ribbon", "roof_type": "flat",
    },
    "hotel": {
        "material": "brick", "base_color": "#b09070",
        "stories": 4, "ground_floor": "storefront",
        "windows": "standard", "roof_type": "flat",
    },
    "church": {
        "material": "stone", "base_color": "#c8b890",
        "stories": 2, "ground_floor": "traditional",
        "windows": "arched", "roof_type": "pitched",
    },
    "civic": {
        "material": "stone", "base_color": "#c8c0a8",
        "stories": 2, "ground_floor": "traditional",
        "windows": "standard", "roof_type": "flat",
    },
    "public": {
        "material": "brick", "base_color": "#b0a090",
        "stories": 2, "ground_floor": "traditional",
        "windows": "standard", "roof_type": "flat",
    },
    "school": {
        "material": "brick", "base_color": "#c09070",
        "stories": 2, "ground_floor": "traditional",
        "windows": "standard", "roof_type": "flat",
    },
    "warehouse": {
        "material": "concrete", "base_color": "#909090",
        "stories": 1, "ground_floor": "traditional",
        "windows": "none", "roof_type": "flat",
    },
    "yes": {
        "material": "brick", "base_color": "#a89080",
        "stories": 1, "ground_floor": "residential",
        "windows": "standard", "roof_type": "flat",
    },
}
DEFAULT_STYLE_KEY = "yes"


def height_from_tags(osm_tags, default_stories):
    h = osm_tags.get("height")
    if h:
        try:
            return float(h.split()[0])
        except (ValueError, AttributeError):
            pass
    levels = osm_tags.get("building:levels")
    if levels:
        try:
            return float(levels) * 3.2
        except (ValueError, AttributeError):
            pass
    return default_stories * 3.2


# ── Overpass ─────────────────────────────────────────────────────────────────

def query_overpass(bbox_str):
    s, w, n, e = bbox_str.split(",")
    query = f"""
[out:json][timeout:60];
(
  way[building]({s},{w},{n},{e});
);
(._;>;);
out body;
""".strip()
    encoded = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        OVERPASS_URL,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "pearl-st-3d/1.0",
        },
    )
    print(f"Querying Overpass for bbox {bbox_str}...")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read())


def parse_overpass(result):
    nodes = {el["id"]: (el["lat"], el["lon"])
             for el in result["elements"] if el["type"] == "node"}
    buildings = []
    for el in result["elements"]:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        btype = tags.get("building", "yes")
        coords = []
        for nid in el.get("nodes", []):
            if nid in nodes:
                coords.append(nodes[nid])
        if len(coords) < 4:
            continue
        # Close ring
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        buildings.append({
            "osm_id": str(el["id"]),
            "building_type": btype,
            "tags": tags,
            "coords": coords[:-1],  # drop closing duplicate
        })
    return buildings


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="viewer/scene.json")
    ap.add_argument("--bbox", default=DEFAULT_BBOX)
    ap.add_argument("--overpass-cache", default="output/overpass_wider.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-cache", action="store_true", help="Re-fetch Overpass even if cached")
    args = ap.parse_args()

    with open(args.scene) as f:
        scene = json.load(f)

    ref_lat = scene["ref_lat"]
    ref_lon = scene["ref_lon"]

    # Build centroid lookup for duplicate detection
    existing_centroids = [
        (b["centroid_m"][0], b["centroid_m"][1])
        for b in scene["buildings"]
    ]

    def is_duplicate(cx, cz):
        for ex, ez in existing_centroids:
            if math.hypot(cx - ex, cz - ez) < DUPLICATE_RADIUS_M:
                return True
        return False

    # Fetch / load Overpass data
    cache_path = Path(args.overpass_cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not args.no_cache:
        print(f"Using cached Overpass data: {cache_path}")
        with open(cache_path) as f:
            raw = json.load(f)
    else:
        raw = query_overpass(args.bbox)
        cache_path.write_text(json.dumps(raw))
        print(f"Saved Overpass cache: {cache_path}")

    osm_buildings = parse_overpass(raw)
    print(f"Overpass returned {len(osm_buildings)} buildings")

    added = skipped_dup = skipped_type = skipped_small = 0
    new_buildings = []

    for ob in osm_buildings:
        btype = ob["building_type"]

        if btype in SKIP_TYPES:
            skipped_type += 1
            continue

        coords_m = [latlon_to_m(lat, lon, ref_lat, ref_lon)
                    for lat, lon in ob["coords"]]

        area = polygon_area_m2(coords_m)
        if area < MIN_AREA_M2:
            skipped_small += 1
            continue

        cx, cz = polygon_centroid(coords_m)

        if is_duplicate(cx, cz):
            skipped_dup += 1
            continue

        # Style
        sdef = STYLE_DEFAULTS.get(btype, STYLE_DEFAULTS[DEFAULT_STYLE_KEY])
        h = height_from_tags(ob["tags"], sdef["stories"])
        color = _vary(sdef["base_color"], ob["osm_id"])

        style = {
            "source": "osm",
            "material": sdef["material"],
            "color": color,
            "stories": sdef["stories"],
            "ground_floor": sdef["ground_floor"],
            "windows": sdef["windows"],
            "roof_type": sdef["roof_type"],
        }

        # Walls
        n = len(coords_m)
        walls = []
        for i in range(n):
            p0 = coords_m[i]
            p1 = coords_m[(i + 1) % n]
            wall_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if wall_len < 0.5:
                continue
            bearing = edge_bearing(coords_m, i, cx, cz)
            walls.append(make_wall(p0, p1, h, i, bearing))

        if not walls:
            continue

        # Roof triangles
        tris_idx = triangulate(coords_m)
        roof = []
        for ti, tj, tk in tris_idx:
            roof.append([
                [coords_m[ti][0], h, coords_m[ti][1]],
                [coords_m[tj][0], h, coords_m[tj][1]],
                [coords_m[tk][0], h, coords_m[tk][1]],
            ])

        bid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"osm:{ob['osm_id']}"))

        bld = {
            "id": bid,
            "osm_id": ob["osm_id"],
            "pois": [],
            "has_mapillary": False,
            "height": h,
            "style": style,
            "centroid_m": [cx, cz],
            "footprint_m": coords_m,
            "walls": walls,
            "roof": roof,
            "roof_color": "#808080",
            "base_height": 0,
        }
        new_buildings.append(bld)
        existing_centroids.append((cx, cz))  # prevent self-duplicates in same batch

        bname = ob["tags"].get("name", f"osm:{ob['osm_id']}")
        if args.dry_run:
            print(f"  + {bid[:8]}  type={btype:<18} h={h:.1f}m  area={area:.0f}m²  {bname[:40]}")
        else:
            print(f"  + {bid[:8]}  {btype:<18} {color}  {h:.1f}m  {bname[:40]}")

        added += 1

    print(f"\nNew buildings: {added}")
    print(f"Skipped — duplicate: {skipped_dup}, bad type: {skipped_type}, too small: {skipped_small}")

    if args.dry_run:
        print("\nDry run — nothing written.")
        return

    scene["buildings"].extend(new_buildings)
    with open(args.scene, "w") as f:
        json.dump(scene, f, separators=(",", ":"))
    print(f"\nWritten to {args.scene}  (total buildings: {len(scene['buildings'])})")


if __name__ == "__main__":
    main()
