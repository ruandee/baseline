"""Idempotent synthetic identities; never run against a real patient database."""
import json
from uuid import NAMESPACE_URL, uuid5

import psycopg

from patient_memory.auth import Identity, synthetic_token
from patient_memory.check_profiles import seed_english_profile
from patient_memory.config import Settings
from patient_memory.consent import grant_fixture_consent


def uid(name):
    return uuid5(NAMESPACE_URL, f"patient-memory/synthetic/{name}")


def seed(cfg=None):
    cfg = cfg or Settings()
    with psycopg.connect(cfg.admin_database_url) as conn:
        for tenant in range(2):
            tid = uid(f"tenant-{tenant}")
            conn.execute("INSERT INTO tenants VALUES(%s,%s) ON CONFLICT DO NOTHING",
                         (tid, f"synthetic-tenant-{tenant}"))
            for role in ["admin", "importer", "nurse", "patient", "psw"]:
                actor = uid(f"{tenant}/{role}")
                conn.execute(
                    "INSERT INTO principals(id,tenant_id,name,administrator) VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (actor, tid, f"synthetic-{role}", role == "admin"))
            for p in range(6):
                pid = uid(f"{tenant}/patient-{p}")
                conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s) "
                             "ON CONFLICT DO NOTHING", (pid, tid, f"synthetic-patient-{p}"))
                for role in ["importer", "nurse", "patient", "psw"]:
                    if role == "patient" and p != 0:
                        continue
                    conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true) "
                                 "ON CONFLICT DO NOTHING", (tid, pid, uid(f"{tenant}/{role}"), role))
                # Decision 017: explicit synthetic consent; a later withdrawal is never undone.
                grant_fixture_consent(conn, tid, pid, uid(f"{tenant}/importer"))
                seed_english_profile(conn, tid, pid, uid(f"{tenant}/importer"))
    return {role: synthetic_token(Identity(uid(f"0/{role}"), uid("tenant-0")), cfg)
            for role in ["admin", "importer", "nurse", "patient", "psw"]}


if __name__ == "__main__":
    print(json.dumps({"patient_id": str(uid("0/patient-0")), "tokens": seed()}, indent=2))
