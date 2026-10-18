"""Pure KAZE ladder rules (decision 018) on a deterministic clock."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from patient_memory.baseline.safety import (
    STANDARD,
    SessionState,
    checkin_update,
    level_contacts,
    plan,
    speech_trigger,
    timing_for,
)
from patient_memory.config import Settings

DUE = datetime(2026, 10, 18, 22, 45, tzinfo=UTC)
MIN = timedelta(minutes=1)
ACTIVE = SessionState(status="active", ends_at=DUE + timedelta(hours=3), next_due_at=DUE,
                      ladder_level=0, episode=0, ladder_trigger=None, escalation_enabled=True,
                      contacts=(1, 2))


def at(minutes: float):
    return DUE + timedelta(minutes=minutes)


def advance(state, step):
    return replace(state, status=step.status, ladder_level=step.level, episode=step.episode,
                   ladder_trigger=step.trigger)


def walk(state, minutes, timing=STANDARD, speech=False):
    """Run the planner at each minute mark, applying steps; returns [(minute, level)]."""
    seen, last = [], None
    for m in minutes:
        step = plan(state, at(m), timing, speech, last if state.ladder_level >= 2 else None)
        if step:
            state, last = advance(state, step), at(m)
            seen.append((m, step.level))
    return state, seen


def test_standard_timings_are_the_spec_and_default():
    assert (STANDARD.nudge, STANDARD.sms, STANDARD.step) == (2.5 * MIN, 5 * MIN, 10 * MIN)
    assert timing_for(Settings()) is STANDARD


def test_nothing_happens_before_the_nudge_offset():
    assert plan(ACTIVE, DUE, STANDARD, False, None) is None
    assert plan(ACTIVE, at(2.49), STANDARD, False, None) is None


def test_two_and_a_half_minutes_overdue_is_the_level_one_nudge():
    step = plan(ACTIVE, at(2.5), STANDARD, False, None)
    assert (step.level, step.trigger, step.status, step.episode, step.contacts) == (
        1, "missed_checkin", "active", 1, ())


def test_five_minutes_overdue_reaches_level_two_text_to_contact_one():
    step = plan(ACTIVE, at(5), STANDARD, False, None)
    assert (step.level, step.status, step.episode, step.contacts) == (2, "escalating", 1, (1,))
    after_nudge = replace(ACTIVE, ladder_level=1, episode=1, ladder_trigger="missed_checkin")
    step = plan(after_nudge, at(5), STANDARD, False, None)
    assert (step.level, step.episode) == (2, 1)  # same episode as its nudge


def test_full_ladder_on_the_standard_clock():
    state, seen = walk(ACTIVE, [x / 4 for x in range(0, 4 * 40)])
    assert seen == [(2.5, 1), (5, 2), (15, 3), (25, 4)]
    assert state.status == "escalating" and state.episode == 1
    assert walk(state, [26, 60, 120])[1] == []  # level 4 is the top; nothing auto-dials


def test_late_worker_steps_one_level_per_pass():
    state, seen = walk(ACTIVE, [40, 40.25, 50.25, 60.25])
    assert seen == [(40, 2), (50.25, 3), (60.25, 4)]


def test_level_three_waits_ten_minutes_from_the_actual_level_two_time():
    level2 = replace(ACTIVE, status="escalating", ladder_level=2, episode=1,
                     ladder_trigger="missed_checkin")
    assert plan(level2, at(15), STANDARD, False, at(6)) is None
    assert plan(level2, at(16), STANDARD, False, at(6)).level == 3
    assert plan(level2, at(16), STANDARD, False, None) is None  # no recorded step: wait


@pytest.mark.parametrize("contacts,level,expected", [
    ((1, 2), 2, (1,)), ((1, 2), 3, (2,)), ((1, 2), 4, (1, 2)),
    ((1,), 2, (1,)), ((1,), 3, (1,)), ((1,), 4, (1,)), ((1, 2), 1, ()),
])
def test_contacts_per_level(contacts, level, expected):
    assert level_contacts(level, contacts) == expected


@pytest.mark.parametrize("status", ["arming", "acknowledged", "ended"])
def test_frozen_states_never_progress(status):
    state = replace(ACTIVE, status=status, ladder_level=2 if status != "arming" else 0,
                    episode=1)
    assert plan(state, at(60), STANDARD, True, at(0)) is None


def test_ack_stops_the_ladder():
    state, _ = walk(ACTIVE, [5])
    acknowledged = replace(state, status="acknowledged")
    assert walk(acknowledged, range(5, 120))[1] == []


def test_expiry_stops_progression():
    ended_soon = replace(ACTIVE, ends_at=at(4))
    assert plan(ended_soon, at(4), STANDARD, False, None) is None
    assert plan(ended_soon, at(3.9), STANDARD, False, None).level == 1
    level2 = replace(ACTIVE, status="escalating", ladder_level=2, episode=1, ends_at=at(12),
                     ladder_trigger="missed_checkin")
    assert plan(level2, at(30), STANDARD, False, at(5)) is None


def test_escalation_disabled_caps_at_the_nudge():
    nudges_only = replace(ACTIVE, escalation_enabled=False)
    state, seen = walk(nudges_only, range(0, 60))
    assert seen == [(3, 1)] and state.status == "active"
    assert plan(nudges_only, at(0), STANDARD, True, None).level == 1  # speech: nudge only


def test_speech_change_goes_straight_to_level_two_before_the_check_is_due():
    step = plan(ACTIVE, DUE - 10 * MIN, STANDARD, True, None)
    assert (step.level, step.trigger, step.episode, step.contacts) == (
        2, "speech_change", 1, (1,))
    nudged = replace(ACTIVE, ladder_level=1, episode=1, ladder_trigger="missed_checkin")
    step = plan(nudged, at(3), STANDARD, True, None)
    assert (step.level, step.trigger, step.episode) == (2, "speech_change", 1)


def test_level_three_keeps_the_episode_trigger():
    speech2 = replace(ACTIVE, status="escalating", ladder_level=2, episode=3,
                      ladder_trigger="speech_change")
    step = plan(speech2, at(20), STANDARD, False, at(5))
    assert (step.level, step.trigger, step.episode) == (3, "speech_change", 3)


def test_new_episode_after_a_reset():
    reset = replace(ACTIVE, episode=2)
    assert plan(reset, at(5), STANDARD, False, None).episode == 3


@pytest.mark.parametrize("change_status,explainers,expected", [
    ("change", [], True), ("provisional", [], True),
    ("change", ["exertion"], False), ("provisional", ["exertion"], False),
    ("change", ["loud_venue"], False),
    ("none", [], False), (None, [], False),
])
def test_speech_trigger_needs_an_unexplained_change(change_status, explainers, expected):
    assert speech_trigger(change_status, explainers) is expected


@pytest.mark.parametrize("status", ["active", "escalating", "acknowledged"])
def test_on_time_usable_normal_check_in_resets_the_timer(status):
    ts = DUE - 3 * MIN
    assert checkin_update(status, True, False, "none", [], ts, 45) == {
        "status": "active", "ladder_level": 0, "ladder_trigger": None,
        "next_due_at": ts + 45 * MIN}


def test_late_normal_check_in_also_resets_from_its_own_time():
    ts = at(12)
    assert checkin_update("escalating", True, False, "none", [], ts, 1)[
        "next_due_at"] == ts + MIN


def test_explained_change_resets_like_a_normal_check_in():
    assert checkin_update("active", True, False, "change", ["exertion"], DUE, 45) is not None


@pytest.mark.parametrize("usable,is_baseline,change_status,explainers,status", [
    (False, False, None, [], "active"),           # unusable clip is not a check-in
    (True, False, "change", [], "active"),     # unexplained change: trigger, not reset
    (True, False, "provisional", [], "escalating"),
    (True, True, "enrolling", [], "arming"),  # baseline clips are activation, not resets
    (True, False, "none", [], "ended"),
    (True, False, "none", [], "arming"),
])
def test_check_ins_that_do_not_reset(usable, is_baseline, change_status, explainers, status):
    assert checkin_update(status, usable, is_baseline, change_status, explainers, DUE, 45) is None


