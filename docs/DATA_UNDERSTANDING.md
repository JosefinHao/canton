# Canton On-Chain Data Understanding

## Purpose

This document captures our evolving understanding of Canton on-chain data structures,
transaction types, and patterns. It is a living document that will grow as we explore
the data more deeply.

**Status**: Initial exploration phase — foundation established, deep-dive ongoing.

---

## 1. Data Landscape

### Scale
- **3.6B+ rows** in the transformed events table (BigQuery)
- **5 migrations** (0 through 4) representing synchronizer upgrade epochs
- **10+ TB** total data across all migrations
- Data is partitioned by `event_date`, clustered by `template_id`, `event_type`, `migration_id`

### Migrations Timeline
| Migration | Approximate Start | Notes |
|-----------|------------------|-------|
| 0 | Early network | Initial synchronizer |
| 1 | — | Short-lived migration |
| 2 | — | Short-lived migration |
| 3 | 2025-06-25 | Longer running period |
| 4 | 2025-12-10 | Current/latest migration |

Migrations 0-2 are relatively short. Migrations 3 and 4 contain the bulk of the data.

### Primary Data Source: Scan API
The Splice Network Scan API (`/v2/updates`) is the canonical source for on-chain data.
Each update contains:

```
Update
├── update_id          (unique identifier, hex-encoded hash)
├── record_time        (ISO timestamp of when the update was recorded)
├── synchronizer_id    (which synchronizer processed this)
├── migration_id       (which migration epoch)
└── update
    ├── root_event_ids    (entry points into the event tree)
    └── events_by_id      (map of event_id → event data)
```

---

## 2. Event Structure

Every on-chain action produces an **event tree**. Events come in three types:

### Created Events
A new contract is instantiated on the ledger.
```
created:
  template_id:       Which Daml template (e.g., Splice.Amulet:Amulet)
  contract_id:       Unique ID for this contract instance
  create_arguments:  The initial state/parameters of the contract
  signatories:       Parties that must sign
  observers:         Parties that can see the contract
  package_name:      Daml package name
```

### Exercised Events
A choice is exercised on an existing contract. This is the primary mechanism
for mutations — transferring coins, buying traffic, closing rounds, voting, etc.
```
exercised:
  template_id:       Which Daml template
  contract_id:       Which contract instance
  choice:            The choice name (e.g., AmuletRules_BuyMemberTraffic)
  choice_argument:   Input parameters to the choice
  exercise_result:   Return value of the choice execution
  acting_parties:    Who initiated the exercise
  consuming:         Whether the contract is consumed (archived) by this exercise
  child_event_ids:   Events caused by this exercise (creates, archives, nested exercises)
  interface_id:      Optional interface through which the choice was exercised
```

### Archived Events
A contract is removed from the active contract set.
```
archived:
  template_id:    Which Daml template
  contract_id:    Which contract instance
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

### Category Map

| Category | Key Templates | Key Choices | Description |
|----------|--------------|-------------|-------------|
| **Token Operations** | `Splice.Amulet:Amulet`, `Splice.AmuletRules:AmuletRules` | `AmuletRules_Transfer`, `AmuletRules_Mint` | CC creation, transfer, burning |
| **Traffic Purchases** | `Splice.DecentralizedSynchronizer:MemberTraffic` | `AmuletRules_BuyMemberTraffic` | Buying synchronizer bandwidth |
| **Mining Rounds** | `Splice.Round:OpenMiningRound`, `IssuingMiningRound`, `ClosedMiningRound`, `SummarizingMiningRound` | — | Round lifecycle (~10 min intervals) |
| **Rewards** | `Splice.Amulet:AppRewardCoupon`, `ValidatorRewardCoupon`, `ValidatorFaucetCoupon`, `SvRewardCoupon` | — | Reward coupons for network participants |
| **Validators** | `Splice.ValidatorLicense:ValidatorLicense`, `Splice.Validator:ValidatorRight` | — | Validator onboarding/licensing |
| **Governance** | `Splice.DsoRules:VoteRequest`, `DsoRules:Vote`, `DsoRules:DsoRules`, `DsoRules:Confirmation` | — | DSO voting and governance |
| **Name Service** | `Splice.Ans:AnsEntry`, `Splice.AnsRules:AnsRules` | — | Amulet Name Service registrations |

### Identifying Transaction Type from Events
A single update (transaction) can contain multiple event types. The **root exercised
event's template and choice** typically defines the transaction's primary type:

- Root choice = `AmuletRules_Transfer` → CC transfer
- Root choice = `AmuletRules_BuyMemberTraffic` → Traffic purchase
- Root choice = `AmuletRules_Mint` → CC minting
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

### Known Patterns (from prior investigation)
- `/v2/updates` contains more events per update than `/v0/events` for the same
  update ID. The difference is null-body verdicts in `/v0/events` that contain
  only verdict metadata (accepted/rejected) without event trees.
- Shared records between the two endpoints have identical `events_by_id` content.
- `/v2/updates` is the recommended endpoint for data ingestion.
- Events 0-2 may have different package versions than events in migrations 3-4.

### Open Questions
- [ ] What is the exact payload structure of `AmuletRules_BuyMemberTraffic`
      choice_argument? (Run `explore_traffic_purchase.py` to confirm)
- [ ] Do traffic purchase event trees differ across migrations? (Schema evolution)
- [ ] What fraction of updates are traffic purchases vs. transfers vs. minting?
- [ ] Are there templates appearing in only one migration? (Migration-specific contracts)
- [ ] What do the `interface_id` fields contain and when are they present?

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

- [Transaction Types Guide](./TRANSACTION_TYPES.md)
- [Update Tree Processing Guide](./UPDATE_TREE_PROCESSING.md)
- [Fee Analysis and Incentives Guide](./FEE_ANALYSIS_AND_INCENTIVES_GUIDE.md)
- [Data Architecture](./DATA_ARCHITECTURE.md)
- [API Reference](./API_REFERENCE.md)
- [Canton Coin Whitepaper](https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20(whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20payment%20application.pdf)
