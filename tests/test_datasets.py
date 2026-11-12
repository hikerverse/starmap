import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import datasets as D
import app as application
from flask import Flask
from query_api import create_query_blueprint
import scenarios as C


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stars = [
            {"name": "Sol", "x": 0, "y": 0, "z": 0, "colour": "#ffffff",
             "spectral_class": "G2V", "abs_mag": 4.83},
            {"name": "Nearby", "x": 1, "y": 2, "z": 3, "colour": "#eeeeee",
             "spectral_class": "K2V", "abs_mag": None},
        ]
        self.write("stars.json", {"units": "parsec", "frame": "Equatorial (J2000)", "stars": self.stars})
        self.write("solar_system.json", C.read_json(Path(__file__).resolve().parents[1] / "data" / "solar_system.json"))
        self.write("known_planets.json", {"systems": {"Nearby": {"planets": []}}})
        baseline = C.snapshot(self.root, "baseline", seed=1)
        self.source = self.root / "scenarios" / "baseline" / f"{baseline['revision']}.sqlite"
        self.database = self.root / "dataset.sqlite"
        D.import_legacy_snapshot(self.source, self.root / "stars.json", self.database, "Test dataset")
        self.store = D.DatasetStore(self.database)

    def write(self, filename, value):
        (self.root / filename).write_text(json.dumps(value), encoding="utf-8")

    def test_normalized_rows_support_star_and_body_queries(self):
        with closing(self.store.connect()) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertTrue({"stars", "systems", "planets", "moons", "hosts", "star_positions"} <= tables)
            columns = {row[1] for row in db.execute("PRAGMA table_info(systems)")}
            self.assertNotIn("editable", columns)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM planets p JOIN stars s ON s.id=p.star_id WHERE s.name='Sol'"
            ).fetchone()[0], 8)
            self.assertGreater(db.execute(
                "SELECT count(*) FROM moons m JOIN planets p ON p.id=m.planet_id WHERE p.name='Earth'"
            ).fetchone()[0], 0)
            distance = db.execute(
                """SELECT sqrt((a.x-b.x)*(a.x-b.x)+(a.y-b.y)*(a.y-b.y)+(a.z-b.z)*(a.z-b.z))
                   FROM stars a JOIN stars b ON a.name='Sol' AND b.name='Nearby'"""
            ).fetchone()[0]
            self.assertAlmostEqual(distance, 14 ** 0.5)
            candidates = db.execute(
                """SELECT s.name FROM star_positions r JOIN stars s ON s.rowid=r.star_rowid
                   WHERE r.x_min BETWEEN -1 AND 1 AND r.y_min BETWEEN -1 AND 1"""
            ).fetchall()
            self.assertIn(("Sol",), candidates)

    def test_catalogue_and_system_are_read_from_normalized_database(self):
        catalogue = self.store.catalogue()
        self.assertEqual(catalogue["stars"], self.stars)
        summary = self.store.summary()
        self.assertEqual(summary["planets"][0], 8)
        self.assertEqual(summary["planets"][1], 0)
        self.assertEqual(summary["catalogue_fingerprint"], catalogue["catalogue_fingerprint"])
        with closing(C.connect(self.source)) as db:
            expected = json.loads(db.execute(
                "SELECT document FROM systems WHERE name='Sol'"
            ).fetchone()[0])
        actual = self.store.system("Sol")
        self.assertEqual(actual["id"], expected["id"])
        self.assertEqual(actual["name"], expected["name"])
        self.assertEqual(actual["planets"], expected["planets"])
        self.assertEqual(actual["star"], expected["star"])

    def test_catalogue_appends_distance_limited_gaia_stars_without_system_rows(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("""
                CREATE TABLE gaia_stars (
                    source_id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                    x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
                    colour TEXT NOT NULL, spectral_class TEXT NOT NULL,
                    abs_mag REAL NOT NULL, extra TEXT NOT NULL, distance_pc REAL NOT NULL
                )
            """)
            db.executemany(
                "INSERT INTO gaia_stars VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    ("gaia-near", "Gaia DR3 1", 1500, 0, 0, "#ffffff", "Other",
                     5.0, '{"distance_pc":1500}', 1500),
                    ("gaia-far", "Gaia DR3 2", 3000, 0, 0, "#ffffff", "Other",
                     7.0, '{"distance_pc":3000}', 3000),
                ],
            )
            db.commit()
        catalogue = self.store.catalogue(2000)
        self.assertEqual([star["name"] for star in catalogue["stars"]],
                         ["Sol", "Nearby", "Gaia DR3 1"])
        self.assertEqual(catalogue["system_star_count"], 2)
        self.assertEqual(catalogue["gaia_star_count"], 1)
        self.assertEqual(catalogue["load_radius_pc"], 2000)
        self.assertEqual(catalogue["catalogue_fingerprint"],
                         self.store.catalogue()["catalogue_fingerprint"])
        self.assertEqual(len(self.store.summary()["planets"]), 2)

    def test_create_builds_a_standalone_dataset_without_legacy_snapshot(self):
        created = self.root / "created.sqlite"
        D.create_dataset(self.root, created, "Generated", seed=1)
        store = D.DatasetStore(created)
        self.assertEqual(store.meta["name"], "Generated")
        self.assertEqual(store.meta["seed"], 1)
        self.assertEqual(store.catalogue()["stars"], self.store.catalogue()["stars"])
        self.assertEqual(store.system("Sol")["planets"], self.store.system("Sol")["planets"])

    def test_radius_remains_selectable_without_gaia_additions(self):
        catalogue = self.store.catalogue(5000)
        self.assertEqual(catalogue["load_radius_pc"], 5000)
        self.assertFalse(catalogue["gaia_available"])
        self.assertEqual(catalogue["gaia_star_count"], 0)

    def test_catalogue_source_and_radius_keep_summary_aligned(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE stars SET x=1500,y=0,z=0 WHERE name='Sol'")
            db.execute("""
                CREATE TABLE gaia_stars (
                    source_id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                    x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
                    colour TEXT NOT NULL, spectral_class TEXT NOT NULL,
                    abs_mag REAL NOT NULL, extra TEXT NOT NULL, distance_pc REAL NOT NULL
                )
            """)
            db.executemany("INSERT INTO gaia_stars VALUES (?,?,?,?,?,?,?,?,?,?)", [
                ("1", "Gaia DR3 1", 1000, 0, 0, "#ffffff", "Other", 5, "{}", 1000),
                ("2", "Gaia DR3 2", 2001, 0, 0, "#ffffff", "Other", 5, "{}", 2001),
            ])
            db.commit()
        expectations = {
            (1000, "both"): (["Nearby", "Gaia DR3 1"], [0]),
            (2000, "hyg"): (["Sol", "Nearby"], [8, 0]),
            (2000, "gaia"): (["Gaia DR3 1"], []),
            (5000, "both"): (["Sol", "Nearby", "Gaia DR3 1", "Gaia DR3 2"], [8, 0]),
        }
        for (radius, source), (names, counts) in expectations.items():
            with self.subTest(radius=radius, source=source):
                catalogue = self.store.catalogue(radius, source)
                summary = self.store.summary(radius, source)
                self.assertEqual([star["name"] for star in catalogue["stars"]], names)
                self.assertEqual(summary["planets"], counts)
                self.assertEqual(len(summary["flags"]), catalogue["system_star_count"])
                self.assertEqual(summary["catalogue_fingerprint"], catalogue["catalogue_fingerprint"])
                self.assertEqual(summary["names_crc"], catalogue["names_crc"])
        with self.assertRaises(D.DatasetError):
            self.store.catalogue(1000, "unknown")

    def test_gaia_selection_includes_crossmatched_hyg_stars_and_aligned_planets(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE stars SET extra=? WHERE name='Nearby'",
                       ('{"gaia_dr3":{"source_id":"123"}}',))
            db.execute("UPDATE stars SET extra=? WHERE name='Sol'",
                       ('{"gaia_dr3":{}}',))
            db.commit()
        catalogue = self.store.catalogue(1000, "gaia")
        summary = self.store.summary(1000, "gaia")
        self.assertEqual([star["name"] for star in catalogue["stars"]], ["Nearby"])
        self.assertEqual(summary["planets"], [0])
        self.assertEqual(summary["catalogue_fingerprint"], catalogue["catalogue_fingerprint"])
        self.assertEqual(summary["names_crc"], catalogue["names_crc"])
        self.assertEqual(len(self.store.catalogue(1000, "both")["stars"]), 2)

    def test_clone_is_independent_and_sql_coordinate_edits_update_api(self):
        clone_path = self.root / "clone.sqlite"
        D.clone_dataset(self.database, clone_path, "Clone")
        clone = D.DatasetStore(clone_path)
        self.assertNotEqual(clone.meta["dataset_id"], self.store.meta["dataset_id"])
        with closing(sqlite3.connect(clone_path)) as db:
            db.execute("UPDATE stars SET x=10 WHERE name='Nearby'")
            db.commit()
        updated = D.DatasetStore(clone_path)
        self.assertEqual(updated.catalogue()["stars"][1]["x"], 10)
        self.assertEqual(updated.system("Nearby")["dataset_name"], "Clone")
        self.assertEqual(self.store.catalogue()["stars"][1]["x"], 1)
        self.assertEqual(updated.summary()["catalogue_fingerprint"],
                         updated.catalogue()["catalogue_fingerprint"])

    def test_refresh_recalculates_summary_flags_after_planet_edits(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE planets SET provenance='manual' WHERE star_id=(SELECT id FROM stars WHERE name='Sol')")
            db.commit()
        self.store.refresh()
        summary = D.DatasetStore(self.database).summary()
        self.assertTrue(summary["flags"][0] & C.FLAG_MANUAL)

    def test_spatial_query_api(self):
        app = Flask(__name__)
        app.register_blueprint(create_query_blueprint(lambda: self.store))
        client = app.test_client()

        within = client.get("/api/query/stars/within?x=0&y=0&z=0&radius_pc=2")
        self.assertEqual(within.status_code, 200)
        self.assertEqual(within.json["units"], "parsec")
        self.assertEqual([star["name"] for star in within.json["stars"]], ["Sol"])
        self.assertEqual(within.json["total"], 1)

        boundary = client.get(
            "/api/query/stars/within?x=1&y=2&z=2&radius_pc=1&limit=1&offset=0"
        )
        self.assertEqual([star["name"] for star in boundary.json["stars"]], ["Nearby"])

        nearest = client.get("/api/query/stars/nearest?x=0&y=0&z=0&limit=2")
        self.assertEqual(nearest.status_code, 200)
        self.assertEqual(nearest.json["stars"][0]["name"], "Sol")
        self.assertIn("id", nearest.json["stars"][0])

        named = client.get("/api/query/stars/Nearby/within?radius_pc=4")
        self.assertEqual(named.status_code, 200)
        self.assertEqual(named.json["center"]["name"], "Nearby")
        self.assertEqual(named.json["total"], 2)

        distance = client.get("/api/query/distance?from=%20Sol%20&to=Nearby")
        self.assertEqual(distance.status_code, 200)
        self.assertAlmostEqual(distance.json["distance_pc"], 14 ** 0.5)
        self.assertEqual(client.get("/api/query/distance?from=Sol&to=Missing").status_code, 404)
        self.assertEqual(client.get("/api/query/stars/within?x=bad&y=0&z=0&radius_pc=2").status_code, 400)
        self.assertEqual(client.get("/api/query/stars/within?x=0&y=0&z=0&radius_pc=NaN").status_code, 400)
        self.assertEqual(client.get("/api/query/stars/nearest?x=0&y=0&z=0&limit=1001").status_code, 400)

    def test_spatial_query_api_is_registered_on_application(self):
        application._systems_state.clear()
        with patch.object(application, "DATASET_FILE", self.database):
            response = application.app.test_client().get(
                "/api/query/stars/within?x=0&y=0&z=0&radius_pc=2"
            )
        application._systems_state.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([star["name"] for star in response.json["stars"]], ["Sol"])

    def test_star_catalogue_api_validates_and_applies_startup_radius(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("""
                CREATE TABLE gaia_stars (
                    source_id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                    x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
                    colour TEXT NOT NULL, spectral_class TEXT NOT NULL,
                    abs_mag REAL NOT NULL, extra TEXT NOT NULL, distance_pc REAL NOT NULL
                )
            """)
            db.execute(
                "INSERT INTO gaia_stars VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("gaia-one", "Gaia DR3 1", 1500, 0, 0, "#ffffff", "Other",
                 5.0, '{"distance_pc":1500,"gaia_dr3":{"source_id":"1"}}', 1500),
            )
            db.commit()
        application._systems_state.clear()
        application._payload_cache.clear()
        with patch.object(application, "DATASET_FILE", self.database):
            client = application.app.test_client()
            response = client.get("/api/stars?max_distance_pc=2000")
            invalid = client.get("/api/stars?max_distance_pc=2001")
            hyg = client.get("/api/stars?max_distance_pc=2000&source=hyg")
            gaia = client.get("/api/stars?max_distance_pc=2000&source=gaia")
            empty_gaia = client.get("/api/stars?max_distance_pc=1000&source=gaia")
            gaia_summary = client.get("/api/systems-summary?max_distance_pc=2000&source=gaia")
            hyg_summary = client.get("/api/systems-summary?max_distance_pc=2000&source=hyg")
            compact = client.get("/api/stars?max_distance_pc=2000&source=gaia&compact=1")
            bad_source = client.get("/api/stars?source=other")
            bad_compact = client.get("/api/stars?compact=yes")
            bad_summary = client.get("/api/systems-summary?source=other")
            distinct_etag = client.get("/api/systems-summary?max_distance_pc=2000&source=hyg",
                                       headers={"If-None-Match": gaia_summary.headers["ETag"]})
        application._systems_state.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["load_radius_pc"], 2000)
        self.assertTrue(response.json["gaia_available"])
        self.assertEqual(response.json["system_star_count"], len(self.stars))
        self.assertEqual(response.json["gaia_star_count"], 1)
        self.assertIn("Gaia DR3 1", [star["name"] for star in response.json["stars"]])
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual([s["name"] for s in hyg.json["stars"]], ["Sol", "Nearby"])
        self.assertEqual([s["name"] for s in gaia.json["stars"]], ["Gaia DR3 1"])
        self.assertEqual(empty_gaia.json["stars"], [])
        self.assertEqual(gaia_summary.json["planets"], [])
        self.assertEqual(compact.json["stars"][0]["distance_pc"], 1500)
        self.assertNotIn("gaia_dr3", compact.json["stars"][0])
        self.assertEqual(gaia.json["stars"][0]["gaia_dr3"]["source_id"], "1")
        self.assertEqual(compact.json["catalogue_fingerprint"], gaia.json["catalogue_fingerprint"])
        self.assertEqual(gaia_summary.json["catalogue_fingerprint"], gaia.json["catalogue_fingerprint"])
        self.assertEqual(hyg_summary.json["planets"], [8, 0])
        self.assertEqual(distinct_etag.status_code, 200)
        self.assertEqual(bad_source.status_code, 400)
        self.assertEqual(bad_compact.status_code, 400)
        self.assertEqual(bad_summary.status_code, 400)


if __name__ == "__main__":
    unittest.main()
