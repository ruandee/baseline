import json
import os
import stat
from email.parser import BytesParser
from email.policy import default
from uuid import uuid4

import httpx
import pytest

from scripts import measure_checks_latency as latency

PROFILE_VERSION = str(uuid4())
PATIENT = uuid4()
OPERATOR = dict(release_sha="6e4d7d9", whisper_model="base", host="test-vm, 4 vCPU / 16 GB")
TOKEN = "aaa.bbb.ccc"


def fake_clock(durations_ms):
    """Each POST reads the clock exactly twice: before and after."""
    ticks, cursor = [], 100.0
    for ms in durations_ms:
        ticks += [cursor, cursor + ms / 1000]
        cursor += ms / 1000 + 1
    values = iter(ticks)
    return lambda: next(values)


def result_body(usable=True, **extra):
    return {"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z", "usable": usable,
            "timings_ms": {"normalize": 40, "asr": 900, "engine": 12}, **extra}


def preflight(request, consent="granted", profile_state="ready"):
    path = request.url.path
    if path.endswith("/consent"):
        return httpx.Response(200, json={"state": consent})
    if path.endswith("/check-profile"):
        return httpx.Response(200, json={"state": profile_state, "version": PROFILE_VERSION,
                                         "protocol_locale": "en"})
    return httpx.Response(200, json={"patient_id": str(PATIENT), "display_name": "Synthetic Probe"})


def client_for(handler, base_url="https://demo.test"):
    return httpx.Client(base_url=base_url, transport=httpx.MockTransport(handler))


def fields_of(request):
    body = (f"Content-Type: {request.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
            + request.content)
    message = BytesParser(policy=default).parsebytes(body)
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.iter_parts()}, {
        part.get_param("name", header="content-disposition"): part.get_content_type()
        for part in message.iter_parts()}


@pytest.fixture
def clips(tmp_path):
    paths = [tmp_path / "a.wav", tmp_path / "b.webm"]
    paths[0].write_bytes(b"RIFF-clip-a")
    paths[1].write_bytes(b"webm-clip-b")
    return paths


def run(clips, tmp_path, handler, durations, *, samples=3, warmup=1, base_url="https://demo.test",
        output=None):
    output = output or tmp_path / "out" / "latency.json"
    with client_for(handler, base_url) as client:
        return latency.measure(client, PATIENT, clips, output, operator=OPERATOR, samples=samples,
                               warmup=warmup, device_id="probe", mode="runner",
                               clock=fake_clock(durations), base_url=base_url, tool_sha="abc1234")


def ok_handler(posts=None):
    def handler(request):
        if request.method == "GET":
            return preflight(request)
        if posts is not None:
            posts.append(request)
        return httpx.Response(200, json=result_body())
    return handler


def test_warmup_excluded_and_nearest_rank_percentiles(clips, tmp_path):
    # Warmup 9000 ms must not enter the stats; measured: 1000..4000 ms plus one 5500 ms.
    durations = [9000, 2000, 1000, 4000, 3000, 5500]
    report = run(clips, tmp_path, ok_handler(), durations, samples=5, warmup=1)
    stats = report["stats"]
    assert stats["n"] == 5 and report["warmup"] == 1
    assert stats["wall_ms"] == {"p50": 3000, "p95": 5500, "max": 5500}
    assert stats["percentile_method"] == "nearest-rank"
    assert [s["warmup"] for s in report["samples"]] == [True] + [False] * 5
    assert report["target_p95_ms"] == 5000 and report["status"] == "complete"
    assert report["meets_target_p95"] is None  # 5 samples cannot support a p95 verdict


def test_p95_nearest_rank_with_twenty_samples_is_not_the_max(clips, tmp_path):
    durations = [100 * i for i in range(1, 21)]  # 100..2000
    report = run(clips, tmp_path, ok_handler(), durations, samples=20, warmup=0)
    assert report["stats"]["wall_ms"] == {"p50": 1000, "p95": 1900, "max": 2000}
    assert report["meets_target_p95"] is True
    assert "warning" not in report["stats"]


