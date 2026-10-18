# Dee's live voice demo

The live speaker is Dee, on the same device used for the baseline. No teammate telephone call,
marathon claim, stairs-trigger promise or breathlessness detector is part of this flow.
See [decision 030](decisions/030-live-voice-demo-protocol.md) for the approved protocol revision.

## Prepare

1. Use a running authorized demo origin and its dedicated runner/capture patient UUID, outside
   the twelve scripted residents. Keep the care-team session file private; never paste tokens
   in commands, screenshots or Git. Verify that this patient is in `PM_NO_ESCALATE_PATIENTS`.
2. Record five independent rested takes on the demo microphone/browser. Read numbers one to
   twenty followed by Monday to Sunday in each. Keep the same microphone distance and quiet
   setting; stop when finished. Each take must be usable and no longer than 30 seconds.
3. Keep them in ignored `data/raw/live-demo/rested-1.wav` through `rested-5.wav` (or supply their
   actual paths). The existing `htv/normal.wav` is only one take; slow/pausey/stairs are not rested
   enrollment material. The upload helper converts locally to 16 kHz mono WAV so the original
   6.6 MB exports can fit the unchanged 2 MB multipart limit; originals remain untouched.

## Enroll through the API

From the repo root, replace the example origin, UUID and private file path:

```powershell
uv run python -m scripts.enroll_voice_baseline --base-url https://demo.example.org --patient-id <capture-uuid> --session-file artifacts/baseline-demo/session.json --device-id dee-demo-phone --record-consent --clips data/raw/live-demo/rested-1.wav data/raw/live-demo/rested-2.wav data/raw/live-demo/rested-3.wav data/raw/live-demo/rested-4.wav data/raw/live-demo/rested-5.wav
```

`--record-consent` explicitly records the volunteer's personally granted decision if state is
unknown. Omit it if consent is already granted. Declined, withdrawn and expired decisions are
not overwritten by the helper. Authorization and consent are also enforced by the server for
every upload. The file can contain a JSON `token` or a plain JWT; no token is printed.

The helper uses only existing HTTP APIs, no admin database access. It requires five distinct
original AND decoded recordings, stops at the first unusable/error response, and writes private
receipts with check IDs/usability. It never automatically retries a POST: a timeout can mean a
check was stored. After a partial failure, inspect the receipt and server before submitting more;
do not re-submit the whole set blindly. No transcript or raw audio is saved in the receipt.

Success means five distinct usable check receipts, not a clinical enrollment claim. Confirm the
latest overview selects enrolled mode and exposes the expected baseline before rehearsal. The
latest baseline check compares against earlier checks, so its displayed prior-check count can
be four immediately after five submissions; the subsequent live check should use all five.

## Rehearse and present

Open the helper's printed URL:

```text
/check?mode=live&patient=<the-same-capture-uuid>&device=dee-demo-phone
```

Do not use the reset's other default live patient: it has no copy of this baseline. Do not use
`mode=runner` for the on-stage result card, because that mode shows a thank-you receipt.

1. Confirm consent, fresh credentials, server/model readiness and the expected baseline.
2. Tap Record, read the same prompt naturally, and tap Stop when finished (auto-stop at 30 s).
3. Verify the real upload is usable, then show transcript/word timing, pauses and feature values
   against the baseline. Open the same patient's resident page for the stored assessment.
4. Say: "This is my live check against my own baseline. Here are the measurements and the actual
   result." A normal result is valid; do not promise an exertion flag.
5. Switch to the explicitly synthetic Mrs. K/Mr. T story for the reproducible verdict/context
   pathway. An optional deliberately slow/pausey challenge must be labelled as acted demo speech;
   its result is not guaranteed and does not show natural exertion or clinical deterioration.
6. Save a clearly labelled prerecorded backup and complete two full rehearsals under four minutes.

The 30-second timer and phone codecs need real-device acceptance, including checking that encoded
duration does not exceed the server's 30-second cap. Use compressed browser WebM/MP4; raw desktop
WAV exports can exceed the upload limit without the helper's local conversion.

## Golden suite

```powershell
uv run pytest -m slow tests/unit/test_golden_clips.py -v -rA
```

Required: four usable clips, lower rate for slow, higher pause ratio/count for pausey. Stairs is
reported as exploratory, with no direction gate. Keep audio in ignored `data/raw/golden/`; never
commit personal recordings or add them to CI. This does not mark API enrollment, phone/host
acceptance or rehearsal complete.
