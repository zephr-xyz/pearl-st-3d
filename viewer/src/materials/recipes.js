// Pearl St bake recipes: the surfaces of a Victorian and early-20th-century commercial brick
// street in Boulder. Each recipe is a GLSL `surface(m, s)` evaluated per texel in tile metres
// (see glsl/common.js NOISE_GLSL for the noise library and the row-layout `Cell`).
//
// Layouts carry `shift: 'half'`: the runtime shifts every odd course by half a unit, so the
// baked stacked bond becomes a running bond and the per-brick tints stay on the bricks.
//
// `detail` and `macro` are taken unchanged from 3DSceneRenderer (recipes/stone.js, MIT): the
// shared fine mineral grain and the macro variation noise the runtime patch samples.

export const detail = {
  name: 'detail', flat: [1, 1, 1, 0.8], size: 512, tile: [0.5, 0.5], ss: 2, aniso: 4,
  pass: { normal: 1.0, ao: 0.0, cavity: 0.0 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  float g = fbm(m, 60.0, 4, 0.55, 3u);
  vec4 v = voro(m, vec2(260.0), 4u, 1.0);
  float grain = v.z;
  vec4 pk = voro(m, vec2(110.0), 5u, 1.0);
  float pit = smoothstep(0.42, 0.1, pk.x) * step(0.55, pk.z);
  s.height = g * 0.0005 + (v.x - 0.5) * 0.00018 - smoothstep(0.18, 0.05, v.x) * step(0.9, grain) * 0.0005 - pit * 0.0004;
  float a = 0.5 + 0.18 * (grain - 0.5) + 0.12 * g;
  a -= smoothstep(0.18, 0.05, v.x) * step(0.9, grain) * 0.18 + pit * 0.05;
  s.ao = clamp(a, 0.0, 1.0);
  s.albedo = vec3(1.0);
  s.rough = 0.8;
}
`,
};

export const macro = {
  name: 'macro', size: 256, tile: [1, 1], raw: true,
  glsl: /* glsl */ `
vec4 rawSurface(vec2 m) {
  float r = fbm(m, 3.0, 5, 0.55, 41u);
  float g = fbm(warp(m, 2.0, 0.08, 42u), 4.0, 5, 0.6, 43u);
  float b = fbm(warp(m, 3.0, 0.12, 44u), 5.0, 6, 0.62, 45u);
  float a = fbm(m, 9.0, 4, 0.5, 46u);
  return vec4(r, g, b, a) * 0.5 + 0.5;
}
`,
};

// Common red clay brick in running bond: courses of 66.7 mm (a 2 1/4" brick on a 3/8" bed
// joint), bricks 218 mm long, 9-11 mm grey sand-lime mortar struck 2-3 mm back. Every brick
// is its own firing: value ±10 %, a tenth over-burnt (dark purple-brown), a tenth under-burnt
// (pale orange), a firing cloud across the face, sand pits, and a few spalled faces. 2.4 m
// tile at 1.2 mm per texel. Mean linear albedo about (0.32, 0.18, 0.15) with the mortar.
export const brick = {
  name: 'brick', flat: [0.32, 0.18, 0.15, 0.85], size: 2048, tile: [2.4, 2.4], ss: 2,
  layout: { rowH: 2.4 / 36, rows: 36, seg: [11, 11], jitter: 0.06, seed: 31, shift: 'half' },
  joint: 0.005,
  pass: { normal: 1.0, ao: 0.5, aoRadius: 0.006, cavity: 0.06 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  Cell c = rowsCell(m);
  vec2 ms = m + vec2(c.h * 23.1, cellRand(c, 30u) * 17.3);     // this brick's own noise space
  // mortar joint: 9-11 mm, the same width on both sides (a function of the tile position)
  float JW = 0.0045 + 0.0012 * noiseM(m, vec2(6.0), 40u);
  float wob = fbm(m, 30.0, 2, 0.5, 11u) * 0.0004;
  float e = c.e + wob;
  float t = clamp((e - JW) / 0.0025, 0.0, 1.0);                // 2.5 mm arris rounding
  float stone = smoothstep(JW - 0.0005, JW + 0.0005, e);
  // face: bowed and tilted a little per brick, sand-textured, some pits
  float face = (cellRand(c, 1u) - 0.5) * 0.0015
             + dot(c.lp - 0.5 * c.size, vec2(cellRand(c, 7u) - 0.5, cellRand(c, 8u) - 0.5)) * 0.006;
  face += fbm(ms, 60.0, 3, 0.55, 42u) * 0.00025 + fbm(ms, 8.0, 2, 0.5, 43u) * 0.0004;
  vec4 pv = voro(ms, vec2(150.0), 17u, 1.0);
  float pit = smoothstep(0.2, 0.05, pv.x) * step(0.9, pv.z);
  face -= pit * 0.0006;
  // spalled face on one brick in sixteen: a patch broken out 2 mm deep
  float spall = 0.0;
  if (cellRand(c, 38u) < 0.06) {
    vec2 sc = vec2(cellRand(c, 50u), cellRand(c, 51u)) * c.size;
    float R = 0.02 + 0.05 * cellRand(c, 52u);
    float d = length((c.lp - sc) / vec2(1.0, 0.6)) + 0.01 * fbm(ms, 40.0, 2, 0.5, 53u);
    spall = 1.0 - smoothstep(R - 0.004, R + 0.004, d);
  }
  float hFace = face - 0.001 * (1.0 - t) * (1.0 - t) - spall * 0.002;
  float mWash = 0.5 + 0.5 * noiseM(m, vec2(3.0), 41u);
  float hMortar = -0.002 - 0.001 * mWash + fbm(m, 80.0, 2, 0.5, 13u) * 0.0003;
  s.height = mix(hMortar, max(hFace, hMortar), stone);
  // colour
  float hv = cellRand(c, 2u), hk = cellRand(c, 3u);
  vec3 col = vec3(0.30, 0.13, 0.09) * (0.9 + 0.2 * hv);
  col = mix(col, col * vec3(0.55, 0.5, 0.6), step(0.9, hk));      // over-burnt
  col = mix(col, col * vec3(1.15, 1.25, 1.1), step(hk, 0.1));     // under-burnt
  col *= 1.0 + 0.08 * fbm(ms, 12.0, 3, 0.5, 44u) + 0.04 * fbm(ms, 70.0, 2, 0.5, 45u);
  col *= 1.0 + 0.12 * dot(c.lp / c.size - 0.5, vec2(cellRand(c, 9u) - 0.5, cellRand(c, 10u) - 0.5));
  col *= 1.0 - 0.25 * pit;
  col = mix(col, col * vec3(1.1, 1.05, 1.0), spall);
  // dust and a trace of efflorescence worked in along the joints
  float ej = e - JW;
  float dusty = (0.02 + 0.04 * cellRand(c, 33u)) * (1.0 - smoothstep(0.0, 0.015, ej));
  col = mix(col, vec3(lum(col)) * vec3(1.1, 1.05, 0.95), 0.6 * dusty);
  // mortar: grey sand-lime, dirtier in the washed-out stretches
  vec3 mortar = vec3(0.42, 0.40, 0.37) * (1.0 + 0.1 * fbm(m, 50.0, 2, 0.5, 19u)) * (1.0 - 0.2 * smoothstep(0.5, 0.9, mWash));
  s.albedo = mix(mortar, col, stone);
  s.rough = mix(0.95, 0.82 + 0.05 * hv + 0.05 * pit, stone);
}
`,
};

