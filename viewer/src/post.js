import * as THREE from 'three';

// Camera post: the scene is rendered to an HDR target (half float, 4x MSAA), then one chain
// of full-screen passes makes a photograph of it: metered exposure, a little unsharp
// sharpening in HDR, a soft bloom from the brightest pixels (sun glints, sky over the roof
// line), AgX tone mapping, vignette and fine grain. Modelled on the camera-like post of
// 3DSceneRenderer (src/env/post.js), reduced to what a still frame needs.

const VERT = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const BRIGHT = /* glsl */ `
uniform sampler2D tScene;
uniform float uExposure;
uniform float uThreshold;
varying vec2 vUv;
void main() {
  vec3 c = texture2D(tScene, vUv).rgb * uExposure;
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float k = max(l - uThreshold, 0.0) / max(l, 1e-4);
  gl_FragColor = vec4(c * k, 1.0);
}
`;

const BLUR = /* glsl */ `
uniform sampler2D tIn;
uniform vec2 uDir;      // (1/w, 0) or (0, 1/h)
varying vec2 vUv;
void main() {
  const float w[7] = float[7](0.1964, 0.1740, 0.1210, 0.0661, 0.0283, 0.0095, 0.0025);
  vec3 c = texture2D(tIn, vUv).rgb * w[0];
  for (int i = 1; i < 7; i++) {
    vec2 o = uDir * float(i) * 1.5;
    c += (texture2D(tIn, vUv + o).rgb + texture2D(tIn, vUv - o).rgb) * w[i];
  }
  gl_FragColor = vec4(c, 1.0);
}
`;

const FINAL = /* glsl */ `
#include <common>
#include <tonemapping_pars_fragment>
uniform sampler2D tScene;
uniform sampler2D tBloom;
uniform vec2 uTexel;
uniform float uExposure;
uniform float uSharpen;
uniform float uBloom;
uniform float uVignette;
uniform float uGrain;
uniform float uSeed;
varying vec2 vUv;
float hash12(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
void main() {
  vec3 c = texture2D(tScene, vUv).rgb;
  // unsharp mask in HDR (a camera's in-body sharpening): the detail a 1920 px frame of a
  // street shows comes partly from this
  vec3 n = (texture2D(tScene, vUv + vec2(uTexel.x, 0.0)).rgb + texture2D(tScene, vUv - vec2(uTexel.x, 0.0)).rgb
          + texture2D(tScene, vUv + vec2(0.0, uTexel.y)).rgb + texture2D(tScene, vUv - vec2(0.0, uTexel.y)).rgb) * 0.25;
  c = max(c + (c - n) * uSharpen, 0.0);
  c *= uExposure;
  // deep-shadow term: below about -2 stops the curve steepens again, so recesses, doorways
  // and the shade under cornices fall towards black while mid shade keeps its detail (the
  // photographs' darkest 2 % sit at luma 4-32; AgX's own toe alone leaves them milky)
  float lh = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c *= mix(0.7, 1.0, smoothstep(0.0, 0.2, lh));
  c += texture2D(tBloom, vUv).rgb * uBloom;
  c = AgXToneMapping(c);
  c = max(c - 0.018, 0.0) / 0.982;          // soft black point
  float r = length((vUv - 0.5) * vec2(1.0, 0.75)) * 1.6;
  c *= 1.0 - uVignette * smoothstep(0.55, 1.25, r);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float g = hash12(gl_FragCoord.xy + uSeed) - 0.5;
  c += g * uGrain * (0.35 + 0.65 * (1.0 - l));
  gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
  #include <colorspace_fragment>
}
`;

export function createPost(renderer, scene, camera, opts = {}) {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const sceneRT = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 4, depthBuffer: true });
  const bw = Math.max(1, Math.floor(size.x / 4)), bh = Math.max(1, Math.floor(size.y / 4));
  const mk = () => new THREE.WebGLRenderTarget(bw, bh, { type: THREE.HalfFloatType, depthBuffer: false });
  let bloomA = mk(), bloomB = mk();

  const quadGeo = new THREE.PlaneGeometry(2, 2);
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const pass = (frag, uniforms) => {
    const m = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: frag, uniforms, depthTest: false, depthWrite: false, toneMapped: false });
    const s = new THREE.Scene();
    const q = new THREE.Mesh(quadGeo, m);
    q.frustumCulled = false;
    s.add(q);
    return { s, m };
  };
  const bright = pass(BRIGHT, { tScene: { value: sceneRT.texture }, uExposure: { value: 1 }, uThreshold: { value: opts.threshold ?? 1.1 } });
  const blur = pass(BLUR, { tIn: { value: null }, uDir: { value: new THREE.Vector2() } });
  const fin = pass(FINAL, {
    tScene: { value: sceneRT.texture }, tBloom: { value: null }, uTexel: { value: new THREE.Vector2(1 / size.x, 1 / size.y) },
    uExposure: { value: 1 }, uSharpen: { value: opts.sharpen ?? 0.35 }, uBloom: { value: opts.bloom ?? 0.08 },
    uVignette: { value: opts.vignette ?? 0.22 }, uGrain: { value: opts.grain ?? 0.03 }, uSeed: { value: 0 },
    toneMappingExposure: { value: 1 },
  });

  const api = {
    sceneRT,
    setSize(w, h) {
      sceneRT.setSize(w, h);
      const nw = Math.max(1, Math.floor(w / 4)), nh = Math.max(1, Math.floor(h / 4));
      bloomA.setSize(nw, nh); bloomB.setSize(nw, nh);
      fin.m.uniforms.uTexel.value.set(1 / w, 1 / h);
    },
    render(exposure, seed = 0) {
      const prevTM = renderer.toneMapping;
      renderer.toneMapping = THREE.NoToneMapping;
      renderer.setRenderTarget(sceneRT);
      renderer.render(scene, camera);
      // bloom: bright pass at quarter res, then a separable blur, twice
      bright.m.uniforms.uExposure.value = exposure;
      renderer.setRenderTarget(bloomA);
      renderer.render(bright.s, cam);
      for (let i = 0; i < 2; i++) {
        blur.m.uniforms.tIn.value = bloomA.texture; blur.m.uniforms.uDir.value.set(1 / bloomA.width, 0);
        renderer.setRenderTarget(bloomB); renderer.render(blur.s, cam);
        blur.m.uniforms.tIn.value = bloomB.texture; blur.m.uniforms.uDir.value.set(0, 1 / bloomA.height);
        renderer.setRenderTarget(bloomA); renderer.render(blur.s, cam);
      }
      fin.m.uniforms.tBloom.value = bloomA.texture;
      fin.m.uniforms.uExposure.value = exposure;
      fin.m.uniforms.uSeed.value = seed;
      renderer.setRenderTarget(null);
      renderer.render(fin.s, cam);
      renderer.toneMapping = prevTM;
    },
    uniforms: fin.m.uniforms,
  };
  return api;
}
