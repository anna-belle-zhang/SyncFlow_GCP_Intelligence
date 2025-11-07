"""Tests for the minimalist agent orchestrator."""

from backend.app.orchestration.orchestrator import AgentOrchestrator, OrchestrationError


def test_orchestrator_runs_registered_agents():
    calls = []

    def agent_a(object_id, ctx):
        calls.append(("a", object_id))
        return {"object_id": object_id, "agent": "a"}

    def agent_b(object_id, ctx):
        return {"object_id": object_id, "agent": "b"}

    orchestrator = AgentOrchestrator()
    orchestrator.register("doc", agent_a)
    orchestrator.register("log", agent_b)

    results = orchestrator.run("OBJ0010")

    assert [r.agent for r in results] == ["doc", "log"]
    assert results[0].payload["agent"] == "a"
    assert calls == [("a", "OBJ0010")]


def test_orchestrator_handles_missing_agent():
    orchestrator = AgentOrchestrator()
    orchestrator.register("doc", lambda object_id, ctx: {})

    results = orchestrator.run("OBJ0010", agents=["doc", "log"])

    assert results[1].error == "agent_not_registered"


def test_orchestrator_without_agents_raises():
    orchestrator = AgentOrchestrator()

    try:
        orchestrator.run("OBJ0010")
    except OrchestrationError as exc:
        assert "No agents" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected OrchestrationError")

