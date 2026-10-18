"""Offline notes workspace controller regressions."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_notes_workspace_controller():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; required in CI")
    root = Path(__file__).resolve().parents[2]
    subprocess.run([node, "--test", "tests/js/notes_workspace.test.js"], cwd=root, check=True,
                   capture_output=True, text=True, timeout=30)
