"""
ETL Objects Logs Explorer

Comprehensive logging system for tracking and exploring ETL object execution,
performance, and troubleshooting. Integrates with:
- BigQuery factlog table (execution metrics)
- Google Cloud Logging (Cloud Functions, Dataflow, etc.)
- Firestore (optional real-time log storage)

Features:
- Real-time log collection from Cloud Logging
- Full-text search across logs
- Performance analysis and anomaly detection
- Error tracking and root cause analysis
- Audit trail and compliance logging
"""

import logging
import json
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum

from google.cloud import logging as cloud_logging
from google.cloud import bigquery

from backend.models import ExecutionLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LogStatus(str, Enum):
    """Log status enumeration."""
    SUCCESS = "success"
    FAILED = "failed"
    WARNING = "warning"
    PENDING = "pending"
    TIMEOUT = "timeout"
    ERROR = "error"


class LogSeverity(str, Enum):
    """Log severity levels matching Cloud Logging."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    ALERT = "ALERT"
    EMERGENCY = "EMERGENCY"


class LogFilter:
    """Builder for complex log filter queries."""

    def __init__(self):
        self.filters = []

    def by_object_id(self, object_id: str) -> "LogFilter":
        """Filter by object ID."""
        self.filters.append(f'object_id = "{object_id}"')
        return self

    def by_object_ids(self, object_ids: List[str]) -> "LogFilter":
        """Filter by multiple object IDs."""
        ids_str = '", "'.join(object_ids)
        self.filters.append(f'object_id IN ("{ids_str}")')
        return self

    def by_status(self, status: LogStatus) -> "LogFilter":
        """Filter by status."""
        self.filters.append(f'status = "{status.value}"')
        return self

    def by_date_range(self, start_date: str, end_date: str) -> "LogFilter":
        """Filter by date range (YYYY-MM-DD)."""
        self.filters.append(f'run_date BETWEEN "{start_date}" AND "{end_date}"')
        return self

    def by_duration_range(self, min_seconds: int, max_seconds: int) -> "LogFilter":
        """Filter by execution duration."""
        self.filters.append(f'duration_seconds BETWEEN {min_seconds} AND {max_seconds}')
        return self

    def with_errors(self) -> "LogFilter":
        """Filter only logs with errors."""
        self.filters.append('error_message IS NOT NULL')
        return self

    def with_text(self, search_text: str) -> "LogFilter":
        """Full-text search in error messages."""
        self.filters.append(f'error_message LIKE "%{search_text}%"')
        return self

    def with_high_bytes(self, min_bytes: int) -> "LogFilter":
        """Filter logs processing high volume of data."""
        self.filters.append(f'bytes_processed >= {min_bytes}')
        return self

    def with_high_rows(self, min_rows: int) -> "LogFilter":
        """Filter logs processing many rows."""
        self.filters.append(f'rows_processed >= {min_rows}')
        return self

    def build(self) -> str:
        """Build WHERE clause."""
        if not self.filters:
            return ""
        return "WHERE " + " AND ".join(self.filters)


class LogsExplorer:
    """Main logs explorer for querying and analyzing ETL object logs."""

    def __init__(
        self,
        project_id: str,
        dataset_id: str = "minietl",
        credentials=None
    ):
        """
        Initialize logs explorer.

        Args:
            project_id: GCP project ID
            dataset_id: BigQuery dataset with factlog table
            credentials: Optional credentials object
        """
        self.project_id = project_id
        self.dataset_id = dataset_id

        if credentials:
            self.bq_client = bigquery.Client(project=project_id, credentials=credentials)
            self.cloud_logging_client = cloud_logging.Client(
                project=project_id,
                credentials=credentials
            )
        else:
            self.bq_client = bigquery.Client(project=project_id)
            self.cloud_logging_client = cloud_logging.Client(project=project_id)

        self.dataset_ref = f"{project_id}.{dataset_id}"

    def fetch_logs_from_cloud_logging(
        self,
        object_name: str,
        days_back: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Fetch execution logs from Cloud Logging API for a specific object.

        Args:
            object_name: Name of the ETL object (Cloud Function, Dataflow job, etc.)
            days_back: Number of days to look back

        Returns:
            List of log records from Cloud Logging
        """
        logs = []
        try:
            # Build filter for Cloud Logging
            # Search for logs from multiple GCP services:
            # - Cloud Functions (resource.labels.function_name)
            # - Cloud Dataflow (resource.labels.job_name)
            # - Cloud Scheduler (logName contains cloudscheduler)
            # - Cloud Run (resource.labels.service_name)
            # - Workflows (logName contains workflows)
            from datetime import datetime, timedelta
            start_time = datetime.utcnow() - timedelta(days=days_back)

            # Build comprehensive filter for multiple resource types
            filter_str = (
                f'('
                f'resource.labels.function_name="{object_name}" OR '
                f'resource.labels.job_name="{object_name}" OR '
                f'resource.labels.service_name="{object_name}" OR '
                f'(logName=~"cloudscheduler.googleapis.com/executions" AND jsonPayload.jobName=~"jobs/{object_name}") OR '
                f'(logName=~"workflows.googleapis.com" AND resource.labels.workflow_id="{object_name}")'
                f') AND timestamp>="{start_time.isoformat()}Z"'
            )

            logger.debug(f"Querying Cloud Logging with filter: {filter_str}")

            # Query Cloud Logging
            entries = self.cloud_logging_client.list_entries(filter_=filter_str, page_size=100)

            for entry in entries:
                try:
                    # Extract payload (can be dict or string)
                    payload = entry.payload if isinstance(entry.payload, dict) else {}

                    # Determine status from HTTP response code or severity
                    status = 'success'
                    error_message = None

                    if entry.severity in ['WARNING', 'ERROR', 'CRITICAL']:
                        status = 'failed'
                        error_message = payload.get('debugInfo') or str(payload)
                    elif 'debugInfo' in payload:
                        # Check HTTP response code in debugInfo
                        debug_info = payload.get('debugInfo', '')
                        if '200' in debug_info or '201' in debug_info or '204' in debug_info:
                            status = 'success'
                        elif '4' in debug_info[:2] or '5' in debug_info[:2]:
                            status = 'failed'
                            error_message = debug_info

                    log_record = {
                        'run_date': entry.timestamp.date().isoformat() if entry.timestamp else None,
                        'created_at': entry.timestamp.isoformat() if entry.timestamp else None,
                        'status': status,
                        'error_message': error_message,
                        'duration_seconds': None,  # Cloud Logging doesn't track duration
                        'start_time': None,
                        'end_time': None,
                        # Additional metadata from Cloud Scheduler
                        'job_name': payload.get('jobName'),
                        'target_type': payload.get('targetType'),
                    }
                    logs.append(log_record)
                except Exception as e:
                    logger.debug(f"Error parsing log entry: {e}")
                    continue

            logger.info(f"Fetched {len(logs)} logs from Cloud Logging for {object_name}")

        except Exception as e:
            logger.warning(f"Failed to fetch logs from Cloud Logging for {object_name}: {e}")

        return logs

    def query_logs(self, filter_clause: str = "") -> List[Dict[str, Any]]:
        """
        Query execution logs from BigQuery.

        Args:
            filter_clause: WHERE clause for filtering

        Returns:
            List of log records
        """
        query = f"""
        SELECT
            log_id,
            object_id,
            run_date,
            start_time,
            end_time,
            duration_seconds,
            status,
            error_message,
            rows_processed,
            bytes_processed,
            created_at
        FROM `{self.dataset_ref}.factlog`
        {filter_clause}
        ORDER BY created_at DESC
        """

        try:
            results = []
            query_job = self.bq_client.query(query)

            for row in query_job:
                results.append({
                    'log_id': row['log_id'],
                    'object_id': row['object_id'],
                    'run_date': str(row['run_date']) if row['run_date'] else None,
                    'start_time': row['start_time'],
                    'end_time': row['end_time'],
                    'duration_seconds': row['duration_seconds'],
                    'status': row['status'],
                    'error_message': row['error_message'],
                    'rows_processed': row['rows_processed'],
                    'bytes_processed': row['bytes_processed'],
                    'created_at': str(row['created_at']) if row['created_at'] else None,
                })

            return results

        except Exception as e:
            logger.error(f"Failed to query logs: {e}")
            raise

    def get_object_logs(
        self,
        object_id: str,
        limit: int = 100,
        days_back: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get execution logs for a specific object.

        Args:
            object_id: ETL object ID
            limit: Maximum number of logs to return
            days_back: Number of days to look back

        Returns:
            List of execution logs
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        filter_builder = LogFilter()
        filter_builder.by_object_id(object_id).by_date_range(start_date, end_date)

        query = f"""
        SELECT
            log_id,
            object_id,
            run_date,
            start_time,
            end_time,
            duration_seconds,
            status,
            error_message,
            rows_processed,
            bytes_processed,
            created_at
        FROM `{self.dataset_ref}.factlog`
        {filter_builder.build()}
        ORDER BY created_at DESC
        LIMIT {limit}
        """

        return self.query_logs(filter_builder.build())

    def get_failed_logs(
        self,
        limit: int = 50,
        days_back: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Get recent failed execution logs.

        Args:
            limit: Maximum number of logs
            days_back: Days to look back

        Returns:
            List of failed logs
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        filter_builder = LogFilter()
        filter_builder.by_status(LogStatus.FAILED).by_date_range(start_date, end_date)

        query = f"""
        SELECT
            log_id,
            object_id,
            run_date,
            status,
            error_message,
            duration_seconds,
            created_at
        FROM `{self.dataset_ref}.factlog`
        {filter_builder.build()}
        ORDER BY created_at DESC
        LIMIT {limit}
        """

        return self.query_logs(filter_builder.build())

    def search_logs(self, search_text: str, days_back: int = 30) -> List[Dict[str, Any]]:
        """
        Full-text search across error messages.

        Args:
            search_text: Text to search for
            days_back: Days to look back

        Returns:
            List of matching logs
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        filter_builder = LogFilter()
        filter_builder.by_date_range(start_date, end_date).with_text(search_text)

        return self.query_logs(filter_builder.build())

    def get_performance_analysis(
        self,
        object_id: str,
        days_back: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze performance metrics for an object.

        Args:
            object_id: ETL object ID
            days_back: Days to analyze

        Returns:
            Performance analysis summary
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        query = f"""
        SELECT
            COUNT(*) as total_executions,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_runs,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs,
            SUM(CASE WHEN status = 'warning' THEN 1 ELSE 0 END) as warning_runs,
            AVG(duration_seconds) as avg_duration_seconds,
            MIN(duration_seconds) as min_duration_seconds,
            MAX(duration_seconds) as max_duration_seconds,
            AVG(bytes_processed) as avg_bytes_processed,
            AVG(rows_processed) as avg_rows_processed,
            SUM(bytes_processed) as total_bytes_processed,
            SUM(rows_processed) as total_rows_processed
        FROM `{self.dataset_ref}.factlog`
        WHERE object_id = "{object_id}"
        AND run_date BETWEEN "{start_date}" AND "{end_date}"
        """

        try:
            query_job = self.bq_client.query(query)
            row = next(query_job)

            success_rate = 0
            if row['total_executions'] > 0:
                success_rate = (row['successful_runs'] / row['total_executions']) * 100

            return {
                'object_id': object_id,
                'analysis_period': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'days': days_back
                },
                'execution_summary': {
                    'total_executions': int(row['total_executions']),
                    'successful_runs': int(row['successful_runs']),
                    'failed_runs': int(row['failed_runs']),
                    'warning_runs': int(row['warning_runs']),
                    'success_rate_percent': round(success_rate, 2)
                },
                'performance_metrics': {
                    'avg_duration_seconds': float(row['avg_duration_seconds'] or 0),
                    'min_duration_seconds': int(row['min_duration_seconds'] or 0),
                    'max_duration_seconds': int(row['max_duration_seconds'] or 0),
                    'avg_bytes_processed': int(row['avg_bytes_processed'] or 0),
                    'avg_rows_processed': int(row['avg_rows_processed'] or 0),
                    'total_bytes_processed': int(row['total_bytes_processed'] or 0),
                    'total_rows_processed': int(row['total_rows_processed'] or 0)
                },
                'analysis_timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Failed to analyze performance: {e}")
            raise

    def get_anomalies(
        self,
        object_id: str,
        threshold_percentile: int = 90,
        days_back: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Detect anomalous executions based on duration.

        Args:
            object_id: ETL object ID
            threshold_percentile: Percentile for anomaly detection
            days_back: Days to analyze

        Returns:
            List of anomalous log entries
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        # Get percentile duration
        percentile_query = f"""
        SELECT
            APPROX_QUANTILES(duration_seconds, 100)[OFFSET({threshold_percentile})] as threshold
        FROM `{self.dataset_ref}.factlog`
        WHERE object_id = "{object_id}"
        AND run_date BETWEEN "{start_date}" AND "{end_date}"
        """

        try:
            job = self.bq_client.query(percentile_query)
            threshold = next(job)['threshold']

            # Find anomalies
            anomaly_query = f"""
            SELECT
                log_id,
                object_id,
                run_date,
                start_time,
                duration_seconds,
                status,
                error_message,
                bytes_processed,
                rows_processed,
                ROUND((duration_seconds / {threshold} - 1) * 100, 2) as duration_anomaly_percent
            FROM `{self.dataset_ref}.factlog`
            WHERE object_id = "{object_id}"
            AND run_date BETWEEN "{start_date}" AND "{end_date}"
            AND duration_seconds > {threshold}
            ORDER BY duration_seconds DESC
            """

            results = []
            anomaly_job = self.bq_client.query(anomaly_query)

            for row in anomaly_job:
                results.append({
                    'log_id': row['log_id'],
                    'object_id': row['object_id'],
                    'run_date': str(row['run_date']),
                    'start_time': row['start_time'],
                    'duration_seconds': row['duration_seconds'],
                    'duration_anomaly_percent': float(row['duration_anomaly_percent']),
                    'status': row['status'],
                    'error_message': row['error_message'],
                    'bytes_processed': row['bytes_processed'],
                    'rows_processed': row['rows_processed'],
                })

            return results

        except Exception as e:
            logger.error(f"Failed to detect anomalies: {e}")
            raise

    def get_error_analysis(
        self,
        object_id: str,
        days_back: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze errors for an object.

        Args:
            object_id: ETL object ID
            days_back: Days to analyze

        Returns:
            Error analysis summary
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        query = f"""
        SELECT
            error_message,
            COUNT(*) as occurrence_count,
            MAX(created_at) as last_occurrence
        FROM `{self.dataset_ref}.factlog`
        WHERE object_id = "{object_id}"
        AND status = 'failed'
        AND run_date BETWEEN "{start_date}" AND "{end_date}"
        AND error_message IS NOT NULL
        GROUP BY error_message
        ORDER BY occurrence_count DESC
        """

        try:
            error_patterns = []
            query_job = self.bq_client.query(query)

            for row in query_job:
                error_patterns.append({
                    'error_message': row['error_message'],
                    'occurrence_count': int(row['occurrence_count']),
                    'last_occurrence': str(row['last_occurrence'])
                })

            # Get total failed logs
            total_query = f"""
            SELECT COUNT(*) as failed_count
            FROM `{self.dataset_ref}.factlog`
            WHERE object_id = "{object_id}"
            AND status = 'failed'
            AND run_date BETWEEN "{start_date}" AND "{end_date}"
            """

            total_job = self.bq_client.query(total_query)
            total_failed = next(total_job)['failed_count']

            return {
                'object_id': object_id,
                'analysis_period': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'days': days_back
                },
                'total_failed_executions': int(total_failed),
                'error_patterns': error_patterns,
                'top_errors': error_patterns[:5],
                'analysis_timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Failed to analyze errors: {e}")
            raise

    def get_trending(
        self,
        object_id: str,
        days_back: int = 30,
        group_by: str = "day"
    ) -> List[Dict[str, Any]]:
        """
        Get execution trends over time.

        Args:
            object_id: ETL object ID
            days_back: Days to analyze
            group_by: Group by 'day', 'week', or 'month'

        Returns:
            Trending data
        """
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        # Map group_by to SQL format
        group_format = {
            'day': 'run_date',
            'week': 'DATE_TRUNC(run_date, WEEK)',
            'month': 'DATE_TRUNC(run_date, MONTH)'
        }.get(group_by, 'run_date')

        query = f"""
        SELECT
            {group_format} as period,
            COUNT(*) as total_executions,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            AVG(duration_seconds) as avg_duration_seconds,
            SUM(bytes_processed) as bytes_processed,
            SUM(rows_processed) as rows_processed
        FROM `{self.dataset_ref}.factlog`
        WHERE object_id = "{object_id}"
        AND run_date BETWEEN "{start_date}" AND "{end_date}"
        GROUP BY period
        ORDER BY period DESC
        """

        try:
            results = []
            query_job = self.bq_client.query(query)

            for row in query_job:
                success_rate = 0
                if row['total_executions'] > 0:
                    success_rate = (row['successful'] / row['total_executions']) * 100

                results.append({
                    'period': str(row['period']),
                    'total_executions': int(row['total_executions']),
                    'successful': int(row['successful']),
                    'failed': int(row['failed']),
                    'success_rate_percent': round(success_rate, 2),
                    'avg_duration_seconds': float(row['avg_duration_seconds'] or 0),
                    'bytes_processed': int(row['bytes_processed'] or 0),
                    'rows_processed': int(row['rows_processed'] or 0)
                })

            return results

        except Exception as e:
            logger.error(f"Failed to get trending data: {e}")
            raise

    def export_logs(
        self,
        filter_clause: str,
        output_file: str,
        format: str = "json"
    ) -> None:
        """
        Export logs to file.

        Args:
            filter_clause: WHERE clause for filtering
            output_file: Output file path
            format: 'json' or 'csv'
        """
        logs = self.query_logs(filter_clause)

        if format == "json":
            with open(output_file, 'w') as f:
                json.dump(logs, f, indent=2, default=str)
        elif format == "csv":
            import csv
            if logs:
                with open(output_file, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=logs[0].keys())
                    writer.writeheader()
                    writer.writerows(logs)

        logger.info(f"✓ Exported {len(logs)} logs to {output_file}")

    def to_json(self) -> str:
        """Convert explorer info to JSON."""
        return json.dumps({
            'project_id': self.project_id,
            'dataset_id': self.dataset_id,
            'dataset_ref': self.dataset_ref
        }, indent=2)
