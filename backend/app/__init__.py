"""Application factory and package initialisation for the backend service."""

from __future__ import annotations

from flask import Flask

from .api import register_blueprints
from .core.config import AppSettings


def create_app(
    settings: AppSettings | None = None,
    *,
    include_legacy_routes: bool = True,
    storage=None,
) -> Flask:
    """Create and configure the Flask application instance."""
    app_settings = settings or AppSettings.from_env()

    app = Flask("syncflow_backend")
    app.config.update(app_settings.to_flask_config())

    storage_instance = storage
    if include_legacy_routes:
        # Register existing routes and services until the refactor replaces them.
        try:
            from backend.syncflow_server import SyncFlowApp
        except ImportError:
            # Try relative import for running from backend directory
            from ..syncflow_server import SyncFlowApp
        from .storage.bigquery import BigQueryStorage

        legacy_app = SyncFlowApp(settings=app_settings, app=app)
        app.extensions["legacy_app"] = legacy_app
        if storage_instance is None:
            storage_instance = BigQueryStorage(legacy_app.bq_manager)

    register_blueprints(app)

    # Surface settings for downstream consumers (tests, blueprints, etc.)
    app.extensions["settings"] = app_settings
    if storage_instance is not None:
        app.extensions["storage"] = storage_instance
    return app


__all__ = ["create_app", "AppSettings"]
