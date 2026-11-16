import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { AU_KM, systemBodies, displayRadius, orbitPoint } from './system-model.js';

const TYPE_NAMES = {
  terrestrial: 'Terrestrial', super_earth: 'Super-Earth', sub_neptune: 'Sub-Neptune',
  neptune: 'Ice giant', gas_giant: 'Gas giant', icy: 'Icy moon', rocky: 'Rocky moon',
};

function appearance(body, system) {
  if (body.kind === 'star') {
    const t = system.star.teff;
    return { colour: t > 10000 ? '#a8c8ff' : t > 6500 ? '#e4edff' : t > 5000 ? '#fff0c4'
      : t > 3500 ? '#ffb568' : '#ff744c', surface: 3 };
  }
  if (system.name === 'Sol') {
    const known = {
      Earth: ['#367fb0', 0], Mars: ['#bf633d', 0], Venus: ['#dbc089', 1],
      Mercury: ['#9e948b', 0], Jupiter: ['#d9b48b', 1], Saturn: ['#e2cd9c', 1],
      Uranus: ['#8ccfd7', 2], Neptune: ['#407ada', 2], Moon: ['#a8a49e', 0],
      Io: ['#d4bd56', 0], Europa: ['#c9d5de', 0], Titan: ['#c58e3a', 1],
    };
    if (known[body.name]) return { colour: known[body.name][0], surface: known[body.name][1] };
  }
  return {
    colour: ({ terrestrial: '#b99470', super_earth: '#ba9f86', sub_neptune: '#74aebd',
      neptune: '#689ee1', gas_giant: '#ddaf79', icy: '#bbdce9', rocky: '#a29b94' })[body.type] ?? '#b8aaa0',
    surface: ['gas_giant', 'sub_neptune'].includes(body.type) ? 1 : body.type === 'neptune' ? 2 : 0,
  };
}

