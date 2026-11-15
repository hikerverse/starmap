"""Convert curated, OpenNGC and published HIZOA observations into data/galaxies.json.

The CSV holds name, catalogue ids, galaxy type, morphology, J2000 RA/Dec ("hh mm ss.s" / "+dd mm ss"),
distance in Mpc, approximate absolute V magnitude, major-axis size in arcmin, constellation, distance
reference and notes. Positions are written in parsecs (equatorial J2000, Sol at the origin) like every
other catalogue. Edit the CSV, then run:

    python tools/import_galaxies.py
"""

import argparse
import csv
import json
import math
import re
from pathlib import Path

from import_neutron_stars import sexagesimal

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "data" / "galaxies.csv"
OUT_FILE = ROOT / "data" / "galaxies.json"
EXPANSION_FILE = ROOT / "data" / "galaxies-opengnc.csv"
OPENNGC_SOURCE = "OpenNGC by Mattia Verga, https://github.com/mattiaverga/OpenNGC (CC BY-SA 4.0)"
HIZOA_HI_FILE = ROOT / "data" / "galaxies-hizoa-hi.tsv"
HIZOA_COUNTERPART_FILE = ROOT / "data" / "galaxies-hizoa-counterparts.tsv"
HIZOA_URL = "https://doi.org/10.26093/cds/vizier.51510052"
HIZOA_SOURCE = "HIZOA-S, Staveley-Smith et al. (2016), AJ 151, 52; " + HIZOA_URL

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


def catalogue_ids(text):
    return {f"{prefix.upper()}{int(number)}{suffix.upper()}"
            for prefix, number, suffix in re.findall(r"\b(NGC|IC|M)\s*0*(\d+)([A-Za-z]*)", text, re.I)}


def crossmatch_ids(text):
    ids = catalogue_ids(text)
    for prefix, number in re.findall(r"\b(PGC|UGC|WKK|RKK)\s*0*(\d+)\b", text, re.I):
        ids.add(f"{prefix.upper()}{int(number)}")
    for prefix, first, second in re.findall(r"\b(ESO|CGMW)\s*0*(\d+)-G?0*(\d+)\b", text, re.I):
        ids.add(f"{prefix.upper()}{int(first)}-{int(second)}")
    for prefix, coordinate in re.findall(r"\b(2MASX|2MASS|HIZOA)\s*(J\d+[+-]\d+[AB]?)\b", text, re.I):
        ids.add(prefix.upper() + coordinate.upper())
    return ids


def read_vizier_table(path):
    with path.open(encoding="utf-8", newline="") as stream:
        lines = [line for line in stream if line.strip() and not line.startswith("#")]
    if len(lines) < 4 or not lines[0].startswith("recno\t"):
        raise ValueError(f"{path}: expected a VizieR TSV table with data")
    fields = lines[0].rstrip("\r\n").split("\t")
    rows = []
    for values in csv.reader(lines[3:], delimiter="\t"):
        if len(values) != len(fields):
            raise ValueError(f"{path}: malformed VizieR row")
        rows.append(dict(zip(fields, (value.strip() for value in values))))
    return rows


def angular_separation(ra, dec, other_ra, other_dec):
    ra, dec, other_ra, other_dec = map(math.radians, (ra, dec, other_ra, other_dec))
    value = (math.sin((dec - other_dec) / 2) ** 2
             + math.cos(dec) * math.cos(other_dec) * math.sin((ra - other_ra) / 2) ** 2)
    return math.degrees(2 * math.asin(math.sqrt(max(0, min(1, value))))) * 60


