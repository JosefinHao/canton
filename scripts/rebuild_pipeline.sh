#!/bin/bash
# =============================================================================
# rebuild_pipeline.sh — Full pipeline rebuild from scratch
#
# Deletes existing BigQuery data tables, verifies GCS data integrity,
# ingests all historical data from BOTH GCS sources, transforms it,
# then sets up the daily scheduled queries for ongoing ingestion.
#
# Data sources:
#   - raw.events_external         → gs://BUCKET/raw/backfill/events/*
#     (historical backfill: 2024 – ~March 3, 2026)
#   - raw.events_updates_external → gs://BUCKET/raw/updates/events/*
#     (ongoing updates: ~March 3, 2026 onward)
#
# Steps:
#   1. Delete raw.events and transformed.events_parsed tables
#   2. Re-create the tables (empty, with correct schema/partitioning)
#   3. Ensure both external tables exist
#   4. Verify GCS parquet folder structure matches effective_at dates
#   5. Ingest ALL historical data from both GCS sources into raw.events
#   6. Transform ALL historical data into transformed.events_parsed
#   7. Set up daily scheduled queries for new incoming data
#
# Usage:
#   bash scripts/rebuild_pipeline.sh --bucket BUCKET_NAME
#
#   # Dry-run (shows commands without executing destructive operations):
#   bash scripts/rebuild_pipeline.sh --bucket BUCKET_NAME --dry-run
#
#   # Skip verification (if you already ran it separately):
#   bash scripts/rebuild_pipeline.sh --bucket BUCKET_NAME --skip-verify
#
#   # Override defaults:
#   GCP_PROJECT_ID=my-project bash scripts/rebuild_pipeline.sh --bucket my-bucket
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ID="${GCP_PROJECT_ID:-governence-483517}"
LOCATION="${LOCATION:-US}"
BUCKET=""
MIGRATIONS="${MIGRATIONS:-0 1 2 3 4}"
VERIFY_START_MONTH="${VERIFY_START_MONTH:-6}"
VERIFY_START_DAY="${VERIFY_START_DAY:-24}"
DRY_RUN=false
SKIP_VERIFY=false

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCHEDULED_DIR="${REPO_ROOT}/bigquery_scheduled"
SCRIPTS_DIR="${REPO_ROOT}/scripts"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
usage() {
    echo "Usage: $0 --bucket BUCKET_NAME [--dry-run] [--skip-verify]"
    echo ""
    echo "Options:"
    echo "  --bucket NAME       GCS bucket name (required)"
    echo "  --dry-run           Show commands without executing destructive ops"
    echo "  --skip-verify       Skip the GCS folder verification step"
    echo "  --migrations M...   Migration IDs to verify (default: ${MIGRATIONS})"
    echo "  --start-month M     Verification start month (default: ${VERIFY_START_MONTH})"
    echo "  --start-day D       Verification start day (default: ${VERIFY_START_DAY})"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bucket)       BUCKET="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --skip-verify)  SKIP_VERIFY=true; shift ;;
        --migrations)   MIGRATIONS=""; shift
                        while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                            MIGRATIONS="${MIGRATIONS} $1"; shift
                        done ;;
        --start-month)  VERIFY_START_MONTH="$2"; shift 2 ;;
        --start-day)    VERIFY_START_DAY="$2"; shift 2 ;;
        -h|--help)      usage ;;
        *)              echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "${BUCKET}" ]]; then
    echo "ERROR: --bucket is required."
    usage
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
step_header() {
    local step_num="$1"
    local title="$2"
    echo ""
    echo "======================================================================"
    echo "  STEP ${step_num}: ${title}"
    echo "======================================================================"
}

run_bq() {
    local description="$1"
    shift
    echo "  -> ${description}"
    if [[ "${DRY_RUN}" == true ]]; then
        echo "     [DRY RUN] bq $*"
    else
        bq "$@"
    fi
}

run_bq_query() {
    local description="$1"
    local sql_file="$2"
    echo "  -> ${description}"
    echo "     SQL file: ${sql_file}"
    if [[ ! -f "${sql_file}" ]]; then
        echo "  ERROR: SQL file not found: ${sql_file}"
        return 1
    fi
    if [[ "${DRY_RUN}" == true ]]; then
        echo "     [DRY RUN] Would execute: $(head -3 "${sql_file}")"
    else
        bq query \
            --use_legacy_sql=false \
            --project_id="${PROJECT_ID}" \
            --location="${LOCATION}" \
            < "${sql_file}"
    fi
}

