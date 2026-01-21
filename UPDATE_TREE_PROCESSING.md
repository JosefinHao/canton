# Update Tree Processing Guide

## Overview

This guide explains how to process Canton Scan API updates using proper tree traversal and state accumulation. The `UpdateTreeProcessor` module implements the recommended approach for processing updates:

1. **Traverse the update tree in preorder** - Start with root event IDs, then process child event IDs recursively
2. **Selectively parse events** - Based on template IDs and contract structure
3. **Accumulate state changes** - Track contracts, balances, mining rounds, and governance decisions
4. **Defensive parsing** - Handle new fields and templates gracefully without breaking

## Background: Update Tree Structure

Canton/Daml transactions are represented as trees of events. Each update from the Canton Scan API v2 has:

- **`root_event_ids`**: Array of strings representing the top-level events (entry points to the tree)
- **`events_by_id`**: Object/map where keys are event IDs and values are event data
- **`child_event_ids`**: Each exercised event contains an array of child event IDs

### Event Types

1. **Created Events** - Contract creation
   - Contains: `template_id`, `contract_id`, `create_arguments`

2. **Archived Events** - Contract archival
   - Contains: `template_id`, `contract_id`

3. **Exercised Events** - Choice execution
   - Contains: `template_id`, `contract_id`, `choice`, `choice_argument`, `child_event_ids`

### Tree Traversal Order

The processor traverses the tree in **preorder** (depth-first):
1. Process the current node (event)
2. Recursively process all children in order

This ensures events are processed in the order they occurred in the transaction.

## Quick Start

### Basic Usage

```python
from canton_scan_client import SpliceScanClient
from update_tree_processor import UpdateTreeProcessor

# Initialize client
client = SpliceScanClient(base_url="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/")

# Fetch updates
updates = client.get_updates(page_size=100)

# Create processor and process updates
processor = UpdateTreeProcessor()
state = processor.process_updates(updates['updates'])

# Get summary
summary = processor.get_summary()
print(f"Processed {summary['updates_processed']} updates")
print(f"Tracked {summary['total_contracts']} contracts")
```

### Using with TransactionAnalyzer

```python
from splice_analytics import TransactionAnalyzer

# Initialize analyzer
analyzer = TransactionAnalyzer(client)

# Process updates with tree traversal
result = analyzer.process_updates_with_tree_traversal(
    max_pages=10,
    page_size=100
)

# Access results
print(result['summary'])
contracts = result['contracts']
balances = result['balances']
mining_rounds = result['mining_rounds']
governance = result['governance']
```

## Selective Parsing with Template Filters

You can filter events by template ID to only process specific contract types:

```python
# Only process Amulet-related contracts
result = processor.process_updates(
    updates,
    filter_templates=['Amulet']
)

# Process multiple template types
result = processor.process_updates(
    updates,
    filter_templates=['Amulet', 'MiningRound', 'Validator']
)
```

### Built-in Template Patterns

The processor recognizes these template categories:

- **`amulet`**: Canton Coin contracts
  - `Splice.Amulet:Amulet`
  - `Splice.AmuletRules:AmuletRules`

- **`mining_round`**: Mining round contracts
  - `Splice.Round:OpenMiningRound`
  - `Splice.Round:IssuingMiningRound`
  - `Splice.Round:ClosedMiningRound`

- **`ans`**: Amulet Name Service
  - `Splice.Ans:AnsEntry`
  - `Splice.AnsRules:AnsRules`

- **`validator`**: Validator contracts
  - `Splice.ValidatorLicense:ValidatorLicense`
  - `Splice.ValidatorRight:ValidatorRight`

- **`governance`**: Governance contracts
  - `Splice.DsoRules:VoteRequest`
  - `Splice.DsoRules:Vote`
  - `Splice.DsoRules:DsoRules`

## State Accumulation

### Contract States

Track all contract creation and archival:

```python
# Get all tracked contracts
contracts = processor.get_contract_states()

# Get only active contracts
active_contracts = processor.get_active_contracts()

# Access contract details
for contract in active_contracts:
    print(f"Contract ID: {contract.contract_id}")
    print(f"Template: {contract.template_id}")
    print(f"Created: {contract.created_at}")
    print(f"Active: {contract.is_active}")
```

### Balance Tracking

Track Canton Coin (Amulet) balances and transfers:

```python
# Get balance history for all owners
balances = processor.get_balance_history()

# Get balance for specific owner
owner_balances = processor.get_balance_history(owner='party_id')

# Calculate current balance
for owner, records in balances.items():
    current_balance = sum(r.amount for r in records)
    print(f"{owner}: {current_balance}")
```

### Mining Round Tracking

Track mining round states and transitions:

```python
# Get all mining rounds
mining_rounds = processor.get_mining_rounds()

# Access round details
for round_num, round_state in mining_rounds.items():
    print(f"Round {round_num}:")
    print(f"  Status: {round_state.status}")
    print(f"  Opened: {round_state.opened_at}")
    print(f"  Issuing: {round_state.issuing_at}")
    print(f"  Closed: {round_state.closed_at}")

# Get current round
current_round = processor.state.current_round
```

### Governance Decisions

Track governance votes and decisions:

```python
# Get all governance decisions
governance = processor.get_governance_decisions()

# Access decision details
for vote_id, decision in governance.items():
    print(f"Action: {decision.action_name}")
    print(f"Requested: {decision.requested_at}")
    print(f"Votes: {len(decision.votes)}")

    # Analyze votes
    for vote in decision.votes:
        print(f"  {vote['voter']}: {'Accept' if vote['accept'] else 'Reject'}")
```

## Custom Event Handlers

You can register custom handlers for specific template types:

```python
def my_custom_handler(event_type, template_id, event_data, record_time, state):
    """
    Custom handler for processing specific events.

    Args:
        event_type: 'created', 'archived', or 'exercised'
        template_id: The template ID of the contract
        event_data: The event data
        record_time: When the event occurred
        state: The ProcessorState object (for accessing accumulated state)
    """
    if event_type == 'created':
        # Handle contract creation
        print(f"New {template_id} created at {record_time}")
    elif event_type == 'archived':
        # Handle contract archival
        print(f"{template_id} archived at {record_time}")

# Register custom handler
processor = UpdateTreeProcessor(
    custom_handlers={
        'Validator': my_custom_handler,
        'AnsEntry': my_custom_handler
    }
)

processor.process_updates(updates)
```

## Defensive Parsing

The processor uses defensive parsing to handle:

1. **Missing fields** - Uses safe defaults when fields are missing
2. **New template types** - Logs but doesn't fail on unknown templates
3. **Schema changes** - Adapts to new field structures
4. **Malformed data** - Continues processing even if individual events fail

### Error Handling

```python
# Process updates (errors are logged, not raised)
state = processor.process_updates(updates)

# Check for errors
summary = processor.get_summary()
if summary['errors_encountered'] > 0:
    print(f"Encountered {summary['errors_encountered']} errors")
    print("Errors:", processor.state.errors_encountered)
```

## Advanced Usage

### Accessing Processor State

The `ProcessorState` object contains all accumulated data:

```python
state = processor.state

# Access raw data structures
contracts = state.contracts  # Dict[str, ContractState]
active_contracts = state.active_contracts  # Set[str]
balances = state.balances  # Dict[str, List[BalanceRecord]]
mining_rounds = state.mining_rounds  # Dict[int, MiningRoundState]
governance_decisions = state.governance_decisions  # Dict[str, GovernanceDecision]

# Statistics
print(f"Events processed: {state.events_processed}")
print(f"Updates processed: {state.updates_processed}")
```

### Batch Processing with Pagination

```python
# Process multiple pages of updates
all_results = []

after_migration_id = None
after_record_time = None

for page in range(10):
    # Fetch page
    result = client.get_updates(
        after_migration_id=after_migration_id,
        after_record_time=after_record_time,
        page_size=100
    )

    updates = result.get('updates', [])
    if not updates:
        break

    # Process this page
    processor.process_updates(updates)

    # Get cursor for next page
    if 'after' in result:
        after_migration_id = result['after']['after_migration_id']
        after_record_time = result['after']['after_record_time']
    else:
        break

# Final summary
print(processor.get_summary())
```

