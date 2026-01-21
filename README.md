# Splice Network Scan API Client

A comprehensive Python client for querying and analyzing on-chain data from the Splice Network using the Scan API.

## Quick Start

```python
from canton_scan_client import SpliceScanClient

# Initialize and start querying - that's it!
client = SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/")
updates = client.get_updates(page_size=10)
print(f"Retrieved {len(updates['updates'])} updates!")
```

## Overview

This client provides an easy-to-use interface for:
- Querying updates (transactions), ANS entries, and amulet holdings from the Splice Network
- Analyzing on-chain data patterns and trends for the Splice ecosystem
- Tracking mining rounds, validators, and DSO information
- Generating reports and visualizations

## Features

- **Full Splice API Coverage**: Support for all Splice Scan API endpoints
- **Update Tree Processing**: Proper preorder traversal of event trees with state accumulation
- **Robust Error Handling**: Automatic retries and comprehensive error messages
- **Data Analysis Tools**: Built-in analyzers for update volume, mining rounds, ANS entries, and featured app rewards
- **Featured App Rewards Analysis**: Comprehensive tracking and visualization of AppRewardCoupon events
- **Selective Event Parsing**: Filter events by template ID for efficient processing
- **State Accumulation**: Track contracts, balances, mining rounds, and governance decisions
- **Defensive Parsing**: Handle new fields and templates gracefully without breaking
- **Visualization**: Generate charts and graphs from on-chain data including reward progression and comparisons
- **Pagination Support**: Efficient retrieval of large datasets
- **Type Hints**: Full type annotations for better IDE support

## Installation

### Prerequisites

- Python 3.8 or higher

### Setup

1. Clone or download this repository:

```bash
git clone <repository-url>
cd canton
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

For minimal installation (without data analysis features):

```bash
pip install requests urllib3
```

## Configuration

### API URL

The Splice Network Scan API is accessible at:

```
https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/
```

### Optional Configuration

You can optionally configure:

```yaml
api:
  base_url: "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"
  timeout: 30  # Request timeout in seconds
  max_retries: 3  # Number of retry attempts
```

## Usage

### Basic Queries

```python
from canton_scan_client import SpliceScanClient

# Initialize client
client = SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/")

# Get DSO information
dso = client.get_dso()
print(f"DSO Info: {dso}")

# Get recent updates (transaction history)
updates = client.get_updates(page_size=10)
print(f"Retrieved {len(updates['updates'])} updates")

# Get ANS entries
ans_entries = client.get_ans_entries(page_size=10)
print(f"Found {len(ans_entries['entries'])} ANS entries")

# Get mining rounds
rounds = client.get_open_and_issuing_mining_rounds()
print(f"Open rounds: {len(rounds['open_mining_rounds'])}")

# Close client when done
client.close()
```

### Using Context Manager

```python
# Recommended: use context manager for automatic cleanup
with SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/") as client:
    # Your queries here
    updates = client.get_updates(page_size=10)
    # Client automatically closes when exiting the context
```

### Update Tree Processing (Recommended)

For proper processing of updates with event tree traversal and state accumulation:

```python
from canton_scan_client import SpliceScanClient
from update_tree_processor import UpdateTreeProcessor

client = SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/")

# Fetch updates
updates_response = client.get_updates(page_size=100)
updates = updates_response['updates']

# Process updates with tree traversal
processor = UpdateTreeProcessor()
state = processor.process_updates(updates)

# Get summary
summary = processor.get_summary()
print(f"Processed {summary['updates_processed']} updates")
print(f"Tracked {summary['total_contracts']} contracts")

# Access accumulated state
contracts = processor.get_contract_states()
balances = processor.get_balance_history()
mining_rounds = processor.get_mining_rounds()
governance = processor.get_governance_decisions()
```

**Key Features:**
- ✅ Traverses update tree in preorder (root events first, then children)
- ✅ Selectively parses events based on template IDs
- ✅ Accumulates state for contracts, balances, mining rounds, and governance
- ✅ Defensive parsing that handles new fields/templates gracefully

See [UPDATE_TREE_PROCESSING.md](UPDATE_TREE_PROCESSING.md) for detailed documentation.

### Paginated Queries

```python
# Retrieve updates using pagination
after_migration_id = None
after_record_time = None
all_updates = []

