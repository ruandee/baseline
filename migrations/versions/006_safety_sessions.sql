-- KAZE safety sessions (BL-25, decision 018). Sessions live only in tenants flagged safety_mode,
-- so residents and people going out never share a tenant. Every new table is patient-owned:
-- composite tenant/patient keys, forced RLS, and session-scoped foreign keys so contacts, checks,
-- locations and acknowledgements cannot point at another person's session.

-- The SECURITY DEFINER functions below must bypass forced RLS to scope by token or tenant
-- themselves. That only holds when their owner (the migration role) is superuser or BYPASSRLS.
DO $$
BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname = current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'migration 006 must run as a superuser or BYPASSRLS role (decision 018)';
 END IF;
END $$;
ALTER TABLE tenants ADD COLUMN safety_mode boolean NOT NULL DEFAULT false;

CREATE FUNCTION pm_safety_tenant() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
 SET search_path = public, pg_temp AS
 $$ SELECT coalesce((SELECT safety_mode FROM tenants WHERE id = pm_tenant()), false) $$;
REVOKE ALL ON FUNCTION pm_safety_tenant() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_safety_tenant() TO pm_runtime;

CREATE TABLE safety_sessions(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 40),
 status text NOT NULL DEFAULT 'arming'
  CHECK (status IN ('arming','active','escalating','acknowledged','ended')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 activated_at timestamptz,
 ends_at timestamptz NOT NULL,
 interval_min integer NOT NULL DEFAULT 45 CHECK (interval_min BETWEEN 1 AND 180),
 context_tags text[] NOT NULL DEFAULT '{}'
  CHECK (context_tags <@ ARRAY['exertion','loud_venue']::text[]),
 escalation_enabled boolean NOT NULL DEFAULT true,
 baseline_required integer NOT NULL DEFAULT 3 CHECK (baseline_required BETWEEN 1 AND 10),
 next_due_at timestamptz,
 last_checkin_at timestamptz,
 ladder_level integer NOT NULL DEFAULT 0 CHECK (ladder_level BETWEEN 0 AND 4),
 episode integer NOT NULL DEFAULT 0 CHECK (episode >= 0),
 ladder_trigger text CHECK (ladder_trigger IN ('missed_checkin','speech_change')),
 acknowledged_at timestamptz,
 ended_at timestamptz,
 end_reason text CHECK (end_reason IN ('user','expired')),
 delete_after timestamptz,
 PRIMARY KEY (tenant_id, patient_id, id),
 FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id),
 CHECK (ends_at > created_at AND ends_at <= created_at + interval '24 hours'),
 CHECK ((status = 'ended') = (ended_at IS NOT NULL)),
 CHECK ((status = 'ended') = (end_reason IS NOT NULL AND delete_after IS NOT NULL)),
 CHECK (delete_after IS NULL OR delete_after = ended_at + interval '24 hours'),
 CHECK (status <> 'arming' OR (activated_at IS NULL AND next_due_at IS NULL AND ladder_level = 0)),
 CHECK (status IN ('arming','ended') OR activated_at IS NOT NULL),
 CHECK (status <> 'active' OR ladder_level <= 1),
 CHECK (status <> 'escalating' OR ladder_level >= 2),
 CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL)
);
-- One open session per person; a second arm is a 409.
CREATE UNIQUE INDEX safety_sessions_one_open ON safety_sessions(tenant_id, patient_id)
 WHERE status <> 'ended';
-- Ended is terminal: nobody, including the runtime role, can reopen a session or move its
-- deletion time. Retention deletes ended rows; it never updates them.
CREATE FUNCTION pm_safety_session_terminal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status = 'ended' THEN
  RAISE EXCEPTION 'an ended safety session cannot be changed' USING ERRCODE = '42501';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER safety_sessions_terminal BEFORE UPDATE ON safety_sessions
 FOR EACH ROW EXECUTE FUNCTION pm_safety_session_terminal();
CREATE INDEX safety_sessions_due ON safety_sessions(tenant_id, next_due_at)
 WHERE status IN ('active','escalating');

CREATE TABLE safety_contacts(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, session_id uuid NOT NULL,
 contact_index integer NOT NULL CHECK (contact_index IN (1, 2)),
 name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
 phone_e164 text NOT NULL CHECK (phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 PRIMARY KEY (tenant_id, patient_id, session_id, contact_index),
 FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id),
 FOREIGN KEY (tenant_id, patient_id, session_id) REFERENCES safety_sessions(tenant_id, patient_id, id)
);

