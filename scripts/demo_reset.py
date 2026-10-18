"""BL-21: explicit, fixture-only current-day reset. No real/runner check is deletable."""
import argparse
import copy
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import psycopg
from botocore.exceptions import ClientError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from patient_memory.baseline.overview import watchlist
from patient_memory.config import Settings
from patient_memory.consent import grant_fixture_consent
from patient_memory.domain import SourceInput
from patient_memory.extraction import extract
from patient_memory.ingestion import digest, lock_patient
from patient_memory.objects import ObjectStore
from patient_memory.storage import transaction
from scripts import load_baseline_demo as loader
from scripts.prepare_baseline_storylines import OUTPUT, build_storylines
from scripts.seed import uid

RESET_OP = "baseline_demo_reset"
RESET_KEY = "canonical-v1"
DATE_FIELDS = {"ts", "as_of", "recorded_at", "effective_from", "effective_to"}
QUALITY = {"provenance": "authored_synthetic_features", "audio_validated": False}


def anchor_time(value):
    at = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise loader.LoaderError("demo_at must be a timezone-aware UTC instant")
    return at.astimezone(UTC)


def canonical_manifest():
    manifest = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if manifest != build_storylines():
        raise loader.LoaderError("The committed canonical fixture and generator must agree")
    loader.validate_manifest(manifest)
    return manifest


def current_day_manifest(manifest, demo_at):
    """Copy, never edit, the authored manifest; align each scenario prefix's final check."""
    demo_at = anchor_time(demo_at)
    shifted = copy.deepcopy(manifest)
    for resident in shifted["residents"]:
        delta = demo_at - datetime.fromisoformat(resident["expected_assessment"]["as_of"])
        def move(value):
            if isinstance(value, list):
                return [move(item) for item in value]
            if isinstance(value, dict):
                return {key: ((datetime.fromisoformat(item) + delta).isoformat()
                              if key in DATE_FIELDS and item is not None else move(item))
                        for key, item in value.items()}
            return value
        resident.update(move(resident))
    shifted["presentation_anchor"] = demo_at.isoformat()
    return shifted


def _variant(manifest, value):
    return manifest if value is None else current_day_manifest(manifest, value)


def _check_matches(row, check, patient_id):
    expected = {**check["features"], **{key: check[key] for key in (
        "device_id", "mode", "prompt_version", "is_baseline", "usable", "synthetic")}}
    return (row["id"] == uuid5(patient_id, f"baseline-v1/day-{check['day']}")
            and row["ts"] == datetime.fromisoformat(check["ts"])
            and all(row[key] == value for key, value in expected.items())
            and row["quality"] == QUALITY and all(row.get(key) is None for key in (
                "device_ts", "transcript", "words", "session_id", "lat", "lon", "accuracy_m")))


def validate_fixture_rows(resident, patient_id, sources, checks):
    """Exact identities/hashes/measurements, never a synthetic flag or patient name alone."""
    expected_sources = {json.dumps([raw["source_system"], raw["external_document_id"]]):
                        SourceInput.model_validate(raw).model_dump(mode="json")
                        for raw in resident["sources"]}
    for row in sources:
        payload = expected_sources.get(row["document_key"])
        if (payload is None or row["external_version"] != payload["external_version_id"]
                or row["payload_hash"] != digest(payload)
                or row["recorded_at"] != datetime.fromisoformat(payload["recorded_at"])
                or row["object_key"] != f"{row['tenant_id']}/{patient_id}/{row['id']}.json"
                or (row["payload"] != payload and not (row["purged_at"] and row["payload"] == {}))):
            raise loader.LoaderError("Reset refused: source is not an exact canonical fixture")
        if row["canonical_text"] and row["canonical_text"] != extract(SourceInput.model_validate(payload))[0]:
            raise loader.LoaderError("Reset refused: canonical evidence is not the fixture")
    expected_checks = {uuid5(patient_id, f"baseline-v1/day-{c['day']}"): c
                       for c in resident["checks"]}
    if any(row["id"] not in expected_checks or not _check_matches(
            row, expected_checks[row["id"]], patient_id) for row in checks):
        raise loader.LoaderError("Reset refused: preserve nonfixture/real/runner/session checks")


