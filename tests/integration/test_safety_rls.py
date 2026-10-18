"""KAZE session tables under the runtime role (decision 018): forced RLS, safety-tenant only,
session-scoped foreign keys, the public acknowledgement function and 24 h retention."""
import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from patient_memory.auth import Identity
from patient_memory.baseline.sessions import arm, retire
from patient_memory.domain import SessionArm
from patient_memory.storage import transaction

TABLES = ["safety_sessions", "safety_contacts", "escalation_events"]


def sha(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def clock(admin):
    return admin.execute("SELECT clock_timestamp()").fetchone()[0]


def add_person(admin, tenant, service=None):
    person = uuid4()
    admin.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-person')",
                  (person, tenant))
    admin.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                  (person, tenant, f"synthetic-{person}"))
    admin.execute("INSERT INTO assignments VALUES(%s,%s,%s,'importer',true)", (tenant, person, person))
    if service:
        admin.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true)",
                      (tenant, person, service))
    return person


def add_safety_tenant(admin):
    tenant, service = uuid4(), uuid4()
    admin.execute("INSERT INTO tenants(id,name,safety_mode) VALUES(%s,'synthetic-kaze-2',true)",
                  (tenant,))
    admin.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-service')",
                  (service, tenant))
    return tenant, Identity(service, tenant)


def add_session(admin, tenant, patient, status="escalating", created=-3600, ends=3600, episode=1,
                ended=-1800):
    """Offsets in seconds from the database clock; deletion is always 24 h after the end."""
    t = clock(admin)

    def at(seconds):
        return t + timedelta(seconds=seconds)

    sid = uuid4()
    admin.execute(
        "INSERT INTO safety_sessions(tenant_id,patient_id,id,display_name,status,created_at,"
        "activated_at,ends_at,next_due_at,ladder_level,episode,ladder_trigger,acknowledged_at,"
        "ended_at,end_reason,delete_after) "
        "VALUES(%s,%s,%s,'Sam',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (tenant, patient, sid, status, at(created),
         None if status == "arming" else at(created), at(ends),
         at(60) if status in ("active", "escalating") else None,
         2 if status == "escalating" else 0, episode,
         "missed_checkin" if status == "escalating" else None,
         t if status == "acknowledged" else None,
         at(ended) if status == "ended" else None, "user" if status == "ended" else None,
         at(ended + 86400) if status == "ended" else None))
    admin.execute("INSERT INTO safety_contacts VALUES(%s,%s,%s,1,'Dee','+14165550101')",
                  (tenant, patient, sid))
    return sid


def add_event(admin, tenant, patient, sid, episode=1, level=2, token=None, expires=3600):
    eid = uuid4()
    admin.execute(
        "INSERT INTO escalation_events(tenant_id,patient_id,id,session_id,episode,level,trigger,"
        "channel,contact_index,ack_token_hash,ack_expires_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,'missed_checkin','sms',1,%s,%s)",
        (tenant, patient, eid, sid, episode, level, sha(token) if token else None,
         clock(admin) + timedelta(seconds=expires) if token else None))
    return eid


def check_sql(tenant, patient, session=None, lat=None, lon=None):
    return ("INSERT INTO voice_checks(tenant_id,patient_id,id,device_id,mode,usable,quality,"
            "session_id,lat,lon) VALUES(%s,%s,%s,'phone','live',true,%s,%s,%s,%s)",
            (tenant, patient, uuid4(), Jsonb({"reasons": []}), session, lat, lon))


def session_sql(tenant, patient):
    return ("INSERT INTO safety_sessions(tenant_id,patient_id,id,display_name,ends_at) "
            "VALUES(%s,%s,%s,'Sam',clock_timestamp()+interval '1 hour')", (tenant, patient, uuid4()))


@pytest.fixture
def admin():
    from patient_memory.config import Settings
    with psycopg.connect(Settings().admin_database_url, autocommit=True) as conn:
        yield conn


def test_row_level_security_is_enabled_and_forced_on_every_session_table(kaze_sandbox, admin):
    flags = dict(admin.execute(
        "SELECT relname, relrowsecurity AND relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY(%s)", (TABLES,)).fetchall())
    assert flags == {table: True for table in TABLES}


