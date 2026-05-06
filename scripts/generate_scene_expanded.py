#!/usr/bin/env python3
"""
Generate full 275-building scene.json using expanded data files.
Uses ear-clipping triangulation for correct concave polygon roofs.
"""
import json
import math

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def latlon_to_meters(lat, lon, ref_lat, ref_lon):
    dlat = (lat - ref_lat) * METERS_PER_DEG_LAT
    dlon = (lon - ref_lon) * m_lng_at(ref_lat)
    return (dlon, dlat)


def polygon_area_signed(pts):
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0


def point_in_triangle(px, py, ax, ay, bx, by, cx, cy):
    denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denom) < 1e-12:
        return False
    u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denom
    v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denom
    w = 1.0 - u - v
    return u >= -1e-10 and v >= -1e-10 and w >= -1e-10


def triangulate_polygon(pts):
    """Ear-clipping triangulation for simple polygons (convex or concave)."""
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    indices = list(range(n))
    if polygon_area_signed(pts) < 0:
        indices.reverse()

    triangles = []
    remaining = list(indices)

    max_iter = n * n
    iteration = 0
    while len(remaining) > 2 and iteration < max_iter:
        iteration += 1
        found_ear = False
        nr = len(remaining)
        for i in range(nr):
            prev_idx = remaining[(i - 1) % nr]
            curr_idx = remaining[i]
            next_idx = remaining[(i + 1) % nr]

            ax, ay = pts[prev_idx]
            bx, by = pts[curr_idx]
            cx, cy = pts[next_idx]

            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if cross <= 0:
                continue

            ear_valid = True
            for j in range(nr):
                check_idx = remaining[j]
                if check_idx in (prev_idx, curr_idx, next_idx):
                    continue
                if point_in_triangle(pts[check_idx][0], pts[check_idx][1],
                                     ax, ay, bx, by, cx, cy):
                    ear_valid = False
                    break

            if ear_valid:
                triangles.append((prev_idx, curr_idx, next_idx))
                remaining.pop(i)
                found_ear = True
                break

        if not found_ear:
            break

    return triangles


def edge_outward_bearing(coords_m, idx, n, cx, cy):
    """Compute outward-facing bearing using centroid test."""
    x0, y0 = coords_m[idx]
    x1, y1 = coords_m[(idx + 1) % n]

    dx = x1 - x0
    dy = y1 - y0
    edge_bearing = math.degrees(math.atan2(dx, dy)) % 360

    mid_x = (x0 + x1) / 2
    mid_y = (y0 + y1) / 2

    for sign in [1, -1]:
        normal = (edge_bearing + sign * 90) % 360
        nr = math.radians(normal)
        test_x = mid_x + 0.1 * math.sin(nr)
        test_y = mid_y + 0.1 * math.cos(nr)
        d_test = (test_x - cx)**2 + (test_y - cy)**2
        d_mid = (mid_x - cx)**2 + (mid_y - cy)**2
        if d_test > d_mid:
            return normal

    return edge_bearing


# Style assignment heuristics based on height/floors
STYLE_TEMPLATES = [
    {"material": "brick", "color": "#8B6B4A", "accent": "#f5f0e0",
     "windows": "traditional", "stories": 2, "awning": None,
     "signage": None, "ground_floor": "storefront"},
    {"material": "brick", "color": "#7a5a3a", "accent": "#d4c5a9",
     "windows": "office", "stories": 2, "awning": None,
     "signage": None, "ground_floor": "traditional"},
    {"material": "stucco", "color": "#c8bfb0", "accent": "#808080",
     "windows": "retail", "stories": 1, "awning": {"color": "#cc2222", "style": "slope"},
     "signage": None, "ground_floor": "storefront"},
    {"material": "painted_brick", "color": "#9e8b7a", "accent": "#ffffff",
     "windows": "office", "stories": 2, "awning": None,
     "signage": {"color": "#ffffff", "band_color": "#5c4a3a"},
     "ground_floor": "traditional"},
    {"material": "brick", "color": "#6b5b4a", "accent": "#ccaa00",
     "windows": "commercial_small", "stories": 2,
     "awning": {"color": "#2a5a2a", "style": "slope"},
     "signage": None, "ground_floor": "storefront"},
]