function material(body, system) {
  const style = appearance(body, system);
  return new THREE.ShaderMaterial({
    uniforms: { colour: { value: new THREE.Color(style.colour) }, surface: { value: style.surface },
      earth: { value: system.name === 'Sol' && body.name === 'Earth' ? 1 : 0 },
      starPosition: { value: new THREE.Vector3() } },
    vertexShader: `
      varying vec3 vNormal; varying vec3 vWorld; varying vec2 vUv;
      void main() {
        vUv = uv;
        vNormal = normalize(mat3(modelMatrix) * normal);
        vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
        gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 colour; uniform float surface; uniform float earth; uniform vec3 starPosition;
      varying vec3 vNormal; varying vec3 vWorld; varying vec2 vUv;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float noise(vec2 p) {
        vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
        return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),
                   mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);
      }
      void main() {
        float n=noise(vUv*18.0)+0.5*noise(vUv*43.0)+0.25*noise(vUv*90.0);
        vec3 c=colour*(0.65+0.45*n);
        if(surface>0.5 && surface<2.5) {
          float bands=sin(vUv.y*90.0+noise(vUv*14.0)*3.0);
          c=colour*(0.78+0.2*bands+0.15*n);
          if(surface>1.5) c=colour*(0.9+0.06*bands);
        }
        if(earth>0.5) {
          c=mix(colour,vec3(0.24,0.42,0.19),smoothstep(0.88,1.04,n));
          c=mix(c,vec3(0.9),smoothstep(1.3,1.6,n));
          c=mix(c,vec3(0.87,0.93,0.98),smoothstep(0.38,0.49,abs(vUv.y-0.5)));
        }
        float light=0.22+0.78*max(0.0,dot(normalize(vNormal),normalize(starPosition-vWorld)));
        if(surface>2.5) light=1.0;
        gl_FragColor=vec4(c*light,1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}

export function createSystemExplorer({ root, onClose, onInformation }) {
  const canvasHost = root.querySelector('.system-space');
  const labelHost = root.querySelector('.system-body-labels');
  const list = root.querySelector('#system-body-list');
  const status = root.querySelector('#system-explorer-status');
  const details = root.querySelector('#system-body-details');
  const viewDistance = root.querySelector('#system-view-distance');
  const scale = root.querySelector('#system-scale');
  let renderer, camera, controls, scene, bodies = [], meshes = [], labels = [], system;
  let selected = 0, focused = -1, frame = null, active = false, pointerDown;
  const raycaster = new THREE.Raycaster();
  const sphere = new THREE.SphereGeometry(1, 40, 24);
  const cameraDirection = new THREE.Vector3(1, 0.85, 1).normalize();

  function clearScene() {
    if (scene) scene.traverse(object => {
      if (object.geometry && object.geometry !== sphere) object.geometry.dispose();
      if (object.material) object.material.dispose();
    });
    meshes = []; labels = []; bodies = [];
    list.replaceChildren(); labelHost.replaceChildren();
  }

  function resize() {
    if (!active || !renderer) return;
    const { width, height } = canvasHost.getBoundingClientRect();
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function select(index) {
    selected = index;
    const body = bodies[index];
    const type = body.kind === 'star' ? body.type : TYPE_NAMES[body.type] ?? body.type;
    const provenance = body.kind === 'star' ? system.star.source
      : body.kind === 'moon' ? system.name === 'Sol' ? 'Solar System observation'
      : bodies[body.parent].data.moons_simulated
        || !system.confirmed ? 'Simulated moon' : 'Dataset moon'
      : system.flags & 64 ? 'Manually edited dataset'
      : system.confirmed ? 'Observed planet' : 'Simulated planet';
    const radius = body.radius * AU_KM;
    details.textContent = `${body.name} - ${type}. Radius ${radius.toLocaleString(undefined,
      { maximumFractionDigits: 1 })} km${body.data.radius_estimated ? ' (est.)' : ''}. ${provenance}.`
      + (body.kind === 'planet' && body.data.minor_moons
        ? ` ${body.data.minor_moons} additional moons counted but not individually modelled.` : '');
    for (const [i, button] of [...list.children].entries()) button.setAttribute('aria-pressed', String(i === index));
  }

  function focus(index) {
    select(index);
    focused = index;
    const body = bodies[index];
    const children = bodies.filter(b => b.parent === index);
    const extent = body.kind === 'planet' && children.length
      ? Math.max(...children.map(b => b.orbit + b.radius)) : body.radius * 3;
    const distance = Math.max(extent * 3, body.radius * 8);
    controls.target.fromArray(body.position);
    camera.position.copy(controls.target).addScaledVector(cameraDirection, distance);
    controls.minDistance = body.radius * 1.15;
    camera.near = Math.max(1e-12, Math.min(body.radius * 0.01, distance * 0.001));
    camera.updateProjectionMatrix();
    controls.update();
  }

  function fit() {
    focused = -1;
    const extent = Math.max(bodies[0].radius * 10, ...bodies.map(b => {
      const parentOrbit = b.kind === 'moon'
        ? bodies[b.parent].orbit * (1 + bodies[b.parent].eccentricity) : 0;
      return parentOrbit + b.orbit * (1 + b.eccentricity) + b.radius;
    }));
    const halfField = Math.atan(Math.tan(camera.fov * Math.PI / 360) * Math.min(1, camera.aspect));
    const distance = extent / Math.sin(halfField) * 1.15;
    controls.target.set(0, 0, 0);
    camera.position.copy(cameraDirection).multiplyScalar(distance);
    controls.minDistance = Math.min(...bodies.map(b => b.radius)) * 1.15;
    controls.maxDistance = Math.max(distance * 10, 1);
    camera.far = controls.maxDistance * 2;
    camera.near = Math.max(1e-12, Math.min(...bodies.map(b => b.radius)) * 0.01);
    camera.updateProjectionMatrix();
    controls.update();
  }

  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(meshes, false)[0];
    if (hit) return meshes.indexOf(hit.object);
    return -1;
  }

  function tick() {
    if (!active || !system) return;
    frame = requestAnimationFrame(tick);
    controls.update();
    camera.updateMatrixWorld();
    const height = canvasHost.clientHeight;
    for (const [index, body] of bodies.entries()) {
      const mesh = meshes[index];
      const radius = displayRadius(body, bodies, camera.position.distanceTo(mesh.position),
        camera.fov, height, scale.value === 'true');
      mesh.scale.setScalar(radius);
      const projected = mesh.position.clone().project(camera);
      const visible = projected.z >= -1 && projected.z <= 1 && Math.abs(projected.x) < 0.98
        && Math.abs(projected.y) < 0.95 && (body.kind !== 'moon'
          || focused === index || focused === body.parent
          || camera.position.distanceTo(mesh.position) < body.orbit * 80);
      const label = labels[index];
      label.hidden = !visible;
      label.style.left = `${(projected.x + 1) / 2 * canvasHost.clientWidth}px`;
      label.style.top = `${(1 - projected.y) / 2 * height}px`;
      label.classList.toggle('selected', index === selected);
    }
    renderer.render(scene, camera);
    const distance = camera.position.distanceTo(controls.target);
    const distanceText = distance < 0.01
      ? `${(distance * AU_KM).toLocaleString(undefined, { maximumFractionDigits: 0 })} km`
      : `${distance.toFixed(3)} AU`;
    viewDistance.textContent = `${focused >= 0 ? `Centred on ${bodies[focused].name}` : 'Whole system / free view'}`
      + ` - camera distance ${distanceText}.`;
  }

  function initialize() {
    if (renderer) return;
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    canvasHost.prepend(renderer.domElement);
    camera = new THREE.PerspectiveCamera(50, 1, 1e-10, 1000);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.screenSpacePanning = true;
    renderer.domElement.addEventListener('pointerdown', e => { pointerDown = { x: e.clientX, y: e.clientY }; });
    renderer.domElement.addEventListener('pointerup', e => {
      const down = pointerDown;
      pointerDown = null;
      if (!down || e.button !== 0 || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return;
      const index = pick(e);
      if (index >= 0) select(index);
    });
    renderer.domElement.addEventListener('pointercancel', () => { pointerDown = null; });
    renderer.domElement.addEventListener('dblclick', e => {
      const index = pick(e);
      if (index >= 0) focus(index);
    });
  }

  function close() {
    if (!active) return;
    active = false;
    cancelAnimationFrame(frame);
    clearScene();
    system = null;
    root.hidden = true;
    onClose();
  }

  root.querySelector('#close-system-explorer').addEventListener('click', close);
  root.querySelector('#focus-system-body').addEventListener('click', () => { if (system) focus(selected); });
  root.querySelector('#fit-system').addEventListener('click', () => { if (system) fit(); });
  root.querySelector('#system-information').addEventListener('click', () => { if (system) onInformation(); });
  root.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return; }
    if (event.key === 'Tab') {
      const buttons = [...root.querySelectorAll('button:not(:disabled), select:not(:disabled)')]
        .filter(element => !element.hidden && element.getClientRects().length);
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  window.addEventListener('resize', resize);

  return {
    get active() { return active; },
    snapshot() {
      if (!system) throw new Error('Wait for the system to finish loading before sharing');
      return { name: system.name, body: bodies[selected].name,
        focus: focused >= 0 ? bodies[focused].name : null,
        scale: scale.value, position: camera.position.toArray(), target: controls.target.toArray() };
    },
    restore(state) {
      const selectedIndex = bodies.findIndex(b => b.name === state.body);
      const focusIndex = state.focus === null ? -1 : bodies.findIndex(b => b.name === state.focus);
      if (selectedIndex < 0 || (state.focus !== null && focusIndex < 0)) {
        throw new Error('The shared planet or moon is not available in this system');
      }
      if (focusIndex >= 0) focus(focusIndex);
      select(selectedIndex);
      focused = focusIndex;
      scale.value = state.scale;
      camera.position.fromArray(state.position);
      controls.target.fromArray(state.target);
      controls.maxDistance = Math.max(controls.maxDistance, camera.position.distanceTo(controls.target) * 2);
      camera.far = Math.max(camera.far, controls.maxDistance * 2);
      camera.updateProjectionMatrix();
      controls.update();
    },
    close,
    loading(name) {
      cancelAnimationFrame(frame);
      clearScene();
      system = null;
      active = true;
      root.hidden = false;
      root.querySelector('#system-explorer-title').textContent = `Explore ${name}`;
      status.textContent = 'Loading system...';
      details.textContent = '';
      viewDistance.textContent = '';
      for (const id of ['focus-system-body', 'fit-system', 'system-information', 'system-scale']) {
        root.querySelector(`#${id}`).disabled = true;
      }
      root.querySelector('#close-system-explorer').focus();
    },
    error(message) { status.textContent = `Could not explore system: ${message}`; },
    show(data) {
      bodies = systemBodies(data);
      initialize();
      system = data;
      scene = new THREE.Scene();
      scene.background = new THREE.Color('#030611');
      scale.value = 'enlarged';
      for (const [index, body] of bodies.entries()) {
        const mesh = new THREE.Mesh(sphere, material(body, system));
        mesh.position.fromArray(body.position);
        mesh.scale.setScalar(body.radius);
        meshes.push(mesh);
        scene.add(mesh);
        if (body.orbit) {
          const points = Array.from({ length: 193 }, (_, k) =>
            new THREE.Vector3(...orbitPoint(body.orbit, body.eccentricity, k / 192 * Math.PI * 2)));
          const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
            new THREE.LineBasicMaterial({ color: body.kind === 'moon' ? '#56637d' : '#2b3e65' }));
          line.position.fromArray(bodies[body.parent].position);
          scene.add(line);
        }
        if (system.name === 'Sol' && body.name === 'Saturn') {
          const ring = new THREE.Mesh(new THREE.RingGeometry(1.4, 2.3, 80),
            new THREE.MeshBasicMaterial({ color: '#b6a88a', side: THREE.DoubleSide, transparent: true, opacity: 0.6 }));
          ring.rotation.x = Math.PI / 2.7;
          mesh.add(ring);
        }
        const button = document.createElement('button');
        button.textContent = `${body.kind === 'moon' ? '\u21b3 ' : ''}${body.name}`;
        button.title = 'Click to select; double-click to centre';
        button.addEventListener('click', () => select(index));
        button.addEventListener('dblclick', () => focus(index));
        list.append(button);
        const label = document.createElement('button');
        label.textContent = body.name;
        label.addEventListener('click', () => select(index));
        label.addEventListener('dblclick', () => focus(index));
        labelHost.append(label);
        labels.push(label);
      }
      status.textContent = `${system.flags & 64 ? 'Manually edited dataset' : system.confirmed
        ? system.name === 'Sol' ? 'Observed Solar System' : 'Confirmed planets' : `Simulated system (seed ${system.seed})`}. `
        + 'Static illustrative orbital phases and common orbital plane, not an ephemeris. '
        + 'Surface patterns are representative, not measured images. Exoplanet moons are simulated.';
      for (const id of ['focus-system-body', 'fit-system', 'system-information', 'system-scale']) {
        root.querySelector(`#${id}`).disabled = false;
      }
      resize();
      select(0);
      fit();
      tick();
    },
  };
}
