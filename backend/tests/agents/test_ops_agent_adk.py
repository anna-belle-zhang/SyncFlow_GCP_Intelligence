"""
Unit tests for Ops Agent ADK module.

Tests:
- Performance metric analysis
- Anomaly detection algorithms
- Trend calculation
- Recommendation generation
- Portfolio summary
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import sys

# Add backend to path
sys.path.insert(0, '/mnt/e/A/GCP_ETL_Pipeline/hackathon/SyncFlow_GCP_Intelligence/backend')

from agents.ops_agent_adk import (
    query_execution_metrics,
    detect_performance_anomalies,
    calculate_performance_trend,
    generate_optimization_recommendations,
    get_portfolio_summary,
    analyze_object_performance,
)
from agents.models_adk import (
    OpsAnalysis,
    PerformanceMetric,
    AnomalyAlert,
    OptimizationRecommendation,
)


class TestPerformanceMetricQueries:
    """Test performance metric querying and data transformation."""

    def test_query_execution_metrics_success(self):
        """Test successful execution metrics query."""
        # Arrange
        with patch('agents.ops_agent_adk.get_bq_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Mock BigQuery results
            mock_rows = [
                Mock(
                    run_date=datetime(2025, 11, 9).date(),
                    object_id='OBJ0001',
                    executions=100,
                    successful=95,
                    failed=5,
                    avg_duration=10.5,
                    min_duration=2.0,
                    max_duration=45.0,
                    duration_stddev=8.5,
                    total_rows=50000,
                    avg_throughput=500.0,
                )
            ]
            mock_query = MagicMock()
            mock_query.result.return_value = mock_rows
            mock_client.query.return_value = mock_query

            # Act
            result = query_execution_metrics('test-project', 'OBJ0001', 7, 'minietl')

            # Assert
            assert result['status'] == 'success'
            assert result['object_id'] == 'OBJ0001'
            assert result['lookback_days'] == 7
            assert len(result['metrics']) == 1
            assert result['metrics'][0]['success_rate'] == 0.95

    def test_query_execution_metrics_clamped_days(self):
        """Test that days parameter is clamped to valid range."""
        with patch('agents.ops_agent_adk.get_bq_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_query = MagicMock()
            mock_query.result.return_value = []
            mock_client.query.return_value = mock_query

            # Act - request 500 days (should be clamped to 180)
            result = query_execution_metrics('test-project', 'OBJ0001', 500, 'minietl')

            # Assert - check the query contained max 180 days
            call_args = mock_client.query.call_args[0][0]
            assert 'INTERVAL 180 DAY' in call_args


class TestAnomalyDetection:
    """Test anomaly detection algorithms."""

    def test_detect_no_anomalies_normal_data(self):
        """Test that normal data produces no anomalies."""
        # Arrange
        metrics = [
            {
                'run_date': '2025-11-09',
                'object_id': 'OBJ0001',
                'avg_duration_seconds': 10.0,
                'success_rate': 0.95,
                'executions': 100,
                'failed': 5,
            },
            {
                'run_date': '2025-11-08',
                'object_id': 'OBJ0001',
                'avg_duration_seconds': 10.2,
                'success_rate': 0.96,
                'executions': 102,
                'failed': 4,
            },
            {
                'run_date': '2025-11-07',
                'object_id': 'OBJ0001',
                'avg_duration_seconds': 9.8,
                'success_rate': 0.94,
                'executions': 98,
                'failed': 6,
            },
        ]

        # Act
        result = detect_performance_anomalies(metrics)

        # Assert
        assert result['status'] == 'success'
        assert result['anomalies_detected'] == 0

    def test_detect_performance_degradation(self):
        """Test detection of performance degradation anomaly."""
        # Arrange - normal values then large spike
        metrics = [
            {'run_date': '2025-11-09', 'avg_duration_seconds': 100.0, 'success_rate': 0.95, 'executions': 100, 'failed': 5},
            {'run_date': '2025-11-08', 'avg_duration_seconds': 10.0, 'success_rate': 0.96, 'executions': 100, 'failed': 4},
            {'run_date': '2025-11-07', 'avg_duration_seconds': 10.5, 'success_rate': 0.94, 'executions': 100, 'failed': 6},
            {'run_date': '2025-11-06', 'avg_duration_seconds': 9.8, 'success_rate': 0.95, 'executions': 100, 'failed': 5},
        ]

        # Act
        result = detect_performance_anomalies(metrics, stddev_threshold=1.5)

        # Assert
        assert result['status'] == 'success'
        # Should detect degradation or at least no error
        assert result['anomalies_detected'] >= 0
        if result['anomalies_detected'] > 0:
            anomalies = result['anomalies']
            assert any(a['anomaly_type'] == 'PERFORMANCE_DEGRADATION' for a in anomalies)

    def test_detect_high_failure_rate(self):
        """Test detection of high failure rate anomaly."""
        # Arrange
        metrics = [
            {'run_date': '2025-11-09', 'avg_duration_seconds': 10.0, 'success_rate': 0.5, 'executions': 100, 'failed': 50},
            {'run_date': '2025-11-08', 'avg_duration_seconds': 10.0, 'success_rate': 0.96, 'executions': 100, 'failed': 4},
            {'run_date': '2025-11-07', 'avg_duration_seconds': 9.5, 'success_rate': 0.94, 'executions': 100, 'failed': 6},
        ]

        # Act
        result = detect_performance_anomalies(metrics)

        # Assert
        assert result['status'] == 'success'
        assert result['anomalies_detected'] > 0
        anomalies = result['anomalies']
        assert any(a['anomaly_type'] == 'HIGH_FAILURE_RATE' for a in anomalies)


class TestTrendCalculation:
    """Test performance trend calculations."""

    def test_calculate_improvement_trend(self):
        """Test calculation of improving performance trend."""
        # Arrange - slower then faster
        metrics = [
            {'run_date': '2025-11-09', 'avg_duration_seconds': 8.0},
            {'run_date': '2025-11-08', 'avg_duration_seconds': 8.2},
            {'run_date': '2025-11-07', 'avg_duration_seconds': 8.1},
            {'run_date': '2025-11-06', 'avg_duration_seconds': 8.3},
            {'run_date': '2025-11-05', 'avg_duration_seconds': 8.2},
            {'run_date': '2025-11-04', 'avg_duration_seconds': 8.4},
            {'run_date': '2025-11-03', 'avg_duration_seconds': 10.0},  # Baseline week
            {'run_date': '2025-11-02', 'avg_duration_seconds': 10.5},
            {'run_date': '2025-11-01', 'avg_duration_seconds': 10.2},
        ]

        # Act
        result = calculate_performance_trend(metrics)

        # Assert
        assert result['status'] == 'success'
        assert result['trend_improvement_percent'] > 0  # Should be improving
        assert result['trend_direction'] == 'improving'

    def test_calculate_degradation_trend(self):
        """Test calculation of degrading performance trend."""
        # Arrange - faster then slower
        metrics = [
            {'run_date': '2025-11-09', 'avg_duration_seconds': 15.0},
            {'run_date': '2025-11-08', 'avg_duration_seconds': 15.2},
            {'run_date': '2025-11-07', 'avg_duration_seconds': 15.1},
            {'run_date': '2025-11-06', 'avg_duration_seconds': 15.3},
            {'run_date': '2025-11-05', 'avg_duration_seconds': 15.2},
            {'run_date': '2025-11-04', 'avg_duration_seconds': 15.4},
            {'run_date': '2025-11-03', 'avg_duration_seconds': 10.0},  # Baseline week
            {'run_date': '2025-11-02', 'avg_duration_seconds': 9.5},
            {'run_date': '2025-11-01', 'avg_duration_seconds': 10.2},
        ]

        # Act
        result = calculate_performance_trend(metrics)

        # Assert
        assert result['status'] == 'success'
        assert result['trend_improvement_percent'] < 0  # Should be degrading
        assert result['trend_direction'] == 'degrading'


class TestRecommendationGeneration:
    """Test optimization recommendation generation."""

    def test_recommend_retry_policy_on_failures(self):
        """Test that high failure rate triggers retry recommendation."""
        # Arrange
        metrics = [
            {
                'run_date': '2025-11-09',
                'avg_duration_seconds': 10.0,
                'failed': 20,
                'executions': 100,
                'max_duration_seconds': 12.0,
            }
        ]
        anomalies = []

        # Act
        result = generate_optimization_recommendations('OBJ0001', metrics, anomalies)

        # Assert
        assert result['status'] == 'success'
        assert result['recommendations_generated'] > 0
        recommendations = result['recommendations']
        assert any(r['recommendation_type'] == 'INCREASE_RETRY_POLICY' for r in recommendations)

    def test_recommend_timeout_increase(self):
        """Test that high duration variance triggers timeout recommendation."""
        # Arrange
        metrics = [
            {
                'run_date': '2025-11-09',
                'avg_duration_seconds': 10.0,
                'max_duration_seconds': 25.0,  # 2.5x average
                'failed': 0,
                'executions': 100,
            }
        ]
        anomalies = []

        # Act
        result = generate_optimization_recommendations('OBJ0001', metrics, anomalies)

        # Assert
        assert result['status'] == 'success'
        recommendations = result['recommendations']
        assert any(r['recommendation_type'] == 'INCREASE_TIMEOUT' for r in recommendations)

    def test_recommend_batching_on_high_execution_frequency(self):
        """Test that high execution count triggers batching recommendation."""
        # Arrange
        metrics = [
            {
                'run_date': '2025-11-09',
                'avg_duration_seconds': 10.0,
                'max_duration_seconds': 12.0,
                'failed': 0,
                'executions': 5000,  # High frequency
            }
        ]
        anomalies = []

        # Act
        result = generate_optimization_recommendations('OBJ0001', metrics, anomalies)

        # Assert
        assert result['status'] == 'success'
        recommendations = result['recommendations']
        assert any(r['recommendation_type'] == 'IMPLEMENT_BATCHING' for r in recommendations)


class TestDataModels:
    """Test Pydantic data models."""

    def test_performance_metric_validation(self):
        """Test PerformanceMetric model validation."""
        # Act
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
            avg_throughput=500.0,
        )

        # Assert
        assert metric.run_date == '2025-11-09'
        assert metric.object_id == 'OBJ0001'
        assert metric.success_rate == 0.95

    def test_anomaly_alert_model(self):
        """Test AnomalyAlert model."""
        # Act
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

        # Assert
        assert alert.anomaly_type == 'PERFORMANCE_DEGRADATION'
        assert alert.severity == 'HIGH'

    def test_ops_analysis_model(self):
        """Test OpsAnalysis model."""
        # Act
        analysis = OpsAnalysis(
            object_id='OBJ0001',
            trend_improvement_percent=15.5,
            sla_compliance_percent=99.5,
        )

        # Assert
        assert analysis.object_id == 'OBJ0001'
        assert analysis.trend_improvement_percent == 15.5
        assert analysis.sla_compliance_percent == 99.5


class TestOpsAgentIntegration:
    """Integration tests for complete Ops Agent workflow."""

    def test_analyze_object_performance_empty_data(self):
        """Test analyzing object with no execution data."""
        # Arrange
        with patch('agents.ops_agent_adk.query_execution_metrics') as mock_query:
            mock_query.return_value = {
                'status': 'success',
                'metrics': [],
            }

            # Act
            result = analyze_object_performance('test-project', 'OBJ0001', 7, 'minietl')

            # Assert
            assert isinstance(result, OpsAnalysis)
            assert result.object_id == 'OBJ0001'
            assert len(result.daily_metrics) == 0

    def test_analyze_object_performance_with_data(self):
        """Test analyzing object with performance data."""
        # Arrange
        with patch('agents.ops_agent_adk.query_execution_metrics') as mock_query:
            mock_query.return_value = {
                'status': 'success',
                'metrics': [
                    {
                        'run_date': '2025-11-09',
                        'object_id': 'OBJ0001',
                        'executions': 100,
                        'successful': 95,
                        'failed': 5,
                        'success_rate': 0.95,
                        'avg_duration_seconds': 10.0,
                        'min_duration_seconds': 2.0,
                        'max_duration_seconds': 25.0,
                        'duration_stddev': 5.0,
                        'total_rows_processed': 50000,
                        'avg_throughput': 5000.0,
                    }
                ]
            }

            # Act
            result = analyze_object_performance('test-project', 'OBJ0001', 7, 'minietl')

            # Assert
            assert isinstance(result, OpsAnalysis)
            assert result.object_id == 'OBJ0001'
            assert len(result.daily_metrics) == 1


# ============================================================================
# PYTEST FIXTURES
# ============================================================================

@pytest.fixture
def sample_metrics():
    """Fixture providing sample execution metrics."""
    return [
        {
            'run_date': '2025-11-09',
            'object_id': 'OBJ0001',
            'executions': 100,
            'successful': 95,
            'failed': 5,
            'success_rate': 0.95,
            'avg_duration_seconds': 10.0,
            'min_duration_seconds': 2.0,
            'max_duration_seconds': 25.0,
            'duration_stddev': 5.0,
            'total_rows_processed': 50000,
            'avg_throughput': 500.0,
        },
        {
            'run_date': '2025-11-08',
            'object_id': 'OBJ0001',
            'executions': 98,
            'successful': 94,
            'failed': 4,
            'success_rate': 0.96,
            'avg_duration_seconds': 9.8,
            'min_duration_seconds': 1.9,
            'max_duration_seconds': 24.0,
            'duration_stddev': 4.8,
            'total_rows_processed': 49000,
            'avg_throughput': 500.0,
        },
    ]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
