"""
Investigation Script: /v2/updates vs /v0/events

Compares the data returned by the two Scan API endpoints to determine
whether the events data alone is sufficient, or whether we also need
to ingest the updates data.

Three investigations:
  1. Single transaction lookup — fetch a known update_id from both endpoints
  2. Paginated window comparison — fetch the same time window from both and diff
  3. Difference categorization — characterize any missing data by template/choice

Usage:
    python scripts/investigate_updates_vs_events.py
    python scripts/investigate_updates_vs_events.py --update-id <id>
    python scripts/investigate_updates_vs_events.py --step 1
    python scripts/investigate_updates_vs_events.py --step 2 --page-size 50
"""

import argparse
import json
import sys
import os
import time
from collections import Counter
from datetime import datetime

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"

# The known traffic-purchase update that is missing from the events table
DEFAULT_UPDATE_ID = (
    "12206a4643d6c600a4e3f1f25df6cf22f4f97565f559f9517197b8a9f1cf05e01f43"
)


def pp(obj, label=None):
    """Pretty-print a JSON-serializable object with an optional label."""
    if label:
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"{'='*70}")
    print(json.dumps(obj, indent=2, default=str))


def summarize_events_by_id(events_by_id: dict) -> list[dict]:
    """Return a compact summary of each event inside an update."""
    summaries = []
    for eid, details in events_by_id.items():
        summary = {
            "event_id": eid,
            "template_id": details.get("template_id"),
            "contract_id": details.get("contract_id", "")[:20] + "...",
        }
        if "create_arguments" in details:
            summary["type"] = "created"
        elif "choice" in details:
            summary["type"] = "exercised"
            summary["choice"] = details["choice"]
            summary["child_event_ids"] = details.get("child_event_ids", [])
        elif details.get("archived"):
            summary["type"] = "archived"
        else:
            summary["type"] = "unknown"

        summary["signatories"] = details.get("signatories", [])
        summary["observers"] = details.get("observers", [])
        summaries.append(summary)
    return summaries


# ── Step 1: Single-transaction comparison ────────────────────────────────────

def step1_single_transaction(client: SpliceScanClient, update_id: str):
    """
    Fetch a single transaction from both /v2/updates/{id} and /v0/events/{id}
    and compare the responses.
    """
    print("\n" + "#" * 70)
    print("  STEP 1: Single Transaction Comparison")
    print(f"  update_id = {update_id}")
    print("#" * 70)

    # ── /v2/updates/{id} ─────────────────────────────────────────────────
    print("\n[1a] Fetching from /v2/updates/{id} ...")
    try:
        updates_resp = client.get_update_by_id(update_id)
        pp(updates_resp, "/v2/updates response (top-level keys)")
        if "transaction" in updates_resp:
            txn = updates_resp["transaction"]
        elif "update" in updates_resp:
            txn = updates_resp["update"]
        else:
            txn = updates_resp

        events_by_id = txn.get("events_by_id", {})
        print(f"\n  → Found {len(events_by_id)} events in this update")
        print(f"  → record_time  : {txn.get('record_time')}")
        print(f"  → effective_at : {txn.get('effective_at')}")
        print(f"  → migration_id : {txn.get('migration_id')}")
        print(f"  → synchronizer : {txn.get('synchronizer_id', '')[:40]}...")
        print(f"  → root_event_ids: {txn.get('root_event_ids', [])}")

        pp(summarize_events_by_id(events_by_id), "Event summaries from /v2/updates")

    except Exception as e:
        print(f"  ✗ /v2/updates failed: {e}")
        updates_resp = None

    # ── /v0/events/{id} ─────────────────────────────────────────────────
    print("\n[1b] Fetching from /v0/events/{id} ...")
    try:
        events_resp = client.get_event_by_id(update_id)
        pp(events_resp, "/v0/events response (top-level keys)")

        # Extract the inner transaction if wrapped
        if "event" in events_resp:
            evt_txn = events_resp["event"]
        elif "update" in events_resp:
            evt_txn = events_resp["update"]
        else:
            evt_txn = events_resp

        evt_events_by_id = evt_txn.get("events_by_id", {})
        print(f"\n  → Found {len(evt_events_by_id)} events in this event response")

    except Exception as e:
        print(f"  ✗ /v0/events/{update_id} failed: {e}")
        events_resp = None

    # ── Comparison ───────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("  STEP 1 CONCLUSION")
    print("-" * 70)
    if updates_resp and not events_resp:
        print("  ⚠  The update EXISTS in /v2/updates but NOT in /v0/events.")
        print("     This confirms /v0/events has a visibility gap.")
    elif updates_resp and events_resp:
        print("  Both endpoints returned data. Comparing event counts...")
        u_keys = set((txn or {}).get("events_by_id", {}).keys())
        e_keys = set((evt_txn or {}).get("events_by_id", {}).keys())
        only_in_updates = u_keys - e_keys
        only_in_events = e_keys - u_keys
        if only_in_updates:
            print(f"  ⚠  {len(only_in_updates)} events ONLY in /v2/updates: {only_in_updates}")
        if only_in_events:
            print(f"  ⚠  {len(only_in_events)} events ONLY in /v0/events: {only_in_events}")
        if not only_in_updates and not only_in_events:
            print("  ✓  Both endpoints returned the same event IDs for this transaction.")
    elif not updates_resp and not events_resp:
        print("  ✗  Neither endpoint returned data — check the update_id.")
    else:
        print("  Unexpected combination of responses.")

    return updates_resp, events_resp


