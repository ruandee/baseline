"""Measure upload-to-result latency of POST /v1/patients/{id}/checks through the HTTP API.

WARNING: every POST stores an immutable, scored check. Run against a dedicated synthetic patient
outside the demo storyline, or only right before a hosted reset; never against a judged resident.

p95 is client wall-clock around the POST (upload, decode, ASR, scoring, response). The server's
`timings_ms` are a per-step diagnostic only. The release SHA, Whisper model and host are declared
by the operator because no endpoint exposes them. A run is evidence for the BL-07 gate (#9), not
its closure, and loopback runs are labelled not_acceptance. Never retries a POST: a lost response
can still mean the check was stored.
"""
import argparse
import ipaddress
import json
import math
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx

from scripts.enroll_voice_baseline import EnrollmentError, load_token, validate_url

MeasurementError = EnrollmentError  # validate_url and load_token raise it too
MAX_CLIP_BYTES = 2_000_000  # the API body limit for /checks is 2 MB
MIN_SAMPLES = 20
TARGET_P95_MS = 5000
CONTENT_TYPES = {".wav": "audio/wav", ".webm": "audio/webm", ".mp4": "audio/mp4",
                 ".m4a": "audio/mp4", ".ogg": "audio/ogg"}


def is_loopback(host):
    try:
        return host == "localhost" or ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def nearest_rank(values, pct):
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)), 1) - 1]


def load_clips(paths):
    clips = []
    for path in map(Path, paths):
        content_type = CONTENT_TYPES.get(path.suffix.lower())
        if content_type is None:
            raise MeasurementError(f"Unsupported clip type {path.suffix!r}; use "
                                   + ", ".join(CONTENT_TYPES))
        data = path.read_bytes()
        if len(data) >= MAX_CLIP_BYTES:
            raise MeasurementError("Every clip must be under the 2 MB upload limit")
        clips.append((path.name, data, content_type))
    if not clips:
        raise MeasurementError("Supply at least one clip")
    return clips


def summarize(samples):
    measured = [s for s in samples if not s["warmup"]]
    walls = [s["wall_ms"] for s in measured]
    stats = dict(n=len(measured), percentile_method="nearest-rank")
    if not measured:
        return stats
    usable = [s["wall_ms"] for s in measured if s["usable"]]
    stats.update(
        wall_ms=dict(p50=nearest_rank(walls, 50), p95=nearest_rank(walls, 95), max=max(walls)),
        usable=len(usable), unusable=len(measured) - len(usable),
        usable_wall_ms_p95=nearest_rank(usable, 95) if usable else None,
        steps_ms={step: dict(p50=nearest_rank(v, 50), p95=nearest_rank(v, 95))
                  for step in sorted({k for s in measured for k in s["timings_ms"]})
                  for v in [[s["timings_ms"][step] for s in measured if step in s["timings_ms"]]]})
    warnings = []
    if len(measured) < MIN_SAMPLES:
        warnings.append(f"Only {len(measured)} measured samples (<{MIN_SAMPLES}): "
                        "p95 is effectively the max")
    if stats["unusable"]:
        warnings.append(f"{stats['unusable']} unusable clips skip scoring and run faster; "
                        "see usable_wall_ms_p95")
    if warnings:
        stats["warning"] = "; ".join(warnings)
    return stats


def meets_target(report):
    """Null unless the run could count toward the gate: complete, not loopback, enough samples."""
    stats = report["stats"]
    if (report["status"] != "complete" or report["not_acceptance"]
            or stats["n"] < MIN_SAMPLES or not stats.get("usable")):
        return None
    return (stats["wall_ms"]["p95"] < TARGET_P95_MS
            and stats["usable_wall_ms_p95"] < TARGET_P95_MS)


def get_json(client, path):
    response = client.get(path)
    if not response.is_success:
        # Do not echo server bodies, transcripts, headers or bearer tokens.
        raise MeasurementError(f"Preflight GET {path.rsplit('/', 1)[-1]} returned HTTP "
                               f"{response.status_code}; nothing was uploaded")
    return response.json()


