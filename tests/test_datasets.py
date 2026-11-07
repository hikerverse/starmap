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

    def test_create_builds_a_standalone_dataset_without_legacy_snapshot(self):
        created = self.root / "created.sqlite"
        D.create_dataset(self.root, created, "Generated", seed=1)
        store = D.DatasetStore(created)
        self.assertEqual(store.meta["name"], "Generated")
        self.assertEqual(store.meta["seed"], 1)
        self.assertEqual(store.catalogue()["stars"], self.store.catalogue()["stars"])
        self.assertEqual(store.system("Sol")["planets"], self.store.system("Sol")["planets"])

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


if __name__ == "__main__":
    unittest.main()
