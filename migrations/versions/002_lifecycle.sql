DROP POLICY patient_read ON patients;
CREATE POLICY patient_read ON patients FOR SELECT USING(tenant_id=pm_tenant() AND
 (pm_access(id) OR EXISTS(SELECT FROM principals WHERE administrator AND active)));
-- Administrative patient metadata access does not grant access to sources or facts.
DROP POLICY scoped_read ON answers;
CREATE POLICY scoped_read ON answers FOR SELECT USING(tenant_id=pm_tenant() AND
 pm_access(patient_id) AND (principal_id=pm_actor() OR pm_access(patient_id,true)));
ALTER TABLE sources ADD COLUMN purge_requested boolean NOT NULL DEFAULT false;
ALTER TABLE sources ADD COLUMN purge_after timestamptz;
ALTER TABLE sources ADD COLUMN purge_attempt integer NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN purge_error text;
CREATE TABLE request_budgets(
 tenant_id uuid NOT NULL, principal_id uuid NOT NULL, window_at timestamptz NOT NULL,
 count integer NOT NULL DEFAULT 1, PRIMARY KEY(tenant_id,principal_id,window_at)
);
ALTER TABLE request_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_budgets FORCE ROW LEVEL SECURITY;
CREATE POLICY budget_scope ON request_budgets USING(tenant_id=pm_tenant() AND principal_id=pm_actor())
 WITH CHECK(tenant_id=pm_tenant() AND principal_id=pm_actor());
GRANT SELECT,INSERT,UPDATE,DELETE ON request_budgets TO pm_runtime;
