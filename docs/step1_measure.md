# Step 1: measurement baseline

Date: 2026-10-23. Branch `sean/step1-measure`. Everything here is reproducible from the
repository: `tools/standard_views.sh` captures the views, `tools/envelope.py` builds the photo
envelope, `tools/imgstats.py stats <renders> --ref <photos>` compares them.

## What was built

- **Determinism.** The viewer painted sky clouds, brick and stone shading, stucco grain and sign
  grain with `Math.random` in 13 places, so no two loads matched and no A/B was possible. Every
  draw now comes from a seeded stream named by what it decorates (`sky`, `facade|<building>|<wall>`,
  `sign|<name>`), hashed with a URL `seed=` (default `pearl`). Two loads of one commit are now
  pixel-identical apart from rendering.
- **URL views.** `view=orbit|birds|street|mall_e|mall_mid_e|mall_w`, `view=px,py,pz,tx,ty,tz`,
  `facade=<building id prefix>[,distance]` (stands across the street from the building's
  road-facing wall at 1.7 m eye height), `fov=`, `mode=`, `capture=1` (no interface, no eased
  camera, overlay removed), `seed=`.
- **Hooks.** `window.__ready` after the fifth drawn frame; `window.__app.stats()` with frame time,
  draw calls, triangles, geometries, textures, programs and the camera.
- **Capture.** `tools/shoot.py`: headless Chrome on the Apple GPU through Metal, a private static
  server, an exact 1920×1080 viewport, PNG plus the stats line and console errors. A fresh tab per
  view: a tab reused across scene rebuilds answered in 32 s, then 105 s, then not at all.
- **Reference set.** `tools/fetch_reference_photos.py` fetched all 62 Mapillary photos whose ids
  the project already held into git-ignored `reference/`, with capture time and heading.
- **Envelope.** `tools/envelope.py` keeps the photos that can serve as a daylight target and
  writes `docs/reference_envelope.json`.

## The reference envelope

62 photos, all perspective phone cameras, from 2014 to January 2026. By month: January 10,
February 9, March 7, April 13, May 1, October 17, November 5. No summer photo exists in the set.
By local hour: 11 at noon to 13:00, 5 at 13:00, 14 at 16:00, 14 at 17:00, 8 at 18:00, 5 at 19:00.
The October 2018 series is late afternoon with a low sun; the January 2026 series is noon.

Excluded by rule, 11 photos: 10 soft (hp1 below 2.5, mostly a February 2019 series at 2576 px
that is blurred and snow-blown) and 1 blue (R/B 0.57, a November dusk frame). Kept: 51.

| metric | min | p10 | median | p90 | max |
|---|---|---|---|---|---|
| mean Y′ | 79.5 | 89.1 | 116.3 | 135.3 | 145.3 |
| p2 | 4.1 | 6.6 | 13.5 | 25.7 | 32.0 |
| p10 | 11.2 | 17.0 | 35.8 | 63.6 | 79.2 |
| p50 | 58.7 | 78.8 | 114.7 | 134.1 | 155.3 |
| p90 | 156.2 | 171.6 | 183.4 | 212.0 | 232.1 |
| p98 | 198.0 | 202.7 | 224.6 | 244.8 | 253.1 |
| black % | 0.0 | 0.1 | 1.1 | 3.7 | 8.6 |
| clip % | 0.1 | 0.3 | 0.7 | 2.8 | 5.2 |
| colourfulness | 21.4 | 25.1 | 53.6 | 65.5 | 75.3 |
| saturation | 0.126 | 0.178 | 0.289 | 0.388 | 0.414 |
| R/B | 0.771 | 0.801 | 0.941 | 1.180 | 1.224 |
| blk16 | 6.2 | 9.0 | 11.0 | 16.9 | 28.4 |
| hp1 | 2.9 | 4.4 | 5.6 | 6.6 | 9.0 |

Noon (12 photos) is brighter and less contrasty than the afternoon set (38 photos): mean Y′
median 121.8 against 108.8, p2 median 23.6 against 10.4, black share 0.1 % against 1.8 %. The
JSON holds both splits. For comparison, the 3DSceneRenderer project's sunny Mediterranean
envelope ran p2 3 to 40, clip 0.05 to 11.6 %, saturation 0.22 to 0.52, blk16 18.5 to 42, hp1 6.8
to 16: Pearl St's photos are less contrasty and less textured at 1000 px than that street, so
its targets are its own.

## Baseline renders of the current viewer (commit 45980a0 content, with the hooks above)

Nine standard views at 1920×1080 (contact sheet: `docs/baseline_views.jpg`). Flags are against
the 51-photo overall range.

