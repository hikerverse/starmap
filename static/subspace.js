import * as THREE from 'three';
import { seedOffset, SUBSPACE_VERSION } from './subspace-field.js';

const FRAGMENT = /* glsl */`
  precision highp float;
  uniform mat4 uCamera;
  uniform mat4 uProjectionInverse;
  uniform vec3 uOffset;
  uniform float uOpacity;
  varying vec2 vUv;
  float field(vec3 p, float footprint) {
    vec3 w = p + vec3(
      17.0 * sin(p.y * 0.023 + uOffset.x) + 11.0 * sin(p.z * 0.031 + uOffset.y),
      19.0 * sin(p.z * 0.019 + uOffset.y) + 9.0 * sin(p.x * 0.027 + uOffset.z),
      15.0 * sin(p.x * 0.021 + uOffset.z) + 13.0 * sin(p.y * 0.029 + uOffset.x));
    vec2 ab = sin(w.xy * 0.09 + uOffset.xy)
      + 0.45 * sin(vec2(w.z * 0.16 + w.y * 0.05, w.x * 0.13 - w.z * 0.07) + uOffset.zx);
    vec2 cd = sin(vec2(w.y + w.z * 0.35, w.z - w.x * 0.4) * 0.075 + uOffset.zx)
      + 0.4 * sin(vec2(w.x * 0.11 + w.y * 0.08, w.y * 0.14 - w.z * 0.06) + uOffset.yz);
    float broad = 0.5 + 0.5 * sin(p.x * 0.007 + uOffset.x) * sin(p.y * 0.009 + uOffset.y) * sin(p.z * 0.006 + uOffset.z);
    float width = 0.075 + 0.065 * broad;
    // Broaden sub-pixel / sub-step strands, preserving their approximate integrated density.
    float filtered = width * width + footprint * footprint * 0.0025;
    float strands = max(exp(-dot(ab, ab) / filtered), 0.85 * exp(-dot(cd, cd) / filtered)) * width * width / filtered;
    float detail = mix(0.8 + 0.2 * sin(w.x * 1.7 + sin(w.z * 1.1)), 0.8, clamp(footprint / 3.0, 0.0, 1.0));
    return (0.008 + 0.018 * broad + strands * (0.25 + 0.72 * broad) * detail)
      * (1.0 - smoothstep(1050.0, 1200.0, length(p)));
  }
  void main() {
    vec4 view = uProjectionInverse * vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
    vec3 ray = normalize(mat3(uCamera) * (view.xyz / view.w));
    vec3 origin = uCamera[3].xyz;
    float b = dot(origin, ray);
    // Cross-product form avoids subtracting two enormous squared distances when zoomed far out.
    vec3 perpendicular = cross(origin, ray);
    float discriminant = 1440000.0 - dot(perpendicular, perpendicular);
    if (discriminant <= 0.0) { gl_FragColor = vec4(0.0); return; }
    float start = max(0.0, -b - sqrt(discriminant));
    float end = -b + sqrt(discriminant);
    if (end <= start) { gl_FragColor = vec4(0.0); return; }
    vec3 colour = vec3(0.0);
    float alpha = 0.0;
    for (int i = 0; i < 192; i++) {
      float u = (float(i) + 0.5) / 192.0;
      float distance = mix(start, end, u * u);
      float stepSize = (end - start) * 2.0 * u / 192.0;
      vec3 p = origin + ray * distance;
      float density = field(p, stepSize);
      float emission = density * 0.004 + max(0.0, density - 0.018) * 0.25;
      float glow = 1.0 - exp(-emission * stepSize * uOpacity);
      vec3 tint = mix(vec3(0.23, 0.16, 0.48), vec3(0.35, 0.72, 0.95), smoothstep(0.018, 0.16, density));
      colour += (1.0 - alpha) * glow * tint;
      alpha += (1.0 - alpha) * glow;
      if (alpha > 0.96) break;
    }
    gl_FragColor = vec4(colour / max(alpha, 0.00001), alpha);
  }`;

