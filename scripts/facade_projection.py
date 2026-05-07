#!/usr/bin/env python3
"""
Facade projection pipeline v2:
1. Fetch Mapillary images where camera faces the building
2. Use vanishing point detection to rectify perspective
3. Extract window/entrance grid from rectified facade
4. Output facade textures + feature counts for the 3D viewer
"""
import json
import math
import os
import urllib.request
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np
from PIL import Image

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/data/facades"
MLY_TOKEN = "MLY|25675740422105056|2acdd632c97850971361fc937b420bd4"

METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def angle_diff(a, b):
    """Smallest signed angle difference in degrees."""
    d = (a - b + 180) % 360 - 180
    return d


def fetch_image_metadata(image_id):
    """Fetch metadata from Mapillary."""
    url = (f"https://graph.mapillary.com/{image_id}?access_token={MLY_TOKEN}"
           f"&fields=thumb_2048_url,computed_geometry,computed_compass_angle,width,height")
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


def fetch_image(thumb_url):
    """Download image from thumb URL."""
    resp = urllib.request.urlopen(thumb_url, timeout=20)
    return Image.open(BytesIO(resp.read()))


def bearing_to_point(from_lat, from_lon, to_lat, to_lon):
    """Compute bearing from one point to another."""
    dlat = to_lat - from_lat
    dlon = (to_lon - from_lon) * math.cos(math.radians(from_lat))
    return math.degrees(math.atan2(dlon, dlat)) % 360


def select_best_image(image_ids, building_lat, building_lon, max_images=8):
    """Select the image that most directly faces the building."""
    scored = []

    for img_id in image_ids[:max_images]:
        try:
            meta = fetch_image_metadata(img_id)
        except Exception:
            continue

        geom = meta.get("computed_geometry", {})
        coords = geom.get("coordinates")
        if not coords:
            continue

        cam_lon, cam_lat = coords[0], coords[1]
        heading = meta.get("computed_compass_angle", 0)
        thumb_url = meta.get("thumb_2048_url")
        if not thumb_url:
            continue

        # Bearing from camera to building centroid
        to_building = bearing_to_point(cam_lat, cam_lon, building_lat, building_lon)

        # How directly does camera face the building?
        face_angle = abs(angle_diff(heading, to_building))

        # Distance to building
        dx = (building_lon - cam_lon) * m_lng_at(cam_lat)
        dy = (building_lat - cam_lat) * METERS_PER_DEG_LAT
        dist = math.sqrt(dx * dx + dy * dy)

        # Prefer: facing building (low angle), moderate distance (8-25m)
        dist_score = abs(dist - 15) / 15  # Optimal around 15m
        angle_score = face_angle / 90  # Lower is better

        # Skip if not facing building at all
        if face_angle > 60:
            continue

        score = angle_score + dist_score * 0.5
        scored.append({
            "image_id": img_id,
            "thumb_url": thumb_url,
            "heading": heading,
            "cam_lat": cam_lat,
            "cam_lon": cam_lon,
            "face_angle": face_angle,
            "distance": dist,
            "score": score,
            "width": meta.get("width", 2048),
            "height": meta.get("height", 1536),
        })

    if not scored:
        return None
    return min(scored, key=lambda x: x["score"])


def detect_vanishing_points(img_cv):
    """Detect vertical and horizontal vanishing points using line segments."""
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # LSD line segment detector
    lsd = cv2.createLineSegmentDetector(0)
    lines, widths, prec, nfa = lsd.detect(gray)
    if lines is None or len(lines) < 10:
        return None, None

    # Classify lines as vertical or horizontal
    vertical_lines = []
    horizontal_lines = []

    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < 20:
            continue
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        if angle > 70:  # Nearly vertical
            vertical_lines.append((x1, y1, x2, y2))
        elif angle < 20:  # Nearly horizontal
            horizontal_lines.append((x1, y1, x2, y2))

    # Estimate vertical vanishing point (from vertical lines)
    vp_vertical = None
    if len(vertical_lines) >= 3:
        # For vertical VP: lines converge at top or bottom
        # Use median of line extensions
        x_at_top = []
        for x1, y1, x2, y2 in vertical_lines:
            if abs(y2 - y1) < 10:
                continue
            slope = (x2 - x1) / (y2 - y1)
            x_top = x1 + slope * (0 - y1)
            x_at_top.append(x_top)
        if x_at_top:
            vp_vertical = (np.median(x_at_top), 0)

    return vp_vertical, len(vertical_lines)


