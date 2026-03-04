#!/bin/bash
# =============================================================================
# rebuild_pipeline.sh — Full pipeline rebuild from scratch
#
# Deletes existing BigQuery data tables, verifies GCS data integrity,
# ingests all historical data, transforms it, then sets up the daily
# scheduled queries for ongoing ingestion.
#
# Steps:
#   1. Delete raw.events and transformed.events_parsed tables
#   2. Re-create the tables (empty, with correct schema/partitioning)
#   3. Verify GCS parquet folder structure matches effective_at dates
#   4. Ingest ALL historical data from GCS into raw.events
#   5. Transform ALL historical data into transformed.events_parsed
#   6. Set up daily scheduled queries for new incoming data
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
GCS_PREFIX="${GCS_PREFIX:-raw/backfill/events/migration=0}"
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
    echo "  --prefix PREFIX     GCS prefix (default: ${GCS_PREFIX})"
    echo "  --start-month M     Verification start month (default: ${VERIFY_START_MONTH})"
    echo "  --start-day D       Verification start day (default: ${VERIFY_START_DAY})"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bucket)       BUCKET="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --skip-verify)  SKIP_VERIFY=true; shift ;;
        --prefix)       GCS_PREFIX="$2"; shift 2 ;;
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
echo "  GCS Prefix:   ${GCS_PREFIX}"
echo "  Dry run:      ${DRY_RUN}"
echo "  Skip verify:  ${SKIP_VERIFY}"
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
        migration_id STRING,
        signatories STRUCT<list ARRAY<STRUCT<element STRING>>>,
        observers STRUCT<list ARRAY<STRUCT<element STRING>>>,
        acting_parties STRUCT<list ARRAY<STRUCT<element STRING>>>,
        witness_parties STRUCT<list ARRAY<STRUCT<element STRING>>>,
        child_event_ids STRUCT<list ARRAY<STRUCT<element STRING>>>,
        choice STRING,
        interface_id STRING,
        consuming STRING,
        reassignment_counter STRING,
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
        event_date DATE
    )
    PARTITION BY event_date;"

# transformed.events_parsed — partitioned by event_date, clustered
run_bq "Creating transformed.events_parsed (partitioned + clustered)" \
    query --use_legacy_sql=false --project_id="${PROJECT_ID}" --location="${LOCATION}" \
    "CREATE TABLE \`${PROJECT_ID}.transformed.events_parsed\` (
        event_id STRING,
        update_id STRING,
        contract_id STRING,
        template_id STRING,
        package_name STRING,
        event_type STRING,
        event_type_original STRING,
        synchronizer_id STRING,
        migration_id STRING,
        choice STRING,
        interface_id STRING,
        consuming STRING,
        effective_at TIMESTAMP,
        recorded_at TIMESTAMP,
        timestamp TIMESTAMP,
        created_at_ts TIMESTAMP,
        signatories ARRAY<STRING>,
        observers ARRAY<STRING>,
        acting_parties ARRAY<STRING>,
        witness_parties ARRAY<STRING>,
        child_event_ids ARRAY<STRING>,
        reassignment_counter STRING,
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
        event_date DATE
    )
    PARTITION BY event_date
    CLUSTER BY template_id, event_type, migration_id;"

# Ensure external table exists
echo ""
echo "  Ensuring external table raw.events_updates_external exists..."
if ! bq show "${PROJECT_ID}:raw.events_updates_external" > /dev/null 2>&1; then
    run_bq "Creating external table raw.events_updates_external" \
        mk --table \
        --external_table_definition="parquet=gs://${BUCKET}/raw/updates/events/*" \
        "${PROJECT_ID}:raw.events_updates_external"
else
    echo "  [OK] External table already exists."
fi

echo ""
echo "  [OK] Tables created."

# ===================================================================
# STEP 3: Verify GCS folder structure
# ===================================================================
step_header 3 "Verify GCS parquet folder dates match effective_at"

if [[ "${SKIP_VERIFY}" == true ]]; then
    echo "  [SKIPPED] --skip-verify was set."
else
    echo "  Running: python ${SCRIPTS_DIR}/verify_gcs_event_data_folders.py"
    echo "    --bucket ${BUCKET}"
    echo "    --prefix ${GCS_PREFIX}"
    echo "    --start-month ${VERIFY_START_MONTH}"
    echo "    --start-day ${VERIFY_START_DAY}"
    echo ""

    if [[ "${DRY_RUN}" == true ]]; then
        echo "  [DRY RUN] Would run verification script."
    else
        python "${SCRIPTS_DIR}/verify_gcs_event_data_folders.py" \
            --bucket "${BUCKET}" \
            --prefix "${GCS_PREFIX}" \
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
# STEP 4: Ingest ALL historical data from GCS
# ===================================================================
step_header 4 "Ingest all historical data from GCS into raw.events"

echo "  This reads the ENTIRE external table. It may take a while."
echo ""

run_bq_query \
    "Running historical ingest (full GCS scan)" \
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
fi

echo ""
echo "  [OK] Historical ingest complete."

# ===================================================================
# STEP 5: Transform ALL historical data
# ===================================================================
step_header 5 "Transform all historical data (raw -> parsed)"

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
fi

echo ""
echo "  [OK] Historical transform complete."

# ===================================================================
# STEP 6: Set up daily scheduled queries
# ===================================================================
step_header 6 "Set up daily scheduled queries for ongoing data"

echo "  This will create two BigQuery scheduled queries:"
echo "    1. Canton: ingest_events_from_gcs  — daily at 00:00 UTC"
echo "    2. Canton: transform_raw_events    — daily at 01:00 UTC"
echo ""

confirm "Set up the scheduled queries now?"

if [[ "${DRY_RUN}" == true ]]; then
    echo "  [DRY RUN] Would run: bash ${SCHEDULED_DIR}/setup_scheduled_query.sh"
else
    bash "${SCHEDULED_DIR}/setup_scheduled_query.sh"
fi

echo ""
echo "  [OK] Scheduled queries created."

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
if [[ "${SKIP_VERIFY}" == true ]]; then
    echo "    3. GCS verification: SKIPPED"
else
    echo "    3. Verified GCS parquet folder dates match effective_at"
fi
echo "    4. Ingested all historical data from GCS into raw.events"
echo "    5. Transformed all historical data into transformed.events_parsed"
echo "    6. Set up daily scheduled queries for ongoing ingestion"
echo ""
echo "  Next steps:"
echo "    - Monitor tomorrow's scheduled query runs in BigQuery Console"
echo "    - Run health check: python scripts/monitor_pipeline.py"
echo "    - Run data quality: python scripts/data_quality_checks.py --skip-api-check"
echo ""
echo "======================================================================"
