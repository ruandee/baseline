"""Run every offline Node suite in one batch; fixtures and harnesses are not suites."""
from tests.js_runner import JS_DIR, run_js_suites

SUITES = sorted(p.name for pattern in ('*.test.js', '*.test.mjs') for p in JS_DIR.glob(pattern))


def test_frontend_suites():
    assert SUITES, 'No JavaScript suites were discovered'
    run_js_suites(*SUITES)
