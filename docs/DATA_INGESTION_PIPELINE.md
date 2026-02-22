# Canton Blockchain Data Ingestion Pipeline

## Overview

This document describes the automated data ingestion pipeline that fetches blockchain data from the Canton Scan API and loads it into BigQuery for analysis.

## Pipeline Strategy Decision (Final)

The Canton data pipeline uses **two complementary pipelines**:

| Pipeline | Trigger | Purpose | Status |
|----------|---------|---------|--------|
| **Primary: Cloud Run + Cloud Scheduler** | Every 15 minutes (OIDC) | Incremental live ingestion from Scan API → `raw.events` | ✅ Active |
| **Secondary: BigQuery Scheduled Query (GCS)** | Daily at 00:00 UTC | Bulk-load historical parquet files from GCS → `raw.events` | ✅ Active (for historical data) |
| **Transformation: BigQuery Scheduled Query** | Daily at 01:00 UTC | Transform `raw.events` → `transformed.events_parsed` | ✅ Active |

**Rationale:**
- The Cloud Run pipeline handles **all new live data** via incremental API polling every 15 minutes.
- The GCS scheduled query handles **historical bulk-loaded parquet files** stored in `gs://canton-bucket/raw/updates/events/`. Once all historical data is migrated, this query will have nothing to insert (expected behavior).
- The transformation scheduled query runs **daily as a reconciliation step** to ensure any events inserted via the GCS pipeline are also transformed. The Cloud Run pipeline also auto-transforms after each run (`auto_transform=true`), so the daily query catches any remaining gaps.
- **Both pipelines are kept active** (not deprecated) because they serve complementary roles.

## Phase 3: Data Pipeline & Automation - Implementation Status

| Step | Status | Description |
|------|--------|-------------|
| Cloud Storage buckets | ✅ Done | Raw data storage configured |
| Cloud Run for Scan API ingestion | ✅ Done | Containerized service with SV node failover |
| Network Configuration | ✅ Done | Cloud NAT + VPC connector for static IP egress |
| Data transformation pipeline | ✅ Done | BigQuery scheduled query transforms raw → parsed |
| Cloud Scheduler | ✅ Done | Triggers ingestion every 15 minutes with OIDC auth |
| IP Whitelisting | ⏳ Pending | Static IP 34.132.24.144 needs whitelisting by SV operators |
| Data Quality Checks | ✅ Done | Comprehensive suite in `scripts/data_quality_checks.py` |
| Monitoring and Alerting | ✅ Done | `scripts/monitor_pipeline.py` + `scripts/setup_monitoring_alerts.sh` |
| Runbook | ✅ Done | `docs/RUNBOOK.md` — common failure scenarios and resolution steps |

---

### Step 1: Cloud Run for Scan API Ingestion

**Purpose:** Containerized service that fetches blockchain events from Canton Scan API and loads them into BigQuery.

**Key Features:**
- **Automatic SV Node Failover:** Tries 13 MainNet Super Validator nodes in sequence until one responds
- **Fast Failover:** 10-second timeout per node (total ~2-3 minutes to try all nodes)
- **URL Caching:** Once a working SV node is found, it's cached for subsequent requests
- **Incremental Loading:** Uses `(migration_id, recorded_at)` cursor to fetch only new events
- **State Table Optimization:** O(1) position lookup via `raw.ingestion_state` table (avoids 10+ TB scans)

**Service Configuration:**
| Setting | Value |
|---------|-------|
| Service Name | `canton-data-ingestion` |
| Region | `us-central1` |
| Memory | 512 MB |
| CPU | 1 |
| Max Instances | 1 |
| Timeout | 300s |
| VPC Connector | `canton-connector` |
| Egress | All traffic through VPC |

**Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/ingest` | POST | Main ingestion (fetches events, inserts to BigQuery) |
| `/transform` | POST | Run transformation only |
| `/status` | GET | Pipeline status and last processed position |

**Files:**
- `cloud_run/data_ingestion/main.py` - Flask HTTP service
- `cloud_run/data_ingestion/data_ingestion_pipeline.py` - Orchestration logic
- `cloud_run/data_ingestion/canton_scan_client.py` - API client with failover
- `cloud_run/data_ingestion/bigquery_client.py` - BigQuery operations
- `cloud_run/data_ingestion/Dockerfile` - Container definition
- `cloud_run/data_ingestion/deploy.sh` - Deployment script

---

### Step 2: Network Configuration (Cloud NAT + VPC Connector)

**Purpose:** Route Cloud Run egress traffic through a static IP address for whitelisting by SV node operators.

**Problem Solved:**
- Cloud Run uses dynamic IPs by default, which cannot be whitelisted
- MainNet SV nodes require IP whitelisting for API access
- Solution: VPC Connector → Cloud NAT → Static IP

**Components:**

| Component | Name | Configuration |
|-----------|------|---------------|
| VPC Connector | `canton-connector` | Network: `default`, IP Range: `10.8.0.0/28`, Region: `us-central1` |
| Cloud Router | `canton-router` | Network: `default`, Region: `us-central1` |
| Cloud NAT | `canton-nat` | Router: `canton-router`, Source: All subnets, IP: Manual |
| Static IP | `canton-nat-ip` | Address: `34.132.24.144`, Type: External, Status: IN_USE |

**Traffic Flow:**
```
Cloud Run Service
       │
       ▼
VPC Connector (canton-connector)
       │
       ▼
Cloud Router (canton-router)
       │
       ▼
Cloud NAT (canton-nat)
       │
       ▼
Static IP: 34.132.24.144
       │
       ▼
Internet → SV Node APIs
```

**Verification Commands:**
```bash
# Check VPC connector
gcloud compute networks vpc-access connectors describe canton-connector \
    --region=us-central1 --project=governence-483517

# Check Cloud NAT
gcloud compute routers nats describe canton-nat \
    --router=canton-router --region=us-central1 --project=governence-483517

# Check static IP
gcloud compute addresses describe canton-nat-ip \
    --region=us-central1 --format='value(address)' --project=governence-483517
```

---

### Step 3: Data Transformation Pipeline (BigQuery Scheduled Query)

**Purpose:** Transform raw STRING data in `raw.events` to properly typed data in `transformed.events_parsed`.

**Transformation Logic:**
- Parse STRING timestamps to TIMESTAMP type
- Convert STRING integers to INT64
- Convert STRING booleans to BOOL
- Parse JSON strings to JSON type
- Handle nested array structures
- Add partitioning and clustering for query performance

**Source Table:** `governence-483517.raw.events`
- All fields stored as STRING for maximum flexibility
- ~10+ TB of historical data

**Target Table:** `governence-483517.transformed.events_parsed`
- Properly typed fields (TIMESTAMP, INT64, BOOL, JSON)
- Partitioned by `DATE(timestamp)`
- Clustered by `template_id`, `event_type`, `migration_id`

**Scheduled Query Configuration:**

Two daily BigQuery scheduled queries run in sequence:

| Setting | Ingest (GCS → raw.events) | Transform (raw → parsed) |
|---------|---------------------------|--------------------------|
| Name | `ingest_events_from_gcs` | `transform_raw_events` |
| Schedule | Daily at 00:00 UTC | Daily at 01:00 UTC |
| Location | US | US |
| SQL File | `bigquery_scheduled/ingest_events_from_gcs.sql` | `bigquery_scheduled/transform_events.sql` |
| Lookback | 1-day (`DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)`) | 1-day (`DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)`) |
| Dedup | `NOT EXISTS` on `event_id + event_date` | `NOT EXISTS` on `event_id + event_date` |
| Est. daily cost | ~$0.50 (~80 GB scanned) | ~$1.00 (~160 GB scanned) |

**Key Transformations:**
```sql
-- Timestamp parsing
SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', recorded_at) AS recorded_at,

-- Integer conversion
SAFE_CAST(migration_id AS INT64) AS migration_id,

-- Boolean conversion
SAFE_CAST(consuming AS BOOL) AS consuming,

-- JSON parsing
SAFE.PARSE_JSON(payload) AS payload,
```

**Setup Commands:**
```bash
# Via CLI
cd bigquery_scheduled
./setup_scheduled_query.sh

