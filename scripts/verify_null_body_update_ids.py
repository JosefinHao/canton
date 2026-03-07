"""
Verify whether update_ids from null-body (verdict-only) events in /v0/events
can be found via the /v2/updates endpoint.

Hypothesis: These rejected transactions exist only in /v0/events (with verdict)
and are NOT present in /v2/updates.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
MIGRATION_ID = 4
DELAY = 0.2


def main():
    client = SpliceScanClient(BASE_URL)

    # Step 1: Fetch events from /v0/events and find null-body ones
    print("=" * 70)
    print("  Fetching /v0/events to find null-body (verdict-only) events")
    print("=" * 70)
    v0_resp = client.get_events(
        after_migration_id=MIGRATION_ID,
        after_record_time="2000-01-01T00:00:00Z",
        page_size=50,
    )

    events = v0_resp.get("events", [])
    null_body = [ev for ev in events if ev.get("update") is None]
    normal = [ev for ev in events if ev.get("update") is not None]

    print(f"  Total events: {len(events)}")
    print(f"  Normal (with update body): {len(normal)}")
    print(f"  Null-body (verdict only): {len(null_body)}")

    if not null_body:
        print("\n  No null-body events found. Exiting.")
        return

    # Step 2: Try to look up each null-body update_id via /v2/updates/{id}
    print(f"\n{'=' * 70}")
    print("  Looking up null-body update_ids via /v2/updates/{{id}}")
    print("=" * 70)

    results = []
    for i, ev in enumerate(null_body[:10]):  # Check up to 10
        verdict = ev.get("verdict", {})
        update_id = verdict.get("update_id", "MISSING")
        verdict_result = verdict.get("verdict_result", "?")

        print(f"\n  [{i+1}] update_id: {update_id[:60]}...")
        print(f"      verdict_result: {verdict_result}")

        time.sleep(DELAY)
        try:
            v2_resp = client.get_update_by_id(update_id)
            found = bool(v2_resp and v2_resp.get("update_id"))
            print(f"      /v2/updates lookup: FOUND  (keys: {sorted(v2_resp.keys())})")
            results.append({"update_id": update_id, "verdict_result": verdict_result, "in_v2": True})
        except Exception as e:
            error_msg = str(e)
            print(f"      /v2/updates lookup: NOT FOUND  ({error_msg[:100]})")
            results.append({"update_id": update_id, "verdict_result": verdict_result, "in_v2": False, "error": error_msg[:200]})

    # Step 3: Also verify a normal event update_id works (sanity check)
    if normal:
        print(f"\n{'─' * 70}")
        print("  SANITY CHECK: looking up a normal event's update_id via /v2/updates")
        print(f"{'─' * 70}")
        normal_id = normal[0]["update"]["update_id"]
        print(f"  update_id: {normal_id[:60]}...")
        time.sleep(DELAY)
        try:
            v2_check = client.get_update_by_id(normal_id)
            print(f"  /v2/updates lookup: FOUND  (keys: {sorted(v2_check.keys())})")
        except Exception as e:
            print(f"  /v2/updates lookup: NOT FOUND  ({e})")

    # Summary
    found_count = sum(1 for r in results if r["in_v2"])
    not_found_count = sum(1 for r in results if not r["in_v2"])
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Null-body update_ids checked: {len(results)}")
    print(f"  Found in /v2/updates:         {found_count}")
    print(f"  NOT found in /v2/updates:     {not_found_count}")
    if not_found_count == len(results):
        print(f"\n  CONFIRMED: Rejected transactions are NOT in /v2/updates.")
        print(f"  They only appear in /v0/events as verdict-only records.")
    elif found_count == len(results):
        print(f"\n  UNEXPECTED: All rejected update_ids were found in /v2/updates.")
    else:
        print(f"\n  MIXED: Some found, some not. Needs further investigation.")


if __name__ == "__main__":
    main()
