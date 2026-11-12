"""Import a capped, quality-filtered Gaia DR3 subset as stars without planetary systems."""

import argparse
import json
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

MAX_GAIA_STARS = D.MAX_GAIA_STARS
MIN_PARALLAX_MAS = 0.2
DEFAULT_MAX_G_MAG = 10.8
POSITION_MATCH_RADIUS_ARCSEC = 5.0
DEFAULT_SOURCE = ROOT / "data" / "stars-gaia-enriched.sqlite"
DEFAULT_DESTINATION = ROOT / "data" / "stars-gaia-expanded.sqlite"
NEARBY_SOURCE = DEFAULT_DESTINATION
NEARBY_DESTINATION = ROOT / "data" / "stars-gaia-nearby.sqlite"

COUNT_QUERY = """
SELECT COUNT(*) AS source_count
FROM gaiadr3.gaia_source
WHERE parallax >= 0.2 AND parallax < 1.0
  AND parallax_over_error >= 5
  AND ruwe < 1.4
  AND astrometric_params_solved IN (31, 95)
  AND phot_g_mean_mag <= {max_g_mag}
  AND ra IS NOT NULL AND dec IS NOT NULL
"""
SOURCE_QUERY = """
SELECT source_id,ra,dec,parallax,parallax_error,parallax_over_error,
       pmra,pmdec,phot_g_mean_mag,phot_bp_mean_mag,phot_rp_mean_mag,ruwe,
       astrometric_params_solved
FROM gaiadr3.gaia_source
WHERE parallax >= 0.2 AND parallax < 1.0
  AND parallax_over_error >= 5
  AND ruwe < 1.4
  AND astrometric_params_solved IN (31, 95)
  AND phot_g_mean_mag <= {max_g_mag}
  AND ra IS NOT NULL AND dec IS NOT NULL
ORDER BY phot_g_mean_mag,source_id
"""

COLOUR_STOPS = (
    (-0.5, (154, 178, 255)),
    (0.0, (204, 221, 255)),
    (0.8, (255, 239, 216)),
    (1.5, (255, 190, 130)),
    (3.0, (255, 112, 72)),
)


class GaiaImportError(ValueError):
    """Raised when Gaia rows cannot be safely added to a dataset."""


def _number(row, field):
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise GaiaImportError(f"Gaia row has an invalid {field}.") from exc
    if not math.isfinite(value):
        raise GaiaImportError(f"Gaia row has a non-finite {field}.")
    return value


def _display_colour(bp_rp):
    if bp_rp is None or not math.isfinite(bp_rp):
        return "#ffffff"
    value = max(COLOUR_STOPS[0][0], min(COLOUR_STOPS[-1][0], bp_rp))
    for (left_x, left), (right_x, right) in zip(COLOUR_STOPS, COLOUR_STOPS[1:]):
        if value <= right_x:
            portion = (value - left_x) / (right_x - left_x)
            channels = [round(a + (b - a) * portion) for a, b in zip(left, right)]
            return "#" + "".join(f"{channel:02x}" for channel in channels)
    return "#" + "".join(f"{channel:02x}" for channel in COLOUR_STOPS[-1][1])


def _j2000_position(ra, dec, pmra, pmdec):
    ra_rad, dec_rad = math.radians(ra), math.radians(dec)
    position = (
        math.cos(dec_rad) * math.cos(ra_rad),
        math.cos(dec_rad) * math.sin(ra_rad),
        math.sin(dec_rad),
    )
    east = (-math.sin(ra_rad), math.cos(ra_rad), 0)
    north = (
        -math.sin(dec_rad) * math.cos(ra_rad),
        -math.sin(dec_rad) * math.sin(ra_rad),
        math.cos(dec_rad),
    )
    radians_per_mas = math.pi / (180 * 3600 * 1000)
    moved = tuple(
        position[i] - 16 * radians_per_mas * (pmra * east[i] + pmdec * north[i])
        for i in range(3)
    )
    norm = math.sqrt(sum(value * value for value in moved))
    x, y, z = (value / norm for value in moved)
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.asin(z))