confirm() {
    local prompt="$1"
    if [[ "${DRY_RUN}" == true ]]; then
        return 0
    fi
    echo ""
    read -r -p "  ${prompt} [y/N] " response
    case "${response}" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) echo "  Aborted."; exit 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Print configuration
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  Canton Pipeline Rebuild"
echo "======================================================================"
echo "  Project:      ${PROJECT_ID}"
echo "  Location:     ${LOCATION}"
echo "  GCS Bucket:   ${BUCKET}"
echo "  Dry run:      ${DRY_RUN}"
echo "  Skip verify:  ${SKIP_VERIFY}"
echo ""
echo "  Data sources:"
echo "    Backfill: gs://${BUCKET}/raw/backfill/events/*"
echo "    Updates:  gs://${BUCKET}/raw/updates/events/*"
echo "======================================================================"

confirm "This will DELETE existing data tables and rebuild from scratch. Continue?"

# ===================================================================
# STEP 1: Delete existing data tables
# ===================================================================
step_header 1 "Delete existing BigQuery data tables"

echo "  Tables to delete:"
echo "    - ${PROJECT_ID}:raw.events"
echo "    - ${PROJECT_ID}:transformed.events_parsed"
echo ""

confirm "Permanently delete these tables? This cannot be undone."

run_bq "Deleting raw.events" \
    rm -f "${PROJECT_ID}:raw.events"

run_bq "Deleting transformed.events_parsed" \
    rm -f "${PROJECT_ID}:transformed.events_parsed"

echo ""
echo "  [OK] Tables deleted."

# ===================================================================
# STEP 2: Re-create empty tables with correct schema
# ===================================================================
step_header 2 "Re-create empty tables with correct schema and partitioning"

# raw.events — partitioned by event_date
# Note: template_name is NOT stored in raw — it is derived during
# transformation.  The raw table stores template_id as-is from parquet.
run_bq "Creating raw.events (partitioned by event_date)" \
    query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
    "CREATE TABLE \`${PROJECT_ID}.raw.events\` (
        event_id STRING,
        update_id STRING,
        event_type STRING,
        event_type_original STRING,
        synchronizer_id STRING,
        effective_at STRING,
        recorded_at STRING,
        timestamp STRING,
        created_at_ts STRING,
        contract_id STRING,
        template_id STRING,
        package_name STRING,
        migration_id INT64,
        signatories ARRAY<STRING>,
        observers ARRAY<STRING>,
        acting_parties ARRAY<STRING>,
        witness_parties ARRAY<STRING>,
        child_event_ids ARRAY<STRING>,
        choice STRING,
        interface_id STRING,
        consuming BOOL,
        reassignment_counter INT64,
        source_synchronizer STRING,
        target_synchronizer STRING,
        unassign_id STRING,
        submitter STRING,
        payload STRING,
        contract_key STRING,
        exercise_result STRING,
        raw_event STRING,
        trace_context STRING,
        year INT64,
        month INT64,
        day INT64,
        migration INT64,
        event_date DATE
    )
    PARTITION BY event_date
    CLUSTER BY template_id, event_type, migration_id;"

# transformed.events_parsed — partitioned by event_date, clustered
# Includes template_name (bare module:entity without package hash)
# for efficient cross-migration queries.
run_bq "Creating transformed.events_parsed (partitioned + clustered)" \
    query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
    "CREATE TABLE \`${PROJECT_ID}.transformed.events_parsed\` (
        event_id STRING,
        update_id STRING,
        contract_id STRING,
        template_id STRING,
        template_name STRING,
        package_name STRING,
        event_type STRING,
        event_type_original STRING,
        synchronizer_id STRING,
        migration_id INT64,
        choice STRING,
        interface_id STRING,
        consuming BOOL,
        effective_at TIMESTAMP,
        recorded_at TIMESTAMP,
        timestamp TIMESTAMP,
        created_at_ts TIMESTAMP,
        signatories ARRAY<STRING>,
        observers ARRAY<STRING>,
        acting_parties ARRAY<STRING>,
        witness_parties ARRAY<STRING>,
        child_event_ids ARRAY<STRING>,
        reassignment_counter INT64,
        source_synchronizer STRING,
        target_synchronizer STRING,
        unassign_id STRING,
        submitter STRING,
        payload JSON,
        contract_key JSON,
        exercise_result JSON,
        raw_event JSON,
        trace_context JSON,
        year INT64,
        month INT64,
        day INT64,
        migration INT64,
        event_date DATE
    )
    PARTITION BY event_date
    CLUSTER BY template_name, event_type, migration_id;"

echo ""
echo "  [OK] Tables created."

# ===================================================================
# STEP 3: Ensure both external tables exist
# ===================================================================
step_header 3 "Ensure external tables exist"

# External table for backfill data (Hive-partitioned: year=.../month=.../day=...)
echo "  Checking raw.events_external..."
if ! bq show "${PROJECT_ID}:raw.events_external" > /dev/null 2>&1; then
    run_bq "Creating external table raw.events_external -> gs://${BUCKET}/raw/backfill/events/*" \
        mk --table \
        --external_table_definition="@PARQUET=gs://${BUCKET}/raw/backfill/events/*" \
        --hive_partitioning_mode=AUTO \
        --hive_partitioning_source_uri_prefix="gs://${BUCKET}/raw/backfill/events/" \
        "${PROJECT_ID}:raw.events_external"
