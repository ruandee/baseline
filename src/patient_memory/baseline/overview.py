"""Read models for the watch list and the resident page (docs/06-baseline.md)."""
from datetime import UTC, datetime
from uuid import UUID

from patient_memory.baseline.assess import COUNTING_PROMPT, escalations_used, valid_tags
from patient_memory.baseline.engine import FEATURES
from patient_memory.baseline.note import draft_note
from patient_memory.baseline.observations import documented_observations
from patient_memory.baseline.signals import features_for, stored_modalities
from patient_memory.baseline.verdict import (
    ACTION_LABELS,
    VERDICT_RANK,
    WATCH_WINDOW_DAYS,
    WATCH_WINDOW_TAGS,
    shift_bounds,
)
from patient_memory.config import Settings
from patient_memory.errors import Problem
from patient_memory.ingestion import lock_patient
from patient_memory.storage import patient_access

FEATURE_META = {
    "speech_rate_wpm": {"label": "Speech rate", "unit": "words/min"},
    "pause_ratio": {"label": "Pause ratio", "unit": "share of time"},
    "mean_pause_s": {"label": "Mean pause", "unit": "s"},
    "f0_median_hz": {"label": "Pitch (F0)", "unit": "Hz"},
}


def watch_window(tags: list[dict], now: datetime) -> dict:
    open_tags = [t for t in tags if t["tag"] in WATCH_WINDOW_TAGS]
    if not open_tags:
        return {"open": False, "day": None, "of": WATCH_WINDOW_DAYS, "reason": None}
    start = max(datetime.fromisoformat(t["valid_from"]) for t in open_tags)
    latest = max(open_tags, key=lambda t: t["valid_from"])
    day = min(max((now - start).days + 1, 1), WATCH_WINDOW_DAYS)
    return {"open": True, "day": day, "of": WATCH_WINDOW_DAYS, "reason": latest["tag"]}


def _latest_assessment(conn, patient_id: UUID, modality: str | None = None, at=None):
    # Shared invoker helper preserves the same eligibility for readback and narrow feedback.
    return conn.execute(
        "SELECT a.*, COALESCE((a.params->>'signal_ts')::timestamptz,v.ts) AS check_ts,"
        "v.synthetic AS check_synthetic FROM assessments a LEFT JOIN voice_checks v "
        "ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id "
        "WHERE a.patient_id=%s AND a.id=pm_latest_resident_assessment_id(%s,%s,%s)",
        (patient_id, patient_id, at or datetime.now(UTC), modality)).fetchone()


def _assessment_payload(row, tags, change_row_features) -> dict:
    params = row["params"]
    return {
        "id": str(row["id"]), "ts": row["check_ts"].isoformat(), "verdict": row["verdict"],
        "check": {"id": str(row["check_id"]), "ts": row["check_ts"].isoformat(),
                  "synthetic": row["check_synthetic"]}
                 if params.get("modality", "speech") == "speech" else None,
        "over_budget": bool(params.get("over_budget")),
        "no_escalate_profile": bool(params.get("no_escalate")),
        "suggested_action": {"id": row["suggested_action"],
                             "label": ACTION_LABELS[row["suggested_action"]]},
        "reasons": row["reasons"],
        "modality": params.get("modality", "speech"),
        "corroborated": bool(row.get("corroborated", False)),
        "modalities": stored_modalities(row),
        "draft_status": params.get("draft_status", "speech"),
        "change": {"status": row["change_status"], "mode": params.get("mode"),
                   "fused_z": row["fused_z"], "per_feature": change_row_features,
                   "params": {k: v for k, v in params.items()
                              if k not in ("over_budget", "no_escalate", "would_escalate")}},
        "sbar": row["sbar"],
    }


