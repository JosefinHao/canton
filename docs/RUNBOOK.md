# Canton Data Pipeline — Runbook

**Last updated:** 2026-02-22

This runbook covers the most common failure scenarios for the Canton on-chain data pipeline, with step-by-step diagnosis and resolution steps.

---

## Table of Contents

1. [Quick Reference](#1-quick-reference)
2. [Scenario: API Connectivity Failure](#2-scenario-api-connectivity-failure)
3. [Scenario: Cloud Run Ingestion Failure](#3-scenario-cloud-run-ingestion-failure)
4. [Scenario: BigQuery Insert Errors](#4-scenario-bigquery-insert-errors)
5. [Scenario: Transformation Failure / Lag](#5-scenario-transformation-failure--lag)
6. [Scenario: Data Freshness SLA Breach](#6-scenario-data-freshness-sla-breach)
7. [Scenario: Schema Drift Detected](#7-scenario-schema-drift-detected)
8. [Scenario: Duplicate Events Detected](#8-scenario-duplicate-events-detected)
9. [Scenario: Pipeline State Corruption](#9-scenario-pipeline-state-corruption)
10. [Scenario: Cloud Scheduler Not Firing](#10-scenario-cloud-scheduler-not-firing)
11. [Scenario: BigQuery Scheduled Query Failures](#11-scenario-bigquery-scheduled-query-failures)
12. [Maintenance Procedures](#12-maintenance-procedures)

---

## 1. Quick Reference

### Health Check Commands

```bash
# Run pipeline health monitor
python scripts/monitor_pipeline.py

# Run comprehensive data quality checks
python scripts/data_quality_checks.py

# Check Cloud Run logs (last 50 entries)
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion" \
  --limit=50 --project=governence-483517 \
  --format="table(timestamp,severity,textPayload)"

# Check for ERROR logs specifically
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit=20 --project=governence-483517

# Check Cloud Scheduler job status
gcloud scheduler jobs describe canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Manually trigger ingestion
gcloud scheduler jobs run canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Check ingestion state in BigQuery
bq query --use_legacy_sql=false \
  "SELECT * FROM \`governence-483517.raw.ingestion_state\` ORDER BY table_name"
```

### Key GCP Resources

| Resource | Name | Region |
|----------|------|--------|
| Cloud Run Service | `canton-data-ingestion` | `us-central1` |
| Cloud Scheduler Job | `canton-data-ingestion-scheduler` | `us-central1` |
| VPC Connector | `canton-connector` | `us-central1` |
| Cloud NAT | `canton-nat` | `us-central1` |
| Static IP | `canton-nat-ip` → `34.132.24.144` | `us-central1` |
| BigQuery Dataset (raw) | `governence-483517.raw` | US |
| BigQuery Dataset (transformed) | `governence-483517.transformed` | US |
| GCS Bucket | `canton-bucket` | US |

### Key Tables

| Table | Purpose |
|-------|---------|
| `raw.events` | Raw events from Scan API (STRING fields) |
| `raw.ingestion_state` | Ingestion cursor tracking (fast O(1) lookup) |
| `raw.events_updates_external` | External table pointing at GCS parquet files |
| `transformed.events_parsed` | Type-cast events for analytics |

---

## 2. Scenario: API Connectivity Failure

**Symptoms:**
- Monitor shows `api_connectivity: CRITICAL`
- Cloud Run logs show repeated "All SV node URLs failed" entries
- No new events inserted (events_inserted=0 in run stats)

**Possible causes:**
- All SV nodes temporarily unreachable (rare network event)
- IP whitelisting issue (static IP `34.132.24.144` revoked by SV operators)
- Cloud NAT misconfiguration (traffic not routing through static IP)
- Cloud Run VPC connector issue

**Diagnosis steps:**

```bash
# Step 1: Check if any SV node is reachable from your workstation
curl -s -o /dev/null -w "%{http_code}" \
  https://scan.sv-1.global.canton.network.cumberland.io/api/scan/v0/dso

# Step 2: Check the static IP is still reserved and in-use
gcloud compute addresses describe canton-nat-ip \
  --region=us-central1 --project=governence-483517 \
  --format="table(address,status)"

# Step 3: Check VPC connector status
gcloud compute networks vpc-access connectors describe canton-connector \
  --region=us-central1 --project=governence-483517

# Step 4: Check Cloud NAT configuration
gcloud compute routers nats describe canton-nat \
  --router=canton-router --region=us-central1 --project=governence-483517

# Step 5: Check Cloud Run egress setting
gcloud run services describe canton-data-ingestion \
  --region=us-central1 --project=governence-483517 \
  --format="value(spec.template.metadata.annotations)"
```

**Resolution:**

- **If the static IP changed:** Notify SV node operators with the new IP for whitelisting.
- **If VPC connector is unhealthy:** Re-create the connector (`gcloud compute networks vpc-access connectors delete canton-connector --region=us-central1 && gcloud compute networks vpc-access connectors create ...`).
- **If it's a temporary SV node outage:** The pipeline will auto-recover at the next Cloud Scheduler trigger. Monitor logs for the next 30 minutes.
- **If all 13 nodes fail for >1 hour:** Contact SV node operators; check the [Canton Network status page](https://status.canton.network/).

---

## 3. Scenario: Cloud Run Ingestion Failure

**Symptoms:**
- Monitor shows `data_freshness` lag growing
- Cloud Run logs show non-200 responses from `/ingest` endpoint
- Cloud Scheduler shows "failed" execution history

**Possible causes:**
- Cloud Run service crashed / unhealthy container
- BigQuery credentials expired or missing
- Container out of memory (OOM)
- Request timeout (Cloud Run max 540s exceeded)

**Diagnosis steps:**

```bash
# Step 1: Check Cloud Run service health
curl -s https://canton-data-ingestion-224112423672.us-central1.run.app/ | jq .

# Step 2: Check recent revisions
gcloud run revisions list --service=canton-data-ingestion \
  --region=us-central1 --project=governence-483517

# Step 3: Check for OOM or crash logs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion \
   AND (textPayload:\"Memory limit\" OR textPayload:\"SIGKILL\" OR severity=CRITICAL)" \
  --limit=20 --project=governence-483517

# Step 4: Check pipeline status endpoint
curl -s https://canton-data-ingestion-224112423672.us-central1.run.app/status | jq .
```

**Resolution:**

- **If OOM:** Increase Cloud Run memory limit:
  ```bash
  gcloud run services update canton-data-ingestion \
    --memory=1Gi --region=us-central1 --project=governence-483517
  ```
- **If timeout:** Reduce `MAX_PAGES_PER_RUN` (each page fetches ~500 events). Update env var:
  ```bash
  gcloud run services update canton-data-ingestion \
    --set-env-vars="MAX_PAGES_PER_RUN=50" \
    --region=us-central1 --project=governence-483517
  ```
- **If credentials issue:** Check the Cloud Run service account has `roles/bigquery.dataEditor` on both datasets.
- **If service is unhealthy:** Redeploy:
  ```bash
  cd cloud_run/data_ingestion && ./deploy.sh
  ```

---

## 4. Scenario: BigQuery Insert Errors

**Symptoms:**
- Cloud Run logs show `insert_failures > 0` in pipeline stats
- `data_quality_checks.py --days 1` shows row count discrepancy
- Log entries containing "BigQuery streaming insert failed"

**Possible causes:**
- Schema mismatch between pipeline code and BigQuery table schema
- Streaming buffer quota exceeded
- Rows exceeding BigQuery row size limit (10 MB)

**Diagnosis steps:**

```bash
# Step 1: Check pipeline stats from last run
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion \
   AND jsonPayload.statistics.insert_failures>0" \
  --limit=10 --project=governence-483517

# Step 2: Check BigQuery table schema
bq show --format=prettyjson governence-483517:raw.events | jq '.schema.fields'

# Step 3: Manually trigger a small test run
curl -X POST https://canton-data-ingestion-224112423672.us-central1.run.app/ingest \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 1, "auto_transform": false}'
```

**Resolution:**

- **If schema mismatch:** Compare the schema in `cloud_run/data_ingestion/data_ingestion_pipeline.py` `_extract_events_from_updates()` against the BigQuery table schema. Update whichever is wrong.
- **If quota issue:** Wait for the streaming buffer to drain (usually <24h) or use `LOAD` jobs instead of streaming.
- **If row too large:** Inspect `raw_event` field (full JSON). Consider truncating or compressing.

---

## 5. Scenario: Transformation Failure / Lag

**Symptoms:**
- `data_quality_checks.py` shows row count difference between raw and parsed
- `transformed.events_parsed` partition is older than `raw.events`
- BigQuery scheduled query `Canton: transform_raw_events` shows failures

**Possible causes:**
- Timestamp parsing failure (`SAFE.PARSE_TIMESTAMP` returns NULL for unexpected format)
- BigQuery concurrent DML limit exceeded
- Scheduled query ran but found no new data (normal if run within 1-day window)

**Diagnosis steps:**

```bash
# Step 1: Check scheduled query history
bq ls --transfer_config --transfer_location=US --project_id=governence-483517

# Step 2: Check for NULL timestamps after transformation
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as null_recorded_at
   FROM \`governence-483517.transformed.events_parsed\`
   WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
     AND recorded_at IS NULL"

# Step 3: Manually trigger transformation via Cloud Run
curl -X POST https://canton-data-ingestion-224112423672.us-central1.run.app/transform

# Step 4: Check untransformed row count
bq query --use_legacy_sql=false \
  "SELECT r.event_date, COUNT(*) as untransformed
   FROM \`governence-483517.raw.events\` r
   WHERE r.event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
     AND NOT EXISTS (
       SELECT 1 FROM \`governence-483517.transformed.events_parsed\` p
       WHERE p.event_id = r.event_id AND p.event_date = r.event_date
     )
   GROUP BY r.event_date ORDER BY r.event_date DESC"
```

**Resolution:**

- **If timestamp format changed:** Update the `SAFE.PARSE_TIMESTAMP` format string in `bigquery_scheduled/transform_events.sql` and in `cloud_run/data_ingestion/bigquery_client.py` `run_transformation_query()`.
- **If scheduled query is disabled:** Re-enable in BigQuery Console → Scheduled queries.
- **For large backlog:** Run transformation via Cloud Run (which handles incremental transform) or run the SQL manually in BigQuery Console for specific date ranges.
- **For manual backfill of a specific date range:**
  ```sql
  -- Run in BigQuery Console for a specific missed partition
  INSERT INTO `governence-483517.transformed.events_parsed` (...)
  SELECT ... FROM `governence-483517.raw.events` r
  WHERE r.event_date = '2026-01-15'
    AND NOT EXISTS (
      SELECT 1 FROM `governence-483517.transformed.events_parsed` p
      WHERE p.event_id = r.event_id AND p.event_date = r.event_date
    );
  ```

---

## 6. Scenario: Data Freshness SLA Breach

**Symptoms:**
- Monitor shows `data_freshness: CRITICAL` (lag > 72h)
- Alert email received for `Canton: Pipeline Monitor Critical`

**Resolution sequence:**

```bash
# Step 1: Confirm the lag
python scripts/monitor_pipeline.py

# Step 2: Check if Cloud Scheduler has been running
gcloud logging read \
  "resource.type=cloud_scheduler_job" \
  --limit=20 --project=governence-483517 \
  --format="table(timestamp,textPayload)"

# Step 3: Check if the scheduler job is paused
gcloud scheduler jobs describe canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517 \
  --format="value(state)"

# Step 4: Resume if paused
gcloud scheduler jobs resume canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Step 5: Manually trigger immediate ingestion run
gcloud scheduler jobs run canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Step 6: Monitor logs to confirm recovery
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion" \
  --limit=30 --project=governence-483517 --freshness=10m \
  --format="table(timestamp,severity,textPayload)"
```

**After recovery:** Verify the state table is updated and both raw and parsed tables have recent partitions:
```bash
python scripts/monitor_pipeline.py
python scripts/data_quality_checks.py --days 3
```

---

## 7. Scenario: Schema Drift Detected

**Symptoms:**
- `data_quality_checks.py` reports `schema_drift: WARNING`
- New fields in API response not captured in BigQuery
- Or existing expected fields missing from API response

**Diagnosis:**

```bash
# Run schema drift check
python scripts/data_quality_checks.py --days 1

# Manually inspect API response
curl -s -X POST \
  https://scan.sv-1.global.canton.network.cumberland.io/api/scan/v2/updates \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"page_size": 1, "daml_value_encoding": "compact_json"}' | jq '.updates[0] | keys'
```

**Resolution:**

**Case A — New field added to API (non-breaking):**
- The new field is not captured in `raw.events`. Decide whether it's needed for analytics.
- If needed: Add the field to `_extract_events_from_updates()` in both `cloud_run/data_ingestion/data_ingestion_pipeline.py` and `src/data_ingestion_pipeline.py`, add a new column to the BigQuery table schema (`ALTER TABLE ... ADD COLUMN`), and update the transform SQL.

**Case B — Existing field renamed or removed (breaking):**
- Do NOT deploy immediately. Investigate the Splice API changelog.
- Update the mapping in `_extract_events_from_updates()` to handle both old and new field names during the transition.
- Test with `--max_pages=1` before deploying the full pipeline.

**Case C — Timestamp format changed:**
- Update `SAFE.PARSE_TIMESTAMP` format strings in both `transform_events.sql` and `bigquery_client.py`.

---

## 8. Scenario: Duplicate Events Detected

**Symptoms:**
- `data_quality_checks.py` reports `duplicate_events: CRITICAL`
- Row count in `raw.events` significantly higher than expected

**Cause analysis:**

Duplicates should be prevented by the `NOT EXISTS` dedup clause in the GCS ingestion query and by the `raw.ingestion_state` cursor for the Cloud Run pipeline. Duplicates usually indicate:
- A cursor reset (ingestion_state table was truncated or reset)
- A bug in the dedup logic for a specific partition
- Concurrent pipeline runs (multiple Cloud Run instances writing simultaneously)

**Diagnosis:**

```bash
# Find duplicate event_ids
bq query --use_legacy_sql=false \
  "SELECT event_date, event_id, COUNT(*) as cnt
   FROM \`governence-483517.raw.events\`
   WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY event_date, event_id
   HAVING cnt > 1
   ORDER BY event_date DESC, cnt DESC
   LIMIT 20"

# Check ingestion state
bq query --use_legacy_sql=false \
  "SELECT * FROM \`governence-483517.raw.ingestion_state\`"
```

**Resolution:**

```sql
-- Step 1: Identify the affected partitions and count extra rows
SELECT event_date, COUNT(*) - COUNT(DISTINCT event_id) AS extra_rows
FROM `governence-483517.raw.events`
WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY event_date
HAVING extra_rows > 0;

-- Step 2: Deduplicate using DML (run in BigQuery Console)
-- WARNING: This is a destructive operation. Create a backup partition first.
MERGE `governence-483517.raw.events` T
USING (
  SELECT * EXCEPT(row_num)
  FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id, event_date ORDER BY recorded_at) AS row_num
    FROM `governence-483517.raw.events`
    WHERE event_date = '2026-01-15'  -- Replace with affected date
  )
  WHERE row_num = 1
) S
ON T.event_id = S.event_id AND T.event_date = S.event_date
WHEN NOT MATCHED BY SOURCE AND T.event_date = '2026-01-15' THEN DELETE;
```

After deduplication, re-run transformation for affected partitions (see Scenario 5).

---

## 9. Scenario: Pipeline State Corruption

**Symptoms:**
- Pipeline suddenly re-ingesting historical data from migration_id=0 or very early cursor
- Large spike in raw.events row count
- `ingestion_state` table shows unexpected values

**Cause:** The `raw.ingestion_state` table was accidentally truncated or set to wrong values.

**Resolution:**

```bash
# Step 1: Pause Cloud Scheduler immediately to stop ingestion
gcloud scheduler jobs pause canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Step 2: Check what is in the state table
bq query --use_legacy_sql=false \
  "SELECT * FROM \`governence-483517.raw.ingestion_state\`"

# Step 3: Find the actual last position from raw.events
bq query --use_legacy_sql=false \
  "SELECT MAX(migration_id) AS max_migration_id,
          MAX(recorded_at) AS max_recorded_at
   FROM \`governence-483517.raw.events\`
   WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"

# Step 4: Correct the state table with the right position
# Replace VALUES with the output from Step 3
bq query --use_legacy_sql=false \
  "MERGE \`governence-483517.raw.ingestion_state\` T
   USING (SELECT 'raw_events' AS table_name) S
   ON T.table_name = S.table_name
   WHEN MATCHED THEN
     UPDATE SET migration_id = <MAX_MIGRATION_ID>,
                recorded_at  = '<MAX_RECORDED_AT>',
                updated_at   = CURRENT_TIMESTAMP()
   WHEN NOT MATCHED THEN
     INSERT (table_name, migration_id, recorded_at, updated_at)
     VALUES ('raw_events', <MAX_MIGRATION_ID>, '<MAX_RECORDED_AT>', CURRENT_TIMESTAMP())"

# Step 5: Verify the state is correct
bq query --use_legacy_sql=false \
  "SELECT * FROM \`governence-483517.raw.ingestion_state\`"

# Step 6: Resume Cloud Scheduler
gcloud scheduler jobs resume canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517
```

---

## 10. Scenario: Cloud Scheduler Not Firing

**Symptoms:**
- Data freshness lag growing steadily
- No Cloud Run invocations visible in the last N hours
- Cloud Scheduler execution history shows no recent entries

**Diagnosis steps:**

```bash
# Step 1: Check scheduler job status
gcloud scheduler jobs describe canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Step 2: Check scheduler execution logs
gcloud logging read \
  "resource.type=cloud_scheduler_job \
   AND resource.labels.job_id=canton-data-ingestion-scheduler" \
  --limit=20 --project=governence-483517

# Step 3: List all scheduler jobs
gcloud scheduler jobs list --location=us-central1 --project=governence-483517

# Step 4: Manually trigger
gcloud scheduler jobs run canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517
```

**Resolution:**

- **If job is paused:** Resume with `gcloud scheduler jobs resume ...`
- **If OIDC auth is failing:** Verify the service account `scheduler-invoker@governence-483517.iam.gserviceaccount.com` still has `roles/run.invoker` on the Cloud Run service.
  ```bash
  gcloud run services get-iam-policy canton-data-ingestion \
    --region=us-central1 --project=governence-483517
  ```
- **If the Cloud Run URL changed:** Update the scheduler job target URL:
  ```bash
  gcloud scheduler jobs update http canton-data-ingestion-scheduler \
    --uri="<NEW_URL>/ingest" \
    --location=us-central1 --project=governence-483517
  ```
- **If Cloud Scheduler API is disabled:** `gcloud services enable cloudscheduler.googleapis.com`

---

## 11. Scenario: BigQuery Scheduled Query Failures

**Symptoms:**
- `raw.events` not populated from GCS files
- `transformed.events_parsed` not updated daily by the scheduled query
- BigQuery Console shows failed scheduled query runs

**Diagnosis:**

```bash
# Check scheduled query transfer configs
bq ls --transfer_config \
  --transfer_location=US \
  --project_id=governence-483517

# View recent run history for a transfer config
# Replace <TRANSFER_CONFIG_ID> with the ID from the above command
bq ls --transfer_run \
  --transfer_location=US \
  --run_attempt=LATEST \
  /projects/governence-483517/locations/US/transferConfigs/<TRANSFER_CONFIG_ID>

# Check if the external table exists
bq show governence-483517:raw.events_updates_external
```

**Resolution:**

- **If external table is missing:** The GCS-based ingestion query requires `raw.events_updates_external` (an external table pointing at `gs://canton-bucket/raw/updates/events/*`). Re-create it:
  ```bash
  bq mk --table \
    --external_table_definition=parquet=gs://canton-bucket/raw/updates/events/* \
    governence-483517:raw.events_updates_external
  ```
- **If scheduled query is disabled:** Re-enable in BigQuery Console → Scheduled queries → Select query → Enable.
- **If query failed due to SQL error:** Check the error message in the run history, fix the SQL in the corresponding file, and re-create the scheduled query with `setup_scheduled_query.sh`.
- **If no new GCS files:** The Cloud Run pipeline writes directly to BigQuery, not to GCS. The GCS-based ingestion query is only for historical bulk-loaded data. If no new GCS files are arriving, this query will have nothing to insert (which is expected behavior once historical backfill is complete).

---

## 12. Maintenance Procedures

### Checking Pipeline Health (Daily)

```bash
# Quick health check
python scripts/monitor_pipeline.py

# Full data quality check (run weekly or after incidents)
python scripts/data_quality_checks.py --days 7

# JSON output for scripting
python scripts/monitor_pipeline.py --json | jq .overall_status
```

### Manually Triggering a Pipeline Run

```bash
# Via Cloud Scheduler (preferred - uses OIDC auth)
gcloud scheduler jobs run canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Via direct HTTP (requires auth token)
TOKEN=$(gcloud auth print-identity-token)
curl -X POST https://canton-data-ingestion-224112423672.us-central1.run.app/ingest \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 100, "auto_transform": true}'

# Via standalone Python script (requires GOOGLE_APPLICATION_CREDENTIALS)
python scripts/run_ingestion.py --max-pages 100

# Check status after run
python scripts/run_ingestion.py --status
```

### Pausing and Resuming the Pipeline

```bash
# Pause (stops automatic ingestion)
gcloud scheduler jobs pause canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517

# Resume
gcloud scheduler jobs resume canton-data-ingestion-scheduler \
  --location=us-central1 --project=governence-483517
```

### Checking SV Node Availability

```bash
# Quick check — try several nodes
for node in \
  "scan.sv-1.global.canton.network.cumberland.io" \
  "scan.sv-2.global.canton.network.cumberland.io" \
  "scan.sv-1.global.canton.network.proofgroup.xyz" \
  "scan.sv-1.global.canton.network.digitalasset.com" \
  "scan.sv-1.global.canton.network.sync.global"; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    "https://${node}/api/scan/v0/dso")
  echo "${node}: HTTP ${STATUS}"
done
```

### Resetting the Ingestion State (Last Resort)

Use this only if the pipeline is ingesting from the wrong position and you have confirmed the correct position from `raw.events`:

```sql
-- Find correct position (run in BigQuery Console)
SELECT migration_id, MAX(recorded_at) AS max_recorded_at
FROM `governence-483517.raw.events`
WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY migration_id
ORDER BY migration_id DESC
LIMIT 1;
```

Then update the state table as shown in [Scenario 9](#9-scenario-pipeline-state-corruption).

### Updating Cloud Run Environment Variables

```bash
gcloud run services update canton-data-ingestion \
  --region=us-central1 \
  --project=governence-483517 \
  --set-env-vars="PAGE_SIZE=500,MAX_PAGES_PER_RUN=100,AUTO_TRANSFORM=true"
```

### Cost Management

| Action | Command |
|--------|---------|
| Check BigQuery slot usage | BigQuery Console → Monitoring → Job history |
| Reduce transformation frequency | Set `AUTO_TRANSFORM=false` and rely on daily BQ scheduled query |
| Reduce Cloud Run invocations | Change scheduler to `*/30 * * * *` (every 30 min) |
| Pause GCS scheduled query | BigQuery Console → Scheduled queries → Disable |
