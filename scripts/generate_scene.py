#!/usr/bin/env python3
"""
Generate a three.js-compatible 3D scene from Overture building footprints.
Extrudes polygons to estimated heights and outputs JSON for the viewer.
"""
import json
import math

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

# Building heights estimated from visual descriptions and building type
# Pearl St commercial buildings are typically 2-3 stories
BUILDING_HEIGHTS = {
    # Covered (Mapillary)
    "954cb30c-1eb3-41e2-b7b0-f6640a4c3595": 9.0,   # PosterScene/Barbara & Co - 2 story commercial
    "e6ca7522-53d7-4842-a190-287b28b224f6": 6.0,    # OZO Coffee/Dragontree - 1 story strip
    "67797069-8ea7-4f97-8280-4ab9392d1bdf": 8.0,    # Mountain Sun - 2 story historic
    "6bf9d300-d51d-428d-b923-519fc0f90351": 8.0,    # Backcountry - 2 story
    "f61c4184-d69c-4fc7-b873-1d42d8b69c8e": 12.0,   # Odd Fellows - 3 story Romanesque
    # Uncovered
    "bb6ab86f-1a76-4a4d-9a3e-9338fb05e067": 6.0,    # Boulder Day Nursery - 1 story
    "b64dc737-f797-43fa-98f8-8fffa62c2338": 7.0,    # JKA Design - likely 2 story
    "6c30df94-a81e-4f61-b05c-f5087093cdce": 7.0,    # LibertyX - small commercial
    "87322f55-be84-4bf4-8582-17d979622abf": 8.0,    # Law Office - 2 story
    "78f21e0e-2859-4e6c-b5a6-8be6abd53b80": 7.0,    # Village Green Society - 2 story
}

# Visual description summary for facade styling
FACADE_STYLE = {
    "954cb30c-1eb3-41e2-b7b0-f6640a4c3595": {
        "material": "brick", "color": "#8B4513", "accent": "#1a237e",
        "description": "Reddish-orange brick, navy blue steel frames, large plate-glass windows"
    },
    "e6ca7522-53d7-4842-a190-287b28b224f6": {
        "material": "mixed", "color": "#3d3d3d", "accent": "#ffffff",
        "description": "Dark storefront, ornate white signage, large glass windows"
    },
    "67797069-8ea7-4f97-8280-4ab9392d1bdf": {
        "material": "brick", "color": "#6b8e6b", "accent": "#ffffff",
        "description": "Sage-green upper floor, ornate white scrollwork, purple/yellow sign"
    },
    "6bf9d300-d51d-428d-b923-519fc0f90351": {
        "material": "brick", "color": "#4a3728", "accent": "#ccaa00",
        "description": "Dark brick, circular yellow sign, Victorian-era"
    },
    "f61c4184-d69c-4fc7-b873-1d42d8b69c8e": {
        "material": "brick", "color": "#8B3A3A", "accent": "#f5f0e0",
        "description": "Red brick and sandstone Romanesque Revival 1899, arched windows, central pediment"
    },
    # Uncovered - these would be predicted by embedding transfer
    "bb6ab86f-1a76-4a4d-9a3e-9338fb05e067": {
        "material": "unknown", "color": "#a0a0a0", "accent": "#808080",
        "description": "PREDICTED: residential/institutional, likely neutral siding"
    },
    "b64dc737-f797-43fa-98f8-8fffa62c2338": {
        "material": "unknown", "color": "#a0a0a0", "accent": "#808080",
        "description": "PREDICTED: office, likely brick or stucco"
    },
    "6c30df94-a81e-4f61-b05c-f5087093cdce": {
        "material": "unknown", "color": "#a0a0a0", "accent": "#808080",
        "description": "PREDICTED: small commercial"
    },
    "87322f55-be84-4bf4-8582-17d979622abf": {
        "material": "unknown", "color": "#a0a0a0", "accent": "#808080",
        "description": "PREDICTED: office/professional"
    },
    "78f21e0e-2859-4e6c-b5a6-8be6abd53b80": {
        "material": "unknown", "color": "#a0a0a0", "accent": "#808080",
        "description": "PREDICTED: retail/society building"
    },
}


