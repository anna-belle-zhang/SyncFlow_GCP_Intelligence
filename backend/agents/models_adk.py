"""
Data models for ADK-based Architect Agent workflow.

Defines Pydantic schemas for:
- Architect review and prioritization
- Architecture proposals
- Impact analysis
- Audit logging
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============================================================================
# ENUMERATIONS
# ============================================================================

class Priority(str, Enum):
    """Priority levels assigned by architect during review."""
    CRITICAL = "CRITICAL"       # Key business process - immediate focus
    HIGH = "HIGH"               # Important - regular monitoring
    MEDIUM = "MEDIUM"           # Moderate impact - scheduled review
    LOW = "LOW"                 # Minimal impact - background monitoring
    DECOMMISSION = "DECOMMISSION"  # Target for removal - legacy/redundant


class ProposalType(str, Enum):
    """Types of architecture proposals generated."""
    CONSOLIDATION = "CONSOLIDATION"    # Merge multiple objects
    OPTIMIZATION = "OPTIMIZATION"      # Improve efficiency
    REDUNDANCY_REMOVAL = "REDUNDANCY_REMOVAL"  # Remove duplicate functionality
    DECOMMISSION = "DECOMMISSION"      # Plan removal
    ENHANCEMENT = "ENHANCEMENT"        # Improve capability


class ProposalStatus(str, Enum):
    """Status of an architecture proposal."""
    DRAFT = "DRAFT"             # Initial generation
    PRESENTED = "PRESENTED"     # Shown to architect
    APPROVED = "APPROVED"       # Approved by architect
    REJECTED = "REJECTED"       # Rejected by architect
    IMPLEMENTED = "IMPLEMENTED" # Applied to system
    CANCELLED = "CANCELLED"     # Canceled


class AuditAction(str, Enum):
    """Types of audit actions recorded."""
    PRIORITY_ASSIGNED = "PRIORITY_ASSIGNED"
    PROPOSAL_GENERATED = "PROPOSAL_GENERATED"
    PROPOSAL_APPROVED = "PROPOSAL_APPROVED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    PROPOSAL_IMPLEMENTED = "PROPOSAL_IMPLEMENTED"
    OBJECT_UPDATED = "OBJECT_UPDATED"
    EDGE_CREATED = "EDGE_CREATED"
    EDGE_UPDATED = "EDGE_UPDATED"
    DECOMMISSION_MARKED = "DECOMMISSION_MARKED"


# ============================================================================
# NODE & EDGE MODELS (Lineage Graph)
# ============================================================================

class LineageNode(BaseModel):
    """Represents a GCP object in the lineage graph."""
    object_id: str = Field(..., description="Unique object identifier")
    name: str = Field(..., description="Object name")
    object_type: str = Field(..., description="Type of GCP object")
    priority: Optional[Priority] = Field(None, description="Architect-assigned priority")
    is_decommission: bool = Field(False, description="Marked for decommission")
    upstream_count: int = Field(0, description="Number of upstream dependencies")
    downstream_count: int = Field(0, description="Number of downstream dependencies")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        use_enum_values = True


class LineageEdge(BaseModel):
    """Represents a dependency relationship between objects."""
    edge_id: str = Field(..., description="Unique edge identifier")
    source_object_id: str = Field(..., description="Source object ID")
    target_object_id: str = Field(..., description="Target object ID")
    edge_type: str = Field(..., description="Type of relationship")
    is_active: bool = Field(True, description="Whether edge is active")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


class LineageGraph(BaseModel):
    """Complete lineage graph structure."""
    nodes: List[LineageNode] = Field(default_factory=list, description="All objects")
    edges: List[LineageEdge] = Field(default_factory=list, description="All relationships")
    critical_nodes: List[str] = Field(default_factory=list, description="IDs of critical objects")
    critical_paths: List[List[str]] = Field(default_factory=list, description="Dependency chains")


# ============================================================================
# IMPACT ANALYSIS MODELS
# ============================================================================

class ImpactMetric(BaseModel):
    """Single impact metric for a proposal."""
    metric_name: str = Field(..., description="Name of metric (cost, latency, etc.)")
    current_value: Optional[float] = Field(None, description="Current value")
    projected_value: Optional[float] = Field(None, description="Value after proposal")
    improvement_pct: Optional[float] = Field(None, description="Percent improvement")
    confidence: float = Field(default=0.8, description="Confidence level (0-1)")


class ImpactAnalysis(BaseModel):
    """Analysis of how a proposal affects the system."""
    proposal_id: str = Field(..., description="Reference to proposal")
    affected_objects: List[str] = Field(default_factory=list, description="Objects affected")
    affected_edges: List[str] = Field(default_factory=list, description="Relationships affected")
    cost_impact_usd: Optional[float] = Field(None, description="Monthly cost change in USD")
    latency_impact_ms: Optional[int] = Field(None, description="Latency change in ms")
    availability_impact: Optional[str] = Field(None, description="Availability implications")
    risk_level: str = Field("LOW", description="Risk: LOW, MEDIUM, HIGH")
    estimated_effort_hours: Optional[int] = Field(None, description="Implementation effort")
    metrics: List[ImpactMetric] = Field(default_factory=list, description="Detailed metrics")

    class Config:
        use_enum_values = True


# ============================================================================
# PROPOSAL MODELS
# ============================================================================

class ConsolidationProposal(BaseModel):
    """Proposal to consolidate multiple objects into one."""
    source_objects: List[str] = Field(..., description="Objects to consolidate")
    target_object_id: Optional[str] = Field(None, description="Consolidated target object")
    consolidation_strategy: str = Field(..., description="How to consolidate (merge, migrate, etc.)")
    expected_cost_savings: float = Field(0.0, description="Monthly savings in USD")
    expected_simplification: str = Field("", description="How complexity decreases")


class OptimizationProposal(BaseModel):
    """Proposal to optimize an object."""
    target_object_id: str = Field(..., description="Object to optimize")
    optimization_type: str = Field(..., description="Type (resource sizing, caching, etc.)")
    rationale: str = Field(..., description="Why this optimization")
    expected_improvement: str = Field(..., description="Expected improvement")
    estimated_cost_savings: float = Field(0.0, description="Monthly savings in USD")


class DecommissionProposal(BaseModel):
    """Proposal to remove an object."""
    target_object_id: str = Field(..., description="Object to decommission")
    reason: str = Field(..., description="Why decommission")
    replacement_id: Optional[str] = Field(None, description="Replacement if any")
    migration_plan: str = Field("", description="Plan for migration/data transfer")
    estimated_cost_savings: float = Field(0.0, description="Monthly savings in USD")
    decommission_date: Optional[str] = Field(None, description="Target removal date")


class ArchitectProposal(BaseModel):
    """Architecture proposal generated by agent for architect review."""
    proposal_id: str = Field(..., description="Unique proposal identifier")
    object_id: str = Field(..., description="Object this proposal concerns")
    proposal_type: ProposalType = Field(..., description="Type of proposal")
    status: ProposalStatus = Field(default=ProposalStatus.DRAFT, description="Proposal status")
    title: str = Field(..., description="Proposal title")
    description: str = Field(..., description="Detailed proposal description")
    rationale: str = Field(..., description="Why agent recommends this")
    priority: Priority = Field(..., description="Priority of this proposal")

    # Specific proposal details (one will be populated)
    consolidation: Optional[ConsolidationProposal] = None
    optimization: Optional[OptimizationProposal] = None
    decommission: Optional[DecommissionProposal] = None

    # Impact analysis
    impact_analysis: Optional[ImpactAnalysis] = None

    # Tracking
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by_agent: str = Field(default="architect_agent")
    architect_notes: Optional[str] = None
    architect_decision_at: Optional[datetime] = None

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================================
# ARCHITECT REVIEW MODELS
# ============================================================================

class ArchitectReview(BaseModel):
    """Architect's review and prioritization of an object."""
    object_id: str = Field(..., description="Object being reviewed")
    priority: Priority = Field(..., description="Assigned priority level")
    is_decommission: bool = Field(False, description="Mark for decommission")
    decommission_reason: Optional[str] = Field(None, description="Reason for decommission")
    notes: str = Field("", description="Architect's notes for Ops/FinOps teams")
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = Field(None, description="Architect name/ID")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class ArchitectReviewBatch(BaseModel):
    """Batch of architect reviews for multiple objects."""
    reviews: List[ArchitectReview] = Field(..., description="Multiple reviews")
    batch_id: str = Field(..., description="Batch identifier")
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    total_objects: int = Field(0, description="Total objects reviewed")
    critical_count: int = Field(0, description="Objects marked CRITICAL")
    decommission_count: int = Field(0, description="Objects marked for decommission")


