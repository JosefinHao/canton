# Canton On-Chain Data Exploration Report

## 1. Overview

This document presents the results of a systematic exploration of Canton Network
on-chain data conducted via the Splice Network Scan API. The exploration was
performed to build a comprehensive understanding of the transaction type
landscape, event structures, and data patterns across all five migration epochs
(0 through 4) prior to loading the full historical dataset into BigQuery.

### Objective

Catalog every template, choice, and event structure present on the Canton Network
ledger, establish a mutually exclusive categorization system suitable for
business analytics, and document data patterns that inform the design of
downstream transformation and analysis pipelines.

### Scope

- **Data source**: Splice Network Scan API (`/v2/updates` endpoint) on MainNet
  SV-1 node
- **Time range**: 2024-06-24 (Migration 0 start) through 2026-02-27 (Migration
  4 most recent)
- **Sampling**: 33 sample windows across 5 migrations, 165,000 updates,
  1,374,349 events
- **Scripts**: `scripts/explore_transaction_types.py`,
  `scripts/explore_traffic_purchase.py`

---

## 2. Data Source and API Structure

### 2.1 Scan API Endpoint

All data was retrieved from the `/v2/updates` POST endpoint:

```
https://scan.sv-1.global.canton.network.sync.global/api/scan/
```

This endpoint returns paginated ledger transactions. Each request accepts
`after_migration_id`, `after_record_time`, `page_size` (max 500), and
`daml_value_encoding` parameters. See
[UPDATES_VS_EVENTS_INVESTIGATION.md](./UPDATES_VS_EVENTS_INVESTIGATION.md)
for a detailed comparison of `/v2/updates` vs `/v0/events`.

### 2.2 Response Structure

Each API response contains a `transactions` array. Each transaction object has
the following top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `update_id` | string | Unique identifier (hex-encoded hash) |
| `migration_id` | integer | Migration epoch (0-4) |
| `record_time` | string | ISO 8601 timestamp when the transaction was recorded |
| `effective_at` | string | ISO 8601 timestamp for the effective time of the transaction |
| `synchronizer_id` | string | Synchronizer that processed the transaction |
| `root_event_ids` | array | Entry points into the event tree |
| `events_by_id` | object | Map of event_id to event data |

All 165,000 sampled updates originated from a single synchronizer:
`global-domain::1220b1431ef217342db44d516bb9befde802be7d8899637d29...`

### 2.3 Event Format

Events within `events_by_id` use a flat structure. Event type is determined by
which fields are present:

| Event Type | Distinguishing Field | Description |
|------------|---------------------|-------------|
| Created | `create_arguments` present | A new contract is instantiated on the ledger |
| Exercised | `choice` present | A choice is exercised on an existing contract |
| Archived | `archived` is truthy | A contract is removed from the active contract set |

**Created event fields**: `template_id`, `contract_id`, `package_name`,
`create_arguments`, `signatories`, `observers`

**Exercised event fields**: `template_id`, `contract_id`, `choice`,
`choice_argument`, `exercise_result`, `acting_parties`, `consuming`,
`child_event_ids`, `interface_id`, `signatories`, `observers`

**Archived event fields**: `template_id`, `contract_id`, `archived`

### 2.4 Template ID Format

Template IDs from the API include a package hash prefix:

```
3ca1343ab26b453d38c8adb70dca5f1ead8440c42b59b68f070786955cbf9ec1:Splice.Amulet:Amulet
```

The format is `{package_hash}:{module_name}:{entity_name}`. The bare template
name (used for categorization and matching) is the last two colon-separated
parts: `Splice.Amulet:Amulet`. Matching must use suffix/endswith comparison,
not exact equality, because the package hash prefix changes across migration
epochs as contract packages are upgraded.

### 2.5 Event Tree Structure

Events within a transaction form a tree. The `root_event_ids` field identifies
the tree roots. Each exercised event may have `child_event_ids` pointing to
events created as a result of the exercise. Traversal is preorder (depth-first):
process the current node, then recurse into children.

Event tree depth distribution across the full sample:

| Depth | Count | Percentage |
|-------|-------|------------|
| 0 (root) | 289,989 | 21.1% |
| 1 | 713,871 | 51.9% |
| 2 | 272,420 | 19.8% |
| 3 | 98,053 | 7.1% |
| 4 | 10 | <0.01% |
| 5 | 6 | <0.01% |

The majority of events occur at depth 1 (direct children of the root exercise),
with meaningful activity at depths 2 and 3. Trees deeper than 3 are extremely
rare.

