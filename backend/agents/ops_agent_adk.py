"""
Ops Agent (LogAgent) - Performance & Reliability Intelligence

Refactored to use Google ADK with composable @agent_tool decorated functions.
Analyzes execution performance, detects anomalies, and provides optimization recommendations.

Design:
- LogAnalystAgent (read-only): Analyzes performance data
- OpsOptimizationAgent (write-enabled): Implements recommendations
"""

import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import uuid
from google.cloud import bigquery

# Handle optional Google ADK import
try:
    from google.adk.tools import agent_tool
except ImportError:
    # Mock decorator for development/testing when ADK not available
    def agent_tool(func):
        """Mock agent_tool decorator for development."""
        return func

# Handle both relative and absolute imports for Cloud Run compatibility
try:
    from .models_adk import (
        PerformanceMetric,
        AnomalyAlert,
        OptimizationRecommendation,
        OpsAnalysis,
    )
except ImportError:
    from agents.models_adk import (
        PerformanceMetric,
        AnomalyAlert,
        OptimizationRecommendation,
        OpsAnalysis,
    )

logger = logging.getLogger(__name__)

# Global BigQuery client (initialized once)
_bq_client: Optional[bigquery.Client] = None


def get_bq_client() -> bigquery.Client:
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


# ============================================================================
# EXECUTION LOG ANALYSIS TOOLS
# ============================================================================

