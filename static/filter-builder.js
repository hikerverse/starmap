import { emptyFilter, FILTER_KINDS, parseFilter, serializeFilter } from './filters.js';

export function createFilterBuilder({ records, firstSpecial, solIndex, sovereignties, spectralClasses, planetCategories, onApply }) {
  const dialog = document.getElementById('filter-dialog');
  const rules = document.getElementById('filter-rules');
  const error = document.getElementById('filter-error');
  const galaxies = document.getElementById('filter-galaxies');
  const title = document.getElementById('filter-title');
  const applyStatus = document.getElementById('filter-apply-status');
  let drag = null;
  let applied = emptyFilter(), draft;
  let includeGalaxies = false;
  const kinds = FILTER_KINDS;
  const filterText = document.getElementById('filter-text');
  const textStatus = document.getElementById('filter-text-status');
  const lookups = { records, starCount: firstSpecial, sovereignties, spectralClasses, planetCategories };
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
    if (dialog.open) keepInView();
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
    if (dialog.open) {
      document.getElementById('filter-close').focus();
      return;
    }
    draft = structuredClone(applied);
    galaxies.checked = includeGalaxies;
    error.textContent = '';
    applyStatus.textContent = '';
    render();
    dialog.show();
    const rect = dialog.getBoundingClientRect();
    positionPanel(rect.left, rect.top);
  });
  document.getElementById('filter-cancel').addEventListener('click', () => dialog.close());
  document.getElementById('filter-close').addEventListener('click', () => dialog.close());
  const markUnapplied = (event) => {
    if (event.target !== filterText) applyStatus.textContent = 'Unapplied edits. Click Apply to update the map.';
  };
  dialog.addEventListener('input', markUnapplied);
  dialog.addEventListener('change', markUnapplied);
  rules.addEventListener('click', (event) => {
    if (event.target instanceof HTMLButtonElement) applyStatus.textContent = 'Unapplied edits. Click Apply to update the map.';
  });
  document.getElementById('filter-clear').addEventListener('click', () => {
    draft = emptyFilter();
    galaxies.checked = false;
    error.textContent = '';
    applyStatus.textContent = 'Rules cleared. Click Apply to update the map.';
    render();
  });
  document.getElementById('filter-form').addEventListener('submit', (event) => {
    event.preventDefault();
    try {
      onApply(draft, galaxies.checked);
      applied = structuredClone(draft);
      includeGalaxies = galaxies.checked;
      error.textContent = '';
      applyStatus.textContent = 'Filters applied. Keep editing or close this panel; applied filters stay active.';
    } catch (err) {
      error.textContent = err.message;
    }
  });
  document.getElementById('filter-export').addEventListener('click', async () => {
    filterText.value = serializeFilter(applied, includeGalaxies, lookups);
    filterText.select();
    try {
      await navigator.clipboard.writeText(filterText.value);
      textStatus.textContent = 'Applied filter copied to the clipboard. Paste it here later and click Load & apply.';
    } catch {
      textStatus.textContent = 'Applied filter shown above (clipboard unavailable). Copy it manually.';
    }
  });
  document.getElementById('filter-import').addEventListener('click', () => {
    let parsed;
    try {
      parsed = parseFilter(filterText.value, lookups);
    } catch (err) {
      error.textContent = err.message;
      textStatus.textContent = '';
      return;
    }
    draft = parsed.tree;
    galaxies.checked = parsed.includeGalaxies;
    render();
    document.getElementById('filter-form').requestSubmit();
    textStatus.textContent = error.textContent ? 'Filter text loaded but could not be applied; see the error above.' : 'Filter text loaded and applied.';
  });
  function positionPanel(left, top) {
    const rect = dialog.getBoundingClientRect();
    dialog.style.margin = '0';
    dialog.style.right = dialog.style.bottom = 'auto';
    dialog.style.left = `${Math.max(0, Math.min(left, window.innerWidth - rect.width))}px`;
    dialog.style.top = `${Math.max(0, Math.min(top, window.innerHeight - rect.height))}px`;
  }
  function keepInView() {
    if (!dialog.open) return;
    const rect = dialog.getBoundingClientRect();
    positionPanel(rect.left, rect.top);
  }
  title.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || !event.isPrimary || drag) return;
    const rect = dialog.getBoundingClientRect();
    drag = { pointerId: event.pointerId, x: event.clientX - rect.left, y: event.clientY - rect.top };
    title.setPointerCapture(event.pointerId);
    title.classList.add('dragging');
    event.preventDefault();
  });
  title.addEventListener('pointermove', (event) => {
    if (drag && event.pointerId === drag.pointerId) positionPanel(event.clientX - drag.x, event.clientY - drag.y);
  });
  function stopDrag() {
    if (!drag) return;
    const { pointerId } = drag;
    drag = null;
    title.classList.remove('dragging');
    if (title.hasPointerCapture(pointerId)) title.releasePointerCapture(pointerId);
  }
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) title.addEventListener(event, stopDrag);
  window.addEventListener('resize', keepInView);
  dialog.addEventListener('keydown', (event) => {
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      dialog.close();
    }
  });
  dialog.addEventListener('close', () => {
    stopDrag();
    document.querySelector('#view-menu summary').focus();
  });
  document.getElementById('open-filters').disabled = false;
  return {
    // Rules applied outside the panel (e.g. restored settings); takes effect when the panel is next opened
    setApplied(tree, galaxiesIncluded) {
      applied = structuredClone(tree);
      includeGalaxies = galaxiesIncluded;
    },
  };
}
