# Canton Network Analytics Plan

## Executive Summary

This document describes the complete analytics layer built on top of the Canton Network on-chain data pipeline. It covers the data model, specific tables, SQL patterns, incremental processing strategy, scheduling, cost management, and maps every business question to the analytics infrastructure that answers it.

**Current Pipeline (already operational):**
```
GCS (canton-bucket)  ──→  raw.events  ──→  transformed.events_parsed
     00:00 UTC               01:00 UTC
```

**Analytics Layer (this plan):**
```
transformed.events_parsed  ──→  analytics.fact_*     ──→  analytics.agg_*
         02:00 UTC                    03:00 UTC
                               analytics.dim_*
                                 (02:30 UTC)
```

---

## 1. Data Model Overview

We use a **star schema** approach with three layers built on top of `transformed.events_parsed`:

| Layer | Dataset | Purpose | Update Frequency | Approx. Size |
|-------|---------|---------|-----------------|--------------|
| **Source** | `transformed` | Parsed events (all 3.6B+ rows) | Daily 01:00 UTC | 10+ TB |
| **Facts** | `analytics` | Domain-specific extracts with denormalized fields from JSON payloads | Daily 02:00 UTC | 1-50 GB each |
| **Dimensions** | `analytics` | Entity registries (parties, validators, apps) | Daily 02:30 UTC | <1 GB each |
| **Aggregates** | `analytics` | Pre-computed daily/weekly rollups for dashboards | Daily 03:00 UTC | <10 GB each |

### Why Not Query events_parsed Directly?

1. **Cost**: A full scan of events_parsed costs ~$50+ at $5/TB. Fact tables are 100-1000x smaller.
2. **Complexity**: Extracting amounts from nested JSON payloads requires complex `JSON_VALUE()` expressions. Fact tables pre-extract these.
3. **Performance**: Dashboard queries need sub-second response. Aggregate tables provide this.
4. **Clarity**: Analysts can query `fact_rewards` instead of writing 20-line JSON extraction queries against events_parsed.

---

## 2. Fact Tables

Each fact table extracts a specific category of events from `events_parsed`, denormalizes the JSON payload into typed columns, and is partitioned/clustered for efficient querying.

### 2.1 `analytics.fact_rewards`

**Purpose**: One row per reward coupon creation. Covers all reward types: app, validator, SV, unclaimed, and development fund.

**Source filter**: `event_type = 'created' AND template_id` matching any of the reward coupon templates.

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `reward_type` | STRING | Derived: 'app', 'validator', 'sv', 'unclaimed', 'dev_fund' |
| `provider_party_id` | STRING | JSON_VALUE(payload, '$.user') or '$.validator' or '$.sv' |
| `round_number` | INT64 | JSON_VALUE(payload, '$.round.number') |
| `amount` | FLOAT64 | JSON_VALUE(payload, '$.amount') or '$.amuletAmount' |
| `featured` | BOOL | JSON_VALUE(payload, '$.featured') (for app rewards) |

**Template ID filters**:
```sql
template_id LIKE '%AppRewardCoupon%'
OR template_id LIKE '%ValidatorRewardCoupon%'
OR template_id LIKE '%SvRewardCoupon%'
OR template_id LIKE '%UnclaimedReward%'
OR template_id LIKE '%UnclaimedDevelopmentFundCoupon%'
OR template_id LIKE '%ValidatorFaucetCoupon%'
```

**Partitioning**: By `event_date`
**Clustering**: By `reward_type`, `provider_party_id`, `round_number`

**Business questions answered**: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9

---

### 2.2 `analytics.fact_transfers`

**Purpose**: One row per Canton Coin transfer exercise event, with sender, receiver, amount, and fee information extracted from the payload.

**Source filter**: `event_type = 'exercised' AND choice = 'AmuletRules_Transfer'`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `sender_party_id` | STRING | First element of acting_parties array |
| `round_number` | INT64 | Extracted from exercise payload |
| `transfer_amount` | FLOAT64 | Extracted from choice_argument |
| `fee_amount` | FLOAT64 | Extracted from exercise_result |

**Partitioning**: By `event_date`
**Clustering**: By `sender_party_id`, `migration_id`

**Business questions answered**: 1.1, 1.3, 4.1, 4.3, 4.4, 5.3, 9.5

---

### 2.3 `analytics.fact_traffic_purchases`

**Purpose**: One row per traffic purchase event (MemberTraffic contract creation), tracking bandwidth consumption by validators/parties.

**Source filter**: `event_type = 'created' AND template_id LIKE '%MemberTraffic%'`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `provider_party_id` | STRING | JSON_VALUE(payload, '$.provider') |
| `synchronizer_id` | STRING | JSON_VALUE(payload, '$.synchronizerId') |
| `total_purchased` | INT64 | JSON_VALUE(payload, '$.totalPurchased') |
| `round_number` | INT64 | JSON_VALUE(payload, '$.round.number') |

**Partitioning**: By `event_date`
**Clustering**: By `provider_party_id`, `migration_id`

**Business questions answered**: 4.5, 6.4, 3.4

---

### 2.4 `analytics.fact_featured_app_activity`

**Purpose**: One row per FeaturedAppActivityMarker creation, tracking app usage. This became a dominant template in migrations 3-4.

**Source filter**: `event_type = 'created' AND template_id LIKE '%FeaturedAppActivityMarker%'`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `provider_party_id` | STRING | JSON_VALUE(payload, '$.provider') |
| `activity_party_id` | STRING | JSON_VALUE(payload, '$.user') or signatories |
| `round_number` | INT64 | JSON_VALUE(payload, '$.round.number') |

