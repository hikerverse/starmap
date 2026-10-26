import copy
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import scenarios as C
import systems as S


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.stars = [
            {"name": "Sol", "x": 0, "y": 0, "z": 0, "colour": "#ffffff",
             "spectral_class": "G2V", "abs_mag": 4.83},
            {"name": "Test Star", "x": 1, "y": 2, "z": 3, "colour": "#ffffff",
             "spectral_class": "K2V", "abs_mag": 6.3},
            {"name": "Empty Star", "x": 4, "y": 5, "z": 6, "colour": "#ffffff",
             "spectral_class": "G2V", "abs_mag": 4.83},
        ]
        self.write("stars.json", {"stars": self.stars})
        self.write("solar_system.json", C.read_json(Path(__file__).resolve().parents[1] / "data" / "solar_system.json"))
        self.write("known_planets.json", {"systems": {"Empty Star": {"planets": []}}})
        self.base = C.snapshot(self.data, "baseline", seed=1)
        self.edit = C.create_scenario(self.data, "edited", "baseline", "Edited")
        self.store = C.Store(self.data, self.stars)

    def write(self, filename, value):
        (self.data / filename).write_text(json.dumps(value), encoding="utf-8")

    def override(self, name="Sol"):
        path = C.export_system(self.data, "edited", name)
        return path, C.read_json(path)

    def publish(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")
        return C.publish(self.data, "edited")

    def test_full_snapshot_preserves_generator_and_precision(self):
        known, _ = S.load_known_systems(self.data)
        expected = S.build_system(self.stars[0], known["Sol"], 1)
        actual = self.store.system(self.base, "Sol")
        for p, q in zip(actual["planets"], expected["planets"]):
            self.assertEqual(p["a_au"], q["a_au"])
            self.assertEqual(p["period_d"], q["period_d"])
            self.assertEqual(len(p["moons"]), len(q["moons"]))
            for m, n in zip(p["moons"], q["moons"]):
                self.assertEqual(m["period_d"], n["period_d"])
        self.assertEqual(self.store.system(self.base, "Empty Star")["planets"], [])
        self.assertIn("generator_hash", self.base)
        self.assertIn("solar_system.json", self.base["sources"])

    def test_sparse_fallback_and_unchanged_export(self):
        self.assertEqual(self.store.system(self.base, "Sol")["planets"],
                         self.store.system(self.edit, "Sol")["planets"])
        path, value = self.override()
        published = self.publish(path, value)
        self.assertEqual(self.store.system(published, "Sol")["planets"],
                         self.store.system(self.base, "Sol")["planets"])
        with closing(C.connect(self.data / "scenarios" / "edited" / f"{published['revision']}.sqlite")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM systems").fetchone()[0], 0)

    def test_edited_observed_orbit_downgraded_and_rederived(self):
        path, value = self.override()
        earth = value["planets"][2]
        identity = earth["id"]
        earth["a_au"] = 3
        published = self.publish(path, value)
        output = self.store.system(published, "Sol")
        changed = next(p for p in output["planets"] if p["id"] == identity)
        self.assertEqual(changed["provenance"], "manual")
        self.assertEqual(changed["source"], "manual")
        self.assertFalse(changed["habitable"])
        self.assertAlmostEqual(changed["period_d"], S.orbital_period_days(3, 1, 1))
        self.assertTrue(output["flags"] & C.FLAG_MANUAL)
        self.assertFalse(output["confirmed"])
        baseline_earth = self.store.system(self.base, "Sol")["planets"][2]
        self.assertEqual(baseline_earth["a_au"], 1)

    def test_add_planet_and_moon_and_empty_system(self):
        path, value = self.override("Empty Star")
        value["planets"] = [{
            "id": "planet-new", "name": "New World", "a_au": 1, "e": 0,
            "mass_mearth": 1, "radius_rearth": 1, "period_source": "derived",
            "provenance": "manual", "source": "manual", "minor_moons": 0,
            "moons": [{"id": "moon-new", "name": "New Moon", "a_km": 384400,
                       "radius_km": 1737, "mass_mearth": 0.0123,
                       "period_source": "derived", "provenance": "manual"}],
        }]
        first = self.publish(path, value)
        output = self.store.system(first, "Empty Star")
        self.assertEqual(len(output["planets"][0]["moons"]), 1)
        self.assertGreater(output["planets"][0]["moons"][0]["period_d"], 0)
        self.assertTrue(output["flags"] & S.FLAG_HABITABLE)
        self.assertFalse(output["flags"] & S.FLAG_CONFIRMED)
        summary = self.store.summary(first)
        self.assertEqual(summary["planets"][2], 1)
        self.assertEqual(summary["flags"][2], output["flags"])
        value["planets"] = []
        second = self.publish(path, value)
        self.assertEqual(self.store.system(second, "Empty Star")["planets"], [])
        self.assertEqual(self.store.system(self.store.resolve("edited", first["revision"]), "Empty Star"), output)

    def test_moon_edits_recalculate_without_claiming_observed(self):
        path, value = self.override()
        earth = value["planets"][2]
        earth["moons"][0]["a_km"] *= 2
        result = self.store.system(self.publish(path, value), "Sol")
        planet = next(p for p in result["planets"] if p["name"] == "Earth")
        self.assertEqual(planet["provenance"], "observed")
        self.assertEqual(planet["moons"][0]["provenance"], "manual")
        self.assertGreater(planet["moons"][0]["period_d"], 27.32)
        self.assertTrue(result["flags"] & C.FLAG_MANUAL)

    def test_stellar_override_and_rename_keep_ids(self):
        path, value = self.override()
        value["name"] = "Our Sun"
        value["star"]["lum"] = 0.1
        first = self.publish(path, value)
        system = self.store.system(first, "Sol")
        self.assertEqual(system["name"], "Our Sun")
        self.assertEqual(system["id"], value["star_id"])
        self.assertEqual(system["star"]["lum"], 0.1)
        self.assertEqual(system["star"]["provenance"], "manual")
        self.assertEqual(self.store.system(first, "Our Sun")["id"], system["id"])

    def test_validation_failures_leave_published_pointer(self):
        path, original = self.override()
        cases = []
        for field, val in [("e", 1), ("a_au", -1), ("mass_mearth", True), ("radius_rearth", float("inf"))]:
            doc = copy.deepcopy(original)
            doc["planets"][0][field] = val
            cases.append(doc)
        doc = copy.deepcopy(original)
        del doc["planets"][0]["moons"]
        cases.append(doc)
        doc = copy.deepcopy(original)
        doc["planets"][1]["id"] = doc["planets"][0]["id"]
        cases.append(doc)
        doc = copy.deepcopy(original)
        doc["planets"][0]["teq_k"] = 100
        cases.append(doc)
        for doc in cases:
            with self.assertRaises(ValueError):
                self.publish(path, doc)
            self.assertEqual(self.store.resolve("edited")["revision"], self.edit["revision"])

    def test_new_object_cannot_claim_confirmation(self):
        path, value = self.override()
        item = copy.deepcopy(value["planets"][0])
        item["id"] = "invented-observed"
        item["name"] = "Invented"
        value["planets"].append(item)
        output = self.store.system(self.publish(path, value), "Sol")
        added = next(p for p in output["planets"] if p["id"] == "invented-observed")
        self.assertEqual(added["provenance"], "manual")

    def test_bad_revision_and_catalogue(self):
        with self.assertRaises(C.ScenarioError) as ctx:
            self.store.resolve("edited", "unknown")
        self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(C.ScenarioError):
            self.store.resolve("../baseline")
        changed = copy.deepcopy(self.stars)
        changed[0]["abs_mag"] += 1
        with self.assertRaises(C.ScenarioError) as ctx:
            C.Store(self.data, changed).resolve("edited")
        self.assertEqual(ctx.exception.status, 409)

    def test_no_runtime_generation_or_writes(self):
        before = {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
                  for p in (self.data / "scenarios").rglob("*") if p.is_file()}
        with patch.object(S, "build_system", side_effect=AssertionError("Runtime generation")):
            self.store.list()
            self.store.summary(self.edit)
            self.store.system(self.edit, "Test Star")
        after = {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
                 for p in (self.data / "scenarios").rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_baseline_immutable_and_export_not_overwritten(self):
        with self.assertRaises(C.ScenarioError):
            C.snapshot(self.data, "baseline")
        with self.assertRaises(C.ScenarioError):
            C.publish(self.data, "baseline")
        self.override()
        with self.assertRaises(C.ScenarioError):
            self.override()

    def test_duplicate_override_and_cross_system_ids_rejected(self):
        path, value = self.override()
        duplicate = path.with_name("duplicate.json")
        duplicate.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(C.ScenarioError):
            C.publish(self.data, "edited")
        duplicate.unlink()
        other = self.store.system(self.base, "Test Star", editable=True)
        value["planets"][0]["id"] = other["star_id"]
        with self.assertRaises(C.ScenarioError):
            self.publish(path, value)

    def test_removed_override_inherits_baseline_again(self):
        path, value = self.override()
        value["planets"] = []
        first = self.publish(path, value)
        self.assertEqual(self.store.system(first, "Sol")["planets"], [])
        path.unlink()
        second = C.publish(self.data, "edited")
        self.assertEqual(len(self.store.system(second, "Sol")["planets"]), 8)

    def test_failed_pointer_publication_preserves_previous_revision(self):
        path, value = self.override()
        value["planets"] = []
        folder = self.data / "scenarios" / "edited"
        before = set(folder.glob("*.sqlite"))
        path.write_text(json.dumps(value), encoding="utf-8")
        with patch.object(C, "atomic_json", side_effect=OSError("Publication interrupted")):
            with self.assertRaises(OSError):
                C.publish(self.data, "edited")
        self.assertEqual(set(folder.glob("*.sqlite")), before)
        self.assertEqual(self.store.resolve("edited")["revision"], self.edit["revision"])
        self.assertFalse((self.data / "scenarios" / ".publish.lock").exists())

    def test_missing_snapshot_and_default_switch(self):
        empty = self.data / "empty"
        with self.assertRaises(C.ScenarioError) as ctx:
            C.Store(empty, self.stars).list()
        self.assertEqual(ctx.exception.status, 503)
        C.set_default(self.data, "edited")
        self.assertEqual(self.store.resolve()["scenario_id"], "edited")

    def test_changed_generator_and_observations_do_not_change_snapshots(self):
        expected = self.store.system(self.edit, "Sol")
        (self.data / "solar_system.json").unlink()
        with patch.object(S, "build_system", side_effect=AssertionError("Must stay frozen")):
            self.assertEqual(self.store.system(self.store.resolve("edited"), "Sol"), expected)

    def test_wsgi_contract_and_conditional_get(self):
        import app
        with patch.object(app, "DATA_DIR", self.data), patch.object(app, "STARS_FILE", self.data / "stars.json"):
            client = app.app.test_client()
            catalogue = client.get("/api/stars")
            self.assertEqual(catalogue.json["catalogue_fingerprint"], C.fingerprint(self.stars))
            listing = client.get("/api/scenarios")
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json["names_crc"], S.names_crc(self.stars))
            url = f"/api/systems-summary?scenario=edited&revision={self.edit['revision']}"
            summary = client.get(url)
            self.assertEqual(summary.status_code, 200)
            self.assertEqual(summary.json["revision"], self.edit["revision"])
            self.assertEqual(client.get(url, headers={"If-None-Match": summary.headers["ETag"]}).status_code, 304)
            system = client.get(f"/api/system/Sol?scenario=edited&revision={self.edit['revision']}")
            self.assertEqual(system.json["scenario_id"], "edited")
            self.assertEqual(client.get("/api/system/unknown?scenario=edited").status_code, 404)
            self.assertEqual(client.get("/api/systems-summary?scenario=edited&revision=missing").status_code, 409)
            app._systems_state.clear()
            app.scenario_summary_payload.cache_clear()

    def test_purge_preview_and_cleanup_preserve_current_data(self):
        path, value = self.override()
        value["planets"] = []
        latest = self.publish(path, value)
        root = self.data / "scenarios"
        old = root / "edited" / f"{self.edit['revision']}.sqlite"
        current = root / "edited" / f"{latest['revision']}.sqlite"
        baseline = root / "baseline" / f"{self.base['revision']}.sqlite"
        preview = C.purge(self.data, dry_run=True)
        self.assertEqual(preview["files"], [str(old)])
        self.assertEqual(preview["bytes"], old.stat().st_size)
        self.assertTrue(old.exists())
        result = C.purge(self.data)
        self.assertEqual(result["file_count"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(current.exists())
        self.assertTrue(baseline.exists())
        self.assertTrue(path.exists())
        self.assertEqual(self.store.system(self.store.resolve("edited"), "Sol")["planets"], [])
        self.assertEqual(C.purge(self.data)["file_count"], 0)

    def test_purge_aborts_before_deleting_for_invalid_manifest(self):
        latest = C.publish(self.data, "edited")
        old = self.data / "scenarios" / "edited" / f"{self.edit['revision']}.sqlite"
        manifest = self.data / "scenarios" / "edited" / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        with self.assertRaises(C.ScenarioError):
            C.purge(self.data)
        self.assertTrue(old.exists())
        self.assertTrue((manifest.parent / f"{latest['revision']}.sqlite").exists())

    def test_purge_aborts_for_missing_dependency_and_respects_lock(self):
        C.publish(self.data, "edited")
        root = self.data / "scenarios"
        old = root / "edited" / f"{self.edit['revision']}.sqlite"
        with C.publication_lock(root):
            with self.assertRaises(C.ScenarioError):
                C.purge(self.data)
        (root / "baseline" / f"{self.base['revision']}.sqlite").unlink()
        with self.assertRaises(C.ScenarioError):
            C.purge(self.data)
        self.assertTrue(old.exists())

    def test_purge_keeps_unpublished_scenario_pinned_baseline_revision(self):
        root = self.data / "scenarios"
        alternate = root / "baseline" / "pinned-old.sqlite"
        alternate.write_bytes(b"dependency sentinel")
        folder = root / "draft"
        folder.mkdir()
        C.atomic_json(folder / "manifest.json", {
            "schema_version": C.SCHEMA, "id": "draft", "kind": "scenario",
            "baseline_id": "baseline", "baseline_revision": "pinned-old",
        })
        C.purge(self.data)
        self.assertTrue(alternate.exists())


if __name__ == "__main__":
    unittest.main()
