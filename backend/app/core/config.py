"""Configuration helpers for the SyncFlow backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AppSettings:
    """Strongly-typed view over environment configuration."""

    project_id: str = "prismatic-smoke-463810-c1"
    dataset_id: str = "minietl"
    service_account_path: Optional[str] = None
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AppSettings":
        source = env or os.environ
        settings = cls(
            project_id=source.get("GCP_PROJECT", cls.project_id),
            dataset_id=source.get("BQ_DATASET", cls.dataset_id),
            service_account_path=source.get("GOOGLE_APPLICATION_CREDENTIALS"),
            host=source.get("HOST", cls.host),
            port=int(source.get("PORT", cls.port)),
            debug=_env_bool(source.get("DEBUG"), cls.debug),
        )

        # Capture any namespaced extras for future use (SYNCFLOW_* vars).
        settings.extra = {
            key: value for key, value in source.items() if key.startswith("SYNCFLOW_")
        }
        return settings

    def to_flask_config(self) -> Dict[str, Any]:
        """Translate settings into keys conventional for Flask apps."""
        return {
            "PROJECT_ID": self.project_id,
            "DATASET_ID": self.dataset_id,
            "SERVICE_ACCOUNT_PATH": self.service_account_path,
            "SERVER_HOST": self.host,
            "SERVER_PORT": self.port,
            "DEBUG": self.debug,
            **{key: value for key, value in self.extra.items()},
        }