def test_few_samples_warn_that_p95_is_effectively_the_max(clips, tmp_path):
    report = run(clips, tmp_path, ok_handler(), [1000, 1100, 1200], samples=3, warmup=0)
    assert "effectively the max" in report["stats"]["warning"]


def test_unusable_samples_reported_and_excluded_from_usable_p95(clips, tmp_path):
    bodies = iter([result_body(), result_body(usable=False), result_body()])

    def handler(request):
        if request.method == "GET":
            return preflight(request)
        return httpx.Response(200, json=next(bodies))

    report = run(clips, tmp_path, handler, [1000, 9000, 2000], samples=3, warmup=0)
    assert report["stats"]["usable"] == 2 and report["stats"]["unusable"] == 1
    assert report["stats"]["usable_wall_ms_p95"] == 2000
    assert report["stats"]["wall_ms"]["max"] == 9000


def test_step_timings_are_summarised_as_diagnostics(clips, tmp_path):
    report = run(clips, tmp_path, ok_handler(), [1000, 1100, 1200], samples=3, warmup=0)
    assert report["stats"]["steps_ms"]["asr"] == {"p50": 900, "p95": 900}


def test_multipart_fields_and_clips_sent_unchanged_round_robin(clips, tmp_path):
    posts = []
    run(clips, tmp_path, ok_handler(posts), [1000] * 3, samples=3, warmup=0)
    assert len(posts) == 3
    first, kinds = fields_of(posts[0])
    assert first["profile_version"].decode() == PROFILE_VERSION
    assert first["protocol_locale"] == b"en" and first["mode"] == b"runner"
    assert first["is_baseline"] == b"false" and first["device_id"] == b"probe"
    assert first["audio"] == b"RIFF-clip-a" and kinds["audio"] == "audio/wav"
    second, kinds = fields_of(posts[1])
    assert second["audio"] == b"webm-clip-b" and kinds["audio"] == "audio/webm"
    assert fields_of(posts[2])[0]["audio"] == b"RIFF-clip-a"


@pytest.mark.parametrize("damage", ["withdrawn", "unknown", "not_ready"])
def test_unfit_consent_or_profile_means_no_post_and_no_file(clips, tmp_path, damage):
    def handler(request):
        assert request.method == "GET", "must not upload after a failed preflight"
        if damage == "not_ready":
            return preflight(request, profile_state="unconfigured")
        return preflight(request, consent=damage)

    output = tmp_path / "out" / "latency.json"
    with pytest.raises(latency.MeasurementError):
        run(clips, tmp_path, handler, [], output=output)
    assert not output.exists()


def test_failure_stops_after_one_post_without_retry_and_keeps_partial(clips, tmp_path):
    posts = []

    def handler(request):
        if request.method == "GET":
            return preflight(request)
        posts.append(request)
        if len(posts) == 2:
            return httpx.Response(503, json={"error": {"code": "dependency_unavailable"}})
        return httpx.Response(200, json=result_body())

    output = tmp_path / "out" / "latency.json"
    with pytest.raises(latency.MeasurementError, match="503"):
        run(clips, tmp_path, handler, [1000, 1000], samples=3, warmup=0, output=output)
    assert len(posts) == 2
    saved = json.loads(output.read_text())
    assert saved["status"] == "incomplete"
    assert len(saved["samples"]) == 1 and saved["failure"]["http_status"] == 503


def test_network_error_is_recorded_not_retried(clips, tmp_path):
    posts = []

    def handler(request):
        if request.method == "GET":
            return preflight(request)
        posts.append(request)
        raise httpx.ReadTimeout("response lost")

    output = tmp_path / "out" / "latency.json"
    with pytest.raises(latency.MeasurementError, match="outcome unknown"):
        run(clips, tmp_path, handler, [1000], samples=3, warmup=0, output=output)
    assert len(posts) == 1
    assert json.loads(output.read_text())["failure"]["kind"] == "network"


def test_psw_receipt_without_timings_is_rejected(clips, tmp_path):
    def handler(request):
        if request.method == "GET":
            return preflight(request)
        return httpx.Response(200, json={"check_id": str(uuid4()), "ts": "2026-10-18T12:00:00Z",
                                         "usable": True})

    with pytest.raises(latency.MeasurementError, match="care-team"):
        run(clips, tmp_path, handler, [1000], samples=3, warmup=0)


