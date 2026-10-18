"""The shell shows one "Demo scenario" disclosure, not a badge or banner per screen (BL-16)."""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SHELLS = ("baseline.html", "index.html")
# Visible copy that earlier screens repeated; the single disclosure replaced all of it.
REMOVED_COPY = ("SYNTHETIC DEMO", "Synthetic records", "Synthetic research prototype",
                "/ Synthetic resident", "Fictional records.")


def test_removed_badge_copy_is_not_reintroduced():
    sources = [*FRONTEND.glob("*.html"), *FRONTEND.glob("*.js")]
    found = [(path.name, text) for path in sources for text in REMOVED_COPY
             if text in path.read_text(encoding="utf-8")]
    assert not found, f"Fold this into the Demo scenario disclosure instead: {found}"


def test_each_shell_has_exactly_one_demo_scenario_disclosure():
    for name in SHELLS:
        html = (FRONTEND / name).read_text(encoding="utf-8")
        assert len(re.findall(r'class="demo-badge"', html)) == 1, name
        assert len(re.findall(r"<summary[^>]*>Demo scenario</summary>", html)) == 1, name


def test_demo_is_not_linked_from_either_website_header():
    for name in SHELLS:
        html = (FRONTEND / name).read_text(encoding="utf-8")
        navigation = re.search(r"<nav\b.*?</nav>", html, re.DOTALL).group()
        assert "demo=" not in navigation, name
