#!/usr/bin/env python3
"""
Run VLM style extraction on buildings that have Wikidata Commons images.

For each building in scene.json that has style.wikidata_image_url:
  1. Download the image
  2. Send to Claude Vision with the same 3D-rendering prompt used by generate_3d_style.py
  3. Merge result into the building's style, preserving wikidata-authoritative fields
     (arch_style, era) as overrides if they were already set

Usage:
  # Dry run — list buildings and image sources
  python3 scripts/run_wikidata_vlm.py --dry-run

  # Run all wikidata-matched buildings
  python3 scripts/run_wikidata_vlm.py

  # Skip specific building IDs (e.g. known-bad images)
  python3 scripts/run_wikidata_vlm.py --skip 4da2870e,68f5bdb6,c9073cdc

  # Re-run even if cached
  python3 scripts/run_wikidata_vlm.py --force
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from anthropic import AnthropicBedrock

BEDROCK_REGION = "us-east-2"
CLAUDE_MODEL = "us.anthropic.claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "You are an expert architectural analyst preparing building descriptions for "
    "3D procedural rendering in Three.js. Your output is consumed directly by a "
    "scene generator — precision matters more than prose. "
    "Return only valid JSON with no markdown fences or commentary."
)

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


def image_to_b64(url: str, cache_path: Path):
    if not cache_path.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pearl-st-3d/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            cache_path.write_bytes(data)
        except Exception as e:
            print(f"  Download error: {e}", file=sys.stderr)
            return None
    return base64.b64encode(cache_path.read_bytes()).decode()


def call_claude(image_b64: str, cardinal: str, media_type: str, client: AnthropicBedrock):
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
                            "media_type": media_type,
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


def normalize_style(raw: dict) -> dict:
    style = {
        "source": "vlm_wikidata",
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
        rp = [t for t in rp if isinstance(t, dict) and t.get("height_add", 0) > 0]
    if rp:
        style["roof_profile"] = rp
    return style


def merge_style(vlm: dict, existing: dict) -> dict:
    merged = dict(vlm)
    # Wikidata-authoritative fields win over VLM when already set
    for field in ("arch_style", "era"):
        if existing.get(field):
            merged[field] = existing[field]
    # Always preserve wikidata image metadata
    for field in ("wikidata_image_url", "wikidata_image_commons", "heritage_qid"):
        if existing.get(field):
            merged[field] = existing[field]
    return merged


def media_type_from_url(url: str) -> str:
    low = url.lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".gif"):
        return "image/gif"
    if low.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="viewer/scene.json")
    ap.add_argument("--cache-dir", default="output/style_cache")
    ap.add_argument("--skip", default="", help="Comma-separated building ID prefixes to skip")
    ap.add_argument("--only", default="", help="Comma-separated building ID prefixes to include (others skipped)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="Re-run even if cached")
    args = ap.parse_args()

    skip_ids = set(s.strip() for s in args.skip.split(",") if s.strip())
    only_ids = set(s.strip() for s in args.only.split(",") if s.strip())

    with open(args.scene) as f:
        scene = json.load(f)

    cache_dir = Path(args.cache_dir)
    img_dir = cache_dir / "wikidata_images"
    styles_dir = cache_dir / "wikidata_styles"
    img_dir.mkdir(parents=True, exist_ok=True)
    styles_dir.mkdir(parents=True, exist_ok=True)

    targets = []
    for b in scene["buildings"]:
        s = b.get("style", {})
        if not isinstance(s, dict):
            continue
        url = s.get("wikidata_image_url")
        if not url:
            continue
        bid = b["id"]
        if any(bid.startswith(p) for p in skip_ids):
            print(f"[skip] {bid[:8]}  (in --skip list)")
            continue
        if only_ids and not any(bid.startswith(p) for p in only_ids):
            continue
        pois = b.get("pois", [])
        name = pois[0] if pois and isinstance(pois[0], str) else bid[:8]
        commons = s.get("wikidata_image_commons", url.split("/")[-1])
        targets.append((b, url, name, commons))

    print(f"Wikidata buildings to process: {len(targets)}")
    for b, url, name, commons in targets:
        s = b.get("style", {})
        print(f"  {b['id'][:8]}  {str(name)[:35]:<36} arch={s.get('arch_style',''):<25} era={s.get('era',''):<12}  {commons}")

    if args.dry_run:
        return

    client = AnthropicBedrock(aws_region=BEDROCK_REGION)
    bld_by_id = {b["id"]: b for b in scene["buildings"]}
    output_path = Path(args.scene)

    for b, img_url, name, commons in targets:
        bid = b["id"]
        style_cache = styles_dir / f"{bid}.json"

        if style_cache.exists() and not args.force:
            print(f"[cache] {bid[:8]}  {str(name)[:35]}")
            cached = json.loads(style_cache.read_text())
            bld_by_id[bid]["style"] = merge_style(cached, b.get("style", {}))
            scene["buildings"] = list(bld_by_id.values())
            output_path.write_text(json.dumps(scene, separators=(",", ":")))
            continue

        ext = commons.rsplit(".", 1)[-1].lower() if "." in commons else "jpg"
        img_path = img_dir / f"{bid}.{ext}"
        mt = media_type_from_url(img_url)

        print(f"[dl]  {bid[:8]}  {commons[:50]}")
        image_b64 = image_to_b64(img_url, img_path)
        if image_b64 is None:
            print(f"  ERROR: could not download image, skipping")
            continue

        print(f"[vlm] {bid[:8]}  {str(name)[:35]}")
        raw = call_claude(image_b64, "primary", mt, client)
        if raw is None:
            continue

        vlm_style = normalize_style(raw)
        merged = merge_style(vlm_style, b.get("style", {}))

        style_cache.write_text(json.dumps(vlm_style, indent=2))
        bld_by_id[bid]["style"] = merged
        scene["buildings"] = list(bld_by_id.values())
        output_path.write_text(json.dumps(scene, separators=(",", ":")))

        print(f"  -> material={merged.get('material')} color={merged.get('color')} "
              f"arch={merged.get('arch_style')} era={merged.get('era')} "
              f"stories={merged.get('stories')}")
        time.sleep(0.3)

    print("\nDone.")


if __name__ == "__main__":
    main()