else
    echo "  [OK] raw.events_external already exists."
fi

# External table for updates data (Hive-partitioned: year=.../month=.../day=...)
echo "  Checking raw.events_updates_external..."
if ! bq show "${PROJECT_ID}:raw.events_updates_external" > /dev/null 2>&1; then
    run_bq "Creating external table raw.events_updates_external -> gs://${BUCKET}/raw/updates/events/*" \
        mk --table \
        --external_table_definition="@PARQUET=gs://${BUCKET}/raw/updates/events/*" \
        --hive_partitioning_mode=AUTO \
        --hive_partitioning_source_uri_prefix="gs://${BUCKET}/raw/updates/events/" \
        "${PROJECT_ID}:raw.events_updates_external"
else
    echo "  [OK] raw.events_updates_external already exists."
fi

echo ""
echo "  [OK] Both external tables verified."

# ===================================================================
# STEP 4: Verify GCS folder structure
# ===================================================================
step_header 4 "Verify GCS parquet folder dates match effective_at"

if [[ "${SKIP_VERIFY}" == true ]]; then
    echo "  [SKIPPED] --skip-verify was set."
else
    echo "  Running: python ${SCRIPTS_DIR}/verify_gcs_event_data_folders.py"
    echo "    --bucket ${BUCKET}"
    echo "    --migrations ${MIGRATIONS}"
    echo "    --start-month ${VERIFY_START_MONTH}"
    echo "    --start-day ${VERIFY_START_DAY}"
    echo ""

    if [[ "${DRY_RUN}" == true ]]; then
        echo "  [DRY RUN] Would run verification script."
    else
        # shellcheck disable=SC2086
        python "${SCRIPTS_DIR}/verify_gcs_event_data_folders.py" \
            --bucket "${BUCKET}" \
            --migrations ${MIGRATIONS} \
            --start-month "${VERIFY_START_MONTH}" \
            --start-day "${VERIFY_START_DAY}"

        VERIFY_EXIT=$?
        if [[ ${VERIFY_EXIT} -ne 0 ]]; then
            echo ""
            echo "  *** VERIFICATION FAILED ***"
            echo "  Some parquet files have effective_at dates that do not match"
            echo "  their folder partitions. Fix the data in GCS before proceeding."
            echo ""
            confirm "Override and continue anyway? (NOT recommended)"
        else
            echo ""
            echo "  [OK] All parquet files verified — folder dates match effective_at."
        fi
    fi
fi

# ===================================================================
# STEP 5: Ingest ALL historical data from BOTH GCS sources
# ===================================================================
step_header 5 "Ingest all historical data from GCS into raw.events"

echo "  This reads BOTH external tables (backfill + updates)."
echo "  The SQL handles dedup so the March 3 overlap is safe."
echo ""

run_bq_query \
    "Running historical ingest (backfill + updates)" \
    "${SCHEDULED_DIR}/ingest_events_from_gcs_historical.sql"

