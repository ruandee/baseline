"""KAZE capture/state tests use fake clocks, permissions and uploads; no model or SMS calls."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required")
@pytest.mark.parametrize("filename", ["kaze_capture.test.js", "kaze_pages.test.js"])
def test_kaze_capture_browser_contracts(filename):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([shutil.which("node"), "--test", f"tests/js/{filename}"],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_kaze_bootstrap_cli_writes_ignored_artifact_without_printing_tokens(tmp_path, monkeypatch,
                                                                         capsys):
    from scripts import kaze_demo
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(kaze_demo, "kaze_demo", lambda: {"people": [{"token": "synthetic-token"}]})
    kaze_demo.main()
    output = capsys.readouterr().out
    assert "synthetic-token" not in output
    assert "synthetic-token" in (tmp_path / "artifacts/kaze-demo/session.json").read_text()
