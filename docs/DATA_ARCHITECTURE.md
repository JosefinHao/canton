# Canton On-Chain Data — Architecture Overview

**Last updated:** 2026-02-22

This document describes the complete data architecture for the Canton on-chain data platform, from raw blockchain event ingestion through transformation to analytics-ready tables.

---

## System Architecture Diagram

```
═══════════════════════════════════════════════════════════════════════════
                        CANTON ON-CHAIN DATA PLATFORM
═══════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────┐
  │                     CANTON MAINNET (SV NODES)                       │
  │                                                                     │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────┐ │
  │  │ Cumberland-1 │  │ Proof Group  │  │ DigitalAsset │  │ ... +9 │ │
  │  │ (primary)    │  │              │  │              │  │        │ │
  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └───┬────┘ │
  │         └─────────────────┴──────────────────┴──────────────┘      │
  │                           Canton Scan API                           │
  │                     /v2/updates  /v0/events                        │
  └────────────────────────────────┬────────────────────────────────────┘
                                   │  HTTPS  (IP: 34.132.24.144)
                                   │
  ═══════════════════════════════════════════════════════════════════════
                    PRIMARY INGESTION PIPELINE (GCS → BigQuery)
  ═══════════════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────────────────────────────────┐
  │             GCS: gs://canton-bucket/raw/updates/events/          │
  │                         (parquet files)                          │
  └──────────────────────────┬───────────────────────────────────────┘
                             │
                    External Table: raw.events_updates_external
                             │
  ┌──────────────────────────▼───────────────────────────────────────┐
  │  BigQuery Scheduled Query: Canton: ingest_events_from_gcs        │
  │  Schedule: Daily at 00:00 UTC                                    │
  │  SQL: bigquery_scheduled/ingest_events_from_gcs.sql              │
  │                                                                  │
  │  Logic:                                                          │
  │  - Scans yesterday's GCS external table partition                │
  │  - NOT EXISTS dedup on (event_id, event_date)                    │
  │  - Inserts only truly new rows into raw.events                   │
  └──────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
                    (same raw.events table below)

  ═══════════════════════════════════════════════════════════════════════
                  BACKUP PIPELINE (Scan API → Cloud Run)
  ═══════════════════════════════════════════════════════════════════════

  ┌─────────────────┐      ┌─────────────────────────────────────────┐
  │ Cloud Scheduler │      │              Cloud Run                  │
  │                 │      │         canton-data-ingestion           │
  │ */15 * * * *    │─────▶│                                         │
  │ (OIDC auth)     │ POST │  ┌──────────────────────────────────┐  │
  │                 │ /ingest│  │     SpliceScanClient             │  │
  └─────────────────┘      │  │   (13-node failover, 10s timeout) │  │
                           │  └──────────────────────────────────┘  │
                           │  ┌──────────────────────────────────┐  │
                           │  │   DataIngestionPipeline           │  │
                           │  │   - /v2/updates endpoint          │  │
                           │  │   - 500 events/page               │  │
                           │  │   - cursor: (migration_id,        │  │
                           │  │             recorded_at)          │  │
                           │  │   - max 100 pages/run             │  │
                           │  └──────────────────────────────────┘  │
                           │  ┌──────────────────────────────────┐  │
                           │  │   BigQueryClient                  │  │
                           │  │   - Streaming insert to raw.events│  │
                           │  │   - Update ingestion_state table  │  │
                           │  │   - Auto-transform if new data    │  │
                           │  └──────────────────────────────────┘  │
                           └────────────┬────────────────────────────┘
                                        │
                           ┌────────────┘
                           │
                    VPC Connector → Cloud NAT → Static IP 34.132.24.144
                    (traffic to Scan API exits via static IP for whitelisting)

  ═══════════════════════════════════════════════════════════════════════
                           BIGQUERY DATA LAYER
  ═══════════════════════════════════════════════════════════════════════

  ┌───────────────────────────────────────────────────────────────────┐
  │  Dataset: governence-483517.raw                                   │
  │                                                                   │
  │  ┌─────────────────────────────────────────────────────────────┐ │
  │  │  Table: raw.events                                          │ │
  │  │  - ~3.6B+ rows (growing ~daily)                             │ │
  │  │  - Partitioned by event_date (DATE)                         │ │
  │  │  - ALL fields stored as STRING for flexibility              │ │
  │  │  - Party arrays as nested STRUCT {list: [{element}]}        │ │
  │  │  - JSON fields (payload, raw_event) as STRING               │ │
  │  └─────────────────────────────────────────────────────────────┘ │
  │                                                                   │
  │  ┌─────────────────────────────────────────────────────────────┐ │
  │  │  Table: raw.ingestion_state                                 │ │
  │  │  - Tracks ingestion cursor (O(1) position lookup)           │ │
  │  │  - Rows: raw_events, parsed_events                          │ │
  │  │  - Fields: table_name, migration_id, recorded_at, updated_at│ │
  │  └─────────────────────────────────────────────────────────────┘ │
  │                                                                   │
  │  ┌─────────────────────────────────────────────────────────────┐ │
  │  │  External Table: raw.events_updates_external                │ │
  │  │  - Points to: gs://canton-bucket/raw/updates/events/*       │ │
  │  │  - Format: Parquet                                          │ │
  │  │  - Used by: ingest_events_from_gcs scheduled query          │ │
  │  └─────────────────────────────────────────────────────────────┘ │
  └───────────────────────────────────────────────────────────────────┘
                                   │
                                   │ Daily at 01:00 UTC
                                   │ BigQuery Scheduled Query:
                                   │ Canton: transform_raw_events
                                   │ SQL: transform_events.sql
                                   │
                                   ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │  Dataset: governence-483517.transformed                           │
  │                                                                   │
  │  ┌─────────────────────────────────────────────────────────────┐ │
  │  │  Table: transformed.events_parsed                           │ │
  │  │  - Type-cast version of raw.events                          │ │
  │  │  - Partitioned by event_date (DATE)                         │ │
  │  │  - Clustered by: template_id, event_type, migration_id      │ │
  │  │  - Timestamps: TIMESTAMP type (parsed from ISO 8601 strings)│ │
  │  │  - Party arrays: ARRAY<STRING> (flattened from nested struct)│ │
  │  │  - JSON fields: JSON type (parsed from STRING)              │ │
  │  │  - NOT EXISTS dedup on (event_id, event_date)               │ │
  │  └─────────────────────────────────────────────────────────────┘ │
  └───────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │                     ANALYTICS LAYER                               │
  │                                                                   │
  │  Analytics scripts, BigQuery queries, dashboards                  │
  │  - Validator rewards analysis (src/validator_rewards_analyzer.py) │
  │  - Featured app rewards analysis                                  │
  │  - Mining round analysis                                          │
  │  - Network health monitoring                                      │
  └───────────────────────────────────────────────────────────────────┘

  ═══════════════════════════════════════════════════════════════════════
                       MONITORING & ALERTING LAYER
  ═══════════════════════════════════════════════════════════════════════

  ┌─────────────────────────┐    ┌──────────────────────────────────┐
  │ scripts/monitor_        │    │ scripts/data_quality_checks.py   │
  │ pipeline.py             │    │                                  │
  │ --notify flag           │    │ - Row count validation           │
  │                         │    │ - Data freshness                 │
  │ Checks:                 │    │ - Timestamp consistency          │
  │ - Freshness lag         │    │ - Duplicate detection            │
  │ - Row consistency       │    │ - Null field checks              │
  │ - Volume trends         │    │ - Partition continuity           │
  │ - API connectivity      │    │ - Schema drift detection         │
  │ - Ingestion state       │    │ - Daily volume trends            │
  └──────────┬──────────────┘    └──────────────────────────────────┘
             │ JSON log (severity=ERROR/WARNING)
             ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                  Google Cloud Logging                           │
  │                                                                 │
  │  Log-based metrics:                                             │
  │  - canton_pipeline_errors (Cloud Run ERROR logs)               │
  │  - canton_monitor_critical (monitor WARNING/CRITICAL)          │
  └──────────────────────┬──────────────────────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │              Google Cloud Monitoring                            │
  │                                                                 │
  │  Alert policies:                                                │
  │  - Canton: Pipeline Errors (Cloud Run) → email                 │
  │  - Canton: Pipeline Monitor Critical → email                   │
  │  - Uptime check: Cloud Run health endpoint (every 5 min)       │
  └─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Summary

| Step | Source | Destination | Trigger | Frequency | Role |
|------|--------|-------------|---------|-----------|------|
| 1. GCS ingest (primary) | `gs://canton-bucket/raw/updates/events/*` | `raw.events` (INSERT) | BigQuery Scheduled Query | Daily 00:00 UTC | **PRIMARY** |
| 2. Transformation | `raw.events` | `transformed.events_parsed` (INSERT) | BQ Scheduled Query | Daily 01:00 UTC | Primary |
| 3. Live ingest (backup) | Canton Scan API `/v2/updates` | `raw.events` (streaming insert) | Cloud Scheduler | Every 15 min | **BACKUP** |
| 4. Quality check | `raw.events` + `transformed.events_parsed` + Scan API | Report/alerts | Manual or cron | On demand / daily | Ops |
| 5. Monitoring | `raw.events` + `transformed.events_parsed` + Cloud Run logs | Cloud Monitoring alerts | Cron / manual | Daily | Ops |

