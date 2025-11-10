"""
FinOps Agent (CloudFnOAgent) - Cost Optimization & Analytics

Refactored to use Google ADK with composable @agent_tool decorated functions.
Analyzes billing data, identifies cost trends, and recommends optimizations.

Design:
- CostAnalystAgent (read-only): Analyzes billing and cost data
- CostOptimizationAgent (write-enabled): Implements recommendations
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
        BillingTrend,
        SavingsOpportunity,
        CostAnalysis,
    )
except ImportError:
    from agents.models_adk import (
        BillingTrend,
        SavingsOpportunity,
        CostAnalysis,
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
# BILLING DATA ANALYSIS TOOLS
# ============================================================================

@agent_tool
def query_billing_data(
    project_id: str,
    object_id: str,
    days: int = 30,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Query billing data from factbilling for cost analysis.

    Args:
        project_id: GCP project ID
        object_id: Object to analyze
        days: Number of days to look back
        dataset_id: BigQuery dataset

    Returns:
        Daily billing data by service
    """
    try:
        client = get_bq_client()
        lookback_days = max(1, min(365, days))

        query = f"""
        SELECT
            DATE(run_date) as cost_date,
            object_id,
            service,
            SUM(cost_usd) as daily_cost,
            SUM(compute_units) as compute_units,
            SUM(slot_hours) as slot_hours
        FROM `{project_id}.{dataset_id}.factbilling`
        WHERE object_id = '{object_id}'
            AND DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
        GROUP BY cost_date, object_id, service
        ORDER BY cost_date DESC, service
        """

        results = client.query(query).result()
        billing_data = []
        for row in results:
            billing_data.append({
                "cost_date": str(row.cost_date),
                "object_id": row.object_id,
                "service": row.service,
                "daily_cost_usd": float(row.daily_cost) if row.daily_cost else 0.0,
                "compute_units": float(row.compute_units) if row.compute_units else None,
                "slot_hours": float(row.slot_hours) if row.slot_hours else None,
            })

        return {
            "status": "success",
            "object_id": object_id,
            "lookback_days": lookback_days,
            "records_count": len(billing_data),
            "billing_data": billing_data,
        }
    except Exception as e:
        logger.error(f"Error querying billing data: {e}")
        return {
            "status": "error",
            "error": str(e),
            "object_id": object_id,
        }


