-- BL-34: immutable client-derived motion captures; ordinary table (decision 004).
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls))
 THEN RAISE EXCEPTION '011 requires a migration owner with BYPASSRLS'; END IF;
END $$;
ALTER TABLE resident_consents DROP CONSTRAINT resident_consents_scope_check;
ALTER TABLE resident_consents ADD CONSTRAINT resident_consents_scope_check
 CHECK(scope IN ('voice_check','vox_encounter','motion_check'));

CREATE TABLE motion_checks(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 ts timestamptz NOT NULL DEFAULT clock_timestamp(), device_ts timestamptz,
 device_id text NOT NULL CHECK(length(device_id) BETWEEN 1 AND 128),
 prompt_version text NOT NULL DEFAULT 'pose-chair-steps-v1'
  CHECK(prompt_version='pose-chair-steps-v1'),
 is_baseline boolean NOT NULL DEFAULT false, usable boolean NOT NULL,
 duration_s double precision NOT NULL CHECK(duration_s BETWEEN 0 AND 12),
 total_frames integer NOT NULL CHECK(total_frames BETWEEN 0 AND 1000),
 confident_frames integer NOT NULL CHECK(confident_frames BETWEEN 0 AND total_frames),
 quality jsonb NOT NULL,
 sit_to_stand_s double precision CHECK(sit_to_stand_s>0 AND sit_to_stand_s<=10),
 trunk_sway double precision CHECK(trunk_sway BETWEEN 0 AND 5),
 step_cadence_spm double precision CHECK(step_cadence_spm>0 AND step_cadence_spm<=360),
 source_id uuid,
 PRIMARY KEY(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id),
 FOREIGN KEY(tenant_id,patient_id,source_id) REFERENCES sources(tenant_id,patient_id,id)
  DEFERRABLE INITIALLY DEFERRED,
 CHECK((source_id IS NOT NULL)=usable),
 CHECK(NOT usable OR (duration_s>=8 AND total_frames>=20
  AND confident_frames>=0.8*total_frames AND sit_to_stand_s IS NOT NULL
  AND trunk_sway IS NOT NULL AND step_cadence_spm IS NOT NULL))
);
CREATE INDEX motion_checks_history ON motion_checks(tenant_id,patient_id,ts);
ALTER TABLE motion_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE motion_checks FORCE ROW LEVEL SECURITY;
CREATE POLICY motion_care_read ON motion_checks FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_care(patient_id));
CREATE POLICY motion_scoring_read ON motion_checks FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_check_scoring(patient_id));
CREATE POLICY motion_capture_insert ON motion_checks FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_checker(patient_id) AND pm_check_scoring(patient_id)
 AND (NOT is_baseline OR pm_care(patient_id)));
GRANT SELECT,INSERT ON motion_checks TO pm_runtime;
-- No runtime UPDATE/DELETE grants: the submitted observations are immutable.

-- PSW scoring can resolve only motion facts in the trusted patient-scoped context.
CREATE POLICY motion_fact_scoring_read ON facts FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_check_scoring(patient_id) AND EXISTS(
  SELECT FROM motion_checks m WHERE m.tenant_id=facts.tenant_id
  AND m.patient_id=facts.patient_id AND m.source_id=facts.source_id AND m.usable));

