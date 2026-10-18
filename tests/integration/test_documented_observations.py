"""Documented measurement readback must retain evidence, time and caller scope."""
from datetime import timedelta
from uuid import uuid4

from patient_memory.baseline.observations import documented_observations
from patient_memory.domain import Record, SourceInput, now
from patient_memory.storage import transaction
from tests.contract.test_api import client_for
from tests.integration.test_retrieval import publish


def measurement(at, value=37.1, **changes):
    return SourceInput(external_document_id=str(uuid4()), external_version_id="1",
        source_system="synthetic", kind="observation", author_role="system", recorded_at=at,
        records=[Record(concept="temperature_c", value=value, unit="Cel", effective_from=at)],
        **changes)


def read(sandbox, at, role="nurse"):
    with transaction(sandbox[0], sandbox[2][role]) as conn:
        return documented_observations(conn, sandbox[1], at, 30)


def test_temperature_is_documented_not_inferred_normal_and_is_rls_scoped(sandbox):
    at = now()
    assert read(sandbox, at) == []
    source = publish(sandbox, measurement(at - timedelta(hours=1), 34.0))
    observation, = read(sandbox, at)
    assert observation["source_id"] == str(source)
    assert observation["value"] == 34.0 and "normal" not in observation["label"].lower()
    assert "34" in observation["quote"]
    assert read(sandbox, at, "psw") == []
    assert client_for(sandbox, "psw").get(f"/v1/patients/{sandbox[1]}/overview").status_code == 404
    publish(sandbox, measurement(at + timedelta(days=1), 39.0))
    assert read(sandbox, at)[0]["value"] == 34.0  # future event is not current evidence
    importer = client_for(sandbox, "importer")
    response = importer.post(f"/v1/patients/{sandbox[1]}/sources/{source}/retract",
        json={"reason": "synthetic correction"}, headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.text
    assert read(sandbox, at) == []


def test_superseded_expired_and_unmeasured_sources_do_not_supply_temperature(sandbox):
    at = now()
    original = measurement(at - timedelta(hours=1))
    sid = publish(sandbox, original)
    successor = original.model_copy(update={"external_version_id": "2",
        "supersedes_version_id": sid,
        "records": [Record(concept="temperature_c", value="not measured", unit="Cel",
                           effective_from=at - timedelta(minutes=1))]})
    publish(sandbox, successor)
    assert read(sandbox, at) == []
    publish(sandbox, measurement(at - timedelta(days=31)))
    assert read(sandbox, at) == []
