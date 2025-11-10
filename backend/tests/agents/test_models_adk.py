"""
Unit tests for ADK data models.

Tests validation, serialization, and JSON encoding of Pydantic models.
"""

import pytest
from datetime import datetime
import json
import sys

sys.path.insert(0, '/mnt/e/A/GCP_ETL_Pipeline/hackathon/SyncFlow_GCP_Intelligence/backend')

from agents.models_adk import (
    # Enums
    Priority,
    ProposalType,
    ProposalStatus,
    AuditAction,
    # Lineage models
    LineageNode,
    LineageEdge,
    LineageGraph,
    # Impact analysis
    ImpactMetric,
    ImpactAnalysis,
    # Proposals
    ConsolidationProposal,
    OptimizationProposal,
    DecommissionProposal,
    ArchitectProposal,
    # Review and audit
    ArchitectReview,
    AuditLogEntry,
    # Ops models
    PerformanceMetric,
    AnomalyAlert,
    OptimizationRecommendation,
    OpsAnalysis,
    # FinOps models
    BillingTrend,
    SavingsOpportunity,
    CostAnalysis,
    # Workflow
    InventorySummary,
)


class TestEnumerations:
    """Test enumeration types."""

    def test_priority_enum(self):
        """Test Priority enumeration."""
        assert Priority.CRITICAL == "CRITICAL"
        assert Priority.HIGH == "HIGH"
        assert Priority.MEDIUM == "MEDIUM"
        assert Priority.LOW == "LOW"
        assert Priority.DECOMMISSION == "DECOMMISSION"

    def test_proposal_type_enum(self):
        """Test ProposalType enumeration."""
        assert ProposalType.CONSOLIDATION == "CONSOLIDATION"
        assert ProposalType.OPTIMIZATION == "OPTIMIZATION"
        assert ProposalType.REDUNDANCY_REMOVAL == "REDUNDANCY_REMOVAL"
        assert ProposalType.DECOMMISSION == "DECOMMISSION"
        assert ProposalType.ENHANCEMENT == "ENHANCEMENT"

    def test_proposal_status_enum(self):
        """Test ProposalStatus enumeration."""
        assert ProposalStatus.DRAFT == "DRAFT"
        assert ProposalStatus.PRESENTED == "PRESENTED"
        assert ProposalStatus.APPROVED == "APPROVED"
        assert ProposalStatus.REJECTED == "REJECTED"
        assert ProposalStatus.IMPLEMENTED == "IMPLEMENTED"
        assert ProposalStatus.CANCELLED == "CANCELLED"

    def test_audit_action_enum(self):
        """Test AuditAction enumeration."""
        assert AuditAction.PRIORITY_ASSIGNED == "PRIORITY_ASSIGNED"
        assert AuditAction.PROPOSAL_GENERATED == "PROPOSAL_GENERATED"
        assert AuditAction.DECOMMISSION_MARKED == "DECOMMISSION_MARKED"


class TestLineageModels:
    """Test lineage graph models."""

    def test_lineage_node_creation(self):
        """Test creating a lineage node."""
        node = LineageNode(
            object_id='OBJ0001',
            name='user_data_processor',
            object_type='Cloud Function',
            priority=Priority.CRITICAL,
            is_decommission=False,
            upstream_count=2,
            downstream_count=3,
        )

        assert node.object_id == 'OBJ0001'
        assert node.name == 'user_data_processor'
        assert node.priority == Priority.CRITICAL

    def test_lineage_edge_creation(self):
        """Test creating a lineage edge."""
        edge = LineageEdge(
            edge_id='edge-001',
            source_object_id='OBJ0001',
            target_object_id='OBJ0002',
            edge_type='data_dependency',
            is_active=True,
        )

        assert edge.source_object_id == 'OBJ0001'
        assert edge.target_object_id == 'OBJ0002'
        assert edge.is_active is True

    def test_lineage_graph_creation(self):
        """Test creating a lineage graph."""
        nodes = [
            LineageNode(
                object_id='OBJ0001',
                name='source',
                object_type='Cloud Function',
                upstream_count=0,
                downstream_count=1,
            ),
            LineageNode(
                object_id='OBJ0002',
                name='target',
                object_type='BigQuery Table',
                upstream_count=1,
                downstream_count=0,
            ),
        ]
        edges = [
            LineageEdge(
                edge_id='edge-001',
                source_object_id='OBJ0001',
                target_object_id='OBJ0002',
                edge_type='data_dependency',
            )
        ]

        graph = LineageGraph(
            nodes=nodes,
            edges=edges,
            critical_nodes=['OBJ0001'],
            critical_paths=[['OBJ0001', 'OBJ0002']],
        )

        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert 'OBJ0001' in graph.critical_nodes


