"""Pytest coverage for the ADK inventory tools module.

These tests exercise the JSON parsing and dependency aggregation logic
without touching real BigQuery resources by supplying canned responses
through a sequential fake client.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from types import SimpleNamespace
from typing import Iterable, List, Sequence

import pytest

# Provide a stub google.cloud.bigquery module if the real SDK is missing.
try:  # pragma: no cover - only executed when the SDK is installed locally
    from google.cloud import bigquery  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - exercised in CI
    bigquery_stub = types.SimpleNamespace()

    class _StubClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "Tests should stub inventory_tools_standalone._bq_client; "
                "BigQuery Client should not be constructed directly."
            )

    setattr(bigquery_stub, "Client", _StubClient)
    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    setattr(cloud_mod, "bigquery", bigquery_stub)
    setattr(google_mod, "cloud", cloud_mod)
    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.cloud", cloud_mod)
    sys.modules.setdefault("google.cloud.bigquery", bigquery_stub)

from backend.agents.tools import inventory_tools_standalone as inventory_tools


class _SequentialQueryJob:
    """Minimal BigQuery query job that returns canned rows."""

    def __init__(self, rows: Iterable[SimpleNamespace]):
        self._rows: List[SimpleNamespace] = list(rows)

    def result(self) -> List[SimpleNamespace]:
        return list(self._rows)


class _SequentialBigQueryClient:
    """Fake BigQuery client that returns pre-seeded row groups in order."""

    def __init__(self, responses: Sequence[Sequence[SimpleNamespace]]):
        self._remaining: List[List[SimpleNamespace]] = [list(group) for group in responses]
        self.executed_queries: List[str] = []

    def query(self, sql: str, job_config=None):
        self.executed_queries.append(sql)
        if not self._remaining:
            raise AssertionError("No fake BigQuery responses remaining for this test.")
        rows = self._remaining.pop(0)
        return _SequentialQueryJob(rows)

    @property
    def pending(self) -> int:
        return len(self._remaining)


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, *response_groups: Sequence[SimpleNamespace]):
    """Install a sequential fake client so inventory tools use canned results."""

    client = _SequentialBigQueryClient(response_groups)
    monkeypatch.setattr(inventory_tools, "_bq_client", client, raising=False)
    return client


def _row(**kwargs) -> SimpleNamespace:
    """Helper to create rows with attribute access."""
    return SimpleNamespace(**kwargs)


def test_load_gcp_inventory_parses_metadata(monkeypatch: pytest.MonkeyPatch):
    """The inventory loader should parse metadata JSON and surface counts."""

    objects = [
        _row(
            object_id="OBJ1",
            name="users_table",
            object_type="TABLE",
            priority="UNREVIEWED",
            is_decommission=False,
            status="active",
            metadata_json='{"owner": "analytics", "last_reviewed": "2024-12-01"}',
        ),
        _row(
            object_id="OBJ2",
            name="orders_view",
            object_type="VIEW",
            priority="UNREVIEWED",
            is_decommission=False,
            status="active",
            metadata_json="",
        ),
    ]

    client = _install_fake_client(monkeypatch, objects)
    result = inventory_tools.load_gcp_inventory("demo-project", "minietl")

    assert result["status"] == "success"
    assert result["total_objects"] == 2
    assert result["objects"][0]["metadata"]["owner"] == "analytics"
    assert isinstance(datetime.fromisoformat(result["loaded_at"]), datetime)
    assert client.pending == 0


def test_get_unreviewed_objects_returns_dependency_counts(monkeypatch: pytest.MonkeyPatch):
    """Unreviewed objects should surface upstream and downstream dependency totals."""

    rows = [
        _row(
            object_id="OBJ1",
            name="users_table",
            object_type="TABLE",
            downstream_count=3,
            upstream_count=1,
        ),
        _row(
            object_id="OBJ2",
            name="orders_view",
            object_type="VIEW",
            downstream_count=0,
            upstream_count=2,
        ),
    ]

    client = _install_fake_client(monkeypatch, rows)
    result = inventory_tools.get_unreviewed_objects("demo-project", "minietl")

    assert result["status"] == "success"
    assert result["unreviewed_count"] == 2
    assert result["objects"][0]["downstream_dependencies"] == 3
    assert result["objects"][1]["upstream_dependencies"] == 2
    assert client.pending == 0


def test_get_priority_summary_aggregates_counts(monkeypatch: pytest.MonkeyPatch):
    """Priority summary should combine counts and expose total object volume."""

    summary_rows = [
        _row(priority="CRITICAL", count=2, object_types=1),
        _row(priority="UNREVIEWED", count=3, object_types=2),
    ]

    client = _install_fake_client(monkeypatch, summary_rows)
    result = inventory_tools.get_priority_summary("demo-project", "minietl")

    assert result["status"] == "success"
    assert result["total_objects"] == 5
    assert result["by_priority"]["CRITICAL"]["count"] == 2
    assert result["by_priority"]["UNREVIEWED"]["object_types"] == 2
    assert client.pending == 0


def test_find_objects_by_pattern_limits_results(monkeypatch: pytest.MonkeyPatch):
    """Pattern matching should include matching rows and track metadata."""

    pattern_rows = [
        _row(object_id="OBJ1", name="users_table", object_type="TABLE"),
        _row(object_id="OBJ2", name="users_transform", object_type="FUNCTION"),
    ]

    client = _install_fake_client(monkeypatch, pattern_rows)
    result = inventory_tools.find_objects_by_pattern("demo-project", "user", "minietl")

    assert result["status"] == "success"
    assert result["matches"] == 2
    assert result["objects"][0]["priority"] == "UNREVIEWED"
    assert not result["objects"][0]["is_decommission"]
    assert client.pending == 0


def test_analyze_object_dependencies_lists_upstream_and_downstream(monkeypatch: pytest.MonkeyPatch):
    """Dependency analysis should capture upstream and downstream edges."""

    obj_details = [_row(name="orders_view", object_type="VIEW")]
    upstream_rows = [
        _row(
            object_id="OBJ_UP_1",
            name="raw_orders",
            object_type="TABLE",
            edge_type="writes_to",
            priority="HIGH",
        )
    ]
    downstream_rows = [
        _row(
            object_id="OBJ_DOWN_1",
            name="orders_dashboard",
            object_type="DASHBOARD",
            edge_type="reads_from",
            priority="MEDIUM",
        )
    ]

    client = _install_fake_client(monkeypatch, obj_details, upstream_rows, downstream_rows)
    result = inventory_tools.analyze_object_dependencies("demo-project", "OBJ_MAIN", "minietl")

    assert result["status"] == "success"
    assert result["object_name"] == "orders_view"
    assert result["upstream_count"] == 1
    assert result["downstream"][0]["edge_type"] == "reads_from"
    assert client.pending == 0


def test_find_critical_dependency_chains_filters_zero_dependency_objects(monkeypatch: pytest.MonkeyPatch):
    """Critical dependency finder should ignore objects with no downstream usage."""

    critical_rows = [
        _row(
            object_id="OBJ1",
            name="orders_view",
            object_type="VIEW",
            priority="HIGH",
            downstream_count=6,
        ),
        _row(
            object_id="OBJ2",
            name="staging_table",
            object_type="TABLE",
            priority="UNREVIEWED",
            downstream_count=0,
        ),
        _row(
            object_id="OBJ3",
            name="inventory_feed",
            object_type="FUNCTION",
            priority="MEDIUM",
            downstream_count=2,
        ),
    ]

    client = _install_fake_client(monkeypatch, critical_rows)
    result = inventory_tools.find_critical_dependency_chains("demo-project", "minietl")

    assert result["status"] == "success"
    assert result["critical_objects"] == 2  # objects with downstream_count > 0
    impacts = {obj["impact"] for obj in result["objects"]}
    assert impacts == {"CRITICAL", "HIGH"}
    assert client.pending == 0

