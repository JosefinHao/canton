#!/bin/bash
# Setup BigQuery Scheduled Queries for the Canton data pipeline
#
# Creates two scheduled queries in sequence:
#   1. Canton: ingest_events_from_gcs  - Daily at 00:00 UTC: GCS → raw.events
#   2. Canton: transform_raw_events    - Daily at 01:00 UTC: raw.events → transformed.events_parsed
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - BigQuery Data Transfer API enabled:
#       gcloud services enable bigquerydatatransfer.googleapis.com --project ${PROJECT_ID}
#   - External table raw.events_updates_external exists pointing at:
#       gs://canton-bucket/raw/updates/events/*
#   - Service account with roles/bigquery.dataEditor on both datasets
#
# Usage:
#   bash bigquery_scheduled/setup_scheduled_query.sh
#
#   # Override defaults:
#   GCP_PROJECT_ID=my-project LOCATION=US bash bigquery_scheduled/setup_scheduled_query.sh

set -e

PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
LOCATION="${LOCATION:-US}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "======================================"
echo "Setting up BigQuery Scheduled Queries"
echo "======================================"
echo "Project:  ${PROJECT_ID}"
echo "Location: ${LOCATION}"
echo ""

# ---- Helper: create a scheduled query via bq CLI ----
create_scheduled_query() {
    local display_name="$1"
    local schedule="$2"
    local sql_file="$3"

    if [ ! -f "${sql_file}" ]; then
        echo "ERROR: SQL file not found: ${sql_file}"
        return 1
    fi

    echo "Creating scheduled query: ${display_name}"
    echo "  Schedule: ${schedule}"
    echo "  SQL file: ${sql_file}"

    local query
    query=$(cat "${sql_file}")

    bq query \
        --use_legacy_sql=false \
        --project_id="${PROJECT_ID}" \
        --location="${LOCATION}" \
        --schedule="${schedule}" \
        --display_name="${display_name}" \
        --replace \
        "${query}"
    return $?
}

# ---------------------------------------------------------------
# Query 1: Ingest new events from GCS into raw.events
# ---------------------------------------------------------------
echo ""
echo "--- Query 1: ingest_events_from_gcs ---"
echo "Description: Reads new parquet files from GCS external table and"
echo "             inserts into raw.events (dedup on event_id + event_date)."

INGEST_FAILED=0
create_scheduled_query \
    "Canton: ingest_events_from_gcs" \
    "every 24 hours" \
    "${SCRIPT_DIR}/ingest_events_from_gcs.sql" \
    || INGEST_FAILED=$?

# ---------------------------------------------------------------
# Query 2: Transform raw events to parsed format
# ---------------------------------------------------------------
echo ""
echo "--- Query 2: transform_raw_events ---"
echo "Description: Transforms raw.events -> transformed.events_parsed"
echo "             (parses timestamps, flattens arrays, parses JSON)."

TRANSFORM_FAILED=0
create_scheduled_query \
    "Canton: transform_raw_events" \
    "every 24 hours" \
    "${SCRIPT_DIR}/transform_events.sql" \
    || TRANSFORM_FAILED=$?

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "======================================"
echo "Setup Summary"
echo "======================================"

if [ "${INGEST_FAILED}" -eq 0 ] && [ "${TRANSFORM_FAILED}" -eq 0 ]; then
    echo "[OK] Both scheduled queries created successfully."
    echo ""
    echo "IMPORTANT - Adjust start times in BigQuery Console:"
    echo "  The bq CLI schedules queries starting at creation time."
    echo "  Manually set the scheduled start times to:"
    echo "    Canton: ingest_events_from_gcs  -> 00:00 UTC daily"
    echo "    Canton: transform_raw_events    -> 01:00 UTC daily"
    echo "  (The 1-hour offset ensures ingest completes before transform runs.)"
else
    echo "[WARN] One or more queries may not have been created. See manual"
    echo "       instructions below."
fi

echo ""
echo "View and manage scheduled queries:"
echo "  https://console.cloud.google.com/bigquery/scheduled-queries?project=${PROJECT_ID}"
echo ""
echo "======================================"
echo "Manual Setup Instructions (if CLI failed)"
echo "======================================"
echo ""
echo "Prerequisite: Enable BigQuery Data Transfer API"
echo "  gcloud services enable bigquerydatatransfer.googleapis.com --project ${PROJECT_ID}"
echo ""
echo "Query 1 -- ingest_events_from_gcs:"
echo "  1. Open: https://console.cloud.google.com/bigquery?project=${PROJECT_ID}"
echo "  2. Click 'Scheduled queries' -> 'Create scheduled query'"
echo "  3. Paste contents of: ${SCRIPT_DIR}/ingest_events_from_gcs.sql"
echo "  4. Display name:  'Canton: ingest_events_from_gcs'"
echo "  5. Schedule type: Custom (cron): 0 0 * * *"
echo "  6. Time zone: UTC, Location: ${LOCATION}"
echo "  7. Click 'Schedule'"
echo ""
echo "Query 2 -- transform_raw_events:"
echo "  1. Click 'Create scheduled query' again"
echo "  2. Paste contents of: ${SCRIPT_DIR}/transform_events.sql"
echo "  3. Display name:  'Canton: transform_raw_events'"
echo "  4. Schedule type: Custom (cron): 0 1 * * *"
echo "  5. Time zone: UTC, Location: ${LOCATION}"
echo "  6. Click 'Schedule'"
echo ""
echo "Verify external table exists:"
echo "  bq show ${PROJECT_ID}:raw.events_updates_external"
