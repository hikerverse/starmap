"""Download confirmed exoplanets from the NASA Exoplanet Archive and match their host stars
to data/stars.json, producing data/known_planets.json.

Usage:  python tools/fetch_exoplanets.py [--offline]

Hosts are matched first by catalogue number (HIP, HD, Gliese/GJ) through the HYG
database, then by sky position (< 4 arcmin, allowing for proper motion) and distance
(within 20 %). Several archive hosts can map to one map star because close binaries
were merged into a single point when the HYG catalogue was imported.
--offline re-uses the last downloaded archive table.
"""

import csv
import gzip
import io
import json
import math
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from import_hyg import SpatialIndex, download_hyg  # noqa: E402

STARS_FILE = ROOT / "data" / "stars.json"
OUT_FILE = ROOT / "data" / "known_planets.json"
CACHE = Path(tempfile.gettempdir()) / "nasa_pscomppars.csv"
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
COLUMNS = ("pl_name,hostname,hip_name,hd_name,ra,dec,sy_dist,sy_pnum,pl_orbper,pl_orbsmax,"
           "pl_orbeccen,pl_rade,pl_bmasse,pl_bmassprov,pl_eqt,pl_insol,st_teff,st_lum,st_mass,"
           "st_rad,st_spectype,discoverymethod,disc_year,pl_controv_flag")
MAX_DIST_PC = 1000
ID_MATCH_PC = 0.06
POS_MATCH_ARCMIN = 4.0
DIST_TOLERANCE = 0.2


