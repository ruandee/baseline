# Frontend redesign inventory

The user expanded the redesign review to every frontend area on 18 October 2026.
Seven product areas contain fifteen screen types; loading, empty, permission, recording,
error and success states are additional states, not additional screens.

| Area | Screen types and entry points | Current redesign evidence |
| --- | --- | --- |
| Notes workspace (1) | `/`: resident picker, timeline, handover, questions, source dialog | Functional workflow integration and flat Nunito styling; desktop/phone fixture checks passed |
| Unit overview (1) | `/unit`: priority worklist and full roster | Functional worklist, compact row layout and inline summary; desktop/phone fixture checks passed |
| Staff resident details (1) | `/resident/{id}`: measurements, evidence, context, SBAR/export | Flat findings/charts/evidence layout and resident-specific navigation; desktop/phone source readback and API failure checked |
| Voice checks (4) | Nurse hub `/check?nurse=1`; staff recorder `/check?mode=live` or `mode=runner`; PSW due list `/check`; resident guided recording `/check?mode=resident&patient={id}` | Nurse hub verified with blocked/error/recovery states. Ready recorder folds setup forms; blocked setup stays open. PSW due list and resident drawing/permission/refusal views checked on desktop/phone |
| Movement (2) | Staff `/check?type=motion&mode=live`; resident `/check?type=motion&mode=resident` | Both variants iterated with plain preparation language, camera-off preview hidden, and cancel controls. Desktop/phone permission denial checked with zero media calls; physical measurement acceptance remains unverified |
| KAZE safety (3) | Arm/permission form `/out`; active/judge session `/out/session/{id}`; contact acknowledgement `/ack/{token}` | Grouped arm form, separate stored permission, flat session timeline and warm contact acknowledgement. Desktop/phone unknown-permission blocking, active session and four acknowledgement states verified; no SMS sent |
| Presentation demo (3) | Nurse room `/unit?demo=handoff`; phone capture `/check?demo=handoff` with role/room fragment; legacy `/check?mode=live&demo=legacy-days` | Nurse room and phone layouts iterated; five Chrome fixture checks cover context, handoff, generated-audio receipt and expired-room cleanup. Legacy layout and fiction disclosure reviewed at both widths; authored outcomes remain explicit |

## Design decisions

Use the accepted flat clinical direction with a warm, locally served Nunito typeface, compact
worklists and fine separators. Avoid bevels, oversized dashboard cards and excessive whitespace.
The resident experience can use a few original line drawings and gentle color. Preserve adult
language, optional participation and visible consent/unknown states. The user accepted the
resident illustration and requested rounder typography; later feedback requested a denser unit.

The research board and isolated concepts live in `docs/design/`. Those concepts are not the
runtime app. In particular, the resident concept's proposed send-or-discard step after automatic
stop is not implemented by this visual milestone: the actual recorder still sends on Stop or
its time limit, and Skip while listening discards. Runtime disclosure describes that behavior.

## Verification and release

At this working milestone, the actual three-workflow Chrome fixture verification passed 27
checks at desktop 1440px and phone 390px. Source dialogs, questions, handovers, loading/empty/error,
permission-blocked and stale-selection guards were exercised without a microphone, remote
provider or clinical API. Screenshots are in ignored `artifacts/workflow-browser/`.
The fresh local regression passed Ruff, 667 unit tests (five optional tests deselected), and
165 JavaScript checks. Demo browser checks used a WebAudio oscillator, never a physical
microphone, and intercepted two JSON receipts containing only duration and request ID.
The prior functional base `8012dba` passed backend and image CI; that is not exact-head acceptance
for these new visual changes. Record fresh regression results and final CI before release.

All fifteen screen types now have a first implementation/review pass. User feedback can
require further iteration; this is engineering preparation, not final user acceptance. The
extended browser audit passed 24 checks and saved 28 screenshots in ignored
`artifacts/full-direction/`, with zero physical-media, remote or page-error events. The
acknowledgement page uses an exact stylesheet hash in its restrictive CSP; no script or
external assets are permitted. Coordinate the proposed release with the user. No deployment is authorized by acceptance of a visual concept.
Physical-phone, resident/staff usability and clinical validation remain separate acceptance.


The final audit also exercised the staff recorder in actual Chrome at both widths, using two
WebAudio-generated takes per width. Four multipart uploads were intercepted, all audio tracks
ended, enrolling/missing-verdict states remained explicit and withdrawn permission blocked the
next microphone attempt. Speech measurement definitions are available on demand in the staff
record; the roster explains that its change score is not a probability or diagnosis.

The proposed combined release also contains the previously prepared reset-wrapper recovery
fix inherited from draft #119: it retains strict reset refusal and original failure status,
then attempts to restore service after safe earlier preparation. See its dedicated regression
coverage; no reset or deploy is performed by the frontend review.

A rendered contrast spot check found and corrected low-contrast secondary Notes/Unit labels
and navigation symbols. This narrow computed-color check does not establish full WCAG
conformance, keyboard/screen-reader acceptance or successful use by residents.


Unit search (requested before deployment): name/reference filtering uses only the authorized
watchlist response and session references, preserves server order and leaves whole-unit totals
unchanged. Matches include stable residents and separate capture identities; searching opens
the matching full roster. Query text survives polling. Authorization denial clears the cached
searchable snapshot; no-match is distinct from an empty assignment list or failed load.
A 64-person synthetic roster regression covers filtering and stable-resident discovery.

Ontario's official 2023 Niagara-on-the-Lake project describes resident home areas of up to
32 residents, larger than the twelve-person demo cohort. This is an example, not a universal
ward-size claim: https://news.ontario.ca/en/release/1003684/ontario-breaks-ground-on-long-term-care-home-in-niagara-on-the-lake

The user explicitly approved deployment, then requested unit search before release. That
authorization persists for the combined candidate. Final CI must pass before the approved
release is activated; existing data/baselines and private server configuration are preserved.
