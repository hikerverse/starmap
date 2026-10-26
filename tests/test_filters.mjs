import { emptyFilter, evaluateFilter, countConditions } from '../static/filters.js';

const records = [
  { name: 'X', x: 0, y: 0, z: 0 },
  { name: 'Y', x: 20, y: 0, z: 0 },
  { name: 'Overlap', x: 10, y: 0, z: 0 },
  { name: 'Off axis', x: 0, y: 0, z: 10 },
  { name: 'Far', x: 100, y: 100, z: 100 },
  { name: 'Nebula', x: 5, y: 0, z: 0 },
  { name: 'Galaxy', x: 1000, y: 0, z: 0 },
];
const data = {
  records, kind: new Uint8Array([0, 0, 0, 0, 0, 3, 4]),
  specClass: new Uint8Array([4, 5, 4, 6, 7, 0, 0]),
  sovereignties: [{ name: 'Test' }], sovOf: new Int16Array([0, -1, 0, -1, -1, -1, -1]),
  planetCat: new Int8Array([3, 1, 2, 0, 0, -1, -1]),
  planetFlags: new Uint8Array([32, 0, 32, 0, 0, 0, 0]),
};
const distance = (anchor, radius, negate = false) => ({ type: 'distance', anchor, radius, negate });
const condition = (type, value, negate = false) => ({ type, value, negate });
const group = (match, children, negate = false) => ({ type: 'group', match, children, negate });
let passed = 0;
function equal(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
  passed++;
}
function matches(tree, expected, label, source = data, galaxies = true) {
  const mask = evaluateFilter(tree, source, galaxies);
  equal([...mask].flatMap((value, i) => value ? [i] : []), expected, label);
}
function rejects(tree, label, source = data) {
  let rejected = false;
  try { evaluateFilter(tree, source); } catch (error) { rejected = error instanceof Error && !!error.message; }
  equal(rejected, true, label);
}

matches(emptyFilter(), [0, 1, 2, 3, 4, 5, 6], 'Empty root disables filtering');
matches(distance(0, 10), [0, 2, 3, 5], 'Radius includes 3D boundary');
matches(distance(0, 0), [0], 'Zero radius is exact, not disabled');
matches(group('all', [distance(0, 10), distance(1, 15)]), [2, 5], 'Sphere intersection');
matches(group('any', [distance(0, 10), distance(1, 15)]), [0, 1, 2, 3, 5], 'Sphere union');
matches(group('any', [distance(0, 10), distance(4, 10)]), [0, 2, 3, 4, 5], 'Separate 10 pc neighbourhoods include distant anchor');
matches(group('all', [distance(0, 10), distance(4, 10)]), [], 'Separate 10 pc spheres have no intersection');
matches(group('all', [distance(0, 10), distance(1, 15, true)]), [0, 3], 'Excluded sphere');
matches(group('any', [distance(0, 10), distance(1, 15)], true), [4, 6], 'Negated group');
matches(group('all', [group('any', [condition('spectral', 4), condition('spectral', 5)]),
  condition('confirmed')]), [0, 2], 'Nested groups and confirmed flag');
matches(condition('kind', 3), [5], 'Object kind');
matches(condition('spectral', 4), [0, 2], 'Spectral class');
matches(condition('sovereignty', -1), [1, 3, 4], 'Unclaimed stars exclude non-stars');
matches(condition('sovereignty', 0), [0, 2], 'Sovereignty membership');
matches(condition('planet', 3), [0], 'Planet category independent of colour');
matches(condition('planet', 1), [1, 6], 'Galaxies exempt by default', data, false);
matches(condition('planet', 1), [1], 'Optional galaxy filtering', data, true);
matches(condition('kind', 0, true), [5, 6], 'NOT complements across object kinds');
matches(condition('planet', 3), [1], 'Scenario change updates result',
  { ...data, planetCat: new Int8Array([0, 3, 0, 0, 0, -1, -1]) });
matches(distance(0, 10), [0, 2, 3, 5], 'Distance uses catalogue, not display coordinates',
  { ...data, pos: new Float32Array(records.length * 3).fill(999) });
equal(countConditions(group('all', [distance(0, 10), group('any', [condition('kind', 0)])])), 2, 'Nested count');
equal(countConditions(emptyFilter()), 0, 'Empty count');
rejects(group('all', [emptyFilter()]), 'Empty nested group rejected');
for (const radius of [-1, NaN, Infinity, 1e200]) rejects(distance(0, radius), `Invalid radius ${radius}`);
rejects(distance(-1, 10), 'Missing anchor rejected');
rejects(distance(6, 10), 'Non-star anchor rejected');
rejects(condition('planet', 3), 'Unavailable scenario explicit error', { ...data, planetCat: null });
rejects(condition('sovereignty', 5), 'Unknown sovereignty rejected');
rejects(condition('spectral', 8), 'Unknown spectral class rejected');
rejects(condition('planet', 4), 'Unknown planetary category rejected');
rejects(condition('unknown', 0), 'Unknown condition rejected');

export const result = { passed };
console.log(`Filter tests: ${passed} passed`);
