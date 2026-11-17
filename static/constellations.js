import * as THREE from 'three';
import { CONSTELLATIONS, resolvePattern, compareSkies, skyArc, projectSky, skyFrame } from './constellation-model.js';

const SVG = 'http://www.w3.org/2000/svg';
function element(tag, attributes = {}, text = '') {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  node.textContent = text;
  return node;
}
const degrees = angle => `${(angle * 180 / Math.PI).toFixed(2)}°`;

export function createConstellations({ scene, getState, getPosition, isVisible, viewFrom, aim }) {
  const dialog = document.getElementById('constellation-dialog');
  const openButton = document.getElementById('open-constellations');
  const choice = document.getElementById('constellation-pattern');
  const overlay = document.getElementById('constellation-overlay');
  const status = document.getElementById('constellation-status');
  const error = document.getElementById('constellation-error');
  const observerLabel = document.getElementById('constellation-observer');
  const useSelected = document.getElementById('constellation-use-selected');
  const enterView = document.getElementById('constellation-view-from');
  const look = document.getElementById('constellation-look');
  const geometry = new THREE.BufferGeometry();
  const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
    color: 0xffc867, transparent: true, opacity: 0.65, depthTest: false, depthWrite: false,
  }));
  lines.frustumCulled = false;
  lines.renderOrder = 2;
  lines.visible = false;
  scene.add(lines);
  let indices = [], byName = new Map(), observer = -1, lastKey = '', comparison = null;
  let figure = CONSTELLATIONS[0], records = [], starCount = 0;

  choice.replaceChildren(...CONSTELLATIONS.map(p => {
    const option = document.createElement('option');
    option.value = p.id;
    option.textContent = p.name;
    return option;
  }));
  function invalidate() { lastKey = ''; }
  function open() {
    if (observer < 0) {
      const state = getState();
      observer = state.viewFrom >= 0 ? state.viewFrom
        : state.selected >= 0 && state.selected < state.starCount ? state.selected
          : state.sol;
    }
    document.getElementById('view-menu').open = false;
    if (!dialog.open) dialog.show();
    openButton.setAttribute('aria-expanded', 'true');
    invalidate();
    update();
    choice.focus();
  }
  openButton.addEventListener('click', open);
  document.getElementById('close-constellations').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    openButton.setAttribute('aria-expanded', 'false');
    openButton.focus();
  });
  choice.addEventListener('change', () => {
    figure = CONSTELLATIONS.find(p => p.id === choice.value);
    indices = resolvePattern(figure, byName);
    invalidate();
    update();
  });
  overlay.addEventListener('change', () => { invalidate(); update(); });
  useSelected.addEventListener('click', () => {
    observer = getState().selected;
    invalidate();
    update();
  });
  enterView.addEventListener('click', () => {
    if (observer < 0) return;
    viewFrom(observer);
    overlay.checked = true;
    invalidate();
    update();
    lookAtPattern();
  });
  function lookAtPattern() {
    if (!comparison) return;
    const state = getState();
    if (state.viewFrom < 0) return;
    const visibleDirections = comparison.other.filter((p, i) => p && indices[i] >= 0 && isVisible(indices[i]));
    const frame = skyFrame(visibleDirections);
    if (!frame) {
      error.textContent = 'No pattern stars are currently visible. Increase the magnitude limit or relax the star filters.';
      return;
    }
    error.textContent = '';
    aim(frame.centre);
  }
  look.addEventListener('click', lookAtPattern);

  function chart(id, directions, frame, radius, label, colour) {
    const svg = document.getElementById(id);
    svg.replaceChildren();
    svg.setAttribute('aria-label', `${figure.name} from ${label}; same angular scale as the other chart`);
    svg.append(element('circle', { cx: 0, cy: 0, r: 100, fill: '#070d1d', stroke: '#3b4f74' }));
    svg.append(element('text', { x: 0, y: -106, 'text-anchor': 'middle', fill: '#aebbdc', 'font-size': 9 }, 'N'));
    svg.append(element('text', { x: -108, y: 0, fill: '#aebbdc', 'font-size': 9 }, 'E'));
    if (!frame) {
      svg.append(element('text', { x: 0, y: 0, 'text-anchor': 'middle', fill: '#aebbdc', 'font-size': 10 }, 'No directions available'));
      return;
    }
    const scale = 91 / radius;
    for (const [a, b] of figure.edges) {
      let path = '', prior = null;
      for (const direction of skyArc(directions[a], directions[b])) {
        const point = projectSky(direction, frame);
        if (!point) { prior = null; continue; }
        const [x, y] = point.map(v => v * scale);
        const continuous = prior && Math.hypot(x - prior[0], y - prior[1]) < Math.PI * scale;
        path += `${continuous ? 'L' : 'M'}${x.toFixed(3)},${y.toFixed(3)} `;
        prior = [x, y];
      }
      svg.append(element('path', { d: path, fill: 'none', stroke: colour, 'stroke-width': 1 }));
    }
    directions.forEach((direction, i) => {
      const point = projectSky(direction, frame);
      if (!point) return;
      const [x, y] = point.map(v => v * scale);
      const circle = element('circle', { cx: x, cy: y, r: 2.3, fill: colour });
      circle.append(element('title', {}, `${i + 1}. ${figure.stars[i].name}`));
      svg.append(circle, element('text', { x: x + 3, y: y - 3, fill: '#eef3ff', 'font-size': 9 }, String(i + 1)));
    });
  }

  function update() {
    if (!records.length || (!dialog.open && !overlay.checked)) { lines.visible = false; return; }
    const state = getState();
    if (state.viewFrom >= 0) observer = state.viewFrom;
    const visibility = indices.map(i => i >= 0 && isVisible(i));
    const key = [observer, state.selected, state.viewFrom, state.frame, state.epoch,
      state.galaxyScale, figure.id, overlay.checked, ...visibility].join('|');
    if (key === lastKey) return;
    lastKey = key;
    error.textContent = '';
    useSelected.disabled = state.viewFrom >= 0 || state.selected < 0 || state.selected >= state.starCount;
    useSelected.textContent = state.selected >= 0 && state.selected < state.starCount
      ? `Compare from ${records[state.selected].name}` : 'Select a star to compare';
    observerLabel.textContent = observer >= 0 ? records[observer].name : 'No observer selected';
    document.getElementById('constellation-observer-caption').textContent = observerLabel.textContent;
    enterView.disabled = observer < 0 || state.viewFrom >= 0;
    look.disabled = state.viewFrom < 0;
    if (observer < 0) {
      status.textContent = 'Select a star or enter a stellar viewpoint first.';
      lines.visible = false;
      return;
    }
    const positions = indices.map(i => i < 0 ? null : getPosition(i));
    comparison = compareSkies(positions, getPosition(observer), state.sol >= 0 ? getPosition(state.sol) : [0, 0, 0]);
    chart('constellation-earth-chart', comparison.earth, comparison.frames[0], comparison.radius, 'Sol (Earth proxy)', '#8fbfff');
    chart('constellation-observer-chart', comparison.other, comparison.frames[1], comparison.radius, records[observer].name, '#ffc867');
    const present = indices.filter(i => i >= 0).length;
    const self = indices.indexOf(observer);
    const shown = visibility.filter(Boolean).length;
    status.textContent = `${present}/${indices.length} pattern stars in loaded catalogue. `
      + (state.viewFrom >= 0 ? `${shown} pass current sky filters. ` : 'Enter the viewpoint to draw sky lines. ')
      + (self >= 0 ? `${figure.stars[self].name} is the observer and has no direction in its own sky. ` : '')
      + `Largest common-star separation: Sol ${degrees(comparison.spanEarth)}, observer ${degrees(comparison.spanOther)}. `
      + (comparison.rms === null ? 'Too few common stars to measure shape change.'
        : `RMS pairwise angular change: ${degrees(comparison.rms)}.`);
    document.getElementById('constellation-scale').textContent =
      `Both charts: centre-to-rim ${degrees(comparison.radius)}. Independently centred, celestial north up, east left. `
      + 'Azimuthal equidistant projection: large patterns distort near the rim. Numbers identify the same stars; not brightness or visibility.';
    document.getElementById('constellation-members').replaceChildren(...figure.stars.map((star, k) => {
      const li = document.createElement('li');
      li.textContent = `${star.name} (HIP ${star.hip})`;
      if (indices[k] < 0) li.textContent += ' - not loaded; incident lines omitted';
      else if (k === self) li.textContent += ' - observer; incident lines omitted';
      else if (state.viewFrom >= 0 && !visibility[k]) li.textContent += ' - hidden in sky by magnitude/filter';
      return li;
    }));
    const points = [];
    if (overlay.checked && state.viewFrom >= 0 && !state.galaxyScale) {
      for (const [a, b] of figure.edges) {
        if (!visibility[a] || !visibility[b]) continue;
        const arc = skyArc(comparison.other[a], comparison.other[b]);
        for (let k = 1; k < arc.length; k++) for (const direction of [arc[k - 1], arc[k]]) {
          points.push(...state.toDisplay(direction));
        }
      }
    }
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    lines.visible = points.length > 0;
  }
  return {
    initialize(stars, count) {
      records = stars;
      starCount = count;
      const wanted = new Set(CONSTELLATIONS.flatMap(p => p.stars.map(s => s.name)));
      byName = new Map();
      for (let i = 0; i < starCount; i++) if (wanted.has(stars[i].name)) byName.set(stars[i].name, i);
      indices = resolvePattern(figure, byName);
      openButton.disabled = false;
    },
    update(camera) {
      update();
      if (camera) lines.position.copy(camera.position);
    },
    invalidate,
    snapshot() {
      return observer >= 0 && (dialog.open || overlay.checked)
        ? { pattern: figure.id, observer: records[observer].name, overlay: overlay.checked }
        : null;
    },
    restore(settings) {
      const next = CONSTELLATIONS.find(p => p.id === settings.pattern);
      const index = records.findIndex((r, i) => i < starCount && r.name === settings.observer);
      if (!next || index < 0) throw new Error('Shared constellation or observer is unavailable in this catalogue');
      observer = index;
      figure = next;
      choice.value = figure.id;
      indices = resolvePattern(figure, byName);
      overlay.checked = settings.overlay;
      open();
    },
  };
}
