import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from patient_memory.domain import DueResident, SourceInput


def legacy_note():
    return {"external_document_id": "synthetic-legacy-note", "external_version_id": "1",
            "source_system": "synthetic", "kind": "nursing_note", "author_role": "nurse",
            "visibility": "care_team", "recorded_at": "2026-01-02T10:00:00Z",
            "effective_from": None, "effective_to": None, "supersedes_version_id": None,
            "text": "Synthetic unchanged note.", "records": None}


def test_absent_author_preserves_all_legacy_payload_fields_and_bytes():
    expected = legacy_note()
    value = SourceInput.model_validate(expected)
    assert value.model_dump(mode="json") == expected
    assert json.loads(value.model_dump_json()) == expected
    raw = json.dumps(expected, sort_keys=True).encode()
    assert hashlib.sha256(json.dumps(value.model_dump(mode="json"), sort_keys=True).encode()
                          ).digest() == hashlib.sha256(raw).digest()
    # Explicit null is also legacy/unknown; other old nullable keys are still serialized.
    assert SourceInput.model_validate({**expected, "author_principal_id": None}).model_dump(
        mode="json") == expected


def test_psw_authorship_is_explicit_and_only_care_notes_accept_principal_attribution():
    body = legacy_note()
    with pytest.raises(ValidationError):
        SourceInput.model_validate({**body, "author_role": "psw"})
    author = uuid4()
    value = SourceInput.model_validate({**body, "author_role": "psw", "author_principal_id": author})
    assert value.model_dump(mode="json")["author_principal_id"] == str(author)
    with pytest.raises(ValidationError):
        SourceInput.model_validate({**body, "kind": "patient_report", "author_role": "patient",
                                    "author_principal_id": author})


def test_feedback_contract_can_never_report_a_negative_or_include_scores():
    row = {"patient_id": uuid4(), "display_name": "Synthetic resident", "status": "due",
           "consent_state": "granted", "last_check_ts": None, "skipped_today": False}
    assert DueResident(**row).observation_helped is None
    assert DueResident(**row, observation_helped=True).observation_helped is True
    for addition in ({"observation_helped": False}, {"verdict": "escalate"}):
        with pytest.raises(ValidationError):
            DueResident(**row, **addition)
