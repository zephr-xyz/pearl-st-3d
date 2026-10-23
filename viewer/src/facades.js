import * as THREE from 'three';

// 3D facades from a building's VLM style: the wall shell with real openings, 0.2 m reveals,
// sills, lintels, string courses, a stepped cornice and a parapet; a storefront ground floor
// with piers, bulkhead, plate glass, transom and fascia, and a recessed entrance at each
// entrance position. Geometry is emitted per material into buckets shared by the whole
// building (one mesh per material per building), with UVs in metres so the baked surfaces
// tile continuously across the wall and into the reveals.
//
// Wall frame: u along the wall (0..L), v up (0..H), w out of the wall (+ towards the street).

const Y = new THREE.Vector3(0, 1, 0);

export class FacadeBuckets {
  constructor() { this.b = new Map(); this.extras = []; }
  bucket(name) {
    if (!this.b.has(name)) this.b.set(name, { pos: [], nor: [], uv: [] });
    return this.b.get(name);
  }
  /** One mesh per material. mats: name → material. */
  meshes(mats) {
    const out = [];
    for (const [name, b] of this.b) {
      if (!b.pos.length) continue;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(b.pos, 3));
      g.setAttribute('normal', new THREE.Float32BufferAttribute(b.nor, 3));
      g.setAttribute('uv', new THREE.Float32BufferAttribute(b.uv, 2));
      const m = new THREE.Mesh(g, mats[name] || mats.wall);
      m.castShadow = true;
      m.receiveShadow = true;
      out.push(m);
    }
    return out.concat(this.extras);
  }
}

/** A point of the wall frame in world space. */
function at(F, u, v, w, out = new THREE.Vector3()) {
  return out.copy(F.O).addScaledVector(F.T, u).addScaledVector(Y, v).addScaledVector(F.N, w);
}

/** The shop's name lettered on the fascia board: a canvas texture on a plane just proud of it. */
function fasciaSign(F, u0, u1, v0, v1, w, text, colors) {
  const W = 1024, H = Math.max(64, Math.round(W * (v1 - v0) / (u1 - u0)));
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = colors.board;
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = colors.text; ctx.globalAlpha = 0.5; ctx.lineWidth = 3;
  ctx.strokeRect(10, 10, W - 20, H - 20);
  ctx.globalAlpha = 1;
  ctx.fillStyle = colors.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  let size = Math.round(H * 0.62);
  ctx.font = `700 ${size}px Georgia, 'Times New Roman', serif`;
  while (ctx.measureText(text).width > W * 0.84 && size > 12) { size -= 2; ctx.font = `700 ${size}px Georgia, 'Times New Roman', serif`; }
  ctx.fillText(text.toUpperCase(), W / 2, H / 2 + H * 0.02);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(u1 - u0, v1 - v0), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.55, metalness: 0.05 }));
  at(F, (u0 + u1) / 2, (v0 + v1) / 2, w, mesh.position);
  mesh.rotation.y = Math.atan2(F.N.x, F.N.z);
  mesh.castShadow = false;
  return mesh;
}

