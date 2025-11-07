"""
SCD Type 2 (Slowly Changing Dimensions) processor.

Handles:
- Detecting changes in ETL objects
- Maintaining version history
- Managing effective date ranges
- Archiving old versions
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import json

from backend.models import ETLObject, ObjectStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SCD2Processor:
    """Processes SCD Type 2 changes for ETL objects."""

    def __init__(self):
        """Initialize SCD2 processor."""
        self.change_log: List[Dict] = []

    @staticmethod
    def detect_changes(existing: Optional[ETLObject], new: ETLObject) -> bool:
        """
        Detect if object has changed.

        Args:
            existing: Existing ETLObject (None if new)
            new: New ETLObject to compare

        Returns:
            True if changes detected
        """
        if not existing:
            return True  # New object

        # Check significant fields for changes
        changed_fields = []

        if existing.name != new.name:
            changed_fields.append("name")

        if existing.object_type != new.object_type:
            changed_fields.append("object_type")

        if existing.description != new.description:
            changed_fields.append("description")

        if existing.parent_id != new.parent_id:
            changed_fields.append("parent_id")

        if existing.gcp_resource_name != new.gcp_resource_name:
            changed_fields.append("gcp_resource_name")

        # Deep comparison of metadata
        if json.dumps(existing.metadata, sort_keys=True) != json.dumps(
            new.metadata, sort_keys=True
        ):
            changed_fields.append("metadata")

        return len(changed_fields) > 0

    @staticmethod
    def expire_record(existing: ETLObject, effective_end: Optional[date] = None) -> ETLObject:
        """
        Expire an existing record (mark it as archived).

        Args:
            existing: ETLObject to expire
            effective_end: End date (default: today)

        Returns:
            Updated expired object
        """
        if effective_end is None:
            effective_end = datetime.now().date()

        existing.effective_end = effective_end.isoformat() if isinstance(effective_end, date) else effective_end
        existing.status = ObjectStatus.ARCHIVED

        logger.debug(f"Expired {existing.object_id}: {existing.name} (v{existing.version})")
        return existing

    @staticmethod
    def create_new_version(
        existing: Optional[ETLObject],
        new: ETLObject,
        effective_start: Optional[date] = None,
    ) -> ETLObject:
        """
        Create new version of object (SCD2 insert).

        Args:
            existing: Existing version (None if first version)
            new: New object data
            effective_start: Start date (default: today)

        Returns:
            New version of object
        """
        if effective_start is None:
            effective_start = datetime.now().date()

        effective_start_str = (
            effective_start.isoformat()
            if isinstance(effective_start, date)
            else effective_start
        )

        if existing:
            new.version = existing.version + 1
        else:
            new.version = 1

        new.effective_start = effective_start_str
        new.effective_end = None
        new.status = ObjectStatus.ACTIVE
        new.updated_at = datetime.utcnow().isoformat() + "Z"

        logger.debug(
            f"Created new version {new.version} of {new.object_id}: {new.name}"
        )
        return new

    def process_object(
        self,
        existing: Optional[ETLObject],
        new: ETLObject,
        effective_date: Optional[date] = None,
    ) -> Tuple[Optional[ETLObject], ETLObject]:
        """
        Process SCD Type 2 logic for an object.

        Args:
            existing: Existing version (None if new)
            new: New object data
            effective_date: Effective date (default: today)

        Returns:
            Tuple of (expired_record, new_record)
        """
        if effective_date is None:
            effective_date = datetime.now().date()

        expired = None

        # Check if changed
        if self.detect_changes(existing, new):
            if existing:
                # Expire old version
                expired = self.expire_record(existing, effective_date)

            # Create new version
            new_version = self.create_new_version(existing, new, effective_date)

            change_log_entry = {
                "object_id": new.object_id,
                "object_name": new.name,
                "event_type": "UPDATE" if existing else "INSERT",
                "from_version": existing.version if existing else 0,
                "to_version": new_version.version,
                "effective_date": effective_date.isoformat(),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

            self.change_log.append(change_log_entry)

            return expired, new_version

        else:
            # No changes
            logger.debug(f"No changes detected for {new.object_id}: {new.name}")
            return None, existing if existing else new

    def process_deletion(
        self,
        existing: ETLObject,
        effective_date: Optional[date] = None,
    ) -> ETLObject:
        """
        Process object deletion (SCD2 logic).

        Args:
            existing: Existing version to delete
            effective_date: Deletion date (default: today)

        Returns:
            Deleted (archived) record
        """
        if effective_date is None:
            effective_date = datetime.now().date()

        deleted = self.expire_record(existing, effective_date)
        deleted.status = ObjectStatus.DELETED

        change_log_entry = {
            "object_id": existing.object_id,
            "object_name": existing.name,
            "event_type": "DELETE",
            "from_version": existing.version,
            "to_version": existing.version,
            "effective_date": effective_date.isoformat(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        self.change_log.append(change_log_entry)

        logger.info(f"Deleted {existing.object_id}: {existing.name}")
        return deleted

    def get_change_log(self) -> List[Dict]:
        """Get change log entries."""
        return self.change_log

    def export_change_log(self, output_file: str) -> None:
        """
        Export change log to JSON.

        Args:
            output_file: Path to output file
        """
        data = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_changes": len(self.change_log),
            "changes": self.change_log,
        }

        try:
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"✓ Exported change log to {output_file}")
        except Exception as e:
            logger.error(f"Failed to export change log: {e}")
            raise

    def build_scd2_merge_statement(
        self,
        target_table: str,
        staging_table: str,
        effective_date: str
    ) -> str:
        """
        Build BigQuery MERGE statement for atomic SCD2 update.

        MERGE logic:
        - WHEN MATCHED (object exists and is current): Close old version when attributes changed
        - WHEN NOT MATCHED (new object): Insert as new version

        Args:
            target_table: Target table ID (project.dataset.etlobjectscd2)
            staging_table: Staging table ID with candidate records
            effective_date: Date string (YYYY-MM-DD) for effective_start/end

        Returns:
            MERGE SQL statement
        """
        merge_sql = f"""
        MERGE `{target_table}` T
        USING `{staging_table}` S
        ON T.object_id = S.object_id AND T.effective_end IS NULL

        WHEN MATCHED AND (
          T.object_type != S.object_type OR
          T.name != S.name OR
          T.parent_id != S.parent_id OR
          T.status != S.status
        ) THEN
          -- Close old version when attributes changed
          UPDATE SET
            effective_end = '{effective_date}',
            status = 'archived'

        WHEN NOT MATCHED THEN
          -- Insert new object or new version (default to version 1)
          INSERT (
            object_id, name, object_type, parent_id, status,
            version, effective_start, effective_end, metadata
          )
          VALUES (
            S.object_id, S.name, S.object_type, S.parent_id, S.status,
            1,
            S.effective_start, S.effective_end, PARSE_JSON(S.metadata)
          );
        """
        return merge_sql.strip()

    def execute_scd2_merge(
        self,
        bq_client,
        target_table: str,
        staging_table: str,
        effective_date: str
    ) -> bool:
        """
        Execute MERGE statement for atomic SCD2 update.

        Args:
            bq_client: BigQuery client instance
            target_table: Target table ID (project.dataset.etlobjectscd2)
            staging_table: Staging table ID with candidate records
            effective_date: Date string (YYYY-MM-DD) for effective_start/end

        Returns:
            True if successful, False otherwise
        """
        try:
            merge_sql = self.build_scd2_merge_statement(
                target_table,
                staging_table,
                effective_date
            )

            logger.info(f"Executing SCD2 MERGE statement (effective_date={effective_date})...")
            job = bq_client.query(merge_sql)
            job.result()  # Wait for completion

            logger.info(f"✓ MERGE completed successfully")
            return True

        except Exception as e:
            logger.error(f"MERGE execution failed: {e}", exc_info=True)
            return False


class SCD2Validator:
    """Validates SCD Type 2 data integrity."""

    @staticmethod
    def validate_dates(obj: ETLObject) -> List[str]:
        """
        Validate date relationships in SCD2 record.

        Args:
            obj: ETLObject to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not obj.effective_start:
            errors.append(f"{obj.object_id}: Missing effective_start")

        if obj.effective_start and obj.effective_end:
            if obj.effective_start > obj.effective_end:
                errors.append(
                    f"{obj.object_id}: effective_start > effective_end"
                )

        if obj.status == ObjectStatus.ACTIVE and obj.effective_end:
            errors.append(
                f"{obj.object_id}: Active record should not have effective_end"
            )

        if obj.status == ObjectStatus.ARCHIVED and not obj.effective_end:
            errors.append(
                f"{obj.object_id}: Archived record should have effective_end"
            )

        return errors

    @staticmethod
    def validate_version(obj: ETLObject) -> List[str]:
        """
        Validate version numbering.

        Args:
            obj: ETLObject to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if obj.version < 1:
            errors.append(f"{obj.object_id}: Version must be >= 1")

        if obj.version > 9999:
            errors.append(f"{obj.object_id}: Version exceeds maximum (9999)")

        return errors

    @staticmethod
    def validate_record(obj: ETLObject) -> List[str]:
        """
        Validate entire SCD2 record.

        Args:
            obj: ETLObject to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        errors.extend(SCD2Validator.validate_dates(obj))
        errors.extend(SCD2Validator.validate_version(obj))

        if not obj.object_id:
            errors.append("Missing object_id")

        if not obj.name:
            errors.append("Missing name")

        return errors

    @staticmethod
    def validate_batch(objects: List[ETLObject]) -> Dict[str, List[str]]:
        """
        Validate a batch of SCD2 records.

        Args:
            objects: List of ETLObject instances

        Returns:
            Dictionary mapping object_id to list of errors
        """
        results = {}

        for obj in objects:
            errors = SCD2Validator.validate_record(obj)
            if errors:
                results[obj.object_id] = errors

        return results
