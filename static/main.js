import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ---------- Tunables ----------
const PICK_RADIUS_PX = 12;      // how close (in pixels) a click must be to a star
const CLICK_MOVE_TOLERANCE = 5; // pixels of movement before a press counts as a drag
const FOCUS_DURATION_MS = 700;
const MAX_LABELS = 60;
const LABEL_CANDIDATES = 400;   // brightest on-screen stars considered for labels
const NAMED_BONUS_MAG = 3;      // proper names get labelled ahead of catalogue ids
const LOCAL_BONUS_MAG = 12;     // max bonus for stars at the rotation centre
const LIST_NEAREST = 25;
const LIST_MAX_MATCHES = 100;
const HOME_DISTANCE_PC = 12;
const DEFAULT_ABS_MAG = 5;
const CATALOGUE_ID = /^(Gl|GJ|HD|HIP|HR|HYG)\s/;
const KIND_NEUTRON = 1;
const KIND_BLACK_HOLE = 2;
const KIND_NEBULA = 3;
const KIND_GALAXY = 4;
// Neutron stars and black holes are optically invisible, so draw them at a fixed minimum size
const KIND_SIZE_PX = [0, 20, 24, 12, 14];
const SPECIAL_BONUS_MAG = 10;   // label priority bonus for neutron stars / black holes
const KIND_CLASS = ['', 'neutron', 'blackhole', 'nebula', 'galaxy'];
// Extragalactic objects: label bonus (they are faint from Sol but famous) and size/priority for clusters without abs_mag
const GALAXY_BONUS_MAG = 6;
const GALAXY_DEFAULT_ABS_MAG = -22;
// Nebula types (index stored in specClass for nebulae; order matters to the puff shader)
const NEB_TYPES = [
  { key: 'emission', label: 'Emission', colour: '#ff5a7a', title: 'Emission nebulae (H II regions)' },
  { key: 'reflection', label: 'Reflection', colour: '#6fa8ff', title: 'Reflection nebulae' },
  { key: 'planetary', label: 'Planetary', colour: '#4fe0c8', title: 'Planetary nebulae' },
  { key: 'snr', label: 'SNR', colour: '#ffa35c', title: 'Supernova remnants' },
  { key: 'dark', label: 'Dark', colour: '#9c7a5a', title: 'Dark nebulae and molecular clouds' },
];
const NEB_DARK = 4;
// Label priority of nebulae, as an equivalent absolute magnitude (curated famous nebulae first)
const NEB_LABEL_MAG = { curated: -7, 'Zucker+ 2020': -5 };
const NEB_LABEL_MAG_DEFAULT = 1;
const NEB_SUBPUFFS = 3;         // extra noise puffs around single-puff nebulae for a less regular shape
// Sovereignty colour mode: members are drawn at least this big and get a label bonus; others are greyed out
const SOV_MEMBER_MIN_PX = 10;
const SOV_BONUS_MAG = 6;
const UNCLAIMED_COLOUR = '#4a5060';
// Per-star sovereignty state (shader attribute `sovState`)
const SOV_NORMAL = 0, SOV_HIDDEN = 1, SOV_MEMBER = 2;
// Planets colour mode (data from /api/systems-summary; flag bits match systems.py)
const PF_GIANT = 1, PF_HZ = 2, PF_HABITABLE = 4, PF_CONSERVATIVE = 8, PF_HAB_MOON = 16, PF_CONFIRMED = 32;
const PLANET_CATS = [
  { label: 'No planets', colour: '#4a5060', title: 'No planets found or simulated' },
  { label: 'Planets', colour: '#5b7cfa', title: 'Has planets, none in the habitable zone' },
  { label: 'Planet in habitable zone', colour: '#ffb02e',
    title: 'A planet orbits in the habitable zone, but it is a giant / sub-Neptune or the star is not a stable main-sequence star' },
  { label: 'Potentially habitable', colour: '#3ddc84',
    title: 'A rocky planet (0.25 M⊕+, ≤ 1.6 R⊕) or a large moon in the habitable zone of a main-sequence star' },
];
const PLANET_HABITABLE = 3;
// Main spectral classes for the class filter; index 7 = other (white dwarfs, carbon, Wolf-Rayet, unknown)
const SPEC_CLASSES = ['O', 'B', 'A', 'F', 'G', 'K', 'M', 'Other'];
const SPEC_OTHER = 7;
const SPEC_COLOURS = ['#9bb0ff', '#aabfff', '#d6e0ff', '#f8f7ff', '#fff1d8', '#ffc98a', '#ff9d5c', '#8a90a0'];
// Leading luminosity prefixes (d = dwarf, sd = subdwarf, g = giant, c = supergiant) before the class letter;
// a lowercase class alone (e.g. "m", "k-m") is a colour-based classification
function mainSpectralClass(sp) {
  const m = /^(?:sd|esd|d|g|c|k)?([OBAFGKM])/.exec(sp) || /^([obafgkm])(?![a-z])/.exec(sp);
  return m ? 'OBAFGKM'.indexOf(m[1].toUpperCase()) : SPEC_OTHER;
}
const OVERLAYS = [
  { kind: KIND_NEUTRON, url: '/api/neutron-stars', label: 'neutron stars' },
  { kind: KIND_BLACK_HOLE, url: '/api/black-holes', label: 'black holes' },
  { kind: KIND_NEBULA, url: '/api/nebulae', label: 'nebulae', key: 'nebulae' },
  { kind: KIND_GALAXY, url: '/api/galaxies', label: 'galaxies', key: 'galaxies' },
];

// J2000 equatorial -> galactic rotation (Hipparcos, ESA SP-1200 vol. 1 §1.5.3). Galactic frame is right-handed:
// +X towards the Galactic Centre (l = 0, b = 0), +Y towards l = 90° (direction of rotation), +Z towards the NGP.
const EQ_TO_GAL = new THREE.Matrix3().set(
  -0.0548755604, -0.8734370902, -0.4838350155,
  0.4941094279, -0.4448296300, 0.7469822445,
  -0.8676661490, -0.1980763734, 0.4559837762,
);
const GAL_TO_EQ = EQ_TO_GAL.clone().transpose();
const FRAMES = {
  galactic: {
    axes: ['Galactic Centre (l 0°)', 'l 90° (rotation)', 'North Galactic Pole'],
    grid: 'galactic plane',
  },
  equatorial: {
    axes: ['RA 0h (vernal equinox)', 'RA 6h', 'North Celestial Pole'],
    grid: 'celestial equator',
  },
};

// Point size / opacity as a function of apparent magnitude seen from the camera.
// Kept identical in GLSL and JS so picking matches what is drawn.
const SIZE = { a: 14.0, b: 1.6, min: 2.5, max: 30.0, nearDist: 3.0, nearBoost: 5.0, minAlpha: 0.4 };

function appMagAt(absMag, dist) {
  return absMag + 5 * Math.log10(Math.max(dist, 1e-3) / 10);
}
function pointSizePx(appMag, dist, k = 0, minPx = 0) {
  const base = Math.min(SIZE.max, Math.max(SIZE.min, SIZE.a - SIZE.b * appMag));
  const near = SIZE.min + SIZE.nearBoost * Math.min(1, SIZE.nearDist / dist);
  return Math.max(base, near, KIND_SIZE_PX[k], minPx);
}

// ---------- Renderer / camera / controls ----------
const container = document.getElementById('canvas-container');
const labelLayer = document.getElementById('labels');

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
// Far plane covers the most distant extragalactic objects (hundreds of Mpc). Nothing is depth-tested
// against anything that writes depth, so the huge far/near ratio costs nothing.
const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.001, 1e10);
camera.up.set(0, 0, 1); // Z-up: towards the north pole of the current frame

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.screenSpacePanning = true;
controls.zoomSpeed = 1.5;
controls.minDistance = 0.02;
controls.maxDistance = 40000;
controls.listenToKeyEvents(window); // arrow keys pan

// ---------- Star data (struct-of-arrays for speed) ----------
let N = 0;
let records = [];          // original JSON objects
let pos;                   // Float32Array(3N), in the current display frame (see `frame`)
let positionAttr = null;
let frame = 'galactic';    // JSON data is equatorial J2000; it is rotated into this frame on load
let absMag;                // Float32Array(N)
let namesLower = [];
let isNamed;               // Uint8Array(N): 1 = proper name, 0 = catalogue id
let kind;                  // Uint8Array(N): 0 = star, 1 = neutron star, 2 = black hole, 3 = nebula, 4 = galaxy
let firstSpecial = 0;      // neutron stars / black holes / nebulae / galaxies are appended after the HYG stars
const kindVisible = [true, true, true, true, true];
let specClass;             // Uint8Array(N): index into SPEC_CLASSES (stars) or NEB_TYPES (nebulae)
const classVisible = SPEC_CLASSES.map(() => true);
const nebTypeVisible = NEB_TYPES.map(() => true);
let labelWidth;             // Float32Array(N), 0 = not measured yet
let solIndex = -1;
let allBounds = new THREE.Sphere();

// Per-frame scratch buffers
let scrX, scrY, scrKey, scrBin;

let selected = -1;
let centre = -1;

const starPos = (i, target = new THREE.Vector3()) => target.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]);
// Distance filter: only show objects within filterRadius pc of the anchor star (0 = off).
// Extragalactic objects are a backdrop and are never hidden by it.
let filterRadius = 0;
let filterAnchor = -1;
const filterCentre = new THREE.Vector3();
function outsideFilter(i) {
  if (filterRadius <= 0 || kind[i] === KIND_GALAXY) return false;
  const dx = pos[3 * i] - filterCentre.x, dy = pos[3 * i + 1] - filterCentre.y, dz = pos[3 * i + 2] - filterCentre.z;
  return dx * dx + dy * dy + dz * dz > filterRadius * filterRadius;
}
// Sovereignties (data/sovereignties.json): membership is by star name, resolved once on load
let sovereignties = [];
let sovOf;                 // Int16Array(N): sovereignty index, -1 = unclaimed
let sovCount = [];         // members found per sovereignty
let sovVisible = [];
let sovState;              // Float32Array(N): SOV_NORMAL / SOV_HIDDEN / SOV_MEMBER
let colourMode = 'spectral';
let showUnclaimed = true;
let naturalColours, sovColours, colourAttr, sovStateAttr;
// Planetary systems summary (stars only; neutron stars / black holes have planetCat -1)
let planetCount = null;    // Uint16Array(N)
let planetFlags = null;    // Uint8Array(N)
let planetCat = null;      // Int8Array(N): index into PLANET_CATS
let planetColours = null;
const planetVisible = PLANET_CATS.map(() => true);
let confirmedOnly = false;

