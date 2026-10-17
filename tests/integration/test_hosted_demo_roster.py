from uuid import uuid4

import psycopg
import pytest

from patient_memory.auth import Identity
from patient_memory.errors import Problem
from scripts.hosted_demo import roster


def test_roster_is_rls_scoped_through_runtime_role(sandbox):
    cfg, pid, actors, _ = sandbox
    # Another patient in the same tenant that the nurse is not assigned to stays invisible.
    hidden = uuid4()
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                     (hidden, actors["nurse"].tenant_id, "synthetic-unassigned"))
    assert [p["id"] for p in roster(cfg, actors["nurse"])] == [str(pid)]
    # The admin principal has no assignments: no roster, so hosted startup refuses.
    with pytest.raises(ValueError, match="bootstrap"):
        roster(cfg, actors["admin"])
    # A token for a principal that bootstrap never created fails before any patient read.
    with pytest.raises(Problem):
        roster(cfg, Identity(uuid4(), actors["nurse"].tenant_id))
