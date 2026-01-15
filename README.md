# Canton Network Scan API Client

A comprehensive Python client for querying and analyzing on-chain data from the Canton Network using the Scan API.

## 🚀 Quick Start - No Authentication Required!

**The Canton Network Scan API is completely PUBLIC** - you can start retrieving on-chain data immediately with zero authentication setup!

```python
from canton_scan_client import CantonScanClient

# Initialize and start querying - that's it!
client = CantonScanClient(base_url="https://scan.canton.network/api/v1")
transactions = client.get_transactions(limit=10)
print(f"Retrieved {len(transactions['transactions'])} transactions!")
```

## Overview

This client provides an easy-to-use interface for:
- Querying transactions, contracts, and events from the Canton ledger
- Analyzing on-chain data patterns and trends
- Generating reports and visualizations
- All **without any authentication required**!

## Features

- **Zero Setup**: No authentication, tokens, or credentials required
- **Full API Coverage**: Support for all major Scan API endpoints
- **Robust Error Handling**: Automatic retries and comprehensive error messages
- **Data Analysis Tools**: Built-in analyzers for transaction volume, contract lifecycle, and party activity
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

The Canton Network Scan API is publicly accessible at:

```
https://scan.canton.network/api/v1
```

Simply provide this URL when initializing the client - **no authentication required**!

### Optional Configuration

You can optionally configure:

```yaml
api:
  base_url: "https://scan.canton.network/api/v1"
  timeout: 30  # Request timeout in seconds
  max_retries: 3  # Number of retry attempts
```

## Usage

### Basic Queries

```python
from canton_scan_client import CantonScanClient

# Initialize client - no authentication needed!
client = CantonScanClient(base_url="https://scan.canton.network/api/v1")

# Get recent transactions
transactions = client.get_transactions(limit=10)
print(f"Retrieved {len(transactions['transactions'])} transactions")

# Get active contracts
contracts = client.get_active_contracts(limit=100)
print(f"Found {len(contracts['contracts'])} active contracts")

# Get all parties
parties = client.get_parties()
print(f"Total parties: {len(parties['parties'])}")

# Close client when done
client.close()
```

### Using Context Manager

```python
# Recommended: use context manager for automatic cleanup
with CantonScanClient(base_url="https://scan.canton.network/api/v1") as client:
    # Your queries here
    transactions = client.get_transactions(limit=10)
    # Client automatically closes when exiting the context
```

### Time-Based Queries

```python
from datetime import datetime, timedelta

# Query transactions from last 24 hours
end_time = datetime.utcnow()
start_time = end_time - timedelta(days=1)

transactions = client.get_transactions(
    start_time=start_time.isoformat() + 'Z',
    end_time=end_time.isoformat() + 'Z',
    limit=100
)
```

### Paginated Queries

```python
# Retrieve all transactions using automatic pagination
all_transactions = client.get_all_transactions_paginated(
    batch_size=100,
    max_items=1000  # Optional limit
)

print(f"Retrieved {len(all_transactions)} total transactions")
```

### Data Analysis

```python
from examples.data_analysis import CantonDataAnalyzer

# Initialize analyzer
analyzer = CantonDataAnalyzer(client)

# Analyze transaction volume over time
volume_df = analyzer.analyze_transaction_volume(days=7, granularity='hour')
print(volume_df.describe())

# Analyze contract lifecycle
lifecycle = analyzer.analyze_contract_lifecycle()
print(f"Active contracts: {lifecycle['active_contracts']}")
print(f"Archival rate: {lifecycle['archival_rate']:.2%}")

# Analyze template usage
template_df = analyzer.analyze_template_usage()
print(template_df.head(10))

# Generate comprehensive report
report = analyzer.generate_summary_report()
print(report)
```

### JWT Token Inspection (Optional)

**Note:** JWT authentication is NOT required for the Scan API! However, if you're working with other Canton APIs that require authentication, the included JWT helper utilities can assist you:

```python
from examples.jwt_helper import inspect_jwt_token, validate_token_claims

# Inspect a JWT token (for other Canton APIs that need auth)
inspection = inspect_jwt_token(jwt_token)
print(f"Subject: {inspection['subject']}")
print(f"Audience: {inspection['audience']}")
print(f"Expires at: {inspection['expiry']['expires_at']}")
```

## Example Scripts

### Basic Queries Example

Run the basic queries example to start retrieving on-chain data:

```bash
cd examples
python basic_queries.py
```

The script uses the public API by default - just run it! You can optionally edit the `BASE_URL` if you're using a different Canton Network instance:

```python
BASE_URL = "https://scan.canton.network/api/v1"  # Default public API
```

### Data Analysis Example

Run comprehensive data analysis:

```bash
cd examples
python data_analysis.py
```

