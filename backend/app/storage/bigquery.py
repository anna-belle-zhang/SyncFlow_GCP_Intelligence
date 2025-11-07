"""BigQuery storage abstractions for the SyncFlow backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from google.cloud import bigquery


class StorageError(RuntimeError):
    """Base class for storage-related exceptions."""


class NotFoundError(StorageError):
    """Raised when a requested record cannot be located."""


class BigQueryStorage:
    """Wrapper around BigQueryManager providing read-focused helpers."""

    def __init__(self, manager):
        self._manager = manager

    @property
    def client(self):
        return self._manager.client

    def list_objects(self) -> List[Dict[str, Any]]:
        sql = (
            f"SELECT * FROM `{self._table('etlobjectscd2_enriched')}` "
            "WHERE effective_end IS NULL "
            "ORDER BY object_id"
        )
        return self._execute_query(sql)

    def get_object(self, object_id: str) -> Dict[str, Any]:
        sql = (
            "SELECT * FROM `{table}` WHERE object_id = @object_id "
            "AND effective_end IS NULL"
        ).format(table=self._table("etlobjectscd2_enriched"))
        rows = self._execute_query(sql, params={"object_id": object_id})
        if not rows:
            raise NotFoundError(f"Object {object_id} not found")
        return rows[0]

    def get_object_history(self, object_id: str) -> List[Dict[str, Any]]:
        sql = (
            "SELECT * FROM `{table}` WHERE object_id = @object_id "
            "ORDER BY effective_start DESC"
        ).format(table=self._table("etlobjectscd2"))
        return self._execute_query(sql, params={"object_id": object_id})

    def _execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        logging.getLogger(__name__).debug("Executing storage query: %s", sql)

        if params:
            job_config = bigquery.QueryJobConfig()
            # Convert params dict to list of ScalarQueryParameter for BigQuery
            query_parameters = [
                bigquery.ScalarQueryParameter(key, "STRING", str(value))
                for key, value in params.items()
            ]
            job_config.query_parameters = query_parameters
            query_job = self.client.query(sql, job_config=job_config)
        else:
            query_job = self.client.query(sql)

        return [dict(row) for row in query_job]

    def _table(self, name: str) -> str:
        project = getattr(self._manager, "project_id", None) or ""
        dataset = getattr(self._manager, "dataset_id", None) or ""
        return f"{project}.{dataset}.{name}" if project and dataset else name


__all__ = [
    "BigQueryStorage",
    "StorageError",
    "NotFoundError",
]
