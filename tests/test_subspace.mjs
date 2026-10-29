import assert from 'node:assert/strict';
import { disturbanceAt, seedOffset, SUBSPACE_RADIUS_PC, SUBSPACE_VERSION } from '../static/subspace-field.js';

assert.equal(SUBSPACE_VERSION, 1);
assert.deepEqual(seedOffset(12345), seedOffset(12345));
assert.notDeepEqual(seedOffset(12345), seedOffset(12346));
assert.notDeepEqual(seedOffset(0), seedOffset(4294967295));
assert.equal(disturbanceAt([SUBSPACE_RADIUS_PC, 0, 0], 12345), 0);
assert.equal(disturbanceAt([0, -SUBSPACE_RADIUS_PC - 1, 0], 12345), 0);
assert.equal(disturbanceAt([1e8, 0, 0], 12345), 0);
assert.ok(Math.abs(disturbanceAt([0, 0, 0], 12345) - 0.010692919791821954) < 1e-12);

let minimum = 1, maximum = 0, different = 0, peak = null;
for (let x = -50; x <= 50; x += 2) {
  for (let y = -50; y <= 50; y += 2) {
    const point = [x, y, 0];
    const a = disturbanceAt(point, 12345), b = disturbanceAt(point, 12346);
    assert.ok(Number.isFinite(a) && a >= 0 && a <= 1);
    assert.equal(a, disturbanceAt(point, 12345));
    if (a !== b) different++;
    minimum = Math.min(minimum, a);
    if (a > maximum) { maximum = a; peak = point; }
    assert.ok(Math.abs(a - disturbanceAt([x + 0.00001, y, 0], 12345)) < 0.0001);
  }
}
assert.ok(minimum < 0.03, 'There should be weak background regions');
assert.ok(maximum > 0.25, 'There should be strong strands');
assert.ok(different > 2500, 'Changing the seed should change the field throughout the region');
assert.ok(disturbanceAt([peak[0] + 8, peak[1] + 8, 0], 12345) < maximum / 2, 'Strands must not fill broad regions');
let halfMaximumWidth = 0;
for (let x = peak[0] - 8; x <= peak[0] + 8; x += 0.1) {
  if (disturbanceAt([x, peak[1], 0], 12345) > maximum / 2) halfMaximumWidth += 0.1;
}
assert.ok(halfMaximumWidth >= 1 && halfMaximumWidth <= 6, 'The sampled strand should be a few parsecs wide');
console.log(`Subspace field tests passed (range ${minimum.toFixed(3)}-${maximum.toFixed(3)}).`);