# Known original 10 buildings keep their specific styles
FACADE_STYLE = {
    "954cb30c-1eb3-41e2-b7b0-f6640a4c3595": {
        "material": "brick", "color": "#8B4513", "accent": "#1a237e",
        "windows": "large_plate_glass", "stories": 2,
        "awning": {"color": "#1a237e", "style": "flat"},
        "signage": {"color": "#ffffff", "band_color": "#1a237e"},
        "ground_floor": "storefront",
    },
    "e6ca7522-53d7-4842-a190-287b28b224f6": {
        "material": "brick", "color": "#4a4a4a", "accent": "#2a2a2a",
        "windows": "storefront_glass", "stories": 1,
        "awning": {"color": "#cc2222", "style": "slope"},
        "signage": {"color": "#ffffff", "band_color": "#333333"},
        "ground_floor": "full_glass",
    },
    "67797069-8ea7-4f97-8280-4ab9392d1bdf": {
        "material": "painted_brick", "color": "#6b8e6b", "accent": "#ffffff",
        "windows": "vertical_triple", "stories": 2,
        "awning": None,
        "signage": {"color": "#ffffff", "band_color": "#6b4b8a"},
        "ground_floor": "storefront",
    },
    "6bf9d300-d51d-428d-b923-519fc0f90351": {
        "material": "brick", "color": "#4a3728", "accent": "#ccaa00",
        "windows": "traditional", "stories": 2,
        "awning": {"color": "#2a5a2a", "style": "slope"},
        "signage": {"color": "#ccaa00", "band_color": "#4a3728", "shape": "circle"},
        "ground_floor": "storefront",
    },
    "f61c4184-d69c-4fc7-b873-1d42d8b69c8e": {
        "material": "brick_sandstone", "color": "#8B3A3A", "accent": "#f5f0e0",
        "windows": "romanesque_arched", "stories": 3,
        "awning": None,
        "signage": {"color": "#f5f0e0", "band_color": "#8B3A3A"},
        "ground_floor": "storefront",
        "pediment": True,
    },
    "bb6ab86f-1a76-4a4d-9a3e-9338fb05e067": {
        "material": "siding", "color": "#b8a590", "accent": "#808080",
        "windows": "residential", "stories": 1,
        "awning": None, "signage": None, "ground_floor": "traditional",
    },
    "b64dc737-f797-43fa-98f8-8fffa62c2338": {
        "material": "stucco", "color": "#9e8b7a", "accent": "#5c4a3a",
        "windows": "office", "stories": 2,
        "awning": None, "signage": None, "ground_floor": "traditional",
    },
    "6c30df94-a81e-4f61-b05c-f5087093cdce": {
        "material": "brick", "color": "#7a6b5a", "accent": "#4a3728",
        "windows": "commercial_small", "stories": 2,
        "awning": {"color": "#3a5a3a", "style": "slope"},
        "signage": None, "ground_floor": "storefront",
    },
    "87322f55-be84-4bf4-8582-17d979622abf": {
        "material": "brick", "color": "#8B6B4A", "accent": "#f5f0e0",
        "windows": "office", "stories": 2,
        "awning": None,
        "signage": {"color": "#f5f0e0", "band_color": "#8B6B4A"},
        "ground_floor": "traditional",
    },
    "78f21e0e-2859-4e6c-b5a6-8be6abd53b80": {
        "material": "painted_brick", "color": "#5a7a5a", "accent": "#ffffff",
        "windows": "retail", "stories": 2,
        "awning": {"color": "#cc2222", "style": "slope"},
        "signage": None, "ground_floor": "storefront",
    },
}


