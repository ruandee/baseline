import shutil
import subprocess
import tempfile
from uuid import UUID, uuid4

import psycopg
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.auth import synthetic_token
from patient_memory.speech import asr
from patient_memory.speech.asr import Word
from patient_memory.speech.quality import DAYS, NUMBER_WORDS
from patient_memory.speech.vad import SAMPLE_RATE
from tests.unit.synthetic_audio import clip

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

# 9.6 s: five 1.4 s voiced runs separated by 0.4 s pauses inside 0.6 s of lead-in silence.
USABLE = [("s", 0.6)] + [("v", 1.4), ("s", 0.4)] * 5
TOO_SHORT = [("s", 0.3), ("v", 2.0), ("s", 0.4), ("v", 1.0)]
ENCODERS = {
    "webm": ["-c:a", "libopus", "-f", "webm"],
    "mp4": ["-c:a", "aac", "-f", "mp4"],
    "wav": ["-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", "-f", "wav"],
}
FIELDS = {"mode": "resident", "device_id": "tablet-1"}


def encode(plan, kind, directory):
    source, target = directory / "source.wav", directory / f"clip.{kind}"
    sf.write(source, clip(plan), SAMPLE_RATE)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source),
                    *ENCODERS[kind], str(target)], check=True)
    return target.read_bytes()


@pytest.fixture(scope="module")
def recordings(tmp_path_factory):
    directory = tmp_path_factory.mktemp("recordings")
    return {kind: encode(USABLE, kind, directory) for kind in ENCODERS} | {
        "short": encode(TOO_SHORT, "webm", directory)}


def on_script(audio):
    """Twenty-seven prompt tokens spread over the clip, standing in for Whisper."""
    tokens = [*NUMBER_WORDS, *DAYS]
    step = (len(audio) / SAMPLE_RATE - 1.0) / len(tokens)
    return [Word(t, 0.5 + i * step, 0.5 + i * step + 0.8 * step) for i, t in enumerate(tokens)]


def client_for(sandbox, role="nurse", transcriber=on_script):
    cfg, _, actors, objects = sandbox
    client = TestClient(create_app(cfg, objects, transcriber=transcriber))
    client.headers["Authorization"] = "Bearer " + synthetic_token(actors[role], cfg)
    return client


def upload(client, patient, content, **fields):
    return client.post(f"/v1/patients/{patient}/checks", data={**FIELDS, **fields},
                       files={"audio": ("clip", content, "application/octet-stream")})


def stored_checks(sandbox):
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        return admin.execute("SELECT * FROM voice_checks WHERE patient_id=%s",
                             (sandbox[1],)).fetchall()


@pytest.mark.parametrize("kind", ["webm", "mp4", "wav"])
def test_check_returns_features_for_every_browser_format(sandbox, recordings, kind):
    response = upload(client_for(sandbox), sandbox[1], recordings[kind])
    assert response.status_code == 200, response.text
    body = response.json()
    assert UUID(body["check_id"]) and body["ts"]
    assert body["usable"] is True and body["quality"]["reasons"] == []
    assert body["quality"]["duration_s"] == pytest.approx(9.6, abs=0.3)
    assert body["quality"]["clipped"] is False
    features = body["features"]
    assert set(features) == {"speech_rate_wpm", "pause_ratio", "mean_pause_s", "f0_median_hz"}
    assert features["speech_rate_wpm"] > 0 and features["pause_ratio"] > 0
    assert features["f0_median_hz"] == pytest.approx(140, rel=0.1)
    assert len(body["words"]) == 27 and body["words"][0]["w"] == "one"
    assert len(body["pauses"]) >= 3
    assert {"normalize", "vad", "asr", "prosody"} <= set(body["timings_ms"])
    assert body["change"]["status"] == "enrolling"
    assert body["assessment"]["verdict"] == "enrolling"
    assert body["assessment"]["suggested_action"] == "none"
    assert len(stored_checks(sandbox)) == 1


def test_check_is_stored_with_its_metadata_and_audited(sandbox, recordings):
    response = upload(client_for(sandbox), sandbox[1], recordings["webm"], mode="runner",
                      device_id="phone-9", device_ts="2026-10-18T14:12:03Z", is_baseline="true")
    assert response.status_code == 200, response.text
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        row = admin.execute(
            "SELECT id, mode, device_id, device_ts, is_baseline, usable, transcript, "
            "speech_rate_wpm, jsonb_array_length(words), prompt_version FROM voice_checks "
            "WHERE patient_id=%s", (sandbox[1],)).fetchone()
        audited = admin.execute("SELECT count(*) FROM audit WHERE patient_id=%s AND action=%s",
                                (sandbox[1], "create_check")).fetchone()[0]
    assert str(row[0]) == response.json()["check_id"]
    assert row[1:6] == ("runner", "phone-9", row[3], True, True)
    assert row[3].isoformat() == "2026-10-18T14:12:03+00:00"
    assert row[6].startswith("one two three") and row[7] == response.json()["features"]["speech_rate_wpm"]
    assert row[8] == 27 and row[9] == "count20-days-v1"
    assert audited == 1


