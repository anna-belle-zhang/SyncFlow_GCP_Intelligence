"""
Enhanced GCP inventory collection with standardized object types.

Collects and normalizes GCP ETL objects into standardized format:
- Cloud Scheduler triggers
- Cloud Functions
- Pub/Sub topics and subscriptions
- BigQuery datasets and tables
- Dataflow jobs
- Cloud Workflows
- Cloud Run services
"""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from google.protobuf.json_format import MessageToDict

# GCP libs
from google.cloud import asset_v1
from google.cloud import pubsub_v1
from google.cloud import bigquery
from google.cloud import functions_v2
from google.cloud import scheduler_v1
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.models import ETLObject, ObjectType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InventoryCollector:
    """Collects GCP ETL objects from various services."""

    def __init__(self, project_id: str, credentials):
        """
        Initialize inventory collector.

        Args:
            project_id: GCP project ID
            credentials: Credentials object
        """
        self.project_id = project_id
        self.credentials = credentials
        self.objects: List[ETLObject] = []

    def collect_cloud_scheduler(self) -> List[ETLObject]:
        """Collect Cloud Scheduler jobs as TRIGGER objects."""
        logger.info("Collecting Cloud Scheduler triggers...")
        try:
            client = scheduler_v1.CloudSchedulerClient(credentials=self.credentials)
            parent = f"projects/{self.project_id}/locations/us-central1"

            for job in client.list_jobs(request={"parent": parent}):
                obj = ETLObject(
                    object_id=None,  # Will be assigned later
                    object_type=ObjectType.TRIGGER,
                    name=job.name.split("/")[-1],
                    gcp_resource_name=job.name,
                    description=job.description or "",
                    metadata={
                        "schedule": job.schedule,
                        "state": job.state.name if job.state else None,
                        "timezone": job.time_zone,
                        "http_target": {
                            "uri": job.http_target.uri if job.http_target else None,
                            "http_method": job.http_target.http_method if job.http_target else None,
                        },
                    },
                )
                self.objects.append(obj)
                logger.debug(f"  Added trigger: {obj.name}")

        except Exception as e:
            logger.warning(f"Cloud Scheduler collection error: {e}")

        return self.objects

    def collect_cloud_functions(self) -> List[ETLObject]:
        """Collect Cloud Functions as FUNCTION objects."""
        logger.info("Collecting Cloud Functions...")
        try:
            client = functions_v2.FunctionServiceClient(credentials=self.credentials)
            parent = f"projects/{self.project_id}/locations/-"

            for func in client.list_functions(request={"parent": parent}):
                # Extract info from service_config (v2 API structure)
                service_config = func.service_config or {}
                entry_point = getattr(service_config, "entry_point", None)
                memory = getattr(service_config, "available_memory", None)
                timeout = getattr(service_config, "timeout_seconds", None)

                # State and environment are numeric enums, map to names
                state_name = functions_v2.Function.State(func.state).name if func.state else "UNKNOWN"
                env_name = functions_v2.Environment(func.environment).name if func.environment else "UNKNOWN"

                obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.FUNCTION,
                    name=func.name.split("/")[-1],
                    gcp_resource_name=func.name,
                    description=func.description or "",
                    metadata={
                        "memory": memory,
                        "timeout_seconds": timeout,
                        "entry_point": entry_point,
                        "state": state_name,
                        "environment": env_name,
                        "uri": getattr(service_config, "uri", None),
                        "service_account": getattr(service_config, "service_account_email", None),
                    },
                )
                self.objects.append(obj)
                logger.debug(f"  Added function: {obj.name}")

        except Exception as e:
            logger.warning(f"Cloud Functions collection error: {e}", exc_info=True)

        return self.objects

    def collect_pubsub(self) -> List[ETLObject]:
        """Collect Pub/Sub topics and subscriptions."""
        logger.info("Collecting Pub/Sub topics and subscriptions...")
        try:
            publisher = pubsub_v1.PublisherClient(credentials=self.credentials)
            subscriber = pubsub_v1.SubscriberClient(credentials=self.credentials)
            project = f"projects/{self.project_id}"

            # Topics
            for topic in publisher.list_topics(request={"project": project}):
                obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.PUBSUB,
                    name=topic.name.split("/")[-1],
                    gcp_resource_name=topic.name,
                    metadata={"resource_type": "topic"},
                )
                self.objects.append(obj)
                logger.debug(f"  Added topic: {obj.name}")

            # Subscriptions
            for subscription in subscriber.list_subscriptions(request={"project": project}):
                obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.PUBSUB,
                    name=subscription.name.split("/")[-1],
                    gcp_resource_name=subscription.name,
                    metadata={"resource_type": "subscription"},
                )
                self.objects.append(obj)
                logger.debug(f"  Added subscription: {obj.name}")

        except Exception as e:
            logger.warning(f"Pub/Sub collection error: {e}")

        return self.objects

    def collect_bigquery(self) -> List[ETLObject]:
        """Collect BigQuery datasets and tables."""
        logger.info("Collecting BigQuery datasets and tables...")
        try:
            bq_client = bigquery.Client(project=self.project_id, credentials=self.credentials)

            for dataset in bq_client.list_datasets():
                # Add dataset
                dataset_obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.BQDATASET,
                    name=dataset.dataset_id,
                    gcp_resource_name=f"{self.project_id}.{dataset.dataset_id}",
                    metadata={
                        "location": dataset.location,
                        "created": dataset.created.isoformat() if dataset.created else None,
                    },
                )
                self.objects.append(dataset_obj)
                logger.debug(f"  Added dataset: {dataset_obj.name}")

                # Add tables
                try:
                    for table in bq_client.list_tables(dataset.dataset_id):
                        table_obj = ETLObject(
                            object_id=None,
                            object_type=ObjectType.BQTABLE,
                            name=f"{dataset.dataset_id}.{table.table_id}",
                            gcp_resource_name=f"{self.project_id}.{dataset.dataset_id}.{table.table_id}",
                            parent_id=None,  # Will be linked to dataset during assignment
                            metadata={
                                "dataset": dataset.dataset_id,
                                "table_id": table.table_id,
                                "created": table.created.isoformat() if table.created else None,
                                "type": table.table_type,
                            },
                        )
                        self.objects.append(table_obj)
                        logger.debug(f"  Added table: {table_obj.name}")
                except Exception as e:
                    logger.warning(f"Error listing tables in {dataset.dataset_id}: {e}")

        except Exception as e:
            logger.warning(f"BigQuery collection error: {e}")

        return self.objects

    def collect_dataflow(self) -> List[ETLObject]:
        """Collect Dataflow jobs."""
        logger.info("Collecting Dataflow jobs...")
        try:
            service = build("dataflow", "v1b3", credentials=self.credentials, cache_discovery=False)
            response = service.projects().jobs().list(projectId=self.project_id, view="JOB_VIEW_ALL").execute()

            for job in response.get("jobs", []):
                obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.DATAFLOW,
                    name=job.get("name", "unknown"),
                    gcp_resource_name=f"projects/{self.project_id}/jobs/{job.get('id')}",
                    description=job.get("description", ""),
                    metadata={
                        "job_id": job.get("id"),
                        "state": job.get("currentState"),
                        "type": job.get("type"),
                        "create_time": job.get("createTime"),
                    },
                )
                self.objects.append(obj)
                logger.debug(f"  Added dataflow: {obj.name}")

        except HttpError as e:
            logger.warning(f"Dataflow API HTTP error: {e}")
        except Exception as e:
            logger.warning(f"Dataflow collection error: {e}")

        return self.objects

    def collect_workflows(self) -> List[ETLObject]:
        """Collect Cloud Workflows."""
        logger.info("Collecting Cloud Workflows...")
        try:
            service = build("workflows", "v1", credentials=self.credentials, cache_discovery=False)
            parent = f"projects/{self.project_id}/locations/us-central1"

            response = service.projects().locations().workflows().list(parent=parent).execute()

            for workflow in response.get("workflows", []):
                obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.WORKFLOW,
                    name=workflow.get("displayName", workflow.get("name", "unknown")),
                    gcp_resource_name=workflow.get("name"),
                    description=workflow.get("description", ""),
                    metadata={
                        "state": workflow.get("state"),
                        "create_time": workflow.get("createTime"),
                        "update_time": workflow.get("updateTime"),
                    },
                )
                self.objects.append(obj)
                logger.debug(f"  Added workflow: {obj.name}")

        except HttpError as e:
            logger.warning(f"Workflows API HTTP error: {e}")
        except Exception as e:
            logger.warning(f"Workflows collection error: {e}")

        return self.objects

    def collect_cloud_run(self) -> List[ETLObject]:
        """Collect Cloud Run services as CLOUD_RUN objects."""
        logger.info("Collecting Cloud Run services...")
        try:
            client = build("run", "v1", credentials=self.credentials)
            parent = f"projects/{self.project_id}/locations/us-central1"

            request = client.projects().locations().services().list(parent=parent)
            response = request.execute()

            for service in response.get("items", []):
                # Extract service metadata and status
                service_metadata = service.get("metadata", {})
                status = service.get("status", {})
                conditions = status.get("conditions", [])
                ready_condition = conditions[0] if conditions else {}

                obj = ETLObject(
                    object_id=None,
                    object_type=ObjectType.CLOUD_RUN,
                    name=service_metadata.get("name", "unknown"),
                    gcp_resource_name=service_metadata.get("name"),
                    description=service_metadata.get("annotations", {}).get("description", ""),
                    metadata={
                        "status_ready": ready_condition.get("status") == "True",
                        "status": ready_condition.get("type"),
                        "url": status.get("url"),
                        "latest_revision": status.get("latestReadyRevisionName"),
                        "region": parent.split("/")[-1],
                        "created_by": service_metadata.get("annotations", {}).get("managed-by"),
                    },
                )
                self.objects.append(obj)
                logger.debug(f"  Added Cloud Run service: {obj.name}")

        except HttpError as e:
            logger.warning(f"Cloud Run API HTTP error: {e}")
        except Exception as e:
            logger.warning(f"Cloud Run collection error: {e}")

        return self.objects

    def collect_all(self) -> List[ETLObject]:
        """
        Collect all GCP ETL objects.

        Returns:
            List of ETLObject instances
        """
        logger.info(f"Starting inventory collection for project {self.project_id}")

        self.collect_cloud_scheduler()
        self.collect_cloud_functions()
        self.collect_pubsub()
        self.collect_bigquery()
        self.collect_dataflow()
        self.collect_workflows()
        self.collect_cloud_run()

        logger.info(f"✓ Collected {len(self.objects)} objects")
        return self.objects

    def to_json(self) -> str:
        """Export objects as JSON."""
        data = {
            "project": self.project_id,
            "collected_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "total_objects": len(self.objects),
            "objects": [
                {
                    "object_type": obj.object_type.value,
                    "name": obj.name,
                    "gcp_resource_name": obj.gcp_resource_name,
                    "description": obj.description,
                    "metadata": obj.metadata,
                }
                for obj in self.objects
            ],
        }
        return json.dumps(data, indent=2, default=str)


def collect_inventory(
    project_id: str,
    sa_path: Optional[str] = None,
    credentials=None,
) -> List[ETLObject]:
    """
    Collect inventory from GCP project.

    Args:
        project_id: GCP project ID
        sa_path: Path to service account JSON
        credentials: Optional pre-loaded credentials

    Returns:
        List of ETLObject instances
    """
    if credentials is None:
        if not sa_path:
            raise ValueError(
                "Either a service account path or explicit credentials must be provided."
            )
        credentials = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

    collector = InventoryCollector(project_id, credentials)
    return collector.collect_all()
