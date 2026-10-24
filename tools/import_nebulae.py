"""Build data/nebulae.json from three sources.

1. data/nebulae_curated.csv: about 90 well-known emission, reflection, planetary, supernova-remnant
   and dark nebulae with literature distances (column `distance_ref`).
2. Planetary nebulae with Gaia EDR3 central-star distances: González-Santamaría et al. (2021),
   A&A 656, A51 (VizieR J/A+A/656/A51, tables A1 + A2).
3. Molecular clouds: Zucker et al. (2020), A&A 633, A51, "A compendium of distances to molecular clouds in
   the Star Formation Handbook" (VizieR J/A+A/633/A51). Each Gaia sightline becomes a "puff"
   at its own distance, so clouds keep their measured 3D shape.

The VizieR tables are downloaded once and cached in %TEMP% (use --offline to only use the cache):

    python tools/import_nebulae.py [--offline]
"""

import argparse
import csv
import json
import math
import os
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURATED_FILE = ROOT / "data" / "nebulae_curated.csv"
OUT_FILE = ROOT / "data" / "nebulae.json"
TMP = Path(os.environ.get("TEMP", "/tmp"))
VIZIER_HOSTS = ["vizier.cds.unistra.fr", "vizier.cfa.harvard.edu"]
CATALOGUES = {
    "pn": ("J/A+A/656/A51", TMP / "gs2021.tsv"),
    "clouds": ("J/A+A/633/A51", TMP / "zucker2020.tsv"),
}

TYPES = {
    #  code         colour     label                    default description
    "emission": ("#ff5a7a", "Emission nebula", "H II region"),
    "reflection": ("#6fa8ff", "Reflection nebula", "Reflection nebula"),
    "planetary": ("#4fe0c8", "Planetary nebula", "Planetary nebula"),
    "snr": ("#ffa35c", "Supernova remnant", "Supernova remnant"),
    "dark": ("#9c7a5a", "Dark nebula", "Dark nebula"),
    "molecular": ("#9c7a5a", "Molecular cloud", "Molecular cloud"),
}
PN_MAX_DISTANCE_PC = 3000
PN_MIN_PARALLAX_SNR = 3.0       # keep central stars with parallax / error >= 3
PN_MATCH_ARCMIN = 1.0           # curated planetary nebula <-> catalogue cross-match radius
SIGHTLINE_RADIUS_DEG = 0.5      # angular radius represented by one Zucker sightline
PN_MORPH = {"E": "elliptical", "R": "round", "B": "bipolar", "I": "irregular", "S": "quasi-stellar",
            "A": "asymmetric", "P": "point-symmetric"}
CLOUD_NAMES = {"Orion_Lam": "Lambda Orionis cloud", "CygnusX": "Cygnus X cloud", "Aquila_Rift": "Aquila Rift"}


def xyz(ra_deg: float, dec_deg: float, dist: float) -> tuple[float, float, float]:
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return (dist * math.cos(dec) * math.cos(ra), dist * math.cos(dec) * math.sin(ra), dist * math.sin(dec))


def ang_sep_arcmin(ra1, dec1, ra2, dec2) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c)))) * 60


def fetch(source: str, path: Path, offline: bool) -> Path:
    if path.exists() or offline:
        if not path.exists():
            raise SystemExit(f"{path} not cached; run without --offline")
        return path
    query = urllib.parse.urlencode({"-source": source, "-out.all": "", "-out.max": "unlimited", "-oc.form": "dec"})
    last = None
    for host in VIZIER_HOSTS:
        try:
            print(f"Downloading {source} from {host} ...")
            data = urllib.request.urlopen(f"https://{host}/viz-bin/asu-tsv?{query}", timeout=600).read()
            path.write_bytes(data)
            return path
        except OSError as exc:
            last = exc
    raise SystemExit(f"Could not download {source}: {last}")


def read_vizier_tsv(path: Path) -> dict[str, list[dict]]:
    """Parse a multi-table VizieR ASU-TSV file into {table name: [row dict, ...]}."""
    tables: dict[str, list[dict]] = defaultdict(list)
    current = None
    header = None
    skip = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#Table"):
            current = line.split("\t")[1].rstrip(":")
            header = None
            continue
        if line.startswith("#") or not line.strip():
            if not line.strip():
                header = None
            continue
        if header is None:
            header = [h.strip() for h in line.split("\t")]
            skip = 2  # units + dashes lines
            continue
        if skip:
            skip -= 1
            continue
        values = [v.strip() for v in line.split("\t")]
        tables[current].append(dict(zip(header, values)))
    return tables