class TestImpactAnalysisModels:
    """Test impact analysis models."""

    def test_impact_metric_creation(self):
        """Test creating an impact metric."""
        metric = ImpactMetric(
            metric_name='cost_usd',
            current_value=1500.0,
            projected_value=1275.0,
            improvement_pct=15.0,
            confidence=0.85,
        )

        assert metric.metric_name == 'cost_usd'
        assert metric.improvement_pct == 15.0
        assert metric.confidence == 0.85

    def test_impact_analysis_creation(self):
        """Test creating impact analysis."""
        analysis = ImpactAnalysis(
            proposal_id='prop-001',
            affected_objects=['OBJ0001', 'OBJ0002'],
            cost_impact_usd=-225.0,
            latency_impact_ms=50,
            risk_level='MEDIUM',
            estimated_effort_hours=16,
        )

        assert analysis.proposal_id == 'prop-001'
        assert len(analysis.affected_objects) == 2
        assert analysis.cost_impact_usd == -225.0


class TestProposalModels:
    """Test architecture proposal models."""

    def test_consolidation_proposal(self):
        """Test consolidation proposal model."""
        proposal = ConsolidationProposal(
            source_objects=['OBJ0001', 'OBJ0002'],
            target_object_id='OBJ0003',
            consolidation_strategy='merge',
            expected_cost_savings=500.0,
            expected_simplification='Reduce cloud function count from 2 to 1',
        )

        assert len(proposal.source_objects) == 2
        assert proposal.target_object_id == 'OBJ0003'
        assert proposal.expected_cost_savings == 500.0

    def test_optimization_proposal(self):
        """Test optimization proposal model."""
        proposal = OptimizationProposal(
            target_object_id='OBJ0001',
            optimization_type='resource sizing',
            rationale='Current machine type is oversized for workload',
            expected_improvement='15% cost reduction',
            estimated_cost_savings=225.0,
        )

        assert proposal.target_object_id == 'OBJ0001'
        assert proposal.estimated_cost_savings == 225.0

    def test_decommission_proposal(self):
        """Test decommission proposal model."""
        proposal = DecommissionProposal(
            target_object_id='OBJ0001',
            reason='Replaced by newer system',
            replacement_id='OBJ0002',
            migration_plan='Data migration completed on 2025-11-01',
            estimated_cost_savings=1000.0,
            decommission_date='2025-11-15',
        )

        assert proposal.target_object_id == 'OBJ0001'
        assert proposal.replacement_id == 'OBJ0002'
        assert proposal.estimated_cost_savings == 1000.0

    def test_architect_proposal_creation(self):
        """Test creating complete architect proposal."""
        proposal = ArchitectProposal(
            proposal_id='prop-001',
            object_id='OBJ0001',
            proposal_type=ProposalType.OPTIMIZATION,
            status=ProposalStatus.DRAFT,
            title='Optimize Object OBJ0001',
            description='Recommend resizing for cost optimization',
            rationale='Current resource allocation exceeds requirements',
            priority=Priority.HIGH,
            optimization=OptimizationProposal(
                target_object_id='OBJ0001',
                optimization_type='resource sizing',
                rationale='Oversized',
                expected_improvement='15% savings',
                estimated_cost_savings=225.0,
            ),
        )

        assert proposal.proposal_type == ProposalType.OPTIMIZATION
        assert proposal.status == ProposalStatus.DRAFT
        assert proposal.optimization is not None


