-- SCD2 Data Quality Investigation - BigQuery Queries
-- Date: 2025-11-03
-- Project: prismatic-smoke-463810-c1
-- Dataset: minietl

-- ============================================================================
-- QUERY 1: Check etledges Table Schema
-- ============================================================================
-- Purpose: Understand actual structure of lineage graph table
-- Result: parent_id, child_id, relationship_type (no is_active column)

SELECT column_name, data_type, is_nullable
FROM `prismatic-smoke-463810-c1.minietl`.INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'etledges'
ORDER BY ordinal_position;

-- Expected Result:
-- +-------------------+-----------+-------------+
-- |    column_name    | data_type | is_nullable |
-- +-------------------+-----------+-------------+
-- | parent_id         | STRING    | YES         |
-- | child_id          | STRING    | YES         |
-- | relationship_type | STRING    | YES         |
-- +-------------------+-----------+-------------+

-- ============================================================================
-- QUERY 2: Check etledges Data Volume
-- ============================================================================
-- Purpose: Verify if lineage graph is populated
-- Result: 0 rows (completely empty)

SELECT COUNT(*) as total_edges
FROM `prismatic-smoke-463810-c1.minietl`.etledges;

-- Expected Result:
-- +-------------+
-- | total_edges |
-- +-------------+
-- |           0 |
-- +-------------+

-- ============================================================================
-- QUERY 3: Find Dependencies for OBJ0002
-- ============================================================================
-- Purpose: Identify what depends on OBJ0002
-- Result: No rows (no dependencies exist)

SELECT
  'Upstream (parents of OBJ0002)' as direction,
  parent_id,
  NULL as child_id,
  relationship_type
FROM `prismatic-smoke-463810-c1.minietl`.etledges
WHERE child_id = 'OBJ0002'

UNION ALL

SELECT
  'Downstream (children of OBJ0002)' as direction,
  NULL as parent_id,
  child_id,
  relationship_type
FROM `prismatic-smoke-463810-c1.minietl`.etledges
WHERE parent_id = 'OBJ0002'

ORDER BY direction, parent_id, child_id;

-- Expected Result: No rows (empty result set)

-- ============================================================================
-- QUERY 4: Search for "mitl-extraction-function"
-- ============================================================================
-- Purpose: Find missing object that user reported
-- Result: Only "minietl-daily-extraction" found (WRONG object for OBJ0002)

SELECT
  object_id,
  name,
  object_type,
  version,
  effective_start,
  effective_end,
  status
FROM `prismatic-smoke-463810-c1.minietl`.etlobjectscd2
WHERE LOWER(name) LIKE '%mitl%'
   OR LOWER(name) LIKE '%extraction%'
   OR LOWER(name) LIKE '%function%'
ORDER BY object_id, version DESC;

-- Expected Result:
-- +-----------+--------------------------+-------------+---------+-----------------+---------------+--------+
-- | object_id |           name           | object_type | version | effective_start | effective_end | status |
-- +-----------+--------------------------+-------------+---------+-----------------+---------------+--------+
-- | OBJ0002   | minietl-daily-extraction | TRIGGER     |       2 |      2025-11-02 |          NULL | active |
-- +-----------+--------------------------+-------------+---------+-----------------+---------------+--------+

-- ============================================================================
-- QUERY 5: Get All Current Objects
-- ============================================================================
-- Purpose: See complete current inventory
-- Result: 9 current objects with OBJ0002 showing WRONG type

SELECT
  object_id,
  name,
  object_type,
  version,
  effective_start,
  effective_end,
  status
FROM `prismatic-smoke-463810-c1.minietl`.etlobjectscd2
WHERE effective_end IS NULL
ORDER BY object_id;

-- Expected Result (9 rows):
-- +-----------+----------------------------------------------------------------------------------------+-------------+---------+-----------------+---------------+--------+
-- | object_id |                                          name                                          | object_type | version | effective_start | effective_end | status |
-- +-----------+----------------------------------------------------------------------------------------+-------------+---------+-----------------+---------------+--------+
-- | OBJ0001   | daily-etl-job                                                                          | TRIGGER     |       1 |      2025-11-02 |          NULL | active |
-- | OBJ0002   | minietl-daily-extraction                                                               | TRIGGER     |       2 |      2025-11-02 |          NULL | active |  ← WRONG!
-- | OBJ0003   | telemetry-events                                                                       | PUBSUB      |       2 |      2025-11-02 |          NULL | active |
-- | OBJ0004   | user-clicks                                                                            | PUBSUB      |       2 |      2025-11-02 |          NULL | active |
-- | OBJ0005   | sales-orders                                                                           | PUBSUB      |       2 |      2025-11-02 |          NULL | active |
-- | OBJ0006   | gcf-pubsub-to-gcs-us-central1-telemetry-events                                         | PUBSUB      |       2 |      2025-11-02 |          NULL | active |
-- | OBJ0007   | eventarc-us-central1-taxi-data-control-sub-090                                         | PUBSUB      |       2 |      2025-11-02 |          NULL | active |
-- | OBJ0008   | projects/prismatic-smoke-463810-c1/locations/us-central1/workflows/etl-workflow        | WORKFLOW    |       2 |      2025-11-02 |          NULL | active |
-- | OBJ0009   | projects/prismatic-smoke-463810-c1/locations/us-central1/workflows/user-daily-pipeline | WORKFLOW    |       1 |      2025-11-02 |          NULL | active |
-- +-----------+----------------------------------------------------------------------------------------+-------------+---------+-----------------+---------------+--------+

