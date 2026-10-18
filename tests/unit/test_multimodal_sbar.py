from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from patient_memory.baseline.grounded import multimodal_template
from patient_memory.baseline.note import StoredSbar, validate_signal_citations
from patient_memory.baseline.verdict import Decision
from patient_memory.baseline.vitals import VITALS  # noqa: F401 registration
from patient_memory.errors import Problem
from tests.unit.test_resident_live_js import ROOT


def entry():
    return {"current": True, "status": "provisional", "ts": datetime.now(UTC).isoformat(),
            "evidence_ids": [str(uuid4())], "params": {"baseline_evidence_ids": [str(uuid4())]},
            "per_feature": {"resting_rr_bpm": {"value": 26., "median": 16.}}}


def test_rr_only_has_no_fabricated_voice_hr_or_clinical_inference():
    rr = entry()
    draft = multimodal_template("Synthetic", Decision("watch", "recheck_1h"), {"vitals": rr}, [])
    StoredSbar.model_validate(draft)
    text = " ".join(s["text"] for s in draft["sentences"])
    assert "26.00 vs baseline median 16.00 breaths/min" in text
    assert "not clinically validated" in text and "No context supplied" in text
    assert not any(word in text.lower() for word in ("speech", "heart", "normal", "diagnosis"))
    assert draft["sentences"][0]["evidence_ids"] == rr["evidence_ids"] + rr["params"]["baseline_evidence_ids"]
    assert draft["sentences"][-1]["text"] == "Suggest Recheck in 1 hour."


@pytest.mark.parametrize("damage", ["baseline", "current", "unit", "missing", "nan"])
def test_incomplete_provenance_or_unknown_measurement_withholds_draft(damage):
    rr = entry()
    if damage == "baseline":
        rr["params"]["baseline_evidence_ids"] = []
    elif damage == "current":
        rr["current"] = False
    elif damage == "unit":
        rr["per_feature"] = {"unregistered": {"value": 26., "median": 16.}}
    elif damage == "missing":
        rr["per_feature"]["resting_rr_bpm"]["median"] = None
    else:
        rr["per_feature"]["resting_rr_bpm"]["value"] = float("nan")
    assert multimodal_template("Synthetic", Decision("watch", "recheck_1h"), {"vitals": rr}, []) is None


def test_corroboration_retains_each_status_and_exact_context_attribution():
    rr = entry()
    speech = deepcopy(rr)
    speech["status"] = "change"
    speech["per_feature"] = {"speech_rate_wpm": {"value": 102., "median": 160.}}
    speech["evidence_ids"] = ["check:"+str(uuid4())]
    speech["params"]["baseline_evidence_ids"] = ["check:"+str(uuid4())]
    tag = {"label": "Patient reports tiredness", "evidence_id": str(uuid4())}
    draft = multimodal_template("Synthetic", Decision("escalate", "4at_now"),
                                {"vitals": rr, "speech": speech}, [tag], True)
    assert len(draft["sentences"]) == 5
    assert draft["sentences"][2]["text"] == "Patient reports tiredness."
    assert "vitals: provisional" in draft["sentences"][3]["text"]
    assert "speech: change" in draft["sentences"][3]["text"]
    assert "corroborate" in draft["sentences"][3]["text"]


def test_expired_multimodal_snapshot_fails_before_retrieval():
    rr = entry()
    rr["ts"] = (datetime.now(UTC)-timedelta(hours=25)).isoformat()
    draft = multimodal_template("Synthetic", Decision("watch", "recheck_1h"), {"vitals": rr}, [])
    with pytest.raises(Problem) as exc:
        validate_signal_citations(None, uuid4(), {"params": {"draft_status": "multimodal_template",
                                  "modality_results": {"vitals": rr}}}, StoredSbar.model_validate(draft))
    assert exc.value.code == "note_unavailable"


def run_multimodal_js(fixture=None):
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if fixture:
        env["MULTIMODAL_FIXTURE"] = str(fixture)
    result = subprocess.run([node, "--test", "tests/js/multimodal_sbar.test.js"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_multimodal_capture_citation_ui():
    run_multimodal_js()


def test_full_three_modality_ten_capture_baselines_keep_every_citation_in_export():
    from patient_memory.baseline.engine import (
        Check,
        ModalityResult,
        combine,
        combined_payload,
        evaluate,
    )
    from patient_memory.baseline.note import build_document_reference
    from patient_memory.config import Settings
    from patient_memory.motion import PROTOCOL  # register actual motion adapter
    from tests.unit.test_note_export import row

    now = datetime.now(UTC)
    values = {
        "motion": ({"sit_to_stand_s": 1.2, "trunk_sway": .04, "step_cadence_spm": 60.},
                   {"sit_to_stand_s": 2.5, "trunk_sway": .12, "step_cadence_spm": 45.}),
        "vitals": ({"resting_rr_bpm": 16., "resting_hr_bpm": 70.},
                   {"resting_rr_bpm": 26., "resting_hr_bpm": 100.}),
        "speech": ({"speech_rate_wpm": 160., "pause_ratio": .2, "mean_pause_s": .4, "f0_median_hz": 100.},
                   {"speech_rate_wpm": 100., "pause_ratio": .4, "mean_pause_s": .8, "f0_median_hz": 130.}),
    }
    results, expected = [], set()
    for modality, (baseline, changed) in values.items():
        def capture(at, measurements):
            cid = str(uuid4())
            evidence = ("check:"+cid,) if modality == "speech" else tuple(str(uuid4()) for _ in measurements)
            return Check(cid, at, "synthetic", PROTOCOL if modality == "motion" else modality,
                         False, True, measurements, modality, evidence)
        history = [capture(now-timedelta(days=11-i), baseline) for i in range(10)]
        history.append(capture(now-timedelta(hours=1), changed))
        current = capture(now, changed)
        result = evaluate(current, history, "rolling", Settings())
        assert result.status == "change" and len(result.baseline_ids) == 10
        baseline_evidence = [eid for prior in history if prior.id in result.baseline_ids
                             for eid in prior.evidence_ids]
        result.params["baseline_evidence_ids"] = baseline_evidence
        expected.update([*current.evidence_ids, *baseline_evidence])
        results.append(ModalityResult(modality, now, result, current.id, current.evidence_ids))
    modalities = combined_payload(combine(results, now))["modalities"]
    context = {"label": "Patient reports tiredness", "evidence_id": str(uuid4())}
    draft = multimodal_template("Synthetic", Decision("escalate", "4at_now"), modalities, [context], True)
    sbar = StoredSbar.model_validate(draft)
    assert [len(s.evidence_ids) for s in sbar.sentences if s.section == "S"] == [33, 11, 22]
    assert len(expected) == 66
    expected.add(context["evidence_id"])
    assert {eid for s in sbar.sentences for eid in s.evidence_ids} == expected
    note = build_document_reference(row(allowed_checks={eid[6:] for eid in expected if eid.startswith("check:")}), sbar)
    assert len(note["context"]["related"]) == 67