for page in range(10):
    result = client.get_updates(
        after_migration_id=after_migration_id,
        after_record_time=after_record_time,
        page_size=100
    )

    updates = result.get('updates', [])
    if not updates:
        break

    all_updates.extend(updates)

    # Get cursor for next page
    if 'after' in result:
        after_migration_id = result['after']['after_migration_id']
        after_record_time = result['after']['after_record_time']
    else:
        break

print(f"Retrieved {len(all_updates)} total updates")
```

### Data Analysis

```python
from examples.data_analysis import SpliceDataAnalyzer

# Initialize analyzer
analyzer = SpliceDataAnalyzer(client)

# Analyze update volume over time
volume_df = analyzer.analyze_update_volume(max_pages=5, page_size=100)
print(volume_df.describe())

# Analyze mining rounds
mining_stats = analyzer.analyze_mining_rounds()
print(f"Open rounds: {mining_stats['open_rounds_count']}")
print(f"Issuing rounds: {mining_stats['issuing_rounds_count']}")

# Analyze ANS entries
ans_df = analyzer.analyze_ans_entries()
print(f"Total ANS entries: {len(ans_df)}")

# Analyze validator activity
validator_stats = analyzer.analyze_validator_activity()
print(f"Total validators: {validator_stats['total_validators']}")

# Generate comprehensive report
report = analyzer.generate_summary_report()
print(report)
```

## Example Scripts

### Basic Queries Example

Run the basic queries example to start retrieving on-chain data:

```bash
cd examples
python basic_queries.py
```

You can optionally edit the `BASE_URL` if you're using a different Splice Network instance:

```python
BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"
```

### Data Analysis Example

Run comprehensive data analysis:

```bash
cd examples
python data_analysis.py
```

This will:
- Generate a summary report with DSO and network information
- Analyze update volume and create visualizations
- Analyze ANS entry patterns
- Analyze mining rounds and validator activity
- Export results to CSV files

## API Methods Reference

### DSO Queries

- `get_dso()` - Get DSO information
- `get_dso_party_id()` - Get the party ID of the DSO

### Network Information

- `get_splice_instance_names()` - Retrieve UI names of Splice network elements

### Update History Queries

- `get_updates(after_migration_id, after_record_time, page_size, daml_value_encoding)` - Get update history (v2 endpoint)
- `get_updates_with_migrated_id(after_migration_id, after_record_time, page_size)` - Get updates with migrated ID

### ACS/State Queries

- `get_acs(migration_id, record_time, record_time_match, after, page_size, party_ids, templates)` - Get the ACS for a given migration id and record time
- `get_acs_with_state(migration_id, record_time, templates, page_size)` - Get ACS with state information

### Holdings Queries

- `get_holdings_state(migration_id, record_time, record_time_match, owner_party_ids, as_of_round)` - Get amulet holdings state
- `get_holdings_summary(migration_id, record_time, record_time_match, owner_party_ids, as_of_round)` - Get aggregated amulet holdings summary
- `get_total_amulet_balance(round_)` - Get total amulet balance across all users

### ANS Queries

- `get_ans_entries(page_size, name_prefix)` - List all non-expired ANS entries
- `lookup_ans_entry_by_party(party_id)` - Lookup ANS entry by party ID
- `lookup_ans_entry_by_name(name)` - Lookup ANS entry by name

### Mining Rounds

- `get_open_and_issuing_mining_rounds(cached_open_mining_round_contract_ids, cached_issuing_round_contract_ids)` - Get all current open and issuing mining rounds
- `get_closed_rounds()` - Get closed mining rounds still in post-close process

### Validator Queries

- `get_validator_faucets(validator_ids)` - Get validator liveness statistics
- `get_validator_licenses(after, limit)` - List all validators currently approved by DSO
- `get_validator_rights(limit)` - List validator right contracts
- `get_validator_onboarding_by_secret(secret)` - Lookup validator onboarding by secret

### Transfer Queries

- `get_transfer_preapproval_by_party(party)` - Lookup TransferPreapproval by receiver party
- `get_accepted_transfer_offers_by_party(party)` - Lookup accepted transfer offers for a party

### Event Queries

- `get_events(after_migration_id, after_record_time, page_size, daml_value_encoding)` - Get event history in ascending order, paged

### Domain/Synchronizer Queries

- `list_activity(active_synchronizer_id)` - List activity for a synchronizer
- `get_domain_id()` - Get the domain ID

### Amulet Configuration

- `get_amulet_rules()` - Get current amulet rules configuration
- `get_amulet_config_for_round(round_)` - Get amulet configuration for specific round

### Featured Apps

- `get_featured_app_rights()` - List featured app rights

### Votes

- `list_vote_requests(actionName, accepted, requester, effectiveFrom, effectiveTo, limit)` - List all current vote requests
- `list_vote_request_by_tracking_cid(trackingCid)` - Lookup vote request by tracking contract ID
- `list_vote_results_by_tracking_cid(trackingCid)` - List votes for a request

### Utility

- `health_check()` - Check if API is accessible (uses GET /v0/dso)

## Data Analysis Features

### SpliceDataAnalyzer

The analyzer provides several methods for analyzing on-chain data:

#### Update Volume Analysis

```python
volume_df = analyzer.analyze_update_volume(max_pages=10, page_size=100)
```

Returns a pandas DataFrame with update counts over time.

#### Mining Round Analysis

```python
mining_stats = analyzer.analyze_mining_rounds()
```

Returns statistics about open, issuing, and closed mining rounds.

#### ANS Entry Analysis

```python
ans_df = analyzer.analyze_ans_entries()
```

Returns a DataFrame with ANS entry statistics including expiration information.

#### Validator Activity Analysis

```python
validator_stats = analyzer.analyze_validator_activity()
```

Returns statistics about validator licensing and sponsorship.

#### Holdings Analysis

```python
holdings = analyzer.analyze_holdings_summary(migration_id=0, record_time="2025-01-01T00:00:00Z")
```

Returns amulet holdings statistics at a specific point in time.

#### Visualization

```python
# Create update volume plot
analyzer.create_update_volume_plot(volume_df, 'output.png')

