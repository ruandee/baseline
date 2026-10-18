"""Real loader → authorized overview/evidence/note → resident DOM; no model calls."""
import json

from scripts.load_baseline_demo import DemoScope, load_demo
from tests.contract.test_frontend import workspace_client
from tests.js_runner import run_js_suites


def test_loaded_resident_citations_and_editable_draft(sandbox, tmp_path):
    cfg, _, actors, objects = sandbox
    report, session = load_demo(cfg, objects=objects,
        scope=DemoScope(actors["importer"].tenant_id, actors["importer"].principal_id,
                        actors["nurse"].principal_id), offline=True,
        presentation="scenario-snapshots")
    assert report["matches_spec"]
    pid = next(p["id"] for p in session["patients"] if p["name"] == "Mrs. K")
    client = workspace_client(sandbox)
    assert client.get(f"/resident/{pid}").status_code == 200
    token = client.get("/demo/session", headers={"X-PM-Demo": "1"}).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    response = client.get(f"/v1/patients/{pid}/overview?days=30")
    assert response.status_code == 200, response.text
    overview = response.json()
    assert overview["latest_assessment"]["verdict"] == "escalate"
    check = overview["latest_assessment"]["check"]
    assert check["synthetic"] is True
    assert check["ts"] == overview["latest_assessment"]["ts"]
    assert any(f"check:{check['id']}" in sentence["evidence_ids"]
               for sentence in overview["latest_assessment"]["sbar"]["sentences"])
    temperature, = overview["documented_observations"]
    assert temperature["value"] == 37.1 and temperature["unit"] == "C"
    assert temperature["recorded_at"].startswith("2026-10-14T12:00")
    assert "normal" not in temperature["label"].lower()
    evidence_ids = {temperature["evidence_id"]}
    evidence_ids.update(r["evidence_id"] for r in overview["latest_assessment"]["reasons"])
    evidence_ids.update(e for s in overview["latest_assessment"]["sbar"]["sentences"]
                        for e in s["evidence_ids"] if not e.startswith("check:"))
    evidence = {}
    for eid in evidence_ids:
        item = client.get(f"/v1/patients/{pid}/evidence/{eid}")
        assert item.status_code == 200, item.text
        evidence[eid] = item.json()
    assert "37.1" in evidence[temperature["evidence_id"]]["quote"]
    aid = overview["latest_assessment"]["id"]
    note = client.get(f"/v1/patients/{pid}/assessments/{aid}/note")
    assert note.status_code == 200, note.text
    fixture = tmp_path / "resident.json"
    fixture.write_text(json.dumps(dict(overview=overview, evidence=evidence, note=note.json())),
                       encoding="utf-8")
    run_js_suites("resident_live.test.js", fixture_env={"RESIDENT_LIVE_FIXTURE": str(fixture)})
