# Phone-to-nurse live voice demo

The selected presentation is now the two-resident flow in
[decision036](decisions/036-phone-to-nurse-demo-handoff.md). After deploying this release, open
`https://baseline.deeruan.com/unit?demo=handoff` or tap **Live demo** in the navigation.

## Selected phone-to-nurse sequence

1. Keep the nurse tab open. Copy its two separate resident links privately to the runner and
   Dee. Do not share the nurse URL. The watch list checks for submissions every two seconds.
2. Runner opens her link, allows microphone access, records the numbers/days prompt (up to30s),
   listens to playback and taps **Submit check-in**. Audio stays on her phone; only a receipt
   containing duration and a UUID request ID reaches the server. Nurse sees Resident A as Watch.
3. Nurse opens **Add context / possible explanation**, chooses **Recent exertion / just finished
   running**, and applies it. Resident A becomes Explained. Exertion is supplied, not detected.
4. Dee opens the other link, records a slow/pause-filled take and submits. Resident B shows Watch.
5. Dee records and submits another take using the same link. Resident B shows Escalate. Open
   **Review baseline and finding**, then **Run4ATnow** to review the proposed action and handoff.
   This control sends no external alert and performs no assessment.
6. **Start a new rehearsal** deletes the room and creates new phone links. Old links stop working.

The small Demo scenario disclosure identifies the supplied fictional baselines and authored
findings. Audio is live, but is not analyzed. There are no clinical history writes or enrollment
requirements. Both takes may occur minutes apart; the authored confirmation is within24hours,
not a change to the real clock. Ordinary resident scoring/permission paths remain separate.

Rooms have separate nurse/capture capabilities, last two hours, and disappear on server restart.
The nurse URL fragment restores the room on reload without localStorage. Keep all room URLs and
recordings outside Git. This demo requires a single API process; multi-worker/instance deployment
needs a shared room store first. Start a new room if a link expires.

Rehearse permission, audible playback, nurse arrival, exertion context, both Dee submissions,
escalation guidance and reset on the exact phones/public HTTPS URL. Headless synthetic microphone
checks do not establish physical phone/codec or presenter acceptance.

## Superseded one-tab presentation

The prior flow below remains reachable only with `demo=legacy-days`. Old `demo=days` links now
open the replacement nurse setup above.

The selected presentation records audio locally, then shows three visibly scripted outcomes for
a fictional resident. It requires no API enrollment, credentials or personal baseline. Start with
Dee's clips, then use the teammate's clips or live microphone. There is no marathon, breathlessness
or clinical-detection claim. See [decision 034](decisions/034-three-day-local-voice-demo.md).

## Present Watch, Explained and Escalate

Open the deployed presentation:

```text
https://baseline.deeruan.com/check?mode=live&demo=legacy-days
```

The equivalent path on a local frontend is `/check?mode=live&demo=legacy-days`. This is separate from
the actual watch list at `/unit`; adding the query to an older deployment does not install it.

1. Day 1: tap **Record live**, read the numbers/days prompt, and tap Stop (auto-stop at 30 s).
   Or choose **load a prerecorded clip**, initially `htv/normal.wav`. Play it back if desired.
   The page reveals the authored **Watch** scenario with the simulated recheck action.
2. Tap **Next simulated day**. The prior clip is cleared; actual dates and history are untouched.
3. Day 2: record or load a clip, initially `htv/slow.wav`. The fictional dentures context produces
   the scripted **Explained** scenario, regardless of the actual audio's features.
4. Advance again. Day 3: record or load a clip, initially `htv/pausey.wav`. Fictional medication
   and intake context produce the scripted **Escalate** scenario and **Run 4AT now** label.
5. **Restart scenario** clears the tab's recording and returns to day 1. To swap speakers, restart
   and use the teammate's recording or microphone; no code/data migration or enrollment is needed.

Say: "We are capturing a real clip. We are now stepping through a scripted three-day example to
show how the three outcomes are presented." Keep the simulation labels visible. The authored
feature table is not measured from the clip. No audio, ASR request, fake assessment or notes are
sent to the backend. A failed microphone/import does not count as a recording or reveal a result.

Rehearse twice on the exact HTTPS demo URL/device; grant microphone permission before presenting.
Keep one labelled prerecorded clip and a backup video available. Local recordings should be
30 seconds or less (known-duration WAV/MP4 is simplest), smaller than 20 MB, and kept outside Git.
The existing four WAVs were exercised locally in Chrome; deployment and physical-phone rehearsal
remain separate checks. The labelled local mode is deployed at baseline.deeruan.com on release f7f02c0; physical-device recording and rehearsal remain unverified.

## Optional genuine baseline comparison (separate flow)

The presenter is Dee, with a later caller planned. API enrollment is not yet complete. Use
only the actual speaker's own baseline and device; the later caller needs a separate identity
and baseline. The Dee examples below are not permission to mix two people's recordings.

## Prepare

1. Use a running authorized demo origin and its dedicated runner/capture patient UUID, outside
   the twelve scripted residents. Keep the care-team session file private; never paste tokens
   in commands, screenshots or Git. Verify that this patient is in `PM_NO_ESCALATE_PATIENTS`.
   Open `/check?mode=live&patient=<capture-uuid>` as the assigned nurse and use the counting
   setup panel to explicitly configure the supported `en` protocol. Supply a given name only
   if the person provides it. Save voice permission as a separate actual decision. The helper
   requires a ready English profile and current version; it never configures language/name.
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
Every baseline upload carries the initially admitted profile version and `protocol_locale=en`.
A profile change stops enrollment with its partial receipt; reload and deliberately review the
person's setup rather than silently adopting a different profile for the remaining recordings.

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

The three-day mode above intentionally does not invoke the optional genuine enrollment path.
Do not mix its fictional values with a real baseline or store its results as clinical history.
