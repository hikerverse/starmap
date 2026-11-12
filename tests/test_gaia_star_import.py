import json
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import datasets as D
from tools import import_gaia_stars as G


class GaiaStarImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.sqlite"
        self.destination = self.root / "expanded.sqlite"
        db = D.create_database(self.source)
        db.execute(
            "INSERT INTO stars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("known", "Known", 0, 0, 0, 0, "#ffffff", "G2V", 5.0, 1,
             D.dumps({"gaia_dr3": {"source_id": "123"}})),
        )
        db.execute(
            "INSERT INTO stars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("unmatched", "Unmatched", 1, 1, 0, 0, "#ffffff", "G2V", 5.0, 1, "{}"),
        )
        db.executemany(
            "INSERT INTO metadata VALUES (?,?)",
            ((key, D.dumps(value)) for key, value in {
                "schema_version": D.SCHEMA, "dataset_id": "source",
                "name": "Source", "star_count": 2, "units": "parsec",
                "frame": "Equatorial (J2000)",
            }.items()),
        )
        db.commit()
        db.close()

    @staticmethod
    def row(source_id, ra=0, dec=0, parallax=0.5):
        return {
            "source_id": str(source_id), "ra": str(ra), "dec": str(dec),
            "parallax": str(parallax), "parallax_error": "0.05",
            "parallax_over_error": "10", "pmra": "0", "pmdec": "0",
            "phot_g_mean_mag": "12", "phot_bp_mean_mag": "12.5",
            "phot_rp_mean_mag": "11.5", "ruwe": "1.1",
            "astrometric_params_solved": "31",
        }

    def test_gaia_source_id_and_distance_are_preserved(self):
        star = G._gaia_star(self.row("4611734916632361600", ra=90, dec=30))
        self.assertEqual(star[0], "4611734916632361600")
        self.assertEqual(star[1], "Gaia DR3 4611734916632361600")
        self.assertAlmostEqual(star[9], 2000)
        self.assertAlmostEqual(star[2], 0, places=8)
        self.assertAlmostEqual(star[3], 2000 * (3 ** 0.5) / 2)
        self.assertEqual(json.loads(star[8])["gaia_dr3"]["reference_epoch"], 2016.0)

    def test_gaia_positions_are_propagated_to_the_catalogue_epoch(self):
        row = self.row("456", ra=90, dec=30)
        row["pmra"], row["pmdec"] = "1000", "0"
        star = G._gaia_star(row)
        extras = json.loads(star[8])
        self.assertAlmostEqual(extras["gaia_dr3"]["ra_deg"], 90)
        self.assertLess(extras["ra_deg"], 90)

    def test_nearby_star_and_parallax_boundary(self):
        self.assertAlmostEqual(G._gaia_star(self.row("456", parallax=2))[9], 500)
        self.assertAlmostEqual(G._gaia_star(self.row("456", parallax=1))[9], 1000)
        with self.assertRaises(G.GaiaImportError):
            G._gaia_star(self.row("456", parallax=0.19))

    def test_position_matching_uses_j2000_coordinates(self):
        row = self.row("456", ra=90)
        row["pmra"] = "1000"
        ra, dec = G._j2000_position(90, 0, 1000, 0)
        angle = math.radians(ra)
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("UPDATE stars SET x=?, y=?, z=0 WHERE name='Unmatched'",
                       (math.cos(angle), math.sin(angle)))
            cells, radius = G._unmatched_position_cells(db)
        self.assertTrue(G._matches_unmatched_position(row, cells, radius))

    def test_import_copies_database_and_excludes_already_matched_sources(self):
        rows = [self.row("123"), self.row("456", ra=45), self.row("789")]
        with patch.object(G, "_tap_csv", side_effect=[
            [{"source_count": "3"}], rows,
        ]):
            candidate_count, imported_count, destination = G.import_gaia_stars(
                self.source, self.destination
            )
        self.assertEqual((candidate_count, imported_count), (3, 1))
        self.assertTrue(destination.is_file())
        with closing(sqlite3.connect(self.source)) as source, \
                closing(sqlite3.connect(destination)) as expanded:
            self.assertIsNone(source.execute(
                "SELECT 1 FROM sqlite_master WHERE name='gaia_stars'"
            ).fetchone())
            self.assertEqual(expanded.execute("SELECT source_id FROM gaia_stars").fetchall(),
                             [("456",)])
            self.assertEqual(expanded.execute(
                "SELECT count(*) FROM gaia_star_positions"
            ).fetchone()[0], 1)
            self.assertEqual(json.loads(expanded.execute(
                "SELECT value FROM metadata WHERE key='gaia_star_import'"
            ).fetchone()[0])["duplicate_source_ids_excluded"], 1)
            self.assertEqual(json.loads(expanded.execute(
                "SELECT value FROM metadata WHERE key='gaia_star_import'"
            ).fetchone()[0])["position_matches_excluded"], 1)
        store = D.DatasetStore(destination)
        self.assertEqual(store.meta["name"], "Gaia DR3 expanded catalogue")
        self.assertNotEqual(store.meta["dataset_id"], "source")
        catalogue = store.catalogue(5000)
        self.assertEqual([star["name"] for star in catalogue["stars"]],
                         ["Known", "Unmatched", "Gaia DR3 456"])
        gaia = store.star_position("Gaia DR3 456")
        within = store.stars_within(gaia["x"], gaia["y"], gaia["z"], 0)
        self.assertEqual([star["name"] for star in within["stars"]], ["Gaia DR3 456"])
        self.assertEqual(store.nearest_stars(gaia["x"], gaia["y"], gaia["z"], 1)["stars"][0]["name"],
                         "Gaia DR3 456")
        self.assertGreater(store.distance_between("Known", "Gaia DR3 456")["distance_pc"], 1000)

    def test_import_refuses_a_too_large_result_before_downloading_rows(self):
        with patch.object(G, "_tap_csv", return_value=[
            {"source_count": str(G.MAX_GAIA_STARS + 1)},
        ]) as tap:
            with self.assertRaisesRegex(G.GaiaImportError, "safe 1,000,000-star limit"):
                G.import_gaia_stars(self.source, self.destination)
        self.assertEqual(tap.call_count, 1)
        self.assertFalse(self.destination.exists())

    def test_nearby_import_preserves_outer_stars_and_excludes_matches(self):
        rows = [self.row("123"), self.row("456", ra=45)]
        with patch.object(G, "_tap_csv", side_effect=[[{"source_count": "2"}], rows]):
            G.import_gaia_stars(self.source, self.destination)
        nearby_destination = self.root / "nearby.sqlite"
        near_rows = [self.row("123", parallax=2), self.row("789", ra=60, parallax=2),
                     self.row("999", parallax=2)]
        with patch.object(G, "_tap_csv", side_effect=[[{"source_count": "3"}], near_rows]) as tap:
            count, imported, _ = G.import_gaia_stars(self.destination, nearby_destination, nearby=True)
        self.assertEqual((count, imported), (3, 1))
        self.assertIn("parallax >= 1.0", tap.call_args_list[0].args[0])
        with closing(sqlite3.connect(nearby_destination)) as db:
            self.assertEqual(db.execute("SELECT source_id FROM gaia_stars ORDER BY source_id").fetchall(),
                             [("456",), ("789",)])
            self.assertEqual(db.execute("SELECT count(*) FROM gaia_star_positions").fetchone()[0], 2)
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            self.assertEqual(json.loads(metadata["gaia_nearby_import"])["distance_range_pc"], [0, 1000])
            self.assertIn("gaia_star_import", metadata)
        self.assertEqual(len(D.DatasetStore(nearby_destination).catalogue(1000, "gaia")["stars"]), 2)
        with closing(sqlite3.connect(self.destination)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM gaia_stars").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