-- Both helpers are closed over a persisted capture, not a generic source-write capability.
CREATE FUNCTION pm_motion_source_payload(p_patient uuid,p_check uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE m public.motion_checks; c public.resident_consents;
BEGIN
 IF NOT public.pm_check_scoring(p_patient) OR NOT public.pm_checker(p_patient) THEN
  RAISE EXCEPTION 'motion capture scope required' USING ERRCODE='42501';
 END IF;
 SELECT * INTO c FROM public.resident_consents WHERE tenant_id=public.pm_tenant()
  AND patient_id=p_patient AND scope='motion_check' ORDER BY recorded_at DESC,id DESC LIMIT 1;
 IF NOT FOUND OR c.status<>'granted' OR c.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'motion consent required' USING ERRCODE='42501';
 END IF;
 SELECT * INTO m FROM public.motion_checks WHERE tenant_id=public.pm_tenant()
  AND patient_id=p_patient AND id=p_check AND usable;
 IF NOT FOUND THEN RAISE EXCEPTION 'motion capture unavailable' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('external_document_id','motion-'||m.id,
  'external_version_id','1','source_system','baseline-motion-client-derived-v1',
  'kind','observation','author_role','system','visibility','care_team',
  'recorded_at',m.ts,'effective_from',m.ts,'effective_to',m.ts+interval '24 hours',
  'records',jsonb_build_array(
   jsonb_build_object('concept','client_derived_sit_to_stand_s','value',m.sit_to_stand_s::text,
    'unit','s','polarity','present'),
   jsonb_build_object('concept','client_derived_trunk_sway','value',m.trunk_sway::text,
    'unit','ratio','polarity','present'),
   jsonb_build_object('concept','client_derived_step_cadence_spm','value',m.step_cadence_spm::text,
    'unit','steps/min','polarity','present')));
END $$;
REVOKE ALL ON FUNCTION pm_motion_source_payload(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_motion_source_payload(uuid,uuid) TO pm_runtime;

CREATE FUNCTION pm_publish_motion_source(p_patient uuid,p_check uuid,p_raw text,p_object_key text)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE m public.motion_checks; payload jsonb; canonical text:=''; r jsonb;
 quote text; offset_at integer:=0; expected_key text;
BEGIN
 payload:=public.pm_motion_source_payload(p_patient,p_check);
 SELECT * INTO m FROM public.motion_checks WHERE tenant_id=public.pm_tenant()
  AND patient_id=p_patient AND id=p_check FOR UPDATE;
 expected_key:=m.tenant_id::text||'/'||m.patient_id::text||'/'||m.source_id::text||'.json';
 IF p_raw::jsonb IS DISTINCT FROM payload OR p_object_key IS DISTINCT FROM expected_key THEN
  RAISE EXCEPTION 'motion source must match immutable capture' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT FROM public.sources WHERE tenant_id=m.tenant_id AND patient_id=m.patient_id
  AND id=m.source_id) THEN
  RAISE EXCEPTION 'motion source already published' USING ERRCODE='22023';
 END IF;
 FOR r IN SELECT value FROM jsonb_array_elements(payload->'records') LOOP
  quote:=(r->>'concept')||': '||(r->>'value')||' '||(r->>'unit')||' [polarity=present]';
  canonical:=canonical||CASE WHEN canonical='' THEN '' ELSE E'\n' END||quote;
 END LOOP;
 INSERT INTO public.sources(id,tenant_id,patient_id,document_key,external_version,payload_hash,
  object_key,payload,visibility,recorded_at,canonical_text,published_at)
 VALUES(m.source_id,m.tenant_id,m.patient_id,
  jsonb_build_array(payload->>'source_system',payload->>'external_document_id')::text,'1',
  encode(sha256(convert_to(p_raw,'UTF8')),'hex'),p_object_key,payload,'care_team',m.ts,
  canonical,clock_timestamp());
 FOR r IN SELECT value FROM jsonb_array_elements(payload->'records') LOOP
  quote:=(r->>'concept')||': '||(r->>'value')||' '||(r->>'unit')||' [polarity=present]';
  INSERT INTO public.facts(id,tenant_id,patient_id,source_id,concept,value,unit,polarity,
   experiencer,valid_from,valid_to,quote,start_offset,end_offset,embedding)
  VALUES(gen_random_uuid(),m.tenant_id,m.patient_id,m.source_id,r->>'concept',r->>'value',
   r->>'unit','present','patient',m.ts,m.ts+interval '24 hours',quote,offset_at,
   offset_at+char_length(quote),('['||array_to_string(array_fill(0,ARRAY[64]),',')||']')::public.vector);
  offset_at:=offset_at+char_length(quote)+1;
 END LOOP;
 -- Identical lifecycle semantics to ingestion.bump: no preserved stale assessment shortcut.
 DELETE FROM public.answers WHERE tenant_id=m.tenant_id AND patient_id=m.patient_id;
 UPDATE public.assessments SET reasons='[]',sbar=NULL,
  params=params||'{"invalidated":true}'::jsonb
  WHERE tenant_id=m.tenant_id AND patient_id=m.patient_id;
 UPDATE public.patients SET revision=revision+1 WHERE tenant_id=m.tenant_id AND id=m.patient_id;
 RETURN m.source_id;
END $$;
REVOKE ALL ON FUNCTION pm_publish_motion_source(uuid,uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_publish_motion_source(uuid,uuid,text,text) TO pm_runtime;

-- Source purge must remove the duplicate raw capture, not only its fact projection.
CREATE FUNCTION pm_purge_motion_projection() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF OLD.purged_at IS NULL AND NEW.purged_at IS NOT NULL THEN
  DELETE FROM public.assessments a USING public.motion_checks m
   WHERE m.tenant_id=NEW.tenant_id AND m.patient_id=NEW.patient_id AND m.source_id=NEW.id
   AND a.tenant_id=m.tenant_id AND a.patient_id=m.patient_id AND a.check_id=m.id;
  DELETE FROM public.motion_checks WHERE tenant_id=NEW.tenant_id
   AND patient_id=NEW.patient_id AND source_id=NEW.id;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION pm_purge_motion_projection() FROM PUBLIC;
CREATE TRIGGER motion_source_purge AFTER UPDATE OF purged_at ON sources
 FOR EACH ROW EXECUTE FUNCTION pm_purge_motion_projection();
