"""Object listing endpoints backed by the new storage layer."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

bp = Blueprint("objects_v2", __name__, url_prefix="/api/v2")


def _get_storage():
    storage = current_app.extensions.get("storage")
    if storage is None:
        raise RuntimeError("Storage layer not configured")
    return storage


@bp.route("/objects", methods=["GET"])
def list_objects_v2():
    storage = _get_storage()
    objects = storage.list_objects()
    return jsonify({"total": len(objects), "objects": objects})

