# Canton On-Chain Data Understanding

## Purpose

This document captures our evolving understanding of Canton on-chain data structures,
transaction types, and patterns. It is a living document that will grow as we explore
the data more deeply.

**Status**: Exploration phase — initial sampling complete (165K updates, 1.37M events).
Traffic purchase deep-dive pending.

---

## 1. Data Landscape

### Scale
- **3.6B+ rows** in the transformed events table (BigQuery)
- **5 migrations** (0 through 4) representing synchronizer upgrade epochs
- **10+ TB** total data across all migrations
- Data is partitioned by `event_date`, clustered by `template_id`, `event_type`, `migration_id`

### Migrations Timeline
| Migration | First Record Time | Notes |
|-----------|------------------|-------|
| 0 | 2024-06-24T21:08:34 | Initial synchronizer |
| 1 | 2024-10-16T13:24:18 | Short-lived migration |
| 2 | 2024-12-11T14:23:05 | Short-lived migration |
| 3 | 2025-06-25T13:44:34 | Longer running period |
| 4 | 2025-12-10T16:23:25 | Current/latest migration |

Migrations 0-2 are relatively short. Migrations 3 and 4 contain the bulk of the data.
All timestamps are from first-page sampling of each migration.

### Primary Data Source: Scan API
The Splice Network Scan API (`/v2/updates`) is the canonical source for on-chain data.

**IMPORTANT — /v2/updates returns a flat structure**: `root_event_ids` and `events_by_id`
are top-level fields on each transaction, NOT nested under an `"update"` wrapper.
This differs from `/v0/events` which uses a `{"update": {...}, "verdict": {...}}` wrapper.

```
POST /v2/updates response:
{
  "transactions": [            ← list of flat transaction objects
    {
      "update_id":        str  ← unique identifier, hex-encoded hash
      "record_time":      str  ← ISO timestamp
      "synchronizer_id":  str  ← which synchronizer processed this
      "migration_id":     int  ← which migration epoch (0-4)
      "effective_at":     str  ← effective timestamp
      "root_event_ids":   [str, ...]    ← entry points into the event tree
      "events_by_id":     {str: {...}}  ← map of event_id → event data
      "trace_context":    {...}         ← optional tracing metadata
    },
    ...
  ]
}
```

The Python client (`SpliceScanClient.get_updates()`) normalizes `"transactions"` to
`"updates"` for backward compatibility, so callers access `resp["updates"]`.

**Event format within events_by_id**: Events use a **flat** structure where
`template_id`, `create_arguments`, `choice`, `choice_argument`, `child_event_ids`
etc. are direct fields on each event object. Event type is determined by which
fields are present (e.g. `create_arguments` → created, `choice` → exercised).

---

## 2. Event Structure

Every on-chain action produces an **event tree**. Events come in three types.

**All events use a flat structure** in `/v2/updates` (confirmed by
[UPDATES_VS_EVENTS_INVESTIGATION.md](./UPDATES_VS_EVENTS_INVESTIGATION.md)).
Event type is determined by which fields are present:

### Created Events (`"create_arguments" in event`)
A new contract is instantiated on the ledger.
```json
{
  "template_id": "Splice.Amulet:Amulet",
  "contract_id": "00a3...",
  "package_name": "splice-amulet",
  "create_arguments": { ... },
  "signatories": ["party1::..."],
  "observers": ["party2::..."]
}
```

### Exercised Events (`"choice" in event`)
A choice is exercised on an existing contract. This is the primary mechanism
for mutations — transferring coins, buying traffic, closing rounds, voting, etc.
```json
{
  "template_id": "Splice.AmuletRules:AmuletRules",
  "contract_id": "00b5...",
  "choice": "AmuletRules_BuyMemberTraffic",
  "choice_argument": { ... },
  "exercise_result": { ... },
  "acting_parties": ["party1::..."],
  "consuming": true,
  "child_event_ids": ["#1:0", "#2:0", "#3:0"],
  "interface_id": "...",
  "signatories": ["party1::..."],
  "observers": []
}
```

