"""Unit tests for the OBJ_ID assignment helpers."""

from backend.models import EdgeType, ObjectType
from backend.object_assigner import ObjectIDAssigner


def test_assign_all_generates_incrementing_ids(make_etl_object):
    assigner = ObjectIDAssigner(start_id=1)
    objects = [
        make_etl_object("orders.etl.load", ObjectType.DATAFLOW),
        make_etl_object("orders.table.daily", ObjectType.BQTABLE),
    ]

    assigned = assigner.assign_all(objects)
    assigned_ids = [obj.object_id for obj in assigned]

    assert assigned_ids == ["OBJ0001", "OBJ0002"]
    assert len(set(assigned_ids)) == len(assigned)


def test_assign_existing_object_reuses_id(make_etl_object):
    assigner = ObjectIDAssigner(start_id=42)
    obj = make_etl_object("users.pipeline.extract", ObjectType.FUNCTION)

    first_id, _ = assigner.assign_object(obj)
    second_id, updated = assigner.assign_object(obj)

    assert first_id == "OBJ0042"
    assert second_id == "OBJ0042"
    assert updated.object_id == "OBJ0042"
    assert assigner.next_id == 43  # counter increments only once


def test_assign_same_name_different_types(make_etl_object):
    """Objects with the same name but different types get distinct IDs."""
    assigner = ObjectIDAssigner(start_id=1)

    trigger = make_etl_object("shared-resource", ObjectType.TRIGGER)
    function = make_etl_object("shared-resource", ObjectType.FUNCTION)

    trigger_id, _ = assigner.assign_object(trigger)
    function_id, _ = assigner.assign_object(function)

    assert trigger_id == "OBJ0001"
    assert function_id == "OBJ0002"
    assert trigger_id != function_id


def test_assign_edges_maps_names_to_ids(make_etl_object, make_edge):
    assigner = ObjectIDAssigner(start_id=10)
    parent = make_etl_object("dataset.orders", ObjectType.BQDATASET)
    child = make_etl_object("dataset.orders.fact_sales", ObjectType.BQTABLE)

    objects = assigner.assign_all([parent, child])
    edge = make_edge(parent.name, child.name, EdgeType.CONTAINS)

    assigned_edges = assigner.assign_edges(objects, [edge])

    assert len(assigned_edges) == 1
    assigned_edge = assigned_edges[0]
    assert assigned_edge.source_object_id == "OBJ0010"
    assert assigned_edge.target_object_id == "OBJ0011"
    assert assigned_edge.edge_type == EdgeType.CONTAINS