def fetch_table(offline: bool) -> list[dict]:
    if not offline or not CACHE.exists():
        query = f"select {COLUMNS} from pscomppars where sy_dist < {MAX_DIST_PC}"
        url = f"{TAP_URL}?query={urllib.parse.quote(query)}&format=csv"
        print("Querying NASA Exoplanet Archive ...")
        with urllib.request.urlopen(url, timeout=180) as r:
            CACHE.write_bytes(r.read())
    with open(CACHE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def norm_gl(name: str) -> str:
    name = name.replace(" ", "").upper()
    for prefix in ("GLIESE", "GL"):
        if name.startswith(prefix):
            return "GJ" + name[len(prefix):]
    return name


def num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def to_xyz(ra_deg: float, dec_deg: float, dist: float):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return (dist * math.cos(dec) * math.cos(ra), dist * math.cos(dec) * math.sin(ra), dist * math.sin(dec))


def main(offline: bool) -> None:
    rows = fetch_table(offline)
    print(f"{len(rows)} confirmed planets within {MAX_DIST_PC} pc")
    stars = json.loads(STARS_FILE.read_text(encoding="utf-8"))["stars"]

    star_index = SpatialIndex(ID_MATCH_PC)
    sky = {}   # direction grid for the positional fallback
    cell = math.radians(POS_MATCH_ARCMIN / 60)
    for s in stars:
        p = (s["x"], s["y"], s["z"])
        star_index.add(p, s)
        d = math.dist((0, 0, 0), p)
        if d > 0:
            u = tuple(c / d for c in p)
            sky.setdefault(tuple(math.floor(c / cell) for c in u), []).append((u, d, s))

    # Catalogue IDs -> HYG positions -> map star
    by_id = {}
    with gzip.open(download_hyg(), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["x"]:
                continue
            p = (float(r["x"]), float(r["y"]), float(r["z"]))
            for key in (f"HIP{r['hip']}" if r["hip"] else None, f"HD{r['hd']}" if r["hd"] else None,
                        norm_gl(r["gl"]) if r["gl"] else None):
                if key:
                    by_id.setdefault(key, p)

    def match_by_id(row):
        keys = []
        for field in ("hip_name", "hd_name"):
            if row[field]:
                keys.append(row[field].replace(" ", "").upper())
        host = norm_gl(row["hostname"])
        if host.startswith("GJ"):
            keys.append(host)
            keys.append(host.rstrip("ABC"))
        for key in keys:
            p = by_id.get(key)
            if p:
                s = star_index.find(p, ID_MATCH_PC)
                if s:
                    return s, "id"
        return None, None

    def match_by_position(row):
        ra, dec, dist = num(row["ra"]), num(row["dec"]), num(row["sy_dist"])
        if ra is None or dec is None or dist is None:
            return None, None
        u = to_xyz(ra, dec, 1.0)
        k = tuple(math.floor(c / cell) for c in u)
        best, best_sep = None, cell
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for v, d, s in sky.get((k[0] + dx, k[1] + dy, k[2] + dz), ()):
                        sep = math.dist(u, v)
                        if sep < best_sep and abs(d - dist) <= DIST_TOLERANCE * dist:
                            best, best_sep = s, sep
        return (best, "position") if best else (None, None)

    systems, unmatched, how = {}, set(), {"id": 0, "position": 0}
    host_cache = {}
    for row in rows:
        host = row["hostname"]
        if host not in host_cache:
            star, method = match_by_id(row)
            if not star:
                star, method = match_by_position(row)
            host_cache[host] = star
            if star:
                how[method] += 1
        star = host_cache[host]
        if not star:
            unmatched.add(host)
            continue
        if star["name"] == "Sol":
            continue
        system = systems.setdefault(star["name"], {"hosts": [], "planets": [], "star": None})
        if host not in system["hosts"]:
            system["hosts"].append(host)
        lum = num(row["st_lum"])
        if system["star"] is None and num(row["st_teff"]) and lum is not None and len(system["hosts"]) == 1:
            system["star"] = {"teff": num(row["st_teff"]), "lum": 10 ** lum,
                              "mass": num(row["st_mass"]), "radius": num(row["st_rad"]),
                              "spectral_type": row["st_spectype"] or None}
        planet = {
            "name": row["pl_name"],
            "host": host,
            "a_au": num(row["pl_orbsmax"]),
            "period_d": num(row["pl_orbper"]),
            "e": num(row["pl_orbeccen"]),
            "mass_mearth": num(row["pl_bmasse"]),
            "mass_kind": row["pl_bmassprov"] or None,
            "radius_rearth": num(row["pl_rade"]),
            "discovery": row["discoverymethod"],
            "year": int(row["disc_year"]) if row["disc_year"] else None,
        }
        if row["pl_controv_flag"] == "1":
            planet["disputed"] = True
        system["planets"].append({k: v for k, v in planet.items() if v is not None})

    for name, system in systems.items():
        if system["star"] is None:
            del system["star"]
        else:
            system["star_source"] = "NASA Exoplanet Archive (host " + system["hosts"][0] + ")"
        system["planets"].sort(key=lambda p: p.get("a_au") or 0)

    lines = [f'    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, separators=(",", ":"))}'
             for k, v in sorted(systems.items())]
    header = {
        "source": "NASA Exoplanet Archive, Planetary Systems Composite Parameters (pscomppars), "
                  "https://exoplanetarchive.ipac.caltech.edu",
        "retrieved": __import__("datetime").date.today().isoformat(),
    }
    OUT_FILE.write_text("{\n" + "".join(f"  {json.dumps(k)}: {json.dumps(v)},\n" for k, v in header.items())
                        + '  "systems": {\n' + ",\n".join(lines) + "\n  }\n}\n", encoding="utf-8")
    planets = sum(len(s["planets"]) for s in systems.values())
    print(f"Matched {len(host_cache) - len(unmatched)} of {len(host_cache)} hosts "
          f"({how['id']} by catalogue ID, {how['position']} by position) -> "
          f"{len(systems)} map stars with {planets} planets")
    print(f"{len(unmatched)} hosts are not in the star map (too faint for HYG, or no spectral type)")


if __name__ == "__main__":
    main("--offline" in sys.argv)