const isHidden = (i) => !kindVisible[kind[i]] || (kind[i] === 0 && !classVisible[specClass[i]])
  || (kind[i] === KIND_NEBULA && !nebTypeVisible[specClass[i]])
  || sovState[i] === SOV_HIDDEN || outsideFilter(i);
// Neutron stars and black holes: always labelled when on screen
const isCompactSpecial = (i) => kind[i] === KIND_NEUTRON || kind[i] === KIND_BLACK_HOLE;
const starSizePx = (i, dist) =>
  pointSizePx(appMagAt(absMag[i], dist), dist, kind[i], sovState[i] === SOV_MEMBER ? SOV_MEMBER_MIN_PX : 0);
function displayColour(i) {
  if (colourMode === 'planets' && planetCat && planetCat[i] >= 0) return PLANET_CATS[planetCat[i]].colour;
  if (colourMode !== 'sovereignty') return records[i].colour;
  return sovOf[i] >= 0 ? sovereignties[sovOf[i]].colour : UNCLAIMED_COLOUR;
}

function hexToRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

// ---------- Star point cloud ----------
const starMaterial = new THREE.ShaderMaterial({
  uniforms: {
    uPixelRatio: { value: renderer.getPixelRatio() },
    uShowStar: { value: 1.0 },
    uShowNeutron: { value: 1.0 },
    uShowBlackHole: { value: 1.0 },
    uShowNebula: { value: 1.0 },
    uShowGalaxy: { value: 1.0 },
    uNebTypeVisible: { value: NEB_TYPES.map(() => 1.0) },
    uFilterCentre: { value: filterCentre },
    uFilterRadius: { value: 0.0 },
    uClassVisible: { value: SPEC_CLASSES.map(() => 1.0) },
  },
  vertexShader: /* glsl */`
    attribute vec3 starColor;
    attribute float absMag;
    attribute float kind;
    attribute float sovState;
    attribute float specClass;
    uniform float uClassVisible[${SPEC_CLASSES.length}];
    uniform float uPixelRatio;
    uniform float uShowStar;
    uniform float uShowNeutron;
    uniform float uShowBlackHole;
    uniform float uShowNebula;
    uniform float uShowGalaxy;
    uniform float uNebTypeVisible[${NEB_TYPES.length}];
    uniform vec3 uFilterCentre;
    uniform float uFilterRadius;
    varying vec3 vColor;
    varying float vAlpha;
    varying float vKind;
    void main() {
      vKind = kind;
      bool isNebula = kind > 2.5 && kind < 3.5;
      bool isGalaxy = kind > 3.5;
      if ((kind < 0.5 && uShowStar < 0.5) || (kind > 0.5 && kind < 1.5 && uShowNeutron < 0.5)
          || (kind > 1.5 && kind < 2.5 && uShowBlackHole < 0.5) || (isNebula && uShowNebula < 0.5)
          || (isGalaxy && uShowGalaxy < 0.5)
          || (sovState > 0.5 && sovState < 1.5)
          || (kind < 0.5 && uClassVisible[int(specClass + 0.5)] < 0.5)
          || (isNebula && uNebTypeVisible[int(specClass + 0.5)] < 0.5)
          || (!isGalaxy && uFilterRadius > 0.0 && distance(position, uFilterCentre) > uFilterRadius)) {
        gl_PointSize = 0.0;
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0); // outside clip space
        return;
      }
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      float d = max(length(mv.xyz), 1e-3);
      float appMag = absMag + 5.0 * log(d / 10.0) / log(10.0);
      float base = clamp(${SIZE.a.toFixed(3)} - ${SIZE.b.toFixed(3)} * appMag, ${SIZE.min.toFixed(3)}, ${SIZE.max.toFixed(3)});
      float nearF = min(1.0, ${SIZE.nearDist.toFixed(3)} / d);
      float size = max(base, ${SIZE.min.toFixed(3)} + ${SIZE.nearBoost.toFixed(3)} * nearF);
      vAlpha = max(clamp(1.0 - (appMag - 5.0) / 12.0, ${SIZE.minAlpha.toFixed(3)}, 1.0), nearF);
      if (kind > 0.5) {
        size = max(size, ${KIND_SIZE_PX.map((px, k) => (k ? `kind > ${k - 0.5} && kind < ${k + 0.5} ? ${px.toFixed(3)} : ` : '')).join('')}0.0);
        vAlpha = 1.0;
      }
      if (sovState > 1.5) {
        size = max(size, ${SOV_MEMBER_MIN_PX.toFixed(3)});
        vAlpha = max(vAlpha, 0.9);
      }
      vColor = starColor;
      gl_PointSize = size * uPixelRatio;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: /* glsl */`
    varying vec3 vColor;
    varying float vAlpha;
    varying float vKind;
    void main() {
      vec2 c = (gl_PointCoord - 0.5) * 2.0;
      float r = length(c);
      if (r > 1.0) discard;
      if (vKind > 3.5) {
        // Galaxy marker: tilted elliptical glow with a bright nucleus and a faint disc rim
        vec2 q = mat2(0.866, 0.5, -0.5, 0.866) * c;
        float e = length(vec2(q.x, q.y * 2.4));
        float disc = pow(max(0.0, 1.0 - e), 1.2);
        float rim = smoothstep(0.12, 0.0, abs(e - 0.92)) * 0.5;
        float nucleus = smoothstep(0.25, 0.0, r);
        gl_FragColor = vec4(mix(vColor, vec3(1.0), nucleus * 0.6) * 1.2, min(1.0, disc * 0.85 + rim + nucleus));
        return;
      }
      if (vKind > 2.5) {
        // Nebula marker: dashed ring around a faint centre dot
        float ang = atan(c.y, c.x);
        float ring = smoothstep(0.16, 0.04, abs(r - 0.72)) * step(0.0, sin(ang * 6.0));
        float centreDot = smoothstep(0.22, 0.0, r);
        gl_FragColor = vec4(mix(vColor, vec3(1.0), 0.25) * 1.2, min(1.0, ring * 0.9 + centreDot * 0.7));
        return;
      }
      if (vKind > 1.5) {
        // Black hole: empty shadow, bright photon ring and a tilted accretion disc
        float shadow = smoothstep(0.30, 0.36, r);
        float photon = smoothstep(0.1, 0.0, abs(r - 0.4));
        float e = length(vec2(c.x, c.y * 3.2));
        float disc = smoothstep(0.22, 0.0, abs(e - 0.78)) * (1.0 - smoothstep(0.85, 1.0, r));
        float a = min(1.0, (photon + disc * 0.9) * shadow);
        gl_FragColor = vec4(mix(vColor, vec3(1.0, 0.95, 0.8), photon * 0.5) * 1.2, a);
        return;
      }
      if (vKind > 0.5) {
        // Neutron star: bright core, thin ring and a four-pointed "pulsar beam" cross
        float coreN = smoothstep(0.35, 0.0, r);
        float ring = smoothstep(0.16, 0.04, abs(r - 0.7));
        float beams = smoothstep(0.14, 0.0, min(abs(c.x), abs(c.y))) * pow(1.0 - r, 0.7);
        float a = min(1.0, coreN + ring + beams);
        gl_FragColor = vec4(mix(vColor, vec3(1.0), coreN * 0.5) * 1.3, a);
        return;
      }
      float core = smoothstep(0.6, 0.0, r);
      float glow = pow(1.0 - r, 1.5) * 0.8;
      vec3 col = mix(vColor, vec3(1.0), core * 0.4);
      gl_FragColor = vec4(col, min(1.0, core + glow) * vAlpha);
    }`,
  transparent: true,
  depthWrite: false,
  depthTest: false,
  blending: THREE.AdditiveBlending,
});

function buildPoints() {
  naturalColours = new Float32Array(3 * N);
  sovColours = new Float32Array(3 * N);
  const sovRgb = sovereignties.map((s) => hexToRgb(s.colour));
  const unclaimedRgb = hexToRgb(UNCLAIMED_COLOUR);
  for (let i = 0; i < N; i++) {
    naturalColours.set(hexToRgb(records[i].colour), 3 * i);
    sovColours.set(sovOf[i] >= 0 ? sovRgb[sovOf[i]] : unclaimedRgb, 3 * i);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  colourAttr = new THREE.BufferAttribute(naturalColours.slice(), 3);
  geo.setAttribute('starColor', colourAttr);
  geo.setAttribute('absMag', new THREE.BufferAttribute(absMag, 1));
  geo.setAttribute('kind', new THREE.BufferAttribute(new Float32Array(kind), 1));
  sovStateAttr = new THREE.BufferAttribute(sovState, 1);
  geo.setAttribute('sovState', sovStateAttr);
  geo.setAttribute('specClass', new THREE.BufferAttribute(new Float32Array(specClass), 1));
  geo.computeBoundingSphere();
  const points = new THREE.Points(geo, starMaterial);
  points.frustumCulled = false;
  scene.add(points);
  positionAttr = geo.attributes.position;
}

// ---------- Nebula clouds (instanced camera-facing noise billboards, sized in parsecs) ----------
// Puff centres stay in equatorial J2000; the group is rotated into the display frame.
const nebulaGroup = new THREE.Group();
nebulaGroup.matrixAutoUpdate = false;
scene.add(nebulaGroup);
const nebulaMeshes = [];   // { mesh, owners: Int32Array (record index per instance), visible attribute }

const NEBULA_VERTEX = /* glsl */`
  attribute vec3 iCentre;
  attribute float iRadius;
  attribute vec3 iColor;
  attribute float iType;
  attribute float iSeed;
  attribute float iVisible;
  varying vec2 vUv;
  varying vec3 vColor;
  varying float vType;
  varying float vSeed;
  varying float vFade;
  void main() {
    if (iVisible < 0.5) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
    vec4 mv = modelViewMatrix * vec4(iCentre, 1.0);
    // Fade out as the camera flies into the cloud so it doesn't fill the screen
    vFade = smoothstep(0.35, 1.6, length(mv.xyz) / iRadius);
    mv.xy += position.xy * iRadius;
    vUv = position.xy;
    vColor = iColor;
    vType = iType;
    vSeed = iSeed;
    gl_Position = projectionMatrix * mv;
  }`;
const NEBULA_FRAGMENT = /* glsl */`
  uniform float uIntensity;
  varying vec2 vUv;
  varying vec3 vColor;
  varying float vType;
  varying float vSeed;
  varying float vFade;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
  }
  float fbm(vec2 p) {
    // Rotate each octave so the value-noise lattice doesn't show as axis-aligned blocks
    const mat2 rot = mat2(1.6, 1.2, -1.2, 1.6);
    float v = 0.0, a = 0.5;
    for (int k = 0; k < 5; k++) { v += a * noise(p); p = rot * p + 17.0; a *= 0.5; }
    return v;
  }
  void main() {
    float r = length(vUv);
    if (r > 1.0 || vFade <= 0.0) discard;
    vec2 q = vUv * 3.0 + vec2(vSeed * 41.0, vSeed * 23.0);
    vec2 p = q + 1.5 * vec2(fbm(q + 3.1), fbm(q + 7.7));
    float n = fbm(p);
    vec3 col = vColor;
    float a;
    if (vType > 3.5) {          // dark nebula / molecular cloud
      a = pow(1.0 - r, 1.3) * smoothstep(0.3, 0.75, n) * 0.55;
    } else if (vType > 2.5) {   // supernova remnant: filamentary shell
      float shell = smoothstep(0.3, 0.0, abs(r - 0.78 + 0.25 * (n - 0.5)));
      float fil = pow(1.0 - abs(fbm(p * 1.8) - 0.5) * 2.0, 5.0);
      a = shell * (0.25 + fil) * 0.8;
      col = mix(col, vec3(0.55, 0.75, 1.0), smoothstep(0.4, 0.8, fil) * 0.4);
    } else if (vType > 1.5) {   // planetary nebula: bright shell, teal inside, red rim
      float shell = smoothstep(0.32, 0.0, abs(r - 0.55));
      a = (shell * 0.9 + 0.3 * (1.0 - r)) * (0.6 + 0.7 * n) * smoothstep(1.0, 0.85, r);
      col = mix(col, vec3(1.0, 0.35, 0.45), smoothstep(0.5, 0.9, r));
    } else {                    // emission / reflection: billowy cloud
      a = pow(1.0 - r, 1.6) * (0.25 + 1.1 * n * n);
    }
    gl_FragColor = vec4(col, clamp(a * vFade * uIntensity, 0.0, 1.0));
  }`;

function makeNebulaMesh(instances, dark) {
  const n = instances.length;
  const geo = new THREE.InstancedBufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  geo.setIndex([0, 1, 2, 0, 2, 3]);
  const centre = new Float32Array(3 * n), radius = new Float32Array(n), colour = new Float32Array(3 * n);
  const type = new Float32Array(n), seed = new Float32Array(n), visible = new Float32Array(n).fill(1);
  const owners = new Int32Array(n);
  instances.forEach((p, k) => {
    centre.set(p.c, 3 * k);
    radius[k] = p.r;
    colour.set(hexToRgb(records[p.owner].colour), 3 * k);
    type[k] = specClass[p.owner];
    seed[k] = p.seed;
    owners[k] = p.owner;
  });
  geo.setAttribute('iCentre', new THREE.InstancedBufferAttribute(centre, 3));
  geo.setAttribute('iRadius', new THREE.InstancedBufferAttribute(radius, 1));
  geo.setAttribute('iColor', new THREE.InstancedBufferAttribute(colour, 3));
  geo.setAttribute('iType', new THREE.InstancedBufferAttribute(type, 1));
  geo.setAttribute('iSeed', new THREE.InstancedBufferAttribute(seed, 1));
  const visibleAttr = new THREE.InstancedBufferAttribute(visible, 1);
  geo.setAttribute('iVisible', visibleAttr);
  geo.instanceCount = n;
  const mesh = new THREE.Mesh(geo, new THREE.ShaderMaterial({
    uniforms: { uIntensity: { value: dark ? 0.6 : 0.5 } },
    vertexShader: NEBULA_VERTEX,
    fragmentShader: NEBULA_FRAGMENT,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: dark ? THREE.NormalBlending : THREE.AdditiveBlending,
  }));
  mesh.frustumCulled = false;
  // Dark clouds first (they dim the background haze), then glowing nebulae, then stars on top
  mesh.renderOrder = dark ? -2 : -1;
  nebulaGroup.add(mesh);
  nebulaMeshes.push({ mesh, owners, visibleAttr });
}

function buildNebulae() {
  const bright = [], dark = [];
  let seed = 0.123;
  const rand = () => (seed = (seed * 9301 + 49297) % 233280 / 233280); // deterministic, so clouds look the same each load
  for (let i = firstSpecial; i < N; i++) {
    if (kind[i] !== KIND_NEBULA) continue;
    const d = records[i];
    const out = specClass[i] === NEB_DARK ? dark : bright;
    if (Array.isArray(d.puffs) && d.puffs.length) {
      for (const [x, y, z, r] of d.puffs) out.push({ owner: i, c: [x, y, z], r, seed: rand() });
      continue;
    }
    out.push({ owner: i, c: [d.x, d.y, d.z], r: d.radius_pc, seed: rand() });
    if (specClass[i] === NEB_TYPES.findIndex((t) => t.key === 'planetary')) continue; // keep a single symmetric shell
    for (let s = 0; s < NEB_SUBPUFFS; s++) {
      const u = rand() * 2 - 1, phi = rand() * Math.PI * 2, off = d.radius_pc * 0.45, q = Math.sqrt(1 - u * u);
      out.push({
        owner: i, c: [d.x + off * q * Math.cos(phi), d.y + off * q * Math.sin(phi), d.z + off * u],
        r: d.radius_pc * 0.6, seed: rand(),
      });
    }
  }
  if (dark.length) makeNebulaMesh(dark, true);
  if (bright.length) makeNebulaMesh(bright, false);
  applyNebulaFrame();
}

function applyNebulaFrame() {
  nebulaGroup.matrix.setFromMatrix3(frame === 'galactic' ? EQ_TO_GAL : new THREE.Matrix3());
  nebulaGroup.matrixWorldNeedsUpdate = true;
}

// Clouds follow their marker's visibility (kind / type toggles, distance filter, colour-mode hiding)
function updateNebulaVisibility() {
  for (const { owners, visibleAttr } of nebulaMeshes) {
    const v = visibleAttr.array;
    for (let k = 0; k < owners.length; k++) v[k] = isHidden(owners[k]) ? 0 : 1;
    visibleAttr.needsUpdate = true;
  }
}

// ---------- Selection ring, drop lines ----------
function makeRingTexture() {
  const size = 128;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  ctx.strokeStyle = 'rgba(140,180,255,0.95)';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 6, 0, Math.PI * 2);
  ctx.stroke();
  return new THREE.CanvasTexture(c);
}
const ringTexture = makeRingTexture();

const selectionRing = new THREE.Sprite(new THREE.SpriteMaterial({
  map: ringTexture, depthTest: false, transparent: true, sizeAttenuation: false,
}));
selectionRing.scale.set(0.045, 0.045, 1);
selectionRing.visible = false;
selectionRing.renderOrder = 10;
scene.add(selectionRing);

const helpers = new THREE.Group();
scene.add(helpers);

class DropLine {
  constructor(colour) {
    this.line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineBasicMaterial({ color: colour, transparent: true, opacity: 0.7, depthWrite: false }),
    );
    this.foot = new THREE.Sprite(new THREE.SpriteMaterial({
      map: ringTexture, color: colour, transparent: true, depthWrite: false, sizeAttenuation: false,
    }));
    this.foot.scale.set(0.015, 0.015, 1);
    helpers.add(this.line, this.foot);
    this.set(-1);
  }

  set(i) {
    const visible = i >= 0;
    this.line.visible = this.foot.visible = visible;
    if (!visible) return;
    const p = starPos(i);
    const attr = this.line.geometry.attributes.position;
    attr.setXYZ(0, p.x, p.y, p.z);
    attr.setXYZ(1, p.x, p.y, 0);
    attr.needsUpdate = true;
    this.line.geometry.computeBoundingSphere();
    this.foot.position.set(p.x, p.y, 0);
  }
}
const selectedDrop = new DropLine(0x8fb4ff);
const centreDrop = new DropLine(0xffd27a);

// ---------- Adaptive grid on the fundamental (z = 0) plane of the current frame ----------
const GRID_DIVISIONS = 20;
let grid = null;
let gridSpacing = 0;
const axes = new THREE.AxesHelper(1);
axes.material.transparent = true;
axes.material.opacity = 0.7;
axes.material.depthWrite = false;
helpers.add(axes);

function makeTextSprite(colour) {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 64;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false, depthTest: false, sizeAttenuation: false,
  }));
  sprite.center.set(0, 0.5);
  sprite.scale.set(0.24, 0.03, 1);
  sprite.userData = { canvas: c, colour };
  return sprite;
}
function setSpriteText(sprite, text) {
  const { canvas, colour } = sprite.userData;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.font = '600 34px system-ui, sans-serif';
  ctx.shadowColor = 'rgba(0,0,0,0.9)';
  ctx.shadowBlur = 6;
  ctx.fillStyle = colour;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 8, canvas.height / 2);
  sprite.material.map.needsUpdate = true;
}
// AxesHelper colours: X red, Y green, Z blue
const axisLabels = ['#ff8080', '#80ff80', '#80a0ff'].map((colour) => {
  const s = makeTextSprite(colour);
  axes.add(s);
  return s;
});
axisLabels[0].position.set(1.05, 0, 0);
axisLabels[1].position.set(0, 1.05, 0);
axisLabels[2].position.set(0, 0, 1.05);
function updateAxisLabels() {
  FRAMES[frame].axes.forEach((name, k) => setSpriteText(axisLabels[k], `${'XYZ'[k]} → ${name}`));
}
updateAxisLabels();

function updateGrid() {
  const dist = camera.position.distanceTo(controls.target);
  const spacing = Math.pow(10, Math.floor(Math.log10(Math.max(dist, 0.01) / 2)));
  if (spacing !== gridSpacing) {
    gridSpacing = spacing;
    if (grid) {
      helpers.remove(grid);
      grid.geometry.dispose();
      grid.material.dispose();
    }
    grid = new THREE.GridHelper(spacing * GRID_DIVISIONS, GRID_DIVISIONS, 0x3a4c88, 0x1c2544);
    grid.rotation.x = Math.PI / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.6;
    grid.material.depthWrite = false;
    helpers.add(grid);
    axes.scale.setScalar(spacing);
    // Labels are fixed screen size; undo the parent scale so they don't grow with the axes
    for (const s of axisLabels) s.scale.set(0.24 / spacing, 0.03 / spacing, 1);
    document.getElementById('scale-info').textContent = `Grid: ${FRAMES[frame].grid}, spacing ${formatPc(spacing)}`;
  }
  grid.position.set(
    Math.round(controls.target.x / spacing) * spacing,
    Math.round(controls.target.y / spacing) * spacing,
    0,
  );
}

function formatPc(v) {
  return v >= 1 ? `${v.toLocaleString()} pc` : `${v} pc`;
}

// ---------- Screen-space projection (shared by picking and labels) ----------
const viewProj = new THREE.Matrix4();

function prepareProjection() {
  camera.updateMatrixWorld();
  viewProj.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
  return viewProj.elements;
}

// ---------- Picking ----------
function pickStar(clientX, clientY) {
  if (!N) return -1;
  const m = prepareProjection();
  const rect = renderer.domElement.getBoundingClientRect();
  const hw = rect.width / 2;
  const hh = rect.height / 2;
  const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
  const reach = PICK_RADIUS_PX + SIZE.max / 2;
  let best = -1;
  let bestScore = Infinity;
  for (let i = 0; i < N; i++) {
    if (isHidden(i)) continue;
    const x = pos[3 * i], y = pos[3 * i + 1], z = pos[3 * i + 2];
    const w = m[3] * x + m[7] * y + m[11] * z + m[15];
    if (w <= 0) continue;
    const sx = rect.left + ((m[0] * x + m[4] * y + m[8] * z + m[12]) / w + 1) * hw;
    const dx = sx - clientX;
    if (dx > reach || dx < -reach) continue;
    const sy = rect.top + (1 - (m[1] * x + m[5] * y + m[9] * z + m[13]) / w) * hh;
    const dy = sy - clientY;
    if (dy > reach || dy < -reach) continue;
    const dPx = Math.hypot(dx, dy);
    const dist = Math.hypot(x - cx, y - cy, z - cz);
    const size = starSizePx(i, dist);
    if (dPx > Math.max(PICK_RADIUS_PX, size / 2 + 4)) continue;
    // Distance from the drawn disc's edge, so big/bright stars win when overlapping
    const score = dPx - size / 2;
    if (score < bestScore) {
      bestScore = score;
      best = i;
    }
  }
  return best;
}

// ---------- Labels (pooled DOM elements, decluttered) ----------
const labelPool = [];
const measureCtx = document.createElement('canvas').getContext('2d');
measureCtx.font = '12px "Segoe UI", system-ui, sans-serif';
let labelsDirty = true;
const lastCamera = new Float32Array(32);

function getLabelWidth(i) {
  if (!labelWidth[i]) labelWidth[i] = measureCtx.measureText(records[i].name).width + 8;
  return labelWidth[i];
}

function cameraChanged() {
  camera.updateMatrixWorld();
  const a = camera.matrixWorld.elements;
  const b = camera.projectionMatrix.elements;
  let changed = false;
  for (let k = 0; k < 16; k++) {
    if (lastCamera[k] !== a[k] || lastCamera[16 + k] !== b[k]) changed = true;
    lastCamera[k] = a[k];
    lastCamera[16 + k] = b[k];
  }
  return changed;
}

const BIN_MIN = -30, BIN_SIZE = 0.25, BIN_COUNT = 280;
const binCounts = new Uint32Array(BIN_COUNT);

function updateLabels() {
  if (!N || labelLayer.hidden) return;
  if (!cameraChanged() && !labelsDirty) return;
  labelsDirty = false;

  const m = prepareProjection();
  const w = window.innerWidth, h = window.innerHeight;
  const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
  const tx = controls.target.x, ty = controls.target.y, tz = controls.target.z;
  // Stars close to the rotation centre (relative to the zoom level) get a label bonus,
  // so the local neighbourhood is named rather than only luminous distant giants.
  const localRadius = Math.max(camera.position.distanceTo(controls.target), 1e-3);
  binCounts.fill(0);

  // Pass 1: project everything, bucket on-screen stars by (apparent magnitude - name bonus)
  for (let i = 0; i < N; i++) {
    scrBin[i] = -1;
    if (isHidden(i)) continue;
    const x = pos[3 * i], y = pos[3 * i + 1], z = pos[3 * i + 2];
    const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
    if (cw <= 0) continue;
    const nx = (m[0] * x + m[4] * y + m[8] * z + m[12]) / cw;
    const ny = (m[1] * x + m[5] * y + m[9] * z + m[13]) / cw;
    if (nx < -1.05 || nx > 1.05 || ny < -1.05 || ny > 1.05) continue;
    const dist = Math.hypot(x - cx, y - cy, z - cz);
    const local = Math.max(0, 1 - Math.hypot(x - tx, y - ty, z - tz) / localRadius);
    const key = appMagAt(absMag[i], dist) - (isNamed[i] ? NAMED_BONUS_MAG : 0) - LOCAL_BONUS_MAG * local
      - (isCompactSpecial(i) ? SPECIAL_BONUS_MAG : kind[i] === KIND_GALAXY ? GALAXY_BONUS_MAG : 0)
      - (sovState[i] === SOV_MEMBER ? SOV_BONUS_MAG : 0);
    const bin = Math.min(BIN_COUNT - 1, Math.max(0, Math.floor((key - BIN_MIN) / BIN_SIZE)));
    scrX[i] = (nx + 1) / 2 * w;
    scrY[i] = (1 - ny) / 2 * h;
    scrKey[i] = dist; // reused below for point size
    scrBin[i] = bin;
    binCounts[bin]++;
  }

  let cutoff = 0;
  for (let total = 0; cutoff < BIN_COUNT; cutoff++) {
    total += binCounts[cutoff];
    if (total >= LABEL_CANDIDATES) break;
  }

  // Pass 2: collect the brightest candidates, then place labels greedily without overlap
  const candidates = [];
  for (let i = 0; i < N; i++) if (scrBin[i] >= 0 && scrBin[i] <= cutoff) candidates.push(i);
  const priority = (i) => (i === selected ? -2000 : i === centre ? -1000
    : isCompactSpecial(i) ? -500 : scrBin[i]);
  for (const forced of [selected, centre]) {
    if (forced >= 0 && scrBin[forced] >= 0 && scrBin[forced] > cutoff) candidates.push(forced);
  }
  for (let i = firstSpecial; i < N; i++) {
    if (scrBin[i] > cutoff && i !== selected && i !== centre && isCompactSpecial(i)) candidates.push(i);
  }
  candidates.sort((p, q) => priority(p) - priority(q));

  const placed = [];
  let used = 0;
  for (const i of candidates) {
    if (used >= MAX_LABELS) break;
    const dist = scrKey[i];
    const size = starSizePx(i, dist);
    const lw = getLabelWidth(i);
    const box = { l: scrX[i] - lw / 2, r: scrX[i] + lw / 2, t: scrY[i] - size / 2 - 18, b: scrY[i] - size / 2 - 2 };
    const forced = i === selected || i === centre;
    if (!forced && placed.some((p) => box.l < p.r && box.r > p.l && box.t < p.b && box.b > p.t)) continue;
    placed.push(box);

    let el = labelPool[used];
    if (!el) {
      el = document.createElement('div');
      el.className = 'star-label';
      labelLayer.appendChild(el);
      labelPool.push(el);
    }
    if (el.textContent !== records[i].name) el.textContent = records[i].name;
    el.style.transform = `translate(${box.l.toFixed(1)}px, ${box.t.toFixed(1)}px)`;
    el.classList.toggle('catalogue', !isNamed[i]);
    el.classList.toggle('neutron', kind[i] === KIND_NEUTRON);
    el.classList.toggle('blackhole', kind[i] === KIND_BLACK_HOLE);
    el.classList.toggle('nebula', kind[i] === KIND_NEBULA);
    el.classList.toggle('galaxy', kind[i] === KIND_GALAXY);
    el.hidden = false;
    used++;
  }
  for (let k = used; k < labelPool.length; k++) labelPool[k].hidden = true;
}

// ---------- Sidebar list (nearest to centre, or search results) ----------
const listEl = document.getElementById('star-list');
const listTitle = document.getElementById('list-title');
const searchEl = document.getElementById('star-search');

function brightnessFromSol(i) {
  const d = Math.hypot(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]);
  return appMagAt(absMag[i], d);
}

function nearestTo(p, count) {
  const best = []; // [dist2, index], sorted ascending
  for (let i = 0; i < N; i++) {
    if (isHidden(i)) continue;
    const dx = pos[3 * i] - p.x, dy = pos[3 * i + 1] - p.y, dz = pos[3 * i + 2] - p.z;
    const d2 = dx * dx + dy * dy + dz * dz;
    if (best.length === count && d2 >= best[count - 1][0]) continue;
    let k = best.length;
    while (k > 0 && best[k - 1][0] > d2) k--;
    best.splice(k, 0, [d2, i]);
    if (best.length > count) best.pop();
  }
  return best.map((b) => b[1]);
}

function renderList() {
  if (!N) return;
  const q = searchEl.value.trim().toLowerCase();
  let indices;
  if (!q) {
    indices = nearestTo(controls.target, LIST_NEAREST);
    listTitle.textContent = centre >= 0 ? `Nearest to ${records[centre].name}` : 'Nearest to view centre';
  } else {
    const matches = [];
    for (let i = 0; i < N; i++) if (!isHidden(i) && namesLower[i].includes(q)) matches.push(i);
    // Names starting with the query first, then brightest as seen from Sol
    matches.sort((a, b) => (namesLower[b].startsWith(q) - namesLower[a].startsWith(q))
      || (brightnessFromSol(a) - brightnessFromSol(b)));
    indices = matches.slice(0, LIST_MAX_MATCHES);
    listTitle.textContent = matches.length > LIST_MAX_MATCHES
      ? `First ${LIST_MAX_MATCHES} of ${matches.length.toLocaleString()} matches`
      : `${matches.length} match${matches.length === 1 ? '' : 'es'}`;
  }

  listEl.replaceChildren(...indices.map((i) => {
    const li = document.createElement('li');
    li.dataset.index = i;
    if (kind[i]) li.classList.add(KIND_CLASS[kind[i]]);
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = sw.style.color = displayColour(i);
    if (kind[i] === KIND_BLACK_HOLE && colourMode !== 'spectral') sw.style.borderColor = displayColour(i);
    const nm = document.createElement('span');
    nm.className = 'name';
    nm.textContent = records[i].name;
    const dist = document.createElement('span');
    dist.className = 'dist';
    dist.textContent = formatListDistance(Math.hypot(pos[3 * i] - controls.target.x,
      pos[3 * i + 1] - controls.target.y, pos[3 * i + 2] - controls.target.z));
    li.append(sw, nm, dist);
    li.addEventListener('click', () => selectStar(i));
    li.addEventListener('dblclick', () => focusStar(i));
    return li;
  }));
  highlightList();
}

function highlightList() {
  for (const li of listEl.children) {
    const i = Number(li.dataset.index);
    li.classList.toggle('selected', i === selected);
    li.classList.toggle('centre', i === centre);
  }
}

let listTimer = null;
function scheduleListRefresh() {
  if (searchEl.value.trim()) return; // search results don't depend on the view
  clearTimeout(listTimer);
  listTimer = setTimeout(renderList, 250);
}

// ---------- Selection / details ----------
const fmt = (n) => `${n.toFixed(3)} pc`;
// Like fmt, but switches to kpc / Mpc for extragalactic distances
function fmtLarge(n) {
  const a = Math.abs(n);
  if (a < 1e5) return fmt(n);
  return a < 1e6 ? `${(n / 1e3).toFixed(2)} kpc` : `${(n / 1e6).toFixed(3)} Mpc`;
}
// Sidebar list distances (pc, kpc above 100 kpc, Mpc above 1 Mpc)
function formatListDistance(d) {
  return d < 1e5 ? d.toFixed(2) : d < 1e6 ? `${(d / 1e3).toFixed(0)} kpc` : `${(d / 1e6).toFixed(1)} Mpc`;
}

function formatGalaxySize(d) {
  if (typeof d.size_arcmin !== 'number' || typeof d.distance_pc !== 'number') return null;
  const kpc = d.distance_pc * Math.tan(THREE.MathUtils.degToRad(d.size_arcmin / 60)) / 1e3;
  const ang = d.size_arcmin >= 60 ? `${+(d.size_arcmin / 60).toFixed(1)}°` : `${d.size_arcmin}′`;
  return `≈ ${kpc >= 10 ? kpc.toFixed(0) : kpc.toFixed(1)} kpc across (${ang} on the sky)`;
}

function formatMass(m) {
  if (typeof m !== 'number') return null;
  const text = m >= 1e6 ? `${+(m / 1e6).toFixed(2)} million` : m.toLocaleString();
  return `${text} M☉`;
}

function formatNebulaSize(d) {
  if (typeof d.radius_pc !== 'number') return null;
  const r = d.radius_pc;
  const text = r >= 10 ? r.toFixed(0) : r >= 1 ? r.toFixed(1) : r.toFixed(2);
  return d.puffs ? `≈ ${text} pc extent (${d.puffs.length} sightline${d.puffs.length > 1 ? 's' : ''})`
    : `${text} pc radius`;
}

function formatDistanceRef(d) {
  if (!d.distance_ref) return null;
  const range = Array.isArray(d.distance_range_pc) ? ` (${d.distance_range_pc[0]}–${d.distance_range_pc[1]} pc)` : '';
  return `${d.distance_ref}${range}`;
}

function updateFilter(force = false) {
  if (!N) return;
  // Galaxies never anchor the filter (they are exempt from it, and a sphere round one would hide every star)
  const anchorSel = selected >= 0 && kind[selected] !== KIND_GALAXY ? selected : -1;
  const anchor = filterRadius > 0 ? (anchorSel >= 0 ? anchorSel : centre >= 0 ? centre : solIndex) : -1;
  const radiusChanged = starMaterial.uniforms.uFilterRadius.value !== filterRadius;
  if (anchor === filterAnchor && !radiusChanged && !force) return;
  filterAnchor = anchor;
  starMaterial.uniforms.uFilterRadius.value = filterRadius;
  if (anchor >= 0) starPos(anchor, filterCentre);
  updateNebulaVisibility();
  const status = document.getElementById('distance-status');
  if (anchor >= 0) {
    let count = 0;
    for (let i = 0; i < N; i++) if (!isHidden(i)) count++;
    status.textContent = `${count.toLocaleString()} shown within ${filterRadius} pc of ${records[anchor].name}`;
  } else {
    status.textContent = '';
  }
  labelsDirty = true;
  renderList();
}

function selectStar(i) {
  selected = i;
  updateFilter();
  labelsDirty = true;
  selectionRing.visible = i >= 0;
  selectedDrop.set(i);
  highlightList();
  if (i < 0) {
    document.getElementById('details').classList.add('hidden');
    return;
  }
  starPos(i, selectionRing.position);
  const li = listEl.querySelector(`li[data-index="${i}"]`);
  if (li) li.scrollIntoView({ block: 'nearest' });

  const d = records[i];
  const p = starPos(i);
  document.getElementById('d-name').textContent = d.name;
  document.getElementById('d-class').textContent = d.spectral_class;
  document.getElementById('d-colour').textContent = d.colour;
  const sw = document.getElementById('d-swatch');
  sw.style.background = sw.style.color = d.colour;
  document.getElementById('d-absmag').textContent = d.abs_mag ?? '—';
  const sov = sovOf[i] >= 0 ? sovereignties[sovOf[i]] : null;
  document.getElementById('row-sovereignty').hidden = !sov;
  if (sov) {
    document.getElementById('d-sovereignty').textContent = sov.name;
    const ss = document.getElementById('d-sov-swatch');
    ss.style.background = ss.style.color = sov.colour;
  }
  for (const [id, value] of [['type', d.type], ['constellation', d.constellation], ['mass', formatMass(d.mass_msun)],
    ['notes', d.notes], ['ids', d.ids], ['size', formatNebulaSize(d) ?? formatGalaxySize(d)],
    ['distref', formatDistanceRef(d)]]) {
    document.getElementById(`d-${id}`).textContent = value ?? '';
    document.getElementById(`row-${id}`).hidden = !value;
  }
  const isNebula = kind[i] === KIND_NEBULA;
  const isGalaxy = kind[i] === KIND_GALAXY;
  document.getElementById('h-class').textContent = isNebula ? 'Class' : isGalaxy ? 'Morphology' : 'Spectral class';
  document.getElementById('row-absmag').hidden = isNebula || (isGalaxy && typeof d.abs_mag !== 'number');
  document.getElementById('h-absmag').textContent = isGalaxy ? 'Absolute magnitude (V, approx.)' : 'Absolute magnitude';
  updatePlanetRow(i);
  const tag = frame === 'galactic' ? 'gal' : 'eq';
  for (const [k, v] of [['x', p.x], ['y', p.y], ['z', p.z]]) {
    document.getElementById(`d-${k}`).textContent = fmtLarge(v);
    document.getElementById(`h-${k}`).textContent = `${k.toUpperCase()} (${tag})`;
  }
  const g = frame === 'galactic' ? p.clone() : p.clone().applyMatrix3(EQ_TO_GAL);
  const r = g.length();
  document.getElementById('d-galactic').textContent = r > 0
    ? `${((THREE.MathUtils.radToDeg(Math.atan2(g.y, g.x)) + 360) % 360).toFixed(3)}°, `
      + `${THREE.MathUtils.radToDeg(Math.asin(g.z / r)).toFixed(3)}°`
    : '—';
  const sol = p.length();
  document.getElementById('d-dist').textContent = sol < 1e5
    ? `${fmt(sol)} (${(sol * 3.26156).toFixed(2)} ly)`
    : formatDistance(sol);
  updateCentreDistance();
  document.getElementById('details').classList.remove('hidden');
}

function updateCentreDistance() {
  if (selected < 0) return;
  const centreName = centre >= 0 ? records[centre].name : 'view centre';
  document.getElementById('d-centre').textContent =
    `${fmtLarge(starPos(selected).distanceTo(controls.target))} (${centreName})`;
}

function updateCentreInfo() {
  const t = controls.target;
  document.getElementById('centre-info').textContent = centre >= 0
    ? `Rotating around: ${records[centre].name}`
    : `Rotating around: (${t.x.toFixed(2)}, ${t.y.toFixed(2)}, ${t.z.toFixed(2)}) pc`;
  centreDrop.set(centre);
  labelsDirty = true;
  highlightList();
  updateFilter();
}

// ---------- Smooth camera moves ----------
let animation = null;

function animateTo(newTarget, newCamPos, onDone, instant = false) {
  animation = {
    start: performance.now() - (instant ? FOCUS_DURATION_MS : 0),
    fromTarget: controls.target.clone(),
    fromCam: camera.position.clone(),
    toTarget: newTarget.clone(),
    toCam: newCamPos.clone(),
    onDone,
  };
}

function stepAnimation(now) {
  if (!animation) return;
  const t = Math.min(1, (now - animation.start) / FOCUS_DURATION_MS);
  const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; // easeInOutCubic
  controls.target.lerpVectors(animation.fromTarget, animation.toTarget, e);
  camera.position.lerpVectors(animation.fromCam, animation.toCam, e);
  if (t >= 1) {
    const done = animation.onDone;
    animation = null;
    if (done) done();
  }
}

function afterMove() {
  updateCentreInfo();
  updateCentreDistance();
  scheduleListRefresh();
}

function focusStar(i) {
  // Extragalactic objects can't become the rotation centre (they are millions of parsecs away); just select them
  if (kind[i] === KIND_GALAXY) {
    selectStar(i);
    return;
  }
  // Keep current viewing direction and distance; just move the pivot to the star
  const offset = camera.position.clone().sub(controls.target);
  const p = starPos(i);
  centre = i;
  selectStar(i);
  animateTo(p, p.clone().add(offset), afterMove);
  updateCentreInfo();
}

const VIEW_DIR = new THREE.Vector3(1, -1.4, 0.9).normalize();

function viewSphere(centrePoint, radius, instant = false) {
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.1;
  animateTo(centrePoint, centrePoint.clone().addScaledVector(VIEW_DIR, dist), afterMove, instant);
}

function resetView(instant = false) {
  centre = solIndex;
  const home = solIndex >= 0 ? starPos(solIndex) : allBounds.center;
  viewSphere(home, HOME_DISTANCE_PC * Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) / 1.1, instant);
}

function showAll() {
  centre = -1;
  viewSphere(allBounds.center, Math.max(allBounds.radius, 1));
}

// ---------- Mouse / keyboard ----------
let downPos = null;
renderer.domElement.addEventListener('pointerdown', (e) => { downPos = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downPos || e.button !== 0) return;
  const moved = Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y);
  downPos = null;
  if (moved > CLICK_MOVE_TOLERANCE) return; // it was a drag, not a click
  selectStar(pickStar(e.clientX, e.clientY));
});
renderer.domElement.addEventListener('dblclick', (e) => {
  const i = pickStar(e.clientX, e.clientY);
  if (i >= 0) focusStar(i);
});

let hoverEvent = null;
renderer.domElement.addEventListener('pointermove', (e) => {
  if (e.buttons) return;
  if (!hoverEvent) {
    requestAnimationFrame(() => {
      renderer.domElement.style.cursor = pickStar(hoverEvent.clientX, hoverEvent.clientY) >= 0 ? 'pointer' : 'grab';
      hoverEvent = null;
    });
  }
  hoverEvent = e;
});

controls.addEventListener('change', () => {
  if (animation) return;
  // User panning moves the pivot off the star
  if (centre >= 0 && controls.target.distanceTo(starPos(centre)) > 1e-4) {
    centre = -1;
    updateCentreInfo();
  }
  updateCentreDistance();
});
controls.addEventListener('end', scheduleListRefresh);

document.getElementById('reset-view').addEventListener('click', () => resetView());
document.getElementById('show-all').addEventListener('click', showAll);
document.getElementById('close-details').addEventListener('click', () => selectStar(-1));
document.getElementById('toggle-grid').addEventListener('change', (e) => { helpers.visible = e.target.checked; });
document.getElementById('toggle-labels').addEventListener('change', (e) => {
  labelLayer.hidden = !e.target.checked;
  labelsDirty = true;
});
function bindKindToggle(id, k, uniform) {
  document.getElementById(id).addEventListener('change', (e) => {
    kindVisible[k] = e.target.checked;
    starMaterial.uniforms[uniform].value = e.target.checked ? 1.0 : 0.0;
    visibilityChanged();
  });
}
bindKindToggle('toggle-stars', 0, 'uShowStar');
bindKindToggle('toggle-neutron', KIND_NEUTRON, 'uShowNeutron');
bindKindToggle('toggle-blackhole', KIND_BLACK_HOLE, 'uShowBlackHole');
bindKindToggle('toggle-nebula', KIND_NEBULA, 'uShowNebula');
bindKindToggle('toggle-galaxy', KIND_GALAXY, 'uShowGalaxy');
document.getElementById('frame-select').addEventListener('change', (e) => setFrame(e.target.value));

function buildClassFilter() {
  const counts = SPEC_CLASSES.map(() => 0);
  for (let i = 0; i < firstSpecial; i++) counts[specClass[i]]++;
  const row = document.getElementById('class-filter');
  const chips = SPEC_CLASSES.map((name, c) => {
    const b = document.createElement('button');
    b.className = 'class-chip on';
    b.textContent = name;
    b.style.setProperty('--chip', SPEC_COLOURS[c]);
    b.title = `${counts[c].toLocaleString()} ${name === 'Other' ? 'other stars (white dwarfs, carbon, Wolf-Rayet, unclassified)' : `${name}-type stars`}`
      + '\nClick to show/hide · double-click to show only this class';
    b.addEventListener('click', () => setClassVisibility(classVisible.map((v, k) => (k === c ? !v : v))));
    b.addEventListener('dblclick', () => setClassVisibility(classVisible.map((_, k) => k === c)));
    return b;
  });
  const all = document.createElement('button');
  all.className = 'class-chip all';
  all.textContent = 'All';
  all.title = 'Show every spectral class';
  all.addEventListener('click', () => setClassVisibility(classVisible.map(() => true)));
  row.replaceChildren(...chips, all);

  function setClassVisibility(vis) {
    vis.forEach((v, k) => {
      classVisible[k] = v;
      starMaterial.uniforms.uClassVisible.value[k] = v ? 1.0 : 0.0;
      chips[k].classList.toggle('on', v);
    });
    visibilityChanged();
  }
}

function buildNebulaFilter() {
  const counts = NEB_TYPES.map(() => 0);
  for (let i = firstSpecial; i < N; i++) if (kind[i] === KIND_NEBULA) counts[specClass[i]]++;
  const chips = NEB_TYPES.map((t, c) => {
    const b = document.createElement('button');
    b.className = 'class-chip on';
    b.textContent = t.label;
    b.style.setProperty('--chip', t.colour);
    b.title = `${t.title} (${counts[c]})\nClick to show/hide · double-click to show only this type`;
    b.addEventListener('click', () => setTypeVisibility(nebTypeVisible.map((v, k) => (k === c ? !v : v))));
    b.addEventListener('dblclick', () => setTypeVisibility(nebTypeVisible.map((_, k) => k === c)));
    return b;
  });
  document.getElementById('nebula-filter').replaceChildren(...chips);

  function setTypeVisibility(vis) {
    vis.forEach((v, k) => {
      nebTypeVisible[k] = v;
      starMaterial.uniforms.uNebTypeVisible.value[k] = v ? 1.0 : 0.0;
      chips[k].classList.toggle('on', v);
    });
    visibilityChanged();
  }
}

// Shared refresh after any show/hide filter changes
function visibilityChanged() {
  if (selected >= 0 && isHidden(selected)) selectStar(-1);
  updateFilter(true);
  labelsDirty = true;
  renderList();
}
document.getElementById('colour-mode').addEventListener('change', (e) => {
  colourMode = e.target.value;
  applyColourState();
});
document.getElementById('toggle-unclaimed').addEventListener('change', (e) => {
  showUnclaimed = e.target.checked;
  applyColourState();
});
document.getElementById('toggle-confirmed').addEventListener('change', (e) => {
  confirmedOnly = e.target.checked;
  applyColourState();
});

// Recompute per-star colour / visibility after the colour mode or a legend toggle changes
function applyColourState() {
  if (!N) return;
  const sovMode = colourMode === 'sovereignty';
  const planetMode = colourMode === 'planets' && planetCat !== null;
  for (let i = 0; i < N; i++) {
    if (planetMode) {
      const c = planetCat[i];
      sovState[i] = c < 0 ? SOV_NORMAL
        : (!planetVisible[c] || (confirmedOnly && !(planetFlags[i] & PF_CONFIRMED))) ? SOV_HIDDEN
          : c === PLANET_HABITABLE ? SOV_MEMBER : SOV_NORMAL;
      continue;
    }
    const s = sovOf[i];
    sovState[i] = !sovMode ? SOV_NORMAL
      : s < 0 ? (showUnclaimed ? SOV_NORMAL : SOV_HIDDEN)
        : (sovVisible[s] ? SOV_MEMBER : SOV_HIDDEN);
  }
  sovStateAttr.needsUpdate = true;
  colourAttr.array.set(sovMode ? sovColours : planetMode ? planetColours : naturalColours);
  colourAttr.needsUpdate = true;
  document.getElementById('sovereignty-legend').hidden = !sovMode;
  document.getElementById('planet-legend').hidden = !planetMode;
  if (selected >= 0 && isHidden(selected)) selectStar(-1);
  updateFilter(true);
  labelsDirty = true;
  renderList();
}

function renderSovereigntyLegend() {
  const list = document.getElementById('sovereignty-list');
  list.replaceChildren(...sovereignties.map((s, k) => {
    const li = document.createElement('li');
    li.title = `${s.notes ? `${s.notes}\n` : ''}Click to fit the view to this sovereignty`;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = sovVisible[k];
    cb.title = 'Show / hide this sovereignty';
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => {
      sovVisible[k] = cb.checked;
      li.classList.toggle('off', !cb.checked);
      applyColourState();
    });
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = sw.style.color = s.colour;
    const nm = document.createElement('span');
    nm.className = 'name';
    nm.textContent = s.name;
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = sovCount[k];
    li.append(cb, sw, nm, count);
    li.addEventListener('click', () => fitSovereignty(k));
    return li;
  }));
}

function fitSovereignty(k) {
  const members = [];
  for (let i = 0; i < N; i++) if (sovOf[i] === k) members.push(i);
  if (!members.length) return;
  if (members.length === 1) { focusStar(members[0]); return; }
  const box = new THREE.Box3();
  const p = new THREE.Vector3();
  for (const i of members) box.expandByPoint(starPos(i, p));
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  centre = -1;
  viewSphere(sphere.center, Math.max(sphere.radius, 0.5));
}
let distanceTimer = null;
document.getElementById('distance-filter').addEventListener('input', (e) => {
  clearTimeout(distanceTimer);
  distanceTimer = setTimeout(() => {
    const r = parseFloat(e.target.value);
    filterRadius = Number.isFinite(r) && r > 0 ? r : 0;
    updateFilter();
  }, 200);
});
let searchTimer = null;
searchEl.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderList, 120);
});
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') { selectStar(-1); hideSystem(); } });

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  labelsDirty = true;
});

// ---------- Load data & start ----------
async function init() {
  document.getElementById('centre-info').textContent = 'Loading stars…';
  const [responses, sovResponse] = await Promise.all([
    Promise.all([fetch('/api/stars'), ...OVERLAYS.map((o) => fetch(o.url))]),
    fetch('/api/sovereignties').catch((err) => ({ ok: false, status: err.message })),
  ]);
  const res = responses[0];
  if (!res.ok) throw new Error(`Failed to load stars (${res.status})`);
  const db = await res.json();
  records = db.stars.slice();
  const kinds = [];
  const counts = [];
  for (let k = 0; k < OVERLAYS.length; k++) {
    const r = responses[k + 1];
    const list = r.ok ? (await r.json())[OVERLAYS[k].key ?? 'stars'] : [];
    if (!r.ok) console.warn(`${OVERLAYS[k].label} unavailable (${r.status})`);
    for (const s of list) { records.push(s); kinds.push(OVERLAYS[k].kind); }
    counts.push(`${list.length} ${OVERLAYS[k].label}`);
  }

  N = records.length;
  firstSpecial = db.stars.length;
  pos = new Float32Array(3 * N);
  absMag = new Float32Array(N);
  isNamed = new Uint8Array(N);
  kind = new Uint8Array(N);
  specClass = new Uint8Array(N);
  labelWidth = new Float32Array(N);
  scrX = new Float32Array(N);
  scrY = new Float32Array(N);
  scrKey = new Float32Array(N);
  scrBin = new Int16Array(N);
  namesLower = new Array(N);
  const v = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    const s = records[i];
    v.set(s.x, s.y, s.z).applyMatrix3(EQ_TO_GAL);
    pos[3 * i] = v.x;
    pos[3 * i + 1] = v.y;
    pos[3 * i + 2] = v.z;
    absMag[i] = typeof s.abs_mag === 'number' ? s.abs_mag : DEFAULT_ABS_MAG;
    isNamed[i] = CATALOGUE_ID.test(s.name) ? 0 : 1;
    kind[i] = i >= firstSpecial ? kinds[i - firstSpecial] : 0;
    specClass[i] = mainSpectralClass(s.spectral_class);
    if (kind[i] === KIND_NEBULA) {
      specClass[i] = Math.max(0, NEB_TYPES.findIndex((t) => t.key === s.nebula_type));
      absMag[i] = NEB_LABEL_MAG[s.source] ?? NEB_LABEL_MAG_DEFAULT;
    } else if (kind[i] === KIND_GALAXY) {
      specClass[i] = 0;
      if (typeof s.abs_mag !== 'number') absMag[i] = GALAXY_DEFAULT_ABS_MAG;
    }
    namesLower[i] = (kind[i] === KIND_GALAXY && s.ids ? `${s.name} ${s.ids}` : s.name).toLowerCase();
    if (solIndex < 0 && s.x === 0 && s.y === 0 && s.z === 0) solIndex = i;
  }
  await loadSovereignties(sovResponse);
  buildClassFilter();
  buildNebulaFilter();
  buildPoints();
  buildNebulae();
  computeBounds();
  document.getElementById('star-count').textContent =
    [`${db.stars.length.toLocaleString()} stars`, ...counts].join(' · ');

  resetView(true);
  stepAnimation(performance.now());
  renderList();
  loadPlanets();
}

// Resolve sovereignty membership with a single pass over the catalogue (only member names are hashed)
async function loadSovereignties(res) {
  sovOf = new Int16Array(N).fill(-1);
  sovState = new Float32Array(N);
  sovereignties = [];
  if (res.ok) {
    sovereignties = (await res.json()).sovereignties ?? [];
  } else {
    console.warn(`Sovereignties unavailable (${res.status})`);
  }
  const owner = new Map();
  sovereignties.forEach((s, k) => { for (const name of s.stars) owner.set(name, k); });
  sovCount = sovereignties.map(() => 0);
  sovVisible = sovereignties.map(() => true);
  const found = new Set();
  if (owner.size) {
    for (let i = 0; i < N; i++) {
      const k = owner.get(records[i].name);
      if (k !== undefined) { sovOf[i] = k; sovCount[k]++; found.add(records[i].name); }
    }
  }
  const missing = [...owner.keys()].filter((n) => !found.has(n));
  if (missing.length) console.warn(`Sovereignty members not found in the catalogue: ${missing.join(', ')}`);
  document.getElementById('colour-mode').querySelector('option[value="sovereignty"]').disabled = !sovereignties.length;
  renderSovereigntyLegend();
}

// ---------- Planetary systems ----------
const PLANET_TYPE_LABELS = {
  terrestrial: 'Terrestrial', super_earth: 'Super-Earth', sub_neptune: 'Sub-Neptune',
  neptune: 'Ice giant', gas_giant: 'Gas giant',
};
const PLANET_TYPE_COLOURS = {
  terrestrial: '#c9a27a', super_earth: '#d8b98d', sub_neptune: '#7fc4d9', neptune: '#5b8cff', gas_giant: '#e0a35a',
};
let systemIndex = -1;
let systemRequest = 0;

async function loadPlanets() {
  const option = document.getElementById('colour-mode').querySelector('option[value="planets"]');
  try {
    const res = await fetch('/api/systems-summary');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const summary = await res.json();
    if (summary.planets.length !== firstSpecial) throw new Error('summary does not match the star catalogue');
    planetCount = new Uint16Array(N);
    planetFlags = new Uint8Array(N);
    planetCat = new Int8Array(N).fill(-1);
    planetColours = naturalColours.slice();
    const rgb = PLANET_CATS.map((c) => hexToRgb(c.colour));
    for (let i = 0; i < firstSpecial; i++) {
      const n = summary.planets[i], f = summary.flags[i];
      planetCount[i] = n;
      planetFlags[i] = f;
      const c = f & (PF_HABITABLE | PF_HAB_MOON) ? PLANET_HABITABLE : f & PF_HZ ? 2 : n > 0 ? 1 : 0;
      planetCat[i] = c;
      planetColours.set(rgb[c], 3 * i);
    }
    option.textContent = 'Planets';
    option.disabled = false;
    renderPlanetLegend();
    if (selected >= 0) updatePlanetRow(selected);
  } catch (err) {
    console.warn(`Planetary systems unavailable (${err.message})`);
    option.textContent = 'Planets (unavailable)';
  }
}

function renderPlanetLegend() {
  const counts = PLANET_CATS.map(() => 0);
  for (let i = 0; i < firstSpecial; i++) counts[planetCat[i]]++;
  document.getElementById('planet-list').replaceChildren(...PLANET_CATS.map((c, k) => {
    const li = document.createElement('li');
    li.title = c.title;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = planetVisible[k];
    cb.addEventListener('change', () => {
      planetVisible[k] = cb.checked;
      li.classList.toggle('off', !cb.checked);
      applyColourState();
    });
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = sw.style.color = c.colour;
    const nm = document.createElement('span');
    nm.className = 'name';
    nm.textContent = c.label;
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = counts[k].toLocaleString();
    const label = document.createElement('label');
    label.style.display = 'contents';
    label.append(cb, sw, nm);
    li.append(label, count);
    return li;
  }));
}

function updatePlanetRow(i) {
  const row = document.getElementById('row-planets');
  row.hidden = i < 0 || kind[i] !== 0;
  if (row.hidden) {
    if (systemIndex >= 0) hideSystem();
    return;
  }
  const text = document.getElementById('d-planets');
  const button = document.getElementById('view-system');
  if (!planetCount) {
    text.textContent = 'loading…';
    button.disabled = true;
    return;
  }
  button.disabled = false;
  const n = planetCount[i], f = planetFlags[i];
  const parts = [n === 0 ? 'none' : `${n} ${f & PF_CONFIRMED ? 'confirmed' : 'simulated'}`];
  if (f & PF_HABITABLE) parts.push('potentially habitable');
  else if (f & PF_HAB_MOON) parts.push('habitable moon');
  else if (f & PF_HZ) parts.push('in habitable zone');
  text.textContent = parts.join(' · ');
  text.style.color = planetCat[i] >= 2 ? PLANET_CATS[planetCat[i]].colour : '';
  if (systemIndex >= 0 && systemIndex !== i) showSystem(i);
}

document.getElementById('view-system').addEventListener('click', () => { if (selected >= 0) showSystem(selected); });
document.getElementById('close-system').addEventListener('click', hideSystem);

function hideSystem() {
  systemIndex = -1;
  systemRequest++;
  document.getElementById('system-panel').classList.add('hidden');
}

const sig = (x, digits = 3) => (x === null || x === undefined ? '—'
  : Number(x).toLocaleString(undefined, { maximumSignificantDigits: digits }));
const formatPeriod = (d) => (d >= 1000 ? `${sig(d / 365.25)} yr` : d < 1 ? `${sig(d * 24)} h` : `${sig(d)} d`);
const svgEl = (tag, attrs) => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};

async function showSystem(i) {
  systemIndex = i;
  const request = ++systemRequest;
  const panel = document.getElementById('system-panel');
  document.getElementById('s-title').textContent = `${records[i].name} system`;
  document.getElementById('s-planets').replaceChildren();
  document.getElementById('s-diagram').replaceChildren();
  for (const id of ['s-badge', 's-star', 's-hz', 's-notes']) document.getElementById(id).textContent = '';
  document.getElementById('s-star').textContent = 'Loading…';
  panel.classList.remove('hidden');
  try {
    const res = await fetch(`/api/system/${encodeURIComponent(records[i].name)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const system = await res.json();
    if (request === systemRequest) renderSystem(system);
  } catch (err) {
    if (request === systemRequest) document.getElementById('s-star').textContent = `Could not load system: ${err.message}`;
  }
}

