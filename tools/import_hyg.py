"""Append the nearest stars from the HYG database (CC BY-SA 4.0) to data/stars.json.

Usage:  python tools/import_hyg.py [count | all]      (default count = 100)

Stars already in stars.json are kept (only a missing abs_mag is filled in). New
stars are taken in order of distance from Sol, skipping:
  * entries without a valid distance or spectral class, and
  * stars within MIN_SEPARATION_PC of an existing star (close binary companions
    would sit on the same point on the map and be impossible to click).
"""

import csv
import gzip
import json
import math
import sys
import tempfile
import urllib.request
from pathlib import Path

HYG_URL = ("https://raw.githubusercontent.com/astronexus/HYG-Database/"
           "c7f7f883fe678cc7680169a50ccd7dcc49b060ce/hyg/CURRENT/hygdata_v40.csv.gz")
STARS_FILE = Path(__file__).resolve().parent.parent / "data" / "stars.json"
MIN_SEPARATION_PC = 0.05

GREEK = {
    "Alp": "Alpha", "Bet": "Beta", "Gam": "Gamma", "Del": "Delta", "Eps": "Epsilon",
    "Zet": "Zeta", "Eta": "Eta", "The": "Theta", "Iot": "Iota", "Kap": "Kappa",
    "Lam": "Lambda", "Mu": "Mu", "Nu": "Nu", "Xi": "Xi", "Omi": "Omicron", "Pi": "Pi",
    "Rho": "Rho", "Sig": "Sigma", "Tau": "Tau", "Ups": "Upsilon", "Phi": "Phi",
    "Chi": "Chi", "Psi": "Psi", "Ome": "Omega",
}

# Fallback colours per spectral letter when no B-V colour index is available
SPECTRAL_COLOURS = {
    "O": "#9bb0ff", "B": "#aabfff", "A": "#cad7ff", "F": "#f8f7ff",
    "G": "#fff4ea", "K": "#ffd2a1", "M": "#ffad6f", "D": "#e6ecff",
}


def download_hyg() -> Path:
    path = Path(tempfile.gettempdir()) / "hygdata_v40.csv.gz"
    if not path.exists():
        print(f"Downloading {HYG_URL} ...")
        urllib.request.urlretrieve(HYG_URL, path)
    return path


def bv_to_hex(bv: float) -> str:
    """Approximate star colour from the B-V colour index (via effective temperature)."""
    bv = max(-0.4, min(2.0, bv))
    temp = 4600 * (1 / (0.92 * bv + 1.7) + 1 / (0.92 * bv + 0.62))  # Ballesteros (2012)
    t = temp / 100
    # Blackbody -> RGB approximation (Tanner Helland)
    if t <= 66:
        r = 255
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255
    clamp = lambda v: int(max(0, min(255, round(v))))
    return f"#{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


def star_colour(row: dict) -> str:
    if row["ci"]:
        return bv_to_hex(float(row["ci"]))
    letter = row["spect"].lstrip("sd")[:1].upper()
    return SPECTRAL_COLOURS.get(letter, "#ffffff")


def star_name(row: dict) -> str:
    if row["proper"]:
        return row["proper"]
    gl = row["gl"]
    component = gl[-1] if gl and gl[-1] in "ABC" else ""
    con = row["con"]
    if row["bayer"] and con:
        bayer = row["bayer"]
        base = GREEK.get(bayer[:3], bayer[:3]) + bayer[3:].replace("-", "")
        name = f"{base} {con}"
    elif row["flam"] and con:
        name = f"{row['flam']} {con}"
    else:
        return gl
    return f"{name} {component}".strip()


def catalogue_id(row: dict) -> str:
    for field, prefix in (("gl", ""), ("hd", "HD "), ("hip", "HIP "), ("hr", "HR ")):
        if row[field]:
            return prefix + row[field]
    return f"HYG {row['id']}"


class SpatialIndex:
    """Uniform grid hash so 'is any star within MIN_SEPARATION_PC?' stays O(1)."""

    def __init__(self, cell: float):
        self.cell = cell
        self.cells: dict[tuple[int, int, int], list] = {}

    def _key(self, p):
        return tuple(math.floor(c / self.cell) for c in p)

    def add(self, p, item):
        self.cells.setdefault(self._key(p), []).append((p, item))

    def find(self, p, radius: float):
        kx, ky, kz = self._key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q, item in self.cells.get((kx + dx, ky + dy, kz + dz), ()):
                        if math.dist(p, q) < radius:
                            return item
        return None


def main(count: float) -> None:
    db = json.loads(STARS_FILE.read_text(encoding="utf-8"))
    existing = db["stars"]
    index = SpatialIndex(MIN_SEPARATION_PC)
    for s in existing:
        index.add((s["x"], s["y"], s["z"]), s)
    taken_names = {s["name"] for s in existing}

    with gzip.open(download_hyg(), "rt", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r["dist"] and 0 < float(r["dist"]) < 100000 and r["spect"].strip()]
    # Process primaries before their B/C companions so the named primary is the one kept
    rows.sort(key=lambda r: float(r["dist"]) + (0.1 if r["gl"][-1:] in ("B", "C") else 0))

    added = []
    for row in rows:
        pos = (float(row["x"]), float(row["y"]), float(row["z"]))
        abs_mag = round(float(row["absmag"]), 2) if row["absmag"] else None
        match = index.find(pos, MIN_SEPARATION_PC)
        if match is not None:
            # Existing entry (hand-made or previously imported): fill in brightness if missing
            if "abs_mag" not in match and abs_mag is not None:
                match["abs_mag"] = abs_mag
            continue
        if len(added) >= count:
            continue  # keep scanning so existing entries still get their abs_mag
        name = star_name(row) or catalogue_id(row)
        if name in taken_names:
            name = f"{name} ({catalogue_id(row)})"
        star = {
            "name": name,
            "x": round(pos[0], 3), "y": round(pos[1], 3), "z": round(pos[2], 3),
            "colour": star_colour(row),
            "spectral_class": " ".join(row["spect"].split()),
        }
        if abs_mag is not None:
            star["abs_mag"] = abs_mag
        added.append(star)
        index.add(pos, star)
        taken_names.add(name)

    for s in existing:
        if "abs_mag" not in s and s["x"] == s["y"] == s["z"] == 0:
            s["abs_mag"] = 4.83  # Sol is not in the distance-filtered catalogue rows

    db["stars"] = existing + added
    db["sources"] = ("Additional stars from the HYG Database v4.0 by David Nash "
                     "(https://github.com/astronexus/HYG-Database), CC BY-SA 4.0")

    # One star per line keeps the file readable and diff-friendly
    lines = [f'    {json.dumps(s, ensure_ascii=False, separators=(",", ":"))}' for s in db["stars"]]
    header = {k: v for k, v in db.items() if k != "stars"}
    body = ",\n".join(f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in header.items())
    STARS_FILE.write_text("{\n" + body + ',\n  "stars": [\n' + ",\n".join(lines) + "\n  ]\n}\n",
                          encoding="utf-8")
    farthest = max((math.dist((0, 0, 0), (s["x"], s["y"], s["z"])) for s in added), default=0)
    print(f"Added {len(added)} stars; {len(db['stars'])} total (farthest added {farthest:.2f} pc)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "100"
    main(math.inf if arg == "all" else int(arg))
