"""Agentic workflow smoke tests for the architect agent."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:  # pragma: no cover - exercised only in test harness when google SDK missing
    from google.cloud import bigquery  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback stub for local tests
    bigquery = types.SimpleNamespace()

    class QueryJobConfig:
        def __init__(self):
            self.query_parameters = None

    class ScalarQueryParameter:
        def __init__(self, name: str, type_: str, value: Any):
            self.name = name
            self.type_ = type_
            self.value = value

    class ArrayQueryParameter:
        def __init__(self, name: str, array_type: str, values: List[Any]):
            self.name = name
            self.array_type = array_type
            self.values = values

    bigquery.QueryJobConfig = QueryJobConfig
    bigquery.ScalarQueryParameter = ScalarQueryParameter
    bigquery.ArrayQueryParameter = ArrayQueryParameter

    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    setattr(cloud_mod, "bigquery", bigquery)
    setattr(google_mod, "cloud", cloud_mod)
    sys.modules["google"] = google_mod
    sys.modules["google.cloud"] = cloud_mod
    sys.modules["google.cloud.bigquery"] = bigquery

from backend.architect_agent import ArchitectAgent
from backend.tests.fakes import FakeQueryJob


class InMemoryBigQueryClient:
    """Simple in-memory stand-in for the BigQuery client."""

    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self.tables = tables
        self.executed_queries: List[str] = []

    def query(self, sql: str, job_config: Any | None = None):
        """Dispatch known queries to their handlers."""
        self.executed_queries.append(sql)

        if "-- load_inventory_summary" in sql:
            return FakeQueryJob(self._load_inventory_summary())
        if "-- load_inventory_unreviewed" in sql:
            return FakeQueryJob(self._load_inventory_unreviewed())
        if "-- critical_high_inventory" in sql:
            return FakeQueryJob(self._critical_high_inventory())
        if "-- unreviewed_objects" in sql:
            return FakeQueryJob(self._load_unreviewed_objects())
        if "-- execution_stats" in sql:
            return FakeQueryJob(self._execution_stats(job_config))
        if "-- cost_stats" in sql:
            return FakeQueryJob(self._cost_stats(job_config))
        if "-- dependency_stats" in sql:
            return FakeQueryJob(self._dependency_stats(job_config))
        if "-- fetch_current_object" in sql:
            return FakeQueryJob(self._fetch_current_object(job_config))
        if "-- insert_new_version" in sql:
            self._insert_new_version(job_config)
            return FakeQueryJob([])
        if "-- expire_previous_version" in sql:
            self._expire_previous_version(job_config)
            return FakeQueryJob([])

        raise NotImplementedError(f"Unsupported query in test client: {sql}")

    def _active_rows(self) -> List[Dict[str, Any]]:
        """Return snapshot of active SCD2 records."""
        return [
            row for row in self.tables["etlobjectscd2"] if row.get("effective_end") is None
        ]

    def _load_inventory_summary(self) -> List[Dict[str, Any]]:
        counts: Dict[Any, int] = {}
        for row in self._active_rows():
            key = row.get("priority")
            counts[key] = counts.get(key, 0) + 1
        return [{"priority": key, "object_count": value} for key, value in counts.items()]

    def _load_inventory_unreviewed(self) -> List[Dict[str, Any]]:
        rows = [
            {
                "object_id": row["object_id"],
                "name": row["name"],
                "object_type": row["object_type"],
            }
            for row in self._active_rows()
            if not row.get("priority")
        ]
        return rows[:25]

    def _critical_high_inventory(self) -> List[Dict[str, Any]]:
        return [
            {
                "object_id": row["object_id"],
                "name": row["name"],
                "object_type": row["object_type"],
                "priority": row.get("priority"),
            }
            for row in self._active_rows()
            if row.get("priority") in ("CRITICAL", "HIGH")
        ]

    def _load_unreviewed_objects(self) -> List[Dict[str, Any]]:
        return [
            {
                "object_id": row["object_id"],
                "name": row["name"],
                "object_type": row["object_type"],
                "parent_id": row.get("parent_id"),
                "metadata": row.get("metadata", ""),
            }
            for row in self._active_rows()
            if not row.get("priority")
        ]

    def _execution_stats(self, job_config: Any) -> List[Dict[str, Any]]:
        params = self._params(job_config)
        object_ids = params.get("object_ids", [])
        today = date.today()

        rows = []
        for object_id in object_ids:
            entries = [
                entry for entry in self.tables["factlog"] if entry["object_id"] == object_id
            ]
            entries_90 = [
                entry for entry in entries if entry["run_date"] >= today - timedelta(days=90)
            ]
            if not entries_90:
                continue

            entries_30 = [entry for entry in entries_90 if entry["run_date"] >= today - timedelta(days=30)]
            entries_7 = [entry for entry in entries_90 if entry["run_date"] >= today - timedelta(days=7)]

            avg_duration = (
                sum(entry["duration_min"] for entry in entries_90) / len(entries_90)
                if entries_90
                else 0.0
            )
            last_run = max((entry["run_date"] for entry in entries_90), default=None)

            rows.append(
                {
                    "object_id": object_id,
                    "executions_last_90_days": len(entries_90),
                    "executions_last_30_days": len(entries_30),
                    "executions_last_7_days": len(entries_7),
                    "last_run_date": last_run,
                    "avg_duration_min": avg_duration,
                }
            )

        return rows

    def _cost_stats(self, job_config: Any) -> List[Dict[str, Any]]:
        params = self._params(job_config)
        object_ids = params.get("object_ids", [])
        today = date.today()

        rows = []
        for object_id in object_ids:
            entries = [
                entry for entry in self.tables["factbilling"] if entry["object_id"] == object_id
            ]
            entries_30 = [
                entry for entry in entries if entry["run_date"] >= today - timedelta(days=30)
            ]
            if not entries_30:
                continue

            cost_30 = sum(entry["cost_usd"] for entry in entries_30)
            cost_7 = sum(
                entry["cost_usd"]
                for entry in entries_30
                if entry["run_date"] >= today - timedelta(days=7)
            )
            rows.append(
                {
                    "object_id": object_id,
                    "cost_last_30_days": cost_30,
                    "cost_last_7_days": cost_7,
                }
            )
        return rows

    def _dependency_stats(self, job_config: Any) -> List[Dict[str, Any]]:
        params = self._params(job_config)
        object_ids = params.get("object_ids", [])

        rows = []
        for object_id in object_ids:
            deps = [
                edge
                for edge in self.tables["etledges"]
                if edge["source_object_id"] == object_id and edge.get("is_active", False)
            ]
            if not deps:
                continue
            rows.append(
                {
                    "object_id": object_id,
                    "downstream_dependents": len(deps),
                }
            )
        return rows

    def _fetch_current_object(self, job_config: Any) -> List[Dict[str, Any]]:
        params = self._params(job_config)
        object_id = params.get("object_id")
        return [
            {
                key: row.get(key)
                for key in (
                    "version",
                    "effective_start",
                    "object_type",
                    "name",
                    "parent_id",
                    "status",
                    "schedule_time",
                    "metadata",
                )
            }
            for row in self._active_rows()
            if row["object_id"] == object_id
        ]

    def _insert_new_version(self, job_config: Any) -> None:
        params = self._params(job_config)
        new_row = {
            "object_id": params["object_id"],
            "object_type": params["object_type"],
            "name": params["name"],
            "parent_id": params.get("parent_id"),
            "version": params["new_version"],
            "status": params.get("status"),
            "schedule_time": params.get("schedule_time"),
            "metadata": params.get("metadata"),
            "priority": params.get("priority"),
            "is_decommission": params.get("is_decommission", False),
            "decommission_reason": params.get("decommission_reason"),
            "architect_notes": params.get("architect_notes"),
            "architect_review_timestamp": datetime.utcnow(),
            "architect_reviewed_by": params.get("reviewed_by"),
            "architect_approval_id": params.get("proposal_id"),
            "architect_approval_status": params.get("approval_status"),
            "architect_approval_timestamp": datetime.utcnow(),
            "effective_start": date.today(),
            "effective_end": None,
        }
        self.tables["etlobjectscd2"].append(new_row)

    def _expire_previous_version(self, job_config: Any) -> None:
        params = self._params(job_config)
        object_id = params["object_id"]
        effective_start = params["effective_start"]

        for row in self.tables["etlobjectscd2"]:
            if (
                row["object_id"] == object_id
                and row.get("effective_start") == effective_start
                and row.get("effective_end") is None
            ):
                row["effective_end"] = date.today()

    @staticmethod
    def _params(job_config: Any) -> Dict[str, Any]:
        if job_config is None or not getattr(job_config, "query_parameters", None):
            return {}

        params: Dict[str, Any] = {}
        for param in job_config.query_parameters:
            if hasattr(param, "values"):
                params[param.name] = list(param.values)
            else:
                params[param.name] = getattr(param, "value", None)
        return params


class FakeBigQueryManager:
    """Minimal BigQueryManager shim for the agent."""

    def __init__(self, client: InMemoryBigQueryClient):
        self.project_id = "test-project"
        self.dataset_id = "minietl"
        self.client = client


class ArchitectAgentWorkflowTest(unittest.TestCase):
    """End-to-end coverage of the architect agent workflow helpers."""

    def setUp(self):
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)

        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "etlobjectscd2": [
                self._base_object("OBJ_CRITICAL", "Critical Dataflow", "DATAFLOW"),
                self._base_object("OBJ_HIGH", "High Function", "FUNCTION"),
                self._base_object("OBJ_LOW", "Dormant Function", "FUNCTION"),
                {
                    **self._base_object("OBJ_EXIST", "Existing High", "CLOUD_RUN"),
                    "priority": "HIGH",
                },
            ],
            "factlog": [],
            "factbilling": [],
            "etledges": [],
        }

        # Populate execution logs
        for day_offset in range(10):
            run_date = today - timedelta(days=day_offset)
            for _ in range(3):
                self.tables["factlog"].append(
                    {"object_id": "OBJ_CRITICAL", "run_date": run_date, "duration_min": 40}
                )

        for day_offset in range(6):
            run_date = today - timedelta(days=day_offset * 2)
            for _ in range(2):
                self.tables["factlog"].append(
                    {"object_id": "OBJ_HIGH", "run_date": run_date, "duration_min": 25}
                )

        for day_offset in range(4):
            run_date = today - timedelta(days=day_offset * 5)
            self.tables["factlog"].append(
                {"object_id": "OBJ_EXIST", "run_date": run_date, "duration_min": 30}
            )

        # Populate billing entries
        for cost in (400.0, 450.0, 500.0):
            self.tables["factbilling"].append(
                {"object_id": "OBJ_CRITICAL", "run_date": today - timedelta(days=cost % 5), "cost_usd": cost}
            )

        for cost in (60.0, 55.0, 50.0, 45.0):
            self.tables["factbilling"].append(
                {"object_id": "OBJ_HIGH", "run_date": thirty_days_ago + timedelta(days=int(cost)), "cost_usd": cost}
            )

        for cost in (80.0, 70.0):
            self.tables["factbilling"].append(
                {"object_id": "OBJ_EXIST", "run_date": today - timedelta(days=int(cost) % 6), "cost_usd": cost}
            )

        # Populate dependencies
        for idx in range(6):
            self.tables["etledges"].append(
                {
                    "edge_id": f"E_CRIT_{idx}",
                    "source_object_id": "OBJ_CRITICAL",
                    "target_object_id": f"T{idx}",
                    "edge_type": "invokes",
                    "is_active": True,
                }
            )

        for idx in range(2):
            self.tables["etledges"].append(
                {
                    "edge_id": f"E_HIGH_{idx}",
                    "source_object_id": "OBJ_HIGH",
                    "target_object_id": f"H{idx}",
                    "edge_type": "invokes",
                    "is_active": True,
                }
            )

        self.tables["etledges"].append(
            {
                "edge_id": "E_EXIST",
                "source_object_id": "OBJ_EXIST",
                "target_object_id": "T_EXIST",
                "edge_type": "invokes",
                "is_active": True,
            }
        )

        client = InMemoryBigQueryClient(self.tables)
        manager = FakeBigQueryManager(client)
        self.agent = ArchitectAgent(manager)

    def _base_object(self, object_id: str, name: str, object_type: str) -> Dict[str, Any]:
        """Create a baseline SCD2 row."""
        return {
            "object_id": object_id,
            "name": name,
            "object_type": object_type,
            "parent_id": None,
            "priority": None,
            "is_decommission": False,
            "decommission_reason": None,
            "architect_notes": "",
            "architect_review_timestamp": None,
            "architect_reviewed_by": None,
            "architect_approval_id": "",
            "architect_approval_status": "",
            "architect_approval_timestamp": None,
            "status": "active",
            "schedule_time": "",
            "metadata": "",
            "version": 1,
            "effective_start": date(2024, 1, 1),
            "effective_end": None,
        }

    def test_agentic_workflow_end_to_end(self):
        """Load inventory, generate proposals, approve, and verify BigQuery state."""

        inventory = self.agent.load_inventory()
        self.assertEqual(inventory["total_objects"], 4)
        self.assertEqual(inventory["unreviewed_count"], 3)

        proposals = self.agent.propose_priority_changes()
        self.assertEqual(len(proposals), 3)

        proposal_map = {proposal["object_id"]: proposal for proposal in proposals}

        self.assertEqual(proposal_map["OBJ_CRITICAL"]["proposed_priority"], "CRITICAL")
        self.assertEqual(proposal_map["OBJ_HIGH"]["proposed_priority"], "HIGH")
        self.assertTrue(proposal_map["OBJ_LOW"]["decommission_candidate"])

        pending = self.agent.get_pending_approvals()
        self.assertEqual(len(pending), 3)

        approved = self.agent.architect_approves(
            proposal_map["OBJ_CRITICAL"]["proposal_id"], architect_name="Architect A"
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["final_priority"], "CRITICAL")

        crit_versions = [
            row for row in self.tables["etlobjectscd2"] if row["object_id"] == "OBJ_CRITICAL"
        ]
        active_versions = [row for row in crit_versions if row.get("effective_end") is None]
        self.assertEqual(len(active_versions), 1)
        self.assertEqual(active_versions[0]["priority"], "CRITICAL")
        self.assertEqual(active_versions[0]["architect_approval_status"], "approved")
        self.assertEqual(active_versions[0]["architect_approval_id"], approved["proposal_id"])

        modified = self.agent.architect_modifies(
            proposal_map["OBJ_HIGH"]["proposal_id"],
            new_priority="MEDIUM",
            architect_notes="Scope reduced after review.",
            architect_name="Architect B",
        )
        self.assertEqual(modified["status"], "modified")
        self.assertEqual(modified["final_priority"], "MEDIUM")

        high_versions = [
            row for row in self.tables["etlobjectscd2"] if row["object_id"] == "OBJ_HIGH"
        ]
        high_active = [row for row in high_versions if row.get("effective_end") is None]
        self.assertEqual(high_active[0]["priority"], "MEDIUM")
        self.assertEqual(high_active[0]["architect_approval_status"], "modified")

        remaining_pending = self.agent.get_pending_approvals()
        self.assertEqual(len(remaining_pending), 1)
        self.assertEqual(remaining_pending[0]["object_id"], "OBJ_LOW")

        critical_summary = self.agent.get_critical_high_summary()
        self.assertEqual(critical_summary["total_objects"], 2)
        object_ids = {obj["object_id"] for obj in critical_summary["objects"]}
        self.assertEqual(object_ids, {"OBJ_CRITICAL", "OBJ_EXIST"})


if __name__ == "__main__":
    unittest.main()
