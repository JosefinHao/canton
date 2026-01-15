"""
Basic Query Examples for Canton Network Scan API

This script demonstrates basic usage of the Canton Scan API client
to retrieve on-chain data.

The Scan API is completely PUBLIC - no authentication required!
Just provide the API URL and start querying immediately.
"""

import sys
import os
from datetime import datetime, timedelta

# Add parent directory to path to import the client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canton_scan_client import CantonScanClient


def main():
    """Run basic query examples."""

    # Configuration - Replace with your actual Scan API URL
    # No authentication required - the API is completely public!
    BASE_URL = "https://scan.canton.network/api/v1"

    # Initialize client - no authentication needed!
    print("Initializing Canton Scan API client (no auth required!)...")
    client = CantonScanClient(base_url=BASE_URL)

    # Example 1: Health Check
    print("\n" + "="*60)
    print("Example 1: Health Check")
    print("="*60)
    is_healthy = client.health_check()
    print(f"API Health Status: {'OK' if is_healthy else 'FAILED'}")

    # Example 2: Get Ledger Identity
    print("\n" + "="*60)
    print("Example 2: Ledger Identity")
    print("="*60)
    try:
        ledger_identity = client.get_ledger_identity()
        print(f"Ledger Identity: {ledger_identity}")
    except Exception as e:
        print(f"Error: {e}")

    # Example 3: Get Recent Transactions
    print("\n" + "="*60)
    print("Example 3: Recent Transactions (last 10)")
    print("="*60)
    try:
        transactions = client.get_transactions(limit=10)
        print(f"Retrieved {len(transactions.get('transactions', []))} transactions")

        for i, tx in enumerate(transactions.get('transactions', [])[:3], 1):
            print(f"\nTransaction {i}:")
            print(f"  ID: {tx.get('transaction_id', 'N/A')}")
            print(f"  Effective At: {tx.get('effective_at', 'N/A')}")
            print(f"  Offset: {tx.get('offset', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 4: Get Active Contracts
    print("\n" + "="*60)
    print("Example 4: Active Contracts")
    print("="*60)
    try:
        contracts = client.get_active_contracts(limit=10)
        print(f"Retrieved {len(contracts.get('contracts', []))} active contracts")

        for i, contract in enumerate(contracts.get('contracts', [])[:3], 1):
            print(f"\nContract {i}:")
            print(f"  ID: {contract.get('contract_id', 'N/A')}")
            print(f"  Template: {contract.get('template_id', 'N/A')}")
            print(f"  Created At: {contract.get('created_at', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 5: Get All Parties
    print("\n" + "="*60)
    print("Example 5: All Parties")
    print("="*60)
    try:
        parties = client.get_parties()
        print(f"Total parties: {len(parties.get('parties', []))}")

        for i, party in enumerate(parties.get('parties', [])[:5], 1):
            print(f"\nParty {i}:")
            print(f"  ID: {party.get('party_id', 'N/A')}")
            print(f"  Display Name: {party.get('display_name', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 6: Get Events
    print("\n" + "="*60)
    print("Example 6: Recent Events")
    print("="*60)
    try:
        events = client.get_events(limit=10)
        print(f"Retrieved {len(events.get('events', []))} events")

        event_types = {}
        for event in events.get('events', []):
            event_type = event.get('event_type', 'unknown')
            event_types[event_type] = event_types.get(event_type, 0) + 1

        print("\nEvent Type Distribution:")
        for event_type, count in event_types.items():
            print(f"  {event_type}: {count}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 7: Get Templates
    print("\n" + "="*60)
    print("Example 7: Contract Templates")
    print("="*60)
    try:
        templates = client.get_templates()
        print(f"Total templates: {len(templates.get('templates', []))}")

        for i, template in enumerate(templates.get('templates', [])[:5], 1):
            print(f"\nTemplate {i}:")
            print(f"  ID: {template.get('template_id', 'N/A')}")
            print(f"  Module: {template.get('module_name', 'N/A')}")
            print(f"  Entity: {template.get('entity_name', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 8: Get Ledger Statistics
    print("\n" + "="*60)
    print("Example 8: Ledger Statistics")
    print("="*60)
    try:
        stats = client.get_ledger_stats()
        print(f"Ledger Stats:")
        for key, value in stats.items():
            print(f"  {key}: {value}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 9: Time-based Query
    print("\n" + "="*60)
    print("Example 9: Transactions from Last 24 Hours")
    print("="*60)
    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=1)

        transactions = client.get_transactions(
            start_time=start_time.isoformat() + 'Z',
            end_time=end_time.isoformat() + 'Z',
            limit=50
        )

        print(f"Transactions in last 24h: {len(transactions.get('transactions', []))}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 10: Paginated Query
    print("\n" + "="*60)
    print("Example 10: Paginated Transaction Retrieval")
    print("="*60)
    try:
        all_transactions = client.get_all_transactions_paginated(
            batch_size=50,
            max_items=200
        )
        print(f"Retrieved {len(all_transactions)} transactions using pagination")

    except Exception as e:
        print(f"Error: {e}")

    # Close the client
    client.close()
    print("\n" + "="*60)
    print("Examples completed!")
    print("="*60)


if __name__ == "__main__":
    main()
