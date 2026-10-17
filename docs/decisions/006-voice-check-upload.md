# 006: Voice check upload is the one multipart route, capped at 2 MB for the whole body

Status: accepted (17 Oct 2026, BL-07, issue #9). Amends the "API contracts" error table in
`docs/06-baseline.md`.

## In plain words

`PayloadLimit` used to refuse anything that was not `application/json` (415) or larger than
`max_payload_bytes` (413). A voice check is an audio upload, so `POST /v1/patients/{id}/checks` now
accepts `multipart/form-data`, and only that route does. JSON sent to it, and multipart sent to any
other route, still get 415.

## Choices and trade-offs

1. **Oversize is 413, not 422.** The middleware buffers and counts the body before routing, so it
   answers first. The spec said 422; the ticket said 413; the spec table now matches the ticket.
   Undecodable audio is 422 `invalid_audio`.
2. **The cap covers the whole body, not just the audio.** Multipart framing adds a few hundred
   bytes, so audio a little under 2 MB is the real ceiling. A 15 s webm or mp4 from `MediaRecorder`
   is about 100 KB, so this does not matter for the prompt. A raw 44.1 kHz stereo WAV of 15 s is
   about 2.6 MB and is refused.
3. **Care-team roles only.** `pm_care` gates the route, so `patient` and `admin` principals get 404
   before any audio work. Authorization is checked again in the insert transaction, because
   decoding and Whisper take seconds and access can change in that time.
4. **Clips over 30 s are refused.** The prompt stops at 15 s; 2 MB of opus is about 16 minutes,
   which would hold a worker in Whisper for minutes.
5. **Whisper loads at startup, and a failed load is not fatal.** The API still serves everything
   else, and the first check retries the load.
6. **`change` and `assessment` are `null`** until the change engine (BL-08) and the verdict table
   (BL-11) exist; `timings_ms` omits `engine` and `verdict` for the same reason.

## Not decided here

- Concurrency limits on Whisper. Requests run in the threadpool with no cap, which may hurt p95
  under load; measure on the demo host (BL-20) before adding one.
- Auditing denied or failed uploads. No other route does, so this one matches.
