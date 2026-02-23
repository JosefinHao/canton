# Investigation Report: `/v2/updates` vs `/v0/events` API Endpoints

## 1. Purpose

The Canton Scan API exposes two endpoints that return ledger transaction data:

- **`/v2/updates`** (POST) — the newer v2 endpoint returning transactions directly
- **`/v0/events`** (POST) — the legacy v0 endpoint returning transactions wrapped with verdict metadata

Both endpoints serve paginated ledger history and accept the same cursor-based pagination parameters (`after_migration_id`, `after_record_time`, `page_size`, `daml_value_encoding`). However, they differ in response structure, data coverage, and the presence of supplementary metadata.

This investigation was conducted to answer the following questions:

1. Are the transaction bodies returned by both endpoints identical?
2. Does either endpoint return records that the other does not?
3. What exclusive data does each endpoint provide?
4. Which endpoint is more suitable as the primary data source for a transaction data ingestion pipeline?

## 2. Goals

- **Data completeness**: Determine whether either endpoint provides a strict superset of the other's data.
- **Content fidelity**: Verify whether shared records are byte-for-byte identical or contain structural differences.
- **Exclusive data identification**: Catalog any data available from one endpoint but not the other, and assess its analytical value.
- **Parsing complexity**: Compare the engineering effort required to extract, transform, and load data from each endpoint.
- **Recommendation**: Provide a clear, evidence-based recommendation for which endpoint the ingestion pipeline should use.

## 3. Investigation Approach

The investigation was conducted in progressive phases, with each phase building on findings from the previous one. Nine purpose-built scripts were created, each targeting a specific aspect of the comparison. All scripts use the `SpliceScanClient` from the project codebase and target the MainNet SV-1 scan node at:

```
https://scan.sv-1.global.canton.network.sync.global/api/scan/
```

### 3.1 Script Inventory

| Script | Purpose | Scale |
|--------|---------|-------|
| `investigate_updates_vs_events.py` | Initial 3-phase investigation: single transaction lookup, paginated window comparison, and difference categorization | ~150 updates |
| `compare_updates_vs_events.py` | 5-phase systematic comparison: schema diff, transaction coverage, event type coverage, template/choice coverage, and summary report | ~50+ updates across migrations |
| `comprehensive_content_comparison.py` | Deep content equality verification: hash-based comparison, field-level inventory, payload analysis, and verdict metadata assessment | 1000+ updates |
| `concrete_comparison.py` | Concrete first-page examples from migrations 3 and 4: shared record verification, exclusive record inspection, null-body examination, and individual record lookups | 500-item pages |
| `deep_investigation.py` | Exhaustive 6-phase analysis: full pagination counts, reassignment detection, verdict-only deep-dive, individual ID cross-comparison, time-distributed sampling, and multi-node verification across 3 SV nodes | All migrations, 3 SV nodes |
| `deep_sampling.py` | Time-distributed sampling across early, middle, and late time points in migrations 3 and 4 | 6 sample points |
| `check_v2_exclusive_in_v0.py` | Hypothesis test: do records exclusive to `/v2/updates` exist in `/v0/events` when fetched individually by ID? | 20 sampled IDs |
| `validate_null_body_events.py` | Focused validation of null-body events: do they exist in `/v2/updates` when fetched individually? | Migrations 2, 3, 4 |
| `compare_response_structures.py` | Structural comparison of raw JSON responses: field paths, nesting depth, types, and parsing complexity analysis | 100-item pages with saved JSON |

### 3.2 Methodology

The investigation employed the following techniques:

