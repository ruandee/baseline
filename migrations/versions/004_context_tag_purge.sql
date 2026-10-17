-- BL-09: purging a source must also remove the quotes copied into context_tags. Tags stay
-- append-only otherwise: a tag can be deleted only while its source is marked for purge.
CREATE POLICY care_delete_purging ON context_tags FOR DELETE USING(
 tenant_id=pm_tenant() AND pm_care(patient_id) AND EXISTS(
  SELECT FROM sources s WHERE s.tenant_id=context_tags.tenant_id
   AND s.patient_id=context_tags.patient_id AND s.id=context_tags.source_id AND s.purge_requested));
GRANT DELETE ON context_tags TO pm_runtime;
