"""API tests for the v2 objects endpoint."""

from backend.app import AppSettings, create_app
from backend.app.storage.bigquery import BigQueryStorage
from backend.tests.fakes import FakeBigQueryClient


class ManagerStub:
    def __init__(self, client):
        self.client = client
        self.project_id = "demo-project"
        self.dataset_id = "demo_dataset"


def test_objects_v2_returns_payload():
    rows = {
        "SELECT * FROM `demo-project.demo_dataset.etlobjectscd2_enriched` "
        "WHERE effective_end IS NULL ORDER BY object_id": [
            {
                "object_id": "OBJ0001",
                "object_type": "FUNCTION",
                "name": "demo",
                "status": "active",
                "version": 1,
                "effective_start": None,
                "effective_end": None,
                "priority": "HIGH",
                "architect_notes": "note",
                "architect_review_timestamp": None,
                "architect_reviewed_by": "alex",
                "is_decommission": False,
                "decommission_reason": None,
                "priority_updated_by": "alex",
                "priority_updated_at": None,
            }
        ]
    }
    client = FakeBigQueryClient(rows)
    storage = BigQueryStorage(ManagerStub(client))

    app = create_app(
        AppSettings(project_id="demo-project", dataset_id="demo_dataset"),
        include_legacy_routes=False,
        storage=storage,
    )

    resp = app.test_client().get("/api/v2/objects")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["total"] == 1
    assert payload["objects"][0]["object_id"] == "OBJ0001"
