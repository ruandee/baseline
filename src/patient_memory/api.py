import logging
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime

from patient_memory.auth import decode_token
from patient_memory.baseline import ack, sessions
from patient_memory.baseline.context import add_context
from patient_memory.baseline.notes import extract_pending_notes
from patient_memory.baseline.overview import overview as build_overview
from patient_memory.baseline.overview import watchlist as build_watchlist
from patient_memory.baseline.sbar import enrich_assessment_sbar
from patient_memory.checks import care_gate, store_check
from patient_memory.config import Settings
from patient_memory.domain import (
    Answer,
    AssignmentInput,
    CheckMode,
    CheckResult,
    ContextInput,
    ContextTagOut,
    NoteExtractionResult,
    PatientInput,
    Question,
    Reason,
    SessionArm,
    SessionEnd,
    SessionList,
    SessionOut,
    SourceInput,
    Summary,
    VisibilityInput,
    now,
)
from patient_memory.errors import Problem
from patient_memory.generation import build_answer
from patient_memory.ingestion import digest, lock_patient, submit
from patient_memory.lifecycle import (
    assign,
    cache_get,
    cache_put,
    change_source,
    rate_limit,
    scope_hash,
)
from patient_memory.objects import ObjectStore
from patient_memory.providers import generator_for
from patient_memory.retrieval import evidence, retrieve
from patient_memory.speech import asr
from patient_memory.speech.pipeline import DecoderUnavailable, InvalidAudio, analyze
from patient_memory.storage import audit, patient_access, require_member, transaction

# Voice-check uploads are the one multipart route; every other route stays JSON only.
CHECK_UPLOAD = re.compile(r"^/v1/patients/[^/]+/checks$")


class PayloadLimit:
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                response = JSONResponse(status_code=413, content={"error": {
                    "code": "payload_too_large", "message": "Payload exceeds limit",
                    "request_id": str(uuid4()), "retryable": False}})
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        headers = dict(scope.get("headers", []))
        upload = scope["method"] == "POST" and CHECK_UPLOAD.match(scope["path"])
        expected = "multipart/form-data" if upload else "application/json"
        if body and headers.get(b"content-type", b"").split(b";")[0] != expected.encode():
            response = JSONResponse(status_code=415, content={"error": {
                "code": "unsupported_content_type", "message": f"Use {expected}",
                "request_id": str(uuid4()), "retryable": False}})
            return await response(scope, receive, send)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


