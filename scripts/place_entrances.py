#!/usr/bin/env python3
"""
Place entrances on building walls using predicted entrance lat/lon positions.
Projects entrance coordinates onto the nearest wall to get exact placement.
"""
import json
import math

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def project_point_to_segment(px, py, x0, y0, x1, y1):
    """Project point (px,py) onto line segment (x0,y0)-(x1,y1). Returns t in [0,1] and distance."""
    dx = x1 - x0
    dy = y1 - y0
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-8:
        return 0.5, math.sqrt((px - x0) ** 2 + (py - y0) ** 2)

    t = ((px - x0) * dx + (py - y0) * dy) / len_sq
    t = max(0.05, min(0.95, t))  # Clamp with margin

    proj_x = x0 + t * dx
    proj_y = y0 + t * dy
    dist = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    return t, dist


def main():
    with open(f"{DATA_DIR}/tile_x3400_y6201.json") as f:
        tile = json.load(f)

    with open(f"{OUTPUT_DIR}/scene.json") as f:
        scene = json.load(f)

    ref_lat = scene["ref_lat"]
    ref_lon = scene["ref_lon"]
    m_lon = m_lng_at(ref_lat)

    # Build building index
    bld_map = {b["id"]: b for b in scene["buildings"]}

    # Collect entrance predictions for our buildings
    entrances_by_bld = {}
    for w in tile["waypoints"]:
        bid = w.get("overture_building_id")
        if bid and bid in bld_map and w.get("entrance_lat") and w.get("entrance_lon"):
            if bid not in entrances_by_bld:
                entrances_by_bld[bid] = []
            entrances_by_bld[bid].append({
                "name": w["name"],
                "lat": w["entrance_lat"],
                "lon": w["entrance_lon"],
            })

    print(f"Buildings with entrance predictions: {len(entrances_by_bld)}")
    total_placed = 0
    buildings_with_entrances = 0

    for bid, ents in entrances_by_bld.items():
        bld = bld_map[bid]
        walls = bld["walls"]
        if not walls:
            continue

        # Convert entrance lat/lon to scene meters
        placed_on_walls = {}  # wall_idx -> list of t values

        for ent in ents:
            ex = (ent["lon"] - ref_lon) * m_lon
            ez = (ent["lat"] - ref_lat) * METERS_PER_DEG_LAT

            # Find closest wall
            best_wall_idx = None
            best_t = 0.5
            best_dist = float('inf')

            for wi, wall in enumerate(walls):
                v = wall["vertices"]
                x0, z0 = v[0][0], v[0][2]
                x1, z1 = v[1][0], v[1][2]
                t, dist = project_point_to_segment(ex, ez, x0, z0, x1, z1)
                if dist < best_dist:
                    best_dist = dist
                    best_wall_idx = wi
                    best_t = t

            if best_wall_idx is not None and best_dist < 15:
                if best_wall_idx not in placed_on_walls:
                    placed_on_walls[best_wall_idx] = []
                # Avoid duplicates too close together
                existing = placed_on_walls[best_wall_idx]
                too_close = any(abs(best_t - et) < 0.1 for et in existing)
                if not too_close:
                    placed_on_walls[best_wall_idx].append(best_t)

        # Apply to scene
        if placed_on_walls:
            buildings_with_entrances += 1
            for wi, t_values in placed_on_walls.items():
                walls[wi]["entrances"] = [{"t": t} for t in sorted(t_values)]
                total_placed += len(t_values)

    # Save
    with open(f"{OUTPUT_DIR}/scene.json", "w") as f:
        json.dump(scene, f)

    print(f"Entrances placed: {total_placed} on {buildings_with_entrances} buildings")
    print(f"  Average per building: {total_placed / max(1, buildings_with_entrances):.1f}")


if __name__ == "__main__":
    main()