### Archived Events (`event.get("archived")` is truthy)
A contract is removed from the active contract set.
```json
{
  "template_id": "Splice.Amulet:Amulet",
  "contract_id": "00a3...",
  "archived": true
}
```

### Tree Traversal
Events form a tree via `root_event_ids` and `child_event_ids`. The recommended
traversal is **preorder** (depth-first): process the current node, then recurse
into children. This preserves the execution order of the transaction.

Example tree for a CC transfer:
```
exercised: Splice.AmuletRules:AmuletRules [AmuletRules_Transfer]
├── archived: Splice.Amulet:Amulet (input coin consumed)
├── created: Splice.Amulet:Amulet (output coin for recipient)
├── created: Splice.Amulet:Amulet (change coin for sender)
└── created: Splice.Amulet:AppRewardCoupon (if featured app)
```

---

## 3. Transaction Type Catalog

### Template ID Format

**IMPORTANT**: Template IDs from the API include a **package hash prefix**:
```
3ca1343ab26b453d38c8adb70dca5f1ead8440c42b59b68f070786955cbf9ec1:Splice.Amulet:Amulet
```
The bare template name is the last two colon-separated parts: `Splice.Amulet:Amulet`.
When matching templates, use suffix/endswith matching, not exact equality.

### Category Map (Analytics-Focused, Mutually Exclusive)

Categories are designed to support business analytics. Each template appears in
exactly one category (no double-counting). Choice breakdowns within categories
show the operation mix.

**Token Economics:**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **CC Coin Contracts** | `Splice.Amulet:Amulet`, `LockedAmulet` | CC coin state changes (creates = minting/transfer outputs, archives = consumption) |
| **AmuletRules Exercises** | `Splice.AmuletRules:AmuletRules` | Top-level token operations with choice breakdown: Transfer, Mint, BuyTraffic, etc. |

**Rewards (split by recipient for economic analysis):**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **App Rewards** | `Splice.Amulet:AppRewardCoupon` | Rewards earned by featured apps for facilitating transactions |
| **Validator Rewards** | `ValidatorRewardCoupon`, `ValidatorFaucetCoupon` | Activity-based coupons + faucet grants for validators |
| **SV Rewards** | `Splice.Amulet:SvRewardCoupon` | Rewards for Super Validators (governance participation) |
| **Unclaimed Rewards & Dev Fund** | `UnclaimedReward`, `UnclaimedDevelopmentFundCoupon` | Minted CC not claimed + dev fund allocations |

**Featured App Ecosystem:**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **Featured App Rights** | `Splice.Amulet:FeaturedAppRight` | App registration — who holds featured app status |
| **Featured App Activity** | `Splice.Amulet:FeaturedAppActivityMarker` | Activity markers — records of transaction facilitation (dominant in M3/M4) |
| **Featured App Batched Markers** | `BatchedMarkersProxy` | Batched marker proxy for efficient multi-party updates |

**Network Infrastructure:**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **Traffic Purchases** | `MemberTraffic` | Synchronizer bandwidth allocation ($17/MB) |
| **Mining Rounds** | `OpenMiningRound`, `IssuingMiningRound`, `ClosedMiningRound`, `SummarizingMiningRound` | Round lifecycle (~10 min intervals) |

**Validator Management:**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **Validator Licensing** | `ValidatorLicense`, `ValidatorRight` | Onboarding, licensing, rights |
| **Validator Liveness** | `ValidatorLivenessActivityRecord` | Heartbeat/liveness tracking |

**Governance:**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **DSO Governance** | `VoteRequest`, `Vote`, `DsoRules`, `Confirmation` | DSO voting and rule changes |
| **SV Operations** | `SvStatusReport`, `SvNodeState`, `SvRewardState`, `AmuletPriceVote`, `SvOnboarding*` | SV status, price voting, onboarding |

**Other:**

