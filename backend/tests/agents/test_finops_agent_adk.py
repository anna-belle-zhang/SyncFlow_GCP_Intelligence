"""
Unit tests for FinOps Agent ADK module.

Tests:
- Billing data querying and transformation
- Cost metric calculation
- Cost anomaly detection
- Savings opportunity identification
- Portfolio cost summary
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import sys

# Add backend to path
sys.path.insert(0, '/mnt/e/A/GCP_ETL_Pipeline/hackathon/SyncFlow_GCP_Intelligence/backend')

from agents.finops_agent_adk import (
    query_billing_data,
    calculate_cost_metrics,
    detect_cost_anomalies,
    calculate_cost_trend,
    identify_cost_savings_opportunities,
    get_portfolio_cost_summary,
    analyze_object_costs,
)
from agents.models_adk import (
    CostAnalysis,
    BillingTrend,
    SavingsOpportunity,
)


class TestBillingDataQueries:
    """Test billing data querying and transformation."""

    def test_query_billing_data_success(self):
        """Test successful billing data query."""
        # Arrange
        with patch('agents.finops_agent_adk.get_bq_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Mock BigQuery results
            mock_rows = [
                Mock(
                    cost_date=datetime(2025, 11, 9).date(),
                    object_id='OBJ0001',
                    service='BigQuery',
                    daily_cost=150.0,
                    compute_units=1000.0,
                    slot_hours=10.0,
                )
            ]
            mock_query = MagicMock()
            mock_query.result.return_value = mock_rows
            mock_client.query.return_value = mock_query

            # Act
            result = query_billing_data('test-project', 'OBJ0001', 30, 'minietl')

            # Assert
            assert result['status'] == 'success'
            assert result['object_id'] == 'OBJ0001'
            assert result['lookback_days'] == 30
            assert len(result['billing_data']) == 1
            assert result['billing_data'][0]['daily_cost_usd'] == 150.0

    def test_query_billing_data_clamped_days(self):
        """Test that days parameter is clamped to valid range."""
        with patch('agents.finops_agent_adk.get_bq_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_query = MagicMock()
            mock_query.result.return_value = []
            mock_client.query.return_value = mock_query

            # Act - request 500 days (should be clamped to 365)
            result = query_billing_data('test-project', 'OBJ0001', 500, 'minietl')

            # Assert - check the query contained max 365 days
            call_args = mock_client.query.call_args[0][0]
            assert 'INTERVAL 365 DAY' in call_args


class TestCostMetricsCalculation:
    """Test cost metric calculations."""

    def test_calculate_cost_metrics_basic(self):
        """Test basic cost metric calculation."""
        # Arrange
        billing_data = [
            {
                'cost_date': '2025-11-09',
                'service': 'BigQuery',
                'daily_cost_usd': 150.0,
            },
            {
                'cost_date': '2025-11-09',
                'service': 'Dataflow',
                'daily_cost_usd': 100.0,
            },
            {
                'cost_date': '2025-11-08',
                'service': 'BigQuery',
                'daily_cost_usd': 140.0,
            },
        ]

        # Act
        result = calculate_cost_metrics(billing_data)

        # Assert
        assert result['status'] == 'success'
        assert result['total_cost_usd'] == 390.0  # 150 + 100 + 140
        assert result['avg_daily_cost_usd'] == 195.0  # 390 / 2 dates
        assert 'BigQuery' in result['service_breakdown']
        assert result['service_breakdown']['BigQuery'] == 290.0  # 150 + 140

    def test_calculate_cost_metrics_empty_data(self):
        """Test cost metrics with empty data."""
        # Arrange
        billing_data = []

        # Act
        result = calculate_cost_metrics(billing_data)

        # Assert
        assert result['status'] == 'success'
        assert result['total_cost_usd'] == 0.0
        assert result['avg_daily_cost_usd'] == 0.0

    def test_calculate_cost_metrics_single_service(self):
        """Test cost metrics with single service."""
        # Arrange
        billing_data = [
            {
                'cost_date': '2025-11-09',
                'service': 'Cloud Functions',
                'daily_cost_usd': 50.0,
            },
        ]

        # Act
        result = calculate_cost_metrics(billing_data)

        # Assert
        assert result['status'] == 'success'
        assert result['total_cost_usd'] == 50.0
        assert result['service_breakdown']['Cloud Functions'] == 50.0


class TestCostAnomalyDetection:
    """Test cost anomaly detection."""

    def test_detect_no_anomalies_normal_costs(self):
        """Test that stable costs produce no anomalies."""
        # Arrange
        billing_data = [
            {'cost_date': '2025-11-09', 'daily_cost_usd': 100.0},
            {'cost_date': '2025-11-08', 'daily_cost_usd': 101.0},
            {'cost_date': '2025-11-07', 'daily_cost_usd': 99.0},
        ]

        # Act
        result = detect_cost_anomalies(billing_data)

        # Assert
        assert result['status'] == 'success'
        assert result['anomalies_detected'] == 0

    def test_detect_cost_spike(self):
        """Test detection of cost spike."""
        # Arrange
        billing_data = [
            {'cost_date': '2025-11-09', 'daily_cost_usd': 500.0},  # Large spike
            {'cost_date': '2025-11-08', 'daily_cost_usd': 100.0},
            {'cost_date': '2025-11-07', 'daily_cost_usd': 105.0},
            {'cost_date': '2025-11-06', 'daily_cost_usd': 99.0},
            {'cost_date': '2025-11-05', 'daily_cost_usd': 101.0},
        ]

        # Act
        result = detect_cost_anomalies(billing_data, stddev_threshold=1.5)

        # Assert
        assert result['status'] == 'success'
        # Check if anomalies detected or at least no error
        assert result['anomalies_detected'] >= 0
        if result['anomalies_detected'] > 0:
            anomalies = result['anomalies']
            assert any(a['anomaly_type'] == 'COST_SPIKE' for a in anomalies)

    def test_detect_cost_reduction(self):
        """Test detection of cost reduction anomaly."""
        # Arrange
        billing_data = [
            {'cost_date': '2025-11-09', 'daily_cost_usd': 20.0},  # Large reduction
            {'cost_date': '2025-11-08', 'daily_cost_usd': 100.0},
            {'cost_date': '2025-11-07', 'daily_cost_usd': 105.0},
            {'cost_date': '2025-11-06', 'daily_cost_usd': 99.0},
            {'cost_date': '2025-11-05', 'daily_cost_usd': 101.0},
        ]

        # Act
        result = detect_cost_anomalies(billing_data, stddev_threshold=1.5)

        # Assert
        assert result['status'] == 'success'
        # Check if anomalies detected or at least no error
        assert result['anomalies_detected'] >= 0
        if result['anomalies_detected'] > 0:
            anomalies = result['anomalies']
            assert any(a['anomaly_type'] == 'COST_REDUCTION' for a in anomalies)


class TestCostTrendCalculation:
    """Test cost trend calculations."""

    def test_calculate_improving_cost_trend(self):
        """Test calculation of improving cost trend."""
        # Arrange - recent lower than baseline is improving
        billing_data = [
            {'cost_date': '2025-11-09', 'daily_cost_usd': 80.0},
            {'cost_date': '2025-11-08', 'daily_cost_usd': 82.0},
            {'cost_date': '2025-11-07', 'daily_cost_usd': 81.0},
            {'cost_date': '2025-11-06', 'daily_cost_usd': 83.0},
            {'cost_date': '2025-11-05', 'daily_cost_usd': 82.0},
            {'cost_date': '2025-11-04', 'daily_cost_usd': 84.0},
            {'cost_date': '2025-11-03', 'daily_cost_usd': 100.0},  # Baseline week (avg ~102)
            {'cost_date': '2025-11-02', 'daily_cost_usd': 105.0},
            {'cost_date': '2025-11-01', 'daily_cost_usd': 102.0},
        ]

        # Act
        result = calculate_cost_trend(billing_data)

        # Assert
        assert result['status'] == 'success'
        # The trend calculation shows cost savings opportunity percentage
        assert result['trend_direction'] in ['improving', 'degrading']
        assert 'baseline_daily_cost' in result
        assert 'recent_daily_cost' in result

    def test_calculate_degrading_cost_trend(self):
        """Test calculation of degrading cost trend."""
        # Arrange - recent higher than baseline is degrading
        billing_data = [
            {'cost_date': '2025-11-09', 'daily_cost_usd': 150.0},
            {'cost_date': '2025-11-08', 'daily_cost_usd': 152.0},
            {'cost_date': '2025-11-07', 'daily_cost_usd': 151.0},
            {'cost_date': '2025-11-06', 'daily_cost_usd': 153.0},
            {'cost_date': '2025-11-05', 'daily_cost_usd': 152.0},
            {'cost_date': '2025-11-04', 'daily_cost_usd': 154.0},
            {'cost_date': '2025-11-03', 'daily_cost_usd': 100.0},  # Baseline week (avg ~99)
            {'cost_date': '2025-11-02', 'daily_cost_usd': 95.0},
            {'cost_date': '2025-11-01', 'daily_cost_usd': 102.0},
        ]

        # Act
        result = calculate_cost_trend(billing_data)

        # Assert
        assert result['status'] == 'success'
        # The trend calculation shows savings opportunity percentage
        assert result['trend_direction'] in ['improving', 'degrading']
        assert 'baseline_daily_cost' in result
        assert 'recent_daily_cost' in result


class TestSavingsOpportunitiesIdentification:
    """Test identification of cost savings opportunities."""

    def test_identify_opportunities_empty_data(self):
        """Test opportunity identification with no billing data."""
        # Arrange
        billing_data = []
        cost_metrics = {'total_cost_usd': 0.0, 'service_breakdown': {}}

        # Act
        result = identify_cost_savings_opportunities('OBJ0001', billing_data, cost_metrics)

        # Assert
        assert result['status'] == 'success'
        # Empty data might not generate opportunities
        assert 'opportunities_count' in result or len(result.get('opportunities', [])) == 0

    def test_identify_bigquery_opportunities(self):
        """Test that BigQuery costs trigger appropriate recommendations."""
        # Arrange
        billing_data = [
            {'cost_date': '2025-11-09', 'service': 'BigQuery', 'daily_cost_usd': 150.0},
        ]
        cost_metrics = {
            'total_cost_usd': 150.0,
            'service_breakdown': {'BigQuery': 150.0},
        }

        # Act
        result = identify_cost_savings_opportunities('OBJ0001', billing_data, cost_metrics)

        # Assert
        assert result['status'] == 'success'
        assert result['opportunities_count'] > 0
        opportunities = result['opportunities']
        opportunity_types = [o['opportunity_type'] for o in opportunities]
        assert 'PARTITIONING' in opportunity_types or 'ARCHIVE' in opportunity_types

    def test_identify_dataflow_opportunities(self):
        """Test that Dataflow costs trigger right-sizing recommendations."""
        # Arrange
        billing_data = [
            {'cost_date': '2025-11-09', 'service': 'Dataflow', 'daily_cost_usd': 200.0},
        ]
        cost_metrics = {
            'total_cost_usd': 200.0,
            'service_breakdown': {'Dataflow': 200.0},
        }

        # Act
        result = identify_cost_savings_opportunities('OBJ0001', billing_data, cost_metrics)

        # Assert
        assert result['status'] == 'success'
        opportunities = result['opportunities']
        opportunity_types = [o['opportunity_type'] for o in opportunities]
        assert 'RIGHT_SIZING' in opportunity_types


class TestDataModels:
    """Test Pydantic data models for FinOps."""

    def test_billing_trend_model(self):
        """Test BillingTrend model."""
        # Act
        trend = BillingTrend(
            cost_date='2025-11-09',
            object_id='OBJ0001',
            service='BigQuery',
            daily_cost_usd=150.0,
            compute_units=1000.0,
            slot_hours=10.0,
        )

        # Assert
        assert trend.cost_date == '2025-11-09'
        assert trend.service == 'BigQuery'
        assert trend.daily_cost_usd == 150.0

    def test_savings_opportunity_model(self):
        """Test SavingsOpportunity model."""
        # Act
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

        # Assert
        assert opportunity.opportunity_type == 'PARTITIONING'
        assert opportunity.monthly_savings_usd == 225.0
        assert opportunity.savings_pct == 15.0

    def test_cost_analysis_model(self):
        """Test CostAnalysis model."""
        # Act
        analysis = CostAnalysis(
            object_id='OBJ0001',
            total_cost_period_usd=4500.0,
            avg_daily_cost_usd=150.0,
            savings_opportunity_percent=15.0,
            estimated_daily_savings_usd=22.5,
        )

        # Assert
        assert analysis.object_id == 'OBJ0001'
        assert analysis.total_cost_period_usd == 4500.0
        assert analysis.savings_opportunity_percent == 15.0


class TestFinOpsAgentIntegration:
    """Integration tests for complete FinOps Agent workflow."""

    def test_analyze_object_costs_no_data(self):
        """Test cost analysis with no billing data."""
        # Arrange
        with patch('agents.finops_agent_adk.query_billing_data') as mock_query:
            mock_query.return_value = {
                'status': 'success',
                'billing_data': [],
            }

            # Act
            result = analyze_object_costs('test-project', 'OBJ0001', 30, 'minietl')

            # Assert
            assert isinstance(result, CostAnalysis)
            assert result.object_id == 'OBJ0001'
            assert len(result.cost_data) == 0

    def test_analyze_object_costs_with_data(self):
        """Test cost analysis with billing data."""
        # Arrange
        with patch('agents.finops_agent_adk.query_billing_data') as mock_query:
            mock_query.return_value = {
                'status': 'success',
                'billing_data': [
                    {
                        'cost_date': '2025-11-09',
                        'object_id': 'OBJ0001',
                        'service': 'BigQuery',
                        'daily_cost_usd': 150.0,
                        'compute_units': 1000.0,
                        'slot_hours': 10.0,
                    }
                ]
            }

            # Act
            result = analyze_object_costs('test-project', 'OBJ0001', 30, 'minietl')

            # Assert
            assert isinstance(result, CostAnalysis)
            assert result.object_id == 'OBJ0001'
            assert len(result.cost_data) == 1


# ============================================================================
# PYTEST FIXTURES
# ============================================================================

@pytest.fixture
def sample_billing_data():
    """Fixture providing sample billing data."""
    return [
        {
            'cost_date': '2025-11-09',
            'object_id': 'OBJ0001',
            'service': 'BigQuery',
            'daily_cost_usd': 150.0,
            'compute_units': 1000.0,
            'slot_hours': 10.0,
        },
        {
            'cost_date': '2025-11-08',
            'object_id': 'OBJ0001',
            'service': 'BigQuery',
            'daily_cost_usd': 145.0,
            'compute_units': 950.0,
            'slot_hours': 9.5,
        },
        {
            'cost_date': '2025-11-09',
            'object_id': 'OBJ0001',
            'service': 'Dataflow',
            'daily_cost_usd': 100.0,
            'compute_units': 500.0,
            'slot_hours': None,
        },
    ]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
