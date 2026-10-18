"""Synthetic workspace, loopback-only unless hosted mode is configured explicitly.

Run with python -m scripts.frontend. Hosted mode (decision 005) is opt-in through
PM_FRONTEND_HOSTS (comma-separated public hostnames behind a TLS proxy) and
PM_DEMO_TOKEN (a pre-minted synthetic nurse token served instead of a fresh one).
PM_DEMO_PSW_TOKEN optionally pre-mints the PSW token used by /check resident mode.
"""
import json
import os
import re
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
import uvicorn
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from evals.run import CORPUS, fixture_identity, load_profile
from patient_memory.api import create_app
from patient_memory.auth import Identity, decode_token, synthetic_token
from patient_memory.baseline.ack import well_formed as ack_token_well_formed
from patient_memory.baseline.sessions import owner_gate
from patient_memory.config import Settings
from patient_memory.consent import grant_fixture_consent
from patient_memory.objects import ObjectStore
from patient_memory.storage import transaction
from scripts.demo_handoff import register as register_handoff

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
        psw = psw_identity(reader.tenant_id)
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,%s) "
                     "ON CONFLICT DO NOTHING", (psw.principal_id, psw.tenant_id,
                                                "synthetic-workspace-psw"))
        for patient in patients:
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true) "
                         "ON CONFLICT DO NOTHING",
                         (reader.tenant_id, patient["id"], reader.principal_id))
            # The PSW records checks and skips on /check but never reads scores (decision 017).
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'psw',true) "
                         "ON CONFLICT DO NOTHING",
                         (reader.tenant_id, patient["id"], psw.principal_id))
            grant_fixture_consent(conn, reader.tenant_id, patient["id"], importer.principal_id)
    return reader, patients


def psw_identity(tenant_id):
    return Identity(uuid5(tenant_id, "workspace-psw"), tenant_id)


LOOPBACK = {"localhost", "127.0.0.1", "::1"}
LOCAL_JWT_SECRET = Settings.model_fields["jwt_secret"].default


def require_deployment_secret(cfg):
    """The default signing secret is public in the repo: anyone could mint tokens with it."""
    if len(cfg.jwt_secret) < 32 or cfg.jwt_secret == LOCAL_JWT_SECRET:
        raise ValueError("Hosted mode needs a deployment-only PM_JWT_SECRET of at least "
                         "32 characters, not the local default")
    return cfg


SHELL_ROUTES = ("/unit", "/check", "/resident/{patient_id}", "/out", "/out/session/{session_id}")
PUBLIC_SHELL_PATHS = {"/", "/unit", "/check", "/out"}
PUBLIC_SHELL_DETAIL = re.compile(r"/(?:resident|out/session)/[^/]+")
PAGE_ROUTES = {"/", "/demo/session", *SHELL_ROUTES}
PAGE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; worker-src 'self'"
)


