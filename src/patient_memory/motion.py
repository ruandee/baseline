"""BL-34 client-derived motion capture. No image, video or landmark payload is accepted."""
from uuid import uuid4

from psycopg.types.json import Jsonb

from patient_memory.baseline.assess import assess_modality, lock_assessment
from patient_memory.baseline.engine import (
    CORROBORATION_WINDOW,
    MIN_BASELINE,
    Check,
    FeatureSpec,
    Modality,
    ModalityResult,
    evaluate,
    register,
)
from patient_memory.baseline.signals import register_projection, signal_sources
from patient_memory.checks import care_gate, scoring_context
from patient_memory.consent import check_gate, require_consent
from patient_memory.domain import MotionInput, MotionResult
from patient_memory.errors import Problem
from patient_memory.storage import audit

PROTOCOL = "pose-chair-steps-v1"
FEATURES = ("sit_to_stand_s", "trunk_sway", "step_cadence_spm")
register(Modality("motion", (
    FeatureSpec("sit_to_stand_s", "motion", 1, 0.2, label="Time to half-rise", unit="s"),
    FeatureSpec("trunk_sway", "motion", 1, 0.01, label="Trunk sway", unit="ratio"),
    FeatureSpec("step_cadence_spm", "motion", -1, 3.0, label="Step cadence", unit="steps/min"),
)))


def quality(body: MotionInput) -> dict:
    q = body.quality
    fraction = q.confident_frames / q.total_frames if q.total_frames else 0.0
    reasons = []
    if q.duration_s < 8:
        reasons.append("too_short")
    if q.total_frames < 20 or fraction < 0.8:
        reasons.append("landmarks_unreliable")
    if body.features.sit_to_stand_s is None:
        reasons.append("rise_incomplete")
    if body.features.trunk_sway is None:
        reasons.append("shoulders_unavailable")
    if body.features.step_cadence_spm is None:
        reasons.append("steps_incomplete")
    return {**q.model_dump(), "confident_fraction": fraction, "reasons": reasons,
            "producer": "client-derived", "protocol": PROTOCOL}


def _evidence(conn, patient_id, row):
    if row["source_id"] is None:
        return ()
    ids = tuple(str(r["id"]) for r in conn.execute(
        "SELECT id FROM facts WHERE patient_id=%s AND source_id=%s ORDER BY start_offset",
        (patient_id, row["source_id"])).fetchall())
    if len(ids) != len(FEATURES):
        return ()
    try:
        signal_sources(conn, patient_id, Check(str(row["id"]), row["ts"], "", PROTOCOL,
                                               False, True, {}, "motion", ids))
    except Problem:
        return ()
    return ids


def _history(conn, patient_id, at):
    # Capture values stay immutable. A retracted/purged/superseded capture cannot calibrate.
    rows = conn.execute(
        "SELECT m.* FROM motion_checks m JOIN sources s ON s.tenant_id=m.tenant_id "
        "AND s.patient_id=m.patient_id AND s.id=m.source_id WHERE m.patient_id=%s "
        "AND m.usable AND m.ts<%s AND s.published_at IS NOT NULL "
        "AND s.retracted_at IS NULL AND s.purged_at IS NULL AND NOT EXISTS(SELECT FROM sources n "
        "WHERE n.tenant_id=s.tenant_id AND n.patient_id=s.patient_id AND n.supersedes=s.id "
        "AND n.published_at IS NOT NULL AND n.retracted_at IS NULL AND n.purged_at IS NULL) "
        "ORDER BY m.ts", (patient_id, at)).fetchall()
    return [Check(str(r["id"]), r["ts"], r["device_id"], PROTOCOL, r["is_baseline"], True,
                  {n: r[n] for n in FEATURES}, "motion", _evidence(conn, patient_id, r)) for r in rows]


