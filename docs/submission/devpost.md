# Baseline — Devpost draft

Prepared for BL-22 / BL-23. **Draft only; not submitted.** The sections from “Project name”
through “What's next” are the paste-ready entry. The final section is for the team only.

## Project name

Baseline

## Tagline

Help care teams notice when someone is different from their usual self—and see the context behind the change.

## Inspiration

“She seems a little different today.”

For a care aide who knows a resident well, that observation can mean a lot. For a nurse
covering a busy unit, or a staff member meeting that resident for the first time, it can be
hard to know what changed or where to look next.

We wanted to make that observation easier to share. Baseline starts with a simple question:
**what is normal for this person?** A resident is compared with their own history, rather than
expected to sound like everyone else.

## What it does

A care aide opens a resident's check, asks them to count and say the days of the week, and
records a short response. The resident gets a simple thank-you, without a score or a warning.

Baseline measures things such as speaking speed and pauses, compares them with earlier
checks, and brings relevant notes and recorded observations into the same view. A nurse gets
a short, prioritized list and can open the records behind each explanation. A draft handoff
helps them share what they found; the nurse remains responsible for reviewing it.

Our fictional residents show three different situations:

- **Mrs. K needs review:** her speech changed, and there is relevant context in her care record.
- **Mrs. L needs another look:** a change is being watched rather than treated as a diagnosis.
- **Mr. T has an explanation to consider:** his record mentions new dentures. That context is
  shown alongside the change; it does not prove that nothing else is wrong.

The goal is to help a busy person decide **who to look at, what changed, and which records to read**.

## How we built it

The app runs in an ordinary browser on a phone or computer. There is no separate mobile app
to install. Its main parts are:

- **HTML, CSS and JavaScript:** the recording screen, nurse list and resident detail pages.
- **Python and FastAPI:** receive a check, run the processing steps and return the result.
- **FFmpeg and Whisper:** prepare the audio and identify the spoken words and their timing.
  Additional audio tools measure pauses and pitch.
- **PostgreSQL with TimescaleDB:** keep the history and build the charts. Source records are
  stored separately so an explanation can point back to what was actually recorded.
- **Docker and Caddy on Google Cloud:** run the services together and provide an HTTPS website.

The change calculation uses measurements and explicit rules. An optional Gemini connection
can help find context in notes and draft a handoff. Its quotes and numbers are checked against
the supplied evidence. It does not decide the verdict. The current hosted demo uses the
no-model-call fallback, so a working page is not a claim that Gemini ran live.

## Challenges we ran into

The difficult part was making the result useful and trustworthy, not just producing a number.
A recording can be noisy. Someone may not have enough history yet. A note may have been
corrected. A user may not be allowed to see a record.

We built explicit “not enough information” and retry states, kept explanations connected to
their sources, and separated the care aide's simple check flow from the nurse's detailed view.
A missing note is never treated as proof that a symptom is absent.

## Accomplishments we're proud of

We connected a short voice check, a person's history, a prioritized nurse view and supporting
records in one prototype. The deployed fictional cohort includes all twelve residents, with
different cases that show why a changed measurement should not always lead to the same response.

We also kept the resident experience simple: clear recording controls, the option to skip,
and no clinical scores on the resident-facing screen.

## What we learned

A useful alert needs a clear explanation and a clear next step. Showing more measurements
is not automatically more helpful. The person using the tool needs to understand what they
are seeing, where it came from, and what is still unknown.

## What's next

Our next step is to test the experience with consenting volunteers and care professionals:
can people complete the check comfortably, and can a nurse quickly understand the result?
We still need physical-phone testing and measured processing times on the hosted system.

We have also built prototype extensions for movement, recorded vital signs and personal
safety check-ins through Project KAZE. These need their own validation. Our Vox encounter
adapter is a mock; there is no live PointClickCare integration.

**Baseline is a decision-support prototype, not a diagnostic tool.** The resident records in
this demo are fictional. We have not established clinical accuracy or improved patient outcomes.
Real-world use would require clinical evaluation and decisions about consent, hosting and data handling.

---

## Team only — do not paste this section into the project story

### Built with

Python, FastAPI, Pydantic, PostgreSQL, TimescaleDB, FFmpeg, faster-whisper, WebRTC VAD,
Praat/parselmouth, HTML, CSS, JavaScript, Docker, Caddy, Google Cloud Compute Engine.

Add Gemini API to the final technology/prize fields only with the team's explanation of its
actual configured use. The hosted release currently uses `PM_PROVIDER=stub`. LocalStack
provides S3-compatible source storage in the demo; do not describe it as a production AWS deployment.

### Links and submission fields

- Code: https://github.com/ruandee/patient-memory-backend — currently private; a repo admin must
  decide on publication after the history/secret review. Do not change visibility as part of this draft.
- Demo: https://baseline.deeruan.com/unit — verified on release
  `f7f02c0a77d60b29efceb32c61b11cd96d74d193` (the same application tree as main
  `250cd51fbb56f1a7d9206439b2cc80be2f55d09f`), per the current deployment handoff.
  Historical scenario snapshots are separate from actual live measurements.
  Recheck immediately before submission; the original VM is scheduled to stop October 18 at
  about 9:09 PM Toronto time. Newer merged features are not automatically deployed.
- Video: add the actual uploaded video URL and verify access from a signed-out browser.
- Team: confirm names, contributions and Devpost accounts with the actual participants.
- AI development tools: Claude Code and OpenAI Codex; confirm the team's complete disclosure.

### Prize claims to confirm

- PointClickCare / healthcare / social impact: frame as an explainable prototype; do not claim
  a vendor partnership, real patient deployment, clinical accuracy or measured health outcomes.
- Gemini: prior connectivity smoke tests do not establish live note or handoff quality. Confirm
  the actual demonstration and official track requirements before selecting the prize.
- Tiger Data: describe the actual TimescaleDB/time-series use. Do not call `voice_checks` a
  hypertable; the implementation uses an ordinary table to preserve its access controls.
- KAZE: describe the extension as a prototype unless the real two-phone text-and-acknowledgement
  loop has been demonstrated. Logged delivery is not a sent text.
- Hosting is Google Cloud; the domain is managed through Namecheap. Do not claim Vultr or GoDaddy use.

### Final editing checks

- Keep the three fictional cases and a screenshot of the actual nurse screen.
- Remove any sentence describing a feature that cannot be shown in the final demo.
- Replace the fallback-provider sentence only after verifying the configured live model.
- The accepted live plan uses Dee instead of the remote runner (decision 030). Claim that
  segment only after successful same-person rested enrollment and rehearsal; an actual live
  result may be normal. The separate three-day local demo has authored results, not measurements
  computed from its recording (decision 034). Neither proves exertion or clinical detection.
- Audio is deleted after processing unless a developer retention flag is enabled. Measurements,
  transcript and word timings remain with the check; confirm consent and data handling before
  recording a real person.
- Public submission, prize selection, repository visibility, video publication and real-person
  recording remain separate human actions. This document does not complete #24 or #25.
