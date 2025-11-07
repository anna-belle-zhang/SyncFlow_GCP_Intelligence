"""Tests for helper fakes used by the backend test suite."""

from backend.tests.fakes import FakeLogEntry


def test_fake_bigquery_client_records_queries(fake_bigquery_client):
    sql = "SELECT * FROM dataset.table LIMIT 1"
    fake_bigquery_client.register_query_result(sql, [{"value": 123}])

    job = fake_bigquery_client.query(sql)

    assert fake_bigquery_client.executed_queries == [(sql, None)]
    assert list(job) == [{"value": 123}]
    assert job.result() == [{"value": 123}]


def test_fake_bigquery_client_tracks_inserts(fake_bigquery_client):
    rows = [{"id": "OBJ0001"}, {"id": "OBJ0002"}]

    errors = fake_bigquery_client.insert_rows_json("dataset.table", rows)

    assert errors == []
    assert fake_bigquery_client.insert_calls["dataset.table"] == rows


def test_fake_logs_service_filters_by_object(fake_logs_service, fake_log_entry_factory):
    fake_logs_service.entries = [
        fake_log_entry_factory("OBJ0001", message="ok"),
        fake_log_entry_factory("OBJ0002", message="warn", severity="WARNING"),
        fake_log_entry_factory("OBJ0001", message="failed", severity="ERROR"),
    ]

    results = fake_logs_service.query(object_id="OBJ0001")

    assert len(results) == 2
    assert all(entry.object_id == "OBJ0001" for entry in results)
    assert fake_logs_service.requests[-1] == {"object_id": "OBJ0001", "severity": None}


def test_fake_billing_service_lookup(fake_billing_service):
    fake_billing_service.register_costs("OBJ0001", [{"date": "2025-10-30", "cost": 1.23}])

    costs = fake_billing_service.get_costs("OBJ0001", days=7)

    assert costs == [{"date": "2025-10-30", "cost": 1.23}]
    assert fake_billing_service.lookup_requests[-1] == {"object_id": "OBJ0001", "days": 7}