function renderSystem(sys) {
  const st = sys.star, hz = sys.habitable_zone;
  const badge = document.getElementById('s-badge');
  const badges = [sys.confirmed
    ? ['confirmed', sys.name === 'Sol' ? 'Real Solar System' : 'Confirmed planets · NASA Exoplanet Archive']
    : ['simulated', `Simulated system (seed ${sys.seed})`]];
  if (sys.flags & (PF_HABITABLE | PF_HAB_MOON)) badges.push(['habitable', 'Potentially habitable']);
  badge.replaceChildren(...badges.map(([cls, text]) => {
    const b = document.createElement('span');
    b.className = `badge ${cls}`;
    b.textContent = text;
    return b;
  }));
  const starText = [`${st.category_label} (${st.spectral_class})`, `T ${sig(st.teff, 4)} K`, `L ${sig(st.lum)} L☉`,
    `M ${sig(st.mass)} M☉`, `R ${sig(st.radius)} R☉`];
  if (st.metallicity !== null && st.metallicity !== undefined) starText.push(`[Fe/H] ${st.metallicity.toFixed(2)} (simulated)`);
  const starEl = document.getElementById('s-star');
  starEl.textContent = starText.join(' · ');
  starEl.title = `Stellar parameters: ${st.source}`;
  document.getElementById('s-hz').textContent =
    `Habitable zone: ${sig(hz.conservative_au[0])}–${sig(hz.conservative_au[1])} AU conservative, `
    + `${sig(hz.optimistic_au[0])}–${sig(hz.optimistic_au[1])} AU optimistic · snow line ${sig(sys.snow_line_au)} AU`
    + (hz.extrapolated ? ' · (extrapolated: star outside 2600–7200 K)' : '');

  drawSystemDiagram(sys);
  renderPlanetTable(sys);

  const notes = [];
  if (!st.habitable_host) notes.push('Not a stable main-sequence star, so no planet is counted as habitable.');
  if (sys.hosts.length && (sys.hosts.length > 1 || sys.name !== 'Sol')) notes.push(`Archive host${sys.hosts.length > 1 ? 's' : ''}: ${sys.hosts.join(', ')}.`);
  if (sys.planets.some((p) => p.mass_kind === 'Msini')) notes.push('≥ : minimum mass (radial velocity, M sin i).');
  if (sys.planets.some((p) => p.mass_estimated || p.radius_estimated)) notes.push('~ : estimated from the mass–radius relation (Chen & Kipping 2017).');
  if (sys.confirmed && sys.planets.some((p) => p.moons_simulated)) notes.push('Exomoons are simulated (none confirmed yet).');
  if (!sys.confirmed) notes.push('Planets and moons are a statistically plausible draw from measured occurrence rates, not observations.');
  document.getElementById('s-notes').textContent = notes.join(' ');
}

