# Baseline frontend release ? 18 October 2026

The user approved deployment and requested resident search before activation. The initial
release source was `20be74b487d671652a643f8fa71af9562e20bc86`, deployed to
https://baseline.deeruan.com/unit. Use [tracker #38](https://github.com/ruandee/patient-memory-backend/issues/38)
for the current running commit/image after follow-up visual changes.

## Scope and evidence

All seven frontend areas/fifteen screen types share the flat visual direction, locally hosted
Nunito, compact layouts and clear controls. Unit search includes stable residents, searches
only authorized names/references, preserves server order and leaves unit totals unchanged.
The user subsequently requested fewer dividers: decorative panel, row and section rules are
removed; control boundaries, focus indicators and meaningful active states remain.

The initial source passed [Backend CI](https://github.com/ruandee/patient-memory-backend/actions/runs/39097615801)
(667 unit tests, five optional deselected; 383 service-backed tests; migrations; stub evaluation)
and [image smoke](https://github.com/ruandee/patient-memory-backend/actions/runs/39097615805).
Local Node verification passed 165 cases. Three fixture Chrome suites covered 27 core,
five presentation and 24 further desktop/phone scenarios, plus generated-audio recording
admission/result/withdrawal checks. The contrast spot check is not a full accessibility audit.

Twelve public HTTPS checks passed after activation: unit search and stable-roster discovery,
source readback and nurse readiness/recorder at 1440px and 390px; PSW score-free due list with
watchlist denial; camera-off movement; KAZE stored permission; inactive acknowledgement;
creation/read/removal of an own ephemeral demo room; and public JS/CSS/font byte comparison.
No physical microphone/camera, generated question, provider or SMS acceptance was exercised.
Ignored `artifacts/release/` contains the detailed local operational evidence and screenshots.

## Operations and retained boundaries

Only the API container was recreated, with existing private settings and volumes. The database,
object store, Caddy and workers were retained. Stored voice-check counts and identifier
fingerprints matched before and after. No reset, loader, migration, baseline enrollment or
permission decision was performed during this UI rollout. Older rehearsal-room capability
links expire when the API restarts; open `/unit?demo=handoff` to make fresh links.

The approved source was archived/built in a separate release directory. The server checkout
was then synchronized to that source from an authorized Git bundle; no Git credentials were
copied to the server. The current image also has the normal `patient-memory-demo:local` tag.
The preceding image is retained as `patient-memory-demo:rollback-before-frontend-20261018`.
An API-only rollback Compose override is stored beside the release on the host; preserve
private configuration and volumes and never use `down -v` for rollback.

Newer main documentation and shared JavaScript-runner cleanup were preserved in the PR.
The shared runner includes every JS suite; the two new thin Python wrappers were removed
because their suites are discovered there. The merged local unit run passed 652 cases with
five optional deselected, without dropping the 165 Node cases. Its CI is recorded on PR #123.

Physical-phone/LTE recording, resident/staff usability, movement accuracy/timing, hosted
latency, real SMS and rehearsal remain separate unverified acceptance gates. This is a
synthetic research prototype and not clinical validation.
