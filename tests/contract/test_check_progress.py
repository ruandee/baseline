"""Real stored engine response feeds the live page; only audio/clock are deterministic stubs."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from patient_memory.speech.pipeline import Analysis
from tests.contract.test_api import client_for
from tests.integration.test_assessments import BASE, QUALITY, seed_checks


@pytest.mark.parametrize("prior_count", [2, 3])
def test_real_enrollment_boundary_and_measured_timings_render_in_live_page(
        sandbox, monkeypatch, tmp_path, prior_count):
    # Unmarked historical checks select rolling mode, rather than synthetic enrollment flags.
    seed_checks(sandbox, prior_count, base=False)
    analysis = Analysis(True, QUALITY, BASE, [], [], {"asr": 7})
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **kw: analysis)
    clock = iter([1.0, 1.012, 2.0, 2.025])
    monkeypatch.setattr("patient_memory.baseline.assess.perf_counter", lambda: next(clock))
    response = client_for(sandbox).post(f"/v1/patients/{sandbox[1]}/checks",
        data={"mode": "live", "device_id": "tablet-1"},
        files={"audio": ("synthetic.wav", b"stub audio", "audio/wav")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["change"]["params"]["baseline_checks"] == prior_count
    assert body["change"]["params"]["min_baseline"] == 3
    assert body["change"]["status"] == ("enrolling" if prior_count == 2 else "none")
    assert body["timings_ms"] == {"asr": 7, "engine": 12, "verdict": 25}
    assert analysis.timings_ms == {"asr": 7}, "shared immutable analysis input is not mutated"
    node = shutil.which("node")
    if node:
        fixture = tmp_path / "actual-check-response.json"
        fixture.write_text(json.dumps(body), encoding="utf-8")
        result = subprocess.run([node, "--test", "tests/js/check_contract.test.js"],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30,
            env={**os.environ, "CHECK_RESPONSE_FIXTURE": str(fixture)})
        assert result.returncode == 0, result.stdout + result.stderr
