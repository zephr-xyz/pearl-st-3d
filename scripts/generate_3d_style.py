#!/usr/bin/env python3
"""
Generate 3D style descriptions for scene buildings using Claude vision.

For each building in scene.json:
  1. Find Mapillary images of the primary facade from embedding-tile waypoints
  2. Fall back to Wikidata Commons image if no Mapillary coverage
  3. Send image to Claude vision with a 3D-rendering-focused JSON prompt
  4. Replace the building's style object in scene.json

Tiles are the same embedding-tile output used by the facade-poi-preprocessing
pipeline. The script computes which z14 tile(s) cover the scene and downloads
only those from S3 — so it scales to any city without pulling the full dataset.

Usage:
  # Dry run — show coverage, no API calls
  python3 scripts/generate_3d_style.py --tiles-dir ~/seangorman/boulder-testset/tiles --dry-run

  # Run on local tiles
  python3 scripts/generate_3d_style.py --tiles-dir ~/seangorman/boulder-testset/tiles

  # Run against S3 (downloads only the needed tiles)
  python3 scripts/generate_3d_style.py \\
    --tiles-s3 s3://zephr-mapillary-cache/poi-tiles/boulder_county/tiles_v23

  # Test single building
  python3 scripts/generate_3d_style.py \\
    --tiles-dir ~/seangorman/boulder-testset/tiles \\
    --building-id 9022e165-3bc1-48c6-a382-4cfc8d5eb9fe

  # Different city: point at a different scene + S3 tile prefix
  python3 scripts/generate_3d_style.py \\
    --scene viewer/denver_scene.json \\
    --tiles-s3 s3://zephr-mapillary-cache/poi-tiles/denver/tiles_v1
"""

import argparse
import base64
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

from anthropic import AnthropicBedrock

MAPILLARY_TOKEN = "MLY|25675740422105056|2acdd632c97850971361fc937b420bd4"
MAPILLARY_API = "https://graph.mapillary.com"
AWS = os.path.expanduser("~/Library/Python/3.9/bin/aws")
BEDROCK_REGION = "us-east-2"
CLAUDE_MODEL = "us.anthropic.claude-sonnet-4-6"

# ── tile math ────────────────────────────────────────────────────────────────

def latlon_to_tile(lat: float, lon: float, z: int = 14) -> tuple:
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return x, y


def centroid_to_latlon(cx: float, cz: float, ref_lat: float, ref_lon: float) -> tuple:
    lat = ref_lat + cz / 111320
    lon = ref_lon + cx / (111320 * math.cos(math.radians(ref_lat)))
    return lat, lon

# ── tile I/O ─────────────────────────────────────────────────────────────────

def load_tile(path: Path) -> list:
    if not path or not path.exists():
        return []
    with open(path) as f:
        return json.load(f).get("waypoints", [])


def download_tile_s3(s3_prefix: str, x: int, y: int, local_dir: Path) -> Path:
    name = f"x{x}_y{y}.json"
    dest = local_dir / name
    if dest.exists():
        return dest
    src = f"{s3_prefix.rstrip('/')}/{name}"
    result = subprocess.run([AWS, "s3", "cp", src, str(dest)], capture_output=True)
    return dest if result.returncode == 0 else None

# ── building → facade image mapping ─────────────────────────────────────────