def _marker(conn, tenant, patient_id, fingerprint):
    row = conn.execute("SELECT * FROM operations WHERE tenant_id=%s AND patient_id=%s "
                       "AND operation=%s AND key=%s", (tenant, patient_id, RESET_OP, RESET_KEY)).fetchone()
    if row is None:
        return None, []
    value = row["result"]
    if row["payload_hash"] != fingerprint or value.get("version") != 1:
        raise loader.LoaderError("Reset marker does not match the canonical fixture")
    return anchor_time(value["anchor"]).isoformat(), value.get("pending_objects", [])


def _cleanup(cfg, scope, manifest, demo_at, objects):
    fingerprint = digest(manifest)
    plans = []
    # This coordinator lock is held across the runtime loader, without holding admission locks.
    # The deployment wrapper stops API and worker before entering this explicit admin operation.
    conn = psycopg.connect(cfg.admin_database_url, row_factory=dict_row)
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))",
                 (f"baseline-reset/{scope.tenant_id}",))
    conn.commit()
    try:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                         (f"baseline-budget/{scope.tenant_id}",))
            tenant = conn.execute("SELECT safety_mode FROM tenants WHERE id=%s", (scope.tenant_id,)).fetchone()
            if tenant and tenant["safety_mode"]:
                raise loader.LoaderError("Reset never operates on a safety tenant")
            conn.execute("INSERT INTO tenants(id,name) VALUES(%s,'synthetic-baseline-demo') "
                         "ON CONFLICT DO NOTHING", (scope.tenant_id,))
            for index, resident in enumerate(manifest["residents"]):
                pid = scope.patient_id(index)
                lock_patient(conn, pid)
                old = conn.execute("SELECT * FROM patients WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                   (scope.tenant_id, pid)).fetchone()
                if old and old["external_id"] not in (resident["display_name"], f"synthetic-patient-{index}"):
                    raise loader.LoaderError("Reset refused: patient identity is not the fixture")
                conn.execute("INSERT INTO patients(tenant_id,id,external_id) VALUES(%s,%s,%s) "
                             "ON CONFLICT DO NOTHING", (scope.tenant_id, pid, resident["display_name"]))
                previous, pending = _marker(conn, scope.tenant_id, pid, fingerprint)
                sources = conn.execute("SELECT * FROM sources WHERE tenant_id=%s AND patient_id=%s",
                                       (scope.tenant_id, pid)).fetchall()
                checks = conn.execute("SELECT * FROM voice_checks WHERE tenant_id=%s AND patient_id=%s",
                                      (scope.tenant_id, pid)).fetchall()
                active = _variant(manifest, previous)["residents"][index]
                validate_fixture_rows(active, pid, sources, checks)
                if conn.execute("SELECT EXISTS(SELECT FROM assessments WHERE tenant_id=%s AND patient_id=%s "
                                "AND NOT(check_id=ANY(%s))) AS orphan", (scope.tenant_id, pid,
                                [row["id"] for row in checks])).fetchone()["orphan"]:
                    raise loader.LoaderError("Reset refused: unrecognised derived assessment is preserved")
                if conn.execute("SELECT EXISTS(SELECT FROM check_skips WHERE tenant_id=%s AND patient_id=%s) "
                                "OR EXISTS(SELECT FROM safety_sessions WHERE tenant_id=%s AND patient_id=%s) AS occupied",
                                (scope.tenant_id, pid, scope.tenant_id, pid)).fetchone()["occupied"]:
                    raise loader.LoaderError("Reset refused: preserve human skips or safety sessions")
                source_map = {str(row["id"]): row for row in sources}
                operations = conn.execute("SELECT * FROM operations WHERE tenant_id=%s AND patient_id=%s "
                                          "AND operation<>%s", (scope.tenant_id, pid, RESET_OP)).fetchall()
                for operation in operations:
                    source = source_map.get(operation["result"].get("source_version_id"))
                    if (operation["operation"] != "submit" or source is None
                            or operation["payload_hash"] != source["payload_hash"]
                            or operation["key"] != "baseline-v1/" + json.loads(source["document_key"])[1]):
                        raise loader.LoaderError("Reset refused: unrecognised operation is preserved")
                for role, actor in (("importer", scope.importer_id), ("nurse", scope.nurse_id)):
                    blocked = conn.execute("SELECT active FROM assignments WHERE tenant_id=%s AND patient_id=%s "
                                           "AND principal_id=%s AND role=%s", (scope.tenant_id, pid, actor, role)).fetchone()
                    if blocked and not blocked["active"]:
                        raise loader.LoaderError("Reset preserves revoked fixture operator assignments")
                changed = previous != demo_at.isoformat()
                if changed:
                    pending += [{"key": row["object_key"], "hash": row["payload_hash"],
                                 "source_id": str(row["id"])} for row in sources if not row["purged_at"]]
                plans.append((pid, changed, sources, checks, operations, pending))
            for role, actor in (("importer", scope.importer_id), ("nurse", scope.nurse_id), ("psw", scope.psw_id)):
                conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,%s) "
                             "ON CONFLICT DO NOTHING", (actor, scope.tenant_id, f"synthetic-{role}"))
                if not conn.execute("SELECT active FROM principals WHERE tenant_id=%s AND id=%s",
                                    (scope.tenant_id, actor)).fetchone()["active"]:
                    raise loader.LoaderError("Reset preserves inactive demo principals")
            # Every patient has passed the complete allowlist before any deletion occurs.
            for pid, changed, sources, checks, operations, pending in plans:
                if changed:
                    sids, cids = [r["id"] for r in sources], [r["id"] for r in checks]
                    for table, column, ids in (("assessments", "check_id", cids),
                                               ("voice_checks", "id", cids),
                                               ("context_tags", "source_id", sids),
                                               ("note_context_runs", "source_id", sids),
                                               ("facts", "source_id", sids),
                                               ("jobs", "source_id", sids),
                                               ("sources", "id", sids)):
                        conn.execute(f"DELETE FROM {table} WHERE tenant_id=%s AND patient_id=%s AND {column}=ANY(%s)",
                                     (scope.tenant_id, pid, ids))
                    conn.execute("DELETE FROM operations WHERE tenant_id=%s AND patient_id=%s "
                                 "AND operation='submit' AND key=ANY(%s)",
                                 (scope.tenant_id, pid, [r["key"] for r in operations]))
                    conn.execute("DELETE FROM answers WHERE tenant_id=%s AND patient_id=%s", (scope.tenant_id, pid))
                    conn.execute("UPDATE patients SET revision=revision+1 WHERE tenant_id=%s AND id=%s",
                                 (scope.tenant_id, pid))
                conn.execute("INSERT INTO audit(tenant_id,patient_id,principal_id,action,result,request_id) "
                             "VALUES(%s,%s,%s,'baseline_demo_reset','validated_fixture_only',%s)",
                             (scope.tenant_id, pid, scope.importer_id, uuid4()))
                conn.execute("INSERT INTO operations VALUES(%s,%s,%s,%s,%s,%s) "
                             "ON CONFLICT(tenant_id,patient_id,operation,key) DO UPDATE SET result=excluded.result",
                             (scope.tenant_id, pid, RESET_OP, RESET_KEY, fingerprint,
                              Jsonb({"version": 1, "anchor": demo_at.isoformat(), "pending_objects": pending})))
        # Objects are deleted only by exact validated tenant/patient/source keys, after commit.
        for pid, _, _, _, _, pending in plans:
            for item in pending:
                expected_key = f"{scope.tenant_id}/{pid}/{UUID(item['source_id'])}.json"
                if item["key"] != expected_key:
                    raise loader.LoaderError("Reset object cleanup marker is not scoped")
                try:
                    objects.get(item["key"], item["hash"])
                except ClientError as exc:
                    if exc.response["Error"]["Code"] not in {"404", "NoSuchKey"}:
                        raise  # a prior interrupted cleanup may already have deleted it
                else:
                    objects.delete(item["key"])
            with conn.transaction():
                conn.execute("UPDATE operations SET result=jsonb_set(result,'{pending_objects}','[]') "
                             "WHERE tenant_id=%s AND patient_id=%s AND operation=%s AND key=%s",
                             (scope.tenant_id, pid, RESET_OP, RESET_KEY))
        return conn
    except Exception:
        conn.close()
        raise


