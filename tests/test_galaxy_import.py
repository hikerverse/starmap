import csv
import importlib.util
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app

TOOLS = Path(__file__).resolve().parents[1] / "tools"
with patch.object(sys, "path", [str(TOOLS), *sys.path]):
    spec = importlib.util.spec_from_file_location("import_galaxies", TOOLS / "import_galaxies.py")
    importer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(importer)


class GalaxyImportTests(unittest.TestCase):
    def hi_row(self, identifier="J0100+10", velocity="7000"):
        return {"HIZOA": identifier, "RAJ2000": "01 00 00", "DEJ2000": "+10 00 00",
                "Dist": "90", "HRV": velocity, "e_HRV": "5", "logMHI": "9"}

    def counterpart(self, identifier="J0100+10", name="NGC 0001", classification="d"):
        return {"HIZOA": identifier, "OName": name, "Cl": classification,
                "RAJ2000": "01 00 00", "DEJ2000": "+10 00 00",
                "u_OName": "", "u_RAJ2000": "", "u_DEJ2000": ""}

    def existing_galaxy(self):
        return {"name": "NGC 1", "ids": "ESO 097-13", "galaxy_type": "spiral",
                "ra_deg": 15, "dec_deg": 10, "distance_pc": 100e6,
                "distance_ref": "Original literature distance", "abs_mag": -20,
                "catalogues": [{"name": "OpenNGC", "url": "https://github.com/mattiaverga/OpenNGC"}]}

    def test_crossmatch_identifier_normalization(self):
        self.assertEqual(importer.crossmatch_ids("ESO 097-G013"), importer.crossmatch_ids("ESO97-13"))
        self.assertEqual(importer.crossmatch_ids("NGC0001 2MASX J01000000+1000000"),
                         {"NGC1", "2MASXJ01000000+1000000"})

    def test_hizoa_alias_merge_preserves_existing_distance_and_photometry(self):
        for alias in ("NGC0001", "ESO 097-G013"):
            with self.subTest(alias=alias):
                entries = [self.existing_galaxy()]
                stats = importer.add_hizoa(entries, [self.hi_row()], [self.counterpart(name=alias)])
                self.assertEqual(stats, {"detections": 1, "crossmatched": 1, "added": 0})
                self.assertEqual(entries[0]["distance_pc"], 100e6)
                self.assertEqual(entries[0]["distance_ref"], "Original literature distance")
                self.assertEqual(entries[0]["abs_mag"], -20)
                self.assertEqual(entries[0]["hi_observations"][0]["distance_pc"], 90e6)
                self.assertIn("HIZOA J0100+10", entries[0]["ids"])
                self.assertEqual([c["name"] for c in entries[0]["catalogues"]], ["OpenNGC", "HIZOA-S"])

    def test_hizoa_spatial_match_requires_definite_counterpart_and_velocity(self):
        for classification, velocity, expected in [
            ("d", "7000", 1), ("p", "7000", 0), ("a", "7000", 0),
            ("c", "7000", 0), ("d", "10000", 0),
        ]:
            with self.subTest(classification=classification, velocity=velocity):
                entries = [self.existing_galaxy()]
                stats = importer.add_hizoa(entries, [self.hi_row(velocity=velocity)],
                                          [self.counterpart(name="" if classification == "d" else "NGC 1",
                                                            classification=classification)])
                self.assertEqual(stats["crossmatched"], expected)
                if not expected:
                    self.assertNotIn("abs_mag", entries[-1])
                    self.assertEqual(entries[-1]["spectral_class"], "Unknown")
                    self.assertNotIn("mass_msun", entries[-1])

    def test_hizoa_ambiguous_matches_stay_separate_and_duplicates_fail(self):
        entries = [self.existing_galaxy(), dict(self.existing_galaxy(), name="Other galaxy", ids="NGC 1")]
        stats = importer.add_hizoa(entries, [self.hi_row()], [self.counterpart()])
        self.assertEqual(stats["added"], 1)
        self.assertIn("Multiple possible", entries[-1]["hi_observations"][0]["crossmatch"])
        with self.assertRaisesRegex(ValueError, "Duplicate HIZOA"):
            importer.add_hizoa([], [self.hi_row(), self.hi_row()], [])
        with self.assertRaisesRegex(ValueError, "invalid HIZOA"):
            importer.add_hizoa([], [dict(self.hi_row(), Dist="nan")], [])

    def test_expansion_filters_duplicates_and_derives_visual_magnitude(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curated = root / "curated.csv"
            with importer.CSV_FILE.open(encoding="utf-8-sig", newline="") as stream:
                curated_fields = csv.DictReader(stream).fieldnames
            with curated.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=curated_fields)
                writer.writeheader()
                writer.writerow({"Name": "Andromeda", "IDs": "M31 NGC 224"})
            raw = root / "NGC.csv"
            fields = ["Name", "Type", "RA", "Dec", "Redshift", "NGC", "IC", "M",
                      "Hubble", "V-Mag", "MajAx", "Const", "Identifiers", "Common names", "OpenNGC notes"]
            base = dict.fromkeys(fields, "")
            base.update(Type="G", RA="01:00:00", Dec="+10:00:00", Redshift="0.01", Hubble="Sb")
            with raw.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
                writer.writeheader()
                for updates in [
                    {"Name": "NGC0224"},
                    {"Name": "NGC0001", "V-Mag": "12"},
                    {"Name": "IC0001", "NGC": "0001"},
                    {"Name": "NGC0002", "Redshift": "0.001"},
                    {"Name": "NGC0003", "Redshift": "0.1"},
                    {"Name": "NGC0004", "Type": "*"},
                    {"Name": "NGC0005", "Type": "GPair", "Hubble": ""},
                ]:
                    writer.writerow(dict(base, **updates))
            expansion = root / "expansion.csv"
            with patch.object(importer, "CSV_FILE", curated), patch.object(importer, "EXPANSION_FILE", expansion):
                importer.expand_opengnc(raw)
            with expansion.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["Name"] for r in rows], ["NGC 1", "NGC 5"])
            distance = 299792.458 * 0.01 / 70
            self.assertAlmostEqual(float(rows[0]["Distance (Mpc)"]), distance, places=5)
            self.assertAlmostEqual(float(rows[0]["Abs mag (V)"]),
                                   12 - 5 * math.log10(distance * 1e6) + 5, places=3)
            self.assertEqual(rows[1]["Abs mag (V)"], "")
            self.assertEqual(rows[1]["Galaxy type"], "interacting")

    def test_bundled_catalogue_is_valid_and_preserves_curated_objects(self):
        galaxies = app.load_galaxies()["galaxies"]
        self.assertEqual(len(galaxies), 10018)
        self.assertEqual(len({g["name"] for g in galaxies}), len(galaxies))
        self.assertTrue(all(math.isfinite(g["distance_pc"]) and g["distance_pc"] > 0 for g in galaxies))
        andromeda = next(g for g in galaxies if g["name"] == "Andromeda Galaxy")
        self.assertEqual(andromeda["distance_pc"], 761000)
        observations = [o for g in galaxies for o in g.get("hi_observations", [])]
        self.assertEqual(len(observations), 883)
        self.assertEqual(len({o["id"] for o in observations}), 883)
        self.assertTrue(all(g["catalogues"] for g in galaxies))
        circinus = next(g for g in galaxies if g["name"] == "Circinus Galaxy")
        self.assertEqual(circinus["distance_pc"], 4200000)
        self.assertEqual(circinus["hi_observations"][0]["id"], "HIZOA J1413-65")
        added = [g for g in galaxies if g["name"].startswith("HIZOA ")]
        self.assertEqual(len(added), 879)
        self.assertTrue(all("abs_mag" not in g and "mass_msun" not in g for g in added))
        # This survey specifically adds real objects close to the Galactic plane.
        north_ra, north_dec = map(math.radians, (192.85948, 27.12825))
        for galaxy in added:
            ra, dec = map(math.radians, (galaxy["ra_deg"], galaxy["dec_deg"]))
            sin_latitude = (math.sin(dec) * math.sin(north_dec)
                            + math.cos(dec) * math.cos(north_dec) * math.cos(ra - north_ra))
            self.assertLess(abs(math.degrees(math.asin(sin_latitude))), 6)
        self.assertFalse(any(g["name"] == "NGC 224" for g in galaxies))
        self.assertEqual(app.app.test_client().get("/api/galaxies").status_code, 200)
