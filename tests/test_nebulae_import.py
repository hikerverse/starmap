import importlib.util
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import app

TOOLS = Path(__file__).resolve().parents[1] / "tools"
with patch.object(sys, "path", [str(TOOLS), *sys.path]):
    spec = importlib.util.spec_from_file_location("import_nebulae", TOOLS / "import_nebulae.py")
    importer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(importer)


class NebulaImportTests(unittest.TestCase):
    def test_resample_polyline_skips_duplicate_adjacent_points(self):
        points = [(0, 0, 0), (0, 0, 0), (10, 0, 0), (10, 0, 0)]

        self.assertEqual(
            importer.resample_polyline(points, 5),
            [(0, 0, 0), (5, 0, 0), (10, 0, 0)],
        )

    def test_radcliffe_wave_uses_published_best_fit_model(self):
        model = importer.load_radcliffe_model(importer.RADCLIFFE_MODEL_FILE)
        wave = importer.radcliffe_wave()

        self.assertEqual(wave["name"], "Radcliffe Wave")
        self.assertEqual(wave["nebula_type"], "dark")
        self.assertEqual(wave["source"], "Konietzka+ 2024")
        self.assertEqual(len(model), 1500)
        self.assertGreater(len(wave["puffs"]), 100)
        self.assertLess(len(wave["puffs"]), len(model))
        converted_start = importer.galactic_to_equatorial_xyz((-994.606, -930.436, 0.227))
        for actual, expected in zip(converted_start, (-405.355, 1282.566, -213.690)):
            self.assertAlmostEqual(actual, expected, places=3)
        for actual, expected in zip(wave["puffs"][0][:3], importer.galactic_to_equatorial_xyz(model[0])):
            self.assertAlmostEqual(actual, expected, places=2)
        for actual, expected in zip(wave["puffs"][-1][:3], importer.galactic_to_equatorial_xyz(model[-1])):
            self.assertAlmostEqual(actual, expected, places=2)
        sampled_length = sum(
            math.dist(a[:3], b[:3])
            for a, b in zip(wave["puffs"], wave["puffs"][1:])
        )
        self.assertGreater(sampled_length, 2900)
        self.assertIn("Published 3D best-fit centerline", wave["notes"])

    def test_bundled_nebulae_include_valid_radcliffe_wave(self):
        nebulae = app.load_nebulae()["nebulae"]
        wave = next(n for n in nebulae if n["name"] == "Radcliffe Wave")
        self.assertEqual(wave["source"], "Konietzka+ 2024")
        self.assertGreater(len(wave["puffs"]), 100)
        response = app.app.test_client().get("/api/nebulae")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            next(n for n in response.json["nebulae"] if n["name"] == "Radcliffe Wave"),
            wave,
        )


if __name__ == "__main__":
    unittest.main()
