# Splice Network Scan API Client

A comprehensive Python client for querying and analyzing on-chain data from the Splice Network using the Scan API.

## 🚀 Quick Start - No Authentication Required!

**The Splice Network Scan API is completely PUBLIC** - you can start retrieving on-chain data immediately with zero authentication setup!

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
- All **without any authentication required**!

## Features

- **Zero Setup**: No authentication, tokens, or credentials required
- **Full Splice API Coverage**: Support for all Splice Scan API endpoints
- **Robust Error Handling**: Automatic retries and comprehensive error messages
- **Data Analysis Tools**: Built-in analyzers for update volume, mining rounds, and ANS entries
- **Visualization**: Generate charts and graphs from on-chain data
- **Pagination Support**: Efficient retrieval of large datasets
- **Type Hints**: Full type annotations for better IDE support

## Installation

### Prerequisites

- Python 3.8 or higher
- That's it! No credentials or authentication needed

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

3. Start using immediately - no configuration needed!

## Configuration

### API URL

The Splice Network Scan API is publicly accessible at:

```
https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/
```

Simply provide this URL when initializing the client - **no authentication required**!

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

# Initialize client - no authentication needed!
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

The script uses the public API by default - just run it! You can optionally edit the `BASE_URL` if you're using a different Splice Network instance:

```python
BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"  # Default public API
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

- `get_updates(after_migration_id, after_record_time, page_size, daml_value_encoding)` - Get update history (recommended v2 endpoint)
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

- `health_check()` - Check if API is accessible
- `get_readiness()` - Check API readiness

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

## Project Structure

```
canton/
├── canton_scan_client.py      # Main Splice API client
├── config_example.yaml         # Configuration template
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── examples/
    ├── basic_queries.py        # Basic query examples
    ├── data_analysis.py        # Data analysis examples
    └── jwt_helper.py           # JWT token utilities (for other APIs)
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
- API still completely public - no authentication required!

### Version 1.0.0

- Initial release with generic Canton Scan API support
