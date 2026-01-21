#!/usr/bin/env python3
"""Test specific endpoints to diagnose the issues."""

import sys
from canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"

print("Initializing client...")
client = SpliceScanClient(base_url=BASE_URL)

print("\n" + "=" * 80)
print("TEST 1: Get validator licenses")
print("=" * 80)
try:
    result = client.get_validator_licenses(limit=10)
    print(f"Success! Got result: {result}")
    validators = result.get('validators', [])
    print(f"Number of validators: {len(validators)}")
except Exception as e:
    print(f"ERROR: {e}")
    print(f"Error type: {type(e).__name__}")

print("\n" + "=" * 80)
print("TEST 2: Get updates")
print("=" * 80)
try:
    result = client.get_updates(page_size=10)
    print(f"Success! Got result keys: {result.keys()}")
    updates = result.get('updates', [])
    print(f"Number of updates: {len(updates)}")
except Exception as e:
    print(f"ERROR: {e}")
    print(f"Error type: {type(e).__name__}")

print("\n" + "=" * 80)
print("TEST 3: Get mining rounds (known working)")
print("=" * 80)
try:
    result = client.get_open_and_issuing_mining_rounds()
    print(f"Success! Got result keys: {result.keys()}")
    open_rounds = result.get('open_mining_rounds', [])
    print(f"Number of open rounds: {len(open_rounds)}")
except Exception as e:
    print(f"ERROR: {e}")

client.close()
