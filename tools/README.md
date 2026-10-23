# Measurement tools

Everything here exists so a change to the viewer can be judged with numbers against photographs
of the real street, and so two commits can be compared on identical frames. No tool here is
needed to run the viewer.

## Viewer hooks (viewer/index.html)

| URL parameter | Meaning |
|---|---|
| `view=<name>` | a standard view: `orbit` (the page default), `birds`, `street`, `mall_e` (on the mall near 13th looking east), `mall_mid_e` (near 14th looking east), `mall_w` (near 15th looking west) |
| `view=px,py,pz,tx,ty,tz` | a free camera in scene metres (x east, z north, y up) |
| `facade=<building id prefix>[,distance]` | stand across the street from that building's primary wall at eye height, e.g. `facade=f61c4184` (Odd Fellows), `facade=9022e165` (Boulder Theater) |
| `fov=<deg>` | vertical field of view (default 45) |
| `mode=textured\|color\|wireframe` | render mode |
| `capture=1` | no interface, no eased camera, loading overlay removed at once |
| `seed=<text>` | the world seed (default `pearl`); all painted variation is a hash of the seed and what it decorates, never `Math.random` |
| `lit=0` | the old lighting (three fixed lights, canvas sky, ACES) instead of the Boulder sun, physical sky, cascaded shadow and AgX |
| `mat=0` | the old painted canvas walls and flat ground instead of the baked surfaces and 3D facades |
| `post=0` | no camera post (HDR target, sharpening, bloom, vignette, grain) |
| `content=0` | the old blob trees instead of the grown trees (3DSceneRenderer's vegetation module) and tree grates |
| `date=MM-DD`, `tod=<hour>` | sun date and local decimal hour (default April 17, 16.75: the April photo series) |
| `expo=`, `envi=`, `suni=`, `haze=` | multipliers and values for exposure, sky-light intensity (default 0.2), sun intensity and haze density, for attribution runs |
| `bloom=`, `grain=`, `sharp=`, `vig=` | post strengths |
| `q=low\|med\|high` | shadow map size per cascade (1024, 2048, 4096) |

`window.__ready` is set once frames are being drawn. `window.__app.stats()` returns frame time
(median and p95 ms), draw calls, triangles, geometries, textures, programs and the camera.

## tools/shoot.py: headless GPU screenshots

```sh
python3 tools/shoot.py --views orbit,mall_e,mall_mid_e,mall_w,birds       # .work/shots/<view>.png
python3 tools/shoot.py --params "facade=f61c4184" --out .work/shots/oddfellows.png
python3 tools/shoot.py --views mall_e --eval "JSON.stringify(window.__app.stats())"
```

Starts a private static server on `viewer/`, launches Chrome headless on the GPU (Metal on a
Mac), opens the page with `capture=1`, waits for `window.__ready`, settles 1.5 s, saves a PNG and
prints the app's `stats:` line and any console errors. Needs Google Chrome (found at its
standard Mac path, or `SHOOT_CHROME=/path`). Exit codes: 0 done, 1 never ready, 2 Chrome did
not start, 3 console errors.

## tools/standard_views.sh: the fixed set

Runs every standard view into one directory, so each commit is captured the same way:

```sh
tools/standard_views.sh .work/shots/$(git rev-parse --short HEAD)
```

## tools/fetch_reference_photos.py: the reference set

Downloads the Mapillary photos listed in `data/mapillary_image_ids.json` into `reference/`
(git-ignored) with an index of capture time and heading. The token is read from `MLY_TOKEN` or
from `scripts/fetch_mapillary.py`.

## tools/imgstats.py: numbers against the photos

```sh
python3 tools/imgstats.py stats .work/shots/*.png --ref reference/*.jpg
python3 tools/imgstats.py stats reference/*.jpg --json > docs/reference_envelope.json
python3 tools/imgstats.py sheet a.png b.png --out ab.jpg --labels L,R
```

Full-frame metrics on every image resized to 1000 px wide: mean and percentile luma, black and
clipped shares, colourfulness, saturation, R/B, block texture and fine detail. With `--ref`
every render metric is flagged LOW or HIGH when it falls outside the photos' range. The metric
definitions are unchanged from the 3DSceneRenderer project (MIT), so its published
reference envelope for a sunny Mediterranean street can be compared directly.
