"""Manifest invariants, not a substitute for BL-11/BL-14 engine and loader checks."""

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from patient_memory.domain import SourceInput  # noqa: E402
from scripts.prepare_baseline_storylines import FEATURES, OUTPUT, build_storylines  # noqa: E402


class StorylineInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.residents = cls.fixture["residents"]

    def test_reproducible_synthetic_cohort(self):
        self.assertEqual(self.fixture, build_storylines())
        self.assertEqual(len(self.residents), 12)
        self.assertEqual(len({r["id"] for r in self.residents}), 12)
        for resident in self.residents:
            self.assertTrue(resident["synthetic"])
            self.assertTrue(resident["id"].startswith("synthetic-"))
            self.assertEqual(len(resident["checks"]), 30)
            for day, check in enumerate(resident["checks"], 1):
                self.assertEqual(check["day"], day)
                self.assertTrue(check["synthetic"])
                self.assertTrue(check["usable"])
                self.assertFalse(check["is_baseline"])
                self.assertEqual(check["device_id"], "unit-tablet-1")
                self.assertEqual(check["prompt_version"], "count20-days-v1")
                self.assertEqual(set(check["features"]), set(FEATURES))
                self.assertTrue(0 < check["features"]["pause_ratio"] < 1)
                if day > 1:
                    previous = datetime.fromisoformat(resident["checks"][day - 2]["ts"])
                    self.assertEqual(datetime.fromisoformat(check["ts"]) - previous,
                                     timedelta(days=1))

    def test_sources_obey_ingestion_contract_and_precede_assessment(self):
        ids = set()
        for resident in self.residents:
            assessment = datetime.fromisoformat(resident["expected_assessment"]["as_of"])
            for payload in resident["sources"]:
                source = SourceInput.model_validate(payload)
                self.assertNotIn(source.external_document_id, ids)
                ids.add(source.external_document_id)
                self.assertLessEqual(source.effective_from, source.recorded_at)
                self.assertLessEqual(source.recorded_at, assessment)
            for context in resident["expected_context"]:
                source = next(s for s in resident["sources"]
                              if s["external_document_id"] == context["source_document_id"])
                if "quote" in context:
                    self.assertIn(context["quote"], source["text"])

    def test_scripted_deltas_and_stable_controls(self):
        changes = [
            ({26, 27}, {"speech_rate_wpm": .78, "pause_ratio": 1.4, "mean_pause_s": 1.35}),
            ({26, 27}, {"speech_rate_wpm": .85, "pause_ratio": 1.35, "mean_pause_s": 1.35}),
            ({29}, {"speech_rate_wpm": .7, "pause_ratio": 1.5}),
        ]
        for index, resident in enumerate(self.residents):
            days, factors = changes[index] if index < 3 else (set(), {})
            for check in resident["checks"]:
                for feature, value in check["features"].items():
                    reference = resident["reference_features"][feature]
                    if check["day"] in days and feature in factors:
                        self.assertAlmostEqual(value, reference * factors[feature], places=5)
                    else:
                        self.assertLessEqual(abs(value - reference), FEATURES[feature][2] * 1.5
                                             + .000001)
        self.assertEqual(self.residents[2]["sources"], [])
        self.assertTrue(all(not r["sources"] for r in self.residents[3:]))

    def test_expected_outputs_are_pending_at_explicit_snapshots(self):
        for index, resident in enumerate(self.residents):
            expected = resident["expected_assessment"]
            day = 27 if index < 2 else 29 if index == 2 else 30
            self.assertEqual(expected["as_of"], resident["checks"][day - 1]["ts"])
            self.assertEqual(expected["verification_status"], "pending_bl11_loader")
        medication, _, temperature = self.residents[0]["sources"]
        self.assertEqual(medication["records"][0]["event_type"], "ordered")
        self.assertEqual(medication["records"][0]["value"], "5 mg")
        self.assertEqual(temperature["records"][0]["value"], 37.1)


if __name__ == "__main__":
    unittest.main()
