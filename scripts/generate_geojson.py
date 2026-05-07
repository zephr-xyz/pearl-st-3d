#!/usr/bin/env python3
"""
Generate GeoJSON files from scene.json for MapLibre GL rendering.
Converts meter-based scene coordinates back to lat/lon for map display.
"""
import json
import math

OUTPUT_DIR = "/private/tmp/pearl-st-3d/viewer"

METERS_PER_DEG_LAT = 111320.0


def m_lng_at(lat):
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def meters_to_latlon(x, z, ref_lat, ref_lon):
    """Convert scene meters (x=east, z=north) to lat/lon."""
    m_lon = m_lng_at(ref_lat)
    lon = x / m_lon + ref_lon
    lat = z / METERS_PER_DEG_LAT + ref_lat
    return [lon, lat]


def main():
    with open(f"{OUTPUT_DIR}/scene.json") as f:
        scene = json.load(f)

    ref_lat = scene["ref_lat"]
    ref_lon = scene["ref_lon"]

    # --- Buildings GeoJSON ---
    bld_features = []
    for bld in scene["buildings"]:
        coords_lonlat = [meters_to_latlon(pt[0], pt[1], ref_lat, ref_lon)
                         for pt in bld["footprint_m"]]
        # Close the polygon
        if coords_lonlat[0] != coords_lonlat[-1]:
            coords_lonlat.append(coords_lonlat[0])

        style = bld.get("style", {})
        pois = bld.get("pois", [])

        feature = {
            "type": "Feature",
            "properties": {
                "id": bld["id"],
                "height": bld["height"],
                "color": style.get("color", "#8B6B4A"),
                "material": style.get("material", "brick"),
                "stories": style.get("stories", 2),
                "pois": ", ".join(pois[:3]) if pois else "",
                "source": style.get("source", "heuristic"),
                "has_awning": 1 if style.get("awning") else 0,
                "window_style": style.get("windows", "traditional"),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_lonlat],
            },
        }
        bld_features.append(feature)

    buildings_geojson = {
        "type": "FeatureCollection",
        "features": bld_features,
    }

    with open(f"{OUTPUT_DIR}/buildings.geojson", "w") as f:
        json.dump(buildings_geojson, f)

    # --- Trees GeoJSON ---
    tree_features = []
    for tree in scene.get("trees", []):
        lonlat = meters_to_latlon(tree["x"], tree["y"], ref_lat, ref_lon)
        tree_features.append({
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": lonlat},
        })

    with open(f"{OUTPUT_DIR}/trees.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": tree_features}, f)

    # --- Signs GeoJSON (from signs.json) ---
    with open(f"{OUTPUT_DIR}/signs.json") as f:
        signs = json.load(f)

    sign_features = []
    for sign in signs:
        if not sign.get("name"):
            continue
        sign_features.append({
            "type": "Feature",
            "properties": {
                "name": sign["name"],
                "building_id": sign["building_id"],
            },
            "geometry": {
                "type": "Point",
                "coordinates": [sign["lon"], sign["lat"]],
            },
        })

    with open(f"{OUTPUT_DIR}/signs.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": sign_features}, f)

    # --- Roads GeoJSON ---
    road_features = []
    for road in scene.get("roads", []):
        coords = [meters_to_latlon(pt[0], pt[1], ref_lat, ref_lon)
                  for pt in road["points"]]
        road_features.append({
            "type": "Feature",
            "properties": {
                "name": road.get("name", ""),
                "class": road.get("class", ""),
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    with open(f"{OUTPUT_DIR}/roads.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": road_features}, f)

    print(f"Generated GeoJSON:")
    print(f"  buildings.geojson: {len(bld_features)} features")
    print(f"  trees.geojson: {len(tree_features)} features")
    print(f"  signs.geojson: {len(sign_features)} features")
    print(f"  roads.geojson: {len(road_features)} features")


if __name__ == "__main__":
    main()
