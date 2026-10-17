import hashlib
import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from patient_memory.domain import SourceInput
from patient_memory.errors import Problem
from patient_memory.storage import patient_access


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def lock_patient(conn, patient_id):
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(patient_id),))


def idempotent(conn, identity, patient_id, operation, key, payload, perform):
    if not key or len(key) > 200:
        raise Problem(422, "idempotency_key_required")
    lock_patient(conn, patient_id)
    old = conn.execute(
        "SELECT * FROM operations WHERE patient_id=%s AND operation=%s AND key=%s",
        (patient_id, operation, key),
    ).fetchone()
    payload_hash = digest(payload)
    if old:
        if old["payload_hash"] != payload_hash:
            raise Problem(409, "idempotency_conflict")
        return old["result"]
    result = perform()
    conn.execute(
        "INSERT INTO operations VALUES(%s,%s,%s,%s,%s,%s)",
        (identity.tenant_id, patient_id, operation, key, payload_hash, Jsonb(result)),
    )
    return result


def submit(conn, identity, patient_id, source: SourceInput, key, objects):
    patient_access(conn, patient_id, write=True)
    payload = source.model_dump(mode="json")

    def perform():
        document_key = json.dumps([source.source_system, source.external_document_id])
        existing = conn.execute(
            "SELECT id,payload_hash FROM sources WHERE patient_id=%s AND document_key=%s "
            "AND external_version=%s", (patient_id, document_key, source.external_version_id),
        ).fetchone()
        raw = json.dumps(payload, sort_keys=True).encode()
        payload_hash = hashlib.sha256(raw).hexdigest()
        if existing:
            if existing["payload_hash"] != payload_hash:
                raise Problem(409, "source_version_conflict")
            job = conn.execute("SELECT id,status FROM jobs WHERE source_id=%s", (existing["id"],)).fetchone()
            return {"job_id": str(job["id"]), "source_version_id": str(existing["id"]), "status": job["status"]}
        if source.supersedes_version_id:
            parent = conn.execute("SELECT * FROM sources WHERE patient_id=%s AND id=%s",
                                  (patient_id, source.supersedes_version_id)).fetchone()
            if not parent or parent["document_key"] != document_key or parent["purged_at"]:
                raise Problem(422, "invalid_supersession")
        sid, jid = uuid4(), uuid4()
        object_key = f"{identity.tenant_id}/{patient_id}/{sid}.json"
        objects.put(object_key, raw)
        conn.execute(
            "INSERT INTO sources(id,tenant_id,patient_id,document_key,external_version,payload_hash,"
            "object_key,payload,visibility,recorded_at,supersedes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (sid, identity.tenant_id, patient_id, document_key, source.external_version_id,
             payload_hash, object_key, Jsonb(payload), source.visibility, source.recorded_at,
             source.supersedes_version_id),
        )
        conn.execute("INSERT INTO jobs(id,tenant_id,patient_id,source_id) VALUES(%s,%s,%s,%s)",
                     (jid, identity.tenant_id, patient_id, sid))
        return {"job_id": str(jid), "source_version_id": str(sid), "status": "queued"}

    return idempotent(conn, identity, patient_id, "submit", key, payload, perform)


def claim_job(conn):
    job = conn.execute(
        "SELECT * FROM jobs WHERE (status='queued' AND next_attempt_at<=now()) "
        "OR (status='processing' AND lease_until<now()) ORDER BY next_attempt_at,id "
        "FOR UPDATE SKIP LOCKED LIMIT 1",
    ).fetchone()
    if not job:
        return None
    token = uuid4()
    return conn.execute(
        "UPDATE jobs SET status='processing',stage='extracting',attempt=attempt+1,"
        "lease_until=now()+interval '60 seconds',lease_token=%s WHERE id=%s RETURNING *",
        (token, job["id"]),
    ).fetchone()


def bump(conn, patient_id):
    # Caller holds patient advisory lock for every revision mutation.
    conn.execute("DELETE FROM answers WHERE patient_id=%s", (patient_id,))
    return conn.execute("UPDATE patients SET revision=revision+1 WHERE id=%s RETURNING revision",
                        (patient_id,)).fetchone()["revision"]
