"""Verdict table, escalation budget and SBAR template (docs/06-baseline.md). No model involved."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHIFT_STARTS = (7, 15, 23)
SHIFT_HOURS = 8
FUSED_ESCALATE = 3.0
WATCH_WINDOW_TAGS = ("high_risk_med_new", "recent_fall", "returned_from_hospital")
WATCH_WINDOW_DAYS = 7

ACTION_LABELS = {
    "none": "No action",
    "recheck_1h": "Recheck in 1 hour",
    "4at_now": "Run 4AT now",
    "restore2_soft_signs": "Check for soft signs (RESTORE2)",
    "vitals_recheck": "Recheck vitals",
}
TAG_LABELS = {
    "exertion": "Recent exertion", "dentures": "New or loose dentures",
    "hearing_aid": "Hearing aid issue", "poor_sleep": "Poor sleep",
    "language_change": "Different language spoken",
    "high_risk_med_new": "New high-risk medication", "fever_documented": "Fever documented",
    "poor_intake": "Poor intake", "recent_fall": "Recent fall",
    "returned_from_hospital": "Returned from hospital", "new_confusion_noted": "New confusion noted",
}
VERDICT_RANK = {"escalate": 0, "watch": 1, "explained": 2, "within_normal": 3, "enrolling": 3}


@dataclass(frozen=True)
class Decision:
    verdict: str
    action: str


def decide(status: str, fused: float | None, kinds_and_tags: list[tuple[str, str]]) -> Decision:
    """One verdict per (change status, valid context). Amplifiers win over explainers."""
    if status == "none":
        return Decision("within_normal", "none")
    if status == "enrolling":
        return Decision("enrolling", "none")
    if status not in ("provisional", "change"):
        raise ValueError(f"unknown change status: {status}")
    amplifiers = [tag for kind, tag in kinds_and_tags if kind == "amplifier"]
    if amplifiers:
        return Decision("escalate", "vitals_recheck" if "fever_documented" in amplifiers else "4at_now")
    if kinds_and_tags:
        return Decision("explained", "none")
    if status == "provisional":
        return Decision("watch", "recheck_1h")
    if fused is not None and fused >= FUSED_ESCALATE:
        return Decision("escalate", "4at_now")
    return Decision("watch", "restore2_soft_signs")


def shift_bounds(now: datetime, timezone: str) -> tuple[datetime, datetime]:
    """The 8-hour shift (07:00, 15:00, 23:00 local) containing `now`, as aware datetimes."""
    local = now.astimezone(ZoneInfo(timezone))
    starts = [h for h in SHIFT_STARTS if h <= local.hour]
    if starts:
        start = local.replace(hour=starts[-1], minute=0, second=0, microsecond=0)
    else:
        start = (local - timedelta(days=1)).replace(hour=SHIFT_STARTS[-1], minute=0, second=0,
                                                    microsecond=0)
    return start, start + timedelta(hours=SHIFT_HOURS)


def apply_profile(decision: Decision, *, escalations_used: int, budget: int,
                  no_escalate: bool) -> tuple[Decision, dict]:
    """Apply the no-escalate list and the shift budget; returns the decision and its flags."""
    flags = {"over_budget": False, "no_escalate": no_escalate, "would_escalate": False}
    if decision.verdict != "escalate":
        return decision, flags
    if no_escalate:  # demo safety: this profile is never interrupted
        flags["would_escalate"] = True
        return Decision("watch", decision.action), flags
    flags["over_budget"] = escalations_used >= budget
    return decision, flags


def _pct(v):
    return f"{v * 100:.0f}%"


def sbar_template(name: str, status: str, decision: Decision, check_id: str, features: dict,
                  tags: list[dict]) -> dict | None:
    """Template SBAR for escalate and watch verdicts; sentences cite check or evidence ids."""
    if decision.verdict not in ("escalate", "watch"):
        return None
    rate = features.get("speech_rate_wpm")
    pause = features.get("pause_ratio")
    cite_check = [f"check:{check_id}"]
    s = f"{name}'s speech differs from their usual"
    if rate and pause:
        s += (f": speech rate {rate['value']:.0f} vs {rate['median']:.0f} words per minute, "
              f"pauses {_pct(pause['value'])} vs {_pct(pause['median'])}")
    context = [t for t in tags if t["evidence_id"]]
    labels = [t["label"] for t in tags]
    amplifiers = [t["label"] for t in tags if t["kind"] == "amplifier"]
    basis = ("Meets the change threshold" if status == "change"
             else "One strong reading, not yet confirmed")
    return {"source": "template", "sentences": [
        {"section": "S", "text": s + ".", "evidence_ids": cite_check},
        {"section": "B", "text": ("; ".join(labels) + ".") if labels else "No context on record.",
         "evidence_ids": [t["evidence_id"] for t in context]},
        {"section": "A", "text": basis + ("; " + ", ".join(amplifiers) + " present." if amplifiers
                                          else "."), "evidence_ids": cite_check},
        {"section": "R", "text": f"Suggest {ACTION_LABELS[decision.action]}.",
         "evidence_ids": cite_check},
    ]}
