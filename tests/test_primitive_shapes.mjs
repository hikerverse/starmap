import assert from 'node:assert/strict';
import { SHAPE_KINDS, validateShape } from '../static/primitive-shapes.js';

const base = {
  id: 'test-shape', kind: 'sphere', label: 'Survey volume', colour: '#55aaff',
  size: [2, 3, 4], position: [-1, 2, 0], rotation: [0, 45, -90],
  transparency: 50, wireframe: false,
};

for (const kind of SHAPE_KINDS) assert.equal(validateShape({ ...base, kind }).kind, kind);
for (const transparency of [0, 100]) assert.equal(validateShape({ ...base, transparency }).transparency, transparency);
assert.deepEqual(validateShape(JSON.parse(JSON.stringify(base))), base);
const copy = validateShape(base);
copy.position[0] = 99;
copy.size[0] = 99;
copy.rotation[0] = 99;
assert.deepEqual(base.position, [-1, 2, 0]);
assert.deepEqual(base.size, [2, 3, 4]);
assert.deepEqual(base.rotation, [0, 45, -90]);
assert.equal(validateShape({ ...base, label: '<script>text only</script>' }).label, '<script>text only</script>');
assert.equal(validateShape({ ...base, size: [0.000001, 1, 1] }).size[0], 0.000001);

for (const invalid of [
  null, [], { ...base, kind: 'unknown' }, { ...base, id: '' },
  { ...base, label: 'x'.repeat(121) }, { ...base, label: 123 },
  { ...base, colour: 'red' }, { ...base, colour: '#123' },
  { ...base, transparency: -1 }, { ...base, transparency: 101 },
  { ...base, transparency: NaN }, { ...base, transparency: '50' },
  { ...base, wireframe: 1 },
  ...['position', 'size', 'rotation'].flatMap((key) =>
    [[1, 2], [1, 2, 3, 4], [1, Infinity, 3], [1, NaN, 3], [1, '2', 3], [1, null, 3]]
      .map((value) => ({ ...base, [key]: value }))),
  ...[0, -1, 0.0000001].map((n) => ({ ...base, size: [n, 1, 1] })),
]) assert.throws(() => validateShape(invalid));

console.log('Primitive shape validation tests passed.');
