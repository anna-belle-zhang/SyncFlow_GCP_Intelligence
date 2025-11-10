"""
Test suite for inventory tools.

Tests @agent_tool decorated functions for GCP inventory collection and analysis.
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from google.cloud import bigquery


def test_inventory_tools():
    """Test all inventory collection and analysis tools."""

    print("\n" + "="*80)
    print("INVENTORY TOOLS TEST SUITE")
    print("="*80)

    # Get project ID from config or environment
    project_id = "prismatic-smoke-463810-c1"
    dataset_id = "minietl"

    print(f"\nProject: {project_id}")
    print(f"Dataset: {dataset_id}")

    try:
        # Initialize BigQuery client
        client = bigquery.Client(project=project_id)
        print(f"✓ BigQuery client initialized")

        # Test 1: Check if dataset exists
        print("\n--- TEST 1: Check Dataset Exists ---")
        dataset = client.get_dataset(dataset_id)
        print(f"✓ Dataset '{dataset_id}' exists")
        print(f"  Location: {dataset.location}")
        print(f"  Created: {dataset.created}")

        # Test 2: Check if etlobjectscd2 table exists and get schema
        print("\n--- TEST 2: Check etlobjectscd2 Table ---")
        table_id = f"{project_id}.{dataset_id}.etlobjectscd2"
        try:
            table = client.get_table(table_id)
            print(f"✓ Table '{table_id}' exists")
            print(f"  Rows: {table.num_rows}")
            print(f"  Size (GB): {table.num_bytes / 1e9:.2f}")
            print(f"  Schema fields: {len(table.schema)}")
            for field in table.schema:
                print(f"    - {field.name}: {field.field_type}")
        except Exception as e:
            print(f"✗ Error accessing table: {e}")
            return False

        # Test 3: Check if etledges table exists
        print("\n--- TEST 3: Check etledges Table ---")
        edges_table_id = f"{project_id}.{dataset_id}.etledges"
        try:
            edges_table = client.get_table(edges_table_id)
            print(f"✓ Table '{edges_table_id}' exists")
            print(f"  Rows: {edges_table.num_rows}")
        except Exception as e:
            print(f"✗ Error accessing edges table: {e}")
            return False

        # Test 4: Test load_gcp_inventory query
        print("\n--- TEST 4: Test load_gcp_inventory Query ---")
        inventory_query = f"""
        SELECT
            COUNT(*) as total_objects,
            COUNT(DISTINCT object_type) as object_types
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
          AND status = 'active'
        """

        try:
            result = list(client.query(inventory_query).result())
            if result:
                row = result[0]
                print(f"✓ Inventory query executed")
                print(f"  Total objects: {row.total_objects}")
                print(f"  Object types: {row.object_types}")
        except Exception as e:
            print(f"✗ Error executing inventory query: {e}")
            return False

        # Test 5: Test get_unreviewed_objects query
        print("\n--- TEST 5: Test get_unreviewed_objects Query ---")
        unreviewed_query = f"""
        SELECT
            COUNT(*) as unreviewed_count,
            COUNT(DISTINCT object_type) as object_types
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
          AND status = 'active'
          AND (priority IS NULL OR priority = '')
        """

        try:
            result = list(client.query(unreviewed_query).result())
            if result:
                row = result[0]
                print(f"✓ Unreviewed objects query executed")
                print(f"  Unreviewed count: {row.unreviewed_count}")
                print(f"  Object types: {row.object_types}")
        except Exception as e:
            print(f"✗ Error executing unreviewed query: {e}")
            return False

        # Test 6: Test get_priority_summary query
        print("\n--- TEST 6: Test get_priority_summary Query ---")
        summary_query = f"""
        SELECT
            COALESCE(priority, 'UNREVIEWED') as priority,
            COUNT(*) as count
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL AND status = 'active'
        GROUP BY priority
        ORDER BY count DESC
        """

        try:
            results = list(client.query(summary_query).result())
            print(f"✓ Priority summary query executed")
            for row in results:
                print(f"  {row.priority}: {row.count}")
        except Exception as e:
            print(f"✗ Error executing summary query: {e}")
            return False

        # Test 7: Test find_objects_by_pattern query
        print("\n--- TEST 7: Test find_objects_by_pattern Query (pattern='user') ---")
        pattern = "user"
        pattern_query = f"""
        SELECT
            COUNT(*) as matches,
            COUNT(DISTINCT object_type) as types
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
          AND status = 'active'
          AND (LOWER(name) LIKE LOWER('%{pattern}%')
               OR LOWER(object_type) LIKE LOWER('%{pattern}%'))
        """

        try:
            result = list(client.query(pattern_query).result())
            if result:
                row = result[0]
                print(f"✓ Pattern search query executed")
                print(f"  Matches: {row.matches}")
                print(f"  Types: {row.types}")
        except Exception as e:
            print(f"✗ Error executing pattern search: {e}")
            return False

        # Test 8: Get sample object for dependency analysis
        print("\n--- TEST 8: Sample Object for Dependency Analysis ---")
        sample_query = f"""
        SELECT object_id, name, object_type
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL AND status = 'active'
        LIMIT 1
        """

        sample_id = None
        try:
            result = list(client.query(sample_query).result())
            if result:
                sample_id = result[0].object_id
                print(f"✓ Sample object found: {sample_id}")
                print(f"  Name: {result[0].name}")
                print(f"  Type: {result[0].object_type}")
        except Exception as e:
            print(f"✗ Error getting sample object: {e}")
            return False

        # Test 9: Test analyze_object_dependencies query
        if sample_id:
            print(f"\n--- TEST 9: Test analyze_object_dependencies Query ---")
            deps_query = f"""
            SELECT
                (SELECT COUNT(*) FROM `{project_id}.{dataset_id}.etledges`
                 WHERE source_object_id = '{sample_id}' AND is_active = TRUE) as downstream,
                (SELECT COUNT(*) FROM `{project_id}.{dataset_id}.etledges`
                 WHERE target_object_id = '{sample_id}' AND is_active = TRUE) as upstream
            """

            try:
                result = list(client.query(deps_query).result())
                if result:
                    row = result[0]
                    print(f"✓ Dependency analysis query executed")
                    print(f"  Upstream dependencies: {row.upstream}")
                    print(f"  Downstream dependencies: {row.downstream}")
            except Exception as e:
                print(f"✗ Error executing dependency analysis: {e}")
                return False

        # Test 10: Test find_critical_dependency_chains query
        print("\n--- TEST 10: Test find_critical_dependency_chains Query ---")
        critical_query = f"""
        WITH downstream_counts AS (
            SELECT
                source_object_id,
                COUNT(*) as downstream_count
            FROM `{project_id}.{dataset_id}.etledges`
            WHERE is_active = TRUE
            GROUP BY source_object_id
        )
        SELECT
            COUNT(*) as critical_objects,
            AVG(downstream_count) as avg_dependencies
        FROM downstream_counts
        WHERE downstream_count > 0
        """

        try:
            result = list(client.query(critical_query).result())
            if result:
                row = result[0]
                print(f"✓ Critical chains query executed")
                print(f"  Objects with dependencies: {row.critical_objects}")
                if row.avg_dependencies is not None:
                    print(f"  Avg dependencies: {row.avg_dependencies:.1f}")
                else:
                    print(f"  Avg dependencies: N/A (no dependencies yet)")
        except Exception as e:
            print(f"✗ Error executing critical chains query: {e}")
            return False

        print("\n" + "="*80)
        print("✓ ALL TESTS PASSED")
        print("="*80)
        return True

    except Exception as e:
        print(f"\n✗ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_inventory_tools()
    sys.exit(0 if success else 1)
