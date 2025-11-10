"""
BigQuery operations for Mini ETL metadata management.

Handles:
- Dataset creation
- Table creation with schemas
- Data insertion
- Query execution
"""

import json
import logging
from typing import Dict, List, Any

from google.cloud import bigquery
from google.cloud.bigquery import SchemaField
from google.oauth2 import service_account

# Handle both relative and absolute imports for Cloud Run compatibility
try:
    from .models import (
        ETLOBJECTSCD2_SCHEMA,
        ETLEDGES_SCHEMA,
        FACTLOG_SCHEMA,
        FACTBILLING_SCHEMA,
        OBJECT_PRIORITY_OVERRIDES_SCHEMA,
    )
except ImportError:
    from models import (
        ETLOBJECTSCD2_SCHEMA,
        ETLEDGES_SCHEMA,
        FACTLOG_SCHEMA,
        FACTBILLING_SCHEMA,
        OBJECT_PRIORITY_OVERRIDES_SCHEMA,
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BigQueryManager:
    """Manages BigQuery operations for Mini ETL."""

    def __init__(self, project_id: str, dataset_id: str = "minietl", credentials=None):
        """
        Initialize BigQuery manager.

        Args:
            project_id: GCP project ID
            dataset_id: BigQuery dataset ID
            credentials: Optional credentials object
        """
        self.project_id = project_id
        self.dataset_id = dataset_id

        self.credentials = credentials

        if credentials:
            self.client = bigquery.Client(project=project_id, credentials=credentials)
        else:
            self.client = bigquery.Client(project=project_id)

        self.dataset_ref = f"{project_id}.{dataset_id}"

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute BigQuery query and return results.

        Args:
            sql: SQL query string

        Returns:
            List of result rows as dictionaries
        """
        try:
            results = self.client.query(sql).result()
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise


def setup_from_service_account(sa_path: str) -> BigQueryManager:
    """
    Create BigQueryManager with service account credentials.

    Args:
        sa_path: Path to service account JSON file

    Returns:
        Initialized BigQueryManager
    """
    with open(sa_path, "r") as f:
        sa_info = json.load(f)

    project_id = sa_info.get("project_id")
    credentials = service_account.Credentials.from_service_account_file(sa_path)

    return BigQueryManager(project_id=project_id, credentials=credentials)