def latlon_to_meters(lat, lon, ref_lat, ref_lon):
    """Convert lat/lon to local meters relative to reference point."""
    dlat = (lat - ref_lat) * 111320
    dlon = (lon - ref_lon) * 111320 * math.cos(math.radians(ref_lat))
    return (dlon, dlat)  # x = east, y = north


def compute_centroid(coords):
    """Compute centroid of a polygon (lat/lon pairs)."""
    n = len(coords)
    if coords[0] == coords[-1]:
        n -= 1
    lat = sum(c[0] for c in coords[:n]) / n
    lon = sum(c[1] for c in coords[:n]) / n
    return lat, lon


def polygon_to_walls(coords_m, height):
    """Generate wall triangles for extruded polygon."""
    walls = []
    n = len(coords_m)
    if coords_m[0] == coords_m[-1]:
        n -= 1

    for i in range(n):
        j = (i + 1) % n
        x0, y0 = coords_m[i]
        x1, y1 = coords_m[j]

        # Two triangles per wall segment
        # Bottom-left, bottom-right, top-right
        walls.append({
            "vertices": [
                [x0, 0, y0], [x1, 0, y1], [x1, height, y1],
                [x0, 0, y0], [x1, height, y1], [x0, height, y0]
            ],
            "edge_index": i
        })

    return walls


def polygon_to_roof(coords_m, height):
    """Simple fan triangulation for roof polygon."""
    n = len(coords_m)
    if coords_m[0] == coords_m[-1]:
        n -= 1

    triangles = []
    cx = sum(c[0] for c in coords_m[:n]) / n
    cy = sum(c[1] for c in coords_m[:n]) / n

    for i in range(n):
        j = (i + 1) % n
        triangles.append([
            [cx, height, cy],
            [coords_m[i][0], height, coords_m[i][1]],
            [coords_m[j][0], height, coords_m[j][1]]
        ])

    return triangles


def main():
    with open(f"{DATA_DIR}/building_footprints.json") as f:
        footprints = json.load(f)

    with open(f"{DATA_DIR}/block_summary.json") as f:
        summary = json.load(f)

    # Compute scene center
    all_coords = []
    for bld in footprints.values():
        all_coords.extend(bld["coordinates"])

    ref_lat = sum(c[0] for c in all_coords) / len(all_coords)
    ref_lon = sum(c[1] for c in all_coords) / len(all_coords)

    # Build scene
    buildings = []
    for bld_id, bld_data in footprints.items():
        coords = bld_data["coordinates"]
        has_mapillary = bld_data["has_mapillary"]
        height = BUILDING_HEIGHTS.get(bld_id, 7.0)
        style = FACADE_STYLE.get(bld_id, {})

        # Convert to local meters
        coords_m = [latlon_to_meters(c[0], c[1], ref_lat, ref_lon) for c in coords]

        # Generate mesh
        walls = polygon_to_walls(coords_m, height)
        roof = polygon_to_roof(coords_m, height)

        # Find POI names for this building
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
            "centroid_m": [
                sum(c[0] for c in coords_m) / len(coords_m),
                sum(c[1] for c in coords_m) / len(coords_m)
            ],
            "footprint_m": coords_m,
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

    print(f"Scene generated: {len(buildings)} buildings")
    print(f"  Reference point: {ref_lat:.6f}, {ref_lon:.6f}")
    print(f"  With Mapillary: {sum(1 for b in buildings if b['has_mapillary'])}")
    print(f"  Without: {sum(1 for b in buildings if not b['has_mapillary'])}")


if __name__ == "__main__":
    main()