| Category | Key Templates | Description |
|----------|--------------|-------------|
| **Transfer Infrastructure** | `TransferPreapproval`, `TransferFactory`, `AmuletAllocation`, `AmuletTransferInstruction` | Preapprovals, factories, allocations |
| **External Party** | `ExternalPartyAmuletRules`, `TransferCommand`, `TransferCommandCounter` | External party CC access (new in M3/M4) |
| **Name Service (ANS)** | `AnsEntry`, `AnsRules`, `AnsEntryContext` | Human-readable names for parties |
| **Wallet & Subscriptions** | `SubscriptionIdleState`, `SubscriptionPayment`, `WalletAppInstall` | Wallet and subscription management |

### Business Questions the Categorization Supports

1. **Which featured apps are most active?** → Featured App Activity (by provider party)
2. **How much CC reward does each app earn?** → App Rewards (by provider party)
3. **How is minted CC distributed?** → Compare App / Validator / SV / Unclaimed Rewards
4. **What % of rewards go unclaimed?** → Unclaimed Rewards & Dev Fund vs total
5. **Faucet vs activity-based validator rewards?** → Validator Rewards sub-breakdown
6. **What's the transaction type mix?** → AmuletRules Exercises choice breakdown
7. **Is the network growing?** → Events/update density trend across migrations
8. **How many active validators?** → Validator Licensing
9. **External party adoption trend?** → External Party event counts over time

### Sampling Results Summary (from `explore_transaction_types.py`)

Run: 33 sample windows across migrations 0-4, 10 pages/window, 500 updates/page.

| Metric | Value |
|--------|-------|
| Total updates sampled | 165,000 |
| Total events sampled | 1,374,349 |
| Unique template IDs | 210 |
| Unique choices | 453 |
| Unique package names | 5 |

**Package names**: `splice-amulet` (~90%+), `splice-dso-governance`, `splice-util-batched-markers`,
`splice-amulet-name-service`, `splice-wallet-payments`.

**Event density growth over time**:
- Migration 0 early: ~3 events/update
- Migration 3 late: ~14.7 events/update
- Migration 4 recent: ~18 events/update

**Top choices by frequency**: Archive (most common), AmuletRules_Transfer,
FeaturedAppRight_CreateActivityMarker, TransferPreapproval_Send, TransferFactory_Transfer.

### Templates New in Migrations 3-4

These templates were **not observed** in migrations 0-2 samples:
- `ExternalPartyAmuletRules` — External party access to CC
- `TransferPreapproval` — Pre-approved transfer workflows
- `ValidatorLivenessActivityRecord` — Validator liveness tracking
- `FeaturedAppActivityMarker` — Featured app activity markers (becomes dominant)
- `FeaturedAppRight` — Featured app rights management
- `AmuletAllocation` — CC allocations
- `BatchedMarkersProxy` — Batched operations
- `AmuletTransferInstruction` — Transfer instructions
- `UnclaimedDevelopmentFundCoupon` — Development fund coupons

### Schema Evolution Detected

11 template×choice combinations showed field differences across migrations,
indicating contract version changes at migration boundaries. This is expected
as migrations upgrade the Splice contract packages.

### Identifying Transaction Type from Events
A single update (transaction) can contain multiple event types. The **root exercised
event's template and choice** typically defines the transaction's primary type:

- Root choice = `AmuletRules_Transfer` → CC transfer
- Root choice = `AmuletRules_BuyMemberTraffic` → Traffic purchase
- Root choice = `AmuletRules_Mint` → CC minting
- Root choice = `FeaturedAppRight_CreateActivityMarker` → Featured app activity
- Root choice = `TransferPreapproval_Send` → Pre-approved transfer
- Root template = `Splice.Round:*` → Mining round lifecycle event
- Root template = `Splice.DsoRules:*` → Governance action

---

## 4. Traffic Purchase Deep-Dive (First Candidate)

### What is a Traffic Purchase?
Parties must buy synchronizer bandwidth (traffic) to submit transactions to the
Canton Network. This is done by exercising `AmuletRules_BuyMemberTraffic` on the
`Splice.AmuletRules:AmuletRules` contract, spending Canton Coin in exchange for
traffic credits.