function drawSystemDiagram(sys) {
  const svg = document.getElementById('s-diagram');
  const W = 600, H = 110, PAD = 14, MID = 62;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const hz = sys.habitable_zone;
  let lo = hz.optimistic_au[0] * 0.7, hi = hz.optimistic_au[1] * 1.5;
  for (const p of sys.planets) {
    lo = Math.min(lo, p.a_au * (1 - p.e) * 0.8);
    hi = Math.max(hi, p.a_au * (1 + p.e) * 1.25);
  }
  lo = Math.max(lo, 1e-3);
  const l0 = Math.log10(lo), l1 = Math.log10(hi);
  const x = (a) => PAD + (W - 2 * PAD) * (Math.log10(Math.max(a, lo)) - l0) / (l1 - l0);
  const band = (range, fill, label) => {
    const r = svgEl('rect', { x: x(range[0]), y: 18, width: Math.max(1, x(range[1]) - x(range[0])), height: 76, fill });
    r.append(svgEl('title', {}));
    r.firstChild.textContent = label;
    svg.append(r);
  };
  band(hz.optimistic_au, 'rgba(255,176,46,0.14)', 'Optimistic habitable zone');
  band(hz.conservative_au, 'rgba(61,220,132,0.22)', 'Conservative habitable zone');
  svg.append(svgEl('line', { x1: PAD, x2: W - PAD, y1: MID, y2: MID, stroke: '#2c3a66' }));
  const ticks = [];
  for (let k = Math.floor(l0); k <= Math.ceil(l1); k++) {
    for (const m of (l1 - l0 < 2 ? [1, 2, 5] : [1])) {
      const v = m * 10 ** k;
      if (v >= lo && v <= hi) ticks.push([v, k]);
    }
  }
  for (const [v, k] of ticks) {
    const tx = x(v);
    svg.append(svgEl('line', { x1: tx, x2: tx, y1: 94, y2: 98, stroke: '#5a6890' }));
    const t = svgEl('text', { x: tx, y: 108, 'text-anchor': 'middle' });
    t.textContent = `${v >= 1 ? v : v.toFixed(-k)} AU`;
    svg.append(t);
  }
  const snow = x(sys.snow_line_au);
  if (sys.snow_line_au > lo && sys.snow_line_au < hi) {
    svg.append(svgEl('line', { x1: snow, x2: snow, y1: 18, y2: 94, stroke: '#9fd8ff', 'stroke-dasharray': '3 3', 'stroke-opacity': 0.6 }));
    const t = svgEl('text', { x: snow + 3, y: 26 });
    t.textContent = 'snow line';
    svg.append(t);
  }
  sys.planets.forEach((p, k) => {
    const cx = x(p.a_au);
    if (p.e > 0.02) {
      svg.append(svgEl('line', { x1: x(p.a_au * (1 - p.e)), x2: x(p.a_au * (1 + p.e)), y1: MID, y2: MID,
        stroke: PLANET_TYPE_COLOURS[p.type], 'stroke-opacity': 0.45, 'stroke-width': 3 }));
    }
    const r = Math.min(9, Math.max(2.5, 3 + 4 * Math.log10(p.radius_rearth)));
    const dot = svgEl('circle', { cx, cy: MID, r, fill: PLANET_TYPE_COLOURS[p.type], class: 'planet-dot',
      stroke: p.habitable ? '#3ddc84' : 'none', 'stroke-width': 2 });
    const title = svgEl('title', {});
    title.textContent = `${p.name}: ${p.description}, a = ${sig(p.a_au)} AU`;
    dot.append(title);
    dot.addEventListener('click', () => toggleSystemPlanet(k, true));
    svg.append(dot);
    const label = svgEl('text', { x: cx, y: k % 2 ? MID + 22 : MID - 14, 'text-anchor': 'middle' });
    label.textContent = p.name.startsWith(sys.name) ? p.name.slice(sys.name.length).trim() || p.name : p.name;
    svg.append(label);
  });
}

