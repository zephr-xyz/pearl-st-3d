#!/bin/sh
# Capture every standard view into one directory (default .work/shots/<short commit>).
# Usage: tools/standard_views.sh [outdir] [extra URL params]
set -e
cd "$(dirname "$0")/.."
OUT="${1:-.work/shots/$(git rev-parse --short HEAD 2>/dev/null || echo wip)}"
EXTRA="${2:-}"
mkdir -p "$OUT"
python3 tools/shoot.py --views orbit,birds,mall_e,mall_mid_e,mall_w --out "$OUT" ${EXTRA:+--params "$EXTRA"}
for f in f61c4184:oddfellows 9022e165:boulder_theater 954cb30c:posterscene 67797069:mountain_sun; do
  id="${f%%:*}"; name="${f##*:}"
  python3 tools/shoot.py --params "facade=$id${EXTRA:+&$EXTRA}" --out "$OUT/facade_$name.png"
done
echo "captured into $OUT"
