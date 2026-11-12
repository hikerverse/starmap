"""Complete, queryable SQLite datasets for StarExplorer."""

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import scenarios as C
import systems as S

SCHEMA = 1
MAX_GAIA_STARS = 1_000_000
STAR_COLUMNS = ("teff", "lum", "mass", "radius", "category", "spectral_class",
                "abs_mag", "source", "metallicity", "provenance")
PLANET_COLUMNS = (
    "id", "star_id", "ordinal", "name", "a_au", "e", "mass_mearth", "radius_rearth",
    "period_d", "period_source", "provenance", "source", "mass_estimated",
    "radius_estimated", "mass_kind", "disputed", "discovery", "year", "minor_moons", "notes",
)
MOON_COLUMNS = (
    "id", "planet_id", "ordinal", "name", "a_km", "mass_mearth", "radius_km",
    "period_d", "period_source", "provenance", "notes",
)


class DatasetError(ValueError):
    pass


class DatasetNotFound(DatasetError):
    pass


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def create_database(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE stars (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, ordinal INTEGER NOT NULL UNIQUE,
            x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL, colour TEXT NOT NULL,
            spectral_class TEXT NOT NULL, abs_mag REAL, abs_mag_present INTEGER NOT NULL,
            extra TEXT NOT NULL
        );
        CREATE TABLE systems (
            star_id TEXT PRIMARY KEY REFERENCES stars(id), name TEXT NOT NULL UNIQUE,
            seed INTEGER NOT NULL, teff REAL NOT NULL, lum REAL NOT NULL,
            mass REAL NOT NULL, radius REAL NOT NULL, category TEXT NOT NULL,
            spectral_class TEXT NOT NULL, abs_mag REAL, source TEXT NOT NULL,
            metallicity REAL, provenance TEXT NOT NULL, present TEXT NOT NULL, flags INTEGER NOT NULL
        );
        CREATE TABLE hosts (
            star_id TEXT NOT NULL REFERENCES systems(star_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL, host TEXT NOT NULL,
            PRIMARY KEY (star_id, ordinal)
        );
        CREATE TABLE planets (
            id TEXT PRIMARY KEY, star_id TEXT NOT NULL REFERENCES systems(star_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL, name TEXT NOT NULL, a_au REAL NOT NULL, e REAL NOT NULL,
            mass_mearth REAL NOT NULL, radius_rearth REAL NOT NULL, period_d REAL,
            period_source TEXT NOT NULL, provenance TEXT NOT NULL, source TEXT,
            mass_estimated INTEGER, radius_estimated INTEGER, mass_kind TEXT, disputed INTEGER,
            discovery TEXT, year INTEGER, minor_moons INTEGER NOT NULL, notes TEXT, present TEXT NOT NULL,
            UNIQUE (star_id, ordinal)
        );
        CREATE TABLE moons (
            id TEXT PRIMARY KEY, planet_id TEXT NOT NULL REFERENCES planets(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL, name TEXT NOT NULL, a_km REAL NOT NULL,
            mass_mearth REAL NOT NULL, radius_km REAL NOT NULL, period_d REAL,
            period_source TEXT NOT NULL, provenance TEXT NOT NULL, notes TEXT, present TEXT NOT NULL,
            UNIQUE (planet_id, ordinal)
        );
        CREATE INDEX stars_xyz ON stars(x, y, z);
        CREATE INDEX planets_star_id ON planets(star_id);
        CREATE INDEX moons_planet_id ON moons(planet_id);
        CREATE VIRTUAL TABLE star_positions USING rtree(star_rowid,x_min,x_max,y_min,y_max,z_min,z_max);
        CREATE TRIGGER stars_position_insert AFTER INSERT ON stars BEGIN
            INSERT INTO star_positions VALUES (new.rowid,new.x,new.x,new.y,new.y,new.z,new.z);
        END;
        CREATE TRIGGER stars_position_update AFTER UPDATE OF x,y,z ON stars BEGIN
            UPDATE star_positions SET x_min=new.x,x_max=new.x,y_min=new.y,y_max=new.y,
                z_min=new.z,z_max=new.z WHERE star_rowid=new.rowid;
        END;
        CREATE TRIGGER stars_position_delete AFTER DELETE ON stars BEGIN
            DELETE FROM star_positions WHERE star_rowid=old.rowid;
        END;
    """)
    return db


def _insert_system(db, star, ordinal, editable, seed, flags):
    extra = {key: value for key, value in star.items()
             if key not in {"name", "x", "y", "z", "colour", "spectral_class", "abs_mag"}}
    db.execute(
        "INSERT INTO stars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (editable["star_id"], star["name"], ordinal, star["x"], star["y"], star["z"],
         star["colour"], star["spectral_class"], star.get("abs_mag"), int("abs_mag" in star),
         dumps(extra)),
    )
    st = editable["star"]
    db.execute(
        "INSERT INTO systems VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (editable["star_id"], editable["name"], seed,
         *(st.get(key) for key in STAR_COLUMNS), dumps(list(st)), flags),
    )
    db.executemany("INSERT INTO hosts VALUES (?,?,?)",
                   ((editable["star_id"], i, host) for i, host in enumerate(editable["hosts"])))
    for i, planet in enumerate(editable["planets"]):
        db.execute(
            "INSERT INTO planets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (planet["id"], editable["star_id"], i)
            + tuple(planet.get(key) for key in PLANET_COLUMNS[3:])
            + (dumps([key for key in planet if key != "moons"]),),
        )
        for j, moon in enumerate(planet["moons"]):
            db.execute(
                "INSERT INTO moons VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (moon["id"], planet["id"], j, *(moon.get(key) for key in MOON_COLUMNS[3:]),
                 dumps(list(moon))),
            )


def import_legacy_snapshot(source, stars_path, destination, name=None):
    """Convert a scenario-era full snapshot into a standalone relational dataset."""
    source, stars_path, destination = Path(source), Path(stars_path), Path(destination)
    if not source.is_file():
        raise DatasetError(f"Legacy snapshot does not exist: {source}")
    if not stars_path.is_file():
        raise DatasetError(f"Star catalogue does not exist: {stars_path}")
    if destination.exists():
        raise DatasetError(f"Destination already exists: {destination}")
    catalogue = C.read_json(stars_path)
    stars = catalogue.get("stars")
    if not isinstance(stars, list):
        raise DatasetError("Star catalogue must contain a stars list.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old, \
                closing(create_database(temporary)) as db:
            rows = old.execute(
                "SELECT ordinal,document,editable,flags FROM systems ORDER BY ordinal"
            )
            count = 0
            for ordinal, document_text, editable_text, flags in rows:
                if ordinal >= len(stars):
                    raise DatasetError("Snapshot has more systems than the star catalogue.")
                star = stars[ordinal]
                document, editable = json.loads(document_text), json.loads(editable_text)
                if document["id"] != editable["star_id"]:
                    raise DatasetError(f"System at catalogue position {ordinal} has inconsistent IDs.")
                _insert_system(db, star, ordinal, editable, document["seed"], flags)
                count += 1
            if count != len(stars):
                raise DatasetError(f"Snapshot contains {count} systems; catalogue contains {len(stars)} stars.")
            metadata = {
                "schema_version": SCHEMA,
                "dataset_id": uuid.uuid4().hex,
                "name": name or destination.stem,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_snapshot": source.name,
                "star_count": count,
                "units": catalogue.get("units", "parsec"),
                "frame": catalogue.get("frame", "Equatorial (J2000)"),
            }
            db.executemany("INSERT INTO metadata VALUES (?,?)",
                           ((key, dumps(value)) for key, value in metadata.items()))
            db.commit()
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def create_dataset(data_dir, destination, name=None, seed=None):
    """Build a complete relational database directly from the catalogue and generator inputs."""
    data_dir, destination = Path(data_dir), Path(destination)
    if destination.exists():
        raise DatasetError(f"Destination already exists: {destination}")
    catalogue = C.read_json(data_dir / "stars.json")
    stars = catalogue.get("stars")
    if not isinstance(stars, list):
        raise DatasetError("Star catalogue must contain a stars list.")
    known, _ = S.load_known_systems(data_dir)
    if seed is None:
        legacy = data_dir / "systems_summary.json"
        seed = C.read_json(legacy).get("seed", S.DEFAULT_SEED) if legacy.exists() else S.DEFAULT_SEED
    inputs = ("stars.json", "known_planets.json", "solar_system.json")
    source_hashes = {
        filename: hashlib.sha256((data_dir / filename).read_bytes()).hexdigest()
        for filename in inputs if (data_dir / filename).exists()
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(create_database(temporary)) as db:
            for ordinal, star in enumerate(stars):
                document, editable = C.annotate_snapshot(
                    star, S.build_system(star, known.get(star["name"]), seed), known.get(star["name"])
                )
                _insert_system(db, star, ordinal, editable, seed, document["flags"])
                if (ordinal + 1) % 10000 == 0:
                    print(f"  Created {ordinal + 1:,} / {len(stars):,} systems", flush=True)
            for filename, digest in source_hashes.items():
                if hashlib.sha256((data_dir / filename).read_bytes()).hexdigest() != digest:
                    raise DatasetError("Input data changed during dataset creation; retry with stable inputs.")
            metadata = {
                "schema_version": SCHEMA,
                "dataset_id": uuid.uuid4().hex,
                "name": name or destination.stem,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "seed": seed,
                "generator_version": S.GENERATOR_VERSION,
                "generator_hash": hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest(),
                "sources": source_hashes,
                "star_count": len(stars),
                "units": catalogue.get("units", "parsec"),
                "frame": catalogue.get("frame", "Equatorial (J2000)"),
            }
            db.executemany("INSERT INTO metadata VALUES (?,?)",
                           ((key, dumps(value)) for key, value in metadata.items()))
            db.commit()
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def clone_dataset(source, destination, name=None):
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise DatasetError(f"Source dataset does not exist: {source}")
    if destination.exists():
        raise DatasetError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    try:
        with closing(sqlite3.connect(destination)) as db:
            metadata = dict((key, json.loads(value))
                            for key, value in db.execute("SELECT key,value FROM metadata"))
            if metadata.get("schema_version") != SCHEMA:
                raise DatasetError("Source database is not a supported StarExplorer dataset.")
            source_id = metadata["dataset_id"]
            metadata.update(
                dataset_id=uuid.uuid4().hex,
                name=name or destination.stem,
                cloned_from=source_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            db.execute("DELETE FROM metadata")
            db.executemany("INSERT INTO metadata VALUES (?,?)",
                           ((key, dumps(value)) for key, value in metadata.items()))
            db.commit()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


class DatasetStore:
    """Read-only runtime access to one complete SQLite dataset."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise DatasetError(f"Dataset database is missing: {self.path}")
        with closing(self.connect()) as db:
            self.meta = {key: json.loads(value) for key, value in
                         db.execute("SELECT key,value FROM metadata")}
        if self.meta.get("schema_version") != SCHEMA:
            raise DatasetError("Unsupported dataset schema.")

    def connect(self):
        uri = self.path.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _star_from_row(self, row):
        name, x, y, z, colour, spectral_class, abs_mag, abs_mag_present, extra, distance = row
        star = json.loads(extra)
        star.update(name=name, x=x, y=y, z=z, colour=colour, spectral_class=spectral_class)
        if abs_mag_present:
            star["abs_mag"] = abs_mag
        else:
            star.pop("abs_mag", None)
        if distance is not None:
            star["distance_pc"] = distance
        return star

    def _query_star_from_row(self, row):
        identifier, *fields = row
        star = self._star_from_row(fields)
        star["id"] = identifier
        return star

    def _star_select(self):
        return """SELECT s.id,s.name,s.x,s.y,s.z,s.colour,s.spectral_class,s.abs_mag,
                         s.abs_mag_present,s.extra"""

    def star_position(self, name):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT id,name,x,y,z FROM stars WHERE name=? OR id=?", (name, name)
            ).fetchone()
            if row is None and self._has_gaia_stars(db):
                row = db.execute(
                    "SELECT source_id,name,x,y,z FROM gaia_stars WHERE name=? OR source_id=?",
                    (name, name),
                ).fetchone()
        if row is None:
            raise DatasetNotFound(f"No star named or identified as '{name}'.")
        return dict(zip(("id", "name", "x", "y", "z"), row))

    @staticmethod
    def _has_gaia_stars(db):
        return db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gaia_stars'"
        ).fetchone() is not None

    def _query_meta(self):
        return {"dataset_id": self.meta["dataset_id"], "units": self.meta["units"],
                "frame": self.meta["frame"]}

    def stars_within(self, x, y, z, radius, limit=100, offset=0):
        def branch(table, positions, identifier, abs_mag_present):
            return f"""SELECT s.{identifier} AS id,s.name,s.x,s.y,s.z,s.colour,
                              s.spectral_class,s.abs_mag,{abs_mag_present} AS abs_mag_present,
                              s.extra
                       FROM {positions} r JOIN {table} s ON s.rowid=r.star_rowid
                       WHERE r.x_min <= ? AND r.x_max >= ?
                         AND r.y_min <= ? AND r.y_max >= ?
                         AND r.z_min <= ? AND r.z_max >= ?
                         AND sqrt((s.x-?)*(s.x-?)+(s.y-?)*(s.y-?)+(s.z-?)*(s.z-?)) <= ?"""
        distance = "sqrt((x-?)*(x-?)+(y-?)*(y-?)+(z-?)*(z-?))"
        bounds = (x + radius, x - radius, y + radius, y - radius, z + radius, z - radius)
        exact = (x, x, y, y, z, z, radius)
        with closing(self.connect()) as db:
            branches = [branch("stars", "star_positions", "id", "s.abs_mag_present")]
            if self._has_gaia_stars(db):
                branches.append(branch("gaia_stars", "gaia_star_positions", "source_id", "1"))
            union = " UNION ALL ".join(branches)
            count = db.execute(
                f"SELECT count(*) FROM ({union})",
                (bounds + exact) * len(branches),
            ).fetchone()[0]
            rows = db.execute(
                f"""SELECT *,{distance} AS distance_pc FROM ({union})
                    ORDER BY distance_pc,name LIMIT ? OFFSET ?""",
                (x, x, y, y, z, z) + (bounds + exact) * len(branches) + (limit, offset),
            )
            stars = []
            for row in rows:
                identifier = row[0]
                star = self._star_from_row((*row[1:10], row[10]))
                star["id"] = identifier
                stars.append(star)
        return dict(self._query_meta(), center={"x": x, "y": y, "z": z},
                    radius_pc=radius, total=count, limit=limit, offset=offset, stars=stars)

    def nearest_stars(self, x, y, z, limit=25, max_radius=None):
        def branch(table, positions, identifier, abs_mag_present):
            if max_radius is None:
                where = ""
                params = ()
            else:
                where = """WHERE r.x_min <= ? AND r.x_max >= ?
                                 AND r.y_min <= ? AND r.y_max >= ?
                                 AND r.z_min <= ? AND r.z_max >= ?
                                 AND sqrt((s.x-?)*(s.x-?)+(s.y-?)*(s.y-?)+(s.z-?)*(s.z-?)) <= ?"""
                params = (x + max_radius, x - max_radius, y + max_radius, y - max_radius,
                          z + max_radius, z - max_radius, x, x, y, y, z, z, max_radius)
            return (
                f"""SELECT s.{identifier} AS id,s.name,s.x,s.y,s.z,s.colour,
                           s.spectral_class,s.abs_mag,{abs_mag_present} AS abs_mag_present,
                           s.extra FROM {positions} r JOIN {table} s ON s.rowid=r.star_rowid
                     {where}""",
                params,
            )
        with closing(self.connect()) as db:
            sources = [("stars", "star_positions", "id", "s.abs_mag_present")]
            if self._has_gaia_stars(db):
                sources.append(("gaia_stars", "gaia_star_positions", "source_id", "1"))
            branches = [branch(*source) for source in sources]
            union = " UNION ALL ".join(sql for sql, _ in branches)
            distance = "sqrt((x-?)*(x-?)+(y-?)*(y-?)+(z-?)*(z-?))"
            params = tuple(value for _, values in branches for value in values)
            rows = db.execute(
                f"""SELECT *,{distance} AS distance_pc FROM ({union})
                    ORDER BY distance_pc,name LIMIT ?""",
                (x, x, y, y, z, z) + params + (limit,),
            )
            stars = []
            for row in rows:
                identifier = row[0]
                star = self._star_from_row((*row[1:10], None))
                star["id"] = identifier
                star["distance_pc"] = row[10]
                stars.append(star)
        return dict(self._query_meta(), center={"x": x, "y": y, "z": z},
                    max_radius_pc=max_radius, limit=limit, stars=stars)

    def distance_between(self, first, second):
        with closing(self.connect()) as db:
            def find(value):
                row = db.execute(
                    """SELECT id,name,x,y,z,colour,spectral_class,abs_mag,abs_mag_present,extra
                       FROM stars WHERE name=? OR id=?""", (value, value)
                ).fetchone()
                if row is None and self._has_gaia_stars(db):
                    row = db.execute(
                        """SELECT source_id,name,x,y,z,colour,spectral_class,abs_mag,1,extra
                           FROM gaia_stars WHERE name=? OR source_id=?""", (value, value)
                    ).fetchone()
                if row is None:
                    raise DatasetNotFound(f"No star named or identified as '{value}'.")
                identifier, *fields = row
                star = self._star_from_row((*fields, None))
                star["id"] = identifier
                return star

            left, right = find(first), find(second)
        distance = ((left["x"] - right["x"]) ** 2 + (left["y"] - right["y"]) ** 2
                    + (left["z"] - right["z"]) ** 2) ** 0.5
        return dict(self._query_meta(), distance_pc=distance, stars=[left, right])

    def _catalogue_system_stars(self, db, max_distance_pc, source):
        if source not in {"both", "hyg", "gaia"}:
            raise DatasetError("Catalogue source must be both, hyg, or gaia.")
        stars, ordinals = [], []
        for row in db.execute(
            """SELECT ordinal,name,x,y,z,colour,spectral_class,abs_mag,abs_mag_present,extra
               FROM stars WHERE x*x+y*y+z*z <= ? ORDER BY ordinal""",
            (max_distance_pc * max_distance_pc,),
        ):
            if source == "gaia" and not json.loads(row[-1]).get("gaia_dr3", {}).get("source_id"):
                continue
            ordinals.append(row[0])
            stars.append(self._star_from_row((*row[1:], None)))
        return stars, ordinals

    def catalogue(self, max_distance_pc=1000, source="both", compact=False):
        with closing(self.connect()) as db:
            system_stars, _ = self._catalogue_system_stars(db, max_distance_pc, source)
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='gaia_stars'"
            )}
            gaia_stars = []
            gaia_available = bool(tables)
            if tables and source != "hyg":
                gaia_count = db.execute(
                    "SELECT count(*) FROM gaia_stars WHERE distance_pc <= ?",
                    (max_distance_pc,),
                ).fetchone()[0]
                if gaia_count > MAX_GAIA_STARS:
                    raise DatasetError(
                        f"Requested radius contains {gaia_count:,} Gaia stars, above the "
                        f"{MAX_GAIA_STARS:,}-star safety limit."
                    )
                for row in db.execute(
                    """SELECT name,x,y,z,colour,spectral_class,abs_mag,1,extra,distance_pc
                       FROM gaia_stars WHERE distance_pc <= ? ORDER BY distance_pc,source_id""",
                    (max_distance_pc,),
                ):
                    if compact:
                        name, x, y, z, colour, spectral_class, abs_mag, _, extra, distance = row
                        star = {"name": name, "x": x, "y": y, "z": z, "colour": colour,
                                "spectral_class": spectral_class, "abs_mag": abs_mag,
                                "distance_pc": distance}
                        if spectral_class != "Other" and json.loads(extra).get("spectral_class_estimated") is True:
                            star["spectral_class_estimated"] = True
                        gaia_stars.append(star)
                    else:
                        gaia_stars.append(self._star_from_row(row))
        stars = system_stars + gaia_stars
        return {
            "units": self.meta["units"],
            "frame": self.meta["frame"],
            "stars": stars,
            "dataset_id": self.meta["dataset_id"],
            "dataset_name": self.meta["name"],
            "system_star_count": len(system_stars),
            "gaia_star_count": len(gaia_stars),
            "gaia_available": gaia_available,
            "gaia_nearby_available": "gaia_nearby_import" in self.meta,
            "load_radius_pc": max_distance_pc,
            "source": source,
            "catalogue_fingerprint": C.fingerprint(system_stars),
            "names_crc": S.names_crc(system_stars),
        }

    def summary(self, max_distance_pc=1000, source="both"):
        counts = [0] * self.meta["star_count"]
        flags = [0] * self.meta["star_count"]
        with closing(self.connect()) as db:
            system_stars, ordinals = self._catalogue_system_stars(db, max_distance_pc, source)
            for ordinal, flag, count in db.execute(
                """SELECT s.ordinal,coalesce(y.flags,0),count(p.id)
                   FROM stars s LEFT JOIN systems y ON y.star_id=s.id
                   LEFT JOIN planets p ON p.star_id=s.id GROUP BY s.id ORDER BY s.ordinal"""
            ):
                flags[ordinal], counts[ordinal] = flag, count
        return {
            "dataset_id": self.meta["dataset_id"],
            "name": self.meta["name"],
            "catalogue_fingerprint": C.fingerprint(system_stars),
            "names_crc": S.names_crc(system_stars),
            "planets": [counts[ordinal] for ordinal in ordinals],
            "flags": [flags[ordinal] for ordinal in ordinals],
        }

    def _system(self, db, name):
        row = db.execute(
            """SELECT y.star_id,y.name,y.seed,y.teff,y.lum,y.mass,y.radius,y.category,
                      y.spectral_class,y.abs_mag,y.source,y.metallicity,y.provenance,y.present
               FROM systems y JOIN stars s ON s.id=y.star_id
               WHERE y.star_id=? OR y.name=? OR s.name=?""",
            (name, name, name),
        ).fetchone()
        if row is None:
            raise DatasetNotFound(f"No system named '{name}'.")
        star_id, display_name, seed, *star_values, star_present = row
        star = dict(zip(STAR_COLUMNS, star_values))
        star = {key: value for key, value in star.items() if key in json.loads(star_present)}
        hosts = [host for (host,) in db.execute(
            "SELECT host FROM hosts WHERE star_id=? ORDER BY ordinal", (star_id,)
        )]
        planets = []
        for planet_row in db.execute(
            "SELECT " + ",".join(PLANET_COLUMNS) + ",present FROM planets WHERE star_id=? ORDER BY ordinal",
            (star_id,),
        ):
            planet = dict(zip(PLANET_COLUMNS, planet_row[:-1]))
            planet.pop("star_id")
            planet.pop("ordinal")
            planet = {key: value for key, value in planet.items() if key in json.loads(planet_row[-1])}
            for key in ("mass_estimated", "radius_estimated", "disputed"):
                if key in planet and planet[key] is not None:
                    planet[key] = bool(planet[key])
            planet["moons"] = []
            for moon_row in db.execute(
                "SELECT " + ",".join(MOON_COLUMNS) + ",present FROM moons WHERE planet_id=? ORDER BY ordinal",
                (planet["id"],),
            ):
                moon = dict(zip(MOON_COLUMNS, moon_row[:-1]))
                moon.pop("planet_id")
                moon.pop("ordinal")
                moon = {key: value for key, value in moon.items() if key in json.loads(moon_row[-1])}
                planet["moons"].append(moon)
            planets.append(planet)
        editable = {
            "schema_version": C.SCHEMA,
            "star_id": star_id,
            "name": display_name,
            "star": star,
            "hosts": hosts,
            "planets": planets,
        }
        document = C.derive_system(editable, seed)
        for planet in document["planets"]:
            if not planet["moons_simulated"]:
                planet.pop("moons_simulated")
        if (star["provenance"] == "manual"
                or any(p["provenance"] == "manual" or any(m["provenance"] == "manual" for m in p["moons"])
                       for p in planets)):
            document["flags"] |= C.FLAG_MANUAL
            document["provenance"] = "manual"
        document.update(dataset_id=self.meta["dataset_id"], dataset_name=self.meta["name"])
        return document

    def system(self, name):
        with closing(self.connect()) as db:
            return self._system(db, name)

    def refresh(self):
        """Recalculate stored flags from relational inputs after direct SQL edits."""
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            ids = [row[0] for row in db.execute("SELECT star_id FROM systems")]
            for star_id in ids:
                document = self._system(db, star_id)
                db.execute("UPDATE systems SET flags=? WHERE star_id=?", (document["flags"], star_id))
            db.commit()
