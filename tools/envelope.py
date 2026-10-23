#!/usr/bin/env python3
"""Build the reference envelope: the numeric range of the real street's photographs.

  tools/envelope.py                       # reference/*.jpg -> docs/reference_envelope.json + table
  tools/envelope.py --all                 # no exclusions

Runs tools/imgstats.py over reference/ and keeps the photos that can serve as a target for a
daylight render. Excluded, with the reason recorded in the JSON:
  soft     hp1 < 2.5           out of focus or heavily compressed
  blown    clip% > 6           snow scenes and over-exposed frames
  blue     R/B < 0.7           blue hour or a strong cast
The envelope is the min, p10, median, p90 and max of every full-frame metric over the kept
photos, overall and split by local hour (noon 11-14, afternoon 15-19), using reference/index.json
for the capture time (UTC-7). Renders are then judged with
  python3 tools/imgstats.py stats <renders> --ref <kept photos>
"""
import argparse, json, os, subprocess, sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "reference")
DOCS = os.path.join(ROOT, "docs")
KEYS = ["mean", "p2", "p10", "p50", "p90", "p98", "black%", "clip%", "colourf", "sat", "R/B", "blk16", "hp1"]


def reason(f):
    if f["hp1"] < 2.5:
        return "soft"
    if f["clip%"] > 6:
        return "blown"
    if f["R/B"] < 0.7:
        return "blue"
    return None


def summarise(rows):
    out = {}
    for k in KEYS:
        v = np.array([r[k] for r in rows])
        out[k] = {"min": float(v.min()), "p10": float(np.percentile(v, 10)), "median": float(np.median(v)),
                  "p90": float(np.percentile(v, 90)), "max": float(v.max())}
    return out


def table(name, s, n):
    print(f"\n{name} ({n} photos)")
    print(f"{'metric':<8} {'min':>7} {'p10':>7} {'median':>7} {'p90':>7} {'max':>7}")
    for k in KEYS:
        r = s[k]
        f = (lambda x: f"{x:.3f}") if abs(r["max"]) < 2 else (lambda x: f"{x:.1f}")
        print(f"{k:<8} {f(r['min']):>7} {f(r['p10']):>7} {f(r['median']):>7} {f(r['p90']):>7} {f(r['max']):>7}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="keep every photo")
    ap.add_argument("--out", default=os.path.join(DOCS, "reference_envelope.json"))
    a = ap.parse_args()
    photos = sorted(f for f in os.listdir(REF) if f.lower().endswith(".jpg"))
    if not photos:
        sys.exit("no photos in reference/: run tools/fetch_reference_photos.py")
    index = json.load(open(os.path.join(REF, "index.json"))) if os.path.exists(os.path.join(REF, "index.json")) else {}
    js = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "imgstats.py"), "stats", "--json",
                         *[os.path.join(REF, p) for p in photos]], capture_output=True, text=True, check=True).stdout
    stats = json.loads(js)["renders"]
    kept, excluded = [], {}
    for s in stats:
        pid = os.path.splitext(os.path.basename(s["file"]))[0]
        full = s["full"]
        meta = index.get(pid, {})
        hour = (meta.get("hour_utc", 12) - 7) % 24 if meta else None
        row = dict(full, id=pid, hour_local=hour, month=meta.get("month"), heading=meta.get("heading"))
        r = None if a.all else reason(full)
        if r:
            excluded[pid] = r
        else:
            kept.append(row)
    noon = [r for r in kept if r["hour_local"] is not None and 11 <= r["hour_local"] <= 14]
    pm = [r for r in kept if r["hour_local"] is not None and 15 <= r["hour_local"] <= 19]
    env = {"source": "Mapillary photos of Pearl St, Boulder (reference/, ids in data/mapillary_image_ids.json)",
           "rule": "excluded: hp1 < 2.5 (soft), clip% > 6 (blown), R/B < 0.7 (blue)",
           "kept": len(kept), "excluded": excluded, "overall": summarise(kept),
           "noon_11_14": summarise(noon) if noon else None, "afternoon_15_19": summarise(pm) if pm else None,
           "photos": {r["id"]: {k: r[k] for k in KEYS + ["hour_local", "month", "heading"]} for r in kept},
           "kept_files": [os.path.join("reference", r["id"] + ".jpg") for r in kept]}
    os.makedirs(DOCS, exist_ok=True)
    json.dump(env, open(a.out, "w"), indent=1, default=float)
    print(f"kept {len(kept)} of {len(stats)}; excluded: " + ", ".join(f"{k} ({v})" for k, v in sorted(excluded.items())))
    table("overall", env["overall"], len(kept))
    if noon:
        table("noon 11-14 local", env["noon_11_14"], len(noon))
    if pm:
        table("afternoon 15-19 local", env["afternoon_15_19"], len(pm))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