def create_app(cfg=None, objects=None, generator=None, transcriber=None):
    cfg = cfg or Settings()

    @asynccontextmanager
    async def lifespan(app):
        if app.state.transcriber is asr.transcribe:
            try:
                asr.model()  # load Whisper once, so the first check does not pay for it
            except Exception:
                logging.getLogger("patient_memory.requests").exception(
                    "Whisper failed to load; voice checks retry on first use")
        yield

    app = FastAPI(title="Patient Memory â€” synthetic prototype", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.objects = objects or ObjectStore(cfg)
    app.state.generator = generator or generator_for(cfg)
    app.state.transcriber = transcriber or asr.transcribe
    app.add_middleware(PayloadLimit, limit=cfg.max_payload_bytes)
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.monotonic()
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        route = request.scope.get("route")
        logging.getLogger("patient_memory.requests").info(
            "request method=%s route=%s status=%d duration_ms=%.1f",
            request.method, getattr(route, "path", "unmatched"), response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem):
        return JSONResponse(status_code=exc.status,
                            headers={"Retry-After": "60"} if exc.status == 429 else None,
                            content={"error": {
            "code": exc.code, "message": exc.message,
            "request_id": str(request.state.request_id), "retryable": exc.status in {409, 429, 502, 503, 504}}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc):
        # Never echo rejected clinical text or tokens in validation responses.
        syntax = any(error["type"] == "json_invalid" for error in exc.errors())
        return await problem_handler(request, Problem(400 if syntax else 422, "invalid_request"))

    async def dependency_error(request: Request, exc):
        return await problem_handler(request, Problem(503, "dependency_unavailable"))

    for error_type in (psycopg.Error, BotoCoreError, ClientError):
        app.add_exception_handler(error_type, dependency_error)

    def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not credentials:
            raise Problem(401, "invalid_identity")
        actor = decode_token(credentials.credentials, cfg)
        with transaction(cfg, actor) as conn:
            require_member(conn)
        return actor

    actor_dep = Depends(identity)

    @app.get("/v1/health/live")
    def live():
        return {"status": "alive", "mode": "synthetic"}

    @app.get("/v1/health/ready")
    def ready(actor=actor_dep):
        with transaction(cfg, actor) as conn:
            if not require_member(conn)["administrator"]:
                raise Problem(404, "not_found")
            conn.execute("SELECT 1")
        app.state.objects.client.head_bucket(Bucket=cfg.object_bucket)
        return {"status": "ready"}

    @app.post("/v1/patients", status_code=201)
    def create_patient(body: PatientInput, request: Request, actor=actor_dep):
        pid = uuid4()
        with transaction(cfg, actor) as conn:
            if not require_member(conn)["administrator"]:
                raise Problem(404, "not_found")
            try:
                conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                             (pid, actor.tenant_id, body.external_id))
            except psycopg.errors.UniqueViolation as exc:
                raise Problem(409, "patient_exists") from exc
            audit(conn, actor, pid, "create_patient", request.state.request_id)
        return {"patient_id": pid}

    @app.post("/v1/patients/{patient_id}/sources", status_code=202)
    def import_source(patient_id: UUID, body: SourceInput, request: Request,
                      idempotency_key: str = Header(), actor=actor_dep):
        with transaction(cfg, actor) as conn:
            result = submit(conn, actor, patient_id, body, idempotency_key, app.state.objects)
            audit(conn, actor, patient_id, "import_source", request.state.request_id)
            return result

    @app.post("/v1/patients/{patient_id}/context", status_code=201, response_model=ContextTagOut)
    def add_context_tag(patient_id: UUID, body: ContextInput, request: Request,
                        idempotency_key: str | None = Header(default=None), actor=actor_dep):
        with transaction(cfg, actor) as conn:
            tag = add_context(conn, actor, patient_id, body, idempotency_key, app.state.objects)
            audit(conn, actor, patient_id, "add_context", request.state.request_id)
            return tag

    @app.post("/v1/patients/{patient_id}/notes/extract", response_model=NoteExtractionResult)
    def extract_notes(patient_id: UUID, request: Request, retry_fallback: bool = Query(default=False),
                      actor=actor_dep):
        result = extract_pending_notes(cfg, actor, patient_id, retry_fallback)
        with transaction(cfg, actor) as conn:
            patient_access(conn, patient_id, write=True)
            audit(conn, actor, patient_id, "extract_note_context", request.state.request_id)
            return result

    @app.get("/v1/patients/{patient_id}/jobs/{job_id}")
    def job_state(patient_id: UUID, job_id: UUID, actor=actor_dep):
        with transaction(cfg, actor) as conn:
            patient = patient_access(conn, patient_id)
            job = conn.execute("SELECT * FROM jobs WHERE patient_id=%s AND id=%s", (patient_id, job_id)).fetchone()
            if not job:
                raise Problem(404, "not_found")
            return {**{key: job[key] for key in ["status", "stage", "attempt", "error_code"]},
                    "memory_revision": patient["revision"]}

    @app.post("/v1/patients/{patient_id}/jobs/{job_id}/retry", status_code=202)
    def retry_job(patient_id: UUID, job_id: UUID, body: dict, request: Request,
                  idempotency_key: str = Header(), actor=actor_dep):
        from patient_memory.ingestion import idempotent
        if body:
            raise Problem(422, "invalid_request")
        with transaction(cfg, actor) as conn:
            patient_access(conn, patient_id, write=True)

            def perform():
                row = conn.execute("SELECT * FROM jobs WHERE patient_id=%s AND id=%s FOR UPDATE",
                                   (patient_id, job_id)).fetchone()
                if not row:
                    raise Problem(404, "not_found")
                if row["status"] != "failed":
                    raise Problem(409, "invalid_retry_state")
                conn.execute("UPDATE jobs SET status='queued',attempt=0,next_attempt_at=now(),"
                             "error_code=NULL WHERE id=%s", (job_id,))
                audit(conn, actor, patient_id, "retry_job", request.state.request_id)
                return {"job_id": str(job_id), "status": "queued"}
            return idempotent(conn, actor, patient_id, "retry", idempotency_key,
                              {"job_id": str(job_id)}, perform)

    def answer(patient_id, body, actor, request, summary=False):
        instant = now()
        as_of = body.shift_end if summary else body.as_of or instant
        known_at = body.known_at or instant
        question = "shift handover summary" if summary else body.question
        with transaction(cfg, actor) as conn:
            patient_access(conn, patient_id)
            allowed = rate_limit(conn, actor, cfg.rate_limit)
        if not allowed:
            raise Problem(429, "rate_limited")
        for attempt in range(2):
            model_version = app.state.generator.version()
            with transaction(cfg, actor) as conn:
                lock_patient(conn, patient_id)
                patient = patient_access(conn, patient_id)
                facts, coverage = retrieve(conn, patient_id, as_of, known_at, question,
                                           cfg.max_evidence, summary)
                revision = patient["revision"]
                initial_scope = scope_hash(conn, actor, patient_id)
                key = digest({"tenant": str(actor.tenant_id), "patient": str(patient_id),
                              "scope": initial_scope, "revision": revision, "asof": as_of,
                              "known": known_at, "question": question,
                              "shift_start": body.shift_start if summary else None,
                              "model": model_version, "prompt": "verbatim-v1",
                              "retriever": "rrf-hash-v1", "embedding": "hash64-v1",
                              "max_evidence": cfg.max_evidence, "coverage": coverage})
                cached = cache_get(conn, patient_id, key)
                if cached:
                    result = Answer.model_validate(cached)
                    result.request_id = request.state.request_id
                    audit(conn, actor, patient_id, "cache_hit", request.state.request_id)
                    return result
            result = build_answer(app.state.generator, question, facts, coverage, patient_id,
                                  revision, as_of, known_at, request.state.request_id,
                                  body.shift_start if summary else None)
            latest_model = app.state.generator.version()
            with transaction(cfg, actor) as conn:
                lock_patient(conn, patient_id)
                latest = patient_access(conn, patient_id)
                if (latest["revision"] != revision or latest_model != model_version
                        or scope_hash(conn, actor, patient_id) != initial_scope):
                    if attempt == 0:
                        continue
                    raise Problem(409, "memory_changed")
                audit(conn, actor, patient_id, "summary" if summary else "question", request.state.request_id)
                cache_put(conn, actor, patient_id, key, revision, result)
                return result

    @app.put("/v1/patients/{patient_id}/assignments")
    def assignment(patient_id: UUID, body: AssignmentInput, request: Request, actor=actor_dep):
        with transaction(cfg, actor) as conn:
            try:
                return assign(conn, actor, patient_id, body, request.state.request_id)
            except psycopg.errors.ForeignKeyViolation as exc:
                raise Problem(422, "invalid_assignment_target") from exc

    @app.post("/v1/patients/{patient_id}/sources/{source_id}/retract")
    def retract(patient_id: UUID, source_id: UUID, body: Reason, request: Request,
                idempotency_key: str = Header(), actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return change_source(conn, actor, patient_id, source_id, "retract", idempotency_key,
                                 body.model_dump(), request.state.request_id)

    @app.post("/v1/patients/{patient_id}/sources/{source_id}/purge", status_code=202)
    def purge(patient_id: UUID, source_id: UUID, body: Reason, request: Request,
              idempotency_key: str = Header(), actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return change_source(conn, actor, patient_id, source_id, "purge", idempotency_key,
                                 body.model_dump(), request.state.request_id)

    @app.put("/v1/patients/{patient_id}/sources/{source_id}/visibility")
    def visibility(patient_id: UUID, source_id: UUID, body: VisibilityInput, request: Request,
                   idempotency_key: str = Header(), actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return change_source(conn, actor, patient_id, source_id, "visibility", idempotency_key,
                                 body.model_dump(), request.state.request_id)

    @app.post("/v1/patients/{patient_id}/checks")
    def create_check(patient_id: UUID, audio: UploadFile, mode: Annotated[CheckMode, Form()],
                     device_id: Annotated[str, Form(min_length=1, max_length=128)],
                     request: Request, actor=actor_dep,
                     device_ts: Annotated[AwareDatetime | None, Form()] = None,
                     is_baseline: Annotated[bool, Form()] = False,
                     session_id: Annotated[UUID | None, Form()] = None,
                     lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
                     lon: Annotated[float | None, Form(ge=-180, le=180)] = None,
                     accuracy_m: Annotated[float | None, Form(ge=0, le=100_000)] = None,
                     ) -> CheckResult:
        location = None
        if lat is not None or lon is not None or accuracy_m is not None:
            if lat is None or lon is None or session_id is None:
                raise Problem(422, "invalid_request")
            location = (lat, lon, accuracy_m)
        with transaction(cfg, actor) as conn:
            care_gate(conn, patient_id)
            if session_id is not None:  # reject before any audio work
                sessions.check_gate(conn, patient_id, session_id, mode, is_baseline)
        work = Path(tempfile.mkdtemp(prefix="check-"))
        try:
            upload = work / "upload"
            with upload.open("wb") as out:
                shutil.copyfileobj(audio.file, out)
            try:
                analysis = analyze(upload, work, app.state.transcriber)
            except InvalidAudio as exc:
                raise Problem(422, "invalid_audio") from exc
            except DecoderUnavailable as exc:
                raise Problem(503, "dependency_unavailable") from exc
        finally:
            # Session audio has no retention index: never leave raw files behind for KAZE.
            if session_id is not None or not cfg.keep_audio:
                shutil.rmtree(work, ignore_errors=True)
        with transaction(cfg, actor) as conn:
            result = store_check(conn, actor, patient_id, request.state.request_id, analysis,
                                 mode, device_id, device_ts, is_baseline, cfg,
                                 session_id=session_id, location=location)
        # KAZE session check-ins never go to a model provider (decision 018).
        if result.assessment and session_id is None:
            enrich_assessment_sbar(cfg, actor, patient_id, result.assessment["id"])
        return result

    @app.post("/v1/patients/{patient_id}/sessions", status_code=201, response_model=SessionOut)
    def arm_session(patient_id: UUID, body: SessionArm, request: Request,
                    idempotency_key: str | None = Header(default=None), actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return sessions.arm(conn, actor, patient_id, body, idempotency_key,
                                request.state.request_id)

    @app.get("/v1/patients/{patient_id}/sessions", response_model=SessionList)
    def list_sessions(patient_id: UUID, actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return {"sessions": sessions.sessions(conn, patient_id)}

    @app.get("/v1/patients/{patient_id}/sessions/{session_id}", response_model=SessionOut)
    def session_status(patient_id: UUID, session_id: UUID, actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return sessions.status(conn, patient_id, session_id)

    @app.post("/v1/patients/{patient_id}/sessions/{session_id}/end", response_model=SessionOut)
    def end_session(patient_id: UUID, session_id: UUID, body: SessionEnd, request: Request,
                    actor=actor_dep):
        with transaction(cfg, actor) as conn:
            return sessions.end(conn, actor, patient_id, session_id, request.state.request_id)

    def ack_response(kind: str) -> HTMLResponse:
        code = {"invalid": 404, "unavailable": 503}.get(kind, 200)
        return HTMLResponse(ack.page(kind), status_code=code, headers=ack.HEADERS)

    # Public acknowledgement links from KAZE texts (decision 023): no bearer identity, the token
    # is the only credential. GET only shows a button, so link previews cannot acknowledge.
    @app.get("/ack/{token}", response_class=HTMLResponse)
    def ack_page(token: str):
        return ack_response("confirm" if ack.well_formed(token) else "invalid")

    @app.post("/ack/{token}", response_class=HTMLResponse)
    def ack_submit(token: str):
        if not ack.well_formed(token):
            return ack_response("invalid")
        try:
            result = ack.acknowledge(cfg, token)
        except psycopg.Error:
            logging.getLogger("patient_memory.requests").warning("acknowledgement unavailable")
            return ack_response("unavailable")
        return ack_response(result)

    @app.get("/v1/watchlist")
    def watchlist(actor=actor_dep):
        with transaction(cfg, actor) as conn:
            require_member(conn)
            return build_watchlist(conn, cfg)

    @app.get("/v1/patients/{patient_id}/overview")
    def patient_overview(patient_id: UUID, days: Annotated[int, Query(ge=1, le=90)] = 30,
                         actor=actor_dep):
        with transaction(cfg, actor) as conn:
            care_gate(conn, patient_id)
            patient = patient_access(conn, patient_id)
            return build_overview(conn, cfg, patient, days)

    @app.post("/v1/patients/{patient_id}/questions", response_model=Answer)
    def question(patient_id: UUID, body: Question, request: Request, actor=actor_dep):
        return answer(patient_id, body, actor, request)

    @app.post("/v1/patients/{patient_id}/summaries", response_model=Answer)
    def summary(patient_id: UUID, body: Summary, request: Request, actor=actor_dep):
        return answer(patient_id, body, actor, request, True)

    @app.get("/v1/patients/{patient_id}/evidence/{evidence_id}")
    def get_evidence(patient_id: UUID, evidence_id: UUID, request: Request, actor=actor_dep):
        with transaction(cfg, actor) as conn:
            patient_access(conn, patient_id)
            f = conn.execute(
                "SELECT f.*,s.payload,s.canonical_text,s.recorded_at,s.ingested_at FROM facts f "
                "JOIN sources s ON s.tenant_id=f.tenant_id AND s.patient_id=f.patient_id AND s.id=f.source_id "
                "WHERE f.patient_id=%s AND f.id=%s AND s.published_at IS NOT NULL "
                "AND s.retracted_at IS NULL AND s.purged_at IS NULL", (patient_id, evidence_id),
            ).fetchone()
            if not f:
                raise Problem(404, "not_found")
            audit(conn, actor, patient_id, "evidence", request.state.request_id)
            return evidence(f)

    @app.get("/v1/patients/{patient_id}/timeline")
    def timeline(patient_id: UUID, request: Request, as_of: datetime | None = None,
                 known_at: datetime | None = None, start: datetime | None = Query(None, alias="from"),
                 end: datetime | None = Query(None, alias="to"), limit: int = Query(50, ge=1, le=100),
                 cursor: str | None = None, actor=actor_dep):
        from patient_memory.pagination import paginate
        instant = now()
        for dt in [as_of, known_at, start, end]:
            if dt and dt.tzinfo is None:
                raise Problem(422, "timezone_required")
        if known_at and known_at > instant or start and end and start > end:
            raise Problem(422, "invalid_interval")
        with transaction(cfg, actor) as conn:
            lock_patient(conn, patient_id)
            patient = patient_access(conn, patient_id)
            return paginate(conn, cfg, actor, patient, as_of, known_at, start, end, limit,
                            cursor, request.state.request_id)

    return app


app = create_app()