function renderPlanetTable(sys) {
  const body = document.getElementById('s-planets');
  const rows = [];
  const cell = (text, title) => {
    const td = document.createElement('td');
    td.textContent = text;
    if (title) td.title = title;
    return td;
  };
  sys.planets.forEach((p, k) => {
    const tr = document.createElement('tr');
    tr.className = `planet${p.habitable ? ' habitable' : p.hz ? ' hz' : ''}`;
    tr.dataset.planet = k;
    const hzCell = cell(p.hz ? (p.hz === 'conservative' ? 'C' : 'O') : '—',
      p.hz ? `${p.hz === 'conservative' ? 'Conservative' : 'Optimistic'} habitable zone` : 'Outside the habitable zone');
    if (p.hz) hzCell.className = p.hz === 'conservative' ? 'hz-c' : 'hz-o';
    const massPrefix = p.mass_estimated ? '~' : p.mass_kind === 'Msini' ? '≥' : '';
    const moonText = p.moons.length || p.minor_moons
      ? `${p.moons.length}${p.minor_moons ? ` + ${p.minor_moons} minor` : ''}` : '—';
    tr.append(cell(`${p.name}${p.disputed ? ' ?' : ''}`, p.disputed ? 'Disputed / controversial detection' : ''),
      cell(PLANET_TYPE_LABELS[p.type]), cell(sig(p.a_au)), cell(formatPeriod(p.period_d)), cell(sig(p.e, 2)),
      cell(`${p.radius_estimated ? '~' : ''}${sig(p.radius_rearth)}`), cell(`${massPrefix}${sig(p.mass_mearth)}`),
      cell(`${sig(p.teq_k)} K`), hzCell, cell(moonText));
    tr.addEventListener('click', () => toggleSystemPlanet(k));
    rows.push(tr);

    const detail = document.createElement('tr');
    detail.className = 'detail';
    detail.dataset.parent = k;
    detail.hidden = true;
    const info = [p.description, `insolation ${sig(p.insolation)} S⊕`];
    if (p.tidally_locked) info.push('likely tidally locked');
    if (p.habitable) info.push('potentially habitable');
    if (p.source === 'confirmed' && p.discovery) info.push(`discovered ${p.year ?? ''} by ${p.discovery.toLowerCase()}`);
    else if (p.source === 'simulated') info.push('simulated');
    const td = document.createElement('td');
    td.colSpan = 10;
    td.textContent = info.join(' · ');
    detail.append(td);
    rows.push(detail);

    for (const m of p.moons) {
      const mr = document.createElement('tr');
      mr.className = `moon${m.habitable ? ' habitable' : ''}`;
      mr.dataset.parent = k;
      mr.hidden = true;
      mr.append(cell(m.name), cell(m.habitable ? 'Moon (habitable size)' : 'Moon'), cell(`${sig(m.a_km)} km`),
        cell(formatPeriod(m.period_d)), cell(''), cell(`${sig(m.radius_km)} km`), cell(sig(m.mass_mearth)),
        cell(''), cell(''), cell(''));
      rows.push(mr);
    }
  });
  if (!sys.planets.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 10;
    td.textContent = 'No planets.';
    tr.append(td);
    rows.push(tr);
  }
  body.replaceChildren(...rows);
}

