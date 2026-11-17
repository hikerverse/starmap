// Stellar identities cross-referenced against HYG v4.0 (CC BY-SA 4.0).
// These deliberately simple stick figures are illustrative, not IAU boundaries.
const pattern = (id, name, stars, edges) => ({
  id, name, stars: stars.map(([hip, name]) => ({ hip, name })), edges,
});
export const CONSTELLATIONS = [
  pattern('orion', 'Orion', [
    [27989, 'Betelgeuse'], [25336, 'Bellatrix'], [26727, 'Alnitak'], [26311, 'Alnilam'],
    [25930, 'Mintaka'], [27366, 'Saiph'], [24436, 'Rigel'], [26207, 'Meissa'],
  ], [[0, 7], [7, 1], [1, 4], [4, 3], [3, 2], [2, 0], [2, 5], [5, 6], [6, 4]]),
  pattern('ursa-major', 'Ursa Major - Big Dipper', [
    [54061, 'Dubhe'], [53910, 'Merak'], [58001, 'Phecda'], [59774, 'Megrez'],
    [62956, 'Alioth'], [65378, 'Mizar'], [67301, 'Alkaid'],
  ], [[0, 1], [1, 2], [2, 3], [3, 0], [3, 4], [4, 5], [5, 6]]),
  pattern('cassiopeia', 'Cassiopeia - W', [
    [746, 'Caph'], [3179, 'Schedar'], [4427, 'Cih'], [6686, 'Ruchbah'], [8886, 'Segin'],
  ], [[0, 1], [1, 2], [2, 3], [3, 4]]),
  pattern('cygnus', 'Cygnus - Northern Cross', [
    [102098, 'Deneb'], [100453, 'Sadr'], [95947, 'Albireo'], [97165, 'Fawaris'], [102488, 'Aljanah'],
  ], [[0, 1], [1, 2], [3, 1], [1, 4]]),
  pattern('crux', 'Crux - Southern Cross', [
    [60718, 'Acrux'], [62434, 'Mimosa'], [61084, 'Gacrux'], [59747, 'Imai'],
  ], [[0, 2], [1, 3]]),
  pattern('scorpius', 'Scorpius', [
    [80763, 'Antares'], [78401, 'Dschubba'], [78265, 'Fang'], [78820, 'Acrab'],
    [80112, 'Alniyat'], [81266, 'Paikauhale'], [82396, 'Larawag'], [82514, 'Xamidimura'],
    [82729, 'Zeta2 Sco'], [84143, 'Eta Sco'], [86228, 'Sargas'], [87073, 'Iota1 Sco'],
    [86670, 'Kappa Sco'], [85927, 'Shaula'], [85696, 'Lesath'],
  ], [[2, 1], [3, 1], [1, 4], [4, 0], [0, 5], [5, 6], [6, 7], [7, 8],
    [8, 9], [9, 10], [10, 11], [11, 12], [12, 13], [13, 14]]),
  pattern('leo', 'Leo', [
    [49669, 'Regulus'], [50583, 'Algieba'], [54872, 'Zosma'], [57632, 'Denebola'],
    [54879, 'Chertan'], [50335, 'Adhafera'], [48455, 'Rasalas'], [47908, 'Ras Elased Australis'],
  ], [[0, 1], [1, 5], [5, 6], [6, 7], [1, 2], [2, 3], [3, 4], [4, 0]]),
  pattern('pegasus', 'Pegasus - Great Square', [
    [113963, 'Markab'], [113881, 'Scheat'], [677, 'Alpheratz'], [1067, 'Algenib'],
  ], [[0, 1], [1, 2], [2, 3], [3, 0]]),
  pattern('taurus', 'Taurus - Hyades V', [
    [21421, 'Aldebaran'], [20889, 'Ain'], [20648, 'Delta3 Tau'],
    [20455, 'Secunda Hyadum'], [20205, 'Prima Hyadum'],
  ], [[0, 3], [3, 4], [4, 2], [2, 1]]),
  pattern('ursa-minor', 'Ursa Minor - Little Dipper', [
    [11767, 'Polaris'], [85822, 'Yildun'], [82080, 'Epsilon UMi'], [77055, 'Zeta UMi'],
    [79822, 'Eta UMi A'], [75097, 'Pherkad'], [72607, 'Kochab'],
  ], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 3]]),
  pattern('gemini', 'Gemini - Twins', [
    [36850, 'Castor'], [37826, 'Pollux'], [35550, 'Wasat'], [35350, 'Lambda Gem A'],
    [34088, 'Mekbuda'], [32246, 'Mebsuta'], [31681, 'Alhena'], [30343, 'Tejat'],
  ], [[0, 1], [0, 5], [5, 7], [1, 2], [2, 4], [4, 6], [2, 3]]),
  pattern('lyra', 'Lyra', [
    [91262, 'Vega'], [91971, 'Zeta1 Lyr'], [92420, 'Sheliak'], [93194, 'Sulafat'], [92791, 'Delta2 Lyr'],
  ], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 1]]),
];