-- ============================================================================
-- QUERY 6: Get Complete Version History for OBJ0002 and OBJ0003
-- ============================================================================
-- Purpose: Understand the merge conflict - what happened to both objects
-- Result: Shows the critical issue clearly

SELECT
  object_id,
  name,
  object_type,
  version,
  effective_start,
  effective_end,
  status
FROM `prismatic-smoke-463810-c1.minietl`.etlobjectscd2
WHERE object_id IN ('OBJ0002', 'OBJ0003')
ORDER BY object_id, version;

-- Expected Result (4 rows):
-- +-----------+--------------------------+-------------+---------+-----------------+---------------+--------+
-- | object_id |           name           | object_type | version | effective_start | effective_end | status |
-- +-----------+--------------------------+-------------+---------+-----------------+---------------+--------+
-- | OBJ0002   | telemetry-events         | PUBSUB      |       1 |      2025-11-02 |    2025-11-02 | active |
-- | OBJ0002   | minietl-daily-extraction | TRIGGER     |       2 |      2025-11-02 |          NULL | active |  ← WRONG: Type changed!
-- | OBJ0003   | user-clicks              | PUBSUB      |       1 |      2025-11-02 |    2025-11-02 | active |
-- | OBJ0003   | telemetry-events         | PUBSUB      |       2 |      2025-11-02 |          NULL | active |  ← OBJ0003 filled the gap
-- +-----------+--------------------------+-------------+---------+-----------------+---------------+--------+

-- ============================================================================
-- ANALYSIS FROM QUERIES
-- ============================================================================

-- KEY FINDINGS:
-- 1. etledges table has correct schema but zero rows
--    → Lineage graph not yet populated
--    → Safe to fix OBJ0002 (no dependencies to update)

-- 2. etledges is empty, so OBJ0002 has no dependencies
--    → No cascading failures from this SCD2 violation
--    → Fix is purely data correction

-- 3. OBJ0002 version history shows clear SCD2 violation:
--    v1: telemetry-events (PUBSUB) → v2: minietl-daily-extraction (TRIGGER)
--    → Type changed from PUBSUB to TRIGGER (ILLEGAL in SCD2)
--    → Completely different entities assigned same ID

-- 4. OBJ0003 shows parallel evolution:
--    v1: user-clicks (PUBSUB) → v2: telemetry-events (PUBSUB)
--    → OBJ0003 v2 filled the gap left by OBJ0002's wrong update

-- 5. "mitl-extraction-function" is not in database
--    → Search for %mitl%, %extraction%, %function% patterns returns only 1 match
--    → Likely never existed or was never discovered

-- ============================================================================
-- REMEDIATION QUERIES (See SCD2_REMEDIATION_PLAN.md for full context)
-- ============================================================================

-- STEP 1: Close the bad v2 record for OBJ0002
UPDATE `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
SET effective_end = CURRENT_DATE()
WHERE object_id = 'OBJ0002'
  AND version = 2
  AND name = 'minietl-daily-extraction'
  AND object_type = 'TRIGGER';

-- STEP 2: Restore OBJ0002 to original (correct) v1
UPDATE `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
SET effective_end = NULL
WHERE object_id = 'OBJ0002'
  AND version = 1
  AND name = 'telemetry-events'
  AND object_type = 'PUBSUB';

-- STEP 3: Create new object for minietl-daily-extraction
INSERT INTO `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
(
  object_id,
  name,
  object_type,
  version,
  effective_start,
  effective_end,
  status
)
VALUES
(
  'OBJ0010',
  'minietl-daily-extraction',
  'TRIGGER',
  1,
  CURRENT_DATE(),
  NULL,
  'active'
);

-- STEP 4: Create audit log entry (if table exists)
-- See SCD2_REMEDIATION_PLAN.md for full audit log insert statement

-- ============================================================================
-- VERIFICATION QUERIES (Run after remediation)
-- ============================================================================

-- Verify OBJ0002 v2 is closed
SELECT object_id, version, name, object_type, effective_end
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE object_id = 'OBJ0002'
ORDER BY version;

-- Should show:
-- OBJ0002, v1, telemetry-events, PUBSUB, NULL (current)
-- OBJ0002, v2, minietl-daily-extraction, TRIGGER, 2025-11-03 (closed)

-- Verify OBJ0010 was created
SELECT *
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE object_id = 'OBJ0010';

-- Should show 1 row with:
-- object_id: OBJ0010
-- name: minietl-daily-extraction
-- object_type: TRIGGER
-- version: 1
-- effective_end: NULL

-- Verify current objects now 10 (was 9)
SELECT COUNT(*) as current_objects
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE effective_end IS NULL;

-- Should show: 10

-- ============================================================================
-- END OF INVESTIGATION QUERIES
-- ============================================================================