def workspace_app(cfg, reader, patients, extra_hosts=(), demo_token=None, psw=None,
                  psw_token=None):
    """Separate PSW credentials keep resident capture responses free of clinical scores."""
    if extra_hosts and not demo_token:
        raise ValueError("Hosted mode (PM_FRONTEND_HOSTS) requires PM_DEMO_TOKEN")
    if extra_hosts:
        require_deployment_secret(cfg)
    app = create_app(cfg)
    register_handoff(app, cfg, reader)
    for token in (demo_token, psw_token):
        if token:
            decode_token(token, cfg)  # fail at startup, not as 401s on every page
    if psw_token and (psw is None or decode_token(psw_token, cfg) != psw):
        raise ValueError("PSW demo token must match the dedicated PSW identity")
    allowed = LOOPBACK | {h.lower() for h in extra_hosts}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        # SMS/webmail links navigate from another site. This public token capability is
        # deliberately GET-based; keep the exception narrower than an API/origin bypass.
        ack_token = request.url.path.removeprefix("/ack/")
        public_ack_navigation = (
            request.method == "GET" and request.url.path.startswith("/ack/")
            and ack_token_well_formed(ack_token)
            and request.headers.get("sec-fetch-mode") == "navigate"
            and request.headers.get("sec-fetch-dest") == "document")
        # Public hosted HTML contains no credentials or patient records. Let a judge follow
        # an external link to it; bootstrap/API requests retain the same-origin guards.
        public_shell_navigation = (
            bool(extra_hosts) and request.method == "GET"
            and request.headers.get("sec-fetch-mode") == "navigate"
            and request.headers.get("sec-fetch-dest") == "document"
            and (request.url.path in PUBLIC_SHELL_PATHS
                 or PUBLIC_SHELL_DETAIL.fullmatch(request.url.path) is not None))
        # Behind a TLS proxy the client address is the visitor's, so hosted mode relies on
        # the Host allowlist; without extra hosts the client must still be loopback.
        if ((not extra_hosts and (not request.client or request.client.host not in LOOPBACK))
                or host not in allowed
                or (origin and origin != f"{request.url.scheme}://{request.url.netloc}"
                    and not public_shell_navigation)
                or (request.headers.get("sec-fetch-site") == "cross-site"
                    and not (public_ack_navigation or public_shell_navigation))):
            return JSONResponse({"error": {"message": "Local workspace only"}}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        page = getattr(request.scope.get("route"), "path", None) in PAGE_ROUTES
        response.headers["Content-Security-Policy"] = PAGE_CSP if page else (
            response.headers.get("Content-Security-Policy", "frame-ancestors 'none'"))
        if request.url.path == "/assets/motion-worker.js":
            # Emscripten bindings compile inside this isolated worker, never in page scripts.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; "
                "connect-src 'self'; worker-src 'self' blob:; base-uri 'none'")
        return response

    @app.get("/demo/session", include_in_schema=False)
    def session(request: Request):
        if request.headers.get("x-pm-demo") != "1":
            return JSONResponse({"error": {"message": "Workspace header required"}}, status_code=403)
        if request.headers.get("x-pm-role") == "kaze":
            token = os.environ.get("PM_DEMO_KAZE_TOKEN")
            patient = os.environ.get("PM_DEMO_KAZE_PATIENT_ID")
            if not token or not patient:
                return JSONResponse({"error": {"message": "KAZE demo unavailable"}}, status_code=503)
            try:
                identity, pid = decode_token(token, cfg), UUID(patient)
            except (ValueError, TypeError):
                return JSONResponse({"error": {"message": "KAZE demo unavailable"}}, status_code=503)
            # Separate synthetic safety tenant and self-custody importer, never nurse fallback.
            with transaction(cfg, identity) as conn:
                owner_gate(conn, pid)
                if identity.principal_id != pid:
                    return JSONResponse({"error": {"message": "KAZE demo unavailable"}}, status_code=503)
                name = conn.execute("SELECT external_id FROM patients WHERE id=%s", (pid,)
                                    ).fetchone()["external_id"]
            return {"token": token, "patients": [{"id": str(pid), "name": name}],
                    "provider": cfg.provider}
        # Hosted mode serves only pre-minted tokens; locally a PSW token is minted on demand.
        minted = psw_token or (synthetic_token(psw, cfg) if psw and not extra_hosts else None)
        is_psw = request.headers.get("x-pm-role") == "psw"
        if is_psw and not minted:
            return JSONResponse({"error": {"message": "PSW demo token unavailable"}}, status_code=503)
        return {"token": minted if is_psw else demo_token or synthetic_token(reader, cfg),
                "patients": patients, "provider": cfg.provider, "as_of": "2026-01-03T00:00:00Z"}

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
    reader, patients = prepare_demo(cfg)
    app = workspace_app(cfg, reader, patients, hosts, os.environ.get("PM_DEMO_TOKEN") or None,
                        psw=psw_identity(reader.tenant_id),
                        psw_token=os.environ.get("PM_DEMO_PSW_TOKEN") or None)
    uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False,
                proxy_headers=bool(hosts), forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
