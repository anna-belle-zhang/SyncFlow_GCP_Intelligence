#!/usr/bin/env python3
"""
Architect Agent - GCP Inventory Review & Prioritization

Implements the agentic prioritization workflow with human-in-the-loop confirmation.

Workflow:
1. Load the current SCD2 inventory snapshot from BigQuery.
2. Analyse usage, billing, and lineage data to propose priority updates.
3. Present proposals for architect confirmation or modification.
4. Persist approved decisions back to BigQuery with SCD2 semantics.
"""

import logging
import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)

VALID_PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
DECOMMISSION_TYPES = {"FUNCTION", "DATAFLOW", "WORKFLOW", "CLOUD_RUN", "TRIGGER"}


class ArchitectAgent:
    """Architect agent for inventory management and prioritization."""

    def __init__(self, bq_manager):
        """Initialize architect agent with BigQuery connection."""
        self.bq_manager = bq_manager
        self.project_id = bq_manager.project_id
        self.dataset_id = bq_manager.dataset_id

        # In-memory proposal store for the current interactive session.
        self._proposal_store: Dict[str, Dict[str, Any]] = {}
        self._object_to_proposal: Dict[str, str] = {}
        self._inventory_snapshot: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Inventory Loading & Summary
    # ------------------------------------------------------------------
    def load_inventory(self) -> Dict[str, Any]:
        """Return an aggregated view of the active inventory state."""

        summary_query = f"""
        -- load_inventory_summary
        SELECT
            priority,
            COUNT(*) AS object_count
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
        WHERE effective_end IS NULL
        GROUP BY priority
        """
        summary_rows = self._rows_to_dicts(
            self._run_query(summary_query).result()
        )

        unreviewed_query = f"""
        -- load_inventory_unreviewed
        SELECT
            object_id,
            name,
            object_type
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
        WHERE effective_end IS NULL
        AND (priority IS NULL OR priority = '')
        ORDER BY name
        LIMIT 25
        """
        unreviewed_rows = self._rows_to_dicts(
            self._run_query(unreviewed_query).result()
        )

        by_priority = defaultdict(int)
        total_objects = 0

        for row in summary_rows:
            priority = row.get("priority") or "UNREVIEWED"
            count = int(row.get("object_count") or 0)
            by_priority[priority] += count
            total_objects += count

        unreviewed_count = len(unreviewed_rows)
        reviewed_count = total_objects - unreviewed_count

        summary = {
            "total_objects": total_objects,
            "reviewed_count": reviewed_count,
            "unreviewed_count": unreviewed_count,
            "by_priority": dict(by_priority),
            "unreviewed_samples": unreviewed_rows,
            "generated_at": self._now_iso(),
        }

        self._inventory_snapshot = summary
        return summary

    def get_critical_high_summary(self) -> Dict[str, Any]:
        """Return usage and dependency insights for CRITICAL and HIGH objects."""

        inventory_query = f"""
        -- critical_high_inventory
        SELECT
            object_id,
            name,
            object_type,
            priority
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
        WHERE effective_end IS NULL
        AND priority IN ('CRITICAL', 'HIGH')
        """
        rows = self._rows_to_dicts(self._run_query(inventory_query).result())

        if not rows:
            return {
                "total_objects": 0,
                "total_cost_last_30_days": 0.0,
                "total_executions_last_30_days": 0,
                "by_priority": {},
                "objects": [],
                "generated_at": self._now_iso(),
            }

        object_ids = [row["object_id"] for row in rows]
        metrics = self._collect_metrics(object_ids)

        objects_summary: List[Dict[str, Any]] = []
        cost_total = 0.0
        executions_total = 0
        by_priority = defaultdict(int)

        for row in rows:
            obj_id = row["object_id"]
            obj_metrics = metrics.get(obj_id, {})
            cost_30 = float(obj_metrics.get("cost_last_30_days", 0.0) or 0.0)
            exec_30 = int(obj_metrics.get("executions_last_30_days", 0) or 0)

            objects_summary.append({
                "object_id": obj_id,
                "name": row.get("name"),
                "object_type": row.get("object_type"),
                "priority": row.get("priority"),
                "executions_last_30_days": exec_30,
                "cost_last_30_days": round(cost_30, 2),
                "downstream_dependencies": int(obj_metrics.get("downstream_dependents", 0) or 0),
                "last_run_date": obj_metrics.get("last_run_date"),
            })

            by_priority[row.get("priority")] += 1
            cost_total += cost_30
            executions_total += exec_30

        return {
            "total_objects": len(rows),
            "total_cost_last_30_days": round(cost_total, 2),
            "total_executions_last_30_days": executions_total,
            "by_priority": dict(by_priority),
            "objects": objects_summary,
            "generated_at": self._now_iso(),
        }

    # ------------------------------------------------------------------
    # Proposal Workflow
    # ------------------------------------------------------------------
    def propose_priority_changes(self) -> List[Dict[str, Any]]:
        """Analyse unreviewed objects and generate prioritization proposals."""

        candidates = self._fetch_unreviewed_objects()
        if not candidates:
            logger.info("No unreviewed objects found; nothing to propose.")
            return []

        object_ids = [row["object_id"] for row in candidates]
        metrics = self._collect_metrics(object_ids)

        proposals: List[Dict[str, Any]] = []
        for candidate in candidates:
            obj_id = candidate["object_id"]
            obj_metrics = metrics.get(obj_id, {})
            proposal = self._build_proposal_payload(candidate, obj_metrics)

            # Mark prior proposals for the same object as superseded
            existing_id = self._object_to_proposal.get(obj_id)
            if existing_id and existing_id in self._proposal_store:
                self._proposal_store[existing_id]["status"] = "superseded"

            self._proposal_store[proposal["proposal_id"]] = proposal
            self._object_to_proposal[obj_id] = proposal["proposal_id"]
            proposals.append(proposal)

        return proposals

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Return proposals awaiting an architect decision."""

        return [
            proposal
            for proposal in self._proposal_store.values()
            if proposal.get("status") == "pending"
        ]

    def get_proposal_details(self, proposal_id: str) -> Dict[str, Any]:
        """Fetch the detailed proposal context for a given identifier."""

        proposal = self._proposal_store.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found.")
        return proposal

    def architect_approves(self, proposal_id: str, architect_name: str) -> Dict[str, Any]:
        """Approve a proposal and persist the decision to BigQuery."""

        proposal = self.get_proposal_details(proposal_id)
        if proposal.get("status") != "pending":
            raise ValueError(f"Proposal {proposal_id} is not pending approval.")

        is_decommission = bool(proposal.get("decommission_candidate"))
        architect_notes = proposal.get("architect_notes") or proposal.get("reasoning") or ""

        self._update_scd2_with_review(
            object_id=proposal["object_id"],
            priority=proposal["proposed_priority"],
            architect_notes=architect_notes,
            is_decommission=is_decommission,
            decommission_reason=proposal.get("decommission_reason"),
            reviewed_by=architect_name,
            proposal_id=proposal_id,
            approval_status="approved",
        )

        proposal.update({
            "status": "approved",
            "approved_by": architect_name,
            "approved_at": self._now_iso(),
            "final_priority": proposal["proposed_priority"],
        })

        return proposal

    def architect_modifies(
        self,
        proposal_id: str,
        new_priority: str,
        architect_notes: str,
        architect_name: str,
        mark_decommission: bool = False,
        decommission_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Override a proposal with a different priority and optional notes."""

        if new_priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority '{new_priority}'. Expected one of {VALID_PRIORITIES}.")

        proposal = self.get_proposal_details(proposal_id)
        if proposal.get("status") != "pending":
            raise ValueError(f"Proposal {proposal_id} is not pending approval.")

        is_decommission = bool(mark_decommission)
        if is_decommission and not decommission_reason:
            raise ValueError("Decommission reason required when marking for removal.")

        self._update_scd2_with_review(
            object_id=proposal["object_id"],
            priority=new_priority,
            architect_notes=architect_notes,
            is_decommission=is_decommission,
            decommission_reason=decommission_reason,
            reviewed_by=architect_name,
            proposal_id=proposal_id,
            approval_status="modified",
        )

        proposal.update({
            "status": "modified",
            "approved_by": architect_name,
            "approved_at": self._now_iso(),
            "final_priority": new_priority,
            "architect_notes": architect_notes,
            "decommission_candidate": is_decommission,
            "decommission_reason": decommission_reason,
        })

        return proposal

    def add_notes(self, proposal_id: str, architect_notes: str) -> Dict[str, Any]:
        """Attach additional context to a pending proposal."""

        proposal = self.get_proposal_details(proposal_id)
        if proposal.get("status") != "pending":
            raise ValueError("Notes can only be added to pending proposals.")

        proposal["architect_notes"] = architect_notes
        proposal["notes_updated_at"] = self._now_iso()
        return proposal

    # ------------------------------------------------------------------
    # Backwards compatible utilities & legacy entry points
    # ------------------------------------------------------------------
    def review_object(
        self,
        object_id: str,
        priority: str,
        architect_notes: str,
        is_decommission: bool = False,
        decommission_reason: Optional[str] = None,
        reviewed_by: str = "architect_agent",
    ) -> Dict[str, Any]:
        """Directly review and prioritise an object without a proposal."""

        logger.info("Architect reviewing object %s with priority %s", object_id, priority)

        if priority not in VALID_PRIORITIES:
            return {
                "status": "error",
                "message": f"Invalid priority. Must be one of: {VALID_PRIORITIES}",
            }

        if is_decommission and not decommission_reason:
            return {
                "status": "error",
                "message": "decommission_reason required when marking for decommission",
            }

        try:
            self._update_scd2_with_review(
                object_id=object_id,
                priority=priority,
                architect_notes=architect_notes,
                is_decommission=is_decommission,
                decommission_reason=decommission_reason,
                reviewed_by=reviewed_by,
                proposal_id=None,
                approval_status="manual",
            )

            return {
                "status": "success",
                "object_id": object_id,
                "priority": priority,
                "is_decommission": is_decommission,
                "message": f"Object {object_id} reviewed and updated",
                "next_steps": self._get_next_steps(priority, is_decommission),
                "timestamp": self._now_iso(),
            }

        except Exception as exc:  # pragma: no cover - BigQuery error propagation
            logger.error("Error reviewing object %s: %s", object_id, exc)
            return {
                "status": "error",
                "object_id": object_id,
                "message": str(exc),
            }

    def get_priority_summary(self) -> Dict[str, Any]:
        """Get summary of all objects by priority level."""

        query = f"""
        -- legacy_priority_summary
        SELECT
            priority,
            is_decommission,
            COUNT(*) AS count
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
        WHERE effective_end IS NULL
        GROUP BY priority, is_decommission
        """

        rows = self._rows_to_dicts(self._run_query(query).result())

        summary = {
            "CRITICAL": {"count": 0, "decommission": 0},
            "HIGH": {"count": 0, "decommission": 0},
            "MEDIUM": {"count": 0, "decommission": 0},
            "LOW": {"count": 0, "decommission": 0},
            "total": 0,
            "unreviewed": 0,
        }

        for row in rows:
            priority = row.get("priority") or "UNREVIEWED"
            count = int(row.get("count") or 0)
            is_decommission = bool(row.get("is_decommission"))

            if priority in summary:
                key = "decommission" if is_decommission else "count"
                summary[priority][key] = count
                summary["total"] += count

        summary["unreviewed"] = summary["total"] - sum(
            summary[level]["count"] for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        )
        return summary

    def get_decommission_candidates(self) -> List[Dict[str, Any]]:
        """Get all objects currently marked for decommission."""

        query = f"""
        -- decommission_candidates
        SELECT
            object_id,
            name,
            object_type,
            decommission_reason,
            architect_notes,
            architect_review_timestamp,
            architect_reviewed_by
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
        AND is_decommission = TRUE
        ORDER BY architect_review_timestamp DESC
        """

        return self._rows_to_dicts(self._run_query(query).result())

    def get_critical_objects(self) -> List[Dict[str, Any]]:
        """Get all CRITICAL priority objects for Ops/FinOps focus."""

        query = f"""
        -- critical_objects
        SELECT
            object_id,
            name,
            object_type,
            status,
            priority,
            architect_notes,
            architect_reviewed_by
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
        AND priority = 'CRITICAL'
        ORDER BY object_id
        """

        return self._rows_to_dicts(self._run_query(query).result())

    # ------------------------------------------------------------------
    # BigQuery persistence
    # ------------------------------------------------------------------
    def _update_scd2_with_review(
        self,
        object_id: str,
        priority: str,
        architect_notes: str,
        is_decommission: bool,
        decommission_reason: Optional[str],
        reviewed_by: str,
        proposal_id: Optional[str],
        approval_status: Optional[str],
    ) -> None:
        """Write architect review data to object_priority_overrides table.

        Does NOT modify etlobjectscd2 (core table). Only writes user overrides.
        """

        approval_status = approval_status or "manual"

        # Verify object exists in etlobjectscd2 (read-only check)
        verify_query = f"""
        SELECT object_id FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
        WHERE object_id = @object_id AND effective_end IS NULL
        """

        verify_job = self._run_query(
            verify_query,
            [
                bigquery.ScalarQueryParameter("object_id", "STRING", object_id),
            ],
        )
        verify_rows = list(verify_job.result())

        if not verify_rows:
            raise ValueError(f"Object {object_id} not found in etlobjectscd2")

        # Insert architect decision to object_priority_overrides table
        insert_query = f"""
        -- insert_architect_override
        INSERT INTO `{self.project_id}.{self.dataset_id}.object_priority_overrides` (
            object_id,
            priority,
            is_decommission,
            decommission_reason,
            architect_notes,
            architect_review_timestamp,
            architect_reviewed_by,
            architect_approval_id,
            architect_approval_status,
            architect_approval_timestamp,
            updated_by,
            updated_at
        )
        VALUES (
            @object_id,
            @priority,
            @is_decommission,
            @decommission_reason,
            @architect_notes,
            CURRENT_TIMESTAMP(),
            @reviewed_by,
            @proposal_id,
            @approval_status,
            CURRENT_TIMESTAMP(),
            @reviewed_by,
            CURRENT_TIMESTAMP()
        )
        """

        insert_params = [
            bigquery.ScalarQueryParameter("object_id", "STRING", object_id),
            bigquery.ScalarQueryParameter("priority", "STRING", priority),
            bigquery.ScalarQueryParameter("is_decommission", "BOOL", is_decommission),
            bigquery.ScalarQueryParameter("decommission_reason", "STRING", decommission_reason or ""),
            bigquery.ScalarQueryParameter("architect_notes", "STRING", architect_notes or ""),
            bigquery.ScalarQueryParameter("reviewed_by", "STRING", reviewed_by),
            bigquery.ScalarQueryParameter("proposal_id", "STRING", proposal_id or ""),
            bigquery.ScalarQueryParameter("approval_status", "STRING", approval_status),
        ]
        self._run_query(insert_query, insert_params).result()

        logger.info(
            "Updated architect override for %s: priority=%s, decommission=%s, reviewed_by=%s",
            object_id,
            priority,
            is_decommission,
            reviewed_by,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_unreviewed_objects(self) -> List[Dict[str, Any]]:
        """Retrieve active objects without a priority assignment."""

        query = f"""
        -- unreviewed_objects
        SELECT
            object_id,
            name,
            object_type,
            parent_id,
            metadata
        FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2`
        WHERE effective_end IS NULL
        AND (priority IS NULL OR priority = '')
        ORDER BY name
        """

        return self._rows_to_dicts(self._run_query(query).result())

    def _collect_metrics(self, object_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Aggregate execution, cost, and dependency metrics for object IDs."""

        if not object_ids:
            return {}

        metrics: Dict[str, Dict[str, Any]] = defaultdict(dict)
        array_param = bigquery.ArrayQueryParameter("object_ids", "STRING", object_ids)

        exec_query = f"""
        -- execution_stats
        SELECT
            object_id,
            COUNT(*) AS executions_last_90_days,
            COUNTIF(run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)) AS executions_last_30_days,
            COUNTIF(run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) AS executions_last_7_days,
            MAX(run_date) AS last_run_date,
            AVG(duration_min) AS avg_duration_min
        FROM `{self.project_id}.{self.dataset_id}.factlog`
        WHERE object_id IN UNNEST(@object_ids)
        AND run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
        GROUP BY object_id
        """
        for row in self._rows_to_dicts(self._run_query(exec_query, [array_param]).result()):
            obj_id = row["object_id"]
            metrics[obj_id].update({
                "executions_last_90_days": int(row.get("executions_last_90_days") or 0),
                "executions_last_30_days": int(row.get("executions_last_30_days") or 0),
                "executions_last_7_days": int(row.get("executions_last_7_days") or 0),
                "last_run_date": self._format_date(row.get("last_run_date")),
                "avg_duration_min": float(row.get("avg_duration_min") or 0.0),
            })

        cost_query = f"""
        -- cost_stats
        SELECT
            object_id,
            SUM(cost_usd) AS cost_last_30_days,
            SUM(IF(run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY), cost_usd, 0)) AS cost_last_7_days
        FROM `{self.project_id}.{self.dataset_id}.factbilling`
        WHERE object_id IN UNNEST(@object_ids)
        AND run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        GROUP BY object_id
        """
        for row in self._rows_to_dicts(self._run_query(cost_query, [array_param]).result()):
            obj_id = row["object_id"]
            metrics[obj_id].update({
                "cost_last_30_days": float(row.get("cost_last_30_days") or 0.0),
                "cost_last_7_days": float(row.get("cost_last_7_days") or 0.0),
            })

        dep_query = f"""
        -- dependency_stats
        SELECT
            source_object_id AS object_id,
            COUNT(*) AS downstream_dependents
        FROM `{self.project_id}.{self.dataset_id}.etledges`
        WHERE source_object_id IN UNNEST(@object_ids)
        AND is_active = TRUE
        GROUP BY source_object_id
        """
        for row in self._rows_to_dicts(self._run_query(dep_query, [array_param]).result()):
            obj_id = row["object_id"]
            metrics[obj_id].update({
                "downstream_dependents": int(row.get("downstream_dependents") or 0),
            })

        return metrics

    def _build_proposal_payload(
        self,
        obj: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a structured proposal payload with reasoning."""

        priority, reasoning, confidence, decomm_candidate, decomm_reason = self._determine_priority(
            obj,
            metrics,
        )

        proposal_id = f"PROP-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "proposal_id": proposal_id,
            "object_id": obj.get("object_id"),
            "object_name": obj.get("name"),
            "object_type": obj.get("object_type"),
            "proposed_priority": priority,
            "confidence_score": confidence,
            "reasoning": reasoning,
            "metrics": metrics,
            "architect_notes": "",
            "decommission_candidate": decomm_candidate,
            "decommission_reason": decomm_reason,
            "status": "pending",
            "created_at": self._now_iso(),
        }

        if metrics.get("last_run_date"):
            payload["last_run_date"] = metrics["last_run_date"]
        return payload

    def _determine_priority(
        self,
        obj: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> Tuple[str, str, float, bool, Optional[str]]:
        """Derive a priority recommendation based on usage and impact."""

        freq_30 = int(metrics.get("executions_last_30_days") or 0)
        cost_30 = float(metrics.get("cost_last_30_days") or 0.0)
        deps = int(metrics.get("downstream_dependents") or 0)
        avg_duration = float(metrics.get("avg_duration_min") or 0.0)
        last_run_str = metrics.get("last_run_date")

        high_freq = freq_30 >= 20
        medium_freq = 8 <= freq_30 < 20
        high_cost = cost_30 >= 500.0
        medium_cost = 100.0 <= cost_30 < 500.0
        heavy_deps = deps >= 5
        medium_deps = 1 <= deps < 5

        if high_freq and high_cost and heavy_deps:
            priority = "CRITICAL"
        elif (
            (high_freq and medium_cost and medium_deps)
            or (medium_freq and high_cost)
            or (medium_freq and medium_cost and medium_deps)
        ):
            priority = "HIGH"
        elif medium_freq or medium_cost or medium_deps:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        reasoning_parts = [
            f"{freq_30} executions (30d)",
            f"${cost_30:,.2f} cost (30d)",
            f"{deps} downstream deps",
        ]
        if avg_duration:
            reasoning_parts.append(f"{avg_duration:.1f}m avg duration")
        if last_run_str:
            reasoning_parts.append(f"last run {last_run_str}")

        reasoning = "; ".join(reasoning_parts)

        # Confidence is weighted across execution, cost, and dependency signals.
        freq_score = min(freq_30 / 30.0, 1.0)
        cost_score = min(cost_30 / 500.0, 1.0)
        dep_score = min(deps / 5.0, 1.0)
        confidence = round(min(1.0, 0.45 * freq_score + 0.35 * cost_score + 0.2 * dep_score), 2)

        last_run_date = None
        if last_run_str:
            try:
                last_run_date = datetime.fromisoformat(str(last_run_str)).date()
            except ValueError:
                last_run_date = None

        days_since_last_run = None
        if last_run_date:
            days_since_last_run = (date.today() - last_run_date).days

        decommission_candidate = (
            (metrics.get("executions_last_90_days") in (None, 0))
            and deps == 0
            and (obj.get("object_type") or "").upper() in DECOMMISSION_TYPES
        )
        if days_since_last_run is not None and days_since_last_run > 90 and deps == 0:
            decommission_candidate = True

        decommission_reason = None
        if decommission_candidate:
            decommission_reason = (
                "No executions in 90 days and no downstream dependencies."
            )

        return priority, reasoning, confidence, decommission_candidate, decommission_reason

    def _get_next_steps(self, priority: str, is_decommission: bool) -> Dict[str, Any]:
        """Get next steps based on priority assignment."""

        steps = {
            "ops_focus": "",
            "finops_focus": "",
            "decommission_action": None,
        }

        if priority == "CRITICAL":
            steps["ops_focus"] = (
                "Ops Agent will closely monitor this object. Anomaly detection enabled with aggressive thresholds."
            )
            steps["finops_focus"] = (
                "FinOps Agent will prioritise cost optimisation. High-value target for savings."
            )
        elif priority in ("HIGH", "MEDIUM"):
            steps["ops_focus"] = (
                "Ops Agent includes in regular monitoring with standard thresholds."
            )
            steps["finops_focus"] = (
                "FinOps Agent tracks costs and surfaces optimisation opportunities."
            )
        else:
            steps["ops_focus"] = (
                "Ops Agent conducts minimal monitoring due to lower business impact."
            )
            steps["finops_focus"] = (
                "FinOps Agent deprioritises optimisation; focus remains on higher impact objects."
            )

        if is_decommission:
            steps["decommission_action"] = {
                "status": "marked_for_removal",
                "next_step": "Validate no active dependencies before removal",
                "timeline": "Schedule consolidation/removal in next maintenance window",
            }

        return steps

    def _run_query(
        self,
        query: str,
        parameters: Optional[List[Any]] = None,
    ):
        """Wrapper to execute a BigQuery query with optional parameters."""

        job_config = None
        if parameters:
            job_config = bigquery.QueryJobConfig()
            job_config.query_parameters = parameters

        return self.bq_manager.client.query(query, job_config=job_config)

    @staticmethod
    def _rows_to_dicts(rows: Any) -> List[Dict[str, Any]]:
        """Convert iterable BigQuery rows to dictionaries."""

        result = []
        for row in rows:
            if hasattr(row, "items"):
                result.append(dict(row.items()))
            else:
                result.append(dict(row))
        return result

    @staticmethod
    def _format_date(value: Any) -> Optional[str]:
        """Convert a date-like BigQuery value to ISO string."""

        if value is None:
            return None

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        try:
            return datetime.fromisoformat(str(value)).date().isoformat()
        except ValueError:
            return str(value)

    @staticmethod
    def _now_iso() -> str:
        """Return the current UTC timestamp in ISO format."""

        return datetime.utcnow().isoformat()


__all__ = ["ArchitectAgent"]
