"""
Example: Processing Updates with Tree Traversal

This example demonstrates how to use the UpdateTreeProcessor to:
1. Traverse update trees in preorder
2. Selectively parse events based on template IDs
3. Accumulate state changes for contracts, balances, mining rounds, and governance
4. Generate reports on the accumulated state
"""

import sys
import os
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient
from src.update_tree_processor import UpdateTreeProcessor


def main():
    """Run the update processing example."""

    BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"

    print("="*80)
    print("Update Tree Processing Example")
    print("="*80)

    # Initialize client and processor
    print("\n1. Initializing Canton Scan client...")
    client = SpliceScanClient(base_url=BASE_URL)

    print("2. Initializing update tree processor...")
    processor = UpdateTreeProcessor()

    # Fetch updates
    print("\n3. Fetching updates from Canton Scan API...")
    try:
        updates_response = client.get_updates(page_size=100)
        updates = updates_response.get('updates', [])
        print(f"   Retrieved {len(updates)} updates")
    except Exception as e:
        print(f"   Error fetching updates: {e}")
        return

    # Process updates with the tree processor
    print("\n4. Processing updates with preorder tree traversal...")
    state = processor.process_updates(updates)

    # Display summary
    print("\n" + "="*80)
    print("Processing Summary")
    print("="*80)
    summary = processor.get_summary()
    print(f"Updates processed:        {summary['updates_processed']}")
    print(f"Events processed:         {summary['events_processed']}")
    print(f"Total contracts tracked:  {summary['total_contracts']}")
    print(f"Active contracts:         {summary['active_contracts']}")
    print(f"Unique balance owners:    {summary['unique_balance_owners']}")
    print(f"Mining rounds tracked:    {summary['mining_rounds_tracked']}")
    print(f"Current round:            {summary['current_round']}")
    print(f"Governance decisions:     {summary['governance_decisions']}")
    print(f"Errors encountered:       {summary['errors_encountered']}")

    # Display contract states
    print("\n" + "="*80)
    print("Contract States (Sample)")
    print("="*80)
    active_contracts = processor.get_active_contracts()
    for i, contract in enumerate(active_contracts[:5], 1):
        print(f"\nContract {i}:")
        print(f"  ID:          {contract.contract_id[:50]}...")
        print(f"  Template:    {contract.template_id}")
        print(f"  Created:     {contract.created_at}")
        print(f"  Status:      {'Active' if contract.is_active else 'Archived'}")

    if len(active_contracts) > 5:
        print(f"\n... and {len(active_contracts) - 5} more active contracts")

    # Display balance information
    print("\n" + "="*80)
    print("Balance Tracking (Sample)")
    print("="*80)
    balance_history = processor.get_balance_history()
    for i, (owner, records) in enumerate(list(balance_history.items())[:5], 1):
        total_balance = sum(r.amount for r in records)
        print(f"\nOwner {i}:")
        print(f"  Party ID:       {owner[:50]}...")
        print(f"  Transactions:   {len(records)}")
        print(f"  Current Balance: {total_balance:.2f}")

    if len(balance_history) > 5:
        print(f"\n... and {len(balance_history) - 5} more owners")

    # Display mining round information
    print("\n" + "="*80)
    print("Mining Rounds")
    print("="*80)
    mining_rounds = processor.get_mining_rounds()
    if mining_rounds:
        sorted_rounds = sorted(mining_rounds.items(), key=lambda x: x[0])
        for round_num, round_state in sorted_rounds[-5:]:
            print(f"\nRound {round_num}:")
            print(f"  Status:      {round_state.status}")
            print(f"  Opened at:   {round_state.opened_at or 'N/A'}")
            print(f"  Issuing at:  {round_state.issuing_at or 'N/A'}")
            print(f"  Closed at:   {round_state.closed_at or 'N/A'}")

        if len(mining_rounds) > 5:
            print(f"\n... and {len(mining_rounds) - 5} earlier rounds")
    else:
        print("  No mining rounds tracked")

    # Display governance information
    print("\n" + "="*80)
    print("Governance Decisions (Sample)")
    print("="*80)
    governance = processor.get_governance_decisions()
    if governance:
        for i, (vote_id, decision) in enumerate(list(governance.items())[:5], 1):
            print(f"\nDecision {i}:")
            print(f"  Action:      {decision.action_name}")
            print(f"  Requested:   {decision.requested_at}")
            print(f"  Votes cast:  {len(decision.votes)}")
            print(f"  Outcome:     {decision.outcome or 'Pending'}")

        if len(governance) > 5:
            print(f"\n... and {len(governance) - 5} more decisions")
    else:
        print("  No governance decisions tracked")

    # Example: Filter by specific templates
    print("\n" + "="*80)
    print("Filtered Processing Example (Amulet contracts only)")
    print("="*80)

    processor_filtered = UpdateTreeProcessor()
    state_filtered = processor_filtered.process_updates(
        updates,
        filter_templates=['Amulet']  # Only process Amulet-related contracts
    )

    summary_filtered = processor_filtered.get_summary()
    print(f"Events processed:         {summary_filtered['events_processed']}")
    print(f"Contracts tracked:        {summary_filtered['total_contracts']}")
    print(f"Balance owners:           {summary_filtered['unique_balance_owners']}")

    # Custom handler example
    print("\n" + "="*80)
    print("Custom Handler Example")
    print("="*80)

    custom_event_count = {'count': 0}

    def custom_handler(event_type, template_id, event_data, record_time, state):
        """Custom handler for processing specific events."""
        custom_event_count['count'] += 1
        # You can add custom logic here
        # For example: log to database, send notifications, etc.

    processor_custom = UpdateTreeProcessor(
        custom_handlers={'Validator': custom_handler}
    )
    processor_custom.process_updates(updates)

    print(f"Custom handler invoked {custom_event_count['count']} times for Validator-related events")

    # Close client
    client.close()

    print("\n" + "="*80)
    print("Example completed!")
    print("="*80)


if __name__ == "__main__":
    main()
