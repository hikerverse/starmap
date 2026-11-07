import assert from 'node:assert/strict';
import { armRadiusKpc, ARM_REFERENCE_RADIUS_KPC, SPIRAL_ARMS } from '../static/milky-way-model.js';

for (const arm of SPIRAL_ARMS) {
  assert.equal(armRadiusKpc(arm, arm.kink), arm.radius);
  assert.ok(Math.abs(armRadiusKpc(arm, arm.kink - 1e-6) - armRadiusKpc(arm, arm.kink + 1e-6)) < 1e-6);
  for (const beta of [arm.minBeta, arm.maxBeta, 0]) {
    assert.ok(Number.isFinite(armRadiusKpc(arm, beta)));
    assert.ok(armRadiusKpc(arm, beta) > 0);
    assert.ok(Math.abs(armRadiusKpc(arm, beta, 8.178)
      / armRadiusKpc(arm, beta) - 8.178 / ARM_REFERENCE_RADIUS_KPC) < 1e-12);
  }
}
const local = SPIRAL_ARMS.find((arm) => arm.name === 'Local (Orion)');
const sagittarius = SPIRAL_ARMS.find((arm) => arm.name === 'Sagittarius-Carina');
const perseus = SPIRAL_ARMS.find((arm) => arm.name === 'Perseus');
assert.ok(Math.abs(armRadiusKpc(local, 0) - 8.5258045773) < 1e-9);
assert.ok(Math.abs(armRadiusKpc(local, 0) - ARM_REFERENCE_RADIUS_KPC) < 2 * local.width);
assert.ok(armRadiusKpc(sagittarius, 0) < ARM_REFERENCE_RADIUS_KPC);
assert.ok(armRadiusKpc(perseus, 0) > armRadiusKpc(local, 0));
assert.ok(local.minBeta < 0 && local.maxBeta > 0);
assert.ok(armRadiusKpc(perseus, 60) < armRadiusKpc(perseus, 20), 'Positive beta follows rotation; arms trail');
console.log('Milky Way arm model tests passed.');
