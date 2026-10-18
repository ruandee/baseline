"""BL-35: explicit resting observations, never inferred rest or a clinical classifier."""
import math
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from patient_memory.baseline.assess import assess_modality, lock_assessment
from patient_memory.baseline.engine import (
    CORROBORATION_WINDOW,
    POLICY_VERSION,
    Check,
    FeatureSpec,
    Modality,
    ModalityResult,
    evaluate,
    register,
)
from patient_memory.baseline.signals import register_projection
from patient_memory.ingestion import digest
from patient_memory.storage import check_writer_access

PROMPT = "resting-observation-v1"
VITALS = register(Modality("vitals", (
    FeatureSpec("resting_hr_bpm", "vitals", 0, 3.0, "Resting heart rate", "beats/min"),
    FeatureSpec("resting_rr_bpm", "vitals", 1, 1.0, "Resting respiratory rate", "breaths/min"),
), min_features=1, cusum_min_features=1))
UNITS = {"resting_hr_bpm": {"bpm", "beats/min", "/min"},
         "resting_rr_bpm": {"breaths/min", "/min"}}


def observation_checks(rows, patient_id):
    """Exact event-time groups; no carry-forward, guessed units/rest or conflict resolution."""
    groups = defaultdict(list)
    for row in rows:
        if row["concept"] in UNITS and row["valid_from"] is not None:
            groups[row["valid_from"]].append(row)
    checks = []
    for at, samples in sorted(groups.items()):
        values, evidence_ids = {}, []
        for name in UNITS:
            matching = [row for row in samples if row["concept"] == name]
            valid = []
            for row in matching:
                try:
                    value = float(row["value"])
                except (ValueError, TypeError):
                    continue
                if (math.isfinite(value) and value > 0
                        and str(row["unit"] or "").strip().casefold() in UNITS[name]):
                    valid.append((row, value))
            # A conflicting or invalid documented measurement is unknown, not a normal value.
            if len(valid) != len(matching) or len({value for _, value in valid}) != 1:
                values[name] = None
            else:
                values[name] = valid[0][1]
                evidence_ids.extend(str(row["id"]) for row, _ in valid)
        cid = uuid5(NAMESPACE_URL, f"{patient_id}/{PROMPT}/{at.isoformat()}")
        checks.append(Check(str(cid), at, "documented-resting-observations", PROMPT, False,
                            any(v is not None for v in values.values()), values, "vitals",
                            tuple(sorted(set(evidence_ids)))))
    return checks


def load_checks(conn, patient_id, at):
    rows = conn.execute(
        "SELECT f.id,f.concept,f.value,f.unit,f.valid_from,f.valid_to FROM facts f JOIN sources s "
        "ON s.tenant_id=f.tenant_id AND s.patient_id=f.patient_id AND s.id=f.source_id "
        "WHERE f.patient_id=%s AND f.concept=ANY(%s) AND f.polarity='present' "
        "AND f.experiencer='patient' AND f.valid_from IS NOT NULL AND f.valid_from<=%s "
        "AND s.payload->>'kind'='observation' AND s.payload->>'author_role'='system' "
        "AND s.recorded_at<=clock_timestamp() AND s.published_at IS NOT NULL "
        "AND s.retracted_at IS NULL AND s.purged_at IS NULL "
        "AND NOT EXISTS(SELECT FROM sources newer WHERE newer.tenant_id=s.tenant_id "
        "AND newer.patient_id=s.patient_id AND newer.supersedes=s.id "
        "AND newer.published_at IS NOT NULL AND newer.retracted_at IS NULL AND newer.purged_at IS NULL) "
        "ORDER BY f.valid_from,f.id", (patient_id, list(UNITS), at)).fetchall()
    return observation_checks(rows, patient_id)


def projection(conn, cfg, patient_id, at):
    if conn.execute("SELECT pm_safety_tenant() AS safety").fetchone()["safety"]:
        return None
    checks = load_checks(conn, patient_id, at)
    if not checks or not checks[-1].usable or checks[-1].ts < at-CORROBORATION_WINDOW:
        return None
    check = checks[-1]
    expired = conn.execute(
        "SELECT id FROM facts WHERE patient_id=%s AND id=ANY(%s::uuid[]) AND valid_to IS NOT NULL AND valid_to<=%s",
        (patient_id, list(check.evidence_ids), at)).fetchall()
    if expired:
        return None
    result = evaluate(check, checks[:-1], "rolling", cfg)
    baseline_ids = set(result.baseline_ids)
    result = replace(result, params={**result.params, "capture_adapter": PROMPT,
                     "baseline_check_ids": list(result.baseline_ids),
                     "baseline_evidence_ids": sorted({eid for earlier in checks
                         if earlier.id in baseline_ids for eid in earlier.evidence_ids}),
                     "measurement_attribution": "documented_system_observation",
                     "threshold_status": "engineering_unvalidated",
                     "feature_meta": {f.name: {"label": f.label, "unit": f.unit} for f in VITALS.features},
                     "unavailable_features": [name for name, value in check.features.items() if value is None]})
    return ModalityResult("vitals", check.ts, result, check.id, check.evidence_ids)


register_projection("vitals", projection)


def refresh_vitals(conn, cfg, identity, patient_id, at=None):
    """Idempotent new knowledge snapshot; never mutate or revive an older assessment."""
    check_writer_access(conn, patient_id)
    lock_assessment(conn, identity.tenant_id, patient_id)
    check_writer_access(conn, patient_id)
    at = at or datetime.now(UTC)
    snapshot = projection(conn, cfg, patient_id, at)
    if snapshot is None:
        return None
    checks = load_checks(conn, patient_id, at)
    check = checks[-1]
    patient = conn.execute("SELECT * FROM patients WHERE id=%s", (patient_id,)).fetchone()
    signature = digest({"check": check, "history": checks[:-1], "revision": patient["revision"],
                        "policy": POLICY_VERSION, "adapter": PROMPT,
                        "params": snapshot.assessment.params})
    existing = conn.execute(
        "SELECT id FROM assessments WHERE patient_id=%s AND check_id=%s "
        "AND params->>'modality'='vitals' AND params->>'vitals_signature'=%s "
        "AND COALESCE((params->>'invalidated')::boolean,false)=false "
        "AND (params->>'source_revision')::bigint=%s ORDER BY created_at DESC LIMIT 1",
        (patient_id, check.id, signature, patient["revision"])).fetchone()
    if existing:
        return {"assessment_id": str(existing["id"]), "reused": True}
    _, assessment = assess_modality(conn, cfg, patient_id, identity.tenant_id, check,
                                   patient["external_id"], lambda scoped: checks[:-1])
    conn.execute("UPDATE assessments SET params=jsonb_set(params || %s,"
                 "'{modality_results,vitals,params}',%s) WHERE patient_id=%s AND id=%s",
                 (Jsonb({"vitals_signature": signature, "capture_adapter": PROMPT,
                         "threshold_status": "engineering_unvalidated"}),
                  Jsonb(snapshot.assessment.params), patient_id, assessment["id"]))
    return {"assessment_id": assessment["id"], "reused": False}
