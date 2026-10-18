-- Only the trusted, transaction-local scoring context can read exact patient facts
-- for a PSW-submitted check. Ordinary PSW retrieval and receipts remain score-free.
CREATE POLICY check_scoring_read ON facts FOR SELECT USING(
 tenant_id=pm_tenant() AND pm_check_scoring(patient_id));
