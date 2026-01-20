"""
Basic Query Examples for Splice Network Scan API

This script demonstrates basic usage of the Splice Scan API client
to retrieve on-chain data from the Splice Network.
"""

import sys
import os
from datetime import datetime

# Add parent directory to path to import the client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canton_scan_client import SpliceScanClient


def main():
    """Run basic query examples."""

    BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"

    # Initialize client - no authentication needed!
    print("Initializing Splice Scan API client (no auth required!)...")
    client = SpliceScanClient(base_url=BASE_URL)

    # Example 1: Health Check
    print("\n" + "="*60)
    print("Example 1: Health Check")
    print("="*60)
    is_healthy = client.health_check()
    print(f"API Health Status: {'OK' if is_healthy else 'FAILED'}")

    # Example 2: Get DSO Information
    print("\n" + "="*60)
    print("Example 2: DSO Information")
    print("="*60)
    try:
        dso = client.get_dso()
        print(f"DSO Info: {dso}")

        dso_party_id = client.get_dso_party_id()
        print(f"DSO Party ID: {dso_party_id}")
    except Exception as e:
        print(f"Error: {e}")

    # Example 3: Get Network Information
    print("\n" + "="*60)
    print("Example 3: Splice Network Names")
    print("="*60)
    try:
        names = client.get_splice_instance_names()
        print(f"Network Names: {names}")
    except Exception as e:
        print(f"Error: {e}")

    # Example 4: Get ANS Entries
    print("\n" + "="*60)
    print("Example 4: ANS Entries (Amulet Name Service)")
    print("="*60)
    try:
        ans_entries = client.get_ans_entries(page_size=10)
        print(f"Retrieved ANS entries")

        for i, entry in enumerate(ans_entries.get('entries', [])[:5], 1):
            print(f"\nANS Entry {i}:")
            print(f"  Name: {entry.get('name', 'N/A')}")
            print(f"  User: {entry.get('user', 'N/A')}")
            print(f"  Expires At: {entry.get('expires_at', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 5: Get Update History
    print("\n" + "="*60)
    print("Example 5: Recent Updates (Transaction History)")
    print("="*60)
    try:
        updates = client.get_updates(page_size=10)
        print(f"Retrieved {len(updates.get('transactions', []))} updates")

        for i, update in enumerate(updates.get('transactions', [])[:3], 1):
            print(f"\nUpdate {i}:")
            print(f"  Record Time: {update.get('record_time', 'N/A')}")
            print(f"  Migration ID: {update.get('migration_id', 'N/A')}")
            print(f"  Update ID: {update.get('update_id', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 6: Get Validator Information
    print("\n" + "="*60)
    print("Example 6: Validator Licenses")
    print("="*60)
    try:
        validators = client.get_validator_licenses(limit=10)
        print(f"Retrieved {len(validators.get('validator_licenses', []))} validators")

        for i, validator in enumerate(validators.get('validator_licenses', [])[:3], 1):
            print(f"\nValidator {i}:")
            print(f"  Contract ID: {validator.get('contract_id', 'N/A')}")
            print(f"  Created At: {validator.get('created_at', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 7: Get Open Mining Rounds
    print("\n" + "="*60)
    print("Example 7: Open Mining Rounds")
    print("="*60)
    try:
        rounds = client.get_open_and_issuing_mining_rounds()
        print(f"Open Rounds: {len(rounds.get('open_mining_rounds', []))}")
        print(f"Issuing Rounds: {len(rounds.get('issuing_mining_rounds', []))}")

        for i, round_data in enumerate(rounds.get('open_mining_rounds', [])[:2], 1):
            print(f"\nOpen Round {i}:")
            print(f"  Contract: {round_data.get('contract', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 8: Get Closed Mining Rounds
    print("\n" + "="*60)
    print("Example 8: Closed Mining Rounds")
    print("="*60)
    try:
        closed_rounds = client.get_closed_rounds()
        print(f"Retrieved {len(closed_rounds.get('rounds', []))} closed rounds")

        for i, round_data in enumerate(closed_rounds.get('rounds', [])[:2], 1):
            print(f"\nClosed Round {i}:")
            print(f"  Contract ID: {round_data.get('contract_id', 'N/A')}")
            print(f"  Created At: {round_data.get('created_at', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 9: Get Amulet Rules
    print("\n" + "="*60)
    print("Example 9: Current Amulet Rules")
    print("="*60)
    try:
        amulet_rules = client.get_amulet_rules()
        print(f"Amulet Rules:")
        for key, value in amulet_rules.items():
            if key not in ['contract']:  # Skip large nested contract data
                print(f"  {key}: {value}")

    except Exception as e:
        print(f"Error: {e}")

    # Example 10: Get Featured Apps
    print("\n" + "="*60)
    print("Example 10: Featured Apps")
    print("="*60)
    try:
        featured_apps = client.get_featured_apps()
        print(f"Retrieved {len(featured_apps.get('featured_app_rights', []))} featured apps")

        for i, app in enumerate(featured_apps.get('featured_app_rights', [])[:3], 1):
            print(f"\nFeatured App {i}:")
            print(f"  Provider: {app.get('provider', 'N/A')}")

    except Exception as e:
        print(f"Error: {e}")

    # Close the client
    client.close()
    print("\n" + "="*60)
    print("Examples completed!")
    print("="*60)


if __name__ == "__main__":
    main()
