"""Enrich an existing StarExplorer SQLite dataset with Gaia DR3 measurements."""

import argparse
import csv
import gzip
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import datasets as D
from import_hyg import catalogue_id, download_hyg, star_name

TAP_SYNC = "https://gea.esac.esa.int/tap-server/tap/sync"
HIPPARCOS_QUERY = """
SELECT h.original_ext_source_id, h.source_id, h.angular_distance,
       h.number_of_neighbours, h.xm_flag, g.ra, g.dec, g.parallax,
       g.parallax_error, g.pmra, g.pmra_error, g.pmdec, g.pmdec_error,
       g.phot_g_mean_mag, g.phot_bp_mean_mag, g.phot_rp_mean_mag, g.ruwe,
       g.astrometric_params_solved
FROM gaiadr3.hipparcos2_best_neighbour AS h
JOIN gaiadr3.gaia_source AS g ON g.source_id = h.source_id
"""
GAIA_COLUMNS = (
    "source_id", "ra", "dec", "parallax", "parallax_error", "pmra", "pmra_error",
    "pmdec", "pmdec_error", "phot_g_mean_mag", "phot_bp_mean_mag",
    "phot_rp_mean_mag", "ruwe", "astrometric_params_solved",
)
GAIA_VALUE_NAMES = {
    "ra": "ra_deg",
    "dec": "dec_deg",
    "parallax": "parallax_mas",
    "parallax_error": "parallax_error_mas",
    "pmra": "pmra_mas_per_year",
    "pmra_error": "pmra_error_mas_per_year",
    "pmdec": "pmdec_mas_per_year",
    "pmdec_error": "pmdec_error_mas_per_year",
    "phot_g_mean_mag": "phot_g_mean_mag",
    "phot_bp_mean_mag": "phot_bp_mean_mag",
    "phot_rp_mean_mag": "phot_rp_mean_mag",
    "ruwe": "ruwe",
    "astrometric_params_solved": "astrometric_params_solved",
}
GAIA_EPOCH = 2016.0
HYG_EPOCH = 2000.0
TAP_MAXREC = 1000000


class EnrichmentError(ValueError):
    """Raised when an input catalogue or Gaia TAP response cannot be used safely."""


