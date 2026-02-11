#!/usr/bin/env python3
"""
Debug version of splice analytics to diagnose data retrieval issues.
"""

import sys
from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"

def test_validators(client):
    """Test validator data retrieval with diagnostics."""
    print("\n" + "=" * 80)
    print("TESTING VALIDATOR DATA")
    print("=" * 80)

    # Try Method 1: Admin endpoint
    print("\n[Method 1] Trying /v0/admin/validator/licenses...")
    try:
        result = client.get_validator_licenses(limit=10)
        print(f"✓ Success! Result type: {type(result)}")
        print(f"  Keys: {list(result.keys())}")

        validators = result.get('validators', [])
        print(f"  Found {len(validators)} validators")

        if validators:
            print(f"  Sample validator keys: {list(validators[0].keys()) if validators else 'N/A'}")
            return len(validators)
        else:
            print("  ⚠ Empty validator list returned")
            return 0

    except Exception as e:
        print(f"✗ Failed: {e}")
        print(f"  Error type: {type(e).__name__}")

    # Try Method 2: Top validators endpoint
    print("\n[Method 2] Trying /v0/top-validators-by-validator-faucets...")
    try:
        result = client.get_top_validators_by_validator_faucets(limit=100)
        print(f"✓ Success! Result type: {type(result)}")
        print(f"  Keys: {list(result.keys())}")

        validators = result.get('validatorsByReceivedFaucets', [])
        print(f"  Found {len(validators)} validators")

        if validators:
            print(f"  Sample validator keys: {list(validators[0].keys()) if validators else 'N/A'}")
            return len(validators)
        else:
            print("  ⚠ Empty validator list returned")
            return 0

    except Exception as e:
        print(f"✗ Failed: {e}")
        print(f"  Error type: {type(e).__name__}")

    # Try Method 3: Check DSO for SV node states
    print("\n[Method 3] Trying /v0/dso for SV node states...")
    try:
        result = client.get_dso()
        print(f"✓ Success! Result type: {type(result)}")
        print(f"  Keys: {list(result.keys())}")

        if 'sv_node_states' in result:
            sv_states = result['sv_node_states']
            count = len(sv_states) if isinstance(sv_states, (list, dict)) else 0
            print(f"  Found {count} SV node states")
            return count
        else:
            print("  ⚠ No sv_node_states field found")
            return 0

    except Exception as e:
        print(f"✗ Failed: {e}")
        print(f"  Error type: {type(e).__name__}")

    print("\n⚠ All validator retrieval methods failed!")
    return 0


def test_updates(client):
    """Test transaction/update data retrieval with diagnostics."""
    print("\n" + "=" * 80)
    print("TESTING TRANSACTION/UPDATE DATA")
    print("=" * 80)

    # Try Method 1: Updates endpoint (v2)
    print("\n[Method 1] Trying POST /v2/updates...")
    try:
        result = client.get_updates(page_size=10)
        print(f"✓ Success! Result type: {type(result)}")
        print(f"  Keys: {list(result.keys())}")

        updates = result.get('updates', [])
        print(f"  Found {len(updates)} updates")

        if updates:
            print(f"  Sample update keys: {list(updates[0].keys()) if updates else 'N/A'}")
            return len(updates)
        else:
            print("  ⚠ Empty updates list returned")
            print("  This might mean the ledger has no recorded updates yet")
            return 0

    except Exception as e:
        print(f"✗ Failed: {e}")
        print(f"  Error type: {type(e).__name__}")

    # Try Method 2: Events endpoint
    print("\n[Method 2] Trying POST /v0/events...")
    try:
        result = client.get_events(page_size=10)
        print(f"✓ Success! Result type: {type(result)}")
        print(f"  Keys: {list(result.keys())}")

        events = result.get('events', [])
        print(f"  Found {len(events)} events")

        if events:
            print(f"  Sample event keys: {list(events[0].keys()) if events else 'N/A'}")
            return len(events)
        else:
            print("  ⚠ Empty events list returned")
            return 0

    except Exception as e:
        print(f"✗ Failed: {e}")
        print(f"  Error type: {type(e).__name__}")

    print("\n⚠ All update/event retrieval methods failed!")
    return 0


def test_mining_rounds(client):
    """Test mining round data retrieval (known to work for user)."""
    print("\n" + "=" * 80)
    print("TESTING MINING ROUNDS DATA (Control Test)")
    print("=" * 80)

    print("\n[Method 1] Trying POST /v0/open-and-issuing-mining-rounds...")
    try:
        result = client.get_open_and_issuing_mining_rounds()
        print(f"✓ Success! Result type: {type(result)}")
        print(f"  Keys: {list(result.keys())}")

        open_rounds = result.get('open_mining_rounds', [])
        issuing_rounds = result.get('issuing_rounds', [])

        print(f"  Open rounds: {len(open_rounds)}")
        print(f"  Issuing rounds: {len(issuing_rounds)}")

        return len(open_rounds) + len(issuing_rounds)

    except Exception as e:
        print(f"✗ Failed: {e}")
        print(f"  Error type: {type(e).__name__}")
        return 0


def main():
    """Run diagnostic tests."""
    print("=" * 80)
    print("SPLICE ANALYTICS DIAGNOSTIC TOOL")
    print("=" * 80)
    print(f"Target API: {BASE_URL}")

    print("\nInitializing client...")
    client = SpliceScanClient(base_url=BASE_URL)

    # Test mining rounds first (control test - should work)
    mining_count = test_mining_rounds(client)

    # Test validators
    validator_count = test_validators(client)

    # Test updates
    update_count = test_updates(client)

    # Summary
    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 80)
    print(f"Mining Rounds: {'✓ WORKING' if mining_count > 0 else '✗ FAILED'} ({mining_count} items)")
    print(f"Validators:    {'✓ WORKING' if validator_count > 0 else '✗ FAILED'} ({validator_count} items)")
    print(f"Updates:       {'✓ WORKING' if update_count > 0 else '✗ FAILED'} ({update_count} items)")

    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)

    if mining_count > 0:
        print("✓ API connection is working (mining rounds successful)")
    else:
        print("✗ Cannot connect to API - check network/firewall settings")

    if validator_count == 0:
        print("✗ Validator endpoints not accessible:")
        print("  - May require authentication/admin privileges")
        print("  - Or the network has no validators registered yet")
        print("  - Try checking if you need API credentials")

    if update_count == 0:
        print("✗ Update/event endpoints not returning data:")
        print("  - The ledger may have no recorded transactions yet")
        print("  - Or the endpoints require authentication")
        print("  - Or there may be an API version mismatch")

    client.close()


if __name__ == "__main__":
    main()
