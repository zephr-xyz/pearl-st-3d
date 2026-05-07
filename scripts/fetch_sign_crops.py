#!/usr/bin/env python3
"""
Fetch sign crop images from Mapillary and build sign data for the 3D scene.
Crops signs from source images using bbox_sign coordinates.
"""
import json
import math
import os
import re
import urllib.request
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    print("pip install Pillow")
    raise

import pyarrow.parquet as pq

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"
SIGNS_DIR = f"{OUTPUT_DIR}/signs"
MLY_TOKEN = "MLY|25675740422105056|2acdd632c97850971361fc937b420bd4"

METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def parse_wkt(wkt):
    m = re.match(r'POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)', str(wkt))
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def nearest_building(lat, lon, blds, max_dist=0.0002):
    best_id = None
    best_dist = float('inf')
    for bid, b in blds.items():
        coords = b['coordinates']
        n = len(coords)
        if coords[0] == coords[-1]:
            n -= 1
        clat = sum(coords[i][0] for i in range(n)) / n
        clon = sum(coords[i][1] for i in range(n)) / n
        d = math.sqrt((lat - clat)**2 + ((lon - clon) * math.cos(math.radians(lat)))**2)
        if d < best_dist:
            best_dist = d
            best_id = bid
    if best_dist < max_dist:
        return best_id
    return None


def fetch_and_crop(image_id, bbox, sign_id):
    """Fetch Mapillary image and crop sign region."""
    try:
        url = f"https://graph.mapillary.com/{image_id}?access_token={MLY_TOKEN}&fields=thumb_2048_url"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        thumb_url = data.get("thumb_2048_url")
        if not thumb_url:
            return None

        img_resp = urllib.request.urlopen(thumb_url, timeout=15)
        img = Image.open(BytesIO(img_resp.read()))
        w, h = img.size

        x_min = int(bbox[0] * w)
        y_min = int(bbox[1] * h)
        x_max = int(bbox[2] * w)
        y_max = int(bbox[3] * h)

        # Add small padding
        pad = 4
        x_min = max(0, x_min - pad)
        y_min = max(0, y_min - pad)
        x_max = min(w, x_max + pad)
        y_max = min(h, y_max + pad)

        crop = img.crop((x_min, y_min, x_max, y_max))

        # Resize to max 256px wide for web
        cw, ch = crop.size
        if cw > 256:
            ratio = 256 / cw
            crop = crop.resize((256, int(ch * ratio)), Image.LANCZOS)

        out_path = f"{SIGNS_DIR}/{sign_id}.jpg"
        crop.save(out_path, "JPEG", quality=80)
        return out_path
    except Exception as e:
        return None


def main():
    os.makedirs(SIGNS_DIR, exist_ok=True)

    table = pq.read_table("/tmp/overture_project/snips/boulder_snips")
    df = table.to_pandas()

    df['lon'], df['lat'] = zip(*df['wkt'].apply(parse_wkt))
    pearl = df[(df['lat'] > 40.017) & (df['lat'] < 40.021) &
               (df['lon'] > -105.284) & (df['lon'] < -105.271)]
    pearl_high = pearl[pearl['confidence_inference'] == 'high'].copy()

    with open(f"{DATA_DIR}/building_footprints_expanded.json") as f:
        blds = json.load(f)

    # Match signs to buildings, deduplicate by name per building
    signs_by_building = {}
    for _, row in pearl_high.iterrows():
        bid = nearest_building(row['lat'], row['lon'], blds)
        if not bid:
            continue
        name = row['name']
        if bid not in signs_by_building:
            signs_by_building[bid] = {}
        # Keep best confidence_semseg per name
        existing = signs_by_building[bid].get(name)
        if existing is None or row['confidence_semseg'] > existing['confidence_semseg']:
            signs_by_building[bid][name] = {
                'name': name,
                'text': row['extracted_text'],
                'lat': row['lat'],
                'lon': row['lon'],
                'image_id': str(row['image_id']),
                'bbox_sign': row['bbox_sign'].tolist() if hasattr(row['bbox_sign'], 'tolist') else list(row['bbox_sign']),
                'confidence_semseg': float(row['confidence_semseg']) if row['confidence_semseg'] else 0,
                'is_logo': bool(row['is_logo']),
            }

    # Flatten to list, limit to 1-2 signs per building for performance
    signs = []
    for bid, name_map in signs_by_building.items():
        # Sort by confidence, take top 2
        sorted_signs = sorted(name_map.values(), key=lambda s: -s['confidence_semseg'])[:2]
        for s in sorted_signs:
            s['building_id'] = bid
            signs.append(s)

    print(f"Signs to fetch: {len(signs)} across {len(signs_by_building)} buildings")

    # Fetch and crop sign images (parallel)
    successful = []
    failed = 0

    def process_sign(idx_sign):
        idx, sign = idx_sign
        sign_id = f"sign_{idx:04d}"
        result = fetch_and_crop(sign['image_id'], sign['bbox_sign'], sign_id)
        if result:
            sign['image_path'] = f"signs/{sign_id}.jpg"
            return sign
        return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_sign, (i, s)): i for i, s in enumerate(signs)}
        for future in as_completed(futures):
            result = future.result()
            if result:
                successful.append(result)
            else:
                failed += 1
            if (len(successful) + failed) % 20 == 0:
                print(f"  Progress: {len(successful)} fetched, {failed} failed")

    print(f"\nDone: {len(successful)} sign crops saved, {failed} failed")
    print(f"Buildings with signs: {len(set(s['building_id'] for s in successful))}")

    # Save sign metadata
    with open(f"{OUTPUT_DIR}/signs.json", "w") as f:
        json.dump(successful, f)

    print(f"Output: {OUTPUT_DIR}/signs.json")


if __name__ == "__main__":
    main()