const VERTEX = /* glsl */`
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

export function createSubspace(renderer, scene) {
  const geometry = new THREE.PlaneGeometry(2, 2);
  const target = new THREE.WebGLRenderTarget(1, 1, { depthBuffer: false, stencilBuffer: false });
  target.texture.minFilter = target.texture.magFilter = THREE.LinearFilter;
  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX, fragmentShader: FRAGMENT,
    uniforms: {
      uCamera: { value: new THREE.Matrix4() },
      uProjectionInverse: { value: new THREE.Matrix4() },
      uOffset: { value: new THREE.Vector3() }, uOpacity: { value: 0.6 },
    },
    depthTest: false, depthWrite: false,
  });
  const volumeScene = new THREE.Scene();
  const volumeCamera = new THREE.Camera();
  const volume = new THREE.Mesh(geometry, material);
  volume.frustumCulled = false;
  volumeScene.add(volume);
  const composite = new THREE.Mesh(geometry, new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: 'uniform sampler2D uMap; varying vec2 vUv; void main() { gl_FragColor = texture2D(uMap, vUv); }',
    uniforms: { uMap: { value: target.texture } },
    transparent: true, depthTest: false, depthWrite: false,
  }));
  composite.frustumCulled = false;
  composite.renderOrder = -10;
  composite.visible = false;
  scene.add(composite);
  let settings = { enabled: false, seed: 12345, opacity: 0.6, generation_version: SUBSPACE_VERSION };
  let dirty = true;
  const lastCamera = new THREE.Matrix4();
  const lastProjection = new THREE.Matrix4();
  const size = new THREE.Vector2();
  const canonicalCamera = new THREE.Matrix4();
  return {
    get settings() { return { ...settings }; },
    configure(next) {
      if (next.generation_version !== SUBSPACE_VERSION || !Number.isInteger(next.seed) || next.seed < 0 || next.seed > 4294967295
        || !Number.isFinite(next.opacity) || next.opacity < 0 || next.opacity > 1 || typeof next.enabled !== 'boolean') {
        throw new Error('Invalid subspace field settings (expected generation version 1, uint32 seed, and opacity 0-1).');
      }
      settings = { ...next };
      material.uniforms.uOffset.value.fromArray(seedOffset(settings.seed));
      material.uniforms.uOpacity.value = settings.opacity;
      composite.visible = settings.enabled && settings.opacity > 0;
      dirty = true;
    },
    update(camera, displayToGalactic) {
      if (!composite.visible) return;
      renderer.getSize(size);
      const mobile = window.matchMedia('(pointer: coarse), (max-width: 600px)').matches;
      const scale = Math.min(mobile ? 0.25 : 0.4, 480 / size.x, 270 / size.y);
      const width = Math.max(1, Math.round(size.x * scale)), height = Math.max(1, Math.round(size.y * scale));
      if (target.width !== width || target.height !== height) { target.setSize(width, height); dirty = true; }
      camera.updateMatrixWorld();
      canonicalCamera.copy(displayToGalactic).multiply(camera.matrixWorld);
      if (!dirty && lastCamera.equals(canonicalCamera) && lastProjection.equals(camera.projectionMatrix)) return;
      material.uniforms.uCamera.value.copy(canonicalCamera);
      material.uniforms.uProjectionInverse.value.copy(camera.projectionMatrixInverse);
      const previous = renderer.getRenderTarget();
      renderer.setRenderTarget(target);
      renderer.render(volumeScene, volumeCamera);
      renderer.setRenderTarget(previous);
      lastCamera.copy(canonicalCamera);
      lastProjection.copy(camera.projectionMatrix);
      dirty = false;
    },
    dispose() {
      scene.remove(composite);
      geometry.dispose();
      material.dispose();
      composite.material.dispose();
      target.dispose();
    },
  };
}