def _gaia_star(row):
    source_id = str(row.get("source_id", ""))
    if not source_id.isdigit():
        raise GaiaImportError("Gaia row has an invalid source_id.")
    ra, dec = _number(row, "ra"), _number(row, "dec")
    pmra = _number(row, "pmra")
    pmdec = _number(row, "pmdec")
    parallax = _number(row, "parallax")
    if parallax < MIN_PARALLAX_MAS:
        raise GaiaImportError(f"Gaia source {source_id} is beyond 5 kpc.")
    distance = 1000 / parallax
    position_ra, position_dec = _j2000_position(ra, dec, pmra, pmdec)
    ra_rad, dec_rad = math.radians(position_ra), math.radians(position_dec)
    g_mag = _number(row, "phot_g_mean_mag")
    bp_rp = None
    if row.get("phot_bp_mean_mag") not in (None, "") and row.get("phot_rp_mean_mag") not in (None, ""):
        bp_rp = _number(row, "phot_bp_mean_mag") - _number(row, "phot_rp_mean_mag")
    extras = {
        "source": "Gaia DR3",
        "distance_pc": distance,
        "ra_deg": position_ra,
        "dec_deg": position_dec,
        "gaia_dr3": {
            "source_id": source_id,
            "reference_epoch": 2016.0,
            "ra_deg": ra,
            "dec_deg": dec,
            "parallax_mas": parallax,
            "parallax_error_mas": _number(row, "parallax_error"),
            "parallax_over_error": _number(row, "parallax_over_error"),
            "phot_g_mean_mag": g_mag,
            "phot_bp_mean_mag": _number(row, "phot_bp_mean_mag") if bp_rp is not None else None,
            "phot_rp_mean_mag": _number(row, "phot_rp_mean_mag") if bp_rp is not None else None,
            "bp_rp": bp_rp,
            "ruwe": _number(row, "ruwe"),
            "astrometric_params_solved": int(row["astrometric_params_solved"]),
        },
    }
    extras["gaia_dr3"]["pmra"] = pmra
    extras["gaia_dr3"]["pmdec"] = pmdec
    return (
        source_id,
        f"Gaia DR3 {source_id}",
        distance * math.cos(dec_rad) * math.cos(ra_rad),
        distance * math.cos(dec_rad) * math.sin(ra_rad),
        distance * math.sin(dec_rad),
        _display_colour(bp_rp),
        "Other",
        g_mag + 5 * math.log10(parallax) - 10,
        D.dumps(extras),
        distance,
    )


def _existing_gaia_ids(db):
    result = set()
    for (text,) in db.execute("SELECT extra FROM stars"):
        record = json.loads(text).get("gaia_dr3", {})
        source_id = record.get("source_id")
        if source_id is not None:
            result.add(str(source_id))
    return result


def _unmatched_position_cells(db):
    radius = 2 * math.sin(math.radians(POSITION_MATCH_RADIUS_ARCSEC / 3600) / 2)
    cells = {}
    for x, y, z, text in db.execute("SELECT x,y,z,extra FROM stars"):
        if json.loads(text).get("gaia_dr3", {}).get("source_id") is not None:
            continue
        distance = math.sqrt(x * x + y * y + z * z)
        if distance == 0:
            continue
        vector = (x / distance, y / distance, z / distance)
        key = tuple(math.floor((value + 1) / radius) for value in vector)
        cells.setdefault(key, []).append(vector)
    return cells, radius


def _matches_unmatched_position(row, cells, radius):
    ra, dec = _j2000_position(_number(row, "ra"), _number(row, "dec"),
                              _number(row, "pmra"), _number(row, "pmdec"))
    ra_rad, dec_rad = math.radians(ra), math.radians(dec)
    vector = (
        math.cos(dec_rad) * math.cos(ra_rad),
        math.cos(dec_rad) * math.sin(ra_rad),
        math.sin(dec_rad),
    )
    cell = tuple(math.floor((value + 1) / radius) for value in vector)
    radius_squared = radius * radius
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for other in cells.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                    if sum((vector[i] - other[i]) ** 2 for i in range(3)) <= radius_squared:
                        return True
    return False


def _ensure_gaia_tables(db):
    db.executescript("""
        CREATE TABLE gaia_stars (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
            colour TEXT NOT NULL, spectral_class TEXT NOT NULL,
            abs_mag REAL NOT NULL, extra TEXT NOT NULL, distance_pc REAL NOT NULL
        );
        CREATE INDEX gaia_stars_distance ON gaia_stars(distance_pc);
        CREATE VIRTUAL TABLE gaia_star_positions USING rtree(
            star_rowid,x_min,x_max,y_min,y_max,z_min,z_max
        );
        CREATE TRIGGER gaia_stars_position_insert AFTER INSERT ON gaia_stars BEGIN
            INSERT INTO gaia_star_positions VALUES
                (new.rowid,new.x,new.x,new.y,new.y,new.z,new.z);
        END;
        CREATE TRIGGER gaia_stars_position_update AFTER UPDATE OF x,y,z ON gaia_stars BEGIN
            UPDATE gaia_star_positions SET x_min=new.x,x_max=new.x,y_min=new.y,y_max=new.y,
                z_min=new.z,z_max=new.z WHERE star_rowid=new.rowid;
        END;
        CREATE TRIGGER gaia_stars_position_delete AFTER DELETE ON gaia_stars BEGIN
            DELETE FROM gaia_star_positions WHERE star_rowid=old.rowid;
        END;
    """)


