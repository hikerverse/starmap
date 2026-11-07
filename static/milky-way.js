import * as THREE from 'three';
import { ARM_REFERENCE_RADIUS_KPC, SPIRAL_ARMS } from './milky-way-model.js';

const VERTEX = /* glsl */`
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const DISK_FRAGMENT = /* glsl */`
  varying vec2 vUv;
  uniform vec4 uArmShape[6];
  uniform vec4 uArmExtent[6];
  uniform float uRadiusScale;

  float hash(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
  }

  float noise(vec2 p) {
    vec2 cell = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(cell), hash(cell + vec2(1.0, 0.0)), f.x),
      mix(hash(cell + vec2(0.0, 1.0)), hash(cell + vec2(1.0)), f.x), f.y);
  }

  float clouds(vec2 p) {
    float value = 0.0, weight = 0.5;
    for (int i = 0; i < 5; i++) {
      value += weight * noise(p);
      p = mat2(1.6, -1.2, 1.2, 1.6) * p + vec2(7.1, 3.4);
      weight *= 0.5;
    }
    return value;
  }

  void main() {
    vec2 p = (vUv * 2.0 - 1.0) * 15.0;
    float radius = length(p);
    float beta = atan(p.y, -p.x);
    float cloud = clouds(p * 2.2);
    float fine = noise(p * 28.0);
    float spiral = 0.0, armHaze = 0.0, dust = 0.0;
    for (int i = 0; i < 6; i++) {
      vec4 shape = uArmShape[i], extent = uArmExtent[i];
      float pitch = beta <= shape.x ? shape.z : shape.w;
      float armRadius = shape.y * exp(-(beta - shape.x) * tan(pitch)) * uRadiusScale;
      float width = max(0.06, extent.z + 0.042 * (armRadius / uRadiusScale - shape.y)) * uRadiusScale;
      float distance = (radius - armRadius) * cos(pitch);
      // Only a short, fading extension outside the parallax coverage; never wrap arms around the far side.
      float coverage = smoothstep(extent.x - extent.w, extent.x, beta)
        * (1.0 - smoothstep(extent.y, extent.y + extent.w, beta));
      spiral = max(spiral, exp(-0.5 * pow(distance / width, 2.0)) * coverage);
      armHaze = max(armHaze, exp(-0.5 * pow(distance / (width * 1.8), 2.0)) * coverage);
      dust = max(dust, exp(-0.5 * pow((distance - width * 0.65) / (width * 0.22), 2.0)) * coverage);
    }
    dust *= smoothstep(0.3, 0.65, cloud);
    float edge = 1.0 - smoothstep(11.0, 15.0, radius + (cloud - 0.5) * 0.8);
    float disk = exp(-radius / 9.0) * edge;
    float clumps = smoothstep(0.38, 0.76, cloud);
    float stars = pow(noise(p * 65.0), 12.0) * 5.0;
    float gas = spiral * smoothstep(0.50, 0.68, clouds(p * 6.0 + 41.0));
    float density = disk * (0.12 + 0.24 * armHaze + spiral * (0.55 + 1.4 * clumps)
      + stars * (0.12 + spiral * 0.9)) * (1.0 - 0.82 * dust);
    vec3 tint = mix(vec3(0.40, 0.43, 0.57), vec3(0.73, 0.80, 1.0),
      clamp(spiral * (0.45 + clumps) + stars, 0.0, 1.0));
    tint = mix(tint, vec3(1.0, 0.34, 0.51), clamp(gas * 1.4, 0.0, 0.65));
    tint *= 0.85 + 0.3 * fine;
    gl_FragColor = vec4(tint, min(density, 1.0));
  }`;

const FRAGMENT = /* glsl */`
  uniform mat4 uCamera;
  uniform mat4 uProjectionInverse;
  uniform vec3 uCentre;
  uniform float uOpacity;
  uniform sampler2D uDisk;
  uniform float uCentreAzimuth;
  varying vec2 vUv;

  vec4 field(vec3 p) {
    p.xy = mat2(cos(uCentreAzimuth), -sin(uCentreAzimuth),
      sin(uCentreAzimuth), cos(uCentreAzimuth)) * p.xy;
    float radius = length(p.xy);
    vec4 detail = texture2D(uDisk, p.xy / 30.0 + 0.5);
    float disk = detail.a * exp(-pow(p.z / (0.18 + radius * 0.006), 2.0));
    float barAngle = 0.45;
    vec2 bar = mat2(cos(barAngle), -sin(barAngle), sin(barAngle), cos(barAngle)) * p.xy;
    float barGlow = exp(-dot(bar / vec2(2.8, 0.75), bar / vec2(2.8, 0.75))
      - pow(p.z / 0.4, 2.0));
    float bulge = exp(-dot(p / vec3(1.0, 1.0, 0.65), p / vec3(1.0, 1.0, 0.65)));
    float halo = exp(-dot(p / vec3(6.0, 6.0, 1.6), p / vec3(6.0, 6.0, 1.6)));
    vec3 emission = disk * detail.rgb + 0.45 * barGlow * vec3(1.0, 0.72, 0.40)
      + 0.75 * bulge * vec3(1.0, 0.88, 0.65) + 0.012 * halo * vec3(0.55, 0.58, 0.72);
    return vec4(emission, disk + 0.45 * barGlow + 0.75 * bulge + 0.012 * halo);
  }

  void main() {
    vec4 view = uProjectionInverse * vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
    vec3 ray = normalize(mat3(uCamera) * (view.xyz / view.w));
    vec3 origin = (uCamera[3].xyz - uCentre) / 1000.0;
    vec3 safeRay = vec3(
      abs(ray.x) < 0.000001 ? (ray.x < 0.0 ? -0.000001 : 0.000001) : ray.x,
      abs(ray.y) < 0.000001 ? (ray.y < 0.0 ? -0.000001 : 0.000001) : ray.y,
      abs(ray.z) < 0.000001 ? (ray.z < 0.0 ? -0.000001 : 0.000001) : ray.z);
    vec3 a = (-vec3(15.0, 15.0, 3.0) - origin) / safeRay;
    vec3 b = (vec3(15.0, 15.0, 3.0) - origin) / safeRay;
    vec3 near = min(a, b), far = max(a, b);
    float start = max(0.0, max(near.x, max(near.y, near.z)));
    float end = min(far.x, min(far.y, far.z));
    if (end <= start) { gl_FragColor = vec4(0.0); return; }
    float stepSize = (end - start) / 96.0;
    vec3 colour = vec3(0.0);
    float alpha = 0.0;
    for (int i = 0; i < 96; i++) {
      vec4 density = field(origin + ray * (start + (float(i) + 0.5) * stepSize));
      float glow = 1.0 - exp(-density.a * stepSize * 4.0 * uOpacity);
      colour += (1.0 - alpha) * glow * density.rgb / max(density.a, 0.00001);
      alpha += (1.0 - alpha) * glow;
    }
    gl_FragColor = vec4(colour / max(alpha, 0.00001), alpha);
  }`;

export function createMilkyWay(renderer, scene) {
  const geometry = new THREE.PlaneGeometry(2, 2);
  const target = new THREE.WebGLRenderTarget(1, 1, { depthBuffer: false, stencilBuffer: false });
  const diskTarget = new THREE.WebGLRenderTarget(1024, 1024, { depthBuffer: false, stencilBuffer: false });
  const diskMaterial = new THREE.ShaderMaterial({
    vertexShader: VERTEX, fragmentShader: DISK_FRAGMENT, depthTest: false, depthWrite: false,
    uniforms: {
      uArmShape: { value: SPIRAL_ARMS.map((arm) => new THREE.Vector4(
        THREE.MathUtils.degToRad(arm.kink), arm.radius,
        THREE.MathUtils.degToRad(arm.pitchBefore), THREE.MathUtils.degToRad(arm.pitchAfter))) },
      uArmExtent: { value: SPIRAL_ARMS.map((arm) => new THREE.Vector4(
        THREE.MathUtils.degToRad(arm.minBeta), THREE.MathUtils.degToRad(arm.maxBeta), arm.width,
        THREE.MathUtils.degToRad(arm.name === 'Local (Orion)' ? 5 : 15))) },
      uRadiusScale: { value: 8.178 / ARM_REFERENCE_RADIUS_KPC },
    },
  });
  const diskScene = new THREE.Scene();
  const disk = new THREE.Mesh(geometry, diskMaterial);
  disk.frustumCulled = false;
  diskScene.add(disk);
  let diskReady = false;
  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX, fragmentShader: FRAGMENT,
    uniforms: {
      uCamera: { value: new THREE.Matrix4() },
      uProjectionInverse: { value: new THREE.Matrix4() },
      uCentre: { value: new THREE.Vector3(8178, 0, 0) },
      uCentreAzimuth: { value: 0 },
      uOpacity: { value: 0 },
      uDisk: { value: diskTarget.texture },
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
  composite.renderOrder = -20;
  composite.visible = false;
  scene.add(composite);
  const size = new THREE.Vector2();
  const canonicalCamera = new THREE.Matrix4();
  const lastCamera = new THREE.Matrix4();
  const lastProjection = new THREE.Matrix4();
  let dirty = true;
  return {
    setCentre(position) {
      material.uniforms.uCentre.value.copy(position);
      material.uniforms.uCentreAzimuth.value = Math.atan2(position.y, position.x);
      diskMaterial.uniforms.uRadiusScale.value = Math.hypot(position.x, position.y) / (1000 * ARM_REFERENCE_RADIUS_KPC);
      diskReady = false;
      dirty = true;
    },
    update(camera, displayToGalactic, viewDistance, enabled) {
      const opacity = 0.65 * THREE.MathUtils.smoothstep(viewDistance, 500, 6000);
      composite.visible = enabled && opacity > 0;
      if (!composite.visible) return;
      renderer.getSize(size);
      const mobile = window.matchMedia('(pointer: coarse), (max-width: 600px)').matches;
      const scale = Math.min(mobile ? 0.4 : 0.65, 800 / size.x, 450 / size.y);
      const width = Math.max(1, Math.round(size.x * scale)), height = Math.max(1, Math.round(size.y * scale));
      if (target.width !== width || target.height !== height) { target.setSize(width, height); dirty = true; }
      camera.updateMatrixWorld();
      canonicalCamera.copy(displayToGalactic).multiply(camera.matrixWorld);
      if (!dirty && lastCamera.equals(canonicalCamera) && lastProjection.equals(camera.projectionMatrix)
        && material.uniforms.uOpacity.value === opacity) return;
      material.uniforms.uCamera.value.copy(canonicalCamera);
      material.uniforms.uProjectionInverse.value.copy(camera.projectionMatrixInverse);
      material.uniforms.uOpacity.value = opacity;
      const previous = renderer.getRenderTarget();
      // Bake cloud detail once; camera movement only samples the resulting texture.
      if (!diskReady) {
        renderer.setRenderTarget(diskTarget);
        renderer.render(diskScene, volumeCamera);
        diskReady = true;
      }
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
      diskMaterial.dispose();
      diskTarget.dispose();
    },
  };
}
