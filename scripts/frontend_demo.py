"""Create a synthetic, nurse-scoped browser session. Tokens only travel in the URL fragment."""
import argparse
import json
import webbrowser
from urllib.parse import quote
from uuid import uuid4, uuid5

import psycopg

from evals.run import CORPUS, fixture_identity, load_profile
from patient_memory.auth import Identity, synthetic_token
from patient_memory.config import Settings
from patient_memory.objects import ObjectStore


def prepare_session(cfg):
    objects = ObjectStore(cfg)
    objects.initialize()
    importer = fixture_identity(cfg, uuid4(), 0)
    nurse = Identity(uuid5(importer.tenant_id, "frontend-nurse"), importer.tenant_id)
    profiles = json.loads(CORPUS.read_text())["profiles"][:6]
    entries = []
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,%s)",
                     (nurse.principal_id, nurse.tenant_id, "synthetic-frontend-nurse"))
    token = synthetic_token(nurse, cfg)
    for i, profile in enumerate(profiles):
        patient, _ = load_profile(cfg, objects, importer, profile)
        with psycopg.connect(cfg.admin_database_url) as conn:
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true)",
                         (nurse.tenant_id, patient, nurse.principal_id))
        entries.append({"patient_id": str(patient), "profile": profile["id"],
                        "name": f"Demo patient {i + 1:02d}", "token": token})
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="Open the local walkthrough in a browser")
    args = parser.parse_args()
    cfg = Settings()
    if cfg.provider != "stub":
        raise SystemExit("Set PM_PROVIDER=stub for this walkthrough (also on the API process).")
    entries = prepare_session(cfg)
    url = "http://127.0.0.1:8000/app/#" + quote(json.dumps(entries), safe="")
    if args.open:
        webbrowser.open(url)
        print("Opened the synthetic walkthrough. Session expires after eight hours.")
    else:
        print(url)


if __name__ == "__main__":
    main()