# Create ANS analysis plots
analyzer.create_ans_analysis_plot(ans_df, 'output.png')
```

## Advanced Analytics Module

For comprehensive on-chain data analysis, use the `splice_analytics.py` module which provides 70+ specialized analysis functions:

```python
from splice_analytics import (
    TransactionAnalyzer,
    MiningRoundAnalyzer,
    ANSAnalyzer,
    ValidatorAnalyzer,
    EconomicAnalyzer,
    GovernanceAnalyzer,
    NetworkHealthAnalyzer
)

# Initialize client
client = SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/")

# Use specialized analyzers
tx_analyzer = TransactionAnalyzer(client)
updates = tx_analyzer.fetch_updates_batch(max_pages=10)
tx_rate = tx_analyzer.calculate_transaction_rate(updates)
spikes = tx_analyzer.detect_activity_spikes(updates)

mining_analyzer = MiningRoundAnalyzer(client)
rounds = mining_analyzer.get_all_rounds_summary()
timing = mining_analyzer.analyze_round_timing()

ans_analyzer = ANSAnalyzer(client)
entries = ans_analyzer.fetch_all_ans_entries()
patterns = ans_analyzer.analyze_name_patterns(entries)
saturation = ans_analyzer.analyze_namespace_saturation(entries)
premium = ans_analyzer.find_premium_names(entries, criteria={'max_length': 3})

validator_analyzer = ValidatorAnalyzer(client)
validators = validator_analyzer.get_validator_summary()
decentralization = validator_analyzer.calculate_decentralization_score(validators)

