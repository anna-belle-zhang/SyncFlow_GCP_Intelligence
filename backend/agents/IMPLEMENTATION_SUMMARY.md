# ADK Architect Agent – Implementation Summary

**Last updated:** 2025-02-15  
**Scope:** Documenting the implementation living under `backend/agents` that delivers the ADK-aligned architect assistant for SyncFlow's GCP estate.  
**Phase status:** Foundation in place; API and dashboard integration targeted for the next milestone.

---

## System Overview

- Dual-agent pattern splits read and write responsibilities:
  - `InventoryAnalystAgent` (read-only) inspects inventory, lineage, and generates ranked options.
  - `ArchitectProposalAgent` (write-enabled) applies architect decisions and records audit trails.
- `ArchitectWorkflow` in `backend/agents/architect_agent_adk.py` orchestrates the end-to-end flow and exposes a module-level `start_architect_review()` helper for API integration.
- BigQuery is the system of record. The agent operates on `etlobjectscd2` (objects) and `etledges` (dependencies), with planned companion tables `architect_proposals` and `architect_audit_log` for richer tracking.
- The implementation currently runs in a synchronous, print-logged mode intended for CLI execution and harness testing; integration into Flask and Streamlit is scheduled for Phase 2.

---

## Core Python Modules

### Data Models – `backend/agents/models_adk.py`
- Enumerations capture architect domain concepts: `Priority`, `ProposalType`, `ProposalStatus`, and `AuditAction`.
- Pydantic models describe lineage graph primitives (`LineageNode`, `LineageEdge`, `LineageGraph`), impact analysis (`ImpactMetric`, `ImpactAnalysis`), proposal payloads, architect reviews, workflow requests/responses, and inventory snapshots.
- Models are serialisation-friendly (`use_enum_values`, JSON encoders for `datetime`) to simplify BigQuery inserts and outbound API responses.

### Orchestration & Agents – `backend/agents/architect_agent_adk.py`
- `InventoryAnalystAgent`:
  - `analyze_inventory()` fetches active objects, priority distribution, and unreviewed items.
  - `analyze_critical_objects()` delegates to lineage tooling to surface risky dependency chains.
  - `generate_options()` inspects the top five unreviewed objects and assembles consolidation, optimisation, or decommission proposals where applicable.
  - `recommend()` ranks proposals via ROI scoring from the proposal tools.
- `ArchitectProposalAgent`:
  - `present_option()` formats proposals for downstream consumption.
  - `collect_review()` stores architect responses and timestamps.
  - Implementation helpers (`implement_priority_assignment()`, `implement_consolidation()`, `implement_decommission()`) map architect intent to BigQuery actions through the update tools.
- `ArchitectWorkflow` sequences the analyst and proposal agents, stores generated proposals, and exposes `apply_architect_decision()` to persist a selected priority.
- Module-level factories (`create_architect_workflow()`, `start_architect_review()`) provide thin shims for Flask route handlers.

### Inventory Tooling – `backend/agents/tools/inventory_tools_standalone.py`
- Shared `agent_tool` decorator marks functions for future ADK registration (currently a no-op).
- BigQuery helper functions (lazy `bigquery.Client` singleton plus query wrappers) power six inventory utilities:
  1. `load_gcp_inventory()` returns active objects with metadata, priority, and dependency counts.
  2. `get_unreviewed_objects()` lists active objects missing architect prioritisation.
  3. `get_priority_summary()` aggregates objects by priority, surfacing review backlogs.
  4. `find_objects_by_pattern()` searches names and object types via case-insensitive patterns.
  5. `analyze_object_dependencies()` counts upstream/downstream edges for a given object.
  6. `find_critical_dependency_chains()` inspects `etledges` to locate high-impact nodes and chains.
- Queries follow SCD2 conventions (`effective_end IS NULL`, `status = 'active'`) and return JSON-serialisable dictionaries suited for agents or API callers.

### Lineage Analysis – `backend/agents/tools/lineage_tools_adk.py`
- Provides upstream and downstream traversal helpers (`analyze_lineage_upstream`, `analyze_lineage_downstream`) built with BigQuery recursive CTEs.
- `build_lineage_graph()` composes nodes, edges, and path metadata for visualisation or policy checks.
- `extract_critical_paths()` flags high fan-out objects, path depths, and dependency chains exceeding configurable thresholds.
- Defensive logic includes cycle avoidance via `ARRAY_LENGTH(path)` checks and optional depth limits for expensive traversals.

