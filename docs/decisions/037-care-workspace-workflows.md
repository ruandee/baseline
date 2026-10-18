# 037: Organize the care workspace around care-team tasks

Date: 2026-10-18 UTC. Status: implemented and initially deployed; see frontend-release-2026-10-18.md.
Scope: BL-16 frontend cohesion, with existing BL-17/18/19 behavior preserved.

Visual review update, 2026-10-18: the user rejected the first preview's visual direction.
Functional checks below remain engineering evidence, not visual acceptance. The revised brief
requires actual award-winning healthcare references, flat surfaces without bevels, stronger
typography and restrained information hierarchy. Resident-facing screens should be warmer,
with a few original minimal drawings and empathetic, explicit choices. The isolated concepts
in `docs/design/` established the accepted direction; it is now applied to the functional
application. The concepts make no API calls or media recordings. Deployment remains separate.

## Problem and decision

The unit view, notes workspace and recorder had different navigation, terminology and visual
hierarchies. A nurse could reach a recording screen without first seeing whose record, permission
and comparable history would be used. The notes workspace emphasized implementation details,
used a cramped mobile resident list and showed a fixed January record horizon on a hosted
October cohort. A visual refresh alone would not fix those workflow and time-context problems.

Use one care-team navigation order with a flat header, locally bundled Nunito type, warm
neutral surfaces, restrained green/ink controls and compact rows separated by fine rules. Keep the unit list, notes review and nurse voice-check preparation
as separate tasks with clear headings, labelled controls and visible loading/empty/error states.
Movement and the visibly labelled presentation demo remain secondary destinations.

The unit overview preserves the API's ordering, clinical status, follow-up and source links.
Resident detail links carry their assigned resident into the notes workspace. Guided resident
checks remain a separate, score-free experience; this is not a new resident portal.

## Workflow and contract boundaries

- `/` finds an assigned resident, displays the record timeline or shift handover, and answers
  questions with exact-source inspection. Medication-event filtering, patient-reported attribution,
  incomplete coverage, unknowns and unresolved conflicts remain visible. Source identifiers,
  character offsets and generation metadata are available through secondary disclosures rather
  than occupying the main review path. Keyboard tabs, focus and practical retry controls are
  part of the workflow.
- `/?patient=<id>` opens only an exact match in the authorized session roster. An unavailable,
  blank or ambiguous explicit identifier opens no other person's record and fetches no clinical
  endpoint until the user explicitly chooses an assigned resident. Missing optional reference or
  suggested-question fields do not make an otherwise authorized record unusable.
- Hosted `/demo/session` returns `snapshot_mode: "current"` and the current UTC `as_of` value
  when hosted mode is configured. Local fixed-fixture mode returns `snapshot_mode: "fixed"`
  with `2026-01-03T00:00:00Z`. Notes timeline and question requests retain that explicit cutoff.
  Current mode initializes a user-editable 24-hour handover window ending at the session cutoff,
  to UTC minute precision. It is a convenience default, not a clinical shift definition. Date
  edits survive resident changes and session retries, including edits made during bootstrap.
  Fixed mode retains January 2 to January 3. Summary requests continue to send explicit dates.
- `/check?nurse=1` uses the nurse bootstrap for an assigned-person picker and read-only
  permission/profile/history preparation. Its recording action hands off to the existing guarded
  recorder. It does not silently configure a profile, grant consent, enroll a person or create a
  check. Plain `/check` retains the PSW bootstrap and score-free guided flow.
- `/check?type=motion` retains the local capture implementation and explicit client-derived,
  unverified measurement boundary. Ten deterministic motion JS checks passed in the audit;
  physical chair-to-three-measurements acceptance remains unverified.
- `/unit?demo=handoff` remains the separate authored phone-to-nurse presentation in decision036;
  its receipt transport is not a clinical measurement or genuine personal baseline. The legacy
  local simulation and decision034 disclosures remain separate. This redesign does not change
  the validated-draft contracts in decision014 or the existing demo-room capability boundaries.

No API authorization, role permissions, scoring, thresholds, consent, provider behavior, evidence
eligibility, request cutoffs or asynchronous response ownership is relaxed. An unavailable
record/service is an error, never a negative finding. The new nurse entry point does not broaden
PSW access, and source access is still authorized again by the evidence API.

## Design sources and interpretation

