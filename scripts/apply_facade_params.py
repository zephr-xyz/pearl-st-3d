#!/usr/bin/env python3
"""
Apply extracted facade parameters to scene.json for improved procedural rendering.
Updates building styles with VLM-informed materials, colors, window grids, entrances.
"""
import json

DATA_DIR = "/private/tmp/pearl-st-3d/data"
FACADES_DIR = "/private/tmp/pearl-st-3d/data/facades"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"


def find_street_facing_wall(bld):
    """Find the wall most likely facing the street (longest exterior wall)."""
    if not bld.get("walls"):
        return None
    best = None
    best_len = 0
    for i, wall in enumerate(bld["walls"]):
        if wall["length"] > best_len:
            best_len = wall["length"]
            best = i
    return best


def main():
    with open(f"{FACADES_DIR}/facade_params.json") as f:
        facade_params = json.load(f)

    with open(f"{OUTPUT_DIR}/scene.json") as f:
        scene = json.load(f)

    # Index facade params by building_id
    params_by_bld = {fp["building_id"]: fp for fp in facade_params}

    updated = 0
    entrances_placed = 0
    for bld in scene["buildings"]:
        fp = params_by_bld.get(bld["id"])
        if not fp:
            continue

        # Update style with VLM-informed parameters
        style = bld.get("style", {})

        style["material"] = fp["material"]
        style["color"] = fp["color"]
        style["accent"] = fp["accent"]
        style["windows"] = fp["window_style"]
        style["stories"] = fp["stories"]
        style["awning"] = fp["awning"]

        # Add new fields for enhanced rendering
        style["window_grid"] = fp["window_grid"]
        style["entrance"] = fp["entrance"]
        style["details"] = fp["details"]
        style["ground_floor"] = "storefront" if fp["window_style"] in (
            "large_plate_glass", "storefront_glass") else "traditional"
        style["source"] = "vlm"  # Mark as VLM-informed vs heuristic

        bld["style"] = style

        # Place entrance on street-facing wall
        street_wall_idx = find_street_facing_wall(bld)
        if street_wall_idx is not None and fp["entrance"]:
            ent_pos = fp["entrance"].get("position", 0.5)
            ent_count = fp["entrance"].get("count", 1)
            wall = bld["walls"][street_wall_idx]
            wall["entrances"] = []
            if ent_count == 1:
                wall["entrances"].append({"t": ent_pos})
            else:
                # Distribute entrances
                for ei in range(ent_count):
                    t = 0.3 + ei * 0.4 / max(1, ent_count - 1)
                    wall["entrances"].append({"t": t})
            entrances_placed += 1

        updated += 1

    with open(f"{OUTPUT_DIR}/scene.json", "w") as f:
        json.dump(scene, f)

    print(f"Updated {updated} / {len(scene['buildings'])} buildings with VLM facade params")
    print(f"  VLM-informed: {updated}")
    print(f"  Heuristic (unchanged): {len(scene['buildings']) - updated}")
    print(f"  Entrances placed: {entrances_placed}")


if __name__ == "__main__":
    main()
