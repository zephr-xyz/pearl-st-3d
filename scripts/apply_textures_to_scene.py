#!/usr/bin/env python3
"""
Apply Paint-it generated textures to scene.json buildings.

Adds texture paths to building style data so the Three.js viewer
can load PBR textures (diffuse, roughness, normal, metallic) for
buildings that have been processed through the texture generation pipeline.
"""
import json
import os
import sys

SCENE_PATH = "/private/tmp/pearl-st-3d/viewer/scene.json"
TEXTURE_DIR = "/private/tmp/pearl-st-3d/data/textures"
MESH_DIR = "/private/tmp/pearl-st-3d/data/meshes"


def main():
    with open(SCENE_PATH) as f:
        scene = json.load(f)

    # Build mapping: safe_name -> building_id
    name_to_id = {}
    for bld in scene["buildings"]:
        pois = bld.get("pois", [])
        if pois:
            name = pois[0]
            safe_name = "".join(
                c if c.isalnum() or c in "-_ " else "" for c in name
            ).strip().replace(" ", "_").lower()
            name_to_id[safe_name] = bld["id"]

    applied = 0
    for dirname in os.listdir(TEXTURE_DIR):
        tex_dir = os.path.join(TEXTURE_DIR, dirname)
        if not os.path.isdir(tex_dir):
            continue

        diffuse = os.path.join(tex_dir, "diffuse.png")
        if not os.path.exists(diffuse):
            continue

        bid = name_to_id.get(dirname)
        if not bid:
            print(f"  WARN: no building match for {dirname}")
            continue

        # Find the building and add texture paths
        for bld in scene["buildings"]:
            if bld["id"] == bid:
                style = bld.get("style", {})
                style["textures"] = {
                    "diffuse": f"textures/{dirname}/diffuse.png",
                    "roughness": f"textures/{dirname}/roughness.png",
                    "normal": f"textures/{dirname}/normal.png",
                    "metallic": f"textures/{dirname}/metallic.png",
                }
                bld["style"] = style
                applied += 1
                print(f"  Applied textures: {dirname} -> {pois[0] if bld.get('pois') else bid[:12]}")
                break

    with open(SCENE_PATH, "w") as f:
        json.dump(scene, f)

    print(f"\n{applied} buildings now have PBR textures.")


if __name__ == "__main__":
    main()
