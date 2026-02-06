# Fee Analysis and Incentives Guide

## Overview

This guide provides detailed calculations and understanding for:
1. **Fees remaining after all incentives and rebates are removed**
2. **Fees generated without incentive support**
3. **Leaderboard analysis for SV, Validators & Featured Apps with fee exposure**
4. **Observed fee behavior as incentives are reduced/changed**

Understanding these relationships is critical for analyzing network economics, predicting costs as the network matures, and identifying fee concentration among participants.

---

## Table of Contents

- [1. Understanding the Fee and Incentive System](#1-understanding-the-fee-and-incentive-system)
- [2. Calculating Net Fees After Incentives](#2-calculating-net-fees-after-incentives)
- [3. Fees Without Incentive Support](#3-fees-without-incentive-support)
- [4. Leaderboard Analysis](#4-leaderboard-analysis)
- [5. Fee Behavior as Incentives Change](#5-fee-behavior-as-incentives-change)
- [6. API Endpoints for Fee Analysis](#6-api-endpoints-for-fee-analysis)
- [7. Practical Examples](#7-practical-examples)

---

## 1. Understanding the Fee and Incentive System

### 1.1 Fee Types (What Users Pay)

Canton Coin users pay **two categories** of fees:

#### A. Transfer Fees (Percentage-Based)
| Transfer Amount | Fee Rate |
|----------------|----------|
| First $100 | 1.0% |
| $100 - $1,000 | 0.1% |
| $1,000 - $1M | 0.01% |
| Above $1M | 0.001% |

#### B. Resource Usage Fees (Fixed)
| Fee Type | Amount | Description |
|----------|--------|-------------|
| Base Transfer Fee | $0.03 | Per output coin created |
| Lock Holder Fee | $0.005 | Per lock holder on locked coins |
| Holding Fee | $1/year | Per coin UTXO (demurrage) |
| Traffic Fee | $17/MB | Synchronizer bandwidth |

### 1.2 Incentive Types (What Participants Receive)

Incentives are **minted** to participants as rewards for providing network value:

| Incentive Type | Recipient | Cap/Multiplier | Status |
|----------------|-----------|----------------|--------|
| **App Rewards (Featured)** | Featured App Providers | Up to 100x fees burned | Active |
| **Validator Rewards** | Validators (coin usage) | 0.2x activity weight | Active |
| **SV Rewards** | Super Validators | Fixed % of tranche | Active |

> **Note: Recent Changes**
> - **Un-featured app rewards have been removed.** Previously, un-featured apps could mint up to 0.8x of fees burned. Only featured apps now receive minting rewards.
> - **Validator liveness fees (faucet) are being phased out.** The validator faucet mechanism that rewarded validators for liveness participation is being deprecated.
> - **Featured apps** now primarily pay **traffic fees** and **holding fees** only.

### 1.3 The Burn-Mint Equilibrium

```
USER PAYS FEES (Burned) ──► PARTICIPANTS MINT REWARDS
         │                            │
         ▼                            ▼
   Decreases Supply              Increases Supply
         │                            │
         └────────► EQUILIBRIUM ◄─────┘
```

**Key Insight**: The "net fee" is the difference between what's burned (fees) and what's minted (rewards).

---

## 2. Calculating Net Fees After Incentives

### 2.1 The Net Fee Formula

```
NET_FEE = GROSS_FEES_BURNED - TOTAL_REWARDS_MINTED

Where:
  GROSS_FEES_BURNED = transfer_fee + base_transfer_fee + lock_fee + holding_fee + traffic_fee

  TOTAL_REWARDS_MINTED = app_rewards + validator_rewards + validator_faucet + sv_rewards
```

### 2.2 Per-Transaction Net Fee Calculation

From the API's `/v0/activities` endpoint, each transfer provides:

```json
{
  "sender": {
    "input_amulet_amount": "1000.00",
    "sender_fee": "1.90",
    "sender_change_fee": "0.03",
    "holding_fees": "0.50",
    "input_app_reward_amount": "0.00",
    "input_validator_reward_amount": "0.00",
    "input_sv_reward_amount": "0.00",
    "input_validator_faucet_amount": "0.00"
  },
  "receivers": [
    {
      "amount": "997.57",
      "receiver_fee": "0.00"
    }
  ]
}
```

**Gross Fees Burned for this transaction:**
```
sender_fee + sender_change_fee + receiver_fee + holding_fees
= $1.90 + $0.03 + $0.00 + $0.50
= $2.43
```

### 2.3 Round-Level Net Fee Calculation

Using `/v0/round-party-totals` or `/v0/round-totals`:

```python
def calculate_net_fees_for_round(round_data):
    """
    Calculate net fees after subtracting all incentives for a round.
    """
    # Total fees burned in the round
    total_fees_burned = (
        round_data.get('change_to_holding_fees_rate', 0) +
        round_data.get('traffic_purchased_cc_spent', 0)
        # Note: transfer fees are implicit in holding fee changes
    )

    # Total rewards minted in the round
    total_rewards_minted = (
        round_data.get('app_rewards', 0) +
        round_data.get('validator_rewards', 0) +
        round_data.get('sv_reward_amount', 0) +
        round_data.get('validator_faucet_amount', 0)
    )

    # Net fees = what's actually "lost" to fees after incentives
    net_fees = total_fees_burned - total_rewards_minted

    return {
        'gross_fees': total_fees_burned,
        'total_rewards': total_rewards_minted,
        'net_fees': net_fees,
        'effective_fee_rate': net_fees / total_fees_burned if total_fees_burned > 0 else 0
    }
```

### 2.4 Example Calculation: $1,000 Transfer

| Component | Amount | Notes |
|-----------|--------|-------|
| **FEES BURNED** | | |
| Transfer Fee | $1.90 | 1% of $100 + 0.1% of $900 |
| Base Transfer Fee | $0.06 | 2 outputs × $0.03 |
| Holding Fee (if aged) | $0.00 | Varies by coin age |
| **Gross Fees** | **$1.96** | |
| | | |
| **REWARDS MINTED** | | |
| Validator Reward | $0.39 | $1.93 × 0.2 (cap) |
| App Reward (Featured) | $2.93 | $1.93 + $1.00 bonus |
| **Total Rewards** | **$3.32** | |
| | | |
| **NET RESULT** | **-$1.36** | Negative = net mint |

> **Note**: Validator liveness (faucet) rewards are being phased out and are no longer included in this calculation.

**Interpretation**: In early network phases, featured apps and validators receive MORE in rewards than users pay in fees, resulting in **net minting** (inflation).

---

## 3. Fees Without Incentive Support

### 3.1 What "Without Incentive Support" Means

This represents the **raw cost** users would pay if:
- No app rewards were minted
- No validator rewards were minted
- No validator faucet existed
- No SV rewards were distributed

This is the "mature network" scenario where burn-mint equilibrium is reached.

### 3.2 Raw Fee Calculation

```python
def calculate_fees_without_incentives(transfer_amount, num_outputs=2, num_locks=0, coin_age_rounds=0):
    """
    Calculate raw fees without any incentive rebates.
    This represents the true cost of using the network.
    """
    # Transfer fee calculation (tiered)
    transfer_fee = 0
    remaining = transfer_amount

    tiers = [
        (100, 0.01),      # First $100 at 1%
        (900, 0.001),     # $100-$1000 at 0.1%
        (999000, 0.0001), # $1000-$1M at 0.01%
        (float('inf'), 0.00001)  # Above $1M at 0.001%
    ]

    for tier_amount, rate in tiers:
        taxable = min(remaining, tier_amount)
        transfer_fee += taxable * rate
        remaining -= taxable
        if remaining <= 0:
            break

    # Resource fees
    base_fee = num_outputs * 0.03
    lock_fee = num_locks * 0.005
    holding_fee = coin_age_rounds * (1.0 / 52560)  # ~$1/year in 10-min rounds

    # Total raw fees
    total_raw_fees = transfer_fee + base_fee + lock_fee + holding_fee

    return {
        'transfer_fee': transfer_fee,
        'base_fee': base_fee,
        'lock_fee': lock_fee,
        'holding_fee': holding_fee,
        'total_raw_fees': total_raw_fees,
        'fee_percentage': (total_raw_fees / transfer_amount) * 100
    }
```

### 3.3 Fee Schedule Without Incentives

| Transfer Value | Total Raw Fee | Fee as % of Transfer |
|---------------|---------------|---------------------|
| $1 | $0.07 | 7.00% |
| $10 | $0.16 | 1.60% |
| $100 | $1.06 | 1.06% |
| $1,000 | $1.96 | 0.20% |
| $10,000 | $2.86 | 0.03% |
| $100,000 | $11.86 | 0.01% |
| $1,000,000 | $101.86 | 0.01% |
| $100,000,000 | $1,091.86 | 0.001% |

### 3.4 Traffic Costs Without Incentives

For synchronizer traffic (non-Canton Coin transactions or additional traffic):

```
Traffic Cost = Transaction Size (MB) × $17/MB

Typical Canton Coin transfer: ~20KB = 0.02MB
Traffic cost per transfer: 0.02 × $17 = $0.34
```

### 3.5 Annual Holding Cost (Demurrage)

Each coin UTXO costs $1/year to hold, regardless of amount:

```python
def calculate_annual_holding_cost(num_utxos, total_balance):
    """
    Calculate annual demurrage cost.
    """
    annual_cost = num_utxos * 1.0  # $1 per UTXO per year

    # Effective rate depends on balance per UTXO
    avg_balance_per_utxo = total_balance / num_utxos if num_utxos > 0 else 0
    effective_rate = (1.0 / avg_balance_per_utxo) * 100 if avg_balance_per_utxo > 0 else float('inf')

    return {
        'annual_cost': annual_cost,
        'effective_annual_rate': effective_rate,
        'recommendation': 'Consolidate UTXOs' if effective_rate > 1 else 'Efficient'
    }
```

**Example**:
- 10 UTXOs holding $100 each = $10/year (1% effective rate)
- 1 UTXO holding $1,000 = $1/year (0.1% effective rate)
- **Consolidation saves 90% on holding fees**

---

## 4. Leaderboard Analysis

### 4.1 Available Leaderboard Endpoints

| Endpoint | Returns | Use Case |
|----------|---------|----------|
| `GET /v0/top-providers-by-app-rewards` | Top app providers by rewards | Featured App leaderboard |
| `GET /v0/top-validators-by-validator-rewards` | Top validators by rewards | Validator leaderboard |
| `GET /v0/top-validators-by-validator-faucets` | Top validators by faucet rounds | Liveness leaderboard |
| `GET /v0/top-validators-by-purchased-traffic` | Top validators by traffic | Traffic purchaser leaderboard |
| `GET /v0/featured-apps` | All featured apps | Featured status list |

### 4.2 Fee Concentration Analysis

```python
from src.canton_scan_client import SpliceScanClient

def analyze_fee_concentration(client: SpliceScanClient, limit: int = 20):
    """
    Analyze how fees/rewards are concentrated among top participants.
    """
    # Get top participants
    top_apps = client._make_request('GET', f'/v0/top-providers-by-app-rewards?limit={limit}')
    top_validators = client._make_request('GET', f'/v0/top-validators-by-validator-rewards?limit={limit}')
    top_faucets = client._make_request('GET', f'/v0/top-validators-by-validator-faucets?limit={limit}')

    # Calculate concentration metrics
    def calculate_concentration(data, value_key):
        values = [entry.get(value_key, 0) for entry in data]
        total = sum(values)
        if total == 0:
            return {'gini': 0, 'top_10_share': 0, 'hhi': 0}

        # Top 10 concentration
        top_10_share = sum(sorted(values, reverse=True)[:10]) / total * 100

        # Herfindahl-Hirschman Index (market concentration)
        shares = [v / total for v in values]
        hhi = sum(s**2 for s in shares) * 10000

        # Gini coefficient
        n = len(values)
        sorted_values = sorted(values)
        gini = (2 * sum((i + 1) * v for i, v in enumerate(sorted_values)) - (n + 1) * total) / (n * total) if total > 0 else 0

        return {
            'gini': gini,
            'top_10_share': top_10_share,
            'hhi': hhi,
            'total_participants': len(values),
            'total_value': total
        }

    return {
        'app_rewards_concentration': calculate_concentration(
            top_apps.get('providers', []), 'total_rewards'
        ),
        'validator_rewards_concentration': calculate_concentration(
            top_validators.get('validators', []), 'total_rewards'
        ),
        'validator_faucet_concentration': calculate_concentration(
            top_faucets.get('validators', []), 'rounds_collected'
        )
    }
```

### 4.3 Leaderboard Data Structure

#### Top App Providers Response:
```json
{
  "providers": [
    {
      "provider_party_id": "digital-asset::12345...",
      "total_rewards": "1500000.00",
      "total_activity_weight": "15000.00",
      "rounds_active": 4320,
      "is_featured": true
    }
  ]
}
```

#### Top Validators Response:
```json
{
  "validators": [
    {
      "validator_party_id": "validator-1::abcde...",
      "total_rewards": "250000.00",
      "total_activity_weight": "1250000.00",
      "rounds_active": 4320
    }
  ]
}
```

### 4.4 Fee Exposure Analysis

```python
def analyze_fee_exposure(client: SpliceScanClient, start_round: int, end_round: int):
    """
    Analyze fee exposure for top participants over a round range.
    Shows how much of total network fees flow to each participant category.
    """
    # Get round-party totals for detailed breakdown
    totals = client.get_round_party_totals(start_round, end_round)

    # Aggregate by participant type
    sv_rewards = 0
    validator_rewards = 0
    app_rewards = 0
    total_traffic_purchased = 0

    party_rewards = {}

    for entry in totals.get('entries', []):
        party_id = entry.get('party')

        app_reward = float(entry.get('app_rewards', 0))
        val_reward = float(entry.get('validator_rewards', 0))
        traffic = float(entry.get('traffic_purchased_cc_spent', 0))

        app_rewards += app_reward
        validator_rewards += val_reward
        total_traffic_purchased += traffic

        if party_id not in party_rewards:
            party_rewards[party_id] = {
                'app_rewards': 0,
                'validator_rewards': 0,
                'traffic_spent': 0
            }

        party_rewards[party_id]['app_rewards'] += app_reward
        party_rewards[party_id]['validator_rewards'] += val_reward
        party_rewards[party_id]['traffic_spent'] += traffic

    # Calculate exposure metrics
    total_rewards = app_rewards + validator_rewards

    # Top 5 by total rewards
    top_5_parties = sorted(
        party_rewards.items(),
        key=lambda x: x[1]['app_rewards'] + x[1]['validator_rewards'],
        reverse=True
    )[:5]

    top_5_share = sum(
        p[1]['app_rewards'] + p[1]['validator_rewards']
        for p in top_5_parties
    ) / total_rewards * 100 if total_rewards > 0 else 0

    return {
        'total_app_rewards': app_rewards,
        'total_validator_rewards': validator_rewards,
        'total_traffic_purchased': total_traffic_purchased,
        'top_5_concentration': top_5_share,
        'top_5_parties': [
            {
                'party_id': p[0][:50] + '...',
                'total_rewards': p[1]['app_rewards'] + p[1]['validator_rewards'],
                'share': (p[1]['app_rewards'] + p[1]['validator_rewards']) / total_rewards * 100
            }
            for p in top_5_parties
        ],
        'unique_participants': len(party_rewards)
    }
```

### 4.5 Interpretation Guidelines

| Metric | Low Concentration | Moderate | High Concentration |
|--------|------------------|----------|-------------------|
| **Gini Coefficient** | < 0.3 | 0.3-0.6 | > 0.6 |
| **Top 10 Share** | < 40% | 40-70% | > 70% |
| **HHI** | < 1500 | 1500-2500 | > 2500 |

**Risk Assessment**:
- **High concentration** = Fee revenue depends on few participants; risky if they leave
- **Low concentration** = Distributed ecosystem; more resilient

---

## 5. Fee Behavior as Incentives Change

### 5.1 Minting Curve Timeline

The network incentives follow a predetermined schedule:

| Period | Years | Rate/Year | SV % | Validator % | App % |
|--------|-------|-----------|------|-------------|-------|
| Bootstrap | 0-0.5 | 40B CC | 80% | 5% | 15% |
| Early Growth | 0.5-1.5 | 20B CC | 48% | 12% | 40% |
| Growth | 1.5-5 | 10B CC | 20% | 18% | 62% |
| Maturation | 5-10 | 5B CC | 10% | 21% | 69% |
| Steady State | 10+ | 2.5B CC | 5% | 20% | 75% |

### 5.2 Fee Impact Calculation Over Time

```python
def calculate_fee_impact_over_time(
    transfer_amount: float,
    activity_weight: float,
    is_featured: bool = True
):
    """
    Calculate effective fees at different network phases.

    Note: Only featured apps receive minting rewards. Un-featured apps
    no longer receive any rewards. Validator liveness (faucet) rewards
    are being phased out and are not included.
    """
    # Minting curve parameters
    phases = [
        {'name': 'Bootstrap (0-0.5yr)', 'tranche_usd': 3805, 'app_pct': 0.15, 'val_pct': 0.05},
        {'name': 'Early (0.5-1.5yr)', 'tranche_usd': 1903, 'app_pct': 0.40, 'val_pct': 0.12},
        {'name': 'Growth (1.5-5yr)', 'tranche_usd': 951, 'app_pct': 0.62, 'val_pct': 0.18},
        {'name': 'Mature (5-10yr)', 'tranche_usd': 476, 'app_pct': 0.69, 'val_pct': 0.21},
        {'name': 'Steady (10+yr)', 'tranche_usd': 238, 'app_pct': 0.75, 'val_pct': 0.20},
    ]

    # Calculate raw fees
    raw_fees = calculate_transfer_fee(transfer_amount)

    results = []
    for phase in phases:
        # Simplified reward calculation (actual depends on competition)
        app_pool = phase['tranche_usd'] * phase['app_pct']
        val_pool = phase['tranche_usd'] * phase['val_pct']

        # Cap calculations - only featured apps get rewards
        cap_fa = 100.0 if is_featured else 0.0  # Un-featured apps get no rewards
        cap_v = 0.2

        # Estimated rewards (assuming low competition in early phases)
        app_reward = min(activity_weight * cap_fa, app_pool)
        val_reward = min(activity_weight * cap_v, val_pool)

        total_rewards = app_reward + val_reward
        net_fee = raw_fees - total_rewards

        results.append({
            'phase': phase['name'],
            'raw_fees': raw_fees,
            'app_reward': app_reward,
            'val_reward': val_reward,
            'total_rewards': total_rewards,
            'net_fee': net_fee,
            'effective_rate': (net_fee / transfer_amount) * 100
        })

    return results

def calculate_transfer_fee(amount):
    """Calculate tiered transfer fee."""
    fee = 0
    if amount > 0:
        fee += min(amount, 100) * 0.01
    if amount > 100:
        fee += min(amount - 100, 900) * 0.001
    if amount > 1000:
        fee += min(amount - 1000, 999000) * 0.0001
    if amount > 1000000:
        fee += (amount - 1000000) * 0.00001
    fee += 0.06  # Base fees for 2 outputs
    return fee
```

### 5.3 Projected Fee Behavior

For a **$1,000 transfer via Featured App**:

| Phase | Raw Fee | Rewards | Net Fee | Effective Rate |
|-------|---------|---------|---------|----------------|
| Bootstrap (0-0.5yr) | $1.96 | $195.30 | **-$193.34** | -19.33% (NET MINT) |
| Early (0.5-1.5yr) | $1.96 | $195.30 | **-$193.34** | -19.33% (NET MINT) |
| Growth (1.5-5yr) | $1.96 | $117.18 | **-$115.22** | -11.52% (NET MINT) |
| Mature (5-10yr) | $1.96 | $65.52 | **-$63.56** | -6.36% (NET MINT) |
| Steady (10+yr) | $1.96 | $35.70 | **-$33.74** | -3.37% (NET MINT) |

For a **$1,000 transfer via Un-featured App**:

> **Note**: Un-featured apps no longer receive rewards. The full raw fee applies.

| Phase | Raw Fee | Rewards | Net Fee | Effective Rate |
|-------|---------|---------|---------|----------------|
| All Phases | $1.96 | $0.00 | **$1.96** | 0.20% |

### 5.4 Key Observations on Fee Behavior

1. **Featured Apps are Subsidized**: Early network phases heavily subsidize featured apps with up to 100x fee multipliers

2. **Net Mint vs Net Burn Transition**:
   - Early: More rewards minted than fees burned (inflationary)
   - Late: Burn-mint equilibrium approaches (stable supply)

3. **Un-featured Apps Pay Full Fees**: Un-featured apps no longer receive rewards, so users pay the full raw fee

4. **Validator Liveness Being Phased Out**: Liveness (faucet) rewards are being deprecated

5. **SV Concentration Decreases**: SV share drops from 80% to 5% over 10 years

6. **Featured Apps Pay Traffic + Holding Fees Only**: Featured apps are subject to traffic fees and holding fees, but no longer to liveliness fees

### 5.5 Monitoring Incentive Changes via API

```python
def track_incentive_changes(client: SpliceScanClient, round_range: int = 1000):
    """
    Track how incentive ratios change over recent rounds.
    """
    # Get current round
    dso = client.get_dso()
    current_round = dso.get('latest_mining_round', 0)

    start_round = max(0, current_round - round_range)

    # Fetch round totals
    totals = client.get_round_party_totals(start_round, current_round)

    # Calculate running averages
    rounds_data = {}
    for entry in totals.get('entries', []):
        round_num = entry.get('round')
        if round_num not in rounds_data:
            rounds_data[round_num] = {
                'app_rewards': 0,
                'validator_rewards': 0,
                'traffic_fees': 0
            }
        rounds_data[round_num]['app_rewards'] += float(entry.get('app_rewards', 0))
        rounds_data[round_num]['validator_rewards'] += float(entry.get('validator_rewards', 0))
        rounds_data[round_num]['traffic_fees'] += float(entry.get('traffic_purchased_cc_spent', 0))

    # Calculate trend
    sorted_rounds = sorted(rounds_data.keys())

    if len(sorted_rounds) < 2:
        return {'error': 'Insufficient data'}

    # First half vs second half comparison
    mid = len(sorted_rounds) // 2
    first_half = sorted_rounds[:mid]
    second_half = sorted_rounds[mid:]

    def avg_metrics(round_list):
        total_app = sum(rounds_data[r]['app_rewards'] for r in round_list)
        total_val = sum(rounds_data[r]['validator_rewards'] for r in round_list)
        total_traffic = sum(rounds_data[r]['traffic_fees'] for r in round_list)
        n = len(round_list)
        return {
            'avg_app_rewards': total_app / n,
            'avg_validator_rewards': total_val / n,
            'avg_traffic_fees': total_traffic / n,
            'reward_to_fee_ratio': (total_app + total_val) / total_traffic if total_traffic > 0 else float('inf')
        }

    first_metrics = avg_metrics(first_half)
    second_metrics = avg_metrics(second_half)

    return {
        'period_1': {
            'rounds': f'{first_half[0]}-{first_half[-1]}',
            **first_metrics
        },
        'period_2': {
            'rounds': f'{second_half[0]}-{second_half[-1]}',
            **second_metrics
        },
        'trend': {
            'app_rewards_change': (second_metrics['avg_app_rewards'] - first_metrics['avg_app_rewards']) / first_metrics['avg_app_rewards'] * 100 if first_metrics['avg_app_rewards'] > 0 else 0,
            'validator_rewards_change': (second_metrics['avg_validator_rewards'] - first_metrics['avg_validator_rewards']) / first_metrics['avg_validator_rewards'] * 100 if first_metrics['avg_validator_rewards'] > 0 else 0,
            'reward_ratio_change': second_metrics['reward_to_fee_ratio'] - first_metrics['reward_to_fee_ratio']
        }
    }
```

---

## 6. API Endpoints for Fee Analysis

### 6.1 Fee Configuration

```bash
GET /v0/amulet-config-for-round?round={round_number}
```

Returns fee schedule parameters:
```json
{
  "amulet_create_fee": "0.03",
  "holding_fee": "0.0000190258751902588",
  "lock_holder_fee": "0.005",
  "transfer_fee": {
    "initial": "0.01",
    "steps": [
      {"amount": "100", "rate": "0.001"},
      {"amount": "1000", "rate": "0.0001"},
      {"amount": "1000000", "rate": "0.00001"}
    ]
  }
}
```

### 6.2 Holdings with Accumulated Fees

```bash
POST /v0/holdings/summary
```

Returns accumulated holding fees:
```json
{
  "summaries": [
    {
      "party_id": "...",
      "total_unlocked_coin": "10000.00",
      "total_locked_coin": "500.00",
      "accumulated_holding_fees_unlocked": "150.00",
      "accumulated_holding_fees_locked": "7.50",
      "accumulated_holding_fees_total": "157.50",
      "total_available_coin": "10342.50"
    }
  ]
}
```

### 6.3 Round-Level Fee and Reward Totals

```bash
POST /v0/round-party-totals
{
  "start_round": 1000,
  "end_round": 1050
}
```

Returns per-party fee/reward metrics:
```json
{
  "entries": [
    {
      "round": 1000,
      "party": "...",
      "app_rewards": "100.00",
      "validator_rewards": "50.00",
      "cumulative_app_rewards": "5000.00",
      "cumulative_validator_rewards": "2500.00",
      "change_to_holding_fees_rate": "0.05",
      "traffic_purchased_cc_spent": "10.00"
    }
  ]
}
```

### 6.4 Transfer Activity Details

```bash
POST /v0/activities
{
  "page_size": 100,
  "include_incomplete_rounds": true
}
```

Returns detailed fee breakdown per transfer.

---

## 7. Practical Examples

### 7.1 Example: Calculate Total Network Fees for a Period

```python
def analyze_network_fees(client: SpliceScanClient, num_rounds: int = 100):
    """
    Analyze total network fee metrics over recent rounds.
    """
    dso = client.get_dso()
    latest_round = dso.get('latest_mining_round', 0)
    start_round = max(0, latest_round - num_rounds)

    # Get round-party totals
    data = client.get_round_party_totals(start_round, latest_round)

    # Aggregate metrics
    total_app_rewards = 0
    total_validator_rewards = 0
    total_traffic_fees = 0
    unique_parties = set()

    for entry in data.get('entries', []):
        total_app_rewards += float(entry.get('app_rewards', 0))
        total_validator_rewards += float(entry.get('validator_rewards', 0))
        total_traffic_fees += float(entry.get('traffic_purchased_cc_spent', 0))
        unique_parties.add(entry.get('party'))

    total_rewards = total_app_rewards + total_validator_rewards

    print(f"=== Network Fee Analysis (Rounds {start_round}-{latest_round}) ===")
    print(f"Total App Rewards Minted: {total_app_rewards:,.2f} CC")
    print(f"Total Validator Rewards Minted: {total_validator_rewards:,.2f} CC")
    print(f"Total Traffic Fees Burned: {total_traffic_fees:,.2f} CC")
    print(f"")
    print(f"Net Reward Flow: {total_rewards - total_traffic_fees:,.2f} CC")
    print(f"  (Positive = net inflation, Negative = net deflation)")
    print(f"")
    print(f"Unique Participants: {len(unique_parties)}")
    print(f"Avg Rewards per Participant: {total_rewards / len(unique_parties):,.2f} CC")

    return {
        'total_app_rewards': total_app_rewards,
        'total_validator_rewards': total_validator_rewards,
        'total_traffic_fees': total_traffic_fees,
        'net_flow': total_rewards - total_traffic_fees,
        'unique_participants': len(unique_parties)
    }
```

### 7.2 Example: Compare Featured vs Un-featured Economics

> **Note**: Un-featured apps no longer receive rewards. This comparison shows the economic advantage of Featured status.

```python
def compare_app_economics(transfer_amount: float = 1000):
    """
    Compare economic outcomes for featured vs un-featured apps.
    Un-featured apps no longer receive any minting rewards.
    """
    # Calculate raw fees
    raw_fee = 1.96  # For $1000 transfer (pre-calculated)
    activity_weight = raw_fee - 0.03  # Exclude change output fee

    print(f"=== Featured vs Un-featured App Comparison ===")
    print(f"Transfer Amount: ${transfer_amount:,.2f}")
    print(f"Raw Fees Burned: ${raw_fee:.2f}")
    print(f"Activity Weight: ${activity_weight:.2f}")
    print()

    # Featured App (100x cap + $1 bonus)
    featured_weight = activity_weight + 1.00  # $1 bonus per transaction
    featured_reward = min(featured_weight * 100, activity_weight * 100)  # 100x cap
    featured_net = raw_fee - featured_reward - (activity_weight * 0.2)  # Include validator

    print("FEATURED APP:")
    print(f"  Activity Weight (with bonus): ${featured_weight:.2f}")
    print(f"  Max App Reward (100x): ${featured_reward:.2f}")
    print(f"  Validator Reward (0.2x): ${activity_weight * 0.2:.2f}")
    print(f"  NET RESULT: ${featured_net:.2f}")
    print(f"  (Negative = app/validator profits exceed user fees)")
    print()

    # Un-featured App (NO rewards)
    print("UN-FEATURED APP:")
    print(f"  Activity Weight: ${activity_weight:.2f}")
    print(f"  App Reward: $0.00 (un-featured apps no longer receive rewards)")
    print(f"  Validator Reward (0.2x): ${activity_weight * 0.2:.2f}")
    print(f"  NET RESULT: ${raw_fee - (activity_weight * 0.2):.2f}")
    print(f"  (Positive = network captures net fees)")
    print()

    print("ECONOMIC DIFFERENCE:")
    print(f"  Featured apps receive minting rewards; un-featured apps do not.")
    print(f"  This is why Featured status requires 2/3 SV vote!")
```

Output:
```
=== Featured vs Un-featured App Comparison ===
Transfer Amount: $1,000.00
Raw Fees Burned: $1.96
Activity Weight: $1.93

FEATURED APP:
  Activity Weight (with bonus): $2.93
  Max App Reward (100x): $193.00
  Validator Reward (0.2x): $0.39
  NET RESULT: $-191.43
  (Negative = app/validator profits exceed user fees)

UN-FEATURED APP:
  Activity Weight: $1.93
  App Reward: $0.00 (un-featured apps no longer receive rewards)
  Validator Reward (0.2x): $0.39
  NET RESULT: $1.57
  (Positive = network captures net fees)

ECONOMIC DIFFERENCE:
  Featured apps receive minting rewards; un-featured apps do not.
  This is why Featured status requires 2/3 SV vote!
```

---

## Summary

### Key Takeaways

1. **Net Fees = Gross Fees - Total Rewards**
   - Early network: Net fees are negative (inflationary)
   - Mature network: Approaches burn-mint equilibrium

2. **Raw Fees Without Incentives**
   - Small transfers (<$100): 1-7% effective fee
   - Large transfers (>$10K): <0.03% effective fee
   - Holding fees: $1/year per UTXO

3. **Fee Concentration**
   - Use leaderboard endpoints to monitor
   - High concentration = systemic risk
   - Track Gini, HHI, and Top-10 share

4. **Incentive Evolution**
   - SV share: 80% → 5% over 10 years
   - App share: 15% → 75% over 10 years
   - Only featured apps receive minting rewards (up to 100x)
   - Un-featured apps no longer receive rewards

5. **Current Fee Structure for Featured Apps**
   - Featured apps pay **traffic fees** and **holding fees**
   - Liveliness fees are being phased out

### Monitoring Checklist

- [ ] Query `/v0/round-party-totals` for aggregate fee/reward data
- [ ] Use leaderboard endpoints to track concentration
- [ ] Compare `app_rewards + validator_rewards` vs `traffic_purchased_cc_spent`
- [ ] Track ratio changes over time to detect incentive phase transitions
- [ ] Monitor featured app list changes via `/v0/featured-apps`

---

## References

- [Canton Coin Whitepaper](https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20(whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20payment%20application.pdf)
- [Scan Open API Reference](./Scan%20Open%20API%20Reference%20—%20Splice%20documentation.pdf)
- [Featured App Rewards Guide](./FEATURED_APP_REWARDS_GUIDE.md)
- [Validator Rewards Guide](./VALIDATOR_REWARDS_GUIDE.md)
- [API Reference](./API_REFERENCE.md)
