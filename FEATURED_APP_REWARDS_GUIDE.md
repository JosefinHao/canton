# Featured App Rewards Analysis Guide

## Overview

This guide explains how to analyze featured app rewards from the Canton ledger by processing `AppRewardCoupon` contract creation events from the update stream. The analysis system provides:

1. **Comprehensive Data Extraction** - Retrieve all AppRewardCoupon events from the ledger
2. **Systematic Organization** - Group rewards by featured app (provider party ID)
3. **Statistical Analysis** - Calculate metrics and progress for each app
4. **Rich Visualizations** - Generate charts showing individual progress and comparisons
5. **Export Capabilities** - Export data to CSV for further analysis

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

Run a complete analysis with default settings:

```bash
python analyze_featured_app_rewards.py
```

This will:
1. Fetch up to 100 pages of updates from the ledger
2. Extract all AppRewardCoupon creation events
3. Calculate statistics for each featured app
4. Generate comprehensive visualizations
5. Create a summary report

### Quick Analysis (First 10 Pages)

For faster analysis during development or testing:

```bash
python analyze_featured_app_rewards.py --max-pages 10 --no-visualizations
```

### Full Analysis with CSV Export

```bash
python analyze_featured_app_rewards.py --export-csv --output-dir my_report
```

## Architecture

### System Components

The featured app rewards analysis system consists of three main components:

1. **FeaturedAppRewardsAnalyzer** (`featured_app_rewards_analyzer.py`)
   - Fetches updates from Canton ledger
   - Traverses event trees to find AppRewardCoupon creation events
   - Extracts reward data (amount, weight, provider, round)
   - Calculates statistics and aggregations

2. **FeaturedAppRewardsVisualizer** (`featured_app_rewards_visualizer.py`)
   - Generates individual app progress charts
   - Creates comparison visualizations
   - Produces ecosystem overview charts
   - Exports publication-quality figures

3. **Main Analysis Script** (`analyze_featured_app_rewards.py`)
   - Provides command-line interface
   - Orchestrates the analysis workflow
   - Generates comprehensive reports

### Data Flow

```
Canton Ledger
    ↓
Update Stream (via get_updates API)
    ↓
Event Tree Traversal
    ↓
AppRewardCoupon Creation Events
    ↓
Data Extraction & Aggregation
    ↓
Statistics Calculation
    ↓
Visualizations & Reports
```

## Data Model

### AppRewardCoupon Event Structure

AppRewardCoupon contracts are created on the Canton ledger with the following data:

```json
{
  "template_id": "*.AppRewardCoupon",
  "contract_id": "...",
  "create_arguments": {
    "provider": "party_id",
    "round": 123,
    "amount": 100.0,
    "weight": 1.5
  }
}
```

### AppRewardRecord

Each reward coupon is stored as an `AppRewardRecord`:

```python
@dataclass
class AppRewardRecord:
    provider_party_id: str      # Featured app provider
    round_number: int            # Mining round number
    amount: float                # Reward amount in CC
    weight: float                # App weight/priority
    contract_id: str             # Contract identifier
    record_time: str             # Timestamp
    event_id: str                # Event identifier
    payload: Dict[str, Any]      # Full payload
```

### AppRewardStats

Aggregated statistics for each app:

```python
@dataclass
class AppRewardStats:
    provider_party_id: str
    total_rewards: float         # Total CC earned
    total_coupons: int           # Number of coupons
    total_weight: float          # Sum of weights
    avg_reward_per_coupon: float
    avg_weight_per_coupon: float
    first_round: int             # First active round
    last_round: int              # Last active round
    rounds_active: int           # Number of rounds active
    rewards_by_round: Dict[int, float]
    coupons_by_round: Dict[int, int]
    weight_by_round: Dict[int, float]
```

## Command-Line Usage

### Basic Options

```bash
python analyze_featured_app_rewards.py [OPTIONS]
```

### Available Options