def import_gaia_stars(source, destination, max_g_mag=DEFAULT_MAX_G_MAG, nearby=False):
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise GaiaImportError(f"Source database does not exist: {source}")
    if destination.exists():
        raise GaiaImportError(f"Destination database already exists: {destination}")
    if not math.isfinite(max_g_mag) or not 5 <= max_g_mag <= 20:
        raise GaiaImportError("Maximum Gaia G magnitude must be between 5 and 20.")

    with closing(sqlite3.connect(source)) as db:
        has_gaia = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gaia_stars'"
        ).fetchone() is not None
        existing_count = db.execute("SELECT count(*) FROM gaia_stars").fetchone()[0] if has_gaia else 0
    if nearby != has_gaia:
        raise GaiaImportError("Nearby import requires an expanded database; a full import requires a database without Gaia additions.")
    parallax_clause = "parallax >= 1.0" if nearby else "parallax >= 0.2 AND parallax < 1.0"
    count_query = COUNT_QUERY.replace("parallax >= 0.2 AND parallax < 1.0", parallax_clause)
    source_query = SOURCE_QUERY.replace("parallax >= 0.2 AND parallax < 1.0", parallax_clause)
    count_rows = _tap_csv(
        count_query.format(max_g_mag=max_g_mag),
        maxrec=2,
        required_column="source_count",
    )
    if len(count_rows) != 1:
        raise GaiaImportError("Gaia TAP did not return a source count.")
    try:
        candidate_count = int(count_rows[0]["source_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GaiaImportError("Gaia TAP returned an invalid source count.") from exc
    if candidate_count + existing_count > MAX_GAIA_STARS:
        raise GaiaImportError(
            f"The selected cuts return {candidate_count:,} Gaia sources plus {existing_count:,} existing additions, above the safe "
            f"{MAX_GAIA_STARS:,}-star limit. Re-run with a brighter --max-g-mag value."
        )
    rows = _tap_csv(
        source_query.format(max_g_mag=max_g_mag),
        maxrec=MAX_GAIA_STARS + 1,
    )
    if len(rows) != candidate_count:
        raise GaiaImportError(
            f"Gaia count changed during download ({candidate_count:,} expected, {len(rows):,} received)."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        D.clone_dataset(source, temporary, name="Gaia DR3 expanded catalogue")
        with closing(sqlite3.connect(temporary)) as db:
            metadata = {
                key: json.loads(value)
                for key, value in db.execute("SELECT key,value FROM metadata")
            }
            if metadata.get("schema_version") != D.SCHEMA:
                raise GaiaImportError("Source database is not a supported StarExplorer dataset.")
            existing_ids = _existing_gaia_ids(db)
            if nearby:
                existing_ids.update(row[0] for row in db.execute("SELECT source_id FROM gaia_stars"))
            unmatched_positions, match_radius = _unmatched_position_cells(db)
            new_rows = []
            seen_ids = set()
            duplicate_ids = 0
            positional_matches = 0
            for row in rows:
                star = _gaia_star(row)
                source_id = star[0]
                if source_id in seen_ids:
                    raise GaiaImportError(f"Gaia TAP returned duplicate source_id {source_id}.")
                seen_ids.add(source_id)
                if source_id in existing_ids:
                    duplicate_ids += 1
                elif _matches_unmatched_position(row, unmatched_positions, match_radius):
                    positional_matches += 1
                else:
                    new_rows.append(star)
            if not nearby:
                _ensure_gaia_tables(db)
            db.executemany("INSERT INTO gaia_stars VALUES (?,?,?,?,?,?,?,?,?,?)", new_rows)
            metadata["gaia_nearby_import" if nearby else "gaia_star_import"] = {
                "release": "Gaia DR3",
                "table": "gaiadr3.gaia_source",
                "source_epoch": 2016.0,
                "distance_range_pc": [0, 1000] if nearby else [1000, 5000],
                "max_g_magnitude": max_g_mag,
                "minimum_parallax_over_error": 5,
                "maximum_ruwe": 1.4,
                "astrometric_solutions": [31, 95],
                "candidate_count": candidate_count,
                "duplicate_source_ids_excluded": duplicate_ids,
                "position_matches_excluded": positional_matches,
                "imported_count": len(new_rows),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute("DELETE FROM metadata")
            db.executemany(
                "INSERT INTO metadata VALUES (?,?)",
                ((key, D.dumps(value)) for key, value in metadata.items()),
            )
            db.commit()
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return candidate_count, len(new_rows), destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="source database to copy")
    parser.add_argument("--destination", type=Path, help="new database; must not already exist")
    parser.add_argument("--nearby", action="store_true",
                        help="add nearby Gaia sources to an existing expanded database")
    parser.add_argument("--max-g-mag", type=float, default=DEFAULT_MAX_G_MAG,
                        help="faintest Gaia G magnitude to import (default: 10.8)")
    args = parser.parse_args()
    try:
        candidates, imported, destination = import_gaia_stars(
            args.source or (NEARBY_SOURCE if args.nearby else DEFAULT_SOURCE),
            args.destination or (NEARBY_DESTINATION if args.nearby else DEFAULT_DESTINATION),
            args.max_g_mag, args.nearby,
        )
    except (D.DatasetError, GaiaImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Gaia star import failed: {exc}\n")
    print(f"Downloaded {candidates:,} candidates; imported {imported:,} new Gaia stars.")
    print(f"Database: {destination}")


if __name__ == "__main__":
    main()
