import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required")
def test_signal_panel_provenance_and_lifecycle():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([shutil.which("node"), "--test", "tests/js/signal_panel.test.js"],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
