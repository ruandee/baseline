import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required")
def test_live_check_contract_rendering():
    result = subprocess.run([shutil.which("node"), "--test", "tests/js/check_contract.test.js"],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
