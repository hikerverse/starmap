import assert from 'node:assert/strict';
import { AU_KM, SOLAR_RADIUS_KM, EARTH_RADIUS_KM, systemBodies, orbitPoint, displayRadius } from '../static/system-model.js';

const data = {
  name: 'Test star', star: { radius: 1, category_label: 'Main sequence' }, snow_line_au: 2.7,
  planets: [{
    name: 'Earth-like', type: 'terrestrial', a_au: 1, e: 0.1, radius_rearth: 1,
    moons: [{ name: 'Test moon', a_km: 384400, radius_km: 1737.4 }],
  }, { name: 'Giant', type: 'gas_giant', a_au: 5, e: 0, radius_rearth: 10, moons: [] }],
};
const bodies = systemBodies(data);
assert.equal(bodies.length, 4);
assert.equal(bodies[0].radius, SOLAR_RADIUS_KM / AU_KM);
assert.equal(bodies[1].radius, EARTH_RADIUS_KM / AU_KM);
assert.equal(bodies[2].radius, 1737.4 / AU_KM);
assert.equal(bodies[2].parent, 1);
assert.ok(Math.abs(Math.hypot(...bodies[2].position.map((v, k) => v - bodies[1].position[k]))
  - 384400 / AU_KM) < 1e-12);
assert.deepEqual(systemBodies(data).map(b => b.position), bodies.map(b => b.position));
assert.deepEqual(orbitPoint(1, 0.1, 0), [0.9, 0, 0]);
assert.ok(Math.abs(orbitPoint(1, 0.1, Math.PI)[0] + 1.1) < 1e-12);
for (const body of bodies) {
  assert.equal(displayRadius(body, bodies, 100, 50, 900, true), body.radius);
  assert.ok(displayRadius(body, bodies, 100, 50, 900, false) >= body.radius);
}
assert.ok(displayRadius(bodies[1], bodies, 100, 50, 900, false) <= bodies[2].orbit * 0.25);
assert.ok(displayRadius(bodies[2], bodies, 100, 50, 900, false) <= bodies[2].orbit * 0.12);
for (const invalid of [
  null, { ...data, star: { radius: NaN } },
  { ...data, planets: [{ ...data.planets[0], e: 1 }] },
  { ...data, planets: [{ ...data.planets[0], radius_rearth: 0 }] },
  { ...data, planets: [{ ...data.planets[0], a_au: Infinity }] },
  { ...data, planets: [{ ...data.planets[0], moons: [{ name: 'Broken', radius_km: 1, a_km: 0 }] }] },
]) assert.throws(() => systemBodies(invalid));
console.log('System model tests passed.');