### Economics
- **Rate**: $17 per MB of synchronizer bandwidth
- **Typical transfer size**: ~20KB = 0.02MB → ~$0.34 in traffic cost
- **Self-referential**: Traffic purchases themselves consume bandwidth (small overhead)
- Tracked in round-party-totals as `traffic_purchased_cc_spent`

### Expected Event Tree Structure
Based on contract template analysis, a traffic purchase update should contain:

```
exercised: Splice.AmuletRules:AmuletRules [AmuletRules_BuyMemberTraffic]
├── archived: Splice.Amulet:Amulet          (CC coin consumed as payment)
├── created: Splice.DecentralizedSynchronizer:MemberTraffic  (traffic allocation)
├── created: Splice.Amulet:Amulet           (change from payment, if any)
└── (possible) created: Splice.Amulet:*RewardCoupon  (reward if applicable)
```

### Key Fields to Investigate (from choice_argument)
These are hypothesized based on the Daml contract model — to be confirmed by
running the exploration scripts against actual API data:

| Field | Expected Type | Description |
|-------|--------------|-------------|
| `member` | string | Participant ID purchasing traffic |
| `synchronizerId` | string | Which synchronizer |
| `trafficAmount` | integer/string | Bandwidth amount (bytes) |
| `round` | object/integer | Which mining round this applies to |
| `provider` | string | The validator/party providing traffic |

### MemberTraffic Contract (create_arguments)
The `Splice.DecentralizedSynchronizer:MemberTraffic` contract records the
traffic allocation:

| Field | Expected Type | Description |
|-------|--------------|-------------|
| `provider` | string | Party providing/buying traffic |
| `synchronizerId` | string | Synchronizer ID |
| `totalPurchased` | integer | Total traffic purchased |
| `round` | object | Mining round context |
| `dso` | string | DSO party ID |
| `migrationId` | integer | Migration epoch |

