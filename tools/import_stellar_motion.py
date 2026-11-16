"""Fetch measured Gaia/HYG velocities, matched by existing Gaia IDs or unambiguous HYG rows.

Usage: python tools/import_stellar_motion.py [dataset] [destination] [--cache DIRECTORY]
The active database is not modified. Download caches allow interrupted imports to resume.
"""

import argparse
import csv
import gzip
import json
import math
import os
import sqlite3
import sys
import tempfile
import urllib.request
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import datasets as D
from stellar_motion import gaia_measurement, number, velocity
from enrich_gaia import _choose_hyg_row, _read_hyg_rows
from import_hyg import HYG_URL

COLUMNS = ("source_id,ra,dec,parallax,parallax_error,pmra,pmdec,pmra_error,"
           "pmdec_error,radial_velocity,radial_velocity_error")
TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
# Curated map names differ from both HYG's proper names and its abbreviated Bayer names.
CURATED_HIP = {"Alpha Centauri A": "71683", "Epsilon Eridani": "16537"}


def download(url, destination, data=None):
    if destination.exists():
        return
    temp = destination.with_suffix(destination.suffix + ".part")
    print(f"Downloading {destination.name}...", flush=True)
    try:
        with urllib.request.urlopen(url, data=data, timeout=600) as response, temp.open("wb") as out:
            while block := response.read(1024 * 1024):
                out.write(block)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def query_csv(query, destination):
    def fetch(adql, path):
        body = urlencode({"REQUEST": "doQuery", "LANG": "ADQL",
                          "FORMAT": "csv", "MAXREC": 1500000, "QUERY": adql}).encode()
        download(TAP, path, body)

    count_file = destination.with_suffix(".count.csv")
    fetch("SELECT COUNT(*) AS n FROM " + query.split(" FROM ", 1)[1], count_file)
    with count_file.open(encoding="utf-8-sig", newline="") as stream:
        expected = int(next(csv.DictReader(stream))["n"])
    fetch(query, destination)
    with destination.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "radial_velocity" not in reader.fieldnames:
            raise ValueError(f"Invalid Gaia response in {destination}; remove it and retry.")
        count = 0
        for row in reader:
            count += 1
            yield row
        if count != expected:
            raise ValueError(f"Truncated Gaia response in {destination}: expected {expected}, read {count}. Remove this cache file and retry with smaller batches.")


