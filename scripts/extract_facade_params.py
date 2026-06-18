#!/usr/bin/env python3
"""
Extract structured facade parameters from visual descriptions and Mapillary images.
Uses the cross-view embedding visual_description (VLM-generated) to parameterize
the procedural renderer with accurate: materials, colors, window grids, entrances.

Also queries Mapillary for a front-facing image and uses CV to validate/refine
window counts from the image.
"""
import json
import math
import os
import re
import urllib.request
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

DATA_DIR = "/private/tmp/pearl-st-3d/data"
OUTPUT_DIR = "/private/tmp/pearl-st-3d/data/facades"
MLY_TOKEN = "MLY|25675740422105056|2acdd632c97850971361fc937b420bd4"
METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


# --- Material/Color extraction from visual descriptions ---

MATERIAL_PATTERNS = {
    "brick": [r"red brick", r"dark brick", r"brown brick", r"brick"],
    "painted_brick": [r"painted brick", r"white brick"],
    "stone": [r"sandstone", r"rough-hewn stone", r"limestone", r"stone"],
    "stucco": [r"stucco", r"plaster"],
    "concrete": [r"concrete", r"cement"],
    "glass": [r"glass facade", r"curtain wall", r"full glass"],
    "metal": [r"metal panel", r"metal cladding", r"corrugated"],
    "wood": [r"wood siding", r"cedar", r"wood panel"],
}

COLOR_MAP = {
    "red brick": "#8B4513",
    "dark brick": "#4a3728",
    "dark brown brick": "#4a3728",
    "brown brick": "#6b5b4a",
    "brick": "#8B5C3A",
    "painted brick": "#c8bfb0",
    "white brick": "#e8e4e0",
    "sandstone": "#d4b896",
    "rough-hewn stone": "#9e8b7a",
    "limestone": "#d4c5a9",
    "stone": "#b0a090",
    "stucco": "#c8bfb0",
    "tan stucco": "#c4a882",
    "white stucco": "#f0ece8",
    "concrete": "#a0a0a0",
    "tan concrete": "#c4b8a0",
}

WINDOW_PATTERNS = {
    "large_plate_glass": [r"large glass.*window", r"plate glass", r"large.*storefront window"],
    "storefront_glass": [r"storefront.*glass", r"glass storefront", r"display window"],
    "arched": [r"arched.*window", r"romanesque.*arch"],
    "traditional": [r"double-hung", r"traditional.*window", r"white-trimmed window"],
    "tall_narrow": [r"tall.*narrow.*window", r"vertical.*window"],
    "bay": [r"bay window"],
    "industrial": [r"industrial.*window", r"multi-pane.*window"],
}

ENTRANCE_PATTERNS = [
    r"recessed.*(?:door|entrance|entry)",
    r"glass.*(?:door|entrance|entry)",
    r"double door",
    r"arched.*(?:door|entrance|entryway)",
    r"(?:door|entrance|entry).*(?:left|right|center|central)",
]


def extract_material(desc):
    """Extract primary facade material from description."""
    desc_lower = desc.lower()
    for material, patterns in MATERIAL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, desc_lower):
                return material
    return "brick"


def extract_color(desc):
    """Extract facade color from description."""
    desc_lower = desc.lower()
    for color_phrase, hex_color in COLOR_MAP.items():
        if color_phrase in desc_lower:
            return hex_color

    # Try generic color words
    color_words = {
        "red": "#8B4513", "brown": "#6b5b4a", "tan": "#c4a882",
        "gray": "#808080", "grey": "#808080", "white": "#f0ece8",
        "dark": "#4a3728", "cream": "#f5f0e0", "beige": "#c8bfb0",
        "green": "#5a7a5a", "blue": "#4a6a8a",
    }
    for word, hex_color in color_words.items():
        if word in desc_lower:
            return hex_color

    return "#8B6B4A"


def extract_window_style(desc):
    """Extract window style from description."""
    desc_lower = desc.lower()
    for style, patterns in WINDOW_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, desc_lower):
                return style
    return "traditional"


