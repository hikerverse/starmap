export const emptyFilter = () => ({ type: 'group', match: 'all', negate: false, children: [] });

export function compileFilter(tree, data) {
  const { records, kind, specClass, sovOf, sovereignties, planetCat, planetFlags } = data;
  function compile(node, root = false) {
    let test;
    if (node.type === 'group') {
      if (!['all', 'any'].includes(node.match)) throw new Error('Choose ALL or ANY for each group.');
      if (!node.children.length) {
        if (!root) throw new Error('Add a condition to each group, or remove the empty group.');
        return () => true;
      }
      const children = node.children.map((child) => compile(child));
      const all = node.match === 'all';
      test = (i) => {
        for (const child of children) if (child(i) !== all) return !all;
        return all;
      };
    } else if (node.type === 'distance') {
      const anchor = records[node.anchor];
      if (!anchor || kind[node.anchor] !== 0) throw new Error('Choose a reference star for each distance condition.');
      if (!Number.isFinite(node.radius) || node.radius < 0) throw new Error('Distance must be a finite, non-negative number in pc.');
      const radius2 = node.radius * node.radius;
      if (!Number.isFinite(radius2)) throw new Error('Distance is too large.');
      const { x, y, z } = anchor;
      test = (i) => {
        const star = records[i];
        const dx = star.x - x, dy = star.y - y, dz = star.z - z;
        return dx * dx + dy * dy + dz * dz <= radius2;
      };
    } else if (node.type === 'kind') {
      if (!Number.isInteger(node.value) || node.value < 0 || node.value > 4) throw new Error('Choose an object type.');
      test = (i) => kind[i] === node.value;
    } else if (node.type === 'spectral') {
      if (!Number.isInteger(node.value) || node.value < 0 || node.value > 7) throw new Error('Choose a spectral class.');
      test = (i) => kind[i] === 0 && specClass[i] === node.value;
    } else if (node.type === 'sovereignty') {
      if (!Number.isInteger(node.value) || node.value < -1 || node.value >= sovereignties.length) {
        throw new Error('Choose a sovereignty.');
      }
      test = (i) => kind[i] === 0 && sovOf[i] === node.value;
    } else if (node.type === 'planet' || node.type === 'confirmed') {
      if (!planetCat || !planetFlags) throw new Error('Planetary scenario data is not available yet. Try again after it loads.');
      if (node.type === 'planet') {
        if (!Number.isInteger(node.value) || node.value < 0 || node.value > 3) throw new Error('Choose a planetary category.');
        test = (i) => kind[i] === 0 && planetCat[i] === node.value;
      } else {
        test = (i) => kind[i] === 0 && (planetFlags[i] & 32) !== 0;
      }
    } else {
      throw new Error('Unknown filter condition.');
    }
    return node.negate ? (i) => !test(i) : test;
  }
  return compile(tree, true);
}

export function evaluateFilter(tree, data, includeGalaxies = false) {
  const test = compileFilter(tree, data);
  const mask = new Uint8Array(data.records.length);
  for (let i = 0; i < mask.length; i++) {
    mask[i] = (!includeGalaxies && data.kind[i] === 4) || test(i) ? 1 : 0;
  }
  return mask;
}

export function countConditions(tree) {
  return tree.type === 'group' ? tree.children.reduce((n, child) => n + countConditions(child), 0) : 1;
}
