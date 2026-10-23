# Step 2: the new rendering path

Date: 2026-10-23. Sheets: `docs/step2_views_1.jpg`, `docs/step2_views_2.jpg` (old above, new
below, for all nine standard views). Reproduce with `tools/standard_views.sh` (new) and
`tools/standard_views.sh <dir> "lit=0&mat=0"` (old) on the same commit.

## What was built

- **three r186 vendored** (`viewer/vendor/three/`: build, OrbitControls, SunLight,
  SunLightShadow, Sky), replacing the r164 CDN load. No build step.
- **Materials** (`viewer/src/materials/`): the GPU texture baker and runtime surface patch of
  3DSceneRenderer (MIT) unchanged, with one addition to the shared layout code: a half-unit
  shift of odd courses so a baked stacked bond becomes a running bond at runtime while the
  per-brick tints stay on the bricks. Pearl St recipes in `recipes.js`: `brick` (66.7 mm
  courses, 218 mm bricks, mortar, per-brick firing variation, spalls), `pavers` (200 × 100 mm
  mall pavers), `sandstone` (Lyons stone ashlar, bedding, iron spots), `stucco`, `concrete`
  (1.5 m slabs, broom finish), `asphalt`, plus the shared `detail` and `macro` maps. Library in
  `library.js` with per-brick tints, weathering (ledge dust, run-off streaks from bed joints),
  macro variation, gum and spill spots on the pavers. 163 MB of maps, baked at start-up.
- **Lighting** (`viewer/src/env.js`): NOAA solar position for Boulder at `date=` and `tod=`
  (default April 17, 16:45, the April photo series); the Sky addon as background and, through a
  PMREM, as the image-based light; a SunLight with the r186 two-cascade shadow (2048 px per
  cascade at `q=med`); exponential haze; a sunny-16-style exposure. The sky dome is bright in
  its own units: at intensity 1 it alone put shaded walls at 0.22 linear and swamped the sun,
  which is what the first frame you saw showed. Attribution with `suni=0` and `envi=0` set it
  at 0.17 for the photographs' sun-to-shade ratio.
- **3D facades** (`viewer/src/facades.js`) on the POI and VLM-described buildings: the wall
  shell cut around real openings from the window grid, 0.2 m reveals, sills, lintels, string
  courses, a three-step cornice and a parapet; storefront ground floors with brick piers,
  bulkhead, plate glass, transom and fascia; a recessed entrance at each entrance position with
  a door; glass that reflects the sky dome over a dark interior. One mesh per material per
  building. The OSM residential blocks keep the painted walls, now as decals over the baked
  surfaces (`viewer/src/decal.js`): the canvas paints only openings and trims on a transparent
  background and the brick shows through.
- **Camera post** (`viewer/src/post.js`): HDR target with 4× MSAA, unsharp sharpening in HDR,
  a deep-shadow term, quarter-resolution bloom, AgX, a soft black point, vignette and grain.
- **Ground**: pavers on the pedestrian mall with courses along it, concrete on footways,
  asphalt elsewhere, UVs in world metres.
- A/B switches `lit=0`, `mat=0`, `post=0` and the attribution knobs in `tools/README.md`.

## Measured against the photo envelope (51 Pearl St photos)

| view | old: outside the photos | new: outside the photos |
|---|---|---|
| mall_e | black LOW, clip HIGH, blk16 1.1, hp1 1.6 | clip LOW; blk16 6.0 and hp1 2.8 just under |
| mall_mid_e | sat HIGH, R/B HIGH, blk16 1.8, hp1 2.3 | p2 34.7 just over, clip LOW |
| mall_w | colourf, sat 0.52, R/B 1.35 HIGH, blk16 1.5, hp1 1.4 | none |
| Odd Fellows | sat 0.65, R/B 1.62, colourf HIGH | mean 76 and p50 56 a little low (a fully shaded wall), clip LOW |
| Mountain Sun | clip HIGH, blk16 2.8, hp1 2.0 | clip LOW |
| Boulder Theater | sat 0.50 HIGH, blk16 2.0, hp1 1.7 | bright and flat: mean, p2, p50 HIGH, blk16 4.1 (a sun-facing wall) |
| PosterScene | sat 0.60, R/B 1.42 HIGH, hp1 1.6 | p2 53 HIGH, p98 LOW, clip LOW |
| orbit | mean, p50 HIGH | clip LOW, colourf LOW |
| birds | mean, p2, p50 HIGH | p90, p98 LOW, colourf LOW |

Texture at eye level (blk16) went from 1.1 to 2.8 up to 6.0 to 14.8; fine detail (hp1) from
1.4 to 2.3 up to 2.8 to 6.7; saturation from 0.40 to 0.65 down to 0.20 to 0.40; R/B from 1.22 to
1.62 down to 0.95 to 1.12. Those were the four tells of step 1 and all four now sit in or at
the photo range on the mall and facade views.

What remains outside, and why:

- **No clipping** (clip 0 to 0.7 % against a photo median of 1.35 %). The sky and sunlit
  whites do not burn. The exposure could go up about a third of a stop, but the sun-facing
  walls (Boulder Theater, PosterScene) are already bright and flat. The real fix is contrast
  in the scene: awnings, signs, trees and people put dark and bright things in every photo.
- **Shaded-wall views dark** (Odd Fellows). The deep-shadow term is a compromise between
  that view and the mall views. Photographers expose for the shade; a metered exposure
  (log-average of the frame, as the renderer does) would lift this view without touching the
  others.
- **Aerial views grey** (colourfulness 16 to 19 against 21 min). Roofs and terrain carry no
  colour. No aerial photo is in the envelope, so this is indicative.

## Performance (headless, M2, 1920×1080)

| | old | new |
|---|---|---|
| draw calls, mall_e | 8,537 | about 17,500 (two shadow cascades redraw every caster) |
| triangles | 165 k | 1.4 M |
| frame ms median | 116 | 55 to 70 |
| time to ready | 26 s | 6 to 19 s |

The frame is cheaper despite more triangles because the post chain renders through one HDR
target and the GPU is better used; the call count is the next thing to cut (one mesh per
material per building, then per block).

## Open work

- Batch the facades per material across buildings and cull far ones (draw calls).
- Awnings, signs and lamp posts on the new materials; trees from the renderer's vegetation.
- Arched window heads for the Romanesque fronts; the Art Deco mural as a decal on the
  3D shell (the Boulder Theater currently gets the plain storefront).
- A metered exposure and a time-of-day slider in the interface.
- The residential blocks as merged far-field boxes.
