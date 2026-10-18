from contextlib import contextmanager
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from patient_memory.baseline import sessions, vitals  # noqa: F401 - register observation adapter
from patient_memory.baseline.assess import COUNTING_PROMPT, assess_check, lock_assessment
from patient_memory.check_profiles import require_protocol
from patient_memory.config import Settings
from patient_memory.consent import check_gate, require_consent
from patient_memory.domain import CheckResult
from patient_memory.errors import Problem
from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import audit, patient_access


def care_gate(conn, patient_id: UUID):
    """Only care-team roles may write voice checks; deny as not_found before any audio work."""
    patient_access(conn, patient_id)
    if not conn.execute("SELECT pm_care(%s) AS ok", (patient_id,)).fetchone()["ok"]:
        raise Problem(404, "not_found")


def store_check(conn, identity, patient_id: UUID, request_id: UUID, analysis: Analysis,
                mode, device_id, device_ts, is_baseline, cfg: Settings,
                consent_scope: str = "voice_check", session_id: UUID | None = None,
                location: tuple[float, float, float | None] | None = None,
                prompt_version: str = COUNTING_PROMPT, profile_snapshot: dict | None = None) -> CheckResult:
    """Insert the check (unusable ones too, for audit) and audit the write.

    Raises ConsentRequired (403) when consent is not granted at insert time; callers audit the
    block in a separate transaction because this one rolls back.
    """
    care = check_gate(conn, patient_id)
    if session_id is not None:
        care_gate(conn, patient_id)
    if not care and (mode != "resident" or is_baseline):
        raise Problem(422, "invalid_request", "PSW checks use resident mode without enrollment")
    # All check writers take tenant/shift admission before the patient history lock.
    # A concurrent final-slot escalation must see the previous committed reservation.
    lock_assessment(conn, identity.tenant_id, patient_id)
    check_gate(conn, patient_id)
    require_consent(conn, patient_id, consent_scope)  # withdrawn during decode: nothing stored
    profile = None
    if session_id is None and prompt_version == COUNTING_PROMPT:
        profile = require_protocol(conn, patient_id,
            expected_version=profile_snapshot["version"] if profile_snapshot else None)
    with scoring_context(conn, patient_id):
        result = _store_check(conn, identity, patient_id, request_id, analysis, mode, device_id,
                              device_ts, is_baseline, cfg, session_id, location, prompt_version)
        if profile:
            conn.execute(
                "INSERT INTO voice_check_profiles(tenant_id,patient_id,check_id,check_ts,"
                "profile_version,locale,prompt_version,first_name) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (identity.tenant_id, patient_id, result.check_id, result.ts, profile["version"],
                 profile["protocol_locale"], profile["prompt_version"], profile["first_name"]))
    check_gate(conn, patient_id)  # role revocation must not leak a result
    require_consent(conn, patient_id, consent_scope)
    return result


@contextmanager
def scoring_context(conn, patient_id: UUID):
    """Trusted server-only, patient-scoped access; never entered by read endpoints.

    The DB runtime credential and request GUCs are private to the server, just like pm.actor.
    Keep the original actor for assignment checks and audit. Call only after admission locks.
    """
    conn.execute("SELECT set_config('pm.check_scoring_patient',%s,true)", (str(patient_id),))
    try:
        yield
    finally:
        if conn.info.transaction_status != TransactionStatus.INERROR:
            conn.execute("SELECT set_config('pm.check_scoring_patient','',true)")


def _store_check(conn, identity, patient_id, request_id, analysis, mode, device_id, device_ts,
                 is_baseline, cfg, session_id, location, prompt_version):
    session = None
    if session_id is not None:
        session = sessions.check_gate(conn, patient_id, session_id, mode, is_baseline, lock=True)
    elif location is not None:
        raise Problem(422, "invalid_request", "Location is stored only for session check-ins")
    lat, lon, accuracy = location or (None, None, None)
    check_id = uuid4()
    words = [{"w": w.w, "start": w.start, "end": w.end} for w in analysis.words]
    features = analysis.features
    ts = conn.execute(
        "INSERT INTO voice_checks(tenant_id,patient_id,id,device_ts,device_id,mode,is_baseline,"
        "usable,quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,transcript,words,"
        "session_id,lat,lon,accuracy_m,prompt_version) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING ts",
        (identity.tenant_id, patient_id, check_id, device_ts, device_id, mode, is_baseline,
         analysis.usable, Jsonb(analysis.quality), features["speech_rate_wpm"],
         features["pause_ratio"], features["mean_pause_s"], features["f0_median_hz"],
         " ".join(w["w"] for w in words), Jsonb(words), session_id, lat, lon,
         accuracy, prompt_version)).fetchone()["ts"]
    audit(conn, identity, patient_id, "create_check", request_id)
    change = assessment = None
    timings = dict(analysis.timings_ms)
    if analysis.usable:  # unusable clips are stored for audit but never scored
        name = conn.execute("SELECT external_id FROM patients WHERE id=%s",
                            (patient_id,)).fetchone()["external_id"]
        change, assessment = assess_check(
            conn, cfg, patient_id, identity.tenant_id, check_id, ts, device_id,
            prompt_version, is_baseline, features, name, session_id=session_id,
            timings_ms=timings)
    summary = sessions.after_check(
        conn, session, ts, analysis.usable, is_baseline,
        change_status=change and change["status"]) if session else None
    return CheckResult(
        session=summary,
        change=change, assessment=assessment,
        check_id=check_id, ts=ts, usable=analysis.usable, quality=analysis.quality,
        features=features, words=words,
        pauses=[{"start": p.start, "end": p.end} for p in analysis.pauses],
        timings_ms=timings)
