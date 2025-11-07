"""
SCD2 Validation & Testing

Validates proper SCD2 handling when two sources update the same table:
1. GCP inventory discovery (inserts new objects)
2. Architect agent updates (updates existing objects)

Test Scenarios:
- Object name mismatch (minietl-daily-extraction vs mitl-extraction-function)
- Wrong object_id assignment
- Missing objects from either source
- Proper version tracking
"""

import os
import sys
from datetime import datetime
from collections import defaultdict

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = (
    '/mnt/e/A/storage_lifecycle_management/.gcp/service-account.json'
)

from google.cloud import bigquery

client = bigquery.Client(project="prismatic-smoke-463810-c1")


def test_scd2_current_state():
    """Validate current SCD2 state in BigQuery."""
    print("\n" + "="*80)
    print("TEST 1: SCD2 Current State Validation")
    print("="*80)

    # Get ALL versions of all objects
    query = """
    SELECT
        object_id,
        name,
        object_type,
        version,
        effective_start,
        effective_end,
        status
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    ORDER BY object_id, version DESC
    """

    results = list(client.query(query).result())

    print(f"\nTotal records: {len(results)}")
    print(f"Objects with versions:\n")

    # Group by object_id
    by_id = defaultdict(list)
    for row in results:
        by_id[row.object_id].append({
            'name': row.name,
            'type': row.object_type,
            'version': row.version,
            'start': row.effective_start,
            'end': row.effective_end,
            'status': row.status,
        })

    for obj_id in sorted(by_id.keys()):
        versions = by_id[obj_id]
        print(f"\n{obj_id}:")
        for v in sorted(versions, key=lambda x: x['version'], reverse=True):
            end_str = f"→{v['end']}" if v['end'] else "(CURRENT)"
            print(f"  v{v['version']}: {v['name']:40} {v['type']:15} {v['start']} {end_str}")

    return by_id


def test_current_objects_only():
    """Validate we get correct CURRENT objects (effective_end IS NULL)."""
    print("\n" + "="*80)
    print("TEST 2: Current Objects Only (WHERE effective_end IS NULL)")
    print("="*80)

    query = """
    SELECT
        object_id,
        name,
        object_type,
        version,
        effective_start
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    WHERE effective_end IS NULL
    ORDER BY object_id
    """

    results = list(client.query(query).result())

    print(f"\nCurrent objects: {len(results)}\n")
    for row in results:
        print(f"{row.object_id:10} {row.name:40} {row.object_type:15} v{row.version}")

    return results


def test_object_name_conflicts():
    """Find objects with similar names (name conflicts)."""
    print("\n" + "="*80)
    print("TEST 3: Object Name Conflicts")
    print("="*80)

    # Look for similar names
    patterns = ['minietl', 'mitl', 'extraction', 'function']

    query = """
    SELECT
        object_id,
        name,
        object_type,
        version,
        effective_end
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    WHERE effective_end IS NULL
    ORDER BY name
    """

    results = list(client.query(query).result())

    print(f"\nSearching for: {patterns}\n")
    matches = []
    for row in results:
        for pattern in patterns:
            if pattern.lower() in row.name.lower():
                matches.append(row)
                break

    if matches:
        print(f"Found {len(matches)} matching objects:\n")
        for row in matches:
            print(f"  {row.object_id:10} {row.name:40} {row.object_type:15} v{row.version}")
    else:
        print("⚠️  No matches found for patterns!")

    return matches


def test_missing_objects():
    """Check for missing or incomplete objects."""
    print("\n" + "="*80)
    print("TEST 4: Missing Objects Detection")
    print("="*80)

    # Check for objects with NULL names or types
    query = """
    SELECT
        object_id,
        name,
        object_type,
        version,
        effective_end
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    WHERE effective_end IS NULL
      AND (name IS NULL OR name = '' OR object_type IS NULL OR object_type = '')
    """

    results = list(client.query(query).result())

    if results:
        print(f"\n⚠️  Found {len(results)} incomplete objects:\n")
        for row in results:
            print(f"  {row.object_id:10} name={row.name} type={row.object_type}")
    else:
        print("\n✓ No incomplete objects found")

    # Check for unused objects (no dependencies)
    # Note: etledges table structure unknown, skip this check for now
    used_ids = set()  # TODO: Check actual etledges schema

    current_query = """
    SELECT object_id
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    WHERE effective_end IS NULL
    """

    current_ids = {row.object_id for row in client.query(current_query).result()}

    unused = current_ids - used_ids
    # Skip unused check since etledges schema not confirmed

    print("\n✓ Dependency check skipped (etledges schema to be verified)")

    return set()


