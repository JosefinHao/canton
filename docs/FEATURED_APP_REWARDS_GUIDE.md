# Featured App Rewards Analysis Guide

## Overview

This guide explains how to analyze featured app rewards from the Canton ledger using the `/v0/round-party-totals` API endpoint. The analysis system provides:

1. **Data Extraction** - Retrieve aggregated reward data per party per round
2. **Systematic Organization** - Group rewards by featured app (provider party ID)
3. **Statistical Analysis** - Calculate metrics and progress for each app
4. **Visualizations** - Generate charts showing individual progress and comparisons
5. **Export Capabilities** - Export data to CSV for further analysis

## Current Fee Structure for Featured Apps

Featured apps are subject to the following fees:
- **Traffic fees**: $17/MB of synchronizer bandwidth consumed by the app's transactions
- **Holding fees**: $1/year per Canton Coin UTXO (demurrage)

> **Note**: Liveliness fees are being phased out. Featured apps no longer pay liveliness fees.

## Reward Mechanism

Featured app rewards are part of Canton Coin's incentive system designed to reward applications that provide value to the network.

### How Featured App Rewards Work

Based on the [Canton Coin Whitepaper](https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20(whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20payment%20application.pdf):

**Featured vs Un-featured Applications:**
- All applications start as "un-featured" with no reward potential
- Super Validators can mark an app as "featured" via 2/3 majority vote
- **Featured apps** can mint up to **100x more Canton Coin** than was burned as fees
- **Un-featured apps no longer receive rewards** from the network

> **Note**: Previously, un-featured apps could mint up to 0.8x of fees burned. This incentive has been removed.

**Activity Weight Calculation:**
- When users burn Canton Coin fees using an application, activity records are created
- Featured apps receive **$1 additional weight** for every Canton Coin transaction they facilitate
- At launch, first featured app earns minimum **$100 worth** of Canton Coin per transaction

**Minting Process:**
- Each 10-minute round has a tranche of Canton Coin available for minting
- Application pool is split among app providers proportional to their activity weights
- Actual rewards depend on:
  * Minting curve allocation (changes over time - see whitepaper Figure 4)
  * Total competition from other apps in the round
  * Minting cap (cap_fa = 100.0 for featured apps; un-featured apps receive no rewards)

**Example:**
If a featured app facilitates a $1000 Canton Coin transfer with $1.96 in fees burned:
- Activity record weight = $1.93 (fees) + $1.00 (featured bonus) = $2.93
- Potential mint = up to $2.93 x 100 = $293 worth of Canton Coin
- Actual mint depends on round allocation and competition

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Data Model](#data-model)
- [Command-Line Usage](#command-line-usage)
- [Programmatic Usage](#programmatic-usage)
- [Visualizations](#visualizations)
- [Analysis Examples](#analysis-examples)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Basic Analysis

Run analysis with default settings:

```bash
python scripts/analyze_featured_app_rewards.py
```

This will:
1. Fetch reward data from the round-party-totals API
2. Calculate statistics for each featured app
3. Generate visualizations
4. Create a summary report

### Quick Analysis (First 100 Rounds)

For faster analysis during development or testing:

```bash
python scripts/analyze_featured_app_rewards.py --max-rounds 100 --no-visualizations
```

### Analysis with CSV Export

```bash
python scripts/analyze_featured_app_rewards.py --export-csv --output-dir my_report
```

## Architecture

### System Components

The featured app rewards analysis system consists of three main components:

1. **FeaturedAppRewardsAnalyzer** (`featured_app_rewards_analyzer.py`)
   - Fetches aggregated data from `/v0/round-party-totals` API
   - Extracts app reward data (per-round and cumulative)
   - Calculates statistics and aggregations

2. **FeaturedAppRewardsVisualizer** (`featured_app_rewards_visualizer.py`)
   - Generates individual app progress charts
   - Creates comparison visualizations
   - Produces ecosystem overview charts
   - Exports publication-quality figures

3. **Main Analysis Script** (`analyze_featured_app_rewards.py`)
   - Provides command-line interface
   - Orchestrates the analysis workflow
   - Generates reports

### Data Flow

```
Canton Scan API
    |
round-party-totals endpoint (/v0/round-party-totals)
    |
Batch Fetching (50 rounds per request)
    |
Data Extraction & Aggregation
    |
Statistics Calculation
    |
Visualizations & Reports
```

## Data Model

### API Response Structure

The `/v0/round-party-totals` endpoint returns aggregated data:

```json
{
  "entries": [
    {
      "closed_round": 1,
      "party": "party_id",
      "app_rewards": "100.50",
      "cumulative_app_rewards": "100.50",
      "validator_rewards": "50.25"
    }
  ]
}
```

### AppRewardRecord

Each reward entry is stored as an `AppRewardRecord`:

```python
@dataclass
class AppRewardRecord:
    provider_party_id: str       # Featured app provider
    round_number: int            # Mining round number
    app_rewards: float           # Rewards for this round
    cumulative_app_rewards: float # Cumulative total up to this round
    metadata: Dict[str, Any]     # Full API response entry
```

### AppRewardStats

Aggregated statistics for each app:

```python
@dataclass
class AppRewardStats:
    provider_party_id: str
    total_rewards: float         # Total CC earned
    total_coupons: int           # Number of rounds with rewards
    avg_reward_per_round: float  # Average per round
    first_round: int             # First active round
    last_round: int              # Last active round
    rounds_active: int           # Number of rounds active
    rewards_by_round: Dict[int, float]
    cumulative_by_round: Dict[int, float]
```

## Command-Line Usage

### Basic Options

```bash
python scripts/analyze_featured_app_rewards.py [OPTIONS]
```

### Available Options

| Option | Default | Description |
|--------|---------|-------------|
| `--url URL` | `https://scan.sv-1.dev.global...` | Splice Scan API base URL |
| `--start-round N` | `1` | Starting round number |
| `--end-round N` | Auto | Ending round number |
| `--max-rounds N` | `500` | Maximum rounds to fetch |
| `--output-dir DIR` | `featured_app_rewards_report` | Output directory |
| `--top-apps N` | `10` | Number of top apps to analyze |
| `--no-visualizations` | Off | Skip generating charts |
| `--export-csv` | Off | Export data to CSV |
| `--verbose` | Off | Enable verbose logging |

### Usage Examples

#### 1. Default Analysis

```bash
python scripts/analyze_featured_app_rewards.py
```

Fetches up to 500 rounds, generates all visualizations, creates summary report.

#### 2. Quick Preview (100 Rounds, No Charts)

```bash
python scripts/analyze_featured_app_rewards.py --max-rounds 100 --no-visualizations
```

#### 3. Analysis with Data Export

```bash
python scripts/analyze_featured_app_rewards.py \
    --max-rounds 1000 \
    --export-csv \
    --output-dir full_analysis_2024
```

#### 4. Analyze Specific Round Range

```bash
python scripts/analyze_featured_app_rewards.py --start-round 100 --end-round 200
```

#### 5. Custom API Endpoint

```bash
python scripts/analyze_featured_app_rewards.py \
    --url https://custom.api.url/api/scan/ \
    --max-rounds 500
```

### Output Files

After running the analysis, the following files are generated:

```
featured_app_rewards_report/
├── summary_report.txt              # Text summary
├── top_apps_rewards.png            # Top apps by rewards
├── top_apps_activity.png           # Top apps by activity
├── ecosystem_overview.png          # Stacked area chart
├── rewards_heatmap.png             # Heatmap by app/round
├── reward_distribution.png         # Distribution analysis
├── timeline_per_round.png          # Per-round comparison
├── timeline_cumulative.png         # Cumulative comparison
├── app_01_*_progress.png           # Individual app charts
├── app_02_*_progress.png
├── ...
├── rewards_data.csv                # Raw data (if --export-csv)
└── app_statistics.csv              # Aggregated stats (if --export-csv)
```

## Programmatic Usage

### Basic Example

```python
from src.canton_scan_client import SpliceScanClient
from src.featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer

# Initialize client
client = SpliceScanClient(
    base_url='https://scan.sv-1.global.canton.network.cumberland.io/api/scan/'
)

# Create analyzer
analyzer = FeaturedAppRewardsAnalyzer(client)

# Fetch and process data
summary = analyzer.fetch_and_process_rewards(
    start_round=1,
    end_round=500,
    max_rounds=500
)

print(f"Found {summary['rewards_found']} reward records")
print(f"Unique apps: {summary['unique_apps']}")

# Get top apps
top_apps = analyzer.get_top_apps_by_rewards(limit=10)
for provider_id, stats in top_apps:
    print(f"{provider_id}: {stats.total_rewards:,.2f} CC")
```

### Analyzing a Specific App

```python
# Get statistics for a specific app
provider_id = "digital-asset.daml.com::12207c8f..."
stats = analyzer.get_provider_stats(provider_id)

if stats:
    print(f"Total Rewards: {stats.total_rewards:,.2f} CC")
    print(f"Rounds Active: {stats.rounds_active}")
    print(f"Avg per Round: {stats.avg_reward_per_round:.2f} CC")

    # Access round-by-round data
    for round_num, amount in stats.rewards_by_round.items():
        print(f"Round {round_num}: {amount:.2f} CC")
```

### Generating Visualizations

```python
from src.featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer

# Create visualizer
visualizer = FeaturedAppRewardsVisualizer(analyzer)

# Generate specific charts
visualizer.plot_top_apps_comparison(
    limit=15,
    output_file='my_top_apps.png',
    by_metric='rewards'
)

visualizer.plot_ecosystem_overview(
    output_file='my_ecosystem.png',
    top_n=20
)

# Generate individual app progress
visualizer.plot_app_progress(
    provider_party_id="...",
    output_file='app_progress.png',
    show_coupons=True
)

# Generate report
output_files = visualizer.generate_comprehensive_report(
    output_dir='my_report',
    top_apps_limit=15
)
```

### Exporting Data

```python
# Export raw rewards data
analyzer.export_to_csv('rewards.csv')

# Export aggregated statistics
analyzer.export_stats_to_csv('stats.csv')
```

### Custom Analysis

```python
# Get all app statistics
all_stats = analyzer.get_all_stats()

# Custom analysis: Find apps with highest average
high_avg_apps = sorted(
    all_stats.items(),
    key=lambda x: x[1].avg_reward_per_round,
    reverse=True
)[:10]

# Timeline analysis
timeline = analyzer.get_rewards_timeline()
for round_num, providers in sorted(timeline.items()):
    total = sum(providers.values())
    print(f"Round {round_num}: {total:,.2f} CC across {len(providers)} apps")
```

## Visualizations

### 1. Top Apps by Rewards (Bar Chart)

Shows the top N featured apps ranked by total rewards earned.

**File**: `top_apps_rewards.png`

**Features**:
- Horizontal bar chart for easy label reading
- Value labels on each bar
- Colorful gradient coloring

**Use Case**: Identify the most successful featured apps by total earnings.

### 2. Top Apps by Activity (Bar Chart)

Shows the top N featured apps ranked by number of rounds active.

**File**: `top_apps_activity.png`

**Features**:
- Shows consistency and longevity
- Identifies long-term contributors

**Use Case**: Find the most consistent and long-lasting featured apps.

### 3. Individual App Progress (Line Chart)

Shows reward progression over time for a single app.

**File**: `app_XX_*_progress.png`

**Features**:
- Primary axis: Rewards per round (blue line)
- Secondary axis: Cumulative rewards (orange dashed line)
- Statistics box with summary metrics
- Clear round-by-round progression

**Use Case**: Deep dive into a specific app's performance over time.

### 4. Timeline Comparison (Multi-Line Chart)

Compares multiple apps' reward progression over time.

**File**: `timeline_per_round.png` or `timeline_cumulative.png`

**Features**:
- Per-round view shows round-by-round rewards
- Cumulative view shows total accumulated rewards
- Up to 10 apps compared on one chart
- Color-coded for easy distinction

**Use Case**: Compare trends and growth patterns between apps.

### 5. Ecosystem Overview (Stacked Area Chart)

Shows the entire ecosystem's growth with top apps broken out.

**File**: `ecosystem_overview.png`

**Features**:
- Stacked areas for top 15 apps
- "Other" category for remaining apps
- Shows relative contribution of each app
- Visualizes ecosystem growth over time

**Use Case**: Understand ecosystem composition and overall growth trajectory.

### 6. Rewards Heatmap

Matrix view of rewards by app and round.

**File**: `rewards_heatmap.png`

**Features**:
- Color intensity represents reward amount
- Rows: Top 20 apps
- Columns: Mining rounds
- Identifies hot spots and patterns

**Use Case**: Spot patterns, gaps, and concentration of rewards.

### 7. Reward Distribution (Pie + Histogram)

Shows how rewards are distributed across all apps.

**File**: `reward_distribution.png`

**Features**:
- Left: Pie chart of top 10 apps + "Other"
- Right: Histogram showing distribution curve
- Reveals concentration vs. spread

**Use Case**: Understand fairness and concentration of reward distribution.

## Analysis Examples

### Example 1: Finding Top Performers

```python
# Get top 5 apps by total rewards
top_apps = analyzer.get_top_apps_by_rewards(limit=5)

for i, (provider_id, stats) in enumerate(top_apps, 1):
    print(f"{i}. Total: {stats.total_rewards:,.0f} CC")
    print(f"   Rounds: {stats.rounds_active}")
    print(f"   Avg/Round: {stats.avg_reward_per_round:.2f} CC")
```

### Example 2: Analyzing Growth Trends

```python
# Get rewards timeline
timeline = analyzer.get_rewards_timeline()

# Calculate growth metrics
for round_num in sorted(timeline.keys()):
    round_data = timeline[round_num]
    total_rewards = sum(round_data.values())
    num_apps = len(round_data)

    print(f"Round {round_num}: {total_rewards:,.0f} CC / {num_apps} apps")
```

### Example 3: Finding Most Consistent Apps

```python
# Apps active in the most rounds
top_consistent = analyzer.get_top_apps_by_activity(limit=10)

for provider_id, stats in top_consistent:
    span = stats.last_round - stats.first_round + 1
    consistency_pct = (stats.rounds_active / span) * 100

    print(f"{provider_id[:50]}")
    print(f"  Active: {stats.rounds_active}/{span} rounds ({consistency_pct:.1f}%)")
```

### Example 4: Comparing Two Apps

```python
from src.featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer

visualizer = FeaturedAppRewardsVisualizer(analyzer)

# Compare two specific apps
app1 = "provider_id_1"
app2 = "provider_id_2"

visualizer.plot_app_comparison_timeline(
    provider_ids=[app1, app2],
    output_file='comparison_two_apps.png',
    cumulative=True
)
```

## API Reference

### FeaturedAppRewardsAnalyzer

#### `__init__(client: SpliceScanClient)`

Initialize analyzer with API client.

#### `fetch_and_process_rewards(start_round: int = 1, end_round: int = None, max_rounds: int = 500) -> Dict[str, Any]`

Fetch and process app rewards from round-party-totals API.

**Returns**: Summary dictionary with:
- `entries_fetched`: Number of API entries fetched
- `batches_fetched`: Number of API batches retrieved
- `rewards_found`: Number of reward records found
- `unique_apps`: Number of unique featured apps
- `providers`: List of provider IDs

#### `get_provider_stats(provider_party_id: str) -> Optional[AppRewardStats]`

Get statistics for a specific app.

#### `get_all_stats() -> Dict[str, AppRewardStats]`

Get statistics for all apps.

#### `get_top_apps_by_rewards(limit: int = 10) -> List[Tuple[str, AppRewardStats]]`

Get top apps by total rewards.

#### `get_top_apps_by_activity(limit: int = 10) -> List[Tuple[str, AppRewardStats]]`

Get top apps by rounds active.

#### `get_rewards_timeline() -> Dict[int, Dict[str, float]]`

Get timeline mapping rounds to provider rewards.

#### `generate_summary_report() -> str`

Generate text summary report.

#### `export_to_csv(filename: str)`

Export raw reward data to CSV.

#### `export_stats_to_csv(filename: str)`

Export aggregated statistics to CSV.

### FeaturedAppRewardsVisualizer

#### `__init__(analyzer: FeaturedAppRewardsAnalyzer)`

Initialize visualizer with analyzer instance.

#### `plot_app_progress(provider_party_id: str, output_file: Optional[str] = None, show_coupons: bool = True) -> str`

Plot reward progression for a single app.

#### `plot_top_apps_comparison(limit: int = 10, output_file: str = 'top_apps_rewards.png', by_metric: str = 'rewards') -> str`

Plot comparison of top apps. `by_metric` can be 'rewards', 'activity', or 'coupons'.

#### `plot_app_comparison_timeline(provider_ids: List[str], output_file: str = 'apps_comparison_timeline.png', cumulative: bool = False) -> str`

Plot timeline comparison for multiple apps.

#### `plot_ecosystem_overview(output_file: str = 'ecosystem_overview.png', top_n: int = 15) -> str`

Plot stacked area chart of ecosystem.

#### `plot_rewards_heatmap(output_file: str = 'rewards_heatmap.png', top_n: int = 20) -> str`

Plot heatmap of rewards by app and round.

#### `plot_reward_distribution(output_file: str = 'reward_distribution.png') -> str`

Plot distribution analysis (pie chart + histogram).

#### `generate_comprehensive_report(output_dir: str = 'featured_app_rewards_report', top_apps_limit: int = 10) -> Dict[str, str]`

Generate report with all visualizations.

## Troubleshooting

### No Rewards Found

**Problem**: "No reward entries found in the fetched data"

**Solutions**:
1. Increase `--max-rounds` to fetch more data
2. Verify the API endpoint is correct
3. Check if the ledger has any featured app rewards yet
4. Try a different network endpoint

### Network/API Errors

**Problem**: Connection errors or timeouts

**Solutions**:
1. Check network connectivity
2. Verify the API URL is correct
3. Check if proxy settings are interfering
4. Try increasing timeout in client configuration

### Memory Issues

**Problem**: Out of memory when processing large datasets

**Solutions**:
1. Reduce `--max-rounds` and process in batches
2. Use `--no-visualizations` to reduce memory usage
3. Export to CSV and analyze externally

### Missing Dependencies

**Problem**: Import errors or missing modules

**Solutions**:
```bash
pip install matplotlib numpy
```

### Visualization Issues

**Problem**: Charts not generating or display errors

**Solutions**:
1. Ensure matplotlib is installed: `pip install matplotlib`
2. Check output directory permissions
3. For server environments, ensure matplotlib backend is configured:
   ```python
   import matplotlib
   matplotlib.use('Agg')
   ```

## Best Practices

1. **Start Small**: Use `--max-rounds 100` for initial exploration
2. **Export Data**: Always use `--export-csv` for long-running analyses
3. **Incremental Analysis**: Process data in batches for very large datasets
4. **Custom Analysis**: Use programmatic interface for specialized queries
5. **Version Control**: Keep reports organized by date/version
6. **Documentation**: Document your analysis parameters and findings

## Performance Notes

- **Fetching**: ~1-2 seconds per batch (50 rounds each)
- **Processing**: Very fast (pre-aggregated data from API)
- **Visualization**: ~2-5 seconds per chart
- **Analysis** (500 rounds): ~30-60 seconds

## Migration Note

This analyzer uses the `/v0/round-party-totals` API endpoint, which provides pre-aggregated data per party per round. This is much faster and more reliable than the previous approach of parsing individual `AppRewardCoupon` contract events from the update stream.

See [ROUND_PARTY_TOTALS_MIGRATION.md](ROUND_PARTY_TOTALS_MIGRATION.md) for details on the migration.

## References

- [Canton Scan API Documentation](https://docs.dev.sync.global/app_dev/scan_api/)
- [Update Tree Processing Guide](UPDATE_TREE_PROCESSING.md)
- [Splice Analytics Guide](README.md)
- [Canton Ledger Documentation](https://docs.daml.com/)
- [Round Party Totals Migration](ROUND_PARTY_TOTALS_MIGRATION.md)

## Support

For issues, questions, or feature requests:
1. Check this documentation
2. Review example scripts in `examples/`
3. Open an issue on the project repository
