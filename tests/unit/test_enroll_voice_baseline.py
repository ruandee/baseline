import hashlib
import json
from email.parser import BytesParser
from email.policy import default
from uuid import uuid4

import httpx
import numpy as np
import pytest

from scripts import enroll_voice_baseline as enrollment

PROFILE_VERSION = str(uuid4())


def ready_profile():
    return {"state": "ready", "preferred_locale": "en", "protocol_locale": "en",
            "prompt_version": "count20-days-v1", "version": PROFILE_VERSION}


def get_response(request):
    value = ({"state": "granted"} if request.url.path.endswith("/consent")
             else ready_profile() if request.url.path.endswith("/check-profile") else {})
    return httpx.Response(200, json=value)


@pytest.fixture
def clips(tmp_path, monkeypatch):
    paths = [tmp_path / f"take-{i}.wav" for i in range(5)]
    for i, path in enumerate(paths):
        path.write_bytes(f"independent-recording-{i}".encode())
    monkeypatch.setattr(enrollment, "normalize", lambda src, dst, **kw:
                        dst.write_bytes(b"normalized-" + src.read_bytes()))
    monkeypatch.setattr(enrollment, "load_pcm", lambda path: np.full(
        16000 * 10, int(path.stem.rsplit("-", 1)[1]) / 100, dtype=np.float32))
    return paths


def client_for(handler):
    return httpx.Client(base_url="https://demo.test", transport=httpx.MockTransport(handler))


def multipart_fields(request):
    body = (f"Content-Type: {request.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
            + request.content)
    message = BytesParser(policy=default).parsebytes(body)
    assert message.is_multipart()
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode()
            for part in message.iter_parts() if part.get_filename() is None}


def test_five_distinct_takes_use_existing_api_and_preserve_receipts(clips, tmp_path):
    posts = []

    def handler(request):
        if request.url.path.endswith("/consent"):
            return httpx.Response(200, json={"state": "granted"})
        if request.method == "GET":
            return get_response(request)
        posts.append(request)
        return httpx.Response(200, json={"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z",
                                         "usable": True, "transcript": "must not enter receipt"})

    output = tmp_path / "receipt.json"
    with client_for(handler) as client:
        report = enrollment.enroll(client, uuid4(), clips, "dee-demo-phone", output)
    assert report["status"] == "five_usable_checks_stored"
    assert len(posts) == 5 and len(report["checks"]) == 5
    assert [check["input_sha256"] for check in report["checks"]] == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in clips]
    for request in posts:
        fields = multipart_fields(request)
        assert fields["profile_version"] == PROFILE_VERSION
        assert fields["protocol_locale"] == "en"
        assert fields["is_baseline"] == "true" and fields["mode"] == "runner"
        assert b'name="is_baseline"\r\n\r\ntrue' in request.content
        assert b'name="mode"\r\n\r\nrunner' in request.content
        assert b'name="device_id"\r\n\r\ndee-demo-phone' in request.content
        assert b"Content-Type: audio/wav" in request.content
        assert b'name="profile_version"\r\n\r\n' + PROFILE_VERSION.encode() in request.content
        assert b'name="protocol_locale"\r\n\r\nen' in request.content
    assert "transcript" not in output.read_text()


def test_duplicate_recording_never_becomes_five_checks(clips, tmp_path):
    with client_for(lambda request: pytest.fail("must not call API")) as client:
        with pytest.raises(enrollment.EnrollmentError, match="Duplicate audio"):
            enrollment.enroll(client, uuid4(), [clips[0]] * 5, "device", tmp_path / "receipt")


def test_different_containers_with_identical_decoded_samples_never_upload(clips, tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "load_pcm", lambda path: np.full(16000 * 10, .125, dtype=np.float32))
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "Duplicate decoded audio must not be uploaded"
        return get_response(request)

    output = tmp_path / "receipt.json"
    with client_for(handler) as client:
        with pytest.raises(enrollment.EnrollmentError, match="Decoded recordings are duplicates"):
            enrollment.enroll(client, uuid4(), clips, "device", output)
    assert len(calls) == 3  # consent, explicit profile and authorized overview only
    assert not output.exists()


@pytest.mark.parametrize("seconds", [5, 31])
def test_decoded_duration_guard_precedes_upload(clips, tmp_path, monkeypatch, seconds):
    monkeypatch.setattr(enrollment, "load_pcm", lambda path: np.zeros(16000 * seconds, dtype=np.float32))

    def handler(request):
        assert request.method == "GET"
        return get_response(request)

    with client_for(handler) as client:
        with pytest.raises(enrollment.EnrollmentError, match="6-30 seconds"):
            enrollment.enroll(client, uuid4(), clips, "device", tmp_path / "receipt")


def test_real_wav_metadata_cannot_make_identical_synthetic_audio_distinct(tmp_path):
    import shutil
    import struct
    import wave

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")
    # Generated tone only: no microphone, personal recording, Whisper or network.
    samples = (3000 * np.sin(2 * np.pi * 220 * np.arange(16000 * 6) / 16000)).astype("<i2")
    clips = []
    for index in range(5):
        clip = tmp_path / f"synthetic-{index}.wav"
        with wave.open(str(clip), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.tobytes())
        title = f"Synthetic export {index}".encode("ascii") + b"\0"
        info = b"INFOINAM" + struct.pack("<I", len(title)) + title
        if len(title) % 2:
            info += b"\0"
        raw = clip.read_bytes() + b"LIST" + struct.pack("<I", len(info)) + info
        clip.write_bytes(raw[:4] + struct.pack("<I", len(raw) - 8) + raw[8:])
        clips.append(clip)

    def handler(request):
        assert request.method == "GET", "Metadata-only variants must not become baseline uploads"
        return get_response(request)

    with client_for(handler) as client:
        with pytest.raises(enrollment.EnrollmentError, match="Decoded recordings are duplicates"):
            enrollment.enroll(client, uuid4(), clips, "device", tmp_path / "receipt")


