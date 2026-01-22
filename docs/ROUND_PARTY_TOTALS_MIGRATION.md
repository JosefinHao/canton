# Featured App Rewards - Using round-party-totals API

## Overview

The Featured App Rewards analysis has been updated to use the `/v0/round-party-totals` API endpoint instead of parsing individual contract events. This provides a more and reliable way to analyze app rewards.

## What Changed

### Previous Approach (Old)
- Parsed `AppRewardCoupon` contract creation events from the update stream
- Required traversing complex event trees
- Slow and unreliable due to network restrictions

### New Approach (Current)
- Uses `/v0/round-party-totals` POST endpoint
- Fetches aggregated data directly per party per round
- Faster
- Returns structured data with:
  - `app_rewards`: Rewards for the round
  - `cumulative_app_rewards`: Total rewards up to that round
  - `validator_rewards`: Validator rewards (also available)
  - Other metrics (traffic, fees, etc.)

## API Endpoint

```python
POST /v0/round-party-totals
Content-Type: application/json

{
    "start_round": 1,
    "end_round": 50  // Max 50 rounds per request
}
```

**Response:**
```json
{
    "entries": [
        {
            "closed_round": 1,
            "party": "party_id",
            "app_rewards": "100.50",
            "cumulative_app_rewards": "100.50",
            "validator_rewards": "50.25",
            // ... other fields
        }
    ]
}
```

## Usage

### Command Line

```bash
# Analyze first 100 rounds
python analyze_featured_app_rewards.py --max-rounds 100

# Analyze specific range
python analyze_featured_app_rewards.py --start-round 100 --end-round 200

# Analysis with CSV export
python analyze_featured_app_rewards.py --export-csv
```

### Programmatic

```python
from canton_scan_client import SpliceScanClient
from featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer

client = SpliceScanClient(base_url="...")
analyzer = FeaturedAppRewardsAnalyzer(client)

# Fetch rewards for rounds 1-500
summary = analyzer.fetch_and_process_rewards(
    start_round=1,
    end_round=500,
    max_rounds=500
)

# Get statistics
stats = analyzer.get_all_stats()
for provider_id, app_stats in stats.items():
    print(f"{provider_id}: {app_stats.total_rewards:.2f} CC")
```

## Data Structure Changes

### AppRewardRecord (Updated)
```python
@dataclass
class AppRewardRecord:
    provider_party_id: str
    round_number: int
    app_rewards: float                 # NEW: Per-round rewards
    cumulative_app_rewards: float      # NEW: Cumulative total
    metadata: Dict[str, Any]           # API response
```

### AppRewardStats (Updated)
```python
@dataclass
class AppRewardStats:
    provider_party_id: str
    total_rewards: float
    total_coupons: int                 # Now means: rounds with rewards
    avg_reward_per_round: float        # NEW: Average per round
    first_round: int
    last_round: int
    rounds_active: int
    rewards_by_round: Dict[int, float]
    cumulative_by_round: Dict[int, float]  # NEW
```

## Benefits

1. **Much Faster**: Direct API calls instead of parsing events
2. **More Reliable**: No complex event tree traversal
3. **Aggregated Data**: Pre-calculated totals and cumulatives
4. **Batch Processing**: Fetch 50 rounds at a time
5. **Works Now**: Real data available immediately

## Backward Compatibility

- The analysis scripts maintain the same interface
- Visualizations work identically
- CSV exports have updated field names
- Statistics calculations produce same insights

## Testing

Test from your Mac terminal:

```bash
# Quick test
python analyze_featured_app_rewards.py --max-rounds 50 --no-visualizations

# Test with visualizations
python analyze_featured_app_rewards.py --max-rounds 200 --export-csv
```

The validator rewards analyzer (`validator_rewards_analyzer.py`) also uses this same endpoint, accessing the `validator_rewards` field instead of `app_rewards`.