def build_motion(source, destination, cache):
    if destination.exists():
        raise ValueError(f"Destination already exists: {destination}")
    cache.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as db:
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM metadata")}
        stars = [
            {"id": sid, "name": name, "ordinal": ordinal, "x": x, "y": y, "z": z, "extra": json.loads(extra)}
            for sid, name, ordinal, x, y, z, extra in db.execute(
                "SELECT id,name,ordinal,x,y,z,extra FROM stars ORDER BY ordinal")
        ]
        additions = [
            {"id": sid, "name": name, "ordinal": 0, "x": x, "y": y, "z": z, "distance": distance,
             "extra": {"gaia_dr3": {"source_id": sid}}}
            for sid, name, x, y, z, distance in db.execute(
                "SELECT source_id,name,x,y,z,distance_pc FROM gaia_stars ORDER BY distance_pc,source_id")
        ] if db.execute("SELECT 1 FROM sqlite_master WHERE name='gaia_stars'").fetchone() else []
    wanted = {s["extra"].get("gaia_dr3", {}).get("source_id") for s in stars + additions}
    wanted.discard(None)
    measured = {}
    seen = set()

    def consume(rows):
        count = 0
        for row in rows:
            sid = row["source_id"]
            seen.add(sid)
            if sid in wanted:
                measurement = gaia_measurement(row)
                if measurement:
                    measured[sid] = measurement
            count += 1
        if count >= 1500000:
            raise ValueError("Gaia query reached MAXREC; refusing a possibly truncated import.")
        print(f"Read {count:,} Gaia rows; {len(measured):,} matched IDs.", flush=True)

    for lower, upper in [(None, 8), (8, 9), (9, 10), (10, 10.4), (10.4, 10.8)]:
        condition = "" if lower is None else f" AND phot_g_mean_mag > {lower}"
        consume(query_csv(f"SELECT {COLUMNS} FROM gaiadr3.gaia_source "
            "WHERE parallax >= 0.2 AND parallax_over_error >= 5 AND ruwe < 1.4 "
            f"AND astrometric_params_solved IN (31,95) AND phot_g_mean_mag <= {upper}{condition}",
            cache / f"gaia-motion-to-{upper}.csv"))
    consume(query_csv("SELECT " + ",".join("g." + col for col in COLUMNS.split(","))
        + " FROM gaiadr3.gaia_source AS g JOIN gaiadr3.hipparcos2_best_neighbour AS h "
          "ON g.source_id=h.source_id", cache / "gaia-motion-hipparcos.csv"))
    remaining = sorted(wanted - seen)
    for offset in range(0, len(remaining), 1000):
        batch = remaining[offset:offset + 1000]
        if not all(str(sid).isdigit() for sid in batch):
            raise ValueError("Invalid stored Gaia source ID")
        import hashlib
        key = hashlib.sha256(",".join(batch).encode()).hexdigest()[:16]
        consume(query_csv(f"SELECT {COLUMNS} FROM gaiadr3.gaia_source WHERE source_id IN ("
                          + ",".join(batch) + ")", cache / f"gaia-motion-{key}.csv"))

    hyg_file = cache / "hygdata_v40.csv.gz"
    download(HYG_URL, hyg_file)
    by_position, by_name = _read_hyg_rows(hyg_file, stars)
    curated = {}
    with gzip.open(hyg_file, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            for name, hip in CURATED_HIP.items():
                if row.get("hip") == hip:
                    curated.setdefault(name, []).append(row)
    counts = Counter()
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(temp)) as out:
            out.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE motion(name TEXT PRIMARY KEY,origin INTEGER,ordinal INTEGER,
                    distance REAL,source_id TEXT,has_gaia INTEGER,measurement TEXT);
                CREATE INDEX motion_distance ON motion(distance);
            """)
            for origin, objects in enumerate((stars, additions)):
                for star in objects:
                    gaia = star["extra"].get("gaia_dr3", {})
                    sid = gaia.get("source_id", "")
                    measurement = measured.get(sid)
                    hyg = None
                    if origin == 0:
                        hyg, _ = _choose_hyg_row(star, by_position, by_name)
                        if hyg is None and len(curated.get(star["name"], [])) == 1:
                            hyg = curated[star["name"]][0]
                    if hyg and star["name"] != "Sol":
                        pmra, pmdec, rv = (number(hyg.get(k)) for k in ("pmra", "pmdec", "rv"))
                        # HYG uses zero for many unknown velocities; do not call these measured.
                        if rv == 0:
                            rv = None
                        if pmra == 0 and pmdec == 0:
                            pmra = pmdec = None
                        distance = number(hyg.get("dist"))
                        if all(v is not None for v in (pmra, pmdec, distance)) and distance > 0:
                            if measurement is None or (not measurement["full"] and rv is not None):
                                # Never interpret HYG's derived vx/vy/vz as proof of a measured RV.
                                ra, dec = number(hyg["ra"]) * 15, number(hyg["dec"])
                                measurement = {"v": velocity(ra, dec, distance, pmra, pmdec, rv or 0),
                                    "full": rv is not None, "rv": rv, "rv_error": None, "sigma": None,
                                    "source": "HYG v4.0", "source_id": hyg["id"], "epoch": 2000.0,
                                    "values": {"ra": ra, "dec": dec, "distance": distance,
                                               "pmra": pmra, "pmdec": pmdec, "radial_velocity": rv}}
                    if star["name"] == "Sol":
                        measurement = {"v": [0, 0, 0], "full": True, "rv": 0, "rv_error": None,
                            "sigma": 0, "source": "Heliocentric reference", "source_id": "Sol", "epoch": 2000.0}
                    counts["complete" if measurement and measurement["full"] else "partial" if measurement else "missing"] += 1
                    if measurement:
                        counts[measurement["source"]] += 1
                    out.execute("INSERT INTO motion VALUES (?,?,?,?,?,?,?)", (
                        star["name"], origin, star["ordinal"],
                        star.get("distance", math.sqrt(sum(star[k]**2 for k in ("x", "y", "z")))),
                        sid, int(bool(sid)), D.dumps(measurement) if measurement else None))
            provenance = {"generated_at": datetime.now(timezone.utc).isoformat(),
                "gaia": "Gaia DR3, gaiadr3.gaia_source; matched by previously cross-referenced source_id",
                "hyg": HYG_URL, "hyg_matching": "Unique existing J2000 position or unambiguous catalogue alias",
                "curated_hipparcos_identifiers": CURATED_HIP,
                "model": "Constant heliocentric Cartesian velocity, anchored to existing J2000 map positions",
                "counts": dict(counts)}
            out.executemany("INSERT INTO metadata VALUES (?,?)", [
                ("dataset_id", D.dumps(meta["dataset_id"])), ("provenance", D.dumps(provenance))])
            out.commit()
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=ROOT / "data" / "stars-gaia-temperatures.sqlite")
    parser.add_argument("destination", nargs="?", type=Path, default=ROOT / "data" / "stellar-motion.sqlite")
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "starexplorer-motion")
    args = parser.parse_args()
    print(dict(build_motion(args.source, args.destination, args.cache)), flush=True)


if __name__ == "__main__":
    main()