/** A sloped canvas awning over u0..u1 hung at vTop: canopy, two side cheeks and a valance. */
function awning(bk, F, u0, u1, vTop, proj, drop) {
  const vFront = vTop - drop;
  quad(bk, F, [[u0, vTop, 0.02], [u1, vTop, 0.02], [u1, vFront, proj], [u0, vFront, proj]], [0, proj, drop], [[u0, 0], [u1, 0], [u1, 1.2], [u0, 1.2]]);
  quad(bk, F, [[u0, vFront, proj], [u1, vFront, proj], [u1, vTop, 0.02], [u0, vTop, 0.02]], [0, -proj, -drop], [[u0, 1.2], [u1, 1.2], [u1, 0], [u0, 0]]);
  // cheeks
  quad(bk, F, [[u0, vTop, 0.02], [u0, vFront, proj], [u0, vFront - 0.28, proj], [u0, vFront - 0.28, proj]], [-1, 0, 0], [[0, 0], [proj, 0], [proj, 0.3], [proj, 0.3]]);
  quad(bk, F, [[u1, vFront, proj], [u1, vTop, 0.02], [u1, vFront - 0.28, proj], [u1, vFront - 0.28, proj]], [1, 0, 0], [[proj, 0], [0, 0], [proj, 0.3], [proj, 0.3]]);
  // valance with a scalloped hem: a strip plus a row of small tabs
  quad(bk, F, [[u0, vFront - 0.22, proj], [u1, vFront - 0.22, proj], [u1, vFront, proj], [u0, vFront, proj]], [0, 0, 1], [[u0, 0], [u1, 0], [u1, 0.22], [u0, 0.22]]);
  quad(bk, F, [[u1, vFront - 0.22, proj], [u0, vFront - 0.22, proj], [u0, vFront, proj], [u1, vFront, proj]], [0, 0, -1], [[u1, 0], [u0, 0], [u0, 0.22], [u1, 0.22]]);
  const n = Math.max(2, Math.round((u1 - u0) / 0.3)), s = (u1 - u0) / n;
  for (let i = 0; i < n; i++) {
    const a = u0 + i * s, b = a + s, m = (a + b) / 2;
    quad(bk, F, [[a + 0.02, vFront - 0.22, proj], [b - 0.02, vFront - 0.22, proj], [m + 0.03, vFront - 0.32, proj], [m - 0.03, vFront - 0.32, proj]], [0, 0, 1], [[a, 0.22], [b, 0.22], [m, 0.32], [m, 0.32]]);
  }
}

/** Arched head over an opening: a ring of trim segments from the springing with a keystone. */
function archHead(bk, F, o, segmental) {
  const uc = (o.u0 + o.u1) / 2, R = (o.u1 - o.u0) / 2 + 0.06;
  const ring = 0.14, n = 9;
  const rise = segmental ? 0.45 : 1.0;             // segmental arches rise less than their radius
  const vc = o.v1 - R * rise;
  const a0 = segmental ? Math.asin(1 - rise) : 0;
  for (let i = 0; i < n; i++) {
    const t0 = a0 + (Math.PI - 2 * a0) * (i / n), t1 = a0 + (Math.PI - 2 * a0) * ((i + 1) / n);
    const c0 = Math.cos(t0), s0 = Math.sin(t0), c1 = Math.cos(t1), s1 = Math.sin(t1);
    const pts = [[uc - c0 * R, vc + s0 * R * (segmental ? 1 / rise : 1) * rise], [uc - c1 * R, vc + s1 * R],
                 [uc - c1 * (R + ring), vc + s1 * (R + ring)], [uc - c0 * (R + ring), vc + s0 * (R + ring)]];
    const P = pts.map(([u, v]) => [u, v]);
    quad(bk, F, [[P[0][0], P[0][1], 0.05], [P[1][0], P[1][1], 0.05], [P[2][0], P[2][1], 0.05], [P[3][0], P[3][1], 0.05]], [0, 0, 1], P.map(([u, v]) => [u, v]));
    quad(bk, F, [[P[3][0], P[3][1], 0.05], [P[2][0], P[2][1], 0.05], [P[2][0], P[2][1], 0], [P[3][0], P[3][1], 0]], [-(P[2][0] - uc), -(P[2][1] - vc), 0].map((x) => -x), [[0, 0], [0.1, 0], [0.1, 0.05], [0, 0.05]]);
  }
  box(bk, F, uc - 0.09, uc + 0.09, o.v1 + R * rise - R + ring * 0.2, o.v1 + R * rise - R + ring * 1.5, 0, 0.08, { back: true });
}

/** The frame of one wall: origin at vertex 0 at ground, tangent along it, outward normal. */
export function wallFrame(wall, centroid) {
  const v = wall.vertices;
  const x0 = v[0][0], z0 = v[0][2], x1 = v[1][0], z1 = v[1][2];
  const dx = x1 - x0, dz = z1 - z0, L = Math.hypot(dx, dz);
  const T = new THREE.Vector3(dx / L, 0, dz / L);
  let N = new THREE.Vector3(-T.z, 0, T.x);
  const mx = (x0 + x1) / 2, mz = (z0 + z1) / 2;
  if ((mx + N.x - centroid[0]) ** 2 + (mz + N.z - centroid[1]) ** 2 < (mx - centroid[0]) ** 2 + (mz - centroid[1]) ** 2) N = N.negate();
  return { O: new THREE.Vector3(x0, 0, z0), T, N, L, H: wall.height };
}

