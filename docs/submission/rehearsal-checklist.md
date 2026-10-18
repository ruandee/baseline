# Rehearsal and demo-day checklist

For BL-24 (#26). Rehearsal is a human task: a written checklist is not a rehearsal, and BL-24 is
done only when **two full solo run-throughs by the Sunday presenters each finish under 4 minutes
with no manual fixes**. Record each run below (or in a comment on #26).

Depends on BL-21 (reset) and BL-23 (video). If either is missing, rehearse with what exists and
note the gap; do not paper over it with hand-edited database rows.

## Roles (fill in)

| Role | Person |
| --- | --- |
| Presenter (talk track) | |
| Driver (laptop) | |
| Live check speaker (phone) | |
| Runner contact / KAZE contact (if used) | |
| Timekeeper | |

## Run log

| Run | Date/time | Presenter | Duration | Manual fixes needed? | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | | | | | |
| 2 | | | | | |

A "manual fix" is anything outside the script: re-running reset mid-demo, refreshing a stuck
page, editing data, restarting the API, switching to the video. Any fix means the run does not count.

## Before each rehearsal

- [ ] `git pull` on the demo machine; note the commit SHA.
- [ ] Run the reset script (BL-21) and time it (target under one minute). It must not touch the
      runner's real clips.
- [ ] Watch list loads on the HTTPS URL (or localhost) with a fresh token.
- [ ] Tokens valid for the whole session (48-hour TTL).
- [ ] `PM_NO_ESCALATE_PATIENTS` contains the runner's patient id, if the runner segment is used.

## Script timing (4:00 total)

| Segment | Target | Fallback if it fails |
| --- | --- | --- |
| Live check on stage | 0:35 | Retry once; then show a stored check |
| Mrs. K (escalate) | 1:15 | Backup video from shot 5 |
| Runner (explained) | 0:55 | Labelled stairs backup clip; or Mr. T (dentures) |
| How it works and why it's trustworthy | 0:30 | |
| Close and honest limits | 0:15 | |
| KAZE (only for the KAZE judge, replaces Mrs. K) | 0:45 | Describe as design; do not show a mock as working |

## Talk-track guardrails (say these, avoid the opposites)

- Say "detects change against her own normal", never "detects delirium" or "diagnoses".
- Say "suggests a standard assessment the nurse decides on", never "recommends treatment".
- Say "fictional residents" and point to the synthetic badge.
- Say "Vox integration is a mock contract we defined"; there is no real PointClickCare connection.
- Say KAZE is "the same engine, designed for outside the care home"; only say it works if the
  two-phone loop was rehearsed successfully.
- Say "statistics detect change, fixed rules choose the verdict, the model only finds context
  and drafts a checked handoff". Never say the model decides.
- If asked about accuracy: "not clinically validated; the best study we cite had 33 patients".

## Demo-day checklist (Sunday, before 10:00)

From `docs/06-baseline.md`, plus items found while preparing:

- [ ] Once BL-21 is merged, run `bash deploy/reset-demo.sh` on the configured demo host; confirm
      the printed watch-list URL loads with fresh tokens. Follow `docs/deployment-walkthrough.md`
      for initial setup. Time the command; the under-one-minute gate remains unverified.
- [ ] Do one live check from the demo phone in the judging room; note the noise level
- [ ] Confirm the runner's two race clips arrived and show `explained`; if not, use the labelled stairs backup clip
- [ ] Run one Gemini extraction; if it fails, confirm the template SBAR and offline tags still show
- [ ] Open the backup demo video in a second tab (and have the offline copy ready)
- [ ] Phone charged, laptop on power, HTTPS URL bookmarked on both
- [ ] Phone microphone permission already granted for the HTTPS origin (Safari and Chrome)
- [ ] Notifications off on every screen being shown; no terminals with secrets visible
- [ ] Devpost entry final submission confirmed by 08:00 (human; check the confirmation email)
