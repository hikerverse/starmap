export const SUBSPACE_VERSION = 1;
export const SUBSPACE_RADIUS_PC = 1200;

export function seedOffset(seed) {
  let state = seed >>> 0;
  return Array.from({ length: 3 }, () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296 * 100;
  });
}

// Galactic parsecs; keep this reference evaluator in sync with field() in the shader.
export function disturbanceAt(position, seed) {
  const [x, y, z] = position;
  const radius = Math.hypot(x, y, z);
  if (radius >= SUBSPACE_RADIUS_PC) return 0;
  const o = seedOffset(seed);
  const wx = x + 17 * Math.sin(y * 0.023 + o[0]) + 11 * Math.sin(z * 0.031 + o[1]);
  const wy = y + 19 * Math.sin(z * 0.019 + o[1]) + 9 * Math.sin(x * 0.027 + o[2]);
  const wz = z + 15 * Math.sin(x * 0.021 + o[2]) + 13 * Math.sin(y * 0.029 + o[0]);
  const a = Math.sin(wx * 0.09 + o[0]) + 0.45 * Math.sin(wz * 0.16 + wy * 0.05 + o[2]);
  const b = Math.sin(wy * 0.09 + o[1]) + 0.45 * Math.sin(wx * 0.13 - wz * 0.07 + o[0]);
  const c = Math.sin((wy + wz * 0.35) * 0.075 + o[2]) + 0.4 * Math.sin(wx * 0.11 + wy * 0.08 + o[1]);
  const d = Math.sin((wz - wx * 0.4) * 0.075 + o[0]) + 0.4 * Math.sin(wy * 0.14 - wz * 0.06 + o[2]);
  const broad = 0.5 + 0.5 * Math.sin(x * 0.007 + o[0]) * Math.sin(y * 0.009 + o[1]) * Math.sin(z * 0.006 + o[2]);
  const width = 0.075 + 0.065 * broad;
  const strands = Math.max(Math.exp(-(a * a + b * b) / (width * width)),
    Math.exp(-(c * c + d * d) / (width * width)) * 0.85);
  const detail = 0.8 + 0.2 * Math.sin(wx * 1.7 + Math.sin(wz * 1.1));
  const t = Math.max(0, Math.min(1, (radius - 1050) / 150));
  return (0.008 + 0.018 * broad + strands * (0.25 + 0.72 * broad) * detail) * (1 - t * t * (3 - 2 * t));
}