const dot = (a, b) => a.reduce((sum, v, k) => sum + v * b[k], 0);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const unit = a => {
  const length = Math.hypot(...a);
  return length > 1e-8 ? a.map(v => v / length) : null;
};
export const angle = (a, b) => Math.acos(Math.max(-1, Math.min(1, dot(a, b))));

export function resolvePattern(figure, recordsByName) {
  return figure.stars.map(star => recordsByName.get(star.name) ?? -1);
}

export function skyDirections(positions, observer) {
  return positions.map(p => p ? unit(p.map((v, k) => v - observer[k])) : null);
}

export function skyFrame(directions) {
  const present = directions.filter(Boolean);
  if (!present.length) return null;
  const centre = unit([0, 1, 2].map(k => present.reduce((sum, p) => sum + p[k], 0))) || present[0];
  const east = unit(cross([0, 0, 1], centre)) || [0, 1, 0];
  return { centre, east, north: cross(centre, east) };
}

export function projectSky(direction, frame) {
  if (!direction || !frame) return null;
  const radius = angle(direction, frame.centre);
  if (radius > Math.PI - 1e-6) return null; // An antipode has no unique azimuth.
  const scale = radius < 1e-8 ? 1 : radius / Math.sin(radius);
  return [-dot(direction, frame.east) * scale, -dot(direction, frame.north) * scale];
}

export function skyArc(a, b) {
  if (!a || !b) return [];
  const theta = angle(a, b);
  if (theta > Math.PI - 1e-6) return []; // No unique shortest great circle.
  const steps = Math.max(1, Math.ceil(theta / (Math.PI / 90)));
  return Array.from({ length: steps + 1 }, (_, step) => {
    const t = step / steps;
    return theta < 1e-8 ? a : unit(a.map((v, k) =>
      (v * Math.sin((1 - t) * theta) + b[k] * Math.sin(t * theta)) / Math.sin(theta)));
  });
}

export function compareSkies(positions, observer, earthObserver = [0, 0, 0]) {
  const earth = skyDirections(positions, earthObserver), other = skyDirections(positions, observer);
  const frames = [skyFrame(earth), skyFrame(other)];
  const projected = [earth, other].map((sky, k) => sky.map(p => projectSky(p, frames[k])));
  let spanEarth = 0, spanOther = 0, change2 = 0, pairs = 0;
  for (let i = 0; i < positions.length; i++) for (let j = 0; j < i; j++) {
    if (!earth[i] || !earth[j] || !other[i] || !other[j]) continue;
    const a = angle(earth[i], earth[j]), b = angle(other[i], other[j]);
    spanEarth = Math.max(spanEarth, a);
    spanOther = Math.max(spanOther, b);
    change2 += (a - b) ** 2;
    pairs++;
  }
  const radius = Math.max(0.01, ...projected.flat().filter(Boolean).map(p => Math.hypot(...p))) * 1.15;
  return { earth, other, frames, projected, radius, spanEarth, spanOther,
    rms: pairs ? Math.sqrt(change2 / pairs) : null, pairs };
}
