-- Create priority override table and enriched view for SCD2 objects.
-- Run this script once per project (dataset defaults to `minietl`).

CREATE TABLE IF NOT EXISTS `prismatic-smoke-463810-c1.minietl.object_priority_overrides` (
  object_id STRING NOT NULL,
  priority STRING NOT NULL,
  is_decommission BOOL,
  decommission_reason STRING,
  decommission_date STRING,
  replacement_id STRING,
  architect_notes STRING,
  architect_review_timestamp TIMESTAMP,
  architect_reviewed_by STRING,
  architect_approval_id STRING,
  architect_approval_status STRING,
  architect_approval_timestamp TIMESTAMP,
  updated_by STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
) OPTIONS(
  description = 'Architect-assigned priority overrides and decisions for SCD2 objects',
  partition_expiration_ms=7776000000
);

CREATE OR REPLACE VIEW `prismatic-smoke-463810-c1.minietl.etlobjectscd2_enriched` AS
SELECT
  scd.* EXCEPT(priority),
  COALESCE(override.priority, scd.priority) AS priority,
  override.is_decommission,
  override.decommission_reason,
  override.decommission_date,
  override.replacement_id,
  override.architect_notes,
  override.architect_review_timestamp,
  override.architect_reviewed_by,
  override.architect_approval_id,
  override.architect_approval_status,
  override.architect_approval_timestamp,
  override.updated_by AS priority_updated_by,
  override.updated_at AS priority_updated_at
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2` AS scd
LEFT JOIN (
  SELECT
    object_id,
    priority,
    is_decommission,
    decommission_reason,
    decommission_date,
    replacement_id,
    architect_notes,
    architect_review_timestamp,
    architect_reviewed_by,
    architect_approval_id,
    architect_approval_status,
    architect_approval_timestamp,
    updated_by,
    updated_at
  FROM (
    SELECT
      object_id,
      priority,
      is_decommission,
      decommission_reason,
      decommission_date,
      replacement_id,
      architect_notes,
      architect_review_timestamp,
      architect_reviewed_by,
      architect_approval_id,
      architect_approval_status,
      architect_approval_timestamp,
      updated_by,
      updated_at,
      ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY updated_at DESC) AS rn
    FROM `prismatic-smoke-463810-c1.minietl.object_priority_overrides`
  )
  WHERE rn = 1
) AS override
ON override.object_id = scd.object_id
WHERE scd.effective_end IS NULL;