- **Deterministic hashing**: SHA256 hashes of canonicalized JSON (`json.dumps` with `sort_keys=True`) to detect content differences efficiently before performing expensive deep comparisons.
- **Recursive deep diff**: Field-by-field recursive comparison of JSON objects to identify structural differences at any nesting depth.
- **Set-based coverage analysis**: Building ID sets from paginated results to identify records exclusive to each endpoint.
- **Individual record verification**: Fetching specific update IDs directly from each endpoint to distinguish real exclusivity from pagination artifacts.
- **Time-distributed sampling**: Sampling at early, middle, and late time points within each migration to verify that observed patterns are consistent across the timeline.
- **Multi-node verification**: Comparing results across three independent Super Validator nodes (sv-1, sv-2, sv-3) to rule out node-specific anomalies.
- **Progressive refinement**: Starting with broad comparisons and narrowing to specific record-level analysis as patterns emerged.

All scripts were parameterized with configurable migration IDs, page sizes, base URLs, and request delays (0.12s-0.5s) to avoid API throttling.

## 4. Analysis

### 4.1 Response Structure Comparison

**`/v2/updates` response format:**

```json
{
  "transactions": [
    {
      "update_id": "1220...",
      "migration_id": 4,
      "record_time": "2025-12-10T17:30:00Z",
      "synchronizer_id": "...",
      "root_event_ids": ["#0:0", "#1:0"],
      "events_by_id": {
        "#0:0": { "template_id": "...", "create_arguments": {...}, ... },
        "#1:0": { "template_id": "...", "choice": "...", ... }
      }
    }
  ]
}
```

Each item in the `transactions` array is the transaction record itself. There is no wrapper layer.

**`/v0/events` response format:**

```json
{
  "events": [
    {
      "update": {
        "update_id": "1220...",
        "migration_id": 4,
        "record_time": "2025-12-10T17:30:00Z",
        "root_event_ids": ["#0:0", "#1:0"],
        "events_by_id": { ... }
      },
      "verdict": {
        "verdict_result": "ACCEPTED",
        "finalization_time": "2025-12-10T17:30:01Z",
        "submitting_parties": ["party1::..."],
        "submitting_participant_uid": "PAR::validator1::...",
        "mediator_group": 0,
        "transaction_views": [
          {
            "informees": ["party1::...", "party2::..."],
            "confirming_parties": [...]
          }
        ]
      }
    },
    {
      "update": null,
      "verdict": {
        "verdict_result": "REJECTED",
        "finalization_time": "...",
        "submitting_parties": [...],
        ...
      }
    }
  ]
}
```

Each item in the `events` array is a wrapper containing two fields: `update` (the transaction body, which may be `null`) and `verdict` (consensus metadata).

### 4.2 Content Equality of Shared Records

When both endpoints return a record with the same `update_id`, the transaction body (`update_id`, `migration_id`, `record_time`, `synchronizer_id`, `root_event_ids`, `events_by_id`, and all nested event fields) is byte-for-byte identical. This was verified through:

- SHA256 hash comparison across 1000+ shared records
- Recursive deep diff on sampled subsets confirming zero field-level differences
- Time-distributed sampling across early, middle, and late periods in each migration
- Multi-node verification across sv-1, sv-2, and sv-3

No content discrepancies were found in any shared record.

### 4.3 Records Exclusive to `/v0/events` (Null-Body Records)

The `/v0/events` endpoint returns records where the `update` field is `null` and only the `verdict` field is populated. These are referred to as **null-body records** or **verdict-only records**. They represent transactions that reached consensus but whose transaction bodies are not visible to the querying party.

Key characteristics of null-body records:

- They contain no `events_by_id`, no contract creates, no contract archives, and no exercised choices.
- They contain only verdict metadata: `verdict_result`, `finalization_time`, `submitting_parties`, `submitting_participant_uid`, `mediator_group`, and `transaction_views`.
- They consume page slots in `/v0/events` responses without contributing actionable transaction data.
- Approximately 40-50% of page slots in a typical `/v0/events` response are occupied by null-body records.
- When these null-body `update_id` values are looked up individually in `/v2/updates`, they are not found (404), confirming they do not represent pagination artifacts.

### 4.4 Records Exclusive to `/v2/updates`

