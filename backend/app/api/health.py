"""Health and readiness endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)


@bp.route("/health", methods=["GET"])
def health():
    """Return basic service metadata for readiness probes."""
    cfg = current_app.config
    return jsonify(
        {
            "status": "ok",
            "project": cfg.get("PROJECT_ID"),
            "dataset": cfg.get("DATASET_ID"),
        }
    )