/** Emit a quad in the wall frame. a, b, c, d counter-clockwise seen from the outside. */
function quad(bk, F, pts, n, uvs) {
  const P = pts.map(([u, v, w]) => F.O.clone().addScaledVector(F.T, u).addScaledVector(Y, v).addScaledVector(F.N, w));
  const nn = F.T.clone().multiplyScalar(n[0]).addScaledVector(Y, n[1]).addScaledVector(F.N, n[2]).normalize();
  const order = [0, 1, 2, 0, 2, 3];
  for (const i of order) {
    bk.pos.push(P[i].x, P[i].y, P[i].z);
    bk.nor.push(nn.x, nn.y, nn.z);
    bk.uv.push(uvs[i][0], uvs[i][1]);
  }
}

/** Axis-aligned rectangle on the wall plane at depth w facing out (+w). */
function faceOut(bk, F, u0, u1, v0, v1, w) {
  quad(bk, F, [[u0, v0, w], [u1, v0, w], [u1, v1, w], [u0, v1, w]], [0, 0, 1], [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]);
}

/** A box in the wall frame: u0..u1, v0..v1, w0..w1 (w1 > w0), all six faces, UVs in metres. */
function box(bk, F, u0, u1, v0, v1, w0, w1, skip = {}) {
  if (!skip.front) quad(bk, F, [[u0, v0, w1], [u1, v0, w1], [u1, v1, w1], [u0, v1, w1]], [0, 0, 1], [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]);
  if (!skip.back) quad(bk, F, [[u1, v0, w0], [u0, v0, w0], [u0, v1, w0], [u1, v1, w0]], [0, 0, -1], [[u1, v0], [u0, v0], [u0, v1], [u1, v1]]);
  if (!skip.top) quad(bk, F, [[u0, v1, w1], [u1, v1, w1], [u1, v1, w0], [u0, v1, w0]], [0, 1, 0], [[u0, w1], [u1, w1], [u1, w0], [u0, w0]]);
  if (!skip.bottom) quad(bk, F, [[u0, v0, w0], [u1, v0, w0], [u1, v0, w1], [u0, v0, w1]], [0, -1, 0], [[u0, w0], [u1, w0], [u1, w1], [u0, w1]]);
  if (!skip.left) quad(bk, F, [[u0, v0, w0], [u0, v0, w1], [u0, v1, w1], [u0, v1, w0]], [-1, 0, 0], [[w0, v0], [w1, v0], [w1, v1], [w0, v1]]);
  if (!skip.right) quad(bk, F, [[u1, v0, w1], [u1, v0, w0], [u1, v1, w0], [u1, v1, w1]], [1, 0, 0], [[w1, v0], [w0, v0], [w0, v1], [w1, v1]]);
}

/** The wall face minus the openings, as the cells of the grid their edges make. */
function shell(bk, F, openings, L, H) {
  const xs = new Set([0, L]), ys = new Set([0, H]);
  for (const o of openings) { xs.add(o.u0); xs.add(o.u1); ys.add(o.v0); ys.add(o.v1); }
  const X = [...xs].sort((a, b) => a - b), Yv = [...ys].sort((a, b) => a - b);
  for (let i = 0; i < X.length - 1; i++) {
    for (let j = 0; j < Yv.length - 1; j++) {
      const cu = (X[i] + X[i + 1]) / 2, cv = (Yv[j] + Yv[j + 1]) / 2;
      if (X[i + 1] - X[i] < 1e-4 || Yv[j + 1] - Yv[j] < 1e-4) continue;
      if (openings.some((o) => cu > o.u0 && cu < o.u1 && cv > o.v0 && cv < o.v1)) continue;
      faceOut(bk, F, X[i], X[i + 1], Yv[j], Yv[j + 1], 0);
    }
  }
}