def assign_style(bld_id, height, num_floors):
    if bld_id in FACADE_STYLE:
        return FACADE_STYLE[bld_id]
    # Deterministic assignment based on building id hash
    idx = hash(bld_id) % len(STYLE_TEMPLATES)
    style = dict(STYLE_TEMPLATES[idx])
    if num_floors:
        style["stories"] = num_floors
    elif height:
        style["stories"] = max(1, round(height / 3.5))
    return style


def main():
    with open(f"{DATA_DIR}/building_footprints_expanded.json") as f:
        footprints = json.load(f)

    with open(f"{DATA_DIR}/roads_expanded.json") as f:
        roads_raw = json.load(f)

    with open(f"{DATA_DIR}/street_furniture_expanded.json") as f:
        furniture_raw = json.load(f)

    with open(f"{DATA_DIR}/roof_features_expanded.json") as f:
        roof_features = json.load(f)

    with open(f"{DATA_DIR}/infrastructure.json") as f:
        infra_raw = json.load(f)

    with open(f"{DATA_DIR}/ground_features.json") as f:
        ground_features = json.load(f)

    with open(f"{DATA_DIR}/block_summary.json") as f:
        summary = json.load(f)

    # Reference point (scene center)
    all_coords = []
    for bld in footprints.values():
        all_coords.extend(bld["coordinates"])
    ref_lat = sum(c[0] for c in all_coords) / len(all_coords)
    ref_lon = sum(c[1] for c in all_coords) / len(all_coords)

    # POI lookup from block_summary
    pois_by_building = {}
    for s in summary:
        pois_by_building[s["building_id"]] = s["pois"]

    # Generate buildings
    buildings = []
    for bld_id, bld_data in footprints.items():
        coords = bld_data["coordinates"]
        has_mapillary = bld_data["has_mapillary"]
        height = bld_data["height"]
        num_floors = bld_data["num_floors"]

        if height is None:
            if num_floors:
                height = num_floors * 3.5
            else:
                height = 7.0

        n = len(coords)
        if n > 1 and coords[0] == coords[-1]:
            n -= 1

        if n < 3:
            continue

        style = assign_style(bld_id, height, num_floors)
        coords_m = [latlon_to_meters(c[0], c[1], ref_lat, ref_lon) for c in coords[:n]]

        cx = sum(c[0] for c in coords_m) / n
        cy = sum(c[1] for c in coords_m) / n

        # Generate walls
        walls = []
        for i in range(n):
            j = (i + 1) % n
            x0, y0 = coords_m[i]
            x1, y1 = coords_m[j]
            length = math.sqrt((x1 - x0)**2 + (y1 - y0)**2)
            if length < 0.3:
                continue

            bearing = edge_outward_bearing(coords_m, i, n, cx, cy)

            wall = {
                "vertices": [
                    [x0, 0, y0], [x1, 0, y1], [x1, height, y1],
                    [x0, 0, y0], [x1, height, y1], [x0, height, y0]
                ],
                "uvs": [[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]],
                "length": length,
                "height": height,
                "bearing": bearing,
                "is_exterior": True,
                "edge_index": i,
                "entrances": [],
            }
            walls.append(wall)

        # Roof — ear-clipping triangulation
        roof_pts_2d = [(c[0], c[1]) for c in coords_m]
        roof_tris = triangulate_polygon(roof_pts_2d)
        roof_verts = []
        for tri in roof_tris:
            i0, i1, i2 = tri
            roof_verts.append([
                [coords_m[i0][0], height, coords_m[i0][1]],
                [coords_m[i1][0], height, coords_m[i1][1]],
                [coords_m[i2][0], height, coords_m[i2][1]]
            ])

        # Fallback to fan if ear-clipping produced nothing (degenerate polygon)
        if not roof_verts:
            for i in range(n):
                j = (i + 1) % n
                roof_verts.append([
                    [cx, height, cy],
                    [coords_m[i][0], height, coords_m[i][1]],
                    [coords_m[j][0], height, coords_m[j][1]]
                ])

        roof_info = roof_features.get(bld_id, {"base_color": "#6b7280", "features": []})

        buildings.append({
            "id": bld_id,
            "pois": pois_by_building.get(bld_id, []),
            "has_mapillary": has_mapillary,
            "height": height,
            "style": style,
            "centroid_m": [cx, cy],
            "footprint_m": coords_m,
            "walls": walls,
            "roof": roof_verts,
            "roof_color": roof_info["base_color"],
            "roof_features": roof_info["features"],
        })

    # Roads
    roads = []
    for r in roads_raw:
        pts_m = [latlon_to_meters(c[1], c[0], ref_lat, ref_lon) for c in r["coordinates"]]
        roads.append({
            "name": r["name"],
            "class": r["class"],
            "subclass": r.get("subclass"),
            "points": pts_m,
        })

    # Trees and benches
    trees = []
    benches = []
    for item in furniture_raw:
        x, y = latlon_to_meters(item["lat"], item["lon"], ref_lat, ref_lon)
        tags = item.get("tags", {})
        item_type = item.get("type", "")
        if tags.get("natural") == "tree" or item_type == "tree":
            trees.append({"x": x, "y": y})
        elif tags.get("amenity") == "bench" or item_type == "bench":
            benches.append({"x": x, "y": y})

    # Bike racks from infrastructure
    bike_racks = []
    for item in infra_raw:
        if item.get("class") == "bicycle_parking":
            geom = item["geometry"]
            if geom["type"] == "Point":
                lon, lat = geom["coordinates"]
                x, y = latlon_to_meters(lat, lon, ref_lat, ref_lon)
                bike_racks.append({"x": x, "y": y})

    # Street labels
    street_labels = []
    road_segments_by_name = {}
    for r in roads:
        if r["name"]:
            road_segments_by_name.setdefault(r["name"], []).append(r)

    for name, segs in road_segments_by_name.items():
        best_seg = max(segs, key=lambda s: sum(
            math.sqrt((s["points"][i+1][0]-s["points"][i][0])**2 +
                      (s["points"][i+1][1]-s["points"][i][1])**2)
            for i in range(len(s["points"])-1)
        ))
        pts = best_seg["points"]
        mid_idx = len(pts) // 2
        if mid_idx > 0:
            mx = (pts[mid_idx][0] + pts[mid_idx-1][0]) / 2
            my = (pts[mid_idx][1] + pts[mid_idx-1][1]) / 2
            dx = pts[mid_idx][0] - pts[mid_idx-1][0]
            dy = pts[mid_idx][1] - pts[mid_idx-1][1]
            angle = math.degrees(math.atan2(dy, dx))
        else:
            mx, my = pts[0]
            angle = 0
        street_labels.append({"name": name, "x": mx, "y": my, "angle": angle})

    scene = {
        "ref_lat": ref_lat,
        "ref_lon": ref_lon,
        "buildings": buildings,
        "roads": roads,
        "trees": trees,
        "benches": benches,
        "bike_racks": bike_racks,
        "street_labels": street_labels,
        "ground_features": ground_features,
    }

    with open(f"{OUTPUT_DIR}/scene.json", "w") as f:
        json.dump(scene, f)

    total_walls = sum(len(b["walls"]) for b in buildings)
    total_roof_tris = sum(len(b["roof"]) for b in buildings)
    print(f"Scene: {len(buildings)} buildings, {total_walls} walls, {total_roof_tris} roof triangles")
    print(f"  Roads: {len(roads)}, Trees: {len(trees)}, Benches: {len(benches)}, Bike racks: {len(bike_racks)}")
    print(f"  Street labels: {len(street_labels)}")

    # Verify roof correctness
    fan_fallbacks = sum(1 for b in buildings if len(b["roof"]) == len(b["footprint_m"]))
    ear_clipped = sum(1 for b in buildings if len(b["roof"]) == len(b["footprint_m"]) - 2)
    print(f"  Ear-clipped roofs: {ear_clipped}, Fan fallbacks: {fan_fallbacks}")


if __name__ == "__main__":
    main()