CREATE TABLE escalation_events(
 tenant_id uuid NOT NULL, patient_id uuid NOT NULL, id uuid NOT NULL,
 session_id uuid NOT NULL,
 episode integer NOT NULL CHECK (episode >= 1),
 level integer NOT NULL CHECK (level BETWEEN 1 AND 4),
 trigger text NOT NULL CHECK (trigger IN ('missed_checkin','speech_change')),
 channel text NOT NULL CHECK (channel IN ('nudge','sms')),
 contact_index integer,
 sent_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 delivery text NOT NULL DEFAULT 'pending' CHECK (delivery IN ('pending','logged','sent','failed')),
 message text,
 ack_token_hash bytea UNIQUE CHECK (ack_token_hash IS NULL OR octet_length(ack_token_hash) = 32),
 ack_expires_at timestamptz,
 ack_at timestamptz,
 PRIMARY KEY (tenant_id, patient_id, id),
 FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id),
 FOREIGN KEY (tenant_id, patient_id, session_id) REFERENCES safety_sessions(tenant_id, patient_id, id),
 FOREIGN KEY (tenant_id, patient_id, session_id, contact_index)
  REFERENCES safety_contacts(tenant_id, patient_id, session_id, contact_index),
 CHECK ((channel = 'nudge' AND level = 1 AND contact_index IS NULL AND ack_token_hash IS NULL)
     OR (channel = 'sms' AND level >= 2 AND contact_index IS NOT NULL)),
 CHECK ((ack_token_hash IS NULL) = (ack_expires_at IS NULL)),
 CHECK (ack_at IS NULL OR ack_token_hash IS NOT NULL),
 -- A duplicate scheduler pass conflicts instead of sending the same step twice.
 UNIQUE NULLS NOT DISTINCT (tenant_id, patient_id, session_id, episode, level, contact_index)
);

ALTER TABLE voice_checks ADD COLUMN session_id uuid, ADD COLUMN lat double precision,
 ADD COLUMN lon double precision, ADD COLUMN accuracy_m double precision;
ALTER TABLE voice_checks
 ADD CONSTRAINT voice_checks_session_fk FOREIGN KEY (tenant_id, patient_id, session_id)
  REFERENCES safety_sessions(tenant_id, patient_id, id),
 -- Location is stored only for checks inside an armed session.
 ADD CONSTRAINT voice_checks_location_needs_session
  CHECK (session_id IS NOT NULL OR (lat IS NULL AND lon IS NULL AND accuracy_m IS NULL)),
 ADD CONSTRAINT voice_checks_location_pair CHECK ((lat IS NULL) = (lon IS NULL)),
 ADD CONSTRAINT voice_checks_location_range CHECK (
  (lat IS NULL OR lat BETWEEN -90 AND 90) AND (lon IS NULL OR lon BETWEEN -180 AND 180)
  AND (accuracy_m IS NULL OR (accuracy_m >= 0 AND lat IS NOT NULL)));
CREATE INDEX voice_checks_session ON voice_checks(tenant_id, patient_id, session_id, ts)
 WHERE session_id IS NOT NULL;

DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['safety_sessions','safety_contacts','escalation_events'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
  EXECUTE format('CREATE POLICY care_read ON %I FOR SELECT USING(tenant_id=pm_tenant() AND pm_care(patient_id))', t);
 END LOOP;
END $$;
-- Only the person (importer on their own row) arms a session and names its contacts.
CREATE POLICY owner_insert ON safety_sessions FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_access(patient_id,true) AND pm_safety_tenant());
CREATE POLICY owner_insert ON safety_contacts FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_access(patient_id,true) AND pm_safety_tenant());
-- The person and the kaze-service principal (nurse) move ladder state and record steps.
CREATE POLICY care_update ON safety_sessions FOR UPDATE USING(tenant_id=pm_tenant() AND pm_care(patient_id))
 WITH CHECK(tenant_id=pm_tenant() AND pm_care(patient_id));
CREATE POLICY care_insert ON escalation_events FOR INSERT WITH CHECK(
 tenant_id=pm_tenant() AND pm_care(patient_id) AND pm_safety_tenant());
CREATE POLICY care_update ON escalation_events FOR UPDATE USING(tenant_id=pm_tenant() AND pm_care(patient_id))
 WITH CHECK(tenant_id=pm_tenant() AND pm_care(patient_id));

GRANT SELECT, INSERT ON safety_sessions, safety_contacts, escalation_events TO pm_runtime;
-- Column-level UPDATE: ladder/lifecycle state only. Identity, schedule, contacts, the stored
-- message, token hash and ack time are written on insert or by the SECURITY DEFINER functions.
GRANT UPDATE (status, activated_at, next_due_at, last_checkin_at, ladder_level, episode,
 ladder_trigger, acknowledged_at, ended_at, end_reason, delete_after) ON safety_sessions TO pm_runtime;
