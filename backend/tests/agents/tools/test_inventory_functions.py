"""
Functional test for inventory_tools @agent_tool decorated functions.

Tests that the actual tool functions work correctly with BigQuery.
"""

import os
import sys
from datetime import datetime

# Set auth before importing
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = (
    '/mnt/e/A/storage_lifecycle_management/.gcp/service-account.json'
)

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from inventory_tools_standalone import (
    load_gcp_inventory,
    get_unreviewed_objects,
    get_priority_summary,
    find_objects_by_pattern,
    analyze_object_dependencies,
    find_critical_dependency_chains,
)


def test_load_gcp_inventory():
    """Test load_gcp_inventory function."""
    print("\n" + "="*80)
    print("TEST: load_gcp_inventory()")
    print("="*80)

    result = load_gcp_inventory(
        project_id="prismatic-smoke-463810-c1",
        dataset_id="minietl"
    )

    print(f"Status: {result.get('status')}")
    if result['status'] == 'success':
        print(f"Total objects: {result.get('total_objects')}")
        print(f"Sample objects: {len(result.get('objects', []))}")
        if result.get('objects'):
            obj = result['objects'][0]
            print(f"  - {obj['object_id']}: {obj['name']} ({obj['object_type']})")
            print(f"    Priority: {obj.get('priority', 'UNREVIEWED')}")
            print(f"    Decommission: {obj.get('is_decommission', False)}")
        print("✓ PASSED")
        return True
    else:
        print(f"Error: {result.get('error')}")
        print("✗ FAILED")
        return False


def test_get_unreviewed_objects():
    """Test get_unreviewed_objects function."""
    print("\n" + "="*80)
    print("TEST: get_unreviewed_objects()")
    print("="*80)

    result = get_unreviewed_objects(
        project_id="prismatic-smoke-463810-c1",
        dataset_id="minietl"
    )

    print(f"Status: {result.get('status')}")
    if result['status'] == 'success':
        print(f"Unreviewed objects: {result.get('unreviewed_count')}")
        if result.get('objects'):
            obj = result['objects'][0]
            print(f"  - {obj['object_id']}: {obj['name']} ({obj['object_type']})")
            print(f"    Downstream deps: {obj.get('downstream_dependencies', 0)}")
            print(f"    Upstream deps: {obj.get('upstream_dependencies', 0)}")
        print("✓ PASSED")
        return True
    else:
        print(f"Error: {result.get('error')}")
        print("✗ FAILED")
        return False


def test_get_priority_summary():
    """Test get_priority_summary function."""
    print("\n" + "="*80)
    print("TEST: get_priority_summary()")
    print("="*80)

    result = get_priority_summary(
        project_id="prismatic-smoke-463810-c1",
        dataset_id="minietl"
    )

    print(f"Status: {result.get('status')}")
    if result['status'] == 'success':
        print(f"Total objects: {result.get('total_objects')}")
        by_priority = result.get('by_priority', {})
        for priority, data in by_priority.items():
            print(f"  {priority}: {data.get('count')} ({data.get('object_types')} types)")
        print("✓ PASSED")
        return True
    else:
        print(f"Error: {result.get('error')}")
        print("✗ FAILED")
        return False


def test_find_objects_by_pattern():
    """Test find_objects_by_pattern function."""
    print("\n" + "="*80)
    print("TEST: find_objects_by_pattern(pattern='user')")
    print("="*80)

    result = find_objects_by_pattern(
        project_id="prismatic-smoke-463810-c1",
        pattern="user",
        dataset_id="minietl"
    )

    print(f"Status: {result.get('status')}")
    if result['status'] == 'success':
        print(f"Pattern: {result.get('pattern')}")
        print(f"Matches: {result.get('matches')}")
        if result.get('objects'):
            for obj in result['objects'][:3]:
                print(f"  - {obj['name']} ({obj['object_type']})")
        print("✓ PASSED")
        return True
    else:
        print(f"Error: {result.get('error')}")
        print("✗ FAILED")
        return False


def test_analyze_object_dependencies():
    """Test analyze_object_dependencies function."""
    print("\n" + "="*80)
    print("TEST: analyze_object_dependencies()")
    print("="*80)

    # First get an object ID
    inv_result = load_gcp_inventory(
        project_id="prismatic-smoke-463810-c1",
        dataset_id="minietl"
    )

    if not inv_result.get('objects'):
        print("✗ FAILED - No objects found")
        return False

    obj_id = inv_result['objects'][0]['object_id']

    result = analyze_object_dependencies(
        project_id="prismatic-smoke-463810-c1",
        object_id=obj_id,
        dataset_id="minietl"
    )

    print(f"Status: {result.get('status')}")
    if result['status'] == 'success':
        print(f"Object: {result.get('object_name')} ({result.get('object_type')})")
        print(f"Upstream: {result.get('upstream_count')}")
        print(f"Downstream: {result.get('downstream_count')}")
        print("✓ PASSED")
        return True
    else:
        print(f"Error: {result.get('error')}")
        print("✗ FAILED")
        return False


def test_find_critical_dependency_chains():
    """Test find_critical_dependency_chains function."""
    print("\n" + "="*80)
    print("TEST: find_critical_dependency_chains()")
    print("="*80)

    result = find_critical_dependency_chains(
        project_id="prismatic-smoke-463810-c1",
        dataset_id="minietl"
    )

    print(f"Status: {result.get('status')}")
    if result['status'] == 'success':
        print(f"Critical objects: {result.get('critical_objects')}")
        if result.get('objects'):
            for obj in result['objects'][:3]:
                print(f"  - {obj['name']}: {obj.get('downstream_count')} dependents")
        else:
            print("  (No critical dependencies found - etledges table is empty)")
        print("✓ PASSED")
        return True
    else:
        print(f"Error: {result.get('error')}")
        print("✗ FAILED")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("INVENTORY TOOLS FUNCTIONAL TEST SUITE")
    print("="*80)
    print(f"Started: {datetime.utcnow().isoformat()}")

    tests = [
        test_load_gcp_inventory,
        test_get_unreviewed_objects,
        test_get_priority_summary,
        test_find_objects_by_pattern,
        test_analyze_object_dependencies,
        test_find_critical_dependency_chains,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n✗ EXCEPTION in {test_func.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    print(f"Completed: {datetime.utcnow().isoformat()}")

    if failed == 0:
        print("\n✓ ALL TESTS PASSED")
        return True
    else:
        print(f"\n✗ {failed} TEST(S) FAILED")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