def num(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def entry(name, kind, ra, dec, dist, radius_pc, **extra) -> dict:
    colour, label, description = TYPES[kind]
    x, y, z = xyz(ra, dec, dist)
    out = {
        "name": name,
        "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
        "colour": colour,
        "spectral_class": label,
        "type": extra.pop("type", None) or description,
        "nebula_type": "dark" if kind == "molecular" else kind,
        "radius_pc": round(max(radius_pc, 0.01), 4),
        "ra_deg": round(ra, 5), "dec_deg": round(dec, 5),
        "distance_pc": round(dist, 1),
    }
    out.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return out


def load_pn_catalogue(path: Path) -> list[dict]:
    tables = read_vizier_tsv(path)
    main = {r["PNG"]: r for r in tables.get("J_A_A_656_A51_tablea1", [])}
    out = []
    for a in tables.get("J_A_A_656_A51_tablea2", []):
        m = main.get(a["PNG"])
        plx, e_plx, dist = num(a.get("Plx")), num(a.get("e_Plx")), num(a.get("Dist"))
        if not m or not plx or not e_plx or not dist:
            continue
        ra, dec = num(m.get("RA_ICRS")), num(m.get("DE_ICRS"))
        if ra is None or dec is None:
            continue
        out.append({
            "png": a["PNG"], "oname": m.get("OName", ""), "ra": ra, "dec": dec,
            "dist": dist, "lo": num(a.get("b_Dist")), "hi": num(a.get("B_Dist")),
            "snr": plx / e_plx, "group": m.get("Group", ""),
            "rad_arcsec": num(a.get("Radang")), "rad_pc": num(a.get("Radphys")),
            "morph": a.get("Morph", ""), "sptype": a.get("SpType", ""),
        })
    return out


def load_clouds(path: Path) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in read_vizier_tsv(path).get("J_A_A_633_A51_handbook", []):
        ra, dec, d = num(r.get("_RA.icrs")), num(r.get("_DE.icrs")), num(r.get("d50"))
        if ra is None or dec is None or not d:
            continue
        groups[r["Name"]].append({"ra": ra, "dec": dec, "d": d, "l": num(r["GLON"]), "b": num(r["GLAT"])})
    return groups


def cloud_name(raw: str) -> str:
    if raw in CLOUD_NAMES:
        return CLOUD_NAMES[raw]
    return raw.replace("_", " ") + " cloud"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="only use cached VizieR downloads")
    args = parser.parse_args()

    pns = load_pn_catalogue(fetch(*CATALOGUES["pn"], args.offline))
    good_pns = [p for p in pns if p["snr"] >= PN_MIN_PARALLAX_SNR and p["dist"] <= PN_MAX_DISTANCE_PC]
    clouds = load_clouds(fetch(*CATALOGUES["clouds"], args.offline))

    entries = []
    names = set()
    used_pn = set()
    gaia_updates = 0
    with CURATED_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name, kind = row["name"].strip(), row["type"].strip()
            if kind not in TYPES:
                raise ValueError(f"{name}: unknown type '{kind}'")
            ra, dec, dist = float(row["ra_deg"]), float(row["dec_deg"]), float(row["distance_pc"])
            size = float(row["size_arcmin"])
            if not (0 <= ra < 360 and -90 <= dec <= 90 and dist > 0 and size > 0):
                raise ValueError(f"{name}: invalid position/distance/size")
            ref = row["distance_ref"].strip()
            dist_range = None
            if kind == "planetary":
                # Prefer the Gaia EDR3 central-star distance when the catalogue has a reliable one
                match = min(good_pns, key=lambda p: ang_sep_arcmin(ra, dec, p["ra"], p["dec"]), default=None)
                if match and ang_sep_arcmin(ra, dec, match["ra"], match["dec"]) <= PN_MATCH_ARCMIN:
                    used_pn.add(match["png"])
                    dist, ref = match["dist"], "González-Santamaría+ 2021 (Gaia EDR3)"
                    if match["lo"] and match["hi"]:
                        dist_range = [match["lo"], match["hi"]]
                    gaia_updates += 1
            radius = dist * math.tan(math.radians(size / 120))
            entries.append(entry(
                name, kind, ra, dec, dist, radius,
                ids=row["ids"].strip(), constellation=row["constellation"].strip(),
                notes=row["notes"].strip(), distance_ref=ref, distance_range_pc=dist_range, source="curated",
            ))
            names.add(name)

    # Remaining planetary nebulae from the Gaia catalogue
    pn_count = 0
    for p in sorted(good_pns, key=lambda p: p["dist"]):
        if p["png"] in used_pn:
            continue
        name = p["oname"] or p["png"]
        if name in names:
            name = f"{name} ({p['png']})"
        rad = p["rad_pc"] or (p["dist"] * math.radians(p["rad_arcsec"] / 3600) if p["rad_arcsec"] else 0.1)
        morph = PN_MORPH.get(p["morph"][:1].upper(), "") if p["morph"] else ""
        entries.append(entry(
            name, "planetary", p["ra"], p["dec"], p["dist"], rad,
            type=f"Planetary nebula ({morph})" if morph else None,
            ids=p["png"],
            notes=f"Central star {p['sptype']}." if p["sptype"] else None,
            distance_ref="González-Santamaría+ 2021 (Gaia EDR3)",
            distance_range_pc=[p["lo"], p["hi"]] if p["lo"] and p["hi"] else None,
            source="González-Santamaría+ 2021",
        ))
        names.add(name)
        pn_count += 1

    # Molecular clouds: centroid of the sightlines, radius enclosing every sightline puff
    cloud_count = 0
    for raw, lines in sorted(clouds.items()):
        puffs = []
        for s in lines:
            x, y, z = xyz(s["ra"], s["dec"], s["d"])
            puffs.append([round(x, 3), round(y, 3), round(z, 3),
                          round(s["d"] * math.tan(math.radians(SIGHTLINE_RADIUS_DEG)), 3)])
        cx = sum(p[0] for p in puffs) / len(puffs)
        cy = sum(p[1] for p in puffs) / len(puffs)
        cz = sum(p[2] for p in puffs) / len(puffs)
        radius = max(math.dist((cx, cy, cz), p[:3]) + p[3] for p in puffs)
        dist = math.sqrt(cx * cx + cy * cy + cz * cz)
        ra = math.degrees(math.atan2(cy, cx)) % 360
        dec = math.degrees(math.asin(cz / dist))
        ds = [s["d"] for s in lines]
        name = cloud_name(raw)
        if name in names:
            name = f"{name} cloud"
        e = entry(
            name, "molecular", ra, dec, dist, radius,
            ids=f"Zucker+ 2020: {raw}",
            notes=f"{len(lines)} Gaia sightline{'s' if len(lines) > 1 else ''}; median distance "
                  f"{statistics.median(ds):.0f} pc" + (f" (range {min(ds):.0f}–{max(ds):.0f} pc)." if len(ds) > 1 else "."),
            distance_ref="Zucker+ 2020 (Gaia DR2)",
            distance_range_pc=[min(ds), max(ds)] if len(ds) > 1 else None,
            source="Zucker+ 2020",
        )
        e["puffs"] = puffs
        entries.append(e)
        names.add(name)
        cloud_count += 1

    data = {
        "units": "parsec",
        "frame": "Equatorial J2000, Sol at origin, +X towards RA 0h, +Z towards the north celestial pole",
        "sources": [
            "data/nebulae_curated.csv (well-known nebulae; distance references per entry)",
            "González-Santamaría et al. 2021, A&A 656, A51: planetary nebulae with Gaia EDR3 central-star distances",
            "Zucker et al. 2020, A&A 633, A51: Gaia DR2 distances to molecular clouds (one puff per sightline)",
        ],
        "puffs_format": "[x, y, z, radius] in parsecs, equatorial J2000",
        "nebulae": entries,
    }
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    curated = sum(1 for e in entries if e["source"] == "curated")
    print(f"Wrote {len(entries)} nebulae to {OUT_FILE.relative_to(ROOT)}: {curated} curated "
          f"({gaia_updates} planetary nebulae with Gaia EDR3 distances), {pn_count} catalogue planetary nebulae "
          f"(of {len(pns)}; parallax S/N >= {PN_MIN_PARALLAX_SNR:g}, <= {PN_MAX_DISTANCE_PC} pc), "
          f"{cloud_count} molecular clouds ({sum(len(v) for v in clouds.values())} sightlines)")


if __name__ == "__main__":
    main()
