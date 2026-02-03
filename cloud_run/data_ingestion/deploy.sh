#!/bin/bash
# Deployment script for Canton Data Ingestion - Cloud Run
#
# This script builds and deploys the container to Cloud Run

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-canton-data-ingestion}"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
MEMORY="${MEMORY:-512Mi}"
CPU="${CPU:-1}"
TIMEOUT="${TIMEOUT:-540}"  # 9 minutes
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"

# Environment variables
SCAN_API_BASE_URL="${SCAN_API_BASE_URL:-https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/}"
BQ_PROJECT_ID="${BQ_PROJECT_ID:-governence-483517}"
BQ_RAW_DATASET="${BQ_RAW_DATASET:-raw}"
BQ_TRANSFORMED_DATASET="${BQ_TRANSFORMED_DATASET:-transformed}"
BQ_RAW_TABLE="${BQ_RAW_TABLE:-events}"
BQ_PARSED_TABLE="${BQ_PARSED_TABLE:-events_parsed}"
PAGE_SIZE="${PAGE_SIZE:-500}"
MAX_PAGES_PER_RUN="${MAX_PAGES_PER_RUN:-100}"
AUTO_TRANSFORM="${AUTO_TRANSFORM:-true}"

echo "======================================"
echo "Deploying Canton Data Ingestion to Cloud Run"
echo "======================================"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo "Image: ${IMAGE_NAME}"
echo ""

# Check if required APIs are enabled
echo "Checking required APIs..."
for api in run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com; do
    if ! gcloud services list --enabled --project ${PROJECT_ID} 2>/dev/null | grep -q ${api}; then
        echo "Enabling ${api}..."
        gcloud services enable ${api} --project ${PROJECT_ID} || {
            echo "Warning: Could not enable ${api}. You may need to enable it manually."
        }
    fi
done

# Build the container using Cloud Build
echo ""
echo "Building container image..."
gcloud builds submit \
    --tag ${IMAGE_NAME} \
    --project ${PROJECT_ID} \
    --timeout=600s \
    .

# Deploy to Cloud Run
echo ""
echo "Deploying to Cloud Run..."

ENV_VARS="SCAN_API_BASE_URL=${SCAN_API_BASE_URL}"
ENV_VARS+=",BQ_PROJECT_ID=${BQ_PROJECT_ID}"
ENV_VARS+=",BQ_RAW_DATASET=${BQ_RAW_DATASET}"
ENV_VARS+=",BQ_TRANSFORMED_DATASET=${BQ_TRANSFORMED_DATASET}"
ENV_VARS+=",BQ_RAW_TABLE=${BQ_RAW_TABLE}"
ENV_VARS+=",BQ_PARSED_TABLE=${BQ_PARSED_TABLE}"
ENV_VARS+=",PAGE_SIZE=${PAGE_SIZE}"
ENV_VARS+=",MAX_PAGES_PER_RUN=${MAX_PAGES_PER_RUN}"
ENV_VARS+=",AUTO_TRANSFORM=${AUTO_TRANSFORM}"

gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --platform managed \
    --region ${REGION} \
    --memory ${MEMORY} \
    --cpu ${CPU} \
    --timeout ${TIMEOUT} \
    --min-instances ${MIN_INSTANCES} \
    --max-instances ${MAX_INSTANCES} \
    --set-env-vars "${ENV_VARS}" \
    --allow-unauthenticated \
    --project ${PROJECT_ID}

# Get the service URL
echo ""
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --platform managed \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --format='value(status.url)')

echo "======================================"
echo "Deployment Complete!"
echo "======================================"
echo ""
echo "Service URL: ${SERVICE_URL}"
echo ""
echo "Endpoints:"
echo "  - Health:    ${SERVICE_URL}/"
echo "  - Ingest:    ${SERVICE_URL}/ingest"
echo "  - Transform: ${SERVICE_URL}/transform"
echo "  - Status:    ${SERVICE_URL}/status"
echo ""
echo "Next steps:"
echo "1. Test the service:"
echo "   curl ${SERVICE_URL}/status"
echo ""
echo "2. Set up Cloud Scheduler:"
echo "   ./setup_scheduler.sh"
