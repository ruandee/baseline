-- BL-31 (decision 017): per-resident check consent, skip log and a PSW assignment role.
-- Consent and skip rows are append-only: the runtime role gets SELECT and INSERT only, and the
-- latest consent row wins, so a withdrawal applies to the next check with no grace period.

ALTER TABLE assignments DROP CONSTRAINT assignments_role_check;
ALTER TABLE assignments ADD CONSTRAINT assignments_role_check
 CHECK(role IN ('importer','nurse','patient','psw'));

-- A PSW assignment is not general record access: pm_access (sources, facts, timeline,
-- questions, evidence) and pm_care (watch list, overview, SBAR) both exclude it.
CREATE OR REPLACE FUNCTION pm_access(p uuid, writing boolean DEFAULT false) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT FROM assignments a JOIN principals u
 ON u.tenant_id=a.tenant_id AND u.id=a.principal_id
 WHERE a.tenant_id=pm_tenant() AND a.patient_id=p AND a.principal_id=pm_actor()
 AND a.active AND u.active AND a.role<>'psw' AND (NOT writing OR a.role='importer'))
$$;

CREATE FUNCTION pm_role(p uuid, r text) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT FROM assignments a JOIN principals u
 ON u.tenant_id=a.tenant_id AND u.id=a.principal_id
 WHERE a.tenant_id=pm_tenant() AND a.patient_id=p AND a.principal_id=pm_actor()
 AND a.active AND u.active AND a.role=r)
$$;

-- Roles that may record a voice check: the care team plus PSWs.
CREATE FUNCTION pm_checker(p uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT pm_role(p,'nurse') OR pm_role(p,'importer') OR pm_role(p,'psw')
$$;

-- Like pm.actor/pm.tenant, this transaction-local context is set only by the trusted server.
-- It is entered after authorization, consent and admission locks, and cleared before return.
-- Ordinary PSW transactions cannot select clinical scoring inputs.
CREATE FUNCTION pm_check_scoring(p uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT p=nullif(current_setting('pm.check_scoring_patient',true),'')::uuid
 AND pm_checker(p)
$$;
CREATE POLICY psw_read ON patients FOR SELECT USING(tenant_id=pm_tenant() AND pm_checker(id));
CREATE POLICY check_scoring_read ON sources FOR SELECT USING(tenant_id=pm_tenant() AND pm_check_scoring(patient_id));
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['voice_checks','context_tags','assessments'] LOOP
  EXECUTE format('CREATE POLICY check_scoring_read ON %I FOR SELECT USING(tenant_id=pm_tenant() AND pm_check_scoring(patient_id))', t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['voice_checks','assessments'] LOOP
  EXECUTE format('CREATE POLICY check_scoring_insert ON %I FOR INSERT WITH CHECK(tenant_id=pm_tenant() AND pm_check_scoring(patient_id))', t);
 END LOOP;
END $$;

CREATE TABLE resident_consents(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 scope text NOT NULL CHECK(scope IN ('voice_check','vox_encounter')),
 status text NOT NULL CHECK(status IN ('granted','declined','withdrawn')),
 decided_by text NOT NULL CHECK(decided_by IN ('resident','substitute_decision_maker','synthetic_fixture')),
 sdm_reference text CHECK(sdm_reference IS NULL OR length(sdm_reference) BETWEEN 1 AND 200),
 expires_at timestamptz,
 note text CHECK(note IS NULL OR length(note)<=500),
 recorded_by uuid NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id),
 FOREIGN KEY(tenant_id,recorded_by) REFERENCES principals(tenant_id,id),
 CHECK(decided_by<>'substitute_decision_maker' OR sdm_reference IS NOT NULL),
 CHECK(expires_at IS NULL OR (status='granted' AND expires_at>recorded_at))
);
CREATE INDEX resident_consents_latest ON resident_consents(tenant_id,patient_id,scope,recorded_at DESC);

CREATE TABLE check_skips(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 reason text NOT NULL CHECK(reason IN ('declined','asleep','unwell','not_available','other')),
 device_ts timestamptz,
 recorded_by uuid NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id),
 FOREIGN KEY(tenant_id,recorded_by) REFERENCES principals(tenant_id,id)
);
CREATE INDEX check_skips_patient_time ON check_skips(tenant_id,patient_id,recorded_at DESC);

ALTER TABLE resident_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE resident_consents FORCE ROW LEVEL SECURITY;
CREATE POLICY checker_read ON resident_consents FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_checker(patient_id));
-- Resident/SDM decisions need a nurse; synthetic_fixture rows come only from an importer.
CREATE POLICY consent_insert ON resident_consents FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND recorded_by=pm_actor() AND (
  (decided_by='synthetic_fixture' AND pm_role(patient_id,'importer'))
  OR (decided_by<>'synthetic_fixture' AND pm_role(patient_id,'nurse'))));

ALTER TABLE check_skips ENABLE ROW LEVEL SECURITY;
ALTER TABLE check_skips FORCE ROW LEVEL SECURITY;
CREATE POLICY checker_read ON check_skips FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_checker(patient_id));
CREATE POLICY checker_insert ON check_skips FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND recorded_by=pm_actor() AND pm_checker(patient_id));

GRANT SELECT, INSERT ON resident_consents, check_skips TO pm_runtime;

-- Deliberately narrow aggregates: due-list metadata and tenant budget, never raw scores.
-- The owner must bypass forced RLS; an ordinary pm_runtime connection never does.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls))
 THEN RAISE EXCEPTION '007 requires a migration owner with BYPASSRLS'; END IF;
END $$;
CREATE FUNCTION pm_last_check_at(p uuid) RETURNS timestamptz
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT max(v.ts) FROM public.voice_checks v
 WHERE v.tenant_id=public.pm_tenant() AND v.patient_id=p AND public.pm_checker(p)
$$;
REVOKE ALL ON FUNCTION pm_last_check_at(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_last_check_at(uuid) TO pm_runtime;

CREATE FUNCTION pm_check_escalations(start_at timestamptz,end_at timestamptz) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT count(*) FROM public.assessments a JOIN public.voice_checks v
 ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id
 WHERE a.tenant_id=public.pm_tenant() AND a.verdict='escalate' AND v.ts>=start_at AND v.ts<end_at
 AND COALESCE((a.params->>'over_budget')::boolean,false)=false
 AND COALESCE((a.params->>'no_escalate')::boolean,false)=false
 AND public.pm_check_scoring(nullif(current_setting('pm.check_scoring_patient',true),'')::uuid)
$$;
REVOKE ALL ON FUNCTION pm_check_escalations(timestamptz,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_check_escalations(timestamptz,timestamptz) TO pm_runtime;