// Brick pavers of the pedestrian mall: 200 × 100 mm clay pavers in running bond, sand joints
// 2-3 mm, trodden satin on the tops, a few replaced (paler or darker) pavers, dirt in the
// joints. 2.4 m tile at 1.2 mm per texel. Mean linear albedo about (0.27, 0.15, 0.11).
export const pavers = {
  name: 'pavers', flat: [0.27, 0.15, 0.11, 0.7], size: 2048, tile: [2.4, 2.4], ss: 2,
  layout: { rowH: 0.1, rows: 24, seg: [12, 12], jitter: 0.04, seed: 47, shift: 'half' },
  joint: 0.0015,
  pass: { normal: 1.0, ao: 0.5, aoRadius: 0.004, cavity: 0.06 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  Cell c = rowsCell(m);
  vec2 ms = m + vec2(c.h * 31.7, cellRand(c, 30u) * 19.3);
  float JW = 0.0012 + 0.0008 * noiseM(m, vec2(8.0), 60u);
  float wob = fbm(m, 40.0, 2, 0.5, 61u) * 0.0003;
  float e = c.e + wob;
  float worn = smoothstep(0.3, 0.8, cellRand(c, 10u));
  float CH = 0.0015 + 0.001 * worn;                            // arris rounding
  float t = clamp((e - JW) / CH, 0.0, 1.0);
  float stone = smoothstep(JW - 0.0004, JW + 0.0004, e);
  float lip = (cellRand(c, 1u) - 0.5) * 0.0015
            + dot(c.lp - 0.5 * c.size, vec2(cellRand(c, 2u) - 0.5, cellRand(c, 3u) - 0.5)) * 0.01;
  float relief = fbm(ms, 40.0, 3, 0.5, 62u) * mix(0.0003, 0.00015, worn);
  float hFace = lip + relief - 0.5 * CH * (1.0 - t) * (1.0 - t);
  float fill = 0.0008 + 0.002 * cellRand(c, 11u);              // sand a little below the top
  float hJ = -fill + fbm(m, 120.0, 2, 0.5, 63u) * 0.0003;
  s.height = mix(hJ, max(hFace, hJ), stone);
  // burnt sienna clay, each paver its own shade, the odd replacement
  float hv = cellRand(c, 4u), hk = cellRand(c, 5u);
  vec3 col = vec3(0.27, 0.14, 0.10) * (0.88 + 0.24 * hv);
  col = mix(col, col * vec3(0.6, 0.55, 0.55), step(0.95, hk));
  col = mix(col, col * vec3(1.2, 1.2, 1.1), step(hk, 0.04));
  col *= 1.0 + 0.07 * fbm(ms, 14.0, 3, 0.5, 64u) + 0.03 * fbm(ms, 90.0, 2, 0.5, 65u);
  col *= mix(1.0, 0.93, worn);                                 // trodden tops darker
  // dirt along the joints and in the low corners
  float ej = e - JW;
  float dirt = (0.08 + 0.1 * cellRand(c, 33u)) * (1.0 - smoothstep(0.0, 0.012, ej));
  col *= 1.0 - dirt;
  vec3 sand = vec3(0.38, 0.33, 0.26) * (1.0 + 0.1 * fbm(m, 60.0, 2, 0.5, 66u)) * (0.75 + 0.25 * cellRand(c, 12u));
  s.albedo = mix(sand, col, stone);
  s.rough = mix(0.97, mix(0.86, 0.72, worn), stone);
}
`,
};

// Lyons sandstone (Boulder's building stone): coursed ashlar, 0.3 m courses, blocks 0.5 to
// 0.9 m, rubbed faces showing the bedding as faint streaks, iron spots, buff to pink. 2.4 m
// tile at 1.2 mm per texel. Mean linear albedo about (0.46, 0.34, 0.26).
export const sandstone = {
  name: 'sandstone', flat: [0.46, 0.34, 0.26, 0.85], size: 2048, tile: [2.4, 2.4], ss: 2,
  layout: { rowH: 0.3, rows: 8, seg: [3, 5], jitter: 0.35, seed: 53, shift: true },
  joint: 0.004,
  pass: { normal: 1.0, ao: 0.5, aoRadius: 0.008, cavity: 0.07 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  Cell c = rowsCell(m);
  vec2 ms = m + vec2(c.h * 19.1, cellRand(c, 30u) * 13.7);
  float JW = 0.0035 + 0.001 * noiseM(m, vec2(5.0), 70u);
  float wob = fbm(m, 20.0, 2, 0.5, 71u) * 0.0005;
  float e = c.e + wob;
  float bev = 0.001 + 0.002 * cellRand(c, 4u);
  float t = clamp((e - JW) / bev, 0.0, 1.0);
  float stone = smoothstep(JW - 0.0005, JW + 0.0005, e);
  float face = (cellRand(c, 1u) - 0.5) * 0.002
             + dot(c.lp - 0.5 * c.size, vec2(cellRand(c, 7u) - 0.5, cellRand(c, 8u) - 0.5)) * 0.006;
  face += fbm(ms, 4.0, 3, 0.5, 72u) * 0.0008 + fbm(ms, 50.0, 3, 0.55, 73u) * 0.0002;
  // bedding: the stone's layers run along the course, slightly ribbed where softer beds weathered back
  float bed = fbm2(ms, vec2(1.5, 25.0), 3, 0.55, 74u);
  face += bed * 0.00025;
  float hFace = face - bev * 0.4 * (1.0 - t) * (1.0 - t);
  float hMortar = -0.0015 - 0.001 * (0.5 + 0.5 * noiseM(m, vec2(3.0), 75u)) + fbm(m, 70.0, 2, 0.5, 76u) * 0.0003;
  s.height = mix(hMortar, max(hFace, hMortar), stone);
  // colour: buff to pink per block, bedding streaks, iron spots, a grey crust in patches
  float hv = cellRand(c, 2u), hp = cellRand(c, 3u);
  vec3 col = mix(vec3(0.48, 0.36, 0.26), vec3(0.46, 0.30, 0.26), hp) * (0.9 + 0.2 * hv);
  col *= 1.0 + 0.1 * bed + 0.05 * fbm(ms, 8.0, 3, 0.5, 77u);
  vec4 fe = voro(ms, vec2(60.0), 78u, 1.0);
  float spot = smoothstep(0.2, 0.05, fe.x) * step(0.9, fe.z);
  col = mix(col, vec3(0.3, 0.17, 0.1), 0.6 * spot);
  float crust = smoothstep(0.2, 0.7, fbm2(ms, vec2(3.0, 1.0), 3, 0.55, 79u) + 0.3 * (cellRand(c, 36u) - 0.5));
  col = mix(col, vec3(lum(col)) * vec3(0.9, 0.88, 0.84), 0.2 * crust) * (1.0 - 0.05 * crust);
  float ej = e - JW;
  float dusty = (0.02 + 0.03 * cellRand(c, 33u)) * (1.0 - smoothstep(0.0, 0.02, ej));
  col = mix(col, vec3(lum(col)) * vec3(0.95, 0.9, 0.82), 0.5 * dusty);
  vec3 mortar = vec3(0.44, 0.40, 0.35) * (1.0 + 0.08 * fbm(m, 45.0, 2, 0.5, 80u));
  s.albedo = mix(mortar, col, stone);
  s.rough = mix(0.95, 0.8 + 0.04 * hv, stone);
}
`,
};

