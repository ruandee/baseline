"""Exercise the editable note preview without any model, browser network or clinical writes."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_note_preview_and_unverified_edits():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "--test", str(root / "tests/js/note_export.test.js")], cwd=root,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
