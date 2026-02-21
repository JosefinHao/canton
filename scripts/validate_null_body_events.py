"""
Focused validation: Do null-body events from /v0/events exist in /v2/updates?

Instead of paginating through millions of records, this script:
1. Fetches one page from /v0/events for migrations 3 and 4
2. Identifies null-body items (events with verdict but no update body)
3. Looks up each null-body event's update_id in /v2/updates/{id}
4. Reports whether the pipeline would miss these records

Total API calls: ~20-30 (vs millions for exhaustive pagination)
"""

import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
REQUEST_DELAY = 0.15


def main():
    client = SpliceScanClient(BASE_URL)
    print("=" * 78)
    print("  VALIDATE NULL-BODY EVENTS: Do they exist in /v2/updates?")
    print("=" * 78)
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print(f"  API:  {BASE_URL}")
    print("=" * 78)

    # Check migrations 3 and 4 (where null-body events were found)
    # Also check migration 2 as a control (no null-body events expected)
    for mig_id in [2, 3, 4]:
        print(f"\n{'─' * 78}")
        print(f"  Migration {mig_id}")
        print(f"{'─' * 78}")

        # Step 1: Fetch a page from /v0/events
        print(f"  Fetching /v0/events page (500 items)...")
        resp = client.get_events(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=500,
        )
        time.sleep(REQUEST_DELAY)

        events = resp.get("events", [])
        print(f"  Got {len(events)} events")

        # Step 2: Separate null-body vs normal events
        null_body_events = []
        normal_events = []
        for ev in events:
            update = ev.get("update")
            if not update:
                null_body_events.append(ev)
            else:
                normal_events.append(ev)

        print(f"  Normal (with update body): {len(normal_events)}")
        print(f"  Null-body (verdict only):  {len(null_body_events)}")

        if not null_body_events:
            print(f"  → No null-body events in migration {mig_id}. Skipping.")
            continue

        # Step 3: Examine the null-body events
        print(f"\n  Examining null-body events...")
        null_body_ids = []
        for i, ev in enumerate(null_body_events[:5]):  # Show first 5
            verdict = ev.get("verdict", {})
            uid = verdict.get("update_id", "MISSING")
            rt = verdict.get("record_time", "MISSING")
            offset = verdict.get("offset", "MISSING")
            mig = verdict.get("migration_id", "MISSING")
            print(f"    [{i+1}] update_id={uid[:40]}... record_time={rt} migration_id={mig}")
            if uid and uid != "MISSING":
                null_body_ids.append(uid)

        # Collect ALL null-body update_ids
        for ev in null_body_events[5:]:
            verdict = ev.get("verdict", {})
            uid = verdict.get("update_id")
            if uid:
                null_body_ids.append(uid)

        if len(null_body_events) > 5:
            print(f"    ... and {len(null_body_events) - 5} more")

        print(f"\n  Total null-body events with update_id: {len(null_body_ids)}")

        # Step 4: Look up each null-body event in /v2/updates/{id}
        print(f"\n  Looking up null-body events in /v2/updates/{{id}}...")
        found_in_updates = 0
        not_found_in_updates = 0
        errors = 0
        found_details = []
        not_found_details = []

        for i, uid in enumerate(null_body_ids):
            try:
                update_resp = client.get_update_by_id(uid)
                time.sleep(REQUEST_DELAY)

                # Check if the response contains actual update data
                update = update_resp.get("update")
                if update:
                    found_in_updates += 1
                    ebi = update.get("events_by_id", {})
                    if len(found_details) < 3:
                        found_details.append({
                            "update_id": uid[:40],
                            "has_events": len(ebi) > 0,
                            "event_count": len(ebi),
                            "record_time": update.get("record_time"),
                        })
                else:
                    not_found_in_updates += 1
                    if len(not_found_details) < 3:
                        not_found_details.append(uid[:40])

            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "not found" in err_str.lower():
                    not_found_in_updates += 1
                    if len(not_found_details) < 3:
                        not_found_details.append(uid[:40])
                else:
                    errors += 1
                    if errors <= 2:
                        print(f"    ERROR looking up {uid[:30]}...: {e}")

            if (i + 1) % 20 == 0:
                print(f"    ... checked {i+1}/{len(null_body_ids)}", flush=True)

        # Step 5: Also check a few NORMAL events as control
        print(f"\n  Control check: looking up 5 normal events in /v2/updates/{{id}}...")
        control_found = 0
        for ev in normal_events[:5]:
            update = ev.get("update", {})
            uid = update.get("update_id")
            if not uid:
                continue
            try:
                ctrl_resp = client.get_update_by_id(uid)
                time.sleep(REQUEST_DELAY)
                if ctrl_resp.get("update"):
                    control_found += 1
            except Exception:
                pass
        print(f"  Control: {control_found}/5 normal events found in /v2/updates")

        # Step 6: Report
        print(f"\n  ┌─────────────────────────────────────────────────┐")
        print(f"  │  RESULTS for Migration {mig_id:>2}                        │")
        print(f"  ├─────────────────────────────────────────────────┤")
        print(f"  │  Null-body events checked:  {len(null_body_ids):>5}               │")
        print(f"  │  Found in /v2/updates:      {found_in_updates:>5}               │")
        print(f"  │  NOT found in /v2/updates:  {not_found_in_updates:>5}               │")
        print(f"  │  Errors:                    {errors:>5}               │")
        print(f"  │  Control (normal events):   {control_found}/5 found          │")
        print(f"  └─────────────────────────────────────────────────┘")

        if found_in_updates > 0 and found_details:
            print(f"\n  Sample FOUND in /v2/updates:")
            for d in found_details:
                print(f"    {d['update_id']}... events={d['event_count']} rt={d['record_time']}")

        if not_found_in_updates > 0 and not_found_details:
            print(f"\n  Sample NOT FOUND in /v2/updates:")
            for uid in not_found_details:
                print(f"    {uid}...")

        if found_in_updates == len(null_body_ids) and len(null_body_ids) > 0:
            print(f"\n  → ALL null-body events exist in /v2/updates!")
            print(f"    The pipeline does NOT miss these records.")
            print(f"    /v0/events simply omits the body for these, but /v2/updates has them.")
        elif not_found_in_updates == len(null_body_ids) and len(null_body_ids) > 0:
            print(f"\n  → NONE of the null-body events exist in /v2/updates!")
            print(f"    The pipeline MISSES these records entirely.")
        elif len(null_body_ids) > 0:
            print(f"\n  → MIXED results: {found_in_updates} found, {not_found_in_updates} missing")
            print(f"    The pipeline may be missing some records.")

    # Also check: do /v2/updates contain items that /v0/events shows as null-body?
    # Fetch from /v2/updates and cross-reference
    print(f"\n{'=' * 78}")
    print(f"  REVERSE CHECK: Items in /v2/updates at the same position")
    print(f"{'=' * 78}")
    for mig_id in [3, 4]:
        print(f"\n  Migration {mig_id}:")
        print(f"  Fetching first page from /v2/updates...")
        resp = client.get_updates(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=500,
        )
        time.sleep(REQUEST_DELAY)
        updates = resp.get("updates", resp.get("transactions", []))
        print(f"  Got {len(updates)} updates")

        # Get all update_ids from this page
        update_ids = set()
        for u in updates:
            uid = u.get("update_id")
            if uid:
                update_ids.add(uid)

        # Now fetch /v0/events and check overlap
        resp2 = client.get_events(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=500,
        )
        time.sleep(REQUEST_DELAY)
        events = resp2.get("events", [])

        event_ids_normal = set()
        event_ids_null = set()
        for ev in events:
            update = ev.get("update")
            if update:
                uid = update.get("update_id")
                if uid:
                    event_ids_normal.add(uid)
            else:
                verdict = ev.get("verdict", {})
                uid = verdict.get("update_id")
                if uid:
                    event_ids_null.add(uid)

        overlap_normal = update_ids & event_ids_normal
        overlap_null = update_ids & event_ids_null
        only_in_updates = update_ids - event_ids_normal - event_ids_null
        only_in_events_normal = event_ids_normal - update_ids
        only_in_events_null = event_ids_null - update_ids

        print(f"  /v2/updates IDs:           {len(update_ids)}")
        print(f"  /v0/events normal IDs:     {len(event_ids_normal)}")
        print(f"  /v0/events null-body IDs:  {len(event_ids_null)}")
        print(f"  Overlap (both endpoints):  {len(overlap_normal)}")
        print(f"  Null-body IDs also in /v2: {len(overlap_null)}")
        print(f"  Only in /v2/updates:       {len(only_in_updates)}")
        print(f"  Only in /v0 (normal):      {len(only_in_events_normal)}")
        print(f"  Only in /v0 (null-body):   {len(only_in_events_null)}")

    print(f"\n{'=' * 78}")
    print(f"  Validation complete")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
