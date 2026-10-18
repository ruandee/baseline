import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
def test_phone_to_nurse_handoff_interactions():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['node', '--test', 'tests/js/demo_handoff.test.js'], cwd=root,
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
