#!/usr/bin/env bash
#
# Deploy the miniETL Cloud Function and configure a Cloud Scheduler trigger.
#
# Environment variables (optional):
#   PROJECT_ID                Target GCP project (defaults to gcloud config value)
#   REGION                    Cloud Functions region (default: australia-southeast1)
#   FUNCTION_NAME             Cloud Function name (default: minietl-extraction-function)
#   JOB_NAME                  Cloud Scheduler job name (default: minietl-daily-extraction)
#   SERVICE_ACCOUNT_EMAIL     Service account for the scheduler OIDC token
#   DATASET_ID                BigQuery dataset for miniETL metadata (default: minietl)
#   SCHEDULE                  Cron schedule (default: "0 23 * * *" -> 9 AM AEST / 11 PM UTC previous day)
#   TIME_ZONE                 Scheduler timezone (default: UTC)
#
# Usage:
#   chmod +x cloud_scheduler_trigger.sh
#   ./cloud_scheduler_trigger.sh

set -euo pipefail

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required but was not found in PATH." >&2
  exit 1
fi

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "Set PROJECT_ID environment variable or configure a default project with 'gcloud config set project PROJECT_ID'." >&2
  exit 1
fi

REGION="${REGION:-australia-southeast1}"
FUNCTION_NAME="${FUNCTION_NAME:-minietl-extraction-function}"
JOB_NAME="${JOB_NAME:-minietl-daily-extraction}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-minietl-scheduler@${PROJECT_ID}.iam.gserviceaccount.com}"
DATASET_ID="${DATASET_ID:-minietl}"
SCHEDULE="${SCHEDULE:-0 23 * * *}"
TIME_ZONE="${TIME_ZONE:-UTC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Deploying Cloud Function '${FUNCTION_NAME}' to project '${PROJECT_ID}' (${REGION})..."
gcloud functions deploy "${FUNCTION_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --runtime=python311 \
  --source="${SCRIPT_DIR}" \
  --entry-point=main \
  --trigger-http \
  --memory=1024MB \
  --timeout=540s \
  --set-env-vars="MINIETL_PROJECT_ID=${PROJECT_ID},MINIETL_DATASET_ID=${DATASET_ID}" \
  --service-account="${SERVICE_ACCOUNT_EMAIL}"

FUNCTION_URL="$(gcloud functions describe "${FUNCTION_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(httpsTrigger.url)')"

if [[ -z "${FUNCTION_URL}" ]]; then
  echo "Failed to resolve function URL. Aborting scheduler configuration." >&2
  exit 1
fi

echo "Function deployed at ${FUNCTION_URL}"
echo "Creating Cloud Scheduler job '${JOB_NAME}' (${SCHEDULE} ${TIME_ZONE})..."

gcloud scheduler jobs delete "${JOB_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --quiet >/dev/null 2>&1 || true

gcloud scheduler jobs create http "${JOB_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="${SCHEDULE}" \
  --time-zone="${TIME_ZONE}" \
  --uri="${FUNCTION_URL}" \
  --http-method=GET \
  --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
  --oidc-token-audience="${FUNCTION_URL}"

echo "Deployment complete."
echo
echo "Verification commands:"
echo "  gcloud functions describe ${FUNCTION_NAME} --region=${REGION} --project=${PROJECT_ID}"
echo "  gcloud scheduler jobs describe ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo "  gcloud scheduler jobs run ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