# ============================================================================
# AUDIT LOG MODELS
# ============================================================================

class AuditLogEntry(BaseModel):
    """Single audit log entry for architect activities."""
    audit_id: str = Field(..., description="Unique audit log ID")
    object_id: str = Field(..., description="Object involved")
    action: AuditAction = Field(..., description="Action taken")
    action_timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor: Optional[str] = Field(None, description="Person/agent who performed action")
    details: Dict[str, Any] = Field(default_factory=dict, description="Action details")
    change_from: Optional[Dict[str, Any]] = Field(None, description="Previous state")
    change_to: Optional[Dict[str, Any]] = Field(None, description="New state")

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class AuditLog(BaseModel):
    """Complete audit log for an object."""
    object_id: str = Field(..., description="Object being audited")
    entries: List[AuditLogEntry] = Field(default_factory=list, description="Log entries")
    first_review: Optional[datetime] = Field(None, description="First architect review")
    last_review: Optional[datetime] = Field(None, description="Most recent review")
    total_reviews: int = Field(0, description="Number of reviews")
    total_changes: int = Field(0, description="Number of applied changes")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================================
# WORKFLOW MODELS
# ============================================================================

class InventorySummary(BaseModel):
    """Summary of GCP inventory for architect review."""
    total_objects: int = Field(..., description="Total objects in inventory")
    objects_by_type: Dict[str, int] = Field(default_factory=dict, description="Count by type")
    objects_by_priority: Dict[str, int] = Field(default_factory=dict, description="Count by priority")
    unreviewed_count: int = Field(0, description="Objects not yet reviewed")
    critical_count: int = Field(0, description="Critical objects")
    decommission_candidates: int = Field(0, description="Objects marked for removal")
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class ArchitectWorkflowRequest(BaseModel):
    """Request to start architect workflow."""
    workflow_id: str = Field(..., description="Unique workflow identifier")
    architect_name: Optional[str] = Field(None, description="Name of architect")
    focus_priority: Optional[Priority] = Field(None, description="Focus on specific priority")
    include_lineage: bool = Field(True, description="Include lineage analysis")
    generate_proposals: bool = Field(True, description="Generate architecture proposals")
    started_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class ArchitectWorkflowResponse(BaseModel):
    """Response from architect workflow."""
    workflow_id: str = Field(..., description="Workflow identifier")
    status: str = Field(..., description="Status: STARTED, IN_PROGRESS, COMPLETED")
    inventory_summary: Optional[InventorySummary] = None
    lineage_graph: Optional[LineageGraph] = None
    proposals: List[ArchitectProposal] = Field(default_factory=list)
    reviews_collected: int = Field(0, description="Number of reviews collected")
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================================
# OPS AGENT MODELS (Performance & Reliability Intelligence)
# ============================================================================

