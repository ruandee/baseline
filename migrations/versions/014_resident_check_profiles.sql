-- Explicit resident preferences. No inferred language/name and no legacy capture rewrites.
CREATE TABLE resident_check_profiles(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL,
 preferred_locale text CHECK(preferred_locale ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
 first_name text CHECK(first_name IS NULL OR (length(first_name) BETWEEN 1 AND 80 AND first_name=btrim(first_name))),
 version uuid NOT NULL, updated_by uuid NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,patient_id),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id),
 FOREIGN KEY(tenant_id,updated_by) REFERENCES principals(tenant_id,id)
);
ALTER TABLE resident_check_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE resident_check_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY check_profile_read ON resident_check_profiles FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_checker(patient_id));
CREATE POLICY check_profile_insert ON resident_check_profiles FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_care(patient_id) AND updated_by=pm_actor());
CREATE POLICY check_profile_update ON resident_check_profiles FOR UPDATE USING(
 tenant_id=pm_tenant() AND pm_care(patient_id)) WITH CHECK(
 tenant_id=pm_tenant() AND pm_care(patient_id) AND updated_by=pm_actor());
GRANT SELECT,INSERT,UPDATE ON resident_check_profiles TO pm_runtime;

-- Append-only sidecar, deliberately leaving historical voice_checks and fixture hashes alone.
CREATE TABLE voice_check_profiles(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, check_id uuid NOT NULL, check_ts timestamptz NOT NULL,
 profile_version uuid NOT NULL, locale text NOT NULL CHECK(locale='en'),
 prompt_version text NOT NULL CHECK(prompt_version='count20-days-v1'), first_name text,
 PRIMARY KEY(tenant_id,patient_id,check_id,check_ts),
 FOREIGN KEY(tenant_id,patient_id,check_id,check_ts)
 REFERENCES voice_checks(tenant_id,patient_id,id,ts) ON DELETE CASCADE
);
ALTER TABLE voice_check_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_check_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY voice_profile_read ON voice_check_profiles FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_care(patient_id));
CREATE POLICY voice_profile_insert ON voice_check_profiles FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_checker(patient_id) AND pm_check_scoring(patient_id) IS TRUE);
GRANT SELECT,INSERT ON voice_check_profiles TO pm_runtime;

CREATE FUNCTION pm_bind_check_profile() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT EXISTS(SELECT FROM public.resident_check_profiles p JOIN public.voice_checks v
    ON v.tenant_id=p.tenant_id AND v.patient_id=p.patient_id
    WHERE p.tenant_id=NEW.tenant_id AND p.patient_id=NEW.patient_id
    AND p.version=NEW.profile_version AND p.preferred_locale=NEW.locale
    AND p.first_name IS NOT DISTINCT FROM NEW.first_name
    AND v.id=NEW.check_id AND v.ts=NEW.check_ts AND v.session_id IS NULL
    AND v.prompt_version=NEW.prompt_version) THEN
  RAISE EXCEPTION 'capture profile must match admitted counting protocol' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION pm_bind_check_profile() FROM PUBLIC;
CREATE TRIGGER voice_profile_bind BEFORE INSERT ON voice_check_profiles
 FOR EACH ROW EXECUTE FUNCTION pm_bind_check_profile();
