import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from patient_memory.domain import MotionInput
from patient_memory.motion import quality

ROOT = Path(__file__).resolve().parents[2]


def payload(**changes):
    return {"device_id": "synthetic-motion-phone", "features": {
        "sit_to_stand_s": 1.2, "trunk_sway": .04, "step_cadence_spm": 60},
        "quality": {"duration_s": 10, "total_frames": 100, "confident_frames": 80}, **changes}


def test_motion_quality_boundary_and_unknown_are_explicit():
    assert quality(MotionInput(**payload()))["reasons"] == []
    below = payload(quality={"duration_s": 10, "total_frames": 100, "confident_frames": 79})
    assert quality(MotionInput(**below))["reasons"] == ["landmarks_unreliable"]
    unknown = payload(features={})
    assert quality(MotionInput(**unknown))["reasons"] == [
        "rise_incomplete", "shoulders_unavailable", "steps_incomplete"]


@pytest.mark.parametrize("changes", [
    {"video": "forbidden"}, {"landmarks": []}, {"features": {"trunk_sway": float("nan")}},
    {"quality": {"duration_s": 10, "total_frames": 5, "confident_frames": 6}},
    {"features": {"sit_to_stand_s": 9},
     "quality": {"duration_s": 8, "total_frames": 100, "confident_frames": 100}},
])
def test_media_nonfinite_and_inconsistent_motion_payloads_are_rejected(changes):
    with pytest.raises(ValidationError):
        MotionInput(**payload(**changes))


def test_pinned_local_pose_assets_match_the_committed_integrity_manifest():
    vendor = ROOT / "frontend/vendor/mediapipe"
    manifest = json.loads((vendor / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.1.1"
    assert manifest["tarball_integrity"].startswith("sha512-")
    for name, expected in manifest["files"].items():
        data = (vendor / name).read_bytes()
        assert len(data) == expected["bytes"]
        assert hashlib.sha256(data).hexdigest() == expected["sha256"]
    worker = (ROOT / "frontend/motion-worker.js").read_text(encoding="utf-8")
    assert "https://" not in worker and "http://" not in worker
    assert "outputSegmentationMasks: false" in worker
    assert "forVisionTasks('/assets/vendor/mediapipe/wasm', true)" in worker


@pytest.mark.skipif(not shutil.which("node"), reason="Node is required for local pose logic tests")
def test_motion_geometry_and_camera_lifecycle_use_synthetic_landmarks_and_mock_devices():
    result = subprocess.run(["node", "--test", "tests/js/motion.test.js",
                             "tests/js/motion_page.test.js"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
