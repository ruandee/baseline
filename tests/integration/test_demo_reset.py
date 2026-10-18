"""BL-21 reset scope, actual current-day outcomes and idempotent preservation."""
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4, uuid5

import psycopg
import pytest
from botocore.exceptions import ClientError
from psycopg.types.json import Jsonb

from patient_memory.baseline.verdict import shift_bounds
from scripts import demo_reset
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
        captures = [capture_patient_id(scope, mode) for mode in ("live", "runner")]
        assert admin.execute("SELECT count(*) FROM resident_consents WHERE tenant_id=%s "
                             "AND patient_id=ANY(%s)", (scope.tenant_id, captures)).fetchone()[0] == 0
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
        assert admin.execute("SELECT count(*) FROM resident_consents WHERE tenant_id=%s "
                             "AND patient_id=ANY(%s)", (scope.tenant_id, captures)).fetchone()[0] == 0
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


def reset_markers(admin, scope):
    return admin.execute("SELECT result FROM operations WHERE tenant_id=%s AND operation=%s "
                         "ORDER BY patient_id", (scope.tenant_id, demo_reset.RESET_OP)).fetchall()


def test_resume_after_committed_object_delete_and_partial_loader_preserves_unrelated_data(
        sandbox, monkeypatch):
    cfg, unrelated, _, objects = sandbox
    scope = scope_for(sandbox)
    manifest = canonical_manifest()
    loader.provision(cfg, scope, manifest["residents"])
    loader._publish_sources(cfg, scope, manifest["residents"], objects)
    sentinel_key, sentinel_bytes = f"synthetic-reset-sentinel/{uuid4()}", b"fictional unrelated object"
    sentinel_hash = hashlib.sha256(sentinel_bytes).hexdigest()
    objects.put(sentinel_key, sentinel_bytes)
    with psycopg.connect(cfg.admin_database_url, autocommit=True) as admin:
        old_objects = admin.execute("SELECT object_key,payload_hash FROM sources WHERE tenant_id=%s",
                                    (scope.tenant_id,)).fetchall()
        assert len(old_objects) == 4
        sentinel_check = uuid4()
        admin.execute("INSERT INTO voice_checks(tenant_id,patient_id,id,device_id,mode,usable,"
                      "quality,synthetic,transcript) VALUES(%s,%s,%s,'volunteer-phone','live',"
                      "false,'{}',false,'synthetic sentinel transcript')",
                      (scope.tenant_id, unrelated, sentinel_check))
        anchor = admin.execute("SELECT clock_timestamp()").fetchone()[0].replace(microsecond=0)
        deleted = []
        original_delete = objects.delete

        def crash_after_delete(key):
            original_delete(key)
            deleted.append(key)
            raise RuntimeError("simulated crash after object-store delete committed")

        monkeypatch.setattr(objects, "delete", crash_after_delete)
        with pytest.raises(RuntimeError, match="after object-store delete"):
            reset_demo(cfg, objects=objects, scope=scope, demo_at=anchor)
        assert len(deleted) == 1
        assert data_counts(admin, scope) == [0, 0, 0]
        markers = reset_markers(admin, scope)
        assert len(markers) == 12
        assert sum(len(row[0]["pending_objects"]) for row in markers) == 4
        monkeypatch.setattr(objects, "delete", original_delete)
        original_score, scored = loader._score, []

        def crash_after_partial_scoring(*args, **kwargs):
            result = original_score(*args, **kwargs)
            scored.append(result)
            if len(scored) == 3:
                raise RuntimeError("simulated crash during loader scoring")
            return result

        monkeypatch.setattr(loader, "_score", crash_after_partial_scoring)
        with pytest.raises(RuntimeError, match="during loader scoring"):
            reset_demo(cfg, objects=objects, scope=scope, demo_at=anchor)
        assert data_counts(admin, scope) == [3, 4, 3]
        assert all(row[0]["pending_objects"] == [] for row in reset_markers(admin, scope))
        partial_ids = admin.execute("SELECT id FROM assessments WHERE tenant_id=%s",
                                    (scope.tenant_id,)).fetchall()
        monkeypatch.setattr(loader, "_score", original_score)
        report, session = reset_demo(cfg, objects=objects, scope=scope, demo_at=anchor)
        assert report["matches_spec"] and len(session["patients"]) == 12
        assert [row["latest"]["verdict"] for row in report["outcomes"]] == [
            "escalate", "explained", "watch"] + ["within_normal"] * 9
        assert data_counts(admin, scope) == [353, 4, 353]
        assert all(row[0]["pending_objects"] == [] for row in reset_markers(admin, scope))
        assert admin.execute("SELECT count(*) FROM assessments WHERE id=ANY(%s)",
                             ([row[0] for row in partial_ids],)).fetchone()[0] == 3
        for key, expected_hash in old_objects:
            with pytest.raises(ClientError) as missing:
                objects.get(key, expected_hash)
            assert missing.value.response["Error"]["Code"] in {"404", "NoSuchKey"}
        assert objects.get(sentinel_key, sentinel_hash) == sentinel_bytes
        assert admin.execute("SELECT transcript FROM voice_checks WHERE id=%s",
                             (sentinel_check,)).fetchone() == ("synthetic sentinel transcript",)


def test_concurrent_resets_wait_for_coordinator_until_interrupted_loader_releases_it(
        sandbox, monkeypatch):
    cfg, _, _, objects = sandbox
    scope = scope_for(sandbox)
    entered, release = Event(), Event()
    calls = []
    application = f"reset-coordinator-test-{uuid4()}"
    original_connect = psycopg.connect

    def named_connect(*args, **kwargs):
        kwargs.setdefault("application_name", application)
        return original_connect(*args, **kwargs)

    def interrupted_loader(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=15), "first reset was not released"
        raise RuntimeError("intentional loader interruption")

    # Observe a real PostgreSQL advisory-lock wait, rather than inferring a race from a sleep.
    with original_connect(cfg.admin_database_url, autocommit=True) as admin:
        anchor = admin.execute("SELECT clock_timestamp()").fetchone()[0].replace(microsecond=0)
        monkeypatch.setattr(demo_reset.psycopg, "connect", named_connect)
        monkeypatch.setattr(loader, "load_demo", interrupted_loader)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reset_demo, cfg, objects=objects, scope=scope, demo_at=anchor)
            try:
                assert entered.wait(timeout=10), "first reset did not reach its loader"
                second = pool.submit(reset_demo, cfg, objects=objects, scope=scope, demo_at=anchor)
                deadline = time.monotonic() + 10
                waiting = False
                while time.monotonic() < deadline:
                    waiting = admin.execute("SELECT EXISTS(SELECT FROM pg_stat_activity WHERE "
                        "application_name=%s AND wait_event_type='Lock' AND wait_event='advisory')",
                        (application,)).fetchone()[0]
                    if waiting:
                        break
                    time.sleep(0.01)
                assert waiting, "second reset never waited on the live coordinator lock"
                assert len(calls) == 1 and not second.done()
            finally:
                release.set()
            for future in (first, second):
                with pytest.raises(RuntimeError, match="intentional loader interruption"):
                    future.result(timeout=15)
        assert len(calls) == 2
        markers = reset_markers(admin, scope)
        assert len(markers) == 12 and all(row[0]["pending_objects"] == [] for row in markers)
