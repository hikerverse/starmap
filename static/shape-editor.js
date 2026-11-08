import * as THREE from 'three';
import { validateShape } from './primitive-shapes.js';

export function createShapeGeometry(kind) {
  let geometry;
  switch (kind) {
    case 'sphere': geometry = new THREE.SphereGeometry(0.5, 32, 24); break;
    case 'box': geometry = new THREE.BoxGeometry(1, 1, 1); break;
    case 'cylinder': geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 32); geometry.rotateX(Math.PI / 2); break;
    case 'cone': geometry = new THREE.ConeGeometry(0.5, 1, 32); geometry.rotateX(Math.PI / 2); break;
    case 'torus': geometry = new THREE.TorusGeometry(0.35, 0.15, 16, 48); break;
    case 'plane': geometry = new THREE.PlaneGeometry(1, 1); break;
    default: throw new Error('Unsupported primitive shape.');
  }
  geometry.computeBoundingBox();
  const extent = geometry.boundingBox.getSize(new THREE.Vector3());
  geometry.scale(1 / extent.x, 1 / extent.y, extent.z > 0 ? 1 / extent.z : 1);
  return geometry;
}

export function createShapeEditor({ scene, camera, labelLayer, eqToGal, galToEq, getObjects, getSelected, onChange }) {
  const root = new THREE.Group();
  scene.add(root);
  const entries = new Map();
  const dialog = document.getElementById('shape-dialog');
  const title = document.getElementById('shape-title');
  const openButton = document.getElementById('open-shapes');
  const form = document.getElementById('shape-form');
  const list = document.getElementById('shape-list');
  const error = document.getElementById('shape-error');
  const status = document.getElementById('shape-status');
  const objectInput = document.getElementById('shape-object');
  const field = (name) => document.getElementById(`shape-${name}`);
  const vector = (prefix) => ['x', 'y', 'z'].map((axis) => Number(field(`${prefix}${axis}`).value));
  const setVector = (prefix, values) => values.forEach((n, i) => { field(`${prefix}${'xyz'[i]}`).value = String(n); });
  let drag = null;

  function positionWindow(left, top) {
    const rect = dialog.getBoundingClientRect();
    dialog.style.left = `${Math.max(0, Math.min(left, innerWidth - rect.width))}px`;
    dialog.style.top = `${Math.max(0, Math.min(top, innerHeight - rect.height))}px`;
  }
  openButton.addEventListener('click', () => {
    document.getElementById('view-menu').open = false;
    if (!dialog.open) dialog.show();
    openButton.setAttribute('aria-expanded', 'true');
    const rect = dialog.getBoundingClientRect();
    positionWindow(rect.left, rect.top);
    field('kind').focus();
  });
  document.getElementById('close-shapes').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    openButton.setAttribute('aria-expanded', 'false');
    document.querySelector('#view-menu summary').focus();
  });
  title.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    const rect = dialog.getBoundingClientRect();
    drag = { id: event.pointerId, x: event.clientX - rect.left, y: event.clientY - rect.top };
    title.setPointerCapture(event.pointerId);
    title.classList.add('dragging');
    event.preventDefault();
  });
  title.addEventListener('pointermove', (event) => {
    if (drag?.id === event.pointerId) positionWindow(event.clientX - drag.x, event.clientY - drag.y);
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    title.addEventListener(type, () => {
      if (!drag) return;
      const { id } = drag;
      drag = null;
      title.classList.remove('dragging');
      if (title.hasPointerCapture(id)) title.releasePointerCapture(id);
    });
  }
  window.addEventListener('resize', () => {
    if (!dialog.open) return;
    const rect = dialog.getBoundingClientRect();
    positionWindow(rect.left, rect.top);
  });

  function syncTransparency() {
    field('transparency-value').value = `${field('transparency').value}%`;
  }
  field('transparency').addEventListener('input', syncTransparency);
  function fillForm(shape) {
    error.textContent = '';
    status.textContent = '';
    form.reset();
    if (shape) {
      field('kind').value = shape.kind;
      field('label').value = shape.label;
      field('colour').value = shape.colour;
      field('transparency').value = shape.transparency;
      field('wireframe').checked = shape.wireframe;
      setVector('size-', shape.size);
      setVector('', shape.position);
      setVector('rotation-', shape.rotation);
    }
    syncTransparency();
    field('save').textContent = shape ? 'Save changes' : 'Add shape';
    field('delete').disabled = !shape;
  }
  list.addEventListener('change', () => fillForm(entries.get(list.value)?.shape));
  field('new').addEventListener('click', () => { list.value = ''; fillForm(); });

  function copyObject(record) {
    if (!record) { error.textContent = 'Select an object on the map or in the star list first.'; return; }
    const centre = new THREE.Vector3(record.x, record.y, record.z).applyMatrix3(eqToGal);
    setVector('', centre.toArray());
    objectInput.value = record.name;
    error.textContent = '';
    status.textContent = `Centre copied from ${record.name}. Press ${list.value ? 'Save changes' : 'Add shape'} to apply.`;
  }
  field('use-selected').addEventListener('click', () => copyObject(getSelected()));
  field('use-object').addEventListener('click', () => {
    const name = objectInput.value.trim().toLowerCase();
    const matches = getObjects().filter((r) => r.name.toLowerCase() === name);
    if (matches.length !== 1) {
      error.textContent = matches.length ? 'Several objects have that name. Select the intended object and use Use selected object.'
        : 'Object not found. Choose an exact catalogue name from the suggestions.';
      return;
    }
    copyObject(matches[0]);
  });
  objectInput.addEventListener('input', () => {
    const options = document.getElementById('shape-object-options');
    options.replaceChildren();
    const query = objectInput.value.trim().toLowerCase();
    if (!query) return;
    let count = 0;
    for (const record of getObjects()) {
      if (!record.name.toLowerCase().includes(query)) continue;
      const option = document.createElement('option');
      option.value = record.name;
      options.appendChild(option);
      if (++count === 25) break;
    }
  });

  function remove(id) {
    const entry = entries.get(id);
    if (!entry) return;
    root.remove(entry.mesh);
    entry.mesh.geometry.dispose();
    entry.mesh.material.dispose();
    entry.label.remove();
    entries.delete(id);
  }
  function put(shape) {
    const mesh = new THREE.Mesh(createShapeGeometry(shape.kind), new THREE.MeshBasicMaterial({
      color: shape.colour, opacity: 1 - shape.transparency / 100, transparent: true,
      depthWrite: false, side: THREE.DoubleSide, wireframe: shape.wireframe,
    }));
    mesh.position.fromArray(shape.position);
    mesh.scale.fromArray(shape.size);
    mesh.rotation.set(...shape.rotation.map(THREE.MathUtils.degToRad));
    const label = document.createElement('div');
    label.className = 'star-label shape-label';
    label.textContent = shape.label;
    label.style.color = shape.colour;
    remove(shape.id);
    root.add(mesh);
    labelLayer.appendChild(label);
    entries.set(shape.id, { shape, mesh, label });
  }
  function refreshList(selectedId = '') {
    list.replaceChildren(new Option('New shape', ''));
    for (const { shape } of entries.values()) list.add(new Option(shape.label || `${shape.kind} (unlabelled)`, shape.id));
    list.value = selectedId;
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    error.textContent = '';
    try {
      const shape = validateShape({
        id: list.value || [...crypto.getRandomValues(new Uint32Array(4))].map((n) => n.toString(16).padStart(8, '0')).join(''),
        kind: field('kind').value, label: field('label').value.trim(),
        colour: field('colour').value, size: vector('size-'), position: vector(''), rotation: vector('rotation-'),
        transparency: Number(field('transparency').value), wireframe: field('wireframe').checked,
      });
      const editing = entries.has(shape.id);
      put(shape);
      refreshList(shape.id);
      fillForm(shape);
      status.textContent = editing ? 'Shape updated.' : 'Shape added.';
      onChange();
    } catch (err) {
      console.warn('Could not save primitive shape:', err);
      error.textContent = err.message;
    }
  });
  field('delete').addEventListener('click', () => {
    remove(list.value);
    refreshList();
    fillForm();
    status.textContent = 'Shape deleted.';
    onChange();
  });

  const projected = new THREE.Vector3();
  return {
    get shapes() { return [...entries.values()].map(({ shape }) => validateShape(shape)); },
    restore(shapes) {
      try {
        if (!Array.isArray(shapes)) throw new Error('Saved shapes must be a list.');
        const validated = shapes.map(validateShape);
        if (new Set(validated.map((s) => s.id)).size !== validated.length) throw new Error('Saved shape IDs must be unique.');
        for (const id of entries.keys()) remove(id);
        for (const shape of validated) put(shape);
        refreshList();
        fillForm();
      } catch (err) {
        console.warn('Saved shapes could not be restored:', err);
        error.textContent = err.message;
      }
    },
    setFrame(frame) {
      root.quaternion.identity();
      if (frame === 'equatorial') root.quaternion.setFromRotationMatrix(new THREE.Matrix4().setFromMatrix3(galToEq));
    },
    updateLabels() {
      if (labelLayer.hidden) return;
      root.updateMatrixWorld(true);
      for (const { shape, mesh, label } of entries.values()) {
        mesh.getWorldPosition(projected).project(camera);
        label.hidden = !shape.label || shape.transparency === 100 || projected.z < -1 || projected.z > 1
          || Math.abs(projected.x) > 1 || Math.abs(projected.y) > 1;
        if (!label.hidden) label.style.transform = `translate(${(projected.x + 1) * innerWidth / 2 + 8}px, ${(1 - projected.y) * innerHeight / 2}px)`;
      }
    },
  };
}
