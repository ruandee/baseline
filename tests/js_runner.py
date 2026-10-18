"""One Node runner for offline suites and API-captured fixture readback."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / 'tests' / 'js'
LONG_SUITES = {'check_resident.test.js', 'check_setup.test.js', 'unit_page.test.mjs'}


def run_js_suites(*filenames, fixture_env=None):
    assert filenames, 'Choose at least one JavaScript suite explicitly'
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is not installed')
    result = subprocess.run(
        [node, '--test', '--test-reporter=tap', *(str(JS_DIR / name) for name in filenames)],
        cwd=ROOT,
        env={**os.environ, **(fixture_env or {})}, capture_output=True, text=True,
        encoding='utf-8', errors='replace',
        timeout=120 if LONG_SUITES.intersection(filenames) else 30)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert re.search(r'^# pass [1-9]\d*$', result.stdout, re.MULTILINE), output
    assert re.search(r'^# fail 0$', result.stdout, re.MULTILINE), output
    return result