def test_each_person_sees_only_their_own_session_rows(kaze_sandbox, sandbox, admin):
    k = kaze_sandbox
    for patient in [k["patient"], k["other_patient"]]:
        sid = add_session(admin, k["tenant"], patient)
        add_event(admin, k["tenant"], patient, sid)
    for table in TABLES:
        for who, expected in [("person", [k["patient"]]), ("other", [k["other_patient"]]),
                              ("service", sorted([k["patient"], k["other_patient"]]))]:
            with transaction(k["cfg"], k["ids"][who]) as conn:
                seen = [r["patient_id"] for r in conn.execute(
                    f"SELECT DISTINCT patient_id FROM {table} ORDER BY patient_id").fetchall()]
            assert seen == expected, (table, who)
        # An unassigned administrator and a resident-tenant nurse see nothing.
        for identity in [k["ids"]["admin"], sandbox[2]["nurse"]]:
            with transaction(k["cfg"], identity) as conn:
                assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def test_only_the_person_arms_and_only_inside_a_safety_tenant(kaze_sandbox, sandbox):
    k = kaze_sandbox
    with transaction(k["cfg"], k["ids"]["person"]) as conn:
        conn.execute(*session_sql(k["tenant"], k["patient"]))
    attempts = [
        (k["ids"]["person"], k["tenant"], k["other_patient"]),  # someone else's row
        (k["ids"]["service"], k["tenant"], k["other_patient"]),  # care team cannot arm
        (sandbox[2]["importer"], sandbox[2]["importer"].tenant_id, sandbox[1]),  # resident tenant
    ]
    for identity, tenant, patient in attempts:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with transaction(k["cfg"], identity) as conn:
                conn.execute(*session_sql(tenant, patient))


