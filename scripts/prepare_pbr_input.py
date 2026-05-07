#!/usr/bin/env python3
"""
Prepare facade images for PBRFusion4 processing.
Takes rectified facade crops and outputs properly sized/formatted inputs
that can be fed to the ComfyUI PBRFusion4 node for PBR map generation.

PBRFusion4 expects:
- Single baked/diffuse texture image
- Supports 1k/2k/4k resolutions
- Outputs: depth, filtered depth, normal map, intensity map

This script:
1. Loads best facade images per building
2. Resizes to 1024x1024 (or aspect-preserving power-of-2)
3. Enhances for better PBR decomposition (normalize exposure)
4. Outputs to pbr_input/ ready for batch processing
"""
import json
import os

import cv2
import numpy as np

DATA_DIR = "/private/tmp/pearl-st-3d/data"
FACADES_DIR = f"{DATA_DIR}/facades"
PBR_INPUT_DIR = f"{DATA_DIR}/pbr_input"
PBR_OUTPUT_DIR = f"{DATA_DIR}/pbr_output"


def prepare_image(img_path, output_path, target_size=1024):
    """Prepare a single facade image for PBRFusion4."""
    img = cv2.imread(img_path)
    if img is None:
        return False

    h, w = img.shape[:2]

    # Resize preserving aspect ratio, fitting into target_size
    if w > h:
        new_w = target_size
        new_h = int(h * target_size / w)
    else:
        new_h = target_size
        new_w = int(w * target_size / h)

    # Round to nearest multiple of 8 (common requirement for neural networks)
    new_w = (new_w // 8) * 8
    new_h = (new_h // 8) * 8

    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    # Normalize exposure (CLAHE on L channel)
    lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    normalized = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    cv2.imwrite(output_path, normalized, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    return True


def generate_procedural_normal_map(style, width=512, height=512):
    """
    Generate a procedural normal map based on material type.
    This is a stand-in until PBRFusion4 produces real normal maps.
    """
    normal = np.zeros((height, width, 3), dtype=np.uint8)
    # Flat normal = (0.5, 0.5, 1.0) in tangent space = (128, 128, 255) as uint8
    normal[:, :] = [128, 128, 255]

    material = style.get("material", "brick")

    if "brick" in material:
        brick_h = int(height * 0.015)
        brick_w = int(width * 0.03)
        mortar = 2

        for y in range(0, height, brick_h + mortar):
            row_idx = y // (brick_h + mortar)
            offset = (row_idx % 2) * (brick_w // 2)

            # Horizontal mortar groove (normal points down)
            normal[y:y+mortar, :] = [128, 110, 240]

            # Vertical mortar grooves
            for x in range(offset, width, brick_w + mortar):
                normal[y:y+brick_h, x:x+mortar] = [110, 128, 240]

            # Slight random perturbation on brick faces
            for x in range(offset, width, brick_w + mortar):
                bx = x + mortar
                by = y + mortar
                if bx < width and by < height:
                    ex = min(bx + brick_w, width)
                    ey = min(by + brick_h, height)
                    # Subtle bump
                    noise = np.random.randint(-3, 4, (ey-by, ex-bx, 3)).astype(np.int16)
                    noise[:, :, 2] = 0  # Don't perturb Z
                    patch = normal[by:ey, bx:ex].astype(np.int16) + noise
                    normal[by:ey, bx:ex] = np.clip(patch, 0, 255).astype(np.uint8)

    elif material == "stone":
        stone_h = int(height * 0.04)
        stone_w = int(width * 0.06)
        for y in range(0, height, stone_h + 3):
            normal[y:y+3, :] = [128, 105, 235]
            offset = (y // (stone_h + 3) % 2) * (stone_w // 3)
            for x in range(offset, width, stone_w + 3):
                normal[y:y+stone_h, x:x+3] = [105, 128, 235]

    return normal


def generate_procedural_roughness_map(style, width=512, height=512):
    """
    Generate roughness map based on material.
    White = rough, Black = smooth (metallic-roughness workflow).
    """
    material = style.get("material", "brick")

    if "brick" in material:
        base_roughness = 200  # Fairly rough
    elif material == "stone":
        base_roughness = 180
    elif material == "stucco":
        base_roughness = 210
    elif material == "glass":
        base_roughness = 30  # Very smooth
    elif material == "metal":
        base_roughness = 80
    else:
        base_roughness = 180

    roughness = np.full((height, width), base_roughness, dtype=np.uint8)

    # Add variation
    noise = np.random.randint(-15, 16, (height, width)).astype(np.int16)
    roughness = np.clip(roughness.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    return roughness


def main():
    os.makedirs(PBR_INPUT_DIR, exist_ok=True)
    os.makedirs(PBR_OUTPUT_DIR, exist_ok=True)

    # Load facade analysis results
    analysis_path = f"{FACADES_DIR}/facade_analysis.json"
    if os.path.exists(analysis_path):
        with open(analysis_path) as f:
            analysis = json.load(f)
    else:
        analysis = []

    # Load facade params for procedural fallback
    params_path = f"{FACADES_DIR}/facade_params.json"
    with open(params_path) as f:
        params = json.load(f)

    prepared = 0
    procedural_generated = 0

    # Prepare real facade images
    for entry in analysis:
        facade_path = entry.get("facade_path")
        if facade_path and os.path.exists(facade_path):
            bid = entry["building_id"][:8]
            out_path = f"{PBR_INPUT_DIR}/{bid}_albedo.png"
            if prepare_image(facade_path, out_path):
                prepared += 1

    # Generate procedural PBR maps for buildings without real images
    for fp in params:
        bid = fp["building_id"][:8]
        normal_path = f"{PBR_OUTPUT_DIR}/{bid}_normal.png"
        roughness_path = f"{PBR_OUTPUT_DIR}/{bid}_roughness.png"

        if not os.path.exists(normal_path):
            normal = generate_procedural_normal_map(fp)
            cv2.imwrite(normal_path, normal)

            roughness = generate_procedural_roughness_map(fp)
            cv2.imwrite(roughness_path, roughness)
            procedural_generated += 1

    print(f"PBR Input prepared: {prepared} real facade images")
    print(f"Procedural PBR maps generated: {procedural_generated} buildings")
    print(f"\nTo process with PBRFusion4 (requires ComfyUI + GPU):")
    print(f"  Input dir: {PBR_INPUT_DIR}/")
    print(f"  Output dir: {PBR_OUTPUT_DIR}/")
    print(f"\nProcedural normal/roughness maps ready for immediate use:")
    print(f"  {PBR_OUTPUT_DIR}/<building_id>_normal.png")
    print(f"  {PBR_OUTPUT_DIR}/<building_id>_roughness.png")


if __name__ == "__main__":
    main()
