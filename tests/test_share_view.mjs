import assert from 'node:assert/strict';
import { validateSharedView, sharedViewFromHash, sharedViewUrl } from '../static/share-view.js';

const state = {
  version: 1,
  settings: {
    frame: 'galactic', colourMode: 'spectral', loadSource: 'hyg', loadRadiusPc: 1000,
    filter: '{}', distance: '', toggles: { 'toggle-stars': true },
    spectralClasses: Array(8).fill(true), nebulaTypes: Array(5).fill(true),
    planetCategories: [false, true, true, true],
    hiddenSovereignties: ['Test & group'],
    shapes: ['not shared'], guide: { open: true },
  },
  camera: { position: [1, 2, 3], target: [0, 0, 0], centre: 'Sol', fov: 55 },
  selected: 'α Centauri A & B', lastStarCentre: 'Sol',
};
const cleaned = validateSharedView(state);
assert.equal(cleaned.settings.shapes, undefined);
assert.equal(cleaned.settings.guide, undefined);
const url = sharedViewUrl('https://example.test/map?test=1#old', state);
assert.equal(new URL(url).search, '?test=1');
assert.deepEqual(sharedViewFromHash(new URL(url).hash), cleaned);
assert.equal(sharedViewFromHash('#section'), null);
for (const overrides of [
  { version: 2 }, { camera: { ...state.camera, position: [NaN, 0, 0] } },
  { settings: { ...state.settings, loadSource: 'invalid' } },
  { settings: { ...state.settings, loadRadiusPc: 999999 } },
  { settings: { ...state.settings, spectralClasses: [true] } },
  { settings: { ...state.settings, planetCategories: [] } },
  { motion: { years: 10001, partial: false } },
  { motion: { years: 10, partial: 'false' } },
  { constellations: { pattern: 'orion', observer: null, overlay: false } },
  { constellations: { pattern: '<script>', observer: 'Sol', overlay: true } },
  { constellations: { pattern: 'orion', observer: 'Sol', overlay: 'true' } },
  { camera: { ...state.camera, position: [0, 0, 0] } },
  { observer: { name: 'Sol', direction: [0, 0, 0], magnitude: 6, fov: 55 } },
  { system: { name: 'Sol', body: 'Earth', focus: 'Earth', scale: 'bad',
    position: [1, 0, 0], target: [0, 0, 0] } },
  { system: { name: 'Sol', body: 'Earth', focus: 'Earth', scale: 'true',
    position: [1, 0, 0], target: [0, 0, 0] } },
]) assert.throws(() => validateSharedView({ ...state, ...overrides }));
assert.throws(() => sharedViewFromHash('#view=%7Bbad'));
assert.throws(() => sharedViewFromHash('#view=' + 'x'.repeat(100001)));
for (const extra of [
  { constellations: { pattern: 'orion', observer: 'Proxima Centauri', overlay: true } },
  { motion: { years: -5000, partial: true } },
  { observer: { name: 'Sol', direction: [0, 0, -1], magnitude: 6.5, fov: 40 } },
  { system: { name: 'Sol', body: 'Moon', focus: 'Moon', scale: 'true',
    position: [1, 0, 0], target: [0, 0, 0], dataset: 'test' } },
]) {
  const view = { ...state, ...extra };
  assert.deepEqual(sharedViewFromHash(new URL(sharedViewUrl('https://example.test/', view)).hash),
    validateSharedView(view));
}
console.log('Shared view tests passed.');