def capture_patient_id(scope, mode):
    if mode not in {"live", "runner"}:
        raise loader.LoaderError("Unknown capture mode")
    return (uid(f"0/{mode}-capture") if scope.tenant_id == uid("tenant-0")
            else uuid5(scope.tenant_id, f"baseline-capture/{mode}"))


def provision_capture(cfg, scope):
    """Only provision separate capture people; never rewrite clips, consent or revocations."""
    people = []
    with psycopg.connect(cfg.admin_database_url, row_factory=dict_row) as conn:
        for mode in ("live", "runner"):
            pid = capture_patient_id(scope, mode)
            name = f"Synthetic {mode} volunteer (outside scripted cohort)"
            existing = conn.execute("SELECT external_id FROM patients WHERE tenant_id=%s AND id=%s",
                                    (scope.tenant_id, pid)).fetchone()
            if existing and existing["external_id"] != name:
                raise loader.LoaderError("Dedicated capture identity is occupied; nothing overwritten")
            conn.execute("INSERT INTO patients(tenant_id,id,external_id) VALUES(%s,%s,%s) "
                         "ON CONFLICT DO NOTHING", (scope.tenant_id, pid, name))
            for role, actor in (("nurse", scope.nurse_id), ("importer", scope.importer_id)):
                conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true) ON CONFLICT DO NOTHING",
                             (scope.tenant_id, pid, actor, role))
            grant_fixture_consent(conn, scope.tenant_id, pid, scope.importer_id)
            people.append({"id": str(pid), "name": name, "capture_mode": mode, "scripted_cohort": False})
    return people