# ── Step 2: Paginated window comparison ──────────────────────────────────────

def step2_paginated_comparison(
    client: SpliceScanClient,
    page_size: int = 50,
    num_pages: int = 3,
):
    """
    Fetch the same time window from /v2/updates and /v0/events, then compare
    which update_ids appear in each.

    Strategy: first fetch one page from /v2/updates to get a cursor, then
    fetch the same window from /v0/events.
    """
    print("\n" + "#" * 70)
    print("  STEP 2: Paginated Window Comparison")
    print(f"  page_size={page_size}, num_pages={num_pages}")
    print("#" * 70)

    # ── Fetch from /v2/updates ───────────────────────────────────────────
    print("\n[2a] Fetching from /v2/updates ...")
    updates_by_id = {}  # update_id → full transaction dict
    cursor_migration_id = None
    cursor_record_time = None
    first_migration_id = None
    first_record_time = None

    for page_num in range(num_pages):
        print(f"  Page {page_num + 1}/{num_pages} ...", end=" ", flush=True)
        resp = client.get_updates(
            after_migration_id=cursor_migration_id,
            after_record_time=cursor_record_time,
            page_size=page_size,
        )

        txns = resp.get("updates", resp.get("transactions", []))
        print(f"got {len(txns)} transactions")

        if not txns:
            break

        for txn in txns:
            uid = txn.get("update_id")
            if uid:
                updates_by_id[uid] = txn

        # Save the first cursor for /v0/events alignment
        if page_num == 0 and txns:
            first_migration_id = txns[0].get("migration_id")
            first_record_time = txns[0].get("record_time")

        # Advance cursor from the 'after' field or last transaction
        after = resp.get("after")
        if after:
            cursor_migration_id = after.get("after_migration_id")
            cursor_record_time = after.get("after_record_time")
        else:
            last = txns[-1]
            cursor_migration_id = last.get("migration_id")
            cursor_record_time = last.get("record_time")

        time.sleep(0.2)

    print(f"\n  → Total unique update_ids from /v2/updates: {len(updates_by_id)}")

    if not updates_by_id:
        print("  ✗  No updates fetched. Cannot proceed with comparison.")
        return

    # Determine the time window we fetched
    all_record_times = [
        t.get("record_time") for t in updates_by_id.values() if t.get("record_time")
    ]
    if all_record_times:
        print(f"  → Time window: {min(all_record_times)} .. {max(all_record_times)}")

    # ── Fetch from /v0/events over the same window ───────────────────────
    # We use the first transaction's cursor as the starting point, but we
    # need to start *before* it. The /v0/events cursor is exclusive (after),
    # so we try starting from the beginning (no cursor) and fetching the
    # same number of pages. If there's a lot of data, we align by using
    # the first record_time we saw.
    print("\n[2b] Fetching from /v0/events (same window) ...")
    events_update_ids = set()
    events_all = {}  # update_id → list of event dicts from this endpoint
    ev_cursor_migration_id = None
    ev_cursor_record_time = None

    # To align windows: start slightly before the first updates record_time
    # We'll use the same starting cursor if available
    if first_migration_id is not None and first_record_time is not None:
        # Start from the same position as updates
        # The "after" cursor is exclusive, so we need to go slightly before
        # For alignment, we pass None to start from the very beginning and
        # collect until we've covered the same time window. But that could
        # be huge. Instead, use the same cursor.
        ev_cursor_migration_id = None
        ev_cursor_record_time = None

    # We may need more pages from events since events are more granular
    # (one event per row vs one update per row with multiple events).
    # Fetch proportionally more pages.
    max_ev_pages = num_pages * 10
    target_max_time = max(all_record_times) if all_record_times else None

    for page_num in range(max_ev_pages):
        print(f"  Page {page_num + 1} ...", end=" ", flush=True)
        try:
            resp = client.get_events(
                after_migration_id=ev_cursor_migration_id,
                after_record_time=ev_cursor_record_time,
                page_size=page_size,
            )
        except Exception as e:
            print(f"error: {e}")
            break

        raw_events = resp.get("events", [])
        print(f"got {len(raw_events)} event wrappers")

        if not raw_events:
            break

        for evt_wrapper in raw_events:
            evt = evt_wrapper.get("update", evt_wrapper)
            uid = evt.get("update_id")
            if uid:
                events_update_ids.add(uid)
                if uid not in events_all:
                    events_all[uid] = []
                events_by_id = evt.get("events_by_id", {})
                events_all[uid].append({
                    "record_time": evt.get("record_time"),
                    "event_count": len(events_by_id),
                    "event_ids": list(events_by_id.keys()),
                })

        # Advance cursor
        last_evt = raw_events[-1]
        last_update = last_evt.get("update", last_evt)
        ev_cursor_migration_id = last_update.get("migration_id")
        ev_cursor_record_time = last_update.get("record_time")

        # Check if we've gone past our target window
        if target_max_time and ev_cursor_record_time and ev_cursor_record_time > target_max_time:
            print(f"  Reached target window end ({target_max_time}), stopping.")
            break

        time.sleep(0.2)

    print(f"\n  → Total unique update_ids from /v0/events: {len(events_update_ids)}")

    # ── Diff ─────────────────────────────────────────────────────────────
    updates_set = set(updates_by_id.keys())
    only_in_updates = updates_set - events_update_ids
    only_in_events = events_update_ids - updates_set
    in_both = updates_set & events_update_ids

    print("\n" + "-" * 70)
    print("  STEP 2 RESULTS")
    print("-" * 70)
    print(f"  update_ids in /v2/updates : {len(updates_set)}")
    print(f"  update_ids in /v0/events  : {len(events_update_ids)}")
    print(f"  In both                   : {len(in_both)}")
    print(f"  ONLY in /v2/updates       : {len(only_in_updates)}")
    print(f"  ONLY in /v0/events        : {len(only_in_events)}")

    if only_in_updates:
        print(f"\n  ⚠  {len(only_in_updates)} updates are MISSING from /v0/events:")
        for uid in sorted(only_in_updates):
            txn = updates_by_id[uid]
            ebi = txn.get("events_by_id", {})
            templates = set(e.get("template_id", "?") for e in ebi.values())
            choices = set(
                e.get("choice", "")
                for e in ebi.values()
                if e.get("choice")
            )
            print(f"    - {uid[:24]}...  events={len(ebi)}  "
                  f"templates={templates}  choices={choices}")

    if only_in_events:
        print(f"\n  ⚠  {len(only_in_events)} update_ids are ONLY in /v0/events "
              "(not in /v2/updates window — likely pagination mismatch):")
        for uid in sorted(only_in_events)[:10]:
            print(f"    - {uid[:24]}...")

    return updates_by_id, events_update_ids, only_in_updates, only_in_events


