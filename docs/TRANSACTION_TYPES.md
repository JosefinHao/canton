# Canton Network Transaction Types

## Overview

This guide documents the different types of transactions on the Canton Network. Each transaction type has distinct characteristics, fee structures, and behaviors on the ledger.

---

## Transaction Types

### 1. Private Transactions (Non-Canton Coin Transfers)

Private transactions are general-purpose Daml transactions that do not involve Canton Coin (CC) transfers. These are the most common transaction type for applications running on the Canton Network.

**Characteristics:**
- Do not involve Canton Coin movement
- Use Daml smart contracts for arbitrary business logic
- Recorded on the ledger as update trees with created, archived, and exercised events

**Fees:**
- **Traffic fees**: Charged based on transaction size at $17/MB of synchronizer bandwidth
- A typical private transaction of ~20KB costs approximately $0.34 in traffic fees

**Example use cases:**
- Supply chain tracking
- Trade finance workflows
- Identity management
- Any Daml application logic that doesn't involve CC

### 2. Canton Coin Transfers

Canton Coin (CC) transfers move value between parties on the Canton Network. These are payment transactions processed through the Amulet smart contracts.

**Characteristics:**
- Involve `Splice.Amulet:Amulet` contract creation and archival
- Subject to tiered transfer fees
- Create activity records that contribute to app rewards (for featured apps)
- Visible via the `/v0/activities` API endpoint

**Fees:**
- **Transfer fees** (tiered by amount):

  | Transfer Amount | Fee Rate |
  |----------------|----------|
  | First $100 | 1.0% |
  | $100 - $1,000 | 0.1% |
  | $1,000 - $1M | 0.01% |
  | Above $1M | 0.001% |

- **Base transfer fee**: $0.03 per output coin created
- **Lock holder fee**: $0.005 per lock holder on locked coins
- **Holding fees**: $1/year per coin UTXO (demurrage), charged at settlement
- **Traffic fees**: Charged based on transaction size at $17/MB

**Example:**
A $1,000 CC transfer incurs approximately:
- Transfer fee: $1.90 (1% of $100 + 0.1% of $900)
- Base fee: $0.06 (2 outputs x $0.03)
- Traffic fee: ~$0.34 (assuming ~20KB transaction size)
- Total: ~$2.30 (excluding holding fees on aged coins)

### 3. Traffic Fee Purchases

Traffic fee purchases are transactions where participants buy synchronizer bandwidth using Canton Coin. This is how parties pre-pay for the right to submit transactions to the network.

**Characteristics:**
- Convert Canton Coin into traffic credits (synchronizer bandwidth)
- Tracked via the `traffic_purchased_cc_spent` field in round-party-totals
- Visible in the `/v0/top-validators-by-purchased-traffic` leaderboard
- Essential for any party that submits transactions to the synchronizer

**Fees:**
- **Traffic rate**: $17 per MB of synchronizer bandwidth
- Traffic purchases themselves consume bandwidth, so there is a small overhead

**API tracking:**
```json
{
  "round": 1000,
  "party": "...",
  "traffic_purchased_cc_spent": "10.00"
}
```

### 4. Featured App Mint Transactions

Featured app mint transactions occur at the end of each mining round when Canton Coin is minted and distributed to featured app providers as rewards. These transactions can also include traffic fee purchases.

**Characteristics:**
- Occur during round close/issuance processing
- Create `AppRewardCoupon` contracts for featured apps
- Reward amount depends on activity weight, minting curve, and competition
- Can bundle traffic fee purchases within the same minting transaction
- Only featured apps (approved by 2/3 Super Validator vote) receive mint rewards

**Reward mechanism:**
- Featured apps receive a **$1 bonus** added to activity weight per transaction facilitated
- Reward cap: up to **100x** the fees burned (cap_fa = 100.0)
- Actual rewards depend on the minting curve allocation for the current network phase

**Minting curve allocation to apps:**

| Network Phase | Years | App Pool % |
|---------------|-------|-----------|
| Bootstrap | 0-0.5 | 15% |
| Early Growth | 0.5-1.5 | 40% |
| Growth | 1.5-5 | 62% |
| Maturation | 5-10 | 69% |
| Steady State | 10+ | 75% |

**Combined minting + traffic purchase:**
Within a single minting transaction, a featured app can also purchase traffic fees. This bundles two operations:
1. Receiving minted CC rewards for the round
2. Using CC (including freshly minted rewards) to purchase synchronizer bandwidth

---

## Fee Summary by Transaction Type

| Transaction Type | Transfer Fees | Traffic Fees | Holding Fees | Mint Rewards |
|-----------------|---------------|--------------|--------------|--------------|
| Private Transactions | No | Yes | No | No |
| Canton Coin Transfers | Yes (tiered) | Yes | Yes (at settlement) | No |
| Traffic Fee Purchases | No | Yes (this IS the fee) | No | No |
| Featured App Mint | No | Yes (if bundled) | Yes | Yes (received) |

---

## Featured Apps: Current Fee Structure

Featured apps currently pay the following fees:

1. **Traffic fees** - For synchronizer bandwidth consumed by the app's transactions ($17/MB)
2. **Holding fees** - Demurrage on Canton Coin UTXOs held by the app ($1/year per UTXO)

### Liveliness Fees: Being Phased Out

Liveliness fees (validator liveness rewards funded by the network) are being phased out. Previously, validators received faucet rewards for demonstrating liveness (participating in consensus). This mechanism is being deprecated as the network matures.

### Un-featured Apps: No Rewards

Un-featured applications no longer receive rewards from the network. Previously, un-featured apps could mint up to 0.6x-0.8x of fees burned back as rewards. This incentive has been removed. Only featured apps (approved by Super Validator vote) participate in the minting reward system.

---

## Transaction Lifecycle on the Ledger

All transactions follow a common lifecycle on the Canton ledger:

```
Transaction Submitted
    │
    ▼
Synchronizer Processes (traffic fee charged)
    │
    ▼
Update Tree Created
    ├── Root Event IDs (entry points)
    ├── Events By ID (created, archived, exercised)
    └── Child Event IDs (nested events)
    │
    ▼
Round Processing
    ├── Fee calculation and burning
    ├── Activity weight recording
    └── Reward minting (featured apps only)
    │
    ▼
State Updated
    ├── Contract states (created/archived)
    ├── Balances (transfers)
    └── Round totals (fees, rewards)
```

---

## API Endpoints by Transaction Type

| Transaction Type | Primary API Endpoints |
|-----------------|----------------------|
| Private Transactions | `/v2/updates`, `/v0/events` |
| Canton Coin Transfers | `/v0/activities`, `/v0/holdings/summary`, `/v2/updates` |
| Traffic Fee Purchases | `/v0/round-party-totals`, `/v0/top-validators-by-purchased-traffic` |
| Featured App Mint | `/v0/round-party-totals`, `/v0/top-providers-by-app-rewards`, `/v0/featured-apps` |

---

## References

- [Fee Analysis and Incentives Guide](./FEE_ANALYSIS_AND_INCENTIVES_GUIDE.md)
- [Featured App Rewards Guide](./FEATURED_APP_REWARDS_GUIDE.md)
- [Update Tree Processing Guide](./UPDATE_TREE_PROCESSING.md)
- [API Reference](./API_REFERENCE.md)
- [Canton Coin Whitepaper](https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20(whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20payment%20application.pdf)