---

## 3. Sampling Methodology

### 3.1 Strategy

With 3.6B+ rows across 10+ TB, exhaustive scanning through the API is
impractical. The exploration used targeted sampling at strategic time points
within each migration to maximize coverage of the template and choice landscape.

The sampling strategy has three components:

1. **Migration boundary sampling**: Multiple pages from the start of each
   migration (0-4) to discover templates/choices that exist at the beginning
   of each epoch.

2. **Temporal sampling**: For long-running migrations (3 and 4), sample at
   many time windows spread across the full timeline — from the first minutes
   through the most recent data — to capture the evolution of the transaction
   mix over time.

3. **Schema evolution detection**: Compare payload field structures for the
   same template across different migrations to detect contract version changes
   introduced at migration boundaries.

### 3.2 Sample Points

33 sample windows were defined across 5 migrations:

| Migration | Windows | Time Range | Notes |
|-----------|---------|------------|-------|
| 0 | 3 (start, mid, late) | 2024-06-24 – 2024-08-01 | Initial synchronizer |
| 1 | 3 (start, mid, late) | 2024-10-16 – 2024-11-01 | Short-lived migration |
| 2 | 3 (start, mid, late) | 2024-12-11 – 2025-01-01 | Short-lived migration |
| 3 | 12 (early through late) | 2025-06-25 – 2025-11-01 | Long-running, high growth |
| 4 | 12 (early through recent) | 2025-12-10 – 2026-02-27 | Current migration |

Each window fetches up to 10 pages of 500 updates (5,000 updates per window).
All 33 windows returned the full 5,000 updates, yielding exactly 165,000 total
updates.

### 3.3 Sampling Parameters

| Parameter | Value |
|-----------|-------|
| Pages per sample window | 10 |
| Updates per page | 500 |
| Updates per window | 5,000 |
| Total sample windows | 33 |
| Total updates sampled | 165,000 |
| Total events sampled | 1,374,349 |
| API request delay | 0.15 seconds |
| Total runtime | ~6 minutes |

### 3.4 Limitations

- **Sample-based frequencies**: All counts and percentages are from the sampled
  windows, not from the complete dataset. They are directionally accurate but
  not exact global counts.
- **Temporal skew**: The aggregate percentages are biased toward periods with
  lower event density (early migration windows). Recent windows produce 5-10x
  more events per 5,000 updates than early windows.
- **Rare events underrepresented**: Templates with very low frequency (e.g.,
  Wallet & Subscriptions: 10 events, Name Service: 131 events) may have
  different proportional representation in the full dataset.
- **Per-party analysis not possible**: The exploration counts events by
  template and choice but does not aggregate by party/provider fields within
  payloads.

---

## 4. Results: Aggregate Statistics

### 4.1 Summary

| Metric | Value |
|--------|-------|
| Total updates sampled | 165,000 |
| Updates with events | 165,000 (100%) |
| Updates without events | 0 |
| Total events sampled | 1,374,349 |
| Unique template IDs (with hash prefix) | 210 |
| Unique choices | 453 |
| Unique synchronizer IDs | 1 |
| Unique package names | 5 |

### 4.2 Package Names

| Package | Event Count | Percentage |
|---------|-------------|------------|
| `splice-amulet` | 1,236,925 | 90.0% |
| `splice-dso-governance` | 136,999 | 10.0% |
| `splice-util-batched-markers` | 284 | <0.1% |
| `splice-amulet-name-service` | 131 | <0.1% |
| `splice-wallet-payments` | 10 | <0.1% |

The `splice-amulet` package accounts for approximately 90% of all events. It
contains the core token contracts (Amulet, AmuletRules), reward coupons,
featured app templates, validator licensing, transfer infrastructure, and
external party contracts. The `splice-dso-governance` package handles DSO
governance, SV operations, and voting.

### 4.3 Migrations Timeline

| Migration | First Record Time | Sample Windows | Events Sampled | Avg Events/Update |
|-----------|------------------|----------------|----------------|-------------------|
| 0 | 2024-06-24T21:08:34 | 3 | 47,472 | 3.2 |
| 1 | 2024-10-16T13:24:18 | 3 | 57,592 | 3.8 |
| 2 | 2024-12-11T14:23:05 | 3 | 60,427 | 4.0 |
| 3 | 2025-06-25T13:44:34 | 12 | 541,963 | 9.0 |
| 4 | 2025-12-10T16:23:25 | 12 | 666,895 | 11.1 |