# Or via Console
# 1. Go to BigQuery Console → Scheduled queries
# 2. Create new scheduled query
# 3. Paste transform_events.sql content
# 4. Set schedule to "every 15 minutes"
```

---

### Step 4: Cloud Scheduler with OIDC Authentication

**Purpose:** Trigger the Cloud Run ingestion service every 15 minutes with secure authentication.

**Why OIDC Authentication:**
- Cloud Run requires authentication by default (not publicly accessible)
- OIDC tokens provide secure service-to-service authentication
- No need to expose the service publicly

**Components:**

| Component | Name | Purpose |
|-----------|------|---------|
| Service Account | `scheduler-invoker@governence-483517.iam.gserviceaccount.com` | Identity for scheduler |
| IAM Binding | `roles/run.invoker` | Permission to invoke Cloud Run |
| Scheduler Job | `canton-data-ingestion-scheduler` | Triggers ingestion every 15 min |

**Scheduler Job Configuration:**
| Setting | Value |
|---------|-------|
| Name | `canton-data-ingestion-scheduler` |
| Region | `us-central1` |
| Schedule | `*/15 * * * *` (every 15 minutes) |
| Time Zone | UTC |
| HTTP Method | POST |
| Target URL | `https://canton-data-ingestion-224112423672.us-central1.run.app/ingest` |
| Auth Type | OIDC Token |
| Service Account | `scheduler-invoker@governence-483517.iam.gserviceaccount.com` |

**Request Body:**
```json
{
    "max_pages": 100,
    "auto_transform": true
}
```

**Management Commands:**
```bash
# View job status
gcloud scheduler jobs describe canton-data-ingestion-scheduler --location=us-central1

# Trigger manually
gcloud scheduler jobs run canton-data-ingestion-scheduler --location=us-central1

# Pause job
gcloud scheduler jobs pause canton-data-ingestion-scheduler --location=us-central1

# Resume job
gcloud scheduler jobs resume canton-data-ingestion-scheduler --location=us-central1

# View execution history
gcloud logging read "resource.type=cloud_scheduler_job" --limit=20 --project=governence-483517
```

**Monitoring:**
```bash
# View Cloud Run logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion" \
    --limit=50 --project=governence-483517 --format="table(timestamp,textPayload)"

# Check for errors
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" \
    --limit=20 --project=governence-483517

# View SV node failover progress
gcloud logging read "resource.type=cloud_run_revision AND textPayload:\"Trying SV node\"" \
    --limit=30 --project=governence-483517
```

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Cloud          │     │  Cloud Run      │     │  BigQuery       │
│  Scheduler      │────▶│  Service        │────▶│  Tables         │
│  (every 15 min) │     │  (with VPC)     │     │                 │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  VPC Connector          │
                    │  (canton-connector)     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Cloud NAT              │
                    │  Static IP: 34.132.24.144│
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  SV Node 1      │  │  SV Node 2      │  │  SV Node 13     │
│  (sync.global)  │  │  (digitalasset) │  │  (sv-nodeops)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
              │                  │                  │
              └──────────────────┴──────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Canton Scan API        │
                    │  (/v0/events endpoint)  │
                    └─────────────────────────┘
