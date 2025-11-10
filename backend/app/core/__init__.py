"""Core utilities for application setup."""

# Handle both relative and absolute imports for Cloud Run compatibility
try:
    from .config import AppSettings
except ImportError:
    from app.core.config import AppSettings

__all__ = ["AppSettings"]

