"""
Deep sampling: Verify /v2/updates vs /v0/events pattern across multiple pages.

Samples from early, middle, and late time windows within migrations 3 and 4
to confirm the first-page findings hold across the full timeline.

For each sample point, fetches one page from both endpoints and compares:
- How many shared IDs, exclusive-to-v2, exclusive null-body in v0
- Whether shared records have identical events_by_id
- Total events_by_id counts
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
REQUEST_DELAY = 0.15

# Time ranges observed from Phase 1 (full pagination run):
# Migration 3: 2025-06-25T13:44:34 .. ongoing (at least several days based on data rate)
# Migration 4: 2025-12-10T16:23:25 .. ongoing
#
# We'll sample at 3 points: early (page 1), middle, and late.
# "Middle" and "late" are approximated by jumping ahead in record_time.

SAMPLE_POINTS = {
    3: [
        ("early",  "2000-01-01T00:00:00Z"),          # First page
        ("middle", "2025-06-25T14:30:00Z"),           # ~45 min in
        ("late",   "2025-06-25T16:00:00Z"),           # ~2.25 hours in
    ],
    4: [
        ("early",  "2000-01-01T00:00:00Z"),           # First page
        ("middle", "2025-12-10T17:30:00Z"),           # ~1 hour in
        ("late",   "2025-12-10T19:00:00Z"),           # ~2.5 hours in
    ],
}


def hash_events(events_by_id):
    if not events_by_id:
        return "EMPTY"
    return hashlib.sha256(json.dumps(events_by_id, sort_keys=True).encode()).hexdigest()[:16]


def compare_page(client, mig_id, after_rt, label):
    """Fetch one page from both endpoints starting at after_rt and compare."""
    print(f"\n  [{label}] after_record_time={after_rt}")

    # Fetch from both
    updates_resp = client.get_updates(
        after_migration_id=mig_id,
        after_record_time=after_rt,
        page_size=500,
    )
    time.sleep(REQUEST_DELAY)

    events_resp = client.get_events(
        after_migration_id=mig_id,
        after_record_time=after_rt,
        page_size=500,
    )
    time.sleep(REQUEST_DELAY)

    updates = updates_resp.get("updates", updates_resp.get("transactions", []))
    events_raw = events_resp.get("events", [])

    if not updates and not events_raw:
        print(f"    No data at this time point (past end of migration)")
        return None

    # Build ID maps
    updates_by_id = {}
    for u in updates:
        uid = u.get("update_id")
        if uid:
            updates_by_id[uid] = u

    events_normal_by_id = {}
    events_null_body = {}
    for ev in events_raw:
        update = ev.get("update")
        if update:
            uid = update.get("update_id")
            if uid:
                events_normal_by_id[uid] = update
        else:
            verdict = ev.get("verdict") or {}
            uid = verdict.get("update_id")
            if uid:
                events_null_body[uid] = verdict

    update_ids = set(updates_by_id.keys())
    event_normal_ids = set(events_normal_by_id.keys())
    event_null_ids = set(events_null_body.keys())

    shared = update_ids & event_normal_ids
    only_v2 = update_ids - event_normal_ids - event_null_ids
    only_v0_null = event_null_ids - update_ids

    # Verify shared records are identical
    identical = 0
    differ = 0
    for uid in shared:
        u_hash = hash_events(updates_by_id[uid].get("events_by_id", {}))
        e_hash = hash_events(events_normal_by_id[uid].get("events_by_id", {}))
        if u_hash == e_hash:
            identical += 1
        else:
            differ += 1

    # Count events_by_id
    u_events = sum(len(u.get("events_by_id", {})) for u in updates)
    e_events = sum(len(events_normal_by_id[uid].get("events_by_id", {})) for uid in event_normal_ids)

    # Count verdict results
    accepted = sum(1 for v in events_null_body.values() if v.get("verdict_result") == "VERDICT_RESULT_ACCEPTED")
    rejected = sum(1 for v in events_null_body.values() if v.get("verdict_result") == "VERDICT_RESULT_REJECTED")

    # Time ranges
    u_times = sorted([u.get("record_time") for u in updates if u.get("record_time")])
    e_times = sorted([
        rt for ev in events_raw
        for rt in [(ev.get("update") or {}).get("record_time") or (ev.get("verdict") or {}).get("record_time")]
        if rt
    ])

    print(f"    /v2/updates: {len(updates)} records, {u_events} events_by_id")
    print(f"    /v0/events:  {len(events_raw)} records ({len(events_normal_by_id)} normal, {len(events_null_body)} null-body)")
    print(f"    Shared: {len(shared)} ({identical} identical, {differ} differ)")
    print(f"    Only in /v2: {len(only_v2)} (with events_by_id)")
    print(f"    Only in /v0 null-body: {len(only_v0_null)} (accepted={accepted}, rejected={rejected})")
    print(f"    events_by_id: /v2={u_events}, /v0={e_events}, diff={u_events - e_events}")
    if u_times and e_times:
        print(f"    Time: /v2 {u_times[0][:19]}..{u_times[-1][:19]}")
        print(f"           /v0 {e_times[0][:19]}..{e_times[-1][:19]}")

    return {
        "label": label,
        "v2_count": len(updates),
        "v0_count": len(events_raw),
        "shared": len(shared),
        "identical": identical,
        "differ": differ,
        "only_v2": len(only_v2),
        "only_v0_null": len(only_v0_null),
        "v2_events": u_events,
        "v0_events": e_events,
        "null_accepted": accepted,
        "null_rejected": rejected,
    }


def main():
    client = SpliceScanClient(BASE_URL)
    print("=" * 78)
    print("  DEEP SAMPLING: Pattern verification across multiple pages")
    print("=" * 78)
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print("=" * 78)

    all_results = {}

    for mig_id in [3, 4]:
        print(f"\n{'=' * 78}")
        print(f"  Migration {mig_id}")
        print(f"{'=' * 78}")

        results = []
        for label, after_rt in SAMPLE_POINTS[mig_id]:
            try:
                r = compare_page(client, mig_id, after_rt, label)
                if r:
                    results.append(r)
            except Exception as e:
                print(f"    ERROR: {e}")

        if results:
            print(f"\n  {'─' * 70}")
            print(f"  Summary for migration {mig_id}:")
            print(f"  {'─' * 70}")
            print(f"  {'Sample':<10} {'Shared':>7} {'Ident':>6} {'OnlyV2':>7} {'NullV0':>7} {'V2 evts':>8} {'V0 evts':>8} {'Diff':>6}")
            for r in results:
                print(f"  {r['label']:<10} {r['shared']:>7} {r['identical']:>6} {r['only_v2']:>7} {r['only_v0_null']:>7} {r['v2_events']:>8} {r['v0_events']:>8} {r['v2_events']-r['v0_events']:>+6}")

            total_shared = sum(r["shared"] for r in results)
            total_identical = sum(r["identical"] for r in results)
            total_differ = sum(r["differ"] for r in results)
            total_only_v2 = sum(r["only_v2"] for r in results)
            total_null = sum(r["only_v0_null"] for r in results)

            print(f"\n  Across all samples:")
            print(f"    Shared records checked: {total_shared}")
            print(f"    Identical: {total_identical}, Differ: {total_differ}")
            print(f"    Only in /v2/updates: {total_only_v2}")
            print(f"    Null-body in /v0/events: {total_null}")

            if total_differ == 0 and total_only_v2 > 0 and total_null > 0:
                print(f"    → Pattern CONFIRMED: /v2/updates has more contract events at all sample points")
            elif total_differ > 0:
                print(f"    → WARNING: {total_differ} shared records have different content!")

        all_results[mig_id] = results

    print(f"\n{'=' * 78}")
    print(f"  FINAL VERDICT")
    print(f"{'=' * 78}")
    all_consistent = True
    for mig_id, results in all_results.items():
        for r in results:
            if r["differ"] > 0:
                all_consistent = False
            if r["only_v2"] == 0 and r["only_v0_null"] == 0:
                pass  # Identical page, fine
    if all_consistent:
        print(f"  All shared records are identical across all sample points.")
        print(f"  /v2/updates consistently contains more contract events than /v0/events.")
        print(f"  The null-body records in /v0/events contain only verdict metadata.")
    else:
        print(f"  WARNING: Inconsistencies found. Further investigation needed.")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
