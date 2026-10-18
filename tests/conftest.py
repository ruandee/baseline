from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.objects import ObjectStore


@pytest.fixture(autouse=True)
def offline_models(monkeypatch):
    monkeypatch.setenv("PM_PROVIDER", "stub")
    # Tests never send a real text, whatever a local .env says (decision 023).
    monkeypatch.setenv("PM_SMS_PROVIDER", "log")
    monkeypatch.setenv("PM_SMS_LOG_LINKS", "false")
    for name in ["PM_TWILIO_SID", "PM_TWILIO_TOKEN", "PM_TWILIO_FROM", "PM_SMS_ALLOWED_RECIPIENTS"]:
        monkeypatch.setenv(name, "")


MAX_DB_CLOCK_LEAD_MS = 10


@pytest.fixture(scope="session")
def db_clock_in_step():
    """Tests take `now()` from the host but rows are stamped by the database clock, so a database
    clock ahead of the host makes just-written rows look like they arrive in the future."""
    with psycopg.connect(Settings().admin_database_url) as conn:
        before = datetime.now(timezone.utc)
        database = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        after = datetime.now(timezone.utc)
    lead_ms = ((database - before) + (database - after)).total_seconds() * 500
    if lead_ms > MAX_DB_CLOCK_LEAD_MS:
        pytest.exit(f"Database clock is {lead_ms:.0f} ms ahead of the host; time-cutoff tests "
                    "would fail. Resync it (macOS Colima: see docs/operations.md).", returncode=3)


@pytest.fixture
def sandbox(db_clock_in_step):
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


@pytest.fixture
def kaze_sandbox(db_clock_in_step):
    """A safety-mode tenant (decision 018): two people, each importer on their own row, the
    kaze-service principal as nurse on both, and an unassigned administrator."""
    cfg = Settings()
    tenant = uuid4()
    ids = {name: uuid4() for name in ["person", "other", "service", "admin"]}
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO tenants(id,name,safety_mode) VALUES(%s,'synthetic-kaze',true)",
                     (tenant,))
        for name, actor in ids.items():
            conn.execute("INSERT INTO principals(id,tenant_id,name,administrator) VALUES(%s,%s,%s,%s)",
                         (actor, tenant, "synthetic-" + name, name == "admin"))
        for name in ["person", "other"]:
            conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                         (ids[name], tenant, "synthetic-kaze-" + name))
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'importer',true)",
                         (tenant, ids[name], ids[name]))
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true)",
                         (tenant, ids[name], ids["service"]))
    objects = ObjectStore(cfg)
    objects.initialize()
    return {"cfg": cfg, "tenant": tenant, "patient": ids["person"], "other_patient": ids["other"],
            "ids": {name: Identity(actor, tenant) for name, actor in ids.items()},
            "objects": objects}
