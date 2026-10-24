"""Convert data/neutron_stars_1000pc.csv into data/neutron_stars.json.

The CSV only gives distance and constellation, so sky positions (J2000 RA/Dec) come from
KNOWN_COORDS below. Each entry is cross-checked against the object's J2000 designation
(e.g. "J1856.5-3754"), which encodes a truncated RA/Dec. Rows without a KNOWN_COORDS entry
fall back to the coordinates encoded in their J designation.

Usage:  python tools/import_neutron_stars.py
"""

import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "data" / "neutron_stars_1000pc.csv"
OUT_FILE = ROOT / "data" / "neutron_stars.json"

COLOUR = "#b48cff"  # distinct violet, so neutron stars stand out from normal blue-white stars

# J2000 positions (SIMBAD / ATNF pulsar catalogue): name -> (J designation, "hh mm ss.s", "+dd mm ss")
KNOWN_COORDS = {
    "RX J1856.5-3754": ("J1856.5-3754", "18 56 35.11", "-37 54 30.5"),
    "Geminga": ("J0633+1746", "06 33 54.15", "+17 46 12.9"),
    "PSR J2124-3358": ("J2124-3358", "21 24 43.85", "-33 58 44.7"),
    "Vela Pulsar (PSR J0835-4510)": ("J0835-4510", "08 35 20.61", "-45 10 34.9"),
    "RX J0720.4-3125": ("J0720.4-3125", "07 20 24.96", "-31 25 50.1"),
    "LAMOST J2354+3356": ("J2354+3356", "23 54 56.76", "+33 56 25.7"),
    "PSR B0943+10": ("J0946+0951", "09 46 07.6", "+09 51 55"),
    "Lich (PSR B1257+12)": ("J1300+1240", "13 00 03.58", "+12 40 56.5"),
    "PSR J1748-2021B": ("J1748-2021", "17 48 52.69", "-20 21 38.9"),
    "PSR J0952-0607": ("J0952-0607", "09 52 08.32", "-06 07 23.5"),
}

J_NAME = re.compile(r"J(\d{2})(\d{2}(?:\.\d+)?)([+-])(\d{2})(\d{2})")


def sexagesimal(text: str) -> float:
    sign = -1.0 if text.strip().startswith("-") else 1.0
    a, b, c = (abs(float(v)) for v in text.split())
    return sign * (a + b / 60 + c / 3600)


def parse_j_name(name: str):
    """Return (ra_deg, dec_deg, ra_step_deg, dec_step_deg) encoded (truncated) in a J designation."""
    m = J_NAME.search(name)
    if not m:
        return None
    hh, mm, sign, dd, dm = m.groups()
    ra_step = (0.1 if "." in mm else 1.0) / 60 * 15  # truncated RA precision, degrees
    ra = (int(hh) + float(mm) / 60) * 15
    dec = int(dd) + int(dm) / 60
    return ra, (-dec if sign == "-" else dec), ra_step, 1 / 60


def position(name: str):
    """J2000 (ra_deg, dec_deg) for a neutron star, verified against its J designation."""
    if name in KNOWN_COORDS:
        jname, ra_s, dec_s = KNOWN_COORDS[name]
        ra, dec = sexagesimal(ra_s) * 15, sexagesimal(dec_s)
        j_ra, j_dec, ra_step, dec_step = parse_j_name(jname)
        # J designations truncate, so the true position lies within one step "outward"
        if not (j_ra <= ra < j_ra + ra_step + 1e-9 and abs(j_dec) <= abs(dec) < abs(j_dec) + dec_step + 1e-9):
            raise ValueError(f"{name}: coordinates {ra_s} {dec_s} don't match {jname}")
        return ra, dec
    parsed = parse_j_name(name)
    if not parsed:
        raise ValueError(f"{name}: no known coordinates and no J2000 designation in the name")
    ra, dec, ra_step, dec_step = parsed
    # Use the centre of the truncation box
    return ra + ra_step / 2, dec + math.copysign(dec_step / 2, dec)


def main() -> None:
    entries = []
    with CSV_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = row["Name"].strip()
            dist = float(row["Distance (pc)"])
            ra, dec = position(name)
            ra_r, dec_r = math.radians(ra), math.radians(dec)
            entries.append({
                "name": name,
                "x": round(dist * math.cos(dec_r) * math.cos(ra_r), 4),
                "y": round(dist * math.cos(dec_r) * math.sin(ra_r), 4),
                "z": round(dist * math.sin(dec_r), 4),
                "colour": COLOUR,
                "spectral_class": "Neutron star",
                "type": row["Type"].strip(),
                "ra_deg": round(ra, 5),
                "dec_deg": round(dec, 5),
                "distance_pc": dist,
                "constellation": row["Constellation"].strip(),
                "notes": row["Key Notes"].strip(),
            })

    data = {
        "units": "parsec",
        "frame": "Equatorial J2000, Sol at origin, +X towards RA 0h, +Z towards the north celestial pole",
        "sources": [
            "Names, types, distances and notes: data/neutron_stars_1000pc.csv",
            "Positions: SIMBAD / ATNF Pulsar Catalogue J2000 coordinates",
        ],
        "stars": entries,
    }
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(entries)} neutron stars to {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
