"""Minimal orchestrator stub to coordinate agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


class OrchestrationError(RuntimeError):
    """Raised when orchestrator execution fails."""


@dataclass
class AgentExecutionResult:
    agent: str
    payload: Any
    error: Optional[str] = None


AgentCallable = Callable[[str, Mapping[str, Any]], Any]


@dataclass
class AgentOrchestrator:
    """Simple fan-out/fan-in orchestrator used for smoke tests."""

    registry: Dict[str, AgentCallable] = field(default_factory=dict)

    def register(self, name: str, handler: AgentCallable) -> None:
        self.registry[name] = handler

    def available_agents(self) -> List[str]:
        return sorted(self.registry.keys())

    def run(self, object_id: str, agents: Optional[Iterable[str]] = None, **kwargs) -> List[AgentExecutionResult]:
        if not self.registry:
            raise OrchestrationError("No agents registered")

        selected = list(agents) if agents is not None else self.available_agents()
        results: List[AgentExecutionResult] = []

        for name in selected:
            handler = self.registry.get(name)
            if handler is None:
                results.append(AgentExecutionResult(agent=name, payload=None, error="agent_not_registered"))
                continue
            try:
                payload = handler(object_id, kwargs)
                results.append(AgentExecutionResult(agent=name, payload=payload))
            except Exception as exc:  # pragma: no cover - thin wrapper
                results.append(AgentExecutionResult(agent=name, payload=None, error=str(exc)))

        return results


__all__ = ["AgentOrchestrator", "AgentExecutionResult", "OrchestrationError"]

