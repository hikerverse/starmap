export const AU_KM = 149597870.7;
export const SOLAR_RADIUS_KM = 695700;
export const EARTH_RADIUS_KM = 6371;

export function orbitPoint(a, e, angle) {
  return [a * (Math.cos(angle) - e), 0, a * Math.sqrt(1 - e * e) * Math.sin(angle)];
}

function phase(name) {
  let hash = 2166136261;
  for (const character of name) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return (hash >>> 0) / 4294967296 * Math.PI * 2;
}

function positive(value, label) {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${label} must be positive and finite`);
  return value;
}

export function systemBodies(system) {
  if (!system?.star || !Array.isArray(system.planets)) throw new Error('Invalid system data');
  const starRadius = positive(system.star.radius, 'Star radius') * SOLAR_RADIUS_KM / AU_KM;
  const bodies = [{
    name: system.name, kind: 'star', type: system.star.category_label,
    radius: starRadius, parent: -1, position: [0, 0, 0], orbit: 0, eccentricity: 0,
    data: system.star,
  }];
  for (const planet of system.planets) {
    const orbit = positive(planet.a_au, `${planet.name} orbit`);
    const e = planet.e ?? 0;
    if (!Number.isFinite(e) || e < 0 || e >= 1) throw new Error(`${planet.name}: invalid eccentricity`);
    const index = bodies.length;
    bodies.push({
      name: planet.name, kind: 'planet', type: planet.type,
      radius: positive(planet.radius_rearth, `${planet.name} radius`) * EARTH_RADIUS_KM / AU_KM,
      parent: 0, position: orbitPoint(orbit, e, phase(planet.name)), orbit, eccentricity: e,
      data: planet,
    });
    if (!Array.isArray(planet.moons)) throw new Error(`${planet.name}: missing moon list`);
    for (const moon of planet.moons) {
      const moonOrbit = positive(moon.a_km, `${moon.name} orbit`) / AU_KM;
      const offset = orbitPoint(moonOrbit, 0, phase(planet.name + moon.name));
      bodies.push({
        name: moon.name, kind: 'moon', type: planet.a_au > system.snow_line_au ? 'icy' : 'rocky',
        radius: positive(moon.radius_km, `${moon.name} radius`) / AU_KM,
        parent: index, position: offset.map((v, k) => v + bodies[index].position[k]),
        orbit: moonOrbit, eccentricity: 0, data: moon,
      });
    }
  }
  return bodies;
}

export function displayRadius(body, bodies, distance, fov, height, trueScale) {
  if (trueScale) return body.radius;
  let limit = body.orbit * (1 - body.eccentricity) * 0.12;
  const children = bodies.filter(b => b.parent === bodies.indexOf(body));
  if (body.kind === 'star') limit = children.length
    ? Math.min(...children.map(b => b.orbit * (1 - b.eccentricity))) * 0.15 : body.radius * 8;
  if (body.kind === 'planet' && children.length) {
    limit = Math.min(limit, Math.min(...children.map(b => b.orbit)) * 0.25);
  }
  const pixelRadius = distance * 2 * Math.tan(fov * Math.PI / 360) / height * 7;
  return Math.max(body.radius, Math.min(limit, pixelRadius));
}
