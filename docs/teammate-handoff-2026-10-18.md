# Baseline teammate handoff: outstanding work

Snapshot: 18 October 2026 UTC. Repository: `ruandee/patient-memory-backend`.
Inspected main: `1d7249fcb6847b81fd43ecf035504178f286f4bc`.
This is an evidence-based task inventory, not a new implementation or deployment.
Branches are actively changing: refresh GitHub before claiming work.

## Start here

The core backend, speech pipeline, personal-baseline change engine, context/evidence,
watchlist, resident details, consent/profile handling, KAZE, motion, vitals and preliminary
handoff export are implemented. The largest remaining work is finishing the frontend
redesign, consolidating overlapping PRs, and proving the actual demo on phones.
An open acceptance ticket does not necessarily mean its feature needs building again.

Read `AGENTS.md`, [build status](build-status.md), [Baseline spec](06-baseline.md),
[product context](07-baseline-proposal.md), and the relevant decisions before coding.
Older untracked `for dee claude.md` and `claude-handoff-2026-10-17.md` contain historical
queues; do not use their ownership or unmerged-feature claims as current instructions.
The original product goal was paused and handed to recovery thread
`01a14c66-8b44-7550-a30e-b5d61364934e`. Coordinate with its operator; this handoff does not
restart that goal, its old agents, recordings, or server mutations.

## What was verified for this handoff

- GitHub open issues, open PR bodies/files/checks, main CI, repository visibility and tracker #38.
- Main's spec, acceptance audit, deployment/presentation guides, rehearsal checklist and decisions.
- The latest frontend branch's `docs/frontend-redesign.md`, which is broader and newer than
  its original PR description. The redesign now covers seven areas and fifteen screen types.
- Read-only SSH: the server checkout is clean at `204f545b0e52db96c4a7fa4e464084aa1cf223fd`.
  API, database and object store report healthy; Caddy and both workers are running.
- Public HTTPS returned 200 for `/unit`, `/check`, `/unit?demo=handoff`, `/out`, and
  `/v1/health/live`. Every script and stylesheet referenced by `/unit` returned 200.
  The scripts live under `/assets/`: requesting `/check-setup.js` at the root gives 404
  and does not prove a broken deployment.