Event density per update increased approximately 3.5x from Migration 0 to
Migration 4. Within Migration 4, the density increased further from ~9.3
events/update (early) to ~19.6 events/update (10 weeks) and ~18.4
events/update (recent), driven primarily by growth in featured app activity.

---

## 5. Results: Transaction Type Categorization

### 5.1 Design Principles

The categorization system was designed with the following constraints:

1. **Mutually exclusive by template**: Each template appears in exactly one
   category. No event is counted in two categories.
2. **Business-analytics-oriented**: Categories map to identifiable business
   domains (rewards, featured apps, governance, etc.) rather than technical
   groupings.
3. **Reward recipient granularity**: Reward coupons are split by recipient type
   (app, validator, SV, unclaimed) rather than grouped into a single "rewards"
   bucket.
4. **Featured app granularity**: Featured app events are split by function
   (rights management, activity tracking, batched operations).
5. **Choice breakdowns within categories**: For templates that serve multiple
   business functions via different choices (e.g., `AmuletRules:AmuletRules`),
   the choice distribution is reported within the category.

### 5.2 Category Results

**Token Economics**

| Category | Events | % of Total | Description |
|----------|--------|------------|-------------|
| CC Coin Contracts | 358,711 | 26.1% | Amulet and LockedAmulet contract state changes |
| AmuletRules Exercises | 131,192 | 9.5% | Top-level token operations (Transfer, ComputeFees, etc.) |

CC Coin Contracts is the largest single category. It represents the actual token
state changes: creates correspond to new coin outputs (from transfers, minting),
and archives correspond to consumed inputs. The top exercised choices on these
contracts are Archive (87.9%) and LockedAmulet_Unlock (11.8%).

AmuletRules Exercises captures the root-level operations that trigger token
state changes. The choice breakdown is:

| Choice | Count | % of AmuletRules |
|--------|-------|------------------|
| AmuletRules_Transfer | 99,704 | 76.0% |
| AmuletRules_ComputeFees | 19,269 | 14.7% |
| AmuletRules_Fetch | 3,718 | 2.8% |
| AmuletRules_ConvertFeaturedAppActivityMarkers | 3,519 | 2.7% |
| AmuletRules_ClaimExpiredRewards | 2,036 | 1.6% |
| AmuletRules_BuyMemberTraffic | 1,282 | 1.0% |
| AmuletRules_MiningRound_Close | 284 | 0.2% |
| AmuletRules_AdvanceOpenMiningRounds | 284 | 0.2% |
| AmuletRules_MiningRound_StartIssuing | 283 | 0.2% |
| AmuletRules_MiningRound_Archive | 276 | 0.2% |

Notable: The choice `AmuletRules_Mint` (previously assumed to exist for CC
minting) was not observed in any sample. Minting occurs as a side effect of
`AmuletRules_MiningRound_Close` and related round lifecycle choices.

**Rewards (by recipient)**

| Category | Events | % of Total | Templates |
|----------|--------|------------|-----------|
| App Rewards | 178,578 | 13.0% | `AppRewardCoupon` |
| Validator Rewards | 77,617 | 5.6% | `ValidatorRewardCoupon`, `ValidatorFaucetCoupon` |
| SV Rewards | 13,455 | 1.0% | `SvRewardCoupon` |
| Unclaimed Rewards & Dev Fund | 6,290 | 0.5% | `UnclaimedReward`, `UnclaimedDevelopmentFundCoupon` |
| **Total Rewards** | **275,940** | **20.1%** | |

Reward distribution by recipient:

| Recipient | Events | % of Rewards |
|-----------|--------|--------------|
| App Rewards | 178,578 | 64.7% |
| Validator Rewards | 77,617 | 28.1% |
| SV Rewards | 13,455 | 4.9% |
| Unclaimed / Dev Fund | 6,290 | 2.3% |

Validator reward sub-breakdown:

| Type | Events | % of Validator Rewards |
|------|--------|----------------------|
| Activity-based (`ValidatorRewardCoupon`) | 68,450 | 88.2% |
| Faucet grants (`ValidatorFaucetCoupon`) | 9,167 | 11.8% |

App reward coupon choices: Archive (83.7%), AppRewardCoupon_DsoExpire (16.3%).
The 16.3% DSO expiry rate indicates that approximately one in six app reward
coupons expires before being claimed.

**Featured App Ecosystem**

| Category | Events | % of Total | Templates |
|----------|--------|------------|-----------|
| Featured App Activity | 192,423 | 14.0% | `FeaturedAppActivityMarker` |
| Featured App Rights | 71,316 | 5.2% | `FeaturedAppRight` |
| Featured App Batched Markers | 284 | <0.1% | `BatchedMarkersProxy` |
| **Total Featured App** | **264,023** | **19.2%** | |

