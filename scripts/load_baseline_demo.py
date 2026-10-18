"""Load authored synthetic features and immutable sources; never invent audio provenance."""
import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from patient_memory.auth import Identity, synthetic_token
from patient_memory.baseline import engine
from patient_memory.baseline.assess import assess_check, lock_assessment
from patient_memory.config import Settings
from patient_memory.consent import grant_fixture_consent
from patient_memory.domain import SourceInput
from patient_memory.ingestion import digest, submit
from patient_memory.objects import ObjectStore
from patient_memory.storage import patient_access, transaction
from patient_memory.worker import run_once
from scripts.prepare_baseline_storylines import OUTPUT
from scripts.seed import uid

ROOT = Path(__file__).resolve().parents[1]
PRESENTATIONS = ("all-history", "scenario-snapshots")


class LoaderError(RuntimeError):
    """Safe operational explanation, never a provider response or credential."""


@dataclass(frozen=True)
class DemoScope:
    tenant_id: UUID = uid("tenant-0")
    importer_id: UUID = uid("0/importer")
    nurse_id: UUID = uid("0/nurse")

    def patient_id(self, index):
        return (uid(f"0/patient-{index}") if self.tenant_id == uid("tenant-0")
                else uuid5(self.tenant_id, f"baseline/patient-{index}"))

    @property
    def psw_id(self):
        return (uid("0/psw") if self.tenant_id == uid("tenant-0")
                else uuid5(self.tenant_id, "baseline/psw"))

    @property
    def psw(self):
        return Identity(self.psw_id, self.tenant_id)

    @property
    def importer(self):
        return Identity(self.importer_id, self.tenant_id)

    @property
    def nurse(self):
        return Identity(self.nurse_id, self.tenant_id)


def validate_manifest(manifest):
    if manifest.get("synthetic") is not True or manifest.get("schema_version") != 1:
        raise LoaderError("Only the version-one synthetic manifest is supported")
    residents = manifest.get("residents", [])
    if len(residents) != 12 or len({r["id"] for r in residents}) != 12:
        raise LoaderError("Expected twelve distinct synthetic residents")
    for resident in residents:
        if resident.get("synthetic") is not True or not resident["id"].startswith("synthetic-"):
            raise LoaderError("Non-synthetic resident rejected")
        if [c["day"] for c in resident["checks"]] != list(range(1, 31)):
            raise LoaderError("Expected thirty ordered authored checks per resident")
        for check in resident["checks"]:
            if (check.get("synthetic") is not True or check.get("usable") is not True
                    or check["mode"] != "resident" or check["is_baseline"]):
                raise LoaderError("Only usable authored synthetic resident features are supported")
            if set(check["features"]) != set(engine.FEATURES):
                raise LoaderError("Incomplete feature row")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                   for v in check["features"].values()):
                raise LoaderError("Feature values must be finite authored numbers")
            if datetime.fromisoformat(check["ts"]).tzinfo is None:
                raise LoaderError("Authored checks require explicit timezone offsets")
        for source in resident["sources"]:
            if source["source_system"] != "synthetic-baseline":
                raise LoaderError("Non-synthetic source rejected")
            SourceInput.model_validate(source)


def selected_checks(resident, presentation):
    if presentation not in PRESENTATIONS:
        raise LoaderError("Unknown presentation mode")
    end = resident["expected_assessment"]["day"] if presentation == "scenario-snapshots" else 30
    return [c for c in resident["checks"] if c["day"] <= end]


def validate_existing_sources(rows, resident):
    expected = {}
    for raw in resident["sources"]:
        payload = SourceInput.model_validate(raw).model_dump(mode="json")
        key = tuple(payload[k] for k in (
            "source_system", "external_document_id", "external_version_id"))
        expected[key] = digest(payload)
    for row in rows:
        payload = row["payload"]
        key = tuple(payload.get(k) for k in (
            "source_system", "external_document_id", "external_version_id"))
        if (key not in expected or row["external_version"] != key[2]
                or row["payload_hash"] != expected[key] or digest(payload) != expected[key]):
            raise LoaderError("Demo patient has an unlisted or conflicting immutable source/version")


