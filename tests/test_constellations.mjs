import assert from 'node:assert/strict';
import { resolvePattern, skyDirections, compareSkies, skyFrame, projectSky, skyArc, angle } from '../static/constellation-model.js';

const close = (actual, expected, tolerance = 1e-10) => assert.ok(
  Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);
const positions = [[10, 0, 0], [10, 1, 0], [10, 0, 1]];
const fromSol = compareSkies(positions, [0, 0, 0]);
assert.deepEqual(fromSol.projected[0], fromSol.projected[1]);
close(fromSol.rms, 0);
const fromStar = compareSkies(positions, [5, 0, 0]);
close(angle(fromStar.other[0], fromStar.other[1]), Math.atan(1 / 5));
close(angle(fromStar.earth[0], fromStar.earth[1]), Math.atan(1 / 10));
assert.ok(fromStar.rms > 0);
assert.ok(fromStar.spanOther > fromStar.spanEarth);
const offset = [100, -20, 7];
const translated = compareSkies(positions.map(p => p.map((v, k) => v + offset[k])),
  [5, 0, 0].map((v, k) => v + offset[k]), offset);
close(translated.rms, fromStar.rms);
assert.deepEqual(translated.projected, fromStar.projected);

const fromMember = compareSkies(positions, positions[1]);
assert.equal(fromMember.other[1], null);
assert.equal(fromMember.pairs, 1);
assert.deepEqual(skyArc(fromMember.other[0], fromMember.other[1]), []);
const incomplete = compareSkies([positions[0], null, positions[2]], [5, 0, 0]);
assert.equal(incomplete.other[1], null);
assert.equal(incomplete.pairs, 1);
assert.equal(compareSkies([null, positions[0]], [0, 0, 0]).rms, null);
assert.equal(compareSkies([null], [0, 0, 0]).frames[0], null);
assert.deepEqual(resolvePattern({ stars: [{ name: 'A' }, { name: 'B' }] }, new Map([['A', 0]])), [0, -1]);
assert.equal(skyDirections([[0, 0, 0]], [0, 0, 0])[0], null);

const pole = skyFrame([[0, 0, 1]]);
for (const value of projectSky([0, 0, 1], pole)) close(value, 0);
assert.equal(projectSky([0, 0, -1], pole), null);
assert.deepEqual(skyArc([0, 0, 1], [0, 0, -1]), []);
const arc = skyArc([1, 0, 0], [0, 1, 0]);
assert.deepEqual(arc[0], [1, 0, 0]);
assert.deepEqual(arc.at(-1), [0, 1, 0]);
for (const point of arc) close(Math.hypot(...point), 1);
const chart = skyFrame([[1, 0, 0]]);
close(projectSky([0, 1, 0], chart)[0], -Math.PI / 2);
close(projectSky([0, 0, 1], chart)[1], -Math.PI / 2);
console.log('Constellation geometry tests passed.');