This will:
- Generate a summary report
- Analyze transaction volume and create visualizations
- Analyze template usage patterns
- Analyze party activity
- Export results to CSV files

### JWT Token Helper

Inspect and validate your JWT token:

```bash
cd examples
python jwt_helper.py "your-jwt-token-here"
```

## API Methods Reference

### Transactions

- `get_transactions(limit, offset, start_time, end_time, party_id)` - Get transactions
- `get_transaction_by_id(transaction_id)` - Get specific transaction
- `get_transaction_tree(limit, offset, party_id)` - Get transaction trees
- `get_all_transactions_paginated(batch_size, max_items, **kwargs)` - Get all transactions with pagination

### Contracts

- `get_active_contracts(template_id, limit, offset)` - Get active contracts
- `get_contract_by_id(contract_id)` - Get specific contract
- `search_contracts(query, limit)` - Search contracts with custom query

### Parties

- `get_parties()` - Get all parties
- `get_party_by_id(party_id)` - Get specific party

### Events

- `get_events(event_type, limit, offset, start_time, end_time)` - Get events

### Templates

- `get_templates()` - Get all templates
- `get_template_by_id(template_id)` - Get specific template

### Statistics

- `get_ledger_stats()` - Get overall ledger statistics
- `get_party_stats(party_id)` - Get party-specific statistics
- `get_template_stats(template_id)` - Get template-specific statistics

### Utility

- `get_ledger_time()` - Get current ledger time
- `get_ledger_identity()` - Get ledger identity
- `health_check()` - Check API health

## Data Analysis Features

### CantonDataAnalyzer

The analyzer provides several methods for analyzing on-chain data:

#### Transaction Volume Analysis

```python
volume_df = analyzer.analyze_transaction_volume(days=7, granularity='hour')
```

Returns a pandas DataFrame with transaction counts over time.

#### Contract Lifecycle Analysis

```python
lifecycle = analyzer.analyze_contract_lifecycle(template_id=None)
```

Returns statistics about contract creation, archival, and active contracts.

#### Party Activity Analysis

```python
party_df = analyzer.analyze_party_activity()
```

Returns a DataFrame with activity metrics for each party.

#### Template Usage Analysis

```python
template_df = analyzer.analyze_template_usage()
```

Returns a DataFrame with usage statistics for each template.

#### Visualization

```python
# Create transaction volume plot
analyzer.create_transaction_volume_plot(volume_df, 'output.png')

# Create template usage plot
analyzer.create_template_usage_plot(template_df, 'output.png')
```

## Project Structure

```
canton/
├── canton_scan_client.py      # Main API client
├── config_example.yaml         # Configuration template
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── examples/
    ├── basic_queries.py        # Basic query examples
    ├── data_analysis.py        # Data analysis examples
    └── jwt_helper.py           # JWT token utilities
```

## Error Handling

The client includes comprehensive error handling:

```python
try:
    transactions = client.get_transactions(limit=10)
except requests.exceptions.HTTPError as e:
    print(f"HTTP Error: {e}")
    print(f"Response: {e.response.text}")
except requests.exceptions.RequestException as e:
    print(f"Request Error: {e}")
```

## Best Practices

1. **Use Context Managers**: Always use the client as a context manager to ensure proper cleanup:
   ```python
   with CantonScanClient(base_url="https://scan.canton.network/api/v1") as client:
       # Your code here
   ```

2. **Use Pagination**: For large datasets, use pagination methods to avoid memory issues:
   ```python
   all_data = client.get_all_transactions_paginated(batch_size=100)
   ```

3. **Handle Errors**: Always wrap API calls in try-except blocks for production use:
   ```python
   try:
       transactions = client.get_transactions(limit=10)
   except Exception as e:
       print(f"Error: {e}")
   ```

4. **Rate Limiting**: Be mindful of API rate limits and implement appropriate delays if needed

5. **Cache Results**: Consider caching frequently accessed data to reduce API calls

## Troubleshooting

### Connection Errors

- Verify the base URL is correct: `https://scan.canton.network/api/v1`
- Check network connectivity
- Verify firewall rules allow outbound HTTPS connections
- Ensure DNS resolution is working

### Empty Results

- Check that the ledger has data in the queried time range
- Try querying without filters first to see if any data is available
- Verify you're using the correct API endpoint
- Check the API documentation for supported parameters

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

- Canton Network Documentation: https://docs.dev.sync.global/
- GitHub Issues: [Add your repository URL]
- Email: [Add support email]

## Changelog

### Version 1.0.0 (2026-01-15)

- Initial release
- Full Scan API coverage (completely public - no authentication required!)
- Zero-setup instant access to on-chain data
- Optional JWT authentication support for other Canton APIs
- Data analysis tools with pandas integration
- Visualization capabilities with matplotlib/seaborn
- Comprehensive examples and documentation
- Context manager support for easy resource management