```

## MainNet SV Node URLs (Failover List)

The pipeline automatically tries multiple Super Validator nodes until one succeeds:

| # | SV Name | URL |
|---|---------|-----|
| 1 | Global-Synchronizer-Foundation | https://scan.sv-1.global.canton.network.sync.global |
| 2 | Digital-Asset-1 | https://scan.sv-1.global.canton.network.digitalasset.com |
| 3 | Digital-Asset-2 | https://scan.sv-2.global.canton.network.digitalasset.com |
| 4 | Cumberland-1 | https://scan.sv-1.global.canton.network.cumberland.io |
| 5 | Cumberland-2 | https://scan.sv-2.global.canton.network.cumberland.io |
| 6 | Tradeweb-Markets-1 | https://scan.sv-1.global.canton.network.tradeweb.com |
| 7 | MPC-Holding-Inc | https://scan.sv-1.global.canton.network.mpch.io |
| 8 | Five-North-1 | https://scan.sv-1.global.canton.network.fivenorth.io |
| 9 | Proof-Group-1 | https://scan.sv-1.global.canton.network.proofgroup.xyz |
| 10 | C7-Technology-Services-Limited | https://scan.sv-1.global.canton.network.c7.digital |
| 11 | Liberty-City-Ventures-1 | https://scan.sv-1.global.canton.network.lcv.mpch.io |
| 12 | Orb-1-LP-1 | https://scan.sv-1.global.canton.network.orb1lp.mpch.io |
| 13 | SV-Nodeops-Limited | https://scan.sv.global.canton.network.sv-nodeops.com |

## Data Flow

1. **Cloud Scheduler** triggers the Cloud Run service every 15 minutes (with OIDC authentication)
2. **Cloud Run** routes traffic through VPC Connector → Cloud NAT (static IP)
3. **Cloud Run** tries SV nodes in order until one responds (10s timeout each)
4. **Cloud Run** queries BigQuery state table for last processed position
5. **Cloud Run** fetches new events from Scan API `/v0/events` endpoint (incremental)
6. **Cloud Run** inserts raw events into `raw.events` table via streaming API
7. **Cloud Run** updates `raw.ingestion_state` table with new position
8. **BigQuery Scheduled Query** transforms raw data to `transformed.events_parsed`

## Components

### 1. Data Ingestion Pipeline (`cloud_run/data_ingestion/data_ingestion_pipeline.py`)

Main orchestration module that:
- Fetches events from Canton Scan API using `/v0/events` endpoint
- Extracts individual events from transaction updates
- Maps API fields to BigQuery schema (e.g., `record_time` → `recorded_at`)
- Converts party arrays to BigQuery nested format `{list: [{element: "..."}]}`
- Inserts raw events into BigQuery via streaming API
- Updates state table for efficient incremental loading

### 2. Scan API Client (`cloud_run/data_ingestion/canton_scan_client.py`)

HTTP client with automatic failover:
- Tries 13 MainNet SV node URLs in sequence
- 10-second timeout per node for fast failover
- Caches working URL for subsequent requests
- Automatic retry with exponential backoff

### 3. BigQuery Client (`cloud_run/data_ingestion/bigquery_client.py`)

Handles all BigQuery operations:
- Get last processed position from state table (O(1) lookup)
- Fallback to MAX() query if state not found
- Insert raw events via streaming API
- Run transformation queries
- Check pipeline status

### 4. Cloud Run Service (`cloud_run/data_ingestion/main.py`)

Flask-based HTTP service with endpoints:
- `GET /`: Health check
- `POST /ingest`: Main ingestion endpoint (called by scheduler)
- `POST /transform`: Manual transformation trigger
- `GET /status`: Pipeline status check

### 5. Network Infrastructure

| Component | Configuration | Purpose |
|-----------|--------------|---------|
| VPC Connector | `canton-connector` | Routes Cloud Run traffic through VPC |
| Cloud Router | `canton-router` | Manages NAT routing |
| Cloud NAT | `canton-nat` | Provides static egress IP |
| Static IP | `34.132.24.144` | Whitelisted by SV node operators |

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

### Option 2: BigQuery Scheduled Queries (GCS-Based Pipeline) - RECOMMENDED

Two daily scheduled queries that load new events from GCS and transform them. This is the primary data pipeline.

**Query 1: `ingest_events_from_gcs`** (Daily at 00:00 UTC)
- Reads new parquet files from `gs://canton-bucket/raw/updates/events/` via external table
- Inserts into `raw.events` with dedup on `event_id + event_date`
- SQL: `bigquery_scheduled/ingest_events_from_gcs.sql`

**Query 2: `transform_raw_events`** (Daily at 01:00 UTC)
- Transforms `raw.events` → `transformed.events_parsed`
- Parses timestamps, flattens arrays, parses JSON fields
- SQL: `bigquery_scheduled/transform_events.sql`