Featured app activity is the fastest-growing category on the network. The
`FeaturedAppRight` template is exercised exclusively with the choice
`FeaturedAppRight_CreateActivityMarker` (100.0%), meaning the sole purpose
of featured app right contracts is to create activity markers.

The ratio of App Reward events to Featured App Activity events is **0.93**,
indicating that nearly every activity marker generates a corresponding reward
coupon.

Activity density progression within Migration 4 (per 5,000-update window):

| Window | FeaturedAppActivityMarker Events | % of Window |
|--------|----------------------------------|-------------|
| M4 early (Dec 10) | 4,071 | 8.8% |
| M4 1hr | 4,584 | 11.7% |
| M4 4hr | 12,659 | 28.9% |
| M4 1week | 11,199 | 26.3% |
| M4 1month | 18,397 | 36.6% |
| M4 6weeks | 24,309 | 36.1% |
| M4 10weeks | 36,184 | 37.0% |
| M4 recent (Feb 27) | 35,837 | 39.1% |

Featured app activity grew approximately 9x in density over the first 10 weeks
of Migration 4 and stabilized at approximately 36,000-37,000 markers per 5,000
updates.

**Network Infrastructure**

| Category | Events | % of Total | Templates |
|----------|--------|------------|-----------|
| Mining Rounds | 22,682 | 1.7% | `OpenMiningRound`, `IssuingMiningRound`, `ClosedMiningRound`, `SummarizingMiningRound` |
| Traffic Purchases | 1,796 | 0.1% | `MemberTraffic` |

Mining rounds cycle through four states approximately every 10 minutes:
Open → Issuing → Closed → Summarizing. The `OpenMiningRound` template
dominates (92.5%) because rounds spend most of their lifecycle in the open
state and are frequently fetched via `OpenMiningRound_Fetch` (94.8% of
mining round choices).

**Validator Management**

| Category | Events | % of Total | Templates |
|----------|--------|------------|-----------|
| Validator Licensing | 58,250 | 4.2% | `ValidatorLicense`, `ValidatorRight` |
| Validator Liveness | 46,601 | 3.4% | `ValidatorLivenessActivityRecord` |

Validator licensing choices:
`ValidatorLicense_RecordValidatorLivenessActivity` (79.0%),
`ValidatorLicense_ReceiveFaucetCoupon` (16.2%),
`ValidatorLicense_UpdateMetadata` (3.7%),
`ValidatorLicense_ReportActive` (1.1%).

Validator liveness record dispositions: normal Archive (86.5%),
`ValidatorLivenessActivityRecord_DsoExpire` (13.5%). The 13.5% DSO
expiry rate indicates that approximately one in seven validators fails to
maintain its heartbeat before the liveness record expires.

**Governance**

| Category | Events | % of Total | Templates |
|----------|--------|------------|-----------|
| SV Operations | 74,796 | 5.4% | `SvStatusReport`, `SvNodeState`, `SvRewardState`, `AmuletPriceVote`, `SvOnboarding*`, `DsoBootstrap` |
| DSO Governance | 62,203 | 4.5% | `DsoRules`, `VoteRequest`, `Vote`, `Confirmation` |

DSO Governance is dominated by `DsoRules_SubmitStatusReport` (59.7%),
which is the mechanism by which Super Validators submit periodic status
reports. Other significant choices: `DsoRules_ConfirmAction` (9.2%),
`DsoRules_AmuletRules_ConvertFeaturedAppActivityMarkers` (6.2%),
`DsoRules_ReceiveSvRewardCoupon` (5.1%),
`DsoRules_ClaimExpiredRewards` (4.7%).

**Transfer & External Party**

| Category | Events | % of Total | Templates |
|----------|--------|------------|-----------|
| Transfer Infrastructure | 45,189 | 3.3% | `TransferPreapproval`, `AmuletAllocation`, `AmuletTransferInstruction`, `ExternalPartySetupProposal` |
| External Party | 32,825 | 2.4% | `ExternalPartyAmuletRules`, `TransferCommand`, `TransferCommandCounter` |

Transfer Infrastructure is dominated by `TransferPreapproval_Send` (82.7% of
choices). External Party operations are dominated by
`TransferFactory_Transfer` (84.3%), indicating that external parties primarily
use the network for executing transfers.

**Other**

