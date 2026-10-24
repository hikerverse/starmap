"""Planetary systems for StarExplorer.

Confirmed planets (NASA Exoplanet Archive, data/known_planets.json) and the Solar
System (data/solar_system.json) are used where available. Every other star gets a
simulated system drawn from measured exoplanet occurrence rates. Generation is
deterministic: the same (seed, star name) always produces the same system, so the
full systems never need to be stored - only a small per-star summary is cached.

Main references
  Stellar parameters   Pecaut & Mamajek (2013, 2022 update) dwarf sequence
  Small planets        SAG13 (Kopparapu et al. 2018), Dressing & Charbonneau (2015),
                       Fulton et al. (2017) radius valley, Weiss et al. (2018) "peas in a pod"
  Giant planets        Johnson et al. (2010) mass/metallicity scaling, Fulton et al. (2021)
                       semi-major-axis distribution, Cumming et al. (2008) mass function
  Cold Neptunes        Suzuki et al. (2016) microlensing
  Eccentricities       Kipping (2013), Van Eylen et al. (2019)
  Mass-radius          Chen & Kipping (2017)
  Habitable zone       Kopparapu et al. (2013, 2014)
  Tidal locking        Gladman et al. (1996)
  Moons                Canup & Ward (2006), Domingos et al. (2006), Barnes & O'Brien (2002)
"""

import math
import random
import re

GENERATOR_VERSION = 2
DEFAULT_SEED = 1

T_SUN = 5772.0
M_BOL_SUN = 4.74
AU_PER_RSUN = 0.00465047
AU_PER_REARTH = 4.26352e-5
MEARTH_PER_MSUN = 332946.0
GM_EARTH_KM3_S2 = 398600.4418
AU_KM = 1.495978707e8

MIN_HABITABLE_MASS = 0.25     # M_earth, enough to keep an atmosphere (Heller & Barnes 2013)
MAX_HABITABLE_RADIUS = 1.6    # R_earth, above this planets are mostly volatile-rich (Rogers 2015)
GIANT_MASS = 50.0             # M_earth, gas giant threshold

FLAG_GIANT = 1          # has a gas giant
FLAG_HZ = 2             # a planet (any type) orbits in the optimistic habitable zone
FLAG_HABITABLE = 4      # potentially habitable rocky planet
FLAG_CONSERVATIVE = 8   # ... inside the conservative habitable zone
FLAG_HAB_MOON = 16      # potentially habitable moon
FLAG_CONFIRMED = 32     # planets come from the NASA Exoplanet Archive / Solar System

# ---------------------------------------------------------------------------
# Stellar model
# ---------------------------------------------------------------------------
_LETTERS = "OBAFGKM"

# Main-sequence (code, Teff [K], M_V, BC_V), code = 10 * letter index + subtype
_DWARF = [
    ("O3", 44900, -5.7, -4.30), ("O5", 41400, -5.2, -4.00), ("O7", 36500, -4.6, -3.60),
    ("O9", 32500, -4.2, -3.20), ("B0", 31400, -3.9, -3.00), ("B1", 26000, -2.7, -2.50),
    ("B2", 20600, -2.0, -2.00), ("B3", 17000, -1.3, -1.60), ("B5", 15700, -0.9, -1.20),
    ("B7", 14000, -0.4, -0.80), ("B8", 12300, -0.25, -0.60), ("B9", 10700, 0.2, -0.35),
    ("A0", 9700, 0.9, -0.25), ("A2", 8840, 1.3, -0.12), ("A5", 8080, 2.1, -0.05),
    ("A7", 7650, 2.3, -0.03), ("F0", 7220, 2.51, -0.01), ("F2", 6810, 2.99, -0.02),
    ("F5", 6510, 3.40, -0.03), ("F8", 6150, 4.0, -0.06), ("G0", 5920, 4.3, -0.07),
    ("G2", 5770, 4.7, -0.08), ("G5", 5660, 5.1, -0.10), ("G8", 5490, 5.5, -0.15),
    ("K0", 5280, 5.9, -0.20), ("K2", 5040, 6.3, -0.30), ("K3", 4830, 6.6, -0.38),
    ("K5", 4410, 7.3, -0.60), ("K7", 4070, 8.1, -0.90), ("M0", 3850, 8.8, -1.20),
    ("M1", 3660, 9.4, -1.35), ("M2", 3560, 10.0, -1.60), ("M3", 3430, 11.0, -1.90),
    ("M4", 3210, 12.6, -2.40), ("M5", 3060, 14.0, -2.80), ("M6", 2810, 16.3, -3.40),
    ("M7", 2680, 17.5, -3.80), ("M8", 2570, 18.5, -4.30), ("M9", 2380, 19.5, -4.60),
]
_DWARF_CODE = [10 * _LETTERS.index(c[0]) + int(c[1:]) for c, *_ in _DWARF]
_DWARF_TEFF = [t for _, t, _, _ in _DWARF]
_DWARF_MV = [m for _, _, m, _ in _DWARF]
_DWARF_BC = [b for _, _, _, b in _DWARF]
# Giants are cooler than dwarfs of the same G-M type: (code, Teff) for luminosity class III
_GIANT_TEFF = [(40, 5600), (45, 5100), (48, 4900), (50, 4750), (52, 4500), (53, 4300),
               (55, 3950), (57, 3900), (60, 3850), (62, 3700), (64, 3550), (65, 3450), (67, 3300)]

