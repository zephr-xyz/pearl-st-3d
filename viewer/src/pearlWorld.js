import * as THREE from 'three';
import { RNG } from './core/rng.js';
import vegetation from './world/vegetation.js';

// Glue between Pearl St's georeferenced scene and the street trees taken from
// 3DSceneRenderer (world/vegetation.js). That module was written against the project's
// `app` object, with a route in (s, d) coordinates and a layout plan bucketed per chunk. Here:
//   - app.params wraps the URL parameters as num()/str();
//   - app.route and app.layout are stand-ins: every tree gets its own stretch of a straight
//     virtual route (s = 20 m per tree, heading east), so toWorld(s, d, h) lands on the tree
//     and the module's planning, props and ground shade work unchanged.

export function makeParams(search) {
  const raw = new URLSearchParams(search);
  return {
    raw,
    num(k, d = 0) { const v = raw.get(k); return v === null || v === '' || Number.isNaN(+v) ? d : +v; },
    str(k, d = '') { const v = raw.get(k); return v === null ? d : v; },
    view: null,
  };
}

/** trees: [{x, z, y}] in scene metres (y = ground). Returns the stand-in route and layout. */
export function makeRouteLayout(trees, seed = 7) {
  const S = 20;
  const list = trees.map((t, i) => {
    const r = RNG.from(seed, 'tree', i);
    return {
      id: i, s: i * S, d: 0, side: 1, seed: r.int(1, 2 ** 31 - 1),
      height: r.range(5.5, 7.5), crown: r.range(2.8, 4.0), mature: r.chance(0.2),
      pos: new THREE.Vector3(t.x, t.y, t.z),
    };
  });
  const at = (s) => list[Math.max(0, Math.min(list.length - 1, Math.round(s / S)))];
  const route = {
    length: list.length * S,
    wrap: (s) => s,
    delta: (a, b) => a - b,
    heading: () => 0,
    curvature: () => 0,
    offsetScale: () => 1,
    groundY: (s, d) => at(s).pos.y,
    elevation: (s) => at(s).pos.y,
    toWorld(s, d, h = 0, out = new THREE.Vector3()) {
      const t = at(s);
      return out.set(t.pos.x + (s - t.s), t.pos.y + h, t.pos.z + d);
    },
  };
  const layout = {
    seed, trees: list, furniture: [], stations: [], obstacles: [],
    chunkIndex: () => 0,
    inChunk: (kind) => (kind === 'trees' ? list : []),
    isInStation: () => false,
    isInCrossStreet: () => false,
    obstaclesNear: () => [],
    addObstacles: () => {},
  };
  return { route, layout };
}

export { vegetation };