@agent_tool
def calculate_cost_metrics(billing_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate cost metrics from billing data.

    Args:
        billing_data: List of daily billing records

    Returns:
        Aggregated cost metrics
    """
    try:
        if not billing_data:
            return {
                "status": "success",
                "total_cost_usd": 0.0,
                "avg_daily_cost_usd": 0.0,
                "message": "No billing data",
            }

        # Aggregate by date
        daily_costs = {}
        service_costs = {}

        for record in billing_data:
            date_key = record.get("cost_date")
            service = record.get("service", "UNKNOWN")
            cost = record.get("daily_cost_usd", 0.0)

            daily_costs[date_key] = daily_costs.get(date_key, 0.0) + cost
            service_costs[service] = service_costs.get(service, 0.0) + cost

        total_cost = sum(daily_costs.values())
        avg_daily_cost = total_cost / len(daily_costs) if daily_costs else 0.0

        # Find max and min daily costs
        max_daily_cost = max(daily_costs.values()) if daily_costs else 0.0
        min_daily_cost = min(daily_costs.values()) if daily_costs else 0.0

        return {
            "status": "success",
            "total_cost_usd": round(total_cost, 2),
            "avg_daily_cost_usd": round(avg_daily_cost, 2),
            "max_daily_cost_usd": round(max_daily_cost, 2),
            "min_daily_cost_usd": round(min_daily_cost, 2),
            "unique_dates": len(daily_costs),
            "services_involved": list(service_costs.keys()),
            "service_breakdown": {k: round(v, 2) for k, v in service_costs.items()},
        }
    except Exception as e:
        logger.error(f"Error calculating cost metrics: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def detect_cost_anomalies(
    billing_data: List[Dict[str, Any]],
    stddev_threshold: float = 2.0
) -> Dict[str, Any]:
    """
    Detect cost anomalies using statistical analysis.

    Args:
        billing_data: List of billing records
        stddev_threshold: Number of standard deviations to flag as anomaly

    Returns:
        List of detected cost anomalies
    """
    try:
        if len(billing_data) < 3:
            return {"status": "success", "anomalies": [], "message": "Insufficient data"}

        # Aggregate by date
        daily_costs = {}
        for record in billing_data:
            date_key = record.get("cost_date")
            cost = record.get("daily_cost_usd", 0.0)
            daily_costs[date_key] = daily_costs.get(date_key, 0.0) + cost

        costs = list(daily_costs.values())
        if len(costs) < 3:
            return {"status": "success", "anomalies": []}

        mean_cost = sum(costs) / len(costs)
        variance = sum((x - mean_cost) ** 2 for x in costs) / len(costs)
        stddev = variance ** 0.5

        anomalies = []
        sorted_dates = sorted(daily_costs.keys(), reverse=True)

        for date_key in sorted_dates[:7]:  # Check last 7 days
            cost = daily_costs[date_key]
            if stddev > 0:
                deviation = abs(cost - mean_cost) / stddev
                if deviation > stddev_threshold:
                    anomalies.append({
                        "anomaly_date": date_key,
                        "anomaly_type": "COST_SPIKE" if cost > mean_cost else "COST_REDUCTION",
                        "severity": "CRITICAL" if deviation > 3 else "HIGH" if deviation > 2 else "MEDIUM",
                        "baseline_cost_usd": round(mean_cost, 2),
                        "observed_cost_usd": round(cost, 2),
                        "deviation_pct": round((cost - mean_cost) / mean_cost * 100, 1) if mean_cost > 0 else 0,
                        "deviation_stddev": round(deviation, 2),
                    })

        return {
            "status": "success",
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies,
        }
    except Exception as e:
        logger.error(f"Error detecting cost anomalies: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def calculate_cost_trend(
    billing_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Calculate cost trend over time.

    Args:
        billing_data: List of billing records (most recent first)

    Returns:
        Cost trend analysis
    """
    try:
        if len(billing_data) < 2:
            return {
                "status": "success",
                "savings_opportunity_percent": 0.0,
                "message": "Insufficient data",
            }

        # Aggregate by date
        daily_costs = {}
        for record in billing_data:
            date_key = record.get("cost_date")
            cost = record.get("daily_cost_usd", 0.0)
            daily_costs[date_key] = daily_costs.get(date_key, 0.0) + cost

        sorted_dates = sorted(daily_costs.keys())

        # Compare first week vs recent week
        first_week_dates = sorted_dates[-7:] if len(sorted_dates) >= 7 else sorted_dates
        recent_week_dates = sorted_dates[:7] if len(sorted_dates) >= 7 else sorted_dates

        avg_first = sum(daily_costs[d] for d in first_week_dates) / len(first_week_dates)
        avg_recent = sum(daily_costs[d] for d in recent_week_dates) / len(recent_week_dates)

        savings_pct = ((avg_first - avg_recent) / avg_first * 100) if avg_first > 0 else 0
        daily_savings = avg_first - avg_recent

        return {
            "status": "success",
            "savings_opportunity_percent": round(savings_pct, 1),
            "estimated_daily_savings_usd": round(daily_savings, 2),
            "baseline_daily_cost": round(avg_first, 2),
            "recent_daily_cost": round(avg_recent, 2),
            "trend_direction": "improving" if savings_pct > 0 else "degrading",
        }
    except Exception as e:
        logger.error(f"Error calculating cost trend: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def identify_cost_savings_opportunities(
    object_id: str,
    billing_data: List[Dict[str, Any]],
    cost_metrics: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Identify cost optimization opportunities.

    Args:
        object_id: Object being analyzed
        billing_data: Billing data
        cost_metrics: Calculated cost metrics

    Returns:
        List of savings opportunities
    """
    try:
        opportunities = []
        monthly_cost = cost_metrics.get("total_cost_usd", 0.0) * 30

        if not billing_data:
            return {"status": "success", "opportunities": []}

        # Identify services with high cost
        service_breakdown = cost_metrics.get("service_breakdown", {})

        # Recommend partitioning for BigQuery
        if "BigQuery" in service_breakdown or "bq" in service_breakdown.get("", "").lower():
            bq_cost = service_breakdown.get("BigQuery", 0.0)
            if bq_cost > 100:  # Over $100/month
                opportunities.append({
                    "opportunity_id": str(uuid.uuid4()),
                    "object_id": object_id,
                    "service": "BigQuery",
                    "opportunity_type": "PARTITIONING",
                    "current_cost_monthly_usd": round(monthly_cost, 2),
                    "projected_cost_monthly_usd": round(monthly_cost * 0.85, 2),
                    "monthly_savings_usd": round(monthly_cost * 0.15, 2),
                    "savings_pct": 15.0,
                    "implementation_effort": "MODERATE",
                    "roi_months": 1.0,
                    "details": {
                        "recommendation": "Partition tables by date",
                        "impact": "Reduces scanned data by ~15%",
                        "prerequisite": "Table schema modification",
                    }
                })

        # Recommend archiving old data
        if "BigQuery" in service_breakdown:
            opportunities.append({
                "opportunity_id": str(uuid.uuid4()),
                "object_id": object_id,
                "service": "BigQuery",
                "opportunity_type": "ARCHIVE",
                "current_cost_monthly_usd": round(monthly_cost, 2),
                "projected_cost_monthly_usd": round(monthly_cost * 0.88, 2),
                "monthly_savings_usd": round(monthly_cost * 0.12, 2),
                "savings_pct": 12.0,
                "implementation_effort": "EASY",
                "roi_months": 0.5,
                "details": {
                    "recommendation": "Archive tables older than 90 days to GCS",
                    "impact": "Reduces BigQuery storage costs",
                    "tools": "bq extract, Cloud Storage",
                }
            })

        # Recommend Dataflow optimization
        if "Dataflow" in service_breakdown:
            opportunities.append({
                "opportunity_id": str(uuid.uuid4()),
                "object_id": object_id,
                "service": "Dataflow",
                "opportunity_type": "RIGHT_SIZING",
                "current_cost_monthly_usd": round(monthly_cost, 2),
                "projected_cost_monthly_usd": round(monthly_cost * 0.90, 2),
                "monthly_savings_usd": round(monthly_cost * 0.10, 2),
                "savings_pct": 10.0,
                "implementation_effort": "MODERATE",
                "roi_months": 2.0,
                "details": {
                    "recommendation": "Adjust worker machine types and autoscaling",
                    "current": "n1-standard-4",
                    "recommended": "n1-standard-2",
                    "impact": "Reduce compute costs by 10-20%",
                }
            })

        return {
            "status": "success",
            "opportunities_count": len(opportunities),
            "opportunities": opportunities,
        }
    except Exception as e:
        logger.error(f"Error identifying savings opportunities: {e}")
        return {"status": "error", "error": str(e)}


@agent_tool
def get_portfolio_cost_summary(
    project_id: str,
    days: int = 30,
    limit: int = 5,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """
    Get summary of highest-cost objects in portfolio.

    Args:
        project_id: GCP project ID
        days: Lookback period
        limit: Number of top objects to return
        dataset_id: BigQuery dataset

    Returns:
        Portfolio cost summary
    """
    try:
        client = get_bq_client()
        lookback_days = max(1, min(365, days))

        query = f"""
        SELECT
            object_id,
            SUM(cost_usd) AS total_cost,
            AVG(cost_usd) AS avg_event_cost,
            SUM(cost_usd) / NULLIF(COUNT(DISTINCT DATE(run_date)), 0) AS avg_daily_cost,
            COUNT(*) AS record_count,
            COUNT(DISTINCT service) AS service_count
        FROM `{project_id}.{dataset_id}.factbilling`
        WHERE DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
            AND object_id IS NOT NULL
        GROUP BY object_id
        ORDER BY total_cost DESC
        LIMIT {limit}
        """

        results = client.query(query).result()
        portfolio = []
        for row in results:
            portfolio.append({
                "object_id": row.object_id,
                "total_cost_usd": float(row.total_cost),
                "avg_daily_cost_usd": float(row.avg_daily_cost) if row.avg_daily_cost else 0.0,
                "avg_event_cost_usd": float(row.avg_event_cost) if row.avg_event_cost else 0.0,
                "record_count": row.record_count,
                "service_count": row.service_count,
            })

        return {
            "status": "success",
            "lookback_days": lookback_days,
            "portfolio_count": len(portfolio),
            "portfolio": portfolio,
        }
    except Exception as e:
        logger.error(f"Error getting portfolio cost summary: {e}")
        return {"status": "error", "error": str(e)}


# ============================================================================
# COMPLETE ANALYSIS FUNCTION
# ============================================================================

def analyze_object_costs(
    project_id: str,
    object_id: str,
    days: int = 30,
    dataset_id: str = "minietl"
) -> CostAnalysis:
    """
    Complete cost analysis for an object.

    Orchestrates all FinOps Agent tools to produce comprehensive analysis.
    """
    try:
        # Query billing data
        billing_result = query_billing_data(project_id, object_id, days, dataset_id)
        billing_data = billing_result.get("billing_data", [])

        # Calculate cost metrics
        metrics_result = calculate_cost_metrics(billing_data)
        total_cost = metrics_result.get("total_cost_usd", 0.0)
        avg_daily_cost = metrics_result.get("avg_daily_cost_usd", 0.0)

        # Detect anomalies (informational)
        anomalies_result = detect_cost_anomalies(billing_data)

        # Calculate trends
        trend_result = calculate_cost_trend(billing_data)
        savings_opportunity = trend_result.get("savings_opportunity_percent", 0.0)
        daily_savings = trend_result.get("estimated_daily_savings_usd", 0.0)

        # Identify opportunities
        opportunities_result = identify_cost_savings_opportunities(
            object_id, billing_data, metrics_result
        )
        opportunities = opportunities_result.get("opportunities", [])

        # Build analysis result
        analysis = CostAnalysis(
            object_id=object_id,
            cost_data=[BillingTrend(**b) for b in billing_data],
            total_cost_period_usd=total_cost,
            avg_daily_cost_usd=avg_daily_cost,
            savings_opportunity_percent=savings_opportunity,
            estimated_daily_savings_usd=daily_savings,
            opportunities=[SavingsOpportunity(**o) for o in opportunities],
            service_breakdown=metrics_result.get("service_breakdown", {}),
            portfolio_summary=[],
            lookback_days=days,
        )

        return analysis

    except Exception as e:
        logger.error(f"Error in analyze_object_costs: {e}")
        return CostAnalysis(
            object_id=object_id,
            total_cost_period_usd=0.0,
            avg_daily_cost_usd=0.0,
        )
