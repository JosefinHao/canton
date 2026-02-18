"""
Set-Difference Analysis: /v2/updates vs /v0/events

Determines whether the two endpoints return the SAME SET of transactions,
or if either endpoint contains transactions missing from the other.

This answers:
  1. Are there update_ids in /v2/updates that are NOT in /v0/events?
  2. Are there update_ids in /v0/events that are NOT in /v2/updates?
  3. Do the counts match per migration_id?
  4. Are there gaps at migration boundaries, page boundaries, or time edges?
  5. What types of transactions (if any) are exclusive to one endpoint?

Strategy:
  - Paginate EXHAUSTIVELY through each migration in both endpoints
  - Collect the full set of update_ids from each
  - Compare sets and investigate any differences

Usage:
    python scripts/set_difference_analysis.py
    python scripts/set_difference_analysis.py --migration-id 3
    python scripts/set_difference_analysis.py --max-pages 500
    python scripts/set_difference_analysis.py --output-json output/set_diff_report.json
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
REQUEST_DELAY = 0.15
MIGRATION_IDS = [0, 1, 2, 3, 4]


def banner(text: str, char: str = "=", width: int = 78):
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}", flush=True)


def sub_banner(text: str):
    banner(text, char="-", width=78)


# ═══════════════════════════════════════════════════════════════════════════════
#  Exhaustive ID Collection
# ═══════════════════════════════════════════════════════════════════════════════

def collect_all_ids(client, migration_id, page_size=500, max_pages=1000,
                    source="updates"):
    """
    Paginate exhaustively through one endpoint for a single migration_id.
    Collects BOTH update_ids AND event_ids (from inside events_by_id).

    Returns:
      - ordered list of update records with embedded event_ids
      - total pages fetched
    """
    results = []
    seen_updates = set()
    all_event_ids = set()
    # Map: update_id → set of event_ids it contains
    events_per_update = {}
    cursor_rt = "2000-01-01T00:00:00Z"

    for page_num in range(max_pages):
        try:
            if source == "updates":
                resp = client.get_updates(
                    after_migration_id=migration_id,
                    after_record_time=cursor_rt,
                    page_size=page_size,
                )
                items = resp.get("updates", resp.get("transactions", []))
            else:
                resp = client.get_events(
                    after_migration_id=migration_id,
                    after_record_time=cursor_rt,
                    page_size=page_size,
                )
                raw_events = resp.get("events", [])
                items = []
                for wrapper in raw_events:
                    update = wrapper.get("update")
                    if update:
                        items.append(update)
                    else:
                        # Event with no update body — track this!
                        verdict = wrapper.get("verdict")
                        uid = None
                        if verdict:
                            uid = verdict.get("update_id")
                        items.append({
                            "update_id": uid or f"__null_update_page{page_num}_{len(items)}",
                            "migration_id": migration_id,
                            "record_time": verdict.get("record_time") if verdict else None,
                            "_null_update": True,
                            "_verdict": verdict,
                        })

            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"    ERROR on page {page_num + 1}: {e}")
            time.sleep(1)
            continue

        if not items:
            break

        # Check if we've left this migration
        first_mig = items[0].get("migration_id")
        if first_mig is not None and first_mig != migration_id:
            break

        for item in items:
            item_mig = item.get("migration_id")
            if item_mig is not None and item_mig != migration_id:
                # We've crossed into the next migration, stop
                return results, events_per_update, all_event_ids, page_num + 1

            uid = item.get("update_id")
            rt = item.get("record_time")

            # Collect event_ids from events_by_id
            ebi = item.get("events_by_id", {})
            event_ids_in_update = set(ebi.keys())
            all_event_ids.update(event_ids_in_update)

            if uid and uid not in seen_updates:
                seen_updates.add(uid)
                events_per_update[uid] = event_ids_in_update
                results.append({
                    "update_id": uid,
                    "record_time": rt,
                    "migration_id": migration_id,
                    "event_count": len(event_ids_in_update),
                    "_null_update": item.get("_null_update", False),
                })

        after = resp.get("after")
        if not after:
            break

        next_mig = after.get("after_migration_id")
        if next_mig != migration_id:
            break

        cursor_rt = after.get("after_record_time")

        if (page_num + 1) % 10 == 0:
            print(f"    ... page {page_num + 1}, {len(results)} unique updates, "
                  f"{len(all_event_ids)} events, at {cursor_rt}", flush=True)

        if len(items) < page_size:
            break

    return results, events_per_update, all_event_ids, page_num + 1 if items else page_num


# ═══════════════════════════════════════════════════════════════════════════════
#  Per-Migration Comparison
# ═══════════════════════════════════════════════════════════════════════════════

def compare_migration(client, migration_id, page_size=500, max_pages=1000):
    """Compare the full set of update_ids AND event_ids for one migration between both endpoints."""
    sub_banner(f"Migration {migration_id}")

    # Collect from /v2/updates (update_ids + event_ids)
    print(f"  Collecting from /v2/updates...", flush=True)
    u_items, u_events_per_update, u_all_events, u_pages = collect_all_ids(
        client, migration_id, page_size, max_pages, source="updates")
    u_ids = {item["update_id"] for item in u_items}
    u_total_events = sum(item["event_count"] for item in u_items)
    print(f"    → {len(u_ids)} unique update_ids, {len(u_all_events)} unique event_ids in {u_pages} pages")
    if u_items:
        print(f"    → Time range: {u_items[0]['record_time']} .. {u_items[-1]['record_time']}")

    # Collect from /v0/events (update_ids + event_ids)
    print(f"  Collecting from /v0/events...", flush=True)
    e_items, e_events_per_update, e_all_events, e_pages = collect_all_ids(
        client, migration_id, page_size, max_pages, source="events")
    e_ids = {item["update_id"] for item in e_items}
    e_total_events = sum(item["event_count"] for item in e_items)
    null_updates = [item for item in e_items if item.get("_null_update")]
    print(f"    → {len(e_ids)} unique update_ids, {len(e_all_events)} unique event_ids in {e_pages} pages")
    if e_items:
        print(f"    → Time range: {e_items[0]['record_time']} .. {e_items[-1]['record_time']}")
    if null_updates:
        print(f"    → ⚠ {len(null_updates)} events with NULL update body!")

    # ── Update-level set comparison ──
    only_in_updates = u_ids - e_ids
    only_in_events = e_ids - u_ids
    in_both = u_ids & e_ids

    print(f"\n  Update-Level Set Comparison:")
    print(f"    In both:           {len(in_both)}")
    print(f"    Only in /v2/upd:   {len(only_in_updates)}")
    print(f"    Only in /v0/evt:   {len(only_in_events)}")

    # Ordering comparison (for update_ids in both)
    u_order = [item["update_id"] for item in u_items if item["update_id"] in in_both]
    e_order = [item["update_id"] for item in e_items if item["update_id"] in in_both]
    ordering_match = u_order == e_order
    print(f"    Ordering match:    {ordering_match}")

    # ── Event-level set comparison ──
    events_only_in_updates = u_all_events - e_all_events
    events_only_in_events = e_all_events - u_all_events
    events_in_both = u_all_events & e_all_events

    print(f"\n  Event-Level Set Comparison (individual event_ids inside events_by_id):")
    print(f"    Total event_ids in /v2/updates: {len(u_all_events)}")
    print(f"    Total event_ids in /v0/events:  {len(e_all_events)}")
    print(f"    In both:           {len(events_in_both)}")
    print(f"    Only in /v2/upd:   {len(events_only_in_updates)}")
    print(f"    Only in /v0/evt:   {len(events_only_in_events)}")

    # ── Per-update event_id comparison ──
    # For updates that exist in both, check if they contain the same event_ids
    event_mismatch_updates = []
    for uid in in_both:
        u_eids = u_events_per_update.get(uid, set())
        e_eids = e_events_per_update.get(uid, set())
        if u_eids != e_eids:
            event_mismatch_updates.append({
                "update_id": uid,
                "only_in_updates": sorted(u_eids - e_eids),
                "only_in_events": sorted(e_eids - u_eids),
                "updates_count": len(u_eids),
                "events_count": len(e_eids),
            })

    print(f"\n  Per-Update Event Consistency (for {len(in_both)} shared updates):")
    print(f"    Updates with matching event_ids:    {len(in_both) - len(event_mismatch_updates)}")
    print(f"    Updates with mismatched event_ids:  {len(event_mismatch_updates)}")
    if event_mismatch_updates:
        print(f"    ⚠ EVENT MISMATCHES FOUND:")
        for mm in event_mismatch_updates[:5]:
            print(f"      Update {mm['update_id'][:40]}...")
            print(f"        /v2/updates has {mm['updates_count']} events, "
                  f"/v0/events has {mm['events_count']} events")
            if mm["only_in_updates"]:
                print(f"        Event_ids only in updates: {mm['only_in_updates'][:3]}")
            if mm["only_in_events"]:
                print(f"        Event_ids only in events: {mm['only_in_events'][:3]}")

    result = {
        "migration_id": migration_id,
        # Update-level
        "updates_count": len(u_ids),
        "events_count": len(e_ids),
        "in_both": len(in_both),
        "only_in_updates": len(only_in_updates),
        "only_in_events": len(only_in_events),
        "null_update_events": len(null_updates),
        "ordering_match": ordering_match,
        "updates_pages": u_pages,
        "events_pages": e_pages,
        "updates_time_range": (
            u_items[0]["record_time"] if u_items else None,
            u_items[-1]["record_time"] if u_items else None,
        ),
        "events_time_range": (
            e_items[0]["record_time"] if e_items else None,
            e_items[-1]["record_time"] if e_items else None,
        ),
        # Event-level
        "total_event_ids_updates": len(u_all_events),
        "total_event_ids_events": len(e_all_events),
        "event_ids_in_both": len(events_in_both),
        "event_ids_only_in_updates": len(events_only_in_updates),
        "event_ids_only_in_events": len(events_only_in_events),
        "event_mismatch_updates_count": len(event_mismatch_updates),
        "event_mismatch_examples": event_mismatch_updates[:10],
        # For investigation
        "only_in_updates_ids": [],
        "only_in_events_ids": [],
        "only_in_updates_details": [],
        "only_in_events_details": [],
        "events_only_in_updates_ids": sorted(events_only_in_updates)[:20],
        "events_only_in_events_ids": sorted(events_only_in_events)[:20],
    }

    # Investigate any differences
    if only_in_updates:
        print(f"\n  ⚠ UPDATES-ONLY transactions ({len(only_in_updates)}):")
        result["only_in_updates_ids"] = sorted(only_in_updates)
        _investigate_exclusive_ids(client, sorted(only_in_updates)[:10],
                                   "updates", result)

    if only_in_events:
        print(f"\n  ⚠ EVENTS-ONLY transactions ({len(only_in_events)}):")
        result["only_in_events_ids"] = sorted(only_in_events)
        _investigate_exclusive_ids(client, sorted(only_in_events)[:10],
                                   "events", result)

    if not only_in_updates and not only_in_events:
        print(f"\n  ✓ PERFECT MATCH: Both endpoints return identical transaction sets")

    return result


def _investigate_exclusive_ids(client, update_ids, found_in, result):
    """For IDs found only in one endpoint, fetch from both to understand why."""
    details_key = f"only_in_{found_in}_details"

    for uid in update_ids[:10]:
        print(f"    Investigating {uid[:40]}...")
        detail = {"update_id": uid}

        # Try to fetch from /v2/updates/{id}
        try:
            u_resp = client.get_update_by_id(uid)
            time.sleep(REQUEST_DELAY)
            detail["in_updates_by_id"] = True
            detail["updates_resp_keys"] = list(u_resp.keys())
            # Check what type of transaction this is
            body = u_resp.get("transaction", u_resp.get("update", u_resp))
            if body:
                detail["update_type"] = "transaction"
                ebi = body.get("events_by_id", {})
                detail["event_count"] = len(ebi)
                templates = set()
                choices = set()
                for evt in ebi.values():
                    tid = evt.get("template_id", "unknown")
                    templates.add(tid)
                    if evt.get("choice"):
                        choices.add(evt["choice"])
                detail["templates"] = sorted(templates)
                detail["choices"] = sorted(choices)
            elif "reassignment" in u_resp:
                detail["update_type"] = "reassignment"
                detail["reassignment_keys"] = list(u_resp["reassignment"].keys())
            else:
                detail["update_type"] = "unknown"
                detail["resp_keys"] = list(u_resp.keys())
        except Exception as e:
            detail["in_updates_by_id"] = False
            detail["updates_error"] = str(e)

        # Try to fetch from /v0/events/{id}
        try:
            e_resp = client.get_event_by_id(uid)
            time.sleep(REQUEST_DELAY)
            detail["in_events_by_id"] = True
            detail["events_resp_keys"] = list(e_resp.keys())
            if e_resp.get("verdict"):
                detail["has_verdict"] = True
                detail["verdict_result"] = e_resp["verdict"].get("verdict_result")
            else:
                detail["has_verdict"] = False
            if e_resp.get("update"):
                detail["events_has_update_body"] = True
            else:
                detail["events_has_update_body"] = False
        except Exception as e:
            detail["in_events_by_id"] = False
            detail["events_error"] = str(e)

        result[details_key].append(detail)

        # Print summary
        u_status = "✓" if detail.get("in_updates_by_id") else "✗"
        e_status = "✓" if detail.get("in_events_by_id") else "✗"
        utype = detail.get("update_type", "?")
        print(f"      /v2/updates/{uid[:20]}...: {u_status} ({utype})")
        print(f"      /v0/events/{uid[:20]}...:  {e_status}")
        if detail.get("templates"):
            print(f"      Templates: {detail['templates']}")
        if detail.get("choices"):
            print(f"      Choices: {detail['choices']}")
        if detail.get("update_type") == "reassignment":
            print(f"      ★ This is a REASSIGNMENT (not a transaction)")
        if detail.get("has_verdict") is False and detail.get("in_events_by_id"):
            print(f"      No verdict on this event")


# ═══════════════════════════════════════════════════════════════════════════════
#  Cross-Migration Boundary Check
# ═══════════════════════════════════════════════════════════════════════════════

def check_migration_boundaries(client, migration_ids):
    """
    Check if there are any transactions at migration boundaries that
    appear differently between endpoints.
    """
    banner("Migration Boundary Analysis")
    print("  Checking if transactions near migration boundaries differ\n")

    results = []

    for i in range(len(migration_ids) - 1):
        mig_a = migration_ids[i]
        mig_b = migration_ids[i + 1]
        print(f"  Boundary: migration {mig_a} → {mig_b}")

        # Get the last few updates from migration A
        # We need to find the end of migration A first
        print(f"    Finding end of migration {mig_a}...")

        # Paginate to the end of migration A
        cursor_rt = "2000-01-01T00:00:00Z"
        last_items_u = []
        for _ in range(200):  # Up to 200 pages
            resp = client.get_updates(
                after_migration_id=mig_a,
                after_record_time=cursor_rt,
                page_size=500,
            )
            items = resp.get("updates", resp.get("transactions", []))
            time.sleep(REQUEST_DELAY)

            if not items:
                break

            # Filter to only this migration
            mig_items = [t for t in items if t.get("migration_id") == mig_a]
            if mig_items:
                last_items_u = mig_items[-10:]  # Keep last 10

            after = resp.get("after")
            if not after or after.get("after_migration_id") != mig_a:
                break
            cursor_rt = after.get("after_record_time")

        if not last_items_u:
            print(f"    No data at end of migration {mig_a}")
            continue

        # Now check these same IDs exist in events
        last_ids = [t["update_id"] for t in last_items_u]
        print(f"    Last {len(last_ids)} update_ids from migration {mig_a}:")

        missing_in_events = []
        for uid in last_ids:
            try:
                e_resp = client.get_event_by_id(uid)
                time.sleep(REQUEST_DELAY)
                status = "✓"
                if not e_resp.get("update"):
                    status = "⚠ no update body"
            except Exception:
                status = "✗ NOT FOUND"
                missing_in_events.append(uid)
            print(f"      {uid[:40]}... → events: {status}")

        # Get first few from migration B
        print(f"    First updates from migration {mig_b}:")
        resp = client.get_updates(
            after_migration_id=mig_b,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=5,
        )
        first_items = resp.get("updates", resp.get("transactions", []))
        time.sleep(REQUEST_DELAY)

        for t in first_items[:5]:
            uid = t["update_id"]
            try:
                e_resp = client.get_event_by_id(uid)
                time.sleep(REQUEST_DELAY)
                status = "✓"
            except Exception:
                status = "✗ NOT FOUND"
            print(f"      {uid[:40]}... → events: {status}")

        results.append({
            "boundary": f"{mig_a}→{mig_b}",
            "last_ids_mig_a": last_ids,
            "missing_in_events": missing_in_events,
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(migration_results, boundary_results):
    banner("OVERALL SUMMARY")

    # ── Update-level totals ──
    total_u = sum(r["updates_count"] for r in migration_results)
    total_e = sum(r["events_count"] for r in migration_results)
    total_both = sum(r["in_both"] for r in migration_results)
    total_only_u = sum(r["only_in_updates"] for r in migration_results)
    total_only_e = sum(r["only_in_events"] for r in migration_results)
    total_null = sum(r["null_update_events"] for r in migration_results)

    print(f"\n  UPDATE-LEVEL (update_id) TOTALS:")
    print(f"    /v2/updates:  {total_u}")
    print(f"    /v0/events:   {total_e}")
    print(f"    In both:      {total_both}")
    print(f"    Only updates: {total_only_u}")
    print(f"    Only events:  {total_only_e}")
    print(f"    Null-body:    {total_null}")

    print(f"\n  Per migration (update_ids):")
    print(f"  {'Mig':>4} {'Updates':>8} {'Events':>8} {'Both':>8} {'Only U':>8} {'Only E':>8} {'Order':>6}")
    print(f"  {'─'*4} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*6}")
    for r in migration_results:
        order = "✓" if r["ordering_match"] else "✗"
        print(f"  {r['migration_id']:>4} {r['updates_count']:>8} {r['events_count']:>8} "
              f"{r['in_both']:>8} {r['only_in_updates']:>8} {r['only_in_events']:>8} {order:>6}")

    # ── Event-level totals ──
    total_evt_u = sum(r.get("total_event_ids_updates", 0) for r in migration_results)
    total_evt_e = sum(r.get("total_event_ids_events", 0) for r in migration_results)
    total_evt_both = sum(r.get("event_ids_in_both", 0) for r in migration_results)
    total_evt_only_u = sum(r.get("event_ids_only_in_updates", 0) for r in migration_results)
    total_evt_only_e = sum(r.get("event_ids_only_in_events", 0) for r in migration_results)
    total_evt_mismatch = sum(r.get("event_mismatch_updates_count", 0) for r in migration_results)

    print(f"\n  EVENT-LEVEL (event_id inside events_by_id) TOTALS:")
    print(f"    /v2/updates:  {total_evt_u}")
    print(f"    /v0/events:   {total_evt_e}")
    print(f"    In both:      {total_evt_both}")
    print(f"    Only updates: {total_evt_only_u}")
    print(f"    Only events:  {total_evt_only_e}")

    print(f"\n  Per migration (event_ids):")
    print(f"  {'Mig':>4} {'Upd Evts':>9} {'Evt Evts':>9} {'Both':>8} {'Only U':>8} {'Only E':>8} {'Mismatch':>9}")
    print(f"  {'─'*4} {'─'*9} {'─'*9} {'─'*8} {'─'*8} {'─'*8} {'─'*9}")
    for r in migration_results:
        print(f"  {r['migration_id']:>4} "
              f"{r.get('total_event_ids_updates', 0):>9} "
              f"{r.get('total_event_ids_events', 0):>9} "
              f"{r.get('event_ids_in_both', 0):>8} "
              f"{r.get('event_ids_only_in_updates', 0):>8} "
              f"{r.get('event_ids_only_in_events', 0):>8} "
              f"{r.get('event_mismatch_updates_count', 0):>9}")

    # ── Conclusions ──
    all_updates_match = total_only_u == 0 and total_only_e == 0
    all_events_match = total_evt_only_u == 0 and total_evt_only_e == 0
    no_mismatches = total_evt_mismatch == 0

    if all_updates_match and all_events_match and no_mismatches:
        print(f"\n  ✓ CONCLUSION: Both endpoints return the EXACT SAME SET of")
        print(f"    update_ids ({total_both}) AND event_ids ({total_evt_both})")
        print(f"    across all {len(migration_results)} migrations. No differences at any level.")
    else:
        print(f"\n  ⚠ CONCLUSION: DIFFERENCES EXIST!")
        if not all_updates_match:
            if total_only_u > 0:
                print(f"    {total_only_u} update_ids exist ONLY in /v2/updates")
                for r in migration_results:
                    for d in r.get("only_in_updates_details", []):
                        utype = d.get("update_type", "?")
                        print(f"      Migration {r['migration_id']}: "
                              f"{d['update_id'][:40]}... ({utype})")
            if total_only_e > 0:
                print(f"    {total_only_e} update_ids exist ONLY in /v0/events")
                for r in migration_results:
                    for d in r.get("only_in_events_details", []):
                        print(f"      Migration {r['migration_id']}: "
                              f"{d['update_id'][:40]}...")
        if not all_events_match:
            print(f"    {total_evt_only_u} event_ids exist ONLY in /v2/updates")
            print(f"    {total_evt_only_e} event_ids exist ONLY in /v0/events")
        if not no_mismatches:
            print(f"    {total_evt_mismatch} updates contain DIFFERENT event_ids between endpoints")
            for r in migration_results:
                for mm in r.get("event_mismatch_examples", []):
                    print(f"      Migration {r['migration_id']}: {mm['update_id'][:40]}...")
                    print(f"        updates: {mm['updates_count']} events, "
                          f"events: {mm['events_count']} events")


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Set-difference analysis: /v2/updates vs /v0/events"
    )
    parser.add_argument("--migration-id", type=int,
                        help="Check only this migration (default: all)")
    parser.add_argument("--max-pages", type=int, default=1000,
                        help="Max pages to fetch per migration per endpoint (default: 1000)")
    parser.add_argument("--page-size", type=int, default=500,
                        help="Page size for API requests (default: 500)")
    parser.add_argument("--skip-boundaries", action="store_true",
                        help="Skip migration boundary analysis")
    parser.add_argument("--output-json", type=str,
                        help="Save results to JSON file")
    parser.add_argument("--base-url", type=str, default=BASE_URL,
                        help="Scan API base URL")
    args = parser.parse_args()

    banner("Set-Difference Analysis: /v2/updates vs /v0/events", char="█", width=78)
    print(f"  Time:        {datetime.utcnow().isoformat()}Z")
    print(f"  API:         {args.base_url}")
    print(f"  Max pages:   {args.max_pages} per migration per endpoint")
    print(f"  Page size:   {args.page_size}")

    if args.migration_id is not None:
        migrations = [args.migration_id]
    else:
        migrations = MIGRATION_IDS

    print(f"  Migrations:  {migrations}")

    client = SpliceScanClient(base_url=args.base_url, timeout=60)

    migration_results = []
    boundary_results = []

    try:
        for mig_id in migrations:
            result = compare_migration(
                client, mig_id,
                page_size=args.page_size,
                max_pages=args.max_pages)
            migration_results.append(result)

        if not args.skip_boundaries and len(migrations) > 1:
            boundary_results = check_migration_boundaries(client, migrations)

        print_summary(migration_results, boundary_results)

        if args.output_json:
            os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
            report = {
                "timestamp": datetime.utcnow().isoformat(),
                "migrations": migration_results,
                "boundaries": boundary_results,
            }
            # Convert sets/tuples for JSON
            def sanitize(obj):
                if isinstance(obj, set):
                    return sorted(obj)
                if isinstance(obj, tuple):
                    return list(obj)
                if isinstance(obj, dict):
                    return {k: sanitize(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [sanitize(v) for v in obj]
                return obj
            with open(args.output_json, "w") as f:
                json.dump(sanitize(report), f, indent=2, default=str)
            print(f"\n  Results saved to: {args.output_json}")

    finally:
        client.close()

    banner("Analysis complete", char="█", width=78)


if __name__ == "__main__":
    main()