class PerformanceMetric(BaseModel):
    """Daily performance metrics for an object."""
    run_date: str = Field(..., description="Date of metric (YYYY-MM-DD)")
    object_id: str = Field(..., description="Object being measured")
    executions: int = Field(..., description="Number of executions")
    successful: int = Field(..., description="Number of successful executions")
    failed: int = Field(..., description="Number of failed executions")
    success_rate: float = Field(..., description="Success rate (0-1)")
    avg_duration_seconds: float = Field(..., description="Average execution duration")
    min_duration_seconds: float = Field(..., description="Minimum execution duration")
    max_duration_seconds: float = Field(..., description="Maximum execution duration")
    duration_stddev: Optional[float] = Field(None, description="Standard deviation of duration")
    total_rows_processed: int = Field(..., description="Total rows processed")
    avg_throughput: float = Field(..., description="Average rows per execution")


class AnomalyAlert(BaseModel):
    """Performance anomaly detected by Ops Agent."""
    anomaly_id: str = Field(..., description="Unique anomaly identifier")
    object_id: str = Field(..., description="Object with anomaly")
    anomaly_type: str = Field(..., description="Type: PERFORMANCE_DEGRADATION, HIGH_FAILURE_RATE, etc.")
    severity: str = Field(..., description="CRITICAL, HIGH, MEDIUM, LOW")
    metric_name: str = Field(..., description="Metric with anomaly (duration, success_rate, etc.)")
    baseline_value: float = Field(..., description="Expected/baseline value")
    observed_value: float = Field(..., description="Actually observed value")
    deviation_stddev: float = Field(..., description="Number of standard deviations from baseline")
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    correlation_notes: Optional[str] = Field(None, description="Correlated events/changes")


