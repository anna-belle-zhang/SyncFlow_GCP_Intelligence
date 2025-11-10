"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

from typing import Callable, Optional

import pytest

from backend.tests.fakes import (
    FakeBigQueryClient,
    FakeBillingService,
    FakeLogEntry,
    FakeLogsService,
)


# Note: ETLObject and EdgeType classes were refactored out of models.py
# as part of the cleanup - models.py now contains only BigQuery schema definitions.
# These fixtures are kept for backward compatibility but should be updated
# to use domain-specific data structures from agents/models_adk.py if needed.

@pytest.fixture
def make_etl_object() -> Callable[[str, str], dict]:
    """Factory for building ETL object dictionaries without real GCP dependencies."""

    def _factory(name: str, object_type: str = "FUNCTION") -> dict:
        return {
            "object_id": "",
            "object_type": object_type,
            "name": name,
            "metadata": {},
        }

    return _factory


@pytest.fixture
def make_edge():
    """Factory for building ETL edge dictionaries with optional assigned IDs."""

    def _factory(
        source_name: str,
        target_name: str,
        edge_type: str = "DEPENDS_ON",
    ) -> dict:
        return {
            "edge_id": f"{source_name}->{target_name}",
            "source_object_id": "",
            "target_object_id": "",
            "edge_type": edge_type,
            "source_name": source_name,
            "target_name": target_name,
        }

    return _factory


@pytest.fixture
def fake_bigquery_client() -> FakeBigQueryClient:
    """In-memory BigQuery client capturing queries and inserts."""
    return FakeBigQueryClient()


@pytest.fixture
def fake_logs_service() -> FakeLogsService:
    """Logs service preloaded with optional entries."""
    return FakeLogsService()


@pytest.fixture
def fake_billing_service() -> FakeBillingService:
    """Billing service that can be seeded with canned costs."""
    return FakeBillingService()


@pytest.fixture
def fake_log_entry_factory() -> Callable[[str, Optional[str], str], FakeLogEntry]:
    """Factory that helps build consistent log entries for tests."""

    def _factory(
        object_id: str,
        severity: Optional[str] = None,
        message: str = "",
        timestamp: str = "2025-10-31T00:00:00Z",
    ) -> FakeLogEntry:
        return FakeLogEntry(
            object_id=object_id,
            severity=severity or "INFO",
            message=message,
            timestamp=timestamp,
        )

    return _factory
