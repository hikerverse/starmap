"""Add Gaia DR3 temperature-based spectral estimates to a copy of a dataset."""

import argparse
import math
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import datasets as D
from tools.enrich_gaia import _tap_csv

DEFAULT_SOURCE = ROOT / "data" / "stars-gaia-nearby.sqlite"
DEFAULT_DESTINATION = ROOT / "data" / "stars-gaia-temperatures.sqlite"
MAX_ROWS = D.MAX_GAIA_STARS

# Approximate broad main-sequence temperature bands, not luminosity classes.
BANDS = ((30000, "O"), (10000, "B"), (7500, "A"), (6000, "F"),
         (5200, "G"), (3700, "K"), (2400, "M"))


def spectral_band(temperature):
    for lower, name in BANDS:
        if temperature >= lower:
            return name
    return None


def temperature_record(row):
    try:
        source_id = str(row["source_id"])
        if not source_id.isdigit():
            raise ValueError("invalid source_id")
        values = [float(row[key]) for key in
                  ("teff_gspphot", "teff_gspphot_lower", "teff_gspphot_upper")]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Gaia returned an invalid temperature record.") from exc
    temperature, lower, upper = values
    if not all(math.isfinite(value) for value in values) or not 0 < lower <= temperature <= upper:
        raise ValueError(f"Gaia returned invalid temperature bounds for {source_id}.")
    band = spectral_band(temperature)
    if band != spectral_band(lower) or band != spectral_band(upper):
        band = None
    return source_id, temperature, lower, upper, band


def enrich_temperatures(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError(f"Destination database already exists: {destination}")
    store = D.DatasetStore(source)
    imports = [store.meta.get("gaia_star_import"), store.meta.get("gaia_nearby_import")]
    if not all(isinstance(item, dict) for item in imports):
        raise ValueError("Source must contain both the outer and nearby Gaia imports.")
    if any(item.get("release") != "Gaia DR3"
           or item.get("minimum_parallax_over_error") != 5
           or item.get("maximum_ruwe") != 1.4
           or item.get("astrometric_solutions") != [31, 95] for item in imports):
        raise ValueError("Source Gaia import criteria differ from the supported temperature query.")
    limits = [item.get("max_g_magnitude") for item in imports]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool)
           or not math.isfinite(value) or not 5 <= value <= 20 for value in limits):
        raise ValueError("Source Gaia import has an invalid magnitude limit.")
    magnitude = max(limits)
    selection = f"""FROM gaiadr3.gaia_source
        WHERE parallax >= 0.2 AND parallax_over_error >= 5 AND ruwe < 1.4
          AND astrometric_params_solved IN (31,95)
          AND phot_g_mean_mag <= {magnitude} AND ra IS NOT NULL AND dec IS NOT NULL
          AND teff_gspphot IS NOT NULL AND teff_gspphot_lower IS NOT NULL
          AND teff_gspphot_upper IS NOT NULL"""
    count_rows = _tap_csv("SELECT COUNT(*) AS source_count " + selection,
                          maxrec=2, required_column="source_count")
    if len(count_rows) != 1:
        raise ValueError("Gaia TAP did not return a temperature count.")
    count = int(count_rows[0]["source_count"])
    if count < 0 or count >= MAX_ROWS:
        raise ValueError(f"Gaia temperature count {count:,} exceeds the safe query limit.")
    print(f"Downloading {count:,} Gaia temperature estimates...", flush=True)
    rows = _tap_csv("SELECT source_id,teff_gspphot,teff_gspphot_lower,teff_gspphot_upper "
                    + selection, maxrec=MAX_ROWS + 1)
    if len(rows) != count:
        raise ValueError(f"Gaia temperature count changed: expected {count:,}, received {len(rows):,}.")

    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        D.clone_dataset(source, temporary, name="Gaia DR3 with temperature estimates")
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("CREATE TEMP TABLE gaia_temperature (source_id TEXT PRIMARY KEY, "
                       "temperature REAL, lower REAL, upper REAL, spectral_class TEXT)")
            db.executemany("INSERT INTO gaia_temperature VALUES (?,?,?,?,?)",
                           (temperature_record(row) for row in rows))
            del rows
            matched = db.execute(
                "SELECT count(*) FROM gaia_stars s JOIN gaia_temperature t ON t.source_id=s.source_id"
            ).fetchone()[0]
            estimated = db.execute(
                "SELECT count(*) FROM gaia_stars s JOIN gaia_temperature t ON t.source_id=s.source_id "
                "WHERE t.spectral_class IS NOT NULL"
            ).fetchone()[0]
            print(f"Applying {matched:,} matched temperatures ({estimated:,} unambiguous classes)...",
                  flush=True)
            db.execute("""
                UPDATE gaia_stars AS s SET
                    spectral_class = coalesce(t.spectral_class, 'Other'),
                    extra = json_set(s.extra,
                        '$.gaia_dr3.teff_gspphot', t.temperature,
                        '$.gaia_dr3.teff_gspphot_lower', t.lower,
                        '$.gaia_dr3.teff_gspphot_upper', t.upper,
                        '$.spectral_class_estimated', json(
                            CASE WHEN t.spectral_class IS NULL THEN 'false' ELSE 'true' END))
                FROM gaia_temperature AS t WHERE s.source_id = t.source_id
            """)
            metadata = {
                "release": "Gaia DR3", "table": "gaiadr3.gaia_source",
                "temperature": "teff_gspphot", "interval": "16th to 84th percentile",
                "classification": "approximate main-sequence temperature bands; both bounds must share a band",
                "candidate_count": count, "matched_count": matched, "estimated_count": estimated,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
                       ("gaia_temperature_import", D.dumps(metadata)))
            db.commit()
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return matched, estimated, destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    try:
        matched, estimated, destination = enrich_temperatures(args.source, args.destination)
    except (D.DatasetError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Gaia temperature import failed: {exc}\n")
    print(f"Imported {matched:,} temperatures and estimated {estimated:,} spectral classes.")
    print(f"Database: {destination}")


if __name__ == "__main__":
    main()
