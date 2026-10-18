"""BL-30: persisted synthetic adapters, temporal corroboration and scoped evidence."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline.assess import assess_modality, escalations_used
from patient_memory.baseline.engine import REGISTRY, Check, FeatureSpec, Modality
from patient_memory.errors import Problem
from patient_memory.storage import transaction
from tests.contract.test_api import client_for, import_note, source_payload
from tests.integration.test_assessments import BASE, SLOW, seed_checks, store

PROBE = Modality("probe", (FeatureSpec("probe_x", "probe", 1, 0.1),
                           FeatureSpec("probe_y", "probe", 1, 0.1)))


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setitem(REGISTRY, "probe", PROBE)


def evidence(sandbox, at=None):
    at = at or datetime.now(UTC) - timedelta(days=10)
    imported = import_note(sandbox, source_payload(
        text=None, kind="observation", author_role="system", recorded_at=at.isoformat(),
        effective_from=at.isoformat(), records=[{"concept": "synthetic_probe", "value": "Synthetic probe capture"}]))
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        fact = conn.execute("SELECT id FROM facts WHERE source_id=%s",
                            (imported["source_version_id"],)).fetchone()["id"]
    return str(fact), imported["source_version_id"]


def capture(fact, at=None, flagged=True):
    return Check(str(uuid4()), at or datetime.now(UTC), "synthetic-probe", "probe-v1", False,
                 True, {"probe_x": 12.0 if flagged else 10.0,
                        "probe_y": 12.0 if flagged else 10.0}, "probe", (fact,))


def history(check):
    return [replace(check, id=str(uuid4()), ts=check.ts-timedelta(days=7-i), is_baseline=True,
                    features={"probe_x": 10.0, "probe_y": 10.0}) for i in range(4)]


def admit(sandbox, check, role="nurse", loader=None):
    cfg, pid, actors, _ = sandbox
    with transaction(cfg, actors[role]) as conn:
        return assess_modality(conn, cfg, pid, actors[role].tenant_id, check, "Synthetic",
                               loader or (lambda scoped: history(check)))


def page(sandbox):
    response = client_for(sandbox).get(f"/v1/patients/{sandbox[1]}/overview")
    assert response.status_code == 200, response.text
    return response.json()


def test_persisted_two_modalities_corroborate_without_breaking_speech_readback(sandbox, probe):
    fact, source = evidence(sandbox)
    seed_checks(sandbox, 6)
    speech = store(sandbox, SLOW)
    assert speech.change["status"] == "provisional"
    change, assessment = admit(sandbox, capture(fact))
    assert change["status"] == "provisional" and change["verdict_status"] == "change"
    assert assessment["corroborated"] and assessment["verdict"] == "escalate"
    assert assessment["draft_status"] == "unavailable_multimodal_evidence"
    overview = page(sandbox)
    latest = overview["latest_assessment"]
    assert latest["corroborated"] and latest["modality"] == "probe" and latest["sbar"] is None
    assert set(latest["modalities"]) == {"speech", "probe"}
    assert latest["modalities"]["probe"]["evidence_ids"] == [fact]
    assert latest["change"]["per_feature"]["speech_rate_wpm"]["value"] == SLOW["speech_rate_wpm"]
    assert overview["baseline"]["features"]["speech_rate_wpm"]["median"] > 0
    assert overview["series"]["speech_rate_wpm"]["checks"]
    resident, = client_for(sandbox).get("/v1/watchlist").json()["residents"]
    assert resident["corroborated"] and "probe" in resident["modalities"]
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        stored = conn.execute("SELECT * FROM assessments WHERE id=%s", (assessment["id"],)).fetchone()
        assert source in stored["params"]["source_ids"]
        assert set(stored["features"]) == {"speech", "probe"}
        assert escalations_used(conn, datetime.now(UTC), sandbox[0]) == 1
        conn.execute("SELECT set_config('pm.check_scoring_patient',%s,true)", (str(sandbox[1]),))
        assert escalations_used(conn, datetime.now(UTC), sandbox[0]) == 1


def test_latest_quiet_modality_replaces_older_flag_not_only_latest_alarm(sandbox, probe):
    fact, _ = evidence(sandbox)
    now = datetime.now(UTC)
    assert admit(sandbox, capture(fact, now-timedelta(hours=2)))[0]["status"] == "provisional"
    assert admit(sandbox, capture(fact, now-timedelta(hours=1), False))[0]["status"] == "none"
    seed_checks(sandbox, 6)
    result = store(sandbox, SLOW)
    assert not result.assessment["corroborated"]
    assert result.change["modalities"]["probe"]["status"] == "none"
    assert result.change["verdict_status"] == "provisional"


@pytest.mark.parametrize("hours", [25, -1])
def test_stale_and_future_modality_cannot_corroborate(sandbox, probe, hours):
    fact, _ = evidence(sandbox)
    check = capture(fact, datetime.now(UTC)-timedelta(hours=hours))
    admit(sandbox, check)
    seed_checks(sandbox, 6)
    result = store(sandbox, SLOW)
    assert not result.assessment["corroborated"]
    if hours > 0:
        assert result.change["modalities"]["probe"]["current"] is False
    else:
        assert result.change["modalities"]["probe"]["status"] == "unavailable"
    assert page(sandbox)["latest_assessment"]["modality"] == "speech"


def test_source_lifecycle_clears_multimodal_snapshot_and_prevents_reuse(sandbox, probe):
    fact, source = evidence(sandbox)
    admit(sandbox, capture(fact))
    response = client_for(sandbox, "importer").post(
        f"/v1/patients/{sandbox[1]}/sources/{source}/retract", json={"reason": "Synthetic correction"},
        headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.text
    assert page(sandbox)["latest_assessment"] is None
    with pytest.raises(Problem) as raised:
        admit(sandbox, capture(fact))
    assert raised.value.code == "signal_evidence_unavailable"
    seed_checks(sandbox, 6)
    assert not store(sandbox, SLOW).assessment["corroborated"]


@pytest.mark.parametrize("role", ["patient", "admin", "psw"])
def test_unauthorized_adapter_cannot_retrieve_history_or_publish(sandbox, probe, role):
    fact, _ = evidence(sandbox)
    def forbidden(conn):
        pytest.fail("authorization must precede history retrieval")
    with pytest.raises(Problem) as raised:
        admit(sandbox, capture(fact), role, forbidden)
    assert raised.value.status == 404
    assert client_for(sandbox, role).get(f"/v1/patients/{sandbox[1]}/overview").status_code == 404


def test_foreign_missing_and_future_citations_cannot_be_admitted(sandbox, probe):
    missing = capture(str(uuid4()))
    with pytest.raises(Problem) as raised:
        admit(sandbox, missing)
    assert raised.value.code == "signal_evidence_unavailable"
    fact, _ = evidence(sandbox, datetime.now(UTC)+timedelta(days=1))
    with pytest.raises(Problem) as raised:
        admit(sandbox, capture(fact))
    assert raised.value.code == "signal_evidence_unavailable"
    with pytest.raises(Problem) as raised:
        admit(sandbox, replace(missing, evidence_ids=()))
    assert raised.value.code == "signal_evidence_required"


def test_revoked_assignment_withholds_previous_modalities(sandbox, probe):
    fact, _ = evidence(sandbox)
    admit(sandbox, capture(fact))
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("UPDATE assignments SET active=false WHERE patient_id=%s AND principal_id=%s",
                     (sandbox[1], sandbox[2]["nurse"].principal_id))
    with pytest.raises(Problem) as raised:
        admit(sandbox, capture(fact))
    assert raised.value.status == 404
    assert client_for(sandbox).get(f"/v1/patients/{sandbox[1]}/overview").status_code == 404


def test_legacy_flat_speech_rows_retain_overview_and_baseline_shape(sandbox):
    seed_checks(sandbox, 6)
    result = store(sandbox, BASE)
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("UPDATE assessments SET features=features->'speech', "
                     "params=params-'modality_results'-'signal_ts'-'modality' WHERE id=%s",
                     (result.assessment["id"],))
    overview = page(sandbox)
    assert overview["latest_assessment"]["change"]["per_feature"]["speech_rate_wpm"]["value"] == BASE["speech_rate_wpm"]
    assert overview["baseline"]["features"]["speech_rate_wpm"]["median"] > 0
    assert overview["latest_assessment"]["modalities"]["speech"]["status"] == "none"
    assert not overview["latest_assessment"]["corroborated"]


def test_fact_from_another_patient_cannot_support_this_signal(sandbox, probe):
    cfg, _, actors, objects = sandbox
    other = uuid4()
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'synthetic-other')",
                     (other, actors["nurse"].tenant_id))
        for role in ("nurse", "importer"):
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true)",
                         (actors[role].tenant_id, other, actors[role].principal_id, role))
    foreign, _ = evidence((cfg, other, actors, objects))
    with pytest.raises(Problem) as raised:
        admit(sandbox, capture(foreign))
    assert raised.value.code == "signal_evidence_unavailable"


def test_source_supersession_cannot_be_reused_as_signal_evidence(sandbox, probe):
    fact, source = evidence(sandbox)
    with transaction(sandbox[0], sandbox[2]["importer"]) as conn:
        payload = conn.execute("SELECT payload FROM sources WHERE id=%s", (source,)).fetchone()["payload"]
    payload.update(external_version_id="2", supersedes_version_id=source)
    payload["records"][0]["value"] = "Synthetic corrected probe capture"
    import_note(sandbox, payload)
    with pytest.raises(Problem) as raised:
        admit(sandbox, capture(fact))
    assert raised.value.code == "signal_evidence_unavailable"