**Partitioning**: By `event_date`
**Clustering**: By `provider_party_id`, `activity_party_id`

**Business questions answered**: 2.1, 2.2, 2.3, 2.5, 2.8, 9.2

---

### 2.5 `analytics.fact_amulet_lifecycle`

**Purpose**: Tracks creation and archival of Amulet (Canton Coin) UTXO contracts. Essential for supply analysis, holding distribution, and token velocity.

**Source filter**: `template_id LIKE '%Splice.Amulet:Amulet'` (exact match, not AmuletRules) `AND event_type IN ('created', 'archived')`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `lifecycle_event` | STRING | 'created' or 'archived' |
| `owner_party_id` | STRING | JSON_VALUE(payload, '$.owner') or first signatory |
| `amount` | FLOAT64 | JSON_VALUE(payload, '$.amount.initialAmount') |
| `created_at_round` | INT64 | JSON_VALUE(payload, '$.amount.createdAt') |

**Partitioning**: By `event_date`
**Clustering**: By `lifecycle_event`, `owner_party_id`

**Business questions answered**: 5.1, 5.2, 5.4, 5.5, 5.7, 4.6

---

### 2.6 `analytics.fact_mining_rounds`

**Purpose**: Tracks the lifecycle of mining rounds (Open → Issuing → Closed). One row per round state transition.

**Source filter**: `event_type = 'created' AND template_id matching *MiningRound*`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `round_type` | STRING | 'open', 'issuing', 'closed', 'summarizing' |
| `round_number` | INT64 | JSON_VALUE(payload, '$.round.number') |

**Partitioning**: By `event_date`
**Clustering**: By `round_type`, `round_number`

**Business questions answered**: 1.5, 3.8

---

### 2.7 `analytics.fact_governance`

**Purpose**: Tracks governance actions — vote requests, votes cast, and confirmations.

**Source filter**: `template_id matching VoteRequest, Vote, Confirmation AND event_type IN ('created', 'exercised')`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `governance_event_type` | STRING | 'vote_request', 'vote', 'confirmation' |
| `voter_party_id` | STRING | Acting party or signatory |
| `action_type` | STRING | JSON_VALUE(payload, '$.action.tag') |
| `vote_value` | STRING | JSON_VALUE(payload, '$.accept') — 'true'/'false' |

**Partitioning**: By `event_date`
**Clustering**: By `governance_event_type`, `voter_party_id`

**Business questions answered**: 7.1, 7.2, 7.3, 7.4, 7.5

---

### 2.8 `analytics.fact_validator_liveness`

**Purpose**: Tracks validator liveness and licensing. One row per ValidatorLivenessActivityRecord or ValidatorLicense event.

**Source filter**: `event_type = 'created' AND template_id matching ValidatorLiveness* or ValidatorLicense*`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `update_id` | STRING | events_parsed.update_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `record_type` | STRING | 'liveness' or 'license' |
| `validator_party_id` | STRING | JSON_VALUE(payload, '$.validator') |
| `round_number` | INT64 | JSON_VALUE(payload, '$.round.number') |

**Partitioning**: By `event_date`
**Clustering**: By `record_type`, `validator_party_id`

**Business questions answered**: 1.6, 1.7, 6.1, 6.2, 6.5, 6.6

---

### 2.9 `analytics.fact_ans_entries`

**Purpose**: Tracks Amulet Name Service registrations, renewals, and expirations.

**Source filter**: `template_id LIKE '%AnsEntry%' AND event_type IN ('created', 'archived')`

| Column | Type | Source |
|--------|------|--------|
| `event_date` | DATE | Partition column |
| `event_id` | STRING | events_parsed.event_id |
| `contract_id` | STRING | events_parsed.contract_id |
| `recorded_at` | TIMESTAMP | events_parsed.recorded_at |
| `migration_id` | INT64 | events_parsed.migration_id |
| `lifecycle_event` | STRING | 'created' or 'archived' |
| `name` | STRING | JSON_VALUE(payload, '$.name') |
| `owner_party_id` | STRING | JSON_VALUE(payload, '$.user') |
| `expires_at` | TIMESTAMP | JSON_VALUE(payload, '$.expiresAt') |

**Partitioning**: By `event_date`
**Clustering**: By `owner_party_id`

**Business questions answered**: 8.1, 8.2, 8.3, 8.4

---

## 3. Dimension Tables

