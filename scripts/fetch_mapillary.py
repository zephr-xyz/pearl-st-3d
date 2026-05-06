#!/usr/bin/env python3
"""
Fetch Mapillary images and metadata for Pearl St POC buildings.
Downloads images and camera poses for facade projection.
"""
import json
import os
import urllib.request
import urllib.error
import time

DATA_DIR = "/private/tmp/pearl-st-3d/data"
IMG_DIR = "/private/tmp/pearl-st-3d/textures/mapillary"
os.makedirs(IMG_DIR, exist_ok=True)

TOKEN = "MLY|25675740422105056|2acdd632c97850971361fc937b420bd4"

# Load block data to map images to buildings
with open(f"{DATA_DIR}/block_pois.json") as f:
    pois = json.load(f)

# Build mapping: image_id -> building_id, poi_name
image_to_building = {}
for poi in pois:
    bld_id = poi.get("overture_building_id") or (poi.get("nav_context", {}) or {}).get("building_gers_id")
    if not bld_id:
        continue
    for img_id in (poi.get("mapillary_ids") or []):
        image_to_building[img_id] = {
            "building_id": bld_id,
            "poi_name": poi.get("name", ""),
        }

print(f"Total image-building mappings: {len(image_to_building)}")

# Fetch metadata and download images
# Use Mapillary Graph API v4
results = []
batch_size = 10
image_ids = list(image_to_building.keys())

# Limit to best images per building (max 4 per building for the POC)
building_image_count = {}
selected_ids = []
for img_id in image_ids:
    bld = image_to_building[img_id]["building_id"]
    building_image_count.setdefault(bld, 0)
    if building_image_count[bld] < 4:
        selected_ids.append(img_id)
        building_image_count[bld] += 1

print(f"Selected {len(selected_ids)} images ({len(building_image_count)} buildings)")

for img_id in selected_ids:
    # Get metadata
    url = f"https://graph.mapillary.com/{img_id}?access_token={TOKEN}&fields=id,geometry,compass_angle,computed_geometry,computed_compass_angle,thumb_1024_url,thumb_2048_url,height,width,captured_at"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            meta = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"  SKIP {img_id}: {e}")
        continue

    # Get image URL (prefer 2048, fall back to 1024)
    img_url = meta.get("thumb_2048_url") or meta.get("thumb_1024_url")
    if not img_url:
        print(f"  SKIP {img_id}: no image URL")
        continue

    # Download image
    img_path = f"{IMG_DIR}/{img_id}.jpg"
    if not os.path.exists(img_path):
        try:
            urllib.request.urlretrieve(img_url, img_path)
        except Exception as e:
            print(f"  SKIP {img_id} download: {e}")
            continue

    # Extract camera data
    geom = meta.get("computed_geometry") or meta.get("geometry") or {}
    coords = geom.get("coordinates", [None, None])
    heading = meta.get("computed_compass_angle") or meta.get("compass_angle") or 0

    result = {
        "image_id": img_id,
        "building_id": image_to_building[img_id]["building_id"],
        "poi_name": image_to_building[img_id]["poi_name"],
        "camera_lon": coords[0],
        "camera_lat": coords[1],
        "camera_heading": heading,
        "width": meta.get("width"),
        "height": meta.get("height"),
        "image_path": f"mapillary/{img_id}.jpg",
        "captured_at": meta.get("captured_at"),
    }
    results.append(result)
    print(f"  OK {img_id} → {result['poi_name'][:30]} heading={heading:.0f}")
    time.sleep(0.1)  # Rate limit

# Save metadata
with open(f"{DATA_DIR}/mapillary_metadata.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nDone: {len(results)} images downloaded with metadata")
print(f"Images in: {IMG_DIR}")

# Summary per building
per_bld = {}
for r in results:
    per_bld.setdefault(r["building_id"], []).append(r)

for bld_id, imgs in per_bld.items():
    names = set(i["poi_name"] for i in imgs)
    print(f"  {bld_id[:8]}... ({', '.join(names)[:40]}): {len(imgs)} images")
