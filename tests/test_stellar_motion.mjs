import assert from 'node:assert/strict';
import { validateMotion, applyMotionPositions, motionDescription, KM_S_TO_PC_YR } from '../static/stellar-motion.js';

const full = [1e-5, -2e-5, 3e-5, 1, 1e-7, 20, 1, 0, '123'];
const partial = [1e-5, 0, 0, 0, null, null, null, 0, '456'];
const data = { dataset_id: 'test', names_crc: 123, count: 3, reference_epoch: 2000,
  measurements: [full, partial, null], sources: ['Gaia DR3'] };
function motionPosition(base, measurement, years, partial = false, enabled = true) {
  const records = [{}];
  applyMotionPositions(records, base, [measurement], years, enabled, partial);
  return [records[0].x, records[0].y, records[0].z];
}
assert.equal(validateMotion(data, 3, 'test', 123), data);
for (const overrides of [
  { dataset_id: 'wrong' }, { names_crc: 124 }, { count: 4 },
  { measurements: [full, partial, [NaN, 0, 0, 1, null, 1, null, 0, '1']] },
  { measurements: [full, partial, [0, 0, 0, 1, null, null, null, 0, '1']] },
]) assert.throws(() => validateMotion({ ...data, ...overrides }, 3, 'test', 123));
assert.deepEqual(motionPosition([1, 2, 3], full, 10000), [1.1, 1.8, 3.3]);
assert.deepEqual(motionPosition([1, 2, 3], full, -10000), [0.9, 2.2, 2.7]);
assert.deepEqual(motionPosition([1, 2, 3], partial, 10000), [1, 2, 3]);
assert.deepEqual(motionPosition([1, 2, 3], partial, 10000, true), [1.1, 2, 3]);
assert.deepEqual(motionPosition([1, 2, 3], null, 10000, true), [1, 2, 3]);
assert.deepEqual(motionPosition([1, 2, 3], full, 0), [1, 2, 3]);
assert.deepEqual(motionPosition([1, 2, 3], full, 10000, true, false), [1, 2, 3]);
const original = new Float64Array([1, 2, 3, 4, 5, 6]);
const moving = [{}, {}];
applyMotionPositions(moving, original, [full, partial], 10000, true, true);
applyMotionPositions(moving, original, [full, partial], 0, true, true);
assert.deepEqual(moving, [{ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }]);
assert.throws(() => motionPosition([1, 2, 3], full, Infinity));
assert.throws(() => motionPosition([1, 2, 3], full, 10001));
assert.ok(Math.abs(KM_S_TO_PC_YR - 1.022712165e-6) < 1e-14);
assert.match(motionDescription(partial, 100, false, 'Gaia DR3'), /unknown/);
assert.match(motionDescription(full, 10000, false, 'Gaia DR3'), /0.00100 pc/);
assert.match(motionDescription(full.map((v, k) => k === 4 ? null : v), 10000, false, 'Gaia DR3'), /unavailable/);
console.log('Stellar motion tests passed.');
