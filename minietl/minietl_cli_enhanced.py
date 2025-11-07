#!/usr/bin/env python3
"""
SyncFlow miniETL CLI - Enhanced with Delta Extraction

Supports:
- Full inventory extraction (all GCP objects)
- Delta logs extraction (only new execution logs)
- Delta billing extraction (only new cost records)

Usage:
    # Full extraction
    python minietl_cli_enhanced.py --sa ~/.gcp/service-account.json --full

    # Full inventory only
    python minietl_cli_enhanced.py --sa ~/.gcp/service-account.json --inventory

    # Delta logs only (since last run)
    python minietl_cli_enhanced.py --sa ~/.gcp/service-account.json --logs --delta

    # Delta billing only (since last run)
    python minietl_cli_enhanced.py --sa ~/.gcp/service-account.json --billing --delta
"""

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google.auth
from google.api_core import exceptions as google_exceptions
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery
from google.oauth2 import service_account

from backend.bigquery_loader import BigQueryManager
from backend.inventory_collector import collect_inventory
from backend.billing_extractor import BillingExtractor
from backend.logs_explorer import LogsExplorer
from backend.object_assigner import ObjectIDAssigner
from backend.scd2_processor import SCD2Processor

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MinietlEnhancedCLI:
    """Enhanced CLI with delta extraction support."""

    @staticmethod
    def _to_utc_datetime(value: Optional[object]) -> Optional[datetime]:
        """Normalize various timestamp representations to timezone-aware UTC."""
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            # BigQuery may return timestamps with trailing Z or space separator
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            if " " in text and "T" not in text:
                text = text.replace(" ", "T")
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                logger.warning("Could not parse timestamp value %s", value)
                return None

            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        logger.debug("Unsupported timestamp type encountered: %s", type(value))
        return None

    def __init__(
        self,
        sa_path: Optional[str],
        project_id: str = "prismatic-smoke-463810-c1",
        dataset_id: str = "minietl",
        use_default_credentials: bool = False
    ):
        """Initialize CLI."""
        self.sa_path = sa_path
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.use_default_credentials = use_default_credentials

        in_cloud_function = any(
            os.environ.get(env) for env in ("FUNCTION_TARGET", "K_SERVICE", "FUNCTION_NAME")
        )

        credentials = None
        try:
            if sa_path:
                logger.info("Using service account credentials from %s", sa_path)
                credentials = service_account.Credentials.from_service_account_file(sa_path)
            else:
                if not use_default_credentials and not in_cloud_function:
                    raise ValueError(
                        "Service account path is required unless default credentials are enabled "
                        "or running inside a Cloud Function."
                    )
                credentials, default_project = google.auth.default()
                if not self.project_id and default_project:
                    self.project_id = default_project

                auth_context = (
                    "Cloud Function ambient credentials" if in_cloud_function else "Application Default Credentials"
                )
                logger.info("Using %s via google.auth.default()", auth_context)

        except DefaultCredentialsError as exc:
            logger.error("Failed to obtain Google Cloud credentials: %s", exc, exc_info=True)
            raise
        except Exception as exc:
            logger.error("Unexpected error while loading credentials: %s", exc, exc_info=True)
            raise

        self.credentials = credentials

        # Initialize BigQuery manager
        self.bq_manager = BigQueryManager(
            project_id=self.project_id,
            credentials=self.credentials,
            dataset_id=self.dataset_id
        )

        # Initialize SCD2 processor (for MERGE pattern support)
        self.scd2_processor = SCD2Processor()

        logger.info(
            "Initialized Enhanced MinietlCLI for %s.%s using %s",
            self.project_id,
            self.dataset_id,
            "service account file" if sa_path else "default credentials"
        )

    @staticmethod
    def _get_etlobjectscd2_schema() -> List[bigquery.SchemaField]:
        """
        Get schema definition for etlobjectscd2 table.

        Used for staging table creation in MERGE pattern.

        Returns:
            List of SchemaField objects
        """
        return [
            bigquery.SchemaField("object_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("object_type", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("parent_id", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("version", "INTEGER", mode="NULLABLE"),
            bigquery.SchemaField("effective_start", "DATE", mode="REQUIRED"),
            bigquery.SchemaField("effective_end", "DATE", mode="NULLABLE"),
            bigquery.SchemaField("metadata", "STRING", mode="NULLABLE"),
        ]

    # ========================================================================
    # INVENTORY EXTRACTION - FULL (always recollects all objects)
    # ========================================================================

    def _load_existing_object_assignments(self) -> Tuple[ObjectIDAssigner, int]:
        """
        Load existing object ID assignments from BigQuery SCD2 table.

        Returns:
            Tuple of (ObjectIDAssigner with loaded assignments, next_id to use)
        """
        logger.debug("Loading existing object ID assignments from BigQuery...")

        query = f"""
        SELECT DISTINCT object_id, name, object_type
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
        WHERE status = 'active' AND effective_end IS NULL
        ORDER BY object_id
        """

        try:
            results = self.bq_manager.query(query)

            if not results:
                logger.debug("No existing assignments found, starting fresh from OBJ0001")
                return ObjectIDAssigner(start_id=1), 1

            # Extract highest ID to determine next_id
            max_id = 0
            assigner = ObjectIDAssigner(start_id=1)

            for row in results:
                obj_id = row.get("object_id")
                name = row.get("name")
                object_type = row.get("object_type")

                if obj_id and name:
                    # Parse the ID number from OBJ0001 format
                    try:
                        id_num = int(obj_id[3:])  # Extract digits after "OBJ"
                        if id_num > max_id:
                            max_id = id_num

                        # Load assignment into assigner using the new composite key
                        key = assigner._make_key(name, object_type)
                        assigner.assignments[key] = obj_id
                        assigner.reverse_assignments[obj_id] = {
                            "name": name,
                            "object_type": object_type,
                        }
                    except (ValueError, IndexError):
                        logger.warning(f"Could not parse object ID: {obj_id}")
                        continue

            next_id = max_id + 1
            assigner.next_id = next_id

            logger.info(f"Loaded {len(results)} existing assignments, next ID will be OBJ{next_id:04d}")
            return assigner, next_id

        except Exception as e:
            logger.warning(f"Could not load existing assignments: {e}. Starting fresh.")
            return ObjectIDAssigner(start_id=1), 1

    def _count_objects_in_table(self) -> int:
        """
        Count active objects in etlobjectscd2 table.

        Returns:
            Number of active objects
        """
        try:
            query = f"""
            SELECT COUNT(DISTINCT object_id) as count
            FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
            WHERE status = 'active' AND effective_end IS NULL
            """
            results = self.bq_manager.query(query)
            if results:
                return results[0].get('count', 0)
            return 0
        except Exception as e:
            logger.warning(f"Could not count objects in table: {e}")
            return 0

    def run_inventory_extraction(self):
        """
        Extract GCP inventory (FULL - all objects) using MERGE pattern.

        Uses staging table + MERGE for atomic SCD2 updates instead of
        separate UPDATE/INSERT operations.
        """
        logger.info("="*60)
        logger.info("INVENTORY EXTRACTION (FULL - MERGE PATTERN)")
        logger.info("="*60)

        staging_table_id = None

        try:
            if not self.sa_path and not self.credentials:
                logger.error(
                    "Google Cloud credentials are required for inventory extraction."
                )
                return False

            # =====================================================================
            # Stage 1: Collect & Prepare Data (In-Memory)
            # =====================================================================

            # Collect all GCP objects
            logger.info("Collecting GCP objects...")
            objects = collect_inventory(
                self.project_id,
                sa_path=self.sa_path,
                credentials=self.credentials,
            )
            logger.info(f"  ✓ Collected {len(objects)} objects")

            if not objects:
                logger.warning("No objects collected from GCP")
                return False

            # Load existing assignments and assign object IDs
            logger.info("Loading existing object ID assignments...")
            assigner, next_id = self._load_existing_object_assignments()
            logger.info(f"Assigning object IDs (continuing from OBJ{next_id:04d})...")
            assigned_objects = assigner.assign_all(objects)
            logger.info(f"  ✓ Assigned IDs to {len(assigned_objects)} objects")

            # Convert to SCD2 format (in-memory)
            logger.info("Normalizing records for SCD2 processing...")
            effective_date = datetime.utcnow().date().isoformat()
            candidate_records = self.convert_to_scd2_format(
                assigned_objects,
                effective_date=effective_date
            )
            logger.info(f"  ✓ Prepared {len(candidate_records)} candidate SCD2 records")

            if not candidate_records:
                logger.info("No inventory changes detected; skipping BigQuery write.")
                self.record_extraction_metadata('inventory', 0)
                return True

            # =====================================================================
            # Stage 2: Create Staging Table & Load Data
            # =====================================================================

            logger.info("Creating staging table for MERGE operation...")
            staging_table_name = f"etlobjectscd2_staging_{int(time.time())}"
            schema = self._get_etlobjectscd2_schema()

            try:
                staging_table_id = self.bq_manager.create_staging_table(
                    staging_table_name,
                    schema
                )
            except Exception as exc:
                logger.error("  ✗ Failed to create staging table: %s", exc, exc_info=True)
                return False

            logger.info(f"Loading {len(candidate_records)} records to staging table...")
            try:
                self.bq_manager.load_records_to_staging(staging_table_id, candidate_records)
            except Exception as exc:
                logger.error("  ✗ Failed to load records to staging: %s", exc, exc_info=True)
                return False

            # =====================================================================
            # Stage 3: Execute MERGE (Atomic Operation)
            # =====================================================================

            target_table = f"{self.project_id}.{self.dataset_id}.etlobjectscd2"

            logger.info("Executing atomic MERGE operation (closes old versions, inserts new)...")
            try:
                success = self.scd2_processor.execute_scd2_merge(
                    self.bq_manager.client,
                    target_table,
                    staging_table_id,
                    effective_date
                )

                if not success:
                    logger.error("  ✗ MERGE operation failed")
                    return False

            except google_exceptions.GoogleAPICallError as exc:
                logger.error("  ✗ BigQuery API error during MERGE: %s", exc, exc_info=True)
                return False
            except Exception as exc:
                logger.error("  ✗ Unexpected error during MERGE: %s", exc, exc_info=True)
                return False

            # =====================================================================
            # Stage 4: Cleanup & Record Metadata
            # =====================================================================

            logger.info("Cleaning up staging table...")
            try:
                self.bq_manager.drop_staging_table(staging_table_id)
                staging_table_id = None  # Mark as cleaned up
            except Exception as exc:
                logger.warning("  ⚠ Warning: Could not drop staging table (will auto-expire): %s", exc)
                # Don't return False - staging table will auto-expire in 1 hour anyway

            logger.info("  ✓ Inventory SCD2 changes applied via atomic MERGE")
            self.record_extraction_metadata('inventory', len(candidate_records))
            return True

        except Exception as e:
            logger.error(f"Inventory extraction failed: {e}", exc_info=True)
            return False

        finally:
            # Ensure staging table is cleaned up even on error
            if staging_table_id:
                try:
                    logger.warning("Cleaning up staging table due to error...")
                    self.bq_manager.drop_staging_table(staging_table_id)
                except Exception as exc:
                    logger.warning("  ⚠ Could not drop staging table (will auto-expire): %s", exc)

    def convert_to_scd2_format(
        self,
        objects: List[Any],
        effective_date: str
    ) -> List[Dict[str, Any]]:
        """
        Convert collected objects into SCD2-ready dictionaries.

        Args:
            objects: List of ETLObject instances with assigned IDs.
            effective_date: Date string (YYYY-MM-DD) to use for SCD2 effective_start.

        Returns:
            List of dictionaries ready for SCD2 deduplication/insertion.
        """
        records: List[Dict[str, Any]] = []
        effective_start = effective_date
        if isinstance(effective_date, datetime):
            effective_start = effective_date.date().isoformat()
        elif isinstance(effective_date, date):
            effective_start = effective_date.isoformat()
        elif isinstance(effective_date, str):
            effective_start = effective_date.strip()
            if "T" in effective_start:
                effective_start = effective_start.split("T", 1)[0]

        for obj in objects:
            metadata = getattr(obj, "metadata", None)
            record = {
                "object_id": getattr(obj, "object_id", None),
                "object_type": getattr(obj.object_type, "value", str(getattr(obj, "object_type", ""))),
                "name": getattr(obj, "name", None),
                "parent_id": getattr(obj, "parent_id", None),
                "status": getattr(obj.status, "value", str(getattr(obj, "status", ""))),
                "metadata": self._serialize_metadata(metadata),
                "version": 1,
                "effective_start": effective_start,
                "effective_end": None,
            }
            records.append(record)

        return records

    def deduplicate_scd2_records(
        self,
        new_records: List[Dict[str, Any]],
        existing_records: Dict[str, Dict[str, Any]],
        effective_date: str,
        latest_versions: Optional[Dict[str, int]] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
        """
        Compare new SCD2 records against existing active records and identify changes.

        Args:
            new_records: Newly collected SCD2 candidate records.
            existing_records: Mapping of object_id -> active SCD2 record from BigQuery.
            effective_date: Date string to use for new version effective_start.

        Returns:
            Tuple of (records_to_insert, records_to_update, stats)
        """
        stats = {"new": 0, "changed": 0, "unchanged": 0}
        records_to_insert: List[Dict[str, Any]] = []
        records_to_update: List[Dict[str, Any]] = []

        for record in new_records:
            object_id = record.get("object_id")
            if not object_id:
                logger.debug("Skipping record without object_id: %s", record)
                continue

            existing = existing_records.get(object_id)
            new_signature = self._build_compare_signature(record)

            if not existing:
                stats["new"] += 1
                record_to_insert = record.copy()
                max_version = (latest_versions or {}).get(object_id, 0)
                if max_version:
                    record_to_insert["version"] = max_version + 1
                records_to_insert.append(record_to_insert)
                continue

            existing_signature = self._build_compare_signature(existing)

            if new_signature == existing_signature:
                stats["unchanged"] += 1
                continue

            stats["changed"] += 1
            current_version = existing.get("version") or 0
            if latest_versions and object_id in latest_versions:
                current_version = max(current_version, latest_versions.get(object_id, 0))
            records_to_update.append(
                {
                    "object_id": object_id,
                    "version": current_version,
                }
            )

            updated_record = record.copy()
            updated_record["version"] = current_version + 1
            updated_record["effective_start"] = effective_date
            updated_record["effective_end"] = None
            records_to_insert.append(updated_record)

        return records_to_insert, records_to_update, stats

    def _fetch_current_scd2_records(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
        """Retrieve currently active SCD2 records and latest version numbers from BigQuery."""
        table_id = f"{self.project_id}.{self.dataset_id}.etlobjectscd2"
        query = f"""
        SELECT object_id,
               object_type,
               name,
               parent_id,
               status,
               effective_start,
               effective_end,
               version,
               metadata
        FROM `{table_id}`
        WHERE effective_end IS NULL
        ORDER BY object_id, version
        """

        try:
            results = self.bq_manager.client.query(query).result()
        except google_exceptions.GoogleAPICallError as exc:
            logger.error("Failed to fetch existing SCD2 records (BigQuery API error): %s", exc, exc_info=True)
            raise
        except Exception as exc:
            logger.error("Unexpected error fetching existing SCD2 records: %s", exc, exc_info=True)
            raise

        records: Dict[str, Dict[str, Any]] = {}
        for row in results:
            row_dict = dict(row)
            object_id = row_dict.get("object_id")
            if not object_id:
                continue

            existing = records.get(object_id)
            if existing and existing.get("version", 0) > row_dict.get("version", 0):
                continue
            records[object_id] = row_dict

        latest_versions_query = f"""
        SELECT object_id, MAX(version) AS max_version
        FROM `{table_id}`
        GROUP BY object_id
        """

        try:
            latest_results = self.bq_manager.client.query(latest_versions_query).result()
        except google_exceptions.GoogleAPICallError as exc:
            logger.error("Failed to fetch latest SCD2 versions (BigQuery API error): %s", exc, exc_info=True)
            raise
        except Exception as exc:
            logger.error("Unexpected error fetching latest SCD2 versions: %s", exc, exc_info=True)
            raise

        latest_versions: Dict[str, int] = {}
        for row in latest_results:
            row_dict = dict(row)
            object_id = row_dict.get("object_id")
            max_version = row_dict.get("max_version")
            if object_id is None or max_version is None:
                continue
            try:
                latest_versions[object_id] = int(max_version)
            except (TypeError, ValueError):
                logger.debug("Could not parse max_version %s for object %s", max_version, object_id)

        return records, latest_versions

    def _expire_existing_versions(
        self,
        table_id: str,
        records_to_update: List[Dict[str, Any]],
        effective_date: str
    ) -> None:
        """Set effective_end for superseded SCD2 records."""
        for entry in records_to_update:
            object_id = entry.get("object_id")
            version = entry.get("version")
            if not object_id or version is None:
                logger.debug("Skipping expire request with missing identifiers: %s", entry)
                continue

            try:
                version_int = int(version)
            except (TypeError, ValueError):
                logger.debug("Skipping expire request with non-integer version: %s", entry)
                continue

            update_query = f"""
            UPDATE `{table_id}`
            SET effective_end = '{effective_date}'
            WHERE object_id = '{object_id}'
              AND version = {version_int}
              AND effective_end IS NULL
            """
            self.bq_manager.client.query(update_query).result()

    def _serialize_metadata(self, metadata: Any) -> str:
        """Serialize metadata payload to a JSON string suitable for storage."""
        if metadata is None:
            return "{}"

        if isinstance(metadata, str):
            stripped = metadata.strip()
            return stripped or "{}"

        try:
            return json.dumps(metadata, sort_keys=True, default=str)
        except (TypeError, ValueError):
            logger.debug("Could not serialize metadata %s; defaulting to empty object", metadata)
            return "{}"

    def _normalize_metadata_for_compare(self, metadata: Any) -> str:
        """Produce a stable representation of metadata for equality checks."""
        if metadata in (None, "", "{}"):
            return "{}"

        if isinstance(metadata, str):
            stripped = metadata.strip()
            if not stripped:
                return "{}"
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                return stripped
            return json.dumps(parsed, sort_keys=True)

        try:
            return json.dumps(metadata, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(metadata)

    def _build_compare_signature(self, record: Dict[str, Any]) -> str:
        """Create a comparison signature for SCD2 change detection."""
        comparable = {
            "object_type": record.get("object_type"),
            "name": record.get("name"),
            "parent_id": record.get("parent_id"),
            "status": record.get("status"),
            "metadata": self._normalize_metadata_for_compare(record.get("metadata")),
        }
        return json.dumps(comparable, sort_keys=True, default=str)

    # ========================================================================
    # LOGS EXTRACTION - DELTA (only new logs since last extraction)
    # ========================================================================

    def get_last_log_extraction_time(self):
        """Get timestamp of last log extraction."""
        query = f"""
        SELECT MAX(extraction_timestamp) as last_extraction
        FROM `{self.project_id}.{self.dataset_id}.minietl_metadata`
        WHERE extraction_type = 'logs'
        """
        try:
            result = list(self.bq_manager.client.query(query).result())
            if result and result[0]['last_extraction']:
                return self._to_utc_datetime(result[0]['last_extraction'])
            logger.info("First run detected - no prior extraction metadata for logs.")
        except google_exceptions.GoogleAPICallError as exc:
            logger.warning("Unable to retrieve last log extraction time: %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("Unexpected error retrieving last log extraction time: %s", exc, exc_info=True)

        return None

    def run_logs_extraction(self, days_back: int = 7, delta: bool = False):
        """Extract execution logs (DELTA if delta=True, else FULL)."""
        logger.info("="*60)
        logger.info(f"LOGS EXTRACTION ({'DELTA' if delta else 'FULL'})")
        logger.info("="*60)
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)

        try:
            # Verify inventory exists
            inventory_query = f"SELECT COUNT(*) as count FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`"
            result = list(self.bq_manager.client.query(inventory_query).result())[0]
            inventory_count = result['count']

            if inventory_count == 0:
                logger.warning("No objects in inventory. Run inventory extraction first.")
                return False

            logger.info(f"Found {inventory_count} objects in inventory")

            if delta:
                # Get last extraction time
                last_extraction = self.get_last_log_extraction_time()
                if last_extraction:
                    query_start_time = last_extraction
                    logger.info("Delta extraction since UTC timestamp: %s", query_start_time.isoformat())
                else:
                    query_start_time = now_utc - timedelta(days=days_back)
                    logger.info(
                        "First delta extraction run detected. Backfilling the last %s days starting from %s.",
                        days_back,
                        query_start_time.date().isoformat()
                    )
            else:
                # Full extraction for past N days
                query_start_time = now_utc - timedelta(days=days_back)
                logger.info(f"Full extraction for past {days_back} days")

            # Get list of objects
            objects_query = f"""
            SELECT DISTINCT object_id, name, object_type
            FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
            WHERE effective_end IS NULL
            """

            objects = list(self.bq_manager.client.query(objects_query).result())
            logger.info(f"Found {len(objects)} active objects")

            # Initialize logs explorer
            logs_explorer = LogsExplorer(
                project_id=self.project_id,
                credentials=self.credentials,
                dataset_id=self.dataset_id
            )

            log_records = []
            end_date = now_utc.date().isoformat()
            lookup_window_seconds = max(int((now_utc - query_start_time).total_seconds()), 0)
            lookup_days = max(1, lookup_window_seconds // 86400 + 1)

            # Collect logs for each object
            for obj in objects:
                object_id = obj['object_id']
                object_name = obj['name']
                try:
                    # Fetch logs from Cloud Logging API
                    logs = logs_explorer.fetch_logs_from_cloud_logging(
                        object_name=object_name,
                        days_back=lookup_days
                    )

                    for log in logs:
                        log_timestamp = self._to_utc_datetime(
                            log.get('created_at') or log.get('run_date')
                        )

                        if delta and log_timestamp and log_timestamp <= query_start_time:
                            continue

                        duration_seconds = log.get('duration_seconds')
                        if duration_seconds is None:
                            duration_seconds = 0
                        else:
                            try:
                                duration_seconds = float(duration_seconds)
                            except (TypeError, ValueError):
                                logger.debug(
                                    "Could not parse duration_seconds value %s for object %s",
                                    duration_seconds,
                                    object_id
                                )
                                duration_seconds = 0

                        # Generate unique log_id (UUID)
                        log_id = str(uuid.uuid4())

                        # Get start and end times if available - convert to strings for JSON
                        start_time = log.get('start_time')
                        if start_time and hasattr(start_time, 'isoformat'):
                            start_time = start_time.isoformat()
                        elif start_time:
                            start_time = str(start_time)

                        end_time = log.get('end_time')
                        if end_time and hasattr(end_time, 'isoformat'):
                            end_time = end_time.isoformat()
                        elif end_time:
                            end_time = str(end_time)

                        # Get records/rows processed
                        records_processed = log.get('records_processed') or log.get('rows_processed')

                        # Get created_at timestamp
                        created_at = log.get('created_at')
                        if created_at:
                            created_at = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
                        else:
                            created_at = datetime.utcnow().isoformat() + "Z"

                        record = {
                            "log_id": log_id,
                            "object_id": object_id,
                            "run_date": log.get('run_date', end_date),
                            "start_time": start_time if start_time else None,
                            "end_time": end_time if end_time else None,
                            "duration_min": int(duration_seconds / 60) if duration_seconds else 0,
                            "duration_seconds": duration_seconds if duration_seconds else None,
                            "status": log.get('status', 'unknown'),
                            "error_message": log.get('error_message') or None,
                            "created_at": created_at,
                            "records_processed": records_processed if records_processed else None,
                            "rows_processed": records_processed if records_processed else None,
                            "bytes_processed": log.get('bytes_processed') or None
                        }
                        log_records.append(record)

                except google_exceptions.GoogleAPICallError as exc:
                    logger.warning(
                        "BigQuery API issue while retrieving logs for object %s: %s",
                        object_id,
                        exc,
                        exc_info=True
                    )
                except Exception as exc:
                    logger.error("Unexpected error retrieving logs for %s: %s", object_id, exc, exc_info=True)

            logger.info(f"  ✓ Collected {len(log_records)} log records")

            # Track count for metrics reporting
            logs_count = len(log_records)

            if log_records:
                # Insert into BigQuery
                logger.info("Inserting into BigQuery...")
                table_id = f"{self.project_id}.{self.dataset_id}.factlog"
                try:
                    errors = self._insert_rows_with_retry(table_id, log_records)
                except google_exceptions.GoogleAPICallError as exc:
                    logger.error("  ✗ BigQuery API error inserting logs: %s", exc, exc_info=True)
                    return (False, 0)

                if errors:
                    logger.error(f"  ✗ Insert errors: {errors}")
                    return (False, 0)

                logger.info(f"  ✓ Successfully inserted {logs_count} records")

            else:
                logger.info("  ✓ No new logs to extract")

            self.record_extraction_metadata('logs', logs_count)
            return (True, logs_count)

        except Exception as e:
            logger.error(f"Log extraction failed: {e}", exc_info=True)
            return (False, 0)

    # ========================================================================
    # BILLING EXTRACTION - DELTA (only new costs since last extraction)
    # ========================================================================

    def get_last_billing_extraction_time(self):
        """Get timestamp of last billing extraction."""
        query = f"""
        SELECT MAX(extraction_timestamp) as last_extraction
        FROM `{self.project_id}.{self.dataset_id}.minietl_metadata`
        WHERE extraction_type = 'billing'
        """
        try:
            result = list(self.bq_manager.client.query(query).result())
            if result and result[0]['last_extraction']:
                return self._to_utc_datetime(result[0]['last_extraction'])
            logger.info("First run detected - no prior extraction metadata for billing.")
        except google_exceptions.GoogleAPICallError as exc:
            logger.warning("Unable to retrieve last billing extraction time: %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("Unexpected error retrieving last billing extraction time: %s", exc, exc_info=True)

        return None

    def run_billing_extraction(self, delta: bool = False):
        """Extract billing data (DELTA if delta=True, else FULL)."""
        logger.info("="*60)
        logger.info(f"BILLING EXTRACTION ({'DELTA' if delta else 'FULL'})")
        logger.info("="*60)
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)

        try:
            # Verify inventory exists
            inventory_query = f"SELECT COUNT(*) as count FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`"
            result = list(self.bq_manager.client.query(inventory_query).result())[0]
            inventory_count = result['count']

            if inventory_count == 0:
                logger.warning("No objects in inventory.")
                return False

            logger.info(f"Found {inventory_count} objects")

            if delta:
                last_extraction = self.get_last_billing_extraction_time()
                if last_extraction:
                    start_timestamp = last_extraction
                    logger.info("Delta extraction since UTC timestamp: %s", start_timestamp.isoformat())
                else:
                    start_timestamp = now_utc - timedelta(days=30)
                    logger.info(
                        "First delta billing extraction run detected. Backfilling the last 30 days starting from %s.",
                        start_timestamp.date().isoformat()
                    )
            else:
                start_timestamp = now_utc - timedelta(days=30)
                logger.info("Full extraction for past 30 days")

            # Check if billing export exists
            logger.info("Checking for billing export data...")
            billing_table = "prismatic-smoke-463810-c1.analytics.gcp_billing_export_v1_01F440_3D63CA_0606BA"

            try:
                check_query = f"""
                SELECT COUNT(*) as count
                FROM `{billing_table}`
                LIMIT 1
                """
                result = list(self.bq_manager.client.query(check_query).result())
                billing_count = result[0]['count'] if result else 0
            except google_exceptions.GoogleAPICallError as exc:
                logger.warning("Unable to verify billing export availability: %s", exc, exc_info=True)
                billing_count = 0
            except Exception as exc:
                logger.error("Unexpected error verifying billing export availability: %s", exc, exc_info=True)
                billing_count = 0

            if billing_count == 0:
                logger.warning("No billing export data found")
                self.record_extraction_metadata('billing', 0)
                return (True, 0)

            logger.info(f"  ✓ Found {billing_count} billing records")

            # Extract billing
            logger.info("Extracting billing data...")
            start_timestamp_str = start_timestamp.isoformat()
            billing_query = f"""
            SELECT
              CAST(usage_start_time AS DATE) as run_date,
              service.description as service,
              SUM(cost) as cost_usd,
              COUNT(*) as usage_records
            FROM `{billing_table}`
            WHERE usage_start_time > TIMESTAMP('{start_timestamp_str}')
            GROUP BY run_date, service
            ORDER BY run_date DESC
            """

            billing_records = []
            # Map billing service names to inventory object types
            service_mapping = {
                'Cloud Pub/Sub': 'PUBSUB',
                'Cloud Scheduler': 'TRIGGER',
                'Workflows': 'WORKFLOW',
                'Cloud Run Functions': 'CLOUD_RUN',
                'Cloud Run': 'CLOUD_RUN',
                'Cloud Functions': 'FUNCTION',
                'Cloud Dataflow': 'FUNCTION',
                'BigQuery': 'FUNCTION',  # No specific BQ object type in inventory
                'Cloud Storage': 'FUNCTION',  # No specific storage object type
            }

            for row in self.bq_manager.client.query(billing_query).result():
                service_name = row['service'] or 'Unknown'
                service_type = None

                # Match service name to object type
                for billing_service, obj_type in service_mapping.items():
                    if billing_service.lower() in str(service_name).lower():
                        service_type = obj_type
                        break

                if service_type:
                    obj_query = f"""
                    SELECT object_id FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
                    WHERE object_type = '{service_type}'
                    AND effective_end IS NULL
                    LIMIT 1
                    """
                    try:
                        obj_result = list(self.bq_manager.client.query(obj_query).result())
                        if obj_result:
                            billing_records.append({
                                "object_id": obj_result[0]['object_id'],
                                "run_date": str(row['run_date']),
                                "service": service_name,
                                "cost_usd": float(row['cost_usd'] or 0),
                                "compute_units": None,
                                "slot_hours": None
                            })
                    except google_exceptions.GoogleAPICallError as exc:
                        logger.warning(
                            "BigQuery API issue while mapping billing record for service %s: %s",
                            service_name,
                            exc,
                            exc_info=True
                        )
                    except Exception as exc:
                        logger.debug(
                            "Error while mapping billing record for service %s: %s",
                            service_name,
                            exc
                        )

            logger.info(f"  ✓ Collected {len(billing_records)} billing records")

            # Track count for metrics reporting
            billing_count = len(billing_records)

            if billing_records:
                logger.info("Inserting into BigQuery...")
                table_id = f"{self.project_id}.{self.dataset_id}.factbilling"
                try:
                    errors = self._insert_rows_with_retry(table_id, billing_records)
                except google_exceptions.GoogleAPICallError as exc:
                    logger.error("  ✗ BigQuery API error inserting billing records: %s", exc, exc_info=True)
                    return (False, 0)

                if errors:
                    logger.error(f"  ✗ Insert errors: {errors}")
                    return (False, 0)

                logger.info(f"  ✓ Successfully inserted {billing_count} records")

            self.record_extraction_metadata('billing', billing_count)
            return (True, billing_count)

        except Exception as e:
            logger.error(f"Billing extraction failed: {e}", exc_info=True)
            return (False, 0)

    def _insert_rows_with_retry(self, table_id: str, rows: list, max_attempts: int = 3):
        """Insert rows into BigQuery with basic retry logic for transient failures."""
        transient_errors = (
            google_exceptions.ServiceUnavailable,
            google_exceptions.DeadlineExceeded,
            google_exceptions.InternalServerError,
        )

        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                errors = self.bq_manager.client.insert_rows_json(table_id, rows)
                return errors or []
            except transient_errors as exc:
                if attempt >= max_attempts:
                    logger.error(
                        "Exceeded retry attempts inserting into %s: %s",
                        table_id,
                        exc,
                        exc_info=True
                    )
                    raise

                sleep_seconds = min(5, 2 ** attempt)
                logger.warning(
                    "Transient BigQuery error inserting into %s (attempt %s/%s): %s. Retrying in %s seconds.",
                    table_id,
                    attempt,
                    max_attempts,
                    exc,
                    sleep_seconds
                )
                time.sleep(sleep_seconds)
            except google_exceptions.GoogleAPICallError:
                raise
            except Exception as exc:
                logger.error(
                    "Unexpected error inserting into %s: %s",
                    table_id,
                    exc,
                    exc_info=True
                )
                raise

    def record_extraction_metadata(self, extraction_type: str, records_extracted: int):
        """Record metadata about extraction (for delta tracking)."""
        try:
            table_id = f"{self.project_id}.{self.dataset_id}.minietl_metadata"
            record = {
                "extraction_type": extraction_type,
                "extraction_timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                "records_extracted": records_extracted,
                "status": "success"
            }
            errors = self._insert_rows_with_retry(table_id, [record])
            if errors:
                logger.warning("Metadata insert returned errors for %s: %s", extraction_type, errors)
            else:
                logger.debug("Recorded metadata for %s (records=%s)", extraction_type, records_extracted)
        except google_exceptions.GoogleAPICallError as exc:
            logger.warning("Could not record metadata for %s: %s", extraction_type, exc, exc_info=True)
        except Exception as exc:
            logger.warning("Unexpected error while recording metadata for %s: %s", extraction_type, exc, exc_info=True)

    def run_full_extraction(self):
        """Run full extraction: inventory + billing + logs."""
        # Generate unique run ID for this extraction session
        run_id = f"extraction_{int(time.time())}"
        extraction_start = time.time()

        logger.info("\n" + "="*60)
        logger.info("FULL EXTRACTION PIPELINE")
        logger.info("="*60)
        logger.info(f"Run ID: {run_id}")
        logger.info(f"Project: {self.project_id}, Dataset: {self.dataset_id}")
        logger.info(f"Started: {datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()}")
        logger.info("="*60 + "\n")

        results = {}
        metrics = {}

        # Inventory (always FULL)
        inventory_start = time.time()
        inventory_result = self.run_inventory_extraction()
        inventory_duration = int(time.time() - inventory_start)
        results['inventory'] = inventory_result
        logger.info("")

        # Record inventory metrics
        if inventory_result:
            metrics['inventory'] = {
                'status': 'SUCCESS',
                'duration': inventory_duration,
                'error': None
            }
            # For now, we'll query the table to get exact counts
            try:
                inventory_count = self._count_objects_in_table()
                metrics['inventory']['etlobjectscd2_new'] = inventory_count
            except:
                metrics['inventory']['etlobjectscd2_new'] = 0
        else:
            metrics['inventory'] = {
                'status': 'FAILED',
                'duration': inventory_duration,
                'error': 'Inventory extraction failed'
            }

        if results['inventory']:
            # Logs (DELTA) - Optional, doesn't block extraction if it fails
            logs_start = time.time()
            try:
                logs_result_tuple = self.run_logs_extraction(days_back=7, delta=True)
                logs_duration = int(time.time() - logs_start)

                # Handle both old (bool) and new (tuple) return formats
                if isinstance(logs_result_tuple, tuple):
                    logs_result, logs_count = logs_result_tuple
                else:
                    logs_result = logs_result_tuple
                    logs_count = 0

                results['logs'] = logs_result
            except Exception as e:
                logger.warning(f"Logs extraction skipped (optional): {e}")
                logs_duration = int(time.time() - logs_start)
                logs_result = True  # Don't fail entire extraction
                logs_count = 0
                results['logs'] = True

            logger.info("")

            # Record logs metrics
            metrics['logs'] = {
                'status': 'SKIPPED (Optional)',
                'duration': logs_duration,
                'factlog_inserted': logs_count
            }

            # Billing (DELTA) - Optional, doesn't block extraction if it fails
            billing_start = time.time()
            try:
                billing_result_tuple = self.run_billing_extraction(delta=True)
                billing_duration = int(time.time() - billing_start)

                # Handle both old (bool) and new (tuple) return formats
                if isinstance(billing_result_tuple, tuple):
                    billing_result, billing_count = billing_result_tuple
                else:
                    billing_result = billing_result_tuple
                    billing_count = 0

                results['billing'] = billing_result
            except Exception as e:
                logger.warning(f"Billing extraction skipped (optional): {e}")
                billing_duration = int(time.time() - billing_start)
                billing_result = True  # Don't fail entire extraction
                billing_count = 0
                results['billing'] = True

            logger.info("")

            # Record billing metrics
            metrics['billing'] = {
                'status': 'SKIPPED (Optional)',
                'duration': billing_duration,
                'factbilling_inserted': billing_count
            }
        else:
            metrics['logs'] = {'status': 'SKIPPED', 'duration': 0, 'factlog_inserted': 0}
            metrics['billing'] = {'status': 'SKIPPED', 'duration': 0, 'factbilling_inserted': 0}
            results['logs'] = False
            results['billing'] = False

        # Record metrics for each phase
        for phase_name, phase_metrics in metrics.items():
            phase_upper = phase_name.upper()
            self.bq_manager.record_extraction_report(
                run_id=run_id,
                extraction_phase=phase_upper,
                status=phase_metrics.get('status', 'UNKNOWN'),
                etlobjectscd2_new=phase_metrics.get('etlobjectscd2_new', 0),
                factlog_inserted=phase_metrics.get('factlog_inserted', 0),
                factbilling_inserted=phase_metrics.get('factbilling_inserted', 0),
                duration_sec=phase_metrics.get('duration', 0),
                error_message=phase_metrics.get('error')
            )

        # Summary
        total_duration = int(time.time() - extraction_start)
        logger.info("="*60)
        logger.info("EXTRACTION SUMMARY")
        logger.info("="*60)
        logger.info(f"Inventory: {'✓ PASS (FULL)' if results.get('inventory') else '✗ FAIL'}")
        logger.info(f"Logs:      {'✓ SKIPPED (Optional)' if results.get('logs') else '✗ FAIL'}")
        logger.info(f"Billing:   {'✓ SKIPPED (Optional)' if results.get('billing') else '✗ FAIL'}")
        logger.info(f"Total Duration: {total_duration}s")
        logger.info(f"Completed: {datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()}")
        logger.info("="*60)

        # Inventory MUST pass, logs/billing are optional
        inventory_passed = results.get('inventory', False)
        return 0 if inventory_passed else 1

    def run_inventory_only(self):
        """Run inventory extraction only."""
        return 0 if self.run_inventory_extraction() else 1

    def run_logs_only(self, days_back: int = 7, delta: bool = False):
        """Run logs extraction only."""
        return 0 if self.run_logs_extraction(days_back=days_back, delta=delta) else 1

    def run_billing_only(self, delta: bool = False):
        """Run billing extraction only."""
        return 0 if self.run_billing_extraction(delta=delta) else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="SyncFlow miniETL Enhanced - Full + Delta Extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--sa', help='Path to service account JSON')
    parser.add_argument('--project', default='prismatic-smoke-463810-c1', help='GCP project ID')
    parser.add_argument('--dataset', default='minietl', help='BigQuery dataset ID')
    parser.add_argument(
        '--use-default-credentials',
        action='store_true',
        help='Use application default credentials (needed for Cloud Functions / ambient auth)'
    )

    # Extraction type
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--full', action='store_true', help='Full extraction (inventory FULL, logs DELTA, billing DELTA)')
    group.add_argument('--inventory', action='store_true', help='Inventory extraction only (FULL)')
    group.add_argument('--logs', action='store_true', help='Logs extraction only')
    group.add_argument('--billing', action='store_true', help='Billing extraction only')

    # Options
    parser.add_argument('--delta', action='store_true', help='Use delta extraction (logs/billing only)')
    parser.add_argument('--days', type=int, default=7, help='Days of history to extract (logs only)')

    args = parser.parse_args()

    # Validate service account
    sa_path = Path(args.sa).expanduser() if args.sa else None
    if sa_path and not sa_path.exists():
        logger.error(f"Service account file not found: {sa_path}")
        return 1

    sa_path_str = str(sa_path) if sa_path else None

    # Initialize CLI
    try:
        cli = MinietlEnhancedCLI(
            sa_path_str,
            args.project,
            args.dataset,
            use_default_credentials=args.use_default_credentials
        )
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    except Exception:
        # __init__ already logged the error details
        return 1

    # Determine which extraction to run
    if args.full or (not args.inventory and not args.logs and not args.billing):
        return cli.run_full_extraction()
    elif args.inventory:
        return cli.run_inventory_only()
    elif args.logs:
        return cli.run_logs_only(days_back=args.days, delta=args.delta)
    elif args.billing:
        return cli.run_billing_only(delta=args.delta)

    return 0


if __name__ == '__main__':
    sys.exit(main())
