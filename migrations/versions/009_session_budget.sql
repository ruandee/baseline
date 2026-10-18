-- BL-27 integration: session assessments never consume the resident shift budget.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls))
 THEN RAISE EXCEPTION '009 requires a migration owner with BYPASSRLS'; END IF;
END $$;
CREATE OR REPLACE FUNCTION pm_check_escalations(start_at timestamptz,end_at timestamptz) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT count(*) FROM public.assessments a JOIN public.voice_checks v
 ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id
 WHERE a.tenant_id=public.pm_tenant() AND a.verdict='escalate' AND v.session_id IS NULL AND v.ts>=start_at AND v.ts<end_at
 AND COALESCE((a.params->>'over_budget')::boolean,false)=false
 AND COALESCE((a.params->>'no_escalate')::boolean,false)=false
 AND public.pm_check_scoring(nullif(current_setting('pm.check_scoring_patient',true),'')::uuid)
$$;
REVOKE ALL ON FUNCTION pm_check_escalations(timestamptz,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_check_escalations(timestamptz,timestamptz) TO pm_runtime;
