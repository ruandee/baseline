"""Synthetic workspace, loopback-only unless hosted mode is configured explicitly.

Run with python -m scripts.frontend. Hosted mode (decision 005) is opt-in through
PM_FRONTEND_HOSTS (comma-separated public hostnames behind a TLS proxy) and
PM_DEMO_TOKEN (a pre-minted synthetic nurse token served instead of a fresh one).
"""
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
import uvicorn
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from evals.run import CORPUS, fixture_identity, load_profile
from patient_memory.api import create_app
from patient_memory.auth import Identity, decode_token, synthetic_token
from patient_memory.config import Settings
from patient_memory.objects import ObjectStore

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["Alex Morgan", "Jamie Chen", "Sam Rivera", "Taylor Brooks", "Jordan Lee",
         "Casey Patel", "Riley Park", "Avery Ellis", "Quinn Davis", "Cameron Reed",
         "Drew Wilson", "Robin Hayes"]


def prepare_demo(cfg):
    objects = ObjectStore(cfg)
    objects.initialize()
    importer = fixture_identity(cfg, uuid5(NAMESPACE_URL, "patient-memory/frontend-v1"), 0)
    reader = Identity(uuid5(importer.tenant_id, "workspace-nurse"), importer.tenant_id)
    patients = []
    for index, profile in enumerate(json.loads(CORPUS.read_text())["profiles"]):
        patient, _ = load_profile(cfg, objects, importer, profile)
        patients.append({"id": str(patient), "reference": profile["id"],
                         "name": NAMES[index], "questions": [q[0] for q in profile["questions"]]})
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,%s) "
                     "ON CONFLICT DO NOTHING", (reader.principal_id, reader.tenant_id,
                                                "synthetic-workspace-nurse"))
        for patient in patients:
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true) "
                         "ON CONFLICT DO NOTHING",
                         (reader.tenant_id, patient["id"], reader.principal_id))
    return reader, patients


LOOPBACK = {"localhost", "127.0.0.1", "::1"}
LOCAL_JWT_SECRET = Settings.model_fields["jwt_secret"].default


def require_deployment_secret(cfg):
    """The default signing secret is public in the repo: anyone could mint tokens with it."""
    if len(cfg.jwt_secret) < 32 or cfg.jwt_secret == LOCAL_JWT_SECRET:
        raise ValueError("Hosted mode needs a deployment-only PM_JWT_SECRET of at least "
                         "32 characters, not the local default")
    return cfg


SHELL_ROUTES = ("/unit", "/check", "/resident/{patient_id}")
PAGE_ROUTES = {"/", "/demo/session", *SHELL_ROUTES}
PAGE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def workspace_app(cfg, reader, patients, extra_hosts=(), demo_token=None):
    if extra_hosts and not demo_token:
        raise ValueError("Hosted mode (PM_FRONTEND_HOSTS) requires PM_DEMO_TOKEN")
    if extra_hosts:
        require_deployment_secret(cfg)
    app = create_app(cfg)
    if demo_token:
        decode_token(demo_token, cfg)  # fail at startup, not as 401s on every page
    allowed = LOOPBACK | {h.lower() for h in extra_hosts}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        # Behind a TLS proxy the client address is the visitor's, so hosted mode relies on
        # the Host allowlist; without extra hosts the client must still be loopback.
        if ((not extra_hosts and (not request.client or request.client.host not in LOOPBACK))
                or host not in allowed
                or (origin and origin != f"{request.url.scheme}://{request.url.netloc}")
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse({"error": {"message": "Local workspace only"}}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        page = getattr(request.scope.get("route"), "path", None) in PAGE_ROUTES
        response.headers["Content-Security-Policy"] = PAGE_CSP if page else (
            response.headers.get("Content-Security-Policy", "frame-ancestors 'none'"))
        return response

    @app.get("/demo/session", include_in_schema=False)
    def session(request: Request):
        if request.headers.get("x-pm-demo") != "1":
            return JSONResponse({"error": {"message": "Workspace header required"}}, status_code=403)
        return {"token": demo_token or synthetic_token(reader, cfg), "patients": patients,
                "provider": cfg.provider, "as_of": "2026-01-03T00:00:00Z"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    def baseline_shell(request: Request):
        return FileResponse(ROOT / "frontend" / "baseline.html")

    for path in SHELL_ROUTES:
        app.add_api_route(path, baseline_shell, methods=["GET"], include_in_schema=False)

    app.mount("/assets", StaticFiles(directory=ROOT / "frontend"), name="workspace-assets")
    return app


def main():
    cfg = Settings(provider="stub")
    hosts = tuple(h.strip() for h in os.environ.get("PM_FRONTEND_HOSTS", "").split(",")
                  if h.strip())
    if hosts:
        # Refuse before any fixture write, not after loading the corpus.
        require_deployment_secret(cfg)
    # Fixture bootstrap is explicit CLI work, never an unauthenticated API write.
    reader, patients = prepare_demo(cfg)
    app = workspace_app(cfg, reader, patients, hosts, os.environ.get("PM_DEMO_TOKEN") or None)
    uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False,
                proxy_headers=bool(hosts), forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
