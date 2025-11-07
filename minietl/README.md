# miniETL Cloud Function Deployment

This package wraps the enhanced miniETL extraction workflow in a Google Cloud Function and schedules a daily run at 9:00 AM AEST (23:00 UTC on the previous day).

## Quick Start
- Ensure the `gcloud` CLI is authenticated (`gcloud auth login`) and configured with the correct project (`gcloud config set project YOUR_PROJECT`).
- Review and, if necessary, update environment variables at the top of `cloud_scheduler_trigger.sh`.
- Deploy and schedule the Cloud Function:
  ```bash
  cd minietl
  chmod +x cloud_scheduler_trigger.sh
  ./cloud_scheduler_trigger.sh
  ```
- The script deploys `main` from `main.py` as `minietl-extraction-function`, sets required environment variables, and creates a Cloud Scheduler job `minietl-daily-extraction`.

## Manual Triggers
Trigger the extraction on demand using `gcloud` (requires appropriate IAM permissions):
```bash
gcloud functions call minietl-extraction-function \
  --region=australia-southeast1 \
  --project=${PROJECT_ID} \
  --data='{"extraction_type": "all"}'
```

For direct HTTP invocation, obtain an identity token with the scheduler service account (replace values as needed):
```bash
FUNCTION_URL="https://australia-southeast1-${PROJECT_ID}.cloudfunctions.net/minietl-extraction-function"
gcloud auth print-identity-token --audiences="${FUNCTION_URL}" --impersonate-service-account="${SERVICE_ACCOUNT_EMAIL}" \
  | xargs -I{} curl -X GET "${FUNCTION_URL}?extraction_type=inventory" -H "Authorization: Bearer {}"
```

## Monitoring and Logs
- View recent executions: `gcloud functions logs read minietl-extraction-function --region=australia-southeast1 --project=${PROJECT_ID}`
- Cloud Scheduler status: `gcloud scheduler jobs describe minietl-daily-extraction --location=australia-southeast1 --project=${PROJECT_ID}`
- On-demand scheduler run: `gcloud scheduler jobs run minietl-daily-extraction --location=australia-southeast1 --project=${PROJECT_ID}`
- BigQuery metadata table `minietl_metadata` stores the extraction summary for inventory, logs, and billing extractions.

## Timezone Reference
- The scheduler cron expression is `0 23 * * *` in the UTC timezone.
- This corresponds to 23:00 UTC on the previous day, which equals 9:00 AM AEST (UTC+10) on the target day.
- Adjust the `SCHEDULE` or `TIME_ZONE` variables in `cloud_scheduler_trigger.sh` if you need to support daylight saving or alternate trigger times.
