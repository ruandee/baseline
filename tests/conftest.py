from uuid import uuid4

import psycopg
import pytest

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.objects import ObjectStore


@pytest.fixture
def sandbox():
    cfg = Settings()
    tenant, patient = uuid4(), uuid4()
    actors = {role: uuid4() for role in ["admin", "importer", "nurse", "patient"]}
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO tenants VALUES(%s,'synthetic-test')", (tenant,))
        for role, actor in actors.items():
            conn.execute("INSERT INTO principals(id,tenant_id,name,administrator) VALUES(%s,%s,%s,%s)",
                         (actor, tenant, "synthetic-" + role, role == "admin"))
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'synthetic-test')",
                     (patient, tenant))
        for role in ["importer", "nurse", "patient"]:
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true)",
                         (tenant, patient, actors[role], role))
    objects = ObjectStore(cfg)
    objects.initialize()
    return cfg, patient, {role: Identity(actor, tenant) for role, actor in actors.items()}, objects
