-- BL-27: a durable at-most-once delivery claim and synchronous public-ack expiry.
DO $$
BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'migration 008 requires a superuser or BYPASSRLS role';
 END IF;
END $$;
ALTER TABLE escalation_events ADD COLUMN delivery_started_at timestamptz;
GRANT UPDATE(delivery_started_at) ON escalation_events TO pm_runtime;

-- A claimed attempt cannot be reset through the runtime role to resend the same event.
CREATE FUNCTION pm_keep_delivery_claim() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.delivery_started_at IS NOT NULL AND NEW.delivery_started_at IS DISTINCT FROM OLD.delivery_started_at THEN
  RAISE EXCEPTION 'delivery claim is immutable' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER escalation_delivery_claim BEFORE UPDATE ON escalation_events
 FOR EACH ROW EXECUTE FUNCTION pm_keep_delivery_claim();

CREATE OR REPLACE FUNCTION pm_acknowledge_escalation(p_token_hash bytea) RETURNS text
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE e escalation_events; s safety_sessions; checked_at timestamptz;
BEGIN
 SELECT * INTO e FROM escalation_events WHERE ack_token_hash=p_token_hash AND channel='sms';
 IF NOT FOUND THEN RETURN 'invalid'; END IF;
 SELECT * INTO s FROM safety_sessions WHERE tenant_id=e.tenant_id AND patient_id=e.patient_id
  AND id=e.session_id FOR UPDATE;
 IF NOT FOUND THEN RETURN 'invalid'; END IF;
 SELECT * INTO e FROM escalation_events WHERE tenant_id=e.tenant_id AND patient_id=e.patient_id
  AND id=e.id FOR UPDATE;
 IF NOT FOUND THEN RETURN 'invalid'; END IF;
 checked_at := clock_timestamp();
 IF s.status='ended' THEN RETURN 'invalid'; END IF;
 IF s.ends_at<=checked_at THEN
  UPDATE safety_sessions SET status='ended',ended_at=ends_at,end_reason='expired',
   delete_after=ends_at+interval '24 hours',next_due_at=NULL
   WHERE tenant_id=s.tenant_id AND patient_id=s.patient_id AND id=s.id;
  RETURN 'invalid';
 END IF;
 IF e.ack_expires_at IS NULL OR e.ack_expires_at<=checked_at THEN RETURN 'invalid'; END IF;
 IF e.ack_at IS NOT NULL THEN RETURN 'recorded'; END IF;
 UPDATE escalation_events SET ack_at=checked_at
  WHERE tenant_id=e.tenant_id AND patient_id=e.patient_id AND id=e.id;
 IF s.status='escalating' AND e.episode=s.episode THEN
  UPDATE safety_sessions SET status='acknowledged',acknowledged_at=checked_at
   WHERE tenant_id=s.tenant_id AND patient_id=s.patient_id AND id=s.id;
  RETURN 'acknowledged';
 END IF;
 RETURN 'recorded';
END $$;
REVOKE ALL ON FUNCTION pm_acknowledge_escalation(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pm_acknowledge_escalation(bytea) TO pm_runtime;
