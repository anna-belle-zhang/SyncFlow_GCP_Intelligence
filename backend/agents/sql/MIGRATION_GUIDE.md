# Database Schema Migration Guide

## Overview
This guide walks through migrating architect decision columns from the core `etlobjectscd2` table to the `object_priority_overrides` table and updating the enriched view.

## Migration Steps

### Step 1: Verify Current State (Optional but Recommended)

```sql
-- Check current columns in etlobjectscd2
SELECT column_name, data_type
FROM `prismatic-smoke-463810-c1.minietl.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'etlobjectscd2'
ORDER BY ordinal_position;

-- Check current columns in object_priority_overrides
SELECT column_name, data_type
FROM `prismatic-smoke-463810-c1.minietl.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'object_priority_overrides'
ORDER BY ordinal_position;
```

### Step 2: Run the Complete Schema Update

Execute the script to create/update the tables and view:

```bash
# Using bq CLI
bq query < backend/agents/sql/create_priority_overrides.sql
```

**OR** manually run in BigQuery console:

```sql
-- Create/update object_priority_overrides table with all architect columns
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

-- Create/replace enriched view with ALL architect columns
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
```

### Step 3: Drop Architect Columns from Core Table

```sql
-- Remove architect decision columns from core table
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
```

### Step 4: Verify Migration Success

```sql
-- Verify core table now only has core columns
SELECT column_name, data_type
FROM `prismatic-smoke-463810-c1.minietl.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'etlobjectscd2'
ORDER BY ordinal_position;

-- Expected columns:
-- object_id, object_type, name, parent_id, version, status
-- schedule_time, metadata, effective_start, effective_end, created_at, updated_at

-- Verify override table has all architect columns
SELECT column_name, data_type
FROM `prismatic-smoke-463810-c1.minietl.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'object_priority_overrides'
ORDER BY ordinal_position;

-- Verify enriched view has all architect columns
SELECT column_name, data_type
FROM `prismatic-smoke-463810-c1.minietl.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'etlobjectscd2_enriched'
ORDER BY ordinal_position;

-- Test the enriched view with a sample query
SELECT
  object_id,
  name,
  priority,
  is_decommission,
  architect_notes,
  architect_reviewed_by,
  priority_updated_by,
  priority_updated_at
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2_enriched`
LIMIT 10;
```

## Table & View Columns After Migration

### Core Table: `etlobjectscd2`
```
object_id (STRING)              - Primary identifier
object_type (STRING)            - Type of GCP resource
name (STRING)                   - Display name
parent_id (STRING)              - Parent object reference
version (INT64)                 - Version number
status (STRING)                 - Resource status (active/inactive)
schedule_time (STRING)          - Scheduler config
metadata (STRING)               - JSON metadata
effective_start (DATE)          - SCD2 validity start
effective_end (DATE)            - SCD2 validity end
created_at (TIMESTAMP)          - Creation timestamp
updated_at (TIMESTAMP)          - Last update timestamp
```

### Override Table: `object_priority_overrides`
```
object_id (STRING)              - Foreign key to etlobjectscd2
priority (STRING)               - CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION
is_decommission (BOOL)          - Decommission flag
decommission_reason (STRING)    - Why being decommissioned
decommission_date (STRING)      - Target removal date
replacement_id (STRING)         - ID of replacement object
architect_notes (STRING)        - Architect context/decisions
architect_review_timestamp (TIMESTAMP) - When reviewed
architect_reviewed_by (STRING)  - Who reviewed
architect_approval_id (STRING)  - Approval/proposal ID
architect_approval_status (STRING) - approved/modified/pending
architect_approval_timestamp (TIMESTAMP) - When approved
updated_by (STRING)             - User who made change
updated_at (TIMESTAMP)          - When changed
```

### Enriched View: `etlobjectscd2_enriched`
**All core columns PLUS:**
```
priority (STRING)               - From override or core, coalesced
is_decommission (BOOL)          - From latest override
decommission_reason (STRING)    - From latest override
decommission_date (STRING)      - From latest override
replacement_id (STRING)         - From latest override
architect_notes (STRING)        - From latest override
architect_review_timestamp (TIMESTAMP) - From latest override
architect_reviewed_by (STRING)  - From latest override
architect_approval_id (STRING)  - From latest override
architect_approval_status (STRING) - From latest override
architect_approval_timestamp (TIMESTAMP) - From latest override
priority_updated_by (STRING)    - From latest override (updated_by)
priority_updated_at (TIMESTAMP) - From latest override (updated_at)
```

## Code Updates Included

All backend code has been updated to:
1. ✅ Write architect decisions to `object_priority_overrides` only
2. ✅ Read architect fields from `etlobjectscd2_enriched` view
3. ✅ Use parameterized queries to prevent SQL injection

### Updated Files:
- `backend/agents/tools/update_tools.py` - Write operations
- `backend/architect_agent.py` - Architect review workflow
- `backend/agents/tools/inventory_tools.py` - Inventory queries
- `backend/agents/tools/inventory_tools_standalone.py` - Standalone tools
- `backend/syncflow_server.py` - API endpoints

## Rollback Plan

If you need to rollback:

1. **Restore architect columns to etlobjectscd2** (from backup)
2. **Update the enriched view** to read from core table
3. **Keep object_priority_overrides** for reference

```sql
-- Restore enriched view to read from core table
CREATE OR REPLACE VIEW `prismatic-smoke-463810-c1.minietl.etlobjectscd2_enriched` AS
SELECT *
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE effective_end IS NULL;
```

## Questions?

Verify the migration worked with:
```sql
-- Check for any data loss
SELECT COUNT(*) as total_objects
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE effective_end IS NULL;

-- Check overrides exist
SELECT COUNT(DISTINCT object_id) as reviewed_objects
FROM `prismatic-smoke-463810-c1.minietl.object_priority_overrides`;
```
