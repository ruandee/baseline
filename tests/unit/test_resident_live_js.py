"""Exercise the actual resident route, also reusable with API-captured payloads."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_resident_js(fixture=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if fixture:
        env["RESIDENT_LIVE_FIXTURE"] = str(fixture)
    result = subprocess.run([node, "--test", "tests/js/resident_live.test.js"], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_live_resident_route():
    run_resident_js()
