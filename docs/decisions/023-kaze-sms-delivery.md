# 023: KAZE message preparation, delivery claims and public acknowledgement

Status: proposed implementation contract (17 Oct 2026, BL-27). The six held ADR018 product
questions remain undecided. This documents delivery mechanics, preserves the specified public
GET acknowledgement and standard ladder timings, and adds no clinical or safety claim.

Each scheduler step prepares immutable event rows under patient then session row locks. Rendering
uses fixed neutral wording, session name, due/check time, optional last session location and a
256-bit random acknowledgement token. Only SHA-256(token), expiry and text with links replaced
are stored. The public GET `/ack/{token}` marks acknowledgement and returns minimal HTML; POST
is equivalent. No response exposes patient/session/contact identifiers or location. Tokens are
bearer capabilities; GET mutation is the existing spec contract, including its link-preview risk.
No scanner/confirmation policy change is adopted here.

After publication commits, a separate short transaction takes patient, session and event locks,
rechecks access, expiry, current episode, escalation_enabled and state, and sets the once-only
`delivery_started_at` claim (migration 008, after consent migration 007). All locks are released
before invoking the sender. A durable claim cannot be reset, so concurrent calls and retries never
send the same event twice. A later ack/end cannot recall a request already in flight. No external
I/O executes while a DB transaction or advisory lock is held.

The default sender logs only redacted text and masked phone; it retains no live outbox. Neither
raw token links nor coordinates are logged, including sender exceptions. Tests may inject an
in-memory capture sender. Optional Twilio delivery requires explicit `PM_SMS_PROVIDER=twilio`,
complete credentials, HTTPS acknowledgement base URL and E.164 recipient allowlist. Tests force
log settings and exercise HTTP only through a mock transport. Credentials are never committed.

The [Twilio Messages API](https://www.twilio.com/docs/messaging/api/message-resource) uses form
POST to `/2010-04-01/Accounts/{AccountSid}/Messages.json` with To, Body and From or
MessagingServiceSid. A validated successful resource response is stored as `sent`, meaning only
provider acceptance, never proof of handset receipt. `logged` means simulated delivery; `failed`
means a failed/unconfirmed attempt, not proof no recipient could receive a message. A provider
timeout or malformed success stays `pending` (unknown), and no automatic resend occurs. A crash
after claim similarly leaves pending; a crash before claim leaves unclaimed pending. Raw links
cannot be reconstructed from DB, and this implementation does not replay pending outbox rows.
The ladder continues from recorded step times unless acknowledged, checked in or ended.

The public ack function locates only the hashed token, locks its exact session then event, and
reads a fresh DB clock after both locks. Session expiry immediately records ended_at=ends_at and
exact +24h retention before returning invalid. Expired/unknown tokens are invalid; old episodes
record a tap without changing the current episode. Replays and concurrent taps are idempotent.
RLS hides all rows from the unauthenticated runtime connection; the scoped definer is the only
entry point. Pages use no external resources, no-store and no-referrer.

Acceptance remains open: no real text was sent and no verified phone receipt or live public-link
acknowledgement has been demonstrated. Provider-side message retention and hosting choices need
an explicit real-delivery review; local 24-hour DB deletion does not claim to erase a carrier or
recipient's message history.
