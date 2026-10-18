from uuid import uuid4

import psycopg
import pytest

from patient_memory.auth import Identity
from patient_memory.errors import Problem
from scripts.hosted_demo import roster


def test_live_display_alias_preserves_stored_identity_and_other_patients(sandbox, monkeypatch):
    from scripts import hosted_demo

    cfg, pid, actors, _ = sandbox
    original_uid = hosted_demo.uid
    monkeypatch.setattr(hosted_demo, "uid", lambda key:
                        pid if key == "0/live-capture" else original_uid(key))
    original = roster(cfg, actors["nurse"])[0]
    named = roster(cfg.model_copy(update={"demo_live_name": "Volunteer A"}), actors["nurse"])[0]
    assert named["id"] == original["id"] == str(pid)
    assert named["reference"] == original["reference"]
    assert named["name"] == "Volunteer A"
    assert named["capture_mode"] == "live"
    assert roster(cfg, actors["nurse"])[0]["name"] == original["name"]


def test_roster_is_rls_scoped_through_runtime_role(sandbox):
    cfg, pid, actors, _ = sandbox
    # Another patient in the same tenant that the nurse is not assigned to stays invisible.
    hidden = uuid4()
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                     (hidden, actors["nurse"].tenant_id, "synthetic-unassigned"))
    assert [p["id"] for p in roster(cfg, actors["nurse"])] == [str(pid)]
    # A principal with no assignments sees no roster, so hosted startup refuses.
    lonely = Identity(uuid4(), actors["nurse"].tenant_id)
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-lonely')",
                     (lonely.principal_id, lonely.tenant_id))
    with pytest.raises(ValueError, match="bootstrap"):
        roster(cfg, lonely)
    # A token for a principal that bootstrap never created fails before any patient read.
    with pytest.raises(Problem):
        roster(cfg, Identity(uuid4(), actors["nurse"].tenant_id))
