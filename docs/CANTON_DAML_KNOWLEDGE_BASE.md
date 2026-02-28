# Canton Network & Daml: Complete Knowledge Base

A comprehensive reference covering the philosophy, technical architecture, smart contract language, protocol mechanics, and ecosystem of the Canton Network and Digital Asset's platform.

**Sources**: [docs.digitalasset.com](https://docs.digitalasset.com), [docs.daml.com](https://docs.daml.com), [canton.network](https://www.canton.network), [Canton White Paper](https://www.digitalasset.com/hubfs/Canton/Canton%20Network%20-%20White%20Paper.pdf)

---

## Table of Contents

1. [Philosophy & Core Principles](#part-1-philosophy--core-principles)
2. [The Daml Smart Contract Language](#part-2-the-daml-smart-contract-language)
3. [The Canton Protocol & Architecture](#part-3-the-canton-protocol--architecture)
4. [The Ledger API](#part-4-the-ledger-api)
5. [The Canton Network Ecosystem](#part-5-the-canton-network-ecosystem)
6. [Canton Coin (CC) Economics](#part-6-canton-coin-cc-economics)
7. [CIP-56 Token Standard and Daml Finance](#part-7-cip-56-token-standard-and-daml-finance)
8. [Application Architecture](#part-8-application-architecture)
9. [SDLC Best Practices](#part-9-sdlc-best-practices)

---

## Part 1: Philosophy & Core Principles

### What Canton Is

Canton is a **privacy-enabled, institutional-grade distributed ledger** built around Daml smart contracts. The core philosophy is:

- **Need-to-know privacy**: Data is only distributed to parties with a legitimate stake — no broadcasting to the entire network
- **Non-repudiation**: Every transaction is cryptographically evidenced and cannot be denied
- **Data sovereignty**: Each participant controls their own data; no single entity has visibility into all contracts
- **Virtual Global Ledger**: All parties perceive a single consistent logical ledger, even though no single data store contains it all

The design was explicitly built for regulated finance: regulators can be added as observer parties on contracts for real-time supervisory access, eliminating manual data requests while preserving commercial confidentiality.

**Real-world scale (2025)**: $280B+ in average daily on-chain repo transactions, $6T in tokenized assets, $4T/month in Treasury repo via Broadridge DLR. DTCC is tokenizing U.S. Treasury securities custodied at DTC on Canton.

---

## Part 2: The Daml Smart Contract Language

### Conceptual Model: A Database Analogy

| Database concept | Daml concept |
|---|---|
| Table schema | **Template** |
| Table row | **Contract instance** |
| Stored procedure (atomic insert/delete) | **Choice** |
| Database | **Virtual Global Ledger** |

Instead of running against one database, different actors exchange which stored procedures they want to run via the Canton protocol. The protocol orders, validates, removes conflicts, and distributes these requests so all affected parties can apply them deterministically to their local stores.

### Core Language Concepts

**Template** — A blueprint for contract creation. Written in Daml source, compiled to Daml-LF (similar to Java→JVM bytecode relationship). Each template defines:
- The `with` block (the **payload** — fields and data types)
- The `signatory` clause — who must consent to creation
- The `observer` clause — who can see but need not consent
- The `where` block — which **choices** exist on this contract

**Contract Instance** — A live record on the ledger. Created by `create` commands. Immutable once created (but can be archived and replaced). Has a globally unique `contract_id`.

**Choice** — An action a party can take on a contract. The choice body specifies what happens when exercised (can create new contracts, archive the current one, or both). Two types:
- **Consuming choice** — archives the contract when exercised (the default)
- **Non-consuming choice** — leaves the contract active (`nonconsuming` keyword)

**Signatories** — Must authorize contract creation; their consent is required. They are the "owners" of the contract and always observers implicitly.

**Observers** — Can see the contract and its payload. Do NOT need to consent to creation.

**Controllers** — Can exercise a specific choice on a specific contract. Must be at least an observer (they need to see the contract to exercise it).

**Maintainers** — Parties on a contract key. Must always be signatories. Guarantee key uniqueness within their visibility scope.

**Stakeholders** — Collective term for all signatories + observers (everyone with an interest in the contract).

### Contract Lifecycle

```
create → [active contract] → archive
                ↑                ↓
         nonconsuming       consuming choice
           exercise         (+ possibly new
                             contracts created)
```

Once archived, a contract is no longer valid and its choices can no longer be exercised. The ledger is **append-only**: archival doesn't delete data, it marks the contract as inactive.

### Daml Interfaces

Daml interfaces allow templates to conform to a common API, enabling polymorphic code. Key points:
- Interface definitions live in separate packages (they are not upgradable via SCU)
- Templates can retroactively implement interfaces via smart contract upgrades (but retroactive instances are NOT compatible with SCU — they require offline migration)
- Used heavily in Daml Finance and CIP-56 token standard for interoperability

### DAR Files and Packages

- Daml source compiles to **Daml-LF** (the bytecode), packaged into a `.dar` file (a zip/jar-like container)
- DARs must be **uploaded AND activated** on a participant node to become usable
- Each package has a **package ID** (content hash) and a **package name + version** (set in `daml.yaml`)
- Once uploaded, a DAR version cannot be replaced or removed
- Packages with the same name+version are not allowed (for LF >= 1.17)

### Smart Contract Upgrades (SCU)

Requires **LF 1.17** and **Canton Protocol version 7**.

Rules for backward-compatible upgrades (checked at compile time, upload time, and runtime):
- **Allowed**: adding optional fields, adding choices, additive model changes
- **Forbidden**: removing fields/choices, changing signatory sets, breaking interface incompatibilities
- Contracts from old packages are **automatically interpreted** as the new version when used in new workflows
- **Rolling deployment**: decide a switch-over time, publish it, then all clients update their package preference

Interface definitions are NOT upgradable via SCU — keep them in a stable separate package referenced by all versions.

---

## Part 3: The Canton Protocol & Architecture

### The Virtual Global Ledger

Canton provides a **logically global, physically distributed** ledger. Each participant stores only the contracts they're a stakeholder of (their **Private Contract Store / PCS**). The Canton protocol guarantees:
- Integrity: all changes are properly authorized
- Privacy: data only goes to parties who need it
- Consistency: no double-spends
- Auditability: cryptographic evidence of all transactions

The result: "every participant only possesses a small part of the virtual global ledger; all the local stores together make up that virtual global ledger."

### Participant Nodes (Validators)

A **Participant Node** (also called a Validator) is:
- The private, self-sovereign computational and storage unit for an entity
- Runs the **Daml Engine** (interprets smart contract code)
- Stores smart contracts in the **Private Contract Store (PCS)**
- Exposes the **Ledger API** (gRPC or JSON) to client applications
- Connects to one or more Synchronizers to participate in transactions

**Critical implication**: Unlike other blockchains with a single global RPC endpoint, in Canton **you must connect to the specific validator that hosts a party** to read their data. There is no all-encompassing data source. (Exception: the Scan API provides data visible to Super Validators.)

**Party hosting types**:
- **Single-hosted**: one validator, simplest setup, full trust in that validator
- **Multi-hosted**: multiple validators share a party's keys for higher availability/security

**Permission levels**:
- **Submission**: validator's signing key authorizes transactions
- **Confirmation**: key only confirms transactions (doesn't submit)
- **Observation**: read-only access, no confirmation required

### Internal vs. External Parties

**Internal parties**: created on the validator node; validator holds the signing keys; transactions are signed by the validator's internal keys.

**External parties**: signing key is held outside the network (like an EOA on Ethereum). Transaction flow:
1. **Prepare** the transaction (assemble the command)
2. **Sign** it externally (with the party's own key)
3. **Submit** it to the network

This is the foundation for exchange/custody integrations where institutions hold their own keys.

### Synchronizers (Sync Domains)

A **Synchronizer** is a sequencing and message-brokering service that:
1. **Routes messages** between connected participant nodes
2. **Orders transactions** deterministically (assigns timestamps/record times)
3. **Coordinates two-phase commit (2PC)** to ensure atomicity

Critical: synchronizers are **blind** — all payloads are **end-to-end encrypted** between participant nodes. The synchronizer sees an encrypted blob, timestamps it, orders it, and routes it. It cannot read transaction contents.

**Mediator**: a synchronizer component that acts as the 2PC coordinator. It collects confirmations from participant nodes and finalizes (or aborts) the transaction. Provides privacy between stakeholders — participants communicate via the mediator, not directly.

### The Two-Phase Commit Protocol

Canton's consensus is a **stakeholder-based 2PC** (not PBFT or PoW):

```
Phase 1 (Prepare):
  Submitter → Synchronizer → Participants (all stakeholders)
  Each participant validates the transaction locally, sends confirmation

Phase 2 (Commit):
  If all confirmations received → Synchronizer sends commit
  All participants atomically apply the transaction to their PCS

  If any rejection → Synchronizer sends abort
  Transaction is rolled back everywhere
```

Only the **stakeholders of a transaction** participate in it. The rest of the network is unaware of its existence. This is what enables horizontal scalability and privacy.

### Transaction Trees and Sub-Transaction Privacy

Transactions in Canton have a **hierarchical (tree) structure** reflecting nested choice execution. Key properties:
- Different validator nodes may see **different sub-trees** of the same transaction depending on which parties they host
- This is **sub-transaction privacy**: parties only learn about the sub-tree relevant to them
- The tree structure in the Ledger API: `root_event_ids` → `events_by_id` with `child_event_ids` for exercised events
- Event types: `CreatedEvent`, `ArchivedEvent`, `ExercisedEvent`

**Record time**: Each transaction is committed at a specific record time assigned by the synchronizer. On the Global Synchronizer, record time is analogous to block height in Bitcoin.

### Multi-Synchronizer: Contract Reassignment

Participants can connect to **multiple synchronizers**. Contracts can be moved between them via a **two-step reassignment**:

1. **Unassign**: Contract is deactivated on the source synchronizer → creates an `unassignment_event` on the Ledger API
2. **Assign**: Contract becomes active on the target synchronizer → creates an `assignment_event`

This appears on the Ledger API as a **reassignment** update (alongside transactions). The `reassignment_counter`, `source_synchronizer`, `target_synchronizer`, and `unassign_id` fields track this.

Why use multiple synchronizers:
- Different trust requirements (private vs. shared domain)
- Scalability (parallel processing across domains)
- Regulatory jurisdiction separation
- Performance (lower latency for geographically distributed parties)

**Caveat**: Contract key uniqueness is NOT guaranteed across sync domains. This limitation is expected to lead to eventual deprecation of key uniqueness.

---

## Part 4: The Ledger API

### Core Services

| Service | Purpose |
|---|---|
| **Update Service** | Subscribe to the stream of ledger changes (transactions, reassignments, topology changes) |
| **Command Submission Service** | Submit `create` and `exercise` commands |
| **Interactive Submission Service** | Two-step: `prepare` + `execute` (for external signing) |
| **Active Contracts Service (ACS)** | Get a snapshot of all active contracts at a given offset |
| **Package Management Service** | Upload and query DAR files |
| **Party Management Service** | Allocate and query parties |
| **User Management Service** | Manage users and their rights (local to participant node) |
| **Event Query Service** | Query specific events without maintaining off-ledger state |

### Ledger Offsets

An **offset** is an opaque string assigned by the participant to each transaction as it arrives. Key properties:
- Offsets are **monotonically increasing** and **opaque** (implementation-specific)
- They are **local to a participant node** — offsets are NOT comparable across nodes
- `update_id` and `record_time` ARE comparable across nodes
- Used as cursors for pagination and crash recovery
- In Daml 3.3+, `event_id` was replaced with `(offset, node_id)` pairs for efficiency

### The ACS + Update Stream Pattern

The canonical pattern for initializing application state:

```
1. Call ActiveContractsService → get snapshot of active contracts at offset X
2. Continue streaming updates from offset X via UpdateService
```

This avoids replaying the entire ledger history (O(n) cost) at startup. The last `GetActiveContractsResponse` message contains the offset to use for the subsequent update subscription.

### Update Stream Contents

Each update from the stream can be:
- **Transaction**: contains created, archived, exercised events with a tree structure
- **Reassignment**: unassign or assign events for multi-synchronizer contract movement
- **Topology transaction**: changes to the network topology (party hosting, domain connections, etc.)

### Flat vs. Tree Transactions

The Ledger API can deliver transactions in two modes:
- **Flat transactions**: only events where the subscribed party is a direct stakeholder (signatory or observer)
- **Transaction trees**: full hierarchical structure, including events where the party is a non-stakeholder witness (e.g., from divulgence)

---

## Part 5: The Canton Network Ecosystem

### Node Types

| Node Type | Description |
|---|---|
| **Validator / Participant** | Private computational/storage unit; hosts parties; runs Daml Engine; exposes Ledger API |
| **Super Validator (SV)** | Validator + Canton synchronizer node; participates in Global Synchronizer consensus; also runs Scan App; governed by 2/3 BFT majority |
| **Synchronizer** | Routes, orders, and coordinates transactions; never sees plaintext data |
| **Global Synchronizer** | The public, decentralized synchronizer operated by SVs; BFT consensus; backbone of the entire network |

### The Global Synchronizer (sync.global)

- Operated collectively by **Super Validators** — no single entity controls it
- Uses **2/3 BFT consensus** for ordering and governance votes
- Governed by the **Global Synchronizer Foundation** (under Linux Foundation)
- Key software: **Splice** (open source, Hyperledger Labs)

**Components exposed by SVs**:
- **SV App**: governance participation
- **Scan App**: public API for data visible to all SVs (all CC transactions, governance decisions, round data)

### The Scan API

The Scan API provides a read-only view of the Global Synchronizer's public data. Key endpoints:
- `/v2/updates` — stream of all updates (transactions + reassignments), tree structure
- `/v0/events` — older event-based API (partially deprecated on MainNet)
- `/v0/holdings/summary` — Canton Coin balance summaries
- `/v0/round-party-totals` — per-round per-party fee/reward totals (deprecated on MainNet)
- `/v0/featured-apps` — list of featured applications

### Network Environments

| Environment | Purpose |
|---|---|
| **DevNet** | Development and testing; faucet available; most permissive |
| **TestNet** | Integration testing against realistic network upgrades |
| **MainNet** | Production; real Canton Coin |

Node operators must run all three environments to keep pace with network upgrades.

---

## Part 6: Canton Coin (CC) Economics

### Minting Mechanism

CC is minted in **mining rounds** (roughly 10 minutes each). Coins are **only minted when participants add measurable utility**:
- Operating validator infrastructure → **ValidatorRewardCoupon**
- Building and running applications → **AppRewardCoupon**
- Running Global Synchronizer software → **SvRewardCoupon**
- Demonstrating liveness → **ValidatorLivenessActivityRecord**

The minting curve allocates newly issued CC across these categories. The allocation percentages shift over time (Bootstrap → Early Growth → Growth → Maturation → Steady State).

### Fee Structure

| Fee Type | Description |
|---|---|
| **Traffic fees** | $17/MB of synchronizer bandwidth; charged per transaction |
| **Transfer fees** | Tiered: 1% (<=\$100), 0.1% (\$100–\$1K), 0.01% (\$1K–\$1M), 0.001% (>\$1M) |
| **Base output fee** | $0.03 per Amulet contract created |
| **Lock holder fee** | $0.005 per lock holder on locked coins |
| **Holding fees** | $1/year per active Amulet UTXO (demurrage, charged at settlement) |

CC is **UTXO-based**: each Amulet contract is a UTXO. Balances are the sum of active Amulet contracts owned by a party. Holding fees decay the value of each UTXO over time (encoded as `ExpiringAmount` with `ratePerRound`).

### Featured vs. Non-Featured Apps

**Featured apps** (approved by 2/3 SV vote):
- Receive up to **100x** the CC fees burned back as rewards
- Get a **$1 bonus** added to activity weight per transaction facilitated
- Can receive `AppRewardCoupon` contracts

**Non-featured apps**: No longer receive rewards (this incentive was removed as the network matured).

---

## Part 7: CIP-56 Token Standard and Daml Finance

### CIP-56 (Canton's ERC-20 Equivalent)

CIP-56 defines a standard for fungible assets on Canton. Six APIs:

| API | Purpose |
|---|---|
| **Token Metadata API** | Symbol, name, total supply, registry UI URL |
| **Holdings API** | Portfolio view, transaction history (the UTXO set) |
| **Transfer Instruction API** | Initiate and monitor FOP (Free-of-Payment) transfers |
| **Allocation API** | Allocate assets for DVP (Delivery-vs-Payment) trades |
| **Allocation Request API** | Standard way for apps to request allocations from wallets |
| **Allocation Instruction API** | Standard way for wallets to create allocations |

APIs are specified using **Daml interfaces** (on-ledger) and **OpenAPI** (off-ledger HTTP). Fully backwards compatible — existing templates add interfaces via smart contract upgrade.

The token model is **UTXO-based** (like Amulet). Each active Holding contract is a UTXO. Wallets should keep UTXOs per user below ~10 for efficiency.

### CIP-0103 (Canton's EIP-1193 Equivalent)

Standard JSON-RPC 2.0 interface for how dApps communicate with wallets. Provided by the **dApp SDK** (`@canton-network/dapp-sdk`). Exposes a `window.canton` provider (analogous to MetaMask's `window.ethereum`). Decouples dApp logic from wallet/key management.

### Daml Finance Library

The Daml Finance library provides production-ready building blocks for financial instruments:

**Core concepts**:
- **Instrument**: defines the asset (what something is — a bond, a token, a currency)
- **Holding**: represents ownership of a quantity of an instrument at a custodian (the actual UTXO)
- **Account**: a party's holding account at a custodian
- **Batch**: a group of Instructions to be settled atomically
- **Instruction**: a single holding transfer from sender to receiver at a custodian

**Settlement flow**:
```
1. Create Batch + Instructions (via Settlement Factory)
2. Sender allocates each instruction (Pledge existing holding, or CreditReceiver if sender=custodian)
3. Receiver approves each instruction (TakeDelivery to an account, or PassThroughTo for intermediated)
4. Settler executes the Batch → all instructions settle atomically
```

**Allocation types**:
- `Pledge` — settle the instruction with the pledged asset
- `CreditReceiver` — settle by crediting the receiver account (sender is custodian)
- `SettleOffledger` — settle the instruction off-ledger
- `PassThroughFrom` — settle with the holding coming from another instruction

**Approval types**:
- `TakeDelivery` — take delivery of a holding to an account
- `DebitSender` — immediately nullify the holding
- `PassThroughTo` — pass the holding through to another instruction

**Pass-through**: When an intermediary receives and sends in the same batch at the same custodian, the holding "passes through" without requiring pre-existing intermediary holdings. First instruction approved with `PassThroughTo`, second allocated with `PassThroughFrom`.

**Lifecycling**: Issuers generate lifecycle events (dividends, splits). Results are `Effect` contracts describing per-unit entitlements. Holders present their Holding to claim Effects, receive entitlements, and the old Holding is exchanged for a new version.

---

## Part 8: Application Architecture

### The Standard Canton App Pattern

```
┌────────────────────┐     ┌────────────────────┐
│   Frontend (UI)    │────>│  Backend Service    │
└────────────────────┘     └────────┬────────────┘
                                    │ Ledger API (gRPC/JSON)
                           ┌────────v────────────┐
                           │  Participant Node   │
                           │  (Validator)        │
                           │  ┌──────────────┐   │
                           │  │ Daml Engine  │   │
                           │  │ (runs DARs)  │   │
                           │  └──────────────┘   │
                           │  ┌──────────────┐   │
                           │  │Private       │   │
                           │  │Contract Store│   │
                           │  └──────────────┘   │
                           └────────┬────────────┘
                                    │ Canton Protocol
                           ┌────────v────────────┐
                           │   Synchronizer      │
                           │(orders, timestamps, │
                           │ coordinates 2PC)    │
                           └─────────────────────┘
```

### Parties vs. Users

| Concept | Scope | Used in Daml? | Identity |
|---|---|---|---|
| **Party** | Global across all participant nodes | Yes — always use party IDs | Cryptographic key identifier; stable even when keys roll |
| **User** | Local to one participant node | No — never in Daml code | Human-readable user ID; maps to one or more parties |

Users are the IAM integration point (OAuth2, external IDP). Parties are the on-ledger identity.

### Privacy by Design

Key architectural principle: **Daml models are the privacy boundary**. When designing a multi-party workflow:
- **Signatories**: parties who must consent and can always see the contract
- **Observers**: parties who need to see but don't control the contract
- Minimize signatories (more signatories = more parties who can block creation)
- Use non-consuming choices for read-only workflows where possible

**Sub-transaction privacy** means party A and party B in the same transaction may see different parts of it. Design workflows knowing this — parties shouldn't rely on seeing other parties' sub-trees.

### Reading Data: Private vs. Public

| Data type | How to read it |
|---|---|
| Your parties' private contracts | Ledger API on your own validator node |
| Global Synchronizer public data (CC transactions, rounds, governance) | Scan API (any SV's scan endpoint) |
| Another party's contracts | That party must make you an observer, OR you query their validator's Ledger API with appropriate authorization |

---

## Part 9: SDLC Best Practices

### Design Phase
- Define all on-ledger state in Daml models first — they are the API contract between organizations
- Balance on-ledger vs. off-ledger: put only what needs multi-party consensus on-chain; keep high-frequency reads off-chain
- Privacy by design: every observer you add is data you're sharing; every signatory you add is a party who can block creation
- Consider performance: every transaction goes through the 2PC protocol; batch where possible

### Development Phase
- Separate interfaces into stable packages (they can't be upgraded via SCU)
- Use **Daml Script** for unit and integration testing (but use Daml Script LTS for SCU compatibility)
- DAR package names follow `package-name` pattern; versions must be semver and increasing
- Keep UTXO counts low (aim for <10 active Holding contracts per user)

### Upgrade Phase
- Only additive changes are backwards-compatible (add fields, add choices, add interface implementations)
- Removing anything requires a breaking upgrade with offline migration
- Communicate switch-over time to all clients before deploying
- Use `upgrade-check` tool to validate DAR compatibility without spinning up Canton

### Testing Environments
- **Daml Sandbox**: local, ephemeral Canton ledger for unit testing
- **Canton Quickstart (LocalNet)**: full local environment with Super Validator, Canton Coin wallet, and app nodes
- **DevNet**: shared test network with faucet
- **TestNet**: pre-production testing against upcoming upgrades
- **MainNet**: production

---

## Summary: The Mental Model

Think of the Canton Network as a **global network of private databases** that can participate in **atomic, multi-party transactions** without ever revealing private data to non-stakeholders.

- **Daml** = the language for defining shared state (templates) and allowed state transitions (choices), with built-in authorization and privacy rules
- **Participant/Validator** = your private database + smart contract executor
- **Synchronizer** = the traffic controller that orders and timestamps transactions atomically (blind to content)
- **Global Synchronizer** = the shared public synchronizer connecting all applications on the Canton Network
- **Canton Coin** = the utility token powering network fees and incentivizing node operators and app developers
- **CIP-56** = the standard making all Canton tokens interoperable (like ERC-20 but with institutional privacy and compliance)
- **Scan API** = the public read API for Global Synchronizer data

The key difference from traditional blockchains: **validators have state** (they're not interchangeable); **privacy is first-class** (not bolted on); **atomicity spans organizations** (2PC not gossip); and **the ledger is virtual** (no single node has everything).

---

## References

- [Key Concepts of Canton Network Applications](https://docs.digitalasset.com/build/3.4/overview/key_concepts.html)
- [Introduction — Digital Asset's platform documentation](https://docs.digitalasset.com/overview/3.4/overview/index.html)
- [Parties and Users](https://docs.digitalasset.com/build/3.5/explanations/parties-users.html)
- [Canton Network Overview](https://docs.digitalasset.com/integrate/devnet/canton-network-overview/index.html)
- [Ledger API Services](https://docs.digitalasset.com/build/3.5/explanations/ledger-api-services.html)
- [Introduction to Canton](https://docs.daml.com/canton/about.html)
- [Daml Glossary](https://docs.daml.com/concepts/glossary.html)
- [Synchronization Domain Architecture](https://docs.daml.com/canton/architecture/domains/domains.html)
- [Settlement Concepts (Daml Finance)](https://docs.daml.com/daml-finance/concepts/settlement.html)
- [Token Instrument](https://docs.daml.com/daml-finance/instruments/token.html)
- [CIP-56: Canton Token Standard](https://www.canton.network/blog/what-is-cip-56-a-guide-to-cantons-token-standard)
- [Token Standard APIs — Splice Docs](https://docs.global.canton.network.sync.global/app_dev/token_standard/index.html)
- [Canton Network Application Architecture](https://docs.digitalasset.com/build/3.4/sdlc-howtos/system-design/daml-app-arch-design.html)
- [Canton White Paper (PDF)](https://www.digitalasset.com/hubfs/Canton/Canton%20Network%20-%20White%20Paper.pdf)
- [SDLC Best Practices](https://docs.digitalasset.com/build/3.5/sdlc-howtos/sdlc-best-practices.html)