class OptimizationRecommendation(BaseModel):
    """Ops Agent recommendation for optimization."""
    recommendation_id: str = Field(..., description="Unique recommendation ID")
    object_id: str = Field(..., description="Object to optimize")
    recommendation_type: str = Field(..., description="Type: SCALING, TIMEOUT_INCREASE, RETRY_POLICY, etc.")
    current_state: str = Field(..., description="Current configuration")
    recommended_state: str = Field(..., description="Recommended configuration")
    rationale: str = Field(..., description="Why this recommendation")
    expected_improvement_pct: float = Field(..., description="Expected improvement percentage")
    confidence: float = Field(default=0.8, description="Confidence level (0-1)")
    implementation_effort: str = Field(..., description="TRIVIAL, EASY, MODERATE, COMPLEX")


class OpsAnalysis(BaseModel):
    """Complete Ops Agent analysis result."""
    object_id: str = Field(..., description="Analyzed object")
    analysis_type: str = Field(default="Performance Analysis")
    daily_metrics: List[PerformanceMetric] = Field(default_factory=list, description="Daily metrics")
    trend_improvement_percent: float = Field(0.0, description="Trend % improvement vs time")
    anomalies_detected: List[AnomalyAlert] = Field(default_factory=list, description="Detected anomalies")
    recommendations: List[OptimizationRecommendation] = Field(default_factory=list)
    sla_compliance_percent: float = Field(100.0, description="SLA compliance percentage")
    portfolio_summary: List[Dict[str, Any]] = Field(default_factory=list, description="Top executing objects")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    lookback_days: int = Field(7, description="Analysis period in days")

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================================
# FINOPS AGENT MODELS (Cost Optimization & Analytics)
# ============================================================================

class BillingTrend(BaseModel):
    """Daily cost trend for an object."""
    cost_date: str = Field(..., description="Date (YYYY-MM-DD)")
    object_id: str = Field(..., description="Object being measured")
    service: str = Field(..., description="GCP service (Dataflow, BigQuery, etc.)")
    daily_cost_usd: float = Field(..., description="Cost for the day in USD")
    compute_units: Optional[float] = Field(None, description="Compute units consumed")
    slot_hours: Optional[float] = Field(None, description="BigQuery slot hours")


class SavingsOpportunity(BaseModel):
    """Cost savings opportunity identified by FinOps Agent."""
    opportunity_id: str = Field(..., description="Unique opportunity ID")
    object_id: str = Field(..., description="Object affected")
    service: str = Field(..., description="GCP service")
    opportunity_type: str = Field(..., description="Type: PARTITIONING, ARCHIVE, RIGHT_SIZING, COMMITMENT, etc.")
    current_cost_monthly_usd: float = Field(..., description="Current monthly cost")
    projected_cost_monthly_usd: float = Field(..., description="Cost after optimization")
    monthly_savings_usd: float = Field(..., description="Potential monthly savings")
    savings_pct: float = Field(..., description="Savings percentage")
    implementation_effort: str = Field(..., description="TRIVIAL, EASY, MODERATE, COMPLEX")
    roi_months: float = Field(..., description="Return on investment in months")
    details: Dict[str, Any] = Field(default_factory=dict, description="Optimization details")


