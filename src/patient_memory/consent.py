"""Resident consent for voice capture and the check-writer gate (decision 017).

Every route that accepts resident audio calls `admit_check` before any decode or ASR work and
`require_consent` again inside the transaction that stores the result: consent can be withdrawn
while Whisper runs, and a withdrawal applies to the very next check. Missing consent is
`unknown`, which blocks exactly like `declined` or `withdrawn`.
"""
from uuid import UUID

from patient_memory.config import Settings
from patient_memory.errors import Problem
from patient_memory.storage import audit, require_member, transaction

CONSENT_SCOPES = ("voice_check", "vox_encounter", "motion_check")
CONSENT_STATES = ("granted", "declined", "withdrawn", "expired", "unknown")


class ConsentRequired(Problem):
    def __init__(self, state: str):
        super().__init__(403, "consent_required",
                         f"Consent for this capture is not recorded as granted (state: {state})")
        self.state = state


def check_gate(conn, patient_id: UUID) -> bool:
    """Authorize a check writer (nurse, importer or PSW); 404 otherwise, before audio work.

    Returns True when the caller is care team and may see scores; False for a PSW.
    """
    require_member(conn)
    row = conn.execute("SELECT pm_checker(%s) AS checker, pm_care(%s) AS care,"
                       " EXISTS(SELECT FROM patients WHERE id=%s) AS present",
                       (patient_id, patient_id, patient_id)).fetchone()
    if not (row["checker"] and row["present"]):
        raise Problem(404, "not_found")
    return bool(row["care"])


def consent_record(conn, patient_id: UUID, scope: str = "voice_check") -> dict:
    """The effective consent: the latest row wins, with no grace period."""
    row = conn.execute(
        "SELECT status, decided_by, recorded_at, expires_at,"
        " expires_at IS NOT NULL AND expires_at<=clock_timestamp() AS expired"
        " FROM resident_consents WHERE patient_id=%s AND scope=%s"
        " ORDER BY recorded_at DESC, id DESC LIMIT 1", (patient_id, scope)).fetchone()
    if not row:
        return {"scope": scope, "state": "unknown", "decided_by": None, "recorded_at": None,
                "expires_at": None}
    state = "expired" if row["status"] == "granted" and row["expired"] else row["status"]
    return {"scope": scope, "state": state, "decided_by": row["decided_by"],
            "recorded_at": row["recorded_at"], "expires_at": row["expires_at"]}


def consent_state(conn, patient_id: UUID, scope: str = "voice_check") -> str:
    return consent_record(conn, patient_id, scope)["state"]


def require_consent(conn, patient_id: UUID, scope: str = "voice_check"):
    state = consent_state(conn, patient_id, scope)
    if state != "granted":
        raise ConsentRequired(state)


def audit_consent_block(cfg: Settings, identity, patient_id: UUID, request_id: UUID):
    """Committed on its own: the blocked request's transaction rolls back."""
    with transaction(cfg, identity) as conn:
        audit(conn, identity, patient_id, "check_blocked_consent", request_id, result="denied")


def admit_check(cfg: Settings, identity, patient_id: UUID, request_id: UUID,
                scope: str = "voice_check") -> bool:
    """Authorize, then require consent, before any audio work. Returns `check_gate`'s result."""
    try:
        with transaction(cfg, identity) as conn:
            care = check_gate(conn, patient_id)
            require_consent(conn, patient_id, scope)
            return care
    except ConsentRequired:
        audit_consent_block(cfg, identity, patient_id, request_id)
        raise


def grant_fixture_consent(admin_conn, tenant_id: UUID, patient_id: UUID, importer_id: UUID,
                          scope: str = "voice_check"):
    """Synthetic setup only (admin connection): grant consent on purpose, never by default.

    Writes nothing if the patient already has a row for `scope`, so reloading fixtures never
    overrides a later withdrawal or decline.
    """
    admin_conn.execute(
        "INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,decided_by,recorded_by)"
        " SELECT %s,%s,gen_random_uuid(),%s,'granted','synthetic_fixture',%s"
        " WHERE NOT EXISTS(SELECT FROM resident_consents WHERE tenant_id=%s AND patient_id=%s"
        " AND scope=%s)",
        (tenant_id, patient_id, scope, importer_id, tenant_id, patient_id, scope))
