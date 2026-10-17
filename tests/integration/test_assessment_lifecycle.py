"""Assessment source lifecycle, baseline preservation and concurrent budget regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline.assess import valid_tags
from patient_memory.domain import SourceInput
from patient_memory.ingestion import submit
from patient_memory.storage import transaction
from patient_memory.worker import run_once
from tests.contract.test_api import client_for
from tests.contract.test_context import post as post_context
from tests.integration.test_assessments import BASE, SLOW, seed_checks, store


def context(sandbox):
    response = post_context(sandbox, {
        "kind": "amplifier", "tag": "high_risk_med_new", "label": "synthetic removable quote",
        "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})
    assert response.status_code == 201, response.text
    return response.json()["source_id"]


@pytest.mark.parametrize("operation", ["retract", "purge", "visibility"])
def test_source_mutation_invalidates_assessment_and_removes_copied_quotes(sandbox, operation):
    seed_checks(sandbox, 6)
    source_id = context(sandbox)
    store(sandbox, SLOW)
    assert store(sandbox, SLOW).assessment["verdict"] == "escalate"
    cfg, pid, actors, objects = sandbox
    importer = client_for(sandbox, "importer")
    path = f"/v1/patients/{pid}/sources/{source_id}/{operation}"
    headers = {"Idempotency-Key": str(uuid4())}
    if operation == "visibility":
        response = importer.put(path, json={"visibility": "patient_and_care_team"}, headers=headers)
    else:
        response = importer.post(path, json={"reason": "synthetic correction"}, headers=headers)
    assert response.status_code in (200, 202), response.text
    if operation == "purge":
        assert run_once(cfg, actors["importer"], objects)
    nurse = client_for(sandbox)
    overview = nurse.get(f"/v1/patients/{pid}/overview")
    assert overview.status_code == 200, overview.text
    assert overview.json()["latest_assessment"] is None
    resident, = [r for r in nurse.get("/v1/watchlist").json()["residents"]
                 if r["patient_id"] == str(pid)]
    assert resident["latest_verdict"] is None
    with transaction(cfg, actors["nurse"]) as conn:
        rows = conn.execute("SELECT reasons,sbar,params FROM assessments WHERE patient_id=%s",
                            (pid,)).fetchall()
    assert rows and all(r["reasons"] == [] and r["sbar"] is None
                        and r["params"]["invalidated"] for r in rows)
    assert client_for(sandbox, "patient").get(f"/v1/patients/{pid}/overview").status_code == 404


def test_published_correction_replaces_context_from_original_source(sandbox):
    cfg, pid, actors, objects = sandbox
    source_id = context(sandbox)
    with transaction(cfg, actors["importer"]) as conn:
        payload = conn.execute("SELECT payload FROM sources WHERE id=%s",
                               (source_id,)).fetchone()["payload"]
        payload.update(external_version_id="2", supersedes_version_id=source_id,
                       records=[{"concept": "context.dentures", "value": "synthetic corrected context"}])
        submit(conn, actors["importer"], pid, SourceInput.model_validate(payload), str(uuid4()), objects)
    assert run_once(cfg, actors["importer"], objects)
    with transaction(cfg, actors["nurse"]) as conn:
        tags = valid_tags(conn, pid, datetime.now(UTC))
    assert [t["tag"] for t in tags] == ["dentures"]
    assert tags[0]["source_id"] != source_id


def test_enrolled_baseline_survives_sixty_newer_checks(sandbox):
    seed_checks(sandbox, 3, days_ago_start=3)
    cfg, pid, actors, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as conn:
        for i in range(60):
            conn.execute(
                "INSERT INTO voice_checks(tenant_id,patient_id,id,ts,device_id,mode,usable,quality,"
                "speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz) "
                "VALUES(%s,%s,%s,%s,'tablet-1','resident',true,'{}',%s,%s,%s,%s)",
                (actors["nurse"].tenant_id, pid, uuid4(),
                 datetime.now(UTC) - timedelta(minutes=i+1), *BASE.values()))
    result = store(sandbox, BASE)
    assert result.change["mode"] == "enrolled"
    assert result.change["status"] == "none"
    assert result.change["params"]["baseline_checks"] == 3


def test_concurrent_checks_share_the_final_shift_budget_slot(sandbox):
    cfg, pid, actors, objects = sandbox
    cfg = cfg.model_copy(update={"escalation_budget": 1})
    sandbox = cfg, pid, actors, objects
    seed_checks(sandbox, 6)
    context(sandbox)
    start = Barrier(4)

    def upload(_):
        start.wait(timeout=10)
        return store(sandbox, SLOW)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(upload, range(4)))
    assert all(r.assessment["verdict"] == "escalate" for r in results)
    assert sum(not r.assessment["over_budget"] for r in results) == 1
    # Serialized scoring also lets the later checks see the first one's drift.
    assert sum(r.change["status"] == "change" for r in results) >= 3


def test_other_prompt_enrollment_does_not_override_rolling_mode(sandbox):
    seed_checks(sandbox, 3)
    cfg, pid, _, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("UPDATE voice_checks SET prompt_version='free-conversation-v1' "
                     "WHERE patient_id=%s", (pid,))
    seed_checks(sandbox, 6, base=False)
    result = store(sandbox, BASE)
    assert result.change["mode"] == "rolling"
    assert result.change["status"] == "none"
