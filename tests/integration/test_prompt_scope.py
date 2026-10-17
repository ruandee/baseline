"""Counting-prompt and free-conversation (Vox) histories never mix (BL-32, decision 016)."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg

from patient_memory.checks import store_check
from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import transaction
from tests.contract.test_api import client_for

COUNTING, FREE = "count20-days-v1", "free-conversation-v1"
QUALITY = {"duration_s": 10.0, "speech_s": 8.0, "snr_db": 20.0, "clipped": False, "reasons": []}


def features(rate):
    return {"speech_rate_wpm": rate, "pause_ratio": 0.21, "mean_pause_s": 0.40,
            "f0_median_hz": 140.0}


def seed(sandbox, prompt_version, rate, count=6):
    cfg, pid, actors, _ = sandbox
    now = datetime.now(UTC)
    with psycopg.connect(cfg.admin_database_url) as admin:
        for i in range(count):
            f = features(rate + i % 3)
            admin.execute(
                "INSERT INTO voice_checks(tenant_id,patient_id,id,ts,device_id,mode,prompt_version,"
                "is_baseline,usable,quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,"
                "synthetic) VALUES(%s,%s,%s,%s,'tablet-1','resident',%s,false,true,'{}',%s,%s,%s,"
                "%s,true)",
                (actors["nurse"].tenant_id, pid, uuid4(), now - timedelta(days=10 - i),
                 prompt_version, *f.values()))


def store(sandbox, prompt_version, rate):
    cfg, pid, actors, _ = sandbox
    analysis = Analysis(True, QUALITY, features(rate), [], [], {})
    with transaction(cfg, actors["nurse"]) as conn:
        return store_check(conn, actors["nurse"], pid, uuid4(), analysis, "resident", "tablet-1",
                           None, False, cfg, prompt_version=prompt_version)


def test_each_prompt_is_scored_against_its_own_history_and_threshold(sandbox):
    seed(sandbox, COUNTING, 158.0)
    seed(sandbox, FREE, 70.0)
    counting = store(sandbox, COUNTING, 159.0).change
    free = store(sandbox, FREE, 71.0).change
    assert counting["per_feature"]["speech_rate_wpm"]["median"] == 159.0
    assert free["per_feature"]["speech_rate_wpm"]["median"] == 71.0
    assert counting["params"]["baseline_checks"] == free["params"]["baseline_checks"] == 6
    assert counting["params"]["z_threshold"] == 2.0 and free["params"]["z_threshold"] == 2.5
    assert counting["status"] == free["status"] == "none"


def test_free_conversation_checks_alone_never_seed_a_counting_baseline(sandbox):
    seed(sandbox, FREE, 70.0)
    assert store(sandbox, COUNTING, 158.0).change["status"] == "enrolling"


def test_overview_charts_the_latest_assessments_prompt_and_watchlist_the_counting_prompt(sandbox):
    seed(sandbox, COUNTING, 158.0)
    seed(sandbox, FREE, 70.0, count=4)
    store(sandbox, COUNTING, 159.0)
    nurse = client_for(sandbox, "nurse")
    pid = sandbox[1]
    page = nurse.get(f"/v1/patients/{pid}/overview?days=30").json()
    assert page["baseline"]["prompt_version"] == COUNTING
    assert len(page["series"]["speech_rate_wpm"]["checks"]) == 7
    assert all(p["value"] > 150 for p in page["series"]["speech_rate_wpm"]["checks"])

    store(sandbox, FREE, 71.0)
    page = nurse.get(f"/v1/patients/{pid}/overview?days=30").json()
    assert page["baseline"]["prompt_version"] == FREE
    assert page["latest_assessment"]["change"]["params"]["prompt_version"] == FREE
    assert len(page["series"]["speech_rate_wpm"]["checks"]) == 5
    assert all(p["value"] < 80 for p in page["series"]["speech_rate_wpm"]["checks"])

    (me,) = [r for r in nurse.get("/v1/watchlist").json()["residents"]
             if r["patient_id"] == str(pid)]
    assert me["sparkline"] and all(d["speech_rate_wpm"] > 150 for d in me["sparkline"])
