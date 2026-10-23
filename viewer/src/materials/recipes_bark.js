// Bark recipes, taken unchanged from github.com/vladi21k/3DSceneRenderer (src/materials/recipes/misc.js, MIT):
// fissured mature bark and smooth young bark for the vegetation module's trunks and branches.

const BARK_COMMON = /* glsl */ `
// fissure profile of a set of n wandering lines around the tile: x phase warped by
// low-frequency noise; returns depth weight 0..1 (1 on the fissure line)
float fissures(vec2 m, float n, float warpA, uint sd, float hw, float actLo, out float plate) {
  float sp = uTile.x / n;
  float ph = m.x / sp + warpA * fbm2(m, vec2(1.25, 0.625), 3, 0.5, sd) + 0.2 * fbm2(m, vec2(5.0, 2.5), 2, 0.5, sd + 11u);
  float fr = fract(ph);
  float d = min(fr, 1.0 - fr) * sp;                        // metres to the nearest line
  int id = sfMod(int(floor(ph + 0.5)), int(n));
  plate = fract(float(sfMod(int(floor(ph)), int(n))) * 0.618);
  // each line fades in and out along its length
  float act = smoothstep(actLo, actLo + 0.35, fbm2(vec2(float(id) * sp, m.y), vec2(1.25, 1.875), 2, 0.5, sd + 23u));
  float t = clamp(d / max(hw * mix(0.4, 1.0, act), 1e-4), 0.0, 1.0);
  return (1.0 - t) * (1.0 - t) * act;
}
// lenticels: a jittered 16 × 12.5 mm grid, one horizontal dash per cell (some empty)
float lenticels(vec2 m, float lenMin, float lenMax, float keep) {
  vec2 lc = vec2(0.016, 0.0125);
  vec2 gi = floor(m / lc);
  ivec2 id = sfMod2(ivec2(gi), ivec2(50, 128));
  vec2 jit = hash22(id, 293u) - 0.5;
  vec2 dd = m - (gi + 0.5 + jit * vec2(0.55, 0.45)) * lc;
  float hl = mix(lenMin, lenMax, fract(jit.x * 7.31 + 0.5));
  float e = length(vec2(dd.x / hl, dd.y / 0.0005));
  return (1.0 - smoothstep(0.55, 1.0, e)) * step(1.0 - keep, sfHash(id, 294u));
}
float lichen(vec2 m) {
  float big = smoothstep(0.15, 0.55, fbm(m, 1.2, 3, 0.5, 305u));          // patchy, per side
  return smoothstep(0.58, 0.7, fbm(m, 4.0, 5, 0.6, 295u)) * big;
}
`;

