-- Baseline voice checks, typed context and assessments (docs/06-baseline.md, decision 004).
-- time_bucket comes from the extension. voice_checks is deliberately NOT a hypertable: row-level
-- security does not apply to chunk tables, and pm_runtime can read a chunk directly.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE voice_checks(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 ts timestamptz NOT NULL DEFAULT clock_timestamp(),
 device_ts timestamptz, device_id text NOT NULL,
 mode text NOT NULL CHECK (mode IN ('resident','runner','live')),
 prompt_version text NOT NULL DEFAULT 'count20-days-v1',
 is_baseline boolean NOT NULL DEFAULT false,
 usable boolean NOT NULL,
 quality jsonb NOT NULL,
 speech_rate_wpm double precision,
 pause_ratio double precision,
 mean_pause_s double precision,
 f0_median_hz double precision,
 transcript text,
 words jsonb,
 synthetic boolean NOT NULL DEFAULT false,
 PRIMARY KEY (tenant_id, patient_id, id, ts),
 FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id)
);
CREATE INDEX voice_checks_patient_ts ON voice_checks(tenant_id, patient_id, ts DESC);

CREATE TABLE context_tags(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 kind text NOT NULL CHECK (kind IN ('explainer','amplifier')),
 tag text NOT NULL,
 source_id uuid NOT NULL, fact_id uuid,
 quote text NOT NULL, start_offset integer NOT NULL, end_offset integer NOT NULL,
 valid_from timestamptz NOT NULL, valid_to timestamptz,
 extracted_by text NOT NULL CHECK (extracted_by IN ('structured','gemini')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (tenant_id, patient_id, id),
 FOREIGN KEY (tenant_id, patient_id, source_id) REFERENCES sources(tenant_id, patient_id, id),
 CHECK (end_offset > start_offset)
);

CREATE TABLE assessments(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 check_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 change_status text NOT NULL CHECK (change_status IN ('none','enrolling','provisional','change')),
 fused_z double precision,
 features jsonb NOT NULL,
 params jsonb NOT NULL,
 verdict text NOT NULL CHECK (verdict IN ('within_normal','enrolling','watch','explained','escalate')),
 reasons jsonb NOT NULL DEFAULT '[]',
 suggested_action text NOT NULL CHECK (suggested_action IN
   ('none','recheck_1h','4at_now','restore2_soft_signs','vitals_recheck')),
 sbar jsonb,
 PRIMARY KEY (tenant_id, patient_id, id),
 FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id)
);

DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['voice_checks','context_tags','assessments'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
  EXECUTE format('CREATE POLICY care_read ON %I FOR SELECT USING(tenant_id=pm_tenant() AND pm_care(patient_id))', t);
  EXECUTE format('CREATE POLICY care_insert ON %I FOR INSERT WITH CHECK(tenant_id=pm_tenant() AND pm_care(patient_id))', t);
 END LOOP;
END $$;
CREATE POLICY care_update ON assessments FOR UPDATE USING(tenant_id=pm_tenant() AND pm_care(patient_id))
 WITH CHECK(tenant_id=pm_tenant() AND pm_care(patient_id));

GRANT SELECT, INSERT ON voice_checks, context_tags TO pm_runtime;
GRANT SELECT, INSERT, UPDATE ON assessments TO pm_runtime;