function toggleSystemPlanet(k, open = false) {
  const body = document.getElementById('s-planets');
  const row = body.querySelector(`tr.planet[data-planet="${k}"]`);
  const show = open || !row.classList.contains('hl');
  for (const tr of body.querySelectorAll(`tr[data-parent="${k}"]`)) tr.hidden = !show;
  row.classList.toggle('hl', show);
  if (open) row.scrollIntoView({ block: 'nearest' });
}

function computeBounds() {
  // "Show all" fits the star catalogue; distant black holes (e.g. Sgr A* at 8 kpc) would shrink it to a dot
  allBounds = new THREE.Box3().setFromBufferAttribute(new THREE.BufferAttribute(pos.subarray(0, 3 * firstSpecial), 3))
    .getBoundingSphere(new THREE.Sphere());
}

// Rotate every position (and the camera) between the galactic and equatorial frames
function setFrame(newFrame) {
  if (newFrame === frame || !N) return;
  const m = newFrame === 'galactic' ? EQ_TO_GAL : GAL_TO_EQ;
  frame = newFrame;
  const v = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    v.fromArray(pos, 3 * i).applyMatrix3(m).toArray(pos, 3 * i);
  }
  positionAttr.needsUpdate = true;
  applyNebulaFrame();
  computeBounds();

  if (animation) { stepAnimation(animation.start + FOCUS_DURATION_MS); }
  // Keep the same stars in view: rotate the pivot and camera with the data (Sol stays at the origin)
  controls.target.applyMatrix3(m);
  camera.position.applyMatrix3(m);
  controls.update();

  if (selected >= 0) starPos(selected, selectionRing.position);
  selectedDrop.set(selected);
  centreDrop.set(centre);
  filterAnchor = -2; // force the distance filter to re-read its centre
  updateFilter();
  gridSpacing = 0;   // rebuild grid + caption
  updateAxisLabels();
  if (selected >= 0) selectStar(selected);
  updateCentreInfo();
  labelsDirty = true;
}