def provision(cfg, scope, residents):
    """Admin setup only; immutable sources/checks and all scoring use pm_runtime afterward."""
    with psycopg.connect(cfg.admin_database_url, row_factory=dict_row) as conn:
        conn.execute("INSERT INTO tenants VALUES(%s,'synthetic-baseline-demo') ON CONFLICT DO NOTHING",
                     (scope.tenant_id,))
        for role, actor in (("importer", scope.importer_id), ("nurse", scope.nurse_id),
                            ("psw", scope.psw_id)):
            conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,%s) "
                         "ON CONFLICT DO NOTHING", (actor, scope.tenant_id, f"synthetic-{role}"))
        for index, resident in enumerate(residents):
            pid = scope.patient_id(index)
            old = conn.execute("SELECT external_id FROM patients WHERE tenant_id=%s AND id=%s",
                               (scope.tenant_id, pid)).fetchone()
            if old:
                # Reject unrelated sources before granting either demo principal access.
                rows = conn.execute("SELECT payload,payload_hash,external_version FROM sources "
                                    "WHERE tenant_id=%s AND patient_id=%s",
                                    (scope.tenant_id, pid)).fetchall()
                validate_existing_sources(rows, resident)
            if old and old["external_id"] != resident["display_name"]:
                occupied = conn.execute(
                    "SELECT EXISTS(SELECT FROM sources WHERE tenant_id=%s AND patient_id=%s) "
                    "OR EXISTS(SELECT FROM voice_checks WHERE tenant_id=%s AND patient_id=%s) AS yes",
                    (scope.tenant_id, pid, scope.tenant_id, pid)).fetchone()["yes"]
                if old["external_id"] != f"synthetic-patient-{index}" or occupied:
                    raise LoaderError("Existing patient identity/data is not an empty demo seed")
                conn.execute("UPDATE patients SET external_id=%s WHERE tenant_id=%s AND id=%s",
                             (resident["display_name"], scope.tenant_id, pid))
            conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s) "
                         "ON CONFLICT DO NOTHING", (pid, scope.tenant_id, resident["display_name"]))
            for role, actor in (("importer", scope.importer_id), ("nurse", scope.nurse_id),
                            ("psw", scope.psw_id)):
                # Never reactivate an explicitly revoked assignment.
                conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true) "
                             "ON CONFLICT DO NOTHING", (scope.tenant_id, pid, actor, role))
            # Decision 017: explicit synthetic consent; never overrides a later withdrawal.
            grant_fixture_consent(conn, scope.tenant_id, pid, scope.importer_id)


def _preflight(cfg, scope, residents, presentation):
    with transaction(cfg, scope.importer) as conn:
        for index, resident in enumerate(residents):
            pid = scope.patient_id(index)
            patient_access(conn, pid, write=True)
            allowed = {uuid5(pid, f"baseline-v1/day-{c['day']}")
                       for c in selected_checks(resident, presentation)}
            rows = conn.execute("SELECT id,synthetic FROM voice_checks WHERE patient_id=%s",
                                (pid,)).fetchall()
            if any(not row["synthetic"] or row["id"] not in allowed for row in rows):
                raise LoaderError("Existing checks exceed this mode; use a separate/reset demo scope")
            sources = conn.execute("SELECT payload,payload_hash,external_version FROM sources "
                                   "WHERE patient_id=%s", (pid,)).fetchall()
            validate_existing_sources(sources, resident)


