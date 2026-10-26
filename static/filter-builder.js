import { emptyFilter } from './filters.js';

export function createFilterBuilder({ records, firstSpecial, solIndex, sovereignties, spectralClasses, planetCategories, onApply }) {
  const dialog = document.getElementById('filter-dialog');
  const rules = document.getElementById('filter-rules');
  const error = document.getElementById('filter-error');
  const galaxies = document.getElementById('filter-galaxies');
  let applied = emptyFilter(), draft;
  let includeGalaxies = false;
  const kinds = ['Star', 'Neutron star', 'Black hole', 'Nebula', 'Galaxy'];
  const fields = [
    ['distance', 'Distance from star'], ['kind', 'Object type'], ['spectral', 'Spectral class'],
    ['sovereignty', 'Sovereignty'], ['planet', 'Planetary category'], ['confirmed', 'Confirmed planets'],
  ];
  const names = records.slice(0, firstSpecial).map((star) => star.name.toLowerCase());

  function button(text, action) {
    const el = document.createElement('button');
    el.type = 'button';
    el.textContent = text;
    el.addEventListener('click', action);
    return el;
  }
  function select(label, options, value, change) {
    const el = document.createElement('select');
    el.setAttribute('aria-label', label);
    for (const [key, text] of options) el.add(new Option(text, String(key)));
    el.value = String(value);
    el.addEventListener('change', () => change(el.value));
    return el;
  }
  function negate(node) {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = node.negate;
    input.addEventListener('change', () => { node.negate = input.checked; });
    label.append(input, ' NOT');
    label.title = 'Exclude matches to this condition or group';
    return label;
  }
  function defaultCondition(type = 'distance') {
    return type === 'distance' ? { type, anchor: solIndex, radius: 10, negate: false }
      : { type, value: type === 'sovereignty' ? -1 : 0, negate: false };
  }
  function render() {
    rules.replaceChildren(renderGroup(draft));
  }
  function renderGroup(node, remove) {
    const group = document.createElement('fieldset');
    group.className = 'filter-group';
    const legend = document.createElement('legend');
    legend.textContent = remove ? 'Group' : 'Show objects matching';
    const header = document.createElement('div');
    header.className = 'filter-actions';
    const explanation = document.createElement('p');
    function explainMatching() {
      explanation.textContent = node.match === 'any'
        ? 'ANY: show either neighbourhood, including separate regions around distant stars.'
        : 'ALL: every condition must match. Distance spheres show only their overlap; use ANY for separate neighbourhoods.';
    }
    explainMatching();
    header.append(select('Group matching', [['all', 'ALL (AND)'], ['any', 'ANY (OR)']], node.match,
      (value) => { node.match = value; explainMatching(); }), negate(node));
    if (remove) header.append(button('Remove group', remove));
    group.append(legend, header, explanation);
    node.children.forEach((child, index) => {
      const removeChild = () => { node.children.splice(index, 1); render(); };
      group.append(child.type === 'group' ? renderGroup(child, removeChild) : renderCondition(child, removeChild));
    });
    const actions = document.createElement('div');
    actions.className = 'filter-actions';
    actions.append(
      button('+ Condition', () => { node.children.push(defaultCondition()); render(); }),
      button('+ Group', () => { node.children.push(emptyFilter()); render(); }),
    );
    group.append(actions);
    return group;
  }
  function renderCondition(node, remove) {
    const row = document.createElement('div');
    row.className = 'filter-condition';
    row.append(select('Condition', fields, node.type, (type) => {
      for (const key of Object.keys(node)) delete node[key];
      Object.assign(node, defaultCondition(type));
      render();
    }), negate(node));
    if (node.type === 'distance') {
      const search = document.createElement('input');
      search.type = 'search';
      search.placeholder = 'Find reference star...';
      search.setAttribute('aria-label', 'Find reference star');
      const chosen = document.createElement('small');
      chosen.setAttribute('role', 'status');
      function showAnchor() {
        chosen.textContent = `Centre: ${records[node.anchor]?.name ?? 'Choose a star'}. Distances use this fixed centre.`;
      }
      const anchor = select('Reference star', [], node.anchor, (value) => {
        node.anchor = Number(value);
        showAnchor();
      });
      function updateAnchors() {
        const query = search.value.trim().toLowerCase();
        const indices = [];
        if (node.anchor >= 0) indices.push(node.anchor);
        for (let i = 0; i < firstSpecial && indices.length < 41; i++) {
          if (i !== node.anchor && names[i].includes(query)) indices.push(i);
        }
        anchor.replaceChildren(...indices.map((i) => new Option(records[i].name, String(i))));
        anchor.value = String(node.anchor);
      }
      search.addEventListener('input', updateAnchors);
      updateAnchors();
      showAnchor();
      const radius = document.createElement('input');
      radius.type = 'number';
      radius.min = '0';
      radius.step = 'any';
      radius.value = node.radius;
      radius.setAttribute('aria-label', 'Radius in pc');
      radius.addEventListener('input', () => { node.radius = radius.value === '' ? NaN : Number(radius.value); });
      const hint = document.createElement('small');
      hint.textContent = 'Search finds up to 40 stars; choose a result in the dropdown to change the centre. Typing alone does not select a star. Radius in pc, inclusive.';
      row.append(search, anchor, radius, chosen, hint);
    } else if (node.type !== 'confirmed') {
      const options = node.type === 'kind' ? kinds.map((text, i) => [i, text])
        : node.type === 'spectral' ? spectralClasses.map((text, i) => [i, text])
          : node.type === 'planet' ? planetCategories.map((c, i) => [i, c.label])
            : [[-1, 'Unclaimed'], ...sovereignties.map((s, i) => [i, s.name])];
      row.append(select('Condition value', options, node.value, (value) => { node.value = Number(value); }));
    }
    row.append(button('Remove condition', remove));
    return row;
  }
  document.getElementById('open-filters').addEventListener('click', () => {
    document.getElementById('view-menu').open = false;
    draft = structuredClone(applied);
    galaxies.checked = includeGalaxies;
    error.textContent = '';
    render();
    dialog.showModal();
  });
  document.getElementById('filter-cancel').addEventListener('click', () => dialog.close());
  document.getElementById('filter-clear').addEventListener('click', () => {
    draft = emptyFilter();
    galaxies.checked = false;
    error.textContent = '';
    render();
  });
  document.getElementById('filter-form').addEventListener('submit', (event) => {
    event.preventDefault();
    try {
      onApply(draft, galaxies.checked);
      applied = structuredClone(draft);
      includeGalaxies = galaxies.checked;
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
    }
  });
  dialog.addEventListener('keydown', (event) => event.stopPropagation());
  dialog.addEventListener('close', () => document.querySelector('#view-menu summary').focus());
  document.getElementById('open-filters').disabled = false;
}
