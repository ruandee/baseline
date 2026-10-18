"""Protocol admission precedes decode and rechecks the same explicit metadata under lock."""
from uuid import uuid4

import psycopg
import pytest

from patient_memory.check_profiles import seed_english_profile
from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import transaction
from tests.contract.test_api import client_for
from tests.integration.test_assessments import QUALITY, SLOW


def path(sandbox):
    return f"/v1/patients/{sandbox[1]}/check-profile"


def upload(sandbox, **fields):
    return client_for(sandbox, "psw").post(f"/v1/patients/{sandbox[1]}/checks",
        data={"mode": "resident", "device_id": "synthetic", **fields},
        files={"audio": ("synthetic.wav", b"stub", "audio/wav")})


def test_profile_and_due_are_score_free_and_authorized(sandbox):
    for role in ("nurse", "importer", "psw"):
        profile = client_for(sandbox, role).get(path(sandbox))
        assert profile.status_code == 200
        assert set(profile.json()) == {"first_name", "preferred_locale", "version", "state",
                                       "protocol_locale", "prompt_version", "can_configure", "can_record_consent", "voice_consent_state"}
        assert profile.json()["can_record_consent"] is (role == "nurse")
        assert profile.json()["can_configure"] is (role != "psw")
        assert profile.json()["voice_consent_state"] == "granted"
    for role in ("patient", "admin"):
        assert client_for(sandbox, role).get(path(sandbox)).status_code == 404
    assert client_for(sandbox, "psw").put(path(sandbox), json={"preferred_locale": "fr"}).status_code == 404
    assert client_for(sandbox).get(f"/v1/patients/{uuid4()}/check-profile").status_code == 404
    assert client_for(sandbox).put(path(sandbox), json={"preferred_locale": "en", "first_name": "Mary Ann"}).status_code == 200
    row = client_for(sandbox, "psw").get("/v1/checks/due").json()["residents"][0]
    assert row["check_profile"]["first_name"] == "Mary Ann"
    assert not {"verdict", "features", "assessment", "sbar", "fused_z"} & set(row)


@pytest.mark.parametrize("locale", [None, "fr", "en-CA"])
def test_unconfigured_or_unsupported_language_blocks_before_decode(sandbox, monkeypatch, locale):
    client_for(sandbox).put(path(sandbox), json={"preferred_locale": locale})
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **k: pytest.fail("decode must not run"))
    response = upload(sandbox)
    assert response.status_code == 409 and response.json()["error"]["code"] == "check_language_unavailable"
    due = client_for(sandbox, "psw").get("/v1/checks/due").json()["residents"][0]
    assert due["status"] == "language_unavailable"
    assert due["check_profile"]["state"] == ("unconfigured" if locale is None else "unsupported")
    # Fixture reloads preserve every existing choice, including explicit unconfigured.
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        seed_english_profile(conn, sandbox[2]["importer"].tenant_id, sandbox[1], sandbox[2]["importer"].principal_id)
    assert client_for(sandbox).get(path(sandbox)).json()["preferred_locale"] == locale


def test_missing_row_is_unconfigured_not_english(sandbox, monkeypatch):
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("DELETE FROM resident_check_profiles WHERE patient_id=%s", (sandbox[1],))
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **k: pytest.fail("decode must not run"))
    assert client_for(sandbox).get(path(sandbox)).json()["state"] == "unconfigured"
    assert upload(sandbox).status_code == 409


def test_client_cannot_override_resident_protocol_or_replay_an_old_profile(sandbox, monkeypatch):
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **k: pytest.fail("decode must not run"))
    assert upload(sandbox, protocol_locale="fr").status_code == 409
    assert upload(sandbox, profile_version=str(uuid4())).status_code == 409


def test_psw_effective_consent_projection_refreshes_without_sdm_details(sandbox, monkeypatch):
    response = client_for(sandbox).post(f"/v1/patients/{sandbox[1]}/consents", json={
        "scope": "voice_check", "status": "withdrawn", "decided_by": "substitute_decision_maker",
        "sdm_reference": "synthetic-private-reference"})
    assert response.status_code == 201
    profile = client_for(sandbox, "psw").get(path(sandbox)).json()
    assert profile["voice_consent_state"] == "withdrawn"
    assert not {"sdm_reference", "decided_by", "note", "recorded_by", "recorded_at"} & set(profile)
    assert "synthetic-private-reference" not in str(profile)
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **k: pytest.fail("decode/ASR must not run"))
    assert upload(sandbox).status_code == 403


def test_profile_cannot_be_read_across_tenants(sandbox):
    tenant, actor = uuid4(), uuid4()
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("INSERT INTO tenants(id,name) VALUES(%s,'synthetic-other')", (tenant,))
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-other')", (actor, tenant))
        # Patients have a global UUID PK, so use an existing foreign patient with its own ID.
        patient = uuid4()
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'synthetic-other')", (patient, tenant))
        seed_english_profile(conn, tenant, patient, actor, first_name="Private synthetic name")
    for role in ("nurse", "importer", "psw"):
        assert client_for(sandbox, role).get(f"/v1/patients/{patient}/check-profile").status_code == 404
    assert all(r["patient_id"] != str(patient)
               for r in client_for(sandbox, "psw").get("/v1/checks/due").json()["residents"])


def test_profile_change_during_decode_rejects_even_english_to_english(sandbox, monkeypatch):
    before = client_for(sandbox).get(path(sandbox)).json()
    def analyze(*args, **kwargs):
        updated = client_for(sandbox).put(path(sandbox), json={"preferred_locale": "en", "first_name": "Mary Ann"})
        assert updated.status_code == 200 and updated.json()["version"] != before["version"]
        return Analysis(True, QUALITY, SLOW, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", analyze)
    assert upload(sandbox, profile_version=before["version"], protocol_locale="en").status_code == 409
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        assert conn.execute("SELECT count(*) FROM voice_checks WHERE patient_id=%s", (sandbox[1],)).fetchone()[0] == 0


def test_new_check_has_immutable_protocol_snapshot_and_psw_only_receipt(sandbox, monkeypatch):
    profile = client_for(sandbox).put(path(sandbox), json={"preferred_locale": "en", "first_name": "Mary Ann"}).json()
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **k: Analysis(True, QUALITY, SLOW, [], [], {}))
    response = upload(sandbox, profile_version=profile["version"], protocol_locale="en")
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"check_id", "ts", "usable"}
    cfg, patient, actors, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as conn:
        row = conn.execute("SELECT * FROM voice_check_profiles WHERE patient_id=%s", (patient,)).fetchone()
        assert str(row[4]) == profile["version"] and row[5:8] == ("en", "count20-days-v1", "Mary Ann")
    with transaction(cfg, actors["psw"]) as conn:
        assert not conn.execute("SELECT * FROM voice_check_profiles WHERE patient_id=%s", (patient,)).fetchall()
    with transaction(cfg, actors["nurse"]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE voice_check_profiles SET locale='en' WHERE patient_id=%s", (patient,))
