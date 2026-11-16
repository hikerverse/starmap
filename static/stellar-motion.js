export const MOTION_LIMIT_YEARS = 10000;
export const KM_S_TO_PC_YR = 31557600 / 3.085677581491367e13;

export function validateMotion(data, count, datasetId, namesCrc) {
  if (!data || data.dataset_id !== datasetId || data.count !== count || data.names_crc !== namesCrc
    || data.reference_epoch !== 2000 || !Array.isArray(data.measurements) || data.measurements.length !== count
    || !Array.isArray(data.sources) || !data.sources.every(s => typeof s === 'string')) {
    throw new Error('Stellar motion does not match the loaded catalogue. Reload or regenerate the motion data.');
  }
  for (const m of data.measurements) {
    if (m === null) continue;
    if (!Array.isArray(m) || m.length !== 9 || !m.slice(0, 3).every(Number.isFinite)
      || ![0, 1].includes(m[3]) || (m[4] !== null && (!Number.isFinite(m[4]) || m[4] < 0))
      || (m[5] !== null && !Number.isFinite(m[5]))
      || (m[6] !== null && (!Number.isFinite(m[6]) || m[6] < 0))
      || (m[3] === 1 && m[5] === null)
      || !Number.isInteger(m[7]) || !data.sources[m[7]] || typeof m[8] !== 'string') {
      throw new Error('Invalid stellar velocity measurement.');
    }
  }
  return data;
}

export function applyMotionPositions(records, base, measurements, years, enabled, partial = false) {
  if (!Number.isFinite(years) || Math.abs(years) > MOTION_LIMIT_YEARS) {
    throw new Error('Choose an offset within 10,000 years of J2000.');
  }
  for (let i = 0; i < measurements.length; i++) {
    const m = measurements[i], r = records[i], j = 3 * i;
    const elapsed = enabled && m && (m[3] || partial) ? years : 0;
    r.x = base[j] + (m ? m[0] * elapsed : 0);
    r.y = base[j + 1] + (m ? m[1] * elapsed : 0);
    r.z = base[j + 2] + (m ? m[2] * elapsed : 0);
  }
}

export function motionDescription(m, years, partial, source) {
  if (!m) return 'Motion unavailable: no usable proper motion. Held at its catalogue position, not known to be stationary.';
  if (source === 'Heliocentric reference') return 'Sol: fixed origin of this heliocentric model.';
  if (!m[3]) return `Radial velocity unknown. ${partial ? 'Tangential-only estimate; radial velocity assumed zero.' : 'Held at catalogue position; enable partial estimates to move sideways.'} ${source}, ID ${m[8]}.`;
  const speed = Math.hypot(...m.slice(0, 3)) / KM_S_TO_PC_YR;
  const error = m[4] === null ? 'Velocity uncertainty unavailable.'
    : `Approximate velocity-error displacement after ${Math.abs(years).toLocaleString()} yr: ${(m[4] * Math.abs(years)).toPrecision(3)} pc (not a confidence bound).`;
  return `Measured 3D velocity: ${speed.toFixed(2)} km/s; radial ${m[5].toFixed(2)}${m[6] === null ? '' : ` +/- ${m[6].toFixed(2)}`} km/s. ${source}, ID ${m[8]}. ${error}`;
}
