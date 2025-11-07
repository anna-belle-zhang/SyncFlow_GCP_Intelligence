"""
Data models for Mini ETL metadata management system.

Defines schemas and data structures for:
- ETL Object Registry (SCD Type 2)
- Execution Logs (factlog)
- Cost Tracking (factbilling)
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class ObjectType(str, Enum):
    """Enumeration of GCP ETL object types."""
    TRIGGER = "TRIGGER"                      # Cloud Scheduler
    FUNCTION = "FUNCTION"                    # Cloud Functions
    PUBSUB = "PUBSUB"                        # Pub/Sub Topics & Subscriptions
    DATAFLOW = "DATAFLOW"                    # Dataflow Jobs
    WORKFLOW = "WORKFLOW"                    # Cloud Workflows
    BQTABLE = "BQTABLE"                      # BigQuery Tables
    BQDATASET = "BQDATASET"                  # BigQuery Datasets
    DBT_MODEL = "DBT_MODEL"                  # dbt Models
    DBT_TEST = "DBT_TEST"                    # dbt Tests
    GCS_BUCKET = "GCS_BUCKET"                # Cloud Storage Buckets
    CLOUD_RUN = "CLOUD_RUN"                 # Cloud Run Services
    COMPOSER = "COMPOSER"                    # Cloud Composer Environments


class EdgeType(str, Enum):
    """Enumeration of relationship types between objects."""
    INVOKES = "invokes"                      # A triggers/calls B
    TRIGGERS = "triggers"                    # A triggers B
    WRITES_TO = "writes_to"                  # A writes to B
    READS_FROM = "reads_from"                # A reads from B
    DEPENDS_ON = "depends_on"                # A depends on B
    CONTAINS = "contains"                    # A contains B


class ObjectStatus(str, Enum):
    """Enumeration of object status values."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
    INACTIVE = "inactive"


@dataclass
class ETLObject:
    """
    ETL Object with SCD Type 2 tracking.

    Tracks metadata and history of GCP ETL components.
    """
    object_id: str                           # Unique identifier (OBJ001, OBJ002, ...)
    object_type: ObjectType                  # Type of object (FUNCTION, DATAFLOW, etc.)
    name: str                                # Name of the object
    parent_id: Optional[str] = None          # Reference to parent object
    gcp_resource_name: Optional[str] = None  # Full GCP resource name
    description: Optional[str] = None        # Description of the object
    effective_start: Optional[str] = None    # SCD2: When this version became active
    effective_end: Optional[str] = None      # SCD2: When this version was superseded
    version: int = 1                         # SCD2: Version number
    status: ObjectStatus = ObjectStatus.ACTIVE  # Current status
    created_at: Optional[str] = None         # Creation timestamp
    updated_at: Optional[str] = None         # Last update timestamp
    metadata: Dict[str, Any] = None          # Additional metadata (JSON)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        d = asdict(self)
        d['object_type'] = self.object_type.value
        d['status'] = self.status.value
        if self.metadata is None:
            d['metadata'] = {}
        return d


@dataclass
class ETLEdge:
    """
    Relationship between two ETL objects.

    Represents dependencies and data flows in the ETL pipeline.
    """
    edge_id: str                             # Unique edge identifier
    source_object_id: str                    # Source object
    target_object_id: str                    # Target object
    edge_type: EdgeType                      # Type of relationship
    source_name: Optional[str] = None        # Cached source name
    target_name: Optional[str] = None        # Cached target name
    method: Optional[str] = None             # How they interact (HTTP POST, etc.)
    is_active: bool = True                   # Whether this edge is currently active
    created_at: Optional[str] = None         # Creation timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        d = asdict(self)
        d['edge_type'] = self.edge_type.value
        return d


@dataclass
class ExecutionLog:
    """
    Execution metrics for ETL objects.

    Tracks when objects run and how long they take.
    """
    object_id: str                           # Reference to ETL object
    run_date: str                            # Date of execution (YYYY-MM-DD)
    start_time: str                          # Start time (HH:MM:SS)
    end_time: str                            # End time (HH:MM:SS)
    duration_min: int                        # Duration in minutes
    status: str = "success"                  # success, failed, warning
    records_processed: Optional[int] = None  # Number of records processed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        return asdict(self)


@dataclass
class BillingRecord:
    """
    Cost tracking for ETL objects.

    Tracks expenses by service and object.
    """
    object_id: str                           # Reference to ETL object
    run_date: str                            # Date of execution (YYYY-MM-DD)
    service: str                             # GCP service (Cloud Functions, Dataflow, etc.)
    cost_usd: float                          # Cost in USD
    compute_units: Optional[float] = None    # Compute units
    slot_hours: Optional[float] = None       # BigQuery slot hours

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        return asdict(self)


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
