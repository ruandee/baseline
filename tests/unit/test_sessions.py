"""Pure KAZE session rules (decision 018): arm validation, activation, check acceptance."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from patient_memory.baseline.sessions import (
    BASELINE_REQUIRED,
    activation,
    check_problem,
    mask_phone,
    window_error,
)
from patient_memory.domain import CheckResult, SessionArm

T0 = datetime(2026, 10, 18, 22, 0, tzinfo=UTC)
CONTACT = {"name": "Dee", "phone_e164": "+14165550101"}


def arm(**fields):
    return SessionArm.model_validate({"display_name": "Sam", "ends_at": T0 + timedelta(hours=3),
                                      "contacts": [CONTACT], **fields})


def test_defaults_match_the_spec():
    body = arm()
    assert body.interval_min == 45 and body.context_tags == [] and body.escalation_enabled


@pytest.mark.parametrize("fields", [
    {"contacts": []},
    {"contacts": [CONTACT, {**CONTACT, "phone_e164": "+14165550102"},
                  {**CONTACT, "phone_e164": "+14165550103"}]},
    {"contacts": [CONTACT, CONTACT]},  # same phone twice
    {"contacts": [{**CONTACT, "phone_e164": "4165550101"}]},  # not E.164
    {"contacts": [{**CONTACT, "phone_e164": "+0165550101"}]},
    {"contacts": [{**CONTACT, "name": ""}]},
    {"interval_min": 0}, {"interval_min": 181},
    {"context_tags": ["marathon"]}, {"context_tags": ["exertion", "exertion"]},
    {"ends_at": "2026-10-18T23:00:00"},  # naive datetime
    {"display_name": ""}, {"display_name": "x" * 41},
    {"lat": 43.6},  # unknown field
])
def test_invalid_arm_bodies_are_rejected(fields):
    with pytest.raises(ValidationError):
        arm(**fields)


def test_two_contacts_and_both_context_tags_are_accepted():
    body = arm(contacts=[CONTACT, {"name": "Eve", "phone_e164": "+447700900123"}],
               context_tags=["exertion", "loud_venue"], interval_min=1)
    assert [c.name for c in body.contacts] == ["Dee", "Eve"]


def test_session_window_is_one_interval_to_24_hours():
    assert window_error(T0, T0 + timedelta(minutes=45), 45) is None
    assert window_error(T0, T0 + timedelta(hours=24), 45) is None
    assert window_error(T0, T0 + timedelta(minutes=44), 45)
    assert window_error(T0, T0 - timedelta(minutes=1), 1)
    assert window_error(T0, T0 + timedelta(hours=24, seconds=1), 45)


def test_third_usable_baseline_activates_and_starts_the_timer():
    assert BASELINE_REQUIRED == 3
    assert activation("arming", 2, 3, T0, 45) is None
    assert activation("arming", 3, 3, T0, 45) == {
        "status": "active", "activated_at": T0, "next_due_at": T0 + timedelta(minutes=45)}
    for status in ["active", "escalating", "acknowledged", "ended"]:
        assert activation(status, 3, 3, T0, 45) is None


@pytest.mark.parametrize("status,mode,is_baseline,expected", [
    ("arming", "live", True, None),
    ("arming", "live", False, (422, "invalid_request")),
    ("arming", "resident", True, (422, "invalid_request")),
    ("active", "live", False, None),
    ("escalating", "live", False, None),
    ("acknowledged", "live", False, None),
    ("active", "live", True, (422, "invalid_request")),
    ("active", "runner", False, (422, "invalid_request")),
    ("ended", "live", False, (409, "session_ended")),
])
def test_which_check_ins_each_state_accepts(status, mode, is_baseline, expected):
    problem = check_problem(status, mode, is_baseline)
    assert (None if problem is None else (problem.status, problem.code)) == expected


def test_phones_are_masked_to_the_last_four_digits():
    assert mask_phone("+14165550101") == "+*******0101"
    assert "416555" not in mask_phone("+14165550101")


def test_check_result_session_summary_is_optional():
    assert CheckResult.model_fields["session"].default is None
