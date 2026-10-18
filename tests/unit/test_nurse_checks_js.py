"""Nurse readiness, identity selection and stale-read isolation in the buildless UI."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_nurse_voice_workspace():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "--test", "tests/js/nurse_checks.test.js"], cwd=root,
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
