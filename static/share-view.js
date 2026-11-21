const MAX_LENGTH = 100000;
const vector = value => Array.isArray(value) && value.length === 3
  && value.every(n => Number.isFinite(n) && Math.abs(n) <= 1e11);
const name = value => value === null || (typeof value === 'string' && value.length <= 300);
const bools = (value, length) => Array.isArray(value) && value.length === length && value.every(v => typeof v === 'boolean');

export function validateSharedView(value) {
  const invalid = () => { throw new Error('Invalid or unsupported shared view'); };
  if (!value || value.version !== 1 || !value.settings || !value.camera) invalid();
  const s = value.settings, c = value.camera;
  if (!['galactic', 'equatorial'].includes(s.frame)
    || !['spectral', 'sovereignty', 'planets'].includes(s.colourMode)
    || !['hyg', 'gaia', 'both'].includes(s.loadSource)
    || ![1000, 2000, 5000].includes(s.loadRadiusPc)
    || typeof s.filter !== 'string' || s.filter.length > 50000
    || typeof s.distance !== 'string' || (s.distance !== '' && (!Number.isFinite(Number(s.distance)) || Number(s.distance) < 0))
    || !s.toggles || typeof s.toggles !== 'object' || Array.isArray(s.toggles)
    || !Object.values(s.toggles).every(v => typeof v === 'boolean')
    || !bools(s.spectralClasses, 8) || !bools(s.nebulaTypes, 5) || !bools(s.planetCategories, 4)
    || !Array.isArray(s.hiddenSovereignties) || s.hiddenSovereignties.length > 10000
    || !s.hiddenSovereignties.every(v => typeof v === 'string' && v.length <= 300)
    || !vector(c.position) || !vector(c.target)
    || Math.hypot(...c.position.map((v, i) => v - c.target[i])) <= 1e-6
    || !Number.isFinite(c.fov) || c.fov < 1 || c.fov > 170
    || !name(c.centre) || !name(value.selected) || !name(value.lastStarCentre)) invalid();
  const settings = Object.fromEntries(['frame', 'colourMode', 'loadSource', 'loadRadiusPc',
    'filter', 'distance', 'toggles', 'spectralClasses', 'nebulaTypes', 'planetCategories',
    'hiddenSovereignties'].map(key => [key, s[key]]));
  if (s.hiddenSpecialObjects !== undefined) {
    if (!Array.isArray(s.hiddenSpecialObjects) || s.hiddenSpecialObjects.length > 10000
      || !s.hiddenSpecialObjects.every(v => typeof v === 'string' && v.length <= 300)) invalid();
    settings.hiddenSpecialObjects = [...s.hiddenSpecialObjects];
  }
  const result = {
    version: 1, settings,
    camera: { position: [...c.position], target: [...c.target], centre: c.centre, fov: c.fov },
    selected: value.selected, lastStarCentre: value.lastStarCentre,
  };
  if (value.constellations !== undefined) {
    const c = value.constellations;
    if (!c || typeof c.pattern !== 'string' || !/^[a-z-]{1,40}$/.test(c.pattern)
      || typeof c.observer !== 'string' || !c.observer.length || !name(c.observer)
      || typeof c.overlay !== 'boolean') invalid();
    result.constellations = { pattern: c.pattern, observer: c.observer, overlay: c.overlay };
  }
  if (value.motion !== undefined) {
    const m = value.motion;
    if (!m || !Number.isFinite(m.years) || Math.abs(m.years) > 10000
      || typeof m.partial !== 'boolean') invalid();
    result.motion = { years: m.years, partial: m.partial };
  }
  if (value.observer !== undefined) {
    const o = value.observer;
    if (!o || typeof o.name !== 'string' || !name(o.name) || !vector(o.direction)
      || Math.hypot(...o.direction) < 1e-6 || !Number.isFinite(o.magnitude)
      || o.magnitude < -2 || o.magnitude > 15 || !Number.isFinite(o.fov) || o.fov < 1 || o.fov > 170) invalid();
    result.observer = { name: o.name, direction: [...o.direction], magnitude: o.magnitude, fov: o.fov };
  }
  if (value.system !== undefined) {
    const sys = value.system;
    if (!sys || typeof sys.name !== 'string' || !name(sys.name)
      || typeof sys.body !== 'string' || !name(sys.body) || !name(sys.focus)
      || !['enlarged', 'true'].includes(sys.scale) || !vector(sys.position) || !vector(sys.target)
      || Math.hypot(...sys.position.map((v, i) => v - sys.target[i])) <= 1e-12
      || typeof sys.dataset !== 'string' || !sys.dataset.length || sys.dataset.length > 300) invalid();
    result.system = { name: sys.name, body: sys.body, focus: sys.focus, scale: sys.scale,
      position: [...sys.position], target: [...sys.target], dataset: sys.dataset };
  }
  if (result.observer && result.system) invalid();
  return result;
}

export function sharedViewFromHash(hash) {
  const query = new URLSearchParams(hash.replace(/^#/, ''));
  if (!query.has('view')) return null;
  const text = query.get('view');
  if (text.length > MAX_LENGTH) throw new Error('Shared view is too large');
  return validateSharedView(JSON.parse(text));
}

export function sharedViewUrl(base, state) {
  const text = JSON.stringify(validateSharedView(state));
  if (text.length > MAX_LENGTH) throw new Error('View is too large to share; simplify its filters');
  const url = new URL(base);
  url.hash = new URLSearchParams({ view: text }).toString();
  return url.href;
}