---

## Network Architecture

```
Cloud Run (canton-data-ingestion)
         │
         │ All egress traffic
         ▼
VPC Connector (canton-connector)
  Network: default  IP Range: 10.8.0.0/28  Region: us-central1
         │
         ▼
Cloud Router (canton-router)
  Network: default  Region: us-central1
         │
         ▼
Cloud NAT (canton-nat)
  Source: All subnets  IP pool: canton-nat-ip (manual)
         │
         ▼
Static IP: 34.132.24.144  (whitelisted by SV node operators)
         │
         ▼
Internet → Canton MainNet SV Nodes
```

---

## BigQuery Table Schemas

### raw.events

| Column | Type | Mode | Description |
|--------|------|------|-------------|
| event_id | STRING | NULLABLE | Unique event identifier |
| update_id | STRING | NULLABLE | Transaction/update identifier |
| event_type | STRING | NULLABLE | Derived type: created / exercised / archived / unknown |
| event_type_original | STRING | NULLABLE | Raw event_type from API |
| synchronizer_id | STRING | NULLABLE | Canton synchronizer domain ID |
| effective_at | STRING | NULLABLE | Event effective timestamp (ISO 8601 string) |
| recorded_at | STRING | NULLABLE | Event record timestamp (ISO 8601 string) — used as cursor |
| timestamp | STRING | NULLABLE | Alias of recorded_at |
| created_at_ts | STRING | NULLABLE | Alias of effective_at |
| contract_id | STRING | NULLABLE | Daml contract ID |
| template_id | STRING | NULLABLE | Daml template identifier |
| package_name | STRING | NULLABLE | Daml package name |
| migration_id | STRING | NULLABLE | Canton migration epoch |
| signatories | RECORD | REPEATED | Signatory parties (nested: list[].element) |
| observers | RECORD | REPEATED | Observer parties (nested: list[].element) |
| acting_parties | RECORD | REPEATED | Acting parties (nested: list[].element) |
| witness_parties | RECORD | REPEATED | Witness parties (nested: list[].element) |
| child_event_ids | RECORD | REPEATED | Child event IDs (nested: list[].element) |
| choice | STRING | NULLABLE | Exercised choice name |
| interface_id | STRING | NULLABLE | Interface template ID (if exercised via interface) |
| consuming | STRING | NULLABLE | Whether exercise is consuming (STRING "true"/"false") |
| reassignment_counter | STRING | NULLABLE | Reassignment counter |
| source_synchronizer | STRING | NULLABLE | Source synchronizer (for reassignments) |
| target_synchronizer | STRING | NULLABLE | Target synchronizer (for reassignments) |
| unassign_id | STRING | NULLABLE | Unassignment ID |
| submitter | STRING | NULLABLE | Submitting party |
| payload | STRING | NULLABLE | JSON string: create_arguments or choice_argument |
| contract_key | STRING | NULLABLE | JSON string: contract key |
| exercise_result | STRING | NULLABLE | JSON string: exercise result |
| raw_event | STRING | NULLABLE | Full raw event JSON |
| trace_context | STRING | NULLABLE | Trace context JSON |
| year | INTEGER | NULLABLE | Year component of event_date |
| month | INTEGER | NULLABLE | Month component of event_date |
| day | INTEGER | NULLABLE | Day component of event_date |
| event_date | DATE | NULLABLE | Partition column |