// Painted stucco or render: trowelled, sand-finished, hairline cracks, a little grime in the
// hollows. 2 m tile at 2 mm per texel. The material colour carries the paint; the bake is
// near-white so the VLM colour is the albedo.
export const stucco = {
  name: 'stucco', flat: [0.62, 0.6, 0.56, 0.85], size: 1024, tile: [2.0, 2.0], ss: 2,
  pass: { normal: 1.0, ao: 0.3, aoRadius: 0.006, cavity: 0.04 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  // trowel sweeps (10-30 cm) over a sand finish
  float sweep = fbm2(warp(m, 3.0, 0.03, 90u), vec2(6.0, 3.0), 3, 0.5, 91u);
  float sand = fbm(m, 90.0, 3, 0.55, 92u);
  vec4 v = voro(m, vec2(220.0), 93u, 1.0);
  float h = sweep * 0.0006 + sand * 0.0002 + smoothstep(0.3, 0.1, v.x) * 0.00015;
  // hairline cracks
  float cr = 1.0 - smoothstep(0.0, 0.0012, abs(fbm(m, 1.5, 3, 0.5, 94u)) * 0.02 + 0.0004 * fbm(m, 30.0, 2, 0.5, 95u));
  cr *= step(0.6, fbm(m, 0.7, 2, 0.5, 96u) * 0.5 + 0.5);
  h -= cr * 0.0005;
  s.height = h;
  vec3 col = vec3(0.62, 0.6, 0.56) * (1.0 + 0.04 * sweep + 0.02 * sand);
  float grime = smoothstep(0.3, 0.8, fbm(m, 2.0, 3, 0.55, 97u)) * 0.06;
  col *= 1.0 - grime - 0.3 * cr;
  s.albedo = col;
  s.rough = 0.88 + 0.04 * sand;
}
`,
};

// Concrete sidewalk: 1.5 m slabs with sawn joints, broom finish along u, aggregate showing
// through in worn patches, dirt in the joints. 3 m tile at 2.9 mm per texel.
export const concrete = {
  name: 'concrete', flat: [0.40, 0.39, 0.37, 0.85], size: 1024, tile: [3.0, 3.0], ss: 2,
  layout: { rowH: 1.5, rows: 2, seg: [2, 2], jitter: 0.0, seed: 61 },
  joint: 0.003,
  pass: { normal: 1.0, ao: 0.4, aoRadius: 0.006, cavity: 0.05 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  Cell c = rowsCell(m);
  vec2 ms = m + vec2(c.h * 11.3, 0.0);
  float JW = 0.003;
  float e = c.e;
  float t = clamp((e - JW) / 0.004, 0.0, 1.0);
  float slab = smoothstep(JW - 0.0008, JW + 0.0008, e);
  // slab a little tilted, broom striations along u, aggregate pits
  float face = dot(c.lp - 0.5 * c.size, vec2(cellRand(c, 7u) - 0.5, cellRand(c, 8u) - 0.5)) * 0.004;
  float broom = sin(m.y * 1100.0 + fbm(ms, 5.0, 2, 0.5, 100u) * 6.0) * 0.00012 * (0.5 + 0.5 * fbm(ms, 3.0, 2, 0.5, 101u));
  vec4 v = voro(ms, vec2(120.0), 102u, 1.0);
  float pit = smoothstep(0.25, 0.08, v.x) * step(0.85, v.z);
  float wear = smoothstep(0.4, 0.8, fbm(ms, 1.2, 3, 0.55, 103u));
  face += broom * (1.0 - wear) + fbm(ms, 40.0, 3, 0.5, 104u) * 0.00015 - pit * 0.0005 * (0.5 + wear);
  float hFace = face - 0.003 * (1.0 - t) * (1.0 - t);
  s.height = mix(-0.006, hFace, slab);
  vec3 col = vec3(0.40, 0.39, 0.37) * (0.95 + 0.1 * cellRand(c, 2u));
  col *= 1.0 + 0.06 * fbm(ms, 6.0, 3, 0.5, 105u) + 0.03 * fbm(ms, 60.0, 2, 0.5, 106u);
  col = mix(col, col * vec3(0.85, 0.85, 0.87), 0.5 * pit);
  col *= mix(1.0, 0.94, wear);
  float ej = e - JW;
  col *= 1.0 - 0.12 * (1.0 - smoothstep(0.0, 0.02, ej));
  s.albedo = mix(vec3(0.22, 0.21, 0.19), col, slab);
  s.rough = mix(0.95, 0.86 - 0.08 * wear, slab);
}
`,
};

