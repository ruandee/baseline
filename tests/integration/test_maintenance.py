import pytest

from patient_memory.domain import now
from patient_memory.errors import Problem
from patient_memory.worker import run_once
from scripts.maintenance import requeue
from tests.contract.test_api import client_for, import_note


def test_repair_requires_import_scope_and_preserves_knowledge_history(sandbox):
    import_note(sandbox)
    cfg, pid, actors, objects = sandbox
    client = client_for(sandbox)
    root = f"/v1/patients/{pid}/questions"
    cutoff = now().isoformat()
    original = client.post(root, json={"question": "sleep", "known_at": cutoff}).json()
    with pytest.raises(Problem):
        requeue(cfg, actors["nurse"], pid)
    assert requeue(cfg, actors["importer"], pid) == 1
    run_once(cfg, actors["importer"], objects)
    replayed = client.post(root, json={"question": "sleep", "known_at": cutoff}).json()
    assert original["evidence"] == replayed["evidence"]