**Setup via Console:**
1. Go to [BigQuery Console](https://console.cloud.google.com/bigquery?project=governence-483517)
2. Click "Scheduled queries" in the left menu
3. Click "Create scheduled query"
4. Paste contents of `bigquery_scheduled/ingest_events_from_gcs.sql`
5. Set schedule to daily at 00:00 UTC, location: US
6. Repeat for `bigquery_scheduled/transform_events.sql` at 01:00 UTC

### Option 3: Cloud Run (Containerized) - RECOMMENDED

Deploy as a containerized service on Cloud Run with VPC egress for IP whitelisting.

**Prerequisites:**
- Cloud Run API enabled
- Cloud Build API enabled
- Artifact Registry API enabled
- VPC Access API enabled
- Cloud NAT configured with static IP

**Network Setup (one-time):**
```bash
# Create VPC connector
gcloud compute networks vpc-access connectors create canton-connector \
    --region=us-central1 \
    --network=default \
    --range=10.8.0.0/28 \
    --project=governence-483517

# Create Cloud Router
gcloud compute routers create canton-router \
    --network=default \
    --region=us-central1 \
    --project=governence-483517

# Reserve static IP
gcloud compute addresses create canton-nat-ip \
    --region=us-central1 \
    --project=governence-483517

# Create Cloud NAT with static IP
gcloud compute routers nats create canton-nat \
    --router=canton-router \
    --region=us-central1 \
    --nat-external-ip-pool=canton-nat-ip \
    --nat-all-subnet-ip-ranges \
    --project=governence-483517

# Get the static IP (send to SV operators for whitelisting)
gcloud compute addresses describe canton-nat-ip \
    --region=us-central1 \
    --format='value(address)' \
    --project=governence-483517
```

**Deploy Cloud Run:**
```bash
cd cloud_run/data_ingestion
./deploy.sh
```

**Set up Cloud Scheduler with OIDC Authentication:**
```bash
# Create service account for scheduler
gcloud iam service-accounts create scheduler-invoker \
    --display-name="Cloud Scheduler Invoker" \
    --project=governence-483517

# Grant Cloud Run invoker role
gcloud run services add-iam-policy-binding canton-data-ingestion \
    --region=us-central1 \
    --member="serviceAccount:scheduler-invoker@governence-483517.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project=governence-483517

# Create scheduler job with OIDC authentication
gcloud scheduler jobs create http canton-data-ingestion-scheduler \
    --location=us-central1 \
    --schedule="*/15 * * * *" \
    --uri="https://canton-data-ingestion-224112423672.us-central1.run.app/ingest" \
    --http-method=POST \
    --time-zone="UTC" \
    --project=governence-483517 \
    --headers="Content-Type=application/json" \
    --message-body='{"max_pages": 100, "auto_transform": true}' \
    --oidc-service-account-email="scheduler-invoker@governence-483517.iam.gserviceaccount.com"
```

**Manual Trigger:**
```bash
gcloud scheduler jobs run canton-data-ingestion-scheduler --location=us-central1
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

Configure these environment variables for Cloud Run:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCAN_API_BASE_URL` | `https://scan.sv-1.global.canton.network.sync.global/api/scan/` | MainNet Scan API base URL |
| `SCAN_API_TIMEOUT` | `60` | API request timeout (seconds) |
| `SCAN_API_MAX_RETRIES` | `3` | Max retries per request |
| `BQ_PROJECT_ID` | `governence-483517` | BigQuery project ID |
| `BQ_RAW_DATASET` | `raw` | Raw events dataset |
| `BQ_TRANSFORMED_DATASET` | `transformed` | Transformed events dataset |
| `BQ_RAW_TABLE` | `events` | Raw events table name |
| `BQ_PARSED_TABLE` | `events_parsed` | Parsed events table name |
| `PAGE_SIZE` | `500` | Events per API call |
| `MAX_PAGES_PER_RUN` | `100` | Max pages per execution |
| `BATCH_SIZE` | `100` | BigQuery insert batch size |
| `AUTO_TRANSFORM` | `true` | Auto-run transformation |

**Note:** The pipeline automatically tries all 13 SV node URLs regardless of `SCAN_API_BASE_URL` when failover is enabled.

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

**POST /v0/events** (Primary endpoint for MainNet)

Request:
```json
{
    "page_size": 500,
    "daml_value_encoding": "compact_json",
    "after": {
        "after_migration_id": 4,
        "after_record_time": "2026-01-27T09:24:02.486Z"
    }
}
```

Response:
```json
{
    "events": [
        {
            "update": {
                "migration_id": 4,
                "record_time": "2026-01-27T09:24:03.000Z",
                "synchronizer_id": "...",
                "update_id": "...",
                "effective_at": "2026-01-27T09:24:03.000Z",
                "events_by_id": {
                    "event_id_1": {
                        "event_type": "created",
                        "contract_id": "...",
                        "template_id": "...",
                        "create_arguments": {...}
                    }
                }
            }
        }
    ]
}
```

**Note:** The `/v2/updates` endpoint is also available but `/v0/events` is recommended for MainNet.

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

---

## Data Quality Verification

An automated data quality suite runs against the BigQuery tables to detect issues early.

### Running Checks

```bash
# Run all checks (last 7 days)
python scripts/data_quality_checks.py

# Extended lookback
python scripts/data_quality_checks.py --days 14

# JSON output (for scripting)
python scripts/data_quality_checks.py --json

# Skip live API schema check (if no network access)
python scripts/data_quality_checks.py --skip-api-check
```

### Checks Performed

| Check | Description | Threshold |
|-------|-------------|-----------|
| **Row count validation** | Compares raw vs parsed row counts per partition | Warn if >5% difference |
| **Data freshness** | Checks latest partition age in both tables | Warn >36h, Critical >72h |
| **Timestamp consistency** | Detects future dates, null timestamps | Zero tolerance for future dates |
| **Duplicate detection** | Finds duplicate event_ids within a partition | Zero tolerance |
| **Null field checks** | Verifies critical fields (event_id, template_id, etc.) | Warn if >1% null |
| **Partition continuity** | Finds missing daily partitions in sequence | Any gap = Warning |
| **Schema drift detection** | Compares live API fields to expected schema | Any missing field = Warning |
| **Daily volume trend** | Compares today's rows to rolling N-day average | Drop >50% or spike >300% = Warning |

**Exit codes:** 0=OK, 1=Warning, 2=Critical

---

## Monitoring and Alerting

### Health Monitor

```bash
# Human-readable output
python scripts/monitor_pipeline.py

# JSON output
python scripts/monitor_pipeline.py --json

# Emit Cloud Logging alerts (for log-based metric triggers)
python scripts/monitor_pipeline.py --notify

# Extend lookback window
python scripts/monitor_pipeline.py --days 14
```

The monitor checks:
- Data freshness (both raw and parsed tables)
- Row count consistency between tables
- Ingestion state staleness (is the cursor being updated?)
- Daily volume trends (sudden drops or spikes)
- Scan API connectivity

When run with `--notify`, issues are emitted as structured JSON log entries at `ERROR`/`WARNING` severity. Cloud Logging captures these and triggers log-based metric alerts.

### Cloud Monitoring Alert Setup

```bash
# Set up all Cloud Monitoring alerts (one-time setup)
ALERT_EMAIL=your@email.com bash scripts/setup_monitoring_alerts.sh
```

This creates:
- **Log-based metric**: `canton_pipeline_errors` (ERROR logs from Cloud Run)
- **Log-based metric**: `canton_monitor_critical` (monitor issues)
- **Alert policy**: Pipeline errors trigger email notification
- **Alert policy**: Monitor critical/warning triggers email
- **Uptime check**: Cloud Run health endpoint checked every 5 minutes

### Cron Integration (for VM-based setups)

```bash
# Run monitor daily and emit alerts to Cloud Logging
0 8 * * * cd /path/to/canton && python scripts/monitor_pipeline.py --notify >> /var/log/canton/monitor.log 2>&1

# Run data quality checks weekly
0 9 * * 0 cd /path/to/canton && python scripts/data_quality_checks.py --days 7 --json >> /var/log/canton/quality.log 2>&1
```

---

## Next Steps

1. **IP Whitelisting**: Coordinate with SV operators to whitelist `34.132.24.144` for full MainNet coverage
2. **Historical GCS backfill**: Verify all historical parquet files are processed by the BigQuery scheduled query
3. **Analytics tables**: Build materialized views or aggregation tables for specific use cases
4. **Data retention policy**: Define and implement a BigQuery table expiration policy for `raw.events`
5. **Alerting integration**: Connect Cloud Monitoring alerts to PagerDuty or Slack if needed
