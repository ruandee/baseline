from datetime import timedelta
from uuid import uuid4

import psycopg

from patient_memory.storage import transaction
from scripts import demo_explain
from tests.integration.test_assessments import SLOW, seed_checks, store


def test_demo_context_reassesses_same_check_and_replays_without_new_capture(sandbox, monkeypatch):
    cfg, pid, actors, objects = sandbox
    mapping = {"0/nurse": actors["nurse"].principal_id, "0/importer": actors["importer"].principal_id,
               "tenant-0": actors["nurse"].tenant_id}
    monkeypatch.setattr(demo_explain, "uid", mapping.__getitem__)
    monkeypatch.setattr(demo_explain, "PATIENT", pid)
    seed_checks(sandbox, 6)
    result = store(sandbox, SLOW)
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE voice_checks SET synthetic=true WHERE patient_id=%s AND id=%s",
                      (pid, result.check_id))
    with transaction(cfg, actors["nurse"]) as conn:
        count = conn.execute("SELECT count(*) AS n FROM voice_checks WHERE patient_id=%s",
                             (pid,)).fetchone()["n"]
    body = demo_explain.Explanation(assessment_id=result.assessment["id"], kind="explainer",
        tag="dentures", label="Synthetic loose dentures observed during this check",
        valid_from=result.ts-timedelta(seconds=1))
    key = str(uuid4())
    first = demo_explain.explain(cfg, actors["nurse"], pid, body, key, objects)
    second = demo_explain.explain(cfg, actors["nurse"], pid, body, key, objects)
    assert first == second and first["verdict"] == "explained"
    with transaction(cfg, actors["nurse"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM voice_checks WHERE patient_id=%s",
                            (pid,)).fetchone()["n"] == count
        row = conn.execute("SELECT check_id,params FROM assessments WHERE id=%s",
                           (first["assessment_id"],)).fetchone()
        assert row["check_id"] == result.check_id
        assert row["params"]["signal_ts"] == result.ts.isoformat()
        assert conn.execute("SELECT count(*) AS n FROM context_tags WHERE patient_id=%s",
                            (pid,)).fetchone()["n"] == 1