def rectify_perspective(img_cv):
    """
    Rectify vertical perspective distortion using detected vertical lines.
    Makes building edges truly vertical.
    """
    h, w = img_cv.shape[:2]
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # Detect lines
    lsd = cv2.createLineSegmentDetector(0)
    lines, _, _, _ = lsd.detect(gray)
    if lines is None or len(lines) < 5:
        return img_cv

    # Find strong vertical lines
    vert_angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < h * 0.1:
            continue
        angle = math.atan2(dx, dy)  # Angle from vertical
        if abs(angle) < math.radians(20):
            vert_angles.append(angle)

    if len(vert_angles) < 3:
        return img_cv

    # Median tilt angle
    tilt = np.median(vert_angles)
    if abs(tilt) < math.radians(1):
        return img_cv  # Already vertical enough

    # Apply perspective correction to make verticals truly vertical
    # The tilt means top of image is shifted relative to bottom
    shift = math.tan(tilt) * h

    src_pts = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst_pts = np.array([
        [shift / 2, 0], [w + shift / 2, 0],
        [w - shift / 2, h], [-shift / 2, h]
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    corrected = cv2.warpPerspective(img_cv, M, (w, h))
    return corrected


def crop_facade_region(img_cv, face_angle, distance):
    """
    Crop the central facade region from the image.
    When camera faces building directly, facade is in the center.
    """
    h, w = img_cv.shape[:2]

    # Vertical crop: remove sky (top ~25%) and ground (bottom ~15%)
    y_top = int(h * 0.15)
    y_bot = int(h * 0.85)

    # Horizontal crop: center region, wider when closer
    coverage = min(0.9, 0.5 + 0.3 * (20 / max(distance, 5)))
    margin = (1 - coverage) / 2
    x_left = int(w * margin)
    x_right = int(w * (1 - margin))

    # Shift based on face angle (if camera is slightly off-center)
    angle_shift = int(w * face_angle / 180 * 0.3)
    x_left = max(0, x_left - angle_shift)
    x_right = min(w, x_right - angle_shift)

    cropped = img_cv[y_top:y_bot, x_left:x_right]
    return cropped


def detect_windows_grid(img_cv):
    """
    Detect windows using morphological analysis tuned for building facades.
    Returns window grid (rows x cols) and individual window bboxes.
    """
    h, w = img_cv.shape[:2]
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # Enhance contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Windows are typically darker rectangular regions
    # Use adaptive threshold
    blurred = cv2.GaussianBlur(enhanced, (7, 7), 0)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 8)

    # Morphological operations to clean up
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter for window-like shapes
    min_area = (w * h) * 0.003
    max_area = (w * h) * 0.12
    min_dim = min(w, h) * 0.04
    max_dim = max(w, h) * 0.4

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < min_dim or bh < min_dim:
            continue
        if bw > max_dim or bh > max_dim:
            continue

        # Windows: aspect ratio between 0.4 and 2.5
        aspect = bw / bh if bh > 0 else 0
        if aspect < 0.3 or aspect > 3.0:
            continue

        # Rectangularity: contour area vs bounding rect area
        rect_area = bw * bh
        rectangularity = area / rect_area if rect_area > 0 else 0
        if rectangularity < 0.5:
            continue

        candidates.append({
            "x": x, "y": y, "w": bw, "h": bh,
            "cx": x + bw / 2, "cy": y + bh / 2,
            "area": area,
        })

    if not candidates:
        return {"count": 0, "rows": 0, "cols": 0, "windows": [], "grid": None}

    # Cluster into rows by y-center
    candidates.sort(key=lambda c: c["cy"])
    rows = []
    row_tolerance = h * 0.08

    current_row = [candidates[0]]
    for c in candidates[1:]:
        if abs(c["cy"] - current_row[0]["cy"]) < row_tolerance:
            current_row.append(c)
        else:
            rows.append(sorted(current_row, key=lambda c: c["cx"]))
            current_row = [c]
    rows.append(sorted(current_row, key=lambda c: c["cx"]))

    # Filter: rows with only 1 window might be noise unless consistent size
    median_area = np.median([c["area"] for c in candidates])
    valid_rows = []
    for row in rows:
        # Keep rows where windows are similar size to median
        row_filtered = [w for w in row if 0.3 * median_area < w["area"] < 3 * median_area]
        if row_filtered:
            valid_rows.append(row_filtered)

    n_rows = len(valid_rows)
    n_cols = max(len(r) for r in valid_rows) if valid_rows else 0
    all_windows = [w for row in valid_rows for w in row]

    return {
        "count": len(all_windows),
        "rows": n_rows,
        "cols": n_cols,
        "windows": all_windows,
        "grid": {"rows": n_rows, "cols": n_cols},
    }


def detect_entrances_v2(img_cv):
    """Detect entrance/door regions in the ground floor."""
    h, w = img_cv.shape[:2]

    # Ground floor = bottom 45%
    gf_top = int(h * 0.55)
    ground_floor = img_cv[gf_top:, :]
    gf_h, gf_w = ground_floor.shape[:2]

    gray = cv2.cvtColor(ground_floor, cv2.COLOR_BGR2GRAY)

    # Doors are typically darker, taller-than-wide openings
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 21, 8)

    # Look for tall rectangular regions
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    entrances = []
    min_area = gf_w * gf_h * 0.02
    max_area = gf_w * gf_h * 0.4

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)

        # Doors are taller than wide
        if bh < bw * 0.7:
            continue

        # Must be reasonably tall
        if bh < gf_h * 0.3:
            continue

        # Must reach near the bottom
        if y + bh < gf_h * 0.8:
            continue

        entrances.append({
            "x": x, "y": y + gf_top,
            "w": bw, "h": bh,
            "cx_norm": (x + bw / 2) / gf_w,
        })

    return entrances


