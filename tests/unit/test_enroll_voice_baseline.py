import json
from uuid import uuid4

import httpx
import numpy as np
import pytest

from scripts import enroll_voice_baseline as enrollment


@pytest.fixture
def clips(tmp_path, monkeypatch):
    paths = [tmp_path / f"take-{i}.wav" for i in range(5)]
    for i, path in enumerate(paths):
        path.write_bytes(f"independent-recording-{i}".encode())
    monkeypatch.setattr(enrollment, "normalize", lambda src, dst, **kw:
                        dst.write_bytes(b"normalized-" + src.read_bytes()))
    monkeypatch.setattr(enrollment, "load_pcm", lambda path: np.zeros(16000 * 10))
    return paths


def client_for(handler):
    return httpx.Client(base_url="https://demo.test", transport=httpx.MockTransport(handler))


def test_five_distinct_takes_use_existing_api_and_preserve_receipts(clips, tmp_path):
    posts = []

    def handler(request):
        if request.url.path.endswith("/consent"):
            return httpx.Response(200, json={"state": "granted"})
        if request.method == "GET":
            return httpx.Response(200, json={})
        posts.append(request)
        return httpx.Response(200, json={"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z",
                                         "usable": True, "transcript": "must not enter receipt"})

    output = tmp_path / "receipt.json"
    with client_for(handler) as client:
        report = enrollment.enroll(client, uuid4(), clips, "dee-demo-phone", output)
    assert report["status"] == "five_usable_checks_stored"
    assert len(posts) == 5 and len(report["checks"]) == 5
    for request in posts:
        assert b'name="is_baseline"\r\n\r\ntrue' in request.content
        assert b'name="mode"\r\n\r\nrunner' in request.content
        assert b'name="device_id"\r\n\r\ndee-demo-phone' in request.content
        assert b"Content-Type: audio/wav" in request.content
    assert "transcript" not in output.read_text()


def test_duplicate_recording_never_becomes_five_checks(clips, tmp_path):
    with client_for(lambda request: pytest.fail("must not call API")) as client:
        with pytest.raises(enrollment.EnrollmentError, match="Duplicate audio"):
            enrollment.enroll(client, uuid4(), [clips[0]] * 5, "device", tmp_path / "receipt")


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
            return httpx.Response(200, json={})
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
            return httpx.Response(200, json={})
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
