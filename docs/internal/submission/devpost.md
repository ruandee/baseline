# Devpost entry: draft text and prize-track notes

Status: **draft for Dee and Alina to edit and submit** (BL-22 #24, BL-23 #25). Nothing here has
been submitted. Before pasting, re-check every "pending" item against the tracker (#38) and
`docs/build-status.md`; replace a "pending" line only when the feature is merged *and* shown
working on the demo host. Do not paste the bracketed editor notes.

## Before the entry goes in (human decisions)

- [ ] Repository visibility changed to public by a repo admin (Devpost rule). Read the secret and
      history review on the BL-23 preparation PR first.
- [ ] Team members on Devpost match the people who built it (confirm names and handles).
- [ ] Prize tracks selected only where the "claim we can make" column below is true on the day.
- [ ] Demo video link (see `backup-video-shot-list.md`) uploaded and set to viewable by link.
- [ ] Hosted demo URL included only if BL-20 is accepted; otherwise say "runs locally".

## Name and tagline

**Baseline**: a 10-second conversation becomes a vital sign, compared with each resident's own normal.

[Alt tagline: "It noticed, and it knew not to interrupt."]

## Inspiration

In older adults an infection often shows up first as confusion, not fever. That confusion
(delirium) is easy to miss, especially in people with dementia. Care aides often notice that
someone "seems off" days before anything reaches the chart, but "seems off" is not something a
system can track. On a night shift one nurse may cover a whole unit, and agency staff do not know
what anyone's normal looks like. PointClickCare's "Catch It Early" challenge asked for a way to
catch a confused moment early and to explain *why* something was flagged. We built around that
last part.

## What it does

1. A care aide asks the resident to count to 20 and say the days of the week. It takes about 10 seconds.
2. Baseline measures how they spoke: speech rate, pause ratio, mean pause length and median pitch.
3. It compares those four numbers with the **same resident's** history, not a population average.
4. If there is a real change, it checks the resident's record for context: a new high-risk
   medication, a documented temperature, a note like "quiet at lunch", or something harmless
   such as new dentures.
5. A fixed rule table picks one verdict: *escalate*, *watch*, *explained*, *within normal* or
   *enrolling*. The nurse sees a short ranked watch list with the evidence behind each flag and
   a suggested standard assessment (for example, a 4AT delirium screen) chosen from a fixed list.
   An interruption budget ("1 of 3 escalations used this shift") keeps it from flooding anyone.

The point of the demo is the *explained* case: Baseline notices a change and does not page anyone,
because the record already explains it.

## How we built it

- **Backend:** Python, FastAPI and Pydantic on top of our existing patient-memory backend:
  immutable source records, exact-quote evidence spans, event time vs knowledge time, and
  PostgreSQL row-level security enforced through a non-owner runtime role.
- **Speech pipeline:** ffmpeg normalisation, WebRTC voice activity detection, faster-whisper
  (`base`) for word timing, Praat (parselmouth) for pitch, and a quality gate that rejects
  short, noisy, clipped or off-script clips with plain-language reasons.
- **Change engine:** per-person robust baseline (median and scaled MAD), z-scores, EWMA and
  CUSUM, with a *provisional* status so a single strong reading asks for a recheck instead of
  escalating. The accepted `multifeature-cusum-v2` policy (decision 019) requires corroboration:
  a change needs at least two of the same features deviating on two consecutive usable checks,
  pitch is tracked as separate signed up/down streams, and a one-feature CUSUM alarm alone never
  sets a status. Thresholds were not retuned, and no clinical sensitivity or specificity is claimed.
- **Context and verdict:** structured rules (medication events, documented temperatures) plus
  note tagging. The model may only return exact quotes from the note, which the server checks
  character-for-character; anything it cannot verify is dropped, and a keyword fallback runs
  when the model is unavailable. The verdict itself is a deterministic table.
- **Data:** PostgreSQL 17 on the TimescaleDB image, pgvector for the existing retrieval path,
  S3-style immutable source storage (LocalStack locally).
- **Frontend:** buildless HTML/CSS/JS served same-origin by the API, with hand-drawn SVG charts.
- **AI tools used to build it:** Claude Code, OpenAI Codex, and Gemini (runtime model for note
  context). [Confirm the final list with the team.]

**The core design idea:** statistics decide whether something changed; simple, visible rules
decide what to do about it; the language model is used only to find context in free-text notes
and (where merged) to assemble a handoff draft that is validated against the computed numbers
and cited evidence. The model never decides a verdict, has no tools, and cannot widen scope.

## Challenges we ran into

- Row-level security does not apply to TimescaleDB chunk tables, so a runtime role could read
  another tenant's rows directly from a chunk. We kept `voice_checks` as a plain table (still
  using `time_bucket`) rather than ship a cross-tenant leak, and recorded the evidence in
  decision 004.
- Voice activity detection ended every voiced run 120 ms late, which hid real pauses; we
  measured it on constructed audio and corrected it.
- Making "absence of documentation" never count as a negative finding: the interface shows a
  sourced temperature and its time without inferring "no fever" or a normal-range finding.
- Keeping copied evidence honest when a source note is corrected or retracted: stale
  assessments are withheld rather than shown with outdated quotes.

## Accomplishments we're proud of

- Every flag shows its evidence, and every quote resolves to the exact characters in a source record.
- Model failures cannot change a verdict: extraction falls back to keyword rules.
- Authorization is enforced in the database, and denial looks like "not found".

## What we learned

[Team to write: one or two honest sentences each.]

## What's next

- Validate the speech features on real recordings with consent and clinical partners.
- Passive signal from ambient documentation (for example, PointClickCare Vox Advantage) instead
  of a separate check. **For the hackathon the Vox side is a mock adapter we defined; we found no
  public Vox API, and there is no real PointClickCare integration.**
- More signals through the same engine (movement, charted vitals), marked *corroborated* when
  two change together.
- KAZE "Baseline Out" safety sessions: session, scheduler, optional SMS delivery/acknowledgement
  and pages are merged; hosted worker/bootstrap integration and a real two-phone rehearsal
  remain pending. Default delivery is simulated logging and sends no text.
  [Claim a working live loop only after host acceptance and the two-phone rehearsal.]
- A Health Canada classification review before any real deployment.

## Honest limits (keep this section in the entry)

- **Change detection, not diagnosis.** Baseline does not detect delirium. It notices that
  someone's speech changed against their own normal and suggests a standard assessment that a
  nurse decides whether to run. No treatment suggestions, no autonomous escalation calls.
- **Not clinically validated.** The best published study linking speech features to delirium had
  33 patients. We call the idea promising, not proven.
- **Synthetic residents.** Every resident record in the repository and demo is fictional and
  labelled synthetic. No real patient data is used.
- **The runner proves the pipeline, not the medicine.** A teammate's real voice during exertion
  shows that the system measures physical change against a personal baseline; it says nothing
  about delirium. [Keep only if the runner segment runs; BL-15 is on hold.]
- **Privacy.** Audio is deleted after processing unless a developer flag is set; the four
  measurements, the transcript and word timings are stored with the check. A real deployment would need consent and Canadian hosting.

## Built with

python, fastapi, pydantic, postgresql, timescaledb, pgvector, faster-whisper, webrtcvad,
praat-parselmouth, ffmpeg, localstack, gemini-api, html, css, javascript
[Add docker, caddy, vultr, godaddy only if BL-20 hosting is actually used.]

## Prize-track notes

Only select a track where the "claim we can make" column is true when you submit.

| Track | Fit | Claim we can make | Do not claim |
| --- | --- | --- | --- |
| PointClickCare: Catch It Early (primary) | Direct: early change, care-team interface, explains why | Per-resident speech change, record-aware verdict, cited evidence, interruption budget | Real PointClickCare or Vox integration; clinical accuracy |
| Project KAZE | Only via the "Baseline Out" extension | Design and spec only, unless BL-25 to BL-29 merge and the two-phone loop works | That KAZE sessions, texts or acknowledgement work today |
| Best Healthcare & Well-being | Good | Decision-support prototype on synthetic data | Diagnosis, validation, patient outcomes |
| AI for Social Impact | Good | Staffing-pressure framing; dignity and consent design | Measured impact |
| MLH Best Use of Gemini API | Moderate | Gemini (OpenAI-compatible endpoint, strict JSON schema) tags note context; server verifies every quote; keyword fallback. Manual `gemini-3.5-flash-lite` strict schema-connectivity smoke passed twice on 17 Oct (recorded in `docs/build-status.md`, validation ledger; not run in CI, and it covers those requests only, not note/SBAR quality); re-confirm before submission | That Gemini decides verdicts, or that it ran live on stage unless it did. SBAR sentence assembly (BL-12, merged) only if shown running against Gemini |
| MLH Best Use of Tiger Data | Moderate, be precise | Runs on the TimescaleDB image; `time_bucket` builds the daily overview and sparkline series | That `voice_checks` is a hypertable: it is a plain table because chunk tables bypassed RLS (decision 004) |
| MLH Vultr / GoDaddy | Only if used | Hosted on a Vultr VM with a GoDaddy domain | Anything, unless BL-20 is deployed that way |
| Overall Top 3 | Yes | | |

## Links

- Code: https://github.com/ruandee/patient-memory-backend (public only after the visibility change)
- Demo video: [URL after upload]
- Live demo: [URL only if BL-20 is accepted]
