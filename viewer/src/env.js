import * as THREE from 'three';
import { SunLight } from 'three/addons/lights/SunLight.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { U } from './core/uniforms.js';

// Sky, sun and camera for Pearl St: real solar geometry for Boulder at a chosen date and
// local time, a physical sky (the three.js Sky addon) as background and as the image-based
// light, a cascaded sun shadow fitted to the view, and a camera-like exposure under AgX.
// Scene coordinates: x east, z north, y up.

export const BOULDER = { lat: 40.0192, lon: -105.2757, utcOffsetHours: -6 }; // MDT

const DEG = Math.PI / 180;

/** Solar elevation and azimuth (radians; azimuth clockwise from north) at a UTC date, NOAA formulas. */
export function solarPosition(dateUtc, lat = BOULDER.lat, lon = BOULDER.lon) {
  const jd = dateUtc.getTime() / 86400000 + 2440587.5;
  const T = (jd - 2451545) / 36525;
  const L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360;
  const M = (357.52911 + T * (35999.05029 - 0.0001537 * T)) * DEG;
  const C = (1.914602 - T * (0.004817 + 0.000014 * T)) * Math.sin(M) + (0.019993 - 0.000101 * T) * Math.sin(2 * M) + 0.000289 * Math.sin(3 * M);
  const lambda = (L0 + C) * DEG;
  const eps = (23.439291 - 0.0130042 * T) * DEG;
  const decl = Math.asin(Math.sin(eps) * Math.sin(lambda));
  const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
  const y = Math.tan(eps / 2) ** 2;
  const L0r = L0 * DEG;
  const eqt = 4 / DEG * (y * Math.sin(2 * L0r) - 2 * e * Math.sin(M) + 4 * e * y * Math.sin(M) * Math.cos(2 * L0r) - 0.5 * y * y * Math.sin(4 * L0r) - 1.25 * e * e * Math.sin(2 * M)); // minutes
  const minutesUtc = dateUtc.getUTCHours() * 60 + dateUtc.getUTCMinutes() + dateUtc.getUTCSeconds() / 60;
  const trueSolarMin = (minutesUtc + eqt + 4 * lon + 1440) % 1440;
  const ha = (trueSolarMin / 4 < 0 ? trueSolarMin / 4 + 180 : trueSolarMin / 4 - 180) * DEG;
  const latr = lat * DEG;
  const cosZ = Math.sin(latr) * Math.sin(decl) + Math.cos(latr) * Math.cos(decl) * Math.cos(ha);
  const zenith = Math.acos(Math.min(1, Math.max(-1, cosZ)));
  let az = Math.acos(Math.min(1, Math.max(-1, (Math.sin(latr) * Math.cos(zenith) - Math.sin(decl)) / (Math.cos(latr) * Math.sin(zenith)))));
  az = ha > 0 ? (az + Math.PI) % (2 * Math.PI) : (3 * Math.PI - az) % (2 * Math.PI);
  return { elevation: Math.PI / 2 - zenith, azimuth: az };
}

/** Local Boulder date and decimal hour to a UTC Date. date is 'MM-DD' (year 2026). */
export function localToUtc(dateStr, hourLocal) {
  const [mm, dd] = dateStr.split('-').map(Number);
  const h = Math.floor(hourLocal), m = Math.round((hourLocal - h) * 60);
  return new Date(Date.UTC(2026, mm - 1, dd, h - BOULDER.utcOffsetHours, m, 0));
}

/** Direction towards the sun in scene coordinates (x east, z north, y up). */
export function sunDirection(elevation, azimuth, out = new THREE.Vector3()) {
  const ch = Math.cos(elevation);
  return out.set(Math.sin(azimuth) * ch, Math.sin(elevation), Math.cos(azimuth) * ch);
}

/**
 * Environment: sky + sun + exposure. opts: {date: 'MM-DD', hour: 16.75, quality: 'med'|'high'}.
 * Call env.update(camera) each frame (the sun's shadow cascades follow the camera).
 */
