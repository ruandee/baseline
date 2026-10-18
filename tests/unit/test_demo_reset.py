import copy
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest

from patient_memory.baseline.engine import Check, evaluate
from patient_memory.baseline.verdict import decide
from patient_memory.config import Settings
from scripts.demo_reset import (
    QUALITY,
    anchor_time,
    canonical_manifest,
    current_day_manifest,
    validate_fixture_rows,
)
from scripts.load_baseline_demo import LoaderError, selected_checks

AT = datetime(2026, 12, 8, 16, 30, tzinfo=UTC)


def test_translation_keeps_original_fixture_and_all_measurements_and_relative_windows():
    original = canonical_manifest()
    before = copy.deepcopy(original)
    shifted = current_day_manifest(original, AT)
    assert original == before
    assert [len(selected_checks(r, "scenario-snapshots")) for r in shifted["residents"]] == [27,27,29]+[30]*9
    for old, new in zip(original["residents"], shifted["residents"], strict=True):
        assert new["expected_assessment"]["as_of"] == AT.isoformat()
        assert selected_checks(new, "scenario-snapshots")[-1]["ts"] == AT.isoformat()
        for a, b in zip(old["checks"], new["checks"], strict=True):
            assert a["features"] == b["features"]
        for a, b in zip(old["sources"], new["sources"], strict=True):
            assert AT-datetime.fromisoformat(b["recorded_at"]) == datetime.fromisoformat(old["expected_assessment"]["as_of"])-datetime.fromisoformat(a["recorded_at"])
            assert a.get("text") == b.get("text")
            for ar, br in zip(a.get("records", []), b.get("records", []), strict=True):
                assert ar["value"] == br["value"]
                assert datetime.fromisoformat(br["effective_from"])-datetime.fromisoformat(b["effective_from"]) == datetime.fromisoformat(ar["effective_from"])-datetime.fromisoformat(a["effective_from"])


def test_all_twelve_canonical_outcomes_survive_new_anchor_without_threshold_changes():
    shifted = current_day_manifest(canonical_manifest(), AT)
    cfg = Settings()
    for index, resident in enumerate(shifted["residents"]):
        history = []
        for raw in selected_checks(resident, "scenario-snapshots"):
            check = Check(str(raw["day"]), datetime.fromisoformat(raw["ts"]), raw["device_id"],
                          raw["prompt_version"], False, True, raw["features"])
            result = evaluate(check, history, "rolling", cfg)
            history.append(check)
        tags = [("amplifier" if index == 0 else "explainer", item["tag"]) for item in resident["expected_context"]]
        decision = decide(result.status, result.fused, tags)
        assert (decision.verdict, decision.action) == (resident["expected_assessment"]["verdict"], resident["expected_assessment"]["suggested_action"])


@pytest.mark.parametrize("value", ["2026-12-08T12:00:00", None, "not-a-date"])
def test_naive_or_missing_anchor_is_rejected(value):
    with pytest.raises((LoaderError, ValueError)):
        anchor_time(value)


def fixture_check(patient_id):
    resident = canonical_manifest()["residents"][0]
    raw = resident["checks"][0]
    row = {**raw["features"], **raw, "id": uuid5(patient_id, "baseline-v1/day-1"),
           "ts": datetime.fromisoformat(raw["ts"]), "quality": QUALITY}
    return resident, row


@pytest.mark.parametrize("field,value", [("synthetic", False), ("mode", "runner"),
    ("transcript", "real volunteer words"), ("session_id", uuid4()), ("id", uuid4()),
    ("quality", {"provenance":"audio"}), ("speech_rate_wpm", 999), ("ts", AT)])
def test_any_real_runner_session_or_changed_measurement_is_not_deletable(field, value):
    pid = uuid4()
    resident, row = fixture_check(pid)
    validate_fixture_rows(resident, pid, [], [row])
    row[field] = value
    with pytest.raises(LoaderError, match="preserve"):
        validate_fixture_rows(resident, pid, [], [row])


def test_capture_selection_never_implicitly_records_into_scripted_residents():
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("Node.js not available")
    root = Path(__file__).resolve().parents[2]
    code = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('frontend/check.js','utf8'),ctx);
const scripted = [{id:'mrs-k',scripted_cohort:true}];
assert.equal(ctx.checkPatientId({mode:'live'},scripted),null);
assert.equal(ctx.checkPatientId({mode:'runner'},scripted),null);
const all = [...scripted,{id:'live-id',capture_mode:'live',scripted_cohort:false},
 {id:'runner-id',capture_mode:'runner',scripted_cohort:false}];
assert.equal(ctx.checkPatientId({mode:'live'},all),'live-id');
assert.equal(ctx.checkPatientId({mode:'runner'},all),'runner-id');
assert.equal(ctx.checkPatientId({mode:'live',patient:'explicit-own-id'},all),'explicit-own-id');
"""
    result = subprocess.run(["node","-e",code], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
