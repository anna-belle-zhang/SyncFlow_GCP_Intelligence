# SCD2 Data Modeling Solution Design

**Problem**: OBJ0002 assigned to two different object types (PUBSUB → TRIGGER) violates SCD2 Type 2 rules

**Root Cause**: Object ID assignment based only on object **name**, not considering **type**

---

## Current Data Model (BROKEN)

```
etlobjectscd2 table:
┌─────────────┬──────────────────────┬─────────────┬────────┐
│ object_id   │ name                 │ object_type │ v_no   │
├─────────────┼──────────────────────┼─────────────┼────────┤
│ OBJ0002     │ telemetry-events     │ PUBSUB      │ 1      │ ← Original
│ OBJ0002     │ minietl-daily-extr.  │ TRIGGER     │ 2-3    │ ← WRONG REUSE
│ OBJ0003     │ telemetry-events     │ PUBSUB      │ 2      │ ← Duplicate
└─────────────┴──────────────────────┴─────────────┴────────┘

Problem: Same object_id = different logical entities
```

---

## Root Cause Analysis

**File**: `backend/object_assigner.py`

The code **ALREADY HAS THE FIX** (composite key using `type::name` format):

```python
@staticmethod
def _make_key(name: str, object_type: Optional[Union[ObjectType, str]]) -> str:
    """Build the de-duplicated assignment key."""
    if isinstance(object_type, ObjectType):
        type_value = object_type.value
    elif object_type:
        type_value = str(object_type)
    else:
        return name
    return f"{type_value}::{name}"  # ✅ COMPOSITE KEY
```

**The Problem**: Existing data in BigQuery was created **before** this code fix was deployed.

**What Happened:**
1. Old system: "telemetry-events" → Assigned OBJ0002 (name-only key)
2. Old system: "minietl-daily-extraction" found → Reused OBJ0002 (name didn't match exactly, but got reused anyway)
3. Result: OBJ0002 points to 2 different entity types in SCD2 history

**Current minietl behavior:**
- Uses new composite key: `TRIGGER::minietl-daily-extraction`
- But has backward compatibility for legacy name-only lookups
- When re-run, it finds old OBJ0002 and creates v3 with same ID

---

## Proposed Solution: Clean Data + Disable Backward Compatibility

The code fix (composite key) is **already deployed**. The issue is legacy data.

### Option A: Clean Data Only (Recommended)
1. Delete bad SCD2 records from BigQuery (see SCD2_FIX.md)
2. Re-run minietl with current code
3. Code will use composite key and won't reuse IDs

### Option B: Clean Data + Remove Backward Compatibility
1. Delete bad SCD2 records (SCD2_FIX.md)
2. Modify object_assigner.py to remove legacy key fallback:
```python
# In assign_object(), remove this line:
cached_id = self.assignments.get(key) or self.assignments.get(legacy_key)

# Change to:
cached_id = self.assignments.get(key)  # ✅ Only composite key
```
3. Re-run minietl
4. All new objects use composite key, no backward compatibility

**Recommendation**: Option A is simpler and maintains compatibility for edge cases.

---

## Result with Fix

```
After applying composite key:

┌─────────────┬──────────────────────┬─────────────┬────────┐
│ object_id   │ name                 │ object_type │ v_no   │
├─────────────┼──────────────────────┼─────────────┼────────┤
│ OBJ0002     │ telemetry-events     │ PUBSUB      │ 1-2    │ ✅ Correct
│ OBJ0010     │ minietl-daily-extr.  │ TRIGGER     │ 1      │ ✅ New ID
│ OBJ0003     │ user-clicks          │ PUBSUB      │ 1-2    │ ✅ Correct
└─────────────┴──────────────────────┴─────────────┴────────┘

Each (name, type) pair gets unique object_id
SCD2 Type 2 integrity maintained
```

---

## Implementation Plan

### Step 1: Data Cleanup (SQL)
See `SCD2_FIX.md` Steps 1-4 for complete SQL remediation.

Summary:
```sql
-- Close bad v3
UPDATE etlobjectscd2 SET effective_end = CURRENT_DATE()
WHERE object_id = 'OBJ0002' AND version = 3;

-- Restore correct v1
UPDATE etlobjectscd2 SET effective_end = NULL
WHERE object_id = 'OBJ0002' AND version = 1;

-- Create new ID for minietl-daily-extraction
INSERT INTO etlobjectscd2
(object_id, name, object_type, version, effective_start, effective_end, status)
VALUES ('OBJ0010', 'minietl-daily-extraction', 'TRIGGER', 1, CURRENT_DATE(), NULL, 'active');
```

### Step 2: (Optional) Remove Backward Compatibility
If you want to prevent this issue in future, remove the legacy key fallback in object_assigner.py line 79:

```python
# Change from:
cached_id = self.assignments.get(key) or self.assignments.get(legacy_key)

# To:
cached_id = self.assignments.get(key)
```

### Step 3: Re-run minietl
```bash
python3 minietl_cli_enhanced.py --sa /path/to/sa.json --inventory
```

Expected:
- OBJ0002: telemetry-events (PUBSUB) - stays as v1 or v2
- OBJ0010: minietl-daily-extraction (TRIGGER) - new v1
- NO v3 created (no collision)

---

## Data Model Changes Summary

| Aspect | Current State | After Fix |
|--------|-------------|-----------|
| Assignment Key | Composite (type::name) ✅ Code is correct | No change needed |
| OBJ0002 Identity | 2 different objects in history | 1 correct object (telemetry-events) |
| minietl-daily-extraction ID | OBJ0002 v3 (wrong) | OBJ0010 v1 (correct) |
| SCD2 Compliance | ❌ Violated (bad data) | ✅ Compliant (clean data) |

---

## Why This Design Works

**SCD2 Type 2 Core Principle:**
- Same object_id = same logical entity across time
- Changes create new versions with effective date ranges

**Composite Key (`type::name`) Ensures:**
- `PUBSUB::telemetry-events` gets OBJ0002
- `TRIGGER::minietl-daily-extraction` gets OBJ0010
- Different entity types never share IDs even if names overlap
- Multiple versions of same entity share one object_id ✅

---

## Verification After Fix

```bash
# Run minietl inventory again
python3 minietl_cli_enhanced.py --sa ~/.gcp/sa.json --inventory

# Check current objects
bq query "
SELECT object_id, name, object_type, version
FROM minietl.etlobjectscd2
WHERE effective_end IS NULL
ORDER BY object_id;
"

# Expected: 10 current objects
# OBJ0002: telemetry-events (PUBSUB)
# OBJ0010: minietl-daily-extraction (TRIGGER)
# No duplicate (type::name) pairs
```

---

## Files to Update

1. **`SCD2_FIX.md`** - Run Steps 1-4 SQL
2. **`backend/object_assigner.py`** - (Optional) Line 79: Remove legacy key fallback

Done. The data model design is correct, just needs data cleanup.
