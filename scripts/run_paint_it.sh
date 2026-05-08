#!/bin/bash
# Run Paint-it texture generation on exported building meshes.
# Execute on EC2 g5.xlarge (A10G 24GB VRAM).
#
# Setup (run once):
#   conda create -n paintit python=3.9 -y
#   conda activate paintit
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
#   pip install git+https://github.com/NVlabs/nvdiffrast
#   git clone https://github.com/facebookresearch/paint-it.git ~/paint-it
#   cd ~/paint-it && pip install -r requirements.txt
#
# Usage:
#   ./run_paint_it.sh /path/to/meshes/ /path/to/output/
#
# Each building gets: diffuse.png, roughness.png, normal.png, metallic.png

set -e

MESH_DIR="${1:-/tmp/pearl-st-3d/data/meshes}"
OUTPUT_DIR="${2:-/tmp/pearl-st-3d/data/textures}"
PAINT_IT_DIR="${PAINT_IT_DIR:-$HOME/paint-it}"

mkdir -p "$OUTPUT_DIR"

# Process each OBJ file with its companion prompt
for obj_file in "$MESH_DIR"/*.obj; do
    basename=$(basename "$obj_file" .obj)
    prompt_file="$MESH_DIR/${basename}_prompt.txt"
    out_dir="$OUTPUT_DIR/$basename"

    if [ -d "$out_dir" ] && [ -f "$out_dir/diffuse.png" ]; then
        echo "SKIP $basename (already done)"
        continue
    fi

    if [ ! -f "$prompt_file" ]; then
        echo "SKIP $basename (no prompt file)"
        continue
    fi

    prompt=$(cat "$prompt_file")
    mkdir -p "$out_dir"

    echo "=== Processing $basename ==="
    echo "    Prompt: ${prompt:0:100}..."

    cd "$PAINT_IT_DIR"
    python run.py \
        --mesh "$obj_file" \
        --text "$prompt" \
        --output_dir "$out_dir" \
        --resolution 1024 \
        --num_views 8 \
        --guidance_scale 7.5 \
        --num_steps 1000 \
        --pbr \
        2>&1 | tail -5

    echo "    Done: $(ls "$out_dir"/*.png 2>/dev/null | wc -l) maps generated"
    echo ""

    # Sync after each building (spot instance safety)
    aws s3 sync "$OUTPUT_DIR" s3://zephr-mapillary-cache/pearl-st-3d/textures/ --quiet
done

echo "=== All buildings processed ==="
echo "Textures at: $OUTPUT_DIR"
echo "S3 sync: s3://zephr-mapillary-cache/pearl-st-3d/textures/"
