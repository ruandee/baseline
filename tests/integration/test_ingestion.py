from uuid import UUID, uuid4

import pytest

from patient_memory.auth import Identity
from patient_memory.config import Settings
from patient_memory.domain import SourceInput, now
from patient_memory.errors import Problem
from patient_memory.ingestion import submit
from patient_memory.storage import transaction
from scripts.seed import seed, uid


class MemoryObjects:
    def __init__(self):
        self.data = {}

    def put(self, key, raw):
        self.data[key] = raw


def test_idempotency_and_cross_patient_amendment():
    seed()
    identity = Identity(uid("0/importer"), uid("tenant-0"))
    objects = MemoryObjects()
    source = SourceInput(external_document_id=str(uuid4()), external_version_id="1",
                         source_system="synthetic", kind="nursing_note", author_role="nurse",
                         text="Patient reports improved sleep.", recorded_at=now())
    key = str(uuid4())
    with transaction(Settings(), identity) as conn:
        a = submit(conn, identity, uid("0/patient-0"), source, key, objects)
        assert submit(conn, identity, uid("0/patient-0"), source, key, objects) == a
        assert len(objects.data) == 1
    with transaction(Settings(), identity) as conn, pytest.raises(Problem) as err:
        submit(conn, identity, uid("0/patient-0"), source.model_copy(update={"text": "Changed"}), key, objects)
    assert err.value.status == 409
    with transaction(Settings(), identity) as conn, pytest.raises(Problem) as err:
        submit(conn, identity, uid("0/patient-1"), source.model_copy(
            update={"supersedes_version_id": UUID(a["source_version_id"])}), str(uuid4()), objects)
    assert err.value.code == "invalid_supersession"