def project(conn, cfg, patient_id, at):
    row = conn.execute(
        "SELECT * FROM motion_checks WHERE patient_id=%s AND usable AND ts<=%s AND ts>=%s "
        "ORDER BY ts DESC,id DESC LIMIT 1", (patient_id, at, at-CORROBORATION_WINDOW)).fetchone()
    if not row:
        return None
    ids = _evidence(conn, patient_id, row)
    if not ids:
        return None  # Never fall back to an older alarm when the latest capture was withdrawn.
    check = Check(str(row["id"]), row["ts"], row["device_id"], PROTOCOL, row["is_baseline"],
                  True, {n: row[n] for n in FEATURES}, "motion", ids)
    history = _history(conn, patient_id, check.ts)
    mode = "enrolled" if sum(c.is_baseline for c in history) >= MIN_BASELINE else "rolling"
    result = evaluate(check, history, mode, cfg)
    result.params["baseline_check_ids"] = list(result.baseline_ids)
    result.params["baseline_evidence_ids"] = sorted({
        fact for capture in history if capture.id in result.baseline_ids
        for fact in capture.evidence_ids})
    return ModalityResult("motion", check.ts, result, check.id, ids)


register_projection("motion", project)


def store(conn, cfg, identity, patient_id, body: MotionInput, objects, request_id):
    care = check_gate(conn, patient_id)
    if body.is_baseline and not care:
        raise Problem(422, "invalid_request", "Only care team can enroll a baseline")
    lock_assessment(conn, identity.tenant_id, patient_id)
    check_gate(conn, patient_id)
    require_consent(conn, patient_id, "motion_check")
    q = quality(body)
    usable = not q["reasons"]
    cid, sid = uuid4(), uuid4() if usable else None
    with scoring_context(conn, patient_id):
        row = conn.execute(
            "INSERT INTO motion_checks(tenant_id,patient_id,id,device_ts,device_id,is_baseline,"
            "usable,duration_s,total_frames,confident_frames,quality,sit_to_stand_s,trunk_sway,"
            "step_cadence_spm,source_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING *", (identity.tenant_id, patient_id, cid, body.device_ts, body.device_id,
                           body.is_baseline, usable, body.quality.duration_s,
                           body.quality.total_frames, body.quality.confident_frames, Jsonb(q),
                           *[getattr(body.features, n) for n in FEATURES], sid)).fetchone()
        change = assessment = None
        ids = ()
        if usable:
            raw = conn.execute("SELECT pm_motion_source_payload(%s,%s)::text AS payload",
                               (patient_id, cid)).fetchone()["payload"]
            key = f"{identity.tenant_id}/{patient_id}/{sid}.json"
            objects.put(key, raw.encode("utf-8"))
            conn.execute("SELECT pm_publish_motion_source(%s,%s,%s,%s)",
                         (patient_id, cid, raw, key))
            ids = _evidence(conn, patient_id, row)
            check = Check(str(cid), row["ts"], body.device_id, PROTOCOL, body.is_baseline, True,
                          body.features.model_dump(), "motion", ids)
            name = conn.execute("SELECT external_id FROM patients WHERE id=%s",
                                (patient_id,)).fetchone()["external_id"]
            change, assessment = assess_modality(
                conn, cfg, patient_id, identity.tenant_id, check, name,
                lambda scoped: _history(scoped, patient_id, row["ts"]))
    audit(conn, identity, patient_id, "create_motion_check", request_id)
    care = check_gate(conn, patient_id)
    require_consent(conn, patient_id, "motion_check")
    receipt = {"check_id": cid, "ts": row["ts"], "usable": usable}
    if not care:
        return receipt
    return MotionResult(**receipt, quality=q, features=body.features, source_id=sid,
                        evidence_ids=list(ids), change=change, assessment=assessment)


def read(conn, patient_id, check_id):
    care_gate(conn, patient_id)
    row = conn.execute("SELECT * FROM motion_checks WHERE patient_id=%s AND id=%s",
                       (patient_id, check_id)).fetchone()
    if not row or (row["usable"] and not _evidence(conn, patient_id, row)):
        raise Problem(404, "not_found")
    return MotionResult(check_id=row["id"], ts=row["ts"], usable=row["usable"],
                        features={n: row[n] for n in FEATURES}, quality=row["quality"],
                        source_id=row["source_id"], evidence_ids=list(_evidence(conn, patient_id, row)))
