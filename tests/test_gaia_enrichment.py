import csv
import gzip
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import datasets as D
from tools import enrich_gaia as G


class GaiaEnrichmentTests(unittest.TestCase):
    def test_tap_csv_accepts_the_count_query_column(self):
        with patch.object(G, "urlopen", return_value=io.BytesIO(b"source_count\n42\n")):
            rows = G._tap_csv(
                "SELECT COUNT(*) AS source_count",
                maxrec=2,
                required_column="source_count",
            )
        self.assertEqual(rows, [{"source_count": "42"}])

    def test_enrichment_writes_a_separate_database_and_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, destination, report_path = (
                root / "source.sqlite", root / "enriched.sqlite", root / "report.csv"
            )
            hyg_path = root / "hyg.csv.gz"
            db = D.create_database(source)
            try:
                db.execute(
                    "INSERT INTO stars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("star-id", "Test Star", 0, 1.0, 2.0, 3.0, "#ffffff", "G2V",
                     None, 0, "{}"),
                )
                db.executemany(
                    "INSERT INTO metadata VALUES (?,?)",
                    ((key, D.dumps(value)) for key, value in {
                        "schema_version": D.SCHEMA,
                        "dataset_id": "source-id",
                        "name": "Source",
                        "star_count": 1,
                        "units": "parsec",
                        "frame": "Equatorial (J2000)",
                    }.items()),
                )
                db.commit()
            finally:
                db.close()
            with gzip.open(hyg_path, "wt", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=(
                    "id", "hip", "hd", "hr", "gl", "proper", "ra", "dec",
                    "pmra", "pmdec", "bayer", "con", "flam", "x", "y", "z",
                ))
                writer.writeheader()
                writer.writerow({
                    "id": "1", "hip": "123", "proper": "Test Star", "ra": "1",
                    "dec": "2", "pmra": "0", "pmdec": "0", "x": "1", "y": "2", "z": "3",
                })
            crossmatch = {
                "original_ext_source_id": "123",
                "source_id": "4611734916632361600",
                "number_of_neighbours": "1",
                "xm_flag": "8",
                "angular_distance": "0.01",
                "ra": "15.0",
                "dec": "2.0",
                "parallax": "10",
                "parallax_error": "0.1",
                "pmra": "1",
                "pmra_error": "0.1",
                "pmdec": "2",
                "pmdec_error": "0.1",
                "phot_g_mean_mag": "5",
                "phot_bp_mean_mag": "5.2",
                "phot_rp_mean_mag": "4.8",
                "ruwe": "1.0",
                "astrometric_params_solved": "31",
            }
            with patch.object(G, "download_hyg", return_value=hyg_path), \
                    patch.object(G, "_hipparcos_matches", return_value={"123": [crossmatch]}):
                counts, total, _, _ = G.enrich_dataset(
                    source, destination, report_path, batch_size=1
                )
            enriched = D.DatasetStore(destination).catalogue()["stars"][0]
            original = D.DatasetStore(source).catalogue()["stars"][0]
            self.assertEqual((counts, total), ({"matched": 1}, 1))
            self.assertEqual(enriched["gaia_dr3"]["source_id"], "4611734916632361600")
            self.assertNotIn("gaia_dr3", original)
            with report_path.open(encoding="utf-8", newline="") as report:
                self.assertEqual(next(csv.DictReader(report))["status"], "matched")

    def test_gaia_epoch_propagation_preserves_zero_motion_coordinates(self):
        ra, dec = G._propagate_hyg_position({
            "ra": "6.0", "dec": "-25.0", "pmra": "0", "pmdec": "0",
        })
        self.assertAlmostEqual(ra, 90.0)
        self.assertAlmostEqual(dec, -25.0)

    def test_gaia_epoch_propagation_applies_proper_motion(self):
        ra, dec = G._propagate_hyg_position({
            "ra": "1.650199", "dec": "-17.949782", "pmra": "3312.95", "pmdec": "560.34",
        })
        self.assertAlmostEqual(ra, 24.768462, places=5)
        self.assertAlmostEqual(dec, -17.947291, places=5)

    def test_hyg_component_name_resolves_rounded_position_ambiguity(self):
        primary = {
            "id": "1", "hip": "32349", "hd": "48915", "hr": "2491",
            "gl": "Gl 244A", "proper": "Sirius",
            "bayer": "", "con": "", "flam": "",
        }
        companion = {
            "id": "2", "hip": "", "hd": "", "hr": "",
            "gl": "Gl 244B", "proper": "",
            "bayer": "", "con": "", "flam": "",
        }
        chosen, error = G._choose_hyg_row(
            {"name": "Sirius A", "x": 1, "y": 2, "z": 3},
            {(1.0, 2.0, 3.0): [primary, companion]},
            {},
        )
        self.assertIsNone(error)
        self.assertEqual(chosen["hip"], "32349")

    def test_gaia_source_id_remains_a_string(self):
        record = G._gaia_record({
            "source_id": "4611734916632361600",
            "ra": "73.0",
            "dec": "-89.0",
        }, "hipparcos2")
        self.assertEqual(record["source_id"], "4611734916632361600")
        self.assertIsInstance(record["source_id"], str)

    def test_angular_separation_is_reported_in_arcseconds(self):
        separation = G._angular_separation_arcsec(0, 0, 1 / 3600, 0)
        self.assertAlmostEqual(separation, 1.0, places=8)


if __name__ == "__main__":
    unittest.main()
