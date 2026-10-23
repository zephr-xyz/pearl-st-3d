#!/usr/bin/env python3
"""Download the Mapillary reference photos of Pearl St into reference/ (git-ignored).

  tools/fetch_reference_photos.py            # every id in data/mapillary_image_ids.json
  tools/fetch_reference_photos.py --ids 123,456

Writes reference/<image id>.jpg (the 2048 px thumbnail) and reference/index.json with the
capture time and compass heading of each, so the reference envelope (tools/imgstats.py) can be
split by season or time of day. The photos are third-party material used only to judge
renders; they are never loaded by the viewer. The access token comes from MLY_TOKEN, or from
scripts/fetch_mapillary.py where the project keeps it.
"""
import argparse, datetime, json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reference")


def token():
    t = os.environ.get("MLY_TOKEN")
    if t:
        return t
    src = open(os.path.join(ROOT, "scripts", "fetch_mapillary.py")).read()
    m = re.search(r"MLY\|[^\"']+", src)
    if not m:
        sys.exit("no Mapillary token: set MLY_TOKEN")
    return m.group(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", default="", help="comma-separated image ids (default: data/mapillary_image_ids.json)")
    a = ap.parse_args()
    ids = [i for i in a.ids.split(",") if i] or json.load(open(os.path.join(ROOT, "data", "mapillary_image_ids.json")))
    os.makedirs(OUT, exist_ok=True)
    index_path = os.path.join(OUT, "index.json")
    index = json.load(open(index_path)) if os.path.exists(index_path) else {}
    tok = urllib.parse.quote(token())
    n_new = 0
    for i in ids:
        path = os.path.join(OUT, f"{i}.jpg")
        if os.path.exists(path) and i in index:
            continue
        url = f"https://graph.mapillary.com/{i}?fields=id,captured_at,compass_angle,thumb_2048_url,width,height,camera_type&access_token={tok}"
        try:
            j = json.load(urllib.request.urlopen(url, timeout=30))
            if not os.path.exists(path):
                with urllib.request.urlopen(j["thumb_2048_url"], timeout=60) as r, open(path, "wb") as f:
                    f.write(r.read())
            d = datetime.datetime.utcfromtimestamp(j["captured_at"] / 1000)
            index[i] = {"captured_utc": d.strftime("%Y-%m-%d %H:%M"), "month": d.month, "hour_utc": d.hour,
                        "heading": round(j.get("compass_angle", -1)), "width": j.get("width"), "height": j.get("height"),
                        "camera_type": j.get("camera_type")}
            n_new += 1
            print(f"{i}: {index[i]['captured_utc']} heading {index[i]['heading']}")
        except Exception as e:
            print(f"{i}: failed: {str(e)[:100]}", file=sys.stderr)
        time.sleep(0.2)
    json.dump(index, open(index_path, "w"), indent=1, sort_keys=True)
    print(f"{len(index)} photos indexed in {OUT} ({n_new} new)")


if __name__ == "__main__":
    main()
