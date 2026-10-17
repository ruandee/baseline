from uuid import uuid4

from psycopg.types.json import Jsonb

from patient_memory.errors import Problem
from patient_memory.ingestion import bump, digest, idempotent, lock_patient
from patient_memory.storage import audit, patient_access, require_member, transaction


def scope_hash(conn, actor, patient_id):
    roles = conn.execute("SELECT role FROM assignments WHERE patient_id=%s AND principal_id=%s "
                         "AND active ORDER BY role", (patient_id, actor.principal_id)).fetchall()
    return digest({"actor": str(actor.principal_id), "roles": [r["role"] for r in roles]})


def rate_limit(conn, actor, limit):
    count = conn.execute(
        "INSERT INTO request_budgets VALUES(%s,%s,date_trunc('minute',now()),1) "
        "ON CONFLICT(tenant_id,principal_id,window_at) DO UPDATE SET count=request_budgets.count+1 "
        "RETURNING count", (actor.tenant_id, actor.principal_id),
    ).fetchone()["count"]
    # Commit accounting before raising so over-budget requests do not erase the count.
    return count <= limit


def cache_get(conn, patient_id, key):
    row = conn.execute("SELECT body FROM answers WHERE patient_id=%s AND cache_key=%s AND expires_at>now()",
                       (patient_id, key)).fetchone()
    return row["body"] if row else None


def cache_put(conn, actor, patient_id, key, revision, answer):
    conn.execute("INSERT INTO answers(tenant_id,patient_id,cache_key,principal_id,revision,body) "
                 "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,patient_id,cache_key) "
                 "DO UPDATE SET body=excluded.body,expires_at=now()+interval '5 minutes'",
                 (actor.tenant_id, patient_id, key, actor.principal_id, revision,
                  Jsonb(answer.model_dump(mode="json"))))


def change_source(conn, actor, patient_id, source_id, operation, key, payload, request_id):
    patient_access(conn, patient_id, write=True)

    def perform():
        source = conn.execute("SELECT * FROM sources WHERE patient_id=%s AND id=%s FOR UPDATE",
                              (patient_id, source_id)).fetchone()
        if not source:
            raise Problem(404, "not_found")
        if source["purged_at"]:
            raise Problem(409, "source_purged")
        if operation == "visibility":
            conn.execute("UPDATE sources SET visibility=%s WHERE id=%s", (payload["visibility"], source_id))
        else:
            conn.execute("UPDATE sources SET retracted_at=coalesce(retracted_at,clock_timestamp()),"
                         "retraction_reason=%s,purge_requested=purge_requested OR %s,"
                         "purge_after=CASE WHEN %s THEN now() ELSE purge_after END WHERE id=%s",
                         (payload["reason"], operation == "purge", operation == "purge", source_id))
            conn.execute("UPDATE jobs SET status='cancelled',stage='cancelled',lease_token=NULL "
                         "WHERE source_id=%s AND status<>'completed'", (source_id,))
        revision = bump(conn, patient_id)
        audit(conn, actor, patient_id, operation, request_id)
        return {"memory_revision": revision}

    return idempotent(conn, actor, patient_id, operation, key,
                      {"source_id": str(source_id), **payload}, perform)


def assign(conn, actor, patient_id, body, request_id):
    if not require_member(conn)["administrator"]:
        raise Problem(404, "not_found")
    lock_patient(conn, patient_id)
    if not conn.execute("SELECT id FROM patients WHERE id=%s", (patient_id,)).fetchone():
        raise Problem(404, "not_found")
    # FK ensures principal is a member of the same tenant; report invalid target without disclosure.
    conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,%s) "
                 "ON CONFLICT(tenant_id,patient_id,principal_id,role) DO UPDATE SET active=excluded.active",
                 (actor.tenant_id, patient_id, body.principal_id, body.role, body.active))
    conn.execute("UPDATE patients SET revision=revision+1 WHERE id=%s", (patient_id,))
    # All future cache keys include revision and current scope. Old rows expire naturally.
    audit(conn, actor, patient_id, "assignment", request_id)
    return {"active": body.active, "role": body.role}


def purge_once(cfg, actor, objects):
    with transaction(cfg, actor) as conn:
        source = conn.execute("SELECT * FROM sources WHERE purge_requested AND purged_at IS NULL "
                              "AND purge_after<=now() ORDER BY purge_after LIMIT 1").fetchone()
        if not source:
            return False
        lock_patient(conn, source["patient_id"])
        source = conn.execute("SELECT * FROM sources WHERE id=%s AND purged_at IS NULL "
                              "FOR UPDATE SKIP LOCKED", (source["id"],)).fetchone()
        if not source:
            return True
        try:
            objects.delete(source["object_key"])
        except Exception:
            conn.execute("UPDATE sources SET purge_attempt=purge_attempt+1,purge_error='object_unavailable',"
                         "purge_after=now()+interval '30 seconds' WHERE id=%s", (source["id"],))
            return True
        conn.execute("DELETE FROM facts WHERE source_id=%s", (source["id"],))
        conn.execute("DELETE FROM answers WHERE patient_id=%s", (source["patient_id"],))
        conn.execute("UPDATE sources SET payload='{}',canonical_text='',purged_at=clock_timestamp(),"
                     "purge_error=NULL WHERE id=%s", (source["id"],))
        bump(conn, source["patient_id"])
        audit(conn, actor, source["patient_id"], "purge_complete", uuid4())
    return True