def _normal_name(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


def _hyg_aliases(row):
    aliases = {star_name(row), catalogue_id(row), row.get("proper", ""), row.get("gl", "")}
    for field, prefix in (("hd", "HD "), ("hip", "HIP "), ("hr", "HR ")):
        if row.get(field):
            aliases.add(prefix + row[field])
    proper = row.get("proper", "").strip()
    gl = row.get("gl", "").strip()
    if proper and gl and gl[-1:] in {"A", "B", "C"}:
        aliases.add(f"{proper} {gl[-1]}")
    return {_normal_name(alias) for alias in aliases if alias}


def _position_key(x, y, z):
    return tuple(round(float(value), 3) for value in (x, y, z))


def _read_hyg_rows(path, stars):
    wanted_positions = {_position_key(star["x"], star["y"], star["z"]) for star in stars}
    wanted_names = {_normal_name(star["name"]) for star in stars}
    by_position = defaultdict(list)
    by_name = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            try:
                key = _position_key(row["x"], row["y"], row["z"])
            except (TypeError, ValueError):
                key = None
            if key in wanted_positions:
                by_position[key].append(row)
            for alias in _hyg_aliases(row) & wanted_names:
                by_name[alias].append(row)
    return by_position, by_name


def _choose_hyg_row(star, by_position, by_name):
    key = _position_key(star["x"], star["y"], star["z"])
    candidates = by_position.get(key, [])
    if len(candidates) == 1:
        return candidates[0], None
    name = _normal_name(star["name"])
    matching = [row for row in candidates if name in _hyg_aliases(row)]
    if len(matching) == 1:
        return matching[0], None
    if candidates:
        return None, "ambiguous_hyg_match"
    named = {row["id"]: row for row in by_name.get(name, [])}
    if len(named) == 1:
        return next(iter(named.values())), None
    return None, "no_hyg_match" if not named else "ambiguous_hyg_match"


def _tap_csv(query, timeout=300, maxrec=TAP_MAXREC, required_column="source_id"):
    params = urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "MAXREC": str(maxrec),
        "QUERY": query,
    }).encode("ascii")
    request = Request(TAP_SYNC, data=params, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "StarExplorer-Gaia-DR3-enrichment/1.0",
    })
    for attempt in range(5):
        try:
            with urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8-sig")
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise EnrichmentError(f"Gaia TAP request failed: {exc}") from exc
            try:
                delay = int(exc.headers.get("Retry-After", ""))
            except ValueError:
                delay = 0
            if delay <= 0:
                delay = min(120, 15 * (2 ** attempt))
            print(f"Gaia TAP is busy; retrying in {delay} seconds.", flush=True)
            time.sleep(delay)
        except (URLError, TimeoutError) as exc:
            raise EnrichmentError(f"Gaia TAP request failed: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or (required_column and required_column not in reader.fieldnames):
        raise EnrichmentError(f"Gaia TAP returned an unexpected response: {text[:300]}")
    rows = list(reader)
    if len(rows) >= maxrec:
        raise EnrichmentError("Gaia TAP result reached MAXREC; reduce the query size.")
    return rows


def _hipparcos_matches():
    rows = _tap_csv(HIPPARCOS_QUERY)
    matches = defaultdict(list)
    for row in rows:
        matches[row["original_ext_source_id"]].append(row)
    return matches


def _finite_number(value):
    if value is None or value == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _gaia_value(row, column):
    value = row.get(column)
    if column == "source_id":
        return value or None
    if column == "astrometric_params_solved":
        return int(value) if value else None
    return _finite_number(value)


def _gaia_record(row, method, separation_arcsec=None, hipparcos=None, candidate_count=1):
    record = {
        "source_id": _gaia_value(row, "source_id"),
        "match_method": method,
        "match_candidate_count": candidate_count,
    }
    if separation_arcsec is not None:
        record["match_separation_arcsec"] = round(separation_arcsec, 6)
    if hipparcos is not None:
        record["hipparcos2"] = {
            "number_of_neighbours": int(hipparcos["number_of_neighbours"]),
            "xm_flag": int(hipparcos["xm_flag"]),
            "angular_distance": _finite_number(hipparcos["angular_distance"]),
        }
    for column, name in GAIA_VALUE_NAMES.items():
        value = _gaia_value(row, column)
        if value is not None:
            record[name] = value
    return record


def _propagate_hyg_position(row):
    try:
        ra = math.radians(float(row["ra"]) * 15)
        dec = math.radians(float(row["dec"]))
        pmra = float(row["pmra"])
        pmdec = float(row["pmdec"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (ra, dec, pmra, pmdec)):
        return None

    cos_ra, sin_ra = math.cos(ra), math.sin(ra)
    cos_dec, sin_dec = math.cos(dec), math.sin(dec)
    position = (cos_dec * cos_ra, cos_dec * sin_ra, sin_dec)
    east = (-sin_ra, cos_ra, 0)
    north = (-sin_dec * cos_ra, -sin_dec * sin_ra, cos_dec)
    radians_per_mas = math.pi / (180 * 3600 * 1000)
    elapsed = GAIA_EPOCH - HYG_EPOCH
    moved = tuple(
        position[i] + elapsed * radians_per_mas * (pmra * east[i] + pmdec * north[i])
        for i in range(3)
    )
    norm = math.sqrt(sum(value * value for value in moved))
    x, y, z = (value / norm for value in moved)
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.asin(z))


def _angular_separation_arcsec(ra1, dec1, ra2, dec2):
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    sin_dec = math.sin((dec2 - dec1) / 2)
    sin_ra = math.sin((ra2 - ra1) / 2)
    haversine = sin_dec * sin_dec + math.cos(dec1) * math.cos(dec2) * sin_ra * sin_ra
    return math.degrees(2 * math.asin(min(1, math.sqrt(haversine)))) * 3600


def _coordinate_candidates(targets, radius_arcsec, batch_size):
    radius_deg = radius_arcsec / 3600
    batch_count = (len(targets) + batch_size - 1) // batch_size
    for start in range(0, len(targets), batch_size):
        batch = targets[start:start + batch_size]
        circles = [
            "1=CONTAINS(POINT('ICRS',g.ra,g.dec),"
            f"CIRCLE('ICRS',{target['ra_deg']:.10f},{target['dec_deg']:.10f},{radius_deg:.10f}))"
            for target in batch
        ]
        query = (
            f"SELECT {','.join('g.' + column for column in GAIA_COLUMNS)} "
            "FROM gaiadr3.gaia_source AS g WHERE " + " OR ".join(f"({circle})" for circle in circles)
        )
        rows = _tap_csv(query)
        candidates = defaultdict(dict)
        for row in rows:
            source_id = row["source_id"]
            ra, dec = _finite_number(row.get("ra")), _finite_number(row.get("dec"))
            if ra is None or dec is None:
                continue
            for target in batch:
                separation = _angular_separation_arcsec(
                    target["ra_deg"], target["dec_deg"], ra, dec
                )
                if separation <= radius_arcsec:
                    candidates[target["star_id"]][source_id] = (row, separation)
        for target in batch:
            yield target, list(candidates[target["star_id"]].values())
        batch_number = start // batch_size + 1
        if batch_number % 10 == 0 or batch_number == batch_count:
            print(f"  Gaia position matches checked: {min(start + batch_size, len(targets)):,} / {len(targets):,}",
                  flush=True)
        time.sleep(0.1)


def enrich_dataset(source, destination, report_path, radius_arcsec=2.0, batch_size=200):
    source, destination, report_path = Path(source), Path(destination), Path(report_path)
    if destination.exists() or report_path.exists():
        raise EnrichmentError("The destination database or match report already exists.")
    if not source.is_file():
        raise EnrichmentError(f"Source database does not exist: {source}")
    if radius_arcsec <= 0 or batch_size < 1:
        raise EnrichmentError("Match radius and coordinate batch size must be positive.")

    with closing(D.DatasetStore(source).connect()) as db:
        stars = [
            {"id": row[0], "name": row[1], "x": row[2], "y": row[3], "z": row[4],
             "extra": json.loads(row[5])}
            for row in db.execute("SELECT id,name,x,y,z,extra FROM stars ORDER BY ordinal")
        ]
    hyg_path = download_hyg()
    by_position, by_name = _read_hyg_rows(hyg_path, stars)
    hip_matches = _hipparcos_matches()
    print(f"Retrieved {sum(map(len, hip_matches.values())):,} Gaia/Hipparcos cross-matches.", flush=True)

    updates = {}
    extras_by_id = {star["id"]: star["extra"] for star in stars}
    report = []
    coordinate_targets = []
    used_gaia_ids = set()
    for star in stars:
        entry = {
            "star_name": star["name"],
            "hyg_id": "",
            "hip": "",
            "gaia_dr3_source_id": "",
            "match_method": "",
            "separation_arcsec": "",
            "candidate_count": "",
        }
        if star["name"] == "Sol":
            entry["status"] = "not_applicable"
            report.append(entry)
            continue
        hyg, hyg_error = _choose_hyg_row(star, by_position, by_name)
        if hyg is None:
            entry["status"] = hyg_error
            report.append(entry)
            continue
        entry["hyg_id"] = hyg.get("id", "")
        hip = hyg.get("hip", "").strip()
        entry["hip"] = hip
        possible = hip_matches.get(hip, []) if hip else []
        if len(possible) == 1 and possible[0]["number_of_neighbours"] == "1":
            match = possible[0]
            gaia_id = match["source_id"]
            if gaia_id not in used_gaia_ids:
                updates[star["id"]] = _gaia_record(match, "hipparcos2", hipparcos=match)
                used_gaia_ids.add(gaia_id)
                entry.update(status="matched", gaia_dr3_source_id=gaia_id,
                             match_method="hipparcos2", candidate_count="1")
                report.append(entry)
                continue
            entry["status"] = "duplicate_gaia_source"
        else:
            entry["status"] = (
                "ambiguous_hipparcos_match" if len(possible) > 1
                or (possible and possible[0]["number_of_neighbours"] != "1")
                else "no_hipparcos_match"
            )

        propagated = _propagate_hyg_position(hyg)
        if propagated is None:
            if not hip:
                entry["status"] = "missing_hyg_motion"
            report.append(entry)
            continue
        coordinate_targets.append({
            "star_id": star["id"],
            "ra_deg": propagated[0],
            "dec_deg": propagated[1],
            "report": entry,
        })
        report.append(entry)

    for target, candidates in _coordinate_candidates(coordinate_targets, radius_arcsec, batch_size):
        entry = target["report"]
        entry["candidate_count"] = str(len(candidates))
        if len(candidates) != 1:
            entry["status"] = "ambiguous_position_match" if candidates else "no_position_candidate"
            continue
        row, separation = candidates[0]
        gaia_id = row["source_id"]
        if gaia_id in used_gaia_ids:
            entry["status"] = "duplicate_gaia_source"
            continue
        updates[target["star_id"]] = _gaia_record(
            row, "position", separation_arcsec=separation, candidate_count=1
        )
        used_gaia_ids.add(gaia_id)
        entry.update(status="matched", gaia_dr3_source_id=gaia_id,
                     match_method="position", separation_arcsec=f"{separation:.6f}")

    counts = defaultdict(int)
    for entry in report:
        counts[entry["status"]] += 1
    temp_database = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temp_report = report_path.with_name(f".{report_path.name}.{uuid.uuid4().hex}.tmp")
    database_published = False
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        D.clone_dataset(source, temp_database, name=f"{source.stem} with Gaia DR3")
        with closing(sqlite3.connect(temp_database)) as db:
            for star_id, gaia in updates.items():
                extra = extras_by_id[star_id]
                extra["gaia_dr3"] = gaia
                db.execute("UPDATE stars SET extra=? WHERE id=?", (
                    json.dumps(extra, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                    star_id,
                ))
            metadata = {
                key: json.loads(value)
                for key, value in db.execute("SELECT key,value FROM metadata")
            }
            metadata["gaia_enrichment"] = {
                "release": "Gaia DR3",
                "table": "gaiadr3.gaia_source",
                "crossmatch_table": "gaiadr3.hipparcos2_best_neighbour",
                "coordinate_match_radius_arcsec": radius_arcsec,
                "coordinate_epoch": GAIA_EPOCH,
                "source_catalogue": "HYG Database v4.0",
                "unambiguous_gaia_matches": len(updates),
                "status_counts": dict(sorted(counts.items())),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute("DELETE FROM metadata")
            db.executemany(
                "INSERT INTO metadata VALUES (?,?)",
                ((key, D.dumps(value)) for key, value in metadata.items()),
            )
            db.commit()
        with temp_report.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=report[0].keys())
            writer.writeheader()
            writer.writerows(report)
        os.replace(temp_database, destination)
        database_published = True
        os.replace(temp_report, report_path)
    except BaseException:
        if database_published:
            destination.unlink(missing_ok=True)
        raise
    finally:
        temp_database.unlink(missing_ok=True)
        temp_report.unlink(missing_ok=True)
    return dict(sorted(counts.items())), len(stars), destination, report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", nargs="?", type=Path, default=ROOT / "data" / "stars.sqlite",
        help="source StarExplorer database (default: data/stars.sqlite)",
    )
    parser.add_argument(
        "destination", nargs="?", type=Path, default=ROOT / "data" / "stars-gaia-enriched.sqlite",
        help="new enriched database; must not already exist",
    )
    parser.add_argument("--report", type=Path, help="match report CSV path")
    parser.add_argument("--radius-arcsec", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    report_path = args.report or args.destination.with_suffix(".gaia-report.csv")
    try:
        counts, total, destination, report_path = enrich_dataset(
            args.source, args.destination, report_path, args.radius_arcsec, args.batch_size
        )
    except (D.DatasetError, EnrichmentError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Gaia enrichment failed: {exc}\n")
    print(f"Enriched {counts.get('matched', 0):,} of {total:,} stars.")
    print(f"Database: {destination}")
    print(f"Match report: {report_path}")
    for status, count in counts.items():
        print(f"  {status}: {count:,}")


if __name__ == "__main__":
    main()
