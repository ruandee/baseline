"""KAZE texts, senders, acknowledgement tokens and the public ack page (BL-27, decision 023).
No database and no network: Twilio is exercised only through an httpx mock transport."""
import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from patient_memory.api import create_app
from patient_memory.baseline import ack, sms
from patient_memory.config import Settings

AT = datetime(2026, 10, 18, 1, 41, tzinfo=UTC)  # 9:41 PM in Toronto
SID = "AC" + "0" * 32
APPROVED = "+14165550101"
FORBIDDEN = re.compile(r"drunk|drink|alcohol|drug|intoxic|impair|overdose|diagnos|stroke|seizure",
                       re.I)


def outbound(to=APPROVED, body="text with https://x/ack/live-token", record="text [ack link]"):
    return sms.OutboundSms(uuid4(), uuid4(), uuid4(), uuid4(), 1, 2, to, body, record)


def test_tokens_are_256_bit_url_safe_and_only_their_hash_is_kept():
    tokens = [ack.new_token() for _ in range(200)]
    assert len({t.token for t in tokens}) == 200
    for t in tokens[:20]:
        assert ack.well_formed(t.token) and len(t.token) == 43
        assert t.digest == ack.token_hash(t.token) and len(t.digest) == 32
        assert t.token.encode() not in t.digest


@pytest.mark.parametrize("token", ["", "short", "a" * 42, "a" * 44, "a" * 42 + "=",
                                   "a" * 42 + "/", "a" * 42 + "\n", "../" + "a" * 40])
def test_malformed_tokens_never_reach_the_database(token, monkeypatch):
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: pytest.fail("database touched"))
    assert not ack.well_formed(token)
    assert ack.acknowledge(Settings(), token) == "invalid"


def test_missed_checkin_text_is_the_fixed_wording():
    body, record = sms.render("missed_checkin", 2, "Sam", AT, "America/Toronto", (43.65321, -79.38),
                              "https://demo.example/ack/TOKEN")
    assert body == ("Sam asked us to check on them if they missed a check-in. They missed one at "
                    "9:41 PM. Last location: https://www.openstreetmap.org/?mlat=43.65321&"
                    "mlon=-79.38000. Tap to say you're on it: https://demo.example/ack/TOKEN")
    assert "TOKEN" not in record and "43.65" not in record and "openstreetmap" not in record
    assert "[ack link]" in record and "[location link]" in record


@pytest.mark.parametrize("trigger", sms.TRIGGERS)
@pytest.mark.parametrize("level", [2, 3, 4])
def test_texts_stay_neutral_and_only_level_4_mentions_911(trigger, level):
    body, record = sms.render(trigger, level, "Sam", AT, "America/Toronto", None, "https://x/ack/T")
    for text in (body, record):
        assert not FORBIDDEN.search(text)
        assert ("911" in text) == (level == 4)
        assert "Last location: not shared." in text
    if level == 4:
        assert body.endswith("If you can't reach them, call 911.")


def test_rendering_rejects_non_sms_levels_and_unknown_triggers():
    for trigger, level in [("missed_checkin", 1), ("missed_checkin", 5), ("other", 2)]:
        with pytest.raises(ValueError):
            sms.render(trigger, level, "Sam", AT, "America/Toronto", None, "https://x/ack/T")


def test_display_name_cannot_inject_lines_or_control_characters():
    assert sms.display_name("Sam\n\nCall +1 555\x07") == "Sam Call +1 555"
    assert sms.display_name("‮​") == "Someone"


def test_log_sender_logs_the_stored_copy_not_the_live_link(caplog):
    sender = sms.LogSender(keep=1)
    message = outbound()
    with caplog.at_level(logging.INFO, logger="patient_memory.kaze.sms"):
        assert sms.deliver(sender, message) == "logged"
    assert "live-token" not in caplog.text and "[ack link]" in caplog.text
    assert APPROVED not in caplog.text and "0101" in caplog.text
    assert list(sender.outbox) == [message]
    assert "live-token" not in repr(message) and APPROVED not in repr(message)