def _publish_sources(cfg, scope, residents, objects):
    jobs = []
    for index, resident in enumerate(residents):
        for raw in resident["sources"]:
            source = SourceInput.model_validate(raw)
            with transaction(cfg, scope.importer) as conn:
                result = submit(conn, scope.importer, scope.patient_id(index), source,
                                "baseline-v1/" + source.external_document_id, objects)
                jobs.append(UUID(result["job_id"]))
    # All source publication precedes every assessment: publication bumps revisions and
    # invalidates copied assessment evidence. Never interleave these two phases.
    for _ in range(max(10, 10 * len(jobs))):
        with transaction(cfg, scope.importer) as conn:
            states = conn.execute(
                "SELECT j.status,s.published_at,s.canonical_text,s.retracted_at,s.purged_at "
                "FROM jobs j JOIN sources s ON s.tenant_id=j.tenant_id AND s.patient_id=j.patient_id "
                "AND s.id=j.source_id WHERE j.id=ANY(%s)", (jobs,)).fetchall()
        if any(r["retracted_at"] or r["purged_at"] for r in states):
            raise LoaderError("An immutable demo source was withdrawn; use a fresh/reset demo scope")
        if len(states) == len(jobs) and all(r["status"] == "completed" for r in states):
            if any(not r["published_at"] or r["canonical_text"] is None for r in states):
                raise LoaderError("A completed demo job has no published canonical evidence")
            return
        if any(r["status"] in ("failed", "cancelled") for r in states):
            raise LoaderError("A demo source could not be published; inspect job error codes")
        if not run_once(cfg, scope.importer, objects):
            raise LoaderError("Source jobs are pending/retrying; rerun after the worker completes")
    raise LoaderError("Source publication exceeded the bounded worker passes")


def _context_report(cfg, scope, residents):
    reports = []
    with transaction(cfg, scope.nurse) as conn:
        for index, resident in enumerate(residents):
            pid = scope.patient_id(index)
            patient_access(conn, pid)
            for expected in resident["expected_context"]:
                rows = conn.execute(
                    "SELECT t.tag,t.quote,t.start_offset,t.end_offset,t.fact_id,s.id AS source_id,"
                    "f.quote AS fact_quote,f.start_offset AS fact_start,f.end_offset AS fact_end,"
                    "s.canonical_text FROM context_tags t JOIN sources s ON s.tenant_id=t.tenant_id "
                    "AND s.patient_id=t.patient_id AND s.id=t.source_id "
                    "JOIN facts f ON f.tenant_id=t.tenant_id AND f.patient_id=t.patient_id "
                    "AND f.source_id=t.source_id AND f.id=t.fact_id WHERE t.patient_id=%s "
                    "AND s.payload->>'external_document_id'=%s AND t.tag=%s "
                    "AND s.published_at IS NOT NULL AND s.retracted_at IS NULL AND s.purged_at IS NULL "
                    "ORDER BY t.start_offset,t.id",
                    (pid, expected["source_document_id"], expected["tag"])).fetchall()
                matched = [r for r in rows if r["canonical_text"][r["start_offset"]:r["end_offset"]]
                           == r["quote"] and r["fact_id"]
                           and r["canonical_text"][r["fact_start"]:r["fact_end"]] == r["fact_quote"]
                           and r["fact_start"] <= r["start_offset"] < r["end_offset"] <= r["fact_end"]
                           and expected.get("quote", "") in r["quote"]]
                reports.append({"resident": resident["id"], "tag": expected["tag"],
                                "source_document_id": expected["source_document_id"],
                                "exact_span_verified": bool(matched),
                                "quotes": [r["quote"] for r in matched]})
    return reports


def _backfill_notes(cfg, scope, residents):
    # BL-10 owns retrieval, provider work and publication transactions. Never call it
    # while holding a loader transaction or duplicate its extraction rules here.
    from patient_memory.baseline.notes import extract_pending_notes
    for index, resident in enumerate(residents):
        if not any(s["kind"] == "nursing_note" for s in resident["sources"]):
            continue
        for _ in range(10):
            result = extract_pending_notes(cfg, scope.importer, scope.patient_id(index))
            if result.processed == 0:
                break
        else:
            raise LoaderError("Note context backfill exceeded its bounded batches")


