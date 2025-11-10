"""
BigQuery Schema Definitions for Mini ETL metadata management.

Defines schemas for:
- ETL Object Registry (SCD Type 2)
- Execution Logs (factlog)
- Cost Tracking (factbilling)
"""

# BigQuery Schema Definitions

ETLOBJECTSCD2_SCHEMA = [
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED", "description": "Unique object identifier"},
    {"name": "object_type", "type": "STRING", "mode": "REQUIRED", "description": "Type of GCP object"},
    {"name": "name", "type": "STRING", "mode": "REQUIRED", "description": "Object name"},
    {"name": "parent_id", "type": "STRING", "mode": "NULLABLE", "description": "Parent object ID"},
    {"name": "gcp_resource_name", "type": "STRING", "mode": "NULLABLE", "description": "Full GCP resource name"},
    {"name": "description", "type": "STRING", "mode": "NULLABLE", "description": "Object description"},
    {"name": "effective_start", "type": "DATE", "mode": "NULLABLE", "description": "SCD2: Effective start date"},
    {"name": "effective_end", "type": "DATE", "mode": "NULLABLE", "description": "SCD2: Effective end date"},
    {"name": "version", "type": "INTEGER", "mode": "REQUIRED", "description": "SCD2: Version number"},
    {"name": "status", "type": "STRING", "mode": "REQUIRED", "description": "Object status (active, archived, deleted)"},
    {"name": "created_at", "type": "TIMESTAMP", "mode": "NULLABLE", "description": "Creation timestamp"},
    {"name": "updated_at", "type": "TIMESTAMP", "mode": "NULLABLE", "description": "Last update timestamp"},
    {"name": "metadata", "type": "JSON", "mode": "NULLABLE", "description": "Additional metadata"},
    {"name": "priority", "type": "STRING", "mode": "NULLABLE", "description": "Architect assigned priority"},
    {"name": "architect_notes", "type": "STRING", "mode": "NULLABLE", "description": "Notes from architect review"},
    {"name": "architect_review_timestamp", "type": "TIMESTAMP", "mode": "NULLABLE", "description": "Timestamp of architect review"},
    {"name": "architect_reviewed_by", "type": "STRING", "mode": "NULLABLE", "description": "Reviewer for architect decision"},
    {"name": "is_decommission", "type": "BOOLEAN", "mode": "NULLABLE", "description": "Whether object is marked for decommission"},
    {"name": "decommission_reason", "type": "STRING", "mode": "NULLABLE", "description": "Reason for decommission flag"},
]

ETLEDGES_SCHEMA = [
    {"name": "edge_id", "type": "STRING", "mode": "REQUIRED", "description": "Unique edge identifier"},
    {"name": "source_object_id", "type": "STRING", "mode": "REQUIRED", "description": "Source object ID"},
    {"name": "target_object_id", "type": "STRING", "mode": "REQUIRED", "description": "Target object ID"},
    {"name": "edge_type", "type": "STRING", "mode": "REQUIRED", "description": "Type of relationship"},
    {"name": "source_name", "type": "STRING", "mode": "NULLABLE", "description": "Cached source name"},
    {"name": "target_name", "type": "STRING", "mode": "NULLABLE", "description": "Cached target name"},
    {"name": "method", "type": "STRING", "mode": "NULLABLE", "description": "How they interact"},
    {"name": "is_active", "type": "BOOLEAN", "mode": "REQUIRED", "description": "Whether edge is active"},
    {"name": "created_at", "type": "TIMESTAMP", "mode": "NULLABLE", "description": "Creation timestamp"},
]

FACTLOG_SCHEMA = [
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED", "description": "Reference to ETL object"},
    {"name": "run_date", "type": "DATE", "mode": "REQUIRED", "description": "Date of execution"},
    {"name": "start_time", "type": "TIME", "mode": "REQUIRED", "description": "Start time (HH:MM:SS)"},
    {"name": "end_time", "type": "TIME", "mode": "REQUIRED", "description": "End time (HH:MM:SS)"},
    {"name": "duration_min", "type": "INTEGER", "mode": "REQUIRED", "description": "Duration in minutes"},
    {"name": "status", "type": "STRING", "mode": "REQUIRED", "description": "Execution status"},
    {"name": "records_processed", "type": "INTEGER", "mode": "NULLABLE", "description": "Records processed"},
]

FACTBILLING_SCHEMA = [
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED", "description": "Reference to ETL object"},
    {"name": "run_date", "type": "DATE", "mode": "REQUIRED", "description": "Date of execution"},
    {"name": "service", "type": "STRING", "mode": "REQUIRED", "description": "GCP service"},
    {"name": "cost_usd", "type": "FLOAT64", "mode": "REQUIRED", "description": "Cost in USD"},
    {"name": "compute_units", "type": "FLOAT64", "mode": "NULLABLE", "description": "Compute units"},
    {"name": "slot_hours", "type": "FLOAT64", "mode": "NULLABLE", "description": "BigQuery slot hours"},
]

OBJECT_PRIORITY_OVERRIDES_SCHEMA = [
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED", "description": "Object identifier referenced in SCD2 table"},
    {"name": "priority", "type": "STRING", "mode": "REQUIRED", "description": "Override priority value"},
    {"name": "updated_by", "type": "STRING", "mode": "REQUIRED", "description": "User or agent that updated the priority"},
    {"name": "updated_at", "type": "TIMESTAMP", "mode": "REQUIRED", "description": "Timestamp when override occurred"},
]