/** Reveal of an opening: jambs, head and sill faces running from the wall plane to depth d. */
function reveal(bk, F, o, d) {
  const { u0, u1, v0, v1 } = o;
  quad(bk, F, [[u0, v0, -d], [u0, v0, 0], [u0, v1, 0], [u0, v1, -d]], [1, 0, 0], [[-d, v0], [0, v0], [0, v1], [-d, v1]]);     // left jamb faces +u
  quad(bk, F, [[u1, v0, 0], [u1, v0, -d], [u1, v1, -d], [u1, v1, 0]], [-1, 0, 0], [[0, v0], [-d, v0], [-d, v1], [0, v1]]);    // right jamb faces -u
  quad(bk, F, [[u0, v1, 0], [u1, v1, 0], [u1, v1, -d], [u0, v1, -d]], [0, -1, 0], [[u0, 0], [u1, 0], [u1, -d], [u0, -d]]);   // head faces down
  quad(bk, F, [[u0, v0, -d], [u1, v0, -d], [u1, v0, 0], [u0, v0, 0]], [0, 1, 0], [[u0, -d], [u1, -d], [u1, 0], [u0, 0]]);    // sill faces up
}

/**
 * Build one wall. style: the building's VLM style. Returns nothing; fills the buckets:
 * 'wall' (masonry), 'trim' (sills, lintels, cornice, piers' caps), 'glass', 'frame' (painted
 * frames, mullions, fascia, bulkhead), 'door', 'dark' (interior backs).
 */
