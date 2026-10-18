"""Bounded Mrs. L demo: publish real context and reassess her immutable synthetic check."""
from uuid import UUID, uuid4

from fastapi import Request

from patient_memory.auth import Identity, decode_token
from patient_memory.baseline.assess import FEATURES, assess_check, lock_assessment
from patient_memory.baseline.context import TAXONOMY, add_context, default_valid_to
from patient_memory.baseline.overview import _latest_assessment
from patient_memory.domain import ContextInput
from patient_memory.errors import Problem
from patient_memory.ingestion import idempotent
from patient_memory.storage import audit, patient_access, transaction
from scripts.seed import uid

PATIENT = uid("0/patient-2")  # Authored Mrs. L, never a volunteer or arbitrary patient.


class Explanation(ContextInput):
    assessment_id: UUID


def nurse_gate(cfg, reader, patient_id):
    if patient_id != PATIENT or reader != Identity(uid("0/nurse"), uid("tenant-0")):
        raise Problem(404, "not_found")
    with transaction(cfg, reader) as conn:
        patient_access(conn, patient_id)
        if not conn.execute("SELECT pm_care(%s) AS ok", (patient_id,)).fetchone()["ok"]:
            raise Problem(404, "not_found")


def explain(cfg, reader, patient_id, body, key, objects):
    nurse_gate(cfg, reader, patient_id)
    if (body.kind != "explainer" or body.tag not in TAXONOMY
            or TAXONOMY[body.tag][0] != "explainer" or body.tag == "language_change"):
        raise Problem(422, "invalid_request", "Choose a supported possible explanation")
    if not body.label.strip():
        raise Problem(422, "invalid_request", "Record the actual observation")
    writer = Identity(uid("0/importer"), reader.tenant_id)
    # Existing hosted importer service performs only this bounded observation publication.
    # The nurse receives no importer credential, generic write role or permission expansion.
    with transaction(cfg, writer) as conn:
        lock_assessment(conn, writer.tenant_id, patient_id)
        nurse_gate(cfg, reader, patient_id)
        patient = patient_access(conn, patient_id, write=True)

        def perform():
            current = _latest_assessment(conn, patient_id)
            if not current or current["id"] != body.assessment_id:
                raise Problem(409, "memory_changed", "The assessment changed; reload before adding context")
            check = conn.execute(
                "SELECT * FROM voice_checks WHERE patient_id=%s AND id=%s "
                "AND usable AND synthetic AND session_id IS NULL",
                (patient_id, current["check_id"])).fetchone()
            if not check:
                raise Problem(409, "context_unavailable", "A current synthetic voice check is required")
            until = body.valid_to or default_valid_to(body.tag, body.valid_from)
            if body.valid_from > check["ts"] or (until and until <= check["ts"]):
                raise Problem(422, "invalid_request", "The observation period must include this check")
            context = ContextInput.model_validate(body.model_dump(exclude={"assessment_id"}))
            tag = add_context(conn, writer, patient_id, context, "demo-explain-" + key, objects)
            _, assessment = assess_check(
                conn, cfg, patient_id, writer.tenant_id, check["id"], check["ts"],
                check["device_id"], check["prompt_version"], check["is_baseline"],
                {name: check[name] for name in FEATURES}, patient["external_id"])
            audit(conn, writer, patient_id, "demo_nurse_context_reassessment", uuid4(),
                  result=f"requested_by:{reader.principal_id};source:{tag.source_id}")
            return {"context": tag.model_dump(mode="json"),
                    "assessment_id": assessment["id"], "verdict": assessment["verdict"]}

        result = idempotent(conn, writer, patient_id, "demo_context_reassessment", key,
                            body.model_dump(mode="json"), perform)
        source = conn.execute(
            "SELECT published_at,retracted_at,purged_at FROM sources WHERE patient_id=%s AND id=%s",
            (patient_id, UUID(result["context"]["source_id"]))).fetchone()
        if (not source or not source["published_at"] or source["retracted_at"]
                or source["purged_at"]):
            raise Problem(409, "source_unavailable", "The saved context is no longer available")
        nurse_gate(cfg, reader, patient_id)
        return result


def register(app, cfg, reader):
    @app.post("/demo/residents/{patient_id}/context", include_in_schema=False)
    def add_explanation(patient_id: UUID, body: Explanation, request: Request):
        identity = decode_token(request.headers.get("authorization", "").removeprefix("Bearer "), cfg)
        if identity != reader or request.headers.get("x-pm-demo") != "1":
            raise Problem(404, "not_found")
        key = request.headers.get("idempotency-key", "")
        if not key or len(key) > 150:
            raise Problem(422, "idempotency_key_required")
        return explain(cfg, identity, patient_id, body, key, app.state.objects)
