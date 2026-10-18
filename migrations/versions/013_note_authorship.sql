-- BL-31: explicit importer-asserted note authorship and score-free positive feedback.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls))
 THEN RAISE EXCEPTION '013 requires a migration owner with BYPASSRLS'; END IF;
END $$;

CREATE TABLE source_authors(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, source_id uuid NOT NULL,
 author_principal_id uuid NOT NULL, author_role text NOT NULL CHECK(author_role IN ('nurse','psw')),
 asserted_by uuid NOT NULL, asserted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,patient_id,source_id),
 FOREIGN KEY(tenant_id,patient_id,source_id) REFERENCES sources(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,author_principal_id) REFERENCES principals(tenant_id,id),
 FOREIGN KEY(tenant_id,asserted_by) REFERENCES principals(tenant_id,id)
);
ALTER TABLE source_authors ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_authors FORCE ROW LEVEL SECURITY;
CREATE POLICY source_author_read ON source_authors FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_care(patient_id));
CREATE POLICY source_author_insert ON source_authors FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND asserted_by=pm_actor() AND pm_role(patient_id,'importer'));
GRANT SELECT,INSERT ON source_authors TO pm_runtime;

-- Exposes only whether this explicitly named author is eligible to the assigned importer.
CREATE FUNCTION pm_note_author_valid(p_patient uuid,p_author uuid,p_role text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT COALESCE(public.pm_role(p_patient,'importer') AND p_role IN ('nurse','psw') AND EXISTS(
  SELECT FROM public.assignments a JOIN public.principals u
  ON u.tenant_id=a.tenant_id AND u.id=a.principal_id
  WHERE a.tenant_id=public.pm_tenant() AND a.patient_id=p_patient
  AND a.principal_id=p_author AND a.role=p_role AND a.active AND u.active),false)
$$;
REVOKE ALL ON FUNCTION pm_note_author_valid(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_note_author_valid(uuid,uuid,text) TO pm_runtime;

CREATE FUNCTION pm_bind_note_author() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE payload jsonb;
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM public.pm_tenant()
    OR NEW.asserted_by IS DISTINCT FROM public.pm_actor()
    OR public.pm_note_author_valid(NEW.patient_id,NEW.author_principal_id,NEW.author_role)
       IS NOT TRUE THEN
  RAISE EXCEPTION 'explicit assigned note author required' USING ERRCODE='42501';
 END IF;
 SELECT s.payload INTO payload FROM public.sources s
  WHERE s.tenant_id=NEW.tenant_id AND s.patient_id=NEW.patient_id AND s.id=NEW.source_id;
 IF NOT FOUND OR payload->>'kind' IS DISTINCT FROM 'nursing_note'
    OR payload->>'author_role' IS DISTINCT FROM NEW.author_role
    OR payload->>'author_principal_id' IS DISTINCT FROM NEW.author_principal_id::text THEN
  RAISE EXCEPTION 'note attribution must match immutable source' USING ERRCODE='22023';
 END IF;
 NEW.asserted_at:=clock_timestamp();
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION pm_bind_note_author() FROM PUBLIC;
CREATE TRIGGER source_author_bind BEFORE INSERT ON source_authors
 FOR EACH ROW EXECUTE FUNCTION pm_bind_note_author();

CREATE FUNCTION pm_purge_note_author() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF OLD.purged_at IS NULL AND NEW.purged_at IS NOT NULL THEN
  DELETE FROM public.source_authors WHERE tenant_id=NEW.tenant_id
   AND patient_id=NEW.patient_id AND source_id=NEW.id;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION pm_purge_note_author() FROM PUBLIC;
CREATE TRIGGER source_author_purge AFTER UPDATE OF purged_at ON sources
 FOR EACH ROW EXECUTE FUNCTION pm_purge_note_author();

-- Invoker security: ordinary PSW calls see no assessment rows under existing forced RLS.
-- This is the existing overview eligibility and ordering, shared by the closed aggregate.
CREATE FUNCTION pm_latest_resident_assessment_id(p_patient uuid,p_at timestamptz,
 p_modality text DEFAULT NULL) RETURNS uuid
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
 SELECT id FROM (
  SELECT a.id,a.created_at,COALESCE((a.params->>'signal_ts')::timestamptz,v.ts) AS check_ts
  FROM public.assessments a LEFT JOIN public.voice_checks v
  ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id
  WHERE a.tenant_id=public.pm_tenant() AND a.patient_id=p_patient
  AND COALESCE((a.params->>'invalidated')::boolean,false)=false
  AND a.params->>'session_id' IS NULL AND v.session_id IS NULL
  AND (p_modality IS NULL OR COALESCE(a.params->>'modality','speech')=p_modality)
  AND (a.params->>'source_revision')::bigint=(SELECT revision FROM public.patients
   WHERE tenant_id=public.pm_tenant() AND id=p_patient)
 ) eligible WHERE check_ts<=p_at ORDER BY check_ts DESC,created_at DESC,id DESC LIMIT 1
$$;
REVOKE ALL ON FUNCTION pm_latest_resident_assessment_id(uuid,timestamptz,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_latest_resident_assessment_id(uuid,timestamptz,text) TO pm_runtime;

CREATE FUNCTION pm_observation_helped(p_patient uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE current_at timestamptz:=statement_timestamp(); selected uuid; signal_at timestamptz;
 a public.assessments;
BEGIN
 IF public.pm_role(p_patient,'psw') IS NOT TRUE THEN RETURN NULL; END IF;
 selected:=public.pm_latest_resident_assessment_id(p_patient,current_at);
 SELECT * INTO a FROM public.assessments WHERE tenant_id=public.pm_tenant()
  AND patient_id=p_patient AND id=selected;
 IF NOT FOUND OR a.verdict<>'escalate'
    OR COALESCE((a.params->>'over_budget')::boolean,false)
    OR COALESCE((a.params->>'no_escalate')::boolean,false) THEN RETURN NULL; END IF;
 SELECT COALESCE((a.params->>'signal_ts')::timestamptz,v.ts) INTO signal_at
  FROM (SELECT 1) singleton LEFT JOIN public.voice_checks v
  ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id AND v.id=a.check_id;
 -- Feedback-only freshness, not a change to verdict policy or clinical source history.
 IF signal_at IS NULL OR signal_at<current_at-interval '24 hours' THEN RETURN NULL; END IF;
 -- Credit must not outlive any contributing capture or citation, even without a revision bump.
 IF a.sbar IS NULL OR EXISTS(
  SELECT FROM jsonb_each(COALESCE(a.params->'modality_results','{}'::jsonb)) m
  WHERE m.value->>'current'='true' AND m.value->>'status' IN ('provisional','change')
  AND (m.key NOT IN ('speech','motion','vitals') OR m.value->>'ts' IS NULL
   OR (m.value->>'ts')::timestamptz>current_at
   OR (m.value->>'ts')::timestamptz<current_at-interval '24 hours')
 ) THEN RETURN NULL; END IF;
 IF EXISTS(
  WITH modalities AS (
   SELECT key AS name,value FROM jsonb_each(COALESCE(a.params->'modality_results','{}'::jsonb))
   WHERE value->>'current'='true' AND value->>'status' IN ('provisional','change')
  ), allowed_voice AS (
   SELECT 'check:'||a.check_id::text AS id WHERE COALESCE(a.params->>'modality','speech')='speech'
   UNION SELECT jsonb_array_elements_text(value->'evidence_ids') FROM modalities WHERE name='speech'
   UNION SELECT jsonb_array_elements_text(value->'params'->'baseline_evidence_ids')
    FROM modalities WHERE name='speech'
  ), cited AS (
   SELECT reason->>'evidence_id' AS id FROM jsonb_array_elements(a.reasons) reason
   UNION SELECT jsonb_array_elements_text(sentence->'evidence_ids')
    FROM jsonb_array_elements(a.sbar->'sentences') sentence
   UNION SELECT jsonb_array_elements_text(value->'evidence_ids') FROM modalities
   UNION SELECT jsonb_array_elements_text(value->'params'->'baseline_evidence_ids') FROM modalities
  )
  SELECT FROM cited c WHERE c.id IS NOT NULL AND (
   (c.id LIKE 'check:%' AND (c.id NOT IN (SELECT id FROM allowed_voice) OR NOT EXISTS(
    SELECT FROM public.voice_checks v
    WHERE v.tenant_id=public.pm_tenant() AND v.patient_id=p_patient
    AND v.id::text=substring(c.id FROM 7) AND v.usable AND v.session_id IS NULL
    AND v.ts<=current_at)))
   OR (c.id NOT LIKE 'check:%' AND NOT EXISTS(
    SELECT FROM public.facts f JOIN public.sources s ON s.tenant_id=f.tenant_id
    AND s.patient_id=f.patient_id AND s.id=f.source_id
    WHERE f.tenant_id=public.pm_tenant() AND f.patient_id=p_patient AND f.id::text=c.id
    AND s.published_at IS NOT NULL AND s.published_at<=a.created_at
    AND s.retracted_at IS NULL AND s.purged_at IS NULL AND s.recorded_at<=current_at
    AND COALESCE(f.valid_from,s.recorded_at)<=current_at
    AND (f.valid_to IS NULL OR f.valid_to>current_at)
    AND ((s.payload->>'kind'='nursing_note' AND f.polarity IN ('present','uncertain')
     AND f.experiencer IN ('patient','unspecified'))
     OR (f.polarity='present' AND f.experiencer='patient'))
    AND NOT EXISTS(SELECT FROM public.sources newer WHERE newer.tenant_id=s.tenant_id
     AND newer.patient_id=s.patient_id AND newer.supersedes=s.id
     AND newer.published_at IS NOT NULL AND newer.retracted_at IS NULL AND newer.purged_at IS NULL)
   )))
 ) THEN RETURN NULL; END IF;
 IF EXISTS(
  WITH cited_context AS (
   SELECT reason->>'context_tag_id' AS id FROM jsonb_array_elements(a.reasons) reason
   UNION SELECT jsonb_array_elements_text(a.params->'draft_context_ids')
  )
  SELECT FROM cited_context c WHERE c.id IS NOT NULL AND NOT EXISTS(
   SELECT FROM public.context_tags t WHERE t.tenant_id=public.pm_tenant()
   AND t.patient_id=p_patient AND t.id::text=c.id AND t.valid_from<=signal_at
   AND (t.valid_to IS NULL OR (t.valid_to>signal_at AND t.valid_to>current_at)))
 ) THEN RETURN NULL; END IF;
 IF EXISTS(
  WITH cited AS (
   SELECT reason->>'evidence_id' AS id FROM jsonb_array_elements(a.reasons) reason
   UNION
   SELECT jsonb_array_elements_text(sentence->'evidence_ids')
    FROM jsonb_array_elements(COALESCE(a.sbar->'sentences','[]'::jsonb)) sentence
  )
  SELECT FROM cited c JOIN public.facts f ON f.id::text=c.id
  JOIN public.sources s ON s.tenant_id=f.tenant_id AND s.patient_id=f.patient_id AND s.id=f.source_id
  JOIN public.source_authors n ON n.tenant_id=s.tenant_id AND n.patient_id=s.patient_id
   AND n.source_id=s.id
  WHERE f.tenant_id=public.pm_tenant() AND f.patient_id=p_patient
  AND f.polarity IN ('present','uncertain') AND f.experiencer IN ('patient','unspecified')
  AND n.author_principal_id=public.pm_actor() AND n.author_role='psw'
  AND n.asserted_at<=a.created_at
  AND s.published_at IS NOT NULL AND s.published_at<=a.created_at
  AND s.retracted_at IS NULL AND s.purged_at IS NULL
  AND s.payload->>'kind'='nursing_note' AND s.recorded_at<=signal_at
  AND COALESCE(f.valid_from,s.recorded_at)<=signal_at
  AND (f.valid_to IS NULL OR (f.valid_to>signal_at AND f.valid_to>current_at))
  AND NOT EXISTS(SELECT FROM public.sources newer WHERE newer.tenant_id=s.tenant_id
   AND newer.patient_id=s.patient_id AND newer.supersedes=s.id AND newer.published_at IS NOT NULL
   AND newer.retracted_at IS NULL AND newer.purged_at IS NULL)
  -- Note context has its own expiry even when the source assertion has no end time.
  AND EXISTS(SELECT FROM public.context_tags t WHERE t.tenant_id=f.tenant_id
   AND t.patient_id=f.patient_id AND t.source_id=s.id AND t.fact_id=f.id
   AND t.valid_from<=signal_at AND (t.valid_to IS NULL
    OR (t.valid_to>signal_at AND t.valid_to>current_at)))
 ) THEN RETURN true; END IF;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION pm_observation_helped(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_observation_helped(uuid) TO pm_runtime;
