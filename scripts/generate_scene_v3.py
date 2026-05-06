#!/usr/bin/env python3
"""
Generate 3D scene with proper exterior/interior wall classification.
Uses logic from facade-poi-preprocessing to determine which edges face streets
vs which are shared party walls or occluded by other buildings.
"""
import json
import math

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

METERS_PER_DEG_LAT = 111320.0

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
        "awning": {"color": "#1a237e", "style": "flat"},
        "signage": {"color": "#ffffff", "band_color": "#1a237e"},
        "ground_floor": "storefront",
        "description": "Reddish-orange brick, navy blue steel frames, large plate-glass windows"
    },
    "e6ca7522-53d7-4842-a190-287b28b224f6": {
        "material": "brick", "color": "#4a4a4a", "accent": "#2a2a2a",
        "windows": "storefront_glass", "stories": 1,
        "awning": {"color": "#cc2222", "style": "slope"},
        "signage": {"color": "#ffffff", "band_color": "#333333"},
        "ground_floor": "full_glass",
        "description": "Dark storefront, red awning, white signage, large glass windows"
    },
    "67797069-8ea7-4f97-8280-4ab9392d1bdf": {
        "material": "painted_brick", "color": "#6b8e6b", "accent": "#ffffff",
        "windows": "vertical_triple", "stories": 2,
        "awning": None,
        "signage": {"color": "#ffffff", "band_color": "#6b4b8a"},
        "ground_floor": "storefront",
        "description": "Sage-green upper floor, ornate white scrollwork, three vertical windows"
    },
    "6bf9d300-d51d-428d-b923-519fc0f90351": {
        "material": "brick", "color": "#4a3728", "accent": "#ccaa00",
        "windows": "traditional", "stories": 2,
        "awning": {"color": "#2a5a2a", "style": "slope"},
        "signage": {"color": "#ccaa00", "band_color": "#4a3728", "shape": "circle"},
        "ground_floor": "storefront",
        "description": "Dark brick, Victorian-era, green awning, circular yellow sign"
    },
    "f61c4184-d69c-4fc7-b873-1d42d8b69c8e": {
        "material": "brick_sandstone", "color": "#8B3A3A", "accent": "#f5f0e0",
        "windows": "romanesque_arched", "stories": 3,
        "awning": None,
        "signage": {"color": "#f5f0e0", "band_color": "#8B3A3A"},
        "ground_floor": "storefront",
        "pediment": True,
        "description": "Red brick + sandstone Romanesque Revival 1899, arched windows, central pediment"
    },
    "bb6ab86f-1a76-4a4d-9a3e-9338fb05e067": {
        "material": "siding", "color": "#b8a590", "accent": "#808080",
        "windows": "residential", "stories": 1,
        "awning": None,
        "signage": None,
        "ground_floor": "traditional",
        "description": "TRANSFER: Likely neutral siding, institutional"
    },
    "b64dc737-f797-43fa-98f8-8fffa62c2338": {
        "material": "stucco", "color": "#9e8b7a", "accent": "#5c4a3a",
        "windows": "office", "stories": 2,
        "awning": None,
        "signage": None,
        "ground_floor": "traditional",
        "description": "TRANSFER: Office, likely brick or stucco"
    },
    "6c30df94-a81e-4f61-b05c-f5087093cdce": {
        "material": "brick", "color": "#7a6b5a", "accent": "#4a3728",
        "windows": "commercial_small", "stories": 2,
        "awning": {"color": "#3a5a3a", "style": "slope"},
        "signage": None,
        "ground_floor": "storefront",
        "description": "TRANSFER: Small commercial (nearest: Backcountry)"
    },
    "87322f55-be84-4bf4-8582-17d979622abf": {
        "material": "brick", "color": "#8B6B4A", "accent": "#f5f0e0",
        "windows": "office", "stories": 2,
        "awning": None,
        "signage": {"color": "#f5f0e0", "band_color": "#8B6B4A"},
        "ground_floor": "traditional",
        "description": "TRANSFER: Office/professional (nearest: Odd Fellows)"
    },
    "78f21e0e-2859-4e6c-b5a6-8be6abd53b80": {
        "material": "painted_brick", "color": "#5a7a5a", "accent": "#ffffff",
        "windows": "retail", "stories": 2,
        "awning": {"color": "#cc2222", "style": "slope"},
        "signage": None,
        "ground_floor": "storefront",
        "description": "TRANSFER: Retail (nearest: Mountain Sun)"
    },
}


