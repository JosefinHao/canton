#!/bin/bash
# Setup Cloud Scheduler for Canton Data Ingestion
#
# This script creates a Cloud Scheduler job that triggers the data ingestion
# function every 15 minutes.

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="${FUNCTION_NAME:-canton-data-ingestion}"
SCHEDULER_NAME="${SCHEDULER_NAME:-canton-data-ingestion-scheduler}"
SCHEDULE="${SCHEDULE:-*/15 * * * *}"  # Every 15 minutes
TIMEZONE="${TIMEZONE:-UTC}"
SERVICE_ACCOUNT="${SCHEDULER_SERVICE_ACCOUNT:-}"  # Leave empty for default

echo "======================================"
echo "Setting up Cloud Scheduler"
echo "======================================"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Schedule: ${SCHEDULE}"
echo ""

# Get the function URL
FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --format='value(serviceConfig.uri)' 2>/dev/null)

if [ -z "${FUNCTION_URL}" ]; then
    echo "Error: Could not get function URL. Make sure the function is deployed."
    exit 1
fi

echo "Function URL: ${FUNCTION_URL}"
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

SCHEDULER_CMD="gcloud scheduler jobs create http ${SCHEDULER_NAME}"
SCHEDULER_CMD+=" --location ${REGION}"
SCHEDULER_CMD+=" --schedule '${SCHEDULE}'"
SCHEDULER_CMD+=" --uri ${FUNCTION_URL}"
SCHEDULER_CMD+=" --http-method POST"
SCHEDULER_CMD+=" --time-zone ${TIMEZONE}"
SCHEDULER_CMD+=" --project ${PROJECT_ID}"
SCHEDULER_CMD+=" --description 'Triggers Canton blockchain data ingestion every 15 minutes'"

# Add headers
SCHEDULER_CMD+=" --headers Content-Type=application/json"

# Add message body (optional configuration)
SCHEDULER_CMD+=" --message-body '{\"max_pages\": 100, \"auto_transform\": true}'"

# Add OIDC token for authenticated invocation (if service account specified)
if [ -n "${SERVICE_ACCOUNT}" ]; then
    SCHEDULER_CMD+=" --oidc-service-account-email ${SERVICE_ACCOUNT}"
    SCHEDULER_CMD+=" --oidc-token-audience ${FUNCTION_URL}"
fi

echo "Executing: ${SCHEDULER_CMD}"
echo ""

eval ${SCHEDULER_CMD}

echo ""
echo "======================================"
echo "Cloud Scheduler Setup Complete!"
echo "======================================"
echo ""
echo "Scheduler job: ${SCHEDULER_NAME}"
echo "Schedule: ${SCHEDULE} (${TIMEZONE})"
echo "Target: ${FUNCTION_URL}"
echo ""
echo "Commands:"
echo "  - View job: gcloud scheduler jobs describe ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Run now:  gcloud scheduler jobs run ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Pause:    gcloud scheduler jobs pause ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Resume:   gcloud scheduler jobs resume ${SCHEDULER_NAME} --location ${REGION}"
echo "  - Delete:   gcloud scheduler jobs delete ${SCHEDULER_NAME} --location ${REGION}"
echo ""
echo "To run the ingestion manually:"
echo "  curl -X POST ${FUNCTION_URL}"