| Option | Default | Description |
|--------|---------|-------------|
| `--url URL` | `https://scan.sv-1.dev.global...` | Splice Scan API base URL |
| `--max-pages N` | `100` | Maximum pages to fetch |
| `--page-size N` | `100` | Updates per page |
| `--output-dir DIR` | `featured_app_rewards_report` | Output directory |
| `--top-apps N` | `10` | Number of top apps to analyze |
| `--no-visualizations` | Off | Skip generating charts |
| `--export-csv` | Off | Export data to CSV |
| `--verbose` | Off | Enable verbose logging |

### Usage Examples

#### 1. Default Analysis

```bash
python analyze_featured_app_rewards.py
```

Fetches 100 pages, generates all visualizations, creates summary report.

#### 2. Quick Preview (10 Pages, No Charts)

```bash
python analyze_featured_app_rewards.py --max-pages 10 --no-visualizations
```

#### 3. Full Analysis with Data Export

```bash
python analyze_featured_app_rewards.py \
    --max-pages 200 \
    --export-csv \
    --output-dir full_analysis_2024
```

#### 4. Analyze Top 20 Apps

```bash
python analyze_featured_app_rewards.py --top-apps 20
```

#### 5. Custom API Endpoint

```bash
python analyze_featured_app_rewards.py \
    --url https://custom.api.url/api/scan/ \
    --max-pages 50
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
from canton_scan_client import SpliceScanClient
from featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer

# Initialize client
client = SpliceScanClient(
    base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
)

# Create analyzer
analyzer = FeaturedAppRewardsAnalyzer(client)

# Fetch and process data
summary = analyzer.fetch_and_process_rewards(
    max_pages=50,
    page_size=100
)

print(f"Found {summary['rewards_found']} reward coupons")
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
    print(f"Avg per Coupon: {stats.avg_reward_per_coupon:.2f} CC")

    # Access round-by-round data
    for round_num, amount in stats.rewards_by_round.items():
        print(f"Round {round_num}: {amount:.2f} CC")
```

### Generating Visualizations

```python
from featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer

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

# Generate comprehensive report
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
    key=lambda x: x[1].avg_reward_per_coupon,
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
- Secondary axis: Coupon count per round (orange dashed line)
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
    print(f"   Avg/Coupon: {stats.avg_reward_per_coupon:.2f} CC")
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
from featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer

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

#### `fetch_and_process_rewards(max_pages: int = 100, page_size: int = 100) -> Dict[str, Any]`

Fetch updates and process AppRewardCoupon events.

**Returns**: Summary dictionary with:
- `updates_fetched`: Number of updates fetched
- `pages_fetched`: Number of pages retrieved
- `rewards_found`: Number of reward coupons found
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

Generate complete report with all visualizations.

## Troubleshooting

### No Rewards Found

**Problem**: "No AppRewardCoupon events found in the fetched data"

**Solutions**:
1. Increase `--max-pages` to fetch more data
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
1. Reduce `--max-pages` and process in batches
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

1. **Start Small**: Use `--max-pages 10` for initial exploration
2. **Export Data**: Always use `--export-csv` for long-running analyses
3. **Incremental Analysis**: Process data in batches for very large datasets
4. **Custom Analysis**: Use programmatic interface for specialized queries
5. **Version Control**: Keep reports organized by date/version
6. **Documentation**: Document your analysis parameters and findings

## Performance Notes

- **Fetching**: ~1-2 seconds per page (100 updates each)
- **Processing**: ~0.1 seconds per 100 updates
- **Visualization**: ~2-5 seconds per chart
- **Complete Analysis** (100 pages): ~3-5 minutes

## Contributing

When extending the analysis system:

1. Add new metrics to `AppRewardStats`
2. Implement new visualization types in `FeaturedAppRewardsVisualizer`
3. Create new analysis methods in `FeaturedAppRewardsAnalyzer`
4. Update this documentation
5. Add examples to `examples/featured_app_rewards_example.py`

## References

- [Canton Scan API Documentation](https://docs.dev.sync.global/app_dev/scan_api/)
- [Update Tree Processing Guide](UPDATE_TREE_PROCESSING.md)
- [Splice Analytics Guide](README.md)
- [Canton Ledger Documentation](https://docs.daml.com/)

## Support

For issues, questions, or feature requests:
1. Check this documentation
2. Review example scripts in `examples/`
3. Open an issue on the project repository
