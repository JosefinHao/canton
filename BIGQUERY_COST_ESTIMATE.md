# BigQuery Cost Estimate for Canton Blockchain Data Pipeline

**Prepared for:** Upper Management
**Date:** February 5, 2026
**Project:** governence-483517
**Document Version:** 1.1

---

## Executive Summary

This document provides a comprehensive cost estimate for implementing a BigQuery-based data pipeline to ingest and analyze Canton blockchain data. The pipeline will:

1. **Historical Backfill:** Ingest all blockchain events from January 2026 to present (~1 month)
2. **Ongoing Ingestion:** Continuously capture new blockchain events in near real-time
3. **Data Transformation:** Process raw data into analytics-ready tables for ML analysis

### Actual Data Volume (Based on Historical Analysis)

> **Key Finding:** Analysis of historical data from November-December 2025 shows an average of **23,330,718 events per day** (~23.3 million events/day).

**Estimated Total Costs (Based on Actual Volume):**

| Category | Monthly Cost | First Year Total |
|----------|--------------|------------------|
| **One-Time Backfill** | - | $50 - $100 |
| **Ongoing Monthly** | $650 - $850 | $7,800 - $10,200 |
| **First Year Total** | - | **$7,850 - $10,300** |

**Recommended Option:** Cloud Run with Cloud Scheduler for compute (due to high volume), combined with BigQuery on-demand pricing initially. Evaluate slot reservations after 2-3 months of operation.

---

## Why This Data Infrastructure Is Essential

BigQuery is the optimal solution for Canton blockchain on-chain data analysis because it uniquely addresses the core challenges of blockchain data: **unlimited scale** for ever-growing append-only datasets, **native JSON/array support** for complex smart contract event structures, **columnar storage** that reduces analytical query costs by 80-95%, and **integrated ML capabilities** for advanced pattern detection without data movement.

**Key Strategic Benefits:**
- **Real-time monitoring** of network activity and contract events
- **Historical trend analysis** across months of transaction data
- **Compliance-ready** immutable audit trail with complete data lineage
- **ML-powered insights** for anomaly detection and usage prediction
- **Cost efficiency** through automatic long-term storage tiering (50% reduction after 90 days)

Traditional databases (PostgreSQL, MongoDB) cannot scale cost-effectively beyond 1TB, while self-managed solutions (Spark clusters) require significant operational overhead. BigQuery's serverless architecture eliminates infrastructure management while seamlessly scaling from gigabytes to petabytes.

---

## 1. Project Overview

### 1.1 Data Source

The Canton Scan API provides blockchain transaction and event data:
- **API Endpoint:** `https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/v2/updates`
- **Data Type:** Blockchain transactions containing smart contract events
- **Event Types:** Contract creates, exercises, archives, and reassignments

### 1.2 Data Pipeline Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Canton Scan    │     │  Compute        │     │  BigQuery       │     │  ML/Analytics   │
│  API            │────▶│  (Function/Run/ │────▶│  Tables         │────▶│  Workloads      │
│                 │     │   VM+Cron)      │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        ┌─────────────────┐
                        │  Transformation │
                        │  (raw → parsed) │
                        └─────────────────┘
