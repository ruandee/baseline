"""Stored checks get an assessment; watch list and overview read it back under RLS."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import transaction
from tests.contract.test_api import client_for
from tests.contract.test_context import post as post_context

BASE = {"speech_rate_wpm": 158.0, "pause_ratio": 0.21, "mean_pause_s": 0.40, "f0_median_hz": 212.0}
SLOW = {"speech_rate_wpm": 123.0, "pause_ratio": 0.29, "mean_pause_s": 0.54, "f0_median_hz": 213.0}
QUALITY = {"duration_s": 10.0, "speech_s": 8.0, "snr_db": 20.0, "clipped": False, "reasons": []}
JITTER = [0, 1, -1, 2, -2, 1]


def seed_checks(sandbox, count, base=True, days_ago_start=10, features=BASE):
    """Insert usable checks directly (the audio path needs ffmpeg), one a day, oldest first."""
    cfg, pid, actors, _ = sandbox
    now = datetime.now(UTC)
    with psycopg.connect(cfg.admin_database_url) as admin:
        for i in range(count):
            j = JITTER[i % len(JITTER)]
            admin.execute(
                "INSERT INTO voice_checks(tenant_id,patient_id,id,ts,device_id,mode,is_baseline,usable,"
                "quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,synthetic) "
                "VALUES(%s,%s,%s,%s,'tablet-1','resident',%s,true,'{}',%s,%s,%s,%s,true)",
                (actors["nurse"].tenant_id, pid, uuid4(), now - timedelta(days=days_ago_start - i),
                 base, features["speech_rate_wpm"] + j, features["pause_ratio"] + 0.003 * j,
                 features["mean_pause_s"] + 0.01 * j, features["f0_median_hz"] + j))


def store(sandbox, features, **kw):
    from patient_memory.checks import store_check
    cfg, pid, actors, _ = sandbox
    analysis = Analysis(True, QUALITY, features, [], [], {})
    with transaction(cfg, actors["nurse"]) as conn:
        return store_check(conn, actors["nurse"], pid, uuid4(), analysis, "resident", "tablet-1",
                           None, False, cfg)


def test_stable_check_is_within_normal(sandbox):
    seed_checks(sandbox, 6)
    result = store(sandbox, BASE)
    assert result.change["status"] == "none"
    assert result.assessment["verdict"] == "within_normal"


def test_first_checks_are_enrolling_not_negative(sandbox):
    result = store(sandbox, BASE)
    assert result.change["status"] == "enrolling"
    assert result.assessment["verdict"] == "enrolling"


def test_change_with_amplifier_escalates_and_cites_the_record(sandbox):
    seed_checks(sandbox, 6)
    body = {"kind": "amplifier", "tag": "high_risk_med_new", "label": "oxybutynin 5 mg ordered",
            "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    assert post_context(sandbox, body).status_code == 201
    store(sandbox, SLOW)  # first drifted check is provisional or unconfirmed
    result = store(sandbox, SLOW)
    assert result.change["status"] == "change"
    assert result.assessment["verdict"] == "escalate"
    assert result.assessment["suggested_action"] == "4at_now"
    (reason,) = result.assessment["reasons"]
    assert reason["tag"] == "high_risk_med_new" and reason["evidence_id"]


def test_explainer_only_is_explained_and_quiet(sandbox):
    seed_checks(sandbox, 6)
    body = {"kind": "explainer", "tag": "exertion", "label": "Running the marathon",
            "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    assert post_context(sandbox, body).status_code == 201
    store(sandbox, SLOW)
    result = store(sandbox, SLOW)
    assert result.assessment["verdict"] == "explained"
    assert result.assessment["suggested_action"] == "none"


def test_no_escalate_profile_never_escalates(sandbox):
    from patient_memory.checks import store_check
    cfg, pid, actors, _ = sandbox
    seed_checks(sandbox, 6)
    body = {"kind": "amplifier", "tag": "high_risk_med_new", "label": "med",
            "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    assert post_context(sandbox, body).status_code == 201
    runner_cfg = cfg.model_copy(update={"no_escalate_patients": f"{uuid4()}, {pid}"})
    analysis = Analysis(True, QUALITY, SLOW, [], [], {})
    results = []
    for _ in range(2):
        with transaction(cfg, actors["nurse"]) as conn:
            results.append(store_check(conn, actors["nurse"], pid, uuid4(), analysis, "resident",
                                       "tablet-1", None, False, runner_cfg))
    assert results[-1].assessment["verdict"] == "watch"
    assert results[-1].assessment["no_escalate"] and results[-1].assessment["would_escalate"]


def test_overview_and_watchlist_read_back_the_assessment(sandbox):
    seed_checks(sandbox, 6)
    body = {"kind": "amplifier", "tag": "high_risk_med_new", "label": "med",
            "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    post_context(sandbox, body)
    store(sandbox, SLOW)
    store(sandbox, SLOW)
    nurse = client_for(sandbox, "nurse")
    pid = sandbox[1]
    watch = nurse.get("/v1/watchlist").json()
    (me,) = [r for r in watch["residents"] if r["patient_id"] == str(pid)]
    assert me["latest_verdict"] == "escalate" and me["watch_window"]["open"]
    assert watch["shift"]["escalation_budget"] == 3 and watch["shift"]["escalations_used"] >= 1
    page = nurse.get(f"/v1/patients/{pid}/overview?days=30").json()
    assert page["latest_assessment"]["verdict"] == "escalate"
    assert page["first_change_ts"] and page["series"]["speech_rate_wpm"]["daily"]
    assert page["baseline"]["features"]["speech_rate_wpm"]["scale"] > 0
    assert page["latest_assessment"]["sbar"]["sentences"][3]["section"] == "R"
    evidence_id = page["latest_assessment"]["reasons"][0]["evidence_id"]
    assert nurse.get(f"/v1/patients/{pid}/evidence/{evidence_id}").status_code == 200


def test_other_patients_and_unassigned_callers_see_nothing(sandbox):
    seed_checks(sandbox, 6)
    store(sandbox, BASE)
    stranger = client_for(sandbox, "patient")  # patients are not care team: no voice data
    assert stranger.get(f"/v1/patients/{sandbox[1]}/overview").status_code == 404
    assert client_for(sandbox, "nurse").get(f"/v1/patients/{uuid4()}/overview").status_code == 404
    assert [r for r in stranger.get("/v1/watchlist").json()["residents"]
            if r["latest_verdict"]] == []


@pytest.mark.parametrize("days", [0, 91])
def test_overview_days_are_bounded(sandbox, days):
    assert client_for(sandbox).get(f"/v1/patients/{sandbox[1]}/overview?days={days}").status_code == 422
