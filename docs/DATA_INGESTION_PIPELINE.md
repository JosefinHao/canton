# Canton Blockchain Data Ingestion Pipeline

## Overview

This document describes the automated data ingestion pipeline that fetches blockchain data from the Canton Scan API and loads it into BigQuery for analysis.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Cloud          │     │  Cloud          │     │  BigQuery       │
│  Scheduler      │────▶│  Function       │────▶│  Tables         │
│  (every 15 min) │     │  (ingestion)    │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               │ Fetches data from
                               ▼
                        ┌─────────────────┐
                        │  Canton Scan    │
                        │  API            │
                        │  (/v2/updates)  │
                        └─────────────────┘
```

## Data Flow

1. **Cloud Scheduler** triggers the Cloud Function every 15 minutes
2. **Cloud Function** queries BigQuery for last processed position
3. **Cloud Function** fetches new updates from Scan API (incremental)
4. **Cloud Function** inserts raw events into `raw.events` table
5. **Cloud Function** runs transformation to update `transformed.events_parsed`

## Components

### 1. Data Ingestion Pipeline (`src/data_ingestion_pipeline.py`)

Main orchestration module that:
- Fetches updates from Canton Scan API using `/v2/updates` endpoint
- Extracts individual events from transaction updates
- Inserts raw events into BigQuery
- Triggers transformation to parsed table

### 2. BigQuery Client (`src/bigquery_client.py`)

Handles all BigQuery operations:
- Get last processed position (for incremental loading)
- Insert raw events via streaming API
- Run transformation queries
- Check pipeline status

### 3. Cloud Function (`cloud_functions/data_ingestion/main.py`)

HTTP-triggered serverless function with three endpoints:
- `ingest_data`: Main ingestion endpoint (called by scheduler)
- `transform_data`: Manual transformation trigger
- `get_status`: Pipeline status check

## BigQuery Tables

### Raw Events Table
- **Table**: `governence-483517.raw.events`
- **Purpose**: Store raw event data from API (STRING format)
- **Schema**: All fields as STRING for maximum flexibility

### Parsed Events Table
- **Table**: `governence-483517.transformed.events_parsed`
- **Purpose**: Store transformed data with proper types
- **Partitioning**: By `DATE(timestamp)`
- **Clustering**: By `template_id`, `event_type`, `migration_id`
- **Schema**: Properly typed fields (TIMESTAMP, INT64, BOOL, ARRAY, JSON)

## Deployment Options

Multiple deployment options are available depending on your GCP permissions and infrastructure preferences.

### Option 1: Standalone Python Script (Simplest)

Run the ingestion script manually or via cron on any machine with Python and BigQuery access.

**Prerequisites:**
- Python 3.8+
- BigQuery access (service account or user credentials)
- `GOOGLE_APPLICATION_CREDENTIALS` environment variable set

**Setup:**
```bash
# Install dependencies
pip install -r requirements.txt

# Run ingestion
python scripts/run_ingestion.py

# Run transformation only
python scripts/run_ingestion.py --transform-only

# Check status
python scripts/run_ingestion.py --status

# Custom settings
python scripts/run_ingestion.py --max-pages 50 --page-size 1000
```

**Cron setup (every 15 minutes):**
```bash
# Add to crontab (crontab -e)
*/15 * * * * cd /path/to/canton && /usr/bin/python3 scripts/run_ingestion.py >> /var/log/canton-ingestion.log 2>&1
```

### Option 2: BigQuery Scheduled Query (Transformation Only)

Use BigQuery's native scheduled queries for transformation. This doesn't fetch new data but transforms any raw data that exists.

**Setup via Console:**
1. Go to [BigQuery Console](https://console.cloud.google.com/bigquery?project=governence-483517)
2. Click "Scheduled queries" in the left menu
3. Click "Create scheduled query"
4. Paste contents of `bigquery_scheduled/transform_events.sql`
5. Set schedule to "every 15 minutes"
6. Click "Schedule"

**Setup via CLI:**
```bash
cd bigquery_scheduled
./setup_scheduled_query.sh
```

### Option 3: Cloud Run (Containerized)

Deploy as a containerized service on Cloud Run.

**Prerequisites:**
- Cloud Run API enabled
- Cloud Build API enabled
- Artifact Registry API enabled

**Deploy:**
```bash
cd cloud_run/data_ingestion
./deploy.sh
./setup_scheduler.sh
```

### Option 4: Cloud Functions (Serverless)

Deploy as a Cloud Function triggered by Cloud Scheduler.

**Prerequisites:**
- Cloud Functions API enabled
- Cloud Scheduler API enabled

**Deploy:**
```bash
cd cloud_functions/data_ingestion
./deploy.sh
./setup_scheduler.sh
```

### Required APIs and Permissions

If you encounter permission errors, ask a project admin to enable:

```bash
# For Cloud Run
gcloud services enable run.googleapis.com --project governence-483517
gcloud services enable cloudbuild.googleapis.com --project governence-483517
gcloud services enable artifactregistry.googleapis.com --project governence-483517

# For Cloud Functions
gcloud services enable cloudfunctions.googleapis.com --project governence-483517

# For Cloud Scheduler
gcloud services enable cloudscheduler.googleapis.com --project governence-483517

# BigQuery (likely already enabled)
gcloud services enable bigquery.googleapis.com --project governence-483517
```

### Environment Variables

Configure these environment variables for the Cloud Function:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCAN_API_BASE_URL` | `https://scan.sv-1.global.canton.network.sync.global/api/scan/` | Scan API base URL |
| `BQ_PROJECT_ID` | `governence-483517` | BigQuery project ID |
| `BQ_RAW_DATASET` | `raw` | Raw events dataset |
| `BQ_TRANSFORMED_DATASET` | `transformed` | Transformed events dataset |
| `BQ_RAW_TABLE` | `events` | Raw events table name |
| `BQ_PARSED_TABLE` | `events_parsed` | Parsed events table name |
| `PAGE_SIZE` | `500` | Updates per API call |
| `MAX_PAGES_PER_RUN` | `100` | Max pages per execution |
| `AUTO_TRANSFORM` | `true` | Auto-run transformation |

