"""Convert data/black_holes.csv into data/black_holes.json.

The CSV holds name, type, distance, constellation, mass, J2000 RA/Dec ("hh mm ss.s" / "+dd mm ss")
and notes for each black hole. Edit the CSV, then run:

    python tools/import_black_holes.py
"""

import csv
import json
import math
from pathlib import Path

from import_neutron_stars import sexagesimal

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "data" / "black_holes.csv"
OUT_FILE = ROOT / "data" / "black_holes.json"

COLOUR = "#ff9d3c"  # accretion-disc orange


def main() -> None:
    entries = []
    with CSV_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = row["Name"].strip()
            dist = float(row["Distance (pc)"])
            ra = sexagesimal(row["RA (J2000)"]) * 15
            dec = sexagesimal(row["Dec (J2000)"])
            if not (0 <= ra < 360 and -90 <= dec <= 90 and dist > 0):
                raise ValueError(f"{name}: invalid position/distance")
            ra_r, dec_r = math.radians(ra), math.radians(dec)
            entries.append({
                "name": name,
                "x": round(dist * math.cos(dec_r) * math.cos(ra_r), 4),
                "y": round(dist * math.cos(dec_r) * math.sin(ra_r), 4),
                "z": round(dist * math.sin(dec_r), 4),
                "colour": COLOUR,
                "spectral_class": "Black hole",
                "type": row["Type"].strip(),
                "mass_msun": float(row["Mass (solar masses)"]),
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
            "data/black_holes.csv (positions from SIMBAD; distances and masses from the literature, see README)",
        ],
        "stars": entries,
    }
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(entries)} black holes to {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
