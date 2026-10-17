# Change notifications for Baseline

`docs/01-product.md` bans "alerts that drive care" and EHR writeback from the original MVP, and `AGENTS.md` bans autonomous diagnosis and treatment. Baseline (`docs/06-baseline.md`) needs to tell a nurse that a resident's speech has shifted from their own normal, so this decision narrows the first ban and leaves the others intact.

**Allowed, as decision support:** a ranked watch list and a per-resident verdict (`within_normal`, `enrolling`, `watch`, `explained`, `escalate`) with a suggested action drawn only from a fixed enum of standard assessments (`recheck_1h`, `4at_now`, `restore2_soft_signs`, `vitals_recheck`). Every verdict shows its evidence and the parameters that produced it. Interruptions are rationed by a per-shift escalation budget (`PM_ESCALATION_BUDGET`, default 3 per 8-hour shift); escalations over budget are listed, not pushed. Statistics decide whether something changed, a deterministic table decides the verdict, and Gemini never decides.

**Still banned:** diagnosis (the system detects change, never "delirium"), treatment or prescribing suggestions, autonomous clinical action, auto-dialling anyone (the KAZE ladder texts contacts and tells them to call 911 itself), and EHR writeback. The note export in BL-33 only produces a `preliminary` FHIR `DocumentReference` draft for a human sign-off queue; nothing is written to a chart.

**Absence rules carry over:** no documentation is never a negative finding, so `fever_documented` needs a recorded temperature, and absence of context tags never proves a change is unexplained.

**Affected contracts:** new `assessments` table and `GET /v1/watchlist`, `GET /v1/patients/{id}/overview` and `POST /v1/patients/{id}/checks` responses. The existing question and summary schemas are unchanged. `AGENTS.md` invariants still apply to all new code; a clinical-validation claim is still out of scope, and the UI states that Baseline is change detection, not diagnosis.

**Regulatory note:** a real product that analyses voice and prompts action could be classed as a medical device by Health Canada; launch would need a classification review. This prototype makes no regulatory claim.
