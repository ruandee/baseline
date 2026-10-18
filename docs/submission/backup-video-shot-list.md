# Backup demo video: shot list

For BL-23 (#25). Target length **3:45 or less** (judging slot is 4 minutes plus 1 minute of
questions). Recording is a human task for the presenters; this list only plans it. The video is
the fallback if the live host, phone or Wi-Fi fails, so it must show the same flow as the stage
demo, recorded against the real running system rather than mock-ups.

## Gate before recording

Record only once each item below is true; otherwise cut the segment or label it on screen.

- [ ] Hosting (BL-20) or a local laptop run is up; note which on the title card.
- [ ] Demo state comes from the synthetic cohort loader and reset (BL-14, BL-21).
- [ ] `/check` (BL-17) and `/resident/{id}` (BL-19) are merged and talk to the live API,
      not fixture mocks.
- [ ] Every evidence chip clicked on camera opens its real source quote.
- [ ] Mrs. K's sourced observation reads **37.1 Celsius**, with its event time and source
      citation. Say the recorded value; do not label it normal or infer absence of fever.
- [ ] The SBAR panel shows its true badge: "AI draft, verify" only if BL-12 produced it,
      otherwise "template".
- [ ] No real person's data appears except the consenting teammate's own voice check, and only
      if they agree to its use in a public video.
- [ ] No token, `.env`, terminal history, browser autofill, email, phone number or notification
      is visible. Use a clean browser profile and Do Not Disturb.

## Shots

| # | Time | Screen | Narration (one line) | Must be visible |
| --- | --- | --- | --- | --- |
| 1 | 0:00-0:15 | Title card | "Baseline: a 10-second conversation compared with each resident's own normal. Synthetic data, prototype." | "Synthetic data prototype" text |
| 2 | 0:15-0:35 | Problem slide | Delirium often shows as confusion before fever; aides notice "seems off" before the chart does. | Source for the cited statistic |
| 3 | 0:35-1:10 | Phone `/check`, live mode | A teammate counts to 20 and says the days of the week. Result: waveform, word chips, shaded pauses, four numbers. | `enrolling` verdict (no baseline yet); `timings_ms` footer |
| 4 | 1:10-1:30 | `/unit` | Watch list sorted by verdict; "1 of 3 escalations used this shift". | "synthetic" badges; text labels on every verdict chip |
| 5 | 1:30-2:25 | `/resident/{Mrs. K}` | Speech slowed and pauses grew two days after a new oxybutynin order; aide's note "quiet at lunch"; recorded temperature 37.1 Celsius. Verdict escalate, suggested 4AT. | Evidence rows with highlighted quotes; click each displayed source/check citation through to its readback; temperature source/time; baseline band and change marker on the charts |
| 6 | 2:25-2:40 | SBAR panel | Handoff draft the nurse edits rather than writes; every number is checked against the computed values. | Badge ("AI draft, verify" or "template"); citation chips |
| 7 | 2:40-3:20 | Dee live comparison, then synthetic Mr. T | Dee replaces the remote runner caller: actual check receipt and own rested baseline; normal is valid. Mr. T's synthetic dentures story demonstrates explained change separately (decision 027). | Same capture identity/device, live measurements and actual result; synthetic explaining quote |
| 8 | 3:20-3:35 | "How this was decided" table | Statistics decide change, fixed rules decide the verdict, the model only finds context in notes. | Per-feature median, scale, z, EWMA, CUSUM |
| 9 | 3:35-3:45 | Close card | "Change detection, not diagnosis. Not clinically validated. Vox integration is a mock." | Limits text, repo URL |

Optional KAZE cut (only if BL-25 to BL-29 merge and the two-phone loop works): 45 seconds
replacing shot 5, showing a missed check-in, the contact's text and "I'm on it". Do not film a
mock of it presented as working.

## Saving

- [ ] Export 1080p MP4 with burned-in captions (the room may be loud).
- [ ] Copy 1: uploaded to the video host chosen for Devpost (unlisted is fine), link tested in a
      private window.
- [ ] Copy 2: on a USB stick or a second laptop, playable offline.
- [ ] Do **not** commit the video, raw audio or screen recordings to Git.
- [ ] Record the two locations in a comment on #25 (BL-23 "done when").