export function buildWall(buckets, wall, bld, style, opts = {}) {
  const F = wallFrame(wall, bld.centroid_m);
  const L = F.L, H = F.H;
  const stories = Math.max(1, style.stories || Math.max(1, Math.round(H / 3.6)));
  const fh = H / stories;
  const D = opts.revealDepth ?? 0.2;
  const isPrimary = !!opts.primary;
  const gf = style.ground_floor || 'storefront';
  const storefront = stories >= 1 && (gf === 'storefront' || gf === 'full_glass' || gf === 'glass' || gf === 'arcade') && L >= 4 && (isPrimary || opts.allStorefront);
  const entrances = (wall.entrances || []).map((e) => e.t * L).filter((u) => u > 1.2 && u < L - 1.2);
  const wallB = buckets.bucket('wall'), trim = buckets.bucket('trim'), glass = buckets.bucket('glass');
  const frame = buckets.bucket('frame'), door = buckets.bucket('door'), dark = buckets.bucket('dark');
  const fabric = buckets.bucket('fabric');
  const openings = [];
  const arched = style.windows === 'arched' || style.windows === 'romanesque_arched' || /romanesque|italianate|victorian/.test(style.arch_style || '') || style.era === 'victorian';
  const segmental = arched && !/romanesque/.test((style.arch_style || '') + (style.windows || ''));
  const ornate = !!(style.accent || style.arch_style || style.era || stories >= 2);

  // ---- upper floors: a row of windows per floor from the window grid
  const cols = style.window_grid && style.window_grid.cols > 0 ? style.window_grid.cols : Math.max(1, Math.round(L / 3.2));
  const pitch = L / cols;
  const wide = style.windows === 'large_plate_glass' || style.windows === 'ribbon' || style.windows === 'office';
  const ww = Math.min(wide ? 2.2 : 1.3, pitch * (wide ? 0.7 : 0.45));
  const wh = Math.min(2.1, fh * 0.55);
  const firstFloor = storefront ? 1 : 0;
  for (let f = firstFloor; f < stories; f++) {
    const base = f * fh;
    const v0 = base + Math.min(0.95, fh * 0.28), v1 = Math.min(v0 + wh, base + fh - 0.45);
    if (v1 - v0 < 0.6) continue;
    for (let c = 0; c < cols; c++) {
      const uc = (c + 0.5) * pitch;
      const u0 = uc - ww / 2, u1 = uc + ww / 2;
      if (u0 < 0.35 || u1 > L - 0.35) continue;
      if (f === 0 && entrances.some((e) => Math.abs(e - uc) < ww / 2 + 0.9)) continue;
      openings.push({ u0, u1, v0, v1, kind: 'window' });
    }
    // string course at the floor line on fronts with trim
    if (f > 0 && (style.accent || style.arch_style || style.era)) box(trim, F, 0, L, base - 0.06, base + 0.06, 0, 0.05, { back: true });
  }

  // ---- ground floor: storefront or doors in the wall
  if (storefront) {
    const gh = fh;                                        // ground floor height
    const fasciaH = Math.min(0.75, gh * 0.22), transom = gh - fasciaH - 0.05;
    const bulk = 0.6;
    const pierW = 0.3;
    // piers every ~3.6 m, and at both ends
    const bays = Math.max(1, Math.round((L - pierW) / 3.6));
    const bayW = (L - pierW) / bays;
    const piers = [];
    for (let i = 0; i <= bays; i++) piers.push(i * bayW);
    // the storefront is one opening in the shell from the bulkhead to the transom
    openings.push({ u0: pierW, u1: L - pierW, v0: 0, v1: transom, kind: 'shop' });
    // piers (brick, proud of the glazing line), bulkhead, glazing, fascia
    for (const pu of piers) {
      if (pu > 0 && pu < L - pierW) box(wallB, F, pu, pu + pierW, 0, transom, -D, 0.04, { back: true });
    }
    box(wallB, F, 0, pierW, 0, transom, -D, 0.04, { back: true, left: true });
    box(wallB, F, L - pierW, L, 0, transom, -D, 0.04, { back: true, right: true });
    for (let i = 0; i < bays; i++) {
      const a = piers[i] + pierW, b = piers[i + 1];
      const ent = entrances.find((e) => e > a + 0.2 && e < b - 0.2);
      const parts = ent ? [[a, ent - 0.75], [ent + 0.75, b]] : [[a, b]];
      for (const [p0, p1] of parts) {
        if (p1 - p0 < 0.3) continue;
        box(frame, F, p0, p1, 0, bulk, -D, -D + 0.06, { back: true });                 // bulkhead
        faceOut(glass, F, p0 + 0.03, p1 - 0.03, bulk + 0.03, transom - 0.03, -D + 0.02);  // plate glass
        faceOut(dark, F, p0, p1, bulk, transom, -D - 0.08);                              // the shop behind
        box(frame, F, p0, p0 + 0.04, bulk, transom, -D, -D + 0.06, { back: true });    // stiles
        box(frame, F, p1 - 0.04, p1, bulk, transom, -D, -D + 0.06, { back: true });
        box(frame, F, p0, p1, transom - 0.3, transom - 0.26, -D, -D + 0.06, { back: true }); // transom bar
      }
      if (ent) {
        // recessed entrance: 1.5 m wide, 0.9 m deep, door at the back
        const e0 = ent - 0.75, e1 = ent + 0.75, ed = 0.9;
        quad(dark, F, [[e0, 0, -ed], [e0, 0, -D], [e0, transom, -D], [e0, transom, -ed]], [1, 0, 0], [[-ed, 0], [-D, 0], [-D, transom], [-ed, transom]]);
        quad(dark, F, [[e1, 0, -D], [e1, 0, -ed], [e1, transom, -ed], [e1, transom, -D]], [-1, 0, 0], [[-D, 0], [-ed, 0], [-ed, transom], [-D, transom]]);
        quad(dark, F, [[e0, transom, -D], [e1, transom, -D], [e1, transom, -ed], [e0, transom, -ed]], [0, -1, 0], [[e0, -D], [e1, -D], [e1, -ed], [e0, -ed]]);
        quad(dark, F, [[e0, 0, -ed], [e1, 0, -ed], [e1, 0, -D], [e0, 0, -D]], [0, 1, 0], [[e0, -ed], [e1, -ed], [e1, -D], [e0, -D]]);
        faceOut(door, F, e0 + 0.1, e1 - 0.1, 0, 2.3, -ed);
        faceOut(glass, F, e0 + 0.1, e1 - 0.1, 2.35, transom - 0.05, -ed);
        box(frame, F, e0, e1, 2.3, 2.35, -ed, -ed + 0.05, { back: true });
      }
    }
    box(frame, F, 0, L, transom, gh - 0.05, 0, 0.06, { back: true });                     // fascia / signboard
    box(trim, F, 0, L, gh - 0.05, gh + 0.07, 0, 0.12, { back: true });                     // storefront cornice
    // the shop's name on the fascia, and canvas awnings over the bays where the style describes one
    if (opts.signText && isPrimary) {
      const sw = Math.min(L * 0.6, 7), su = L / 2;
      buckets.extras.push(fasciaSign(F, su - sw / 2, su + sw / 2, transom + 0.08, gh - 0.12, 0.075, opts.signText, opts.signColors));
    }
    if (style.awning) {
      for (let i = 0; i < bays; i++) {
        const a = piers[i] + pierW + 0.05, b = piers[i + 1] - 0.05;
        if (b - a > 1.2) awning(fabric, F, a, b, transom - 0.02, 1.1, 0.5);
      }
    }
  } else {
    // doors straight in the wall at each entrance
    for (const e of entrances) openings.push({ u0: e - 0.55, u1: e + 0.55, v0: 0, v1: 2.4, kind: 'door' });
  }

  // ---- the shell, the reveals and what sits in each opening
  const shellOpenings = openings.filter((o) => o.kind !== 'shop');
  shell(wallB, F, openings, L, H);
  for (const o of shellOpenings) {
    reveal(wallB, F, o, D);
    if (o.kind === 'window') {
      faceOut(glass, F, o.u0 + 0.04, o.u1 - 0.04, o.v0 + 0.04, o.v1 - 0.04, -D + 0.06);
      faceOut(dark, F, o.u0, o.u1, o.v0, o.v1, -D - 0.02);
      // frame and a centre mullion
      box(frame, F, o.u0, o.u1, o.v0, o.v0 + 0.05, -D + 0.04, -D + 0.1, { back: true });
      box(frame, F, o.u0, o.u1, o.v1 - 0.05, o.v1, -D + 0.04, -D + 0.1, { back: true });
      box(frame, F, o.u0, o.u0 + 0.05, o.v0, o.v1, -D + 0.04, -D + 0.1, { back: true });
      box(frame, F, o.u1 - 0.05, o.u1, o.v0, o.v1, -D + 0.04, -D + 0.1, { back: true });
      const mu = (o.u0 + o.u1) / 2;
      box(frame, F, mu - 0.025, mu + 0.025, o.v0, o.v1, -D + 0.04, -D + 0.09, { back: true });
      const mv = o.v0 + (o.v1 - o.v0) * 0.55;
      box(frame, F, o.u0, o.u1, mv - 0.02, mv + 0.02, -D + 0.04, -D + 0.09, { back: true });
      // sill, and a lintel or an arched head with a keystone
      box(trim, F, o.u0 - 0.07, o.u1 + 0.07, o.v0 - 0.09, o.v0, -D * 0.5, 0.06, { back: true });
      if (arched) archHead(trim, F, o, segmental);
      else box(trim, F, o.u0 - 0.05, o.u1 + 0.05, o.v1, o.v1 + 0.16, 0, 0.04, { back: true });
    } else if (o.kind === 'door') {
      faceOut(door, F, o.u0, o.u1, o.v0, o.v1, -D - 0.02);
      box(trim, F, o.u0 - 0.06, o.u1 + 0.06, o.v1, o.v1 + 0.16, 0, 0.05, { back: true });
    }
  }

  // ---- cornice (bracketed, with dentils on the ornate fronts) and parapet
  if (H >= 5 || stories >= 2) {
    box(trim, F, 0, L, H - 0.42, H - 0.28, 0, 0.08, { back: true });
    box(trim, F, 0, L, H - 0.28, H - 0.14, 0, 0.16, { back: true });
    box(trim, F, 0, L, H - 0.14, H, 0, 0.26, { back: true });
    if (ornate) {
      const nb = Math.max(2, Math.round(L / 0.9)), sb = L / nb;
      for (let i = 0; i <= nb; i++) {
        const u = Math.min(L - 0.08, Math.max(0.08, i * sb));
        box(trim, F, u - 0.07, u + 0.07, H - 0.78, H - 0.42, 0, 0.2, { back: true });     // brackets
      }
      const nd = Math.max(2, Math.round(L / 0.15));
      for (let i = 0; i < nd; i++) {
        const u = (i + 0.5) * (L / nd);
        box(trim, F, u - 0.035, u + 0.035, H - 0.5, H - 0.42, 0.08, 0.15, { back: true }); // dentils
      }
    }
    box(wallB, F, 0, L, H, H + 0.55, -0.3, 0.02, { bottom: true });
    box(trim, F, 0, L, H + 0.55, H + 0.62, -0.34, 0.06, { bottom: true });
  }
  // a downspout at one end of the longer fronts
  if (L > 8 && opts.downspout) {
    const u = opts.downspout > 0 ? L - 0.35 : 0.35;
    box(frame, F, u - 0.05, u + 0.05, 0.1, H + 0.5, 0.06, 0.16, {});
    box(frame, F, u - 0.05, u + 0.35 * Math.sign(opts.downspout), 0.1, 0.2, 0.06, 0.3, {});
  }
}
