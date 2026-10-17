"""Score a stored check, decide the verdict and persist the assessment."""
from datetime import datetime
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from patient_memory.baseline.engine import FEATURES, MIN_BASELINE, Check, evaluate
from patient_memory.baseline.verdict import (
    ACTION_LABELS,
    TAG_LABELS,
    apply_profile,
    decide,
    sbar_template,
    shift_bounds,
)
from patient_memory.config import Settings


def valid_tags(conn, patient_id: UUID, at: datetime) -> list[dict]:
    """Tags valid at `at`; tags of retracted or purged sources never count (decision 007)."""
    rows = conn.execute(
        "SELECT t.id,t.kind,t.tag,t.fact_id,t.quote,t.valid_from,t.valid_to,t.source_id,"
        "s.payload->>'kind' AS source_kind,s.recorded_at FROM context_tags t "
        "JOIN sources s ON s.tenant_id=t.tenant_id AND s.patient_id=t.patient_id AND s.id=t.source_id "
        "WHERE t.patient_id=%s AND s.retracted_at IS NULL AND s.purged_at IS NULL "
        "AND s.published_at IS NOT NULL "
        "AND NOT EXISTS(SELECT FROM sources amended WHERE amended.tenant_id=s.tenant_id "
        "AND amended.patient_id=s.patient_id AND amended.supersedes=s.id "
        "AND amended.published_at IS NOT NULL AND amended.retracted_at IS NULL "
        "AND amended.purged_at IS NULL) "
        "AND t.valid_from<=%s AND (t.valid_to IS NULL OR t.valid_to>%s) ORDER BY t.valid_from",
        (patient_id, at, at)).fetchall()
    return [{
        "kind": r["kind"], "tag": r["tag"], "label": TAG_LABELS.get(r["tag"], r["tag"]),
        "context_tag_id": str(r["id"]), "source_id": str(r["source_id"]),
        "valid_to": r["valid_to"].isoformat() if r["valid_to"] else None,
        "evidence_id": str(r["fact_id"]) if r["fact_id"] else None,
        "quote": r["quote"], "match": [0, len(r["quote"])], "source_kind": r["source_kind"],
        "recorded_at": r["recorded_at"].isoformat(), "valid_from": r["valid_from"].isoformat(),
    } for r in rows]


def escalations_used(conn, now: datetime, cfg: Settings) -> int:
    start, end = shift_bounds(now, cfg.shift_timezone)
    # Counted by when the clip was recorded, so history loaded in bulk never uses today's budget.
    return conn.execute(
        "SELECT count(*) AS n FROM assessments a JOIN voice_checks v ON v.tenant_id=a.tenant_id "
        "AND v.patient_id=a.patient_id AND v.id=a.check_id WHERE a.verdict='escalate' "
        "AND v.ts>=%s AND v.ts<%s AND COALESCE((a.params->>'over_budget')::boolean,false)=false "
        "AND COALESCE((a.params->>'no_escalate')::boolean,false)=false", (start, end)
    ).fetchone()["n"]


def _history(conn, patient_id: UUID, before: datetime, prompt_version: str) -> list[Check]:
    rows = conn.execute(
        "SELECT id,ts,device_id,prompt_version,is_baseline,usable,speech_rate_wpm,pause_ratio,"
        "mean_pause_s,f0_median_hz FROM voice_checks WHERE patient_id=%s AND usable AND ts<%s "
        "AND prompt_version=%s ORDER BY ts DESC",
        (patient_id, before, prompt_version)).fetchall()
    return [Check(str(r["id"]), r["ts"], r["device_id"], r["prompt_version"], r["is_baseline"],
                  r["usable"], {n: r[n] for n in FEATURES}) for r in rows]


def change_payload(assessment, mode: str) -> dict:
    per_feature = {name: {"value": s.value, "median": s.median, "scale": s.scale, "z": s.z,
                          "ewma": s.ewma, "cusum": s.cusum}
                   for name, s in assessment.features.items()}
    return {"status": assessment.status, "mode": mode, "fused_z": assessment.fused,
            "per_feature": per_feature, "params": assessment.params}


def assess_check(conn, cfg: Settings, patient_id: UUID, tenant_id: UUID, check_id: UUID,
                 ts: datetime, device_id: str, prompt_version: str, is_baseline: bool,
                 features: dict, display_name: str) -> tuple[dict, dict]:
    """Returns the (change, assessment) payloads of POST /checks and stores the assessment row."""
    history = _history(conn, patient_id, ts, prompt_version)
    mode = "enrolled" if sum(c.is_baseline for c in history) >= MIN_BASELINE else "rolling"
    check = Check(str(check_id), ts, device_id, prompt_version, is_baseline, True, dict(features))
    result = evaluate(check, history, mode, cfg)
    tags = valid_tags(conn, patient_id, ts)
    decision = decide(result.status, result.fused, [(t["kind"], t["tag"]) for t in tags])
    no_escalate = str(patient_id) in {p.strip() for p in cfg.no_escalate_patients.split(",")}
    decision, flags = apply_profile(
        decision, escalations_used=escalations_used(conn, ts, cfg),
        budget=cfg.escalation_budget, no_escalate=no_escalate)
    change = change_payload(result, mode)
    sbar = sbar_template(display_name, result.status, decision, str(check_id),
                         change["per_feature"], tags)
    reasons = [t for t in tags if t["kind"] == "amplifier"] if decision.verdict in (
        "escalate", "watch") and any(t["kind"] == "amplifier" for t in tags) else (
        tags if decision.verdict == "explained" else [])
    source_revision = conn.execute("SELECT revision FROM patients WHERE id=%s",
                                   (patient_id,)).fetchone()["revision"]
    assessment_id = uuid4()
    conn.execute(
        "INSERT INTO assessments(tenant_id,patient_id,id,check_id,change_status,fused_z,features,"
        "params,verdict,reasons,suggested_action,sbar) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (tenant_id, patient_id, assessment_id, check_id, result.status, result.fused,
         Jsonb(change["per_feature"]), Jsonb({**result.params, "mode": mode, "source_revision": source_revision,
                                                "source_ids": [t["source_id"] for t in tags], **flags}),
         decision.verdict, Jsonb(reasons), decision.action, Jsonb(sbar) if sbar else None))
    payload = {"id": str(assessment_id), "verdict": decision.verdict,
               "suggested_action": decision.action,
               "suggested_action_label": ACTION_LABELS[decision.action], "reasons": reasons,
               **flags}
    return change, payload