```

### 1.3 BigQuery Table Structure

| Table | Purpose | Storage Type |
|-------|---------|--------------|
| `raw.events` | Raw event data (STRING format) | Active storage |
| `transformed.events_parsed` | Analytics-ready data (typed) | Partitioned by date, clustered |
| `raw.ingestion_state` | Pipeline position tracking | Minimal storage |

---

## 2. Data Volume Estimates

### 2.1 Actual Measured Volume

> **Based on historical data analysis (Nov 1 - Dec 31, 2025):**
>
> | Metric | Value |
> |--------|-------|
> | **Average Events per Day** | **23,330,718** |
> | Estimated Raw Size per Day | ~35 GB |
> | Estimated Parsed Size per Day | ~28 GB |

### 2.2 Projected Monthly & Annual Volume

| Timeframe | Events | Raw Data Size | Parsed Data Size |
|-----------|--------|---------------|------------------|
| Daily | 23.3M | 35 GB | 28 GB |
| Monthly | 700M | 1.05 TB | 840 GB |
| Yearly | 8.5B | 12.6 TB | 10.2 TB |

### 2.3 Historical Backfill (January 2026)

| Period | Est. Events | Est. Raw Size | Est. Parsed Size |
|--------|-------------|---------------|------------------|
| Jan 2026 (~31 days) | ~723M | ~1.1 TB | ~870 GB |

---

## 3. Compute Infrastructure Options

### 3.1 Option A: Cloud Functions

**Description:** Serverless functions triggered every 15 minutes by Cloud Scheduler.

| Component | Specification | Monthly Cost |
|-----------|---------------|--------------|
| Cloud Functions Gen2 | 512MB memory, 540s timeout | ~$15 - $25 |
| Cloud Scheduler | 1 job, every 15 minutes | $0.10 |
| Cloud Logging | Included in free tier | $0 |
| **Subtotal** | | **$15 - $25/month** |

**Limitation:** At 23M events/day, Cloud Functions may hit timeout limits. Consider Cloud Run instead.

### 3.2 Option B: Cloud Run (Recommended for This Volume)

**Description:** Containerized service with HTTP endpoints, triggered by Cloud Scheduler.

| Component | Specification | Monthly Cost |
|-----------|---------------|--------------|
| Cloud Run | 1Gi memory, 2 vCPU, min 0 instances | ~$40 - $60 |
| Cloud Scheduler | 1 job, every 15 minutes | $0.10 |
| Artifact Registry | Container storage | ~$1 |
| **Subtotal** | | **$41 - $61/month** |

**Pros:**
- Longer timeout (up to 60 minutes)
- Better suited for high-volume processing
- Can handle 23M+ events/day reliably

### 3.3 Option C: Compute Engine VM with Cron

**Description:** Dedicated VM running cron job for scheduled ingestion.

| Component | Specification | Monthly Cost |
|-----------|---------------|--------------|
| e2-standard-2 VM | 2 vCPU, 8GB memory, 100GB disk | ~$60 |
| e2-standard-4 VM | 4 vCPU, 16GB memory, 200GB disk | ~$120 |
| **Subtotal** | | **$60 - $120/month** |

**Pros:**
- No execution time limits
- Best for heavy backfill operations
- Consistent performance

### 3.4 Compute Option Comparison

| Factor | Cloud Functions | Cloud Run | VM + Cron |
|--------|----------------|-----------|-----------|
| Monthly Cost | $15 - $25 | $41 - $61 | $60 - $120 |
| Setup Complexity | Low | Medium | Medium |
| Maintenance | None | Low | Medium |
| Max Execution Time | 9 min | 60 min | Unlimited |
| **Suitable for 23M events/day** | Limited | Yes | Yes |

**Recommendation:** Use **Cloud Run** for ongoing ingestion due to high event volume.

---

## 4. BigQuery Cost Breakdown (Based on Actual Volume)

### 4.1 Storage Costs

BigQuery storage pricing (US multi-region):
- **Active Storage:** $0.02 per GB/month
- **Long-term Storage:** $0.01 per GB/month (data unchanged for 90+ days)

| Timeframe | Cumulative Raw | Cumulative Parsed | Monthly Storage Cost |
|-----------|----------------|-------------------|---------------------|
| Month 1 | 1.05 TB | 840 GB | $38 |
| Month 6 | 6.3 TB | 5 TB | $170* |
| Month 12 | 12.6 TB | 10.2 TB | $275* |

*Includes long-term storage discount for data older than 90 days

**Average Monthly Storage Cost (Year 1):** ~$150/month

### 4.2 Streaming Insert Costs (Data Ingestion)

BigQuery streaming insert pricing:
- **Cost:** $0.01 per 200 MB = $0.05 per GB

| Timeframe | Data Volume | Insert Cost |
|-----------|-------------|-------------|
| Daily | 35 GB | $1.75 |
| Monthly | 1.05 TB | **$52.50** |
| Yearly | 12.6 TB | $630 |

### 4.3 Query Costs (Transformation & Analytics)

BigQuery on-demand query pricing:
- **Cost:** $6.25 per TB scanned (first 1 TB/month free)

#### Transformation Queries (Raw → Parsed)

| Frequency | Data Scanned | Monthly Cost |
|-----------|--------------|--------------|
| Every 15 min (96x/day) | ~1 TB/day | ~$187/month |
| Optimized (incremental) | ~100 GB/day | ~$19/month |

**Recommendation:** Use incremental transformation with state tracking to reduce costs.

#### Analytics/ML Queries

| Query Type | Estimated Scans | Monthly Frequency | Monthly Cost |
|------------|-----------------|-------------------|--------------|
| Exploratory Analysis | 100 - 500 GB/query | 20 queries | $12.50 - $62.50 |
| ML Feature Engineering | 500 GB - 2 TB/query | 30 queries | $93.75 - $375 |
| Dashboard Refreshes | 50 - 200 GB/query | 100 queries | $31.25 - $125 |
| Ad-hoc Reports | 100 - 500 GB/query | 10 queries | $6.25 - $31.25 |
| **Subtotal Analytics** | | | **$144 - $594/month** |

### 4.4 Cost Optimization: Slot Reservations

At this query volume, slot reservations become cost-effective:

| Edition | Slots | Monthly Cost | Break-even Query TB |
|---------|-------|--------------|---------------------|
| Standard (Flex) | 100 | $292/month | 47 TB/month |
| Enterprise (Monthly) | 100 | $219/month | 35 TB/month |
| Enterprise (Annual) | 100 | $146/month | 23 TB/month |

**Recommendation:** If analytics queries exceed 35 TB/month, switch to Enterprise Monthly slots to cap query costs at $219/month.

---

## 5. Historical Backfill Cost Estimate

### 5.1 One-Time Backfill Costs (January 2026)

Ingesting ~1 month of historical data at 23.3M events/day:

| Component | Cost |
|-----------|------|
| **Data Volume** | ~1.1 TB raw, ~870 GB parsed |
| Streaming Inserts | $55 |
| Or: Batch Load (FREE) | $0 |
| Initial Transform Query | $6.25 |
| Temp VM (e2-standard-2, 3 days) | $6 |
| **Total One-Time (with streaming)** | **$67** |
| **Total One-Time (with batch load)** | **$12** |

**Recommendation:** Use batch loading (free) for historical backfill to save ~$55.

---

## 6. Ongoing Monthly Cost Summary

### 6.1 Detailed Monthly Breakdown (23.3M events/day)

| Component | Monthly Cost |
|-----------|--------------|
| Compute (Cloud Run) | $50 |
| Cloud Scheduler | $0.10 |
| Storage (growing average) | $150 |
| Streaming Inserts | $53 |
| Transformation Queries (optimized) | $20 |
| Analytics Queries (moderate usage) | $250 |
| **Monthly Total** | **$523** |

### 6.2 Cost Range by Analytics Usage

| Analytics Usage | Transform + Analytics Queries | Total Monthly |
|-----------------|------------------------------|---------------|
| Light | $20 + $144 = $164 | **$417** |
| Moderate | $20 + $300 = $320 | **$573** |
| Heavy | $20 + $594 = $614 | **$867** |

### 6.3 Annual Cost Projection

| Component | Year 1 Cost |
|-----------|-------------|
| Compute (Cloud Run) | $600 |
| Storage (cumulative) | $1,800 |
| Streaming Inserts | $636 |
| Transformation Queries | $240 |
| Analytics Queries (moderate) | $3,600 |
| Backfill (one-time) | $12 |
| **Year 1 Total** | **$6,888** |

---

## 7. ML/Analytics Workload Considerations

### 7.1 Additional ML Infrastructure Costs

| Component | Purpose | Est. Monthly Cost |
|-----------|---------|-------------------|
| BigQuery ML | In-database ML models | $250/TB processed |
| Vertex AI Training | Custom model training | $50 - $500+ |
| Vertex AI Prediction | Model serving | $20 - $200+ |
| Looker/BI Tools | Dashboards & reporting | $0 - $300+ |

### 7.2 Analytics-Ready Table Design

The `transformed.events_parsed` table is optimized for analytics:

- **Partitioning:** By `DATE(timestamp)` - reduces query costs by scanning only relevant dates
- **Clustering:** By `template_id`, `event_type`, `migration_id` - improves query performance 2-5x
- **Typed Fields:** Proper TIMESTAMP, INT64, BOOL, JSON types for efficient processing

**Estimated Query Cost Savings:** 60-80% reduction vs. unpartitioned tables

### 7.3 Recommended Analytics Tables

For ML workloads, consider creating additional materialized views:

| Table | Purpose | Refresh Frequency |
|-------|---------|-------------------|
| `analytics.daily_event_summary` | Daily aggregates | Hourly |
| `analytics.contract_lifecycle` | Contract states | Daily |
| `analytics.party_activity` | Party metrics | Daily |
| `analytics.ml_features` | Pre-computed ML features | Daily |

**Additional Storage Cost:** ~10-20% of base data (~$15-30/month)

---

## 8. Cost Comparison: Infrastructure Options

### 8.1 First Year Total Cost by Compute Option

| Compute Option | Compute Cost | Other Costs | Total Year 1 |
|----------------|--------------|-------------|--------------|
| Cloud Functions | $240 | $6,288 | $6,528 |
| **Cloud Run (Recommended)** | $600 | $6,288 | **$6,888** |
| VM (e2-standard-2) | $720 | $6,288 | $7,008 |

### 8.2 Recommendation Matrix

| Use Case | Recommended Option | Reason |
|----------|-------------------|--------|
| **23M events/day (current)** | **Cloud Run** | Reliable processing within timeout limits |
| Heavy analytics (>35 TB/mo) | Cloud Run + Slot Reservations | Caps query costs at $219/month |
| Initial backfill | Temporary VM | No timeout limits, batch loading |

---

## 9. Implementation Recommendations

### Phase 1: Historical Backfill (Days 1-3)

1. Provision temporary e2-standard-2 VM (~$6 for 3 days)
2. Run batch load script for January 2026 data (free)
3. Execute initial transformation query
4. Validate data completeness and quality
5. Terminate VM

**Phase 1 Cost:** ~$12

### Phase 2: Production Deployment (Days 4-7)

1. Deploy Cloud Run service for ingestion
2. Configure Cloud Scheduler (every 15 minutes)
3. Set up BigQuery scheduled query for transformation
4. Configure monitoring and alerting

**Phase 2 Cost:** ~$20 (setup) + ongoing

### Phase 3: Analytics Enablement (Week 2)

1. Create additional analytics tables/views
2. Set up Looker or BI tool connections
3. Build initial dashboards
4. Configure ML feature pipelines

**Phase 3 Cost:** Varies by tooling choice

---

## 10. Risk Factors and Contingencies

### 10.1 Cost Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Data volume increases further | Medium | +25-50% | Monitor and set budget alerts |
| Runaway analytics queries | Medium | +$200-500/mo | Set query cost limits, use slots |
| API rate limiting | Low | Delays | Implement exponential backoff |
| Storage growth exceeds estimate | Low | +20% | Archive old data to GCS |

### 10.2 Budget Contingency

**Recommended contingency buffer:** 25-30% of estimated costs

| Scenario | Estimated Year 1 | With 30% Buffer |
|----------|------------------|-----------------|
| Current Volume (23M/day) | $6,888 | **$8,955** |
| With Heavy Analytics | $8,500 | $11,050 |

### 10.3 Cost Controls

1. **Query Cost Limits:** Set per-user daily limit of $50
2. **Budget Alerts:** Configure alerts at 50%, 80%, 100% of budget
3. **Slot Reservations:** Switch to Enterprise slots if query costs exceed $219/month
4. **Data Retention:** Consider archiving raw data older than 1 year to Cloud Storage

---

## 11. Approval Request

### Requested Budget

| Category | Year 1 Budget Request |
|----------|----------------------|
| BigQuery Storage | $1,800 |
| BigQuery Streaming Inserts | $650 |
| BigQuery Queries (Transform + Analytics) | $4,000 |
| Compute (Cloud Run) | $600 |
| Backfill Infrastructure | $15 |
| Contingency (25%) | $1,765 |
| **Total Requested** | **$8,830** |

### Approval Signatures

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Project Lead | | | |
| Finance Approval | | | |
| Engineering Manager | | | |
| VP/Director Approval | | | |

---

## Appendix A: Pricing Sources

- [BigQuery Pricing](https://cloud.google.com/bigquery/pricing)
- [Cloud Functions Pricing](https://cloud.google.com/functions/pricing)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
- [Compute Engine Pricing](https://cloud.google.com/compute/vm-instance-pricing)

## Appendix B: Technical Configuration

### Current Pipeline Settings

```
Project ID: governence-483517
Raw Table: governence-483517.raw.events
Parsed Table: governence-483517.transformed.events_parsed
Ingestion Frequency: Every 15 minutes
Page Size: 500 updates per API call
Max Pages per Run: 100
Batch Size: 100 events per BigQuery insert
```

### Recommended Production Settings (for 23M events/day)

```
Page Size: 1000 (for higher throughput)
Max Pages per Run: 500 (process more data per invocation)
Batch Size: 1000 (larger BigQuery batches)
API Delay: 0.02 seconds (faster API polling)
Auto Transform: true (immediate transformation)
```

## Appendix C: Data Volume Verification Query

```sql
-- Query used to determine actual event volume
WITH daily_counts AS (
  SELECT
    DATE(timestamp) AS event_date,
    COUNT(*) AS event_count
  FROM `governence-483517.transformed.events_parsed`
  WHERE timestamp >= '2025-11-01'
    AND timestamp < '2026-01-01'
  GROUP BY DATE(timestamp)
)
SELECT
  MIN(event_date) AS start_date,
  MAX(event_date) AS end_date,
  COUNT(*) AS days_with_data,
  SUM(event_count) AS total_events,
  ROUND(AVG(event_count), 0) AS avg_events_per_day
FROM daily_counts

-- Result: avg_events_per_day = 23,330,718
```

---

**Document Prepared By:** Data Engineering Team
**Last Updated:** February 5, 2026
