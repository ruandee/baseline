-- Accepted ADR032 option A: reuse exactly the safety-session arm/end custody boundary.
CREATE FUNCTION pm_safety_voice_custodian(p_patient uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
 SELECT COALESCE(public.pm_safety_tenant() AND public.pm_role(p_patient,'importer'),false)
$$;
REVOKE ALL ON FUNCTION pm_safety_voice_custodian(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_safety_voice_custodian(uuid) TO pm_runtime;

-- Existing nurse/fixture policies remain unchanged; this adds only explicit self decisions.
CREATE POLICY safety_self_voice_permission ON resident_consents FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND recorded_by=pm_actor() AND scope='voice_check'
 AND decided_by='resident' AND pm_safety_voice_custodian(patient_id) IS TRUE);
