import csv
import gzip
import json
import math
import sqlite3
import tempfile
import unittest
import zlib
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as application
import datasets as D
from stellar_motion import KM_S_TO_PC_YR, MAS_TO_RAD, gaia_measurement, motion_payload, velocity
from tools import import_stellar_motion as importer


class MotionMathTests(unittest.TestCase):
    @staticmethod
    def row(source_id="123", rv="20"):
        return dict(source_id=source_id, ra="0", dec="0", parallax="1000",
                    parallax_error="1", pmra="1000", pmdec="2000", pmra_error="1",
                    pmdec_error="2", radial_velocity=rv, radial_velocity_error="0.5")

    def test_cartesian_basis_and_units(self):
        x, y, z = velocity(0, 0, 1, 1000, 2000, 20)
        self.assertAlmostEqual(x, 20 * KM_S_TO_PC_YR)
        self.assertAlmostEqual(y, 1000 * MAS_TO_RAD)
        self.assertAlmostEqual(z, 2000 * MAS_TO_RAD)
        self.assertAlmostEqual(velocity(90, 0, 1, 0, 0, 20)[1], x)
        self.assertAlmostEqual(velocity(0, 90, 1, 0, 0, -20)[2], -x)

    def test_missing_and_genuinely_zero_gaia_radial_velocity(self):
        self.assertFalse(gaia_measurement(self.row(rv=""))["full"])
        zero = gaia_measurement(self.row(rv="0"))
        self.assertTrue(zero["full"])
        self.assertEqual(zero["rv"], 0)
        self.assertGreater(zero["sigma"], 0)
        self.assertIsNone(gaia_measurement({**self.row(), "parallax": "-1"}))
        self.assertIsNone(gaia_measurement({**self.row(), "pmra": ""}))
        missing_error = gaia_measurement({**self.row(), "pmra_error": ""})
        self.assertIsNone(missing_error["sigma"])

    def test_velocity_error_budget(self):
        m = gaia_measurement(self.row())
        expected = math.sqrt(MAS_TO_RAD**2 * 5 + (MAS_TO_RAD * math.hypot(1000, 2000) / 1000)**2
                             + (0.5 * KM_S_TO_PC_YR)**2)
        self.assertAlmostEqual(m["sigma"], expected)

    def test_truncated_archive_responses_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "query.csv"
            row = self.row()
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=row.keys())
                writer.writeheader()
                writer.writerow(row)
            path.with_suffix(".count.csv").write_text("n\n2\n", encoding="utf-8")
            with patch.object(importer, "download"), self.assertRaisesRegex(ValueError, "Truncated"):
                list(importer.query_csv("SELECT source_id FROM gaiadr3.gaia_source", path))


class MotionImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.sqlite"
        self.destination = self.root / "motion.sqlite"
        self.cache = self.root / "cache"
        self.cache.mkdir()
        db = D.create_database(self.source)
        for i, name in enumerate(("Sol", "Measured", "Fallback", "UnknownRV", "Missing")):
            extra = {"gaia_dr3": {"source_id": "123"}} if i == 1 else {}
            db.execute("INSERT INTO stars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (str(i), name, i, i, 0, 0, "#ffffff", "G2V", 5, 1, D.dumps(extra)))
        db.executescript("""CREATE TABLE gaia_stars(source_id TEXT,name TEXT,x REAL,y REAL,z REAL,
                            colour TEXT,spectral_class TEXT,abs_mag REAL,extra TEXT,distance_pc REAL);""")
        db.execute("INSERT INTO gaia_stars VALUES (?,?,?,?,?,?,?,?,?,?)",
                   ("456", "Gaia DR3 456", 1200, 0, 0, "#ffffff", "Other", 5,
                    D.dumps({"gaia_dr3": {"source_id": "456"}}), 1200))
        db.executemany("INSERT INTO metadata VALUES (?,?)", [
            (k, D.dumps(v)) for k, v in dict(schema_version=D.SCHEMA, dataset_id="test",
                name="Test", star_count=5, units="parsec", frame="Equatorial (J2000)").items()])
        db.commit()
        db.close()
        hyg_rows = []
        for i, name, rv in [(2, "Fallback", "12"), (3, "UnknownRV", "0")]:
            row = dict.fromkeys(("id", "proper", "gl", "con", "bayer", "flam", "hd", "hip", "hr",
                                 "x", "y", "z", "dist", "pmra", "pmdec", "rv", "ra", "dec"), "")
            row.update(id=str(i), proper=name, x=str(i), y="0", z="0", dist=str(i),
                       pmra="100", pmdec="200", rv=rv, ra="0", dec="0")
            hyg_rows.append(row)
        with gzip.open(self.cache / "hygdata_v40.csv.gz", "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=hyg_rows[0].keys())
            writer.writeheader()
            writer.writerows(hyg_rows)

    def build(self):
        with patch.object(importer, "query_csv", return_value=[
            MotionMathTests.row(), MotionMathTests.row("456", "")]), patch.object(importer, "download"):
            return importer.build_motion(self.source, self.destination, self.cache)

    def test_import_identity_fallback_missing_data_order_and_crc(self):
        counts = self.build()
        self.assertEqual(counts["complete"], 3)  # includes fixed Sol
        self.assertEqual(counts["partial"], 2)
        store = D.DatasetStore(self.source)
        for source in ("hyg", "gaia", "both"):
            for radius in (1000, 2000):
                result = motion_payload(store, self.destination, radius, source)
                names = [s["name"] for s in store.catalogue(radius, source)["stars"]]
                self.assertEqual(result["count"], len(names))
                self.assertEqual(result["names_crc"], zlib.crc32("\n".join(names).encode()))
        result = motion_payload(store, self.destination, 2000, "both")
        self.assertIsNone(result["measurements"][4])
        self.assertEqual(result["measurements"][2][7], 1)
        self.assertEqual(result["measurements"][3][3], 0)  # HYG zero does not prove a measured RV
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.build()

    def test_api_compression_validation_and_dataset_mismatch(self):
        self.build()
        application.stellar_motion_payload.cache_clear()
        with patch.object(application, "DATASET_FILE", self.source), patch.object(application, "MOTION_FILE", self.destination):
            client = application.app.test_client()
            response = client.get("/api/stellar-motion?source=hyg", headers={"Accept-Encoding": "gzip"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Content-Encoding"], "gzip")
            self.assertEqual(json.loads(gzip.decompress(response.data))["count"], 5)
            self.assertEqual(client.get("/api/stellar-motion?source=bad").status_code, 400)
            with closing(sqlite3.connect(self.destination)) as db:
                db.execute("UPDATE metadata SET value='\"wrong\"' WHERE key='dataset_id'")
                db.commit()
            application.stellar_motion_payload.cache_clear()
            self.assertEqual(client.get("/api/stellar-motion").status_code, 503)
        application.stellar_motion_payload.cache_clear()

    def test_curated_long_form_name_uses_explicit_hipparcos_identifier(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("UPDATE stars SET name='Epsilon Eridani' WHERE name='Missing'")
            db.commit()
        hyg = self.cache / "hygdata_v40.csv.gz"
        with gzip.open(hyg, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            list(reader)
        row = dict.fromkeys(fields, "")
        row.update(id="16496", hip="16537", proper="Ran", x="10", y="0", z="0",
                   dist="10", pmra="-976.44", pmdec="17.97", rv="16.9", ra="3.5", dec="-9")
        with gzip.open(hyg, "at", encoding="utf-8", newline="") as stream:
            csv.DictWriter(stream, fieldnames=fields).writerow(row)
        self.build()
        data = motion_payload(D.DatasetStore(self.source), self.destination, 1000, "hyg")
        self.assertEqual(data["measurements"][4][3], 1)
        self.assertEqual(data["measurements"][4][8], "16496")


if __name__ == "__main__":
    unittest.main()