# Generate comprehensive network health report
health_analyzer = NetworkHealthAnalyzer(client)
health_score = health_analyzer.generate_health_score()
report = health_analyzer.generate_comprehensive_report()
print(report)
```

### Available Analysis Functions

**TransactionAnalyzer**:
- `fetch_updates_batch()` - Fetch updates with pagination
- `calculate_transaction_rate()` - Throughput and rate statistics
- `analyze_update_types()` - Update type distribution
- `detect_activity_spikes()` - Anomaly detection
- `calculate_growth_rate()` - Period-over-period growth

**MiningRoundAnalyzer**:
- `get_all_rounds_summary()` - Round state statistics
- `analyze_round_timing()` - Duration and timing patterns
- `track_round_progression()` - Historical progression tracking

**ANSAnalyzer**:
- `fetch_all_ans_entries()` - Complete ANS dataset
- `analyze_name_patterns()` - Character and length analysis
- `analyze_expiration_patterns()` - Expiry timeline analysis
- `analyze_namespace_saturation()` - Short name availability
- `find_premium_names()` - Premium name identification

**ValidatorAnalyzer**:
- `get_validator_summary()` - Network statistics
- `analyze_validator_growth()` - Growth tracking
- `calculate_decentralization_score()` - Decentralization metric

**EconomicAnalyzer**:
- `get_total_supply()` - Amulet supply queries
- `analyze_amulet_rules()` - Economic configuration
- `estimate_velocity()` - Token velocity estimation

**GovernanceAnalyzer**:
- `analyze_vote_requests()` - Voting pattern analysis
- `calculate_governance_participation()` - Participation metrics

**NetworkHealthAnalyzer**:
- `generate_health_score()` - Composite 100-point health score
- `generate_comprehensive_report()` - Full network health report

**FeaturedAppRewardsAnalyzer**:
- `fetch_and_process_rewards()` - Extract AppRewardCoupon events from ledger
- `get_provider_stats()` - Statistics for specific featured app
- `get_top_apps_by_rewards()` - Top apps by total rewards
- `get_top_apps_by_activity()` - Top apps by rounds active
- `get_rewards_timeline()` - Timeline of rewards by round
- `generate_summary_report()` - Text summary report
- `export_to_csv()` - Export raw reward data
- `export_stats_to_csv()` - Export aggregated statistics

**Utility Functions**:
- `calculate_gini_coefficient()` - Wealth inequality metric
- `export_to_csv()` - Export data to CSV files

## Featured App Rewards Analysis

Analyze featured app rewards by processing `AppRewardCoupon` contract creation events from the Canton ledger. This provides comprehensive insights into reward distribution, app performance, and ecosystem growth.

### Quick Start - Command Line

Run a complete analysis with visualizations:

```bash
python analyze_featured_app_rewards.py
```

This generates:
- Summary report with top apps statistics
- Individual progress charts for each top app
- Comparison visualizations across apps
- Ecosystem overview and heatmaps
- CSV export of raw data and statistics

### Quick Start - Programmatic

```python
from canton_scan_client import SpliceScanClient
from featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer
from featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer

# Initialize
client = SpliceScanClient(base_url="...")
analyzer = FeaturedAppRewardsAnalyzer(client)

# Fetch and process AppRewardCoupon events
summary = analyzer.fetch_and_process_rewards(max_pages=100, page_size=100)
print(f"Found {summary['rewards_found']} reward coupons for {summary['unique_apps']} apps")

# Get top apps by total rewards
top_apps = analyzer.get_top_apps_by_rewards(limit=10)
for provider_id, stats in top_apps:
    print(f"{provider_id}: {stats.total_rewards:,.2f} CC over {stats.rounds_active} rounds")

# Generate visualizations
visualizer = FeaturedAppRewardsVisualizer(analyzer)
visualizer.generate_comprehensive_report(output_dir='rewards_report', top_apps_limit=10)

# Export data
analyzer.export_to_csv('rewards_data.csv')
analyzer.export_stats_to_csv('app_statistics.csv')
```

### Visualization Types

The Featured App Rewards system generates:

1. **Individual Progress Charts** - Reward progression over mining rounds for each app
2. **Top Apps Rankings** - Bar charts of top performers by rewards or activity
3. **Timeline Comparisons** - Multi-app comparison charts (per-round and cumulative)
4. **Ecosystem Overview** - Stacked area chart showing ecosystem composition
5. **Rewards Heatmap** - Matrix view of rewards by app and round
6. **Distribution Analysis** - Pie charts and histograms of reward distribution

### Command-Line Options

```bash
# Quick analysis (10 pages, no visualizations)
python analyze_featured_app_rewards.py --max-pages 10 --no-visualizations

# Full analysis with CSV export
python analyze_featured_app_rewards.py --export-csv --max-pages 200

