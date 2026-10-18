"""Explicit synthetic bootstrap and container entry points for BL-20.

`bootstrap` seeds the existing tenant-0 identities (six empty synthetic patients) and prints
the nurse token. It never invents story outcomes: BL-14's loader (PR #53) fills the same
tenant-0 patient UUIDs with the 12-resident roster, and `serve` reads whatever roster the
seeded nurse can see from the database at startup.

`serve` and `worker` run as the non-owner runtime role only; they refuse to start with an
admin database URL in their environment. `check` is the container readiness probe.
"""
import argparse
import logging
import os
import shutil
import time
import urllib.request
from datetime import timedelta

import jwt

from patient_memory.auth import Identity, decode_token
from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.objects import ObjectStore
from patient_memory.storage import require_member, transaction
from scripts.seed import seed, uid

PORT = 8001
TOKEN_WARNING = timedelta(hours=24)
log = logging.getLogger("patient_memory.hosted_demo")


def nurse():
    return Identity(uid("0/nurse"), uid("tenant-0"))


def deployment_settings():
    from scripts.frontend import require_deployment_secret

    return require_deployment_secret(Settings())


def runtime_only(cfg):
    """Long-running processes must not hold the superuser URL (migrate/bootstrap only)."""
    if cfg.admin_database_url:
        raise ValueError("Hosted serve/worker run without admin credentials: "
                         "set PM_ADMIN_DATABASE_URL to an empty value")
    return cfg


def roster(cfg, reader):
    """Patients visible to the seeded nurse under RLS, via the runtime role."""
    with transaction(cfg, reader) as conn:
        require_member(conn)
        rows = conn.execute("SELECT id, external_id FROM patients "
                            "ORDER BY external_id, id").fetchall()
    if not rows:
        raise ValueError("No patients assigned to the seeded nurse: run migrate and bootstrap")
    return [{"id": str(row["id"]), "name": row["external_id"], "reference": row["external_id"],
             "questions": []} for row in rows]


def hosted_app(cfg, patients=None):
    from scripts.frontend import workspace_app

    hosts = tuple(h.strip().lower() for h in os.environ.get("PM_FRONTEND_HOSTS", "").split(",")
                  if h.strip())
    if not hosts or any(":" in h or "/" in h or "*" in h for h in hosts):
        raise ValueError("PM_FRONTEND_HOSTS must contain explicit hostnames without scheme/port")
    token = os.environ.get("PM_DEMO_TOKEN", "")
    reader = nurse()
    if not token or decode_token(token, cfg) != reader:
        raise ValueError("PM_DEMO_TOKEN must be the seeded tenant-0 nurse token")
    warn_if_expiring(token)
    if patients is None:
        patients = roster(cfg, reader)
    return workspace_app(cfg, reader, patients, hosts, token)


def warn_if_expiring(token):
    """The running app keeps serving this token; say so before it turns into 401s."""
    # Signature and expiry were already verified by decode_token; only exp is read here.
    claims = jwt.decode(token, options={"verify_signature": False})
    left = claims["exp"] - now().timestamp()
    if left < TOKEN_WARNING.total_seconds():
        log.warning("PM_DEMO_TOKEN expires in %.1f h: rerun bootstrap, update .env.demo and "
                    "recreate api before it lapses", left / 3600)
    return left


def readiness(cfg):
    """Runtime DB role + bootstrap identity, bucket, ffmpeg and the serving app itself."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed")
    with transaction(cfg, nurse()) as conn:
        require_member(conn)
    ObjectStore(cfg).client.head_bucket(Bucket=cfg.object_bucket)
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/health/live", timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f"liveness returned {response.status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "serve", "worker", "check"))
    args = parser.parse_args()
    cfg = deployment_settings()
    if args.command == "bootstrap":
        ObjectStore(cfg).initialize()
        # Explicit CLI provisioning only. Do not print importer/admin bearer tokens.
        print(seed(cfg)["nurse"])
    elif args.command == "check":
        readiness(cfg)
    elif args.command == "serve":
        import uvicorn

        app = hosted_app(runtime_only(cfg))
        # Loopback unless the container overlay opts in; never bind publicly by default.
        host = os.environ.get("PM_BIND_HOST", "127.0.0.1")
        uvicorn.run(app, host=host, port=PORT, access_log=False, proxy_headers=True,
                    forwarded_allow_ips=os.environ.get("PM_PROXY_TRUSTED_IPS", "127.0.0.1"))
    else:
        from patient_memory.worker import run_once

        runtime_only(cfg)
        actor = Identity(uid("0/importer"), uid("tenant-0"))
        objects = ObjectStore(cfg)
        while True:
            if not run_once(cfg, actor, objects):
                time.sleep(1)


if __name__ == "__main__":
    main()
