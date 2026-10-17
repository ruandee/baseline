"""Loopback-only synthetic workspace. Run with python -m scripts.frontend."""
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
import uvicorn
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from evals.run import CORPUS, fixture_identity, load_profile
from patient_memory.api import create_app
from patient_memory.auth import Identity, synthetic_token
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


def workspace_app(cfg, reader, patients):
    app = create_app(cfg)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        allowed = {"localhost", "127.0.0.1", "::1"}
        if (not request.client or request.client.host not in allowed or host not in allowed
                or (origin and origin != f"{request.url.scheme}://{request.url.netloc}")
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse({"error": {"message": "Local workspace only"}}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        ) if request.url.path in {"/", "/demo/session"} else response.headers.get(
            "Content-Security-Policy", "frame-ancestors 'none'")
        return response

    @app.get("/demo/session", include_in_schema=False)
    def session(request: Request):
        if request.headers.get("x-pm-demo") != "1":
            return JSONResponse({"error": {"message": "Workspace header required"}}, status_code=403)
        return {"token": synthetic_token(reader, cfg), "patients": patients,
                "provider": cfg.provider, "as_of": "2026-01-03T00:00:00Z"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    app.mount("/assets", StaticFiles(directory=ROOT / "frontend"), name="workspace-assets")
    return app


def main():
    cfg = Settings(provider="stub")
    # Fixture bootstrap is explicit CLI work, never an unauthenticated API write.
    reader, patients = prepare_demo(cfg)
    uvicorn.run(workspace_app(cfg, reader, patients), host="127.0.0.1", port=8001,
                access_log=False)


if __name__ == "__main__":
    main()
