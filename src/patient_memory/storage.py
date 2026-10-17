from contextlib import contextmanager
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.errors import Problem


@contextmanager
def transaction(cfg: Settings, identity: Identity):
    with psycopg.connect(cfg.database_url, row_factory=dict_row) as conn:
        conn.execute("SELECT set_config('pm.tenant',%s,true)", (str(identity.tenant_id),))
        conn.execute("SELECT set_config('pm.actor',%s,true)", (str(identity.principal_id),))
        conn.execute("SET LOCAL statement_timeout='10s'")
        yield conn


def require_member(conn):
    row = conn.execute("SELECT * FROM principals WHERE active").fetchone()
    if not row:
        raise Problem(401, "inactive_identity")
    return row


def patient_access(conn, patient_id: UUID, write=False):
    require_member(conn)
    patient = conn.execute("SELECT * FROM patients WHERE id=%s", (patient_id,)).fetchone()
    if not patient or not conn.execute("SELECT pm_access(%s,%s) AS ok", (patient_id, write)).fetchone()["ok"]:
        raise Problem(404, "not_found")
    return patient


def audit(conn, identity, patient_id, action, request_id, result="ok"):
    conn.execute(
        "INSERT INTO audit(tenant_id,patient_id,principal_id,action,result,request_id) "
        "VALUES(%s,%s,%s,%s,%s,%s)",
        (identity.tenant_id, patient_id, identity.principal_id, action, result, request_id),
    )