def m_lng_at(lat):
    """Meters per degree longitude at given latitude."""
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def dist_m(lat1, lon1, lat2, lon2):
    """Approximate distance in meters between two lat/lon points."""
    mlng = m_lng_at((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * mlng
    dy = (lat2 - lat1) * METERS_PER_DEG_LAT
    return math.sqrt(dx * dx + dy * dy)


def point_to_segment_dist(px, py, ax, ay, bx, by):
    """Perpendicular distance from point to segment (in same units)."""
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return math.sqrt((px - ax)**2 + (py - ay)**2)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)


def edge_outward_bearing(coords, idx):
    """Compute outward-facing bearing of building edge (degrees, 0=N CW).
    Uses centroid test to determine outward direction."""
    n = len(coords)
    if coords[0] == coords[-1]:
        n -= 1

    c0 = coords[idx]
    c1 = coords[(idx + 1) % n]

    # Centroid
    clat = sum(coords[i][0] for i in range(n)) / n
    clon = sum(coords[i][1] for i in range(n)) / n

    # Edge direction in meters
    mlng = m_lng_at(c0[0])
    dx = (c1[1] - c0[1]) * mlng
    dy = (c1[0] - c0[0]) * METERS_PER_DEG_LAT
    edge_bearing = math.degrees(math.atan2(dx, dy)) % 360

    # Two candidate normals (perpendicular to edge)
    mid_lat = (c0[0] + c1[0]) / 2
    mid_lon = (c0[1] + c1[1]) / 2

    for sign in [1, -1]:
        normal = (edge_bearing + sign * 90) % 360
        nr = math.radians(normal)
        # Project test point outward
        test_lat = mid_lat + 0.00001 * math.cos(nr)
        test_lon = mid_lon + 0.00001 * math.sin(nr) / math.cos(math.radians(mid_lat))
        # Check if test point is farther from centroid (= outward)
        d_test = (test_lat - clat)**2 + ((test_lon - clon) * math.cos(math.radians(clat)))**2
        d_mid = (mid_lat - clat)**2 + ((mid_lon - clon) * math.cos(math.radians(clat)))**2
        if d_test > d_mid:
            return normal

    return edge_bearing


def find_shared_walls(bld_id, bld_coords, all_footprints, max_dist_m=2.5):
    """Find edges that are shared/party walls with adjacent buildings.
    An edge is shared if 3 sample points along it are all within max_dist_m
    of an edge of another building."""
    n = len(bld_coords)
    if bld_coords[0] == bld_coords[-1]:
        n -= 1

    shared = set()

    # Collect all neighbor edges
    neighbor_edges = []
    for other_id, other_data in all_footprints.items():
        if other_id == bld_id:
            continue
        other_coords = other_data["coordinates"]
        on = len(other_coords)
        if other_coords[0] == other_coords[-1]:
            on -= 1
        for i in range(on):
            j = (i + 1) % on
            neighbor_edges.append((other_coords[i], other_coords[j]))

    if not neighbor_edges:
        return shared

    for i in range(n):
        j = (i + 1) % n
        c0 = bld_coords[i]
        c1 = bld_coords[j]

        # Sample 3 points along edge (t=0.25, 0.5, 0.75)
        all_close = True
        for t in [0.25, 0.5, 0.75]:
            px = c0[0] + t * (c1[0] - c0[0])
            py = c0[1] + t * (c1[1] - c0[1])

            mlng = m_lng_at(px)
            # Convert to meters for distance calc
            px_m = px * METERS_PER_DEG_LAT
            py_m = py * mlng

            min_d = float('inf')
            for ne0, ne1 in neighbor_edges:
                ax_m = ne0[0] * METERS_PER_DEG_LAT
                ay_m = ne0[1] * mlng
                bx_m = ne1[0] * METERS_PER_DEG_LAT
                by_m = ne1[1] * mlng
                d = point_to_segment_dist(px_m, py_m, ax_m, ay_m, bx_m, bx_m)
                # Proper calculation
                d = point_to_segment_dist(px_m, py_m, ax_m, ay_m, bx_m, by_m)
                min_d = min(min_d, d)

            if min_d > max_dist_m:
                all_close = False
                break

        if all_close:
            shared.add(i)

    return shared


def filter_occluded_edges(edge_indices, bld_coords, bld_id, all_footprints, step_m=4.0):
    """Filter out edges where stepping outward hits another building."""
    n = len(bld_coords)
    if bld_coords[0] == bld_coords[-1]:
        n -= 1

    clat = sum(bld_coords[i][0] for i in range(n)) / n
    clon = sum(bld_coords[i][1] for i in range(n)) / n

    clear_edges = set()

    for i in edge_indices:
        j = (i + 1) % n
        c0 = bld_coords[i]
        c1 = bld_coords[j]

        mid_lat = (c0[0] + c1[0]) / 2
        mid_lon = (c0[1] + c1[1]) / 2

        # Outward bearing
        bearing = edge_outward_bearing(bld_coords, i)
        br = math.radians(bearing)

        # Step outward
        probe_lat = mid_lat + (step_m / METERS_PER_DEG_LAT) * math.cos(br)
        probe_lon = mid_lon + (step_m / m_lng_at(mid_lat)) * math.sin(br)

        # Check if probe falls inside any other building
        occluded = False
        for other_id, other_data in all_footprints.items():
            if other_id == bld_id:
                continue
            if point_in_polygon(probe_lat, probe_lon, other_data["coordinates"]):
                occluded = True
                break

        if not occluded:
            clear_edges.add(i)

    return clear_edges


def point_in_polygon(lat, lon, coords):
    """Ray casting point-in-polygon test."""
    n = len(coords)
    if coords[0] == coords[-1]:
        n -= 1

    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = coords[i]
        yj, xj = coords[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def polygon_area_signed(pts):
    """Signed area of a 2D polygon. Positive = CCW."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0


def point_in_triangle(px, py, ax, ay, bx, by, cx, cy):
    """Check if point (px,py) is inside triangle (a,b,c) using barycentric coords."""
    denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denom) < 1e-12:
        return False
    u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denom
    v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denom
    w = 1.0 - u - v
    return u >= -1e-10 and v >= -1e-10 and w >= -1e-10


def triangulate_polygon(pts):
    """Ear-clipping triangulation for simple polygons (convex or concave).
    Returns list of triangle index triples."""
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    # Ensure CCW winding
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

            # Check if this vertex is convex (left turn in CCW polygon)
            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if cross <= 0:
                continue

            # Check no other vertex is inside this triangle
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


def latlon_to_meters(lat, lon, ref_lat, ref_lon):
    dlat = (lat - ref_lat) * METERS_PER_DEG_LAT
    dlon = (lon - ref_lon) * m_lng_at(ref_lat)
    return (dlon, dlat)


def edge_length_m(coords, i):
    n = len(coords)
    if coords[0] == coords[-1]:
        n -= 1
    j = (i + 1) % n
    return dist_m(coords[i][0], coords[i][1], coords[j][0], coords[j][1])


def angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def main():
    with open(f"{DATA_DIR}/building_footprints.json") as f:
        footprints = json.load(f)

    with open(f"{DATA_DIR}/block_summary.json") as f:
        summary = json.load(f)

    with open(f"{DATA_DIR}/mapillary_metadata.json") as f:
        mapillary = json.load(f)

    with open(f"{DATA_DIR}/roof_features.json") as f:
        roof_features = json.load(f)

    # Reference point
    all_coords = []
    for bld in footprints.values():
        all_coords.extend(bld["coordinates"])
    ref_lat = sum(c[0] for c in all_coords) / len(all_coords)
    ref_lon = sum(c[1] for c in all_coords) / len(all_coords)

    # Group images by building
    images_by_building = {}
    for img in mapillary:
        images_by_building.setdefault(img["building_id"], []).append(img)

    # Classify edges for each building
    print("Classifying building edges...")
    buildings = []

    for bld_id, bld_data in footprints.items():
        coords = bld_data["coordinates"]
        has_mapillary = bld_data["has_mapillary"]
        height = BUILDING_HEIGHTS.get(bld_id, 7.0)
        style = FACADE_STYLE.get(bld_id, {})

        n = len(coords)
        if coords[0] == coords[-1]:
            n -= 1

        # Step 1: Find shared walls
        shared_walls = find_shared_walls(bld_id, coords, footprints)

        # Step 2: All non-shared edges are candidates
        candidate_edges = set(range(n)) - shared_walls

        # Step 3: Filter occluded edges (blocked by other buildings)
        exterior_edges = filter_occluded_edges(candidate_edges, coords, bld_id, footprints)

        # Interior = everything not exterior
        interior_edges = set(range(n)) - exterior_edges

        print(f"  {bld_id[:8]}... edges={n} exterior={len(exterior_edges)} "
              f"shared_walls={len(shared_walls)} occluded={len(candidate_edges - exterior_edges)}")

        # Convert to meters for rendering
        coords_m = [latlon_to_meters(c[0], c[1], ref_lat, ref_lon) for c in coords]

        # Get entrances and visual descriptions for this building
        bld_entrances = []
        bld_visual_desc = []
        for s in summary:
            if s["building_id"] == bld_id:
                bld_entrances = s.get("entrances", [])
                bld_visual_desc = s.get("visual_descriptions", [])
                break

        # Convert entrance positions to meters
        entrance_pts_m = []
        for ent in bld_entrances:
            ex, ey = latlon_to_meters(ent["lat"], ent["lon"], ref_lat, ref_lon)
            entrance_pts_m.append({"x": ex, "y": ey, "poi": ent["poi"]})

        # Generate walls
        walls = []
        for i in range(n):
            j = (i + 1) % n
            x0, y0 = coords_m[i]
            x1, y1 = coords_m[j]
            length = math.sqrt((x1 - x0)**2 + (y1 - y0)**2)

            if length < 0.3:
                continue

            is_exterior = i in exterior_edges
            bearing = edge_outward_bearing(coords, i)

            # Find entrances that project onto this wall edge
            wall_entrances = []
            if is_exterior and length > 1.0:
                for ent in entrance_pts_m:
                    dx = x1 - x0
                    dy = y1 - y0
                    t = ((ent["x"] - x0) * dx + (ent["y"] - y0) * dy) / (dx * dx + dy * dy)
                    # Clamp to edge and check distance
                    t_clamped = max(0, min(1, t))
                    proj_x = x0 + t_clamped * dx
                    proj_y = y0 + t_clamped * dy
                    dist = math.sqrt((ent["x"] - proj_x)**2 + (ent["y"] - proj_y)**2)
                    if dist < 3.0:
                        # Place at clamped position (at least 0.1 from edges)
                        wall_entrances.append({"t": max(0.1, min(0.9, t_clamped)), "poi": ent["poi"]})

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
                "is_exterior": is_exterior,
                "edge_index": i,
                "entrances": wall_entrances,
            }

            walls.append(wall)

        # Roof (ear-clipping triangulation for correct concave polygon handling)
        cx = sum(c[0] for c in coords_m[:n]) / n
        cy = sum(c[1] for c in coords_m[:n]) / n
        roof_pts_2d = [(coords_m[i][0], coords_m[i][1]) for i in range(n)]
        roof_tris = triangulate_polygon(roof_pts_2d)
        roof_verts = []
        for tri in roof_tris:
            i0, i1, i2 = tri
            roof_verts.append([
                [coords_m[i0][0], height, coords_m[i0][1]],
                [coords_m[i1][0], height, coords_m[i1][1]],
                [coords_m[i2][0], height, coords_m[i2][1]]
            ])
        roof_info = roof_features.get(bld_id, {"base_color": "#6b7280", "features": []})

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
            "roof": roof_verts,
            "roof_color": roof_info["base_color"],
            "roof_features": roof_info["features"],
        })

    # Load roads
    with open(f"{DATA_DIR}/roads.json") as f:
        roads_raw = json.load(f)

    roads = []
    for r in roads_raw:
        pts_m = [latlon_to_meters(c[1], c[0], ref_lat, ref_lon) for c in r["coordinates"]]
        roads.append({
            "name": r["name"],
            "class": r["class"],
            "subclass": r.get("subclass"),
            "points": pts_m,
        })

    # Load trees and benches
    with open(f"{DATA_DIR}/street_furniture.json") as f:
        furniture_raw = json.load(f)

    trees = []
    benches = []
    for item in furniture_raw:
        x, y = latlon_to_meters(item["lat"], item["lon"], ref_lat, ref_lon)
        tags = item.get("tags", {})
        if tags.get("natural") == "tree":
            trees.append({"x": x, "y": y})
        elif tags.get("amenity") == "bench":
            benches.append({"x": x, "y": y})

    # Load Overture infrastructure (bike racks, etc)
    with open(f"{DATA_DIR}/infrastructure.json") as f:
        infra_raw = json.load(f)

    bike_racks = []
    for item in infra_raw:
        if item["class"] == "bicycle_parking":
            geom = item["geometry"]
            if geom["type"] == "Point":
                lon, lat = geom["coordinates"]
                x, y = latlon_to_meters(lat, lon, ref_lat, ref_lon)
                bike_racks.append({"x": x, "y": y})

    # Street labels — pick longest segment per named road for label placement
    street_labels = []
    road_segments_by_name = {}
    for r in roads:
        if r["name"]:
            road_segments_by_name.setdefault(r["name"], []).append(r)

    for name, segs in road_segments_by_name.items():
        # Find midpoint of longest segment
        best_seg = max(segs, key=lambda s: sum(
            math.sqrt((s["points"][i+1][0]-s["points"][i][0])**2 + (s["points"][i+1][1]-s["points"][i][1])**2)
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
    }

    with open(f"{OUTPUT_DIR}/scene.json", "w") as f:
        json.dump(scene, f)

    # Stats
    ext_walls = sum(1 for b in buildings for w in b["walls"] if w["is_exterior"])
    int_walls = sum(1 for b in buildings for w in b["walls"] if not w["is_exterior"])
    print(f"\nScene: {len(buildings)} buildings")
    print(f"  Exterior walls: {ext_walls} (will get textures/windows)")
    print(f"  Interior walls: {int_walls} (plain/blank)")
    print(f"  Roads: {len(roads)} segments")
    print(f"  Trees: {len(trees)}, Benches: {len(benches)}, Bike racks: {len(bike_racks)}")

    for b in buildings:
        ext = sum(1 for w in b["walls"] if w["is_exterior"])
        name = b["pois"][0] if b["pois"] else "?"
        print(f"  {b['id'][:8]}... {name:30s} ext={ext}/{len(b['walls'])}")


if __name__ == "__main__":
    main()
