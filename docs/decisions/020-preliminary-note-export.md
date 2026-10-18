# 020: Preliminary SBAR export and separate human draft editing

Status: implemented for review (BL-33); frontend mounting and integrated acceptance remain open.
No external sign-off queue or clinical-system write is authorized or implemented.

## Server projection

`GET /v1/patients/{id}/assessments/{aid}/note` returns `application/fhir+json`: a FHIR R4
`DocumentReference`, `status=current`, `docStatus=preliminary`, type text exactly
`Baseline change-of-condition draft`. The base64 UTF-8 attachment copies every stored SBAR
sentence verbatim and in stored order, prefixed by its S/B/A/R section. The attachment records
its byte size and SHA-1 hash as specified by the R4 Attachment datatype. Nothing is signed.

The payload retains synthetic/draft labels, patient, assessment/check identifiers, source revision,
drafting source, timestamps, per-sentence citations and distinct fact versus voice-check reference
systems. References are logical identifiers for the synthetic system, not a claim that an EHR
contains matching FHIR resources. No model runs during export; it projects the validated stored
draft from decision 014. Evidence consistency is not clinical truth or completeness.

An active care-team assignment is required before assessment retrieval. The same patient lock
as source lifecycle changes protects the read. Unknown or unauthorized patients/assessments,
including PSW-only callers, return 404. Missing SBAR, unusable checks, invalidated/source-revision
mismatches, malformed drafts or unavailable/foreign/retracted/purged/superseded citations return
409 `note_unavailable`, without the old text. Successful projections append a `note_export` audit
entry. There is no payload cache, retention copy, public download URL or export write endpoint.

The shape validator checks the R4 elements used here, required cardinality/value sets, attachment
encoding, and the project's preliminary/exact-text profile. It is not a complete FHIR validator:
no terminology server, external profile resolution or EHR conformance certification is claimed.
Reference contracts: [R4 DocumentReference](https://hl7.org/fhir/R4/documentreference.html) and
[R4 Attachment](https://hl7.org/fhir/R4/datatypes.html#Attachment).

## Browser preview and human edits

`frontend/note-export.js` exposes `window.noteExportPanel(h, patientId, assessmentId)` to the
resident-page owner. It needs the existing `h.api` and `h.el` helpers. Loading the module and
mounting that hook is separate from changing the resident page on another owner's branch.

The "Send to sign-off queue (preview)" button performs the authorized GET and shows the exact
note text, citations summary and payload. It explicitly says nothing is sent to an EHR or real
queue. A textarea supports an editable local human draft without rewriting the stored SBAR.
"Preview edited draft" repeats the authorized GET first; revocation, lifecycle change or failed
freshness checks clear the stale payload. If the server draft changed, a reload is required.

Human previews receive a new local identifier, preliminary status and explicit human/unverified
author, description and tag. The original document is only `transforms` provenance. Original
sentence-to-evidence extensions and context citations are removed: arbitrary human wording must
not inherit the server's claim validation. The attachment contains the edited UTF-8 text and
correct size, without the original hash. HTML is escaped in the narrative and displayed through
text nodes. This does not establish the editor's identity or validate any edited clinical claim.

Edits live only in the current page: no localStorage, server persistence, external transmission,
signature or real queue. This is a preview workflow; a durable authenticated review/sign-off
system would require a separate contract. The exact server projection remains separately visible
and unchanged. Normal navigation/reload discards unsaved edits.

## Validation and remaining gates

Synthetic tests cover exact text/provenance and R4 shape, authorization, source lifecycle and
revision withholding, malformed citations, no model calls, edited UTF-8/HTML, removing inherited
evidence claims, revalidation failure and changed server drafts. DB-backed checks require the
repository's PostgreSQL/S3 CI environment. Real frontend mounting, human usability/readback and
external-system interoperability are separate acceptance gates. No real records or provider calls
are used by the default tests.

## BL-19 resident readback integration

The live resident route mounts the local human draft/export module only for an available
stored SBAR. It uses authorized overview and evidence requests, preserves the server action
label as a button opening the handoff review, and renders engine parameters as structured JSON.
No action click records a completed clinical assessment.

Overview now includes typed `documented_observations`: the most recent currently published,
unsuperseded patient temperature fact within the requested window, with numeric Celsius value,
exact evidence ID/quote, source ID, recorded and effective times. UCUM `Cel`, `C` and degree-C
units are supported. Future/expired/retracted/purged evidence is excluded under caller RLS.
Missing or unmeasured temperature remains unknown. The resident page shows the measurement
and source/time without deriving a normal, fever or negative clinical finding.

The API-captured synthetic cohort test follows Mrs. K overview, temperature and SBAR citations
through the real resident DOM into the preliminary export and explicitly unverified human
preview. This is synthetic engineering acceptance; phone and hosted acceptance remain separate.

Every SBAR citation is interactive. Fact citations fetch the authorized exact source quote;
`check:<uuid>` citations re-fetch the overview and require both the displayed assessment ID
and its explicit check ID to match before showing the recorded time and measured features.
Authored synthetic checks explicitly have no audio/source-document quote. A changed assessment
or revoked access withholds the signal readback and asks for reload. Check IDs are never sent
to the fact-only evidence endpoint. The DOM acceptance exercises every evidence button.

A missing current assessment is explicitly unavailable, without assuming incomplete baseline
enrollment. Source-revision invalidation can withhold an assessment while historical checks
still exist, so the empty-state message does not infer calibration state from that absence.
