// Facade decal: the canvas that paints a wall's windows, doors, trims and signage (with a
// transparent background) composited over a library material's baked surface. Chained after
// the surface patch's onBeforeCompile: where the decal is opaque the albedo is the decal's,
// the roughness is the decal's (glass), and the baked normal is flattened.
//
// The wall's UVs are metres (u along the wall, v up); the decal covers 0..size.

export function attachDecal(mat, texture, size, rough = 0.35) {
  const prevBefore = mat.onBeforeCompile;
  const prevKey = mat.customProgramCacheKey;
  mat.onBeforeCompile = function (shader, renderer) {
    if (prevBefore) prevBefore.call(this, shader, renderer);
    shader.uniforms.uDecal = { value: texture };
    shader.uniforms.uWallSize = { value: size };
    shader.uniforms.uDecalRough = { value: rough };
    const hasSurf = shader.fragmentShader.includes('diffuseColor.rgb *= sfAlb;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform sampler2D uDecal;\nuniform vec2 uWallSize;\nuniform float uDecalRough;\nfloat sfDecalA = 0.0;\n');
    if (hasSurf) {
      shader.fragmentShader = shader.fragmentShader
        .replace('diffuseColor.rgb *= sfAlb;',
          'diffuseColor.rgb *= sfAlb;\n  { vec4 sfDc = texture(uDecal, vMapUv / uWallSize); sfDecalA = sfDc.a; diffuseColor.rgb = mix(diffuseColor.rgb, sfDc.rgb, sfDecalA); }')
        .replace('float roughnessFactor = clamp(roughness * sfRough, 0.0, 1.0);',
          'float roughnessFactor = mix(clamp(roughness * sfRough, 0.0, 1.0), uDecalRough, sfDecalA);')
        .replace('normal = normalize(tbn * vec3(sfN, sqrt(max(1.0 - dot(sfN, sfN), 1e-4))));',
          'normal = normalize(mix(normalize(tbn * vec3(sfN, sqrt(max(1.0 - dot(sfN, sfN), 1e-4)))), nonPerturbedNormal, sfDecalA));');
    } else {
      // a flat (fallback) material: composite over its colour
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <map_fragment>',
          '#include <map_fragment>\n  { vec4 sfDc = texture(uDecal, vUv / uWallSize); sfDecalA = sfDc.a; diffuseColor.rgb = mix(diffuseColor.rgb, sfDc.rgb, sfDecalA); }')
        .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\n  roughnessFactor = mix(roughnessFactor, uDecalRough, sfDecalA);');
    }
  };
  mat.customProgramCacheKey = function () { return (prevKey ? prevKey.call(this) : '') + 'Dc'; };
  mat.needsUpdate = true;
  return mat;
}