@pytest.mark.parametrize("state", ["unknown", "withdrawn", "declined", "expired"])
def test_consent_refusal_never_decodes_or_uploads(clips, tmp_path, monkeypatch, state):
    monkeypatch.setattr(enrollment, "normalize", lambda *a, **kw: pytest.fail("must not decode"))
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={"state": state})

    with client_for(handler) as client:
        with pytest.raises(enrollment.EnrollmentError, match="Granted voice-check consent"):
            enrollment.enroll(client, uuid4(), clips, "device", tmp_path / "receipt",
                              record_consent=state != "unknown")
    assert calls == ["GET"]


def test_explicit_unknown_consent_decision_precedes_upload(clips, tmp_path):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/consent"):
            return httpx.Response(200, json={"state": "unknown"})
        if request.url.path.endswith("/consents"):
            assert json.loads(request.content)["decided_by"] == "resident"
            return httpx.Response(201, json={"state": "granted"})
        if request.method == "GET":
            return get_response(request)
        return httpx.Response(200, json={"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z",
                                         "usable": True})

    with client_for(handler) as client:
        enrollment.enroll(client, uuid4(), clips, "device", tmp_path / "receipt",
                          record_consent=True)
    assert calls[1][1].endswith("/consents")


@pytest.mark.parametrize("failure", ["network", "unusable", "denied"])
def test_failures_stop_without_retries_and_keep_partial_receipt(clips, tmp_path, failure):
    posted = []

    def handler(request):
        if request.url.path.endswith("/consent"):
            return httpx.Response(200, json={"state": "granted"})
        if request.method == "GET":
            return get_response(request)
        posted.append(request)
        if failure == "network":
            raise httpx.ReadTimeout("response lost")
        if failure == "denied":
            return httpx.Response(403, json={})
        return httpx.Response(200, json={"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z",
                                         "usable": False})

    output = tmp_path / "receipt.json"
    with client_for(handler) as client:
        with pytest.raises((enrollment.EnrollmentError, httpx.ReadTimeout)):
            enrollment.enroll(client, uuid4(), clips, "device", output)
    assert len(posted) == 1
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "incomplete"
    assert len(receipt["checks"]) == (1 if failure == "unusable" else 0)


@pytest.mark.parametrize("url", ["http://demo.test", "https://user:secret@demo.test",
                                     "https://demo.test?token=secret", "https://demo.test/v1"])
def test_credentials_only_go_to_explicit_secure_origin(url):
    with pytest.raises(enrollment.EnrollmentError):
        enrollment.validate_url(url)


@pytest.mark.parametrize("damage", ["unconfigured", "unsupported", "wrong_protocol", "wrong_locale",
                                    "missing_version", "null_version", "invalid_version"])
def test_explicit_supported_versioned_profile_required_before_decode_or_upload(clips, tmp_path, monkeypatch, damage):
    profile = ready_profile()
    if damage == "unconfigured":
        profile.update(state="unconfigured", preferred_locale=None)
    elif damage == "unsupported":
        profile.update(state="unsupported", preferred_locale="fr")
    elif damage == "wrong_protocol":
        profile["prompt_version"] = "other-protocol"
    elif damage == "wrong_locale":
        profile["protocol_locale"] = "fr"
    elif damage == "missing_version":
        profile.pop("version")
    else:
        profile["version"] = None if damage == "null_version" else "invalid"
    calls = []
    monkeypatch.setattr(enrollment, "normalize", lambda *a, **kw: pytest.fail("profile must admit before decode"))

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "No profile/consent inference or capture upload"
        return httpx.Response(200, json=profile) if request.url.path.endswith("/check-profile") else get_response(request)

    with client_for(handler) as client:
        with pytest.raises(enrollment.EnrollmentError):
            enrollment.enroll(client, uuid4(), clips, "device", tmp_path / "receipt")
    assert len(calls) == 2 and calls[-1][1].endswith("/check-profile")
    assert not (tmp_path / "receipt").exists()


def test_changed_profile_stops_partial_enrollment_without_retry_or_silent_adoption(clips, tmp_path):
    posted, profile_reads = [], []

    def handler(request):
        if request.method == "GET":
            if request.url.path.endswith("/check-profile"):
                profile_reads.append(request)
            return get_response(request)
        posted.append(request)
        fields = multipart_fields(request)
        assert fields["profile_version"] == PROFILE_VERSION and fields["protocol_locale"] == "en"
        if len(posted) == 2:
            return httpx.Response(409, json={"error": {"code": "check_profile_changed"}})
        return httpx.Response(200, json={"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z", "usable": True})

    output = tmp_path / "receipt.json"
    with client_for(handler) as client:
        with pytest.raises(enrollment.EnrollmentError, match="409"):
            enrollment.enroll(client, uuid4(), clips, "device", output)
    assert len(profile_reads) == 1 and len(posted) == 2
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "incomplete" and len(receipt["checks"]) == 1
    assert receipt["pending_clip"] == 2