| Category | Events | % of Total |
|----------|--------|------------|
| Name Service (ANS) | 131 | <0.01% |
| Wallet & Subscriptions | 10 | <0.01% |

These categories have minimal activity in the sampled data. The Name Service
sees occasional entry renewals and conversion rate updates. Wallet &
Subscriptions activity is negligible.

### 5.3 Categorization Coverage

All 1,374,349 sampled events were successfully categorized (**100.00%
coverage**). No uncategorized templates with 2 or more occurrences remained.

---

## 6. Results: Template Presence by Migration

### 6.1 Templates Present Across All Migrations

The following templates (by bare name) were observed in all five migrations:

- `Splice.Amulet:Amulet`
- `Splice.AmuletRules:AmuletRules`
- `Splice.DsoRules:DsoRules`
- `Splice.DSO.SvState:SvStatusReport`
- `Splice.ValidatorLicense:ValidatorLicense`
- `Splice.Round:OpenMiningRound`

### 6.2 Templates New in Migrations 3-4

The following templates were not observed in Migrations 0-2 samples and first
appeared in Migration 3 or 4:

| Template | First Seen | Category |
|----------|-----------|----------|
| `FeaturedAppActivityMarker` | M3 | Featured App Activity |
| `FeaturedAppRight` | M3 | Featured App Rights |
| `TransferPreapproval` | M3 | Transfer Infrastructure |
| `ValidatorLivenessActivityRecord` | M3 | Validator Liveness |
| `ExternalPartyAmuletRules` | M3 | External Party |
| `AmuletAllocation` | M3 | Transfer Infrastructure |
| `TransferCommand` | M3 | External Party |
| `TransferCommandCounter` | M3 | External Party |
| `BatchedMarkersProxy` | M3 | Featured App Batched Markers |
| `AmuletTransferInstruction` | M3 | Transfer Infrastructure |
| `UnclaimedDevelopmentFundCoupon` | M3 | Unclaimed Rewards & Dev Fund |
| `ExternalPartySetupProposal` | M3 | Transfer Infrastructure |
| `LockedAmulet` | M2/M3 | CC Coin Contracts |
| `UnclaimedReward` | M3 | Unclaimed Rewards & Dev Fund |

The introduction of featured app templates, transfer preapprovals, external
party contracts, and validator liveness tracking in Migrations 3-4 represents
a significant expansion of the network's functional capabilities.

### 6.3 Package Hash Changes Across Migrations

The same bare template name appears with different package hash prefixes in
different migrations. For example, `Splice.Amulet:Amulet` was observed with
the following prefixes:

| Migration | Package Hash Prefix |
|-----------|-------------------|
| 0-1 | `1446ffdf23326cef...` |
| 1-2 | `a36ef8888fb44caa...` (M1), multiple in M2 |
| 2-3 | `979ec710c3ae3a05...` |
| 3 | `511bd3bf23fab4e5...`, `a5b055492fb8f08b...`, `6e9fc50fb94e5675...` |
| 3-4 | `3ca1343ab26b453d...` |
| 4 | `67fac2f853bce8db...` (most recent) |

This confirms that contract packages are upgraded at migration boundaries and
sometimes within migrations. Any code that matches template IDs must use
suffix matching against the bare template name, not exact string equality.

---

## 7. Results: Schema Evolution

11 template-choice combinations showed field differences across migrations,
indicating contract version changes at migration boundaries. Key examples:

**AmuletRules_Transfer choice_argument** (M2 → M3):
- M2: 18 fields
- M3: 21 fields
- Added: `transfer.outputs[].lock.expiresAt`, `transfer.outputs[].lock.holders`,
  `transfer.outputs[].lock.optContext`

**AmuletAllocation created** (M3 → M4):
- M3: 22 fields
- M4: 31 fields
- Added: settlement metadata fields including `Verity.larIdentifier`,
  `Verity.loanIdentifier`, `id`, `operator`, and reason annotations

**ExternalPartyAmuletRules TransferFactory_Transfer choice_argument** (M3 → M4):
- M3: 34 fields
- M4: 40 fields
- Added: `expire-lock` context, `sending_party` metadata, `marketId` annotation

**DsoRules ConfirmAction choice_argument** (M3 → M4):
- M3: 15 fields
- M4: 19 fields
- Added: `dsoAction` fields for sender identification

These schema changes indicate that the transformation layer (`events_parsed`)
must account for field presence differences across migrations. Fields added in
later migrations will be null in earlier data.

---

## 8. Results: Event Tree Structures

### 8.1 Representative Transaction Trees

