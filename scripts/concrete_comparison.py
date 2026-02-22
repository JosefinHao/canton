"""
Concrete examples: What exactly differs between /v2/updates and /v0/events?

Fetches the first page from both endpoints for migrations 3 and 4, then:
1. Shows the exact ID sets and their overlap/exclusions
2. For records exclusive to /v2/updates: shows what data they contain
3. For null-body records exclusive to /v0/events: shows what the verdict contains
4. For shared records: confirms they have identical events_by_id
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


def hash_events(events_by_id):
    """Hash events_by_id for comparison."""
    if not events_by_id:
        return "EMPTY"
    return hashlib.sha256(json.dumps(events_by_id, sort_keys=True).encode()).hexdigest()[:16]


def main():
    client = SpliceScanClient(BASE_URL)
    print("=" * 78)
    print("  CONCRETE EXAMPLES: /v2/updates vs /v0/events")
    print("=" * 78)
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print("=" * 78)

    for mig_id in [3, 4]:
        print(f"\n{'=' * 78}")
        print(f"  Migration {mig_id}")
        print(f"{'=' * 78}")

        # Fetch from both endpoints
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

        # Build lookup maps
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
                    events_normal_by_id[uid] = {"update": update, "verdict": ev.get("verdict")}
            else:
                verdict = ev.get("verdict", {})
                uid = verdict.get("update_id")
                if uid:
                    events_null_body[uid] = {"verdict": verdict}

        update_ids = set(updates_by_id.keys())
        event_normal_ids = set(events_normal_by_id.keys())
        event_null_ids = set(events_null_body.keys())

        shared_ids = update_ids & event_normal_ids
        only_in_updates = update_ids - event_normal_ids - event_null_ids
        only_in_events_null = event_null_ids - update_ids

        print(f"  /v2/updates: {len(updates)} records")
        print(f"  /v0/events:  {len(events_raw)} records ({len(events_normal_by_id)} normal, {len(events_null_body)} null-body)")
        print(f"\n  Shared IDs:                  {len(shared_ids)}")
        print(f"  Only in /v2/updates:         {len(only_in_updates)}")
        print(f"  Only in /v0/events (null):   {len(only_in_events_null)}")

        # ── SECTION 1: Verify shared records are identical ──
        print(f"\n{'─' * 78}")
        print(f"  SECTION 1: Are shared records identical?")
        print(f"{'─' * 78}")
        identical_count = 0
        differ_count = 0
        for uid in sorted(shared_ids)[:20]:  # Check first 20
            u_events = updates_by_id[uid].get("events_by_id", {})
            e_events = events_normal_by_id[uid]["update"].get("events_by_id", {})
            u_hash = hash_events(u_events)
            e_hash = hash_events(e_events)
            if u_hash == e_hash:
                identical_count += 1
            else:
                differ_count += 1
                if differ_count <= 3:
                    print(f"    DIFFER: {uid[:50]}...")
                    print(f"      /v2/updates hash: {u_hash}, events: {len(u_events)}")
                    print(f"      /v0/events hash:  {e_hash}, events: {len(e_events)}")
        # Check remaining
        for uid in sorted(shared_ids)[20:]:
            u_events = updates_by_id[uid].get("events_by_id", {})
            e_events = events_normal_by_id[uid]["update"].get("events_by_id", {})
            if hash_events(u_events) == hash_events(e_events):
                identical_count += 1
            else:
                differ_count += 1
        print(f"  Result: {identical_count}/{len(shared_ids)} identical, {differ_count} differ")

        # ── SECTION 2: Records only in /v2/updates ──
        print(f"\n{'─' * 78}")
        print(f"  SECTION 2: Records ONLY in /v2/updates ({len(only_in_updates)} records)")
        print(f"  These are records the pipeline captures but /v0/events does NOT have.")
        print(f"{'─' * 78}")
        total_events_only_updates = 0
        for i, uid in enumerate(sorted(only_in_updates)):
            u = updates_by_id[uid]
            ebi = u.get("events_by_id", {})
            total_events_only_updates += len(ebi)
            if i < 5:
                rt = u.get("record_time", "?")
                templates = set()
                event_types = set()
                for eid, ev in ebi.items():
                    templates.add(ev.get("template_id", "?"))
                    if "create_arguments" in ev:
                        event_types.add("created")
                    elif "choice" in ev:
                        event_types.add(f"exercised:{ev.get('choice', '?')}")
                    else:
                        event_types.add("other")
                print(f"\n    [{i+1}] update_id: {uid[:60]}...")
                print(f"        record_time:   {rt}")
                print(f"        events_by_id:  {len(ebi)} events")
                print(f"        event_types:   {event_types}")
                print(f"        templates:     {templates}")
        if len(only_in_updates) > 5:
            print(f"\n    ... and {len(only_in_updates) - 5} more")
        print(f"\n  Total events_by_id in /v2-only records: {total_events_only_updates}")

        # ── SECTION 3: Null-body records only in /v0/events ──
        print(f"\n{'─' * 78}")
        print(f"  SECTION 3: Null-body records ONLY in /v0/events ({len(only_in_events_null)} records)")
        print(f"  These are records the pipeline does NOT capture.")
        print(f"{'─' * 78}")
        for i, uid in enumerate(sorted(only_in_events_null)):
            if i >= 5:
                break
            v = events_null_body[uid]["verdict"]
            rt = v.get("record_time", "?")
            result = v.get("verdict_result", "?")
            submitters = v.get("submitting_parties", [])
            views = v.get("transaction_views", [])
            finalization = v.get("finalization_time", "?")

            print(f"\n    [{i+1}] update_id: {uid[:60]}...")
            print(f"        record_time:       {rt}")
            print(f"        verdict_result:    {result}")
            print(f"        finalization_time: {finalization}")
            print(f"        submitting_parties: {submitters[:3]}{'...' if len(submitters) > 3 else ''}")
            print(f"        transaction_views: {len(views)} views")
            if views:
                for vi, view in enumerate(views[:2]):
                    informees = view.get("informees", [])
                    print(f"          view[{vi}]: {len(informees)} informees")
            print(f"        ALL verdict keys: {sorted(v.keys())}")
        if len(only_in_events_null) > 5:
            print(f"\n    ... and {len(only_in_events_null) - 5} more")

        # ── SECTION 4: Fetch null-body events individually via /v0/events/{id} ──
        print(f"\n{'─' * 78}")
        print(f"  SECTION 4: Fetch null-body events individually via /v0/events/{{id}}")
        print(f"  Check if they have bodies when fetched by ID (pagination artifact?)")
        print(f"{'─' * 78}")
        sample_null_ids = sorted(only_in_events_null)[:10]
        has_body_count = 0
        no_body_count = 0
        for uid in sample_null_ids:
            try:
                resp = client.get_event_by_id(uid)
                time.sleep(REQUEST_DELAY)
                update = resp.get("update")
                verdict = resp.get("verdict")
                if update:
                    has_body_count += 1
                    ebi = update.get("events_by_id", {})
                    print(f"    {uid[:40]}... → HAS BODY, {len(ebi)} events")
                else:
                    no_body_count += 1
                    v_result = verdict.get("verdict_result", "?") if verdict else "no-verdict"
                    print(f"    {uid[:40]}... → NO BODY, verdict={v_result}")
            except Exception as e:
                print(f"    {uid[:40]}... → ERROR: {e}")

        print(f"\n  Individual fetch results: {has_body_count} have body, {no_body_count} no body")
        if has_body_count > 0:
            print(f"  → Some null-body events DO have bodies when fetched individually!")
            print(f"     This suggests the null body in pagination is an ARTIFACT.")
        elif no_body_count == len(sample_null_ids):
            print(f"  → Null-body events are truly bodyless even when fetched individually.")

        # ── SECTION 5: Time range comparison ──
        print(f"\n{'─' * 78}")
        print(f"  SECTION 5: Time ranges")
        print(f"{'─' * 78}")
        u_times = sorted([u.get("record_time") for u in updates if u.get("record_time")])
        e_times = sorted([
            ev.get("update", {}).get("record_time") or ev.get("verdict", {}).get("record_time", "")
            for ev in events_raw if (ev.get("update", {}).get("record_time") or ev.get("verdict", {}).get("record_time"))
        ])
        print(f"  /v2/updates: {u_times[0]} .. {u_times[-1]}")
        print(f"  /v0/events:  {e_times[0]} .. {e_times[-1]}")

        # Count events_by_id totals
        u_total_events = sum(len(u.get("events_by_id", {})) for u in updates)
        e_total_events = sum(
            len(ev.get("update", {}).get("events_by_id", {}))
            for ev in events_raw if ev.get("update")
        )
        print(f"\n  Total events_by_id:")
        print(f"    /v2/updates: {u_total_events} events across {len(updates)} updates")
        print(f"    /v0/events:  {e_total_events} events across {len(events_normal_by_id)} non-null updates")
        print(f"    Difference:  {u_total_events - e_total_events} more in /v2/updates")

    print(f"\n{'=' * 78}")
    print(f"  Done")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
