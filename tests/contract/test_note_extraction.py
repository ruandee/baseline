from uuid import uuid4

from tests.contract.test_api import client_for, import_note, source_payload


def test_extract_route_is_assigned_importer_only(sandbox):
    root = f"/v1/patients/{sandbox[1]}/notes/extract"
    for role in ("nurse", "patient", "admin"):
        assert client_for(sandbox, role).post(root).status_code == 404
    assert client_for(sandbox, "importer").post(
        f"/v1/patients/{uuid4()}/notes/extract").status_code == 404
    response = client_for(sandbox, "importer").post(root)
    assert response.status_code == 200, response.text
    assert response.json() == {"processed": 0, "tags_created": 0, "methods": [], "batch_limit": 5}


def test_worker_processed_notes_are_idempotent_on_demand(sandbox):
    import_note(sandbox, source_payload("Quiet at lunch, didn't finish her soup. Not her usual chatty self."))
    response = client_for(sandbox, "importer").post(f"/v1/patients/{sandbox[1]}/notes/extract")
    assert response.status_code == 200, response.text
    assert response.json()["processed"] == response.json()["tags_created"] == 0