GRANT UPDATE (delivery, sent_at) ON escalation_events TO pm_runtime;

-- Public acknowledgement (BL-27's /ack/{token} has no bearer identity). Takes the SHA-256 of the
-- token, never the token. Locks the session before the event, matching the scheduler's order.
-- Returns only 'acknowledged', 'recorded' or 'invalid' so a caller learns nothing else.
CREATE FUNCTION pm_acknowledge_escalation(p_token_hash bytea) RETURNS text
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE e escalation_events; s safety_sessions;
BEGIN
 SELECT * INTO e FROM escalation_events WHERE ack_token_hash = p_token_hash AND channel = 'sms';
 IF NOT FOUND THEN RETURN 'invalid'; END IF;
 SELECT * INTO s FROM safety_sessions WHERE tenant_id = e.tenant_id AND patient_id = e.patient_id
  AND id = e.session_id FOR UPDATE;
 SELECT * INTO e FROM escalation_events WHERE tenant_id = e.tenant_id AND patient_id = e.patient_id
  AND id = e.id FOR UPDATE;
 IF NOT FOUND OR s.status = 'ended' OR e.ack_expires_at <= clock_timestamp() THEN
  RETURN 'invalid';
 END IF;
 IF e.ack_at IS NULL THEN
  UPDATE escalation_events SET ack_at = clock_timestamp()
   WHERE tenant_id = e.tenant_id AND patient_id = e.patient_id AND id = e.id;
 END IF;
 IF s.status = 'escalating' AND e.episode = s.episode THEN
  UPDATE safety_sessions SET status = 'acknowledged', acknowledged_at = clock_timestamp()
   WHERE tenant_id = s.tenant_id AND patient_id = s.patient_id AND id = s.id;
  RETURN 'acknowledged';
 END IF;
 RETURN 'recorded';
END $$;
REVOKE ALL ON FUNCTION pm_acknowledge_escalation(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_acknowledge_escalation(bytea) TO pm_runtime;

-- Retention: within the caller's tenant only, expire sessions past ends_at, then delete sessions
-- (with their checks, locations, assessments, contacts and events) 24 h after they ended.
-- voice_checks stays append-only for the runtime role; only this function deletes session checks.
CREATE FUNCTION pm_retire_safety_sessions() RETURNS integer
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE t uuid := pm_tenant(); r record; n integer := 0;
BEGIN
 IF t IS NULL OR NOT EXISTS(SELECT FROM principals WHERE tenant_id = t AND id = pm_actor() AND active) THEN
  RAISE EXCEPTION 'inactive identity' USING ERRCODE = '42501';
 END IF;
 UPDATE safety_sessions SET status = 'ended', end_reason = 'expired', ended_at = ends_at,
  delete_after = ends_at + interval '24 hours', next_due_at = NULL
  WHERE tenant_id = t AND status <> 'ended' AND ends_at <= clock_timestamp();
 FOR r IN SELECT tenant_id, patient_id, id FROM safety_sessions
  WHERE tenant_id = t AND status = 'ended' AND delete_after <= clock_timestamp() FOR UPDATE LOOP
  DELETE FROM assessments a USING voice_checks v
   WHERE a.tenant_id = r.tenant_id AND a.patient_id = r.patient_id AND v.tenant_id = r.tenant_id
   AND v.patient_id = r.patient_id AND v.session_id = r.id AND a.check_id = v.id;
  DELETE FROM voice_checks WHERE tenant_id = r.tenant_id AND patient_id = r.patient_id AND session_id = r.id;
  DELETE FROM escalation_events WHERE tenant_id = r.tenant_id AND patient_id = r.patient_id AND session_id = r.id;
  DELETE FROM safety_contacts WHERE tenant_id = r.tenant_id AND patient_id = r.patient_id AND session_id = r.id;
  -- The arm idempotency snapshot copies contacts and the session; it goes too.
  DELETE FROM operations WHERE tenant_id = r.tenant_id AND patient_id = r.patient_id
   AND operation = 'arm_session' AND result->>'id' = r.id::text;
  DELETE FROM safety_sessions WHERE tenant_id = r.tenant_id AND patient_id = r.patient_id AND id = r.id;
  INSERT INTO audit(tenant_id, patient_id, principal_id, action, result, request_id)
   VALUES (r.tenant_id, r.patient_id, pm_actor(), 'purge_safety_session', 'ok', gen_random_uuid());
  n := n + 1;
 END LOOP;
 RETURN n;
END $$;
REVOKE ALL ON FUNCTION pm_retire_safety_sessions() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_retire_safety_sessions() TO pm_runtime;
