# Plan: Comprehensive Comparison of `/v2/updates` vs `/v0/events`

## Goal
Determine definitively whether we can rely solely on `/v0/events` or need both endpoints, by comparing every dimension of the data they return.

## Approach
Build a single script (`scripts/compare_updates_vs_events.py`) that runs a battery of tests across multiple time windows and transaction types, producing a structured report. The script will be divided into 5 phases.

---

## Phase 1: Schema & Field Comparison (per-update deep diff)

**What**: For a sample of ~50 individual update_ids, fetch from both endpoints and do a recursive key-by-key diff.

**Tests**:
1. **Top-level keys**: Compare the set of keys in the response from `GET /v2/updates/{id}` vs `GET /v0/events/{id}`. We already know events wraps in an `update` + `verdict` structure — catalog every key difference.
2. **Update-level fields**: After unwrapping, compare keys like `update_id`, `migration_id`, `workflow_id`, `record_time`, `synchronizer_id`, `effective_at`, `root_event_ids`, `trace_context`. Flag any field present in one but not the other.
3. **Event-level fields**: For each event in `events_by_id`, compare the full set of keys. Check: `event_type`, `event_id`, `contract_id`, `template_id`, `package_name`, `choice`, `choice_argument`, `exercise_result`, `create_arguments`, `child_event_ids`, `consuming`, `acting_parties`, `signatories`, `observers`, `witness_parties`, `interface_id`, `reassignment_counter`, `source_synchronizer`, `target_synchronizer`, `unassign_id`, `submitter`, `created_at`.
4. **Value equality**: For every shared field, assert value equality. Report any value mismatches.
5. **Verdict field analysis**: Catalog every field inside the `verdict` object (only in events endpoint). Determine what unique information it provides (finalization_time, submitting_parties, transaction_views, etc.).

**Sampling strategy**: Pick updates spread across different time periods (early history, mid, recent) and different transaction types.

---

## Phase 2: Transaction Coverage (set comparison over large windows)

**What**: Over several large, non-overlapping time windows, fetch ALL update_ids from both endpoints and compare sets.

**Tests**:
1. **Same time window, same pagination**: For 3 distinct 1-hour windows (early, mid, recent data), paginate fully through both endpoints. Compare the set of `update_id`s.
2. **Count parity**: Assert that both endpoints return the same count of transactions per window.
3. **Ordering**: Verify both endpoints return updates in the same order (by `migration_id`, `record_time`).
4. **Edge of window**: Check that cursor-based pagination produces consistent boundaries (no off-by-one between endpoints).

---

## Phase 3: Event Type Coverage

**What**: Verify that both endpoints handle all event types identically.

**Tests**:
1. **Created events**: Find updates containing `created_event` events. Compare `create_arguments`, `signatories`, `observers`, `created_at` between endpoints.
2. **Exercised events**: Find updates with `exercised_event`. Compare `choice`, `choice_argument`, `exercise_result`, `acting_parties`, `consuming`, `child_event_ids`.
3. **Reassignment events**: Search for updates with `reassignment_counter > 0` or containing `assign`/`unassign` events. These are the most likely to differ between endpoints. Compare `source_synchronizer`, `target_synchronizer`, `unassign_id`, `submitter`.
4. **Archive-only events**: Find exercised events where `choice == "Archive"` and `consuming == true`. Ensure both endpoints represent these identically.

---

## Phase 4: Template & Choice Coverage

**What**: Ensure both endpoints return the same data for every template/choice combination we care about.

**Tests**:
1. **Collect template_id/choice pairs**: Over a large sample, build the set of unique `(template_id, choice)` pairs from each endpoint. Compare sets.
2. **Per-template spot check**: For each unique template_id, pick one representative update and do a Phase-1-style deep diff.
3. **Key templates to verify** (based on our analytics needs):
   - `Splice.AmuletRules:AmuletRules` / `AmuletRules_BuyMemberTraffic`
   - `Splice.AmuletRules:AmuletRules` / `AmuletRules_Transfer`
   - `Splice.Amulet:Amulet` / created events
   - `Splice.Round:OpenMiningRound` / various choices
   - `Splice.Round:IssuingMiningRound` / various choices
   - `Splice.Round:ClosedMiningRound` / various choices
   - `Splice.ValidatorLicense:*` / various
   - `Splice.DecentralizedSynchronizer:MemberTraffic` / created
   - `Splice.Amulet:ValidatorRewardCoupon` / created
   - `Splice.Amulet:AppRewardCoupon` / created
   - Any `AmuletNameService` templates

---

## Phase 5: Summary Report

**What**: Aggregate all findings into a clear decision report.

**Output**:
1. **Field inventory table**: Every field, which endpoint(s) return it, sample values.
2. **Coverage summary**: Total transactions compared, any set differences.
3. **Value mismatch summary**: Any fields where values differed between endpoints.
4. **Verdict field assessment**: What unique data lives only in `verdict`, and do we need it.
5. **Recommendation**: "Events only", "Updates only", or "Both needed" — with justification.

---

## Implementation Details

- **Script**: `scripts/compare_updates_vs_events.py`
- **Reuses**: `src/canton_scan_client.py` (existing API client)
- **Output**: Prints structured report to stdout; optionally saves JSON report to `output/comparison_report.json`
- **CLI args**:
  - `--sample-size N` (number of individual updates to deep-diff, default 50)
  - `--window-minutes M` (size of each time window for coverage test, default 60)
  - `--num-windows W` (number of time windows to test, default 3)
  - `--phase {1,2,3,4,5,all}` (run specific phase or all)
  - `--output-json PATH` (save structured results)
- **No BigQuery dependency**: Runs entirely against the Scan API
- **Rate limiting**: 0.5s delay between individual GET requests to avoid throttling
