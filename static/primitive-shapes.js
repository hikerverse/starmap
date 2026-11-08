export const SHAPE_KINDS = ['sphere', 'box', 'cylinder', 'cone', 'torus', 'plane'];

export function validateShape(value) {
  if (!value || typeof value !== 'object' || !SHAPE_KINDS.includes(value.kind)) {
    throw new Error('Choose a supported primitive shape.');
  }
  if (typeof value.id !== 'string' || !value.id) throw new Error('Shape ID is missing.');
  if (typeof value.label !== 'string' || value.label.length > 120) {
    throw new Error('Labels must be at most 120 characters.');
  }
  for (const key of ['size', 'position', 'rotation']) {
    if (!Array.isArray(value[key]) || value[key].length !== 3 || !value[key].every(Number.isFinite)) {
      throw new Error(`Shape ${key} must contain three finite numbers.`);
    }
  }
  if (value.size.some((n) => n < 0.000001)) throw new Error('Each dimension must be at least 0.000001 pc.');
  if (typeof value.colour !== 'string' || !/^#[0-9a-f]{6}$/i.test(value.colour)) {
    throw new Error('Choose a valid hex colour.');
  }
  if (!Number.isFinite(value.transparency) || value.transparency < 0 || value.transparency > 100) {
    throw new Error('Transparency must be between 0 and 100%.');
  }
  if (typeof value.wireframe !== 'boolean') throw new Error('Wireframe must be on or off.');
  return {
    id: value.id, kind: value.kind, label: value.label, colour: value.colour,
    size: [...value.size], position: [...value.position], rotation: [...value.rotation],
    transparency: value.transparency, wireframe: value.wireframe,
  };
}