def test_a_raising_or_misbehaving_sender_is_recorded_as_failed(caplog):
    class Broken:
        name = "broken"

        def send(self, message):
            raise RuntimeError("live-token secret phone")

    class Liar:
        name = "liar"

        def send(self, message):
            return "delivered"

    assert sms.deliver(Broken(), outbound()) == "failed"
    assert sms.deliver(Liar(), outbound()) == "failed"
    assert "live-token" not in caplog.text and "secret phone" not in caplog.text


def twilio(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return sms.TwilioSender(SID, "secret-auth", "+14165550199", frozenset({APPROVED}), client)


def test_twilio_posts_one_form_request_with_basic_auth():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"sid": "SM" + "a" * 32, "status": "queued", "to": APPROVED})

    assert twilio(handler).send(outbound()) == "sent"
    (request,) = seen
    assert str(request.url) == f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    assert request.headers["authorization"].startswith("Basic ")
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form == {"To": APPROVED, "From": "+14165550199",
                    "Body": "text with https://x/ack/live-token"}


def test_twilio_messaging_service_sender():
    seen = []
    sender = sms.TwilioSender(SID, "t", "MG" + "a" * 32, frozenset({APPROVED}),
                              httpx.Client(transport=httpx.MockTransport(
                                  lambda r: seen.append(r) or httpx.Response(201, json={"sid": "SM" + "a" * 32, "status": "accepted"}))))
    assert sender.send(outbound()) == "sent"
    assert "MessagingServiceSid" in dict(httpx.QueryParams(seen[0].content.decode()))


def test_twilio_never_texts_a_number_off_the_allowlist():
    def handler(request):
        pytest.fail("network call to an unapproved number")

    assert twilio(handler).send(outbound(to="+14165550102")) == "failed"


@pytest.mark.parametrize("response", [httpx.Response(400, json={"message": "unverified"}),
                                      httpx.Response(500), httpx.Response(302)])
def test_twilio_rejections_are_failed_and_not_logged_verbatim(response, caplog):
    with caplog.at_level(logging.INFO, logger="patient_memory.kaze.sms"):
        assert twilio(lambda r: response).send(outbound()) == "failed"
    assert "unverified" not in caplog.text and "secret-auth" not in caplog.text


def test_twilio_timeouts_remain_unknown_without_retry():
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    assert twilio(handler).send(outbound()) == "pending"
    assert "secret-auth" not in repr(twilio(handler))


def test_default_settings_use_the_log_sender():
    cfg = Settings()
    assert cfg.sms_provider == "log" and isinstance(sms.sender_for(cfg), sms.LogSender)


def twilio_settings(**overrides):
    fields = {"sms_provider": "twilio", "twilio_sid": SID, "twilio_token": "t",
              "twilio_from": "+14165550199", "sms_allowed_recipients": APPROVED,
              "ack_base_url": "https://demo.example"} | overrides
    return Settings(**fields)


def test_twilio_is_selected_only_when_fully_configured():
    sender = sms.sender_for(twilio_settings())
    assert isinstance(sender, sms.TwilioSender) and sender.allowed == {APPROVED}
    for bad in [{"twilio_sid": "AC123"}, {"twilio_token": ""}, {"twilio_from": "4165550199"},
                {"sms_allowed_recipients": ""}, {"sms_allowed_recipients": "416-555-0101"},
                {"ack_base_url": "http://127.0.0.1:8000"}]:
        with pytest.raises(ValidationError):
            twilio_settings(**bad)


@pytest.mark.parametrize("url", ["http://demo.example", "https://u:p@demo.example",
                                 "https://demo.example/?x=1", "ftp://demo.example", "not a url"])
def test_ack_base_url_must_be_https_or_loopback(url):
    with pytest.raises(ValidationError):
        Settings(ack_base_url=url)
    with pytest.raises(ValidationError):
        Settings(sms_provider="carrier-pigeon")


def test_ack_links_and_expiry_bounds():
    assert ack.ack_link("https://demo.example/", "T") == "https://demo.example/ack/T"
    with pytest.raises(ValidationError):
        Settings(ack_ttl_min=2)
    assert Settings().ack_ttl_min == 360