[W3C's consistent-navigation guidance](https://www.w3.org/WAI/WCAG22/Understanding/consistent-navigation.html)
explains the value of keeping repeated navigation in a predictable relative order. We apply it
to the common care-team menu and current-page indication. This is design guidance, not a claim
that the application has passed an accessibility conformance audit.

[W3C's labels and instructions guidance](https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html)
supports naming the resident search, question and UTC shift inputs so users know what to enter.
[W3C's page-structure tutorial](https://www.w3.org/WAI/tutorials/page-structure/)
informs labelled navigation, main content, record sections and headings.

[Nielsen Norman Group's progressive-disclosure guidance](https://www.nngroup.com/articles/progressive-disclosure/)
informs keeping the primary review actions visible while moving technical identifiers and
provider metadata into inspectable detail. Clinical uncertainty, conflicts, permission blockers
and synthetic/demo labels are essential information and stay in the main workflow.

These are engineering interpretations of published design guidance. They do not establish
clinical usability, improved outcomes or successful testing with residents and care professionals.

## Engineering acceptance and remaining evidence

Local integrated deterministic JavaScript verification reported 161 passing scenarios, including
notes request-scope/race guards, assigned-only deep links, current/fixed cutoff behavior and
user-edited handover dates. The movement audit's ten JS scenarios passed. At functional head `1f824cf`, the fresh full unit suite passed 667 tests with five optional
tests deselected. Database-backed, evaluation and image checks remain pending in exact combined
CI; record that final head and CI result before declaring the integration accepted.

Independent actual headless Chrome verification at the functional integration passed 25 checks
across desktop 1440px and phone 390px views of all three workflows, with six screenshots saved
in ignored `artifacts/workflow-browser/` under the integration worktree. The reviewed layouts
were cohesive. There were zero media calls, remote calls or page errors; question and summary
POSTs were fixture responses only. These checks use synthetic fixtures and do not establish
real-backend response quality, physical microphone capture or user acceptance. Maintain
regressions for navigation/current-page state, resident selection, source readback, keyboard
tabs, empty/error/retry states and handoff to the guarded recorder.

Deployment is a separate operator action. No live upgrade, physical iPhone/Android/LTE capture,
chair timing, screen-reader/user study or rehearsal is established here. Existing external gates
remain open, as does the distinction between authored demo outcomes and real measurements.


### Typography feedback ? 18 October 2026

The user accepted the revised visual direction and resident illustration, requesting slightly
more warmth and a rounder font. The static concept previews now use locally served Nunito
(variable weight), with its SIL Open Font License in `docs/design/fonts/OFL.txt`. Resident
buttons have a restrained 8px corner radius; the flat staff layout stays intact. This is a
concept revision, with no runtime recording, consent, scoring or deployment change.

The next review found excessive blank space in the unit concept. Desktop rows now use a
78px minimum (previously 108px), with tighter heading/summary spacing, 3% outer gutters and
a closer 320px context pane. Text contrast and secondary type size were increased rather
than shrinking text to achieve density. Phone rows retain an 88px minimum and 44px controls.


### Runtime visual milestone and expanded review

The accepted flat direction now reaches the functional shared header, compact unit worklist,
notes desk and nurse hub. Nunito and its license are bundled in `frontend/fonts/`; no font
service is contacted. The resident recorder gains the original line drawing, warm surfaces,
truthful recording disclosure and optional retry language. Consent blocking hides the prompt;
completion hides old instructions. Capture, automatic submission, cancellation and scoring
logic are unchanged. The runtime disclosure explicitly describes Stop/time-limit submission,
rather than claiming the concept's unimplemented post-stop send/discard choice.

The user requested iteration on every frontend piece. `docs/frontend-redesign.md` now lists
all seven product areas and fifteen screen types, including movement, KAZE contact
acknowledgement and both current/legacy presentation surfaces. Shared typography alone does
not mark those detailed workflows visually accepted.


### Remaining-screen implementation pass

Staff resident details now use flat charts/findings/evidence and resident-specific links back
to notes and voice readiness. Ready staff recording folds setup forms into a native disclosure;
blocked setup remains open without granting permission. Resident refusal is acknowledged before
staff reason entry, with old prompt text hidden. Existing capture/upload/cancel logic remains.

Movement uses Get ready before Start, describes preparation without model jargon, and keeps the
empty camera preview hidden until capture starts. Cancel and failed readiness leave it hidden.
The browser audit denied readiness and made no media calls; real pose quality, chair timing,
physical-phone capture and the under-15-second acceptance are still unverified. The local model
may require preparation time and is not warmed automatically.

KAZE arm fields are grouped into plan and contacts; stored permission stays distinct. Session
controls/timeline use the shared system. Contact acknowledgement remains self-contained, with
no scripts/external resources: its CSP allows only the SHA-256 hash of its exact inline style.
This changes presentation policy only, not token consumption, acknowledgement behavior or
contact messages. The legacy simulation also uses flat capture/controls and visible fiction.

Actual headless Chrome checked 24 additional desktop/phone scenarios and saved 28 screenshots
for these screens, with zero media calls, remote calls or page errors. Its source data and
session responses were intercepted fixtures. This does not demonstrate real SMS, live-provider,
physical-device or resident usability acceptance. All fifteen screen types now have a first
pass; final user review and exact-head CI remain release conditions.


Before deployment the user requested unit search for larger wards. The search filters only
already authorized visible names/session references, keeps server ordering and unit-wide
counts, includes stable residents and persists across polls. Denial invalidates the searchable
snapshot. No new API query, ward model, authorization grant or clinical sorting is introduced.


The user approved deployment; source `20be74b` passed CI and hosted checks. Their subsequent
request removes decorative section, row and panel borders while preserving control/focus and
active-state cues. Deployment and later polish are tracked separately from clinical or
physical-device acceptance.
