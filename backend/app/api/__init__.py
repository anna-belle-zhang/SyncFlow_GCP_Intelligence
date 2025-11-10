"""API blueprint registration."""

from __future__ import annotations

from flask import Flask

# Handle both relative and absolute imports for Cloud Run compatibility
try:
    from .health import bp as health_blueprint
    from .objects import bp as objects_blueprint
except ImportError:
    from app.api.health import bp as health_blueprint
    from app.api.objects import bp as objects_blueprint


def register_blueprints(app: Flask) -> None:
    """Attach API blueprints to the Flask app."""
    app.register_blueprint(health_blueprint)
    app.register_blueprint(objects_blueprint)


__all__ = ["register_blueprints"]