def _source_evidence(cfg, scope, residents):
    evidence = []
    with transaction(cfg, scope.nurse) as conn:
        for index, resident in enumerate(residents):
            pid = scope.patient_id(index)
            patient_access(conn, pid)
            for source in resident["sources"]:
                rows = conn.execute(
                    "SELECT f.id,f.quote,f.start_offset,f.end_offset,s.canonical_text "
                    "FROM sources s JOIN facts f ON f.tenant_id=s.tenant_id "
                    "AND f.patient_id=s.patient_id AND f.source_id=s.id "
                    "WHERE s.patient_id=%s AND s.payload->>'external_document_id'=%s "
                    "AND s.published_at IS NOT NULL AND s.retracted_at IS NULL "
                    "AND s.purged_at IS NULL ORDER BY f.start_offset,f.id",
                    (pid, source["external_document_id"])).fetchall()
                if not rows or any(r["canonical_text"][r["start_offset"]:r["end_offset"]]
                                   != r["quote"] for r in rows):
                    raise LoaderError("Published source has missing or invalid exact-span evidence")
                evidence.append({"resident": resident["id"], "kind": source["kind"],
                                 "source_document_id": source["external_document_id"],
                                 "recorded_at": source["recorded_at"],
                                 "facts": [{"evidence_id": str(r["id"]), "quote": r["quote"]}
                                           for r in rows]})
    return evidence


def _score(cfg, scope, index, resident, check, signature):
    pid = scope.patient_id(index)
    cid = uuid5(pid, f"baseline-v1/day-{check['day']}")
    ts = datetime.fromisoformat(check["ts"])
    features = check["features"]
    with transaction(cfg, scope.nurse) as conn:
        patient_access(conn, pid)
        lock_assessment(conn, scope.tenant_id, pid)  # tenant then patient, like assess_check
        old = conn.execute("SELECT * FROM voice_checks WHERE patient_id=%s AND id=%s",
                           (pid, cid)).fetchone()
        if old:
            expected = {**features, **{k: check[k] for k in (
                "device_id", "mode", "prompt_version", "is_baseline", "usable", "synthetic")}}
            if (old["ts"] != ts or any(old[k] != value for k, value in expected.items())
                    or old["quality"] != {"provenance": "authored_synthetic_features",
                                          "audio_validated": False}
                    or old["transcript"] is not None or old["words"] is not None):
                raise LoaderError("Immutable authored check differs; reset or use a fresh demo scope")
        else:
            conn.execute(
                "INSERT INTO voice_checks(tenant_id,patient_id,id,ts,device_id,mode,prompt_version,"
                "is_baseline,usable,quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,"
                "synthetic) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,%s,true)",
                (scope.tenant_id, pid, cid, ts, check["device_id"], check["mode"],
                 check["prompt_version"], check["is_baseline"],
                 Jsonb({"provenance": "authored_synthetic_features", "audio_validated": False}),
                 *[features[name] for name in engine.FEATURES]))
        revision = conn.execute("SELECT revision FROM patients WHERE id=%s", (pid,)).fetchone()["revision"]
        existing = conn.execute(
            "SELECT * FROM assessments WHERE patient_id=%s AND check_id=%s "
            "AND params->>'loader_signature'=%s AND (params->>'source_revision')::bigint=%s "
            "AND COALESCE((params->>'invalidated')::boolean,false)=false "
            "ORDER BY created_at DESC LIMIT 1", (pid, cid, signature, revision)).fetchone()
        if existing:
            return {"day": check["day"], "status": existing["change_status"],
                    "verdict": existing["verdict"], "suggested_action": existing["suggested_action"]}
        change, assessment = assess_check(
            conn, cfg, pid, scope.tenant_id, cid, ts, check["device_id"], check["prompt_version"],
            check["is_baseline"], features, resident["display_name"])
        conn.execute("UPDATE assessments SET params=params || %s WHERE patient_id=%s AND id=%s",
                     (Jsonb({"loader_signature": signature}), pid, UUID(assessment["id"])))
        return {"day": check["day"], "status": change["status"], "verdict": assessment["verdict"],
                "suggested_action": assessment["suggested_action"]}