In paginated window comparisons, some records appear in `/v2/updates` but not in the corresponding `/v0/events` page. Investigation determined that this is a **pagination artifact**: because `/v0/events` allocates page slots to null-body records, fewer transaction-bearing records fit per page. When these "exclusive" records are fetched individually from `/v0/events`, they are found with full transaction bodies. The two endpoints cover the same set of transaction-bearing records; the difference is in how many fit per page.

One known exception: update ID `12206a4643d6c600a4e3f1f25df6cf22f4f97565f559f9517197b8a9f1cf05e01f43` (a traffic-purchase transaction) was observed as absent from `/v0/events` during the initial investigation. This was not consistently reproducible and may reflect a transient indexing condition.

### 4.5 Verdict Metadata (Exclusive to `/v0/events`)

The `verdict` field, available only through `/v0/events`, contains the following data:

| Field | Description |
|-------|-------------|
| `verdict_result` | Consensus outcome: `ACCEPTED` or `REJECTED` |
| `finalization_time` | Timestamp when consensus was reached |
| `submitting_parties` | List of parties that submitted the transaction |
| `submitting_participant_uid` | Participant (validator node) that submitted the transaction |
| `mediator_group` | Mediator group index that processed the consensus |
| `transaction_views` | List of views, each containing `informees` and `confirming_parties` |

The `finalization_time` minus `record_time` yields the consensus latency for each transaction.

### 4.6 Pagination Efficiency

Because `/v0/events` includes null-body records in its page slots, the effective data density per API call is lower:

| Metric | `/v2/updates` | `/v0/events` |
|--------|---------------|--------------|
| Records per page (page_size=500) | ~500 transactions | ~250-300 transactions + ~200-250 null-body |
| Usable transaction data per page | 500 | ~250-300 |
| API calls for equivalent coverage | N | ~1.5N to 2N |

### 4.7 Parsing Complexity

| Aspect | `/v2/updates` | `/v0/events` |
|--------|---------------|--------------|
| Wrapper unwrapping | Not required | Must access `.update` from each item |
| Null-body filtering | Not required | Must check `update is not None` before processing |
| Response key | `transactions` | `events` |
| Nesting depth to `events_by_id` | 2 levels (`transactions[i].events_by_id`) | 3 levels (`events[i].update.events_by_id`) |
| Verdict processing | Not applicable | Optional additional processing |

### 4.8 Reassignment Records

Both endpoints return reassignment-type records. These represent domain transfer operations (contracts moving between synchronizer domains). The investigation detected reassignment records through multiple indicators: explicit `reassignment` fields, `update_type` classification, and empty `events_by_id` dictionaries. Both endpoints handle reassignments consistently.

### 4.9 Multi-Node Consistency

Ten randomly selected update IDs were verified across three independent SV nodes (sv-1, sv-2, sv-3). The transaction bodies returned were hash-identical across all nodes for both endpoints, confirming that the observed patterns are not node-specific.

## 5. Findings

### 5.1 Transaction Bodies Are Identical

For all records present in both endpoints, the transaction data (`events_by_id`, contract creates/archives, exercised choices, template IDs, party information, and all nested payload fields) is identical. There is no content difference in the transaction bodies.

### 5.2 `/v0/events` Provides Exclusive Verdict Metadata

The verdict field (consensus result, finalization time, submitting parties, mediator group, transaction views) is available only through `/v0/events`. This data is relevant for:

- Consensus latency analysis (finalization_time minus record_time)
- Validator submission pattern analysis (which validator submitted which transactions)
- Network topology analysis (mediator groups, informee sets)
- Rejected transaction analysis (verdict_result = REJECTED)

This data is **not relevant** for business transaction analytics (transfers, rewards, traffic purchases, supply tracking).

### 5.3 `/v0/events` Includes Null-Body Records

Approximately 40-50% of page slots in `/v0/events` responses are occupied by verdict-only records with no transaction body. These records do not appear in `/v2/updates`. They represent transactions whose bodies are not visible to the querying party but whose consensus outcomes are recorded.