export function createEnvironment(renderer, scene, opts = {}) {
  const q = opts.quality === 'high' ? { shadow: 4096, far: 450 } : opts.quality === 'low' ? { shadow: 1024, far: 250 } : { shadow: 2048, far: 350 };

  const sky = new Sky();
  sky.scale.setScalar(20000);
  const su = sky.material.uniforms;
  // dry Front Range air: low turbidity, a little haze near the horizon
  su.turbidity.value = 2.2;
  su.rayleigh.value = 1.1;
  su.mieCoefficient.value = 0.004;
  su.mieDirectionalG.value = 0.8;
  scene.add(sky);

  const sun = new SunLight(0xffffff, 3);
  sun.castShadow = true;
  sun.shadow.mapSize.set(q.shadow, q.shadow);
  sun.shadow.camera.near = 0.5;
  sun.shadow.camera.far = q.far;
  sun.shadow.bias = -0.0003;
  sun.shadow.normalBias = 0.03;
  sun.shadow.radius = 2;
  scene.add(sun);

  const pmrem = new THREE.PMREMGenerator(renderer);
  pmrem.compileEquirectangularShader();
  const skyScene = new THREE.Scene();
  let envRT = null;

  const state = { elevation: 0, azimuth: 0, sunDir: new THREE.Vector3(), date: opts.date || '04-17', hour: opts.hour ?? 16.75, exposure: 1 };

  function setTime(date = state.date, hour = state.hour) {
    state.date = date; state.hour = hour;
    const { elevation, azimuth } = solarPosition(localToUtc(date, hour));
    state.elevation = elevation; state.azimuth = azimuth;
    sunDirection(elevation, azimuth, state.sunDir);
    su.sunPosition.value.copy(state.sunDir);
    sun.position.copy(state.sunDir).multiplyScalar(500);
    sun.visible = elevation > 0.5 * DEG;
    // direct sun through the atmosphere: Kasten-Young air mass, a dry clear sky's extinction
    const el = Math.max(elevation, 0);
    const m = 1 / (Math.sin(el) + 0.50572 * Math.pow(el / DEG + 6.07995, -1.6364));
    const tr = Math.exp(-0.075 * m), tg = Math.exp(-0.105 * m), tb = Math.exp(-0.17 * m);
    sun.color.setRGB(tr, tg, tb, THREE.LinearSRGBColorSpace);
    sun.intensity = 3.4 * (opts.sunScale ?? 1) * (sun.visible ? 1 : 0);
    U.uSunDir.value.copy(state.sunDir);
    U.uSunColor.value.copy(sun.color).multiplyScalar(sun.intensity);
    U.uNight.value = THREE.MathUtils.clamp(-elevation / (6 * DEG), 0, 1);
    // image-based light from the sky dome
    if (envRT) envRT.dispose();
    skyScene.add(sky);
    envRT = pmrem.fromScene(skyScene, 0, 10, 30000);
    scene.add(sky);              // (the dome itself draws the background)
    scene.environment = envRT.texture;
    // the Sky dome is bright in its own units: at 1.0 the sky light alone put shaded walls at
    // 0.22 linear and swamped the sun; 0.2 gives the photographs' sun-to-shade ratio (~3.5:1)
    scene.environmentIntensity = opts.envIntensity ?? 0.2;
    // exposure: a sunny-16 anchor lifted for the shade, falling with the sun (the photos of
    // the street expose for the shaded facades and let the sky clip)
    const Eh = Math.max(Math.sin(el), 0.05);
    state.exposure = (0.45 / Math.pow(Eh, 0.45)) * (opts.exposureScale ?? 1);
    renderer.toneMappingExposure = state.exposure;
  }

  setTime();

  return {
    sun, sky, state, setTime,
    update(camera) {
      // SunLight's cascades fit the view camera; nothing to do per frame beyond keeping the
      // light's direction (the position) current
      U.uCameraPos.value.copy(camera.position);
    },
    dispose() { if (envRT) envRT.dispose(); pmrem.dispose(); },
  };
}