# Analyze top 20 apps in detail
python analyze_featured_app_rewards.py --top-apps 20

# Custom output directory
python analyze_featured_app_rewards.py --output-dir my_analysis
```

### Documentation

For comprehensive documentation, examples, and API reference, see:
- [Featured App Rewards Analysis Guide](FEATURED_APP_REWARDS_GUIDE.md)
- [Example Scripts](examples/featured_app_rewards_example.py)

## Data Analytics Insights

For executive-level insights and strategic decision-making, use the `splice_insights.py` module which provides actionable business intelligence:

```python
from splice_insights import (
    NetworkGrowthInsights,
    UserBehaviorInsights,
    EconomicHealthInsights,
    DecentralizationInsights,
    GovernanceInsights,
    InsightVisualizer
)

client = SpliceScanClient(base_url="...")

# Growth & Sustainability Analysis
growth_insights = NetworkGrowthInsights(client)
trajectory = growth_insights.analyze_growth_trajectory(max_pages=20)

print(f"Growth Status: {trajectory['interpretation']}")
print(f"30-day Projection: {trajectory['projection_30d']} updates")
print(f"Sustainability Score: {trajectory['sustainability_score']}/100")

# Detect viral events or anomalies
spikes = growth_insights.detect_viral_events(updates, spike_threshold=3.0)
for spike in spikes:
    print(f"Spike at {spike['timestamp']}: {spike['severity']} - {spike['likely_cause']}")

# User Behavior & Infrastructure Optimization
behavior_insights = UserBehaviorInsights(client)
patterns = behavior_insights.analyze_temporal_patterns(updates)

print(f"Peak Hour: {patterns['peak_hour_utc']}:00 UTC")
print(f"Infrastructure Insight: {patterns['infrastructure_insight']}")
print(f"User Pattern: {patterns['user_pattern_insight']}")

# Power user analysis
power_users = behavior_insights.analyze_power_users(updates)
print(f"Concentration Risk: {power_users['risk_assessment']}")
print(f"Diversity Score: {power_users['diversity_score']}/100")

# Economic Health Assessment
economic_insights = EconomicHealthInsights(client)
velocity_analysis = economic_insights.analyze_token_velocity(updates, total_supply=1000000)
print(f"Velocity Analysis: {velocity_analysis['interpretation']}")

# Decentralization & Security
decentral_insights = DecentralizationInsights(client)
risk_assessment = decentral_insights.assess_decentralization_risk(validator_data)

print(f"Security Risk Level: {risk_assessment['risk_level']}")
print(f"Nakamoto Coefficient: {risk_assessment['nakamoto_coefficient_estimate']}")
print(f"Assessment: {risk_assessment['security_assessment']}")

# Governance Effectiveness
gov_insights = GovernanceInsights(client)
governance_health = gov_insights.analyze_governance_health(vote_data, validator_count)

print(f"Governance Health: {governance_health['overall_health']}")
print(f"Community Priorities: {governance_health['community_priorities']}")

