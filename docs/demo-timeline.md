# Demo timeline: phone-to-nurse presentation

For the 4:00 judging slot. The live demo target is about 2:00, leaving time for the opening and Q&A.
The flow is [decision 036](decisions/036-phone-to-nurse-demo-handoff.md), opened at
`/unit?demo=handoff`. Everything the nurse screen shows after a recording is an **authored
scenario**; the audio is real but is never analyzed. Say so (see the disclosure wording below).

## Beats

Cast: **Nurse** (laptop, nurse screen), **Runner** (phone A, runner link), **Dee** (phone B,
resident link). Seconds are a plan, not a measurement of real voices: the dry run below used a
synthetic tone for 5 to 15 s per take. Time a real rehearsal and adjust.

| # | Time | Screen | Action | Nurse screen shows |
| --- | --- | --- | --- | --- |
| 1 | 0:00 to 0:15 | Nurse | Open **Live demo**. Open *Phone recording links*; send the runner link to phone A and the resident link to phone B. Keep the nurse URL private. | Two waiting cards, "Connected, checking every 2 seconds" |
| 2 | 0:15 to 0:45 | Runner phone | Allow microphone, tap **Start recording**, count one to twenty then the days of the week, **Stop**, play back, **Submit check-in**. | Resident A: **Watch**, "Recheck in 1 hour", within about 2 s of Submit |
| 3 | 0:45 to 1:00 | Nurse | **Add context / possible explanation**, keep "Recent exertion / just finished running", **Apply context and reassess**. | Resident A: **Explained**, "No escalation suggested" |
| 4 | 1:00 to 1:30 | Dee phone | Record a slow, pause-filled take, **Submit check-in**. | Resident B: **Watch** |
| 5 | 1:30 to 1:55 | Dee phone | **Record next check**, record again, **Submit check-in**. | Resident B: **Escalate**, "Run 4AT now" |
| 6 | 1:55 to 2:10 | Nurse | Open **Review baseline and finding**, then **Run 4AT now**. | Supplied baseline, repeated finding (two matching changes within 24 hours, combined score 3.2) and a handoff draft. No alert is sent. |

Total about 2:10. If it runs long, drop beat 6's baseline panel and show only the handoff draft.

## Disclosure wording

Keep the page's own "Demo scenario" disclosure visible. Say it aloud once, around beat 2:

> The recordings are real, but they stay on the phones and are not analyzed. The baselines and the
> Watch, Explained and Escalate results are scripted scenarios, so none of this is a measurement
> or a clinical finding.

Do not say the runner's result was detected or measured. The exertion context is entered by the
nurse; the page does not detect it. Page text for reference: "Live recording with supplied
fictional baselines and authored findings. Audio stays on the recording device; only check-in
receipts are shared. No voice analysis, clinical history writes or external alerts."

## If something fails

| Failure | What the page shows | Do this |
| --- | --- | --- |
| Microphone blocked or no HTTPS | "Could not record. Use HTTPS, allow microphone access, and try again." | Allow the microphone in the browser, tap **Start recording** again. A phone needs the HTTPS host, not a LAN address. |
| Phone shows the recording is unplayable | "Could not play this recording. Please record again." | Record again. |
| Network drops during Submit | "Connection failed. Try again; the same check-in will not be duplicated." | Tap **Submit check-in** again. The recording is kept and the retry reuses the same ID. |
| Link expired or room replaced | "This demo link expired or is invalid. Ask the nurse for a new link." | Nurse taps **Start a new rehearsal** (this deletes the room and creates new links), then re-send both links. |
| Scenario step already used | "This scenario step is complete or out of order. Check the nurse screen." | The runner submits once and Dee twice per room. Start a new rehearsal. |
| Live recording fails entirely | n/a | Switch to the backup video. **No backup video exists yet** (shot list only, issue #25); record one before judging. |

Rooms last two hours and are lost on a server restart, so start a fresh room right before presenting.

## Dry run, 2026-10-18 local, Chrome, synthetic microphone

Run against `bl/bl-16-danny-overnight-polish` at the local frontend. Two Chrome tabs (nurse and
phone page). A WebAudio tone stood in for the microphone, so the real browser permission prompt
and real phone audio were **not** exercised. This does not replace a rehearsal on the phones.

| Step | Result |
| --- | --- |
| Separate runner, resident and nurse links | Pass. A capture key cannot read the room (404). |
| Microphone permission request | Partial. The page waits on the real prompt ("Waiting for microphone permission…"); the grant itself was not tested. A failed stream shows the "Could not record" message. |
| Record, play back, submit | Pass. Receipt confirmed on the phone page. |
| Runner receipt arrives as Watch | Pass (2:37:11). |
| Add exertion context gives Explained | Pass. |
| Dee first submit gives Watch, second gives Escalate | Pass (2:38:07, 2:38:54). |
| Run 4AT and handoff draft guidance | Pass. |
| Nurse reload mid-flow | Pass. Both cards restored from the URL fragment. |
| New rehearsal invalidates old links | Pass. Old runner and Dee keys return 404 on submit and read; a stale phone link shows the expired-link message; the new room starts empty. |
| Interrupted submission | Found and fixed. The phone showed the browser's raw "Failed to fetch"; it now shows the retry message (commit `5dcd4b3`, test in `tests/js/demo_handoff.test.js`). The recording was kept and the retry reused the same request ID. |
| Room expiry (two hours) | Not waited. Covered by `tests/unit/test_demo_handoff.py` and `tests/js/demo_handoff.test.js`. |
| "Switch to another day" shows three routes | Not applicable. That is the superseded one-tab flow (decision 036); it remains at `demo=legacy-days` and was not run. |

Not verified: physical phones, LTE, real microphone permission prompts, codecs, and a timed
rehearsal with real voices.
