CREATE EXTENSION IF NOT EXISTS vector;
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='pm_runtime') THEN
   CREATE ROLE pm_runtime LOGIN PASSWORD 'synthetic-runtime' NOSUPERUSER NOBYPASSRLS;
 END IF;
END $$;
CREATE TABLE tenants(id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE principals(
 id uuid NOT NULL, tenant_id uuid NOT NULL REFERENCES tenants, name text NOT NULL,
 administrator boolean NOT NULL DEFAULT false, active boolean NOT NULL DEFAULT true,
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE patients(
 id uuid NOT NULL, tenant_id uuid NOT NULL REFERENCES tenants, external_id text NOT NULL,
 revision bigint NOT NULL DEFAULT 0, PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,external_id)
);
CREATE TABLE assignments(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, principal_id uuid NOT NULL,
 role text NOT NULL CHECK(role IN ('importer','nurse','patient')), active boolean DEFAULT true,
 PRIMARY KEY(tenant_id,patient_id,principal_id,role),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id),
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id)
);
CREATE FUNCTION pm_tenant() RETURNS uuid LANGUAGE sql STABLE AS
 $$ SELECT nullif(current_setting('pm.tenant',true),'')::uuid $$;
CREATE FUNCTION pm_actor() RETURNS uuid LANGUAGE sql STABLE AS
 $$ SELECT nullif(current_setting('pm.actor',true),'')::uuid $$;
CREATE FUNCTION pm_access(p uuid, writing boolean DEFAULT false) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT FROM assignments a JOIN principals u
 ON u.tenant_id=a.tenant_id AND u.id=a.principal_id
 WHERE a.tenant_id=pm_tenant() AND a.patient_id=p AND a.principal_id=pm_actor()
 AND a.active AND u.active AND (NOT writing OR a.role='importer'))
$$;
CREATE FUNCTION pm_care(p uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT FROM assignments a WHERE a.tenant_id=pm_tenant()
 AND a.patient_id=p AND a.principal_id=pm_actor() AND a.active AND a.role IN ('nurse','importer'))