**CC Transfer** (root choice: `AmuletRules_Transfer`):
```
exercised: AmuletRules:AmuletRules [AmuletRules_Transfer]
├── exercised: Amulet:SvRewardCoupon [SvRewardCoupon_ArchiveAsBeneficiary]
└── created: Amulet:Amulet
```

**DSO Status Report** (root choice: `DsoRules_SubmitStatusReport`):
```
exercised: DsoRules:DsoRules [DsoRules_SubmitStatusReport]
├── exercised: DSO.SvState:SvStatusReport [Archive]
└── created: DSO.SvState:SvStatusReport
```

**Validator Metadata Update**:
```
exercised: ValidatorLicense:ValidatorLicense [ValidatorLicense_UpdateMetadata]
└── created: ValidatorLicense:ValidatorLicense
```

**DSO Bootstrap** (Migration 0 genesis):
```
exercised: DsoBootstrap:DsoBootstrap [DsoBootstrap_Bootstrap]
├── created: AmuletRules:AmuletRules
├── created: Ans:AnsRules
├── exercised: AmuletRules:AmuletRules [AmuletRules_Bootstrap_Rounds]
│   ├── created: Round:OpenMiningRound
│   ├── created: Round:OpenMiningRound
│   └── created: Round:OpenMiningRound
├── created: DsoRules:DsoRules
├── created: DSO.SvState:SvRewardState
├── created: DSO.AmuletPrice:AmuletPriceVote
├── created: DSO.SvState:SvStatusReport
└── created: DSO.SvState:SvNodeState
```

### 8.2 Transaction Type Identification

The primary type of a transaction is determined by the root exercised event's
template and choice:

| Root Choice | Transaction Type |
|-------------|-----------------|
| `AmuletRules_Transfer` | CC transfer between parties |
| `AmuletRules_BuyMemberTraffic` | Synchronizer bandwidth purchase |
| `AmuletRules_MiningRound_Close` | Mining round close (triggers minting) |
| `AmuletRules_ComputeFees` | Fee computation |
| `AmuletRules_ConvertFeaturedAppActivityMarkers` | Batch conversion of activity markers to rewards |
| `AmuletRules_ClaimExpiredRewards` | Claim of expired reward coupons |
| `FeaturedAppRight_CreateActivityMarker` | Featured app activity recording |
| `TransferPreapproval_Send` | Pre-approved transfer execution |
| `TransferFactory_Transfer` | External party transfer |
| `DsoRules_SubmitStatusReport` | SV status report submission |
| `DsoRules_ConfirmAction` | DSO governance action confirmation |
| `ValidatorLicense_RecordValidatorLivenessActivity` | Validator heartbeat |

---

## 9. Results: Business Insights

### 9.1 Reward Economics

Total reward events in sample: 275,940

| Recipient | Events | Share | Interpretation |
|-----------|--------|-------|----------------|
| Featured Apps | 178,578 | 64.7% | Apps earn the majority of CC rewards |
| Validators | 77,617 | 28.1% | Second largest reward recipient |
| Super Validators | 13,455 | 4.9% | Governance participation rewards |
| Unclaimed / Dev Fund | 6,290 | 2.3% | Low unclaimed rate indicates healthy claim behavior |

Validator rewards are 88.2% activity-based and 11.8% faucet grants.

### 9.2 Transaction Type Mix

Of 131,191 AmuletRules exercises (the top-level token operations):

| Operation | Count | Share |
|-----------|-------|-------|
| CC Transfers | 99,704 | 76.0% |
| Fee Computations | 19,269 | 14.7% |
| Other (Fetch, Convert, Claim, etc.) | 12,218 | 9.3% |

CC transfers dominate token operations at over three-quarters of all
AmuletRules exercises. No `AmuletRules_Mint` choice was observed; minting
occurs as part of the mining round close process.

### 9.3 Featured App Growth Trend

Featured app activity markers per 5,000-update window in Migration 4:

- Early (Dec 10, 2025): 4,071
- 6 weeks (Jan 24, 2026): 24,309
- 10 weeks (Feb 20, 2026): 36,184
- Recent (Feb 27, 2026): 35,837

This represents approximately a **9x increase** in activity density over 10
weeks, stabilizing at ~36,000 markers per 5,000 updates. Featured app activity
is now the single largest event type on the network by volume, surpassing CC
coin contract state changes in the most recent samples.

### 9.4 Network Activity Growth

Events per update across migrations:

| Period | Events/Update | Notes |
|--------|---------------|-------|
| M0 start | 3.0 | Governance-dominated |
| M0 late | 3.5 | |
| M1 | 3.8 | |
| M2 late | 4.4 | |
| M3 early | 5.4 | Featured apps begin |
| M3 late | 14.8 | |
| M4 early | 9.3 | Post-migration reset |
| M4 recent | 18.4 | Driven by featured app growth |

---

## 10. Data Infrastructure Considerations

### 10.1 Raw Data Format

Historical data is available in two formats from the Scan API:

- **`/v2/updates`**: Flat transaction structure, no null-body records,
  simpler parsing. Recommended for data ingestion.
- **`/v0/events`**: Wrapped format with verdict metadata, includes null-body
  records (40-50% of page slots). Provides consensus metadata not available
  in `/v2/updates`.

For backfill data that may include both formats, the transformation layer must
handle both: flat format (where `root_event_ids` and `events_by_id` are
top-level fields on the transaction) and wrapped format (where they are nested
under an `update` wrapper).

### 10.2 Key Fields for Transformation

Based on the exploration results, the following fields should be extracted in
the parsed events table:

| Field | Source | Purpose |
|-------|--------|---------|
| `template_id` (full) | Event | Full template identifier with package hash |
| `template_id` (bare) | Derived | `module:entity` for matching and categorization |
| `event_type` | Derived | `created`, `exercised`, or `archived` |
| `choice` | Exercised events | The choice exercised (e.g., `AmuletRules_Transfer`) |
| `category` | Derived | Business category from the categorization map |
| `effective_at` | Transaction | Effective timestamp (preferred over `record_time` for time-series) |
| `migration_id` | Transaction | Migration epoch |
| `update_id` | Transaction | Transaction identifier |
| `contract_id` | Event | Contract being acted upon |
| `package_name` | Created events | Package name (e.g., `splice-amulet`) |
| `signatories` | Event | Parties that signed |
| `acting_parties` | Exercised events | Parties that exercised the choice |
| `create_arguments` | Created events | Full payload (JSON) for downstream extraction |
| `choice_argument` | Exercised events | Full payload (JSON) for downstream extraction |
| `exercise_result` | Exercised events | Full result payload (JSON) |

### 10.3 Category-Specific Views

The 20 categories defined in Section 5 map directly to BigQuery views or
materialized views for domain-specific analysis:

- **Featured App Analysis**: Filter to `FeaturedAppActivityMarker` and
  `AppRewardCoupon` templates, extract `provider` field from payloads to
  identify individual apps.
- **Reward Economics**: Filter to all four reward categories, extract `amount`
  fields to compute CC value distributions.
- **Transfer Analysis**: Filter to `AmuletRules_Transfer` choice events,
  extract `amount`, sender/receiver parties.
- **Validator Health**: Filter to `ValidatorLivenessActivityRecord` and
  `ValidatorLicense` templates, compute liveness rates per validator.

### 10.4 Deduplication Considerations

The `effective_at` field is the preferred timestamp for ordering and
time-series analysis. The `update_id` field provides the unique identifier for
deduplication. For incremental ingestion, a watermark based on the most recent
`effective_at` or `record_time` successfully ingested can be used to avoid
reprocessing.

---

## 11. Methodology: Tools and Scripts

### 11.1 Exploration Script

**`scripts/explore_transaction_types.py`**: The primary exploration tool.
Samples Canton on-chain data across all migrations and produces:

- Per-migration sample summaries (updates, events, time ranges, top templates)
- Aggregated template frequency distribution
- Template × event type distribution
- Choice distribution for exercised events
- Template presence by migration matrix
- Event tree depth distribution
- Sample event tree structures from each migration
- Business-analytics-focused categorization with choice breakdowns
- Business insights summary (reward distribution, featured app ecosystem,
  transaction type mix)
- Schema evolution detection across migrations
- JSON report for offline analysis (`transaction_type_exploration.json`)
- Raw update samples for reference (`raw_update_samples.json`)

Usage:
```bash
python scripts/explore_transaction_types.py
python scripts/explore_transaction_types.py --pages-per-sample 20
python scripts/explore_transaction_types.py --migration 3 4
```

### 11.2 Traffic Purchase Deep-Dive Script

**`scripts/explore_traffic_purchase.py`**: Targeted exploration of traffic
purchase transactions (choice `AmuletRules_BuyMemberTraffic`). Extracts event
trees, payload fields, parties, and co-occurring templates for traffic
purchases specifically.

### 11.3 Supporting Investigation

