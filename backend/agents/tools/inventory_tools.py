"""
Inventory collection and analysis tools for Architect Agent.

Provides @agent_tool decorated functions for:
- Loading current GCP inventory from BigQuery
- Analyzing object relationships and dependencies
- Identifying unreviewed objects
- Generating inventory summaries
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from google.cloud import bigquery
from google.adk.tools import agent_tool

from ..models_adk import (
    LineageNode,
    LineageGraph,
    InventorySummary,
    Priority,
)


# Global BigQuery client (initialized once)
_bq_client: Optional[bigquery.Client] = None


def get_bq_client() -> bigquery.Client:
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


# ============================================================================
# INVENTORY COLLECTION TOOLS
# ============================================================================

@agent_tool
def load_gcp_inventory(project_id: str, dataset_id: str = "minietl") -> Dict[str, Any]:
    """
    Load all current GCP ETL objects from BigQuery inventory.

    Retrieves the latest version of all objects from the SCD Type 2 table,
    including their current priority status and decommission flags.

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset containing inventory

    Returns:
        Dictionary with inventory summary and detailed objects
    """
    try:
        client = get_bq_client()

        # Query to get latest version of each object (SCD2)
        query = f"""
        SELECT
            object_id,
            name,
            object_type,
            CAST(NULL AS STRING) as priority,  -- Will be NULL if never reviewed
            FALSE as is_decommission,
            description,
            status,
            CAST(metadata AS STRING) as metadata_json
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
          AND status = 'active'
        ORDER BY object_id
        """

        query_job = client.query(query)
        results = query_job.result()

        objects = []
        for row in results:
            try:
                metadata = json.loads(row.metadata_json) if row.metadata_json else {}
            except:
                metadata = {}

            obj = {
                "object_id": row.object_id,
                "name": row.name,
                "object_type": row.object_type,
                "priority": row.priority,  # NULL for unreviewed
                "is_decommission": row.is_decommission,
                "description": row.description,
                "status": row.status,
                "metadata": metadata,
            }
            objects.append(obj)

        return {
            "status": "success",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "total_objects": len(objects),
            "objects": objects,
            "loaded_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "project_id": project_id,
        }


@agent_tool
def get_unreviewed_objects(
    project_id: str,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Get objects that have not yet been reviewed by architect.

    Returns objects where priority is NULL (never assigned).

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset containing inventory

    Returns:
        List of unreviewed objects
    """
    try:
        client = get_bq_client()

        query = f"""
        SELECT
            object_id,
            name,
            object_type,
            description,
            (
                SELECT COUNT(*)
                FROM `{project_id}.{dataset_id}.etledges`
                WHERE source_object_id = obj.object_id AND is_active = TRUE
            ) as downstream_count,
            (
                SELECT COUNT(*)
                FROM `{project_id}.{dataset_id}.etledges`
                WHERE target_object_id = obj.object_id AND is_active = TRUE
            ) as upstream_count
        FROM `{project_id}.{dataset_id}.etlobjectscd2` as obj
        WHERE effective_end IS NULL
          AND status = 'active'
          AND (priority IS NULL OR priority = '')
        ORDER BY object_type, name
        """

        query_job = client.query(query)
        results = query_job.result()

        objects = []
        for row in results:
            objects.append({
                "object_id": row.object_id,
                "name": row.name,
                "object_type": row.object_type,
                "description": row.description,
                "downstream_dependencies": row.downstream_count or 0,
                "upstream_dependencies": row.upstream_count or 0,
            })

        return {
            "status": "success",
            "unreviewed_count": len(objects),
            "objects": objects,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@agent_tool
def get_priority_summary(
    project_id: str,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Get summary of objects by priority level.

    Shows count of objects assigned to each priority tier.

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset containing inventory

    Returns:
        Summary with counts by priority
    """
    try:
        client = get_bq_client()

        query = f"""
        SELECT
            COALESCE(priority, 'UNREVIEWED') as priority,
            COUNT(*) as count,
            COUNT(DISTINCT object_type) as object_types
        FROM `{project_id}.{dataset_id}.etlobjectscd2_enriched`
        WHERE effective_end IS NULL AND status = 'active'
        GROUP BY priority
        ORDER BY
            CASE COALESCE(priority, 'UNREVIEWED')
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                WHEN 'LOW' THEN 4
                WHEN 'DECOMMISSION' THEN 5
                ELSE 6
            END
        """

        query_job = client.query(query)
        results = query_job.result()

        summary = {}
        total = 0
        for row in results:
            priority = row.priority
            count = row.count
            summary[priority] = {
                "count": count,
                "object_types": row.object_types or 0,
            }
            total += count

        return {
            "status": "success",
            "total_objects": total,
            "by_priority": summary,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@agent_tool
def find_objects_by_pattern(
    project_id: str,
    pattern: str,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Find objects matching a name or type pattern.

    Useful for architect to locate specific objects by partial name.

    Args:
        project_id: GCP project ID
        pattern: Pattern to match (case-insensitive substring)
        dataset_id: BigQuery dataset containing inventory

    Returns:
        List of matching objects
    """
    try:
        client = get_bq_client()

        query = f"""
        SELECT
            object_id,
            name,
            object_type,
            COALESCE(priority, 'UNREVIEWED') as priority,
            is_decommission,
            description
        FROM `{project_id}.{dataset_id}.etlobjectscd2_enriched`
        WHERE effective_end IS NULL
          AND status = 'active'
          AND (LOWER(name) LIKE LOWER('%{pattern}%')
               OR LOWER(object_type) LIKE LOWER('%{pattern}%'))
        ORDER BY name
        LIMIT 50
        """

        query_job = client.query(query)
        results = query_job.result()

        objects = []
        for row in results:
            objects.append({
                "object_id": row.object_id,
                "name": row.name,
                "object_type": row.object_type,
                "priority": row.priority,
                "is_decommission": row.is_decommission,
                "description": row.description,
            })

        return {
            "status": "success",
            "pattern": pattern,
            "matches": len(objects),
            "objects": objects,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# INVENTORY ANALYSIS TOOLS
# ============================================================================

@agent_tool
def analyze_object_dependencies(
    project_id: str,
    object_id: str,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Analyze upstream and downstream dependencies for an object.

    Shows all objects that feed into this object and all objects
    that depend on this object.

    Args:
        project_id: GCP project ID
        object_id: Target object ID
        dataset_id: BigQuery dataset

    Returns:
        Dictionary with upstream and downstream dependencies
    """
    try:
        client = get_bq_client()

        # Get object details
        obj_query = f"""
        SELECT name, object_type, priority, is_decommission
        FROM `{project_id}.{dataset_id}.etlobjectscd2_enriched`
        WHERE object_id = '{object_id}' AND effective_end IS NULL
        LIMIT 1
        """
        obj_result = list(client.query(obj_query).result())

        if not obj_result:
            return {
                "status": "error",
                "error": f"Object {object_id} not found",
            }

        obj = obj_result[0]

        # Get upstream dependencies (objects that feed into this one)
        upstream_query = f"""
        SELECT DISTINCT
            e.source_object_id as object_id,
            o.name,
            o.object_type,
            e.edge_type,
            COALESCE(o.priority, 'UNREVIEWED') as priority
        FROM `{project_id}.{dataset_id}.etledges` e
        JOIN `{project_id}.{dataset_id}.etlobjectscd2_enriched` o
          ON e.source_object_id = o.object_id
          AND o.effective_end IS NULL
        WHERE e.target_object_id = '{object_id}'
          AND e.is_active = TRUE
        ORDER BY o.name
        """

        # Get downstream dependencies (objects that depend on this one)
        downstream_query = f"""
        SELECT DISTINCT
            e.target_object_id as object_id,
            o.name,
            o.object_type,
            e.edge_type,
            COALESCE(o.priority, 'UNREVIEWED') as priority
        FROM `{project_id}.{dataset_id}.etledges` e
        JOIN `{project_id}.{dataset_id}.etlobjectscd2_enriched` o
          ON e.target_object_id = o.object_id
          AND o.effective_end IS NULL
        WHERE e.source_object_id = '{object_id}'
          AND e.is_active = TRUE
        ORDER BY o.name
        """

        upstream = []
        for row in client.query(upstream_query).result():
            upstream.append({
                "object_id": row.object_id,
                "name": row.name,
                "type": row.object_type,
                "edge_type": row.edge_type,
                "priority": row.priority,
            })

        downstream = []
        for row in client.query(downstream_query).result():
            downstream.append({
                "object_id": row.object_id,
                "name": row.name,
                "type": row.object_type,
                "edge_type": row.edge_type,
                "priority": row.priority,
            })

        return {
            "status": "success",
            "object_id": object_id,
            "object_name": obj.name,
            "object_type": obj.object_type,
            "priority": obj.priority,
            "is_decommission": obj.is_decommission,
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "upstream": upstream,
            "downstream": downstream,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@agent_tool
def find_critical_dependency_chains(
    project_id: str,
    dataset_id: str = "minietl",
    max_depth: int = 5
) -> Dict[str, Any]:
    """
    Identify critical dependency chains in the system.

    Finds the longest dependency paths and objects with highest
    impact (many downstream dependencies).

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset
        max_depth: Maximum chain depth to analyze

    Returns:
        List of critical dependency chains
    """
    try:
        client = get_bq_client()

        # Find objects with most downstream dependencies
        query = f"""
        WITH downstream_counts AS (
            SELECT
                source_object_id,
                COUNT(*) as downstream_count
            FROM `{project_id}.{dataset_id}.etledges`
            WHERE is_active = TRUE
            GROUP BY source_object_id
        )
        SELECT
            o.object_id,
            o.name,
            o.object_type,
            COALESCE(o.priority, 'UNREVIEWED') as priority,
            COALESCE(dc.downstream_count, 0) as downstream_count
        FROM `{project_id}.{dataset_id}.etlobjectscd2_enriched` o
        LEFT JOIN downstream_counts dc
          ON o.object_id = dc.source_object_id
        WHERE o.effective_end IS NULL
          AND o.status = 'active'
        ORDER BY downstream_count DESC
        LIMIT 20
        """

        query_job = client.query(query)
        results = query_job.result()

        critical_objects = []
        for row in results:
            if row.downstream_count > 0:  # Only include objects with dependencies
                critical_objects.append({
                    "object_id": row.object_id,
                    "name": row.name,
                    "type": row.object_type,
                    "priority": row.priority,
                    "downstream_count": row.downstream_count,
                    "impact": "CRITICAL" if row.downstream_count > 5 else "HIGH",
                })

        return {
            "status": "success",
            "critical_objects": len(critical_objects),
            "objects": critical_objects,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }
