"""BL-21 reset scope, actual current-day outcomes and idempotent preservation."""
from datetime import timedelta
from uuid import uuid4, uuid5

import psycopg
import pytest
from psycopg.types.json import Jsonb

from patient_memory.baseline.verdict import shift_bounds
from scripts import load_baseline_demo as loader
from scripts.demo_reset import (
    QUALITY,
    canonical_manifest,
    capture_patient_id,
    provision_capture,
    reset_demo,
)
from tests.integration.test_baseline_loader import scope_for
from tests.integration.test_safety_rls import add_session


def seed_authored_checks(conn, scope, manifest, *, limit=30):
    for i, resident in enumerate(manifest["residents"]):
        for check in resident["checks"][:limit]:
            conn.execute("INSERT INTO voice_checks(tenant_id,patient_id,id,ts,device_id,mode,prompt_version,"
                         "is_baseline,usable,quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,synthetic) "
                         "VALUES(%s,%s,%s,%s,%s,%s,%s,false,true,%s,%s,%s,%s,%s,true)",
                         (scope.tenant_id, scope.patient_id(i), uuid5(scope.patient_id(i), f"baseline-v1/day-{check['day']}"),
                          check["ts"], check["device_id"], check["mode"], check["prompt_version"], Jsonb(QUALITY),
                          *[check["features"][name] for name in loader.engine.FEATURES]))


def data_counts(conn, scope):
    ids = [scope.patient_id(i) for i in range(12)]
    return [conn.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s AND patient_id=ANY(%s)",
                         (scope.tenant_id, ids)).fetchone()[0] for table in ("voice_checks", "sources", "assessments")]


def test_reset_preserves_capture_unrelated_safety_consent_and_revocations_and_all_outcomes(sandbox, kaze_sandbox):
    cfg, unrelated, _, objects = sandbox
    scope = scope_for(sandbox)
    manifest = canonical_manifest()
    loader.provision(cfg, scope, manifest["residents"])
    loader._publish_sources(cfg, scope, manifest["residents"], objects)
    provision_capture(cfg, scope)
    with psycopg.connect(cfg.admin_database_url, autocommit=True) as admin:
        seed_authored_checks(admin, scope, manifest)
        sentinel_ids = []
        for pid, mode in [(capture_patient_id(scope, "live"), "live"),
                          (capture_patient_id(scope, "runner"), "runner"), (unrelated, "resident")]:
            cid = uuid4()
            sentinel_ids.append(cid)
            admin.execute("INSERT INTO voice_checks(tenant_id,patient_id,id,device_id,mode,usable,quality,"
                          "synthetic,transcript) VALUES(%s,%s,%s,'synthetic-test-phone',%s,false,%s,false,"
                          "'synthetic capture placeholder')", (scope.tenant_id, pid, cid, mode, Jsonb({})))
        sid = add_session(admin, kaze_sandbox["tenant"], kaze_sandbox["patient"])
        admin.execute("UPDATE assignments SET active=false WHERE tenant_id=%s AND patient_id=%s "
                      "AND principal_id=%s AND role='psw'", (scope.tenant_id, scope.patient_id(0), scope.psw_id))
        admin.execute("INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,decided_by,recorded_by) "
                      "VALUES(%s,%s,%s,'voice_check','withdrawn','synthetic_fixture',%s)",
                      (scope.tenant_id, scope.patient_id(0), uuid4(), scope.importer_id))
        now = admin.execute("SELECT clock_timestamp()").fetchone()[0].replace(microsecond=0)
        first, _ = reset_demo(cfg, objects=objects, scope=scope, demo_at=now-timedelta(days=1))
        assert first["matches_spec"] and first["checks_loaded"] == 353
        counts = data_counts(admin, scope)
        assert counts == [353,4,353]
        again, _ = reset_demo(cfg, objects=objects, scope=scope, demo_at=now-timedelta(days=1))
        assert data_counts(admin, scope) == counts
        assert first["outcomes"] == again["outcomes"]
        current, _ = reset_demo(cfg, objects=objects, scope=scope, demo_at=now)
        assert current["canonical_cohort_count"] == 12 and current["matches_spec"]
        assert current["token_ttl_hours"] == 48
        assert [r["latest"]["verdict"] for r in current["outcomes"]] == ["escalate","explained","watch"]+["within_normal"]*9
        start, end = shift_bounds(now, cfg.shift_timezone)
        assert current["current_shift"]["start"] == start.astimezone(now.tzinfo).isoformat()
        assert current["current_shift"]["end"] == end.astimezone(now.tzinfo).isoformat()
        assert current["current_shift"]["escalations_used"] == 1
        assert data_counts(admin, scope) == counts
        ids = [scope.patient_id(i) for i in range(12)]
        assert admin.execute("SELECT max(ts),count(*) FROM voice_checks WHERE tenant_id=%s AND patient_id=ANY(%s)",
                              (scope.tenant_id, ids)).fetchone() == (now,353)
        assert admin.execute("SELECT count(*) FROM voice_checks WHERE id=ANY(%s)", (sentinel_ids,)).fetchone()[0] == 3
        assert admin.execute("SELECT count(*) FROM safety_sessions WHERE id=%s", (sid,)).fetchone()[0] == 1
        assert admin.execute("SELECT active FROM assignments WHERE tenant_id=%s AND patient_id=%s "
                             "AND principal_id=%s AND role='psw'", (scope.tenant_id, scope.patient_id(0), scope.psw_id)).fetchone()[0] is False
        assert admin.execute("SELECT status FROM resident_consents WHERE tenant_id=%s AND patient_id=%s "
                             "ORDER BY recorded_at DESC,id DESC LIMIT 1", (scope.tenant_id, scope.patient_id(0))).fetchone()[0] == "withdrawn"


def test_nonfixture_check_in_last_patient_refuses_before_any_fixture_deletion(sandbox):
    cfg, _, _, objects = sandbox
    scope = scope_for(sandbox)
    manifest = canonical_manifest()
    loader.provision(cfg, scope, manifest["residents"])
    with psycopg.connect(cfg.admin_database_url, autocommit=True) as admin:
        seed_authored_checks(admin, scope, manifest, limit=1)
        admin.execute("INSERT INTO voice_checks(tenant_id,patient_id,id,device_id,mode,usable,quality,synthetic) "
                      "VALUES(%s,%s,%s,'real-phone','runner',false,%s,false)",
                      (scope.tenant_id, scope.patient_id(11), uuid4(), Jsonb({})))
        with pytest.raises(loader.LoaderError, match="preserve nonfixture"):
            reset_demo(cfg, objects=objects, scope=scope)
        assert data_counts(admin, scope) == [13,0,0]
        assert admin.execute("SELECT count(*) FROM operations WHERE tenant_id=%s AND operation='baseline_demo_reset'",
                              (scope.tenant_id,)).fetchone()[0] == 0
