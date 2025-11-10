"""Unit tests for the architect command parser used in the dashboard chat box."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import (
    parse_architect_commands,
    build_mermaid_from_path,
    merge_mermaid_diagrams,
)  # noqa: E402


def test_parse_priority_commands():
    commands = parse_architect_commands("obj001 obj002 critical - promote")
    assert len(commands) == 1
    command = commands[0]
    assert command["priority"] == "CRITICAL"
    assert command["action"] is None
    assert command["object_ids"] == ["OBJ001", "OBJ002"]
    assert "promote" in command["notes"]


def test_parse_decommission_commands():
    commands = parse_architect_commands("OBJ003 decom legacy workload")
    assert len(commands) == 1
    command = commands[0]
    assert command["action"] == "decommission"
    assert command["priority"] is None
    assert command["object_ids"] == ["OBJ003"]
    assert "legacy" in command["reason"]


def test_parse_multiple_segments():
    text = "OBJ001 high; OBJ002 decom; OBJ003 low follow up"
    commands = parse_architect_commands(text)
    assert len(commands) == 3
    assert commands[0]["priority"] == "HIGH"
    assert commands[1]["action"] == "decommission"
    assert commands[2]["priority"] == "LOW"


def test_parse_digits_without_prefix():
    commands = parse_architect_commands("obj001 002 007 critical.")
    assert len(commands) == 1
    command = commands[0]
    assert command["object_ids"] == ["OBJ001", "OBJ002", "OBJ007"]
    assert command["priority"] == "CRITICAL"
    assert command["notes"] == ""


def test_build_mermaid_from_path():
    diagram = build_mermaid_from_path("obj001 -> obj002 -> obj007")
    assert diagram is not None
    assert "flowchart TD" in diagram
    assert "OBJ0001" in diagram
    assert "OBJ0001 --> OBJ0002" in diagram


def test_merge_mermaid_diagrams_appends_without_overwrite():
    base = """flowchart TD
OBJ0002["OBJ0002"]
OBJ0004["OBJ0004"]
OBJ0020["OBJ0020"]
OBJ0002 --> OBJ0004
"""
    addition = """flowchart TD
OBJ0020["OBJ0020"]
OBJ0022["OBJ0022"]
OBJ0020 --> OBJ0022
"""
    merged = merge_mermaid_diagrams(base, addition)
    assert merged.startswith("flowchart TD")
    assert merged.count('OBJ0020["OBJ0020"]') == 1
    assert "OBJ0002 --> OBJ0004" in merged
    assert "OBJ0020 --> OBJ0022" in merged
    assert 'OBJ0022["OBJ0022"]' in merged


def test_build_mermaid_from_path_handles_after_instructions():
    diagram = build_mermaid_from_path("add 0021 after 0008")
    assert diagram is not None
    assert "OBJ0008" in diagram
    assert "OBJ0021" in diagram
    assert "OBJ0008 -->" in diagram


def test_merge_mermaid_diagrams_normalizes_zero_prefix_ids():
    base = """flowchart TD
0BJ0020["0BJ0020\\nlegacy"]
OBJ0004["OBJ0004"]
OBJ0004 --> 0BJ0020
"""
    addition = """flowchart TD
OBJ0020["OBJ0020"]
OBJ0021["OBJ0021"]
OBJ0020 --> OBJ0021
"""
    merged = merge_mermaid_diagrams(base, addition)
    assert merged.count('OBJ0020["') == 1
    assert 'OBJ0004 --> OBJ0020' in merged
    assert '0BJ0020 -->' not in merged
    assert 'OBJ0020 --> OBJ0021' in merged
