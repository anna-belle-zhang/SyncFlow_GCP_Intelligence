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
from typing import Dict, List, Any, Optional
from datetime import datetime

from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, SchemaField
from google.oauth2 import service_account

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

    def create_dataset(self, location: str = "us-central1", exists_ok: bool = True) -> None:
        """
        Create BigQuery dataset for minietl.

        Args:
            location: GCP region
            exists_ok: If True, don't error if dataset exists
        """
        dataset = bigquery.Dataset(self.dataset_ref)
        dataset.location = location
        dataset.description = "Mini ETL metadata management system"

        try:
            dataset = self.client.create_dataset(dataset, exists_ok=exists_ok)
            logger.info(f"✓ Created dataset {self.dataset_ref}")
        except Exception as e:
            logger.error(f"Failed to create dataset: {e}")
            raise

    def create_table(self, table_name: str, schema: List[Dict[str, Any]]) -> None:
        """
        Create BigQuery table with schema.

        Args:
            table_name: Name of table to create
            schema: List of schema field definitions
        """
        table_id = f"{self.dataset_ref}.{table_name}"

        # Convert schema to SchemaField objects
        schema_fields = [
            SchemaField(
                name=field["name"],
                field_type=field["type"],
                mode=field.get("mode", "NULLABLE"),
                description=field.get("description", ""),
            )
            for field in schema
        ]

        table = bigquery.Table(table_id, schema=schema_fields)
        table.description = f"Table: {table_name}"

        try:
            table = self.client.create_table(table, exists_ok=True)
            logger.info(f"✓ Created table {table_id}")
        except Exception as e:
            logger.error(f"Failed to create table {table_id}: {e}")
            raise

    def create_all_tables(self) -> None:
        """Create all mini ETL tables."""
        logger.info("Creating Mini ETL tables...")

        # Ensure dataset exists
        self.create_dataset()

        # Create all tables
        tables = [
            ("etlobjectscd2", ETLOBJECTSCD2_SCHEMA),
            ("etledges", ETLEDGES_SCHEMA),
            ("factlog", FACTLOG_SCHEMA),
            ("factbilling", FACTBILLING_SCHEMA),
            ("object_priority_overrides", OBJECT_PRIORITY_OVERRIDES_SCHEMA),
        ]

        for table_name, schema in tables:
            self.create_table(table_name, schema)

        self._create_priority_view()

        logger.info("✓ All tables created successfully")

    def _create_priority_view(self) -> None:
        """Create or replace the SCD2 + priority override view."""
        view_name = "etlobjectscd2_enriched"
        table_id = f"{self.dataset_ref}.{view_name}"
        view = bigquery.Table(table_id)
        view.view_query = f"""
        SELECT
          scd.* EXCEPT(priority),
          COALESCE(override.priority, scd.priority) AS priority,
          override.updated_by AS priority_updated_by,
          override.updated_at AS priority_updated_at
        FROM `{self.dataset_ref}.etlobjectscd2` AS scd
        LEFT JOIN (
          SELECT object_id, priority, updated_by, updated_at
          FROM (
            SELECT
              object_id,
              priority,
              updated_by,
              updated_at,
              ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY updated_at DESC) AS rn
            FROM `{self.dataset_ref}.object_priority_overrides`
          )
          WHERE rn = 1
        ) AS override
        ON override.object_id = scd.object_id
        WHERE scd.effective_end IS NULL
        """
        view.view_use_legacy_sql = False

        try:
            self.client.create_table(view, exists_ok=True)
            self.client.update_table(view, ["view_query", "view_use_legacy_sql"])
            logger.info(f"✓ Created view {table_id}")
        except Exception as e:
            logger.error(f"Failed to create view {table_id}: {e}")
            raise

    def insert_rows(self, table_name: str, rows: List[Dict[str, Any]]) -> None:
        """
        Insert rows into BigQuery table.

        Args:
            table_name: Name of table
            rows: List of row dictionaries
        """
        if not rows:
            logger.warning(f"No rows to insert into {table_name}")
            return

        table_id = f"{self.dataset_ref}.{table_name}"

        try:
            errors = self.client.insert_rows_json(table_id, rows)
            if errors:
                logger.error(f"Insert errors for {table_name}: {errors}")
                raise Exception(f"Failed to insert rows: {errors}")
            logger.info(f"✓ Inserted {len(rows)} rows into {table_name}")
        except Exception as e:
            logger.error(f"Failed to insert rows into {table_name}: {e}")
            raise

    def upsert_etl_object(self, obj_dict: Dict[str, Any]) -> None:
        """
        Upsert ETL object with SCD Type 2 logic.

        If object_id exists, expire old version and insert new one.
        Otherwise, insert new object.

        Args:
            obj_dict: ETL object dictionary
        """
        table_id = f"{self.dataset_ref}.etlobjectscd2"
        object_id = obj_dict.get("object_id")
        today = datetime.now().date().isoformat()

        # Query to find existing active record
        query = f"""
        SELECT version, effective_end
        FROM `{table_id}`
        WHERE object_id = '{object_id}'
        AND effective_end IS NULL
        AND status = 'active'
        LIMIT 1
        """

        try:
            result = self.client.query(query).result()
            existing = list(result)

            if existing:
                # Expire old version
                old_version = existing[0].version
                update_query = f"""
                UPDATE `{table_id}`
                SET effective_end = '{today}', status = 'archived'
                WHERE object_id = '{object_id}'
                AND version = {old_version}
                AND effective_end IS NULL
                """
                self.client.query(update_query).result()
                logger.info(f"Expired version {old_version} of {object_id}")

                # Insert new version
                obj_dict["version"] = old_version + 1
                obj_dict["effective_start"] = today
                obj_dict["effective_end"] = None
                obj_dict["status"] = "active"
            else:
                # First version
                obj_dict["version"] = 1
                obj_dict["effective_start"] = today
                obj_dict["effective_end"] = None
                obj_dict["status"] = "active"

            self.insert_rows("etlobjectscd2", [obj_dict])

        except Exception as e:
            logger.error(f"Failed to upsert ETL object {object_id}: {e}")
            raise

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

    def get_object_lineage(self, object_id: str) -> Dict[str, Any]:
        """
        Get complete lineage for an object.

        Args:
            object_id: The object ID to query

        Returns:
            Dictionary with upstream and downstream lineage
        """
        # Get object details
        obj_query = f"""
        SELECT *
        FROM `{self.dataset_ref}.etlobjectscd2`
        WHERE object_id = '{object_id}'
        AND effective_end IS NULL
        """

        # Get upstream dependencies
        upstream_query = f"""
        SELECT e.source_object_id, o.name, o.object_type, e.edge_type
        FROM `{self.dataset_ref}.etledges` e
        JOIN `{self.dataset_ref}.etlobjectscd2` o
        ON e.source_object_id = o.object_id
        WHERE e.target_object_id = '{object_id}'
        AND e.is_active = TRUE
        AND o.effective_end IS NULL
        """

        # Get downstream dependencies
        downstream_query = f"""
        SELECT e.target_object_id, o.name, o.object_type, e.edge_type
        FROM `{self.dataset_ref}.etledges` e
        JOIN `{self.dataset_ref}.etlobjectscd2` o
        ON e.target_object_id = o.object_id
        WHERE e.source_object_id = '{object_id}'
        AND e.is_active = TRUE
        AND o.effective_end IS NULL
        """

        try:
            obj = list(self.client.query(obj_query).result())
            upstream = [dict(row) for row in self.client.query(upstream_query).result()]
            downstream = [dict(row) for row in self.client.query(downstream_query).result()]

            return {
                "object": dict(obj[0]) if obj else None,
                "upstream": upstream,
                "downstream": downstream,
            }
        except Exception as e:
            logger.error(f"Failed to get lineage for {object_id}: {e}")
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