def extract_stories(desc, building_height):
    """Extract number of stories from description."""
    desc_lower = desc.lower()

    # Direct mentions
    story_patterns = [
        (r"(?:single|one)[- ]stor(?:y|ey|ied)", 1),
        (r"(?:two|2)[- ]stor(?:y|ey|ied)", 2),
        (r"(?:three|3)[- ]stor(?:y|ey|ied)", 3),
        (r"(?:four|4)[- ]stor(?:y|ey|ied)", 4),
    ]
    for pat, n in story_patterns:
        if re.search(pat, desc_lower):
            return n

    # Indirect mentions
    if "upper floor" in desc_lower or "second floor" in desc_lower:
        return 2
    if "third floor" in desc_lower:
        return 3

    # From building height
    if building_height:
        return max(1, round(building_height / 3.5))

    return 2


def extract_entrance_info(desc):
    """Extract entrance details from description."""
    desc_lower = desc.lower()
    info = {"count": 1, "style": "standard", "position": 0.5}

    # Multiple entrances
    if re.search(r"double door|two door|multiple entrance", desc_lower):
        info["count"] = 2

    # Entrance style
    if "recessed" in desc_lower:
        info["style"] = "recessed"
    elif "arched" in desc_lower:
        info["style"] = "arched"
    elif "glass door" in desc_lower:
        info["style"] = "glass"

    # Position hints
    if re.search(r"entrance.*left|left.*entrance|door.*left|left.*door", desc_lower):
        info["position"] = 0.3
    elif re.search(r"entrance.*right|right.*entrance|door.*right|right.*door", desc_lower):
        info["position"] = 0.7
    elif re.search(r"entrance.*center|central.*entrance|center.*door", desc_lower):
        info["position"] = 0.5

    return info


def extract_accent_color(desc):
    """Extract accent/trim color from description."""
    desc_lower = desc.lower()
    patterns = {
        "#ffffff": [r"white.*trim", r"white.*frame", r"white.*cornice"],
        "#1a237e": [r"blue.*trim", r"navy.*frame", r"blue.*awning"],
        "#2a5a2a": [r"green.*awning", r"green.*trim"],
        "#cc2222": [r"red.*awning", r"red.*trim", r"red.*door"],
        "#ccaa00": [r"gold.*trim", r"gold.*accent", r"brass"],
        "#4a4a4a": [r"black.*metal", r"dark.*metal", r"iron"],
        "#808080": [r"gray.*trim", r"grey.*frame", r"silver"],
    }
    for hex_color, pats in patterns.items():
        for pat in pats:
            if re.search(pat, desc_lower):
                return hex_color
    return "#d4c5a9"


_AWNING_COLORS = [
    ("yellow",     "#ccaa00"),
    ("gold",       "#ccaa00"),
    ("dark brown", "#3a1a0a"),
    ("dark metal", "#333333"),
    ("dark grey",  "#333333"),
    ("dark gray",  "#333333"),
    ("dark blue",  "#1a237e"),
    ("brown",      "#5c3a1a"),
    ("grey",       "#555555"),
    ("gray",       "#555555"),
    ("teal",       "#1a7a6a"),
    ("sage",       "#5a7a5a"),
    ("purple",     "#6a2a7a"),
    ("maroon",     "#6b1a1a"),
    ("burgundy",   "#6b1a1a"),
    ("navy",       "#1a237e"),
    ("blue",       "#1a3a6a"),
    ("green",      "#2a6a2a"),
    ("red",        "#cc2222"),
    ("black",      "#2a2a2a"),
    ("white",      "#e0e0e0"),
    ("cream",      "#d4c8a0"),
    ("orange",     "#cc6622"),
    ("dark",       "#333333"),
]
_AWNING_PROX = 50  # max chars between color word and awning/canopy


def extract_awning(desc):
    """Extract awning info from description."""
    dl = desc.lower()
    if "awning" not in dl and "canopy" not in dl:
        return None

    awning = {"style": "flat", "color": "#3a3a3a"}

    # Stripe style: only when "striped" appears near awning/canopy (not elsewhere on facade)
    stripe_pat = (rf"(?:stripe|striped)[^.]{{0,{_AWNING_PROX}}}(?:awning|canopy)"
                  rf"|(?:awning|canopy)[^.]{{0,{_AWNING_PROX}}}(?:stripe|striped)")
    if re.search(stripe_pat, dl):
        awning["style"] = "striped"
    elif re.search(r"\bslop|angled|slanted", dl):
        awning["style"] = "slope"

    # Color — [^.] blocks cross-sentence matches; most-specific phrases first
    for word, color in _AWNING_COLORS:
        pat = (rf"(?:{re.escape(word)}[^.]{{0,{_AWNING_PROX}}}(?:awning|canopy)"
               rf"|(?:awning|canopy)[^.]{{0,{_AWNING_PROX}}}{re.escape(word)})")
        if re.search(pat, dl):
            awning["color"] = color
            break

    if awning["style"] == "striped":
        awning["stripe_color"] = "rgba(255,255,255,0.45)"

    return awning


