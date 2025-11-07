#!/usr/bin/env python3
"""
SyncFlow GCP Intelligence - Local Frontend Dashboard

Interactive Streamlit dashboard for:
- Viewing ETL objects and lineage
- Running multi-agent analysis
- Monitoring execution logs
- Tracking costs and optimization opportunities
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import pandas as pd
from datetime import datetime, timedelta
import re
import plotly.express as px
import plotly.graph_objects as go
from typing import Any
import os

import uuid

# Page configuration
st.set_page_config(
    page_title="SyncFlow GCP Intelligence",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Styling
st.markdown("""
<style>
    .main-header {
        font-size: 3em;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 10px;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .success { color: #06a84e; font-weight: bold; }
    .warning { color: #ff6b35; font-weight: bold; }
    .error { color: #d62828; font-weight: bold; }
    .info { color: #1f77b4; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


OBJECT_ID_TOKEN = re.compile(r"\bOBJ(\d{1,6})\b", re.IGNORECASE)
BARE_ID_TOKEN = re.compile(r"\b(0\d{2,5})\b")


def normalize_object_id(raw: str | None) -> str | None:
    """Return canonical OBJ identifier (OBJ0001) when possible."""
    if not raw:
        return None
    cleaned = raw.strip().upper()
    if not cleaned:
        return None

    match = re.fullmatch(r"OBJ(\d{1,6})", cleaned)
    if match:
        return f"OBJ{int(match.group(1)):04d}"

    if cleaned.isdigit():
        return f"OBJ{int(cleaned):04d}"

    return None


def extract_object_id_from_text(text: str | None) -> str | None:
    """Parse the first object identifier embedded in free-form input."""
    if not text:
        return None

    token = OBJECT_ID_TOKEN.search(text)
    if token:
        return f"OBJ{int(token.group(1)):04d}"

    fallback = BARE_ID_TOKEN.search(text)
    if fallback:
        return f"OBJ{int(fallback.group(1)):04d}"

    return None


def render_mermaid_diagram(diagram_text: str, title: str = "Diagram"):
    """Render a mermaid diagram with both code and visualization using Mermaid CDN.

    Args:
        diagram_text: The mermaid diagram definition
        title: Optional title for the diagram section
    """
    if not diagram_text:
        return

    try:
        # Replace \n with space in object labels (e.g., OBJ0002\nminietl-daily-extraction -> OBJ0002 minietl-daily-extraction)
        diagram_text_display = diagram_text.replace('\\n', ' ')

        # Show the raw Mermaid code (for users to copy/edit)
        with st.expander("📄 Show Mermaid Code", expanded=False):
            st.code(diagram_text, language="mermaid")

        # Generate unique ID for this diagram
        diagram_id = f"mermaid_{uuid.uuid4().hex[:8]}"

        # Render the visual diagram using Mermaid.js with components.html()
        mermaid_html = f"""
<div class="mermaid">
{diagram_text_display}
</div>

<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script>
    mermaid.initialize({{ startOnLoad: true }});
</script>
"""
        # Use components.html() for proper JavaScript rendering
        components.html(mermaid_html, height=400, scrolling=True)

    except Exception as e:
        st.warning(f"Could not render diagram: {e}")
        st.code(diagram_text, language="mermaid")


def summarize_doc_agent_response(object_id: str, prompt: str | None, payload: dict[str, Any]) -> str:
    """Produce a human-readable response for DocAgent results."""
    lines: list[str] = []
    question = (prompt or "").strip()
    if question:
        lines.append(f"*Question*: {question}")

        referenced_ids = {f"OBJ{int(token):04d}" for token in OBJECT_ID_TOKEN.findall(question)}
        referenced_ids |= {f"OBJ{int(token):04d}" for token in BARE_ID_TOKEN.findall(question)}
        referenced_ids = {rid for rid in referenced_ids if rid != object_id}
        if referenced_ids:
            lines.append(
                f"_Note_: Additional IDs mentioned ({', '.join(sorted(referenced_ids))}). "
                f"Current analysis focuses on `{object_id}`."
            )

    if not payload:
        lines.append("Architect Agent did not return any data.")
        return "\n\n".join(lines)

    if payload.get("error"):
        lines.append(f"Architect Agent encountered an error: `{payload['error']}`.")
        return "\n\n".join(lines)

    snapshot = payload.get("object_snapshot") or {}
    diagram_summary = payload.get("diagram_summary") or {}
    diagram_history = payload.get("diagram_history") or []
    diagram_network = payload.get("diagram_network") or {}
    context_rows = payload.get("object_context") or []
    related_ids = payload.get("related_object_ids") or []
    prompt_ids = payload.get("prompt_object_ids") or []
    if snapshot:
        name = snapshot.get("name")
        headline = f"*Current state*: `{object_id}`"
        if name:
            headline += f" — {name}"

        detail_parts = []
        priority = snapshot.get("priority")
        if priority:
            detail_parts.append(f"priority `{priority}`")
        status = snapshot.get("status")
        if status:
            detail_parts.append(f"status `{status}`")
        schedule_val = snapshot.get("schedule_time")
        if schedule_val:
            detail_parts.append(f"schedule `{schedule_val}`")
        if detail_parts:
            headline += " (" + ", ".join(detail_parts) + ")"
        lines.append(headline)

        updated_by = snapshot.get("priority_updated_by")
        updated_at = snapshot.get("priority_updated_at")
        if updated_by or updated_at:
            audit = " ".join(
                part for part in [
                    "Last override by" if updated_by else "",
                    f"`{updated_by}`" if updated_by else "",
                    "at" if updated_at else "",
                    f"`{updated_at}`" if updated_at else "",
                ] if part
            )
            if audit:
                lines.append(f"- {audit}")

    if context_rows:
        other_objects = [
            row for row in context_rows
            if (row.get("object_id") or "").upper() != object_id.upper()
        ]
        if other_objects:
            lines.append("*Related objects overview*:")
            max_rows = 5
            for record in other_objects[:max_rows]:
                ctx_id = record.get("object_id")
                obj_type = record.get("object_type") or "unknown"
                status = record.get("status") or "unknown"
                priority = record.get("priority") or "unset"
                notes = record.get("architect_notes")
                detail = f"- `{ctx_id}` ({obj_type}) — status {status}, priority {priority}"
                if notes:
                    detail += f"; notes: {notes}"
                lines.append(detail)
            extra_count = max(0, len(other_objects) - max_rows)
            if extra_count:
                lines.append(f"- …plus {extra_count} more object(s) referenced in your question/diagrams.")
    elif prompt_ids:
        lines.append(
            "*Related objects*: Prompt referenced "
            + ", ".join(prompt_ids)
            + " but no active records were found in the current inventory snapshot."
        )

    changes = payload.get("recent_changes") or []
    downstream = payload.get("downstream_impact")

    if changes:
        change_types = {entry.get("change_type", "Update") for entry in changes}
        latest_change = changes[0]
        latest_at = latest_change.get("effective_start")
        lines.append(
            f"*Finding*: {len(changes)} configuration update(s) recorded for `{object_id}` "
            f"({', '.join(sorted(change_types))}). Latest update effective at `{latest_at}`."
        )
        schedule_updates = [
            entry for entry in changes if (entry.get("schedule_time") != entry.get("prev_schedule"))
        ]
        metadata_updates = [
            entry for entry in changes if entry.get("change_type") == "Metadata Changed"
        ]
        if schedule_updates:
            first = schedule_updates[0]
            lines.append(
                f"- Schedule changed from `{first.get('prev_schedule')}` to `{first.get('schedule_time')}`."
            )
        if metadata_updates:
            lines.append(
                "- Metadata diff detected; review SCD2 version history for specific field changes."
            )
    else:
        lines.append(
            f"*Finding*: Architect Agent found no recent configuration deltas for `{object_id}`. "
            "The latest SCD2 version matches the previous schedule and metadata."
        )

    if diagram_summary:
        diagram_name = diagram_summary.get("diagram_name") or diagram_summary.get("diagram_id")
        generated_at = diagram_summary.get("generated_at")
        is_active = diagram_summary.get("is_active")
        status_label = "active" if is_active else "inactive"
        lines.append(
            f"*Diagram insight*: Latest `{diagram_name}` ({diagram_summary.get('diagram_format')}) "
            f"generated `{generated_at}`, currently {status_label}."
        )
        diagram_text = (diagram_summary.get("diagram_text") or "").strip()
        if diagram_text:
            preview = diagram_text if len(diagram_text) <= 800 else diagram_text[:780] + "..."
            lines.append("```mermaid\n" + preview + "\n```")
        if diagram_network:
            node_count = len(diagram_network.get("nodes") or [])
            edge_count = len(diagram_network.get("edges") or [])
            lines.append(
                f"*Diagram graph*: {node_count} node(s) and {edge_count} connection(s) parsed from Mermaid."
            )
    elif diagram_history == []:
        lines.append("*Diagram insight*: No stored Mermaid diagrams were found for this object.")

    if downstream:
        total_dependents = sum(int(row.get("dependency_count", 0) or 0) for row in downstream)
        sample = downstream[:5]
        sample_list = ", ".join(
            "{obj} (x{count}{rel})".format(
                obj=row.get("dependent_object"),
                count=row.get("dependency_count"),
                rel=f", {row.get('relationship_types')}" if row.get("relationship_types") else "",
            )
            for row in sample
        )
        lines.append(
            f"*Downstream impact*: {len(downstream)} dependent object(s) totaling {total_dependents} "
            f"edges. Top dependents: {sample_list}."
        )

    lines.append("Use the tables below for full context.")
    return "\n\n".join(lines)


class SyncFlowDashboard:
    """Dashboard interface for SyncFlow backend."""

    def __init__(self, api_url: str = "http://127.0.0.1:5000"):
        self.api_url = api_url
        self.session = requests.Session()

    def get_health(self):
        """Check backend health."""
        try:
            response = self.session.get(f"{self.api_url}/health", timeout=5)
            return response.json()
        except Exception as e:
            st.error(f"Backend connection error: {e}")
            return None

    def get_objects(self):
        """Get all ETL objects (prefers v2 endpoint, falls back to legacy)."""
        errors = []
        for path in ("/api/v2/objects", "/api/objects"):
            try:
                response = self.session.get(f"{self.api_url}{path}", timeout=10)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and "objects" in data:
                    return data
                errors.append(f"Unexpected payload from {path}")
            except Exception as exc:  # pragma: no cover - UI helper
                errors.append(f"{path}: {exc}")
        if errors:
            st.error("Error fetching objects: " + "; ".join(errors))
        return None

    def get_object_details(self, object_id: str):
        """Get details for specific object."""
        try:
            response = self.session.get(f"{self.api_url}/api/objects/{object_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching object: {e}")
            return None

    def get_object_history(self, object_id: str):
        """Get version history."""
        try:
            response = self.session.get(f"{self.api_url}/api/objects/{object_id}/history", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching history: {e}")
            return None

    def get_lineage_upstream(self, object_id: str):
        """Get upstream dependencies."""
        try:
            response = self.session.get(f"{self.api_url}/api/lineage/{object_id}/upstream", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching lineage: {e}")
            return None

    def get_lineage_downstream(self, object_id: str):
        """Get downstream dependencies."""
        try:
            response = self.session.get(f"{self.api_url}/api/lineage/{object_id}/downstream", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching lineage: {e}")
            return None

    def get_executions(self, object_id: str, days: int = 7, limit: int = 100):
        """Get execution logs."""
        try:
            response = self.session.get(
                f"{self.api_url}/api/metrics/{object_id}/executions",
                params={"days": days, "limit": limit},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching executions: {e}")
            return None

    def get_costs(self, object_id: str, days: int = 30):
        """Get cost data."""
        try:
            response = self.session.get(
                f"{self.api_url}/api/metrics/{object_id}/costs",
                params={"days": days},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching costs: {e}")
            return None

    def analyze_object(self, object_id: str, days: int = 7, cost_days: int = 30):
        """Run all three agents."""
        try:
            response = self.session.get(
                f"{self.api_url}/api/agents/analyze/{object_id}",
                params={"days": days, "cost_days": cost_days},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error running analysis: {e}")
            return None

    def run_agent(self, agent_key: str, object_id: str, **params):
        """Invoke a single agent, with fallback to legacy endpoints."""
        routes = {
            "architect": ["/api/v2/agents/architect", "/api/agents/doc"],
            "ops": ["/api/v2/agents/ops", "/api/agents/log"],
            "finops": ["/api/v2/agents/finops", "/api/agents/cost"],
        }

        base_paths = routes.get(agent_key, [])
        if not base_paths:
            st.error(f"Unknown agent key: {agent_key}")
            return None

        errors = []
        for path in base_paths:
            try:
                response = self.session.get(
                    f"{self.api_url}{path}/{object_id}",
                    params={k: v for k, v in params.items() if v is not None},
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    return data
                errors.append(f"Unexpected payload from {path}")
            except Exception as exc:  # pragma: no cover - UI helper
                errors.append(f"{path}: {exc}")

        if errors:
            st.error("Error running agent: " + "; ".join(errors))
        return None

    def get_stats(self):
        """Get system statistics."""
        try:
            response = self.session.get(f"{self.api_url}/api/stats", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Error fetching stats: {e}")
        return None

    def apply_architect_decision(
        self,
        object_id: str,
        *,
        priority: str | None = None,
        action: str | None = None,
        architect_name: str = "dashboard",
        notes: str | None = None,
        decommission_reason: str | None = None,
        replacement_id: str | None = None,
    ):
        """Apply architect decision via backend endpoint."""
        payload = {
            "architect_name": architect_name,
        }
        if action:
            payload["action"] = action
        if priority:
            payload["priority"] = priority
        if notes:
            payload["notes"] = notes
        if decommission_reason:
            payload["decommission_reason"] = decommission_reason
        if replacement_id:
            payload["replacement_id"] = replacement_id

        try:
            response = self.session.post(
                f"{self.api_url}/api/architect/workflows/{object_id}/decision",
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            detail = ""
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                try:
                    detail_json = exc.response.json()
                    detail = f" Response: {detail_json}"
                except Exception:
                    detail = f" Response: {exc.response.text}"
            st.error(f"Failed to update {object_id}: {exc}{detail}")
            return None

    def generate_architect_diagram(
        self,
        object_id: str,
        *,
        scope: str = "both",
        store: bool = False,
        diagram_name: str | None = None,
    ):
        """Generate a mermaid diagram for the selected object."""
        payload = {
            "scope": scope,
            "store": store,
        }
        if diagram_name:
            payload["diagram_name"] = diagram_name

        try:
            response = self.session.post(
                f"{self.api_url}/api/architect/diagrams/{object_id}",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            st.error(f"Failed to generate diagram: {exc}")
            return None

    def save_custom_diagram(
        self,
        object_id: str,
        diagram_text: str,
        diagram_format: str = "mermaid",
        diagram_name: str | None = None,
        activate: bool = True,
    ):
        """Persist a custom Mermaid diagram supplied by the user."""
        payload = {
            "diagram_text": diagram_text,
            "format": diagram_format,
        }
        if diagram_name:
            payload["diagram_name"] = diagram_name
        payload["activate"] = activate
        try:
            response = self.session.post(
                f"{self.api_url}/api/architect/diagrams/{object_id}/custom",
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            detail = ""
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                try:
                    detail_json = exc.response.json()
                    detail = f" Response: {detail_json}"
                except Exception:
                    detail = f" Response: {exc.response.text}"
            st.error(f"Failed to store diagram: {exc}{detail}")
            return None

    def get_latest_diagram(self, object_id: str):
        """Retrieve the most recent active diagram for an object."""
        try:
            response = self.session.get(
                f"{self.api_url}/api/architect/diagrams/{object_id}",
                timeout=10,
            )
            if response.status_code == 404:
                return {"status": "not_found"}
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            detail = ""
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                try:
                    detail_json = exc.response.json()
                    detail = f" Response: {detail_json}"
                except Exception:
                    detail = f" Response: {exc.response.text}"
            st.error(f"Failed to load diagram: {exc}{detail}")
            return None

    def get_diagram_history(self, object_id: str, limit: int = 10):
        """Retrieve diagram history for an object."""
        try:
            response = self.session.get(
                f"{self.api_url}/api/architect/diagrams/{object_id}/history",
                params={"limit": limit},
                timeout=10,
            )
            if response.status_code == 404:
                return {"status": "not_found", "diagrams": []}
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            if exc.response is not None:
                try:
                    detail = exc.response.json()
                    st.error(f"Failed to load history: {detail}")
                except Exception:
                    st.error(f"Failed to load history: {exc.response.text}")
            else:
                st.error(f"Failed to load history: {exc}")
            return None
        except Exception as exc:
            st.error(f"Failed to load history: {exc}")
            return None


def get_api_url() -> str:
    """Retrieve the configured backend API URL from environment or session state.

    Priority:
    1. SYNCFLOW_BACKEND_URL environment variable (set by Cloud Run)
    2. Session state (set by user in configuration panel)
    3. Default localhost (for local development)
    """
    # Check environment variable first (Cloud Run deployment)
    env_url = os.environ.get('SYNCFLOW_BACKEND_URL')
    if env_url:
        return env_url

    # Fall back to session state (user configuration)
    return st.session_state.get('api_url', "http://127.0.0.1:5000")


def parse_architect_commands(command_text: str):
    """Parse chat-style commands into structured architect requests."""
    if not command_text:
        return []

    segments = [
        segment.strip()
        for segment in re.split(r'[;\n\.]+', command_text)
        if segment.strip()
    ]

    parsed = []
    for segment in segments:
        tokens = re.split(r'[,\s]+', segment)
        object_ids: list[str] = []

        for token in tokens:
            cleaned = token.strip().upper()
            if not cleaned:
                continue
            if re.fullmatch(r'OBJ\d+', cleaned):
                object_ids.append(cleaned)
            elif re.fullmatch(r'\d+', cleaned):
                object_ids.append(f"OBJ{cleaned.zfill(max(3, len(cleaned)))}")

        if not object_ids:
            continue

        object_ids = list(dict.fromkeys(object_ids))

        segment_lower = segment.lower()
        action = None
        priority = None
        notes = ""
        reason = ""

        decom_match = re.search(r'\bdecom\w*\b', segment_lower)
        if decom_match:
            action = "decommission"
            reason = segment[decom_match.end():].strip(" ,.-")
        else:
            priority_patterns = [
                ("CRITICAL", r'\bcritical\b'),
                ("HIGH", r'\bhigh\b'),
                ("MEDIUM", r'\bmedium\b'),
                ("LOW", r'\blow\b'),
            ]
            for priority_value, pattern in priority_patterns:
                match = re.search(pattern, segment_lower)
                if match:
                    priority = priority_value
                    trailing = segment[match.end():].strip(" ,.-")
                    notes = trailing
                    break

        parsed.append({
            "object_ids": object_ids,
            "action": action,
            "priority": priority,
            "notes": notes,
            "reason": reason,
        })

    return parsed


def build_mermaid_from_path(path_text: str) -> str | None:
    """Convert a simple arrow-separated path into a Mermaid flowchart."""
    if not path_text:
        return None

    normalized = re.sub(r'\s*(?:->|→|⇒|to)\s*', '->', path_text, flags=re.IGNORECASE)

    tokens = [
        token.strip()
        for token in re.split(r'->', normalized)
        if token.strip()
    ]

    if len(tokens) < 2:
        return None

    object_lookup = st.session_state.get('architect_object_lookup', {}) or {}
    name_lookup = st.session_state.get('architect_name_lookup', {}) or {}

    node_map: dict[str, tuple[str, str]] = {}
    resolved_sequence: list[str] = []

    def resolve_identifier(raw: str) -> tuple[str | None, str | None, str | None]:
        stripped = raw.strip()
        if not stripped:
            return None, None, None
        upper = stripped.upper()
        canonical = None

        match = re.fullmatch(r"OBJ(\d{1,6})", upper)
        if match:
            canonical = f"OBJ{int(match.group(1)):04d}"
        elif upper in object_lookup:
            canonical = upper
        else:
            canonical = name_lookup.get(stripped.lower())

        if not canonical:
            canonical = upper

        node_id = re.sub(r'\W+', '_', canonical)
        if not node_id:
            node_id = re.sub(r'\W+', '_', upper) or f"NODE_{len(node_map) + 1}"

        display_name = object_lookup.get(canonical)
        if display_name:
            label_text = f"{canonical}\\n{display_name}"
        elif canonical != stripped:
            label_text = f"{canonical}\\n{stripped}"
        else:
            label_text = canonical

        safe_label = label_text.replace('"', '\\"')
        return canonical, node_id, safe_label

    for token in tokens:
        canonical, node_id, label = resolve_identifier(token)
        if not canonical or not node_id or not label:
            continue
        resolved_sequence.append(canonical)
        if canonical not in node_map:
            node_map[canonical] = (node_id, label)

    if len(node_map) < 2:
        return None

    lines = ["flowchart TD"]
    for _, (node_id, label) in node_map.items():
        lines.append(f'{node_id}["{label}"]')

    for idx in range(len(resolved_sequence) - 1):
        src = node_map.get(resolved_sequence[idx])
        tgt = node_map.get(resolved_sequence[idx + 1])
        if not src or not tgt:
            continue
        lines.append(f"{src[0]} --> {tgt[0]}")

    return "\n".join(lines) if len(lines) > 1 else None


def render_header():
    """Render main header and connection status."""
    col1, col2 = st.columns([3, 1])

    with col1:
        st.markdown(
            '<div class="main-header">🚀 SyncFlow GCP Intelligence</div>',
            unsafe_allow_html=True
        )
        st.markdown("*Making Complex GCP Systems Simple Through Multi-Agent Intelligence*")

    with col2:
        dashboard = SyncFlowDashboard(api_url=get_api_url())
        health = dashboard.get_health()

        if health:
            st.markdown(
                '<div class="success">✓ Backend Connected</div>',
                unsafe_allow_html=True
            )
            st.caption(f"Project: {health.get('project', 'N/A')}")
        else:
            st.markdown(
                '<div class="error">✗ Backend Offline</div>',
                unsafe_allow_html=True
            )

    st.divider()


def render_home_page():
    """Render home page with system overview aligned with CLAUDE.md."""

    dashboard = SyncFlowDashboard(api_url=get_api_url())

    # The Problem
    st.markdown("## The Problem")
    st.warning("""
    **GCP is powerful but complex.** Managing architecture, operations, and costs across complex GCP systems requires:
    - Deep visibility into configuration changes
    - Constant performance and reliability analysis
    - Continuous cost optimization and monitoring

    **SyncFlow** solves this through specialized intelligent agents that work together.
    """)

    st.divider()

    # What SyncFlow Does
    st.markdown("## What SyncFlow Does")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📦 Comprehensive Metadata Management")
        st.markdown("""
        - **Mini ETL**: Centralized object registry tracking all GCP resources
        - **SCD Type 2 Versioning**: Complete history with effective date ranges
        - **Execution Monitoring**: Capture and analyze logs
        """)

    with col2:
        st.markdown("### 🤖 Three Specialized Agents")
        st.markdown("""
        **Architect Agent** - Configuration & Change Management
        - Detects configuration changes and lineage modifications
        - Tracks version history and audit trail

        **Ops Agent** - Performance & Reliability
        - Analyzes execution performance and trends
        - Detects anomalies and SLA violations

        **FinOps Agent** - Cost Optimization
        - Monitors costs across all GCP services
        - Identifies savings opportunities
        """)

    st.divider()

    # Why Multi-Agent Architecture
    st.markdown("## Why Multi-Agent Architecture?")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.info("""
        **🎯 No Overload**

        Each agent focuses on one domain
        """)

    with col2:
        st.info("""
        **⚡ Parallel Analysis**

        All agents run simultaneously
        """)

    with col3:
        st.info("""
        **💡 Actionable Results**

        Correlated insights from multiple perspectives
        """)

    with col4:
        st.info("""
        **🔧 Simple to Extend**

        Add new agents without touching existing code
        """)

    st.divider()

    # How to Navigate
    st.markdown("## How to Use SyncFlow")

    st.markdown("""
    ### 🏗️ Architect Agent
    Browse your GCP inventory and prioritize objects for Ops/FinOps focus:
    - **Object Browser**: View all objects with SCD Type 2 version history
    - **Architect Review**: Assign priorities (CRITICAL, HIGH, MEDIUM, LOW)
    - **Mark Decommission**: Identify technical debt candidates
    - **Agent Workbench**: Run detailed Architect analysis

    ### 📊 Ops Agent
    Analyze performance trends and detect reliability issues:
    - Select any object in your inventory
    - View execution metrics and performance trends
    - Detect anomalies and performance degradation
    - Analyze logs over custom time periods

    ### 💰 FinOps Agent
    Monitor costs and identify optimization opportunities:
    - Analyze billing data for any object
    - View cost trends over time
    - Identify cost reduction opportunities
    - Calculate potential savings (ROI)
    """)

    st.divider()

    # Key Facts
    st.markdown("## Inventory Snapshot")
    objects_data = dashboard.get_objects()
    if objects_data and 'objects' in objects_data and objects_data['objects']:
        df = pd.DataFrame(objects_data['objects'])
        columns = [col for col in ['object_id', 'name', 'object_type', 'status', 'priority'] if col in df.columns]
        if columns:
            st.dataframe(df[columns].head(10), use_container_width=True, hide_index=True)
        else:
            st.info("Objects loaded, but no displayable columns were returned.")
    else:
        st.info("Inventory data is not available right now. Check your backend connection.")

    st.divider()

    st.markdown("## Latest Architecture Updates")
    st.info(
        "Generate new diagrams or view existing ones in the Architect tab. "
        "Stored Mermaid diagrams live in `architect_diagrams` and can be exported for architecture docs."
    )

    st.success("""
    ✅ **Ready to get started?**
    Use the sidebar navigation to explore:
    - **🏗️ Architect Agent**: Manage your GCP inventory
    - **📊 Ops Agent**: Monitor performance
    - **💰 FinOps Agent**: Optimize costs
    """)


def render_object_browser():
    """Render object browser page with Architect prioritization features."""
    dashboard = SyncFlowDashboard(api_url=get_api_url())
    data = dashboard.get_objects()

    if not data or 'objects' not in data:
        st.error("Unable to load objects")
        return

    objects = data['objects']

    if not objects:
        st.info("No ETL objects found")
        return

    object_lookup = {}
    name_lookup = {}
    for obj in objects:
        obj_id = (obj.get('object_id') or "").strip()
        name = (obj.get('name') or "").strip()
        if obj_id:
            object_lookup[obj_id.upper()] = name
        if obj_id and name:
            name_lookup[name.lower()] = obj_id.upper()
    st.session_state['architect_object_lookup'] = object_lookup
    st.session_state['architect_name_lookup'] = name_lookup

    # Create dataframe (same as Home page Inventory Snapshot)
    df = pd.DataFrame(objects)

    # Add default priority if not present
    if 'priority' not in df.columns:
        df['priority'] = 'MEDIUM'
    else:
        df['priority'] = df['priority'].fillna('MEDIUM')
    if 'is_decommission' not in df.columns:
        df['is_decommission'] = False
    else:
        df['is_decommission'] = df['is_decommission'].fillna(False)

    # Display table with color coding (matching Inventory Snapshot format)
    display_cols = [col for col in ['object_id', 'name', 'object_type', 'status', 'priority'] if col in df.columns]

    df_display = df[display_cols].copy()

    # Add color coding via styling
    def color_priority(val):
        if val == 'CRITICAL':
            return 'background-color: #ffcccc'  # Light red
        elif val in ['HIGH', 'MEDIUM']:
            return 'background-color: #ffe6cc'  # Light orange
        elif val == 'LOW':
            return 'background-color: #fffbcc'  # Light yellow
        return ''

    styled_df = df_display.style.map(
        color_priority,
        subset=['priority']
    )

    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    # Detailed Object Analysis
    st.divider()
    st.markdown("### Detailed Object Analysis")

    selected_object = st.selectbox(
        "Select Object for Detailed Review",
        options=[obj['object_id'] for obj in objects],
        format_func=lambda x: f"{x} ({next(o['name'] for o in objects if o['object_id'] == x)})"
    )

    if st.button("Load Object Details", key="load_object_details"):
        st.session_state['selected_object_for_details'] = selected_object
        st.rerun()


def render_object_details(object_id: str):
    """Render detailed object view."""
    st.markdown(f"## Object: {object_id}")

    dashboard = SyncFlowDashboard(api_url=get_api_url())

    # Get object details for header display
    obj = dashboard.get_object_details(object_id)
    if obj:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"**Type**: {obj.get('object_type')}")
        with col2:
            st.markdown(f"**Status**: {obj.get('status')}")
        with col3:
            st.markdown(f"**Version**: {obj.get('version')}")
        with col4:
            priority_badge = obj.get('priority') or 'MEDIUM'
            st.markdown(f"**Priority**: `{priority_badge}`")
            updated_at = obj.get('priority_updated_at')
            updated_by = obj.get('priority_updated_by')
            if updated_at or updated_by:
                display_parts = []
                if updated_by:
                    display_parts.append(updated_by)
                if updated_at:
                    try:
                        ts = pd.to_datetime(updated_at).tz_localize(None)
                        display_parts.append(ts.strftime('%Y-%m-%d %H:%M'))
                    except Exception:
                        display_parts.append(str(updated_at))
                st.caption("Updated: " + " · ".join(display_parts))

    st.divider()

    # Tabs
    tab1, tab2 = st.tabs([
        "🏗️ Architect Review",
        "History"
    ])

    with tab1:
        st.markdown("### 🏗️ Architect Review & Prioritization")
        st.markdown("Architect Agent analysis for inventory management and focus areas")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Priority Assignment")
            priority = st.selectbox(
                "Object Priority (for Ops/FinOps focus)",
                options=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                help="CRITICAL: Immediate ops/finops attention | HIGH: Regular monitoring | LOW: Background tasks"
            )

            if priority == "CRITICAL":
                st.info("🔴 **CRITICAL** - Needs immediate ops monitoring and finops optimization")
            elif priority in ["HIGH", "MEDIUM"]:
                st.warning(f"🟠 **{priority}** - Important for regular monitoring and cost tracking")
            else:
                st.success("🟡 **LOW** - Background object with minimal impact")

        with col2:
            st.markdown("#### Object Status")
            is_decommission = st.checkbox(
                "Mark for Decommission",
                value=False,
                help="Check if this object is identified as technical debt and should be removed/consolidated"
            )

            if is_decommission:
                st.error("🗑️ This object is marked for decommission/removal")
                decomm_reason = st.text_input(
                    "Reason for decommission",
                    placeholder="e.g., Replaced by new pipeline, no longer needed, consolidating services..."
                )

        st.markdown("#### Architect's Notes")
        architect_notes = st.text_area(
            "Add notes for Ops and FinOps teams",
            placeholder="Examples:\n- CRITICAL: This is our main user pipeline, any slowdown impacts revenue\n- HIGH: Monitor daily costs, investigate spikes\n- LOW: Legacy pipeline, candidate for consolidation\n- DECOMMISSION: Replaced by new_pipeline_v2, can be removed after 2025-12-31",
            height=150
        )

        # Save button
        if st.button("💾 Update Inventory", key="update_architect_priority"):
            decomm_reason = st.session_state.get("decomm_reason", "")
            result = dashboard.apply_architect_decision(
                object_id,
                priority=priority,
                decommission_reason=decomm_reason if is_decommission else None,
                notes=architect_notes,
                architect_name="dashboard_user"
            )
            if result:
                st.success(f"✅ Updated {object_id} successfully!")
                st.rerun()
            else:
                st.error("Failed to update inventory. Check backend connection.")

        st.markdown("---")
        st.markdown("**How Ops and FinOps use this:**")
        st.markdown("""
        - **Ops Agent** focuses on CRITICAL and HIGH priority objects for anomaly detection
        - **FinOps Agent** tracks costs for CRITICAL objects and identifies optimization opportunities
        - LOW priority objects receive less frequent monitoring
        - DECOMMISSION objects are targets for consolidation/removal efforts
        """)

    with tab2:
        st.markdown("### Version History (SCD Type 2) & Configuration")
        history = dashboard.get_object_history(object_id)
        if history and 'history' in history:
            hist_list = history['history']
            if hist_list:
                st.markdown("**Version Timeline**")
                # Display timeline table
                hist_df = pd.DataFrame(hist_list)
                display_columns = [
                    col for col in [
                        'version',
                        'effective_start',
                        'effective_end',
                        'status',
                        'schedule_time',
                    ] if col in hist_df.columns
                ]
                if display_columns:
                    hist_display = hist_df[display_columns].copy()
                    st.dataframe(hist_display, use_container_width=True, hide_index=True)

                # Show detailed configuration for each version
                st.markdown("**Configuration by Version**")
                for idx, record in enumerate(hist_list):
                    version = record.get('version', f'v{idx}')
                    effective_start = record.get('effective_start', 'N/A')
                    effective_end = record.get('effective_end', 'Current')

                    with st.expander(f"📋 Version {version} ({effective_start} → {effective_end})"):
                        col1, col2 = st.columns(2)

                        with col1:
                            st.markdown("**Basic Info**")
                            st.write(f"**Status**: {record.get('status', 'N/A')}")
                            st.write(f"**Type**: {record.get('object_type', 'N/A')}")
                            st.write(f"**Name**: {record.get('name', 'N/A')}")
                            st.write(f"**Schedule**: {record.get('schedule_time', 'N/A')}")

                        with col2:
                            st.markdown("**Dates**")
                            st.write(f"**Effective Start**: {effective_start}")
                            st.write(f"**Effective End**: {effective_end}")
                            st.write(f"**Created**: {record.get('created_at', 'N/A')}")
                            st.write(f"**Updated**: {record.get('updated_at', 'N/A')}")

                        # Show configuration metadata
                        if record.get('metadata'):
                            st.markdown("**Configuration**")
                            try:
                                metadata = record['metadata']
                                if isinstance(metadata, str):
                                    import json
                                    metadata = json.loads(metadata)
                                st.json(metadata)
                            except Exception as e:
                                st.write(f"Metadata: {record.get('metadata', 'N/A')}")
                        else:
                            st.info("No configuration metadata for this version")
            else:
                st.info("No version history available for this object.")


def render_agent_workbench():
    """Render the dedicated agent workspace."""
    st.markdown("## Agent Workbench")
    st.markdown(
        """Interact with the individual agents to inspect Mini ETL metadata (SCD2 objects) and the
        fact tables powering performance and cost insights."""
    )

    dashboard = SyncFlowDashboard(api_url=get_api_url())

    tabs = st.tabs([
        "Architect Agent",
        "Ops Agent",
        "FinOps Agent",
    ])

    with tabs[0]:
        st.markdown("### Architect Agent")
        st.caption("Analyze SCD2 history and lineage by referencing an object inside your question.")
        architect_prompt = st.text_area(
            "Question or instructions",
            key="architect_workbench_prompt",
            height=140,
            placeholder="Summarize lineage changes impacting OBJ0001 this month.",
        )
        architect_override = st.text_input(
            "Target object override (optional)",
            key="architect_workbench_override",
            placeholder="OBJ0001",
        )
        if st.button("Run Architect Agent", key="architect_run"):
            object_id = normalize_object_id(architect_override)
            if not object_id:
                object_id = extract_object_id_from_text(architect_prompt)
            if not object_id:
                st.warning("Include an object identifier (e.g., OBJ0001) in your request or provide it in the override field.")
            else:
                with st.spinner("Consulting Architect Agent..."):
                    result = dashboard.run_agent("architect", object_id, notes=(architect_prompt or None))
                    if result:
                        if result.get("agent") == "DocAgent":
                            st.markdown("### Agent Answer")
                            st.markdown(summarize_doc_agent_response(object_id, architect_prompt, result))
                        render_agent_analysis(result)

    with tabs[1]:
        st.markdown("### Ops Agent")
        st.caption("Surface performance trends by pointing Ops Agent at a specific object in your question.")
        ops_prompt = st.text_area(
            "Question or instructions",
            key="ops_workbench_prompt",
            height=140,
            placeholder="Highlight error spikes for OBJ0001 over the last 14 days.",
        )
        ops_override = st.text_input(
            "Target object override (optional)",
            key="ops_workbench_override",
            placeholder="OBJ0001",
        )
        days = st.slider("Lookback window (days)", 1, 90, 7, key="ops_days")
        if st.button("Run Ops Agent", key="ops_run"):
            object_id = normalize_object_id(ops_override)
            if not object_id:
                object_id = extract_object_id_from_text(ops_prompt)
            if not object_id:
                st.warning("Include an object identifier (e.g., OBJ0001) in your request or provide it in the override field.")
            else:
                with st.spinner("Consulting Ops Agent..."):
                    result = dashboard.run_agent("ops", object_id, days=days, notes=(ops_prompt or None))
                    if result:
                        render_agent_analysis(result)

    with tabs[2]:
        st.markdown("### FinOps Agent")
        st.caption("Analyze billing exports by referencing an object inside your cost question.")
        finops_prompt = st.text_area(
            "Question or instructions",
            key="finops_workbench_prompt",
            height=140,
            placeholder="Break down the monthly spend for OBJ0001 and related functions.",
        )
        finops_override = st.text_input(
            "Target object override (optional)",
            key="finops_workbench_override",
            placeholder="OBJ0001",
        )
        days = st.slider("Billing analysis window (days)", 7, 365, 30, key="finops_days")
        if st.button("Run FinOps Agent", key="finops_run"):
            object_id = normalize_object_id(finops_override)
            if not object_id:
                object_id = extract_object_id_from_text(finops_prompt)
            if not object_id:
                st.warning("Include an object identifier (e.g., OBJ0001) in your request or provide it in the override field.")
            else:
                with st.spinner("Consulting FinOps Agent..."):
                    result = dashboard.run_agent("finops", object_id, days=days, notes=(finops_prompt or None))
                    if result:
                        render_agent_analysis(result)

def render_agent_analysis(agent_data):
    """Render individual agent analysis results."""
    raw_agent_name = agent_data.get('agent', 'Unknown Agent')
    agent_name_map = {
        "DocAgent": "Architect Agent",
        "LogAgent": "Ops Agent",
        "CloudFnOAgent": "FinOps Agent",
    }
    agent_name = agent_name_map.get(raw_agent_name, raw_agent_name)
    analysis_type = agent_data.get('analysis_type', '')

    def render_shared_arch_context(agent_data):
        context_rows = agent_data.get("object_context") or []
        if context_rows:
            context_df = pd.DataFrame(context_rows)
            display_cols = [
                col for col in [
                    "object_id",
                    "object_type",
                    "name",
                    "status",
                    "priority",
                    "schedule_time",
                    "architect_notes",
                    "architect_reviewed_by",
                    "architect_review_timestamp",
                    "priority_updated_by",
                    "priority_updated_at",
                    "is_decommission",
                    "decommission_reason",
                ] if col in context_df.columns
            ]
            st.markdown("### Inventory Context")
            st.dataframe(
                context_df[display_cols] if display_cols else context_df,
                use_container_width=True,
                hide_index=True,
            )

        diagram_summary = agent_data.get("diagram_summary") or {}
        diagram_history = agent_data.get("diagram_history") or []
        diagram_network = agent_data.get("diagram_network") or {}

        if diagram_summary:
            st.markdown("### Latest Architecture Diagram")
            diagram_name = diagram_summary.get("diagram_name") or diagram_summary.get("diagram_id")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Diagram", diagram_name)
            with col2:
                st.metric("Generated", diagram_summary.get("generated_at", ""))
            diagram_text = diagram_summary.get("diagram_text") or ""
            if diagram_text:
                render_mermaid_diagram(diagram_text)
        elif diagram_history == []:
            st.info("No Mermaid diagrams were found for the referenced objects.")

        if diagram_network:
            st.markdown("### Diagram Network")
            nodes = diagram_network.get("nodes") or []
            edges = diagram_network.get("edges") or []
            if nodes:
                node_df = pd.DataFrame(nodes)
                st.write("Nodes")
                st.dataframe(node_df, use_container_width=True, hide_index=True)
            if edges:
                edge_df = pd.DataFrame(edges)
                st.write("Edges")
                st.dataframe(edge_df, use_container_width=True, hide_index=True)

        if diagram_history:
            hist_df = pd.DataFrame(diagram_history)
            columns = [col for col in ["diagram_id", "diagram_name", "generated_at", "is_active"] if col in hist_df.columns]
            if columns:
                st.markdown("### Diagram History")
                st.dataframe(hist_df[columns], use_container_width=True, hide_index=True)

        portfolio_summary = agent_data.get("portfolio_summary") or []
        if portfolio_summary:
            st.markdown("### Portfolio Top Spenders")
            portfolio_df = pd.DataFrame(portfolio_summary)
            display_cols = [
                col for col in [
                    "object_id",
                    "total_cost",
                    "avg_daily_cost",
                    "avg_event_cost",
                    "record_count",
                ] if col in portfolio_df.columns
            ]
            st.dataframe(
                portfolio_df[display_cols] if display_cols else portfolio_df,
                use_container_width=True,
                hide_index=True,
            )

    with st.expander(f"**{agent_name}** - {analysis_type}", expanded=True):

        if raw_agent_name == "DocAgent":
            st.markdown("### Configuration Changes")

            changes = agent_data.get('recent_changes', [])
            if changes:
                changes_df = pd.DataFrame(changes)
                st.dataframe(changes_df, use_container_width=True, hide_index=True)
            else:
                st.info("No recent configuration changes")

            render_shared_arch_context(agent_data)

        elif raw_agent_name == "LogAgent":
            st.markdown("### Performance Analysis")

            improvement = agent_data.get('trend_improvement_percent', 0)
            if improvement > 0:
                st.success(f"✓ Performance Improvement: {improvement}%")
            elif improvement < 0:
                st.warning(f"⚠ Performance Degradation: {abs(improvement)}%")
            else:
                st.info("→ No significant change")

            # Portfolio summary (top executions by object)
            portfolio_summary = agent_data.get("portfolio_summary") or []
            if portfolio_summary:
                st.markdown("**Top Executed Objects**")
                portfolio_df = pd.DataFrame(portfolio_summary)
                display_cols = [
                    col for col in [
                        "object_id",
                        "total_executions",
                        "successful_runs",
                        "success_rate",
                        "avg_duration",
                        "peak_duration",
                        "total_rows",
                    ] if col in portfolio_df.columns
                ]
                st.dataframe(
                    portfolio_df[display_cols] if display_cols else portfolio_df,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No portfolio data available")

            # Daily execution metrics (runs per day, duration trends, anomalies)
            st.markdown("**Daily Execution Metrics**")
            metrics = agent_data.get('daily_metrics', [])

            # Debug: show what we have
            if not metrics:
                st.warning("⚠️ No daily metrics returned from Ops Agent")
                st.info("Check: Did you specify an object_id? Portfolio view may be limited.")
                with st.expander("🔧 Debug Info"):
                    st.json({
                        "agent": agent_data.get("agent"),
                        "object_id": agent_data.get("object_id"),
                        "daily_metrics_count": len(agent_data.get('daily_metrics', [])),
                        "portfolio_summary_count": len(agent_data.get("portfolio_summary", [])),
                    })
            else:
                metrics_df = pd.DataFrame(metrics)
                st.info(f"Found {len(metrics)} days of execution data")

                display_cols = [
                    col for col in [
                        "run_date",
                        "object_id",
                        "executions",
                        "successful",
                        "avg_duration",
                        "min_duration",
                        "max_duration",
                        "total_rows",
                        "avg_throughput",
                        "performance_status",
                    ] if col in metrics_df.columns
                ]
                st.dataframe(
                    metrics_df[display_cols] if display_cols else metrics_df,
                    use_container_width=True,
                    hide_index=True,
                )

            # Show architecture context with Mermaid diagram (helps understand dependencies)
            st.markdown("**Architecture Context** (for dependency analysis)")
            context_rows = agent_data.get("object_context") or []
            if context_rows:
                context_df = pd.DataFrame(context_rows)
                display_cols = [
                    col for col in [
                        "object_id",
                        "object_type",
                        "name",
                        "status",
                        "priority",
                    ] if col in context_df.columns
                ]
                st.dataframe(
                    context_df[display_cols] if display_cols else context_df,
                    use_container_width=True,
                    hide_index=True,
                )

            # Show lineage diagram to understand impact
            diagram_summary = agent_data.get("diagram_summary") or {}
            if diagram_summary:
                st.markdown("**Dependency Lineage (Mermaid)**")
                diagram_text = diagram_summary.get("diagram_text") or ""
                if diagram_text:
                    render_mermaid_diagram(diagram_text)

        elif raw_agent_name == "CloudFnOAgent":
            st.markdown("### Cost Analysis")

            savings = agent_data.get('savings_opportunity_percent', 0)
            daily_savings = agent_data.get('estimated_daily_savings', 0)

            col1, col2 = st.columns(2)
            with col1:
                if savings > 0:
                    st.success(f"💰 Savings: {savings}%")
                else:
                    st.info(f"Cost Trend: {savings}%")

            with col2:
                st.metric("Daily Savings", f"${daily_savings:.2f}")

            cost_data = agent_data.get('cost_data', [])
            if cost_data:
                cost_df = pd.DataFrame(cost_data)
                st.dataframe(cost_df, use_container_width=True, hide_index=True)

            render_shared_arch_context(agent_data)

    # Export option (outside expander to avoid nesting)
    object_id = agent_data.get('object_id', 'object')
    export_name = f"{object_id}_{agent_name.lower().replace(' ', '_')}.json"
    col1, col2 = st.columns([10, 1])
    with col1:
        st.caption("📥 Download full analysis report as JSON:")
    with col2:
        st.download_button(
            label="📥 Download",
            data=json.dumps(agent_data, indent=2),
            file_name=export_name,
            mime="application/json",
            key=f"download_{export_name}",
        )


def render_architect_agent():
    """Render Architect Agent section - combined Object Browser and Agent Workbench."""
    st.markdown("# 🏗️ Architect Agent")
    st.markdown("**Configuration & Change Management**")

    with st.expander("ℹ️ What does Architect Agent do?", expanded=True):
        st.markdown("""
        - **Detects configuration changes** and lineage modifications across your GCP infrastructure
        - **Tracks version history** with full audit trail showing who changed what and when
        - **Analyzes impact** of changes on downstream systems
        - **Manages priorities** (CRITICAL, HIGH, MEDIUM, LOW) for operational focus
        - **Identifies decommission candidates** for consolidation and cost savings

        **Example**:
        > View and update minietl OBJ0002's architecture. Check its priority, dependencies, and generate mermaid diagram.
        """)

    st.markdown("---")
    st.markdown("## Architect Agent Workbench")

    dashboard = SyncFlowDashboard(api_url=get_api_url())

    # Object Inventory -------------------------------------------------------
    st.markdown("## Object Inventory & Prioritization")
    render_object_browser()

    # Display object details if selected
    if 'selected_object_for_details' in st.session_state:
        selected_obj = st.session_state['selected_object_for_details']
        st.divider()
        render_object_details(selected_obj)
        st.divider()

    # Architect Chat Commands -------------------------------------------------
    st.markdown("## Architect Chat Commands")
    st.caption("Describe updates in plain language. Example: `OBJ0001 OBJ0002 critical, OBJ0003 decom legacy pipeline`")

    chat_input = st.text_area(
        "Bulk instructions",
        key="architect_chat_input",
        placeholder="obj0001 obj0002 critical - promote after incident review\nobj0003 decommission legacy pipeline",
        height=150,
    )
    architect_name = st.text_input("Architect name", value="dashboard_user", key="architect_chat_user")

    if st.button("Apply Instructions", key="architect_chat_submit"):
        commands = parse_architect_commands(chat_input)
        if not commands:
            st.warning("No recognizable commands found. Reference object IDs such as OBJ0001 and specify critical/high/low/decommission.")
        else:
            results = []
            for command in commands:
                if command["action"] == "decommission":
                    reason = command["reason"] or "Marked for decommission via dashboard chat"
                    for obj_id in command["object_ids"]:
                        response = dashboard.apply_architect_decision(
                            obj_id,
                            action="decommission",
                            architect_name=architect_name or "dashboard_user",
                            notes=reason,
                            decommission_reason=reason,
                        )
                        if response:
                            results.append((obj_id, response))
                elif command["priority"]:
                    priority_value = command["priority"]
                    notes_value = command["notes"] or None
                    for obj_id in command["object_ids"]:
                        response = dashboard.apply_architect_decision(
                            obj_id,
                            priority=priority_value,
                            architect_name=architect_name or "dashboard_user",
                            notes=notes_value,
                        )
                        if response:
                            results.append((obj_id, response))
            if results:
                st.success(f"Processed {len(results)} updates.")
                with st.expander("Update results"):
                    for obj_id, payload in results:
                        st.write(obj_id, payload)
            else:
                st.error("No updates were applied. Check API connectivity or input format.")

    # Architecture Diagram Builder -------------------------------------------
    st.divider()
    st.markdown("## Architecture Diagram Builder")
    st.caption("Generate lineage-based diagrams or store custom Mermaid snippets for later reference.")

    if 'architect_loaded_history' not in st.session_state:
        st.session_state['architect_loaded_history'] = []
    if 'architect_last_loaded_key' not in st.session_state:
        st.session_state['architect_last_loaded_key'] = ""

    diagram_key_input = st.text_input(
        "Diagram id",
        key="architect_diagram_key",
        placeholder="e.g., minietl, MAIN_PATH, user_analytics",
    )
    key_str = diagram_key_input.strip()
    last_loaded_key = st.session_state.get('architect_last_loaded_key', "")

    # Action buttons
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        show_clicked = st.button("🎯 Show Diagram (code and map)", key="architect_diagram_show")
    with col2:
        history_clicked = st.button("📜 Load History", key="architect_diagram_fetch")
    with col3:
        clear_clicked = st.button("🗑️ Clear", key="architect_diagram_clear")

    if clear_clicked:
        st.session_state['architect_suggested_key'] = ""
        st.session_state['architect_diagram_text_editor'] = ""
        st.session_state['architect_diagram_name_state'] = ""
        st.session_state['architect_latest_status'] = None
        st.session_state['architect_loaded_history'] = []
        st.session_state['architect_last_loaded_key'] = ""
        st.rerun()

    # Show Diagram - displays latest diagram with code and map
    if show_clicked:
        if not key_str:
            st.warning("Enter a diagram key or id to show an existing diagram, or leave blank to create a new one.")
        else:
            latest_result = dashboard.get_latest_diagram(key_str)
            st.session_state['architect_latest_status'] = latest_result
            st.session_state['architect_last_loaded_key'] = key_str
            if latest_result and latest_result.get("status") == "success":
                diagram = latest_result.get("diagram", {})
                st.session_state['architect_diagram_text_editor'] = diagram.get("diagram_text", "")
                st.session_state['architect_diagram_name_state'] = diagram.get("diagram_name", "")
            elif latest_result and latest_result.get("status") == "not_found":
                st.info("No diagram found for this key. Create a new one below.")
                if not st.session_state.get('architect_diagram_text_editor'):
                    st.session_state['architect_diagram_text_editor'] = "flowchart TD\n"
            elif latest_result and latest_result.get("error"):
                st.error(latest_result.get("error"))

    # Load History - shows all versions of this diagram
    if history_clicked:
        if not key_str:
            st.warning("Enter a diagram key or id to load diagram history.")
        else:
            history_result = dashboard.get_diagram_history(key_str, limit=10)
            if history_result and history_result.get("status") == "success":
                st.session_state['architect_loaded_history'] = history_result.get("diagrams", [])
            else:
                st.session_state['architect_loaded_history'] = []
                if history_result and history_result.get("status") == "not_found":
                    st.info("No diagram history found for this key.")
                elif history_result and history_result.get("error"):
                    st.error(history_result.get("error"))

    if key_str:
        st.session_state['architect_suggested_key'] = ""
        if key_str != last_loaded_key:
            st.info(f"📌 Click '🎯 Show Diagram (code and map)' to display '{key_str}', or edit below to create new.")
    else:
        suggestion = st.session_state.get('architect_suggested_key')
        if suggestion:
            st.info(f"✨ Suggested key: **{suggestion}**. Enter it above and click '🎯 Show Diagram (code and map)'")
        else:
            st.info("📝 **Workflow**: (1) Enter a key like 'minietl' → (2) Click 'Show Diagram' → (3) Edit below → (4) Click 'Save Diagram'")

    if 'architect_latest_status' not in st.session_state:
        st.session_state['architect_latest_status'] = None
    if 'architect_diagram_text_editor' not in st.session_state:
        st.session_state['architect_diagram_text_editor'] = ""
    if 'architect_diagram_name_state' not in st.session_state:
        st.session_state['architect_diagram_name_state'] = ""
    if 'architect_suggested_key' not in st.session_state:
        st.session_state['architect_suggested_key'] = ""

    pending_name = st.session_state.pop('architect_diagram_name_state_pending', None)
    if pending_name is not None:
        st.session_state['architect_diagram_name_state'] = pending_name

    pending_text = st.session_state.pop('architect_diagram_text_editor_pending', None)
    if pending_text is not None:
        st.session_state['architect_diagram_text_editor'] = pending_text

    latest_result = st.session_state.get('architect_latest_status')
    if latest_result:
        status = latest_result.get("status")
        if status == "success":
            diagram = latest_result.get("diagram", {})
            st.success(f"Loaded diagram '{diagram.get('diagram_name') or diagram.get('diagram_id')}'.")
            text = diagram.get("diagram_text", "")
            if text:
                st.markdown("#### Mermaid Preview")
                render_mermaid_diagram(text)
            st.json(diagram)
        elif status == "not_found":
            st.info("No active diagrams found for this object. Enter a Mermaid definition below to create the first one.")
            if not st.session_state.get('architect_diagram_text_editor'):
                st.session_state['architect_diagram_text_editor'] = "flowchart TD\n"
        else:
            st.error(latest_result.get("error", "Unknown error while loading diagram."))

    history_records = st.session_state.get('architect_loaded_history', [])
    history_expanded = bool(history_records) and bool(key_str) and key_str.lower() == st.session_state.get('architect_last_loaded_key', "").lower()

    if history_records:
        with st.expander("Diagram history", expanded=history_expanded):
            history_df = pd.DataFrame(history_records)
            display_cols = [col for col in ["diagram_id", "diagram_name", "generated_at", "is_active"] if col in history_df.columns]
            if display_cols:
                st.dataframe(history_df[display_cols], use_container_width=True, hide_index=True)

            option_labels = [
                f"{rec.get('diagram_id')} - {rec.get('diagram_name') or 'Unnamed'} ({rec.get('generated_at')})"
                for rec in history_records
            ]
            selected_index = st.selectbox(
                "Select a diagram to preview",
                options=list(range(len(option_labels))),
                format_func=lambda idx: option_labels[idx],
                key="architect_diagram_history_select",
            )
            if st.button("Load selected diagram", key="architect_diagram_load_history"):
                chosen = history_records[selected_index]
                st.session_state['architect_diagram_text_editor'] = chosen.get("diagram_text", "")
                st.session_state['architect_diagram_name_state'] = chosen.get("diagram_name", "")
                st.session_state['architect_latest_status'] = {
                    "status": "success",
                    "diagram": chosen,
                }
                st.success(f"Loaded diagram '{chosen.get('diagram_id')}'.")

                # Display the loaded diagram with code and visualization
                st.markdown("#### Selected Diagram Preview")
                diagram_text = chosen.get("diagram_text", "")
                if diagram_text:
                    render_mermaid_diagram(diagram_text)

    st.markdown("### Generate From Path (optional for new)")
    st.caption("Provide arrow instructions or guidance to draft a diagram, then refine or save below.")
    path_instructions = st.text_input(
        "Arrow instructions or architecture advice",
        key="architect_path_instructions",
    )

    if st.button("Generate Diagram From Path", key="architect_diagram_generate_path"):
        instructions = path_instructions.strip()
        if not instructions:
            st.warning("Provide arrow instructions before generating a diagram.")
        else:
            normalized = re.sub(r'\s*(?:->|→|⇒|to)\s*', '->', instructions, flags=re.IGNORECASE)
            tokens = [token.strip() for token in re.split(r'->', normalized) if token.strip()]
            generated = build_mermaid_from_path(instructions)
            if not generated:
                st.warning("Unable to generate diagram from the provided instructions.")
            else:
                st.session_state['architect_diagram_text_editor'] = generated
                if tokens:
                    first = tokens[0].upper()
                    if first.isdigit():
                        first = f"OBJ{first.zfill(4)}"
                    st.session_state['architect_suggested_key'] = first
                st.session_state['architect_latest_status'] = None
                st.session_state['architect_diagram_name_state'] = st.session_state.get('architect_diagram_name_state') or "Generated Path"
                if st.session_state.get('architect_suggested_key'):
                    st.info(f"Suggested diagram key: {st.session_state['architect_suggested_key']}. Enter it above before saving or choose your own label.")
                st.success("Generated diagram preview from instructions. Update or save below if satisfied.")
                st.markdown("#### Preview")
                render_mermaid_diagram(generated)

    st.markdown("### Edit Diagram")
    st.caption("Review the current Mermaid definition, apply your changes, then save.")
    diagram_name_input = st.text_input(
        "Diagram name (optional)",
        value=st.session_state.get('architect_diagram_name_state', ""),
        key="architect_diagram_name_state",
    )
    diagram_text_input = st.text_area(
        "Mermaid diagram text",
        value=st.session_state.get('architect_diagram_text_editor', ""),
        key="architect_diagram_text_editor",
        height=200,
    )

    if st.button("Save Diagram", key="architect_diagram_save"):
        diagram_text = st.session_state.get('architect_diagram_text_editor', "").strip()
        raw_key = diagram_key_input.strip() or diagram_name_input.strip() or "adhoc_diagram"
        diagram_key = re.sub(r"\s+", "_", raw_key)
        clean_name = diagram_name_input.strip()

        if not diagram_text:
            st.error("Provide Mermaid text to store.")
        else:
            if not diagram_text.lower().lstrip().startswith(("flowchart", "graph")):
                diagram_text = f"flowchart TD\n{diagram_text}"
            result = dashboard.save_custom_diagram(
                diagram_key,
                diagram_text=diagram_text,
                diagram_format="mermaid",
                diagram_name=clean_name or None,
                activate=True,
            )
            if result and result.get("status") == "success":
                st.session_state['architect_suggested_key'] = diagram_key
                st.success("Diagram stored successfully.")
                st.markdown("#### Updated Diagram")
                render_mermaid_diagram(diagram_text)
                if result.get("warning"):
                    st.warning(result["warning"])
                st.write(result)
                st.info(f"Diagram saved under key '{diagram_key}'. Use this key in the field above to reload or view history.")
                st.session_state['architect_diagram_name_state_pending'] = clean_name
                st.session_state['architect_diagram_text_editor_pending'] = diagram_text
                history_update = dashboard.get_diagram_history(diagram_key, limit=10)
                if history_update and history_update.get("status") == "success":
                    st.session_state['architect_loaded_history'] = history_update.get("diagrams", [])
                else:
                    st.session_state['architect_loaded_history'] = []
                st.session_state['architect_last_loaded_key'] = diagram_key
                latest = dashboard.get_latest_diagram(diagram_key)
                st.session_state['architect_latest_status'] = latest
            elif result:
                st.error(f"Diagram storage failed: {result.get('error')}")

    # Agent Analysis ----------------------------------------------------------
    st.divider()
    st.markdown("## Talk with Architect Agent")
    st.caption("Ask architectural questions about an object. Include an object ID to focus analysis. Example: \"View OBJ0002 architecture\"")

    analysis_prompt = st.text_area(
        "Question or instructions",
        key="architect_analysis_prompt",
        height=140,
        placeholder="View OBJ0002 architecture and dependencies",
    )
    analysis_override = st.text_input(
        "Target object override (optional)",
        key="architect_analysis_override",
        placeholder="OBJ0002",
    )

    if st.button("Run Architect Agent", key="architect_analysis_run"):
        if not analysis_prompt.strip():
            st.warning("Please ask a question or provide instructions.")
        else:
            target = normalize_object_id(analysis_override)
            if not target:
                target = extract_object_id_from_text(analysis_prompt)

            with st.spinner("Consulting Architect Agent..."):
                result = dashboard.run_agent("architect", target, notes=(analysis_prompt or None))
                if result:
                    if result.get("agent") == "DocAgent":
                        st.markdown("### Agent Answer")
                        st.markdown(summarize_doc_agent_response(target, analysis_prompt, result))
                    render_agent_analysis(result)


def render_ops_agent():
    """Render Ops Agent workbench only."""
    st.markdown("# 📊 Ops Agent")
    st.markdown("**Performance & Reliability Intelligence**")

    with st.expander("ℹ️ What does Ops Agent do?", expanded=True):
        st.markdown("""
        - **Analyzes execution performance** and trends over time (duration, throughput, success rates)
        - **Detects anomalies** (jobs running 2+ standard deviations slower than baseline)
        - **Tracks reliability patterns** and SLA violations
        - **Identifies bottlenecks** in your data pipelines
        - **Forecasts capacity needs** based on growth trends

        **Example**:
        > Analyze minietl OBJ0001 execution logs and performance trends. Check duration and success rates.
        """)

    st.markdown("---")
    st.caption("Ask about execution performance. Include an object ID to focus analysis. Example: \"Analyze OBJ0001 execution logs\"")

    dashboard = SyncFlowDashboard(api_url=get_api_url())
    ops_prompt = st.text_area(
        "Question or instructions",
        key="ops_page_prompt",
        height=140,
        placeholder="Analyze minietl OBJ0001 execution logs and performance trends",
    )
    ops_override = st.text_input(
        "Target object override (optional)",
        key="ops_page_object_override",
        placeholder="OBJ0001",
    )
    days = st.slider("Lookback window (days)", 1, 90, 7, key="ops_page_days")

    if st.button("Run Ops Agent", key="ops_page_run"):
        target = normalize_object_id(ops_override)
        if not target:
            target = extract_object_id_from_text(ops_prompt)

        auto_portfolio = False
        if not target:
            target = "PORTFOLIO"
            auto_portfolio = True

        with st.spinner("Consulting Ops Agent..."):
            result = dashboard.run_agent("ops", target, days=days, notes=(ops_prompt or None))
            if result:
                if auto_portfolio:
                    st.info("No object ID supplied. Displaying top performers across your portfolio.")
                render_agent_analysis(result)


def render_finops_agent():
    """Render FinOps Agent workbench only."""
    st.markdown("# 💰 FinOps Agent")
    st.markdown("**Cost Optimization & Financial Intelligence**")

    with st.expander("ℹ️ What does FinOps Agent do?", expanded=True):
        st.markdown("""
        - **Monitors costs** across all GCP services (Dataflow, BigQuery, Cloud Functions, Scheduler, etc.)
        - **Identifies cost drivers** and optimization opportunities
        - **Calculates savings potential** from rightsizing and consolidation
        - **Tracks cost trends** month-over-month and year-over-year
        - **Recommends actions** (partitioning, archival, resource optimization)

        **Example**:
        > Analyze minietl's top cost objects. Check billing data and identify optimization opportunities.
        """)

    st.markdown("---")
    st.caption("Ask about costs. Leave blank to see top spenders. Example: \"Show top 5 highest cost objects\"")

    dashboard = SyncFlowDashboard(api_url=get_api_url())
    finops_prompt = st.text_area(
        "Question or instructions",
        key="finops_page_prompt",
        height=140,
        placeholder="Show top 5 highest cost minietl objects",
    )
    finops_override = st.text_input(
        "Target object override (optional)",
        key="finops_page_object_override",
        placeholder="OBJ0001",
    )
    days = st.slider("Billing analysis window (days)", 7, 365, 30, key="finops_page_days")

    if st.button("Run FinOps Agent", key="finops_page_run"):
        target = normalize_object_id(finops_override)
        if not target:
            target = extract_object_id_from_text(finops_prompt)

        auto_portfolio = False
        if not target:
            target = "PORTFOLIO"
            auto_portfolio = True

        with st.spinner("Consulting FinOps Agent..."):
            result = dashboard.run_agent("finops", target, days=days, notes=(finops_prompt or None))
            if result:
                if auto_portfolio:
                    st.info("No object ID supplied. Displaying top spenders across your portfolio.")
                render_agent_analysis(result)


def main():
    """Main application."""
    # Sidebar
    st.sidebar.markdown("## Navigation")

    page = st.sidebar.radio(
        "Select Page",
        ["Home", "🏗️ Architect Agent", "📊 Ops Agent", "💰 FinOps Agent"],
        label_visibility="collapsed"
    )

    st.sidebar.divider()

    # API Configuration
    with st.sidebar.expander("⚙️ Configuration"):
        # Get default value (from environment or hardcoded)
        env_url = os.environ.get('SYNCFLOW_BACKEND_URL')
        default_url = env_url or "http://127.0.0.1:5000"

        # Show status
        if env_url:
            st.info(f"✅ Using Cloud Run backend: {env_url}")
        else:
            st.caption("💻 Using local development backend")

        # Allow override (if not using Cloud Run)
        api_url = st.text_input(
            "Backend API URL (override)",
            value=default_url,
            help="SyncFlow backend API endpoint. Leave empty to use environment default."
        )

        # Store in session state if user provided a value
        if api_url and api_url != default_url:
            st.session_state.api_url = api_url
        elif env_url:
            st.session_state.api_url = env_url
        else:
            st.session_state.api_url = api_url or "http://127.0.0.1:5000"

    # Render page
    render_header()

    if page == "Home":
        render_home_page()

    elif page == "🏗️ Architect Agent":
        render_architect_agent()

    elif page == "📊 Ops Agent":
        render_ops_agent()

    elif page == "💰 FinOps Agent":
        render_finops_agent()


if __name__ == "__main__":
    main()