### API Endpoints for Traffic Data
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v2/updates` | POST | Raw transaction data (includes traffic purchases) |
| `/v0/round-party-totals` | POST | Aggregated per-party stats including `traffic_purchased_cc_spent` |
| `/v0/top-validators-by-purchased-traffic` | GET | Leaderboard (deprecated) |
| `/v0/domains/{id}/members/{id}/traffic-status` | GET | Live traffic status for a member |

### Exploration Scripts
Two scripts are available for exploring traffic purchase data:

1. **`scripts/explore_transaction_types.py`** — Smart sampling across migrations 0-4
   to catalog all transaction types and their frequencies. Uses targeted sample
   windows rather than full scans.

2. **`scripts/explore_traffic_purchase.py`** — Dedicated deep-dive into traffic
   purchase events, extracting event trees, payload fields, parties, and
   co-occurring templates.

Both scripts must be run from a **whitelisted VM** with access to the Scan API.

---

## 5. Exploration Strategy for 10+ TB of Data

### Why Smart Sampling?
With 3.6B+ rows across 10+ TB, exhaustive scanning is impractical for initial
exploration. Instead, we use targeted sampling to build understanding efficiently.

### Sampling Approach
1. **Migration boundary sampling** — Fetch the first 1-2 pages from each
   migration (0-4) to discover which templates/choices exist at the start
   of each epoch. Short migrations (0-2) may fit in a few pages entirely.

2. **Temporal sampling** — For long migrations (3, 4), sample at early/middle/late
   time windows to detect if the transaction mix evolves.

3. **Schema evolution detection** — Compare payload field structures for the
   same template across different migrations. Contract version changes at
   migration boundaries may alter field names or add new fields.

4. **Frequency estimation** — Per-sample-window frequency distributions give
   local estimates of the transaction mix (not global counts).

### What Sampling Cannot Tell Us
- Exact global counts or percentages (only estimates from sample windows)
- Rare event types that don't appear in our sample windows
- Time-series trends (would require many sample points or BigQuery)
- Exhaustive party lists or complete network topology

### Next Steps After Sampling
Once sampling establishes the template/choice landscape:
1. Use **BigQuery** for exact frequency counts and time-series analysis
2. Use **targeted update_id lookups** (`/v2/updates/{id}`) for specific transactions
3. Schedule **domain expert sessions** with KC (Digital Asset) and Alex (DRW)
   to validate interpretations

---

## 6. Data Quality Observations

### Known Patterns (from [UPDATES_VS_EVENTS_INVESTIGATION.md](./UPDATES_VS_EVENTS_INVESTIGATION.md))
- Transaction bodies are **byte-for-byte identical** across `/v2/updates` and
  `/v0/events` for all shared records (verified via SHA256 hash comparison across
  1000+ records, 3 SV nodes).
- `/v0/events` contains **null-body records** (~40-50% of page slots) that are
  verdict-only with no transaction body. These do not appear in `/v2/updates`.
- `/v2/updates` is ~1.5-2x more efficient per API call due to no null-body overhead.
- `/v2/updates` is the recommended endpoint for data ingestion.
- Verdict metadata (finalization_time, submitting_parties, mediator_group) is
  exclusively available through `/v0/events` but is not needed for business analytics.
- Confirmed templates across both endpoints include: `Splice.AmuletRules:AmuletRules`,
  `Splice.Amulet:Amulet`, `Splice.Round:OpenMiningRound`, `Splice.Amulet:ValidatorRewardCoupon`,
  `Splice.DecentralizedSynchronizer:MemberTraffic`, and more (see investigation doc for full list).
- Events 0-2 may have different package versions than events in migrations 3-4.

### Answered Questions
- [x] Are there templates appearing in only one migration? **Yes** — 9+ templates
      are exclusive to M3/M4 (FeaturedAppActivityMarker, TransferPreapproval, etc.)
- [x] Does the transaction mix evolve over time? **Yes** — event density grows from
      ~3/update (M0) to ~18/update (M4). FeaturedAppActivityMarker becomes dominant.
- [x] Do payload fields differ across migrations? **Yes** — 11 template×choice
      combinations show schema evolution.

### Open Questions
- [ ] What is the exact payload structure of `AmuletRules_BuyMemberTraffic`
      choice_argument? (Run `explore_traffic_purchase.py` to confirm)
- [ ] Do traffic purchase event trees differ across migrations? (Schema evolution)
- [ ] What fraction of updates are traffic purchases vs. transfers vs. minting?
      (Sampling gives estimates; BigQuery needed for exact counts)
- [ ] What do the `interface_id` fields contain and when are they present?
- [ ] What drives the 6x growth in events/update from M0 to M4?
- [ ] How do the new M3/M4 templates (TransferPreapproval, FeaturedAppActivityMarker)
      interact with the existing transfer and rewards system?

---

## 7. Key Relationships & Domain Experts

| Person | Organization | Expertise |
|--------|-------------|-----------|
| KC | Digital Asset | Canton Network protocol, Daml contracts, transaction flow |
| Alex | DRW | Trading perspective, traffic economics |

### Recommended Questions for Domain Experts
1. Can you walk through a traffic purchase transaction step by step?
2. What is the lifecycle of a MemberTraffic contract after creation?
3. How does the traffic amount relate to actual bandwidth consumption?
4. Are there scenarios where traffic purchases fail or are rejected?
5. How do traffic purchases interact with mining round boundaries?

---

## 8. References

- [Updates vs Events Investigation](./UPDATES_VS_EVENTS_INVESTIGATION.md) — Definitive comparison of `/v2/updates` vs `/v0/events` with actual API data
- [Transaction Types Guide](./TRANSACTION_TYPES.md)
- [Update Tree Processing Guide](./UPDATE_TREE_PROCESSING.md)
- [Fee Analysis and Incentives Guide](./FEE_ANALYSIS_AND_INCENTIVES_GUIDE.md)
- [Data Architecture](./DATA_ARCHITECTURE.md)
- [API Reference](./API_REFERENCE.md)
- [Canton Coin Whitepaper](https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20(whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20payment%20application.pdf)