def add_hizoa(entries, hi_rows, counterpart_rows):
    counterparts = {}
    for row in counterpart_rows:
        counterparts.setdefault(row["HIZOA"], []).append(row)
    identifier_index = {}
    for i, entry in enumerate(entries):
        if entry["galaxy_type"] in {"cluster", "interacting"}:
            continue
        for identifier in crossmatch_ids(entry["name"] + " " + entry["ids"]):
            identifier_index.setdefault(identifier, set()).add(i)
    # Only cross-match against the optical/curated catalogue, not coarse HI detections.
    original_count = len(entries)
    merged = 0
    seen = set()
    for row in hi_rows:
        identifier = row["HIZOA"]
        if identifier in seen:
            raise ValueError(f"Duplicate HIZOA detection: {identifier}")
        seen.add(identifier)
        name = "HIZOA " + identifier
        ra = sexagesimal(row["RAJ2000"]) * 15
        dec = sexagesimal(row["DEJ2000"])
        distance = float(row["Dist"]) * 1e6
        velocity = float(row["HRV"])
        error = float(row["e_HRV"])
        log_mass = float(row["logMHI"])
        if not (0 <= ra < 360 and -90 <= dec <= 90 and distance > 0
                and all(map(math.isfinite, (ra, dec, distance, velocity, error, log_mass)))):
            raise ValueError(f"{name}: invalid HIZOA measurement")
        candidates = counterparts.get(identifier, [])
        # Probable, ambiguous and confused candidates are not asserted as aliases.
        definite = [c for c in candidates if c["Cl"] == "d" and not c["u_OName"]]
        matches = set()
        aliases = [c["OName"] for c in definite if c["OName"]]
        for alias in aliases:
            for key in crossmatch_ids(alias):
                matches.update(identifier_index.get(key, set()))
        method = "Published definite counterpart identifier"
        if not matches:
            method = "Definite counterpart within 1 arcmin and compatible radial velocity"
            for counterpart in definite:
                if (not counterpart["RAJ2000"] or not counterpart["DEJ2000"]
                        or counterpart["u_RAJ2000"] or counterpart["u_DEJ2000"]):
                    continue
                cra = sexagesimal(counterpart["RAJ2000"]) * 15
                cdec = sexagesimal(counterpart["DEJ2000"])
                for i, entry in enumerate(entries[:original_count]):
                    if entry["galaxy_type"] in {"cluster", "interacting"}:
                        continue
                    # Existing flow distances use H0=70; this is a compatibility
                    # screen, not a replacement for their published distance.
                    expected_velocity = entry["distance_pc"] / 1e6 * 70
                    if (abs(expected_velocity - velocity) <= max(300, abs(velocity) * 0.1)
                            and angular_separation(cra, cdec, entry["ra_deg"], entry["dec_deg"]) <= 1):
                        matches.add(i)
        observation = {
            "id": name, "radial_velocity_kms": velocity,
            "radial_velocity_error_kms": error, "distance_pc": distance,
            "log_hi_mass_msun": log_mass,
            "distance_ref": "HIZOA-S Table 2 published distance; primarily Local Group velocity "
                            "with H0=75 km/s/Mpc. See survey reference for nearby distance choices.",
            "counterparts": [f"{c['OName'] or '(unnamed)'} [{c['Cl']}]" for c in candidates],
            "crossmatch": method if len(matches) == 1 else
                         "Multiple possible catalogue matches; kept separate" if matches else
                         "No confirmed existing catalogue match",
        }
        if len(matches) == 1:
            entry = entries[next(iter(matches))]
            merged += 1
        else:
            rar, decr = math.radians(ra), math.radians(dec)
            entry = {
                "name": name, "ids": "", "ra_deg": round(ra, 5), "dec_deg": round(dec, 5),
                "distance_pc": distance,
                "x": round(distance * math.cos(decr) * math.cos(rar), 1),
                "y": round(distance * math.cos(decr) * math.sin(rar), 1),
                "z": round(distance * math.sin(decr), 1),
                "colour": TYPES["irregular"][0], "galaxy_type": "irregular",
                "spectral_class": "Unknown", "type": "HI-selected galaxy",
                "distance_ref": observation["distance_ref"],
                "notes": "Observed in the 21-cm neutral-hydrogen line with Parkes. "
                         "Position is the radio detection centroid. Morphology and V magnitude are unknown; "
                         "irregular marker is illustrative. HI mass is neutral hydrogen only, not total galaxy mass. "
                         "Flow distances are uncertain due to peculiar velocities.",
                "catalogues": [],
            }
            entries.append(entry)
        entry["ids"] = "; ".join(filter(None, [entry["ids"], name, *aliases]))
        entry.setdefault("hi_observations", []).append(observation)
        if not any(c["name"] == "HIZOA-S" for c in entry["catalogues"]):
            entry["catalogues"].append({"name": "HIZOA-S", "url": HIZOA_URL})
    return {"detections": len(hi_rows), "crossmatched": merged, "added": len(hi_rows) - merged}


