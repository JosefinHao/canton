#!/bin/bash
# Setup Cloud Scheduler for Canton Data Ingestion (Cloud Run)
#
# Creates a scheduler job that triggers the ingestion every 15 minutes

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-canton-data-ingestion}"
SCHEDULER_NAME="${SCHEDULER_NAME:-canton-data-ingestion-scheduler}"
SCHEDULE="${SCHEDULE:-*/15 * * * *}"  # Every 15 minutes
TIMEZONE="${TIMEZONE:-UTC}"

echo "======================================"
echo "Setting up Cloud Scheduler for Cloud Run"
echo "======================================"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Schedule: ${SCHEDULE} (${TIMEZONE})"
echo ""

# Enable Cloud Scheduler API if needed
echo "Checking Cloud Scheduler API..."
if ! gcloud services list --enabled --project ${PROJECT_ID} 2>/dev/null | grep -q cloudscheduler.googleapis.com; then
    echo "Enabling Cloud Scheduler API..."
    gcloud services enable cloudscheduler.googleapis.com --project ${PROJECT_ID} || {
        echo "Warning: Could not enable Cloud Scheduler API. You may need to enable it manually."
    }
fi

# Get the Cloud Run service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --platform managed \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --format='value(status.url)' 2>/dev/null)

if [ -z "${SERVICE_URL}" ]; then
    echo "Error: Could not get service URL. Make sure the Cloud Run service is deployed."
    echo "Run ./deploy.sh first."
    exit 1
fi

INGEST_URL="${SERVICE_URL}/ingest"
echo "Target URL: ${INGEST_URL}"
echo ""

# Delete existing scheduler job if it exists
echo "Checking for existing scheduler job..."
if gcloud scheduler jobs describe ${SCHEDULER_NAME} \
    --location ${REGION} \
    --project ${PROJECT_ID} >/dev/null 2>&1; then
    echo "Deleting existing scheduler job..."
    gcloud scheduler jobs delete ${SCHEDULER_NAME} \
        --location ${REGION} \
        --project ${PROJECT_ID} \
        --quiet
fi

# Create the scheduler job
echo "Creating Cloud Scheduler job..."
gcloud scheduler jobs create http ${SCHEDULER_NAME} \
    --location ${REGION} \
    --schedule "${SCHEDULE}" \
    --uri "${INGEST_URL}" \
    --http-method POST \
    --time-zone "${TIMEZONE}" \
    --project ${PROJECT_ID} \
    --description "Triggers Canton blockchain data ingestion every 15 minutes" \
    --headers "Content-Type=application/json" \
    --message-body '{"max_pages": 100, "auto_transform": true}'

echo ""
echo "======================================"
echo "Cloud Scheduler Setup Complete!"
echo "======================================"
echo ""
echo "Scheduler job: ${SCHEDULER_NAME}"
echo "Schedule: ${SCHEDULE} (${TIMEZONE})"
echo "Target: ${INGEST_URL}"
echo ""
echo "Commands:"
echo "  - View job:  gcloud scheduler jobs describe ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Run now:   gcloud scheduler jobs run ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Pause:     gcloud scheduler jobs pause ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Resume:    gcloud scheduler jobs resume ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Delete:    gcloud scheduler jobs delete ${SCHEDULER_NAME} --location ${REGION}"
echo ""
echo "Test manually:"
echo "  curl -X POST ${INGEST_URL}"