- Main backend CI [39094977533](https://github.com/ruandee/patient-memory-backend/actions/runs/39094977533)
  passed at `1d7249f`. PR checks below are snapshots, not permanent approvals.

No new recordings, clinical API writes, resets, deployments, provider calls or SMS were
performed for this audit. No fresh local runtime test suite was run for this document.
The host checkout and public responses do not independently prove its image's source SHA,
personal-baseline enrollment, phone behavior or end-to-end readiness.

## Work order and useful division of ownership

| Priority | Workstream | First concrete action | Done when |
| --- | --- | --- | --- |
| 1 | Frontend owner | Continue the active redesign in #123, coordinate with #119's owner | All fifteen screens and meaningful states reviewed; visual approval, exact-head tests and CI recorded |
| 1 | Integration owner | Map #108–#113/#118/#119/#122 overlap before merging | One reviewed release contains intended fixes, current docs and no duplicated/stale changes |
| 1 | Demo operator + presenters | Rehearse the selected phone-to-nurse flow on actual HTTPS phones | Real capture/playback, receipts, context, second submission, guidance and new-room reset all work |
| 2 | Speech/QA owner | Confirm whether genuine measured comparison is required in addition to the scripted demo | If required, enroll the same consenting speaker and verify a real scored upload/readback |
| 2 | Ops/QA owner | Preserve live recordings; verify reset recovery and measure hosted latency | Refusal cannot leave services down; successful safe fixture reset and actual upload timing documented |
| 2 | Submission owner | Finalize talk track, video, rehearsals, publication and Devpost | Two clean runs, accessible backups and actual submission confirmation |
| 3 | KAZE owner | Confirm scope, approved contacts/provider and actual two-phone test | Real SMS/ack loop and two rehearsals, or describe honestly as an unvalidated prototype |
| 3 | Motion/Vox/usability owner | Test existing features rather than rebuilding them | Physical movement, consented mock encounter and nontechnical-user gates recorded |

Assign a single operator for the VM and a single integrator for shared frontend files.
Separate worktrees are appropriate for independent work; two agents must not edit the
same branch/worktree or reset the same host concurrently.

## Open PRs: integrate deliberately

All links below are in this repository. Green CI is engineering evidence, not visual
approval or human/phone acceptance. No current PR had an approving review decision in
the inspected list.

| PR | Snapshot | What the teammate should do |
| --- | --- | --- |
| [#123](https://github.com/ruandee/patient-memory-backend/pull/123) | Draft, head `96df5b9`; backend/image checks running when inspected | Active visual redesign, stacked on #119. It now changes runtime styles/recording copy as well as concepts. Read its inventory and current diff; do not rely on the original static-concept-only body. Finish the outstanding screens and request final visual acceptance before release. |
| [#119](https://github.com/ruandee/patient-memory-backend/pull/119) | Draft, `8012dba`; backend and image checks passed | Notes, unit worklist and nurse-check workflow foundation; includes earlier integration/reset changes. Preserve the functional work while finishing #123's accepted direction. Do not merge as the finished visual redesign just because CI is green. |
| [#122](https://github.com/ruandee/patient-memory-backend/pull/122) | `2fd245f`; backend checks passed | Review test-runner consolidation separately. It reports 646 units, 128 unchanged Node cases and 383 DB-backed tests. Reconcile added frontend suites when integrating; a lower wrapper count is not lost scenario coverage. No runtime deployment needed for this alone. |
| [#118](https://github.com/ruandee/patient-memory-backend/pull/118) | `b6c2c66`; backend checks passed | Documentation-only correction of current deployment/frontend handoff. Preserve accurate facts while reconciling newer redesign and presentation notes. |
| [#113](https://github.com/ruandee/patient-memory-backend/pull/113) | `940b922`; backend/image passed | Integrates #106/#108/#109/#110/#111/#112. Review whether its changes are already carried by #119; merge through one path, then close superseded PRs with an explanation. Its deployment wording is older than the verified `204f545` host. |
| [#112](https://github.com/ruandee/patient-memory-backend/pull/112) | Draft, `c57de0d`; backend/image passed | Reset-refusal service recovery, already included by integration work. Preserve the original nonzero reset result and strict data guards. Do not weaken reset protection. |
| [#111](https://github.com/ruandee/patient-memory-backend/pull/111) | `e352a9d`; backend passed | Golden-run evidence only, incorporated by integration work. Decide #8 acceptance from its revised actual done-when, not phone/latency gates. |
| [#110](https://github.com/ruandee/patient-memory-backend/pull/110) | `2acb01d`; backend/image passed | Withholds usual-range copy until a real current scored comparison exists. Preserve through redesign and integration. |
| [#109](https://github.com/ruandee/patient-memory-backend/pull/109) | `cdad1a3`; backend passed | README/tracker refresh included by later integration. Reconcile outdated deployment/presentation references. |
| [#108](https://github.com/ruandee/patient-memory-backend/pull/108) | `258a1f6`; backend/image passed | Earlier UI polish and external-document navigation fix. Some fixes already reached main through other integration. Diff against current main; do not restore the rejected old visual direction or close #107 prematurely. |

The Devpost edits are already on main through #106/#116/#117/#120/#121. Preserve the
user's research-linked inspiration, 30-second window, personal-baseline emphasis,
dementia-care audience and end-to-end diagram when resolving older branches.
Do not restore an older long technical draft. The repository is still **private**.

## Frontend: remaining implementation and acceptance

Source of truth for the active iteration: `docs/frontend-redesign.md` on
`bl/bl-16-award-directed-concepts` (#123), plus its ADR037 and current user feedback.
That document is not yet on main. Its latest inventory says these are required scope:

| Area | Remaining work |
| --- | --- |
| Notes `/` and unit `/unit` | Existing functional/styling work has fixture evidence. Finish current density/type/layout feedback; preserve evidence, errors, unknown states, selection races and API ordering. |
| Resident details `/resident/{id}` | Detailed visual/interaction review: charts, baseline/current comparison, sources, action guidance and preliminary draft/export. |
| Four voice-check screens | Verify nurse hub `/check?nurse=1`, staff recorder, score-free PSW due list, and guided resident recording. Complete expanded resident visual review and permission/loading/retry/success/decline states. |
| Two movement screens | Iterate and browser-check staff and resident variants, including consent, model startup/failure, cancel and missing results. |
| Three KAZE screens | Dedicated visual work and synthetic workflow checks for arm/permission, active session/timeline, and contact acknowledgement. Preserve capability boundaries. |
| Three presentation screens | Finish nurse room/phone flow acceptance and the legacy presentation review. Keep authored-result disclosure visible. |

Latest branch notes describe accepted flat styling, rounder locally served typography,
compact worklists and an original resident illustration. Do not restart design discovery
without reading the latest feedback. Screen loading, empty, blocked, stale, denied and
error states matter as much as a populated screenshot.

The concept's post-stop **send/discard** step is still not implemented in the ordinary
recorder at the inspected milestone: Stop/time limit sends; Skip while listening discards.
The presentation recorder is a separate flow with playback and explicit submission.
Do not silently promise or change ordinary recording behavior. If adopting send/discard,
confirm that direction and add meaningful cancellation, late-callback, consent-change and
one-retry regressions. Never expose clinical scores in resident/PSW mode.

Final acceptance requires screenshots on desktop and phone widths, keyboard/focus review,
no overflow, the appropriate JS/authorization tests, and nontechnical-user/physical-phone
testing. Headless fixture screenshots alone do not satisfy those last gates.

## Demo: keep scripted presentation separate from measured detection

The selected presentation is [decision036](decisions/036-phone-to-nurse-demo-handoff.md),
documented in [live-voice-demo.md](live-voice-demo.md): `/unit?demo=handoff`.
Two phones record/play back real clips; only duration and request ID are submitted.
**The audio is not analyzed on this presentation path.** Watch/Explained/Escalate and
baselines are authored fixtures. Exertion is supplied by the nurse, not detected.

Outstanding rehearsal steps: privately distribute separate phone links; confirm microphone
permission and playback; submit runner receipt; add exertion context; submit Dee twice;
review escalation/handoff guidance; start a new room and prove old links fail. Test reload,
expiry, interrupted submission and actual phone codecs. Keep nurse capabilities private.
Rooms expire after two hours, disappear on restart, and require a single API process.
A multi-worker deployment needs a shared room store before this demo can support it.

The legacy one-tab simulation is `demo=legacy-days`. Old `demo=days` opens the replacement
nurse setup. Do not rehearse an obsolete URL from an older checklist.

If the team also wants **genuine measured personal-baseline detection**, #17 remains:

1. Confirm the consenting speaker; use their own separate capture patient/device, supported
   English profile/version and current explicit voice permission. Do not use a scripted
   resident or mix speakers. Preserve the capture identity's no-escalate configuration.
2. Obtain five distinct usable rested takes, not five copies or acted slow/pausey clips.
   Use `scripts.enroll_voice_baseline` and private session files per the live guide.
   A previous hold delegated actual enrollment to a teammate; this audit did not lift it.
3. Inspect partial receipts before retrying a timed-out POST; do not blindly replay a set.
4. Submit a real live check for the same person/device/prompt and verify actual authorized
   baseline selection, features, verdict and evidence readback. A normal result is valid.

The engine needs at least three eligible earlier baseline checks; the demo preparation
protocol calls for five distinct takes. Rolling calibration uses up to ten eligible checks
from thirty days, excluding the latest twelve hours. Do not confuse enrollment policy,
the presentation's fictional baseline, and clinical validation.

## Every open acceptance issue

See [tracker #38](https://github.com/ruandee/patient-memory-backend/issues/38).
The following issues were open at inspection; links use issue numbers, not BL numbers.

| Issue / milestone | Outstanding evidence or decision |
| --- | --- |
| #8 / BL-06 | Revised golden protocol has reported local real-Whisper evidence: all four usable, slow lowers rate, pausey raises pause ratio/count; stairs exploratory. Review #111/current integration evidence and accept the revised gate if appropriate. Preserve the original stairs-direction failure. Do not demand a new recording just because an old issue comment says none exist. |
| #9 / BL-07 | Measure actual hosted upload p95 below 5 seconds after warming. Record release, device/format, sample count, total/request and available stage timings. Do not use synthetic timing or engine-only milliseconds as upload latency. |
| #17 / BL-15 | Genuine same-speaker API enrollment and usable live readback, if kept in demo scope; scripted presentation does not close it. |
| #19 / BL-17 | Physical iPhone/Safari and Android/Chrome recording over public HTTPS/LTE; denial, retry, stop/timer, upload/decode and result states. Main capture limit is 30 seconds, whole multipart body 2 MB; encoded duration must not exceed the cap. KAZE retains a separate 15-second recorder. |
| #22 / BL-20 | Final coordinated release, host/token/readiness/asset checks, actual phone/LTE capture and latency. Host/domain already exist; do not provision a second VM by following stale setup text. |
| #23 / BL-21 | Successful safe fixture-only reset under one minute, and refusal/recovery on the actual host. A nonfixture recording in a scripted identity previously blocked reset; preserve it. Never delete history or Docker volumes to manufacture success. |
| #24 / BL-22 | Human decision on repository visibility, publication review and actual Devpost submission/confirmation. The private repository and draft Markdown are not a submitted entry. |
| #25 / BL-23 | Clean-clone setup walkthrough and backup video accessible in two places, including an offline copy; final write-up/demo links verified. Existing draft/shot list is preparation only. |
| #26 / BL-24 | Two full solo presenter runs under four minutes each, with no manual fixes, recorded in the rehearsal run log. Update the older checklist to decision036 before relying on it. |
| #29 / BL-27 | Actual approved SMS recipient receives a real text and opens an acknowledgement link. Default log sender does not send SMS. |
| #30 / BL-28 | Actual two-phone arm/enroll/check/miss/text/ack loop; verify session permission, countdown, delivery labels and end/expiry behavior. |
| #31 / BL-29 | Two KAZE rehearsals and actual chosen Devpost track/section; use staged/recorded material honestly if fitting delayed escalation into a short demo. |
| #33 / BL-31 | A nontechnical tester completes the score-free resident/PSW flow without help; actual-device accessibility and language/profile handling. Do not invent translations for unsupported protocols. |
| #34 / BL-32 | Consenting teammate-voiced encounter fixture through the existing mock Vox adapter, resident-only extraction/quality and consent refusal. No live Vox/PointClickCare integration exists. Overview prompt switching remains on hold. |
| #36 / BL-34 | Physical chair-to-three-measurements flow under 15 seconds plus device/permission/cancel verification. Client-derived movement values remain unverified, not clinically validated. |
| #107 / BL-16 follow-up | Complete the current all-screen redesign and visual/usability acceptance; #108's original polish alone is no longer the whole task. |
| #38 / tracker | Reconcile stale release/PR/acceptance wording after integration; keep human gates open until evidence exists. |

KAZE real SMS needs approved provider configuration and recipient allowlisting in private
environment configuration. Respect the user's credits-only constraint; do not enable paid
calls or SMS where coverage is uncertain. Actual escalation delays remain 5 minutes for first
contact and 10 minutes per further level; do not silently accelerate production timers.
Background push is not implemented; on-page reminders may be browser-suppressed.

## Existing host and deployment boundaries

- URL: `https://baseline.deeruan.com`; Namecheap manages DNS for `deeruan.com`.
- GCP project `baseline-deeruan-demo`, VM `baseline-demo`, zone `us-central1-a`,
  static public IPv4 `35.208.29.79`. Use the existing authorized access method.
- VM repository: `/home/deeruan_r/patient-memory-backend`. Configuration/session files
  are private; do not print or copy credentials into a handoff, issue or command argument.
- Compose operations need **both** `-f compose.yaml -f compose.demo.yaml` plus `.env.demo`.
  The override alone fails because its dependency services are defined by the base file.
- Use [deployment walkthrough](deployment-walkthrough.md), [hosting guide](demo-hosting.md)
  and [deployment path](deployment-path.md). Choose a reviewed immutable release; verify
  image/backend CI, operator coordination and approval before rollout. Concept acceptance
  does not authorize deployment of the current redesign.
- Recheck the configured automatic VM stop time before the presentation. Original setup
  targeted about 21:09 Toronto on October 18; this audit did not inspect the current cloud
  schedule. Persistent disk/static-IP allocation can outlast a stopped VM.
- Private database/object-store/API ports must stay private. Do not run destructive resets,
  `down -v`, reinitialize an existing host, rotate signing secrets casually, or auto-grant
  permission. Refresh expiring demo role tokens with the documented helper.

## Documentation and narrative cleanup

Several main/status/tracker passages still describe old release SHAs, pending already-merged
work, a 15-second core capture, missing public assets at the wrong paths, or the superseded
presentation. Reconcile these through the existing documentation/integration PRs; retain
historical validation as explicitly historical rather than deleting it.

The Devpost describes the genuine product pipeline and dementia-care audience. The chosen
phone presentation demonstrates authored outcomes. Make this difference clear in the video
and talk track; never claim that acted speech or receipt-only submission produced measured
deterioration. Keep "change from personal baseline" separate from diagnosis. Movement,
vitals and contextual records do not establish clinical accuracy either.

Optional Gemini/provider quality is still separate from connectivity smoke and stub CI.
If demonstrating it, verify authorized configured-provider note extraction and grounded draft
fallback on synthetic data, within an approved no-cost budget. Otherwise retain honest
fallback wording. No provider secret belongs in Git or teammates' handoff files.

## Beyond the hackathon: unfinished original-spec areas

The backend B01–B11 implementation does not make it ready for real patient use. Remaining
work includes production identity/source mapping; permissioned EHR/source integration;
clinically evaluated extraction and model quality; semantic embeddings and model token
budgets; human support and untouched-model evaluation gates; queue/load/operations testing;
retention/backup expiry policy; and clinical ownership, consent and hosting decisions.
The patient-diary UI and live EHR writeback are not completed product capabilities. Do not
pull these into a rushed demo or claim diagnostic prediction/treatment functionality.

## Verification and completion report

Use Python 3.12–3.14, uv 0.13.1, Node for frontend checks, FFmpeg and Docker Compose.
For runtime integration mirror the actual CI sequence:

```sh
uv sync --frozen
uv run ruff check .
for f in frontend/*.js; do node --check "$f"; done
uv run pytest tests/unit
docker compose up -d --wait db object-store
uv run alembic upgrade head
uv run pytest tests/integration tests/contract tests/e2e
uv run python -m evals.run --suite synthetic --provider stub --output artifacts/eval.json
```

The JavaScript syntax loop above is Bash; use the PowerShell equivalent on Windows.
Run frontend Node scenarios and exact-head demo image smoke for the final runtime release.
If #122 merges, use its `tests/README.md` for focused commands and preserve all scenario
coverage. Real golden tests are optional/offline and require existing approved local clips;
they are not part of ordinary CI. Keep personal audio, transcripts and private receipts out
of Git. Default tests must not call paid providers.

Each handback should name the ticket, final SHA, changed behavior, actual tests/results,
unrun checks and unresolved human decisions. Attach device/run evidence to its issue
without secrets. Recheck live branch heads and don't close an acceptance ticket from
file existence, a draft PR, an assignee or an unrelated green test.