def process_building(building_id, image_ids, building_lat, building_lon,
                     building_height=None, poi_name=None):
    """Full pipeline for one building."""
    print(f"\n  Processing: {poi_name or building_id[:8]}")

    # Step 1: Select best image
    best = select_best_image(image_ids, building_lat, building_lon)
    if not best:
        print(f"    No suitable image found")
        return None

    print(f"    Best image: {best['image_id']} (face_angle={best['face_angle']:.1f}, dist={best['distance']:.1f}m)")

    # Step 2: Fetch image
    try:
        img_pil = fetch_image(best["thumb_url"])
    except Exception as e:
        print(f"    Failed to fetch image: {e}")
        return None

    img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    # Step 3: Rectify perspective (make verticals straight)
    rectified = rectify_perspective(img_cv)

    # Step 4: Crop facade region
    facade = crop_facade_region(rectified, best["face_angle"], best["distance"])
    fh, fw = facade.shape[:2]
    print(f"    Facade crop: {fw}x{fh}")

    # Step 5: Detect windows
    windows = detect_windows_grid(facade)
    print(f"    Windows: {windows['count']} ({windows['rows']}r x {windows['cols']}c)")

    # Step 6: Detect entrances
    entrances = detect_entrances_v2(facade)
    print(f"    Entrances: {len(entrances)}")

    # Save outputs
    facade_path = f"{OUTPUT_DIR}/{building_id[:8]}_facade.jpg"
    cv2.imwrite(facade_path, facade, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # Save annotated
    annotated = facade.copy()
    for win in windows["windows"]:
        cv2.rectangle(annotated, (win["x"], win["y"]),
                     (win["x"] + win["w"], win["y"] + win["h"]), (0, 255, 0), 2)
    for ent in entrances:
        cv2.rectangle(annotated, (ent["x"], ent["y"]),
                     (ent["x"] + ent["w"], ent["y"] + ent["h"]), (0, 0, 255), 3)
    cv2.imwrite(f"{OUTPUT_DIR}/{building_id[:8]}_annotated.jpg", annotated)

    # Save full source for reference
    cv2.imwrite(f"{OUTPUT_DIR}/{building_id[:8]}_source.jpg", img_cv, [cv2.IMWRITE_JPEG_QUALITY, 85])

    return {
        "building_id": building_id,
        "poi_name": poi_name,
        "image_id": best["image_id"],
        "face_angle": best["face_angle"],
        "distance": best["distance"],
        "camera_heading": best["heading"],
        "facade_path": facade_path,
        "facade_size": [fw, fh],
        "building_height": building_height,
        "windows": {
            "count": windows["count"],
            "rows": windows["rows"],
            "cols": windows["cols"],
        },
        "entrances": {
            "count": len(entrances),
            "positions": [e["cx_norm"] for e in entrances],
        },
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(f"{DATA_DIR}/tile_x3400_y6201.json") as f:
        tile = json.load(f)

    with open(f"{DATA_DIR}/building_footprints_expanded.json") as f:
        blds = json.load(f)

    bld_ids = set(blds.keys())

    # Select buildings with good Mapillary coverage
    candidates = []
    for w in tile["waypoints"]:
        bid = w.get("overture_building_id")
        if bid and bid in bld_ids and w.get("mapillary_ids") and len(w["mapillary_ids"]) >= 3:
            candidates.append(w)

    candidates.sort(key=lambda x: -len(x["mapillary_ids"]))
    print(f"Candidates: {len(candidates)} buildings with 3+ images")

    # Process top 10
    all_results = []
    for wp in candidates[:10]:
        bid = wp["overture_building_id"]
        bld = blds[bid]
        height = bld.get("height")
        if height is None and bld.get("num_floors"):
            height = bld["num_floors"] * 3.5
        if height is None:
            height = 7.0

        # Building centroid
        coords = bld["coordinates"]
        n = len(coords)
        if coords[0] == coords[-1]:
            n -= 1
        blat = sum(c[0] for c in coords[:n]) / n
        blon = sum(c[1] for c in coords[:n]) / n

        result = process_building(
            bid,
            wp["mapillary_ids"],
            building_lat=blat,
            building_lon=blon,
            building_height=height,
            poi_name=wp["name"],
        )
        if result:
            all_results.append(result)

    # Save results
    with open(f"{OUTPUT_DIR}/facade_analysis.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Successfully processed: {len(all_results)} / 10 buildings")
    total_windows = sum(r["windows"]["count"] for r in all_results)
    total_entrances = sum(r["entrances"]["count"] for r in all_results)
    print(f"Total windows detected: {total_windows}")
    print(f"Total entrances detected: {total_entrances}")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