def bearing_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def dominant_facade(waypoints: list) -> tuple:
    """
    Return (bearing, cardinal) of the most-photographed facade among these waypoints.
    Bearings are bucketed to the nearest 45° to group collinear walls.
    """
    counts = Counter()
    for wp in waypoints:
        fb = (wp.get("nav_context") or {}).get("facade_bearing")
        if fb is not None:
            bucket = round(fb / 45) * 45 % 360
            counts[bucket] += 1
    if not counts:
        return None, "primary"
    top = counts.most_common(1)[0][0]
    dirs = {0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW"}
    return top, dirs.get(top, "primary")


def collect_facade_images(waypoints: list, primary_bearing: float, max_images: int = 3) -> list:
    """
    Return Mapillary image IDs for the given facade bearing (±45°).
    Deduplicates across waypoints.
    """
    seen = set()
    ids = []
    for wp in waypoints:
        fb = (wp.get("nav_context") or {}).get("facade_bearing")
        if fb is not None and bearing_diff(fb, primary_bearing) > 45:
            continue
        for img_id in wp.get("mapillary_ids") or []:
            if img_id not in seen:
                seen.add(img_id)
                ids.append(img_id)
                if len(ids) >= max_images:
                    return ids
    return ids

# ── Mapillary ────────────────────────────────────────────────────────────────

def fetch_thumb_url(image_id: str, cache_dir: Path) -> str:
    meta = cache_dir / "mapillary" / f"{image_id}.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    if meta.exists():
        return json.loads(meta.read_text()).get("thumb_url")

    url = (f"{MAPILLARY_API}/{image_id}"
           f"?access_token={MAPILLARY_TOKEN}&fields=thumb_1024_url")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        thumb = data.get("thumb_1024_url")
        meta.write_text(json.dumps({"thumb_url": thumb}))
        return thumb
    except Exception as e:
        print(f"  Mapillary API error {image_id}: {e}", file=sys.stderr)
        return None


def image_to_b64(url: str, cache_path: Path) -> str:
    if not cache_path.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pearl-st-3d/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                cache_path.write_bytes(resp.read())
        except Exception as e:
            print(f"  Image download error: {e}", file=sys.stderr)
            return None
    return base64.b64encode(cache_path.read_bytes()).decode()

# ── VLM ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an expert architectural analyst preparing building descriptions for "
    "3D procedural rendering in Three.js. Your output is consumed directly by a "
    "scene generator — precision matters more than prose. "
    "Return only valid JSON with no markdown fences or commentary."
)

# Position convention in the prompt: 0.0 = far-left edge, 1.0 = far-right edge
# as seen in the photo. The 3D engine maps this via footprint projection onto
# the primary wall tangent axis, so it is facade-width-relative, not wall-segment-relative.
USER_PROMPT = """\
You are looking at the {cardinal}-facing facade of this building.

Describe it for 3D map rendering. Return exactly this JSON schema \
(null for genuinely unknown; estimate from visible evidence where possible):

{{
  "material": "brick|concrete|glass|stone|wood|stucco|metal|mixed",
  "color": "#RRGGBB",
  "accent": "#RRGGBB or null",
  "era": "colonial|federal|greek_revival|italianate|victorian|edwardian|art_deco|modernist|brutalist|postmodern|contemporary|unknown",
  "arch_style": "specific named style or null",
  "stories": 2,
  "ground_floor": "storefront|traditional|arcade|glass|residential",
  "windows": "standard|arched|bay|casement|ribbon|none",
  "window_grid": {{"rows": 2, "cols": 4}},
  "awning": {{"style": "flat|curved|dome", "color": "#RRGGBB"}} or null,
  "entrance": {{
    "count": 1,
    "style": "standard|recessed|arched|canopy|revolving",
    "position": 0.5
  }},
  "roof_type": "flat|stepped|pitched|mansard|dome|shed",
  "roof_profile": [
    {{"fraction": 0.6, "height_add": 2.5}}
  ] or null,
  "landmark_features": {{
    "marquee": false,
    "marquee_position": null,
    "cornice": false,
    "columns": false,
    "pediment": false,
    "clock": false,
    "tower": false
  }},
  "signage": {{"text": "VISIBLE TEXT", "position": 0.5}} or null
}}

Position rules — all position values (entrance.position, marquee_position, \
signage.position) use this scale:
  0.0 = far-left edge of this facade as seen in the photo
  1.0 = far-right edge of this facade as seen in the photo

roof_profile — only fill when roof_type is "stepped" or "mansard"; list tiers \
widest to narrowest; fraction = share of full facade width; \
height_add = metres above base building height for that tier.

Return only the JSON object.\
"""


