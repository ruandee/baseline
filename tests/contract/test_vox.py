"""POST /v1/integrations/vox/encounters: the MOCK Vox Advantage adapter (BL-32, decision 016)."""
import io
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.auth import synthetic_token
from patient_memory.integrations import vox
from patient_memory.speech.vad import SAMPLE_RATE
from tests.unit.synthetic_audio import encounter
from tests.unit.test_vox import chatter

# CI installs ffmpeg; there a missing decoder must fail these contracts rather than skip them.
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None and not os.environ.get("CI"),
                                reason="ffmpeg not installed")

ROUTE = "/v1/integrations/vox/encounters"
FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "fixtures/synthetic/"
                      "vox_encounter_mrs_k.json").read_text(encoding="utf-8"))


def wav(segments):
    buffer = io.BytesIO()
    sf.write(buffer, encounter(segments), SAMPLE_RATE, format="WAV")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def fixture_audio():
    return wav(FIXTURE["segments"])


class Spy:
    """Stub transcriber that records the clip lengths it was given."""

    def __init__(self):
        self.heard = []

    def __call__(self, audio):
        self.heard.append(len(audio) / SAMPLE_RATE)
        return chatter(audio)


def client_for(sandbox, role="nurse", transcriber=None):
    cfg, _, actors, objects = sandbox
    client = TestClient(create_app(cfg, objects, transcriber=transcriber or Spy()))
    client.headers["Authorization"] = "Bearer " + synthetic_token(actors[role], cfg)
    return client


def post(client, resident_id, content, **overrides):
    data = {"resident_id": str(resident_id), "segments": json.dumps(FIXTURE["segments"]),
            "consent": "true", "encounter_ts": FIXTURE["encounter_ts"], **overrides}
    data = {k: v for k, v in data.items() if v is not None}
    return client.post(ROUTE, data=data,
                       files={"audio": ("encounter.wav", content, "application/octet-stream")})


def admin_rows(sandbox, sql, *args):
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        return admin.execute(sql, args).fetchall()


def checks(sandbox, patient=None):
    return admin_rows(sandbox, "SELECT mode, device_id, device_ts, prompt_version, usable, transcript,"
                      " is_baseline FROM voice_checks WHERE patient_id=%s", patient or sandbox[1])


def audits(sandbox, patient=None):
    return admin_rows(sandbox, "SELECT action, result FROM audit WHERE patient_id=%s ORDER BY id",
                      patient or sandbox[1])


@pytest.fixture
def no_audio_work(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("audio must not be processed")

    monkeypatch.setattr(vox, "decode_upload", forbidden)
    return forbidden


def test_fixture_encounter_produces_a_resident_only_free_conversation_check(sandbox, fixture_audio):
    spy = Spy()
    response = post(client_for(sandbox, transcriber=spy), sandbox[1], fixture_audio)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mock"] is True and body["adapter"] == "vox-advantage-mock-v1"
    assert body["prompt_version"] == "free-conversation-v1"
    assert body["usable"] is True and body["reasons"] == []
    assert body["segments"] == {"resident": 3, "staff": 3, "other": 1}
    assert 8 <= body["resident_speech_s"] < body["analyzed_s"]
    assert body["resident_speech_s"] == body["check"]["quality"]["speech_s"]
    # Whisper saw one clip, exactly as long as the resident speech: no staff or other audio.
    assert spy.heard == [pytest.approx(body["analyzed_s"], abs=0.01)]
    assert body["check"]["features"]["f0_median_hz"] == pytest.approx(140, rel=0.05)
    assert body["check"]["change"]["status"] == "enrolling"
    assert body["check"]["change"]["params"]["z_threshold"] == 2.5
    assert body["check"]["assessment"]["verdict"] == "enrolling"

    (row,) = checks(sandbox)
    assert row[:2] == ("resident", "vox-mock") and row[3] == "free-conversation-v1"
    assert row[2] == datetime.fromisoformat(FIXTURE["encounter_ts"]) and row[4] is True
    assert row[6] is False
    # The stored transcript is exactly our ASR output on the resident-only clip; no submitted
    # segment text (staff or resident) is copied into storage.
    assert row[5] == " ".join(w["w"] for w in body["check"]["words"])
    assert not any(s["text"] in row[5] for s in FIXTURE["segments"])
    (params,) = admin_rows(sandbox, "SELECT params FROM assessments WHERE patient_id=%s",
                           sandbox[1])
    assert params[0]["prompt_version"] == "free-conversation-v1"
    assert params[0]["z_threshold"] == 2.5
    assert audits(sandbox) == [("create_check", "ok"), ("vox_encounter", "ok")]


@pytest.mark.parametrize("consent", [None, "false", "", "yes", "True", " true",
                                     ["true", "true"], ["true", "false"]])
def test_missing_false_loose_or_repeated_consent_is_422_audited_and_stores_nothing(
        sandbox, fixture_audio, no_audio_work, consent):
    response = post(client_for(sandbox), sandbox[1], fixture_audio, consent=consent)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "consent_not_given"
    assert checks(sandbox) == []
    assert admin_rows(sandbox, "SELECT count(*) FROM assessments WHERE patient_id=%s",
                      sandbox[1]) == [(0,)]
    assert audits(sandbox) == [("vox_encounter", "consent_refused")]


def test_consent_is_refused_even_when_the_rest_of_the_request_is_malformed(sandbox, no_audio_work):
    response = client_for(sandbox).post(ROUTE, data={"resident_id": str(sandbox[1]),
                                                     "consent": "false"},
                                        files={"segments": (None, "not json")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "consent_not_given"
    assert audits(sandbox) == [("vox_encounter", "consent_refused")]


def other_tenant_patient(sandbox):
    tenant, patient = uuid4(), uuid4()
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        admin.execute("INSERT INTO tenants VALUES(%s,'synthetic-other')", (tenant,))
        admin.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'other')",
                      (patient, tenant))
    return patient


def unassigned_patient(sandbox):
    patient = uuid4()
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        admin.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'unassigned')",
                      (patient, sandbox[2]["nurse"].tenant_id))
    return patient