def test_oversized_clip_refused_before_any_request(tmp_path):
    big = tmp_path / "big.wav"
    big.write_bytes(b"0" * 2_000_000)

    def handler(request):
        pytest.fail("no request before clip validation")

    with pytest.raises(latency.MeasurementError, match="2 MB"):
        run([big], tmp_path, handler, [])


def test_unknown_clip_type_refused(tmp_path):
    odd = tmp_path / "clip.txt"
    odd.write_bytes(b"x")
    with pytest.raises(latency.MeasurementError, match="type"):
        latency.load_clips([odd])


def test_operator_declared_fields_are_separate_from_tool_sha(clips, tmp_path):
    report = run(clips, tmp_path, ok_handler(), [1000] * 3, samples=3, warmup=0)
    assert report["operator_declared"] == OPERATOR
    assert report["tool_git_sha"] == "abc1234"
    assert report["not_acceptance"] is False


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8010", "http://127.0.0.2:8010",
                                      "http://localhost:8010", "http://[::1]:8010"])
def test_loopback_runs_are_labelled_not_acceptance_and_never_give_a_verdict(
        clips, tmp_path, base_url):
    report = run(clips, tmp_path, ok_handler(), [1000] * 20, samples=20, warmup=0,
                 base_url=base_url)
    assert report["not_acceptance"] is True and report["meets_target_p95"] is None


def test_verdict_is_given_only_for_a_complete_hosted_run_with_enough_samples(clips, tmp_path):
    hosted = run(clips, tmp_path, ok_handler(), [4900] * 20, samples=20, warmup=0)
    assert hosted["meets_target_p95"] is True
    slow = run(clips, tmp_path, ok_handler(), [5000] * 20, samples=20, warmup=0,
               output=tmp_path / "slow.json")
    assert slow["meets_target_p95"] is False


def test_incomplete_run_never_gives_a_verdict(clips, tmp_path):
    posts = []

    def handler(request):
        if request.method == "GET":
            return preflight(request)
        posts.append(request)
        if len(posts) == 4:
            return httpx.Response(500)
        return httpx.Response(200, json=result_body())

    output = tmp_path / "latency.json"
    with pytest.raises(latency.MeasurementError):
        run(clips, tmp_path, handler, [100] * 4, samples=20, warmup=0, output=output)
    assert json.loads(output.read_text())["meets_target_p95"] is None


def test_warmup_below_clip_count_is_warned(clips, tmp_path):
    report = run(clips, tmp_path, ok_handler(), [1000] * 4, samples=3, warmup=1)
    assert "below the clip count" in report["warnings"][0]
    assert run(clips, tmp_path, ok_handler(), [1000] * 4, samples=2, warmup=2,
               output=tmp_path / "ok.json")["warnings"] == []


@pytest.mark.parametrize("body", [b"<html>not json</html>", b"[1, 2]",
                                  json.dumps({"timings_ms": {"asr": 1}, "usable": True}).encode(),
                                  json.dumps({**result_body(), "check_id": "nope"}).encode()])
def test_malformed_200_is_recorded_as_a_failure_with_no_retry(clips, tmp_path, body):
    posts = []

    def handler(request):
        if request.method == "GET":
            return preflight(request)
        posts.append(request)
        return httpx.Response(200, content=body)

    output = tmp_path / "latency.json"
    with pytest.raises(latency.MeasurementError):
        run(clips, tmp_path, handler, [1000], samples=3, warmup=0, output=output)
    assert len(posts) == 1
    assert json.loads(output.read_text())["status"] == "incomplete"


def test_interrupt_during_post_is_recorded_not_lost(clips, tmp_path):
    def handler(request):
        if request.method == "GET":
            return preflight(request)
        raise KeyboardInterrupt

    output = tmp_path / "latency.json"
    with pytest.raises(latency.MeasurementError, match="outcome unknown"):
        run(clips, tmp_path, handler, [1000], samples=3, warmup=0, output=output)
    assert json.loads(output.read_text())["failure"]["error"] == "KeyboardInterrupt"


