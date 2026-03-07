"""
Verify whether update_ids from null-body (verdict-only) events in /v0/events
can be found via the /v2/updates endpoint.

Null-body events (update=null, verdict-only) can occur for multiple reasons:
  - Rejected transactions (verdict_result=VERDICT_RESULT_REJECTED)
  - Private transactions where the querying party lacks visibility into the
    update body but still receives the verdict metadata

Hypothesis: These verdict-only update_ids are NOT present in /v2/updates,
regardless of whether they were rejected or private.
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

        # Classify reason for null body
        if verdict_result == "VERDICT_RESULT_REJECTED":
            reason = "rejected"
        elif verdict_result == "VERDICT_RESULT_ACCEPTED":
            reason = "private (accepted but no update body visible)"
        else:
            reason = f"unknown ({verdict_result})"

        print(f"\n  [{i+1}] update_id: {update_id[:60]}...")
        print(f"      verdict_result: {verdict_result}")
        print(f"      likely reason:  {reason}")

        time.sleep(DELAY)
        try:
            v2_resp = client.get_update_by_id(update_id)
            found = bool(v2_resp and v2_resp.get("update_id"))
            print(f"      /v2/updates lookup: FOUND  (keys: {sorted(v2_resp.keys())})")
            results.append({"update_id": update_id, "verdict_result": verdict_result, "reason": reason, "in_v2": True})
        except Exception as e:
            error_msg = str(e)
            print(f"      /v2/updates lookup: NOT FOUND  ({error_msg[:100]})")
            results.append({"update_id": update_id, "verdict_result": verdict_result, "reason": reason, "in_v2": False, "error": error_msg[:200]})

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

    # Break down by reason
    rejected = [r for r in results if r["verdict_result"] == "VERDICT_RESULT_REJECTED"]
    accepted = [r for r in results if r["verdict_result"] == "VERDICT_RESULT_ACCEPTED"]
    other = [r for r in results if r not in rejected and r not in accepted]

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Null-body update_ids checked: {len(results)}")
    print(f"    - Rejected:                 {len(rejected)}")
    print(f"    - Accepted (private):       {len(accepted)}")
    if other:
        print(f"    - Other:                    {len(other)}")
    print(f"  Found in /v2/updates:         {found_count}")
    print(f"  NOT found in /v2/updates:     {not_found_count}")

    if found_count > 0:
        found_items = [r for r in results if r["in_v2"]]
        print(f"\n  Items FOUND in /v2/updates:")
        for r in found_items:
            print(f"    - {r['update_id'][:50]}... ({r['reason']})")

    if not_found_count == len(results):
        print(f"\n  CONFIRMED: All null-body update_ids are absent from /v2/updates.")
        print(f"  Verdict-only records (rejected + private) only appear in /v0/events.")
    elif found_count == len(results):
        print(f"\n  UNEXPECTED: All null-body update_ids were found in /v2/updates.")
    else:
        print(f"\n  MIXED: Some null-body update_ids found in /v2/updates, some not.")
        print(f"  This may indicate different behavior for rejected vs private transactions.")


if __name__ == "__main__":
    main()