def overview(conn, cfg: Settings, patient: dict, days: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    pid = patient["id"]
    lock_patient(conn, pid)
    patient = patient_access(conn, pid)
    if not conn.execute("SELECT pm_care(%s) AS ok", (pid,)).fetchone()["ok"]:
        raise Problem(404, "not_found")
    tags = valid_tags(conn, pid, now)
    latest = _latest_assessment(conn, pid, at=now)
    latest_speech = _latest_assessment(conn, pid, "speech", at=now)
    # The chart shows one prompt's checks, the one the latest band was computed from, so free
    # conversation (Vox) points never sit on a counting-prompt band or the reverse.
    prompt = (latest_speech["params"].get("prompt_version") if latest_speech else None) or COUNTING_PROMPT
    series = {name: {"daily": [], "checks": []} for name in FEATURES}
    for row in conn.execute(
            "SELECT time_bucket('1 day', ts) AS day, "
            + ",".join(f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {n}) AS {n}" for n in FEATURES)
            + " FROM voice_checks WHERE patient_id=%s AND usable AND prompt_version=%s "
            "AND ts>=%s - make_interval(days=>%s) GROUP BY 1 ORDER BY 1", (pid, prompt, now, days)):
        for name in FEATURES:
            if row[name] is not None:
                series[name]["daily"].append({"day": row["day"].date().isoformat(),
                                              "median": row[name]})
    for row in conn.execute(
            "SELECT ts," + ",".join(FEATURES) + " FROM voice_checks WHERE patient_id=%s AND usable "
            "AND prompt_version=%s AND ts>=%s - make_interval(days=>%s) ORDER BY ts",
            (pid, prompt, now, days)):
        for name in FEATURES:
            if row[name] is not None:
                series[name]["checks"].append({"ts": row["ts"].isoformat(), "value": row[name]})
    baseline = {"mode": None, "n_checks": 0, "features": {}, "prompt_version": prompt}
    assessment = None
    if latest:
        assessment = _assessment_payload(latest, tags, features_for(latest["features"]))
        if latest["params"].get("draft_status") == "multimodal_template" and latest["sbar"]:
            try:
                draft_note(conn, pid, latest["id"])
            except Problem as exc:
                if exc.status != 409:
                    raise
                assessment["sbar"] = None
                assessment["draft_status"] = "unavailable_multimodal_evidence"
            else:
                check_ids = {e.removeprefix("check:") for sentence in latest["sbar"]["sentences"]
                             for e in sentence["evidence_ids"] if e.startswith("check:")}
                assessment["cited_checks"] = {str(r["id"]): {
                    "id": str(r["id"]), "ts": r["ts"].isoformat(), "synthetic": r["synthetic"],
                    "features": {f: r[f] for f in FEATURES}, "prompt_version": r["prompt_version"]}
                    for r in conn.execute("SELECT * FROM voice_checks WHERE patient_id=%s "
                        "AND id=ANY(%s::uuid[]) AND usable AND session_id IS NULL",
                        (pid, list(check_ids))).fetchall()}
    if latest_speech:
        speech_features = features_for(latest_speech["features"])
        baseline = {"mode": latest_speech["params"].get("mode"), "prompt_version": prompt,
                    "n_checks": latest_speech["params"].get("baseline_checks", 0),
                    "features": {n: {"median": f["median"], "scale": f["scale"]}
                                 for n, f in speech_features.items()}}
    first = conn.execute(
        "SELECT min(v.ts) AS ts FROM assessments a JOIN voice_checks v "
        "ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id "
        "WHERE a.patient_id=%s AND a.change_status='change' AND v.prompt_version=%s "
        "AND COALESCE((a.params->>'invalidated')::boolean,false)=false "
        "AND (a.params->>'source_revision')::bigint=%s "
        "AND a.params->>'session_id' IS NULL AND v.session_id IS NULL "
        "AND v.ts>=%s - make_interval(days=>%s) AND v.ts<=%s",
        (pid, prompt, patient["revision"], now, days, now)).fetchone()["ts"]
    return {
        "patient_id": str(pid), "display_name": patient["external_id"], "synthetic": True,
        "watch_window": watch_window(tags, now), "features": FEATURE_META, "series": series,
        "baseline": baseline, "first_change_ts": first.isoformat() if first else None,
        "latest_assessment": assessment,
        "context_tags": tags,
        "documented_observations": documented_observations(conn, pid, now, days),
    }


def watchlist(conn, cfg: Settings, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start, end = shift_bounds(now, cfg.shift_timezone)
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                 ("baseline-budget/" + str(conn.execute("SELECT pm_tenant() AS id").fetchone()["id"]),))
    residents = []
    for patient in conn.execute("SELECT id, external_id FROM patients WHERE pm_care(id) ORDER BY id"):
        pid = patient["id"]
        lock_patient(conn, pid)
        # Assignment changes use the same patient lock. Recheck rows enumerated before waiting.
        if not conn.execute("SELECT id FROM patients WHERE id=%s AND pm_care(id)",
                            (pid,)).fetchone():
            continue
        latest = _latest_assessment(conn, pid, at=now)
        last_check = conn.execute("SELECT max(ts) AS ts FROM voice_checks WHERE patient_id=%s",
                                  (pid,)).fetchone()["ts"]
        spark = conn.execute(
            "SELECT time_bucket('1 day', ts) AS day, "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY speech_rate_wpm) AS speech_rate_wpm "
            "FROM voice_checks WHERE patient_id=%s AND usable AND prompt_version=%s "
            "AND ts>=%s - interval '14 days' GROUP BY 1 ORDER BY 1",
            (pid, COUNTING_PROMPT, now)).fetchall()
        params = latest["params"] if latest else {}
        residents.append({
            "patient_id": str(pid), "display_name": patient["external_id"], "synthetic": True,
            "latest_verdict": latest["verdict"] if latest else None,
            "over_budget": bool(params.get("over_budget")),
            "corroborated": bool(latest["corroborated"]) if latest else False,
            "modalities": stored_modalities(latest) if latest else {},
            "fused_z": latest["fused_z"] if latest else None,
            "last_check_ts": last_check.isoformat() if last_check else None,
            "watch_window": watch_window(valid_tags(conn, pid, now), now),
            "sparkline": [{"day": r["day"].date().isoformat(),
                           "speech_rate_wpm": r["speech_rate_wpm"]} for r in spark],
        })
    residents.sort(key=lambda r: (VERDICT_RANK.get(r["latest_verdict"], 4),
                                  -(r["fused_z"] if r["fused_z"] is not None else float("-inf"))))
    return {"shift": {"start": start.astimezone(UTC).isoformat(),
                      "end": end.astimezone(UTC).isoformat(),
                      "escalations_used": escalations_used(conn, now, cfg),
                      "escalation_budget": cfg.escalation_budget},
            "residents": residents}
