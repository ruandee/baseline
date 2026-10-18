"""BL-18 live acceptance: the /unit page against the real /v1/watchlist for the BL-14 cohort.

Loads the 12-resident synthetic cohort through the real loader (sources, worker, note
extraction, assessments), reads the watch list through the same workspace app and demo token
the page uses, checks every field frontend/baseline.js reads exists in the live response, then
runs the page code under Node against that captured response.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from scripts.load_baseline_demo import DemoScope, load_demo
from tests.contract.test_frontend import workspace_client
from tests.js_runner import run_js_suites

ROOT = Path(__file__).resolve().parents[2]
RANK = {"escalate": 0, "watch": 1, "explained": 2, "within_normal": 3, "enrolling": 3}


def unit_page_fields():
    """Property names the /unit code reads from the watch-list payload."""
    js = (ROOT / "frontend" / "baseline.js").read_text(encoding="utf-8")
    start, end = js.index("function sparkline"), js.index("async function renderPage")
    unit = js[start:end]
    return {name: set(re.findall(rf"\b{var}\.(\w+)", unit)) - {"length"}
            for name, var in (("resident", "resident"), ("shift", "shift"),
                              ("watch_window", "window"), ("data", "data"))}


def test_unit_page_matches_the_live_watchlist_for_the_loaded_cohort(sandbox, tmp_path):
    cfg, sandbox_patient, actors, objects = sandbox
    scope = DemoScope(actors["importer"].tenant_id, actors["importer"].principal_id,
                      actors["nurse"].principal_id)
    report, session = load_demo(cfg, objects=objects, scope=scope, offline=True,
                                presentation="scenario-snapshots")
    assert report["matches_spec"] is True

    client = workspace_client(sandbox)
    assert client.get("/unit").status_code == 200
    token = client.get("/demo/session", headers={"X-PM-Demo": "1"}).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    response = client.get("/v1/watchlist")
    assert response.status_code == 200
    data = response.json()

    # Field contract: everything baseline.js reads exists in the live payload.
    fields = unit_page_fields()
    assert fields["resident"] >= {"patient_id", "display_name", "latest_verdict", "fused_z",
                                  "over_budget", "watch_window", "sparkline", "last_check_ts"}
    assert fields["data"] <= set(data), fields["data"] - set(data)
    assert fields["shift"] <= set(data["shift"]), fields["shift"] - set(data["shift"])
    assert isinstance(data["shift"]["escalations_used"], int)
    assert isinstance(data["shift"]["escalation_budget"], int)
    for name in ("start", "end"):
        datetime.fromisoformat(data["shift"][name])
    residents = data["residents"]
    for resident in residents:
        assert fields["resident"] <= set(resident), fields["resident"] - set(resident)
        assert fields["watch_window"] <= set(resident["watch_window"])
        assert resident["synthetic"] is True
        assert resident["latest_verdict"] in (*RANK, None)
        for point in resident["sparkline"]:
            assert set(point) == {"day", "speech_rate_wpm"}

    # Everyone the nurse cares for is listed: the 12 cohort residents plus the sandbox patient.
    roster = {p["id"]: p["name"] for p in session["patients"]}
    ids = [r["patient_id"] for r in residents]
    assert len(ids) == len(set(ids)) == 13
    assert set(ids) == set(roster) | {str(sandbox_patient)}
    assert all(r["display_name"] == roster[r["patient_id"]] for r in residents
               if r["patient_id"] in roster)

    # Sort contract (docs/06-baseline.md): verdict rank, then fused z descending; no data last.
    keys = [(RANK.get(r["latest_verdict"], 4),
             -(r["fused_z"] if r["fused_z"] is not None else float("-inf"))) for r in residents]
    assert keys == sorted(keys)
    assert [(r["display_name"], r["latest_verdict"]) for r in residents[:3]] == [
        ("Mrs. K", "escalate"), ("Mrs. L", "watch"), ("Mr. T", "explained")]
    assert all(r["latest_verdict"] == "within_normal" for r in residents[3:12])
    assert residents[-1]["patient_id"] == str(sandbox_patient)
    assert residents[-1]["latest_verdict"] is None and residents[-1]["last_check_ts"] is None
    assert all(r["last_check_ts"] for r in residents[:12])

    # Run the real page code against this captured response.
    fixture = tmp_path / "watchlist-live.json"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    result = run_js_suites("unit_page.test.mjs", fixture_env={"UNIT_WATCHLIST_FIXTURE": str(fixture)})
    print(result.stdout)