def load_demo(cfg=None, *, objects=None, manifest=None, scope=None, offline=False,
              presentation="all-history"):
    cfg, scope = cfg or Settings(), scope or DemoScope()
    if offline:
        cfg = cfg.model_copy(update={"provider": "stub"})
    if manifest is None:
        manifest = json.loads(OUTPUT.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    if presentation not in PRESENTATIONS:
        raise LoaderError("Unknown presentation mode")
    if find_spec("patient_memory.baseline.notes") is None:
        raise LoaderError("BL-10 note publication is required before loading storylines")
    residents = manifest["residents"]
    provision(cfg, scope, residents)
    _preflight(cfg, scope, residents, presentation)
    objects = objects or ObjectStore(cfg)
    objects.initialize()
    _publish_sources(cfg, scope, residents, objects)
    _backfill_notes(cfg, scope, residents)
    source_evidence = _source_evidence(cfg, scope, residents)
    context = _context_report(cfg, scope, residents)
    if not all(r["exact_span_verified"] for r in context):
        raise LoaderError("Published source context is incomplete; run BL-10 extraction then retry")
    signature = digest({"manifest": manifest, "policy": getattr(engine, "POLICY_VERSION", "v1"),
                        "settings": {name: getattr(cfg, name) for name in (
                            "z_threshold", "provisional_z", "min_features", "ewma_lambda",
                            "cusum_k", "cusum_h", "no_escalate_patients", "escalation_budget",
                            "shift_timezone")}})
    outcomes, roster = [], []
    for index, resident in enumerate(residents):
        checks = selected_checks(resident, presentation)
        trajectory = [_score(cfg, scope, index, resident, check, signature) for check in checks]
        expected = resident["expected_assessment"]
        snapshot = next(row for row in trajectory if row["day"] == expected["day"])
        matches = all(snapshot[k] == expected[k] for k in ("verdict", "suggested_action"))
        outcomes.append({"resident": resident["id"], "snapshot_at": expected["as_of"],
                         "expected": {k: expected[k] for k in ("verdict", "suggested_action")},
                         "actual_snapshot": snapshot, "latest": trajectory[-1],
                         "matches_spec": matches, "checks_loaded": len(checks)})
        roster.append({"id": str(scope.patient_id(index)), "reference": resident["id"],
                       "name": resident["display_name"], "synthetic": True,
                       "last_check_at": checks[-1]["ts"]})
    report = {"presentation": presentation, "offline": cfg.provider == "stub",
              "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
              "policy": getattr(engine, "POLICY_VERSION", "v1"),
              "checks_loaded": sum(r["checks_loaded"] for r in outcomes),
              "sources_published_before_assessments": True, "real_audio_validated": False,
              "knowledge_semantics": "retrospective event-time replay with currently published evidence",
              "shared_event_time": presentation == "all-history", "current_time_demo_ready": False,
              "source_evidence": source_evidence, "context": context, "outcomes": outcomes,
              "matches_spec": all(r["matches_spec"] for r in outcomes)}
    session = {"token": synthetic_token(scope.nurse, cfg), "tenant_id": str(scope.tenant_id),
               "patients": roster, "presentation": presentation}
    return report, session


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--presentation", choices=PRESENTATIONS, required=True)
    args = parser.parse_args(argv)
    try:
        report, session = load_demo(offline=args.offline, presentation=args.presentation)
        directory = ROOT / "artifacts" / "baseline-demo"
        directory.mkdir(parents=True, exist_ok=True)
        for name, payload in (("report.json", report), ("session.json", session)):
            (directory / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        # The nurse token is written only to ignored artifacts, never stdout or Git.
        print(json.dumps({"matches_spec": report["matches_spec"], "checks_loaded": report["checks_loaded"],
                          "presentation": args.presentation, "report": "artifacts/baseline-demo/report.json",
                          "session": "artifacts/baseline-demo/session.json"}))
        return 0 if report["matches_spec"] else 1
    except LoaderError as exc:
        print(json.dumps({"status": "incomplete", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
