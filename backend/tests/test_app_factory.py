"""Smoke tests for the Flask application factory."""

from backend.app import AppSettings, create_app


def test_create_app_uses_settings(fake_bigquery_client):
    app = create_app(
        AppSettings(
            project_id="demo-project",
            dataset_id="demo_dataset",
            service_account_path="/tmp/sa.json",
            host="0.0.0.0",
            port=8080,
            debug=True,
        ),
        include_legacy_routes=False,
    )

    assert app.config["PROJECT_ID"] == "demo-project"
    assert app.config["DATASET_ID"] == "demo_dataset"
    assert app.extensions["settings"].service_account_path == "/tmp/sa.json"


def test_health_endpoint_reports_status():
    app = create_app(
        AppSettings(
            project_id="demo-project",
            dataset_id="demo_dataset",
        ),
        include_legacy_routes=False,
    )

    client = app.test_client()
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {
        "status": "ok",
        "project": "demo-project",
        "dataset": "demo_dataset",
    }