$$;
CREATE TABLE sources(
 id uuid NOT NULL, tenant_id uuid NOT NULL, patient_id uuid NOT NULL,
 document_key text NOT NULL, external_version text NOT NULL, payload_hash text NOT NULL,
 object_key text NOT NULL, payload jsonb NOT NULL, canonical_text text NOT NULL DEFAULT '',
 visibility text NOT NULL CHECK(visibility IN ('care_team','patient_and_care_team')),
 recorded_at timestamptz NOT NULL, ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 published_at timestamptz, retracted_at timestamptz, retraction_reason text, purged_at timestamptz,
 supersedes uuid, PRIMARY KEY(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id),
 FOREIGN KEY(tenant_id,patient_id,supersedes) REFERENCES sources(tenant_id,patient_id,id),
 UNIQUE(tenant_id,patient_id,document_key,external_version)
);
CREATE TABLE jobs(
 id uuid NOT NULL, tenant_id uuid NOT NULL, patient_id uuid NOT NULL, source_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'queued', stage text NOT NULL DEFAULT 'accepted',
 attempt integer NOT NULL DEFAULT 0, lease_until timestamptz, lease_token uuid,
 next_attempt_at timestamptz NOT NULL DEFAULT now(), error_code text,
 PRIMARY KEY(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,patient_id,source_id) REFERENCES sources(tenant_id,patient_id,id)
);
CREATE TABLE facts(
 id uuid NOT NULL, tenant_id uuid NOT NULL, patient_id uuid NOT NULL, source_id uuid NOT NULL,
 concept text NOT NULL, value text NOT NULL, unit text, polarity text NOT NULL,
 experiencer text NOT NULL DEFAULT 'patient', event_type text, order_id text,
 valid_from timestamptz, valid_to timestamptz, review_status text NOT NULL DEFAULT 'extracted',
 quote text NOT NULL, start_offset integer NOT NULL, end_offset integer NOT NULL,
 embedding vector(64) NOT NULL,
 search tsvector GENERATED ALWAYS AS (to_tsvector('english',concept || ' ' || quote)) STORED,
 PRIMARY KEY(tenant_id,patient_id,id),
 FOREIGN KEY(tenant_id,patient_id,source_id) REFERENCES sources(tenant_id,patient_id,id),
 CHECK(start_offset>=0 AND end_offset>start_offset),
 CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from)
);
CREATE INDEX fact_scope ON facts(tenant_id,patient_id,source_id);
CREATE INDEX fact_search ON facts USING gin(search);
CREATE INDEX source_scope_time ON sources(tenant_id,patient_id,ingested_at);
CREATE TABLE relations(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, subject_id uuid NOT NULL,
 object_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('contradicts','supersedes','supports')),
 PRIMARY KEY(tenant_id,patient_id,subject_id,object_id,kind),
 FOREIGN KEY(tenant_id,patient_id,subject_id) REFERENCES facts(tenant_id,patient_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,patient_id,object_id) REFERENCES facts(tenant_id,patient_id,id) ON DELETE CASCADE
);
CREATE TABLE operations(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, operation text NOT NULL,
 key text NOT NULL, payload_hash text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(tenant_id,patient_id,operation,key),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id)
);
CREATE TABLE answers(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, cache_key text NOT NULL,
 principal_id uuid NOT NULL, revision bigint NOT NULL, body jsonb NOT NULL,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '5 minutes',
 PRIMARY KEY(tenant_id,patient_id,cache_key),
 FOREIGN KEY(tenant_id,patient_id) REFERENCES patients(tenant_id,id)
);
CREATE TABLE audit(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tenant_id uuid NOT NULL, patient_id uuid, principal_id uuid NOT NULL,
 action text NOT NULL, result text NOT NULL, request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE principals FORCE ROW LEVEL SECURITY;
CREATE POLICY principal_scope ON principals USING(tenant_id=pm_tenant() AND id=pm_actor());
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY assignment_scope ON assignments USING(tenant_id=pm_tenant() AND
 (principal_id=pm_actor() OR EXISTS(SELECT FROM principals WHERE administrator AND active)))
 WITH CHECK(tenant_id=pm_tenant() AND EXISTS(SELECT FROM principals WHERE administrator AND active));
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_read ON patients FOR SELECT USING(tenant_id=pm_tenant() AND pm_access(id));
CREATE POLICY patient_insert ON patients FOR INSERT WITH CHECK(tenant_id=pm_tenant()
 AND EXISTS(SELECT FROM principals WHERE administrator AND active));
CREATE POLICY patient_update ON patients FOR UPDATE USING(tenant_id=pm_tenant() AND
 (pm_access(id,true) OR EXISTS(SELECT FROM principals WHERE administrator AND active)))
 WITH CHECK(tenant_id=pm_tenant());
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['sources','jobs','facts','relations','operations','answers'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  IF t='sources' THEN
   EXECUTE 'CREATE POLICY scoped_read ON sources FOR SELECT USING(tenant_id=pm_tenant() AND
    pm_access(patient_id) AND (visibility=''patient_and_care_team'' OR pm_care(patient_id)))';
  ELSIF t='facts' THEN
   EXECUTE 'CREATE POLICY scoped_read ON facts FOR SELECT USING(tenant_id=pm_tenant() AND
    pm_access(patient_id) AND EXISTS(SELECT FROM sources s WHERE s.tenant_id=facts.tenant_id
      AND s.patient_id=facts.patient_id AND s.id=facts.source_id))';
  ELSIF t='jobs' THEN
   EXECUTE 'CREATE POLICY scoped_read ON jobs FOR SELECT USING(tenant_id=pm_tenant() AND
    pm_access(patient_id) AND EXISTS(SELECT FROM sources s WHERE s.tenant_id=jobs.tenant_id
      AND s.patient_id=jobs.patient_id AND s.id=jobs.source_id))';
  ELSIF t='answers' THEN
   EXECUTE 'CREATE POLICY scoped_read ON answers FOR SELECT USING(tenant_id=pm_tenant()
    AND pm_access(patient_id) AND principal_id=pm_actor())';
  ELSE
   EXECUTE format('CREATE POLICY scoped_read ON %I FOR SELECT USING(tenant_id=pm_tenant()
    AND pm_access(patient_id,true))',t);
  END IF;
  EXECUTE format('CREATE POLICY scoped_insert ON %I FOR INSERT WITH CHECK(tenant_id=pm_tenant()
   AND pm_access(patient_id,true))',t);
  EXECUTE format('CREATE POLICY scoped_update ON %I FOR UPDATE USING(tenant_id=pm_tenant()
   AND pm_access(patient_id,true)) WITH CHECK(tenant_id=pm_tenant())',t);
  EXECUTE format('CREATE POLICY scoped_delete ON %I FOR DELETE USING(tenant_id=pm_tenant()
   AND pm_access(patient_id,true))',t);
 END LOOP;
END $$;
-- Readers may cache only their own validated answer under their current assignment.
CREATE POLICY answer_reader_insert ON answers FOR INSERT WITH CHECK(tenant_id=pm_tenant()
 AND pm_access(patient_id) AND principal_id=pm_actor());
CREATE POLICY answer_reader_update ON answers FOR UPDATE USING(tenant_id=pm_tenant()
 AND pm_access(patient_id) AND principal_id=pm_actor()) WITH CHECK(principal_id=pm_actor());
ALTER TABLE audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_append ON audit FOR INSERT WITH CHECK(tenant_id=pm_tenant()
 AND principal_id=pm_actor());
GRANT USAGE ON SCHEMA public TO pm_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON patients,assignments,sources,jobs,facts,relations,operations,answers TO pm_runtime;
GRANT SELECT ON principals TO pm_runtime;
GRANT INSERT ON audit TO pm_runtime;
GRANT USAGE ON SEQUENCE audit_id_seq TO pm_runtime;
