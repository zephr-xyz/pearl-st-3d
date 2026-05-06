#!/usr/bin/env python3
"""
Generate enhanced 3D scene with facade texture assignments.
Picks best Mapillary image per building face based on camera angle alignment.
"""
import json
import math

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

BUILDING_HEIGHTS = {
    "954cb30c-1eb3-41e2-b7b0-f6640a4c3595": 9.0,
    "e6ca7522-53d7-4842-a190-287b28b224f6": 6.0,
    "67797069-8ea7-4f97-8280-4ab9392d1bdf": 8.0,
    "6bf9d300-d51d-428d-b923-519fc0f90351": 8.0,
    "f61c4184-d69c-4fc7-b873-1d42d8b69c8e": 12.0,
    "bb6ab86f-1a76-4a4d-9a3e-9338fb05e067": 6.0,
    "b64dc737-f797-43fa-98f8-8fffa62c2338": 7.0,
    "6c30df94-a81e-4f61-b05c-f5087093cdce": 7.0,
    "87322f55-be84-4bf4-8582-17d979622abf": 8.0,
    "78f21e0e-2859-4e6c-b5a6-8be6abd53b80": 7.0,
}

FACADE_STYLE = {
    "954cb30c-1eb3-41e2-b7b0-f6640a4c3595": {
        "material": "brick", "color": "#8B4513", "accent": "#1a237e",
        "windows": "large_plate_glass", "stories": 2,
        "description": "Reddish-orange brick, navy blue steel frames, large plate-glass windows"
    },
    "e6ca7522-53d7-4842-a190-287b28b224f6": {
        "material": "mixed", "color": "#3d3d3d", "accent": "#ffffff",
        "windows": "storefront_glass", "stories": 1,
        "description": "Dark storefront, ornate white signage, large glass windows"
    },
    "67797069-8ea7-4f97-8280-4ab9392d1bdf": {
        "material": "painted_brick", "color": "#6b8e6b", "accent": "#ffffff",
        "windows": "vertical_triple", "stories": 2,
        "description": "Sage-green upper floor, ornate white scrollwork, three vertical windows"
    },
    "6bf9d300-d51d-428d-b923-519fc0f90351": {
        "material": "brick", "color": "#4a3728", "accent": "#ccaa00",
        "windows": "traditional", "stories": 2,
        "description": "Dark brick, Victorian-era, circular yellow sign"
    },
    "f61c4184-d69c-4fc7-b873-1d42d8b69c8e": {
        "material": "brick_sandstone", "color": "#8B3A3A", "accent": "#f5f0e0",
        "windows": "romanesque_arched", "stories": 3,
        "description": "Red brick + sandstone Romanesque Revival 1899, arched windows, central pediment"
    },
    "bb6ab86f-1a76-4a4d-9a3e-9338fb05e067": {
        "material": "unknown", "color": "#b8a590", "accent": "#808080",
        "windows": "residential", "stories": 1,
        "description": "TRANSFER: Likely neutral siding, institutional"
    },
    "b64dc737-f797-43fa-98f8-8fffa62c2338": {
        "material": "unknown", "color": "#9e8b7a", "accent": "#5c4a3a",
        "windows": "office", "stories": 2,
        "description": "TRANSFER: Office, likely brick or stucco"
    },
    "6c30df94-a81e-4f61-b05c-f5087093cdce": {
        "material": "unknown", "color": "#7a6b5a", "accent": "#4a3728",
        "windows": "commercial_small", "stories": 2,
        "description": "TRANSFER: Small commercial (nearest neighbor: Backcountry)"
    },
    "87322f55-be84-4bf4-8582-17d979622abf": {
        "material": "unknown", "color": "#8B6B4A", "accent": "#f5f0e0",
        "windows": "office", "stories": 2,
        "description": "TRANSFER: Office/professional (nearest neighbor: Odd Fellows)"
    },
    "78f21e0e-2859-4e6c-b5a6-8be6abd53b80": {
        "material": "unknown", "color": "#5a7a5a", "accent": "#ffffff",
        "windows": "retail", "stories": 2,
        "description": "TRANSFER: Retail (nearest neighbor: Mountain Sun)"
    },
}


def latlon_to_meters(lat, lon, ref_lat, ref_lon):
    dlat = (lat - ref_lat) * 111320
    dlon = (lon - ref_lon) * 111320 * math.cos(math.radians(ref_lat))
    return (dlon, dlat)


def edge_normal_bearing(x0, y0, x1, y1):
    """Compute outward-facing bearing of an edge (degrees, 0=north, CW)."""
    dx = x1 - x0
    dy = y1 - y0
    # Normal pointing outward (right side of edge direction for CW polygon)
    nx, ny = dy, -dx
    bearing = math.degrees(math.atan2(nx, ny)) % 360
    return bearing