Dimension tables are fully rebuilt daily (they're small) to maintain accuracy. No incremental logic needed — just `CREATE OR REPLACE`.

### 3.1 `analytics.dim_parties`

**Purpose**: Registry of all parties ever seen on-chain with classification metadata.

```sql
CREATE OR REPLACE TABLE `analytics.dim_parties`
PARTITION BY DATE_TRUNC(first_seen, MONTH)
AS
WITH all_parties AS (
  -- From signatories
  SELECT party_id, MIN(recorded_at) as first_seen, MAX(recorded_at) as last_seen
  FROM `transformed.events_parsed`,
       UNNEST(signatories) AS party_id
  GROUP BY party_id
  UNION ALL
  -- From acting_parties
  SELECT party_id, MIN(recorded_at), MAX(recorded_at)
  FROM `transformed.events_parsed`,
       UNNEST(acting_parties) AS party_id
  GROUP BY party_id
)
SELECT
  party_id,
  MIN(first_seen) AS first_seen,
  MAX(last_seen) AS last_seen,
  DATE_DIFF(CURRENT_DATE(), DATE(MIN(first_seen)), DAY) AS tenure_days
FROM all_parties
GROUP BY party_id;
```

**Note**: This full rebuild is expensive (~$50). For cost optimization, we can:
- Build it once as backfill, then incrementally merge new parties from the last day's events
- Or build only from fact tables (much cheaper since they're pre-filtered)

**Recommended approach**: Build `dim_parties` incrementally from fact tables:

```sql
-- Daily incremental merge (runs at 02:30 UTC)
MERGE `analytics.dim_parties` T
USING (
  SELECT DISTINCT party_id, MIN(recorded_at) AS first_seen, MAX(recorded_at) AS last_seen
  FROM (
    SELECT provider_party_id AS party_id, recorded_at FROM analytics.fact_rewards WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    UNION ALL
    SELECT sender_party_id, recorded_at FROM analytics.fact_transfers WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    UNION ALL
    SELECT provider_party_id, recorded_at FROM analytics.fact_traffic_purchases WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    UNION ALL
    SELECT provider_party_id, recorded_at FROM analytics.fact_featured_app_activity WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    UNION ALL
    SELECT owner_party_id, recorded_at FROM analytics.fact_amulet_lifecycle WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    UNION ALL
    SELECT validator_party_id, recorded_at FROM analytics.fact_validator_liveness WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  ) sub
  WHERE party_id IS NOT NULL
  GROUP BY party_id
) S
ON T.party_id = S.party_id
WHEN MATCHED THEN
  UPDATE SET last_seen = GREATEST(T.last_seen, S.last_seen)
WHEN NOT MATCHED THEN
  INSERT (party_id, first_seen, last_seen, tenure_days)
  VALUES (S.party_id, S.first_seen, S.last_seen, DATE_DIFF(CURRENT_DATE(), DATE(S.first_seen), DAY));
```

**Business questions answered**: 1.2 (new vs returning), 9.4 (time to first tx)

---

### 3.2 `analytics.dim_validators`

**Purpose**: Registry of all validators with license status and liveness summary.

Built from `fact_validator_liveness`:

```sql
CREATE OR REPLACE TABLE `analytics.dim_validators` AS
SELECT
  validator_party_id,
  MIN(CASE WHEN record_type = 'license' THEN recorded_at END) AS first_licensed,
  MAX(CASE WHEN record_type = 'license' THEN recorded_at END) AS last_license_event,
  MIN(CASE WHEN record_type = 'liveness' THEN recorded_at END) AS first_liveness,
  MAX(CASE WHEN record_type = 'liveness' THEN recorded_at END) AS last_liveness,
  COUNTIF(record_type = 'liveness') AS total_liveness_records,
  COUNT(DISTINCT CASE WHEN record_type = 'liveness' THEN round_number END) AS rounds_with_liveness,
  COUNT(DISTINCT event_date) AS active_days
FROM `analytics.fact_validator_liveness`
GROUP BY validator_party_id;
```

**Business questions answered**: 1.6, 1.7, 6.1, 6.2, 6.5

---

### 3.3 `analytics.dim_featured_apps`

**Purpose**: Registry of apps that hold or have held FeaturedAppRight.

Built from `events_parsed` filtered on FeaturedAppRight:

```sql
CREATE OR REPLACE TABLE `analytics.dim_featured_apps` AS
SELECT
  JSON_VALUE(payload, '$.provider') AS provider_party_id,
  contract_id,
  MIN(recorded_at) AS granted_at,
  MAX(CASE WHEN event_type = 'archived' THEN recorded_at END) AS revoked_at,
  CASE WHEN MAX(CASE WHEN event_type = 'archived' THEN recorded_at END) IS NULL THEN TRUE ELSE FALSE END AS is_active
FROM `transformed.events_parsed`
WHERE template_id LIKE '%FeaturedAppRight%'
  AND event_type IN ('created', 'archived')
GROUP BY JSON_VALUE(payload, '$.provider'), contract_id;
```

**Note**: This is a small query since `FeaturedAppRight` events are rare (one per app grant). Cost: negligible.

**Business questions answered**: 2.1, 2.4, 2.6, 2.7

---

### 3.4 `analytics.dim_date`

**Purpose**: Standard date dimension for joins and calendar-aware aggregations.

```sql
CREATE OR REPLACE TABLE `analytics.dim_date` AS
SELECT
  d AS date_key,
  EXTRACT(YEAR FROM d) AS year,
  EXTRACT(QUARTER FROM d) AS quarter,
  EXTRACT(MONTH FROM d) AS month,
  EXTRACT(WEEK FROM d) AS week_of_year,
  EXTRACT(DAYOFWEEK FROM d) AS day_of_week,
  FORMAT_DATE('%A', d) AS day_name,
  CASE WHEN EXTRACT(DAYOFWEEK FROM d) IN (1, 7) THEN TRUE ELSE FALSE END AS is_weekend,
  -- Canton Network epochs
  CASE
    WHEN d < '2024-10-16' THEN 'migration_0'
    WHEN d < '2024-12-11' THEN 'migration_1'
    WHEN d < '2025-06-25' THEN 'migration_2'
    WHEN d < '2025-12-10' THEN 'migration_3'
    ELSE 'migration_4'
  END AS migration_epoch,
  -- Mining curve phases (approximate, from network launch 2024-06-24)
  CASE
    WHEN d < '2024-12-24' THEN 'bootstrap'
    WHEN d < '2025-12-24' THEN 'early_growth'
    WHEN d < '2029-06-24' THEN 'growth'
    WHEN d < '2034-06-24' THEN 'maturation'
    ELSE 'steady_state'
  END AS mining_phase
FROM UNNEST(GENERATE_DATE_ARRAY('2024-06-24', CURRENT_DATE())) AS d;
```

**Business questions answered**: 9.5 (weekday/weekend), 3.8 (phase transitions), 1.4 (migration epochs)

---

## 4. Aggregate Tables

Pre-computed rollups for dashboard performance. These are the tables analysts and dashboards query directly.

### 4.1 `analytics.agg_daily_network`

**Purpose**: One row per day with network-level summary metrics. The primary "health dashboard" table.

```sql
-- Built from events_parsed (1-day scan, clustered access)
CREATE OR REPLACE TABLE `analytics.agg_daily_network`
PARTITION BY event_date
AS
SELECT
  event_date,
  -- Volume metrics
  COUNT(DISTINCT update_id) AS transaction_count,
  COUNT(*) AS total_events,
  -- Activity metrics
  (SELECT COUNT(DISTINCT p) FROM UNNEST(signatories_agg) AS p) AS unique_signatories,
  -- Event type breakdown
  COUNTIF(event_type = 'created') AS created_events,
  COUNTIF(event_type = 'exercised') AS exercised_events,
  COUNTIF(event_type = 'archived') AS archived_events,
  -- Template category breakdown
  COUNTIF(template_id LIKE '%Amulet:Amulet' AND event_type = 'created') AS amulet_creates,
  COUNTIF(template_id LIKE '%RewardCoupon%' AND event_type = 'created') AS reward_coupons,
  COUNTIF(template_id LIKE '%FeaturedAppActivityMarker%' AND event_type = 'created') AS app_activity_markers,
  COUNTIF(template_id LIKE '%MiningRound%') AS mining_round_events,
  COUNTIF(template_id LIKE '%ValidatorLiveness%') AS liveness_records,
  COUNTIF(template_id LIKE '%MemberTraffic%' AND event_type = 'created') AS traffic_purchases,
  COUNTIF(template_id LIKE '%VoteRequest%') AS governance_events,
  COUNTIF(template_id LIKE '%AnsEntry%') AS ans_events,
  -- Migration
  MAX(migration_id) AS migration_id
FROM `transformed.events_parsed`
GROUP BY event_date;
```

**Note on unique parties**: The signatories aggregation above is pseudocode. In practice, counting unique parties across a day requires either:
- A subquery approach: `SELECT event_date, COUNT(DISTINCT party_id) FROM events_parsed, UNNEST(signatories) party_id GROUP BY event_date`
- Or building from fact tables (cheaper)

**Recommended daily incremental approach** (cheaper, runs at 03:00 UTC):
```sql
-- Only process yesterday and today
INSERT INTO `analytics.agg_daily_network` (...)
SELECT ...
FROM `transformed.events_parsed`
WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND NOT EXISTS (
    SELECT 1 FROM `analytics.agg_daily_network` a
    WHERE a.event_date = events_parsed.event_date
  )
GROUP BY event_date;
```

**Business questions answered**: 1.1, 1.4, 1.5, 9.5, 9.6

---

### 4.2 `analytics.agg_daily_rewards`

**Purpose**: Daily reward totals by type and provider. The core "rewards dashboard" table.

```sql
-- Built from fact_rewards (very cheap)
SELECT
  event_date,
  reward_type,
  provider_party_id,
  COUNT(*) AS coupon_count,
  SUM(amount) AS total_amount,
  AVG(amount) AS avg_amount,
  MIN(round_number) AS min_round,
  MAX(round_number) AS max_round
FROM `analytics.fact_rewards`
GROUP BY event_date, reward_type, provider_party_id;
```

**Partitioning**: By `event_date`
**Clustering**: By `reward_type`, `provider_party_id`

**Business questions answered**: 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 3.9

---

### 4.3 `analytics.agg_daily_featured_apps`

**Purpose**: Daily metrics per featured app — activity markers, unique users, and rewards earned.

```sql
SELECT
  a.event_date,
  a.provider_party_id,
  -- Activity metrics (from fact_featured_app_activity)
  COUNT(DISTINCT a.event_id) AS activity_marker_count,
  COUNT(DISTINCT a.activity_party_id) AS unique_users,
  -- Rewards (joined from fact_rewards)
  COALESCE(r.total_rewards, 0) AS total_rewards,
  COALESCE(r.coupon_count, 0) AS reward_coupon_count
FROM `analytics.fact_featured_app_activity` a
LEFT JOIN (
  SELECT event_date, provider_party_id,
         SUM(amount) AS total_rewards,
         COUNT(*) AS coupon_count
  FROM `analytics.fact_rewards`
  WHERE reward_type = 'app'
  GROUP BY event_date, provider_party_id
) r ON a.event_date = r.event_date AND a.provider_party_id = r.provider_party_id
GROUP BY a.event_date, a.provider_party_id, r.total_rewards, r.coupon_count;
```

**Business questions answered**: 2.2, 2.3, 2.4, 2.5, 2.8

---

### 4.4 `analytics.agg_daily_token_economics`

**Purpose**: Daily CC minting, burning (fee proxy), and net supply change. The "tokenomics dashboard" table.

```sql
SELECT
  event_date,
  -- Minting (Amulet creations)
  SUM(CASE WHEN lifecycle_event = 'created' THEN amount ELSE 0 END) AS cc_minted,
  COUNTIF(lifecycle_event = 'created') AS utxos_created,
  -- Consumption (Amulet archivals)
  SUM(CASE WHEN lifecycle_event = 'archived' THEN amount ELSE 0 END) AS cc_consumed,
  COUNTIF(lifecycle_event = 'archived') AS utxos_archived,
  -- Net
  SUM(CASE WHEN lifecycle_event = 'created' THEN amount ELSE -amount END) AS net_supply_change,
  -- UTXO set size change
  COUNTIF(lifecycle_event = 'created') - COUNTIF(lifecycle_event = 'archived') AS net_utxo_change
FROM `analytics.fact_amulet_lifecycle`
GROUP BY event_date;
```

**Note**: "cc_consumed" is not exactly "fees burned" — it's amulets archived (consumed as inputs to transfers). The actual fee amount is the difference between inputs and outputs of a transfer. For precise fee calculation, we'd need to correlate within each `update_id`. This is addressed in section 6.

**Business questions answered**: 4.1, 5.1, 5.4

---

### 4.5 `analytics.agg_daily_validators`

**Purpose**: Daily validator metrics — liveness, rewards, and traffic.

```sql
SELECT
  v.event_date,
  v.validator_party_id,
  -- Liveness
  COUNTIF(v.record_type = 'liveness') AS liveness_records,
  COUNT(DISTINCT CASE WHEN v.record_type = 'liveness' THEN v.round_number END) AS rounds_live,
  -- Rewards (from fact_rewards)
  COALESCE(r.total_rewards, 0) AS total_rewards,
  COALESCE(r.coupon_count, 0) AS reward_coupon_count,
  -- Traffic (from fact_traffic_purchases)
  COALESCE(t.total_purchased, 0) AS traffic_purchased,
  COALESCE(t.purchase_count, 0) AS traffic_purchase_count
FROM `analytics.fact_validator_liveness` v
LEFT JOIN (
  SELECT event_date, provider_party_id, SUM(amount) AS total_rewards, COUNT(*) AS coupon_count
  FROM `analytics.fact_rewards` WHERE reward_type = 'validator'
  GROUP BY event_date, provider_party_id
) r ON v.event_date = r.event_date AND v.validator_party_id = r.provider_party_id
LEFT JOIN (
  SELECT event_date, provider_party_id, SUM(total_purchased) AS total_purchased, COUNT(*) AS purchase_count
  FROM `analytics.fact_traffic_purchases`
  GROUP BY event_date, provider_party_id
) t ON v.event_date = t.event_date AND v.validator_party_id = t.provider_party_id
GROUP BY v.event_date, v.validator_party_id, r.total_rewards, r.coupon_count, t.total_purchased, t.purchase_count;
```

**Business questions answered**: 6.1, 6.4, 6.5, 6.6

---

### 4.6 `analytics.agg_daily_governance`

**Purpose**: Daily governance activity — proposals, votes, approvals.

```sql
SELECT
  event_date,
  COUNTIF(governance_event_type = 'vote_request') AS proposals_created,
  COUNTIF(governance_event_type = 'vote') AS votes_cast,
  COUNTIF(governance_event_type = 'confirmation') AS confirmations,
  COUNT(DISTINCT voter_party_id) AS unique_voters,
  COUNT(DISTINCT CASE WHEN governance_event_type = 'vote_request' THEN contract_id END) AS unique_proposals
FROM `analytics.fact_governance`
GROUP BY event_date;
```

**Business questions answered**: 7.1, 7.3, 7.4

---

## 5. Business Questions → Table Mapping

Complete mapping of every business question to the specific analytics table(s) and query pattern needed.

### Category 1: Network Growth & Health

| # | Question | Primary Table | Join Tables | Query Pattern |
|---|----------|---------------|-------------|---------------|
| 1.1 | Transaction volume trend | `agg_daily_network` | `dim_date` | `SELECT event_date, transaction_count FROM agg_daily_network ORDER BY event_date` |
| 1.2 | Active parties & retention | `dim_parties` + `fact_*` | — | Compare first_seen dates to daily activity; cohort analysis |
| 1.3 | Transfer size distribution | `fact_transfers` | — | Histogram: `SELECT CASE WHEN transfer_amount < 100 THEN '<$100' ... END AS bucket, COUNT(*)` |
| 1.4 | Evolution across migrations | `agg_daily_network` | `dim_date` | Group by `dim_date.migration_epoch`, compare averages |
| 1.5 | Throughput per mining round | `agg_daily_network` | `fact_mining_rounds` | `events / mining_round_events` ratio per day |
| 1.6 | Validator onboarding rate | `fact_validator_liveness` | — | `COUNTIF(record_type = 'license')` per month |
| 1.7 | Active vs total validators | `dim_validators` | — | `COUNTIF(last_liveness > DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) / COUNT(*)` |

### Category 2: Featured App Ecosystem

| # | Question | Primary Table | Join Tables | Query Pattern |
|---|----------|---------------|-------------|---------------|
| 2.1 | Featured app count & growth | `dim_featured_apps` | — | `COUNT(*) WHERE is_active`, plus monthly grants |
| 2.2 | Activity concentration | `agg_daily_featured_apps` | — | Gini coefficient across `activity_marker_count` per provider |
| 2.3 | Activity weight per app per round | `fact_featured_app_activity` | `fact_rewards` | Group by provider + round, join rewards |
| 2.4 | Dormant featured apps | `dim_featured_apps` | `agg_daily_featured_apps` | LEFT JOIN; apps with is_active=TRUE but zero activity in last 30 days |
| 2.5 | User overlap between apps | `fact_featured_app_activity` | — | `SELECT COUNT(DISTINCT activity_party_id) FROM ... GROUP BY provider HAVING COUNT(DISTINCT provider) > 1` |
| 2.6 | Impact of unfeatured reward removal | `agg_daily_network` | `dim_date` | Compare app_activity_markers before/after policy change |
| 2.7 | Time-to-featured | `dim_featured_apps` | `dim_parties` | `TIMESTAMP_DIFF(granted_at, first_seen, DAY)` |
| 2.8 | Apps driving most fee burn | `fact_featured_app_activity` | `fact_transfers` | Join on update_id to correlate app activity with transfer fees |

### Category 3: Rewards Economics

| # | Question | Primary Table | Join Tables | Query Pattern |
|---|----------|---------------|-------------|---------------|
| 3.1 | Total CC minted per round by pool | `fact_rewards` | — | `GROUP BY round_number, reward_type; SUM(amount)` |
| 3.2 | Actual vs theoretical allocation | `agg_daily_rewards` | `dim_date` | Compare reward_type ratios against mining curve percentages per phase |
| 3.3 | AppRewardCoupon value trend | `agg_daily_rewards` | — | `WHERE reward_type = 'app'; SUM(total_amount) by event_date` |
| 3.4 | Validator reward-to-cost ratio | `agg_daily_validators` | — | `total_rewards / (traffic_purchased * 17 / 1e6)` per validator |
| 3.5 | Unclaimed reward leakage | `agg_daily_rewards` | — | `WHERE reward_type IN ('unclaimed', 'dev_fund'); SUM(total_amount) / total minted` |
| 3.6 | Effective yield by participant type | `agg_daily_rewards` | — | `SUM(amount) / COUNT(DISTINCT provider)` by reward_type |
| 3.7 | SV reward distribution | `fact_rewards` | — | `WHERE reward_type = 'sv'; GROUP BY provider_party_id` |
| 3.8 | Phase transition impact | `agg_daily_rewards` | `dim_date` | Time series of total rewards; annotate phase boundaries |
| 3.9 | Dev fund percentage trend | `agg_daily_rewards` | — | `dev_fund_amount / total_minted` per day |

### Category 4: Transaction Economics & Fees

| # | Question | Primary Table | Join Tables | Query Pattern |
|---|----------|---------------|-------------|---------------|
| 4.1 | Total fee burn vs minting | `agg_daily_token_economics` | `agg_daily_rewards` | `cc_consumed vs SUM(total_amount) from rewards` |
| 4.3 | Transfer fee tier distribution | `fact_transfers` | — | Bucket by transfer_amount into fee tiers, count |
| 4.4 | Avg transaction cost by type | `agg_daily_network` | `agg_daily_token_economics` | `cc_consumed / transaction_count` per day |
| 4.5 | Bandwidth consumption trend | `fact_traffic_purchases` | — | `SUM(total_purchased) GROUP BY event_date` |
| 4.6 | Holding fee impact | `fact_amulet_lifecycle` | — | Track active UTXO count over time; correlate with archival rate |

### Category 5: Token Economics

| # | Question | Primary Table | Join Tables | Query Pattern |
|---|----------|---------------|-------------|---------------|
| 5.1 | Total CC supply over time | `agg_daily_token_economics` | — | Running SUM of net_supply_change |
| 5.2 | Holding distribution | `fact_amulet_lifecycle` | — | Active contracts by owner; top-N concentration |
| 5.3 | CC velocity | `fact_transfers` | `agg_daily_token_economics` | `SUM(transfer_amount) / estimated_supply` per period |
| 5.4 | UTXO fragmentation | `agg_daily_token_economics` | — | `net_utxo_change` cumulative; `avg(amount)` from fact_amulet_lifecycle |
| 5.5 | Locked Amulet percentage | Custom query on events_parsed | — | Filter for `LockedAmulet` template; created - archived |
| 5.7 | Net CC flow between validators | `fact_transfers` | `dim_validators` | Join transfers to validator parties; net flow matrix |

### Category 6-9: Validators, Governance, ANS, Strategic

| # | Question | Primary Table | Query Pattern |
|---|----------|---------------|---------------|
| 6.1 | Highest liveness scores | `dim_validators` | `ORDER BY rounds_with_liveness DESC` |
| 6.4 | Traffic vs parties correlation | `agg_daily_validators` | Scatter plot data: traffic_purchased vs unique_users |
| 7.1-7.4 | Governance metrics | `agg_daily_governance` + `fact_governance` | Various aggregations |
| 8.1-8.4 | ANS metrics | `fact_ans_entries` | Registration/renewal/expiry counts |
| 9.2 | Pareto distribution | `agg_daily_featured_apps` or `fact_transfers` | Top-N% activity share |
| 9.5 | Weekday vs weekend | `agg_daily_network` | `JOIN dim_date; GROUP BY is_weekend` |
| 9.6 | Anomaly detection | `agg_daily_network` | Rolling avg ± 2σ bands; flag outliers |

---

## 6. Advanced Analytics: Fee Calculation

Precise fee calculation requires correlating inputs and outputs within a single transaction (update_id). This is a more complex query pattern:

```sql
-- Per-transfer fee calculation
-- Within each AmuletRules_Transfer exercise, fee = SUM(archived amulets) - SUM(created amulets)
WITH transfer_events AS (
  SELECT
    update_id,
    event_date,
    SUM(CASE
      WHEN template_id LIKE '%Splice.Amulet:Amulet' AND event_type = 'archived'
      THEN CAST(JSON_VALUE(payload, '$.amount.initialAmount') AS FLOAT64)
      ELSE 0
    END) AS total_inputs,
    SUM(CASE
      WHEN template_id LIKE '%Splice.Amulet:Amulet' AND event_type = 'created'
      THEN CAST(JSON_VALUE(payload, '$.amount.initialAmount') AS FLOAT64)
      ELSE 0
    END) AS total_outputs
  FROM `transformed.events_parsed`
  WHERE update_id IN (
    SELECT DISTINCT update_id
    FROM `transformed.events_parsed`
    WHERE choice = 'AmuletRules_Transfer'
      AND event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  )
  AND event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY update_id, event_date
)
SELECT
  event_date,
  COUNT(*) AS transfer_count,
  SUM(total_inputs - total_outputs) AS total_fees_burned,
  AVG(total_inputs - total_outputs) AS avg_fee,
  SUM(total_outputs) AS total_transferred
FROM transfer_events
GROUP BY event_date;
```

This could be materialized as `analytics.agg_daily_transfer_fees` if the use case warrants it.

---

## 7. Incremental Processing Strategy

### 7.1 Schedule

All times UTC. Each step depends on the previous completing successfully.

| Time | Job | Source → Target | Est. Daily Cost |
|------|-----|----------------|-----------------|
| 00:00 | `ingest_events_from_gcs` | GCS → raw.events | ~$0.50 |
| 01:00 | `transform_raw_events` | raw.events → transformed.events_parsed | ~$1.00 |
| 02:00 | `build_fact_tables` | events_parsed → analytics.fact_* (9 tables) | ~$2-5 |
| 02:30 | `build_dim_tables` | fact_* → analytics.dim_* (4 tables) | ~$0.50 |
| 03:00 | `build_agg_tables` | fact_* → analytics.agg_* (6 tables) | ~$0.50 |

**Total estimated daily cost**: ~$5-8/day (~$150-240/month)

### 7.2 Incremental Pattern for Fact Tables

Every fact table uses the same pattern — scan only the last day from events_parsed and dedup:

```sql
INSERT INTO `analytics.fact_XXXX` (...)
SELECT ...
FROM `transformed.events_parsed`
WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND template_id LIKE '%TEMPLATE_FILTER%'   -- clustering prunes efficiently
  AND event_type = 'created'                  -- clustering prunes efficiently
  AND NOT EXISTS (
    SELECT 1 FROM `analytics.fact_XXXX` f
    WHERE f.event_id = events_parsed.event_id
      AND f.event_date = events_parsed.event_date
  );
```

**Why this is cheap**:
1. `event_date >= yesterday` → partition pruning (scans ~1 day, not 10+ TB)
2. `template_id LIKE '%...'` → clustering eliminates most blocks
3. `event_type = '...'` → clustering further reduces scan
4. Net result: each fact table scans perhaps 1-10 GB per day

### 7.3 Aggregate Table Incremental Pattern

Aggregates use MERGE (upsert) to update the current day:

```sql
MERGE `analytics.agg_daily_XXXX` T
USING (
  SELECT event_date, ... aggregations ...
  FROM `analytics.fact_XXXX`
  WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY event_date
) S
ON T.event_date = S.event_date
WHEN MATCHED THEN
  UPDATE SET ... = S....
WHEN NOT MATCHED THEN
  INSERT (...) VALUES (...);
```

### 7.4 Backfill Strategy

For initial population of analytics tables (one-time, from the full history):

1. **Fact tables**: Run without the `event_date >= ...` filter. Process in monthly chunks to control cost:
   ```sql
   -- Example: backfill one month at a time
   INSERT INTO analytics.fact_rewards (...)
   SELECT ... FROM transformed.events_parsed
   WHERE event_date BETWEEN '2024-06-01' AND '2024-06-30'
     AND template_id LIKE '%RewardCoupon%';
   ```
   Estimated total backfill cost: ~$50-100 (one-time)

2. **Dimension tables**: Run `CREATE OR REPLACE` once.

3. **Aggregate tables**: Run once over the full fact tables after backfill.

### 7.5 Idempotency & Recovery

- All incremental queries use `NOT EXISTS` dedup → safe to re-run
- If a day's pipeline fails, simply re-run the next day (2-day lookback catches up)
- For longer outages, extend the lookback window: `INTERVAL 3 DAY` etc.
- The `ingestion_state` table tracks pipeline position for monitoring

---

## 8. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Create `analytics` dataset in BigQuery
- [ ] Implement and backfill all 9 fact tables
- [ ] Validate fact table row counts against known template distributions
- [ ] Investigate JSON payload structures for each template to finalize field extraction paths

### Phase 2: Dimensions & Aggregates (Week 2)
- [ ] Build and populate all 4 dimension tables
- [ ] Build and populate all 6 aggregate tables
- [ ] Create BigQuery scheduled queries for daily incremental updates
- [ ] Set up monitoring for the analytics pipeline

### Phase 3: Dashboard & Analysis (Week 3)
- [ ] Build Looker Studio (or equivalent) dashboards connecting to aggregate tables
- [ ] Implement the priority business questions (1.1, 2.2, 3.1, 4.1, 5.1, 6.1)
- [ ] Create saved queries / views for the remaining business questions
- [ ] Document dashboard access and interpretation

### Phase 4: Advanced Analytics (Week 4+)
- [ ] Implement precise fee calculation (section 6)
- [ ] Build party cohort analysis for retention (1.2)
- [ ] Build anomaly detection queries (9.6)
- [ ] Implement network effect correlation analysis (9.1, 9.3)
- [ ] Add LockedAmulet tracking for escrow analysis (5.5)

---

## 9. Important Caveats & Open Items

### 9.1 JSON Payload Field Paths

The field paths in this plan (e.g., `JSON_VALUE(payload, '$.amount')`) are based on documentation and sampling. **Before implementing each fact table, we must validate the exact payload structure** by running:

```sql
SELECT
  template_id,
  JSON_KEYS(payload) AS top_level_keys,
  payload
FROM `transformed.events_parsed`
WHERE template_id LIKE '%TARGET_TEMPLATE%'
  AND event_type = 'created'
  AND event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
LIMIT 10;
```

Known variations:
- Amount field may be `$.amount`, `$.amuletAmount`, `$.amount.initialAmount`, or `$.reward`
- Party field may be `$.user`, `$.validator`, `$.provider`, `$.owner`, `$.sv`, or `$.beneficiary`
- Round field may be `$.round`, `$.round.number`, `$.roundNumber`
- These vary by template AND by migration epoch

### 9.2 Supply Calculation Complexity

True CC supply calculation is non-trivial because:
- Amulets decay via holding fees ($1/yr demurrage), so the face value at creation decays over time
- The actual value at archival depends on time elapsed since creation
- A precise supply tracker needs to account for `createdAt` round and current round to compute decay
- The `agg_daily_token_economics` table gives a rough approximation (initial amounts only)

### 9.3 Transfer Amount Extraction

Transfer amounts are embedded in the `choice_argument` of `AmuletRules_Transfer` exercise events. The exact JSON path depends on migration epoch. We should sample extensively before finalizing `fact_transfers`.

### 9.4 Cost Guardrails

- Set BigQuery **custom cost controls** (project-level query quota) to prevent accidental full table scans
- Use `--dry_run` flag when developing queries to estimate bytes scanned before executing
- All scheduled queries should have the `maximum_bytes_billed` parameter set (e.g., 50 GB per query)

---

## 10. Summary Architecture Diagram

```
                          CANTON MAINNET
                               │
                    ┌──────────┴──────────┐
                    │    Scan API          │
                    │  (/v2/updates)       │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                                  ▼
     ┌────────────────┐              ┌────────────────────┐
     │  GCS            │              │  Cloud Run         │
     │  canton-bucket  │              │  (backup, 15 min)  │
     │  /backfill/     │              │                    │
     │  /updates/      │              │                    │
     └───────┬────────┘              └────────┬───────────┘
             │  00:00 UTC                      │  streaming
             ▼                                 ▼
     ┌─────────────────────────────────────────────────┐
     │              raw.events                          │
     │       (3.6B+ rows, STRING types)                │
     │   Partitioned: event_date                        │
     │   Clustered: template_id, event_type, migration_id│
     └──────────────────────┬──────────────────────────┘
                            │  01:00 UTC
                            ▼
     ┌─────────────────────────────────────────────────┐
     │         transformed.events_parsed                │
     │     (TIMESTAMP, INT64, BOOL, JSON types)        │
     │   Partitioned: event_date                        │
     │   Clustered: template_id, event_type, migration_id│
     └──────────────────────┬──────────────────────────┘
                            │  02:00 UTC
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌──────────────┐ ┌──────────┐ ┌──────────────────┐
     │  FACT TABLES  │ │  DIMS    │ │  AGGREGATES      │
     │               │ │          │ │                  │
     │  fact_rewards │ │ dim_     │ │ agg_daily_       │
     │  fact_trans.. │ │ parties  │ │ network          │
     │  fact_traffic │ │ dim_     │ │ agg_daily_       │
     │  fact_app_act │ │ valid..  │ │ rewards          │
     │  fact_amulet  │ │ dim_     │ │ agg_daily_       │
     │  fact_mining  │ │ feat..   │ │ featured_apps    │
     │  fact_govern  │ │ dim_date │ │ agg_daily_       │
     │  fact_valid.. │ │          │ │ token_economics  │
     │  fact_ans     │ │          │ │ agg_daily_       │
     │               │ │          │ │ validators       │
     │  02:00 UTC    │ │ 02:30    │ │ agg_daily_       │
     │               │ │          │ │ governance       │
     └──────────────┘ └──────────┘ │  03:00 UTC       │
                                   └──────────────────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  DASHBOARDS   │
                                   │  & NOTEBOOKS  │
                                   │              │
                                   │  Looker Studio│
                                   │  Colab / JN   │
                                   │  Ad-hoc SQL   │
                                   └──────────────┘
```

---

## 11. Business Questions Checklist

Total: 48 questions across 9 categories.

| Category | Count | Key Tables |
|----------|-------|------------|
| 1. Network Growth & Health | 7 | agg_daily_network, dim_parties, dim_validators |
| 2. Featured App Ecosystem | 8 | agg_daily_featured_apps, dim_featured_apps, fact_featured_app_activity |
| 3. Rewards Economics | 9 | agg_daily_rewards, fact_rewards |
| 4. Transaction Economics | 6 | agg_daily_token_economics, fact_transfers, fact_traffic_purchases |
| 5. Token Economics | 7 | agg_daily_token_economics, fact_amulet_lifecycle |
| 6. Validator Operations | 6 | agg_daily_validators, dim_validators |
| 7. Governance | 5 | agg_daily_governance, fact_governance |
| 8. ANS | 4 | fact_ans_entries |
| 9. Strategic/Cross-cutting | 7 | Multiple (cross-table joins) |

Every question in the brainstorm is answerable with this analytics infrastructure.