def extract_architectural_details(desc):
    """Extract notable architectural features."""
    desc_lower = desc.lower()
    details = []

    if re.search(r"cornice|dentil", desc_lower):
        details.append("cornice")
    if re.search(r"pediment|parapet", desc_lower):
        details.append("pediment")
    if re.search(r"column|pilaster", desc_lower):
        details.append("columns")
    if re.search(r"balcony|balconette", desc_lower):
        details.append("balcony")
    if re.search(r"mural|art.*wall|painted.*mural", desc_lower):
        details.append("mural")
    if re.search(r"victorian|ornate", desc_lower):
        details.append("ornate")

    return details


def parse_visual_description(desc, building_height=None):
    """Parse a visual description into structured facade parameters."""
    if not desc:
        return None

    return {
        "material": extract_material(desc),
        "color": extract_color(desc),
        "accent": extract_accent_color(desc),
        "window_style": extract_window_style(desc),
        "stories": extract_stories(desc, building_height),
        "entrance": extract_entrance_info(desc),
        "awning": extract_awning(desc),
        "details": extract_architectural_details(desc),
    }


# --- Window count validation from Mapillary image ---

def angle_diff(a, b):
    return (a - b + 180) % 360 - 180


def bearing_to(from_lat, from_lon, to_lat, to_lon):
    dlat = to_lat - from_lat
    dlon = (to_lon - from_lon) * math.cos(math.radians(from_lat))
    return math.degrees(math.atan2(dlon, dlat)) % 360


def select_front_image(image_ids, bld_lat, bld_lon, max_check=6):
    """Find image most directly facing building."""
    best = None
    best_score = float('inf')

    for img_id in image_ids[:max_check]:
        try:
            url = (f"https://graph.mapillary.com/{img_id}?access_token={MLY_TOKEN}"
                   f"&fields=thumb_2048_url,computed_geometry,computed_compass_angle")
            resp = urllib.request.urlopen(urllib.request.Request(url), timeout=10)
            meta = json.loads(resp.read())
        except Exception:
            continue

        geom = meta.get("computed_geometry", {})
        coords = geom.get("coordinates")
        if not coords:
            continue

        cam_lon, cam_lat = coords
        heading = meta.get("computed_compass_angle", 0)
        thumb_url = meta.get("thumb_2048_url")
        if not thumb_url:
            continue

        to_bld = bearing_to(cam_lat, cam_lon, bld_lat, bld_lon)
        face_angle = abs(angle_diff(heading, to_bld))

        dx = (bld_lon - cam_lon) * m_lng_at(cam_lat)
        dy = (bld_lat - cam_lat) * METERS_PER_DEG_LAT
        dist = math.sqrt(dx * dx + dy * dy)

        if face_angle > 45:
            continue

        score = face_angle / 45 + abs(dist - 18) / 30
        if score < best_score:
            best_score = score
            best = {"img_id": img_id, "thumb_url": thumb_url, "dist": dist,
                    "face_angle": face_angle, "heading": heading}

    return best


def count_windows_cv(img_pil, stories, building_height):
    """Use CV to count visible windows in a facade image."""
    img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    h, w = img_cv.shape[:2]

    # Crop to central facade area
    crop = img_cv[int(h * 0.1):int(h * 0.85), int(w * 0.2):int(w * 0.8)]
    ch, cw = crop.shape[:2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Multi-scale window detection
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)

    # Canny edges
    edges = cv2.Canny(blurred, 30, 100)

    # Find rectangular structures
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(edges, kernel, iterations=2)
    closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Expected window size given building stories and image coverage
    expected_win_h = ch / (stories * 2.5) if stories else ch / 5
    min_win_h = expected_win_h * 0.3
    max_win_h = expected_win_h * 3

    windows = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh

        if bh < min_win_h or bh > max_win_h:
            continue
        if bw < min_win_h * 0.4 or bw > max_win_h * 2:
            continue

        aspect = bw / bh if bh > 0 else 0
        if aspect < 0.3 or aspect > 3:
            continue

        # Rectangularity check
        cnt_area = cv2.contourArea(cnt)
        if cnt_area < area * 0.4:
            continue

        windows.append({"x": x, "y": y, "w": bw, "h": bh,
                       "cy": y + bh / 2, "cx": x + bw / 2})

    if not windows:
        return 0, 0

    # Cluster into rows
    windows.sort(key=lambda w: w["cy"])
    rows = [[windows[0]]]
    for win in windows[1:]:
        if abs(win["cy"] - rows[-1][0]["cy"]) < ch * 0.12:
            rows[-1].append(win)
        else:
            rows.append([win])

    n_rows = len(rows)
    n_cols = max(len(r) for r in rows)

    return n_rows, n_cols