def call_claude(image_b64: str, cardinal: str, client: AnthropicBedrock) -> dict:
    prompt = USER_PROMPT.format(cardinal=cardinal)
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception as e:
        print(f"  Claude error: {e}", file=sys.stderr)
        return None

# ── style normalisation ───────────────────────────────────────────────────────

def normalize_style(raw: dict) -> dict:
    style = {
        "source": "vlm_3d",
        "material": raw.get("material") or "concrete",
        "color": raw.get("color") or "#808080",
        "accent": raw.get("accent"),
        "era": raw.get("era") or "unknown",
        "arch_style": raw.get("arch_style"),
        "stories": max(1, int(raw.get("stories") or 2)),
        "ground_floor": raw.get("ground_floor") or "storefront",
        "windows": raw.get("windows") or "standard",
        "window_grid": raw.get("window_grid"),
        "awning": raw.get("awning"),
        "entrance": raw.get("entrance") or {"count": 1, "style": "standard", "position": 0.5},
        "roof_type": raw.get("roof_type") or "flat",
        "landmark_features": raw.get("landmark_features") or {},
        "signage": raw.get("signage"),
    }
    rp = raw.get("roof_profile")
    if isinstance(rp, list):
        # Drop base tier (height_add=0) — that's the building itself, not a step
        rp = [t for t in rp if isinstance(t, dict) and t.get("height_add", 0) > 0]
    if rp:
        style["roof_profile"] = rp
    return style

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="viewer/scene.json", help="Input scene.json")
    ap.add_argument("--tiles-dir", help="Local directory of tile JSON files")
    ap.add_argument("--tiles-s3", help="S3 prefix, e.g. s3://bucket/path/tiles_v23")
    ap.add_argument("--output", help="Output scene.json (default: in-place)")
    ap.add_argument("--cache-dir", default="output/style_cache")
    ap.add_argument("--building-id", help="Process single building (for testing)")
    ap.add_argument("--max-images", type=int, default=2, help="Max Mapillary images per building")
    ap.add_argument("--dry-run", action="store_true", help="Show coverage only, no API calls")
    ap.add_argument("--force", action="store_true", help="Re-run even if style cache exists")
    args = ap.parse_args()

    if not args.tiles_dir and not args.tiles_s3:
        ap.error("Supply --tiles-dir or --tiles-s3")

    with open(args.scene) as f:
        scene = json.load(f)

    ref_lat, ref_lon = scene["ref_lat"], scene["ref_lon"]
    buildings = scene["buildings"]
    if args.building_id:
        buildings = [b for b in buildings if b["id"] == args.building_id]
        if not buildings:
            sys.exit(f"Building {args.building_id} not found")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output or args.scene)

    # ── resolve tile files ────────────────────────────────────────────────

    needed: set = set()
    for b in buildings:
        cx, cz = b["centroid_m"]
        lat, lon = centroid_to_latlon(cx, cz, ref_lat, ref_lon)
        needed.add(latlon_to_tile(lat, lon))

    print(f"z14 tiles needed: {sorted(needed)}")

    if args.tiles_s3:
        tile_dir = cache_dir / "tiles"
        tile_dir.mkdir(exist_ok=True)
        for x, y in sorted(needed):
            p = download_tile_s3(args.tiles_s3, x, y, tile_dir)
            print(f"  {'OK' if p else 'MISSING'}: x{x}_y{y}.json")
    else:
        tile_dir = Path(args.tiles_dir).expanduser()

    # ── load waypoints ────────────────────────────────────────────────────

    waypoint_map: dict = {}
    for x, y in needed:
        for wp in load_tile(tile_dir / f"x{x}_y{y}.json"):
            bld_id = (wp.get("overture_building_id")
                      or (wp.get("nav_context") or {}).get("building_gers_id"))
            if bld_id:
                waypoint_map.setdefault(bld_id, []).append(wp)

    # ── coverage report ───────────────────────────────────────────────────

    n_mapillary = n_wikidata = n_none = 0
    for b in buildings:
        bid = b["id"]
        wps = waypoint_map.get(bid, [])
        bearing, _ = dominant_facade(wps)
        has_imgs = bool(bearing is not None and collect_facade_images(wps, bearing, 1))
        has_wiki = bool((b.get("wikidata_facts") or {}).get("image_url"))
        if has_imgs:
            n_mapillary += 1
        elif has_wiki:
            n_wikidata += 1
        else:
            n_none += 1

    print(f"\nCoverage ({len(buildings)} buildings):")
    print(f"  Mapillary: {n_mapillary}")
    print(f"  Wikidata image only: {n_wikidata}")
    print(f"  No imagery: {n_none}")

    if args.dry_run:
        return

    # ── process ───────────────────────────────────────────────────────────

    client = AnthropicBedrock(aws_region=BEDROCK_REGION)
    styles_dir = cache_dir / "styles"
    styles_dir.mkdir(exist_ok=True)

    # Work on a mutable copy of all buildings
    with open(args.scene) as f:
        full_scene = json.load(f)
    bld_by_id = {b["id"]: b for b in full_scene["buildings"]}

    processed = skipped = 0

    for bld in buildings:
        bid = bld["id"]
        style_cache = styles_dir / f"{bid}.json"

        if style_cache.exists() and not args.force:
            print(f"[cache] {bid[:16]}")
            bld_by_id[bid]["style"] = json.loads(style_cache.read_text())
            processed += 1
            continue

        # Determine primary facade
        wps = waypoint_map.get(bid, [])
        bearing, cardinal = dominant_facade(wps)
        image_b64 = None
        source_tag = ""

        # Try Mapillary first
        if bearing is not None:
            img_ids = collect_facade_images(wps, bearing, args.max_images)
            img_dir = cache_dir / "images"
            img_dir.mkdir(exist_ok=True)
            for img_id in img_ids:
                thumb = fetch_thumb_url(img_id, cache_dir)
                if thumb:
                    image_b64 = image_to_b64(thumb, img_dir / f"{img_id}.jpg")
                    if image_b64:
                        source_tag = f"mapillary:{img_id}"
                        break
                time.sleep(0.05)

        # Fall back to Wikidata Commons image
        if image_b64 is None:
            wiki_url = (bld.get("wikidata_facts") or {}).get("image_url")
            if wiki_url:
                fake_id = f"wiki_{bid[:8]}"
                img_path = (cache_dir / "images" / f"{fake_id}.jpg")
                img_path.parent.mkdir(exist_ok=True)
                image_b64 = image_to_b64(wiki_url, img_path)
                if image_b64:
                    source_tag = f"wikidata:{wiki_url.split('/')[-1][:30]}"
                    cardinal = cardinal  # use dominant facade bearing if available

        if image_b64 is None:
            print(f"[skip] {bid[:16]} no imagery")
            skipped += 1
            continue

        print(f"[{source_tag}] {bid[:16]} ({cardinal})")
        raw = call_claude(image_b64, cardinal, client)
        if raw is None:
            skipped += 1
            continue

        style = normalize_style(raw)

        # Carry forward Wikidata metadata fields (not overwritten by VLM)
        wf = bld.get("wikidata_facts") or {}
        for key, field in [("image_url", "wikidata_image_url"),
                            ("image_commons", "wikidata_image_commons"),
                            ("arch_style", "arch_style"),
                            ("era", "era"),
                            ("heritage_qid", "heritage_qid")]:
            if wf.get(key) and not style.get(field):
                style[field] = wf[key]

        style_cache.write_text(json.dumps(style, indent=2))
        bld_by_id[bid]["style"] = style
        processed += 1

        # Write incrementally so a crash doesn't lose progress
        full_scene["buildings"] = list(bld_by_id.values())
        output_path.write_text(json.dumps(full_scene, separators=(",", ":")))

        time.sleep(0.3)

    print(f"\nDone: {processed} processed, {skipped} skipped.")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
