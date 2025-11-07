"""Tests for the BigQuery storage adapter."""

import pytest

from backend.app.storage.bigquery import BigQueryStorage, NotFoundError
from backend.tests.fakes import FakeBigQueryClient


def make_storage(rows_by_sql):
    client = FakeBigQueryClient(rows_by_sql)

    class DummyManager:
        project_id = "demo-project"
        dataset_id = "demo_dataset"

        def __init__(self, client):
            self.client = client

    manager = DummyManager(client)
    return BigQueryStorage(manager), client


def test_list_objects(fake_bigquery_client):
    storage, _ = make_storage({
        "SELECT * FROM `demo-project.demo_dataset.etlobjectscd2_enriched` "
        "WHERE effective_end IS NULL ORDER BY object_id": [
            {
                "object_id": "OBJ0001",
                "object_type": "FUNCTION",
                "name": "foo",
                "status": "active",
                "version": 1,
                "effective_start": None,
                "effective_end": None,
                "priority": "HIGH",
            }
        ]
    })

    objects = storage.list_objects()

    assert objects[0]["object_id"] == "OBJ0001"


def test_get_object_returns_single_row():
    storage, client = make_storage({
        "SELECT * FROM `demo-project.demo_dataset.etlobjectscd2_enriched` WHERE object_id = @object_id AND effective_end IS NULL": [
            {"object_id": "OBJ0010", "name": "orders.pipeline"}
        ]
    })

    obj = storage.get_object("OBJ0010")

    assert obj["object_id"] == "OBJ0010"
    assert client.executed_queries[0][0].startswith("SELECT * FROM")


def test_get_object_missing_raises():
    storage, _ = make_storage({
        "SELECT * FROM `demo-project.demo_dataset.etlobjectscd2_enriched` WHERE object_id = @object_id AND effective_end IS NULL": []
    })

    with pytest.raises(NotFoundError):
        storage.get_object("OBJ9999")


def test_get_object_history_orders_desc():
    storage, _ = make_storage({
        "SELECT * FROM `demo-project.demo_dataset.etlobjectscd2` WHERE object_id = @object_id ORDER BY effective_start DESC": [
            {"version": 2},
            {"version": 1},
        ]
    })

    history = storage.get_object_history("OBJ0010")

    assert [row["version"] for row in history] == [2, 1]