class TestReviewAndAuditModels:
    """Test review and audit log models."""

    def test_architect_review_creation(self):
        """Test creating architect review."""
        review = ArchitectReview(
            object_id='OBJ0001',
            priority=Priority.CRITICAL,
            is_decommission=False,
            notes='Critical for business process. Monitor closely.',
            reviewed_by='alice@company.com',
        )

        assert review.object_id == 'OBJ0001'
        assert review.priority == Priority.CRITICAL
        assert review.reviewed_by == 'alice@company.com'

    def test_audit_log_entry_creation(self):
        """Test creating audit log entry."""
        entry = AuditLogEntry(
            audit_id='audit-001',
            object_id='OBJ0001',
            action=AuditAction.PRIORITY_ASSIGNED,
            actor='alice@company.com',
            details={'priority': 'CRITICAL'},
            change_from={'priority': None},
            change_to={'priority': 'CRITICAL'},
        )

        assert entry.action == AuditAction.PRIORITY_ASSIGNED
        assert entry.actor == 'alice@company.com'
        assert entry.details['priority'] == 'CRITICAL'


class TestOpsModels:
    """Test Ops Agent data models."""

    def test_performance_metric_validation(self):
        """Test PerformanceMetric model validation."""
        metric = PerformanceMetric(
            run_date='2025-11-09',
            object_id='OBJ0001',
            executions=100,
            successful=95,
            failed=5,
            success_rate=0.95,
            avg_duration_seconds=10.5,
            min_duration_seconds=2.0,
            max_duration_seconds=45.0,
            total_rows_processed=50000,
            avg_throughput=5000.0,
        )

        assert metric.success_rate == 0.95
        assert metric.avg_duration_seconds == 10.5

    def test_anomaly_alert_creation(self):
        """Test AnomalyAlert model creation."""
        alert = AnomalyAlert(
            anomaly_id='anom-001',
            object_id='OBJ0001',
            anomaly_type='PERFORMANCE_DEGRADATION',
            severity='HIGH',
            metric_name='avg_duration_seconds',
            baseline_value=10.0,
            observed_value=50.0,
            deviation_stddev=2.5,
        )

        assert alert.anomaly_type == 'PERFORMANCE_DEGRADATION'
        assert alert.deviation_stddev == 2.5

    def test_optimization_recommendation_creation(self):
        """Test OptimizationRecommendation model creation."""
        rec = OptimizationRecommendation(
            recommendation_id='rec-001',
            object_id='OBJ0001',
            recommendation_type='INCREASE_RETRY_POLICY',
            current_state='3 retries',
            recommended_state='5 retries, exponential backoff',
            rationale='High failure rate detected',
            expected_improvement_pct=15.0,
            confidence=0.85,
            implementation_effort='EASY',
        )

        assert rec.recommendation_type == 'INCREASE_RETRY_POLICY'
        assert rec.expected_improvement_pct == 15.0

    def test_ops_analysis_creation(self):
        """Test OpsAnalysis model creation."""
        analysis = OpsAnalysis(
            object_id='OBJ0001',
            trend_improvement_percent=15.5,
            sla_compliance_percent=99.5,
            lookback_days=7,
        )

        assert analysis.object_id == 'OBJ0001'
        assert analysis.trend_improvement_percent == 15.5


class TestFinOpsModels:
    """Test FinOps Agent data models."""

    def test_billing_trend_creation(self):
        """Test BillingTrend model creation."""
        trend = BillingTrend(
            cost_date='2025-11-09',
            object_id='OBJ0001',
            service='BigQuery',
            daily_cost_usd=150.0,
            compute_units=1000.0,
            slot_hours=10.0,
        )

        assert trend.service == 'BigQuery'
        assert trend.daily_cost_usd == 150.0

    def test_savings_opportunity_creation(self):
        """Test SavingsOpportunity model creation."""
        opportunity = SavingsOpportunity(
            opportunity_id='opp-001',
            object_id='OBJ0001',
            service='BigQuery',
            opportunity_type='PARTITIONING',
            current_cost_monthly_usd=1500.0,
            projected_cost_monthly_usd=1275.0,
            monthly_savings_usd=225.0,
            savings_pct=15.0,
            implementation_effort='MODERATE',
            roi_months=1.0,
        )

        assert opportunity.opportunity_type == 'PARTITIONING'
        assert opportunity.monthly_savings_usd == 225.0

    def test_cost_analysis_creation(self):
        """Test CostAnalysis model creation."""
        analysis = CostAnalysis(
            object_id='OBJ0001',
            total_cost_period_usd=4500.0,
            avg_daily_cost_usd=150.0,
            savings_opportunity_percent=15.0,
            estimated_daily_savings_usd=22.5,
            lookback_days=30,
        )

        assert analysis.total_cost_period_usd == 4500.0
        assert analysis.savings_opportunity_percent == 15.0


