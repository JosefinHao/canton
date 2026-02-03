#!/bin/bash
# Setup BigQuery Scheduled Query for transformation
#
# This creates a scheduled query that runs every 15 minutes to transform
# new raw events into the parsed format.

PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
LOCATION="${LOCATION:-us}"
DISPLAY_NAME="${DISPLAY_NAME:-Canton Events Transformation}"
SCHEDULE="${SCHEDULE:-every 15 minutes}"

echo "======================================"
echo "Setting up BigQuery Scheduled Query"
echo "======================================"
echo "Project: ${PROJECT_ID}"
echo "Location: ${LOCATION}"
echo "Schedule: ${SCHEDULE}"
echo ""

# Read the SQL file
SQL_FILE="$(dirname "$0")/transform_events.sql"
if [ ! -f "${SQL_FILE}" ]; then
    echo "Error: SQL file not found: ${SQL_FILE}"
    exit 1
fi

QUERY=$(cat "${SQL_FILE}")

# Create the scheduled query using bq command
echo "Creating scheduled query..."

bq query \
    --use_legacy_sql=false \
    --project_id=${PROJECT_ID} \
    --schedule="${SCHEDULE}" \
    --display_name="${DISPLAY_NAME}" \
    --location=${LOCATION} \
    "${QUERY}"

if [ $? -eq 0 ]; then
    echo ""
    echo "======================================"
    echo "Scheduled Query Created!"
    echo "======================================"
    echo ""
    echo "The transformation will run ${SCHEDULE}"
    echo ""
    echo "View scheduled queries:"
    echo "  https://console.cloud.google.com/bigquery/scheduled-queries?project=${PROJECT_ID}"
else
    echo ""
    echo "======================================"
    echo "Alternative: Create via Console"
    echo "======================================"
    echo ""
    echo "If the command failed, create the scheduled query manually:"
    echo ""
    echo "1. Go to: https://console.cloud.google.com/bigquery?project=${PROJECT_ID}"
    echo "2. Click 'Scheduled queries' in the left menu"
    echo "3. Click 'Create scheduled query'"
    echo "4. Paste the contents of: ${SQL_FILE}"
    echo "5. Set schedule to: ${SCHEDULE}"
    echo "6. Set destination dataset (optional - query has INSERT)"
    echo "7. Click 'Schedule'"
fi
