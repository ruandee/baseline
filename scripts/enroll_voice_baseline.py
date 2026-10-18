"""Enroll five distinct rested recordings through the existing authorized checks API.

Local FFmpeg conversion keeps original files intact and fits WAV uploads below the body limit.
Never automatically retry a POST: a lost response can still mean the check was stored.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx

from patient_memory.speech.audio import load_pcm, normalize


class EnrollmentError(ValueError):
    pass


def validate_url(value):
    parsed = urlsplit(value)
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        pass
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")
            or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))):
        raise EnrollmentError("Use an HTTPS origin, or HTTP on loopback; no credentials/query/path")
    return value.rstrip("/")


def check_response(response):
    if not response.is_success:
        # Do not echo server bodies, transcripts, headers or bearer tokens.
        raise EnrollmentError(f"API returned HTTP {response.status_code}; inspect server state "
                              "before retrying any partially submitted enrollment")
    return response.json()


def enroll(client, patient_id, clips, device_id, output, *, record_consent=False):
    if len(clips) != 5:
        raise EnrollmentError("Supply five distinct rested recordings")
    patient_id = str(UUID(str(patient_id)))
    if not re.fullmatch(r"[\w.-]{1,64}", device_id, re.ASCII):
        raise EnrollmentError("Device ID must use 1-64 ASCII letters, digits, dots, dashes or underscores")
    hashes = [hashlib.sha256(Path(clip).read_bytes()).hexdigest() for clip in clips]
    if len(set(hashes)) != 5:
        raise EnrollmentError("Duplicate audio: do not reuse one recording as multiple baseline checks")
    root = f"/v1/patients/{patient_id}"
    consent = check_response(client.get(root + "/consent"))
    if consent["state"] == "unknown" and record_consent:
        consent = check_response(client.post(root + "/consents", json={
            "scope": "voice_check", "status": "granted", "decided_by": "resident",
            "note": "Volunteer personally granted voice-check consent for the live demo",
        }))
    if consent["state"] != "granted":
        raise EnrollmentError("Granted voice-check consent is required; existing refusal, withdrawal "
                              "or expiry is never overridden by this tool")
    # Also verify scoring/readback access before local decode or audio transmission.
    check_response(client.get(root + "/overview"))
    output = Path(output)
    if output.exists():
        raise EnrollmentError("Receipt file exists; inspect it before submitting anything again")
    with tempfile.TemporaryDirectory(prefix="voice-enrollment-") as scratch:
        normalized, pcm_hashes = [], []
        for index, clip in enumerate(clips):
            wav = Path(scratch) / f"baseline-{index + 1}.wav"
            normalize(Path(clip), wav, max_seconds=31)
            samples = load_pcm(wav)
            duration = len(samples) / 16000
            if not 6 <= duration <= 30 or wav.stat().st_size >= 2_000_000:
                raise EnrollmentError("Every recording must be 6-30 seconds and fit the upload limit")
            normalized.append(wav)
            # WAV containers can retain differing RIFF metadata around identical audio.
            # Fingerprint the same decoded mono/16 kHz samples used for duration, with
            # explicit byte order and format so export tags cannot manufacture takes.
            header = f"f32le:16000:mono:{len(samples)}\0".encode("ascii")
            pcm_hashes.append(hashlib.sha256(
                header + samples.astype("<f4", copy=False).tobytes(order="C")).hexdigest())
        if len(set(pcm_hashes)) != 5:
            raise EnrollmentError("Decoded recordings are duplicates; record five separate takes")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        report = dict(patient_id=patient_id, device_id=device_id, status="incomplete", checks=[])
        with os.fdopen(fd, "w", encoding="utf-8") as receipt:
            def save():
                receipt.seek(0)
                json.dump(report, receipt, indent=2)
                receipt.truncate()
                receipt.flush()

            save()
            for index, wav in enumerate(normalized):
                # Save the pending attempt first. Network failure means its outcome is unknown;
                # keep prior receipts and stop instead of duplicating an accepted check.
                report["pending_clip"] = index + 1
                save()
                with wav.open("rb") as audio:
                    result = check_response(client.post(root + "/checks", data={
                        "mode": "runner", "device_id": device_id, "is_baseline": "true",
                    }, files={"audio": (wav.name, audio, "audio/wav")}))
                report["checks"].append({"check_id": str(UUID(result["check_id"])),
                    "ts": result["ts"], "usable": result["usable"], "input_sha256": hashes[index]})
                report.pop("pending_clip")
                save()
                if not result["usable"]:
                    raise EnrollmentError("An unusable check was stored for audit. Enrollment stopped; "
                                          "inspect receipts and quality before submitting more")
            if len({c["check_id"] for c in report["checks"]}) != 5:
                raise EnrollmentError("Expected five distinct stored check IDs")
            check_response(client.get(root + "/overview"))
            report["status"] = "five_usable_checks_stored"
            save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--patient-id", required=True, type=UUID)
    parser.add_argument("--session-file", required=True, type=Path,
                        help="Private JSON with a care-team 'token', or a private plain JWT file")
    parser.add_argument("--device-id", default="dee-demo-phone")
    parser.add_argument("--clips", required=True, nargs=5, type=Path)
    parser.add_argument("--record-consent", action="store_true",
                        help="Record my personally granted decision only if consent is unknown")
    parser.add_argument("--output", type=Path, default=Path("artifacts/live-baseline") /
                        (datetime.now(UTC).strftime("enrollment-%Y%m%dT%H%M%SZ") + ".json"))
    args = parser.parse_args(argv)
    try:
        base = validate_url(args.base_url)
        raw = args.session_file.read_text(encoding="utf-8").strip()
        token = json.loads(raw)["token"] if raw.startswith("{") else raw
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
            raise EnrollmentError("Session file must contain a JWT; no credentials were printed")
        with httpx.Client(base_url=base, headers={"Authorization": "Bearer " + token},
                          timeout=90, follow_redirects=False, trust_env=False) as client:
            report = enroll(client, args.patient_id, args.clips, args.device_id, args.output,
                            record_consent=args.record_consent)
        print(json.dumps({"status": report["status"], "receipt": str(args.output),
            "live_url": base + "/check?" + urlencode({"mode": "live",
                        "patient": str(args.patient_id), "device": args.device_id})}))
        return 0
    except (EnrollmentError, OSError, httpx.HTTPError, KeyError, ValueError):
        print("Enrollment incomplete. Inspect the private receipt and current server state before "
              "retrying; no automatic POST retry was made. Check consent, five distinct clips, "
              "the endpoint and session credentials.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