export const bark = {
  name: 'bark', flat: [0.2, 0.18, 0.155, 0.9], size: [768, 1536], tile: [0.8, 1.6], ss: 2,
  pass: { normal: 1.0, ao: 0.7, aoRadius: 0.01, cavity: 0.08 },
  glsl: BARK_COMMON + /* glsl */ `
void surface(vec2 m, inout Surf s) {
  float wv = 0.5 + 0.5 * fbm2(m, vec2(2.5, 1.25), 2, 0.5, 296u);   // width / depth along the trunk
  float hw = 0.003 + 0.006 * wv;
  float dep = 0.0015 + 0.0035 * smoothstep(0.1, 0.9, wv);
  float pa, pb, pc;
  float fa = fissures(m, 10.0, 1.3, 291u, hw, -0.25, pa);
  float fb = fissures(m + vec2(0.0, 0.53), 7.0, 1.8, 311u, hw * 1.15, -0.1, pb);
  float fc = fissures(m + vec2(0.0, 0.27), 23.0, 0.9, 321u, 0.0022, 0.15, pc);
  float f1 = max(fa, fb);
  float f2 = fc * (1.0 - f1);
  float rid = 1.0 - f1;
  // plate tops: soft scaly relief and short cross checks
  float relief = fbm2(m, vec2(20.0, 8.0), 4, 0.55, 297u);
  vec4 cc = voro(m + 0.17, vec2(10.0, 40.0), 303u, 0.9);
  float check = (1.0 - smoothstep(0.0, 0.05, cc.w)) * smoothstep(0.35, 0.75, fbm(m, 5.0, 2, 0.5, 304u)) * rid * (1.0 - f2);
  float top = smoothstep(0.3, 0.0, f1 + f2);
  float lent = lenticels(m, 0.001, 0.003, 0.4) * top;
  float lich = lichen(m) * rid;
  float scale = fbm(m, 45.0, 3, 0.55, 306u);                                   // fine scaly grain
  s.height = -dep * f1 - 0.0008 * f2 - 0.0005 * check + rid * (relief * 0.0018 + scale * 0.0006) + lent * 0.00012 + lich * 0.0002;
  float mot = fbm(m, 4.0, 3, 0.5, 301u);
  vec3 c = vec3(0.205, 0.185, 0.158) * (1.0 + 0.28 * mot + 0.1 * scale);
  c *= 1.0 - 0.18 * smoothstep(0.2, 0.7, fbm(m, 1.5, 3, 0.5, 307u));        // darker sooty / damp patches
  c *= 1.0 + 0.08 * (pa - 0.5);                                                // plates differ a little
  c = mix(c, vec3(0.25, 0.24, 0.22) * (1.0 + 0.1 * relief), 0.4 * top);       // weathered grey ridge tops
  c *= mix(1.0, 0.72, f1) * mix(1.0, 0.85, f2) * (1.0 - 0.12 * check);          // fissure floors: darker,
  c = mix(c, c * vec3(1.08, 0.97, 0.88), f1);                                  // a little warmer
  c = mix(c, vec3(0.34, 0.31, 0.26), lent * 0.6);
  c = mix(c, vec3(0.36, 0.38, 0.32) * (1.0 + 0.15 * relief), lich * 0.75);     // grey-green crust
  s.albedo = c;
  s.rough = mix(0.85, 0.95, f1) + 0.03 * relief;
}
`,
};

// Smooth young street-tree bark (trunks under ~25 cm, branches), same tile and mapping:
// smooth grey skin with faint vertical striation and a few long shallow splits, horizontal
// lenticel dashes (3-8 mm), soft mottling, lichen patches.
export const barksmooth = {
  name: 'barksmooth', flat: [0.23, 0.215, 0.19, 0.82], size: [512, 1024], tile: [0.8, 1.6], ss: 2,
  pass: { normal: 1.0, ao: 0.5, aoRadius: 0.006, cavity: 0.05 },
  glsl: BARK_COMMON + /* glsl */ `
void surface(vec2 m, inout Surf s) {
  float pa;
  float split = fissures(m, 6.0, 1.5, 312u, 0.0035, 0.3, pa);                // splits only here and there
  float stri = fbm2(m, vec2(30.0, 2.5), 3, 0.5, 314u);                        // faint vertical striation
  float wr = fbm2(m, vec2(5.0, 60.0), 2, 0.5, 315u);                          // fine horizontal wrinkles
  float lent = lenticels(m, 0.0015, 0.004, 0.6);
  float lich = lichen(m);
  s.height = -0.0012 * split + stri * 0.00015 + wr * 0.00006 + lent * 0.00018 + lich * 0.00015;
  vec3 c = vec3(0.235, 0.22, 0.195) * (1.0 + 0.16 * fbm(m, 3.0, 3, 0.5, 316u) + 0.05 * stri);
  c *= 1.0 - 0.15 * smoothstep(0.2, 0.7, fbm(m, 1.5, 3, 0.5, 317u));        // darker damp patches
  c *= mix(1.0, 0.8, split);
  c = mix(c, vec3(0.36, 0.33, 0.27), lent * 0.85);
  c = mix(c, vec3(0.37, 0.39, 0.33), lich * 0.7);
  s.albedo = c;
  s.rough = 0.8 + 0.06 * stri + 0.08 * split;
}
`,
};
