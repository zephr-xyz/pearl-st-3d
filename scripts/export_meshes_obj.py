#!/usr/bin/env python3
"""
Export building meshes from scene.json as OBJ files with UV coordinates.

Each building gets its own OBJ file with:
- Wall faces UV-mapped (U along wall length, V along height)
- Roof faces UV-mapped (planar projection from above)
- A companion .txt file with the VLM text prompt for texture generation

These OBJ files are input to Paint-it or TEXTure for photorealistic texture generation.
"""
import json
import math
import os
import sys

SCENE_PATH = "/private/tmp/pearl-st-3d/viewer/scene.json"
TILE_PATH = "/private/tmp/pearl-st-3d/data/tile_x3400_y6201.json"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/data/meshes"


def build_vlm_prompt(bld, desc_by_bld):
    """Build a text prompt for texture generation from VLM description + style."""
    bid = bld["id"]
    style = bld.get("style", {})
    pois = bld.get("pois", [])

    # Use VLM description if available
    desc = desc_by_bld.get(bid, "")
    if desc:
        # Truncate to key visual details (first 300 chars usually has facade description)
        prompt = desc[:400]
    else:
        # Fallback: build from style metadata
        material = style.get("material", "brick")
        color_desc = style.get("color", "#8B4513")
        stories = style.get("stories", 2)
        arch_style = style.get("arch_style", "")
        lf = style.get("landmark_features", {})

        parts = []
        if arch_style:
            parts.append(f"{arch_style} style")
        parts.append(f"{stories}-story {material} building")
        if lf.get("columns"):
            parts.append("with columns")
        if lf.get("pediment"):
            parts.append("with pediment")
        if lf.get("marquee"):
            parts.append("with marquee sign")
        if pois:
            parts.append(f"housing {pois[0]}")
        prompt = ", ".join(parts)

    return prompt


def export_building_obj(bld, filepath):
    """Export a single building as an OBJ file with UV coordinates."""
    vertices = []  # (x, y, z)
    uvs = []       # (u, v)
    faces = []     # list of (v_indices, uv_indices)

    vi = 1  # OBJ is 1-indexed
    ui = 1

    # Export walls
    for wall in bld["walls"]:
        verts = wall["vertices"]
        if len(verts) < 4:
            continue

        # Wall vertices: [bl, br, tr, tl] typically
        # Bottom-left, bottom-right, top-right, top-left
        # Compute wall length for UV mapping
        bl = verts[0]
        br = verts[1]
        tr = verts[2]
        tl = verts[3] if len(verts) > 3 else verts[0]

        wall_len = math.sqrt(
            (br[0] - bl[0])**2 + (br[2] - bl[2])**2
        )
        wall_h = wall.get("height", bld["height"])

        if wall_len < 0.1 or wall_h < 0.1:
            continue

        # UV: U spans 0 to wall_len/wall_h (preserves aspect ratio), V spans 0-1
        u_scale = wall_len / max(wall_h, 1)

        # Add 4 vertices
        for v in [bl, br, tr, tl]:
            vertices.append(v)

        # UV coords: bl=(0,0), br=(u_scale,0), tr=(u_scale,1), tl=(0,1)
        uvs.append((0, 0))
        uvs.append((u_scale, 0))
        uvs.append((u_scale, 1))
        uvs.append((0, 1))

        # Two triangles: bl-br-tr, bl-tr-tl
        faces.append(([vi, vi+1, vi+2], [ui, ui+1, ui+2]))
        faces.append(([vi, vi+2, vi+3], [ui, ui+2, ui+3]))

        vi += 4
        ui += 4

    # Export roof triangles
    roof_verts_all = []
    for tri in bld.get("roof", []):
        for v in tri:
            roof_verts_all.append(v)

    if roof_verts_all:
        # Compute bounding box for planar UV projection
        xs = [v[0] for v in roof_verts_all]
        zs = [v[2] for v in roof_verts_all]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        span_x = max_x - min_x if max_x > min_x else 1
        span_z = max_z - min_z if max_z > min_z else 1

        for tri in bld.get("roof", []):
            for v in tri:
                vertices.append(v)
                u = (v[0] - min_x) / span_x
                vv = (v[2] - min_z) / span_z
                uvs.append((u, vv))

            faces.append(([vi, vi+1, vi+2], [ui, ui+1, ui+2]))
            vi += 3
            ui += 3

    # Write OBJ
    with open(filepath, 'w') as f:
        f.write(f"# Building: {bld['id']}\n")
        f.write(f"# POIs: {bld.get('pois', [])}\n")
        f.write(f"# Height: {bld['height']}m\n\n")

        for v in vertices:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")

        f.write("\n")
        for u, v in uvs:
            f.write(f"vt {u:.4f} {v:.4f}\n")

        f.write("\n")
        for v_idx, uv_idx in faces:
            f.write(f"f {v_idx[0]}/{uv_idx[0]} {v_idx[1]}/{uv_idx[1]} {v_idx[2]}/{uv_idx[2]}\n")

    return len(vertices), len(faces)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(SCENE_PATH) as f:
        scene = json.load(f)

    with open(TILE_PATH) as f:
        tile = json.load(f)

    # Build VLM description map
    desc_by_bld = {}
    for w in tile["waypoints"]:
        bid = w.get("overture_building_id", "")
        desc = w.get("visual_description") or ""
        if bid and desc:
            if bid not in desc_by_bld or len(desc) > len(desc_by_bld[bid]):
                desc_by_bld[bid] = desc

    # Select buildings to export (all with POIs, or specific targets)
    target_ids = set()
    if len(sys.argv) > 1:
        # Export specific buildings by POI name substring
        for bld in scene["buildings"]:
            for poi in bld.get("pois", []):
                for arg in sys.argv[1:]:
                    if arg.lower() in poi.lower():
                        target_ids.add(bld["id"])
    else:
        # Export all buildings with POIs (have VLM data)
        for bld in scene["buildings"]:
            if bld.get("pois"):
                target_ids.add(bld["id"])

    print(f"Exporting {len(target_ids)} buildings to {OUTPUT_DIR}/")

    exported = 0
    for bld in scene["buildings"]:
        if bld["id"] not in target_ids:
            continue

        pois = bld.get("pois", [])
        # Sanitize filename from first POI
        name = pois[0] if pois else bld["id"][:12]
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip().replace(" ", "_").lower()

        obj_path = os.path.join(OUTPUT_DIR, f"{safe_name}.obj")
        txt_path = os.path.join(OUTPUT_DIR, f"{safe_name}_prompt.txt")

        n_verts, n_faces = export_building_obj(bld, obj_path)

        # Write texture prompt
        prompt = build_vlm_prompt(bld, desc_by_bld)
        with open(txt_path, 'w') as f:
            f.write(prompt)

        print(f"  {safe_name}: {n_verts} verts, {n_faces} faces")
        exported += 1

    print(f"\nDone. {exported} buildings exported.")


if __name__ == "__main__":
    main()
