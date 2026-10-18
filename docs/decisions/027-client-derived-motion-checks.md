# 027: Client-derived motion captures and scoped observation publication

Status: implemented for engineering review (BL-34); exact-head integrated CI and camera acceptance required.

Motion uses a separate motion_check consent scope. No consent row means unknown and blocks
capture admission. The plain motion_checks table follows decision 004: composite tenant/patient
keys, forced RLS, append-only capture fields, no runtime UPDATE/DELETE. Clinical readers require
care scope; trusted patient-scoped scoring may read inputs for PSW capture while responses expose
only a score-free receipt. Baseline enrollment is care-team only.

Only derived numeric observations and quality counts enter this endpoint. No video, image,
landmark trajectory, device log or model request is stored. Names explicitly identify values as
client-derived measurements, not verified clinical observations. Feature floors are engineering
assumptions: stand time 0.2s (spec), normalized sway 0.01 and cadence 3steps/min. Speech policy is
unchanged. The quality gate requires at least 80% confident frames; incomplete rise/steps remain
unknown, never zero or a fabricated measurement.

Narrow security-definer helpers construct an exact observation payload from a persisted usable
capture, verify the stored motion consent and trusted patient scoring scope, and publish only
that payload. The backend stages its exact UTF8 JSON bytes in immutable object storage first;
the publisher checks payload equality, deterministic object key and computes the content hash.
Three facts cite exact Unicode spans in the resulting canonical text. These sensor facts have
zero hash-vector entries and remain lexical candidates; no semantic embedding claim is made.
No generic source/fact write policy is added for nurses or PSWs.

Publication preserves ingestion.bump semantics: increment patient revision, clear answer caches,
and invalidate/scrub earlier assessment snapshots. Cross-modal corroboration reprojects eligible
immutable raw capture/history under the current revision using decision 025's trusted projection
registry; it never revives an old verdict or rewrites an invalidated snapshot. Retraction/purge
and visibility changes retain the ordinary source lifecycle and evidence withholding.

The planned browser path uses a pinned, self-hosted MediaPipe package/WASM/model in a local
worker, with no remote asset load or video upload. Synthetic landmark tests and mocked camera
lifecycle checks establish engineering behavior only. Actual camera/browser performance and the
judge obtaining three measurements in under 15seconds remain external acceptance gates.


Browser measurement protocol pose-chair-steps-v1 uses a 10-second capture, at most 30 processed
frames per second, and visibility/presence 0.5 for both shoulders, hips and ankles. Initial/final
0.8-second hip medians define travel; travel below 0.05 normalized image height is incomplete.
Rise time is from the 10% to 50% travel crossings after the seated lead-in. Standing shoulder
midpoint SD is divided by median shoulder width (minimum 0.03 image width). Smoothed ankle-height
peaks require 0.01 prominence and 0.25s per-ankle separation; at least three distinct peaks are
needed for cadence. These are engineering extraction assumptions, not validated movement tests.

The motion page offers explicit person/SDM granted/declined/withdrawn consent recording to care
team roles only; PSWs cannot record consent or enroll baseline captures. Readiness is rechecked
before camera permission and measurements are rechecked at storage. Cancellation, patient
switching, page exit, errors and the 10-second limit stop tracks; permission/model responses from
cancelled operations cannot restart capture. No MediaRecorder, image upload or video blob is
created. Low quality and incomplete actions have explicit null measurements and no assessment.

MediaPipe tasks-vision 1.1.1 is pinned by the NPM archive SHA512 and a committed per-file SHA256
manifest. The official pose_landmarker_lite float16/v1 task is pinned by SHA256. JS, all WASM
variants and the model are served from assets/vendor/mediapipe. The page keeps its existing
script restriction; Emscripten/WASM compilation is allowed only by the isolated local worker's
response CSP, whose connections and scripts remain same-origin. No CDN is configured at runtime.
Model preparation occurs before the timed capture; device cold-start and live performance are
separate acceptance measurements, never inferred from package installation or geometry tests.

Source purge's protected trigger removes the matching duplicate raw motion row and its own
assessment. No direct runtime capture UPDATE/DELETE capability is introduced. Standard source
retraction/supersession/visibility checks withhold capture readback and future corroboration.
OpenAPI is regenerated; LF normalization of the prior CRLF export is included.


A headless Chrome 155 smoke exercised the actual module worker and deployed response CSP with
no camera permission requested. Selecting the module WASM fileset is required: the classic
loader otherwise fails with `ModuleFactory not set`. The corrected local WASM/model graph
initialized in 606 ms; a model 404 left Start disabled with a clear failure. Both cases made
only same-origin GET requests and no camera requests. This is model preparation evidence,
not physical-phone capture or end-to-end latency acceptance. Playback stalls are covered by
the camera deadline, and cancellation settles pending playback/inference without submission.


The closed SQL publisher requires both checker authorization and an explicitly true scoring
context. Its definer guard uses `IS NOT TRUE`: an unset custom setting can produce SQL NULL
and must reject, rather than falling through a three-valued `IF NOT` condition. Contract tests
exercise this boundary for care-team and PSW identities outside the trusted scoring context.