echo ""
echo "  Verifying row count..."
if [[ "${DRY_RUN}" != true ]]; then
    bq query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
        "SELECT COUNT(*) AS total_rows,
                COUNT(DISTINCT event_date) AS distinct_dates,
                MIN(event_date) AS min_date,
                MAX(event_date) AS max_date
         FROM \`${PROJECT_ID}.raw.events\`"

    echo ""
    echo "  Checking for gaps in daily coverage..."
    bq query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
        "WITH date_range AS (
            SELECT MIN(event_date) AS min_d, MAX(event_date) AS max_d
            FROM \`${PROJECT_ID}.raw.events\`
        ),
        all_dates AS (
            SELECT d
            FROM date_range, UNNEST(GENERATE_DATE_ARRAY(min_d, max_d)) AS d
        ),
        actual_dates AS (
            SELECT DISTINCT event_date FROM \`${PROJECT_ID}.raw.events\`
        )
        SELECT a.d AS missing_date
        FROM all_dates a
        LEFT JOIN actual_dates b ON a.d = b.event_date
        WHERE b.event_date IS NULL
        ORDER BY a.d"
fi

echo ""
echo "  [OK] Historical ingest complete."

# Clean up: drop the backfill external table (no longer needed)
echo ""
echo "  Dropping raw.events_external (backfill data already ingested)..."
run_bq "Dropping raw.events_external" \
    rm -f "${PROJECT_ID}:raw.events_external"
echo "  [OK] raw.events_external dropped."

# ===================================================================
# STEP 6: Transform ALL historical data
# ===================================================================
step_header 6 "Transform all historical data (raw -> parsed)"

echo "  This reads the ENTIRE raw.events table. It may take a while."
echo ""

run_bq_query \
    "Running historical transform (full table scan)" \
    "${SCHEDULED_DIR}/transform_events_historical.sql"

echo ""
echo "  Verifying row count..."
if [[ "${DRY_RUN}" != true ]]; then
    bq query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
        "SELECT COUNT(*) AS total_rows,
                COUNT(DISTINCT event_date) AS distinct_dates,
                MIN(event_date) AS min_date,
                MAX(event_date) AS max_date
         FROM \`${PROJECT_ID}.transformed.events_parsed\`"

    echo ""
    echo "  Comparing raw vs parsed counts..."
    bq query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
        "SELECT
            (SELECT COUNT(*) FROM \`${PROJECT_ID}.raw.events\`) AS raw_count,
            (SELECT COUNT(*) FROM \`${PROJECT_ID}.transformed.events_parsed\`) AS parsed_count"

    echo ""
    echo "  Spot-checking template_name extraction..."
    bq query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
        "SELECT template_id, template_name
         FROM \`${PROJECT_ID}.transformed.events_parsed\`
         WHERE template_name IS NOT NULL
         LIMIT 5"
fi

echo ""
echo "  [OK] Historical transform complete."

# ===================================================================
# STEP 7: Set up daily scheduled queries (MANUAL — BigQuery UI)
# ===================================================================
step_header 7 "Set up daily scheduled queries for ongoing data"

echo "  The bq CLI has limited support for scheduled queries (cannot set"
echo "  precise start times, cron expressions, or time zones reliably)."
echo "  Create these manually in the BigQuery Console."
echo ""
echo "  Console URL:"
echo "    https://console.cloud.google.com/bigquery/scheduled-queries?project=${PROJECT_ID}"
echo ""
echo "  ---------------------------------------------------------------"
echo "  QUERY 1: Canton: ingest_events_from_gcs"
echo "  ---------------------------------------------------------------"
echo "    1. Click 'Create scheduled query'"
echo "    2. Paste the contents of:"
echo "       ${SCHEDULED_DIR}/ingest_events_from_gcs.sql"
echo "    3. Display name:  Canton: ingest_events_from_gcs"
echo "    4. Schedule:      Custom cron: 0 0 * * *  (daily at 00:00 UTC)"
echo "    5. Location:      ${LOCATION}"
echo "    6. Click 'Schedule'"
echo ""
echo "    NOTE: This query reads from raw.events_updates_external"
echo "          (gs://${BUCKET}/raw/updates/events/*)."
echo "          New data must be written to this GCS path."
echo ""
echo "  ---------------------------------------------------------------"
echo "  QUERY 2: Canton: transform_raw_events"
echo "  ---------------------------------------------------------------"
echo "    1. Click 'Create scheduled query'"
echo "    2. Paste the contents of:"
echo "       ${SCHEDULED_DIR}/transform_events.sql"
echo "    3. Display name:  Canton: transform_raw_events"
echo "    4. Schedule:      Custom cron: 0 1 * * *  (daily at 01:00 UTC)"
echo "    5. Location:      ${LOCATION}"
echo "    6. Click 'Schedule'"
echo ""
echo "  The 1-hour offset ensures ingest completes before transform runs."
echo ""

read -r -p "  Press Enter once you have created both scheduled queries... "

# ===================================================================
# Summary
# ===================================================================
echo ""
echo "======================================================================"
echo "  PIPELINE REBUILD COMPLETE"
echo "======================================================================"
echo ""
echo "  What was done:"
echo "    1. Deleted old raw.events and transformed.events_parsed tables"
echo "    2. Re-created empty tables with correct schema/partitioning"
echo "    3. Created external tables for ingestion"
if [[ "${SKIP_VERIFY}" == true ]]; then
    echo "    4. GCS verification: SKIPPED"
else
    echo "    4. Verified GCS parquet folder dates match effective_at"
fi
echo "    5. Ingested all historical data from BOTH GCS sources"
echo "    6. Dropped raw.events_external (one-time backfill table)"
echo "    7. Transformed all historical data (with template_name extraction)"
echo "    8. Scheduled queries set up manually in BigQuery Console"
echo ""
echo "  Schema highlights:"
echo "    - raw.events: template_id as-is from parquet"
echo "    - transformed.events_parsed: template_name added"
echo "      (bare module:entity name without package hash prefix)"
echo "    - Clustering: transformed table clusters by template_name"
echo "      (not template_id) for efficient cross-migration queries"
echo ""
echo "  Next steps:"
echo "    - Monitor tomorrow's scheduled query runs in BigQuery Console"
echo "    - Query by template_name (e.g. 'Splice.Amulet:Amulet') instead"
echo "      of template_id for cross-migration analysis"
echo ""
echo "======================================================================"
