"""
Do /v2/updates-exclusive records exist in /v0/events?

Takes the IDs that appear only in /v2/updates (not in /v0/events first page),
and looks them up individually via /v0/events/{id} to determine if they
exist anywhere in the events endpoint.

If they DO exist in /v0/events by ID, then /v2/updates doesn't have
exclusive data — it just paginates more efficiently (no null-body slots).

If they DON'T exist, then /v2/updates genuinely contains data that
/v0/events doesn't have at all.
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
    print("  DO /v2/updates EXCLUSIVE RECORDS EXIST IN /v0/events?")
    print("=" * 78)
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print("=" * 78)

    for mig_id in [3, 4]:
        print(f"\n{'=' * 78}")
        print(f"  Migration {mig_id}")
        print(f"{'=' * 78}")

        # Step 1: Fetch first page from both endpoints
        print(f"\n  Fetching first page from both endpoints...")
        updates_resp = client.get_updates(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=500,
        )
        time.sleep(REQUEST_DELAY)

        events_resp = client.get_events(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=500,
        )
        time.sleep(REQUEST_DELAY)

        updates = updates_resp.get("updates", updates_resp.get("transactions", []))
        events_raw = events_resp.get("events", [])

        # Build ID sets
        update_ids = {}
        for u in updates:
            uid = u.get("update_id")
            if uid:
                update_ids[uid] = u

        event_ids = set()
        for ev in events_raw:
            update = ev.get("update")
            if update:
                uid = update.get("update_id")
                if uid:
                    event_ids.add(uid)
            else:
                verdict = ev.get("verdict") or {}
                uid = verdict.get("update_id")
                if uid:
                    event_ids.add(uid)

        only_in_v2 = set(update_ids.keys()) - event_ids
        print(f"  IDs only in /v2/updates (first page): {len(only_in_v2)}")

        # Step 2: Look up each /v2-exclusive ID via /v0/events/{id}
        print(f"\n  Looking up /v2-exclusive IDs via /v0/events/{{id}}...")
        found_with_body = 0
        found_no_body = 0
        not_found = 0
        errors = 0

        sample_ids = sorted(only_in_v2)[:20]  # Check first 20

        for i, uid in enumerate(sample_ids):
            try:
                resp = client.get_event_by_id(uid)
                time.sleep(REQUEST_DELAY)

                update = resp.get("update")
                verdict = resp.get("verdict")

                if update:
                    ebi = update.get("events_by_id", {})
                    found_with_body += 1
                    if i < 5:
                        print(f"    {uid[:40]}... → FOUND with body, {len(ebi)} events")
                elif verdict:
                    found_no_body += 1
                    vr = verdict.get("verdict_result", "?")
                    if i < 5:
                        print(f"    {uid[:40]}... → FOUND verdict-only, result={vr}")
                else:
                    not_found += 1
                    if i < 5:
                        print(f"    {uid[:40]}... → FOUND but empty response")

            except Exception as e:
                err_str = str(e)
                if "404" in err_str:
                    not_found += 1
                    if i < 5:
                        print(f"    {uid[:40]}... → NOT FOUND (404)")
                else:
                    errors += 1
                    if i < 5:
                        print(f"    {uid[:40]}... → ERROR: {e}")

            if (i + 1) % 10 == 0 and i + 1 < len(sample_ids):
                print(f"    ... checked {i+1}/{len(sample_ids)}")

        print(f"\n  Results ({len(sample_ids)} /v2-exclusive IDs checked via /v0/events/{{id}}):")
        print(f"    Found with body:     {found_with_body}")
        print(f"    Found verdict-only:  {found_no_body}")
        print(f"    Not found (404):     {not_found}")
        print(f"    Errors:              {errors}")

        if found_with_body == len(sample_ids):
            print(f"\n  → ALL /v2-exclusive records exist in /v0/events with full bodies!")
            print(f"    /v2/updates does NOT have exclusive data.")
            print(f"    It just paginates more efficiently (skips null-body verdicts).")
        elif not_found == len(sample_ids):
            print(f"\n  → NONE of the /v2-exclusive records exist in /v0/events!")
            print(f"    /v2/updates genuinely contains data that /v0/events doesn't have.")
        elif found_with_body > 0:
            print(f"\n  → MIXED: {found_with_body} found, {not_found} not found, {found_no_body} verdict-only")

        # Step 3: Also check the reverse — do /v0 null-body IDs exist in /v0/events/{id}?
        null_body_ids = set()
        for ev in events_raw:
            if not ev.get("update"):
                verdict = ev.get("verdict") or {}
                uid = verdict.get("update_id")
                if uid:
                    null_body_ids.add(uid)

        only_in_v0_null = null_body_ids - set(update_ids.keys())
        if only_in_v0_null:
            print(f"\n  Also checking: do /v0 null-body exclusive IDs exist in /v0/events/{{id}} with bodies?")
            sample_null = sorted(only_in_v0_null)[:5]
            for uid in sample_null:
                try:
                    resp = client.get_event_by_id(uid)
                    time.sleep(REQUEST_DELAY)
                    update = resp.get("update")
                    if update:
                        ebi = update.get("events_by_id", {})
                        print(f"    {uid[:40]}... → HAS BODY, {len(ebi)} events")
                    else:
                        vr = (resp.get("verdict") or {}).get("verdict_result", "?")
                        print(f"    {uid[:40]}... → NO BODY, verdict={vr}")
                except Exception as e:
                    if "404" in str(e):
                        print(f"    {uid[:40]}... → NOT FOUND (404)")
                    else:
                        print(f"    {uid[:40]}... → ERROR: {e}")

    print(f"\n{'=' * 78}")
    print(f"  Done")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
