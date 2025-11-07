"""API contract tests for the ADK architect workflow routes."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from backend.agents.models_adk import ArchitectWorkflowResponse, InventorySummary
from backend.app import AppSettings, create_app
from backend.syncflow_server import SyncFlowApp


def _stub_legacy_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace BigQuery-dependent setup in SyncFlowApp with lightweight fakes."""

    def _fake_initialize(self: SyncFlowApp) -> None:
        self.bq_manager = SimpleNamespace(
            project_id=self.project_id,
            dataset_id=self.dataset_id,
            client=None,
            credentials=None,
        )
        self.storage = SimpleNamespace(
            list_objects=lambda: [],
            get_object=lambda object_id: {},
            get_object_history=lambda object_id: [],
        )
        self.logs_explorer = None
        self.analyzer = SimpleNamespace(
            doc_agent_analysis=lambda object_id: {"object_id": object_id},
            log_agent_analysis=lambda object_id, days: {"object_id": object_id, "days": days},
            cloud_fn_agent_analysis=lambda object_id, days: {"object_id": object_id, "days": days},
        )
        self.billing_extractor = None
        self.architect_agent = SimpleNamespace(
            review_object=lambda **kwargs: {"status": "success", **kwargs},
            get_priority_summary=lambda: [],
            get_decommission_candidates=lambda: [],
            get_critical_objects=lambda: [],
        )

    monkeypatch.setattr(SyncFlowApp, "_initialize_components", _fake_initialize)


