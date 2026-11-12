import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import datasets as D
from tools import estimate_gaia_spectral as E
from tools.import_gaia_stars import _ensure_gaia_tables


class GaiaSpectralTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.sqlite"
        self.destination = Path(self.temp.name) / "output.sqlite"
        db = D.create_database(self.source)
        _ensure_gaia_tables(db)
        db.execute("INSERT INTO stars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("sol", "Sol", 0, 0, 0, 0, "#ffffff", "G2V", 4.83, 1, "{}"))
        db.executemany("INSERT INTO gaia_stars VALUES (?,?,?,?,?,?,?,?,?,?)", [
            ("1", "Gaia DR3 1", 1, 0, 0, "#ffffff", "Other", 5, '{"gaia_dr3":{}}', 1),
            ("2", "Gaia DR3 2", 2, 0, 0, "#ffffff", "Other", 5, '{"gaia_dr3":{}}', 2),
            ("3", "Gaia DR3 3", 3, 0, 0, "#ffffff", "Other", 5, '{"gaia_dr3":{}}', 3),
        ])
        provenance = {"release": "Gaia DR3", "minimum_parallax_over_error": 5,
                      "maximum_ruwe": 1.4, "astrometric_solutions": [31, 95],
                      "max_g_magnitude": 10.8}
        meta = {"schema_version": D.SCHEMA, "dataset_id": "original", "name": "Original",
                "star_count": 1, "units": "parsec", "frame": "Equatorial (J2000)",
                "gaia_star_import": provenance, "gaia_nearby_import": provenance}
        db.executemany("INSERT INTO metadata VALUES (?,?)",
                       ((key, D.dumps(value)) for key, value in meta.items()))
        db.commit()
        db.close()

    @staticmethod
    def row(source, median, lower, upper):
        return {"source_id": source, "teff_gspphot": str(median),
                "teff_gspphot_lower": str(lower), "teff_gspphot_upper": str(upper)}

    def test_temperature_ranges_and_uncertain_boundary(self):
        for value, expected in [(30000, "O"), (10000, "B"), (7500, "A"), (6000, "F"),
                                (5200, "G"), (3700, "K"), (2400, "M"), (2399, None)]:
            with self.subTest(value=value):
                self.assertEqual(E.spectral_band(value), expected)
        self.assertEqual(E.temperature_record(self.row("1", 5800, 5700, 5900))[-1], "G")
        self.assertIsNone(E.temperature_record(self.row("1", 5900, 5800, 6100))[-1])
        for row in [self.row("1", 5800, 6000, 6100), self.row("1", "nan", 5000, 6000)]:
            with self.assertRaises(ValueError):
                E.temperature_record(row)

    def test_enrichment_preserves_source_and_estimated_provenance(self):
        records = [self.row("1", 5800, 5700, 5900), self.row("2", 5900, 5800, 6100),
                   self.row("999", 5800, 5700, 5900)]
        with patch.object(E, "_tap_csv", side_effect=[[{"source_count": "3"}], records]):
            matched, estimated, output = E.enrich_temperatures(self.source, self.destination)
        self.assertEqual((matched, estimated), (2, 1))
        with closing(sqlite3.connect(self.source)) as db:
            self.assertEqual(db.execute("SELECT spectral_class FROM gaia_stars WHERE source_id='1'").fetchone()[0],
                             "Other")
        store = D.DatasetStore(output)
        full = store.catalogue(1000, "gaia")
        compact = store.catalogue(1000, "gaia", compact=True)
        self.assertEqual([s["spectral_class"] for s in full["stars"]], ["G", "Other", "Other"])
        self.assertTrue(full["stars"][0]["spectral_class_estimated"])
        self.assertEqual(full["stars"][0]["gaia_dr3"]["teff_gspphot"], 5800)
        self.assertFalse(full["stars"][1]["spectral_class_estimated"])
        self.assertTrue(compact["stars"][0]["spectral_class_estimated"])
        self.assertNotIn("spectral_class_estimated", compact["stars"][1])
        self.assertNotIn("gaia_dr3", compact["stars"][0])
        self.assertEqual(store.meta["gaia_temperature_import"]["matched_count"], 2)

    def test_failed_or_truncated_download_does_not_publish(self):
        with patch.object(E, "_tap_csv", side_effect=[[{"source_count": "2"}], []]):
            with self.assertRaisesRegex(ValueError, "count changed"):
                E.enrich_temperatures(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
