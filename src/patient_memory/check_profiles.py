"""Explicit counting protocol preferences; no language detection or translated protocols."""
from uuid import uuid4

from patient_memory.baseline.assess import COUNTING_PROMPT
from patient_memory.consent import check_gate, consent_state
from patient_memory.errors import Problem
from patient_memory.ingestion import lock_patient
from patient_memory.storage import audit

PROTOCOLS = {"en": COUNTING_PROMPT}


def project(row):
    locale = row["preferred_locale"] if row else None
    protocol = PROTOCOLS.get(locale)
    return {"first_name": row["first_name"] if row else None, "preferred_locale": locale,
            "version": str(row["version"]) if row else None,
            "state": "ready" if protocol else "unconfigured" if locale is None else "unsupported",
            "protocol_locale": locale if protocol else None, "prompt_version": protocol}


def read_profile(conn, patient_id):
    care = check_gate(conn, patient_id)
    row = conn.execute("SELECT * FROM resident_check_profiles WHERE patient_id=%s",
                       (patient_id,)).fetchone()
    return {**project(row), "voice_consent_state": consent_state(conn, patient_id),
            "can_configure": care,
            "can_record_consent": bool(conn.execute("SELECT pm_role(%s,'nurse') AS ok",
                                                     (patient_id,)).fetchone()["ok"])}


def write_profile(conn, identity, patient_id, body, request_id):
    check_gate(conn, patient_id)
    lock_patient(conn, patient_id)
    check_gate(conn, patient_id)
    if not conn.execute("SELECT pm_care(%s) AS ok", (patient_id,)).fetchone()["ok"]:
        raise Problem(404, "not_found")
    conn.execute(
        "INSERT INTO resident_check_profiles(tenant_id,patient_id,preferred_locale,first_name,"
        "version,updated_by) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,patient_id) "
        "DO UPDATE SET preferred_locale=EXCLUDED.preferred_locale,first_name=EXCLUDED.first_name,"
        "version=EXCLUDED.version,updated_by=EXCLUDED.updated_by,updated_at=clock_timestamp()",
        (identity.tenant_id, patient_id, body.preferred_locale, body.first_name, uuid4(),
         identity.principal_id))
    audit(conn, identity, patient_id, "check_profile_updated", request_id)
    return read_profile(conn, patient_id)


def require_protocol(conn, patient_id, *, expected_version=None, requested_locale=None):
    profile = read_profile(conn, patient_id)
    if profile["state"] != "ready":
        raise Problem(409, "check_language_unavailable", "Counting language is not configured or supported")
    if ((expected_version is not None and profile["version"] != str(expected_version))
            or (requested_locale is not None and requested_locale != profile["protocol_locale"])):
        raise Problem(409, "check_profile_changed", "Reload the resident's counting profile")
    return profile


def seed_english_profile(admin_conn, tenant_id, patient_id, actor_id, *, first_name=None):
    """Deliberate synthetic setup only. Never replace an existing choice, including null."""
    admin_conn.execute(
        "INSERT INTO resident_check_profiles(tenant_id,patient_id,preferred_locale,first_name,"
        "version,updated_by) VALUES(%s,%s,'en',%s,%s,%s) ON CONFLICT DO NOTHING",
        (tenant_id, patient_id, first_name, uuid4(), actor_id))
