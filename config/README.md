# Configuration Directory

This directory contains configuration files for SyncFlow GCP Intelligence.

## Credentials Setup

### ⚠️ Security Notice
**DO NOT commit real service account keys or API keys to Git!**

This directory is protected by `.gitignore` to prevent accidental credential leaks:
- `service-account.json` is ignored (your real credentials)
- `service-account.example.json` is tracked (template only)

### How to Setup Credentials

#### 1. Get Your Service Account JSON

**Option A: Using GCP Console**
1. Go to [GCP Console](https://console.cloud.google.com/)
2. Navigate to **IAM & Admin** → **Service Accounts**
3. Create a new service account or select existing one
4. Go to **Keys** tab
5. Click **Create Key** → **JSON**
6. Save the file

**Option B: Using gcloud CLI**
```bash
export GCP_PROJECT=your-project-id

gcloud iam service-accounts create syncflow-sa \
  --display-name="SyncFlow Service Account"

gcloud projects add-iam-policy-binding $GCP_PROJECT \
  --member="serviceAccount:syncflow-sa@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud iam service-accounts keys create service-account.json \
  --iam-account=syncflow-sa@$GCP_PROJECT.iam.gserviceaccount.com
```

#### 2. Place Your Credentials

**Local Development:**
```bash
# Copy your downloaded JSON to this directory
cp ~/Downloads/service-account.json ./service-account.json

# Secure the file
chmod 600 service-account.json
```

**Or use `~/.gcp/` (recommended):**
```bash
mkdir -p ~/.gcp
cp ~/Downloads/service-account.json ~/.gcp/service-account.json
chmod 600 ~/.gcp/service-account.json
```

#### 3. Configure Environment Variable

Update your `.env` file:
```bash
# Copy the example
cp ../.env.example ../.env

# Edit and set the path to your credentials
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

**Examples:**
```bash
# WSL/Linux
GOOGLE_APPLICATION_CREDENTIALS=/home/username/.gcp/service-account.json

# Windows (PowerShell)
GOOGLE_APPLICATION_CREDENTIALS=C:\Users\Username\.gcp\service-account.json

# macOS
GOOGLE_APPLICATION_CREDENTIALS=/Users/username/.gcp/service-account.json
```

#### 4. Verify Setup

```bash
# Test the credentials work
python -c "
from google.cloud import bigquery
from backend.app.core.config import AppSettings

settings = AppSettings.from_env()
print(f'✓ Project: {settings.gcp_project}')
print(f'✓ Dataset: {settings.bq_dataset}')

# Try connecting to BigQuery
client = bigquery.Client(project=settings.gcp_project)
print(f'✓ BigQuery connected')
"
```

## Files in This Directory

| File | Purpose | Git Status |
|------|---------|-----------|
| `service-account.example.json` | Template for your credentials | ✅ Tracked |
| `service-account.json` | Your actual GCP credentials | ❌ Ignored |
| `README.md` | This file | ✅ Tracked |

## Troubleshooting

### "Module not found" or credential errors
```bash
# Ensure you're in the project root
cd /path/to/SyncFlow_GCP_Intelligence

# Activate virtual environment
source .venv/bin/activate

# Set credentials
export GOOGLE_APPLICATION_CREDENTIALS=~/.gcp/service-account.json

# Test again
python -m backend.syncflow_server --help
```

### "Permission denied" errors
```bash
# Check file permissions (should be 600)
ls -la ~/.gcp/service-account.json

# Fix if needed
chmod 600 ~/.gcp/service-account.json
```

### "No such file or directory"
```bash
# Verify the path is correct and file exists
test -f ~/.gcp/service-account.json && echo "File exists" || echo "File not found"
```

## Cloud Run Deployment

For Cloud Run, credentials are handled differently:
1. The Cloud Run service automatically uses its assigned service account
2. No need to store JSON keys in the container
3. Grant the service account BigQuery permissions in GCP Console

See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) for details.
