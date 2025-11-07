#!/usr/bin/env python3
"""
SyncFlow GCP Intelligence - Integrated Backend Server

Combines:
1. Mini ETL metadata management (objects, lineage, costs)
2. Multi-Agent Architecture (DocAgent, LogAgent, CloudFnOAgent)
3. Execution monitoring and analytics
4. Cost analysis and optimization

Entry Point for both WSL backend and local frontend dashboard.
"""

import os
import json
import logging
import re
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime, timedelta
from uuid import uuid4
from functools import lru_cache

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from google.oauth2 import service_account
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

# Import Mini ETL modules
from bigquery_loader import BigQueryManager, setup_from_service_account
from billing_extractor import BillingExtractor
from logs_explorer import LogsExplorer, LogFilter
from architect_agent import ArchitectAgent
try:
    from agents.architect_agent_adk import (
        create_architect_workflow,
        start_architect_review,
    )
    from agents.models_adk import Priority as ArchitectPriority
except ImportError:
    # ADK agents optional - continue without them
    create_architect_workflow = None
    start_architect_review = None
    ArchitectPriority = None

from app.storage.bigquery import BigQueryStorage, StorageError, NotFoundError

if TYPE_CHECKING:
    from app.core.config import AppSettings

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MultiAgentAnalyzer:
    """Orchestrates the three specialized agents for analysis."""

    MERMAID_EDGE_PATTERN = re.compile(
        r'^\s*([A-Za-z0-9_]+)\s*-->\s*(?:\|([^|]+)\|\s*)?([A-Za-z0-9_]+)'
    )
    MERMAID_NODE_PATTERN = re.compile(
        r'^\s*([A-Za-z0-9_]+)\s*\[\s*["\']?([^"\']*?)["\']?\s*\]'
    )
    OBJECT_ID_PATTERN = re.compile(r'\bOBJ(\d{1,6})\b', re.IGNORECASE)

    def __init__(self, bq_manager: BigQueryManager):
        self.bq_manager = bq_manager
        self.client = bq_manager.client
        self.dataset_id = bq_manager.dataset_id
        self._table_schema_cache: Dict[str, Dict[str, bigquery.SchemaField]] = {}

    def _get_table_schema(self, table_name: str) -> Dict[str, bigquery.SchemaField]:
        """Fetch and cache BigQuery table schema."""
        table_path = f"{self.bq_manager.project_id}.{self.dataset_id}.{table_name}"
        cache_key = table_path.lower()
        schema = self._table_schema_cache.get(cache_key)
        if schema is None:
            try:
                table = self.client.get_table(table_path)
            except NotFound:
                schema = {}
            else:
                schema = {field.name.lower(): field for field in table.schema}
            self._table_schema_cache[cache_key] = schema
        return schema

    def _table_has_column(self, table_name: str, column_name: str) -> bool:
        """Return True if the specified table contains the column (cached)."""
        schema = self._get_table_schema(table_name)
        return column_name.lower() in schema

    def _parse_mermaid_diagram(self, diagram_text: str) -> Dict[str, Any]:
        """Extract nodes and edges from a Mermaid flowchart."""
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        for raw_line in (diagram_text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("%"):
                continue

            edge_match = self.MERMAID_EDGE_PATTERN.match(line)
            if edge_match:
                src, label, dst = edge_match.groups()
                edges.append({
                    "source": src,
                    "target": dst,
                    "label": label.strip() if label else None,
                })
                nodes.setdefault(src, {"id": src, "label": None})
                nodes.setdefault(dst, {"id": dst, "label": None})
                continue

            node_match = self.MERMAID_NODE_PATTERN.match(line)
            if node_match:
                node_id, label = node_match.groups()
                nodes.setdefault(node_id, {"id": node_id, "label": label.strip() or None})

        ordered_nodes = sorted(nodes.values(), key=lambda item: item["id"])
        return {"nodes": ordered_nodes, "edges": edges}

    def _extract_object_ids_from_prompt(self, prompt: Optional[str]) -> List[str]:
        """Return canonical OBJ identifiers referenced within the prompt."""
        if not prompt:
            return []
        matches = self.OBJECT_ID_PATTERN.findall(prompt)
        object_ids = [f"OBJ{int(match):04d}" for match in matches]
        return object_ids

    def _normalize_object_id(self, raw: Optional[str]) -> Optional[str]:
        """Normalize raw identifiers into OBJ0001 form if possible."""
        if not raw:
            return None
        cleaned = raw.strip().upper()
        if not cleaned:
            return None

        obj_match = re.fullmatch(r"OBJ(\d{1,6})", cleaned)
        if obj_match:
            return f"OBJ{int(obj_match.group(1)):04d}"

        if cleaned.isdigit():
            return f"OBJ{int(cleaned):04d}"

        return None

    def _fetch_enriched_context(
        self,
        object_ids: List[str],
        available_columns: List[str],
    ) -> List[Dict[str, Any]]:
        """Fetch enriched object records for the given identifiers."""
        if not object_ids:
            return []

        unique_ids = sorted({obj_id.upper() for obj_id in object_ids if obj_id})
        if not unique_ids:
            return []

        select_columns = [col for col in available_columns if col]
        if not select_columns:
            select_columns = ["object_id"]

        context_query = f"""
        SELECT {', '.join(select_columns)}
        FROM `{self.bq_manager.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
        WHERE object_id IN UNNEST(@object_ids)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("object_ids", "STRING", unique_ids)
            ]
        )
        results = self.client.query(context_query, job_config=job_config).result()
        rows = [dict(row) for row in results]
        rows_by_id = {row.get("object_id", "").upper(): row for row in rows}

        ordered_rows = [rows_by_id[obj_id] for obj_id in unique_ids if obj_id in rows_by_id]
        return ordered_rows

    def _gather_architect_context(
        self,
        primary_id: Optional[str],
        prompt: Optional[str],
        base_snapshot: Optional[Dict[str, Any]] = None,
        additional_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Aggregate enriched context, diagrams, and related objects."""
        primary_upper = (primary_id or "").upper()
        prompt_ids = self._extract_object_ids_from_prompt(prompt)

        related_ids: List[str] = []
        if primary_upper:
            related_ids.append(primary_upper)
        for pid in prompt_ids:
            upper = pid.upper()
            if upper and upper not in related_ids:
                related_ids.append(upper)
        if additional_ids:
            for extra in additional_ids:
                upper = (extra or "").upper()
                if upper and upper not in related_ids:
                    related_ids.append(upper)

        diagram_summary = None
        diagram_records: List[Dict[str, Any]] = []
        diagram_network: Optional[Dict[str, Any]] = None
        diagram_schema = self._get_table_schema("architect_diagrams")

        if diagram_schema:
            diagram_keys_set: set[str] = set()
            if primary_upper:
                diagram_keys_set.add(primary_upper)
            for pid in prompt_ids:
                if pid:
                    diagram_keys_set.add(pid.upper())
            diagram_keys = sorted(diagram_keys_set)

            if diagram_keys:
                diagram_query = f"""
                SELECT
                    diagram_id,
                    object_id,
                    diagram_name,
                    diagram_format,
                    diagram_text,
                    is_active,
                    generated_at
                FROM `{self.bq_manager.project_id}.{self.dataset_id}.architect_diagrams`
                WHERE UPPER(object_id) IN UNNEST(@diagram_keys)
                ORDER BY generated_at DESC
                LIMIT 5
                """
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ArrayQueryParameter("diagram_keys", "STRING", diagram_keys)
                    ]
                )
                diagram_result = self.client.query(diagram_query, job_config=job_config).result()
                diagram_records = [dict(row) for row in diagram_result]

            if not diagram_records:
                search_terms = [primary_upper, *prompt_ids]
                search_terms = sorted({term for term in search_terms if term})
                if search_terms:
                    pattern = "(" + "|".join(re.escape(term.upper()) for term in search_terms) + ")"
                    fallback_query = f"""
                    SELECT
                        diagram_id,
                        object_id,
                        diagram_name,
                        diagram_format,
                        diagram_text,
                        is_active,
                        generated_at
                    FROM `{self.bq_manager.project_id}.{self.dataset_id}.architect_diagrams`
                    WHERE REGEXP_CONTAINS(UPPER(diagram_text), @diagram_pattern)
                    ORDER BY generated_at DESC
                    LIMIT 5
                    """
                    job_config = bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter("diagram_pattern", "STRING", pattern)
                        ]
                    )
                    diagram_result = self.client.query(fallback_query, job_config=job_config).result()
                    diagram_records = [dict(row) for row in diagram_result]

        if diagram_records:
            diagram_summary = diagram_records[0]
            diagram_network = self._parse_mermaid_diagram(diagram_summary.get("diagram_text", ""))
            for node in diagram_network.get("nodes", []):
                node_id = (node.get("id") or "").upper()
                if node_id.startswith("OBJ") and node_id not in related_ids:
                    related_ids.append(node_id)

        enriched_schema = self._get_table_schema("etlobjectscd2_enriched")
        candidate_columns = [
            "object_id",
            "object_type",
            "name",
            "status",
            "priority",
            "priority_updated_by",
            "priority_updated_at",
            "architect_notes",
            "architect_reviewed_by",
            "architect_review_timestamp",
            "is_decommission",
            "decommission_reason",
            "effective_start",
            "schedule_time",
            "metadata",
        ]
        available_columns = [
            column for column in candidate_columns
            if column.lower() in enriched_schema
        ]
        context_rows = self._fetch_enriched_context(related_ids, available_columns)

        snapshot = dict(base_snapshot) if base_snapshot else None
        if not snapshot:
            snapshot = next(
                (
                    record for record in context_rows
                    if (record.get("object_id") or "").upper() == primary_upper
                ),
                None,
            )
        elif context_rows:
            for record in context_rows:
                if (record.get("object_id") or "").upper() == primary_upper:
                    for field in (
                        "priority",
                        "status",
                        "schedule_time",
                        "architect_notes",
                        "architect_reviewed_by",
                        "architect_review_timestamp",
                        "priority_updated_by",
                        "priority_updated_at",
                    ):
                        if not snapshot.get(field) and record.get(field):
                            snapshot[field] = record.get(field)
                    break

        return {
            "snapshot": snapshot,
            "diagram_summary": diagram_summary,
            "diagram_history": diagram_records,
            "diagram_network": diagram_network,
            "object_context": context_rows,
            "related_object_ids": related_ids,
            "prompt_object_ids": prompt_ids,
        }

    def doc_agent_analysis(self, object_id: str, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        DocAgent - Configuration Change Detection

        Analyzes SCD Type 2 history to detect configuration changes,
        surfaces related inventory context, and attaches latest architecture
        diagrams so UI can answer architecture questions.
        """
        logger.info(f"DocAgent analyzing {object_id}")

        table_name = "etlobjectscd2"
        prompt_ids = self._extract_object_ids_from_prompt(prompt)
        primary_id = object_id.upper()
        schema = self._get_table_schema(table_name)
        schedule_exists = "schedule_time" in schema
        metadata_exists = "metadata" in schema
        metadata_is_json = (
            metadata_exists and schema["metadata"].field_type.upper() == "JSON"
        )

        if metadata_exists:
            metadata_expr = "TO_JSON_STRING(metadata)" if metadata_is_json else "CAST(metadata AS STRING)"
        else:
            metadata_expr = None

        history_select_parts = [
            "object_id",
            "object_type",
            "name",
            "effective_start",
            "effective_end",
            "version",
        ]

        if schedule_exists:
            history_select_parts.append("schedule_time")
            history_select_parts.append(
                "LAG(schedule_time) OVER (PARTITION BY object_id ORDER BY effective_start) AS prev_schedule"
            )
        else:
            history_select_parts.append("NULL AS schedule_time")
            history_select_parts.append("NULL AS prev_schedule")

        if metadata_expr:
            history_select_parts.append(f"{metadata_expr} AS metadata_snapshot")
            history_select_parts.append(
                f"LAG({metadata_expr}) OVER (PARTITION BY object_id ORDER BY effective_start) AS prev_metadata_snapshot"
            )
        else:
            history_select_parts.append("NULL AS metadata_snapshot")
            history_select_parts.append("NULL AS prev_metadata_snapshot")

        history_select_parts.append("status")
        history_select = ",\n                ".join(history_select_parts)

        change_case_lines = ["CASE"]
        if schedule_exists:
            change_case_lines.append(
                "    WHEN schedule_time IS DISTINCT FROM prev_schedule THEN 'Schedule Changed'"
            )
        if metadata_expr:
            change_case_lines.append(
                "    WHEN metadata_snapshot IS DISTINCT FROM prev_metadata_snapshot THEN 'Metadata Changed'"
            )
        change_case_lines.append("    ELSE 'Minor Update'")
        change_case_lines.append("END as change_type")
        change_case = "\n                ".join(change_case_lines)

        change_select_parts = [
            "object_id",
            "object_type",
            "name",
            "effective_start",
            "effective_end",
            "version",
            "schedule_time",
            "prev_schedule",
            change_case,
            "status",
        ]
        change_select = ",\n                ".join(change_select_parts)

        change_conditions: List[str] = []
        if schedule_exists:
            change_conditions.append("schedule_time IS DISTINCT FROM prev_schedule")
        if metadata_expr:
            change_conditions.append("metadata_snapshot IS DISTINCT FROM prev_metadata_snapshot")
        change_predicate = " OR ".join(change_conditions) if change_conditions else "FALSE"

        enriched_schema = self._get_table_schema("etlobjectscd2_enriched")
        summary_columns: List[str] = []
        for column in (
            "object_id",
            "name",
            "object_type",
            "priority",
            "status",
            "schedule_time",
            "priority_updated_by",
            "priority_updated_at",
        ):
            if column.lower() in enriched_schema:
                summary_columns.append(column)
        if not summary_columns:
            summary_columns = ["object_id"]

        query = f"""
        WITH object_history AS (
            SELECT
                {history_select}
            FROM `{self.bq_manager.project_id}.{self.dataset_id}.{table_name}`
            WHERE object_id = '{object_id}'
        ),
        changes AS (
            SELECT
                {change_select}
            FROM object_history
            WHERE version > 1 AND ({change_predicate})
        )
        SELECT * FROM changes ORDER BY effective_start DESC LIMIT 10
        """

        try:
            summary_query = f"""
            SELECT {', '.join(summary_columns)}
            FROM `{self.bq_manager.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
            WHERE object_id = '{object_id}'
            LIMIT 1
            """
            summary_result = self.client.query(summary_query).result()
            snapshot = next((dict(row) for row in summary_result), None)

            results = self.client.query(query).result()
            changes = [dict(row) for row in results]

            context = self._gather_architect_context(primary_id, prompt, base_snapshot=snapshot)
            snapshot = context.get("snapshot")
            diagram_summary = context.get("diagram_summary")
            diagram_records = context.get("diagram_history", [])
            diagram_network = context.get("diagram_network")
            context_rows = context.get("object_context", [])
            related_object_ids = context.get("related_object_ids", [])
            prompt_ids = context.get("prompt_object_ids", prompt_ids)

            return {
                "agent": "DocAgent",
                "object_id": object_id,
                "analysis_type": "Configuration Change Detection",
                "recent_changes": changes,
                "object_snapshot": snapshot,
                "downstream_impact": [],
                "diagram_summary": diagram_summary,
                "diagram_history": diagram_records,
                "diagram_network": diagram_network,
                "related_object_ids": related_object_ids,
                "prompt_object_ids": prompt_ids,
                "prompt_text": prompt,
                "object_context": context_rows,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"DocAgent error: {e}")
            return {"error": str(e), "agent": "DocAgent"}

    def log_agent_analysis(self, object_id: str, days: int = 7, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        LogAgent - Performance Analysis & Anomaly Detection

        Analyzes execution logs to detect performance improvements/degradations,
        timing anomalies, and optimization opportunities.
        """
        logger.info(f"LogAgent analyzing {object_id} for {days} days")

        normalized_id = self._normalize_object_id(object_id)
        portfolio_summary: List[Dict[str, Any]] = []
        lookback_days = max(1, min(180, int(days or 7)))

        if not normalized_id:
            logger.info("No object identifier provided; aggregating factlog portfolio metrics.")
            agg_query = f"""
            SELECT
                object_id,
                COUNT(*) AS total_executions,
                COUNTIF(status = 'success') AS successful_runs,
                SAFE_DIVIDE(COUNTIF(status = 'success'), COUNT(*)) AS success_rate,
                AVG(duration_seconds) AS avg_duration,
                MAX(duration_seconds) AS peak_duration,
                SUM(rows_processed) AS total_rows
            FROM `{self.bq_manager.project_id}.{self.dataset_id}.factlog`
            WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
                AND object_id IS NOT NULL
            GROUP BY object_id
            ORDER BY total_executions DESC
            LIMIT 5
            """
            agg_results = self.client.query(agg_query).result()
            portfolio_summary = [dict(row) for row in agg_results]
            if portfolio_summary:
                normalized_id = self._normalize_object_id(portfolio_summary[0].get("object_id"))
            else:
                normalized_id = None

        query = f"""
        WITH daily_metrics AS (
            SELECT
                DATE(created_at) as run_date,
                object_id,
                COUNT(*) as executions,
                COUNTIF(status = 'success') as successful,
                AVG(duration_seconds) as avg_duration,
                MIN(duration_seconds) as min_duration,
                MAX(duration_seconds) as max_duration,
                SUM(rows_processed) as total_rows,
                AVG(rows_processed) as avg_throughput
            FROM `{self.bq_manager.project_id}.{self.dataset_id}.factlog`
            WHERE object_id = '{normalized_id}'
                AND DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
            GROUP BY run_date, object_id
        ),
        anomalies AS (
            SELECT
                run_date,
                object_id,
                avg_duration,
                PERCENTILE_CONT(avg_duration, 0.9) OVER () as p90_duration,
                CASE
                    WHEN avg_duration > PERCENTILE_CONT(avg_duration, 0.9) OVER () THEN 'Slow'
                    WHEN avg_duration < PERCENTILE_CONT(avg_duration, 0.1) OVER () THEN 'Fast'
                    ELSE 'Normal'
                END as performance_status
            FROM daily_metrics
        )
        SELECT * FROM anomalies ORDER BY run_date DESC
        """

        try:
            metrics: List[Dict[str, Any]] = []
            if normalized_id:
                results = self.client.query(query).result()
                metrics = [dict(row) for row in results]
            else:
                logger.info("No execution records located for portfolio window.")

            # Calculate trend
            if len(metrics) >= 2:
                first_week = metrics[-7:] if len(metrics) >= 7 else metrics
                recent = metrics[:7] if len(metrics) >= 7 else metrics

                avg_first = sum(m['avg_duration'] for m in first_week) / len(first_week) if first_week else 0
                avg_recent = sum(m['avg_duration'] for m in recent) / len(recent) if recent else 0

                improvement_pct = ((avg_first - avg_recent) / avg_first * 100) if avg_first > 0 else 0
            else:
                improvement_pct = 0

            additional_ids = [entry.get("object_id") for entry in portfolio_summary[1:]] if portfolio_summary else None
            context = self._gather_architect_context(normalized_id, prompt, additional_ids=additional_ids)
            return {
                "agent": "LogAgent",
                "object_id": normalized_id or object_id,
                "analysis_type": "Performance Analysis",
                "daily_metrics": metrics,
                "trend_improvement_percent": round(improvement_pct, 1),
                "portfolio_summary": portfolio_summary,
                "object_snapshot": context.get("snapshot"),
                "diagram_summary": context.get("diagram_summary"),
                "diagram_history": context.get("diagram_history", []),
                "diagram_network": context.get("diagram_network"),
                "object_context": context.get("object_context", []),
                "related_object_ids": context.get("related_object_ids", []),
                "prompt_object_ids": context.get("prompt_object_ids", []),
                "prompt_text": prompt,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"LogAgent error: {e}")
            return {"error": str(e), "agent": "LogAgent"}

    def cloud_fn_agent_analysis(self, object_id: str, days: int = 30, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        CloudFnOAgent - Cost Analysis & Financial Optimization

        Analyzes billing data to track costs, identify savings opportunities,
        and correlate costs with configuration changes.
        """
        logger.info(f"CloudFnOAgent analyzing {object_id} for {days} days")

        normalized_id = self._normalize_object_id(object_id)
        portfolio_summary: List[Dict[str, Any]] = []

        lookback_days = max(1, min(365, int(days or 30)))

        if not normalized_id:
            logger.info("No object identifier provided; running portfolio spend aggregation.")
            agg_query = f"""
            SELECT
                object_id,
                SUM(cost_usd) AS total_cost,
                AVG(cost_usd) AS avg_event_cost,
                SUM(cost_usd) / NULLIF(COUNT(DISTINCT DATE(run_date)), 0) AS avg_daily_cost,
                COUNT(*) AS record_count
            FROM `{self.bq_manager.project_id}.{self.dataset_id}.factbilling`
            WHERE DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
                AND object_id IS NOT NULL
            GROUP BY object_id
            ORDER BY total_cost DESC
            LIMIT 5
            """
            agg_results = self.client.query(agg_query).result()
            portfolio_summary = [dict(row) for row in agg_results]
            if portfolio_summary:
                normalized_id = self._normalize_object_id(portfolio_summary[0].get("object_id"))
            else:
                normalized_id = None

        query = f"""
        WITH cost_metrics AS (
            SELECT
                DATE(run_date) as cost_date,
                object_id,
                service,
                SUM(cost_usd) as daily_cost,
                SUM(compute_units) as compute_units,
                SUM(slot_hours) as slot_hours
            FROM `{self.bq_manager.project_id}.{self.dataset_id}.factbilling`
            WHERE object_id = '{normalized_id}' 
                AND DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
            GROUP BY cost_date, object_id, service
        ),
        daily_total AS (
            SELECT
                cost_date,
                object_id,
                SUM(daily_cost) as total_daily_cost,
                SUM(compute_units) as total_compute_units,
                SUM(slot_hours) as total_slot_hours
            FROM cost_metrics
            GROUP BY cost_date, object_id
        )
        SELECT
            cost_date,
            object_id,
            total_daily_cost,
            total_compute_units,
            total_slot_hours,
            ROUND(AVG(total_daily_cost) OVER (
                ORDER BY cost_date
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
            ), 2) as avg_7day_cost
        FROM daily_total
        ORDER BY cost_date DESC
        """

        try:
            cost_data: List[Dict[str, Any]] = []
            if normalized_id:
                results = self.client.query(query).result()
                cost_data = [dict(row) for row in results]
            else:
                logger.info("No spend records located for aggregation window.")

            # Calculate savings opportunity
            if len(cost_data) >= 2:
                first_week = cost_data[-7:] if len(cost_data) >= 7 else cost_data
                recent = cost_data[:7] if len(cost_data) >= 7 else cost_data

                cost_first = sum(c['total_daily_cost'] for c in first_week) / len(first_week) if first_week else 0
                cost_recent = sum(c['total_daily_cost'] for c in recent) / len(recent) if recent else 0

                savings_pct = ((cost_first - cost_recent) / cost_first * 100) if cost_first > 0 else 0
                daily_savings = cost_first - cost_recent
            else:
                savings_pct = 0
                daily_savings = 0

            additional_ids = [entry.get("object_id") for entry in portfolio_summary[1:]] if portfolio_summary else None
            context = self._gather_architect_context(normalized_id, prompt, additional_ids=additional_ids)
            return {
                "agent": "CloudFnOAgent",
                "object_id": normalized_id or object_id,
                "analysis_type": "Cost Analysis & Optimization",
                "cost_data": cost_data[:14],  # Last 2 weeks
                "savings_opportunity_percent": round(savings_pct, 1),
                "estimated_daily_savings": round(daily_savings, 2),
                "portfolio_summary": portfolio_summary,
                "object_snapshot": context.get("snapshot"),
                "diagram_summary": context.get("diagram_summary"),
                "diagram_history": context.get("diagram_history", []),
                "diagram_network": context.get("diagram_network"),
                "object_context": context.get("object_context", []),
                "related_object_ids": context.get("related_object_ids", []),
                "prompt_object_ids": context.get("prompt_object_ids", []),
                "prompt_text": prompt,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"CloudFnOAgent error: {e}")
            return {"error": str(e), "agent": "CloudFnOAgent"}


class SyncFlowApp:
    """Main application class integrating Mini ETL and Multi-Agent Architecture."""

    def __init__(
        self,
        config_file: Optional[str] = None,
        *,
        settings: "AppSettings | None" = None,
        app: Optional[Flask] = None,
    ):
        self.settings = settings
        self.app = app if app is not None else Flask(__name__)
        CORS(self.app)

        # Configuration
        if settings is not None:
            self.config = {
                'project_id': settings.project_id,
                'dataset_id': settings.dataset_id,
                'service_account_path': settings.service_account_path,
                'port': settings.port,
                'host': settings.host,
                'debug': settings.debug,
            }
        else:
            self.config = self._load_config(config_file)

        self.project_id = self.config.get('project_id', 'prismatic-smoke-463810-c1')
        self.dataset_id = self.config.get('dataset_id', 'minietl')
        self.sa_path = self.config.get('service_account_path')
        self.app.config.setdefault("PROJECT_ID", self.project_id)
        self.app.config.setdefault("DATASET_ID", self.dataset_id)
        self.app.config.setdefault("SERVICE_ACCOUNT_PATH", self.sa_path)

        # Initialize components
        self.bq_manager = None
        self.logs_explorer = None
        self.analyzer = None
        self.billing_extractor = None
        self.architect_agent = None

        self._initialize_components()
        self._register_routes()

    def _load_config(self, config_file: Optional[str]) -> Dict:
        """Load configuration from file or environment."""
        config = {
            'project_id': os.getenv('GCP_PROJECT', 'prismatic-smoke-463810-c1'),
            'dataset_id': os.getenv('BQ_DATASET', 'minietl'),
            'service_account_path': os.getenv('GOOGLE_APPLICATION_CREDENTIALS', config_file),
            'port': int(os.getenv('PORT', 5000)),
            'host': os.getenv('HOST', '127.0.0.1'),
            'debug': os.getenv('DEBUG', 'False').lower() == 'true'
        }

        if config_file and os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    file_config = json.load(f)
                    config.update(file_config)
            except Exception as e:
                logger.warning(f"Failed to load config file: {e}")

        return config

    def _initialize_components(self):
        """Initialize BigQuery and analysis components."""
        try:
            if self.sa_path and os.path.exists(self.sa_path):
                self.bq_manager = setup_from_service_account(self.sa_path)
            else:
                self.bq_manager = BigQueryManager(
                    project_id=self.project_id,
                    dataset_id=self.dataset_id,
                )

            self.bq_manager.project_id = self.project_id
            self.bq_manager.dataset_id = self.dataset_id
            self.bq_manager.dataset_ref = f"{self.project_id}.{self.dataset_id}"

            self.storage = BigQueryStorage(self.bq_manager)
            self.app.extensions.setdefault("storage", self.storage)

            self.logs_explorer = LogsExplorer(self.project_id, self.bq_manager.credentials)
            self.analyzer = MultiAgentAnalyzer(self.bq_manager)
            self.billing_extractor = BillingExtractor(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                billing_project_id=self.project_id,
                credentials=self.bq_manager.credentials,
            )
            self.architect_agent = ArchitectAgent(self.bq_manager)

            logger.info(f"✓ Components initialized for project: {self.project_id}")
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            raise

    def _create_adk_workflow(self):
        """Create a new ADK architect workflow wired to the current project."""
        return create_architect_workflow(self.project_id, self.dataset_id)

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        """Convert various truthy/falsy representations into a boolean."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)

    def _register_routes(self):
        """Register all API routes."""

        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({
                "status": "healthy",
                "project": self.project_id,
                "dataset": self.dataset_id,
                "timestamp": datetime.now().isoformat()
            })

        # ==== ETL Objects ====
        @self.app.route('/api/objects', methods=['GET'])
        def list_objects():
            """List all ETL objects with latest version."""
            try:
                objects = self.storage.list_objects()
                return jsonify({"total": len(objects), "objects": objects})
            except StorageError as e:
                logger.error(f"Object listing failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/objects/<object_id>', methods=['GET'])
        def get_object(object_id):
            """Get detailed object information."""
            try:
                obj = self.storage.get_object(object_id)
                return jsonify(obj)
            except NotFoundError:
                return jsonify({"error": "Object not found"}), 404
            except StorageError as e:
                logger.error(f"Error fetching object {object_id}: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/objects/<object_id>/history', methods=['GET'])
        def get_object_history(object_id):
            """Get version history for an object (SCD Type 2)."""
            try:
                history = self.storage.get_object_history(object_id)
                return jsonify({
                    "object_id": object_id,
                    "versions": len(history),
                    "history": history
                })
            except StorageError as e:
                logger.error(f"Error fetching history for {object_id}: {e}")
                return jsonify({"error": str(e)}), 500

        # ==== Lineage ====
        @self.app.route('/api/lineage/<object_id>/upstream', methods=['GET'])
        def get_upstream(object_id):
            """Get upstream dependencies."""
            try:
                query = f"""
                WITH RECURSIVE upstream_deps AS (
                    SELECT upstream_id, downstream_id, 1 as depth
                    FROM `{self.project_id}.{self.dataset_id}.etledges`
                    WHERE downstream_id = '{object_id}'

                    UNION ALL

                    SELECT e.upstream_id, e.downstream_id, ud.depth + 1
                    FROM `{self.project_id}.{self.dataset_id}.etledges` e
                    JOIN upstream_deps ud ON e.downstream_id = ud.upstream_id
                    WHERE ud.depth < 10
                )
                SELECT DISTINCT upstream_id, MIN(depth) as depth
                FROM upstream_deps
                GROUP BY upstream_id
                ORDER BY depth, upstream_id
                """

                results = self.bq_manager.client.query(query).result()
                deps = [dict(row) for row in results]

                return jsonify({
                    "object_id": object_id,
                    "dependencies_count": len(deps),
                    "upstream": deps
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/lineage/<object_id>/downstream', methods=['GET'])
        def get_downstream(object_id):
            """Get downstream dependencies."""
            try:
                query = f"""
                WITH RECURSIVE downstream_deps AS (
                    SELECT upstream_id, downstream_id, 1 as depth
                    FROM `{self.project_id}.{self.dataset_id}.etledges`
                    WHERE upstream_id = '{object_id}'

                    UNION ALL

                    SELECT e.upstream_id, e.downstream_id, dd.depth + 1
                    FROM `{self.project_id}.{self.dataset_id}.etledges` e
                    JOIN downstream_deps dd ON e.upstream_id = dd.downstream_id
                    WHERE dd.depth < 10
                )
                SELECT DISTINCT downstream_id, MIN(depth) as depth
                FROM downstream_deps
                GROUP BY downstream_id
                ORDER BY depth, downstream_id
                """

                results = self.bq_manager.client.query(query).result()
                deps = [dict(row) for row in results]

                return jsonify({
                    "object_id": object_id,
                    "dependents_count": len(deps),
                    "downstream": deps
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        # ==== Multi-Agent Analysis ====
        @self.app.route('/api/agents/analyze/<object_id>', methods=['GET'])
        def analyze_object(object_id):
            """Run all three agents on an object."""
            try:
                doc_analysis = self.analyzer.doc_agent_analysis(object_id)
                log_analysis = self.analyzer.log_agent_analysis(
                    object_id,
                    int(request.args.get('days', 7))
                )
                cost_analysis = self.analyzer.cloud_fn_agent_analysis(
                    object_id,
                    int(request.args.get('cost_days', 30))
                )

                return jsonify({
                    "object_id": object_id,
                    "agents": [doc_analysis, log_analysis, cost_analysis],
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/agents/doc/<object_id>', methods=['GET'])
        def doc_agent(object_id):
            """Run DocAgent - Configuration analysis."""
            prompt = request.args.get('notes') or request.args.get('prompt')
            return jsonify(self.analyzer.doc_agent_analysis(object_id, prompt=prompt))

        @self.app.route('/api/agents/log/<object_id>', methods=['GET'])
        def log_agent(object_id):
            """Run LogAgent - Performance analysis."""
            days = int(request.args.get('days', 7))
            prompt = request.args.get('notes') or request.args.get('prompt')
            return jsonify(self.analyzer.log_agent_analysis(object_id, days, prompt=prompt))

        @self.app.route('/api/agents/cost/<object_id>', methods=['GET'])
        def cost_agent(object_id):
            """Run CloudFnOAgent - Cost analysis."""
            days = int(request.args.get('days', 30))
            prompt = request.args.get('notes') or request.args.get('prompt')
            return jsonify(self.analyzer.cloud_fn_agent_analysis(object_id, days, prompt=prompt))

        # v2 aliases for agent-specific endpoints
        @self.app.route('/api/v2/agents/architect/<object_id>', methods=['GET'])
        def architect_agent_v2(object_id):
            try:
                prompt = request.args.get('notes') or request.args.get('prompt')
                return jsonify(self.analyzer.doc_agent_analysis(object_id, prompt=prompt))
            except Exception as e:
                logger.error(f"Architect agent failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/v2/agents/ops/<object_id>', methods=['GET'])
        def ops_agent_v2(object_id):
            try:
                days = int(request.args.get('days', 7))
                prompt = request.args.get('notes') or request.args.get('prompt')
                return jsonify(self.analyzer.log_agent_analysis(object_id, days, prompt=prompt))
            except Exception as e:
                logger.error(f"Ops agent failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/v2/agents/finops/<object_id>', methods=['GET'])
        def finops_agent_v2(object_id):
            try:
                days = int(request.args.get('days', 30))
                prompt = request.args.get('notes') or request.args.get('prompt')
                return jsonify(self.analyzer.cloud_fn_agent_analysis(object_id, days, prompt=prompt))
            except Exception as e:
                logger.error(f"FinOps agent failed: {e}")
                return jsonify({"error": str(e)}), 500

        # ==== Architect Agent - Inventory Review & Prioritization ====
        @self.app.route('/api/objects/<object_id>/architect-review', methods=['POST'])
        def architect_review(object_id):
            """Submit architect review for an object."""
            try:
                data = request.get_json()

                # Validate required fields
                if not data:
                    return jsonify({"error": "Request body required"}), 400

                priority = data.get('priority')
                architect_notes = data.get('architect_notes', '')
                is_decommission = data.get('is_decommission', False)
                decommission_reason = data.get('decommission_reason')
                reviewed_by = data.get('reviewed_by', 'web_user')

                # Validate priority
                valid_priorities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
                if priority not in valid_priorities:
                    return jsonify({
                        "error": f"Invalid priority. Must be one of: {valid_priorities}"
                    }), 400

                # Call architect agent
                result = self.architect_agent.review_object(
                    object_id=object_id,
                    priority=priority,
                    architect_notes=architect_notes,
                    is_decommission=is_decommission,
                    decommission_reason=decommission_reason,
                    reviewed_by=reviewed_by
                )

                return jsonify(result), 200 if result.get('status') == 'success' else 400
            except Exception as e:
                logger.error(f"Architect review failed for {object_id}: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/architect/priority-summary', methods=['GET'])
        def architect_priority_summary():
            """Get summary of objects by priority level."""
            try:
                summary = self.architect_agent.get_priority_summary()
                return jsonify({
                    "summary": summary,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Priority summary failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/architect/decommission-candidates', methods=['GET'])
        def architect_decommission_candidates():
            """Get objects marked for decommission."""
            try:
                candidates = self.architect_agent.get_decommission_candidates()
                return jsonify({
                    "count": len(candidates),
                    "candidates": candidates,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Decommission candidates failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/architect/critical-objects', methods=['GET'])
        def architect_critical_objects():
            """Get all CRITICAL priority objects for Ops/FinOps focus."""
            try:
                critical = self.architect_agent.get_critical_objects()
                return jsonify({
                    "count": len(critical),
                    "critical_objects": critical,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Critical objects fetch failed: {e}")
                return jsonify({"error": str(e)}), 500

        # ==== ADK Architect Workflow ====
        @self.app.route('/api/architect/workflows', methods=['POST'])
        def start_adk_architect_workflow():
            """Kick off the ADK-based architect workflow and return its summary."""

            data = request.get_json() or {}
            workflow_id = data.get('workflow_id') or f"WF_{uuid4().hex[:8].upper()}"
            architect_name = data.get('architect_name')
            focus_priority_raw = data.get('focus_priority')
            include_lineage = self._coerce_bool(data.get('include_lineage'), True)
            generate_proposals = self._coerce_bool(data.get('generate_proposals'), True)

            focus_priority = None
            if focus_priority_raw:
                try:
                    focus_priority = ArchitectPriority(focus_priority_raw.upper())
                except ValueError:
                    return jsonify({
                        "error": (
                            f"Invalid focus_priority '{focus_priority_raw}'. "
                            "Valid values: CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION"
                        )
                    }), 400

            try:
                response = start_architect_review(
                    project_id=self.project_id,
                    workflow_id=workflow_id,
                    architect_name=architect_name,
                    dataset_id=self.dataset_id,
                    focus_priority=focus_priority,
                    include_lineage=include_lineage,
                    generate_proposals=generate_proposals,
                )
            except Exception as exc:
                logger.error(f"ADK architect workflow failed: {exc}")
                return jsonify({"error": str(exc)}), 500

            payload = response.model_dump(mode="json")
            return jsonify(payload)

        @self.app.route('/api/architect/workflows/<object_id>/decision', methods=['POST'])
        def apply_adk_architect_decision(object_id: str):
            """Apply an architect decision via the ADK workflow helpers."""
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request body required"}), 400

            try:
                workflow = self._create_adk_workflow()
                action = (data.get('action') or '').strip().lower()
                architect_name = data.get('architect_name', 'system')

                if action == "decommission" or data.get('is_decommission'):
                    reason = data.get('decommission_reason') or data.get('notes') or "Marked for decommission"
                    replacement_id = data.get('replacement_id')
                    result = workflow.mark_object_for_decommission(
                        object_id=object_id,
                        reason=reason,
                        replacement_id=replacement_id,
                        architect_name=architect_name,
                    )
                else:
                    priority_raw = data.get('priority')
                    if not priority_raw:
                        return jsonify({"error": "Field 'priority' is required"}), 400

                    try:
                        priority_value = ArchitectPriority(priority_raw.upper())
                    except ValueError:
                        return jsonify({
                            "error": (
                                f"Invalid priority '{priority_raw}'. "
                                "Valid values: CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION"
                            )
                        }), 400

                    notes = data.get('notes', '')
                    # If the requested priority is explicit decommission, also mark it.
                    if priority_value == ArchitectPriority.DECOMMISSION:
                        reason = data.get('decommission_reason') or notes or "Marked for decommission"
                        result = workflow.mark_object_for_decommission(
                            object_id=object_id,
                            reason=reason,
                            replacement_id=data.get('replacement_id'),
                            architect_name=architect_name,
                        )
                    else:
                        result = workflow.apply_architect_decision(
                            object_id=object_id,
                            priority=priority_value,
                            architect_name=architect_name,
                            notes=notes,
                        )
            except Exception as exc:
                logger.error(f"Architect decision application failed for {object_id}: {exc}")
                return jsonify({"error": str(exc)}), 500

            status_code = 200 if result.get('status') == 'success' else 400
            return jsonify(result), status_code

        @self.app.route('/api/architect/diagrams/<object_id>', methods=['POST'])
        def generate_architect_diagram(object_id: str):
            """Generate (and optionally persist) a Mermaid diagram for an object's lineage."""
            data = request.get_json() or {}
            include_scope = data.get('scope', 'both')
            store = self._coerce_bool(data.get('store'), False)
            diagram_name = data.get('diagram_name')

            try:
                workflow = self._create_adk_workflow()
                result = workflow.generate_mermaid_diagram(
                    object_id=object_id,
                    include_scope=include_scope,
                    store=store,
                    diagram_name=diagram_name,
                )
            except Exception as exc:
                logger.error(f"Diagram generation failed for {object_id}: {exc}")
                return jsonify({"error": str(exc)}), 500

            status_code = 200 if result.get("status") in {"success", "partial"} else 400
            return jsonify(result), status_code

        @self.app.route('/api/architect/diagrams/<object_id>/custom', methods=['POST'])
        def store_custom_architect_diagram(object_id: str):
            """Store a custom Mermaid diagram supplied by the client."""
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request body required"}), 400

            diagram_text = data.get('diagram_text')
            if not diagram_text:
                return jsonify({"error": "Field 'diagram_text' is required"}), 400

            diagram_format = data.get('format', 'mermaid')
            diagram_name = data.get('diagram_name')
            activate = self._coerce_bool(data.get('activate'), True)

            try:
                workflow = self._create_adk_workflow()
                result = workflow.store_custom_diagram(
                    object_id=object_id,
                    diagram_text=diagram_text,
                    diagram_format=diagram_format,
                    diagram_name=diagram_name,
                    activate=activate,
                )
            except Exception as exc:
                logger.error(f"Custom diagram storage failed for {object_id}: {exc}")
                return jsonify({"error": str(exc)}), 500

            status_code = 200 if result.get("status") == "success" else 400
            return jsonify(result), status_code

        @self.app.route('/api/architect/diagrams/<object_id>', methods=['GET'])
        def get_latest_architect_diagram(object_id: str):
            """Return the most recent active diagram for an object."""
            try:
                workflow = self._create_adk_workflow()
                result = workflow.get_latest_diagram(object_id)
            except Exception as exc:
                logger.error(f"Diagram lookup failed for {object_id}: {exc}")
                return jsonify({"error": str(exc)}), 500

            status = result.get("status")
            if status == "success":
                return jsonify(result), 200
            if status == "not_found":
                return jsonify(result), 404
            return jsonify(result), 400

        @self.app.route('/api/architect/diagrams/<object_id>/history', methods=['GET'])
        def get_architect_diagram_history(object_id: str):
            """Return diagram history for an object."""
            limit = int(request.args.get('limit', 10))
            try:
                workflow = self._create_adk_workflow()
                result = workflow.list_diagram_history(object_id, limit=limit)
            except Exception as exc:
                logger.error(f"Diagram history lookup failed for {object_id}: {exc}")
                return jsonify({"error": str(exc)}), 500

            status = result.get("status")
            if status == "success":
                return jsonify(result), 200
            if status == "not_found":
                return jsonify(result), 404
            return jsonify(result), 400

        @self.app.route('/api/objects/by-priority/<priority>', methods=['GET'])
        def objects_by_priority(priority):
            """Get objects filtered by priority level."""
            try:
                valid_priorities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
                if priority not in valid_priorities:
                    return jsonify({
                        "error": f"Invalid priority. Must be one of: {valid_priorities}"
                    }), 400

                query = f"""
                SELECT
                    object_id,
                    name,
                    object_type,
                    status,
                    priority,
                    is_decommission,
                    architect_notes,
                    architect_reviewed_by,
                    architect_review_timestamp
                FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2_enriched`
                WHERE effective_end IS NULL
                AND priority = @priority
                ORDER BY architect_review_timestamp DESC, object_id
                """

                job_config = bigquery.QueryJobConfig()
                job_config.query_parameters = [
                    bigquery.ScalarQueryParameter("priority", "STRING", priority)
                ]

                results = self.bq_manager.client.query(query, job_config=job_config).result()
                objects = [dict(row) for row in results]

                return jsonify({
                    "priority": priority,
                    "count": len(objects),
                    "objects": objects,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Priority filter failed for {priority}: {e}")
                return jsonify({"error": str(e)}), 500

        # ==== Metrics & Logs ====
        @self.app.route('/api/metrics/<object_id>/executions', methods=['GET'])
        def get_executions(object_id):
            """Get execution logs for an object."""
            try:
                days = int(request.args.get('days', 7))
                limit = int(request.args.get('limit', 100))

                query = f"""
                SELECT *
                FROM `{self.project_id}.{self.dataset_id}.factlog`
                WHERE object_id = '{object_id}'
                    AND DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
                ORDER BY created_at DESC
                LIMIT {limit}
                """

                results = self.bq_manager.client.query(query).result()
                logs = [dict(row) for row in results]

                return jsonify({
                    "object_id": object_id,
                    "executions": len(logs),
                    "logs": logs
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/metrics/<object_id>/costs', methods=['GET'])
        def get_costs(object_id):
            """Get cost data for an object."""
            try:
                days = int(request.args.get('days', 30))

                query = f"""
                SELECT
                    DATE(run_date) as date,
                    service,
                    SUM(cost_usd) as total_cost,
                    SUM(compute_units) as compute_units,
                    AVG(slot_hours) as slot_hours
                FROM `{self.project_id}.{self.dataset_id}.factbilling`
                WHERE object_id = '{object_id}'
                    AND DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
                GROUP BY date, service
                ORDER BY date DESC, service
                """

                results = self.bq_manager.client.query(query).result()
                costs = [dict(row) for row in results]

                return jsonify({
                    "object_id": object_id,
                    "cost_records": len(costs),
                    "costs": costs
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        # ==== System Stats ====
        @self.app.route('/api/stats', methods=['GET'])
        def get_stats():
            """Get system statistics."""
            try:
                stats = {}

                # Object count
                obj_query = f"SELECT COUNT(DISTINCT object_id) as count FROM `{self.project_id}.{self.dataset_id}.etlobjectscd2` WHERE effective_end IS NULL"
                result = self.bq_manager.client.query(obj_query).result()
                stats['total_objects'] = dict(next(result))['count']

                # Recent logs
                log_query = f"SELECT COUNT(*) as count FROM `{self.project_id}.{self.dataset_id}.factlog` WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
                result = self.bq_manager.client.query(log_query).result()
                stats['recent_logs'] = dict(next(result))['count']

                # Total cost
                cost_query = f"SELECT SUM(cost_usd) as total FROM `{self.project_id}.{self.dataset_id}.factbilling` WHERE DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)"
                result = self.bq_manager.client.query(cost_query).result()
                row = dict(next(result))
                stats['recent_costs'] = row['total'] or 0.0

                return jsonify({
                    "stats": stats,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    def run(self):
        """Start the application."""
        host = self.config.get('host', '127.0.0.1')
        port = self.config.get('port', 5000)
        debug = self.config.get('debug', False)

        logger.info(f"\n{'='*60}")
        logger.info(f"SyncFlow GCP Intelligence - Backend API")
        logger.info(f"{'='*60}")
        logger.info(f"Project: {self.project_id}")
        logger.info(f"Dataset: {self.dataset_id}")
        logger.info(f"Server: http://{host}:{port}")
        logger.info(f"Debug: {debug}")
        logger.info(f"{'='*60}\n")

        self.app.run(host=host, port=port, debug=debug)


def main():
    """Main entry point."""
    import argparse
    from app import AppSettings

    parser = argparse.ArgumentParser(description="SyncFlow GCP Intelligence Backend")
    parser.add_argument('--sa', help='Service account JSON path')
    parser.add_argument('--project', default='prismatic-smoke-463810-c1', help='GCP project ID')
    parser.add_argument('--dataset', default='minietl', help='BigQuery dataset')
    parser.add_argument('--port', type=int, default=None, help='Port to run on (default: $PORT or 5000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--config', help='Config JSON file')
    parser.add_argument('--debug', action='store_true', help='Debug mode')

    args = parser.parse_args()

    # Set environment variables
    if args.sa:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = args.sa

    # Use PORT environment variable if set (Cloud Run), otherwise use --port arg or default
    port = args.port or int(os.getenv('PORT', 5000))

    settings = AppSettings(
        project_id=args.project,
        dataset_id=args.dataset,
        service_account_path=args.sa or os.getenv('GOOGLE_APPLICATION_CREDENTIALS'),
        host=args.host,
        port=port,
        debug=args.debug,
    )

    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, 'r') as fp:
                file_config = json.load(fp)
            settings.project_id = file_config.get('project_id', settings.project_id)
            settings.dataset_id = file_config.get('dataset_id', settings.dataset_id)
            settings.service_account_path = file_config.get('service_account_path', settings.service_account_path)
            settings.host = file_config.get('host', settings.host)
            settings.port = file_config.get('port', settings.port)
            settings.debug = file_config.get('debug', settings.debug)
        except Exception as exc:
            logger.warning(f"Failed to load config file {args.config}: {exc}")

    # Create SyncFlowApp directly to avoid circular imports
    syncflow_app = SyncFlowApp(settings=settings)
    syncflow_app.run()


if __name__ == '__main__':
    main()
