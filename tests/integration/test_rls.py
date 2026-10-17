import psycopg
import pytest

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.storage import transaction
from scripts.seed import seed, uid


@pytest.fixture(scope="session", autouse=True)
def synthetic_identities():
    seed()


def test_actual_runtime_role_is_scoped_and_not_owner():
    cfg = Settings()
    with transaction(cfg, Identity(uid("0/nurse"), uid("tenant-0"))) as conn:
        assert conn.execute("SELECT count(*) AS n FROM patients").fetchone()["n"] == 6
        assert not conn.execute("SELECT * FROM patients WHERE id=%s", (uid("1/patient-0"),)).fetchone()
        role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert not role["rolsuper"] and not role["rolbypassrls"]
    with psycopg.connect(cfg.database_url) as conn:
        assert conn.execute("SELECT count(*) FROM patients").fetchone()[0] == 0
