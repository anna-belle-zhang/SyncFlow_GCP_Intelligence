# SCD2 Data Quality Issue - Single File Reference

**Status**: ✅ Investigation Complete - Ready to Fix
**Issue**: OBJ0002 has illegal SCD2 Type 2 violation
**Impact**: Safe - zero dependencies (etledges is empty)
**Time to Fix**: ~5 minutes

---

## The Problem

OBJ0002 was reused for two different objects:
- **v1 (Original)**: telemetry-events (PUBSUB) ✅
- **v2 (Current)**: minietl-daily-extraction (TRIGGER) ❌ WRONG

This violates SCD2 rules: same object_id must represent same logical entity.

---

## The Fix (Option 1 - Recommended)

### Step 1: Close bad v2
```sql
UPDATE `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
SET effective_end = CURRENT_DATE()
WHERE object_id = 'OBJ0002'
  AND version = 2
  AND name = 'minietl-daily-extraction'
  AND object_type = 'TRIGGER';
```

### Step 2: Restore correct v1
```sql
UPDATE `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
SET effective_end = NULL
WHERE object_id = 'OBJ0002'
  AND version = 1
  AND name = 'telemetry-events'
  AND object_type = 'PUBSUB';
```

### Step 3: Create new object for minietl-daily-extraction
```sql
INSERT INTO `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
(object_id, name, object_type, version, effective_start, effective_end, status)
VALUES ('OBJ0010', 'minietl-daily-extraction', 'TRIGGER', 1, CURRENT_DATE(), NULL, 'active');
```

### Step 4: Verify results
```sql
-- Check OBJ0002
SELECT object_id, version, name, object_type, effective_end
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE object_id IN ('OBJ0002', 'OBJ0010')
ORDER BY object_id, version;

-- Check total current objects (should be 10, was 9)
SELECT COUNT(*) as current_objects
FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
WHERE effective_end IS NULL;
```

---

## Key Facts

| Item | Value |
|------|-------|
| Root Cause | Assignment key uses only object name, not (name + type) |
| Current Dependencies | 0 (etledges table is empty) |
| Risk Level | Low |
| Reversible | Yes (100%) |
| Time to Execute | ~5 minutes SQL + 1 code change |
| Production Impact | None |

---

## Code Status

✅ **Code is ALREADY CORRECT** - Uses composite key `type::name` in object_assigner.py

The issue is **bad data** in BigQuery created before the code fix was deployed.

See `SCD2_DATA_MODEL_DESIGN.md` for design details.

---

## Execution Steps

1. **Data Fix**: Run Steps 1-4 SQL below
2. **Verify**: Run Step 4 verification queries
3. **Test**: Run minietl CLI again to confirm OBJ0010 created (no v3)
4. **(Optional)** Remove backward compatibility in object_assigner.py line 79

---

## Test Suite

Run after fix:
```bash
python test_scd2_validation.py --sa /path/to/service-account.json
```

Expected: All 7 tests PASSED

---

## Status Tracker

- [x] Code design reviewed - ✅ Composite key already implemented
- [ ] SQL steps 1-4 executed
- [ ] Verification passed (Step 4 queries)
- [ ] minietl re-run successful (check OBJ0010 created)
- [ ] All tests passing (test_scd2_validation.py)
- [ ] (Optional) Backward compatibility removed from object_assigner.py

Update this file as you complete steps.
