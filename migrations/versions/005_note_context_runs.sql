-- No source text or provider logs: durable completion even when a note yields no tags.
CREATE TABLE note_context_runs(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, source_id uuid NOT NULL,
 method text NOT NULL CHECK(method IN ('keyword','gemini')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,patient_id,source_id),
 FOREIGN KEY(tenant_id,patient_id,source_id) REFERENCES sources(tenant_id,patient_id,id)
);
ALTER TABLE note_context_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_context_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY care_read ON note_context_runs FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_care(patient_id));
CREATE POLICY writer_insert ON note_context_runs FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_access(patient_id,true));
CREATE POLICY writer_update ON note_context_runs FOR UPDATE USING(
 tenant_id=pm_tenant() AND pm_access(patient_id,true)) WITH CHECK(
 tenant_id=pm_tenant() AND pm_access(patient_id,true));
GRANT SELECT,INSERT,UPDATE ON note_context_runs TO pm_runtime;
