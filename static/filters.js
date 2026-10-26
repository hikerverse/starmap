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

export const FILTER_KINDS = ['Star', 'Neutron star', 'Black hole', 'Nebula', 'Galaxy'];
const MAX_TEXT_DEPTH = 32;
const MAX_TEXT_NODES = 1000;

// Portable text form: references use names (not array indices) so it survives reloads and data rebuilds
export function serializeFilter(tree, includeGalaxies, lookups) {
  const { records, sovereignties, spectralClasses, planetCategories } = lookups;
  function encode(node) {
    let out;
    if (node.type === 'group') out = { match: node.match, rules: node.children.map(encode) };
    else if (node.type === 'distance') out = { distance: node.radius, from: records[node.anchor]?.name ?? null, index: node.anchor };
    else if (node.type === 'kind') out = { kind: FILTER_KINDS[node.value] };
    else if (node.type === 'spectral') out = { spectral: spectralClasses[node.value] };
    else if (node.type === 'sovereignty') out = { sovereignty: node.value < 0 ? null : sovereignties[node.value]?.name };
    else if (node.type === 'planet') out = { planet: planetCategories[node.value]?.label ?? planetCategories[node.value] };
    else if (node.type === 'confirmed') out = { confirmed: true };
    else throw new Error('Unknown filter condition.');
    if (node.negate) out.not = true;
    return out;
  }
  const { match, rules, not } = encode(tree);
  return JSON.stringify({ starexplorer: 1, galaxies: !!includeGalaxies, match, ...(not ? { not } : {}), rules });
}

export function parseFilter(text, lookups) {
  const { records, starCount, sovereignties, spectralClasses, planetCategories } = lookups;
  let root;
  try {
    root = JSON.parse(String(text).trim());
  } catch {
    throw new Error('Filter text is not valid. Paste the full text copied from "Copy filter text".');
  }
  if (!root || typeof root !== 'object' || root.starexplorer !== 1) {
    throw new Error('Filter text is not a StarExplorer filter (version 1).');
  }
  let byName = null;
  let nodes = 0;
  const lower = (value) => String(value).toLowerCase();
  function lookup(list, value, what) {
    const index = list.findIndex((item) => lower(item) === lower(value));
    if (index < 0) throw new Error(`Unknown ${what} "${value}" in filter text.`);
    return index;
  }
  function findStar(name, hint) {
    if (typeof name !== 'string' || !name) throw new Error('Each distance rule needs a "from" star name.');
    if (Number.isInteger(hint) && hint >= 0 && hint < starCount && records[hint].name === name) return hint;
    if (!byName) {
      byName = new Map();
      for (let i = 0; i < starCount; i++) {
        const key = lower(records[i].name);
        if (!byName.has(key)) byName.set(key, i);
      }
    }
    const index = byName.get(lower(name));
    if (index === undefined) throw new Error(`Star "${name}" in filter text was not found in the catalogue.`);
    return index;
  }
  function decode(item, depth) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('Filter text contains an invalid rule.');
    if (++nodes > MAX_TEXT_NODES) throw new Error(`Filter text has more than ${MAX_TEXT_NODES} rules.`);
    if (item.not !== undefined && typeof item.not !== 'boolean') throw new Error('"not" must be true or false.');
    const negate = item.not === true;
    if ('rules' in item) {
      if (depth >= MAX_TEXT_DEPTH) throw new Error('Filter text has too many nested groups.');
      if (!['all', 'any'].includes(item.match)) throw new Error('Each group needs "match": "all" or "any".');
      if (!Array.isArray(item.rules)) throw new Error('Group "rules" must be a list.');
      return { type: 'group', match: item.match, negate, children: item.rules.map((child) => decode(child, depth + 1)) };
    }
    if ('distance' in item) {
      if (typeof item.distance !== 'number') throw new Error('Distance must be a number in pc.');
      return { type: 'distance', anchor: findStar(item.from, item.index), radius: item.distance, negate };
    }
    if ('kind' in item) return { type: 'kind', value: lookup(FILTER_KINDS, item.kind, 'object type'), negate };
    if ('spectral' in item) return { type: 'spectral', value: lookup(spectralClasses, item.spectral, 'spectral class'), negate };
    if ('sovereignty' in item) {
      const value = item.sovereignty === null ? -1 : lookup(sovereignties.map((s) => s.name), item.sovereignty, 'sovereignty');
      return { type: 'sovereignty', value, negate };
    }
    if ('planet' in item) {
      const labels = planetCategories.map((c) => c.label ?? c);
      return { type: 'planet', value: lookup(labels, item.planet, 'planetary category'), negate };
    }
    if (item.confirmed === true) return { type: 'confirmed', negate };
    throw new Error('Filter text contains an unknown rule.');
  }
  if (root.galaxies !== undefined && typeof root.galaxies !== 'boolean') throw new Error('"galaxies" must be true or false.');
  return { tree: decode(root, 0), includeGalaxies: root.galaxies === true };
}

export function countConditions(tree) {
  return tree.type === 'group' ? tree.children.reduce((n, child) => n + countConditions(child), 0) : 1;
}