**[UPDATES_VS_EVENTS_INVESTIGATION.md](./UPDATES_VS_EVENTS_INVESTIGATION.md)**:
Detailed comparison of `/v2/updates` vs `/v0/events` endpoints, conducted via
9 purpose-built scripts across 3 SV nodes. Established that transaction bodies
are byte-for-byte identical across endpoints and that `/v2/updates` is the
recommended data source.

---

## 12. Category Reference

Complete template-to-category mapping. Each template appears in exactly one
category.

### CC Coin Contracts
- `Splice.Amulet:Amulet`
- `Splice.Amulet:LockedAmulet`

### AmuletRules Exercises
- `Splice.AmuletRules:AmuletRules`

### App Rewards
- `Splice.Amulet:AppRewardCoupon`

### Validator Rewards
- `Splice.Amulet:ValidatorRewardCoupon`
- `Splice.ValidatorLicense:ValidatorFaucetCoupon`

### SV Rewards
- `Splice.Amulet:SvRewardCoupon`

### Unclaimed Rewards & Dev Fund
- `Splice.Amulet:UnclaimedReward`
- `Splice.Amulet:UnclaimedDevelopmentFundCoupon`

### Featured App Rights
- `Splice.Amulet:FeaturedAppRight`

### Featured App Activity
- `Splice.Amulet:FeaturedAppActivityMarker`

### Featured App Batched Markers
- `Splice.Util.FeaturedApp.BatchedMarkersProxy:BatchedMarkersProxy`

### Traffic Purchases
- `Splice.DecentralizedSynchronizer:MemberTraffic`

### Mining Rounds
- `Splice.Round:OpenMiningRound`
- `Splice.Round:IssuingMiningRound`
- `Splice.Round:ClosedMiningRound`
- `Splice.Round:SummarizingMiningRound`

### Validator Licensing
- `Splice.ValidatorLicense:ValidatorLicense`
- `Splice.Amulet:ValidatorRight`

### Validator Liveness
- `Splice.ValidatorLicense:ValidatorLivenessActivityRecord`

### DSO Governance
- `Splice.DsoRules:VoteRequest`
- `Splice.DsoRules:Vote`
- `Splice.DsoRules:DsoRules`
- `Splice.DsoRules:Confirmation`

### SV Operations
- `Splice.DSO.SvState:SvStatusReport`
- `Splice.DSO.SvState:SvNodeState`
- `Splice.DSO.SvState:SvRewardState`
- `Splice.DSO.AmuletPrice:AmuletPriceVote`
- `Splice.SvOnboarding:SvOnboardingRequest`
- `Splice.SvOnboarding:SvOnboardingConfirmed`
- `Splice.DsoBootstrap:DsoBootstrap`

### Transfer Infrastructure
- `Splice.AmuletRules:TransferPreapproval`
- `Splice.AmuletRules:TransferFactory`
- `Splice.AmuletAllocation:AmuletAllocation`
- `Splice.AmuletTransferInstruction:AmuletTransferInstruction`
- `Splice.AmuletRules:ExternalPartySetupProposal`

### External Party
- `Splice.ExternalPartyAmuletRules:ExternalPartyAmuletRules`
- `Splice.ExternalPartyAmuletRules:TransferCommand`
- `Splice.ExternalPartyAmuletRules:TransferCommandCounter`

### Name Service (ANS)
- `Splice.Ans:AnsEntry`
- `Splice.AnsRules:AnsRules`
- `Splice.Ans:AnsRules`
- `Splice.Ans:AnsEntryContext`
- `Splice.Ans.AmuletConversionRateFeed:AmuletConversionRateFeed`

### Wallet & Subscriptions
- `Splice.Wallet.Subscriptions:SubscriptionIdleState`
- `Splice.Wallet.Subscriptions:SubscriptionPayment`
- `Splice.Wallet.Subscriptions:SubscriptionRequest`
- `Splice.Wallet.Install:WalletAppInstall`

---

## 13. References

- [Updates vs Events Investigation](./UPDATES_VS_EVENTS_INVESTIGATION.md)
- [Canton Coin Whitepaper](https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20(whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20payment%20application.pdf)
- [Transaction Types Guide](./TRANSACTION_TYPES.md)
- [Update Tree Processing Guide](./UPDATE_TREE_PROCESSING.md)
- [Fee Analysis and Incentives Guide](./FEE_ANALYSIS_AND_INCENTIVES_GUIDE.md)
- [Data Architecture](./DATA_ARCHITECTURE.md)
- [API Reference](./API_REFERENCE.md)