// ---------- Camera readout ----------
const cameraInfo = document.getElementById('camera-info');
const _camGal = new THREE.Vector3();
const _objPos = new THREE.Vector3();
let cameraInfoText = '';

// Distances span AU to kpc, so pick a readable unit
function formatDistance(pc) {
  if (pc < 0.01) return `${(pc * 206264.806).toFixed(pc < 1e-4 ? 2 : 0)} AU`;
  if (pc < 10) return `${pc.toFixed(3)} pc (${(pc * 3.26156).toFixed(2)} ly)`;
  if (pc < 10000) return `${pc.toFixed(1)} pc (${(pc * 3.26156).toFixed(0)} ly)`;
  if (pc < 1e6) {
    const ly = pc * 3.26156;
    return `${(pc / 1000).toFixed(2)} kpc (${ly < 1e6 ? `${(ly / 1e3).toFixed(0)} kly` : `${(ly / 1e6).toFixed(2)} Mly`})`;
  }
  return `${(pc / 1e6).toFixed(pc < 1e8 ? 3 : 1)} Mpc (${(pc * 3.26156e-6).toFixed(pc < 1e8 ? 2 : 0)} Mly)`;
}

function updateCameraInfo() {
  if (!N) return;
  _camGal.copy(camera.position);
  if (frame !== 'galactic') _camGal.applyMatrix3(EQ_TO_GAL);
  const r = _camGal.length();
  const maxAbs = Math.max(Math.abs(_camGal.x), Math.abs(_camGal.y), Math.abs(_camGal.z));
  const digits = maxAbs < 10 ? 3 : maxAbs < 1000 ? 2 : 1;
  const c = (v) => v.toFixed(digits);
  let text = `Camera (gal): X ${c(_camGal.x)}, Y ${c(_camGal.y)}, Z ${c(_camGal.z)} pc`;
  if (r > 0) {
    const l = (THREE.MathUtils.radToDeg(Math.atan2(_camGal.y, _camGal.x)) + 360) % 360;
    const b = THREE.MathUtils.radToDeg(Math.asin(_camGal.z / r));
    text += ` · l ${l.toFixed(2)}°, b ${b.toFixed(2)}°`;
  }
  const obj = selected >= 0 ? selected : centre;
  const d = obj >= 0
    ? camera.position.distanceTo(starPos(obj, _objPos))
    : camera.position.distanceTo(controls.target);
  const what = obj >= 0 ? records[obj].name : 'view centre';
  text += `\nDistance to ${what}: ${formatDistance(d)}`;
  if (text !== cameraInfoText) {
    cameraInfoText = text;
    cameraInfo.textContent = text;
  }
}

function loop(now) {
  requestAnimationFrame(loop);
  stepAnimation(now);
  controls.update();
  updateGrid();
  updateLabels();
  updateCameraInfo();
  renderer.render(scene, camera);
}

init().catch((err) => {
  console.error(err);
  document.getElementById('centre-info').textContent = `Error: ${err.message}`;
});
requestAnimationFrame(loop);
