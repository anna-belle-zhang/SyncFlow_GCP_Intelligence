"""API blueprint registration."""

from __future__ import annotations

from flask import Flask

from .health import bp as health_blueprint
from .objects import bp as objects_blueprint


def register_blueprints(app: Flask) -> None:
    """Attach API blueprints to the Flask app."""
    app.register_blueprint(health_blueprint)
    app.register_blueprint(objects_blueprint)


__all__ = ["register_blueprints"]