def angle_diff(a, b):
    """Smallest angle between two bearings."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def edge_length(x0, y0, x1, y1):
    return math.sqrt((x1 - x0)**2 + (y1 - y0)**2)


def main():
    with open(f"{DATA_DIR}/building_footprints.json") as f:
        footprints = json.load(f)

    with open(f"{DATA_DIR}/block_summary.json") as f:
        summary = json.load(f)

    with open(f"{DATA_DIR}/mapillary_metadata.json") as f:
        mapillary = json.load(f)

    # Reference point (scene center)
    all_coords = []
    for bld in footprints.values():
        all_coords.extend(bld["coordinates"])
    ref_lat = sum(c[0] for c in all_coords) / len(all_coords)
    ref_lon = sum(c[1] for c in all_coords) / len(all_coords)

    # Group Mapillary images by building
    images_by_building = {}
    for img in mapillary:
        images_by_building.setdefault(img["building_id"], []).append(img)

    buildings = []
    for bld_id, bld_data in footprints.items():
        coords = bld_data["coordinates"]
        has_mapillary = bld_data["has_mapillary"]
        height = BUILDING_HEIGHTS.get(bld_id, 7.0)
        style = FACADE_STYLE.get(bld_id, {})

        # Convert to meters
        coords_m = [latlon_to_meters(c[0], c[1], ref_lat, ref_lon) for c in coords]

        # Close polygon if not closed
        n = len(coords_m)
        if coords_m[0] == coords_m[-1]:
            n -= 1

        # Generate wall faces with UV and texture assignment
        walls = []
        for i in range(n):
            j = (i + 1) % n
            x0, y0 = coords_m[i]
            x1, y1 = coords_m[j]

            length = edge_length(x0, y0, x1, y1)
            if length < 0.5:
                continue

            bearing = edge_normal_bearing(x0, y0, x1, y1)

            # Find best matching Mapillary image for this edge
            best_image = None
            best_score = 180
            for img in images_by_building.get(bld_id, []):
                camera_heading = img["camera_heading"]
                # Camera should be facing the wall (heading ~= wall bearing)
                diff = angle_diff(camera_heading, bearing)
                if diff < best_score:
                    best_score = diff
                    best_image = img

            wall = {
                "vertices": [
                    [x0, 0, y0], [x1, 0, y1], [x1, height, y1],
                    [x0, 0, y0], [x1, height, y1], [x0, height, y0]
                ],
                "uvs": [
                    [0, 0], [1, 0], [1, 1],
                    [0, 0], [1, 1], [0, 1]
                ],
                "length": length,
                "height": height,
                "bearing": bearing,
                "edge_index": i,
            }

            if best_image and best_score < 60:
                wall["texture"] = best_image["image_path"]
                wall["texture_score"] = best_score
                wall["camera_heading"] = best_image["camera_heading"]
            else:
                wall["texture"] = None

            walls.append(wall)

        # Roof triangulation (fan from centroid)
        cx = sum(c[0] for c in coords_m[:n]) / n
        cy = sum(c[1] for c in coords_m[:n]) / n
        roof = []
        for i in range(n):
            j = (i + 1) % n
            roof.append([
                [cx, height, cy],
                [coords_m[i][0], height, coords_m[i][1]],
                [coords_m[j][0], height, coords_m[j][1]]
            ])

        # POI names
        poi_names = []
        for s in summary:
            if s["building_id"] == bld_id:
                poi_names = s["pois"]
                break

        buildings.append({
            "id": bld_id,
            "pois": poi_names,
            "has_mapillary": has_mapillary,
            "height": height,
            "style": style,
            "centroid_m": [cx, cy],
            "footprint_m": coords_m[:n],
            "walls": walls,
            "roof": roof,
        })

    scene = {
        "ref_lat": ref_lat,
        "ref_lon": ref_lon,
        "buildings": buildings,
    }

    with open(f"{OUTPUT_DIR}/scene.json", "w") as f:
        json.dump(scene, f)

    # Stats
    textured_walls = sum(1 for b in buildings for w in b["walls"] if w.get("texture"))
    total_walls = sum(len(b["walls"]) for b in buildings)
    print(f"Scene: {len(buildings)} buildings, {total_walls} walls ({textured_walls} textured)")
    for b in buildings:
        tw = sum(1 for w in b["walls"] if w.get("texture"))
        print(f"  {b['id'][:8]}... {b['pois'][0] if b['pois'] else '?':30s} walls={len(b['walls'])} textured={tw} h={b['height']}m")


if __name__ == "__main__":
    main()