def test_start_adk_architect_workflow_returns_serialised_response(monkeypatch: pytest.MonkeyPatch):
    """POST /api/architect/workflows should proxy the ADK workflow helper."""
    _stub_legacy_components(monkeypatch)

    workflow_response = ArchitectWorkflowResponse(
        workflow_id="WF_TEST",
        status="COMPLETED",
        inventory_summary=InventorySummary(
            total_objects=5,
            objects_by_type={"TABLE": 3, "VIEW": 2},
            objects_by_priority={"UNREVIEWED": 3, "CRITICAL": 1},
            unreviewed_count=3,
            critical_count=1,
            decommission_candidates=0,
            collected_at=datetime.utcnow(),
        ),
        proposals=[],
        reviews_collected=0,
        completed_at=datetime.utcnow(),
        duration_seconds=12.5,
    )

    def _fake_start(**kwargs: Any) -> ArchitectWorkflowResponse:
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["dataset_id"] == "demo_dataset"
        assert kwargs["workflow_id"] == "WF_TEST"
        return workflow_response

    monkeypatch.setattr("backend.syncflow_server.start_architect_review", _fake_start)

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().post(
        "/api/architect/workflows",
        json={"workflow_id": "WF_TEST", "focus_priority": "critical"},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["workflow_id"] == "WF_TEST"
    assert payload["status"] == "COMPLETED"
    assert payload["inventory_summary"]["total_objects"] == 5


def test_apply_adk_architect_decision_calls_workflow(monkeypatch: pytest.MonkeyPatch):
    """POST /api/architect/workflows/<object_id>/decision should apply updates."""
    _stub_legacy_components(monkeypatch)

    class _FakeWorkflow:
        def apply_architect_decision(self, object_id: str, priority, architect_name: str, notes: str) -> Dict[str, Any]:
            assert object_id == "OBJ123"
            assert priority.value == "CRITICAL"
            assert architect_name == "Dana"
            assert notes == "promote to critical"
            return {
                "status": "success",
                "object_id": object_id,
                "priority": priority.value,
                "architect_name": architect_name,
                "notes": notes,
            }

    monkeypatch.setattr(SyncFlowApp, "_create_adk_workflow", lambda self: _FakeWorkflow())

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().post(
        "/api/architect/workflows/OBJ123/decision",
        json={"priority": "critical", "architect_name": "Dana", "notes": "promote to critical"},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "success"
    assert payload["priority"] == "CRITICAL"


def test_apply_adk_architect_decision_decommission(monkeypatch: pytest.MonkeyPatch):
    """Decommission actions should route to the workflow decommission helper."""
    _stub_legacy_components(monkeypatch)

    class _FakeWorkflow:
        def mark_object_for_decommission(self, object_id: str, reason: str, replacement_id: str | None, architect_name: str):
            assert object_id == "OBJ004"
            assert reason == "Legacy pipeline"
            assert replacement_id is None
            assert architect_name == "Ava"
            return {
                "status": "success",
                "object_id": object_id,
                "decommission_reason": reason,
            }

    monkeypatch.setattr(SyncFlowApp, "_create_adk_workflow", lambda self: _FakeWorkflow())

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().post(
        "/api/architect/workflows/OBJ004/decision",
        json={
            "action": "decommission",
            "architect_name": "Ava",
            "decommission_reason": "Legacy pipeline",
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "success"
    assert payload["decommission_reason"] == "Legacy pipeline"


def test_generate_architect_diagram_endpoint(monkeypatch: pytest.MonkeyPatch):
    """Diagram endpoint should return the workflow's mermaid payload."""
    _stub_legacy_components(monkeypatch)

    class _FakeWorkflow:
        def generate_mermaid_diagram(self, object_id: str, include_scope: str, store: bool, diagram_name: str | None):
            assert object_id == "OBJ005"
            assert include_scope == "both"
            assert not store
            assert diagram_name == "demo-diagram"
            return {
                "status": "success",
                "object_id": object_id,
                "diagram_format": "mermaid",
                "diagram_text": "flowchart TD",
            }

    monkeypatch.setattr(SyncFlowApp, "_create_adk_workflow", lambda self: _FakeWorkflow())

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().post(
        "/api/architect/diagrams/OBJ005",
        json={"diagram_name": "demo-diagram"},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["diagram_format"] == "mermaid"
    assert payload["diagram_text"].startswith("flowchart TD")


def test_store_custom_architect_diagram(monkeypatch: pytest.MonkeyPatch):
    """Custom diagram endpoint should store mermaid text as-is."""
    _stub_legacy_components(monkeypatch)

    class _FakeWorkflow:
        def store_custom_diagram(self, object_id: str, diagram_text: str, diagram_format: str, diagram_name: str | None, activate: bool):
            assert object_id == "OBJ900"
            assert diagram_format == "mermaid"
            assert "OBJ900 --> OBJ901" in diagram_text
            assert diagram_name == "Demo Path"
            assert activate is True
            return {
                "status": "success",
                "diagram_id": "DIAG_TEST",
                "object_id": object_id,
                "diagram_format": diagram_format,
            }

    monkeypatch.setattr(SyncFlowApp, "_create_adk_workflow", lambda self: _FakeWorkflow())

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().post(
        "/api/architect/diagrams/OBJ900/custom",
        json={"diagram_text": "flowchart TD\nOBJ900 --> OBJ901", "diagram_name": "Demo Path", "activate": True},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "success"
    assert payload["diagram_format"] == "mermaid"


def test_get_latest_architect_diagram(monkeypatch: pytest.MonkeyPatch):
    """GET diagram endpoint should surface latest active diagram."""
    _stub_legacy_components(monkeypatch)

    class _FakeWorkflow:
        def get_latest_diagram(self, object_id: str) -> Dict[str, Any]:
            assert object_id == "OBJ777"
            return {
                "status": "success",
                "diagram": {
                    "diagram_id": "DIAG_ACTIVE",
                    "object_id": object_id,
                    "diagram_name": "Critical Chain",
                    "diagram_format": "mermaid",
                    "diagram_text": "flowchart TD\nOBJ777 --> OBJ778",
                    "is_active": True,
                    "generated_at": "2025-11-02T00:00:00Z",
                },
            }

    monkeypatch.setattr(SyncFlowApp, "_create_adk_workflow", lambda self: _FakeWorkflow())

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().get("/api/architect/diagrams/OBJ777")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["diagram"]["diagram_id"] == "DIAG_ACTIVE"


def test_get_architect_diagram_history(monkeypatch: pytest.MonkeyPatch):
    """History endpoint should return ordered diagrams."""
    _stub_legacy_components(monkeypatch)

    class _FakeWorkflow:
        def list_diagram_history(self, object_id: str, limit: int):
            assert object_id == "OBJ888"
            assert limit == 5
            return {
                "status": "success",
                "diagrams": [
                    {
                        "diagram_id": "DIAG_NEW",
                        "generated_at": "2025-11-02T01:00:00Z",
                        "is_active": True,
                    },
                    {
                        "diagram_id": "DIAG_OLD",
                        "generated_at": "2025-11-01T23:00:00Z",
                        "is_active": False,
                    },
                ],
            }

    monkeypatch.setattr(SyncFlowApp, "_create_adk_workflow", lambda self: _FakeWorkflow())

    app = create_app(AppSettings(project_id="demo-project", dataset_id="demo_dataset"))
    resp = app.test_client().get("/api/architect/diagrams/OBJ888/history?limit=5")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert len(payload["diagrams"]) == 2
    assert payload["diagrams"][0]["diagram_id"] == "DIAG_NEW"