class TestJsonSerialization:
    """Test JSON serialization of models."""

    def test_ops_analysis_json_serialization(self):
        """Test OpsAnalysis JSON serialization."""
        analysis = OpsAnalysis(
            object_id='OBJ0001',
            trend_improvement_percent=15.5,
        )

        # Should be JSON serializable
        json_str = analysis.model_dump_json()
        assert '"object_id":"OBJ0001"' in json_str
        assert '"trend_improvement_percent":15.5' in json_str

    def test_cost_analysis_json_serialization(self):
        """Test CostAnalysis JSON serialization."""
        analysis = CostAnalysis(
            object_id='OBJ0001',
            total_cost_period_usd=4500.0,
            avg_daily_cost_usd=150.0,
        )

        # Should be JSON serializable
        json_str = analysis.model_dump_json()
        assert '"object_id":"OBJ0001"' in json_str
        assert '"total_cost_period_usd":4500.0' in json_str

    def test_lineage_graph_json_serialization(self):
        """Test LineageGraph JSON serialization."""
        graph = LineageGraph(
            nodes=[
                LineageNode(
                    object_id='OBJ0001',
                    name='test',
                    object_type='Cloud Function',
                )
            ]
        )

        json_str = graph.model_dump_json()
        assert '"object_id":"OBJ0001"' in json_str


class TestModelValidation:
    """Test model field validation."""

    def test_performance_metric_required_fields(self):
        """Test that PerformanceMetric requires essential fields."""
        with pytest.raises(Exception):  # Pydantic validation error
            PerformanceMetric(
                run_date='2025-11-09',
                # Missing required fields
            )

    def test_anomaly_alert_required_fields(self):
        """Test that AnomalyAlert requires essential fields."""
        with pytest.raises(Exception):
            AnomalyAlert(
                anomaly_id='anom-001',
                # Missing required fields
            )

    def test_cost_analysis_required_fields(self):
        """Test that CostAnalysis requires essential fields."""
        with pytest.raises(Exception):
            CostAnalysis(
                object_id='OBJ0001',
                # Missing required total_cost_period_usd
            )


class TestModelDefaults:
    """Test default values in models."""

    def test_performance_metric_optional_duration_stddev(self):
        """Test that duration_stddev is optional in PerformanceMetric."""
        metric = PerformanceMetric(
            run_date='2025-11-09',
            object_id='OBJ0001',
            executions=100,
            successful=95,
            failed=5,
            success_rate=0.95,
            avg_duration_seconds=10.5,
            min_duration_seconds=2.0,
            max_duration_seconds=45.0,
            total_rows_processed=50000,
            avg_throughput=5000.0,
            # duration_stddev not provided
        )

        assert metric.duration_stddev is None

    def test_ops_analysis_default_values(self):
        """Test OpsAnalysis default values."""
        analysis = OpsAnalysis(
            object_id='OBJ0001',
        )

        assert analysis.trend_improvement_percent == 0.0
        assert analysis.sla_compliance_percent == 100.0
        assert analysis.lookback_days == 7

    def test_cost_analysis_default_values(self):
        """Test CostAnalysis default values."""
        analysis = CostAnalysis(
            object_id='OBJ0001',
            total_cost_period_usd=1000.0,
            avg_daily_cost_usd=33.33,
        )

        assert analysis.savings_opportunity_percent == 0.0
        assert analysis.estimated_daily_savings_usd == 0.0
        assert analysis.lookback_days == 30


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