### transformed.events_parsed

Same columns as `raw.events` but with proper types:
- `effective_at`, `recorded_at`, `timestamp`, `created_at_ts` → **TIMESTAMP**
- `migration_id` → **INT64**
- `consuming` → **BOOL**
- `signatories`, `observers`, `acting_parties`, `witness_parties`, `child_event_ids` → **ARRAY\<STRING\>** (flattened)
- `payload`, `contract_key`, `exercise_result`, `raw_event`, `trace_context` → **JSON**

---

## Key Design Decisions

### Why two ingestion pipelines?

The **GCS BigQuery scheduled query is the primary pipeline**: parquet files land in GCS and are bulk-loaded daily via scheduled query — reliable, cost-efficient, and independent of API availability. The initial historical migration (3.6B+ rows) was performed via this path.

The **Cloud Run pipeline is the backup**: it polls the Canton Scan API every 15 minutes to provide near-real-time supplemental ingestion when GCS delivery is delayed or for catching up between daily GCS loads. It requires IP whitelisting by SV node operators and depends on API availability. Both are kept active because:
1. The GCS pipeline provides reliable daily bulk ingestion without API dependencies.
2. The Cloud Run pipeline ensures near-real-time data availability as a supplement and fallback.

### Why use STRING for all raw.events fields?

