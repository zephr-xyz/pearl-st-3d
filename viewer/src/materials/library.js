// Pearl St material library. Colours are LINEAR RGB. Textured materials keep colour = 1 and
// roughness = 1: the baked maps hold the values; the building's own colour (from the VLM
// style) goes on as a tint multiplier against the recipe's mean albedo (see index.html
// wallTint).
//
//   props  three.js material properties
//   bake   recipe name (recipes.js) providing albedo + surface maps
//   surf   runtime surface settings (surface.js surfaceUniforms)
//   meta   published in materials.meta[name]

// per-brick patchwork: ±6 % value, a warm/cool hue drift, courses banded a little, 3 % odd
// bricks (burnt dark, pale, dirty)
const BRICK_CELL = {
  value: 0.06, hue: 0.5, rough: 0.04, row: 0.3, a: [1.05, 0.98, 0.95], b: [0.96, 1.0, 1.03],
  out: { p: 0.03, fam: [[0.7, 0.65, 0.7], [1.15, 1.15, 1.05], [0.85, 0.8, 0.78]] },
};
const STONE_CELL = {
  value: 0.08, hue: 0.6, rough: 0.05, row: 0.4, a: [1.05, 0.99, 0.95], b: [0.96, 0.99, 1.04],
  out: { p: 0.08, fam: [[1.04, 0.95, 0.9], [0.92, 0.92, 0.94], [1.06, 1.02, 0.96]] },
};
const PAVER_CELL = {
  value: 0.07, hue: 0.6, rough: 0.03, row: 0.25, a: [1.06, 1.0, 0.94], b: [0.95, 0.99, 1.05],
  corr: 0.4, corrHue: 0.5, corrFreq: 1 / 6, far: 0.75,
  out: { p: 0.04, fam: [[0.75, 0.72, 0.72], [1.12, 1.05, 0.95], [0.9, 0.95, 1.05]] },
};
const WALL_MACRO = { f1: 1 / 4, f2: 1 / 15, albedo: 0.05, rough: 0.05, an1: [1, 1], an2: [2, 0.4] };
const WALL_DETAIL = { freq: 2.0, normal: 0.5, albedo: 0.25, rough: 0.05 };
// soiled ledges, run-off streaks hanging from the bed joints, sheltered soffits
const WALL_WEATHER = { ledge: 0.2, streak: 0.35, share: 0.5, soffit: 0.1 };
const GROUND_MACRO = { f1: 1 / 2.5, f2: 1 / 20, albedo: 0.14, rough: 0.12, an1: [1, 1], an2: [1, 1] };
const PAVING_FAR = { start: 0.08, end: 0.45, joint: 1.2 };
const GUM = { radius: 0.0065, albedo: 0.67, rough: 0.8, cluster: { freq: 1 / 25, lo: 0.5, hi: 0.6 } };

export const LIBRARY = {
  'brick': {
    props: { roughness: 1 },
    bake: 'brick',
    surf: { cell: BRICK_CELL, macro: WALL_MACRO, detail: WALL_DETAIL, weather: WALL_WEATHER, mirror: 0.5, microShadow: 1 },
    vc: 'tint',
    meta: { albedo: [0.32, 0.18, 0.15], courseH: 2.4 / 36, uv: 'u along the wall, v up (m)' },
  },
  'brick.painted': {
    // the paint covers brick and mortar alike: the cell patchwork is damped, the colour is the paint
    props: { roughness: 1 },
    bake: 'brick',
    surf: { cell: { ...BRICK_CELL, value: 0.025, hue: 0.1, out: { p: 0, fam: [[1, 1, 1]] } }, macro: { ...WALL_MACRO, albedo: 0.08 }, detail: WALL_DETAIL, weather: { ...WALL_WEATHER, streak: 0.45 }, mirror: 0.5, microShadow: 1 },
    vc: 'tint',
    meta: { albedo: [0.32, 0.18, 0.15], paint: true, courseH: 2.4 / 36 },
  },
  'sandstone': {
    props: { roughness: 1 },
    bake: 'sandstone',
    surf: { cell: STONE_CELL, macro: WALL_MACRO, detail: WALL_DETAIL, weather: WALL_WEATHER, mirror: 0.6, microShadow: 1 },
    vc: 'tint',
    meta: { albedo: [0.46, 0.34, 0.26], courseH: 0.3 },
  },
  'stucco': {
    props: { roughness: 1 },
    bake: 'stucco',
    surf: { macro: { ...WALL_MACRO, albedo: 0.08, rough: 0.06 }, detail: { ...WALL_DETAIL, normal: 0.35 }, weather: { ...WALL_WEATHER, streak: 0.4 }, stain: { amount: 0.06, freq: 0.6, threshold: 0.75, stretch: 5 } },
    vc: 'tint',
    meta: { albedo: [0.62, 0.6, 0.56], paint: true },
  },
  'pavers': {
    props: { roughness: 1 },
    bake: 'pavers',
    surf: {
      cell: PAVER_CELL, far: PAVING_FAR, macro: GROUND_MACRO, detail: { ...WALL_DETAIL, normal: 0.4, albedo: 0.2 }, mirror: 0.75,
      spots: { ...GUM, prob: 0.14, blot: { prob: 0.04, radius: 0.022, albedo: 0.8, rough: 0.93 } },
      stain: { amount: 0.18, freq: 0.5, threshold: 0.66, stretch: 1.5 },
    },
    vc: 'tint',
    meta: { albedo: [0.27, 0.15, 0.11], paver: [0.2, 0.1], uv: 'u along the mall, v across (m)' },
  },
  'concrete': {
    props: { roughness: 1 },
    bake: 'concrete',
    surf: {
      cell: { value: 0.04, hue: 0.2, rough: 0.05, row: 0, a: [1.02, 1.0, 0.98], b: [0.98, 0.99, 1.02] }, macro: GROUND_MACRO, detail: { ...WALL_DETAIL, normal: 0.3, albedo: 0.2 },
      spots: { ...GUM, prob: 0.1 }, stain: { amount: 0.2, freq: 0.5, threshold: 0.66 },
    },
    vc: 'tint',
    meta: { albedo: [0.40, 0.39, 0.37], slab: [1.5, 1.5], uv: 'metres, any orientation' },
  },
  'asphalt': {
    props: { roughness: 1 },
    bake: 'asphalt',
    surf: { macro: { ...GROUND_MACRO, albedo: 0.2, rough: 0.1 }, detail: { ...WALL_DETAIL, normal: 0.3, albedo: 0.15 }, stain: { amount: 0.25, freq: 0.4, threshold: 0.62, stretch: 2 } },
    vc: 'tint',
    meta: { albedo: [0.07, 0.07, 0.07], uv: 'metres, any orientation' },
  },
};
