"""Convert data/galaxies.csv into data/galaxies.json (curated well-known extragalactic objects).

The CSV holds name, catalogue ids, galaxy type, morphology, J2000 RA/Dec ("hh mm ss.s" / "+dd mm ss"),
distance in Mpc, approximate absolute V magnitude, major-axis size in arcmin, constellation, distance
reference and notes. Positions are written in parsecs (equatorial J2000, Sol at the origin) like every
other catalogue. Edit the CSV, then run:

    python tools/import_galaxies.py
"""

import csv
import json
import math
from pathlib import Path

from import_neutron_stars import sexagesimal

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "data" / "galaxies.csv"
OUT_FILE = ROOT / "data" / "galaxies.json"

# Marker colour and readable label per galaxy type (keys must match GALAXY_TYPES in app.py)
TYPES = {
    "spiral": ("#9fbfff", "Spiral galaxy"),
    "elliptical": ("#ffd9a0", "Elliptical galaxy"),
    "irregular": ("#a8e6ff", "Irregular galaxy"),
    "dwarf": ("#c9b8ff", "Dwarf galaxy"),
    "interacting": ("#ff9de2", "Interacting galaxies"),
    "peculiar": ("#ffb3b3", "Peculiar (ring) galaxy"),
    "active": ("#7ff0ff", "Active galaxy (AGN)"),
    "cluster": ("#ffcf6b", "Galaxy cluster"),
}


def optional_float(text: str):
    text = text.strip()
    return float(text) if text else None


def main() -> None:
    entries = []
    with CSV_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = row["Name"].strip()
            gtype = row["Galaxy type"].strip()
            if gtype not in TYPES:
                raise ValueError(f"{name}: unknown galaxy type '{gtype}'")
            dist = float(row["Distance (Mpc)"]) * 1e6
            ra = sexagesimal(row["RA (J2000)"]) * 15
            dec = sexagesimal(row["Dec (J2000)"])
            if not (0 <= ra < 360 and -90 <= dec <= 90 and dist > 0):
                raise ValueError(f"{name}: invalid position/distance")
            ra_r, dec_r = math.radians(ra), math.radians(dec)
            colour, label = TYPES[gtype]
            entry = {
                "name": name,
                "x": round(dist * math.cos(dec_r) * math.cos(ra_r), 1),
                "y": round(dist * math.cos(dec_r) * math.sin(ra_r), 1),
                "z": round(dist * math.sin(dec_r), 1),
                "colour": colour,
                "spectral_class": row["Morphology"].strip(),
                "galaxy_type": gtype,
                "type": label,
                "ids": row["IDs"].strip(),
                "ra_deg": round(ra, 5),
                "dec_deg": round(dec, 5),
                "distance_pc": dist,
                "distance_ref": row["Distance ref"].strip(),
                "constellation": row["Constellation"].strip(),
                "notes": row["Notes"].strip(),
            }
            abs_mag = optional_float(row["Abs mag (V)"])
            if abs_mag is not None:
                entry["abs_mag"] = abs_mag
            size = optional_float(row["Size (arcmin)"])
            if size is not None:
                entry["size_arcmin"] = size
            entries.append(entry)

    entries.sort(key=lambda e: e["distance_pc"])
    data = {
        "units": "parsec",
        "frame": "Equatorial J2000, Sol at origin, +X towards RA 0h, +Z towards the north celestial pole",
        "sources": [
            "data/galaxies.csv (positions from NED/SIMBAD; distances from the reference given per object, "
            "Hubble-flow distances use H0 = 70 km/s/Mpc)",
        ],
        "galaxies": entries,
    }
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(entries)} extragalactic objects to {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
