"""Score a stored check, decide the verdict and persist the assessment."""
from datetime import datetime
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from patient_memory.baseline.engine import (
    FEATURES,
    MIN_BASELINE,
    REGISTRY,
    Assessment,
    Check,
    FeatureScore,
    ModalityResult,
    combine,
    combined_payload,
    evaluate,
)
from patient_memory.baseline.sbar import sbar_template
from patient_memory.baseline.signals import features_for
from patient_memory.baseline.verdict import (
    ACTION_LABELS,
    TAG_LABELS,
    apply_profile,
    decide,
    shift_bounds,
)
from patient_memory.config import Settings
from patient_memory.ingestion import lock_patient
from patient_memory.storage import check_writer_access

COUNTING_PROMPT = "count20-days-v1"
FREE_CONVERSATION = "free-conversation-v1"


def engine_settings(cfg: Settings, prompt_version: str) -> Settings:
    """Free conversation uses its own, higher z threshold (PM_Z_THRESHOLD_FREE)."""
    if prompt_version == FREE_CONVERSATION:
        return cfg.model_copy(update={"z_threshold": cfg.z_threshold_free})
    return cfg


def lock_assessment(conn, tenant_id: UUID, patient_id: UUID):
    """All admission paths, including synthetic fixture scoring, use this lock order."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                 ("baseline-budget/" + str(tenant_id),))
    lock_patient(conn, patient_id)


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
    if conn.execute("SELECT nullif(current_setting('pm.check_scoring_patient',true),'') AS p"
                    ).fetchone()["p"]:
        return conn.execute("SELECT pm_check_escalations(%s,%s) AS n", (start, end)
                            ).fetchone()["n"]
    # Counted by when the clip was recorded, so history loaded in bulk never uses today's budget.
    return conn.execute(
        "SELECT count(*) AS n FROM assessments a JOIN voice_checks v ON v.tenant_id=a.tenant_id "
        "AND v.patient_id=a.patient_id AND v.id=a.check_id WHERE a.verdict='escalate' "
        "AND v.session_id IS NULL AND v.ts>=%s AND v.ts<%s AND COALESCE((a.params->>'over_budget')::boolean,false)=false "
        "AND COALESCE((a.params->>'no_escalate')::boolean,false)=false", (start, end)
    ).fetchone()["n"]


def _history(conn, patient_id: UUID, before: datetime, prompt_version: str,
             session_id: UUID | None = None) -> list[Check]:
    # A KAZE session is compared only with its own arm-time baseline; checks outside a session
    # never use session clips (decision 018).
    rows = conn.execute(
        "SELECT id,ts,device_id,prompt_version,is_baseline,usable,speech_rate_wpm,pause_ratio,"
        "mean_pause_s,f0_median_hz FROM voice_checks WHERE patient_id=%s AND usable AND ts<%s "
        "AND prompt_version=%s AND session_id IS NOT DISTINCT FROM %s ORDER BY ts DESC",
        (patient_id, before, prompt_version, session_id)).fetchall()
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
                 features: dict, display_name: str,
                 session_id: UUID | None = None) -> tuple[dict, dict]:
    """Speech adapter: scoped immutable voice history enters the shared signal assessment."""
    check = Check(str(check_id), ts, device_id, prompt_version, is_baseline, True, dict(features),
                  evidence_ids=("check:" + str(check_id),))
    return assess_modality(conn, cfg, patient_id, tenant_id, check, display_name,
                           lambda scoped: _history(scoped, patient_id, ts, prompt_version, session_id),
                           session_id=session_id)


def _latest_modalities(conn, patient_id, check, revision):
    """Latest known result per other modality, not the latest *flagged* result.

    Event time, not assessment creation time, controls the as-of boundary. The current revision
    and RLS protect source lifecycle and tenant/patient access. KAZE sessions never corroborate
    a care assessment; legacy flat rows derive event time/session identity from voice_checks.
    """
    rows = conn.execute(
        "SELECT DISTINCT ON (modality) * FROM (SELECT a.*,"
        " COALESCE(a.params->>'modality','speech') AS modality,"
        " COALESCE((a.params->>'signal_ts')::timestamptz,v.ts) AS signal_ts"
        " FROM assessments a LEFT JOIN voice_checks v ON v.tenant_id=a.tenant_id"
        " AND v.patient_id=a.patient_id AND v.id=a.check_id WHERE a.patient_id=%s"
        " AND a.check_id<>%s AND COALESCE(a.params->>'modality','speech')<>%s"
        " AND a.params->>'session_id' IS NULL AND v.session_id IS NULL"
        " AND COALESCE((a.params->>'invalidated')::boolean,false)=false"
        " AND (a.params->>'source_revision')::bigint=%s) eligible"
        " WHERE signal_ts<=%s AND modality=ANY(%s)"
        " ORDER BY modality,signal_ts DESC,created_at DESC,id DESC",
        (patient_id, UUID(check.id), check.modality, revision, check.ts, list(REGISTRY))).fetchall()
    results = []
    for row in rows:
        modality = row["modality"]
        specs = {f.name: f for f in REGISTRY[modality].features}
        scores = {}
        for name, raw in features_for(row["features"], modality).items():
            if name not in specs:
                continue
            z = raw["z"]
            direction = specs[name].direction
            scores[name] = FeatureScore(raw["value"], raw["median"], raw["scale"], z,
                                        abs(z) if direction == 0 else direction * z,
                                        raw["ewma"], raw["cusum"])
        params = row["params"]
        results.append(ModalityResult(modality, row["signal_ts"], Assessment(
            params.get("modality_status", row["change_status"]), scores,
            params.get("modality_fused_z", row["fused_z"]), (),
            params.get("engine_params", params)), str(row["check_id"]),
            tuple(params.get("signal_evidence_ids", ()))))
    return results


def assess_modality(conn, cfg: Settings, patient_id: UUID, tenant_id: UUID, check: Check,
                    display_name: str, history_loader, *, session_id: UUID | None = None):
    """Adapter admission hook: authorize/lock before loading history and publish atomically.

    Capture adapters own immutable check storage and scoped history retrieval. There is no
    generic public ingestion route. Evidence IDs must refer to actually resolvable stored
    evidence; absence withholds a non-speech draft, never invents a citation.
    """
    check_writer_access(conn, patient_id)
    lock_assessment(conn, tenant_id, patient_id)
    check_writer_access(conn, patient_id)
    if check.ts.tzinfo is None:
        raise ValueError("signal event time must be timezone-aware")
    if session_id is not None and check.modality != "speech":
        raise ValueError("KAZE sessions use only the speech protocol")
    history = history_loader(conn)
    mode = "enrolled" if sum(c.is_baseline for c in history) >= MIN_BASELINE else "rolling"
    result = evaluate(check, history, mode, engine_settings(cfg, check.prompt_version))
    source_revision = conn.execute("SELECT revision FROM patients WHERE id=%s",
                                   (patient_id,)).fetchone()["revision"]
    other = _latest_modalities(conn, patient_id, check, source_revision) if session_id is None else []
    combined = combine([*other, ModalityResult(check.modality, check.ts, result, check.id,
                                               check.evidence_ids)], check.ts)
    modal = combined_payload(combined)
    tags = valid_tags(conn, patient_id, check.ts)
    decision = decide(combined.verdict_status, combined.fused, [(t["kind"], t["tag"]) for t in tags])
    no_escalate = str(patient_id) in {p.strip() for p in cfg.no_escalate_patients.split(",")}
    decision, flags = apply_profile(
        decision, escalations_used=escalations_used(conn, check.ts, cfg),
        budget=cfg.escalation_budget, no_escalate=no_escalate)
    change = change_payload(result, mode)
    change.update(modal)
    reasons = [t for t in tags if t["kind"] == "amplifier"] if decision.verdict in (
        "escalate", "watch") and any(t["kind"] == "amplifier" for t in tags) else (
        tags if decision.verdict == "explained" else [])
    non_speech_flag = check.modality != "speech" or any(
        name != "speech" and entry["current"] and entry["status"] in ("provisional", "change")
        for name, entry in modal["modalities"].items())
    sbar = None if non_speech_flag else sbar_template(
        display_name, combined.verdict_status, decision, check.id, change["per_feature"], reasons)
    params = {**result.params, "mode": mode, "prompt_version": check.prompt_version,
              "signal_ts": check.ts.isoformat(), "session_id": str(session_id) if session_id else None,
              "modality_status": result.status, "modality_fused_z": result.fused,
              "signal_evidence_ids": list(check.evidence_ids), "engine_params": result.params,
              "verdict_status": combined.verdict_status,
              "modality_results": {name: {k: v for k, v in entry.items() if k != "per_feature"}
                                   for name, entry in modal["modalities"].items()},
              "draft_status": "unavailable_multimodal_evidence" if non_speech_flag else "speech",
              "source_revision": source_revision, "source_ids": [t["source_id"] for t in tags], **flags}
    assessment_id = uuid4()
    conn.execute(
        "INSERT INTO assessments(tenant_id,patient_id,id,check_id,change_status,fused_z,features,"
        "params,verdict,reasons,suggested_action,sbar,corroborated)"
        " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (tenant_id, patient_id, assessment_id, UUID(check.id), combined.status, combined.fused,
         Jsonb({name: entry["per_feature"] for name, entry in modal["modalities"].items()}), Jsonb(params),
         decision.verdict, Jsonb(reasons), decision.action, Jsonb(sbar) if sbar else None,
         combined.corroborated))
    payload = {"id": str(assessment_id), "verdict": decision.verdict,
               "suggested_action": decision.action,
               "suggested_action_label": ACTION_LABELS[decision.action], "reasons": reasons,
               "corroborated": combined.corroborated, "draft_status": params["draft_status"], **flags}
    return change, payload
