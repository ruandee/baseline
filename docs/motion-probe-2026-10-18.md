# Motion check probe, 2026-10-18 (BL-34)

Browser probe of `/check?type=motion` (staff) and `/check?type=motion&mode=resident&patient=<id>`.
Synthetic data only. Camera input was a stubbed `canvas.captureStream()`, so no pose was ever
detected; every capture ended "incomplete" with all features `null`. Pose accuracy is not covered.

## Environment

- Branch `bl/bl-34-overnight-motion-probe`, code under test at `9390ed5` (on `9b4f604`).
- Chrome 155.0.8059.40 driven through Claude in Chrome, one tab, desktop viewport (1470 px wide).
- Server: `python -m scripts.frontend` on `127.0.0.1:8002`, local mode, **without** `PM_DEMO_TOKEN`
  (see "Probe setup trap"). Real vendored MediaPipe worker, real API and Postgres (`pmb_overnight`).
- Stubs injected from the page after each load: `getUserMedia` (fresh animated canvas stream per
  call), `Worker` (for model-failure cases) and `fetch` (to drop a key from the POST response).

## Probe setup trap

The overnight handoff starts this server with `PM_DEMO_TOKEN` read from
`artifacts/baseline-demo/session.json`. That token is for tenant `9850ebb5…` (Mrs. K, Mr. T, …),
but `scripts/frontend.py` seeds its own patients (Alex Morgan, …) under a different tenant. With
the mismatched token every `/v1/patients/<id>/…` call returns 404, so consent recording and
readiness both fail and the page shows the same failure copy as a real motion fault. Start the
server without `PM_DEMO_TOKEN` for local probing; local mode mints a matching reader token.

## Cases

All "works" rows are browser-verified at the stated commit unless marked otherwise.

| Case | Steps | Observed | Verdict |
|---|---|---|---|
| Get ready, no motion consent | Open page, click Get ready | Failure copy within ~250 ms, Start stays disabled | works |
| Save-permission gating | Open page; tick "I have confirmed" | Save disabled until ticked; ticked and disabled again after each save | works |
| Consent granted (person) | Tick confirm, Record | "Movement permission recorded. Camera is off." | works |
| SDM without reference | Decision maker = SDM, empty reference, Record | Rejected with generic "Check the decision-maker details…" copy | works, vague copy |
| SDM with reference | Same, reference filled | Recorded; Get ready then succeeds | works |
| Declined, then withdrawn | Record each, then Get ready | Recorded; Get ready fails each time, Start disabled | works |
| Re-grant after withdrawn | Record granted, Get ready | Ready | works |
| Real model start | Consent present, Get ready | "Ready" in 513 ms; worker standalone 292 ms; CSP OK | works |
| Model failure (worker posts error) | Stub `Worker`, Get ready | Failure copy, Start disabled, Get ready re-enabled | works |
| Model failure (worker constructor throws) | Same | Same | works |
| Worker never answers | Stub `Worker`, Get ready, wait 3 s | "Getting ready…", Get ready disabled; Cancel recovers it | works (30 s limit not waited out) |
| Capture, 10 s | Start with animated canvas | 161 frames processed, no per-frame timeout, tracks `ended`, POST has `quality, features, device_id, device_ts, prompt_version, is_baseline` (no media) | works |
| All-null result | Same | Three "Unknown" lines, incomplete-movement message, "Measurements saved; camera is off." | works |
| Missing feature key in response | Wrap `fetch`, delete `features.trunk_sway` | "Unknown" shown, "Measurements saved", no failure copy | works (fixed) |
| Cancel during capture | Start, wait 3 s, Cancel | Track live to ended, preview hidden, "Camera off. No video was sent.", nothing posted | works |
| Cancel during Get ready | Click Get ready then Cancel | Start disabled, camera-off copy | works |
| Person switch mid-ready | Get ready, change person | Start disabled; Get ready for a person without consent fails | works |
| Pagehide during capture | Dispatch `pagehide` after 2.5 s | Tracks ended, no POST, no result | works |
| Resident mode | `&mode=resident&patient=<id>` | Permission fieldset and baseline hidden, result is only "Thank you.", no measurements, resident failure copy "Please ask your care team…", POST has no media | works |
| Resident person selector | Same page | Selector visible with all 12 names, switchable | broken (see recommendations) |
| Stale result after Cancel | Complete a capture, Start again, Cancel | Previous result text stays on screen | minor, not fixed |
| 390 px layout | `resize_window` to 390 px | Viewport did not change (`innerWidth` stayed 1470) | **not verified** |

## Fix made

`frontend/motion.js` (commit `9390ed5`): a response whose `features` lacked a key, or held a
non-number, made `value.toFixed(2)` throw. The outer catch then ran `failure()`, which cancelled the
warmed model and said "could not continue" even though the POST had already saved the measurements.
The page now prints "Unknown" for any non-finite value. Test added in `tests/js/motion_page.test.js`
(red before the change, green after). Browser re-check of the fixed build is in the table above.

I did not reproduce the old failure in the browser; the served file was already the fixed one. The
Node test is the evidence for the old behavior.

## Recommendations (not done)

1. **Hide or lock the person selector in resident mode.** Residents can see all names and capture
   as another person. Lock it to `patient` from the URL, or do not render it.
2. **Distinguish failure causes for staff.** Missing consent, 404 and model failure all show the same
   copy, which is how the token mismatch above looked like a motion bug. A short reason code or
   separate "no recorded consent" copy would help. Keep the resident copy generic.
3. **SDM error copy.** "Reference required" is thrown client-side but replaced by the generic message.
   Show a specific message when the reference is empty.
4. **Per-frame 1 s worker timeout** (`motion-capture.js`, `ask(..., timeout = 1000)`) aborts the whole
   capture on one slow frame. It did not trip in 161 frames here, but a slower phone could. Consider
   dropping the frame instead, and keep a longer timeout for the first frame after init.
5. **Clear the result on Start and Cancel** so stale measurements are not shown beside a new capture.
6. **Handoff command:** drop `PM_DEMO_TOKEN` from the local server start (see above).

## Not verified

- Real camera and real pose detection (stubbed canvas only; no person in frame).
- Physical phone, mobile browsers, and the 390 px layout.
- The 30 s model-init timeout (hung worker was checked at 3 s only).
- Ticket #36.
- Old-build failure reproduction in the browser.

## Checks run at `9390ed5`

- `node --check frontend/*.js`: pass.
- `uv run ruff check .`: pass.
- `uv run pytest tests/unit`: 636 passed, 13 skipped, 5 deselected, **3 failed** in
  `tests/unit/test_reset_demo_wrapper.py` (`deploy/reset-demo.sh: ARGS[@]: unbound variable` under
  macOS bash 3.2). The same three fail on base `9b4f604`, so they are not caused by this branch.
- Not run: integration, contract and e2e suites, and the stub evaluation (no Python changes).