// Asphalt: fine aggregate in bitumen, worn paler on the crown, patched, cracked. 2 m tile at
// 2 mm per texel. Mean linear albedo about 0.07.
export const asphalt = {
  name: 'asphalt', flat: [0.07, 0.07, 0.07, 0.9], size: 1024, tile: [2.0, 2.0], ss: 2,
  pass: { normal: 0.8, ao: 0.3, aoRadius: 0.004, cavity: 0.04 },
  glsl: /* glsl */ `
void surface(vec2 m, inout Surf s) {
  vec4 v = voro(warp(m, 60.0, 0.001, 110u), vec2(220.0), 111u, 1.0);     // ~4.5 mm stones
  vec4 v2 = voro(m, vec2(500.0), 112u, 1.0);                             // fines
  float stoneTop = smoothstep(0.5, 0.15, v.x);
  float wear = smoothstep(0.35, 0.75, fbm(m, 0.8, 3, 0.55, 113u));       // bitumen worn off the stones
  s.height = stoneTop * 0.0008 + (v2.x - 0.5) * 0.0002 + fbm(m, 4.0, 3, 0.5, 114u) * 0.0006;
  // cracks
  float cr = 1.0 - smoothstep(0.0, 0.002, abs(fbm(m, 1.0, 3, 0.5, 115u)) * 0.03);
  cr *= step(0.55, fbm(m, 0.5, 2, 0.5, 116u) * 0.5 + 0.5);
  s.height -= cr * 0.002;
  vec3 bit = vec3(0.055, 0.055, 0.057);
  vec3 stone = mix(vec3(0.16, 0.15, 0.14), vec3(0.28, 0.27, 0.25), fract(v.z * 7.3)) * (0.8 + 0.4 * v2.z);
  vec3 col = mix(bit, stone, stoneTop * (0.25 + 0.75 * wear));
  col *= 1.0 + 0.1 * fbm(m, 2.0, 3, 0.5, 117u);
  col *= 1.0 - 0.5 * cr;
  s.albedo = col;
  s.rough = mix(0.92, 0.75, stoneTop * wear);
}
`,
};

export const RECIPES = Object.fromEntries([detail, macro, brick, pavers, sandstone, stucco, concrete, asphalt].map((r) => [r.name, r]));
