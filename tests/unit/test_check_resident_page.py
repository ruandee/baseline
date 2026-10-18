"""BL-31 resident/PSW /check experience: runs the node:test suite and checks static layout rules.

The behaviour tests live in tests/js (fake DOM, stubbed mic/speech/API). They need Node, which the
CI runner has (it already runs `node --check` on frontend/*.js); without Node they are skipped.
They are not a substitute for real-browser or phone acceptance.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_resident_experience_js_suite():
    result = subprocess.run(
        ["node", "--test", str(ROOT / "tests" / "js" / "check_resident.test.js"),
         str(ROOT / "tests" / "js" / "check_setup.test.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert re.search(r"\bpass [1-9]\d*\b", result.stdout)  # "pass N" in spec or TAP output
    assert re.search(r"\bfail 0\b", result.stdout)


def test_resident_script_loads_before_check_and_shell():
    html = (FRONTEND / "baseline.html").read_text(encoding="utf-8")
    assert html.index("check-resident.js") < html.index("check.js") < html.index("baseline.js")


def test_resident_layout_is_large_and_mobile_friendly():
    css = (FRONTEND / "baseline.css").read_text(encoding="utf-8")
    block = css[css.index("/* BL-31"):]
    # Tap targets of at least 56px, the record button larger, and a phone-width stacked layout.
    assert re.search(r"\.bl-record\{[^}]*min-height:88px", block)
    for selector in (".bl-skip", ".bl-due-item"):
        rule = re.search(re.escape(selector) + r"[^{]*\{([^}]*)\}", block).group(1)
        height = int(re.search(r"min-height:(\d+)px", rule).group(1))
        assert height >= 56, selector
    assert "@media (max-width:640px)" in block and "flex-direction:column" in block
    assert "prefers-reduced-motion" in block
    assert ":focus-visible" in block


def test_resident_view_reads_only_usable_from_a_check_result():
    js = (FRONTEND / "check-resident.js").read_text(encoding="utf-8")
    for field in ("assessment", "verdict", "fused_z", "per_feature", "features.", "quality",
                  "reasons"):
        assert f"data.{field}" not in js and f"result.{field}" not in js, field
    assert "data.usable === true" in js