def reset_demo(cfg=None, *, objects=None, scope=None, demo_at=None):
    cfg, scope = cfg or Settings(), scope or loader.DemoScope()
    if cfg.environment != "synthetic" or not cfg.admin_database_url:
        raise loader.LoaderError("Explicit synthetic admin setup is required")
    cfg = cfg.model_copy(update={"provider": "stub", "token_ttl_hours": 48})
    at = anchor_time(demo_at or datetime.now(UTC).replace(microsecond=0))
    manifest = canonical_manifest()
    objects = objects or ObjectStore(cfg)
    objects.initialize()
    coordinator = _cleanup(cfg, scope, manifest, at, objects)
    try:
        report, session = loader.load_demo(cfg, objects=objects, scope=scope,
            manifest=current_day_manifest(manifest, at), offline=True, presentation="scenario-snapshots")
        if not report["matches_spec"] or len(session["patients"]) != 12:
            raise loader.LoaderError("Reset failed the strict twelve-resident outcome gate")
        captures = provision_capture(cfg, scope)
        with transaction(cfg, scope.nurse) as conn:
            current = watchlist(conn, cfg, now=at)
        cohort = {str(scope.patient_id(i)) for i in range(12)}
        visible = {row["patient_id"]: row for row in current["residents"] if row["patient_id"] in cohort}
        if len(visible) != 12 or any(visible[str(scope.patient_id(i))]["latest_verdict"]
                != resident["expected_assessment"]["verdict"] for i, resident in enumerate(manifest["residents"])):
            raise loader.LoaderError("Current watch list does not match all twelve authored outcomes")
        report["current_shift"] = current["shift"]
        report.update(presentation="current-day", demo_at=at.isoformat(), token_ttl_hours=48,
                      canonical_cohort_count=12, capture_people=captures, current_time_demo_ready=True)
        return report, session
    finally:
        coordinator.close()  # release the reset coordinator lock, including failure paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-at", help="Aware timestamp; defaults to current UTC second")
    args = parser.parse_args(argv)
    try:
        report, _ = reset_demo(demo_at=args.demo_at)
        directory = OUTPUT.parents[2] / "artifacts/baseline-demo"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "reset-report.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        print(json.dumps({"matches_spec": report["matches_spec"], "demo_at": report["demo_at"],
                          "scripted_residents": 12, "capture_people": 2,
                          "report": "artifacts/baseline-demo/reset-report.json"}))
        return 0
    except (loader.LoaderError, ValueError, psycopg.Error, ClientError):
        print("Reset incomplete: canonical data or service checks failed. Existing nonfixture data is preserved.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
