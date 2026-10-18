-- BL-30: preserve historical flat speech rows; new assessments store modality-keyed features.
ALTER TABLE assessments ADD COLUMN corroborated boolean NOT NULL DEFAULT false;

-- Preserve the existing narrow tenant budget aggregate for PSW scoring. Non-speech
-- assessments carry event time in params and must consume the same interruption budget.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls))
 THEN RAISE EXCEPTION '010 requires a migration owner with BYPASSRLS'; END IF;
END $$;
CREATE OR REPLACE FUNCTION pm_check_escalations(start_at timestamptz,end_at timestamptz) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT count(*) FROM public.assessments a LEFT JOIN public.voice_checks v
 ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id
 WHERE a.tenant_id=public.pm_tenant() AND a.verdict='escalate' AND v.session_id IS NULL
 AND a.params->>'session_id' IS NULL
 AND COALESCE((a.params->>'signal_ts')::timestamptz,v.ts)>=start_at
 AND COALESCE((a.params->>'signal_ts')::timestamptz,v.ts)<end_at
 AND COALESCE((a.params->>'over_budget')::boolean,false)=false
 AND COALESCE((a.params->>'no_escalate')::boolean,false)=false
 AND public.pm_check_scoring(nullif(current_setting('pm.check_scoring_patient',true),'')::uuid)
$$;
REVOKE ALL ON FUNCTION pm_check_escalations(timestamptz,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_check_escalations(timestamptz,timestamptz) TO pm_runtime;