## Performance Considerations

1. **Memory Usage**: The processor accumulates state in memory. For very large datasets, consider:
   - Processing in batches
   - Periodically exporting/clearing state
   - Using filter_templates to reduce memory footprint

2. **Processing Speed**: Tree traversal is efficient (O(n) where n = number of events)
   - Each event is processed exactly once
   - No redundant lookups or iterations

3. **API Rate Limits**: Respect Canton Scan API rate limits when fetching updates

## Complete Example

See `examples/update_processing_example.py` for a complete working example that demonstrates:

- Basic update processing
- Filtered processing by template
- Custom event handlers
- State accumulation and reporting
- Integration with the analytics module

## API Reference

### UpdateTreeProcessor

Main class for processing update trees.

**Methods:**

- `process_updates(updates, filter_templates=None)` - Process a list of updates
- `get_summary()` - Get processing statistics
- `get_contract_states()` - Get all contract states
- `get_active_contracts()` - Get active contracts
- `get_balance_history(owner=None)` - Get balance history
- `get_mining_rounds()` - Get mining round states
- `get_governance_decisions()` - Get governance decisions

### Data Classes

**ContractState:**
- `contract_id`: Contract identifier
- `template_id`: Template identifier
- `created_at`: Creation timestamp
- `archived_at`: Archival timestamp (if archived)
- `is_active`: Whether contract is active
- `payload`: Contract creation arguments

**BalanceRecord:**
- `owner`: Owner party ID
- `amount`: Amount (positive = incoming, negative = outgoing)
- `record_time`: When the change occurred
- `details`: Additional details

**MiningRoundState:**
- `round_number`: Round number
- `status`: 'open', 'issuing', or 'closed'
- `opened_at`: When round opened
- `issuing_at`: When round started issuing
- `closed_at`: When round closed
- `configuration`: Round configuration

**GovernanceDecision:**
- `vote_request_id`: Vote request identifier
- `action_name`: Action being voted on
- `requested_at`: When vote was requested
- `votes`: List of cast votes
- `outcome`: Decision outcome (if resolved)

## References

- [Canton / Daml 3.3 Release Notes](https://blog.digitalasset.com/developers/release-notes/canton-daml-3.3-preview)
- [Scan Bulk Data API Documentation](https://docs.dev.sync.global/app_dev/scan_api/scan_bulk_data_api.html)
- [Scan Open API Reference](https://docs.dev.sync.global/app_dev/scan_api/scan_openapi.html)
- [TransactionTree Documentation](https://docs.daml.com/app-dev/services.html)

## Troubleshooting

### No events processed

**Cause**: Updates may not contain event trees (some update types don't have events)

**Solution**: Check the update type:
```python
update_data = update.get('update', {})
update_type = update_data.get('type')
print(f"Update type: {update_type}")
```

### Missing contract states

**Cause**: Contracts may have been created before the processed time range

**Solution**: Process earlier updates or query the ACS (Active Contract Set) for initial state

### Incorrect balances

**Cause**: Balance tracking only includes processed updates

**Solution**:
- Process from the beginning of time, or
- Query `/v0/holdings/summary` for current balances

## Best Practices

1. **Always use defensive parsing** - The processor handles this automatically
2. **Filter by templates** when you only need specific contract types
3. **Process in batches** for large datasets
4. **Log errors** but don't fail the entire processing job
5. **Export results periodically** for very large datasets
6. **Use custom handlers** for application-specific logic
7. **Test with sample data** before processing production data

## Contributing

When adding new template processors:

1. Add template patterns to `TEMPLATE_PATTERNS` in `UpdateTreeProcessor`
2. Implement processing methods (`_process_*_creation`, `_process_*_archival`, etc.)
3. Add data classes for new state types
4. Update documentation
5. Add tests
