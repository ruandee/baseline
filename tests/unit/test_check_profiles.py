from uuid import uuid4

import pytest
from pydantic import ValidationError

from patient_memory.check_profiles import project, require_protocol
from patient_memory.domain import CheckProfile, CheckProfileInput
from patient_memory.errors import Problem


@pytest.mark.parametrize("locale,state,protocol", [(None, "unconfigured", None),
    ("fr", "unsupported", None), ("en-CA", "unsupported", None), ("en", "ready", "count20-days-v1")])
def test_protocol_registry_never_falls_back(locale, state, protocol):
    profile = project({"preferred_locale": locale, "first_name": "Mary Ann", "version": uuid4()})
    assert profile["state"] == state and profile["prompt_version"] == protocol
    assert profile["first_name"] == "Mary Ann"
    CheckProfile.model_validate(profile)


def test_missing_profile_has_no_inferred_name_or_language():
    assert project(None) == {"state": "unconfigured", "first_name": None, "preferred_locale": None,
                             "protocol_locale": None, "prompt_version": None, "version": None}


@pytest.mark.parametrize("body", [{"first_name": " "}, {"first_name": " Alex"},
    {"preferred_locale": "English"}, {"preferred_locale": "en<script>"}, {"prompt_version": "fr-v1"}])
def test_profile_input_rejects_ambiguous_names_or_protocol_invention(body):
    with pytest.raises(ValidationError):
        CheckProfileInput.model_validate(body)


def test_profile_changed_even_when_language_stays_english(monkeypatch):
    profile = project({"preferred_locale": "en", "first_name": "Mary Ann", "version": uuid4()})
    monkeypatch.setattr("patient_memory.check_profiles.read_profile", lambda *a: profile)
    with pytest.raises(Problem) as exc:
        require_protocol(None, uuid4(), expected_version=uuid4())
    assert exc.value.code == "check_profile_changed"
    with pytest.raises(Problem):
        require_protocol(None, uuid4(), requested_locale="fr")
