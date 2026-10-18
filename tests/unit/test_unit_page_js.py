"""BL-18: run the /unit behaviour test (tests/js) under Node; skipped when Node is absent."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_TEST = ROOT / "tests" / "js" / "unit_page.test.mjs"


def run_unit_page_js(fixture: Path | None = None) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = {**os.environ}
    if fixture is not None:
        env["UNIT_WATCHLIST_FIXTURE"] = str(fixture)
    result = subprocess.run([node, "--test", str(JS_TEST)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# fail 0" in result.stdout or "fail 0" in result.stdout, result.stdout
    return result


def test_unit_page_order_and_polling_against_the_schema_fixture():
    run_unit_page_js()
