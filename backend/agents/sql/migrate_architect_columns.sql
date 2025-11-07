-- Migration script: Remove architect decision columns from etlobjectscd2
-- These columns are now in object_priority_overrides table
-- Run this script after columns are added to object_priority_overrides

-- Drop architect decision columns from core table
ALTER TABLE `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
DROP COLUMN IF EXISTS priority,
DROP COLUMN IF EXISTS is_decommission,
DROP COLUMN IF EXISTS decommission_reason,
DROP COLUMN IF EXISTS architect_notes,
DROP COLUMN IF EXISTS architect_reviewed_by,
DROP COLUMN IF EXISTS architect_review_timestamp,
DROP COLUMN IF EXISTS architect_approval_id,
DROP COLUMN IF EXISTS architect_approval_status,
DROP COLUMN IF EXISTS architect_approval_timestamp;

-- Verify the core table now only has core metadata columns
-- Expected columns:
-- - object_id, object_type, name, parent_id, version, status
-- - schedule_time, metadata
-- - effective_start, effective_end, created_at, updated_at

SELECT column_name, data_type
FROM `prismatic-smoke-463810-c1.minietl.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'etlobjectscd2'
ORDER BY ordinal_position;
