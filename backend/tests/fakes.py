"""Lightweight fake implementations for backend dependencies.

These helpers keep unit tests isolated from Google Cloud SDKs while still
providing realistic behaviour (query logging, simple filtering, etc.).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional


class FakeQueryJob:
    """Minimal stand-in for BigQuery query job results."""

    def __init__(self, rows: Iterable[Dict[str, Any]]):
        self._rows = list(rows)

    def result(self) -> List[Dict[str, Any]]:
        """Return materialised rows like google.cloud.bigquery job objects."""
        return list(self._rows)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self._rows)


class FakeBigQueryClient:
    """Records queries and can return pre-canned result sets."""

    def __init__(self, query_results: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None):
        self.query_results: Dict[str, List[Dict[str, Any]]] = {
            sql: list(rows) for sql, rows in (query_results or {}).items()
        }
        self.executed_queries: List[str] = []
        self.insert_calls: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    def register_query_result(self, sql: str, rows: Iterable[Dict[str, Any]]) -> None:
        """Register canned rows to be returned when a query executes."""
        self.query_results[sql] = list(rows)

    def query(self, sql: str, job_config: Any | None = None):
        """Simulate BigQuery client's query method."""
        self.executed_queries.append((sql, job_config))
        rows = self.query_results.get(sql, [])
        return FakeQueryJob(rows)

    def insert_rows_json(self, table_id: str, rows: Iterable[Dict[str, Any]]):
        """Track inserted rows for assertions."""
        self.insert_calls[table_id].extend(list(rows))
        return []  # mimic BigQuery client returning empty error list


@dataclass
class FakeLogEntry:
    object_id: str
    severity: str = "INFO"
    message: str = ""
    timestamp: str = "2025-10-31T00:00:00Z"


class FakeLogsService:
    """Simple in-memory log store for agent/log tests."""

    def __init__(self, entries: Optional[Iterable[FakeLogEntry]] = None):
        self.entries: List[FakeLogEntry] = list(entries or [])
        self.requests: List[Dict[str, Any]] = []

    def query(self, object_id: Optional[str] = None, severity: Optional[str] = None) -> List[FakeLogEntry]:
        """Return log entries filtered by object id and/or severity."""
        self.requests.append({"object_id": object_id, "severity": severity})
        results = self.entries
        if object_id:
            results = [entry for entry in results if entry.object_id == object_id]
        if severity:
            results = [entry for entry in results if entry.severity == severity]
        return list(results)


class FakeBillingService:
    """Tracks cost lookups for unit tests."""

    def __init__(self, cost_map: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.cost_map = cost_map or {}
        self.lookup_requests: List[Dict[str, Any]] = []

    def get_costs(self, object_id: str, days: int = 30) -> List[Dict[str, Any]]:
        """Return canned cost breakdowns for a given object."""
        self.lookup_requests.append({"object_id": object_id, "days": days})
        return list(self.cost_map.get(object_id, []))

    def register_costs(self, object_id: str, rows: Iterable[Dict[str, Any]]) -> None:
        """Add/overwrite canned cost rows for an object."""
        self.cost_map[object_id] = list(rows)
