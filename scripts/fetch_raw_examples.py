"""
Fetch raw JSON examples from /v2/updates and /v0/events endpoints.

Saves:
  - scripts/output/v2_updates_sample.json   (first page from /v2/updates)
  - scripts/output/v0_events_sample.json    (first page from /v0/events)
  - scripts/output/null_body_events.json    (events with update=null, verdict only)
  - scripts/output/matched_pair_example.json (same update_id from both endpoints side-by-side)

Prints summary to stdout.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
MIGRATION_ID = 4
PAGE_SIZE = 20  # Small page for readable examples
DELAY = 0.15


def save_json(data, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    client = SpliceScanClient(BASE_URL)

    # ── 1. Fetch /v2/updates ──
    print("=" * 70)
    print("  Fetching /v2/updates (page_size={}, migration={})".format(PAGE_SIZE, MIGRATION_ID))
    print("=" * 70)
    v2_resp = client.get_updates(
        after_migration_id=MIGRATION_ID,
        after_record_time="2000-01-01T00:00:00Z",
        page_size=PAGE_SIZE,
    )
    # Remove the normalized "updates" key to show raw structure
    raw_v2 = {k: v for k, v in v2_resp.items() if k != "updates"}
    save_json(raw_v2, "v2_updates_sample.json")

    transactions = v2_resp.get("transactions", [])
    print(f"  Response top-level keys: {sorted(raw_v2.keys())}")
    print(f"  Number of transactions: {len(transactions)}")
    if transactions:
        t = transactions[0]
        print(f"\n  First transaction keys: {sorted(t.keys())}")
        print(f"  First transaction update_id: {t.get('update_id', '?')[:60]}...")
        ebi = t.get("events_by_id", {})
        print(f"  First transaction events_by_id: {len(ebi)} events")
        for eid, ev in list(ebi.items())[:2]:
            print(f"    Event {eid}: keys={sorted(ev.keys())}")

    time.sleep(DELAY)

    # ── 2. Fetch /v0/events ──
    print(f"\n{'=' * 70}")
    print("  Fetching /v0/events (page_size={}, migration={})".format(PAGE_SIZE, MIGRATION_ID))
    print("=" * 70)
    v0_resp = client.get_events(
        after_migration_id=MIGRATION_ID,
        after_record_time="2000-01-01T00:00:00Z",
        page_size=PAGE_SIZE,
    )
    save_json(v0_resp, "v0_events_sample.json")

    events = v0_resp.get("events", [])
    print(f"  Response top-level keys: {sorted(v0_resp.keys())}")
    print(f"  Number of events: {len(events)}")

    null_body_events = []
    normal_events = []
    for ev in events:
        if ev.get("update") is None:
            null_body_events.append(ev)
        else:
            normal_events.append(ev)

    print(f"  Normal events (update != null): {len(normal_events)}")
    print(f"  Null-body events (update == null): {len(null_body_events)}")

    if normal_events:
        ne = normal_events[0]
        print(f"\n  First normal event top-level keys: {sorted(ne.keys())}")
        print(f"  First normal event .update keys: {sorted(ne['update'].keys())}")
        if ne.get("verdict"):
            print(f"  First normal event .verdict keys: {sorted(ne['verdict'].keys())}")
        else:
            print(f"  First normal event .verdict: {ne.get('verdict')}")

    # ── 3. Save null-body events separately ──
    if null_body_events:
        save_json(null_body_events, "null_body_events.json")
        print(f"\n{'─' * 70}")
        print(f"  NULL-BODY EVENTS (verdict-only, no update body)")
        print(f"{'─' * 70}")
        for i, ev in enumerate(null_body_events[:5]):
            v = ev.get("verdict", {})
            print(f"\n  [{i+1}] Null-body event:")
            print(f"    Top-level keys: {sorted(ev.keys())}")
            print(f"    update: {ev.get('update')}")
            print(f"    verdict keys: {sorted(v.keys())}")
            print(f"    verdict_result: {v.get('verdict_result')}")
            print(f"    finalization_time: {v.get('finalization_time')}")
            print(f"    submitting_parties: {json.dumps(v.get('submitting_parties', [])[:2])}{'...' if len(v.get('submitting_parties', [])) > 2 else ''}")
            print(f"    submitting_participant_uid: {v.get('submitting_participant_uid')}")
            print(f"    mediator_group: {v.get('mediator_group')}")
            views = v.get("transaction_views", [])
            if isinstance(views, list):
                print(f"    transaction_views: {len(views)} views")
                for vi, view in enumerate(views[:2]):
                    if isinstance(view, dict):
                        informees = view.get("informees", [])
                        print(f"      view[{vi}]: {len(informees)} informees, keys={sorted(view.keys())}")
            # Check for update_id in verdict
            if "update_id" in v:
                print(f"    update_id (in verdict): {v['update_id'][:60]}...")
    else:
        print("\n  No null-body events found on this page. Trying larger page...")
        time.sleep(DELAY)
        v0_big = client.get_events(
            after_migration_id=MIGRATION_ID,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=100,
        )
        big_null = [ev for ev in v0_big.get("events", []) if ev.get("update") is None]
        if big_null:
            save_json(big_null[:10], "null_body_events.json")
            print(f"  Found {len(big_null)} null-body events in 100-item page")
            for i, ev in enumerate(big_null[:3]):
                v = ev.get("verdict", {})
                print(f"\n  [{i+1}] Null-body event:")
                print(f"    verdict keys: {sorted(v.keys())}")
                print(json.dumps(ev, indent=2)[:1500])
        else:
            print("  Still no null-body events found.")

    # ── 4. Build a matched pair example ──
    time.sleep(DELAY)
    print(f"\n{'─' * 70}")
    print(f"  MATCHED PAIR: same update_id from both endpoints")
    print(f"{'─' * 70}")
    if normal_events:
        sample_id = normal_events[0]["update"]["update_id"]
        print(f"  Looking up update_id: {sample_id[:60]}...")

        # Fetch individually from both endpoints
        v2_single = client.get_update_by_id(sample_id)
        time.sleep(DELAY)
        v0_single = client.get_event_by_id(sample_id)

        matched = {
            "update_id": sample_id,
            "v2_updates_response": v2_single,
            "v0_events_response": v0_single,
        }
        save_json(matched, "matched_pair_example.json")

        print(f"\n  /v2/updates/{sample_id[:30]}... response keys: {sorted(v2_single.keys())}")
        print(f"  /v0/events/{sample_id[:30]}... response keys: {sorted(v0_single.keys())}")
        if v0_single.get("verdict"):
            print(f"\n  Verdict (only in /v0/events):")
            print(json.dumps(v0_single["verdict"], indent=2)[:1000])

    print(f"\n{'=' * 70}")
    print(f"  Done. JSON files saved in {OUTPUT_DIR}/")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
