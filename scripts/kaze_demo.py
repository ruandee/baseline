"""Idempotent KAZE demo tenant (decision 018); synthetic identities only.

Creates the separate `kaze-demo` tenant with safety_mode on, two people going out (each an
importer on their own patient row) and the `kaze-service` principal the scheduler and sender run
as (nurse on every person). CLI writes short-lived tokens to an ignored local artifact.
Never run against a real database.
"""
import json
from pathlib import Path

import psycopg

from patient_memory.auth import Identity, synthetic_token
from patient_memory.config import Settings
from patient_memory.consent import grant_fixture_consent
from scripts.seed import uid

PEOPLE = 2


def kaze_demo(cfg=None, *, grant_consent=False) -> dict:
    cfg = cfg or Settings()
    tenant, service = uid("kaze-demo"), uid("kaze-demo/service")
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO tenants(id,name,safety_mode) VALUES(%s,'kaze-demo',true) "
                     "ON CONFLICT (id) DO UPDATE SET safety_mode=true", (tenant,))
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'kaze-service') "
                     "ON CONFLICT DO NOTHING", (service, tenant))
        for n in range(PEOPLE):
            person = uid(f"kaze-demo/person-{n}")
            conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,%s) "
                         "ON CONFLICT DO NOTHING", (person, tenant, f"kaze-person-{n}"))
            conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s) "
                         "ON CONFLICT DO NOTHING", (person, tenant, f"kaze-person-{n}"))
            for principal, role in [(person, "importer"), (service, "nurse")]:
                conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true) "
                             "ON CONFLICT DO NOTHING", (tenant, person, principal, role))
            if grant_consent:
                grant_fixture_consent(conn, tenant, person, person)
    people = [uid(f"kaze-demo/person-{n}") for n in range(PEOPLE)]
    return {
        "tenant_id": str(tenant),
        "service": {"principal_id": str(service),
                    "token": synthetic_token(Identity(service, tenant), cfg)},
        "people": [{"patient_id": str(p), "token": synthetic_token(Identity(p, tenant), cfg)}
                   for p in people],
    }


def main():
    output = Path("artifacts/kaze-demo/session.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(kaze_demo(), indent=2), encoding="utf-8")
    output.chmod(0o600)
    print(f"Synthetic KAZE identities written to ignored {output}; configure locally, never share it.")


if __name__ == "__main__":
    main()