# Generate Executive Dashboard (one-page visual summary)
visualizer = InsightVisualizer(client)
visualizer.create_executive_dashboard('executive_dashboard.png')
```

### Critical Business Questions Answered

**For Executives & Investors:**
- Is the network growing sustainably? → Growth trajectory analysis
- What's the 30/90/180-day outlook? → Growth projections
- Is the network healthy overall? → Composite health score (0-100)
- Resource allocation analysis → Risk assessments & classifications

**For Network Operators:**
- Infrastructure scaling timing → Peak hour analysis
- Power user concentration risk → Concentration risk metrics
- Traffic spike analysis → Anomaly detection with cause inference
- Decentralization status → Decentralization score tracking

**For Token Economists:**
- Is wealth concentrating dangerously? → Gini coefficient & inequality metrics
- Is token velocity healthy? → Velocity analysis with interpretations
- What's the supply outlook? → Supply dynamics tracking
- Are we at risk of plutocracy? → Wealth concentration assessments

**For Security Teams:**
- How many validators to compromise? → Nakamoto coefficient
- Is centralization increasing? → Decentralization risk scoring
- Are there geographic risks? → Validator distribution analysis
- What's our security posture? → Comprehensive security assessment

**For Community Managers:**
- When are users most active? → Temporal pattern analysis
- Who are the power users? → Top user identification
- Is participation healthy? → Governance participation metrics
- What does community want? → Priority inference from proposals

### Output Classifications

**Risk Assessments**:
- HIGH RISK / MODERATE RISK / LOW RISK classifications
- Quantitative thresholds and scoring
- Risk level determination

**Growth Classifications**:
- EXCELLENT: Strong accelerating growth
- GOOD: Positive growth trend
- WATCH: Growth slowing
- CRITICAL: Declining activity

**Infrastructure Analysis**:
- Peak pattern identification
- Resource allocation metrics
- Utilization patterns

**Executive Visualizations**:
- 6-panel executive dashboard (PNG export)
- Growth trajectories with trend lines
- Activity heatmaps (hourly × daily)
- Health score gauges
- Key metrics summaries
- Distribution charts

## Project Structure

```
canton/
├── canton_scan_client.py      # Main Splice API client
├── splice_analytics.py         # Comprehensive analytics module (70+ functions)
├── splice_insights.py          # Data analytics insights & visualizations
├── config_example.yaml         # Configuration template
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── examples/
    ├── basic_queries.py        # Basic query examples
    └── data_analysis.py        # Data analysis examples
```

```
canton/
├── canton_scan_client.py      # Main Splice API client
├── splice_analytics.py         # Comprehensive analytics module (70+ functions)
├── config_example.yaml         # Configuration template
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── examples/
    ├── basic_queries.py        # Basic query examples
    └── data_analysis.py        # Data analysis examples
```

## Error Handling

The client includes comprehensive error handling:

```python
try:
    updates = client.get_updates(page_size=10)
except requests.exceptions.HTTPError as e:
    print(f"HTTP Error: {e}")
    print(f"Response: {e.response.text}")
except requests.exceptions.RequestException as e:
    print(f"Request Error: {e}")
```

## Best Practices

1. **Use Context Managers**: Always use the client as a context manager to ensure proper cleanup:
   ```python
   with SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/") as client:
       # Your code here
   ```

2. **Use Pagination**: For large datasets, use pagination to avoid memory issues:
   ```python
   # Fetch updates in pages
   result = client.get_updates(page_size=100, after_migration_id=prev_id, after_record_time=prev_time)
   ```

3. **Handle Errors**: Always wrap API calls in try-except blocks for production use:
   ```python
   try:
       updates = client.get_updates(page_size=10)
   except Exception as e:
       print(f"Error: {e}")
   ```

4. **Rate Limiting**: Be mindful of API rate limits and implement appropriate delays if needed

5. **Cache Results**: Consider caching frequently accessed data to reduce API calls

## Troubleshooting

### Connection Errors

- Verify the base URL is correct: `https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/`
- Check network connectivity
- Verify firewall rules allow outbound HTTPS connections
- Ensure DNS resolution is working

### Empty Results

- Check that the Splice Network has data in the queried time range
- Try querying without filters first to see if any data is available
- Verify you're using the correct API endpoint
- Check the official Splice API documentation for supported parameters

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Follow PEP 8 style guidelines
2. Add type hints to all functions
3. Include docstrings for public methods
4. Add tests for new features
5. Update documentation as needed

## License

[Add your license information here]

## Support

For issues and questions:

- Splice Network Documentation: https://docs.splice.global/
- GitHub Issues: [Add your repository URL]
- Email: [Add support email]

## Changelog

### Version 2.0.0 (2026-01-15)

- **BREAKING CHANGE**: Complete rewrite to support Splice Network Scan API
- Changed from `CantonScanClient` to `SpliceScanClient`
- Replaced generic Canton ledger methods with Splice-specific endpoints
- Added support for:
  - DSO queries
  - ANS (Amulet Name Service) entries
  - Mining rounds (open, issuing, closed)
  - Amulet holdings and balances
  - Validator faucets and licenses
  - Transfer preapprovals
  - Featured app rights
  - Vote requests and results
  - Splice-specific network configuration
- Updated all examples to use new Splice API methods
- Updated data analyzer to work with Splice data structures

### Version 1.0.0

- Initial release with generic Canton Scan API support
