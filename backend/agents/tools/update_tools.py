"""
Update tools for Architect Agent.

Applies architect decisions to BigQuery:
- Update object priorities in SCD2 table
- Create new lineage edges
- Mark objects for decommission
- Maintain audit trail
"""

import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4
from google.cloud import bigquery

logger = logging.getLogger(__name__)

def agent_tool(func):
    """Decorator marking function as agent tool."""
    return func

_bq_client: Optional[bigquery.Client] = None

def get_bq_client() -> bigquery.Client:
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


@agent_tool
def update_object_priority(
    project_id: str,
    object_id: str,
    priority: str,
    architect_notes: str = "",
    architect_name: str = "system",
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Update architect priority for an object via object_priority_overrides table.

    Does NOT modify etlobjectscd2 (core table). Only writes user overrides.
    Maintains audit trail with timestamp and architect name.

    Args:
        project_id: GCP project ID
        object_id: Object to update
        priority: Priority (CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION)
        architect_notes: Notes from architect
        architect_name: Name of architect
        dataset_id: BigQuery dataset

    Returns:
        Update result with audit info
    """
    try:
        client = get_bq_client()

        if priority not in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "DECOMMISSION"]:
            return {
                "status": "error",
                "error": f"Invalid priority: {priority}",
            }

        # Verify object exists in etlobjectscd2 (read-only check)
        verify_query = f"""
        SELECT object_id, name FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE object_id = '{object_id}' AND effective_end IS NULL
        LIMIT 1
        """
        verify_result = list(client.query(verify_query).result())
        if not verify_result:
            return {
                "status": "error",
                "error": f"Object {object_id} not found in etlobjectscd2",
            }

        # Insert to object_priority_overrides (user priority override table)
        override_query = (
            f"INSERT INTO `{project_id}.{dataset_id}.object_priority_overrides` "
            "(object_id, priority, architect_notes, updated_by, updated_at) "
            "VALUES (@object_id, @priority, @architect_notes, @updated_by, CURRENT_TIMESTAMP())"
        )
        override_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("object_id", "STRING", object_id),
                bigquery.ScalarQueryParameter("priority", "STRING", priority),
                bigquery.ScalarQueryParameter("architect_notes", "STRING", architect_notes),
                bigquery.ScalarQueryParameter("updated_by", "STRING", architect_name),
            ]
        )
        client.query(override_query, job_config=override_config).result()

        # Log to audit table
        audit_log_query = f"""
        INSERT INTO `{project_id}.{dataset_id}.architect_audit_log`
        (audit_id, object_id, action, action_timestamp, actor, details,
         change_from, change_to)
        VALUES (
            'AUDIT_{uuid4().hex[:8].upper()}',
            '{object_id}',
            'PRIORITY_ASSIGNED',
            CURRENT_TIMESTAMP(),
            '{architect_name}',
            {{'priority': '{priority}', 'notes': '{architect_notes.replace("'", "''")}'}},
            {{'priority': NULL}},
            {{'priority': '{priority}'}}
        )
        """

        try:
            client.query(audit_log_query).result()
        except:
            pass  # Audit table might not exist yet

        return {
            "status": "success",
            "object_id": object_id,
            "priority": priority,
            "architect_notes": architect_notes,
            "architect_name": architect_name,
            "updated_at": datetime.utcnow().isoformat(),
            "rows_updated": 1,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@agent_tool
def create_lineage_edge(
    project_id: str,
    source_object_id: str,
    target_object_id: str,
    edge_type: str,
    method: str = "auto-detected",
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Create new lineage edge (dependency relationship) between objects.

    Verifies both objects exist before creating edge.

    Args:
        project_id: GCP project ID
        source_object_id: Source object ID
        target_object_id: Target object ID
        edge_type: Type (invokes, triggers, writes_to, reads_from, depends_on)
        method: How they interact
        dataset_id: BigQuery dataset

    Returns:
        Created edge with metadata
    """
    try:
        client = get_bq_client()

        valid_edge_types = [
            "invokes", "triggers", "writes_to", "reads_from", "depends_on", "contains"
        ]

        if edge_type not in valid_edge_types:
            return {
                "status": "error",
                "error": f"Invalid edge_type. Valid: {valid_edge_types}",
            }

        # Verify both objects exist
        verify_query = f"""
        SELECT
            (SELECT COUNT(*) FROM `{project_id}.{dataset_id}.etlobjectscd2`
             WHERE object_id = '{source_object_id}' AND effective_end IS NULL) as source_exists,
            (SELECT COUNT(*) FROM `{project_id}.{dataset_id}.etlobjectscd2`
             WHERE object_id = '{target_object_id}' AND effective_end IS NULL) as target_exists
        """

        verify_result = list(client.query(verify_query).result())[0]

        if not verify_result.source_exists:
            return {
                "status": "error",
                "error": f"Source object {source_object_id} not found",
            }

        if not verify_result.target_exists:
            return {
                "status": "error",
                "error": f"Target object {target_object_id} not found",
            }

        # Get object names
        names_query = f"""
        SELECT
            (SELECT name FROM `{project_id}.{dataset_id}.etlobjectscd2`
             WHERE object_id = '{source_object_id}' AND effective_end IS NULL LIMIT 1) as source_name,
            (SELECT name FROM `{project_id}.{dataset_id}.etlobjectscd2`
             WHERE object_id = '{target_object_id}' AND effective_end IS NULL LIMIT 1) as target_name
        """

        names_result = list(client.query(names_query).result())[0]
        source_name = names_result.source_name
        target_name = names_result.target_name

        edge_id = f"EDGE_{uuid4().hex[:8].upper()}"

        # Create edge
        insert_query = f"""
        INSERT INTO `{project_id}.{dataset_id}.etledges`
        (edge_id, source_object_id, target_object_id, edge_type,
         source_name, target_name, method, is_active, created_at)
        VALUES (
            '{edge_id}',
            '{source_object_id}',
            '{target_object_id}',
            '{edge_type}',
            '{source_name}',
            '{target_name}',
            '{method}',
            TRUE,
            CURRENT_TIMESTAMP()
        )
        """

        query_job = client.query(insert_query)
        query_job.result()

        return {
            "status": "success",
            "edge_id": edge_id,
            "source_object_id": source_object_id,
            "source_name": source_name,
            "target_object_id": target_object_id,
            "target_name": target_name,
            "edge_type": edge_type,
            "method": method,
            "created_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@agent_tool
def mark_for_decommission(
    project_id: str,
    object_id: str,
    reason: str,
    decommission_date: Optional[str] = None,
    replacement_id: Optional[str] = None,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Mark object for decommission via object_priority_overrides table.

    Does NOT modify etlobjectscd2 (core table). Only writes user overrides.
    Creates audit trail for decommission process.

    Args:
        project_id: GCP project ID
        object_id: Object to mark
        reason: Reason for decommission
        decommission_date: Target removal date (YYYY-MM-DD)
        replacement_id: ID of replacement object if any
        dataset_id: BigQuery dataset

    Returns:
        Decommission marking with audit info
    """
    try:
        client = get_bq_client()

        # Verify object exists in etlobjectscd2 (read-only check)
        verify_query = f"""
        SELECT name, object_type
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE object_id = '{object_id}' AND effective_end IS NULL
        LIMIT 1
        """

        verify_result = list(client.query(verify_query).result())
        if not verify_result:
            return {
                "status": "error",
                "error": f"Object {object_id} not found",
            }

        obj = verify_result[0]

        # Insert decommission mark to object_priority_overrides
        override_query = (
            f"INSERT INTO `{project_id}.{dataset_id}.object_priority_overrides` "
            "(object_id, priority, is_decommission, decommission_reason, "
            "decommission_date, replacement_id, updated_by, updated_at) "
            "VALUES (@object_id, 'DECOMMISSION', TRUE, @reason, "
            "@decommission_date, @replacement_id, @updated_by, CURRENT_TIMESTAMP())"
        )
        override_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("object_id", "STRING", object_id),
                bigquery.ScalarQueryParameter("reason", "STRING", reason),
                bigquery.ScalarQueryParameter("decommission_date", "STRING", decommission_date or ""),
                bigquery.ScalarQueryParameter("replacement_id", "STRING", replacement_id or ""),
                bigquery.ScalarQueryParameter("updated_by", "STRING", "architect_agent"),
            ]
        )
        client.query(override_query, job_config=override_config).result()

        # Deactivate all related edges
        deactivate_edges_query = f"""
        UPDATE `{project_id}.{dataset_id}.etledges`
        SET is_active = FALSE
        WHERE source_object_id = '{object_id}' OR target_object_id = '{object_id}'
        """

        try:
            client.query(deactivate_edges_query).result()
        except:
            pass  # Edges might not exist

        # Log to audit table
        audit_log_query = f"""
        INSERT INTO `{project_id}.{dataset_id}.architect_audit_log`
        (audit_id, object_id, action, action_timestamp, actor, details,
         change_from, change_to)
        VALUES (
            'AUDIT_{uuid4().hex[:8].upper()}',
            '{object_id}',
            'DECOMMISSION_MARKED',
            CURRENT_TIMESTAMP(),
            'architect_agent',
            {{'reason': '{reason.replace("'", "''")}', 'replacement_id': '{replacement_id or ""}'}},
            {{'priority': NULL}},
            {{'priority': 'DECOMMISSION', 'is_decommission': TRUE}}
        )
        """

        try:
            client.query(audit_log_query).result()
        except:
            pass  # Audit table might not exist

        return {
            "status": "success",
            "object_id": object_id,
            "object_name": obj.name,
            "object_type": obj.object_type,
            "decommission_reason": reason,
            "replacement_id": replacement_id,
            "decommission_date": decommission_date,
            "edges_deactivated": True,
            "marked_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@agent_tool
def store_architecture_diagram(
    project_id: str,
    object_id: str,
    diagram_text: str,
    *,
    diagram_format: str = "mermaid",
    diagram_name: Optional[str] = None,
    activate: bool = True,
    dataset_id: str = "minietl",
) -> Dict[str, Any]:
    """Persist a generated architecture diagram to BigQuery for future retrieval."""
    try:
        client = get_bq_client()
        table_id = f"{project_id}.{dataset_id}.architect_diagrams"

        deactivate_warning = None
        if activate:
            try:
                deactivate_sql = (
                    f"UPDATE `{table_id}`\n"
                    "SET is_active = FALSE\n"
                    "WHERE object_id = @object_id"
                )
                job_config = bigquery.QueryJobConfig()
                job_config.query_parameters = [
                    bigquery.ScalarQueryParameter("object_id", "STRING", object_id)
                ]
                client.query(deactivate_sql, job_config=job_config).result()
            except Exception as exc:
                message = str(exc)
                if "streaming buffer" in message.lower():
                    deactivate_warning = (
                        "Previous diagrams remain marked active due to streaming buffer; "
                        "latest diagram will still be surfaced by timestamp order."
                    )
                    logger.warning(
                        "Skipping diagram deactivation because rows are in streaming buffer: %s",
                        exc,
                    )
                else:
                    return {
                        "status": "error",
                        "error": f"Failed to deactivate previous diagrams: {exc}",
                    }

        row = {
            "diagram_id": f"DIAG_{uuid4().hex[:8].upper()}",
            "object_id": object_id,
            "diagram_name": diagram_name,
            "diagram_format": diagram_format,
            "diagram_text": diagram_text,
            "is_active": activate,
            "generated_at": datetime.utcnow().isoformat(),
        }

        errors = client.insert_rows_json(table_id, [row])
        if errors:
            return {
                "status": "error",
                "error": f"Failed to insert diagram: {errors}",
            }

        response = {
            "status": "success",
            "table": table_id,
            "diagram_id": row["diagram_id"],
            "object_id": object_id,
            "diagram_format": diagram_format,
            "diagram_name": diagram_name,
            "is_active": activate,
            "generated_at": row["generated_at"],
        }
        if deactivate_warning:
            response["warning"] = deactivate_warning

        return response
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }


@agent_tool
def get_latest_architecture_diagram(
    project_id: str,
    object_id: str,
    dataset_id: str = "minietl",
) -> Dict[str, Any]:
    """Fetch the most recent active diagram for an object."""
    try:
        client = get_bq_client()
        table_id = f"{project_id}.{dataset_id}.architect_diagrams"
        query = (
            f"SELECT diagram_id, object_id, diagram_name, diagram_format, diagram_text, "
            "is_active, generated_at\n"
            f"FROM `{table_id}`\n"
            "WHERE object_id = @object_id AND is_active = TRUE\n"
            "ORDER BY generated_at DESC\n"
            "LIMIT 1"
        )
        job_config = bigquery.QueryJobConfig()
        job_config.query_parameters = [
            bigquery.ScalarQueryParameter("object_id", "STRING", object_id)
        ]
        rows = list(client.query(query, job_config=job_config).result())
        if not rows:
            return {"status": "not_found", "object_id": object_id}

        row = dict(rows[0])
        return {
            "status": "success",
            "diagram": {
                "diagram_id": row.get("diagram_id"),
                "object_id": row.get("object_id"),
                "diagram_name": row.get("diagram_name"),
                "diagram_format": row.get("diagram_format"),
                "diagram_text": row.get("diagram_text"),
                "is_active": row.get("is_active"),
                "generated_at": row.get("generated_at"),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }


@agent_tool
def list_architecture_diagrams(
    project_id: str,
    object_id: str,
    dataset_id: str = "minietl",
    limit: int = 10,
) -> Dict[str, Any]:
    """Return history of diagrams for an object ordered by newest first."""
    try:
        client = get_bq_client()
        table_id = f"{project_id}.{dataset_id}.architect_diagrams"
        query = (
            f"SELECT diagram_id, object_id, diagram_name, diagram_format, diagram_text, is_active, generated_at\n"
            f"FROM `{table_id}`\n"
            "WHERE object_id = @object_id\n"
            "ORDER BY generated_at DESC\n"
            "LIMIT @limit"
        )
        job_config = bigquery.QueryJobConfig()
        job_config.query_parameters = [
            bigquery.ScalarQueryParameter("object_id", "STRING", object_id),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
        rows = [dict(row) for row in client.query(query, job_config=job_config).result()]
        return {
            "status": "success",
            "diagrams": rows,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }
