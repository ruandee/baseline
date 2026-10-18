# 027: Client-derived motion captures and scoped observation publication

Status: implementation in progress (BL-34); migration 011 schema milestone only.

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
