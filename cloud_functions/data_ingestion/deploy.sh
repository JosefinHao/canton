#!/bin/bash
# Deployment script for Canton Data Ingestion Cloud Function
#
# Prerequisites:
# - gcloud CLI installed and authenticated
# - Appropriate permissions to deploy Cloud Functions
# - Service account with BigQuery admin and Cloud Functions invoker roles

set -e

# Configuration - modify these as needed
PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="${FUNCTION_NAME:-canton-data-ingestion}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-}" # Leave empty to use default
MEMORY="${MEMORY:-512MB}"
TIMEOUT="${TIMEOUT:-540s}"  # 9 minutes max for Cloud Functions
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"

# Environment variables for the function
SCAN_API_BASE_URL="${SCAN_API_BASE_URL:-https://scan.sv-1.global.canton.network.cumberland.io/api/scan/}"
BQ_PROJECT_ID="${BQ_PROJECT_ID:-governence-483517}"
BQ_RAW_DATASET="${BQ_RAW_DATASET:-raw}"
BQ_TRANSFORMED_DATASET="${BQ_TRANSFORMED_DATASET:-transformed}"
BQ_RAW_TABLE="${BQ_RAW_TABLE:-events}"
BQ_PARSED_TABLE="${BQ_PARSED_TABLE:-events_parsed}"
PAGE_SIZE="${PAGE_SIZE:-500}"
MAX_PAGES_PER_RUN="${MAX_PAGES_PER_RUN:-100}"
AUTO_TRANSFORM="${AUTO_TRANSFORM:-true}"

echo "======================================"
echo "Deploying Canton Data Ingestion Function"
echo "======================================"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Function: ${FUNCTION_NAME}"
echo ""

# Build environment variables string
ENV_VARS="SCAN_API_BASE_URL=${SCAN_API_BASE_URL}"
ENV_VARS+=",BQ_PROJECT_ID=${BQ_PROJECT_ID}"
ENV_VARS+=",BQ_RAW_DATASET=${BQ_RAW_DATASET}"
ENV_VARS+=",BQ_TRANSFORMED_DATASET=${BQ_TRANSFORMED_DATASET}"
ENV_VARS+=",BQ_RAW_TABLE=${BQ_RAW_TABLE}"
ENV_VARS+=",BQ_PARSED_TABLE=${BQ_PARSED_TABLE}"
ENV_VARS+=",PAGE_SIZE=${PAGE_SIZE}"
ENV_VARS+=",MAX_PAGES_PER_RUN=${MAX_PAGES_PER_RUN}"
ENV_VARS+=",AUTO_TRANSFORM=${AUTO_TRANSFORM}"

# Build the deployment command
DEPLOY_CMD="gcloud functions deploy ${FUNCTION_NAME}"
DEPLOY_CMD+=" --gen2"
DEPLOY_CMD+=" --runtime python311"
DEPLOY_CMD+=" --region ${REGION}"
DEPLOY_CMD+=" --source ."
DEPLOY_CMD+=" --entry-point ingest_data"
DEPLOY_CMD+=" --trigger-http"
DEPLOY_CMD+=" --memory ${MEMORY}"
DEPLOY_CMD+=" --timeout ${TIMEOUT}"
DEPLOY_CMD+=" --min-instances ${MIN_INSTANCES}"
DEPLOY_CMD+=" --max-instances ${MAX_INSTANCES}"
DEPLOY_CMD+=" --set-env-vars ${ENV_VARS}"
DEPLOY_CMD+=" --project ${PROJECT_ID}"

# Add service account if specified
if [ -n "${SERVICE_ACCOUNT}" ]; then
    DEPLOY_CMD+=" --service-account ${SERVICE_ACCOUNT}"
fi

# Allow unauthenticated invocations (for Cloud Scheduler)
# Remove this if you want to require authentication
DEPLOY_CMD+=" --allow-unauthenticated"

echo "Executing deployment..."
echo "${DEPLOY_CMD}"
echo ""

eval ${DEPLOY_CMD}

echo ""
echo "======================================"
echo "Deployment Complete!"
echo "======================================"

# Get the function URL
FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME} --region ${REGION} --project ${PROJECT_ID} --format='value(serviceConfig.uri)' 2>/dev/null || echo "URL not available")
echo "Function URL: ${FUNCTION_URL}"
echo ""

# Deploy status and transform endpoints
echo "Deploying status endpoint..."
gcloud functions deploy ${FUNCTION_NAME}-status \
    --gen2 \
    --runtime python311 \
    --region ${REGION} \
    --source . \
    --entry-point get_status \
    --trigger-http \
    --memory 256MB \
    --timeout 60s \
    --set-env-vars ${ENV_VARS} \
    --project ${PROJECT_ID} \
    --allow-unauthenticated

echo ""
echo "Deploying transform endpoint..."
gcloud functions deploy ${FUNCTION_NAME}-transform \
    --gen2 \
    --runtime python311 \
    --region ${REGION} \
    --source . \
    --entry-point transform_data \
    --trigger-http \
    --memory 512MB \
    --timeout ${TIMEOUT} \
    --set-env-vars ${ENV_VARS} \
    --project ${PROJECT_ID} \
    --allow-unauthenticated

echo ""
echo "======================================"
echo "All Functions Deployed!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Set up Cloud Scheduler to call the function every 15 minutes"
echo "   Run: ./setup_scheduler.sh"
echo ""
echo "2. Test the function manually:"
echo "   curl ${FUNCTION_URL}"
echo ""
echo "3. Check status:"
echo "   curl ${FUNCTION_URL/ingest/status}"