def measure(client, patient_id, clip_paths, output, *, operator, samples=MIN_SAMPLES, warmup=2,
            device_id="latency-probe", mode="runner", clock=time.perf_counter, base_url="",
            tool_sha=""):
    patient_id = str(UUID(str(patient_id)))
    if samples < 1 or warmup < 0:
        raise MeasurementError("Need at least one measured sample and a non-negative warmup")
    clips = load_clips(clip_paths)
    output = Path(output)
    if output.exists():
        raise MeasurementError("Result file exists; inspect it before measuring again")
    root = f"/v1/patients/{patient_id}"
    if get_json(client, root + "/consent").get("state") != "granted":
        raise MeasurementError("Granted voice-check consent is required; this tool never "
                               "records or overrides consent")
    profile = get_json(client, root + "/check-profile")
    try:
        profile_version = str(UUID(str(profile["version"])))
    except (KeyError, ValueError, TypeError) as exc:
        raise MeasurementError("A ready check profile with a version is required") from exc
    if profile.get("state") != "ready":
        raise MeasurementError("A ready check profile is required before measuring")
    protocol_locale = profile.get("protocol_locale") or "en"
    overview = get_json(client, root + "/overview")  # care-team readback proves the token role
    output.parent.mkdir(parents=True, exist_ok=True)
    host = httpx.URL(base_url).host if base_url else ""
    report = dict(
        status="incomplete", not_acceptance=is_loopback(host),
        warnings=([f"Warmup ({warmup}) is below the clip count ({len(clips)}): a clip's first, "
                   "cold-format upload may be measured"] if warmup < len(clips) else []),
        acceptance="not recorded by this tool; post the result in #22/#9",
        operator_declared=dict(operator), tool_git_sha=tool_sha, base_url=base_url,
        patient_id=patient_id, resident=overview.get("display_name"),
        started=datetime.now(UTC).isoformat(), warmup=warmup, requested_samples=samples,
        target_p95_ms=TARGET_P95_MS, samples=[])
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        def save():
            report["stats"] = summarize(report["samples"])
            report["meets_target_p95"] = meets_target(report)
            out.seek(0)
            json.dump(report, out, indent=2)
            out.truncate()
            out.flush()

        def fail(message, **failure):
            report["failure"] = failure
            report["ended"] = datetime.now(UTC).isoformat()
            save()
            raise MeasurementError(message)

        save()
        for index in range(warmup + samples):
            name, data, content_type = clips[index % len(clips)]
            started = clock()
            try:
                response = client.post(root + "/checks", data={
                    "mode": mode, "device_id": device_id, "is_baseline": "false",
                    "profile_version": profile_version, "protocol_locale": protocol_locale,
                }, files={"audio": (name, data, content_type)})
            except (httpx.HTTPError, KeyboardInterrupt) as exc:
                fail("Network error or interrupt on POST; outcome unknown, the check may be "
                     "stored. Inspect server state before re-running; no retry was made",
                     kind="network", error=type(exc).__name__, sample=index + 1)
            wall_ms = round((clock() - started) * 1000)
            if not response.is_success:
                fail(f"POST /checks returned HTTP {response.status_code}; no retry was made",
                     kind="http", http_status=response.status_code, sample=index + 1)
            try:
                body = response.json()
                receipt_only = "timings_ms" not in body
            except (ValueError, TypeError):
                body, receipt_only = None, False  # not JSON: reported as malformed below
            if receipt_only:
                fail("Response had no timings_ms (a PSW receipt?); use a care-team token",
                     kind="no_timings", sample=index + 1)
            try:
                sample = dict(
                    n=index + 1, warmup=index < warmup, clip=index % len(clips), wall_ms=wall_ms,
                    check_id=str(UUID(body["check_id"])), usable=bool(body["usable"]),
                    timings_ms={k: int(v) for k, v in body["timings_ms"].items()})
            except (KeyError, ValueError, TypeError, AttributeError):
                fail("Unexpected 200 response shape; the check may be stored. Inspect server "
                     "state before re-running", kind="malformed", sample=index + 1)
            report["samples"].append(sample)
            save()
        report["status"] = "complete"
        report["ended"] = datetime.now(UTC).isoformat()
        save()
    return report


def local_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--patient-id", required=True, type=UUID,
                        help="A dedicated synthetic patient: every POST stores a scored check")
    parser.add_argument("--session-file", required=True, type=Path,
                        help="Private JSON with a care-team 'token', or a private plain JWT file")
    parser.add_argument("--clips", required=True, nargs="+", type=Path,
                        help="Counting clips (wav/webm/mp4/m4a/ogg, under 2 MB), uploaded as-is "
                             "and used round-robin")
    parser.add_argument("--release-sha", required=True, help="Deployed commit (operator-declared)")
    parser.add_argument("--whisper-model", required=True,
                        help="PM_WHISPER_MODEL on the host (operator-declared)")
    parser.add_argument("--host", required=True,
                        help="Host and resources, e.g. 'baseline.deeruan.com, GCE 4 vCPU/16 GB'")
    parser.add_argument("--samples", type=int, default=MIN_SAMPLES, help="Measured POSTs")
    parser.add_argument("--warmup", type=int, default=None,
                        help="Initial POSTs excluded from stats (default: 2, or one per clip "
                             "if more, so every clip format is warm before timing)")
    parser.add_argument("--device-id", default="latency-probe")
    parser.add_argument("--mode", default="runner", choices=["runner", "resident"])
    parser.add_argument("--output", type=Path, default=Path("artifacts/latency") /
                        (datetime.now(UTC).strftime("checks-latency-%Y%m%dT%H%M%SZ") + ".json"))
    args = parser.parse_args(argv)
    try:
        base = validate_url(args.base_url)
        token = load_token(args.session_file)
        with httpx.Client(base_url=base, headers={"Authorization": "Bearer " + token},
                          timeout=90, follow_redirects=False, trust_env=False) as client:
            report = measure(
                client, args.patient_id, args.clips, args.output,
                operator=dict(release_sha=args.release_sha, whisper_model=args.whisper_model,
                              host=args.host),
                samples=args.samples,
                warmup=max(2, len(args.clips)) if args.warmup is None else args.warmup,
                device_id=args.device_id, mode=args.mode, base_url=base, tool_sha=local_sha())
        stats = report["stats"]
        print(json.dumps(dict(
            status=report["status"], result=str(args.output), n=stats["n"],
            wall_ms=stats["wall_ms"], usable_wall_ms_p95=stats["usable_wall_ms_p95"],
            meets_target_p95=report["meets_target_p95"], not_acceptance=report["not_acceptance"],
            operator_declared=report["operator_declared"], tool_git_sha=report["tool_git_sha"],
            base_url=base, warnings=report["warnings"] + ([stats["warning"]]
                                                          if "warning" in stats else []))))
        return 0
    except (MeasurementError, OSError, httpx.HTTPError, KeyError, ValueError) as exc:
        message = str(exc) if isinstance(exc, MeasurementError) else type(exc).__name__
        print(f"Measurement incomplete: {message}. Any partial result is in {args.output}; "
              "check server state before re-running.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