class CostAnalysis(BaseModel):
    """Complete FinOps Agent cost analysis."""
    object_id: str = Field(..., description="Analyzed object")
    analysis_type: str = Field(default="Cost Analysis & Optimization")
    cost_data: List[BillingTrend] = Field(default_factory=list, description="Daily cost trends")
    total_cost_period_usd: float = Field(..., description="Total cost for period")
    avg_daily_cost_usd: float = Field(..., description="Average daily cost")
    savings_opportunity_percent: float = Field(0.0, description="Potential savings percentage")
    estimated_daily_savings_usd: float = Field(0.0, description="Estimated daily savings")
    opportunities: List[SavingsOpportunity] = Field(default_factory=list, description="Cost savings opportunities")
    service_breakdown: Dict[str, float] = Field(default_factory=dict, description="Cost by service")
    portfolio_summary: List[Dict[str, Any]] = Field(default_factory=list, description="Top cost objects")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    lookback_days: int = Field(30, description="Analysis period in days")

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================================
# DATABASE SCHEMA EXTENSIONS
# ============================================================================

# New columns to add to etlobjectscd2 table
ARCHITECT_REVIEW_COLUMNS = [
    {"name": "priority", "type": "STRING", "mode": "NULLABLE",
     "description": "Architect priority: CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION"},
    {"name": "is_decommission", "type": "BOOLEAN", "mode": "NULLABLE",
     "description": "Marked for decommission"},
    {"name": "decommission_reason", "type": "STRING", "mode": "NULLABLE",
     "description": "Reason for decommission"},
    {"name": "architect_notes", "type": "STRING", "mode": "NULLABLE",
     "description": "Architect's notes for Ops/FinOps teams"},
    {"name": "architect_review_timestamp", "type": "TIMESTAMP", "mode": "NULLABLE",
     "description": "When architect reviewed this object"},
]

# Schema for architect_proposals table
ARCHITECT_PROPOSALS_SCHEMA = [
    {"name": "proposal_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "proposal_type", "type": "STRING", "mode": "REQUIRED"},
    {"name": "status", "type": "STRING", "mode": "REQUIRED"},
    {"name": "title", "type": "STRING", "mode": "REQUIRED"},
    {"name": "description", "type": "STRING", "mode": "NULLABLE"},
    {"name": "rationale", "type": "STRING", "mode": "NULLABLE"},
    {"name": "priority", "type": "STRING", "mode": "REQUIRED"},
    {"name": "consolidation", "type": "JSON", "mode": "NULLABLE"},
    {"name": "optimization", "type": "JSON", "mode": "NULLABLE"},
    {"name": "decommission", "type": "JSON", "mode": "NULLABLE"},
    {"name": "impact_analysis", "type": "JSON", "mode": "NULLABLE"},
    {"name": "generated_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
    {"name": "generated_by_agent", "type": "STRING", "mode": "REQUIRED"},
    {"name": "architect_notes", "type": "STRING", "mode": "NULLABLE"},
    {"name": "architect_decision_at", "type": "TIMESTAMP", "mode": "NULLABLE"},
]

# Schema for architect_audit_log table
ARCHITECT_AUDIT_LOG_SCHEMA = [
    {"name": "audit_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "action", "type": "STRING", "mode": "REQUIRED"},
    {"name": "action_timestamp", "type": "TIMESTAMP", "mode": "REQUIRED"},
    {"name": "actor", "type": "STRING", "mode": "NULLABLE"},
    {"name": "details", "type": "JSON", "mode": "NULLABLE"},
    {"name": "change_from", "type": "JSON", "mode": "NULLABLE"},
    {"name": "change_to", "type": "JSON", "mode": "NULLABLE"},
]

# Schema for architect_diagrams table
ARCHITECT_DIAGRAMS_SCHEMA = [
    {"name": "diagram_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "object_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "diagram_name", "type": "STRING", "mode": "NULLABLE"},
    {"name": "diagram_format", "type": "STRING", "mode": "REQUIRED"},
    {"name": "diagram_text", "type": "STRING", "mode": "REQUIRED"},
    {"name": "is_active", "type": "BOOLEAN", "mode": "REQUIRED"},
    {"name": "generated_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
]
