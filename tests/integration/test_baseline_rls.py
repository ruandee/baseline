from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from patient_memory.auth import Identity
from patient_memory.storage import transaction

TABLES = ["voice_checks", "context_tags", "assessments"]


def make_tenant(admin):
    """A second tenant with one patient and one nurse assigned to it."""
    tenant, patient, nurse = uuid4(), uuid4(), uuid4()
    admin.execute("INSERT INTO tenants VALUES(%s,'synthetic-other')", (tenant,))
    admin.execute("INSERT INTO principals(id,tenant_id,name,administrator) VALUES(%s,%s,'synthetic-nurse',false)",
                  (nurse, tenant))
    admin.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'synthetic-other')",
                  (patient, tenant))
    admin.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true)", (tenant, patient, nurse))
    return tenant, patient, Identity(nurse, tenant)


def add_source(admin, tenant, patient):
    source = uuid4()
    admin.execute(
        "INSERT INTO sources(id,tenant_id,patient_id,document_key,external_version,payload_hash,"
        "object_key,payload,canonical_text,visibility,recorded_at) "
        "VALUES(%s,%s,%s,'doc','1','h','k','{}','Not her usual chatty self.','care_team',now())",
        (source, tenant, patient))
    return source


def insert_sql(table, tenant, patient, source):
    """One valid INSERT per table for the given owner."""
    ident = uuid4()
    if table == "voice_checks":
        return ("INSERT INTO voice_checks(tenant_id,patient_id,id,device_id,mode,usable,quality) "
                "VALUES(%s,%s,%s,'dev','resident',true,%s)",
                (tenant, patient, ident, Jsonb({"reasons": []})))
    if table == "context_tags":
        return ("INSERT INTO context_tags(tenant_id,patient_id,id,kind,tag,source_id,quote,"
                "start_offset,end_offset,valid_from,extracted_by) "
                "VALUES(%s,%s,%s,'amplifier','new_confusion_noted',%s,'Not her usual',0,13,now(),'gemini')",
                (tenant, patient, ident, source))
    return ("INSERT INTO assessments(tenant_id,patient_id,id,check_id,change_status,features,params,"
            "verdict,suggested_action) VALUES(%s,%s,%s,%s,'change',%s,%s,'escalate','4at_now')",
            (tenant, patient, ident, uuid4(), Jsonb({}), Jsonb({})))


@pytest.fixture
def two_tenants(sandbox):
    cfg, patient, identities, _ = sandbox
    with psycopg.connect(cfg.admin_database_url, autocommit=True) as admin:
        other_tenant, other_patient, other_nurse = make_tenant(admin)
        mine = identities["nurse"]
        own_source = add_source(admin, mine.tenant_id, patient)
        other_source = add_source(admin, other_tenant, other_patient)
        for table in TABLES:
            admin.execute(*insert_sql(table, mine.tenant_id, patient, own_source))
            admin.execute(*insert_sql(table, other_tenant, other_patient, other_source))
    return {"cfg": cfg, "patient": patient, "own_source": own_source, "nurse": mine,
            "others": identities, "other_patient": other_patient, "other_tenant": other_tenant,
            "other_nurse": other_nurse}


@pytest.mark.parametrize("table", TABLES)
def test_nurse_sees_only_the_assigned_patients_rows(two_tenants, table):
    t = two_tenants
    with transaction(t["cfg"], t["nurse"]) as conn:
        seen = conn.execute(f"SELECT DISTINCT tenant_id, patient_id FROM {table}").fetchall()
    assert seen == [{"tenant_id": t["nurse"].tenant_id, "patient_id": t["patient"]}]


@pytest.mark.parametrize("table", TABLES)
def test_patient_role_and_unassigned_principals_see_nothing(two_tenants, table):
    t = two_tenants
    for role in ["patient", "admin"]:  # patient is not care team; admin has no assignment
        with transaction(t["cfg"], t["others"][role]) as conn:
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0, role


@pytest.mark.parametrize("table", TABLES)
def test_nurse_writes_for_the_assigned_patient_but_not_for_another_patient_or_tenant(two_tenants, table):
    t = two_tenants
    with transaction(t["cfg"], t["nurse"]) as conn:
        before = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
        conn.execute(*insert_sql(table, t["nurse"].tenant_id, t["patient"], t["own_source"]))
        assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == before + 1
    for tenant, patient in [(t["other_tenant"], t["other_patient"]),
                            (t["nurse"].tenant_id, t["other_patient"])]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with transaction(t["cfg"], t["nurse"]) as conn:
                conn.execute(*insert_sql(table, tenant, patient, t["own_source"]))


def test_assessment_updates_stay_inside_the_callers_patient(two_tenants):
    t = two_tenants
    with transaction(t["cfg"], t["nurse"]) as conn:
        own = conn.execute("UPDATE assessments SET verdict='watch' WHERE patient_id=%s",
                           (t["patient"],)).rowcount
        theirs = conn.execute("UPDATE assessments SET verdict='watch' WHERE patient_id=%s",
                              (t["other_patient"],)).rowcount
    assert (own, theirs) == (1, 0)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(t["cfg"], t["nurse"]) as conn:
            conn.execute("UPDATE assessments SET patient_id=%s WHERE patient_id=%s",
                         (t["other_patient"], t["patient"]))


@pytest.mark.parametrize("table", ["voice_checks", "context_tags"])
def test_checks_and_tags_are_append_only_for_the_runtime_role(two_tenants, table):
    t = two_tenants
    for statement in (f"UPDATE {table} SET tenant_id=tenant_id", f"DELETE FROM {table}"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with transaction(t["cfg"], t["nurse"]) as conn:
                conn.execute(statement)


def test_context_tag_must_cite_a_real_span_of_a_source_of_the_same_patient(sandbox):
    cfg, patient, identities, _ = sandbox
    nurse = identities["nurse"]
    with psycopg.connect(cfg.admin_database_url, autocommit=True) as admin:
        other_tenant, other_patient, _ = make_tenant(admin)
        foreign_source = add_source(admin, other_tenant, other_patient)
        own_source = add_source(admin, nurse.tenant_id, patient)
    sql, params = insert_sql("context_tags", nurse.tenant_id, patient, foreign_source)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with transaction(cfg, nurse) as conn:
            conn.execute(sql, params)
    sql, params = insert_sql("context_tags", nurse.tenant_id, patient, own_source)
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction(cfg, nurse) as conn:
            conn.execute(sql.replace("0,13", "13,13"), params)


def test_row_level_security_is_enabled_and_forced_on_every_new_table(sandbox):
    cfg = sandbox[0]
    with psycopg.connect(cfg.admin_database_url) as admin:
        flags = dict(admin.execute(
            "SELECT relname, relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s)", (TABLES,)).fetchall())
    assert flags == {table: True for table in TABLES}


def test_voice_checks_is_not_a_hypertable_until_chunk_access_is_closed(sandbox):
    # decision 004: RLS does not apply to chunk tables, so a runtime read of a chunk would
    # cross tenants. Convert only after that is solved, and replace this test with a chunk test.
    cfg = sandbox[0]
    with psycopg.connect(cfg.admin_database_url) as admin:
        found = admin.execute(
            "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name = ANY(%s)",
            (TABLES,)).fetchone()[0]
    assert found == 0
