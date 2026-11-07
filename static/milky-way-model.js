// Reid et al. (2019), Table 2 and Section III: https://arxiv.org/html/1910.03357v1#A2.T2
// Radii/widths are kpc; angles are degrees. Beta is zero towards Sol, increasing with Galactic rotation.
export const ARM_REFERENCE_RADIUS_KPC = 8.15;
export const SPIRAL_ARMS = [
  { name: 'Norma', kink: 18, radius: 4.46, pitchBefore: -1.0, pitchAfter: 19.5, minBeta: 5, maxBeta: 54, width: 0.14 },
  { name: 'Scutum-Centaurus', kink: 23, radius: 4.91, pitchBefore: 14.1, pitchAfter: 12.1, minBeta: 0, maxBeta: 104, width: 0.23 },
  { name: 'Sagittarius-Carina', kink: 24, radius: 6.04, pitchBefore: 17.1, pitchAfter: 1.0, minBeta: 2, maxBeta: 97, width: 0.27 },
  { name: 'Local (Orion)', kink: 9, radius: 8.26, pitchBefore: 11.4, pitchAfter: 11.4, minBeta: -8, maxBeta: 34, width: 0.31 },
  { name: 'Perseus', kink: 40, radius: 8.87, pitchBefore: 10.3, pitchAfter: 8.7, minBeta: -23, maxBeta: 115, width: 0.35 },
  { name: 'Outer', kink: 18, radius: 12.24, pitchBefore: 3.0, pitchAfter: 9.4, minBeta: -16, maxBeta: 71, width: 0.65 },
];

export function armRadiusKpc(arm, betaDegrees, solarRadiusKpc = ARM_REFERENCE_RADIUS_KPC) {
  const radians = Math.PI / 180;
  const pitch = betaDegrees <= arm.kink ? arm.pitchBefore : arm.pitchAfter;
  return arm.radius * solarRadiusKpc / ARM_REFERENCE_RADIUS_KPC
    * Math.exp(-(betaDegrees - arm.kink) * radians * Math.tan(pitch * radians));
}
