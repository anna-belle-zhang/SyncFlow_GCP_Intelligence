"""
GCP Billing Data Extraction and ETL Cost Tracking

Extracts billing data from GCP billing export tables and maps costs
to ETL objects for comprehensive cost analysis.

Supports:
- GCP Billing Export (Cloud Billing to BigQuery)
- Resource-level cost tracking
- Service-level cost aggregation
- ETL object cost attribution
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date
import json

from google.cloud import bigquery

from backend.models import BillingRecord, ETLObject

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BillingExtractor:
    """Extracts billing data from GCP billing export tables."""

    # GCP Billing Export table schemas
    # Resource-level costs
    RESOURCE_BILLING_TABLE = "gcp_billing_export_resource_v1"
    # Total costs including shared services
    TOTAL_BILLING_TABLE = "gcp_billing_export_v1"

    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        billing_project_id: str,
        billing_dataset_id: str = "analytics",
        credentials=None
    ):
        """
        Initialize billing extractor.

        Args:
            project_id: ETL project ID (where minietl data is stored)
            dataset_id: BigQuery dataset for minietl
            billing_project_id: Project where billing data is exported
            billing_dataset_id: Dataset containing billing export tables
            credentials: Optional credentials object
        """
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.billing_project_id = billing_project_id
        self.billing_dataset_id = billing_dataset_id

        if credentials:
            self.client = bigquery.Client(project=project_id, credentials=credentials)
        else:
            self.client = bigquery.Client(project=project_id)

        self.minietl_ref = f"{project_id}.{dataset_id}"
        self.billing_ref = f"{billing_project_id}.{billing_dataset_id}"

    def extract_billing_by_resource(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract resource-level billing data from GCP billing export.

        Args:
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)

        Returns:
            List of billing records grouped by resource
        """
        logger.info("Extracting resource-level billing data...")

        # Build date filter
        date_filter = ""
        if start_date and end_date:
            date_filter = f"""
            WHERE DATE(usage_time) BETWEEN '{start_date}' AND '{end_date}'
            """

        query = f"""
        SELECT
            CAST(usage_start_time AS DATE) as usage_date,
            resource.name as resource_name,
            resource.service as service_name,
            resource.location as resource_location,
            service.description as service_description,
            sku.description as sku_description,
            SUM(usage.amount) as total_usage_amount,
            usage.unit as usage_unit,
            SUM(cost) as total_cost_usd,
            SUM(credits) as total_credits_usd,
            COUNT(*) as record_count
        FROM `{self.billing_ref}.{self.RESOURCE_BILLING_TABLE}*`
        {date_filter}
        GROUP BY
            usage_date,
            resource_name,
            service_name,
            resource_location,
            service_description,
            sku_description,
            usage_unit
        ORDER BY usage_date DESC, total_cost_usd DESC
        """

        try:
            results = []
            query_job = self.client.query(query)

            for row in query_job:
                results.append({
                    'usage_date': str(row['usage_date']),
                    'resource_name': row['resource_name'],
                    'service_name': row['service_name'],
                    'resource_location': row['resource_location'],
                    'service_description': row['service_description'],
                    'sku_description': row['sku_description'],
                    'total_usage_amount': float(row['total_usage_amount'] or 0),
                    'usage_unit': row['usage_unit'],
                    'total_cost_usd': float(row['total_cost_usd'] or 0),
                    'total_credits_usd': float(row['total_credits_usd'] or 0),
                    'record_count': int(row['record_count'])
                })

            logger.info(f"✓ Extracted {len(results)} resource-level billing records")
            return results

        except Exception as e:
            logger.error(f"Failed to extract resource billing data: {e}")
            raise

    def extract_billing_by_service(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract service-level billing data from GCP billing export.

        Args:
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)

        Returns:
            List of billing records grouped by service
        """
        logger.info("Extracting service-level billing data...")

        # Build date filter
        date_filter = ""
        if start_date and end_date:
            date_filter = f"""
            WHERE DATE(usage_start_time) BETWEEN '{start_date}' AND '{end_date}'
            """

        query = f"""
        SELECT
            CAST(usage_start_time AS DATE) as usage_date,
            service.id as service_id,
            service.description as service_description,
            SUM(usage.amount) as total_usage_amount,
            usage.unit as usage_unit,
            SUM(cost) as total_cost_usd,
            SUM(credits) as total_credits_usd,
            COUNT(*) as record_count
        FROM `{self.billing_ref}.{self.TOTAL_BILLING_TABLE}*`
        {date_filter}
        GROUP BY
            usage_date,
            service_id,
            service_description,
            usage_unit
        ORDER BY usage_date DESC, total_cost_usd DESC
        """

        try:
            results = []
            query_job = self.client.query(query)

            for row in query_job:
                results.append({
                    'usage_date': str(row['usage_date']),
                    'service_id': row['service_id'],
                    'service_description': row['service_description'],
                    'total_usage_amount': float(row['total_usage_amount'] or 0),
                    'usage_unit': row['usage_unit'],
                    'total_cost_usd': float(row['total_cost_usd'] or 0),
                    'total_credits_usd': float(row['total_credits_usd'] or 0),
                    'record_count': int(row['record_count'])
                })

            logger.info(f"✓ Extracted {len(results)} service-level billing records")
            return results

        except Exception as e:
            logger.error(f"Failed to extract service billing data: {e}")
            raise

    def map_costs_to_objects(
        self,
        objects: List[ETLObject],
        billing_records: List[Dict[str, Any]]
    ) -> List[BillingRecord]:
        """
        Map billing costs to ETL objects based on GCP resource names.

        Args:
            objects: List of ETL objects
            billing_records: List of billing records from GCP

        Returns:
            List of BillingRecord objects mapped to ETL objects
        """
        logger.info(f"Mapping {len(billing_records)} billing records to {len(objects)} objects...")

        billing_data = []
        mapped_count = 0

        # Create a lookup of object names and resource references
        object_lookup = {}
        for obj in objects:
            if obj.gcp_resource_name:
                object_lookup[obj.gcp_resource_name.lower()] = obj
            object_lookup[obj.name.lower()] = obj

        for record in billing_records:
            # Try to match resource name
            resource_key = record.get('resource_name', '').lower()

            matched_object = None
            if resource_key in object_lookup:
                matched_object = object_lookup[resource_key]
            else:
                # Try fuzzy matching on service name
                service = record.get('service_name', '').lower()
                for name, obj in object_lookup.items():
                    if service in name or name in service:
                        matched_object = obj
                        break

            if matched_object:
                # Create billing record
                billing_record = BillingRecord(
                    billing_id=f"BILL{len(billing_data)+1:05d}",
                    object_id=matched_object.object_id,
                    run_date=record['usage_date'],
                    service=record.get('service_description', record.get('service_name', 'Unknown')),
                    cost_usd=record['total_cost_usd'],
                    units=record.get('usage_unit', 'unknown'),
                    unit_quantity=record.get('total_usage_amount', 0),
                    created_at=datetime.utcnow().isoformat() + 'Z'
                )
                billing_data.append(billing_record)
                mapped_count += 1

        logger.info(f"✓ Mapped {mapped_count}/{len(billing_records)} billing records to objects")
        return billing_data

    def load_billing_records(
        self,
        bq_manager,
        billing_records: List[BillingRecord]
    ) -> None:
        """
        Load billing records into BigQuery factbilling table.

        Args:
            bq_manager: BigQueryManager instance
            billing_records: List of BillingRecord objects to load
        """
        if not billing_records:
            logger.warning("No billing records to load")
            return

        logger.info(f"Loading {len(billing_records)} billing records to BigQuery...")

        try:
            records_dict = [record.to_dict() for record in billing_records]
            bq_manager.insert_rows('factbilling', records_dict)
            logger.info(f"✓ Loaded {len(billing_records)} billing records")

        except Exception as e:
            logger.error(f"Failed to load billing records: {e}")
            raise

    def generate_cost_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive cost report.

        Args:
            start_date: Start date for report
            end_date: End date for report

        Returns:
            Cost report summary
        """
        logger.info("Generating cost report...")

        service_costs = self.extract_billing_by_service(start_date, end_date)

        total_cost = sum(record['total_cost_usd'] for record in service_costs)
        total_credits = sum(record['total_credits_usd'] for record in service_costs)

        return {
            'date_range': {
                'start_date': start_date or 'N/A',
                'end_date': end_date or 'N/A'
            },
            'total_cost_usd': total_cost,
            'total_credits_usd': total_credits,
            'net_cost_usd': total_cost + total_credits,
            'service_breakdown': service_costs,
            'generated_at': datetime.utcnow().isoformat() + 'Z'
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps({
            'extractor': 'BillingExtractor',
            'billing_project': self.billing_project_id,
            'billing_dataset': self.billing_dataset_id,
            'minietl_project': self.project_id,
            'minietl_dataset': self.dataset_id
        }, indent=2)