@pytest.mark.parametrize("consent", ["true", "false"])
def test_wrong_tenant_patient_or_role_is_404_before_any_audio_or_consent_work(
        sandbox, fixture_audio, no_audio_work, consent):
    targets = [("nurse", uuid4()), ("nurse", other_tenant_patient(sandbox)),
               ("nurse", unassigned_patient(sandbox)), ("patient", sandbox[1]),
               ("admin", sandbox[1])]
    for role, patient in targets:
        response = post(client_for(sandbox, role), patient, fixture_audio, consent=consent)
        assert response.status_code == 404, (role, response.text)
        assert checks(sandbox, patient) == [] and audits(sandbox, patient) == []


def test_too_little_resident_speech_is_stored_unusable_without_transcription(sandbox):
    plan = [{"speaker": "staff", "start": 0.0, "end": 12.0, "text": "A long staff turn."},
            {"speaker": "resident", "start": 12.0, "end": 19.0, "text": "Short reply."}]
    spy = Spy()
    response = post(client_for(sandbox, transcriber=spy), sandbox[1], wav(plan),
                    segments=json.dumps(plan))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["usable"] is False and body["reasons"] == ["too_little_resident_speech"]
    assert body["check"]["change"] is None and body["check"]["assessment"] is None
    assert spy.heard == []
    (row,) = checks(sandbox)
    assert row[4] is False and row[3] == "free-conversation-v1"


def seed(sandbox, prompt_version, count=6, speech_rate=158.0):
    cfg, pid, actors, _ = sandbox
    now = datetime.now(UTC)
    with psycopg.connect(cfg.admin_database_url) as admin:
        for i in range(count):
            admin.execute(
                "INSERT INTO voice_checks(tenant_id,patient_id,id,ts,device_id,mode,prompt_version,"
                "is_baseline,usable,quality,speech_rate_wpm,pause_ratio,mean_pause_s,f0_median_hz,"
                "synthetic) VALUES(%s,%s,%s,%s,'vox-mock','resident',%s,false,true,'{}',%s,0.21,"
                "0.40,140.0,true)",
                (actors["nurse"].tenant_id, pid, uuid4(), now - timedelta(days=10 - i),
                 prompt_version, speech_rate + i % 3))


def test_counting_prompt_history_never_becomes_a_free_conversation_baseline(sandbox,
                                                                            fixture_audio):
    seed(sandbox, "count20-days-v1")
    body = post(client_for(sandbox), sandbox[1], fixture_audio).json()
    assert body["check"]["change"]["status"] == "enrolling"
    assert body["check"]["change"]["params"]["baseline_checks"] == 0