def expand_opengnc(path: Path) -> None:
    with CSV_FILE.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        curated = list(reader)
    seen = set()
    for row in curated:
        seen.update(catalogue_ids(row["Name"] + " " + row["IDs"]))
    entries = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["Type"] not in {"G", "GPair", "GTrpl", "GGroup"}:
                continue
            redshift = optional_float(row["Redshift"])
            if redshift is None or not math.isfinite(redshift) or not 0.0033 <= redshift <= 0.05:
                continue
            identifiers = row["Name"]
            for prefix in ("NGC", "IC", "M"):
                identifiers += " " + " ".join(prefix + n for n in row[prefix].split(",") if n)
            ids = catalogue_ids(identifiers)
            if ids & seen:
                continue
            seen.update(ids)
            distance = 299792.458 * redshift / 70
            morphology = row["Hubble"]
            gtype = ("interacting" if row["Type"] != "G" else
                     "elliptical" if morphology.startswith(("E", "S0")) else
                     "spiral" if morphology.startswith("S") else "irregular")
            magnitude = optional_float(row["V-Mag"])
            entries.append({
                "Name": re.sub(r"^(NGC|IC)0*(\d+)", lambda m: f"{m[1]} {int(m[2])}", row["Name"]),
                "IDs": identifiers + " " + row["Identifiers"] + " " + row["Common names"],
                "Galaxy type": gtype, "Morphology": morphology or row["Type"],
                "RA (J2000)": row["RA"].replace(":", " "),
                "Dec (J2000)": row["Dec"].replace(":", " "),
                "Distance (Mpc)": f"{distance:.6f}",
                "Abs mag (V)": f"{magnitude - 5 * math.log10(distance * 1e6) + 5:.3f}" if magnitude is not None else "",
                "Size (arcmin)": row["MajAx"], "Constellation": row["Const"],
                "Distance ref": f"OpenNGC heliocentric z={redshift}; approximate Hubble flow, H0=70 km/s/Mpc",
                "Notes": "OpenNGC expansion. Distance ignores peculiar velocity and cosmological corrections. "
                         "Unknown morphology uses an irregular marker; groups are not resolved into members. "
                         + row["OpenNGC notes"],
            })
    with EXPANSION_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(entries)
    print(f"Wrote {len(entries)} OpenNGC additions")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opengnc", type=Path, help="Rebuild the expansion from a downloaded OpenNGC NGC.csv")
    args = parser.parse_args()
    if args.opengnc:
        expand_opengnc(args.opengnc)
    entries = []
    files = [CSV_FILE] + ([EXPANSION_FILE] if EXPANSION_FILE.exists() else [])
    rows = []
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows.extend((row, path) for row in csv.DictReader(f))
    for row, path in rows:
        name = row["Name"].strip()
        gtype = row["Galaxy type"].strip()
        if gtype not in TYPES:
            raise ValueError(f"{name}: unknown galaxy type '{gtype}'")
        dist = float(row["Distance (Mpc)"]) * 1e6
        ra = sexagesimal(row["RA (J2000)"]) * 15
        dec = sexagesimal(row["Dec (J2000)"])
        if not (0 <= ra < 360 and -90 <= dec <= 90 and math.isfinite(dist) and dist > 0):
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
            "catalogues": [{"name": "OpenNGC", "url": "https://github.com/mattiaverga/OpenNGC"}]
                          if path == EXPANSION_FILE else
                          [{"name": "Curated literature (NED/SIMBAD)", "url": "https://ned.ipac.caltech.edu/"}],
        }
        abs_mag = optional_float(row["Abs mag (V)"])
        if abs_mag is not None:
            entry["abs_mag"] = abs_mag
        size = optional_float(row["Size (arcmin)"])
        if size is not None:
            entry["size_arcmin"] = size
        entries.append(entry)

    survey_stats = add_hizoa(entries, read_vizier_table(HIZOA_HI_FILE),
                            read_vizier_table(HIZOA_COUNTERPART_FILE))
    print(f"HIZOA: {survey_stats}")
    entries.sort(key=lambda e: e["distance_pc"])
    data = {
        "units": "parsec",
        "frame": "Equatorial J2000, Sol at origin, +X towards RA 0h, +Z towards the north celestial pole",
        "sources": [
            "data/galaxies.csv (positions from NED/SIMBAD; distances from the reference given per object, "
            "Hubble-flow distances use H0 = 70 km/s/Mpc)",
            OPENNGC_SOURCE + "; adapted subset in data/galaxies-opengnc.csv; https://creativecommons.org/licenses/by-sa/4.0/",
            HIZOA_SOURCE + "; published tables 2 and 3, bundled VizieR TSV snapshots",
        ],
        "hizoa_import": survey_stats,
        "galaxies": entries,
    }
    with OUT_FILE.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(entries)} extragalactic objects to {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