### Proposal Generation – `backend/agents/tools/proposal_tools.py`
- Generates proposal stubs enriched with quantitative signals:
  - `generate_consolidation_proposal()` validates at least two sources, summarises downstream impact, and estimates savings/effort.
  - `generate_optimization_proposal()` tailors guidance based on optimisation type (resource sizing, caching, partitioning, compression, scheduling, etc.).
  - `generate_decommission_proposal()` ensures replacements or migration notes are captured before marking for retirement.
  - `analyze_proposal_impact()` joins lineage counts and priority data to derive cost, latency, and risk estimates.
  - `prioritize_proposals()` assigns ROI scores, sorts the portfolio, and aggregates potential savings.
- Outputs are structured dictionaries that map directly back into the Pydantic proposal models.

### Update Utilities – `backend/agents/tools/update_tools.py`
- `update_object_priority()` performs SCD2-compliant updates on `etlobjectscd2`, records review metadata, and attempts an audit-table insert (gracefully handling the absence of the table).
- `create_lineage_edge()` validates object existence, enforces allowed edge types, and inserts a new entry into `etledges` with generated IDs and descriptive fields.
- `mark_for_decommission()` flips status flags, sets decommission metadata, and deactivates associated edges when possible.
- All functions rely on server-side SQL to centralise business logic in BigQuery; failures are surfaced via structured error dictionaries.

---

## BigQuery Integration & Configuration

- Default dataset is `minietl`; override via optional parameters for project-specific environments.
- Authentication expects `GOOGLE_APPLICATION_CREDENTIALS` to reference a service-account JSON with BigQuery read/write permissions.
- The schema assumes:
  - `etlobjectscd2` contains SCD2 history with `effective_end`, `status`, `priority`, architect annotations, and metadata columns referenced in queries.
  - `etledges` stores active dependency edges (`is_active` flag, `edge_type`, optional names).
  - Planned extensions (`architect_proposals`, `architect_audit_log`) are surfaced via schema constants in `models_adk.py` and referenced by update tools.
- Queries are parameterised through Python string formatting today; moving to parameterised queries is listed as a hardening task to avoid SQL injection on user-supplied inputs.

---

## Testing & Validation

- `backend/agents/test_architect_workflow.py` executes an end-to-end scenario over a live BigQuery project, exercising inventory analysis, proposal generation, workflow orchestration, and priority application.
- `backend/agents/tools/test_inventory_tools.py` validates dataset/table existence and key SQL queries (inventory counts, unreviewed objects, priority summaries, pattern searches).
- `backend/agents/tools/test_inventory_functions.py` invokes each inventory tool directly, logging sample outputs to confirm parsing and data-shaping logic.
- Tests require:
  - Python 3.11 virtual environment with `backend/requirements.txt`.
  - `GOOGLE_APPLICATION_CREDENTIALS` pointing at a non-production service account.
  - Access to the `prismatic-smoke-463810-c1.minietl` dataset (or equivalent staging project).
- Automation status: tests currently rely on print-driven assertions and real GCP resources. Migrating to pytest assertions with fixtures and recorded datasets is an explicit follow-up task.

---

## Current Limitations & Hardening Tasks

- SQL statements use string interpolation; introduce query parameters or templating with explicit binding.
- `agent_tool` decorator is a placeholder—replace with the real ADK decorator once the SDK is integrated.
- Error handling prints exceptions inline; formalise logging and exception propagation before exposing via the Flask API.
- Workflow currently simulates architect review rather than persisting selections; Phase 2 should connect to user input (API or Streamlit UI).
- Audit logging silently ignores insert failures; add telemetry so missing tables are surfaced during provisioning.
- Tests should decouple from production-like datasets and adopt pytest assertions to fit the repo’s testing guidelines.

---

## Next Milestones

1. Wire the architect workflow into `backend/syncflow_server.py` with secured endpoints that call `start_architect_review()` and `apply_architect_decision()`.
2. Surface proposal and review artefacts in the Streamlit dashboard (`frontend/dashboard.py`) using models from `shared/`.
3. Finalise BigQuery DDL for `architect_proposals` and `architect_audit_log`, and automate migrations in the MiniETL deployment pipeline.
4. Replace print logging with structured logging (e.g., `structlog`) and propagate trace IDs through the workflow.
5. Backfill pytest-based unit and integration coverage, targeting fixtures that emulate BigQuery responses where feasible.

---

The Foundation phase delivers a functional ADK-compatible architect agent with modular tooling across inventory, lineage, proposal, and update domains. With API integration, UI surfacing, and production hardening queued for Phase 2, the agent is positioned to support actionable architecture reviews on SyncFlow’s GCP footprint.