_SPEC = re.compile(r"^(?:sd|esd|d|g|c|k)?([OBAFGKM])(\d+(?:\.\d+)?)?")
_SPEC_LOWER = re.compile(r"^([obafgkm])(?![a-z])")
_LUM = re.compile(r"^[\s:]*(Iab|Ia|Ib|III|II|IV|I|VI|V)")
_PREFIX_LUM = {"sd": "VI", "esd": "VI", "d": "V", "g": "III", "c": "I"}
_WHITE_DWARF = re.compile(r"^D[ABOQZCXP]*(\d+(?:\.\d+)?)?")


def _interp(x, xs, ys):
    """Piecewise-linear interpolation with clamping (xs ascending)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + t * (ys[hi] - ys[lo])


_BC_TEFF = sorted(zip(_DWARF_TEFF, _DWARF_BC))


def bolometric_correction(teff: float) -> float:
    return _interp(teff, [t for t, _ in _BC_TEFF], [b for _, b in _BC_TEFF])


def parse_spectral(sp: str) -> dict:
    """Split a spectral type into kind, numeric code (O0 = 0 ... M9 = 69) and luminosity class."""
    sp = (sp or "").strip()
    m = _SPEC.match(sp)
    if m:
        code = 10 * _LETTERS.index(m.group(1)) + (float(m.group(2)) if m.group(2) else 5.0)
        prefix = sp[:m.start(1)]
        lum = _PREFIX_LUM.get(prefix)
        lm = _LUM.match(sp[m.end():])
        if lm:
            lum = {"Iab": "I", "Ia": "I", "Ib": "I"}.get(lm.group(1), lm.group(1))
        return {"kind": "normal", "code": min(code, 69.0), "lum": lum}
    m = _SPEC_LOWER.match(sp)
    if m:
        return {"kind": "normal", "code": 10 * _LETTERS.index(m.group(1).upper()) + 5.0, "lum": None}
    m = _WHITE_DWARF.match(sp)
    if m:
        index = float(m.group(1)) if m.group(1) else 5.0
        return {"kind": "white_dwarf", "teff": 50400.0 / max(index, 0.5)}
    if sp[:1] in ("C", "N") or sp[:2] in ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"):
        return {"kind": "carbon", "teff": 4500.0 if sp[:1] == "R" else 3000.0}
    if sp[:1] == "S" and not sp[:2] == "sd":
        return {"kind": "carbon", "teff": 3300.0}
    if sp[:1] == "W":
        return {"kind": "wolf_rayet", "teff": 50000.0}
    return {"kind": "unknown"}


def _ms_mass_from_lum(lum: float) -> float:
    """Invert the main-sequence mass-luminosity relation."""
    if lum < 0.23 * 0.43 ** 2.3:
        return (lum / 0.23) ** (1 / 2.3)
    if lum < 16.0:
        return lum ** 0.25
    if lum < 1.4 * 55 ** 3.5:
        return (lum / 1.4) ** (1 / 3.5)
    return lum / 32000.0


def _ms_lum(code: float) -> float:
    mv = _interp(code, _DWARF_CODE, _DWARF_MV)
    bc = _interp(code, _DWARF_CODE, _DWARF_BC)
    return 10 ** (-0.4 * (mv + bc - M_BOL_SUN))


def teff_group(teff: float) -> str:
    for limit, group in ((30000, "O"), (10000, "B"), (7300, "A"), (6000, "F"), (5300, "G"), (3900, "K")):
        if teff >= limit:
            return group
    return "M"


CATEGORY_LABELS = {
    "main_sequence": "Main-sequence dwarf", "subdwarf": "Subdwarf", "subgiant": "Subgiant",
    "giant": "Giant", "bright_giant": "Bright giant", "supergiant": "Supergiant",
    "white_dwarf": "White dwarf", "carbon": "Carbon / S-type giant", "wolf_rayet": "Wolf-Rayet star",
}


def star_properties(spectral_class: str, abs_mag: float | None) -> dict:
    """Effective temperature, luminosity, mass and radius from spectral type and M_V."""
    sp = parse_spectral(spectral_class)
    kind = sp["kind"]
    if abs_mag is None:
        abs_mag = 5.0
    if kind == "unknown":
        # No usable type: assume a main-sequence star of this absolute magnitude
        code = _interp(abs_mag, _DWARF_MV, _DWARF_CODE)
        sp = {"kind": "normal", "code": code, "lum": "V"}
        kind = "normal"

    if kind == "normal":
        code, lum_class = sp["code"], sp["lum"]
        if lum_class is None:
            excess = _interp(code, _DWARF_CODE, _DWARF_MV) - abs_mag   # > 0: brighter than the main sequence
            lum_class = "III" if excess > 2.5 else "IV" if excess > 1.0 else "V"
        teff = _interp(code, _DWARF_CODE, _DWARF_TEFF)
        if code >= 40 and lum_class in ("I", "II", "III", "IV"):
            giant = _interp(code, [c for c, _ in _GIANT_TEFF], [t for _, t in _GIANT_TEFF])
            teff = giant if lum_class != "IV" else teff - 0.4 * (teff - giant)
        category = {"I": "supergiant", "II": "bright_giant", "III": "giant", "IV": "subgiant",
                    "V": "main_sequence", "VI": "subdwarf"}[lum_class]
        ms_mass = _ms_mass_from_lum(_ms_lum(code))
        mass = {"supergiant": max(12.0, ms_mass), "bright_giant": max(4.0, ms_mass),
                "giant": max(1.5, ms_mass) if code >= 30 else ms_mass}.get(category, ms_mass)
    elif kind == "white_dwarf":
        teff, mass, category = sp["teff"], 0.6, "white_dwarf"
    elif kind == "carbon":
        teff, mass, category = sp["teff"], 1.5, "carbon"
    else:
        teff, mass, category = sp["teff"], 15.0, "wolf_rayet"

    lum = 10 ** (-0.4 * (abs_mag + bolometric_correction(teff) - M_BOL_SUN))
    radius = math.sqrt(lum) * (T_SUN / teff) ** 2
    return {"teff": round(teff), "lum": lum, "mass": mass, "radius": radius, "category": category,
            "group": teff_group(teff)}


# ---------------------------------------------------------------------------
# Habitable zone (Kopparapu et al. 2014, 1 Earth-mass coefficients)
# ---------------------------------------------------------------------------
_HZ_COEFFS = {
    "recent_venus": (1.776, 2.136e-4, 2.533e-8, -1.332e-11, -3.097e-15),
    "runaway_greenhouse": (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15),
    "maximum_greenhouse": (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16),
    "early_mars": (0.320, 5.547e-5, 1.526e-9, -2.874e-12, -5.011e-16),
}


def habitable_zone(teff: float, lum: float) -> dict:
    """Habitable-zone limits as stellar flux (S_earth) and distance (AU)."""
    t = min(max(teff, 2600.0), 7200.0) - 5780.0
    flux = {k: s + a * t + b * t ** 2 + c * t ** 3 + d * t ** 4 for k, (s, a, b, c, d) in _HZ_COEFFS.items()}
    return {
        "flux": flux,
        "conservative_au": [math.sqrt(lum / flux["runaway_greenhouse"]), math.sqrt(lum / flux["maximum_greenhouse"])],
        "optimistic_au": [math.sqrt(lum / flux["recent_venus"]), math.sqrt(lum / flux["early_mars"])],
        "extrapolated": not 2600.0 <= teff <= 7200.0,
    }


def hz_status(insolation: float, hz: dict) -> str | None:
    f = hz["flux"]
    if f["maximum_greenhouse"] <= insolation <= f["runaway_greenhouse"]:
        return "conservative"
    if f["early_mars"] <= insolation <= f["recent_venus"]:
        return "optimistic"
    return None

# ---------------------------------------------------------------------------
# Planet physics
# ---------------------------------------------------------------------------
TYPE_LABELS = {
    "terrestrial": "Terrestrial (rocky)", "super_earth": "Super-Earth", "sub_neptune": "Sub-Neptune",
    "neptune": "Ice giant (Neptune-like)", "gas_giant": "Gas giant",
}


def radius_from_mass(mass: float) -> float:
    """Chen & Kipping (2017) mean mass-radius relation (R_earth from M_earth)."""
    if mass < 2.04:
        return mass ** 0.279
    if mass < 132.0:
        return 0.80811 * mass ** 0.589
    return 17.739 * mass ** -0.044


def mass_from_radius(radius: float) -> float:
    if radius < 2.04 ** 0.279:
        return radius ** (1 / 0.279)
    if radius < 0.80811 * 132.0 ** 0.589:
        return (radius / 0.80811) ** (1 / 0.589)
    return 318.0  # the Jovian branch is flat: radius does not constrain the mass


def planet_type(radius: float, mass: float) -> str:
    if mass >= GIANT_MASS or radius >= 8.0:
        return "gas_giant"
    if radius >= 3.5:
        return "neptune"
    if radius >= 2.0:
        return "sub_neptune"
    if radius >= 1.25:
        return "super_earth"
    return "terrestrial"


def is_rocky(radius: float, mass: float) -> bool:
    return radius <= MAX_HABITABLE_RADIUS and mass < 10.0


def orbital_period_days(a_au: float, star_mass: float, planet_mass: float = 0.0) -> float:
    return 365.25 * math.sqrt(a_au ** 3 / (star_mass + planet_mass / MEARTH_PER_MSUN))


def semi_major_axis_au(period_d: float, star_mass: float) -> float:
    return (star_mass * (period_d / 365.25) ** 2) ** (1 / 3)


def equilibrium_temperature(insolation: float, albedo: float = 0.3) -> float:
    """Planet equilibrium temperature (K), full heat redistribution."""
    return 278.6 * ((1 - albedo) * insolation) ** 0.25


def tidal_lock_time_yr(a_au: float, star_mass: float, mass: float, radius: float) -> float:
    """Gladman et al. (1996) despinning time for a rocky body (initial 12 h day, Q = 100, k2 = 0.3)."""
    omega = 2 * math.pi / (12 * 3600)
    a = a_au * 1.495978707e11
    m = mass * 5.9722e24
    r = radius * 6.371e6
    ms = star_mass * 1.98847e30
    t = omega * a ** 6 * 0.33 * m * 100 / (3 * 6.674e-11 * ms ** 2 * 0.3 * r ** 3)
    return t / 3.15576e7


def snow_line_au(star_mass: float) -> float:
    return 2.7 * star_mass ** 2


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, rng.random()
    while p > limit:
        k += 1
        p *= rng.random()
    return k


class _LogSampler:
    """Draw x from a density defined per unit ln(x) on [lo, hi] (tabulated inverse CDF)."""

    def __init__(self, lo: float, hi: float, density, bins: int = 400):
        self.edges = [math.log(lo) + (math.log(hi) - math.log(lo)) * i / bins for i in range(bins + 1)]
        weights = [density(math.exp(0.5 * (self.edges[i] + self.edges[i + 1]))) for i in range(bins)]
        total = sum(weights)
        self.cdf, acc = [], 0.0
        for w in weights:
            acc += w / total
            self.cdf.append(acc)

    def sample(self, rng: random.Random) -> float:
        u = rng.random()
        lo, hi = 0, len(self.cdf) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.cdf[mid] < u:
                lo = mid + 1
            else:
                hi = mid
        return math.exp(self.edges[lo] + rng.random() * (self.edges[lo + 1] - self.edges[lo]))


# Small planets (0.5-6 R_earth): SAG13 period slope beta = 0.26, steep fall-off inside ~10 days
_SMALL_PERIOD = _LogSampler(0.5, 1500.0, lambda p: p ** 0.26 if p >= 10 else 10 ** 0.26 * (p / 10) ** 1.9)
# Radius distribution of a system's "typical" planet: SAG13 for FGK, rockier for M dwarfs
_SMALL_RADIUS_FGK = _LogSampler(0.5, 6.0, lambda r: 0.38 * r ** -0.19 if r < 3.4 else 0.73 * r ** -1.18)
_SMALL_RADIUS_M = _LogSampler(0.5, 6.0, lambda r: 1.0 if r < 1.5 else 0.8 if r < 2.5 else 0.35 if r < 4 else 0.05)
# Giant planets: dN/dlnM ~ M^-0.31, 50 M_earth - 13 M_Jup
_GIANT_MASS = _LogSampler(GIANT_MASS, 4100.0, lambda m: m ** -0.31)


def _giant_a_density(a: float) -> float:
    if a < 0.1:
        return 0.09        # hot Jupiters: ~6 % of giants
    if a < 2.0:
        return (a / 2.0) ** 0.7
    if a < 8.0:
        return 1.0
    return (a / 8.0) ** -1.0


_GIANT_A = _LogSampler(0.02, 30.0, _giant_a_density)

# Per spectral group: (probability of an inner small-planet system, extra planets per system)
_SMALL_SYSTEMS = {"O": (0.0, 0.0), "B": (0.02, 0.3), "A": (0.20, 0.8), "F": (0.45, 1.3),
                  "G": (0.55, 1.6), "K": (0.65, 1.8), "M": (0.80, 2.0)}
_COLD_NEPTUNE_PROB = {"O": 0.0, "B": 0.0, "A": 0.20, "F": 0.35, "G": 0.35, "K": 0.35, "M": 0.35}


# ---------------------------------------------------------------------------
# System generation
# ---------------------------------------------------------------------------
def _rng(seed, *parts) -> random.Random:
    # String seeds are hashed with SHA-512, so results do not depend on PYTHONHASHSEED
    return random.Random("|".join([str(seed), *parts]))


def _sig(x: float, digits: int = 4) -> float:
    return float(f"{x:.{digits}g}")


def _rayleigh(rng: random.Random, sigma: float) -> float:
    return sigma * math.sqrt(-2.0 * math.log(1.0 - rng.random()))


def _simulate_planets(rng: random.Random, props: dict) -> tuple[list, float | None]:
    """Draw planets for a star without confirmed planets. Returns (planets, simulated [Fe/H])."""
    cat, group, mstar, lum = props["category"], props["group"], props["mass"], props["lum"]
    if cat in ("supergiant", "bright_giant", "wolf_rayet") or group == "O":
        return [], None
    feh = rng.gauss(-0.05, 0.2)
    inner_edge = max(0.01, 3.0 * props["radius"] * AU_PER_RSUN)
    if cat == "white_dwarf":
        p_small, extra, p_giant, p_nep, inner_edge = 0.005, 0.0, 0.02, 0.02, 0.5
        group = "K"
    elif cat in ("giant", "carbon"):
        # Planets inside ~0.5 AU are engulfed or tidally destroyed as the star expands
        (p_small, extra), p_giant, p_nep = _SMALL_SYSTEMS["F"], 0.10, 0.2
        p_small *= 0.6
        inner_edge = max(inner_edge, 0.5)
        group = "F"
    else:
        p_small, extra = _SMALL_SYSTEMS[group]
        p_giant = 0.02 if group == "B" else min(0.35, 0.14 * mstar * 10 ** (1.2 * feh))
        p_nep = _COLD_NEPTUNE_PROB[group]

    planets = []
    if rng.random() < p_small:
        n = 1 + _poisson(rng, extra)
        base = (_SMALL_RADIUS_M if group == "M" else _SMALL_RADIUS_FGK).sample(rng)
        for _ in range(n):
            period = _SMALL_PERIOD.sample(rng)
            a = semi_major_axis_au(period, mstar)
            radius = min(6.0, max(0.4, base * math.exp(rng.gauss(0.0, 0.25))))   # "peas in a pod"
            if 1.8 < radius < 4.0 and lum / a ** 2 > 100 and rng.random() < 0.8:
                radius = min(1.7, max(1.0, 0.55 * radius))   # atmosphere photo-evaporated: bare core
            mass = mass_from_radius(radius) * math.exp(rng.gauss(0.0, 0.15))
            e = _rayleigh(rng, 0.049) if n > 1 else abs(rng.gauss(0.0, 0.32))
            planets.append({"a_au": a, "e": min(e, 0.8), "mass_mearth": mass, "radius_rearth": radius})
    if rng.random() < p_giant:
        for _ in range(1 + _poisson(rng, 0.35)):
            mass = _GIANT_MASS.sample(rng)
            planets.append({"a_au": _GIANT_A.sample(rng), "e": min(0.9, rng.betavariate(0.867, 3.03)),
                            "mass_mearth": mass, "radius_rearth": radius_from_mass(mass)})
    if rng.random() < p_nep:
        for _ in range(1 + _poisson(rng, 0.3)):
            mass = math.exp(rng.uniform(math.log(8.0), math.log(50.0)))
            planets.append({"a_au": snow_line_au(mstar) * math.exp(rng.uniform(0.0, math.log(10.0))),
                            "e": min(0.9, rng.betavariate(0.867, 3.03)),
                            "mass_mearth": mass, "radius_rearth": radius_from_mass(mass)})

    for p in planets:
        if orbital_period_days(p["a_au"], mstar) < 5.0:
            p["e"] = 0.0     # tidally circularised
    planets = [p for p in planets if p["a_au"] * (1 - p["e"]) > inner_edge]
    hot = [p["a_au"] for p in planets if p["mass_mearth"] >= GIANT_MASS and p["a_au"] < 0.1]
    if hot:   # hot Jupiters have no close companions
        planets = [p for p in planets if p["mass_mearth"] >= GIANT_MASS or p["a_au"] > 3 * hot[0]]
    return _stabilise(planets, mstar), feh


def _stabilise(planets: list, mstar: float) -> list:
    """Drop the lighter planet of any pair closer than 8 mutual Hill radii or with crossing orbits."""
    planets = sorted(planets, key=lambda p: p["a_au"])
    i = 1
    while i < len(planets):
        p, q = planets[i - 1], planets[i]
        mu = (p["mass_mearth"] + q["mass_mearth"]) / (3.0 * mstar * MEARTH_PER_MSUN)
        hill = mu ** (1 / 3) * 0.5 * (p["a_au"] + q["a_au"])
        if q["a_au"] - p["a_au"] < 8.0 * hill or p["a_au"] * (1 + p["e"]) >= q["a_au"] * (1 - q["e"]):
            del planets[i - 1 if p["mass_mearth"] < q["mass_mearth"] else i]
            i = max(1, i - 1)
        else:
            i += 1
    return planets


def _describe(ptype: str, climate: str, teq: float, period: float, habitable: bool, radius: float) -> str:
    if ptype == "gas_giant":
        if period < 10:
            return "Hot Jupiter"
        return {"hot": "Warm gas giant", "temperate": "Temperate gas giant"}.get(climate, "Cold gas giant")
    if ptype == "neptune":
        return {"hot": "Hot Neptune", "temperate": "Temperate ice giant"}.get(climate, "Cold ice giant")
    if ptype == "sub_neptune":
        return {"hot": "Hot sub-Neptune", "temperate": "Temperate sub-Neptune (possible water world)"}.get(
            climate, "Cold sub-Neptune")
    if teq >= 1000:
        return "Lava world"
    if climate == "hot":
        return "Hot rocky world (Venus-like)"
    if climate == "temperate":
        if habitable:
            return "Temperate rocky world (Earth-like candidate)"
        return "Temperate super-Earth (likely volatile-rich)" if radius > MAX_HABITABLE_RADIUS else "Temperate rocky world (too small to hold an atmosphere)"
    return "Frozen rocky world" if teq < 150 else "Cold rocky world (Mars-like)"


_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _simulate_moons(seed, planet: dict, props: dict) -> tuple[list, int]:
    """Regular moons inside the stable part of the Hill sphere (sizes in planet radii)."""
    rng = _rng(seed, planet["name"], "moons")
    mass, radius, a, e = planet["mass_mearth"], planet["radius_rearth"], planet["a_au"], planet["e"]
    hill_au = a * (1 - e) * (mass / (3.0 * props["mass"] * MEARTH_PER_MSUN)) ** (1 / 3)
    max_orbit = 0.49 * hill_au / (radius * AU_PER_REARTH)
    if max_orbit < 10.0:
        return [], 0   # too close to the star: moons are stripped or spiral in (Barnes & O'Brien 2002)
    ptype = planet["type"]
    raw = []
    if ptype in ("gas_giant", "neptune"):
        gas = ptype == "gas_giant"
        n = _poisson(rng, 3.5 if gas else 3.0)
        if n:
            total = mass * 10 ** rng.uniform(-4.3, -3.7)     # Canup & Ward (2006): ~1e-4 of the planet
            weights = [rng.expovariate(1.0) ** 2.5 for _ in range(n)]
            orbit = rng.uniform(3.5, 7.0)
            for w in weights:
                if orbit > max_orbit:
                    break
                raw.append((total * w / sum(weights), orbit))
                orbit *= rng.uniform(1.4, 2.4)
        minor = _poisson(rng, (20.0 if gas else 8.0) * min(1.0, hill_au / (0.35 if gas else 0.5)))
    elif ptype == "sub_neptune":
        if rng.random() < 0.10:
            raw.append((mass * 10 ** rng.uniform(-3.0, -2.0), rng.uniform(min(10.0, 0.5 * max_orbit), min(60.0, max_orbit))))
        minor = _poisson(rng, 0.5)
    else:
        if rng.random() < 0.12:   # giant-impact moon like ours (Moon: 0.0123 M_earth at 60 R_earth)
            raw.append((mass * 10 ** rng.uniform(-2.5, -1.5), rng.uniform(min(15.0, 0.5 * max_orbit), min(60.0, max_orbit))))
        minor = _poisson(rng, 0.4)

    icy = a > snow_line_au(props["mass"])
    moons = []
    for m, orbit in sorted(raw, key=lambda x: x[1]):
        if m < 1e-7:
            minor += 1
            continue
        a_km = orbit * radius * 6371.0
        moons.append({
            "mass_mearth": m,
            "radius_km": 6371.0 * (1.16 if icy else 1.0) * m ** 0.279,
            "a_km": a_km,
            "period_d": 2 * math.pi * math.sqrt(a_km ** 3 / (GM_EARTH_KM3_S2 * mass)) / 86400.0,
        })
    for k, moon in enumerate(moons):
        moon["name"] = f"{planet['name']} {_ROMAN[k] if k < len(_ROMAN) else k + 1}"
    return moons, minor


def _host_can_be_habitable(props: dict) -> bool:
    return props["category"] in ("main_sequence", "subdwarf") and 2600 <= props["teff"] <= 7200


def build_system(star: dict, known: dict | None, seed=DEFAULT_SEED, with_moons: bool = True) -> dict:
    """Full planetary system for one catalogue star (confirmed planets if `known`, otherwise simulated)."""
    name = star["name"]
    props = star_properties(star["spectral_class"], star.get("abs_mag"))
    star_source = "derived from spectral type and absolute magnitude"
    if known and known.get("star"):
        overrides = {k: v for k, v in known["star"].items() if k in ("teff", "lum", "mass", "radius") and v}
        if overrides:
            props.update(overrides)
            props["group"] = teff_group(props["teff"])
            star_source = known.get("star_source", "NASA Exoplanet Archive")
    hz = habitable_zone(props["teff"], props["lum"])
    habitable_host = _host_can_be_habitable(props)
    mstar = props["mass"]

    metallicity = None
    if known:
        raw = []
        for kp in known.get("planets", []):
            p = dict(kp)
            if not p.get("a_au") and p.get("period_d"):
                p["a_au"] = semi_major_axis_au(p["period_d"], mstar)
            if not p.get("a_au"):
                continue
            if not p.get("mass_mearth") and not p.get("radius_rearth"):
                continue
            p.setdefault("e", 0.0)
            p["e"] = p["e"] or 0.0
            if not p.get("mass_mearth"):
                p["mass_mearth"] = mass_from_radius(p["radius_rearth"])
                p["mass_estimated"] = True
            if not p.get("radius_rearth"):
                p["radius_rearth"] = radius_from_mass(p["mass_mearth"])
                p["radius_estimated"] = True
            p["source"] = "confirmed"
            raw.append(p)
        raw.sort(key=lambda p: p["a_au"])
    else:
        raw, metallicity = _simulate_planets(_rng(seed, name), props)
        for k, p in enumerate(raw):
            p["name"] = f"{name} {'bcdefghijklmnopqrstuvwxyz'[k]}"
            p["source"] = "simulated"

    flags = FLAG_CONFIRMED if known else 0
    planets = []
    flux = hz["flux"]
    for p in raw:
        a, e, mass, radius = p["a_au"], p["e"], p["mass_mearth"], p["radius_rearth"]
        period = p.get("period_d") or orbital_period_days(a, mstar, mass)
        insolation = props["lum"] / a ** 2 / math.sqrt(1 - min(e, 0.99) ** 2)
        teq = equilibrium_temperature(insolation)
        ptype = planet_type(radius, mass)
        zone = hz_status(insolation, hz)
        habitable = bool(zone and habitable_host and is_rocky(radius, mass) and mass >= MIN_HABITABLE_MASS)
        climate = "hot" if insolation > flux["recent_venus"] else "temperate" if zone else "cold"
        if mass < GIANT_MASS:
            locked = tidal_lock_time_yr(a, mstar, mass, radius) < 1e9
        else:
            locked = period < 10
        planet = dict(p, period_d=period, insolation=insolation, teq_k=teq, type=ptype, hz=zone,
                      habitable=habitable, tidally_locked=locked,
                      description=_describe(ptype, climate, teq, period, habitable, radius))

        # Moons can only be habitable around a planet in the habitable zone that is massive enough
        # to hold a >= MIN_HABITABLE_MASS moon, so the summary only needs to simulate those.
        need_moons = with_moons or (zone and habitable_host and mass >= 7.0)
        if "moons" in p:
            moons, minor = [dict(m) for m in p["moons"]], p.get("minor_moons", 0)
        elif need_moons:
            moons, minor = _simulate_moons(seed, planet, props)
            planet["moons_simulated"] = True
        else:
            moons, minor = [], 0
        for moon in moons:
            moon["habitable"] = bool(zone and habitable_host and moon["mass_mearth"] >= MIN_HABITABLE_MASS)
            if moon["habitable"]:
                flags |= FLAG_HAB_MOON
        planet["moons"] = moons
        planet["minor_moons"] = minor

        if ptype == "gas_giant":
            flags |= FLAG_GIANT
        if zone:
            flags |= FLAG_HZ
        if habitable:
            flags |= FLAG_HABITABLE
            if zone == "conservative":
                flags |= FLAG_CONSERVATIVE
        planets.append(planet)

    return {
        "name": name, "seed": seed, "confirmed": bool(known), "flags": flags,
        "star": dict(props, spectral_class=star["spectral_class"], abs_mag=star.get("abs_mag"),
                     category_label=CATEGORY_LABELS[props["category"]], source=star_source,
                     metallicity=metallicity, habitable_host=habitable_host),
        "habitable_zone": hz, "snow_line_au": snow_line_au(mstar),
        "hosts": (known or {}).get("hosts", []),
        "planets": planets,
    }


def round_floats(obj, digits: int = 4):
    """Round every float in a JSON-like structure to `digits` significant figures."""
    if isinstance(obj, float):
        return _sig(obj, digits) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: round_floats(v, digits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_floats(v, digits) for v in obj]
    return obj


def build_summary(stars: list, known_systems: dict, seed=DEFAULT_SEED) -> tuple[list, list]:
    """Planet count and FLAG_* bits for every star, in catalogue order."""
    counts, flags = [], []
    for star in stars:
        system = build_system(star, known_systems.get(star["name"]), seed, with_moons=False)
        counts.append(len(system["planets"]))
        flags.append(system["flags"])
    return counts, flags


# ---------------------------------------------------------------------------
# Data files and the cached per-star summary
# ---------------------------------------------------------------------------
def load_known_systems(data_dir) -> tuple[dict, int]:
    """Confirmed systems keyed by map star name, plus a CRC of the source files (for cache checks)."""
    import json
    import zlib
    from pathlib import Path

    data_dir = Path(data_dir)
    known, crc = {}, 0
    path = data_dir / "known_planets.json"
    if path.exists():
        raw = path.read_bytes()
        crc = zlib.crc32(raw, crc)
        known.update(json.loads(raw.decode("utf-8"))["systems"])
    path = data_dir / "solar_system.json"
    if path.exists():
        raw = path.read_bytes()
        crc = zlib.crc32(raw, crc)
        sol = json.loads(raw.decode("utf-8"))
        known[sol["name"]] = sol
    return known, crc


def names_crc(stars: list) -> int:
    import zlib
    return zlib.crc32("\n".join(s["name"] for s in stars).encode("utf-8"))


def load_or_build_summary(data_dir, stars: list, seed=None, force: bool = False) -> dict:
    """Return data/systems_summary.json, regenerating it if missing, stale or a new seed is given."""
    import json
    from pathlib import Path

    path = Path(data_dir) / "systems_summary.json"
    known, known_crc = load_known_systems(data_dir)
    current = None
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            current = None
    if seed is None:
        seed = current.get("seed", DEFAULT_SEED) if current else DEFAULT_SEED
    expected = {"version": GENERATOR_VERSION, "seed": seed, "star_count": len(stars),
                "names_crc": names_crc(stars), "known_crc": known_crc}
    if not force and current and all(current.get(k) == v for k, v in expected.items()):
        return current
    counts, flags = build_summary(stars, known, seed)
    summary = dict(expected, planets=counts, flags=flags)
    path.write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    return summary