@agent_tool
def query_execution_metrics(
    project_id: str,
    object_id: str,
    days: int = 7,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Query execution metrics from factlog for performance analysis.

    Args:
        project_id: GCP project ID
        object_id: Object to analyze
        days: Number of days to look back
        dataset_id: BigQuery dataset

    Returns:
        Daily performance metrics
    """
    try:
        client = get_bq_client()
        lookback_days = max(1, min(180, days))

        query = f"""
        SELECT
            DATE(created_at) as run_date,
            object_id,
            COUNT(*) as executions,
            COUNTIF(status = 'success') as successful,
            COUNTIF(status != 'success') as failed,
            AVG(duration_seconds) as avg_duration,
            MIN(duration_seconds) as min_duration,
            MAX(duration_seconds) as max_duration,
            STDDEV(duration_seconds) as duration_stddev,
            SUM(rows_processed) as total_rows,
            AVG(SAFE_DIVIDE(rows_processed, NULLIF(duration_seconds, 0))) as avg_throughput
        FROM `{project_id}.{dataset_id}.factlog`
        WHERE object_id = '{object_id}'
            AND DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
        GROUP BY run_date, object_id
        ORDER BY run_date DESC
        """

        results = client.query(query).result()
        metrics = []
        for row in results:
            metrics.append({
                "run_date": str(row.run_date),
                "object_id": row.object_id,
                "executions": row.executions,
                "successful": row.successful,
                "failed": row.failed,
                "success_rate": row.successful / row.executions if row.executions > 0 else 0,
                "avg_duration_seconds": row.avg_duration,
                "min_duration_seconds": row.min_duration,
                "max_duration_seconds": row.max_duration,
                "duration_stddev": row.duration_stddev,
                "total_rows_processed": row.total_rows,
                "avg_throughput": row.avg_throughput or 0,
            })

        return {
            "status": "success",
            "object_id": object_id,
            "lookback_days": lookback_days,
            "metrics_count": len(metrics),
            "metrics": metrics,
        }
    except Exception as e:
        logger.error(f"Error querying execution metrics: {e}")
        return {
            "status": "error",
            "error": str(e),
            "object_id": object_id,
        }


@agent_tool
def detect_performance_anomalies(
    metrics: List[Dict[str, Any]],
    stddev_threshold: float = 2.0
) -> Dict[str, Any]:
    """
    Detect performance anomalies using statistical analysis.

    Args:
        metrics: List of daily performance metrics
        stddev_threshold: Number of standard deviations to flag as anomaly

    Returns:
        List of detected anomalies
    """
    try:
        if len(metrics) < 3:
            return {"status": "success", "anomalies": [], "message": "Insufficient data"}

        anomalies = []

        # Analyze duration trends
        durations = [m.get("avg_duration_seconds", 0) for m in metrics if m.get("avg_duration_seconds")]
        if len(durations) >= 3:
            mean_duration = sum(durations) / len(durations)
            variance = sum((x - mean_duration) ** 2 for x in durations) / len(durations)
            stddev = variance ** 0.5

            for i, metric in enumerate(metrics[:7]):  # Check last 7 days
                duration = metric.get("avg_duration_seconds", 0)
                if stddev > 0:
                    deviation = abs(duration - mean_duration) / stddev
                    if deviation > stddev_threshold:
                        anomalies.append({
                            "anomaly_id": str(uuid.uuid4()),
                            "object_id": metric.get("object_id"),
                            "anomaly_type": "PERFORMANCE_DEGRADATION" if duration > mean_duration else "PERFORMANCE_IMPROVEMENT",
                            "severity": "CRITICAL" if deviation > 3 else "HIGH" if deviation > 2 else "MEDIUM",
                            "metric_name": "avg_duration_seconds",
                            "baseline_value": mean_duration,
                            "observed_value": duration,
                            "deviation_stddev": round(deviation, 2),
                            "detected_at": metric.get("run_date"),
                        })

        # Analyze success rate
        success_rates = [m.get("success_rate", 1.0) for m in metrics]
        if len(success_rates) >= 3:
            for i, metric in enumerate(metrics[:7]):
                success_rate = metric.get("success_rate", 1.0)
                if success_rate < 0.9:  # Below 90% is flagged
                    anomalies.append({
                        "anomaly_id": str(uuid.uuid4()),
                        "object_id": metric.get("object_id"),
                        "anomaly_type": "HIGH_FAILURE_RATE",
                        "severity": "CRITICAL" if success_rate < 0.5 else "HIGH",
                        "metric_name": "success_rate",
                        "baseline_value": 0.95,
                        "observed_value": success_rate,
                        "deviation_stddev": (0.95 - success_rate) / 0.05,
                        "detected_at": metric.get("run_date"),
                    })

        return {
            "status": "success",
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies,
        }
    except Exception as e:
        logger.error(f"Error detecting anomalies: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def calculate_performance_trend(metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate performance trend over time.

    Args:
        metrics: List of daily performance metrics (most recent first)

    Returns:
        Trend analysis
    """
    try:
        if len(metrics) < 2:
            return {
                "status": "success",
                "trend_improvement_percent": 0.0,
                "message": "Insufficient data",
            }

        # Compare first week vs recent week
        first_week = metrics[-7:] if len(metrics) >= 7 else metrics
        recent_week = metrics[:7] if len(metrics) >= 7 else metrics

        avg_first = sum(m.get("avg_duration_seconds", 0) for m in first_week) / len(first_week)
        avg_recent = sum(m.get("avg_duration_seconds", 0) for m in recent_week) / len(recent_week)

        improvement_pct = ((avg_first - avg_recent) / avg_first * 100) if avg_first > 0 else 0

        return {
            "status": "success",
            "trend_improvement_percent": round(improvement_pct, 1),
            "baseline_avg_duration": round(avg_first, 2),
            "recent_avg_duration": round(avg_recent, 2),
            "trend_direction": "improving" if improvement_pct > 0 else "degrading",
        }
    except Exception as e:
        logger.error(f"Error calculating trend: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def generate_optimization_recommendations(
    object_id: str,
    metrics: List[Dict[str, Any]],
    anomalies: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Generate optimization recommendations based on analysis.

    Args:
        object_id: Object being optimized
        metrics: Performance metrics
        anomalies: Detected anomalies

    Returns:
        List of recommendations
    """
    try:
        recommendations = []

        if not metrics:
            return {"status": "success", "recommendations": []}

        latest_metric = metrics[0]

        # Recommend scaling if high throughput or failures
        if latest_metric.get("failed", 0) > 0:
            failure_rate = latest_metric.get("failed", 0) / max(1, latest_metric.get("executions", 1))
            if failure_rate > 0.1:
                recommendations.append({
                    "recommendation_id": str(uuid.uuid4()),
                    "object_id": object_id,
                    "recommendation_type": "INCREASE_RETRY_POLICY",
                    "current_state": "Standard retry policy (3 retries)",
                    "recommended_state": "Enhanced retry policy (5 retries, exponential backoff)",
                    "rationale": f"Failure rate of {failure_rate:.1%} exceeds acceptable threshold",
                    "expected_improvement_pct": 15.0,
                    "confidence": 0.85,
                    "implementation_effort": "EASY",
                })

        # Recommend timeout increase if duration is high
        if latest_metric.get("max_duration_seconds", 0) > latest_metric.get("avg_duration_seconds", 1) * 2:
            recommendations.append({
                "recommendation_id": str(uuid.uuid4()),
                "object_id": object_id,
                "recommendation_type": "INCREASE_TIMEOUT",
                "current_state": "300 second timeout",
                "recommended_state": "600 second timeout",
                "rationale": "Max duration exceeds current timeout; consider increasing",
                "expected_improvement_pct": 10.0,
                "confidence": 0.80,
                "implementation_effort": "TRIVIAL",
            })

        # Recommend batching if high execution frequency
        if latest_metric.get("executions", 0) > 1000:
            recommendations.append({
                "recommendation_id": str(uuid.uuid4()),
                "object_id": object_id,
                "recommendation_type": "IMPLEMENT_BATCHING",
                "current_state": "Individual executions",
                "recommended_state": "Batch processing (100 items/batch)",
                "rationale": f"High execution frequency ({latest_metric.get('executions')} executions/day)",
                "expected_improvement_pct": 25.0,
                "confidence": 0.75,
                "implementation_effort": "MODERATE",
            })

        return {
            "status": "success",
            "recommendations_generated": len(recommendations),
            "recommendations": recommendations,
        }
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def get_portfolio_summary(
    project_id: str,
    days: int = 7,
    limit: int = 5,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Get summary of most active objects in portfolio.

    Args:
        project_id: GCP project ID
        days: Lookback period
        limit: Number of top objects to return
        dataset_id: BigQuery dataset

    Returns:
        Portfolio execution summary
    """
    try:
        client = get_bq_client()
        lookback_days = max(1, min(180, days))

        query = f"""
        SELECT
            object_id,
            COUNT(*) AS total_executions,
            COUNTIF(status = 'success') AS successful_runs,
            SAFE_DIVIDE(COUNTIF(status = 'success'), COUNT(*)) AS success_rate,
            AVG(duration_seconds) AS avg_duration,
            MAX(duration_seconds) AS peak_duration,
            SUM(rows_processed) AS total_rows
        FROM `{project_id}.{dataset_id}.factlog`
        WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
            AND object_id IS NOT NULL
        GROUP BY object_id
        ORDER BY total_executions DESC
        LIMIT {limit}
        """

        results = client.query(query).result()
        portfolio = [dict(row) for row in results]

        return {
            "status": "success",
            "lookback_days": lookback_days,
            "portfolio_count": len(portfolio),
            "portfolio": portfolio,
        }
    except Exception as e:
        logger.error(f"Error getting portfolio summary: {e}")
        return {"status": "error", "error": str(e)}


# ============================================================================
# COMPLETE ANALYSIS FUNCTION
# ============================================================================

def analyze_object_performance(
    project_id: str,
    object_id: str,
    days: int = 7,
    dataset_id: str = "minietl"
) -> OpsAnalysis:
    """
    Complete performance analysis for an object.

    Orchestrates all Ops Agent tools to produce comprehensive analysis.
    """
    try:
        # Query metrics
        metrics_result = query_execution_metrics(project_id, object_id, days, dataset_id)
        metrics = metrics_result.get("metrics", [])

        # Detect anomalies
        anomalies_result = detect_performance_anomalies(metrics)
        anomalies = anomalies_result.get("anomalies", [])

        # Calculate trend
        trend_result = calculate_performance_trend(metrics)
        trend_improvement = trend_result.get("trend_improvement_percent", 0.0)

        # Generate recommendations
        recommendations_result = generate_optimization_recommendations(object_id, metrics, anomalies)
        recommendations = recommendations_result.get("recommendations", [])

        # Build analysis result
        analysis = OpsAnalysis(
            object_id=object_id,
            daily_metrics=[PerformanceMetric(**m) for m in metrics],
            trend_improvement_percent=trend_improvement,
            anomalies_detected=[AnomalyAlert(**a) for a in anomalies],
            recommendations=[OptimizationRecommendation(**r) for r in recommendations],
            portfolio_summary=[],
            lookback_days=days,
        )

        return analysis

    except Exception as e:
        logger.error(f"Error in analyze_object_performance: {e}")
        return OpsAnalysis(
            object_id=object_id,
            daily_metrics=[],
            anomalies_detected=[],
            recommendations=[],
        )