# ── Step 3: Categorize differences ───────────────────────────────────────────

def step3_categorize_differences(
    updates_by_id: dict,
    missing_update_ids: set,
):
    """
    For updates that are in /v2/updates but missing from /v0/events,
    categorize them by template_id, choice, and other attributes.
    """
    print("\n" + "#" * 70)
    print("  STEP 3: Categorize Missing Updates")
    print("#" * 70)

    if not missing_update_ids:
        print("\n  ✓  No missing updates to categorize. /v0/events appears complete.")
        return

    template_counter = Counter()
    choice_counter = Counter()
    event_type_counter = Counter()
    sample_payloads = {}  # template_id → first payload seen

    for uid in missing_update_ids:
        txn = updates_by_id.get(uid)
        if not txn:
            continue

        events_by_id = txn.get("events_by_id", {})
        for eid, details in events_by_id.items():
            tid = details.get("template_id", "unknown")
            template_counter[tid] += 1

            if "create_arguments" in details:
                event_type_counter["created"] += 1
            elif "choice" in details:
                event_type_counter["exercised"] += 1
                choice_counter[details["choice"]] += 1
            elif details.get("archived"):
                event_type_counter["archived"] += 1

            # Capture one sample payload per template
            if tid not in sample_payloads:
                payload = details.get("create_arguments") or details.get("choice_argument")
                if payload:
                    sample_payloads[tid] = {
                        "event_id": eid,
                        "update_id": uid,
                        "payload_keys": list(payload.keys()) if isinstance(payload, dict) else str(type(payload)),
                    }

    print(f"\n  Missing updates: {len(missing_update_ids)}")

    print("\n  Event types in missing updates:")
    for et, count in event_type_counter.most_common():
        print(f"    {et:12s} : {count}")

    print("\n  Templates in missing updates:")
    for tid, count in template_counter.most_common(20):
        print(f"    {tid:50s} : {count}")

    print("\n  Choices in missing updates:")
    for ch, count in choice_counter.most_common(20):
        print(f"    {ch:40s} : {count}")

    if sample_payloads:
        print("\n  Sample payload structures (one per template):")
        for tid, info in list(sample_payloads.items())[:10]:
            print(f"    {tid}:")
            print(f"      event_id   : {info['event_id']}")
            print(f"      update_id  : {info['update_id'][:24]}...")
            print(f"      payload keys: {info['payload_keys']}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compare /v2/updates vs /v0/events from the Canton Scan API"
    )
    parser.add_argument(
        "--update-id",
        default=DEFAULT_UPDATE_ID,
        help="Specific update_id to investigate in Step 1",
    )
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Run only a specific step (default: run all)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="Page size for paginated fetches (default: 50)",
    )
    parser.add_argument(
        "--num-pages",
        type=int,
        default=3,
        help="Number of pages to fetch from /v2/updates in Step 2 (default: 3)",
    )
    parser.add_argument(
        "--url",
        default=BASE_URL,
        help="Scan API base URL",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  Canton Scan API: /v2/updates vs /v0/events Investigation")
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print(f"  API:  {args.url}")
    print("=" * 70)

    client = SpliceScanClient(base_url=args.url, timeout=60)

    # ── Step 1 ───────────────────────────────────────────────────────────
    if args.step is None or args.step == 1:
        step1_single_transaction(client, args.update_id)

    # ── Step 2 ───────────────────────────────────────────────────────────
    updates_by_id = None
    missing_ids = None

    if args.step is None or args.step == 2:
        result = step2_paginated_comparison(
            client,
            page_size=args.page_size,
            num_pages=args.num_pages,
        )
        if result:
            updates_by_id, _, missing_ids, _ = result

    # ── Step 3 ───────────────────────────────────────────────────────────
    if args.step is None or args.step == 3:
        if updates_by_id is not None and missing_ids is not None:
            step3_categorize_differences(updates_by_id, missing_ids)
        elif args.step == 3:
            print("\n  Step 3 requires Step 2 results. Run without --step or use --step 2 first.")

    print("\n" + "=" * 70)
    print("  Investigation complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