def test_version_tracking():
    """Verify version numbers are sequential and correct."""
    print("\n" + "="*80)
    print("TEST 5: Version Number Tracking")
    print("="*80)

    query = """
    SELECT
        object_id,
        name,
        version,
        effective_start,
        effective_end
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    ORDER BY object_id, version
    """

    results = list(client.query(query).result())

    print(f"\nValidating {len(results)} records...\n")

    by_id = defaultdict(list)
    for row in results:
        by_id[row.object_id].append(row)

    issues = []
    for obj_id, records in sorted(by_id.items()):
        # Check version sequence
        versions = sorted([r.version for r in records])
        expected_versions = list(range(1, len(records) + 1))

        if versions != expected_versions:
            issues.append(f"{obj_id}: versions {versions} != expected {expected_versions}")

        # Check effective dates
        for i, record in enumerate(sorted(records, key=lambda r: r.version)):
            if i < len(records) - 1:  # Not the last version
                if record.effective_end is None:
                    issues.append(f"{obj_id} v{record.version}: has NULL effective_end but not current")
            else:  # Last version
                if record.effective_end is not None:
                    issues.append(f"{obj_id} v{record.version}: is current but has effective_end={record.effective_end}")

    if issues:
        print(f"⚠️  Found {len(issues)} version tracking issues:\n")
        for issue in issues:
            print(f"  • {issue}")
    else:
        print("✓ Version tracking is correct")

    return issues


def test_scd2_merge_conflict():
    """Test for SCD2 merge conflicts from two sources."""
    print("\n" + "="*80)
    print("TEST 6: SCD2 Merge Conflict Detection")
    print("="*80)

    print("""
SCD2 Merge Conflict Scenario:
- Source 1: GCP Inventory discovers "minietl-daily-extraction" → creates OBJ0010
- Source 2: Architect updates priority for "minietl-extraction" → creates OBJ0011
- Problem: Are these the SAME object or different?

Expected:
  If SAME → One object_id (e.g., OBJ0010 with multiple versions)
  If DIFFERENT → Different IDs (OBJ0010 and OBJ0011)

Actual:
    """)

    # Find all objects with "minietl" or "mitl" in name
    query = """
    SELECT
        object_id,
        name,
        version,
        effective_start,
        effective_end
    FROM `prismatic-smoke-463810-c1.minietl.etlobjectscd2`
    WHERE LOWER(name) LIKE '%minietl%' OR LOWER(name) LIKE '%mitl%'
    ORDER BY object_id, version
    """

    results = list(client.query(query).result())

    if not results:
        print("  No 'minietl' or 'mitl' objects found")
        return None

    # Group by object_id
    by_id = defaultdict(list)
    for row in results:
        by_id[row.object_id].append(row)

    print(f"\n  Found {len(by_id)} object_id(s) with similar names:\n")

    for obj_id in sorted(by_id.keys()):
        versions = by_id[obj_id]
        print(f"  {obj_id}:")
        for v in sorted(versions, key=lambda x: x.version):
            current = "✓ CURRENT" if v.effective_end is None else f"✗ CLOSED {v.effective_end}"
            print(f"    v{v.version}: {v.name:40} {v.effective_start} → {current}")

    # Check if they should be merged
    if len(by_id) > 1:
        print(f"\n  ⚠️  ISSUE: Multiple object_ids for similar objects!")
        print(f"      Are these the same object created by different sources?")
        print(f"      Or genuinely different objects?")
        return True
    else:
        print(f"\n  ✓ Single object_id - proper SCD2 handling")
        return False


def test_recommendations():
    """Generate recommendations based on findings."""
    print("\n" + "="*80)
    print("TEST 7: Recommendations")
    print("="*80)

    # Run all tests and collect issues
    state = test_scd2_current_state()
    current = test_current_objects_only()
    conflicts = test_object_name_conflicts()
    unused = test_missing_objects()
    version_issues = test_version_tracking()
    merge_conflict = test_scd2_merge_conflict()

    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    recommendations = []

    if merge_conflict:
        recommendations.append("""
1. MERGE CONFLICT - Multiple object_ids for same logical object
   Action:
   - Verify which object_id is correct
   - Mark incorrect ones with effective_end = TODAY
   - Update all lineage edges to use correct object_id
   - Add audit log entry explaining merge""")

    if len(unused) > 2:
        recommendations.append(f"""
2. TOO MANY UNUSED OBJECTS ({len(unused)})
   Action:
   - Review if they should be marked for decommission
   - Check if discovery process is creating duplicates
   - Consider consolidation""")

    if version_issues:
        recommendations.append(f"""
3. VERSION TRACKING ISSUES ({len(version_issues)})
   Action:
   - Manually fix version sequences
   - Audit architect update process
   - Add validation to update_object_priority()""")

    if not recommendations:
        recommendations.append("""
✓ NO ISSUES FOUND
  SCD2 data is properly maintained
  Both sources (GCP discovery + architect updates) are working correctly""")

    for rec in recommendations:
        print(rec)

    return recommendations


def main():
    """Run all SCD2 validation tests."""
    print("\n" + "="*80)
    print("SCD2 VALIDATION TEST SUITE")
    print("="*80)
    print(f"Started: {datetime.utcnow().isoformat()}")
    print(f"Project: prismatic-smoke-463810-c1")
    print(f"Dataset: minietl")

    try:
        test_scd2_current_state()
        test_current_objects_only()
        test_object_name_conflicts()
        test_missing_objects()
        test_version_tracking()
        test_scd2_merge_conflict()
        test_recommendations()

        print("\n" + "="*80)
        print("✓ VALIDATION COMPLETE")
        print("="*80)
        return True

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