def test_existing_result_file_is_refused_before_any_request(clips, tmp_path):
    output = tmp_path / "latency.json"
    output.write_text("{}")

    def handler(request):
        pytest.fail("no request before the output file is checked")

    with pytest.raises(latency.MeasurementError, match="exists"):
        run(clips, tmp_path, handler, [], output=output)


def test_psw_token_is_stopped_at_preflight_without_upload(clips, tmp_path):
    def handler(request):
        assert request.method == "GET", "must not upload when care-team readback is denied"
        if request.url.path.endswith("/overview"):
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return preflight(request)

    with pytest.raises(latency.MeasurementError, match="HTTP 404"):
        run(clips, tmp_path, handler, [])


def test_result_file_is_private_and_never_overwritten(clips, tmp_path):
    output = tmp_path / "out" / "latency.json"
    run(clips, tmp_path, ok_handler(), [1000] * 3, samples=3, warmup=0, output=output)
    assert stat.S_IMODE(os.stat(output).st_mode) == 0o600
    with pytest.raises(latency.MeasurementError, match="exists"):
        run(clips, tmp_path, ok_handler(), [1000] * 3, samples=3, warmup=0, output=output)


@pytest.mark.parametrize("url", ["http://demo.test", "https://user:secret@demo.test",
                                 "https://demo.test?token=secret", "https://demo.test/v1"])
def test_credentials_only_go_to_explicit_secure_origin(url):
    with pytest.raises(latency.MeasurementError):
        latency.validate_url(url)


def test_main_never_prints_or_stores_the_token(clips, tmp_path, monkeypatch, capsys):
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"token": TOKEN}))
    output = tmp_path / "latency.json"
    seen_auth = []

    def handler(request):
        seen_auth.append(request.headers.get("authorization"))
        if request.method == "GET":
            return preflight(request)
        return httpx.Response(200, json=result_body())

    real_client = httpx.Client
    monkeypatch.setattr(latency.httpx, "Client", lambda **kw: real_client(
        **{**kw, "transport": httpx.MockTransport(handler)}))
    code = latency.main([
        "--base-url", "https://demo.test", "--session-file", str(session),
        "--patient-id", str(PATIENT), "--clips", *map(str, clips),
        "--release-sha", "6e4d7d9", "--whisper-model", "base", "--host", "test-vm",
        "--samples", "3", "--output", str(output)])
    printed = capsys.readouterr()
    assert code == 0
    assert set(seen_auth) == {"Bearer " + TOKEN}
    assert TOKEN not in printed.out + printed.err and TOKEN not in output.read_text()
    summary = json.loads(printed.out.strip().splitlines()[-1])
    assert summary["status"] == "complete" and summary["result"] == str(output)
    assert summary["operator_declared"] == dict(release_sha="6e4d7d9", whisper_model="base",
                                                host="test-vm")
    assert summary["n"] == 3 and summary["meets_target_p95"] is None  # 3 samples: no verdict
    assert json.loads(output.read_text())["warmup"] == 2  # default: one warmup per clip, min 2


def test_main_failure_prints_no_server_body_or_token(clips, tmp_path, monkeypatch, capsys):
    session = tmp_path / "session.json"
    session.write_text(TOKEN)

    def handler(request):
        if request.method == "GET":
            return preflight(request)
        return httpx.Response(500, text="secret transcript " + TOKEN)

    real_client = httpx.Client
    monkeypatch.setattr(latency.httpx, "Client", lambda **kw: real_client(
        **{**kw, "transport": httpx.MockTransport(handler)}))
    code = latency.main([
        "--base-url", "https://demo.test", "--session-file", str(session),
        "--patient-id", str(PATIENT), "--clips", str(clips[0]),
        "--release-sha", "6e4d7d9", "--whisper-model", "base", "--host", "test-vm",
        "--samples", "3", "--warmup", "0", "--output", str(tmp_path / "latency.json")])
    printed = capsys.readouterr()
    assert code == 1
    assert "secret transcript" not in printed.out + printed.err
    assert TOKEN not in printed.out + printed.err