def test_an_encounter_is_scored_against_free_conversation_history_only(sandbox, fixture_audio):
    seed(sandbox, "count20-days-v1", speech_rate=300.0)
    seed(sandbox, "free-conversation-v1", speech_rate=70.0)
    body = post(client_for(sandbox), sandbox[1], fixture_audio).json()
    change = body["check"]["change"]
    assert change["params"]["baseline_checks"] == 6
    assert change["per_feature"]["speech_rate_wpm"]["median"] == pytest.approx(71.0)


def test_overview_first_change_marker_does_not_cross_prompt_histories(sandbox, fixture_audio):
    client = client_for(sandbox)
    first = post(client, sandbox[1], fixture_audio).json()["check"]
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        admin.execute("UPDATE assessments SET change_status='change' WHERE check_id=%s",
                      (first["check_id"],))
    assert post(client, sandbox[1], fixture_audio).status_code == 200
    route = f"/v1/patients/{sandbox[1]}/overview"
    assert client.get(route).json()["first_change_ts"] is not None
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        admin.execute("UPDATE voice_checks SET prompt_version='count20-days-v1' WHERE id=%s",
                      (first["check_id"],))
    page = client.get(route).json()
    assert page["baseline"]["prompt_version"] == "free-conversation-v1"
    assert page["first_change_ts"] is None


def test_multipart_exemption_is_this_route_and_the_check_route_only(sandbox, fixture_audio):
    client = client_for(sandbox)
    assert client.post(ROUTE, json={"resident_id": str(sandbox[1])}).status_code == 415
    for path in [f"/v1/patients/{sandbox[1]}/context", f"/v1/patients/{sandbox[1]}/questions",
                 "/v1/integrations/vox/encounters/extra", "/v1/integrations/vox"]:
        response = client.post(path, data={"x": "y"}, files={"audio": ("a", b"x", "audio/wav")})
        assert response.status_code == 415, path
    assert client.put(ROUTE, data={"x": "y"},
                      files={"audio": ("a", b"x", "audio/wav")}).status_code == 415


def test_body_over_the_limit_is_413_before_anything_is_stored(sandbox, no_audio_work):
    response = post(client_for(sandbox), sandbox[1], b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert checks(sandbox) == [] and audits(sandbox) == []


@pytest.mark.parametrize("overrides", [
    {"segments": "not json"}, {"segments": None}, {"encounter_ts": None},
    {"encounter_ts": "2026-10-16T14:05:00"},
    {"segments": json.dumps([{"speaker": "nurse", "start": 0, "end": 9}])},
])
def test_malformed_encounters_are_422_and_store_nothing(sandbox, fixture_audio, overrides):
    response = post(client_for(sandbox), sandbox[1], fixture_audio, **overrides)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "nurse" not in response.text and checks(sandbox) == []


def test_undecodable_audio_is_422_and_temp_audio_is_deleted(sandbox, tmp_path, monkeypatch,
                                                            fixture_audio):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    response = post(client_for(sandbox), sandbox[1], b"not audio at all")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_audio"
    assert post(client_for(sandbox), sandbox[1], fixture_audio).status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_encounter_audio_is_deleted_even_with_keep_audio(sandbox, tmp_path, monkeypatch,
                                                         fixture_audio):
    """Raw encounter audio contains staff speech, so PM_KEEP_AUDIO never keeps it."""
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    keeper = (sandbox[0].model_copy(update={"keep_audio": True}), *sandbox[1:])
    assert post(client_for(keeper), sandbox[1], fixture_audio).status_code == 200
    assert post(client_for(keeper), sandbox[1], b"not audio at all").status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_access_revoked_during_processing_stores_nothing(sandbox, fixture_audio):
    def revoke_then_transcribe(audio):
        with psycopg.connect(sandbox[0].admin_database_url) as admin:
            admin.execute("UPDATE assignments SET active=false WHERE patient_id=%s", (sandbox[1],))
        return chatter(audio)

    client = client_for(sandbox, transcriber=revoke_then_transcribe)
    assert post(client, sandbox[1], fixture_audio).status_code == 404
    assert checks(sandbox) == []