def test_one_open_session_per_person(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"], status="active")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with transaction(k["cfg"], k["ids"]["person"]) as conn:
            conn.execute(*session_sql(k["tenant"], k["patient"]))
    admin.execute("UPDATE safety_sessions SET status='ended',ended_at=now(),end_reason='user',"
                  "delete_after=now()+interval '24 hours',next_due_at=NULL WHERE id=%s", (sid,))
    with transaction(k["cfg"], k["ids"]["person"]) as conn:
        conn.execute(*session_sql(k["tenant"], k["patient"]))


def test_contacts_checks_and_events_cannot_point_at_another_persons_session(kaze_sandbox, admin):
    k = kaze_sandbox
    theirs = add_session(admin, k["tenant"], k["other_patient"])
    mine = add_session(admin, k["tenant"], k["patient"])
    writes = [
        (k["ids"]["person"], "INSERT INTO safety_contacts VALUES(%s,%s,%s,2,'Eve','+14165550102')",
         (k["tenant"], k["patient"], theirs)),
        (k["ids"]["person"], *check_sql(k["tenant"], k["patient"], theirs, 43.6, -79.4)),
        (k["ids"]["service"],
         "INSERT INTO escalation_events(tenant_id,patient_id,id,session_id,episode,level,trigger,"
         "channel,contact_index) VALUES(%s,%s,%s,%s,1,2,'missed_checkin','sms',1)",
         (k["tenant"], k["patient"], uuid4(), theirs)),
        # contact 2 does not exist on my own session
        (k["ids"]["service"],
         "INSERT INTO escalation_events(tenant_id,patient_id,id,session_id,episode,level,trigger,"
         "channel,contact_index) VALUES(%s,%s,%s,%s,1,2,'missed_checkin','sms',2)",
         (k["tenant"], k["patient"], uuid4(), mine)),
    ]
    for identity, sql, params in writes:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with transaction(k["cfg"], identity) as conn:
                conn.execute(sql, params)


def test_location_is_stored_only_with_a_session_and_checks_stay_append_only(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"])
    with transaction(k["cfg"], k["ids"]["person"]) as conn:
        conn.execute(*check_sql(k["tenant"], k["patient"], sid, 43.6, -79.4))
    for session, lat, lon in [(None, 43.6, -79.4), (sid, 43.6, None), (sid, 91.0, 0.0)]:
        with pytest.raises(psycopg.errors.CheckViolation):
            with transaction(k["cfg"], k["ids"]["person"]) as conn:
                conn.execute(*check_sql(k["tenant"], k["patient"], session, lat, lon))
    for statement in ["DELETE FROM voice_checks", "DELETE FROM safety_sessions",
                      "DELETE FROM safety_contacts", "DELETE FROM escalation_events",
                      "UPDATE safety_contacts SET name='x'"]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with transaction(k["cfg"], k["ids"]["person"]) as conn:
                conn.execute(statement)


def test_service_cannot_move_a_session_to_another_patient(kaze_sandbox, sandbox, admin):
    k = kaze_sandbox
    add_session(admin, k["tenant"], k["patient"])
    with transaction(k["cfg"], k["ids"]["service"]) as conn:
        assert conn.execute("UPDATE safety_sessions SET ladder_level=3 WHERE patient_id=%s",
                            (k["patient"],)).rowcount == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(k["cfg"], k["ids"]["service"]) as conn:
            conn.execute("UPDATE safety_sessions SET patient_id=%s WHERE patient_id=%s",
                         (sandbox[1], k["patient"]))


def test_a_duplicate_scheduler_step_conflicts_instead_of_sending_twice(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"])
    sms = ("INSERT INTO escalation_events(tenant_id,patient_id,id,session_id,episode,level,trigger,"
           "channel,contact_index) VALUES(%s,%s,%s,%s,1,2,'missed_checkin','sms',1)")
    nudge = ("INSERT INTO escalation_events(tenant_id,patient_id,id,session_id,episode,level,trigger,"
             "channel) VALUES(%s,%s,%s,%s,1,1,'missed_checkin','nudge')")
    for sql in [sms, nudge]:
        with transaction(k["cfg"], k["ids"]["service"]) as conn:
            conn.execute(sql, (k["tenant"], k["patient"], uuid4(), sid))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with transaction(k["cfg"], k["ids"]["service"]) as conn:
                conn.execute(sql, (k["tenant"], k["patient"], uuid4(), sid))
    with pytest.raises(psycopg.errors.CheckViolation):  # a nudge never names a contact
        with transaction(k["cfg"], k["ids"]["service"]) as conn:
            conn.execute(sms.replace("2,'missed_checkin','sms'", "1,'missed_checkin','nudge'"),
                         (k["tenant"], k["patient"], uuid4(), sid))


def ack(cfg, token):
    """The public route has no bearer identity: a bare runtime connection, no pm.tenant."""
    with psycopg.connect(cfg.database_url) as conn:
        assert conn.execute("SELECT count(*) FROM escalation_events").fetchone()[0] == 0
        return conn.execute("SELECT pm_acknowledge_escalation(%s)", (sha(token),)).fetchone()[0]


def session_state(admin, sid):
    return admin.execute("SELECT status,acknowledged_at FROM safety_sessions WHERE id=%s",
                         (sid,)).fetchone()


def test_acknowledgement_stops_only_the_current_episode(kaze_sandbox, admin):
    k = kaze_sandbox
    cfg = k["cfg"]
    assert ack(cfg, "no-such-token") == "invalid"
    sid = add_session(admin, k["tenant"], k["patient"], episode=2)
    old = add_event(admin, k["tenant"], k["patient"], sid, episode=1, token="old-episode")
    add_event(admin, k["tenant"], k["patient"], sid, episode=2, level=3, token="expired", expires=-1)
    current = add_event(admin, k["tenant"], k["patient"], sid, episode=2, level=2, token="current")

    assert ack(cfg, "expired") == "invalid"
    assert ack(cfg, "old-episode") == "recorded"
    assert session_state(admin, sid)[0] == "escalating"
    assert ack(cfg, "current") == "acknowledged"
    status, acknowledged_at = session_state(admin, sid)
    assert status == "acknowledged" and acknowledged_at is not None
    first = admin.execute("SELECT ack_at FROM escalation_events WHERE id=%s", (current,)).fetchone()[0]
    assert ack(cfg, "current") == "recorded"  # replay changes nothing
    again = admin.execute("SELECT ack_at FROM escalation_events WHERE id=%s", (current,)).fetchone()[0]
    assert first == again and session_state(admin, sid)[0] == "acknowledged"
    assert admin.execute("SELECT ack_at FROM escalation_events WHERE id=%s", (old,)).fetchone()[0]
    assert admin.execute("SELECT ack_at FROM escalation_events WHERE ack_token_hash=%s",
                         (sha("expired"),)).fetchone()[0] is None


def test_acknowledgement_of_an_ended_session_is_invalid(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"], status="ended")
    add_event(admin, k["tenant"], k["patient"], sid, token="late")
    assert ack(k["cfg"], "late") == "invalid"


def test_retention_expires_then_deletes_only_the_callers_tenant(kaze_sandbox, admin):
    k = kaze_sandbox
    tenant, service = k["tenant"], k["ids"]["service"]
    expiring, purged, recent = (add_person(admin, tenant, service.principal_id) for _ in range(3))
    expiring_sid = add_session(admin, tenant, expiring, status="active", created=-7200, ends=-60)
    # Armed through the idempotent API path, so an operations snapshot exists, then aged.
    body = SessionArm(display_name="Sam", ends_at=clock(admin) + timedelta(hours=2),
                      contacts=[{"name": "Dee", "phone_e164": "+14165550101"}])
    with transaction(k["cfg"], Identity(purged, tenant)) as conn:
        purged_sid = UUID(arm(conn, Identity(purged, tenant), purged, body, "arm-1", uuid4())["id"])
    admin.execute(
        "UPDATE safety_sessions SET status='ended',created_at=now()-interval '30 hours',"
        "ends_at=now()-interval '29 hours',ended_at=now()-interval '29 hours',end_reason='user',"
        "delete_after=now()-interval '5 hours' WHERE id=%s", (purged_sid,))
    snapshot = ("SELECT count(*) FROM operations WHERE patient_id=%s AND operation='arm_session'",
                (purged,))
    assert admin.execute(*snapshot).fetchone()[0] == 1
    recent_sid = add_session(admin, tenant, recent, status="ended", ended=-60)
    for sid, patient in [(purged_sid, purged), (recent_sid, recent)]:
        sql, params = check_sql(tenant, patient, sid, 43.6, -79.4)
        admin.execute(sql, params)
        admin.execute("INSERT INTO assessments(tenant_id,patient_id,id,check_id,change_status,"
                      "features,params,verdict,suggested_action) "
                      "VALUES(%s,%s,%s,%s,'none','{}','{}','within_normal','none')",
                      (tenant, patient, uuid4(), params[2]))
        add_event(admin, tenant, patient, sid)
    outside = check_sql(tenant, purged)  # the same person's check outside any session stays
    admin.execute(*outside)
    other_tenant, other_service = add_safety_tenant(admin)
    other_person = add_person(admin, other_tenant, other_service.principal_id)
    other_sid = add_session(admin, other_tenant, other_person, status="ended", created=-30 * 3600,
                            ends=-29 * 3600, ended=-29 * 3600)

    assert retire(k["cfg"], service) == 1

    row = admin.execute("SELECT status,end_reason,ended_at=ends_at AS at_end,"
                        "delete_after=ends_at+interval '24 hours' AS window,next_due_at "
                        "FROM safety_sessions WHERE id=%s", (expiring_sid,)).fetchone()
    assert row == ("ended", "expired", True, True, None)

    def count(table, column, value):
        return admin.execute(f"SELECT count(*) FROM {table} WHERE {column}=%s",
                             (value,)).fetchone()[0]

    for table in ["voice_checks", "escalation_events", "safety_contacts"]:
        assert count(table, "session_id", purged_sid) == 0, table
        assert count(table, "session_id", recent_sid) == 1, table
    assert count("safety_sessions", "id", purged_sid) == 0
    assert admin.execute(*snapshot).fetchone()[0] == 0  # idempotency snapshot deleted too
    assert count("assessments", "patient_id", purged) == 0
    assert count("assessments", "patient_id", recent) == 1
    assert count("voice_checks", "id", outside[1][2]) == 1
    assert admin.execute("SELECT count(*) FROM audit WHERE patient_id=%s AND "
                         "action='purge_safety_session'", (purged,)).fetchone()[0] == 1
    assert count("safety_sessions", "id", other_sid) == 1  # another tenant is untouched

    assert retire(k["cfg"], other_service) == 1
    assert count("safety_sessions", "id", other_sid) == 0


def test_retention_refuses_an_unknown_identity(kaze_sandbox):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        retire(kaze_sandbox["cfg"], Identity(uuid4(), kaze_sandbox["tenant"]))


def test_security_definer_owners_can_bypass_forced_rls(admin):
    # Forced RLS would silently hide rows inside retention/ack if ownership were transferred
    # to the ordinary runtime role. The migration assertion and actual owner must agree.
    functions = ["pm_safety_tenant", "pm_acknowledge_escalation", "pm_retire_safety_sessions"]
    rows = admin.execute(
        "SELECT p.proname,p.prosecdef,r.rolsuper OR r.rolbypassrls AS bypass "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' "
        "AND p.proname=ANY(%s)", (functions,)).fetchall()
    assert sorted(rows) == sorted((name, True, True) for name in functions)


def test_migration_owner_guard_refuses_runtime_role(kaze_sandbox):
    from pathlib import Path
    migration = Path(__file__).parents[2] / "migrations/versions/006_safety_sessions.sql"
    # Execute only the migration's pre-DDL ownership guard under the real runtime role.
    guard = migration.read_text(encoding="utf-8").split("ALTER TABLE tenants", 1)[0]
    with pytest.raises(psycopg.errors.RaiseException, match="superuser or BYPASSRLS"):
        with transaction(kaze_sandbox["cfg"], kaze_sandbox["ids"]["service"]) as conn:
            conn.execute(guard)


def test_ended_is_terminal_and_deletion_cannot_be_postponed(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"], status="ended")
    for who in ["person", "service"]:
        for statement in ["UPDATE safety_sessions SET status='active',ended_at=NULL,end_reason=NULL,"
                          "delete_after=NULL,activated_at=now() WHERE id=%s",
                          "UPDATE safety_sessions SET delete_after=delete_after+interval '1 day',"
                          "ended_at=ended_at+interval '1 day' WHERE id=%s"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with transaction(k["cfg"], k["ids"][who]) as conn:
                    conn.execute(statement, (sid,))
    # Even on an open session the deletion time is fixed at 24 h after the end.
    open_sid = add_session(admin, k["tenant"], k["other_patient"], status="active")
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction(k["cfg"], k["ids"]["other"]) as conn:
            conn.execute("UPDATE safety_sessions SET status='ended',ended_at=now(),end_reason='user',"
                         "delete_after=now()+interval '30 days' WHERE id=%s", (open_sid,))


def test_runtime_updates_are_limited_to_ladder_and_delivery_columns(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"])
    eid = add_event(admin, k["tenant"], k["patient"], sid, token="t")
    with transaction(k["cfg"], k["ids"]["service"]) as conn:
        assert conn.execute("UPDATE escalation_events SET delivery='logged' WHERE id=%s",
                            (eid,)).rowcount == 1
        assert conn.execute("UPDATE safety_sessions SET ladder_level=3 WHERE id=%s",
                            (sid,)).rowcount == 1
    forbidden = [
        ("UPDATE escalation_events SET ack_token_hash=%s WHERE id=%s", (sha("mine"), eid)),
        ("UPDATE escalation_events SET ack_at=now() WHERE id=%s", (eid,)),
        ("UPDATE escalation_events SET message='x' WHERE id=%s", (eid,)),
        ("UPDATE escalation_events SET ack_expires_at=now()+interval '1 year' WHERE id=%s", (eid,)),
        ("UPDATE safety_sessions SET ends_at=ends_at+interval '1 hour' WHERE id=%s", (sid,)),
        ("UPDATE safety_sessions SET interval_min=180 WHERE id=%s", (sid,)),
        ("UPDATE safety_sessions SET escalation_enabled=false WHERE id=%s", (sid,)),
    ]
    for who in ["person", "service"]:
        for sql, params in forbidden:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with transaction(k["cfg"], k["ids"][who]) as conn:
                    conn.execute(sql, params)