@pytest.fixture
def public(monkeypatch):
    calls = []

    def fake(cfg, token):
        calls.append(token)
        return results.pop(0)

    results = []
    monkeypatch.setattr(ack, "acknowledge", fake)
    return TestClient(create_app(Settings(), objects=object())), calls, results


def test_get_records_acknowledgement_per_contract(public):
    client, calls, results = public
    token = ack.new_token().token
    results.append("acknowledged")
    response = client.get(f"/ack/{token}")
    assert response.status_code == 200 and calls == [token]
    assert "following up" in response.text
    for header, value in ack.HEADERS.items():
        assert response.headers[header] == value
    assert token not in response.text


@pytest.mark.parametrize("result,status,phrase", [("acknowledged", 200, "following up"),
                                                  ("recorded", 200, "recorded"),
                                                  ("invalid", 404, "no longer active")])
def test_submitting_reports_only_the_outcome(public, result, status, phrase):
    client, calls, results = public
    token = ack.new_token().token
    results.append(result)
    # A browser form with no fields posts an empty urlencoded body.
    response = client.post(f"/ack/{token}",
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == status and phrase in response.text
    assert calls == [token] and response.headers["Cache-Control"] == "no-store"
    assert "<form" not in response.text and token not in response.text


def test_malformed_links_are_invalid_without_a_lookup(public):
    client, calls, _ = public
    assert client.get("/ack/not-a-token").status_code == 404
    assert client.post("/ack/not-a-token").status_code == 404
    assert calls == []


def test_a_database_outage_asks_the_contact_to_retry(public, monkeypatch):
    client, _, _ = public

    def down(cfg, token):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(ack, "acknowledge", down)
    response = client.post(f"/ack/{ack.new_token().token}")
    assert response.status_code == 503 and "<form" in response.text


def test_log_sender_keeps_no_live_tokens_by_default():
    sender = sms.LogSender()
    assert sender.send(outbound()) == "logged"
    assert list(sender.outbox) == []


@pytest.mark.parametrize("response", [httpx.Response(201), httpx.Response(201, json={}),
                                      httpx.Response(201, json={"sid": "SM1", "status": "queued"})])
def test_twilio_unconfirmed_success_is_pending(response):
    assert twilio(lambda _: response).send(outbound()) == "pending"


@pytest.fixture
def hosted_ack(monkeypatch):
    from patient_memory.auth import Identity, synthetic_token
    from scripts.frontend import workspace_app

    cfg = Settings(jwt_secret="deployment-only-test-secret-32-characters")
    reader = Identity(uuid4(), uuid4())
    calls = []
    monkeypatch.setattr(ack, "acknowledge", lambda cfg, token: calls.append(token) or "acknowledged")
    app = workspace_app(cfg, reader, [], extra_hosts=("demo.example",),
                        demo_token=synthetic_token(reader, cfg))
    return TestClient(app, base_url="https://demo.example", client=("192.0.2.1", 1234)), calls


def test_hosted_ack_accepts_external_document_navigation_only(hosted_ack):
    client, calls = hosted_ack
    token = ack.new_token().token
    navigation = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate",
                  "Sec-Fetch-Dest": "document"}
    response = client.get(f"/ack/{token}", headers=navigation)
    assert response.status_code == 200 and calls == [token]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Content-Security-Policy"] == ack.HEADERS["Content-Security-Policy"]
    for headers in [{**navigation, "Host": "evil.example"},
                    {**navigation, "Origin": "https://evil.example"},
                    {**navigation, "Sec-Fetch-Mode": "cors"},
                    {**navigation, "Sec-Fetch-Dest": "image"},
                    {"Sec-Fetch-Site": "cross-site"}]:
        assert client.get(f"/ack/{token}", headers=headers).status_code == 403
    assert client.post(f"/ack/{token}", headers=navigation).status_code == 403
    assert client.get("/ack/not-a-token", headers=navigation).status_code == 403
    assert client.get("/demo/session", headers={**navigation, "X-PM-Demo": "1"}).status_code == 403
    assert client.get("/v1/watchlist", headers=navigation).status_code == 403
    assert calls == [token]
