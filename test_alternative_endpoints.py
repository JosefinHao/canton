#!/usr/bin/env python3
"""Test alternative endpoints that might have validator data."""

import sys
import json
from canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"

print("Initializing client...")
client = SpliceScanClient(base_url=BASE_URL)

print("\n" + "=" * 80)
print("TEST: Get DSO information (might contain validator/SV data)")
print("=" * 80)
try:
    result = client.get_dso()
    print(f"Success! Got result keys: {list(result.keys())}")

    if 'sv_node_states' in result:
        print(f"\nFound sv_node_states!")
        sv_states = result['sv_node_states']
        print(f"Type: {type(sv_states)}")
        if isinstance(sv_states, dict):
            print(f"Number of SV nodes: {len(sv_states)}")
            print(f"First few keys: {list(sv_states.keys())[:3]}")
        elif isinstance(sv_states, list):
            print(f"Number of SV nodes: {len(sv_states)}")

    # Check for other relevant fields
    for key in result.keys():
        if isinstance(result[key], (list, dict)):
            if isinstance(result[key], list):
                print(f"  {key}: list with {len(result[key])} items")
            else:
                print(f"  {key}: dict with {len(result[key])} items")
        else:
            print(f"  {key}: {type(result[key]).__name__}")

except Exception as e:
    print(f"ERROR: {e}")
    print(f"Error type: {type(e).__name__}")

print("\n" + "=" * 80)
print("TEST: Get top validators by faucets (non-admin endpoint)")
print("=" * 80)
try:
    result = client.get_top_validators_by_validator_faucets(limit=100)
    print(f"Success! Got result keys: {result.keys()}")
    validators = result.get('validatorsByReceivedFaucets', [])
    print(f"Number of validators: {len(validators)}")
    if validators:
        print(f"Sample validator: {validators[0]}")
except Exception as e:
    print(f"ERROR: {e}")
    print(f"Error type: {type(e).__name__}")

print("\n" + "=" * 80)
print("TEST: Get events (might work better than updates)")
print("=" * 80)
try:
    result = client.get_events(page_size=10)
    print(f"Success! Got result keys: {result.keys()}")
    events = result.get('events', [])
    print(f"Number of events: {len(events)}")
except Exception as e:
    print(f"ERROR: {e}")
    print(f"Error type: {type(e).__name__}")

client.close()
