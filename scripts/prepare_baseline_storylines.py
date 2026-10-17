"""Rebuild the BL-14 synthetic input manifest; does not load or assess patients."""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "fixtures/synthetic/baseline_storylines.json"
SEED = 20261017
FEATURES = {
    "speech_rate_wpm": (120, 165, 4),
    "pause_ratio": (0.15, 0.30, 0.02),
    "mean_pause_s": (0.30, 0.60, 0.04),
    "f0_median_hz": (110, 230, 5),
}


def timestamp(day, hour=14):
    """Days are one-based and fixture dates are fixed, never wall-clock relative."""
    return (datetime(2026, 9, 18, hour, tzinfo=UTC) + timedelta(days=day - 1)).isoformat()


def source(resident_id, slug, day, kind, *, text=None, records=None, hour=12):
    payload = {
        "external_document_id": f"{resident_id}-{slug}",
        "external_version_id": "synthetic-v1",
        "source_system": "synthetic-baseline",
        "kind": kind,
        "author_role": "nurse" if kind == "nursing_note" else "system",
        "visibility": "care_team",
        "recorded_at": timestamp(day, hour),
        "effective_from": timestamp(day, hour),
    }
    payload["text" if text is not None else "records"] = text if text is not None else records
    return payload


def build_storylines():
    rng = random.Random(SEED)
    residents = []
    for index in range(12):
        resident_id = ("synthetic-mrs-k", "synthetic-mr-t", "synthetic-mrs-l")[index] \
            if index < 3 else f"synthetic-resident-{index + 1:02d}"
        name = ("Mrs. K", "Mr. T", "Mrs. L")[index] \
            if index < 3 else f"Synthetic Resident {index + 1:02d}"
        means = {key: round(rng.uniform(lo, hi), 6) for key, (lo, hi, _) in FEATURES.items()}
        checks = []
        for day in range(1, 31):
            # Bound synthetic noise so stable controls do not acquire accidental large outliers.
            values = {
                key: round(means[key] + max(-1.5, min(1.5, rng.gauss(0, 1))) * sd, 6)
                for key, (_, _, sd) in FEATURES.items()
            }
            multipliers = {}
            if index == 0 and day in {26, 27}:
                multipliers = {"speech_rate_wpm": 0.78, "pause_ratio": 1.40, "mean_pause_s": 1.35}
            elif index == 1 and day in {26, 27}:
                multipliers = {"speech_rate_wpm": 0.85, "pause_ratio": 1.20, "mean_pause_s": 1.20}
            elif index == 2 and day == 29:
                multipliers = {"speech_rate_wpm": 0.70, "pause_ratio": 1.50}
            for key, factor in multipliers.items():
                values[key] = round(means[key] * factor, 6)
            checks.append({
                "day": day, "ts": timestamp(day), "mode": "resident",
                "device_id": "unit-tablet-1", "prompt_version": "count20-days-v1",
                "is_baseline": False, "synthetic": True, "usable": True,
                "features": values,
            })
        sources = []
        expectations = []
        if index == 0:
            sources = [
                source(resident_id, "oxybutynin-order", 24, "medication_event", records=[{
                    "concept": "oxybutynin", "value": "5 mg", "polarity": "present",
                    "event_type": "ordered", "order_id": "synthetic-mrs-k-oxybutynin-1",
                    "effective_from": timestamp(24, 12),
                }]),
                source(resident_id, "lunch-note", 27, "nursing_note", text=(
                    "Quiet at lunch, didn't finish her soup. Not her usual chatty self."
                )),
                source(resident_id, "temperature", 27, "observation", records=[{
                    "concept": "temperature_c", "value": 37.1, "unit": "Cel",
                    "polarity": "present", "effective_from": timestamp(27, 12),
                }]),
            ]
            expectations = [
                {"source_document_id": sources[0]["external_document_id"],
                 "tag": "high_risk_med_new"},
                {"source_document_id": sources[1]["external_document_id"],
                 "tag": "poor_intake", "quote": "didn't finish her soup"},
                {"source_document_id": sources[1]["external_document_id"],
                 "tag": "new_confusion_noted", "quote": "Not her usual chatty self"},
            ]
        elif index == 1:
            sources = [source(resident_id, "denture-note", 25, "nursing_note", hour=9,
                              text="New upper denture fitted this morning, says it feels loose.")]
            expectations = [{"source_document_id": sources[0]["external_document_id"],
                             "tag": "dentures", "quote": sources[0]["text"]}]
        assessment_day = 27 if index < 2 else 29 if index == 2 else 30
        verdict, action = (("escalate", "4at_now"), ("explained", "none"),
                           ("watch", "recheck_1h"))[index] if index < 3 else ("within_normal", "none")
        residents.append({
            "id": resident_id, "display_name": name, "synthetic": True,
            "reference_features": means, "checks": checks, "sources": sources,
            "expected_context": expectations,
            "expected_assessment": {
                "day": assessment_day, "as_of": timestamp(assessment_day),
                "verdict": verdict, "suggested_action": action,
                "verification_status": "pending_bl11_loader",
            },
        })
    return {
        "schema_version": 1, "synthetic": True, "seed": SEED,
        "status": "storyline_inputs_only", "start_date": "2026-09-18", "days": 30,
        "generation": "bounded_gaussian_sd_clipped_at_1.5; scripted_deltas_from_reference",
        "residents": residents,
    }


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build_storylines(), indent=2) + "\n", encoding="utf-8")