| view | mean | p2 | p50 | black % | clip % | colourf | sat | R/B | blk16 | hp1 | outside the photos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mall_e | 138.3 | 31.3 | 111.1 | 0.002 | 6.8 | 72.0 | 0.406 | 1.221 | 1.09 | 1.66 | black LOW, clip HIGH, blk16 LOW, hp1 LOW |
| mall_mid_e | 133.4 | 31.6 | 108.6 | 0.107 | 4.2 | 74.1 | 0.419 | 1.238 | 1.80 | 2.3 | sat HIGH, R/B HIGH, blk16 LOW, hp1 LOW |
| mall_w | 116.0 | 28.2 | 90.3 | 0.357 | 0.30 | 81.5 | 0.516 | 1.352 | 1.47 | 1.39 | colourf HIGH, sat HIGH, R/B HIGH, blk16 LOW, hp1 LOW |
| facade oddfellows | 92.6 | 26.3 | 66.9 | 0.000 | 4.5 | 78.5 | 0.650 | 1.627 | 12.0 | 3.2 | black LOW, colourf HIGH, sat HIGH, R/B HIGH |
| facade boulder_theater | 102.3 | 9.3 | 69.4 | 2.7 | 0.11 | 64.7 | 0.502 | 1.133 | 2.0 | 1.69 | clip LOW, sat HIGH, blk16 LOW, hp1 LOW |
| facade posterscene | 93.6 | 20.0 | 70.1 | 0.001 | 0.13 | 77.9 | 0.597 | 1.427 | 11.0 | 1.63 | black LOW, clip LOW, colourf HIGH, sat HIGH, R/B HIGH, hp1 LOW |
| facade mountain_sun | 118.5 | 24.5 | 95.0 | 0.07 | 6.2 | 54.8 | 0.402 | 1.142 | 2.8 | 2.0 | clip HIGH, blk16 LOW, hp1 LOW |
| orbit | 155.1 | 31.4 | 174.5 | 0.44 | 1.9 | 50.2 | 0.261 | 1.069 | 13.2 | 4.6 | mean HIGH, p50 HIGH |
| birds | 152.4 | 43.5 | 168.5 | 0.57 | 0.00 | 29.4 | 0.131 | 1.090 | 15.4 | 3.5 | mean HIGH, p2 HIGH, p50 HIGH, clip LOW |

What the numbers say, in order of how far outside the photos they fall:

1. **No texture.** blk16 at eye level is 1.1 to 2.8 against a photo minimum of 6.2 and median
   11.0; hp1 is 1.4 to 2.3 against a minimum of 2.9 and median 5.6. The painted facades and the
   flat ground carry no mid-scale or fine detail at all. Only the two facade views whose canvas
   brick fills the frame (oddfellows, posterscene) reach the photo range on blk16, and they still
   fail hp1. This is the materials gap: baked brick with joints and per-brick tone, and a paver
   recipe for the mall surface.
2. **Too saturated and too warm.** Saturation 0.40 to 0.65 against a photo maximum of 0.414
   (median 0.289); R/B 1.22 to 1.63 against a maximum of 1.224 (median 0.94). The VLM hex colours
   are applied as flat albedo under warm lights, and there is nothing cool in the frame: the
   photos' sky-lit shade pulls their R/B down. This is the lighting gap (sky-lit shade, a camera
   white balance) as much as a colour gap.
3. **No blacks.** Black share 0.000 to 0.36 % at eye level against a photo median of 1.1 %; p2
   luma 20 to 32 against a median of 13.5. Nothing in the scene is in deep shadow: no reveals, no
   under-awning or under-cornice shade, one coarse shadow map. This is the geometry and shadow gap.
4. **Aerial views too bright.** Orbit and birds sit at mean 152 to 155 and p50 169 to 175
   against photo maxima of 145 and 155. The grey ground plane and pale roofs dominate; there is
   no aerial reference photo, so treat this as indicative.

## Performance baseline (headless, Apple M2, 1920×1080)

| view | draw calls | triangles | geometries | textures | frame ms median | p95 |
|---|---|---|---|---|---|---|
| orbit | 8,335 | 168,686 | 9,309 | 2,154 | 64 | 564 |
| birds | 1,374 | 95,752 | 5,842 | 276 | 48 | 78 |
| mall_e | 8,537 | 165,361 | 10,922 | 2,468 | 116 | 835 |
| mall_mid_e | 7,151 | 151,432 | 10,305 | 2,021 | 102 | 408 |
| mall_w | 3,336 | 124,243 | 6,850 | 616 | 75 | 130 |
| facade oddfellows | 5,802 | 123,314 | 10,693 | 2,483 | 95 | 877 |

Time to ready: 21 to 28 s per view. Milliseconds in headless Chrome are indicative only; the
structural counts are the reliable signal. The scene is draw-call bound, not triangle bound:
8,000 to 8,500 draw calls for 170 k triangles, one mesh and one canvas texture per wall plus
one mesh per cornice band, bench slat and lamp part. The renderer's budget for a far heavier
scene was 1,500 calls. Any geometry work in step 3 has to batch per material, which the
renderer's shared-batch pattern does.

## Caveats

- The photos are winter, spring and autumn, phone cameras, many at a low October sun. No summer
  set exists on Mapillary for these ids. Targets for a midday summer render should lean on the
  noon split (January 2026) for tone and on the afternoon split for shadow depth.
- Compositions differ: the photos are mostly facade-on from the sidewalk; the standard views
  include two aerials with no photographic counterpart.
- Headless frame times on a laptop GPU are not the deployed experience; count calls and
  triangles when comparing commits, and time only on a quiet machine.
- The facade views depend on the viewer's road-facing primary wall choice; where that picks a
  side wall the view stands at the wrong face. Check the contact sheet when adding a building.

## Standard views for every later commit

```sh
tools/standard_views.sh .work/shots/$(git rev-parse --short HEAD)
python3 tools/imgstats.py stats .work/shots/<commit>/*.png --ref $(python3 -c "import json; print(' '.join(json.load(open('docs/reference_envelope.json'))['kept_files']))")
```

Accept a change when it moves a flagged metric toward the photo range on the eye-level views
without pushing another one out, and confirm with a blind side-by-side of the two commits
(`tools/imgstats.py sheet`).