def process_all():
    """Process all buildings with visual descriptions."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(f"{DATA_DIR}/tile_x3400_y6201.json") as f:
        tile = json.load(f)
    with open(f"{DATA_DIR}/building_footprints_expanded.json") as f:
        blds = json.load(f)

    bld_ids = set(blds.keys())

    # Collect all POIs on our buildings with visual descriptions
    pois_by_building = {}
    for w in tile["waypoints"]:
        bid = w.get("overture_building_id")
        if bid and bid in bld_ids:
            if bid not in pois_by_building:
                pois_by_building[bid] = []
            pois_by_building[bid].append(w)

    results = []
    processed = 0

    for bid, pois in pois_by_building.items():
        # Use the POI with best visual description
        best_poi = None
        for p in pois:
            if p.get("visual_description"):
                if best_poi is None or len(p["visual_description"]) > len(best_poi.get("visual_description", "")):
                    best_poi = p

        if not best_poi or not best_poi.get("visual_description"):
            continue

        bld = blds[bid]
        height = bld.get("height")
        if height is None and bld.get("num_floors"):
            height = bld["num_floors"] * 3.5
        if height is None:
            height = 7.0

        # Parse visual description
        params = parse_visual_description(best_poi["visual_description"], height)
        if not params:
            continue

        # Building centroid
        coords = bld["coordinates"]
        n = len(coords)
        if coords[0] == coords[-1]:
            n -= 1
        blat = sum(c[0] for c in coords[:n]) / n
        blon = sum(c[1] for c in coords[:n]) / n

        # Try to validate window count from Mapillary image
        window_rows_cv = 0
        window_cols_cv = 0
        image_id = None

        mly_ids = best_poi.get("mapillary_ids", [])
        if mly_ids and processed < 20:  # Limit API calls
            best_img = select_front_image(mly_ids, blat, blon)
            if best_img:
                try:
                    resp = urllib.request.urlopen(best_img["thumb_url"], timeout=15)
                    img = Image.open(BytesIO(resp.read()))
                    window_rows_cv, window_cols_cv = count_windows_cv(
                        img, params["stories"], height)
                    image_id = best_img["img_id"]
                except Exception:
                    pass

        # Combine VLM description params with CV validation
        result = {
            "building_id": bid,
            "poi_name": best_poi["name"],
            "material": params["material"],
            "color": params["color"],
            "accent": params["accent"],
            "window_style": params["window_style"],
            "stories": params["stories"],
            "entrance": params["entrance"],
            "awning": params["awning"],
            "details": params["details"],
            "window_grid": {
                "rows": window_rows_cv if window_rows_cv > 0 else params["stories"],
                "cols": window_cols_cv if window_cols_cv > 0 else 3,
                "source": "cv" if window_rows_cv > 0 else "estimated",
            },
            "image_id": image_id,
            "building_height": height,
        }
        results.append(result)
        processed += 1

        if processed % 10 == 0:
            print(f"  Processed {processed} buildings...")

    # Save
    with open(f"{OUTPUT_DIR}/facade_params.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nExtracted facade parameters for {len(results)} buildings")
    from collections import Counter
    mat_counts = Counter(r['material'] for r in results)
    print(f"  Materials: {dict(mat_counts)}")
    print(f"  With CV window counts: {sum(1 for r in results if r['window_grid']['source'] == 'cv')}")
    print(f"  With awnings: {sum(1 for r in results if r['awning'])}")
    print(f"  Architectural details: {sum(len(r['details']) for r in results)}")

    return results


if __name__ == "__main__":
    results = process_all()