Maximum schema flexibility. If the API adds a new field or changes a value format, no BigQuery schema changes are required — everything lands in `raw.events` as-is. Type conversion is deferred to the transformation step, where `SAFE.PARSE_TIMESTAMP` and `SAFE_CAST` handle failures gracefully.

### Why an ingestion_state table?

`raw.events` has 3.6B+ rows. Finding the last ingested position via `MAX(recorded_at)` would scan 10+ TB on every pipeline run. The `ingestion_state` table reduces this to an O(1) point lookup — a single row read.

### Why partition by event_date rather than recorded_at?

BigQuery partition pruning on DATE columns is efficient and human-readable. Using `event_date` (derived from `recorded_at`) allows queries to be scoped to specific days without scanning the full table.

### Why cluster by template_id, event_type, migration_id?

Analytics queries almost always filter on one or more of these. Clustering reduces bytes scanned significantly for common query patterns like "all ValidatorRewardCoupon events in this migration epoch."

---

## Ingestion Cursor Logic

The pipeline tracks position as `(migration_id, recorded_at)`:

```
1. Read position from raw.ingestion_state (O(1))
2. If not found, fallback: MAX(migration_id) from recent partitions
3. Call Scan API: POST /v2/updates { "after": { "after_migration_id": N, "after_record_time": T } }
4. Insert events into raw.events
5. Update raw.ingestion_state with the new max (migration_id, recorded_at)
```

This ensures:
- **No gaps**: Cursor advances only after successful insert
- **No expensive scans**: State table lookup is always O(1)
- **Recovery after downtime**: Pipeline resumes from the last committed cursor

---

## MainNet SV Node URLs (Failover Order)

The pipeline tries these in order, using a 10-second timeout per node:

| Priority | SV Name | URL |
|----------|---------|-----|
| 1 | Cumberland-1 | https://scan.sv-1.global.canton.network.cumberland.io |
| 2 | Cumberland-2 | https://scan.sv-2.global.canton.network.cumberland.io |
| 3 | Proof-Group-1 | https://scan.sv-1.global.canton.network.proofgroup.xyz |
| 4 | Tradeweb-Markets-1 | https://scan.sv-1.global.canton.network.tradeweb.com |
| 5 | Digital-Asset-1 | https://scan.sv-1.global.canton.network.digitalasset.com |
| 6 | Digital-Asset-2 | https://scan.sv-2.global.canton.network.digitalasset.com |
| 7 | SV-Nodeops-Limited | https://scan.sv.global.canton.network.sv-nodeops.com |
| 8 | Five-North-1 | https://scan.sv-1.global.canton.network.fivenorth.io |
| 9 | MPC-Holding-Inc | https://scan.sv-1.global.canton.network.mpch.io |
| 10 | Liberty-City-Ventures | https://scan.sv-1.global.canton.network.lcv.mpch.io |
| 11 | Orb-1-LP-1 | https://scan.sv-1.global.canton.network.orb1lp.mpch.io |
| 12 | Global-Sync-Foundation | https://scan.sv-1.global.canton.network.sync.global |
| 13 | C7-Technology | https://scan.sv-1.global.canton.network.c7.digital |

A working URL is cached per Cloud Run instance for subsequent requests.

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [DATA_INGESTION_PIPELINE.md](DATA_INGESTION_PIPELINE.md) | Deployment guide and operational details |
| [RUNBOOK.md](RUNBOOK.md) | Failure scenarios and resolution steps |
| [API_REFERENCE.md](API_REFERENCE.md) | Scan API endpoint reference |
| [TRANSACTION_TYPES.md](TRANSACTION_TYPES.md) | Canton transaction and event type guide |
| [UPDATE_TREE_PROCESSING.md](UPDATE_TREE_PROCESSING.md) | Event tree traversal documentation |