def test_short_clip_is_unusable_but_still_stored_for_audit(sandbox, recordings):
    response = upload(client_for(sandbox), sandbox[1], recordings["short"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["usable"] is False and "too_short" in body["quality"]["reasons"]
    assert body["change"] is None and body["assessment"] is None
    assert len(stored_checks(sandbox)) == 1


def test_other_patient_and_non_care_roles_get_404_before_any_audio_work(sandbox, recordings):
    def forbidden(audio):
        raise AssertionError("audio must not be processed for an unauthorized caller")

    stranger = upload(client_for(sandbox, transcriber=forbidden), uuid4(), recordings["webm"])
    assert stranger.status_code == 404
    for role in ["patient", "admin"]:
        response = upload(client_for(sandbox, role, forbidden), sandbox[1], recordings["webm"])
        assert response.status_code == 404, role
    assert stored_checks(sandbox) == []


def test_body_over_two_megabytes_is_413(sandbox):
    response = upload(client_for(sandbox), sandbox[1], b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert stored_checks(sandbox) == []


def test_multipart_is_still_refused_on_every_other_route(sandbox):
    client = client_for(sandbox)
    response = client.post(f"/v1/patients/{sandbox[1]}/questions", data={"question": "sleep?"},
                           files={"audio": ("clip", b"x", "audio/wav")})
    assert response.status_code == 415
    json_on_checks = client.post(f"/v1/patients/{sandbox[1]}/checks", json={"mode": "resident"})
    assert json_on_checks.status_code == 415


@pytest.mark.parametrize("fields", [{"mode": "doctor"}, {"device_id": ""},
                                    {"device_ts": "yesterday"}, {"is_baseline": "maybe"}])
def test_invalid_form_fields_are_422(sandbox, recordings, fields):
    response = upload(client_for(sandbox), sandbox[1], recordings["webm"], **fields)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"


def test_missing_audio_is_422(sandbox):
    fields = {name: (None, value) for name, value in FIELDS.items()}
    response = client_for(sandbox).post(f"/v1/patients/{sandbox[1]}/checks", files=fields)
    assert response.status_code == 422


def test_undecodable_audio_is_422_and_leaks_nothing(sandbox):
    response = upload(client_for(sandbox), sandbox[1], b"not audio at all")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert "ffmpeg" not in response.text.lower()
    assert stored_checks(sandbox) == []


@pytest.mark.parametrize("kind", ["webm", "mp4", "wav"])
def test_temp_audio_is_deleted_unless_keep_audio(sandbox, recordings, tmp_path, monkeypatch, kind):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    upload(client_for(sandbox), sandbox[1], recordings[kind])
    upload(client_for(sandbox), sandbox[1], b"not audio at all")
    assert list(tmp_path.iterdir()) == []

    keeper = (sandbox[0].model_copy(update={"keep_audio": True}), *sandbox[1:])
    assert upload(client_for(keeper), sandbox[1], recordings[kind]).status_code == 200
    assert len(list(tmp_path.iterdir())) == 1


def test_missing_ffmpeg_is_503_and_stores_nothing(sandbox, recordings, monkeypatch):
    monkeypatch.setenv("PATH", "")
    response = upload(client_for(sandbox), sandbox[1], recordings["webm"])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert stored_checks(sandbox) == []


def test_a_body_just_under_the_limit_reaches_the_route(sandbox):
    response = upload(client_for(sandbox), sandbox[1], b"x" * (2 * 1024 * 1024 - 4096))
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_audio"


def test_access_revoked_during_processing_stores_nothing(sandbox, recordings):
    def revoke_then_transcribe(audio):
        with psycopg.connect(sandbox[0].admin_database_url) as admin:
            admin.execute("UPDATE assignments SET active=false WHERE patient_id=%s", (sandbox[1],))
        return on_script(audio)

    client = client_for(sandbox, transcriber=revoke_then_transcribe)
    assert upload(client, sandbox[1], recordings["webm"]).status_code == 404
    assert stored_checks(sandbox) == []


def test_whisper_loads_at_startup_but_a_failure_does_not_stop_the_app(sandbox, monkeypatch, caplog):
    def broken():
        raise OSError("offline")

    cfg, _, _, objects = sandbox
    monkeypatch.setattr(asr, "model", broken)
    with TestClient(create_app(cfg, objects)) as client:
        assert client.get("/v1/health/live").status_code == 200
    assert "Whisper failed to load" in caplog.text

    loaded = []
    monkeypatch.setattr(asr, "model", lambda: loaded.append(True))
    with TestClient(create_app(cfg, objects)):
        pass
    assert loaded == [True]
    with TestClient(create_app(cfg, objects, transcriber=on_script)):
        pass
    assert loaded == [True]  # a stubbed transcriber never triggers the real model
