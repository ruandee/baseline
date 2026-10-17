from datetime import UTC, datetime
from itertools import product

import pytest

from patient_memory.baseline.verdict import (
    ACTION_LABELS,
    Decision,
    apply_profile,
    decide,
    sbar_template,
    shift_bounds,
)

STATUSES = ("none", "enrolling", "provisional", "change")
CONTEXTS = {
    "no tags": [],
    "explainer": [("explainer", "dentures")],
    "amplifier": [("amplifier", "high_risk_med_new")],
    "both": [("explainer", "exertion"), ("amplifier", "poor_intake")],
    "fever": [("amplifier", "fever_documented")],
}


@pytest.mark.parametrize("status,context", list(product(STATUSES, CONTEXTS)))
def test_every_status_and_context_maps_to_one_verdict(status, context):
    for fused in (None, 2.9, 3.0):
        got = decide(status, fused, CONTEXTS[context])
        assert got.action in ACTION_LABELS
        assert got.verdict in {"within_normal", "enrolling", "watch", "explained", "escalate"}


@pytest.mark.parametrize("status,context,fused,verdict,action", [
    ("none", "amplifier", 0.0, "within_normal", "none"),
    ("enrolling", "amplifier", None, "enrolling", "none"),
    ("provisional", "no tags", 3.2, "watch", "recheck_1h"),
    ("provisional", "explainer", 3.2, "explained", "none"),
    ("change", "explainer", 5.0, "explained", "none"),
    ("change", "no tags", 2.9, "watch", "restore2_soft_signs"),
    ("change", "no tags", 3.0, "escalate", "4at_now"),
    ("change", "amplifier", 2.1, "escalate", "4at_now"),
    ("provisional", "both", 3.1, "escalate", "4at_now"),  # amplifier wins over explainer
    ("change", "fever", 2.5, "escalate", "vitals_recheck"),
])
def test_verdict_table(status, context, fused, verdict, action):
    assert decide(status, fused, CONTEXTS[context]) == Decision(verdict, action)


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError):
        decide("maybe", 1.0, [])


@pytest.mark.parametrize("hour_utc,start_local_hour", [
    (11, 7), (18, 7), (19, 15), (2, 15), (10, 23), (9, 23)])
def test_shift_windows_are_eight_hours_at_0700_1500_2300_toronto(hour_utc, start_local_hour):
    now = datetime(2026, 10, 17, hour_utc, 30, tzinfo=UTC)  # EDT is UTC-4
    start, end = shift_bounds(now, "America/Toronto")
    assert start.hour == start_local_hour and (end - start).total_seconds() == 8 * 3600
    assert start <= now < end


def test_escalation_budget_marks_the_overflow():
    esc = Decision("escalate", "4at_now")
    inside, flags = apply_profile(esc, escalations_used=2, budget=3, no_escalate=False)
    assert inside == esc and not flags["over_budget"]
    over, flags = apply_profile(esc, escalations_used=3, budget=3, no_escalate=False)
    assert over.verdict == "escalate" and flags["over_budget"]  # stored, shown, not interruptive


def test_no_escalate_profile_never_escalates():
    got, flags = apply_profile(Decision("escalate", "4at_now"), escalations_used=0, budget=3,
                               no_escalate=True)
    assert got.verdict == "watch" and flags["would_escalate"] and flags["no_escalate"]
    unchanged, _ = apply_profile(Decision("explained", "none"), escalations_used=0, budget=3,
                                 no_escalate=True)
    assert unchanged.verdict == "explained"


def test_sbar_template_covers_all_sections_and_names_the_action():
    features = {"speech_rate_wpm": {"value": 123.0, "median": 158.0},
                "pause_ratio": {"value": 0.29, "median": 0.21}}
    tags = [{"kind": "amplifier", "label": "New high-risk medication", "evidence_id": "e1"}]
    sbar = sbar_template("Mrs. K", "change", Decision("escalate", "4at_now"), "c1", features, tags)
    assert [s["section"] for s in sbar["sentences"]] == ["S", "B", "A", "R"]
    assert "Run 4AT now" in sbar["sentences"][3]["text"]
    assert sbar["sentences"][1]["evidence_ids"] == ["e1"] and sbar["source"] == "template"
    assert sbar_template("Mrs. K", "none", Decision("within_normal", "none"), "c1", {}, []) is None
