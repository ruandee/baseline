from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

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
                mode, device_id, device_ts, is_baseline) -> CheckResult:
    """Insert the check (unusable ones too, for audit) and audit the write."""
    care_gate(conn, patient_id)
    check_id = uuid4()
    words = [{"w": w.w, "start": w.start, "end": w.end} for w in analysis.words]
    features = analysis.features
    ts = conn.execute(
        "INSERT INTO voice_checks(tenant_id,patient_id,id,device_ts,device_id,mode,is_baseline,"
        "usable,quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,transcript,words) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING ts",
        (identity.tenant_id, patient_id, check_id, device_ts, device_id, mode, is_baseline,
         analysis.usable, Jsonb(analysis.quality), features["speech_rate_wpm"],
         features["pause_ratio"], features["mean_pause_s"], features["f0_median_hz"],
         " ".join(w["w"] for w in words), Jsonb(words))).fetchone()["ts"]
    audit(conn, identity, patient_id, "create_check", request_id)
    return CheckResult(
        check_id=check_id, ts=ts, usable=analysis.usable, quality=analysis.quality,
        features=features, words=words,
        pauses=[{"start": p.start, "end": p.end} for p in analysis.pauses],
        timings_ms=analysis.timings_ms)
