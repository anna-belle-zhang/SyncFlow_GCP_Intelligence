"""Storage adapters for backend services."""

# Handle both relative and absolute imports for Cloud Run compatibility
try:
    from .bigquery import BigQueryStorage, StorageError, NotFoundError
except ImportError:
    from app.storage.bigquery import BigQueryStorage, StorageError, NotFoundError

__all__ = ["BigQueryStorage", "StorageError", "NotFoundError"]

