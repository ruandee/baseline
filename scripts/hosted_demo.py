"""Explicit synthetic bootstrap and container entry points for BL-20.

BL-14/21 will supply the complete cohort/reset. This seeds the existing tenant-0
identities and six empty synthetic patients, without inventing story outcomes.
"""
import argparse
import os
import time

import uvicorn

from patient_memory.auth import Identity, decode_token
from patient_memory.config import Settings
from patient_memory.objects import ObjectStore
from patient_memory.worker import run_once
from scripts.frontend import workspace_app
from scripts.seed import seed, uid


def deployment_settings():
    cfg = Settings()
    if len(cfg.jwt_secret) < 32 or cfg.jwt_secret == Settings.model_fields["jwt_secret"].default:
        raise ValueError("Set a deployment-only PM_JWT_SECRET of at least 32 characters")
    return cfg


def hosted_app(cfg):
    hosts = tuple(h.strip().lower() for h in os.environ.get("PM_FRONTEND_HOSTS", "").split(",")
                  if h.strip())
    if not hosts or any(":" in h or "/" in h or "*" in h for h in hosts):
        raise ValueError("PM_FRONTEND_HOSTS must contain explicit hostnames without scheme/port")
    token = os.environ.get("PM_DEMO_TOKEN", "")
    reader = Identity(uid("0/nurse"), uid("tenant-0"))
    if not token or decode_token(token, cfg) != reader:
        raise ValueError("PM_DEMO_TOKEN must be the seeded tenant-0 nurse token")
    patients = [{"id": str(uid(f"0/patient-{i}")), "name": f"Synthetic Resident {i + 1}",
                 "reference": f"synthetic-patient-{i}", "questions": []} for i in range(6)]
    return workspace_app(cfg, reader, patients, hosts, token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "serve", "worker"))
    args = parser.parse_args()
    cfg = deployment_settings()
    if args.command == "bootstrap":
        ObjectStore(cfg).initialize()
        # Explicit CLI provisioning only. Do not print importer/admin bearer tokens.
        print(seed(cfg)["nurse"])
    elif args.command == "serve":
        app = hosted_app(cfg)
        uvicorn.run(app, host="0.0.0.0", port=8001, access_log=False, proxy_headers=True,
                    forwarded_allow_ips=os.environ.get("PM_PROXY_TRUSTED_IPS", "127.0.0.1"))
    else:
        actor = Identity(uid("0/importer"), uid("tenant-0"))
        objects = ObjectStore(cfg)
        while True:
            if not run_once(cfg, actor, objects):
                time.sleep(1)


if __name__ == "__main__":
    main()