## Manual Operations

### Run Ingestion Manually

```bash
# Using curl
curl -X POST https://REGION-PROJECT.cloudfunctions.net/canton-data-ingestion

# Using gcloud scheduler
gcloud scheduler jobs run canton-data-ingestion-scheduler --location=us-central1
```

### Run Transformation Only

```bash
curl -X POST https://REGION-PROJECT.cloudfunctions.net/canton-data-ingestion-transform
```

### Check Status

```bash
curl https://REGION-PROJECT.cloudfunctions.net/canton-data-ingestion-status
```

### Run Locally (for testing)

```bash
cd cloud_functions/data_ingestion

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BQ_PROJECT_ID=governence-483517
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Run local server
python main.py

# Test endpoints
curl http://localhost:8080/status
curl -X POST http://localhost:8080/ingest
```

## Monitoring

### View Function Logs

```bash
gcloud functions logs read canton-data-ingestion --region=us-central1
```

### BigQuery Monitoring

```sql
-- Check latest ingestion (using state table for efficiency)
SELECT migration_id, recorded_at, updated_at
FROM `governence-483517.raw.ingestion_state`
WHERE table_name = 'raw_events';

-- Check latest raw data
SELECT
    MAX(recorded_at) as latest_record,
    COUNT(*) as total_events
FROM `governence-483517.raw.events`;

-- Check transformation status
SELECT
    MAX(recorded_at) as latest_transformed,
    COUNT(*) as total_parsed
FROM `governence-483517.transformed.events_parsed`;

-- Events per day
SELECT
    DATE(timestamp) as date,
    COUNT(*) as event_count
FROM `governence-483517.transformed.events_parsed`
GROUP BY date
ORDER BY date DESC
LIMIT 30;
```

## Incremental Loading Logic

The pipeline uses `migration_id` and `recorded_at` to track position:

1. Query state table for latest `(migration_id, recorded_at)` (very fast)
2. Fallback to MAX() query if state not found
3. Call Scan API with `after` parameter (API uses `record_time`, mapped to `recorded_at`)
4. Insert new events and update state table

This ensures:
- No duplicate events
- No gaps in data
- Efficient incremental loading (avoids 10+ TB table scans)
- Ability to catch up after downtime

## Error Handling

- **API errors**: Retry with exponential backoff (3 attempts)
- **BigQuery errors**: Logged and returned in response
- **Partial failures**: Continue processing, report errors in stats
- **Transformation errors**: Logged, raw data preserved

## Performance Tuning

### For High Volume

```python
config = PipelineConfig(
    page_size=1000,           # Larger pages
    max_pages_per_run=200,    # More pages per run
    batch_size=500,           # Larger BigQuery batches
    api_delay_seconds=0.05    # Faster API calls
)
```

### For Cost Optimization

```python
config = PipelineConfig(
    page_size=500,
    max_pages_per_run=50,     # Fewer pages
    transform_batch_threshold=5000,  # Less frequent transforms
    auto_transform=False      # Manual transformation
)
```

## Troubleshooting

### Function Timeout
- Increase `TIMEOUT` in deployment (max 540s)
- Reduce `MAX_PAGES_PER_RUN`
- Increase function memory

### Rate Limiting
- Increase `API_DELAY_SECONDS`
- Reduce `PAGE_SIZE`

### Missing Data
- Check last processed position in BigQuery
- Verify Scan API is accessible
- Check for error messages in function logs

### Transformation Lag
- Run transformation manually
- Increase `TRANSFORM_BATCH_THRESHOLD`
- Check for BigQuery quota limits

## API Reference

### Scan API Endpoint

**POST /v2/updates**

Request:
```json
{
    "page_size": 500,
    "daml_value_encoding": "compact_json",
    "after": {
        "after_migration_id": 0,
        "after_record_time": "2024-01-01T00:00:00Z"
    }
}
```

Response:
```json
{
    "transactions": [
        {
            "migration_id": 0,
            "record_time": "2024-01-01T00:00:01Z",
            "synchronizer_id": "...",
            "update_id": "...",
            "effective_at": "2024-01-01T00:00:01Z",
            "events_by_id": {...}
        }
    ]
}
```

### Schema Mapping

The pipeline maps API fields to BigQuery columns:

| API Field | BigQuery Column | Notes |
|-----------|----------------|-------|
| `record_time` | `recorded_at` | Timestamp of when event was recorded |
| `synchronizer_id` | `synchronizer_id` | Synchronizer that processed the event |
| Party arrays | Nested `{list: [{element}]}` | Arrays use BigQuery nested format |

## Cost Estimation

| Component | Approximate Cost |
|-----------|-----------------|
| Cloud Function (per invocation) | ~$0.0000004 |
| Cloud Scheduler (per job/month) | $0.10 |
| BigQuery Streaming Insert | $0.01 per 200 MB |
| BigQuery Storage | $0.02 per GB/month |

With 96 invocations/day (every 15 min):
- Cloud Function: ~$0.001/day
- Cloud Scheduler: $0.10/month
- BigQuery costs depend on data volume

## Next Steps

1. **Set up alerting**: Configure Cloud Monitoring alerts for failures
2. **Add dead letter queue**: Handle persistent failures
3. **Create analytics tables**: Build materialized views for specific use cases
4. **Implement backfill**: Handle historical data gaps
5. **Add data validation**: Verify data integrity checks