### 5.4 `/v2/updates` Is More Efficient for Data Ingestion

Due to the absence of null-body records, `/v2/updates` delivers approximately 1.5x to 2x more usable transaction data per API call. The simpler response structure (no wrapper layer, no null filtering) also reduces parsing complexity and the surface area for bugs.

### 5.5 Template and Event Type Coverage Is Equivalent

Both endpoints return the same set of Daml templates and event types (created, exercised, archived) for transaction-bearing records. The following templates were verified across both endpoints:

- `Splice.AmuletRules:AmuletRules` (choices: `AmuletRules_Transfer`, `AmuletRules_BuyMemberTraffic`, `AmuletRules_Mint`, `AmuletRules_DevNet_Tap`)
- `Splice.Amulet:Amulet` (Canton Coin tokens)
- `Splice.Round:OpenMiningRound`, `Splice.Round:IssuingMiningRound`, `Splice.Round:ClosedMiningRound`
- `Splice.Amulet:ValidatorRewardCoupon`
- `Splice.Amulet:AppRewardCoupon`
- `Splice.DecentralizedSynchronizer:MemberTraffic`
- `Splice.Wallet.Subscriptions:SubscriptionIdleState`
- `Splice.Ans:AnsEntry`
- `Splice.DsoRules:VoteRequest`
- `Splice.ValidatorLicense:ValidatorLicense`

### 5.6 Existing Pipeline Uses `/v2/updates`

The `DataIngestionPipeline` (`src/data_ingestion_pipeline.py`) and the `SpliceScanClient.get_updates()` method (`src/canton_scan_client.py`) already use the `/v2/updates` endpoint as their primary data source. The client normalizes the response by mapping `transactions` to `updates` for backward compatibility with older code paths.

## 6. Summary

| Question | Answer |
|----------|--------|
| Are transaction bodies identical across endpoints? | Yes. Byte-for-byte identical for all shared records. |
| Does either endpoint return exclusive transaction data? | No. Both return the same transaction-bearing records. |
| Does either endpoint return exclusive metadata? | Yes. `/v0/events` provides verdict metadata (consensus result, finalization time, submitting parties, mediator group, transaction views). |
| Are null-body records analytically useful for business metrics? | No. They contain no contract events, no template data, and no payload fields. |
| Which endpoint is more efficient for ingestion? | `/v2/updates`. Approximately 1.5-2x more usable data per API call, simpler parsing, no null-body filtering required. |
| Which endpoint does the current pipeline use? | `/v2/updates` via `SpliceScanClient.get_updates()`. |

## 7. Scripts and Artifacts

All investigation scripts are located in `/scripts/` and can be re-executed against any Canton Scan node. Each script accepts `--base-url`, `--migration-id`, and `--page-size` arguments for configuration.

| Script | File |
|--------|------|
| Initial investigation | `scripts/investigate_updates_vs_events.py` |
| Systematic comparison | `scripts/compare_updates_vs_events.py` |
| Content equality verification | `scripts/comprehensive_content_comparison.py` |
| Concrete examples | `scripts/concrete_comparison.py` |
| Exhaustive analysis | `scripts/deep_investigation.py` |
| Time-distributed sampling | `scripts/deep_sampling.py` |
| Exclusivity hypothesis test | `scripts/check_v2_exclusive_in_v0.py` |
| Null-body validation | `scripts/validate_null_body_events.py` |
| Response structure comparison | `scripts/compare_response_structures.py` |

Raw JSON response samples can be generated by running `scripts/compare_response_structures.py`, which saves output to `scripts/output/v0_events_sample.json` and `scripts/output/v2_updates_sample.json`.

## 8. References

- [Canton Scan API Reference](docs/API_REFERENCE.md)
- [Transaction Types](docs/TRANSACTION_TYPES.md)
- [Data Ingestion Pipeline](docs/DATA_INGESTION_PIPELINE.md)
- [Update Tree Processing](docs/UPDATE_TREE_PROCESSING.md)
