"""
Comprehensive Comparison: /v2/updates vs /v0/events

Runs a battery of tests across multiple time windows and transaction types
to determine whether we can rely solely on /v0/events, or need both endpoints.

Five phases:
  1. Schema & field-level deep diff (per-update recursive comparison)
  2. Transaction coverage over large time windows (set comparison)
  3. Event type coverage (created, exercised, reassignment edge cases)
  4. Template & choice coverage (per-template spot checks)
  5. Summary report

Usage:
    python scripts/compare_updates_vs_events.py
    python scripts/compare_updates_vs_events.py --phase 1
    python scripts/compare_updates_vs_events.py --sample-size 100 --num-windows 5
    python scripts/compare_updates_vs_events.py --output-json output/report.json
"""

import argparse
import json
import sys
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"

# Delay between individual GET requests to avoid throttling
REQUEST_DELAY = 0.5


# ═══════════════════════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════════════════════

def banner(text: str, char: str = "=", width: int = 78):
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def sub_banner(text: str):
    banner(text, char="-", width=78)


def pp(obj, label: Optional[str] = None):
    if label:
        banner(label)
    print(json.dumps(obj, indent=2, default=str))


def deep_diff(a: Any, b: Any, path: str = "") -> List[Dict[str, Any]]:
    """
    Recursively compare two JSON-like objects.
    Returns a list of difference records:
      {"path": "...", "type": "missing_in_a|missing_in_b|value_mismatch|type_mismatch", ...}
    """
    diffs = []

    if type(a) != type(b):
        diffs.append({
            "path": path or "(root)",
            "type": "type_mismatch",
            "a_type": type(a).__name__,
            "b_type": type(b).__name__,
            "a_value": _truncate(a),
            "b_value": _truncate(b),
        })
        return diffs

    if isinstance(a, dict):
        all_keys = set(a.keys()) | set(b.keys())
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in a:
                diffs.append({
                    "path": child_path,
                    "type": "missing_in_a",
                    "b_value": _truncate(b[key]),
                })
            elif key not in b:
                diffs.append({
                    "path": child_path,
                    "type": "missing_in_b",
                    "a_value": _truncate(a[key]),
                })
            else:
                diffs.extend(deep_diff(a[key], b[key], child_path))

    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append({
                "path": path,
                "type": "list_length_mismatch",
                "a_length": len(a),
                "b_length": len(b),
            })
        for i in range(min(len(a), len(b))):
            diffs.extend(deep_diff(a[i], b[i], f"{path}[{i}]"))

    else:
        if a != b:
            diffs.append({
                "path": path or "(root)",
                "type": "value_mismatch",
                "a_value": _truncate(a),
                "b_value": _truncate(b),
            })

    return diffs


def _truncate(value: Any, max_len: int = 120) -> Any:
    """Truncate long values for display."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    if isinstance(value, (dict, list)):
        s = json.dumps(value, default=str)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return value
    return value


def collect_all_keys_recursive(obj: Any, prefix: str = "") -> Set[str]:
    """Collect all key paths from a nested JSON object."""
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else k
            keys.add(full)
            keys.update(collect_all_keys_recursive(v, full))
    elif isinstance(obj, list) and obj:
        # Just inspect first element for schema discovery
        keys.update(collect_all_keys_recursive(obj[0], f"{prefix}[]"))
    return keys


def unwrap_updates_response(resp: Dict) -> Dict:
    """Extract the update/transaction body from /v2/updates/{id} response."""
    if "transaction" in resp:
        return resp["transaction"]
    if "update" in resp:
        return resp["update"]
    return resp


def unwrap_events_response(resp: Dict) -> Tuple[Dict, Optional[Dict]]:
    """
    Extract the update body and verdict from /v0/events/{id} response.
    Returns (update_body, verdict_or_None).
    """
    verdict = resp.get("verdict")
    if "event" in resp:
        return resp["event"], verdict
    if "update" in resp:
        return resp["update"], verdict
    return resp, verdict


def fetch_updates_page(client, cursor_migration_id, cursor_record_time, page_size):
    """Fetch one page from /v2/updates."""
    resp = client.get_updates(
        after_migration_id=cursor_migration_id,
        after_record_time=cursor_record_time,
        page_size=page_size,
    )
    txns = resp.get("updates", resp.get("transactions", []))
    after = resp.get("after")
    return txns, after


def fetch_events_page(client, cursor_migration_id, cursor_record_time, page_size):
    """Fetch one page from /v0/events."""
    resp = client.get_events(
        after_migration_id=cursor_migration_id,
        after_record_time=cursor_record_time,
        page_size=page_size,
    )
    raw = resp.get("events", [])
    # Unwrap: events endpoint wraps each item in {"update": {...}, "verdict": {...}}
    items = []
    for wrapper in raw:
        update = wrapper.get("update", wrapper)
        verdict = wrapper.get("verdict")
        items.append({"update": update, "verdict": verdict})
    after = resp.get("after")
    return items, after


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 1: Schema & Field-Level Deep Diff
# ═══════════════════════════════════════════════════════════════════════════════

def phase1_schema_and_field_diff(
    client: SpliceScanClient,
    sample_size: int = 50,
    migration_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Fetch a sample of update_ids from both endpoints, do recursive deep diff.
    """
    banner("PHASE 1: Schema & Field-Level Deep Diff")
    print(f"  Sampling {sample_size} updates from different time periods...")

    results = {
        "sample_size_requested": sample_size,
        "sample_size_actual": 0,
        "updates_compared": 0,
        "updates_identical": 0,
        "updates_with_diffs": 0,
        "all_diffs": [],
        "top_level_keys_updates": set(),
        "top_level_keys_events": set(),
        "event_level_keys_updates": set(),
        "event_level_keys_events": set(),
        "verdict_keys": set(),
        "verdict_samples": [],
        "diff_summary": Counter(),
    }

    # Collect update_ids by paginating through /v2/updates
    # Sample from beginning, middle, and recent data
    update_ids = _collect_sample_update_ids(client, sample_size, migration_ids=migration_ids)
    results["sample_size_actual"] = len(update_ids)

    print(f"  Collected {len(update_ids)} update_ids to compare.\n")

    for i, uid in enumerate(update_ids):
        print(f"  [{i+1}/{len(update_ids)}] Comparing {uid[:32]}...", end=" ", flush=True)

        try:
            updates_resp = client.get_update_by_id(uid)
            time.sleep(REQUEST_DELAY)
            events_resp = client.get_event_by_id(uid)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        # Track top-level response keys
        results["top_level_keys_updates"].update(updates_resp.keys())
        results["top_level_keys_events"].update(events_resp.keys())

        # Unwrap
        u_body = unwrap_updates_response(updates_resp)
        e_body, verdict = unwrap_events_response(events_resp)

        # Track verdict keys
        if verdict is not None:
            results["verdict_keys"].update(collect_all_keys_recursive(verdict))
            if len(results["verdict_samples"]) < 3:
                results["verdict_samples"].append({
                    "update_id": uid,
                    "verdict": verdict,
                })
        elif "verdict" in events_resp:
            # verdict key exists but is None/empty
            if len(results["verdict_samples"]) < 1:
                results["verdict_samples"].append({
                    "update_id": uid,
                    "verdict_raw": events_resp.get("verdict"),
                    "note": "verdict key present but value is None/empty",
                })

        # Track event-level keys from events_by_id
        for eid, edetails in u_body.get("events_by_id", {}).items():
            results["event_level_keys_updates"].update(edetails.keys())
        for eid, edetails in e_body.get("events_by_id", {}).items():
            results["event_level_keys_events"].update(edetails.keys())

        # Deep diff the unwrapped update bodies
        diffs = deep_diff(u_body, e_body)
        results["updates_compared"] += 1

        if not diffs:
            results["updates_identical"] += 1
            print("IDENTICAL")
        else:
            results["updates_with_diffs"] += 1
            for d in diffs:
                results["diff_summary"][d["path"]] += 1
            results["all_diffs"].append({
                "update_id": uid,
                "num_diffs": len(diffs),
                "diffs": diffs,
            })
            print(f"{len(diffs)} difference(s)")

    # Print summary
    _print_phase1_summary(results)
    return results


def _discover_migration_range(
    client: SpliceScanClient,
    migration_id: int,
) -> List[Dict]:
    """
    Discover the data range for a single migration_id by paginating until exhaustion.
    Returns a list of cursor checkpoints for this migration.
    """
    checkpoints = []
    total_updates = 0
    checkpoint_interval = 5

    cursor_mig = migration_id
    cursor_rt = "2000-01-01T00:00:00Z"

    page_num = 0
    while True:
        txns, after = fetch_updates_page(client, cursor_mig, cursor_rt, 500)
        if not txns:
            break

        # Stop if we've crossed into a different migration
        first_mig = txns[0].get("migration_id")
        if first_mig != migration_id:
            break

        total_updates += len(txns)
        page_num += 1

        if page_num % checkpoint_interval == 1 or page_num == 1:
            first = txns[0]
            checkpoints.append({
                "migration_id": first.get("migration_id"),
                "record_time": first.get("record_time"),
                "page": page_num,
                "total_so_far": total_updates,
            })

        if not after:
            break
        next_mig = after.get("after_migration_id")
        # Stop if cursor advances past our target migration
        if next_mig != migration_id:
            break
        cursor_mig = next_mig
        cursor_rt = after.get("after_record_time")
        time.sleep(0.05)

        if page_num % 20 == 0:
            print(f"      ... {page_num} pages, ~{total_updates} updates, "
                  f"at {cursor_rt}", flush=True)

    # Save last checkpoint
    if txns and txns[-1].get("migration_id") == migration_id:
        last = txns[-1]
        checkpoints.append({
            "migration_id": last.get("migration_id"),
            "record_time": last.get("record_time"),
            "page": page_num,
            "total_so_far": total_updates,
        })

    return checkpoints, total_updates


def _discover_all_migrations(
    client: SpliceScanClient,
    migration_ids: List[int],
) -> Dict[int, List[Dict]]:
    """
    Discover data ranges for all specified migration_ids.
    Returns {migration_id: [checkpoints]}.
    """
    print(f"  Discovering data across migration_ids: {migration_ids}")
    all_checkpoints = {}

    for mig_id in migration_ids:
        print(f"    Migration {mig_id}...", end=" ", flush=True)
        checkpoints, total = _discover_migration_range(client, mig_id)
        all_checkpoints[mig_id] = checkpoints
        if checkpoints:
            print(f"{total} updates, "
                  f"{checkpoints[0]['record_time']} .. {checkpoints[-1]['record_time']}")
        else:
            print("no data")

    non_empty = {k: v for k, v in all_checkpoints.items() if v}
    print(f"  Migrations with data: {sorted(non_empty.keys())}")
    total_all = sum(cp[-1]["total_so_far"] for cp in non_empty.values())
    print(f"  Total updates across all migrations: ~{total_all}")

    return all_checkpoints


def _collect_sample_update_ids(
    client: SpliceScanClient,
    target_count: int,
    migration_ids: Optional[List[int]] = None,
) -> List[str]:
    """
    Collect update_ids sampled evenly across all migration_ids.
    Distributes the sample budget proportionally by data volume.
    """
    if migration_ids is None:
        migration_ids = [0, 1, 2, 3, 4]

    all_checkpoints = _discover_all_migrations(client, migration_ids)

    # Determine per-migration sample counts proportional to data volume
    volumes = {}
    for mig_id, cps in all_checkpoints.items():
        if cps:
            volumes[mig_id] = cps[-1]["total_so_far"]
    total_volume = sum(volumes.values())

    if total_volume == 0:
        print("  WARNING: No data found across any migration!")
        return []

    ids = []
    for mig_id in sorted(volumes.keys()):
        cps = all_checkpoints[mig_id]
        # Proportional allocation, minimum 3 per migration
        proportion = volumes[mig_id] / total_volume
        n_samples = max(3, int(target_count * proportion))

        num_cp = len(cps)
        # Pick up to 3 evenly-spaced checkpoints within this migration
        if num_cp >= 3:
            cp_indices = [0, num_cp // 2, num_cp - 1]
        elif num_cp == 2:
            cp_indices = [0, 1]
        else:
            cp_indices = [0]

        samples_per_cp = max(1, n_samples // len(cp_indices))

        for cp_idx in cp_indices:
            cp = cps[cp_idx]
            print(f"  Sampling {samples_per_cp} from migration {mig_id} "
                  f"at {cp['record_time'][:19]}...")

            if cp_idx == 0:
                # Start from beginning of this migration
                txns, _ = fetch_updates_page(
                    client, mig_id, "2000-01-01T00:00:00Z", samples_per_cp
                )
            else:
                prev_cp = cps[cp_idx - 1]
                txns, _ = fetch_updates_page(
                    client, prev_cp["migration_id"], prev_cp["record_time"], samples_per_cp
                )

            # Only take updates from the target migration
            for t in txns:
                if t.get("migration_id") == mig_id and "update_id" in t:
                    ids.append(t["update_id"])
            time.sleep(REQUEST_DELAY)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            unique.append(uid)
    return unique[:target_count]


def _print_phase1_summary(results: Dict):
    sub_banner("Phase 1 Summary")

    print(f"\n  Updates compared:    {results['updates_compared']}")
    print(f"  Identical:           {results['updates_identical']}")
    print(f"  With differences:    {results['updates_with_diffs']}")

    print(f"\n  Top-level response keys:")
    print(f"    /v2/updates: {sorted(results['top_level_keys_updates'])}")
    print(f"    /v0/events:  {sorted(results['top_level_keys_events'])}")

    only_updates = results["top_level_keys_updates"] - results["top_level_keys_events"]
    only_events = results["top_level_keys_events"] - results["top_level_keys_updates"]
    if only_updates:
        print(f"    ONLY in /v2/updates: {sorted(only_updates)}")
    if only_events:
        print(f"    ONLY in /v0/events:  {sorted(only_events)}")

    print(f"\n  Event-level keys (inside events_by_id):")
    print(f"    /v2/updates: {sorted(results['event_level_keys_updates'])}")
    print(f"    /v0/events:  {sorted(results['event_level_keys_events'])}")

    only_u_event = results["event_level_keys_updates"] - results["event_level_keys_events"]
    only_e_event = results["event_level_keys_events"] - results["event_level_keys_updates"]
    if only_u_event:
        print(f"    ONLY in /v2/updates events: {sorted(only_u_event)}")
    if only_e_event:
        print(f"    ONLY in /v0/events events:  {sorted(only_e_event)}")

    if results["verdict_keys"]:
        print(f"\n  Verdict field (ONLY in /v0/events):")
        print(f"    All key paths: {sorted(results['verdict_keys'])}")

    if results["diff_summary"]:
        print(f"\n  Most frequent diff paths (across all compared updates):")
        for path, count in results["diff_summary"].most_common(20):
            print(f"    {path}: {count} occurrence(s)")

    if results["all_diffs"]:
        print(f"\n  First 3 updates with differences:")
        for item in results["all_diffs"][:3]:
            print(f"\n    update_id: {item['update_id']}")
            for d in item["diffs"][:10]:
                print(f"      {d['type']:20s} at {d['path']}")
                if "a_value" in d:
                    print(f"        /v2/updates: {d['a_value']}")
                if "b_value" in d:
                    print(f"        /v0/events:  {d['b_value']}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 2: Transaction Coverage (Set Comparison Over Large Windows)
# ═══════════════════════════════════════════════════════════════════════════════

def phase2_transaction_coverage(
    client: SpliceScanClient,
    num_windows: int = 3,
    window_pages: int = 10,
    page_size: int = 100,
    migration_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Fetch large windows from both endpoints using identical cursors, compare sets.
    Places one window per migration_id to cover all migrations.
    """
    banner("PHASE 2: Transaction Coverage (Set Comparison)")
    print(f"  {num_windows} window(s), {window_pages} pages each, page_size={page_size}")

    results = {
        "windows": [],
        "total_updates_only": 0,
        "total_events_only": 0,
        "total_in_both": 0,
        "ordering_mismatches": 0,
    }

    if migration_ids is None:
        migration_ids = [0, 1, 2, 3, 4]

    # Discover data for all migrations, then pick windows across them
    all_checkpoints = _discover_all_migrations(client, migration_ids)

    # Build a flat list of window start cursors spread across all migrations
    window_starts = []
    non_empty_migs = sorted(mig for mig, cps in all_checkpoints.items() if cps)

    if not non_empty_migs:
        print("  No data found. Cannot run Phase 2.")
        return results

    # Distribute windows across migrations: at least 1 per migration, extras go to larger ones
    windows_per_mig = max(1, num_windows // len(non_empty_migs))
    for mig_id in non_empty_migs:
        cps = all_checkpoints[mig_id]
        num_cp = len(cps)
        n_wins = min(windows_per_mig, num_cp)
        if num_cp == 1:
            window_starts.append(cps[0])
        else:
            step = max(1, (num_cp - 1) // max(n_wins - 1, 1))
            for j in range(n_wins):
                window_starts.append(cps[min(j * step, num_cp - 1)])

    # Cap to requested number
    window_starts = window_starts[:num_windows]

    for win_idx, start_cp in enumerate(window_starts):
        banner(f"Window {win_idx + 1}/{len(window_starts)} "
               f"(migration {start_cp['migration_id']})", char="·")

        cursor_mig = start_cp["migration_id"]
        cursor_rt = start_cp["record_time"]
        # For the very first checkpoint of a migration, use a sentinel
        if start_cp == all_checkpoints[cursor_mig][0]:
            cursor_rt = "2000-01-01T00:00:00Z"

        print(f"  Starting from record_time={cursor_rt or 'beginning'}")

        # ── Fetch from /v2/updates ──
        print(f"  Fetching /v2/updates ({window_pages} pages)...")
        u_ids_ordered = []
        u_data = {}  # update_id → record_time
        u_cursor_mig = cursor_mig
        u_cursor_rt = cursor_rt

        for p in range(window_pages):
            txns, after = fetch_updates_page(client, u_cursor_mig, u_cursor_rt, page_size)
            print(f"    Page {p+1}: {len(txns)} updates", flush=True)
            if not txns:
                break
            for t in txns:
                uid = t.get("update_id")
                if uid and uid not in u_data:
                    u_ids_ordered.append(uid)
                    u_data[uid] = t.get("record_time")
            if after:
                u_cursor_mig = after.get("after_migration_id")
                u_cursor_rt = after.get("after_record_time")
            else:
                break
            time.sleep(0.1)

        # ── Fetch from /v0/events using the SAME starting cursor ──
        print(f"  Fetching /v0/events ({window_pages} pages, same cursor)...")
        e_ids_ordered = []
        e_data = {}
        e_cursor_mig = cursor_mig
        e_cursor_rt = cursor_rt

        for p in range(window_pages):
            items, after = fetch_events_page(client, e_cursor_mig, e_cursor_rt, page_size)
            print(f"    Page {p+1}: {len(items)} events", flush=True)
            if not items:
                break
            for item in items:
                update = item["update"]
                uid = update.get("update_id")
                if uid and uid not in e_data:
                    e_ids_ordered.append(uid)
                    e_data[uid] = update.get("record_time")
            if after:
                e_cursor_mig = after.get("after_migration_id")
                e_cursor_rt = after.get("after_record_time")
            else:
                break
            time.sleep(0.1)

        # ── Compare sets ──
        u_set = set(u_data.keys())
        e_set = set(e_data.keys())
        in_both = u_set & e_set
        only_u = u_set - e_set
        only_e = e_set - u_set

        # ── Compare ordering ──
        common_ordered_u = [uid for uid in u_ids_ordered if uid in in_both]
        common_ordered_e = [uid for uid in e_ids_ordered if uid in in_both]
        ordering_match = common_ordered_u == common_ordered_e

        win_result = {
            "window": win_idx + 1,
            "start_cursor": {"migration_id": cursor_mig, "record_time": cursor_rt},
            "updates_count": len(u_set),
            "events_count": len(e_set),
            "in_both": len(in_both),
            "only_in_updates": len(only_u),
            "only_in_events": len(only_e),
            "ordering_match": ordering_match,
            "only_in_updates_ids": sorted(only_u)[:10],
            "only_in_events_ids": sorted(only_e)[:10],
            "updates_time_range": (min(u_data.values()) if u_data else None,
                                   max(u_data.values()) if u_data else None),
            "events_time_range": (min(e_data.values()) if e_data else None,
                                  max(e_data.values()) if e_data else None),
        }
        results["windows"].append(win_result)
        results["total_in_both"] += len(in_both)
        results["total_updates_only"] += len(only_u)
        results["total_events_only"] += len(only_e)
        if not ordering_match:
            results["ordering_mismatches"] += 1

        print(f"\n  Window {win_idx+1} results:")
        print(f"    /v2/updates:  {len(u_set)} unique update_ids")
        print(f"    /v0/events:   {len(e_set)} unique update_ids")
        print(f"    In both:      {len(in_both)}")
        print(f"    Only updates: {len(only_u)}")
        print(f"    Only events:  {len(only_e)}")
        print(f"    Ordering:     {'MATCH' if ordering_match else 'MISMATCH'}")
        if u_data:
            print(f"    Updates time:  {min(u_data.values())} .. {max(u_data.values())}")
        if e_data:
            print(f"    Events time:   {min(e_data.values())} .. {max(e_data.values())}")

    # Overall summary
    _print_phase2_summary(results)
    return results


def _print_phase2_summary(results: Dict):
    sub_banner("Phase 2 Summary")
    print(f"\n  Total across all windows:")
    print(f"    In both endpoints:        {results['total_in_both']}")
    print(f"    Only in /v2/updates:      {results['total_updates_only']}")
    print(f"    Only in /v0/events:       {results['total_events_only']}")
    print(f"    Ordering mismatches:      {results['ordering_mismatches']}")

    if results["total_updates_only"] == 0 and results["total_events_only"] == 0:
        print("\n    CONCLUSION: Both endpoints return the SAME set of transactions.")
    elif results["total_updates_only"] > 0:
        print(f"\n    WARNING: {results['total_updates_only']} transactions found ONLY in /v2/updates!")
    elif results["total_events_only"] > 0:
        print(f"\n    NOTE: {results['total_events_only']} transactions found only in /v0/events "
              "(likely pagination boundary artifact).")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 3: Event Type Coverage
# ═══════════════════════════════════════════════════════════════════════════════

def phase3_event_type_coverage(
    client: SpliceScanClient,
    sample_size: int = 50,
    migration_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Find examples of each event type and verify both endpoints handle them identically.
    Focus on: created, exercised (consuming/non-consuming), and reassignment events.
    """
    banner("PHASE 3: Event Type Coverage")
    print(f"  Looking for diverse event types across {sample_size} updates...")

    results = {
        "event_types_found": Counter(),
        "consuming_exercises_found": 0,
        "non_consuming_exercises_found": 0,
        "reassignment_events_found": 0,
        "created_events_checked": 0,
        "exercised_events_checked": 0,
        "created_diffs": [],
        "exercised_diffs": [],
        "reassignment_diffs": [],
        "samples_by_type": defaultdict(list),
    }

    # Collect a diverse sample
    print("  Collecting updates sample for event type analysis...")
    update_ids = _collect_sample_update_ids(client, sample_size, migration_ids=migration_ids)

    for i, uid in enumerate(update_ids):
        print(f"  [{i+1}/{len(update_ids)}] Checking {uid[:32]}...", end=" ", flush=True)

        try:
            u_resp = client.get_update_by_id(uid)
            time.sleep(REQUEST_DELAY)
            e_resp = client.get_event_by_id(uid)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        u_body = unwrap_updates_response(u_resp)
        e_body, _ = unwrap_events_response(e_resp)

        u_events = u_body.get("events_by_id", {})
        e_events = e_body.get("events_by_id", {})

        found_types = set()

        for eid, u_evt in u_events.items():
            e_evt = e_events.get(eid)
            if not e_evt:
                continue

            evt_type = u_evt.get("event_type", "unknown")
            results["event_types_found"][evt_type] += 1
            found_types.add(evt_type)

            # Track consuming vs non-consuming
            if evt_type == "exercised_event":
                results["exercised_events_checked"] += 1
                if u_evt.get("consuming"):
                    results["consuming_exercises_found"] += 1
                else:
                    results["non_consuming_exercises_found"] += 1

                # Compare exercised-specific fields
                for field in ["choice", "choice_argument", "exercise_result",
                              "acting_parties", "consuming", "child_event_ids"]:
                    if u_evt.get(field) != e_evt.get(field):
                        results["exercised_diffs"].append({
                            "update_id": uid,
                            "event_id": eid,
                            "field": field,
                            "updates_value": _truncate(u_evt.get(field)),
                            "events_value": _truncate(e_evt.get(field)),
                        })

            elif evt_type == "created_event":
                results["created_events_checked"] += 1

                # Compare created-specific fields
                for field in ["create_arguments", "signatories", "observers", "created_at"]:
                    if u_evt.get(field) != e_evt.get(field):
                        results["created_diffs"].append({
                            "update_id": uid,
                            "event_id": eid,
                            "field": field,
                            "updates_value": _truncate(u_evt.get(field)),
                            "events_value": _truncate(e_evt.get(field)),
                        })

            # Check for reassignment indicators
            if (u_evt.get("reassignment_counter") and u_evt["reassignment_counter"] > 0) or \
               u_evt.get("source_synchronizer") or u_evt.get("target_synchronizer") or \
               u_evt.get("unassign_id"):
                results["reassignment_events_found"] += 1
                diffs = deep_diff(u_evt, e_evt)
                if diffs:
                    results["reassignment_diffs"].append({
                        "update_id": uid,
                        "event_id": eid,
                        "diffs": diffs,
                    })

            # Track samples (max 3 per type)
            if len(results["samples_by_type"][evt_type]) < 3:
                results["samples_by_type"][evt_type].append({
                    "update_id": uid,
                    "event_id": eid,
                    "template_id": u_evt.get("template_id"),
                    "choice": u_evt.get("choice"),
                })

        print(f"types: {sorted(found_types)}")

    _print_phase3_summary(results)
    return results


def _print_phase3_summary(results: Dict):
    sub_banner("Phase 3 Summary")

    print(f"\n  Event types found:")
    for et, count in results["event_types_found"].most_common():
        print(f"    {et}: {count}")

    print(f"\n  Exercised events: {results['exercised_events_checked']} total")
    print(f"    Consuming:     {results['consuming_exercises_found']}")
    print(f"    Non-consuming: {results['non_consuming_exercises_found']}")

    print(f"\n  Created events checked: {results['created_events_checked']}")
    print(f"  Reassignment events found: {results['reassignment_events_found']}")

    if results["created_diffs"]:
        print(f"\n  CREATED EVENT DIFFS: {len(results['created_diffs'])} field difference(s)!")
        for d in results["created_diffs"][:5]:
            print(f"    {d['event_id']}: {d['field']}")
            print(f"      updates: {d['updates_value']}")
            print(f"      events:  {d['events_value']}")
    else:
        print(f"\n  Created events: ALL IDENTICAL between endpoints")

    if results["exercised_diffs"]:
        print(f"\n  EXERCISED EVENT DIFFS: {len(results['exercised_diffs'])} field difference(s)!")
        for d in results["exercised_diffs"][:5]:
            print(f"    {d['event_id']}: {d['field']}")
            print(f"      updates: {d['updates_value']}")
            print(f"      events:  {d['events_value']}")
    else:
        print(f"\n  Exercised events: ALL IDENTICAL between endpoints")

    if results["reassignment_diffs"]:
        print(f"\n  REASSIGNMENT EVENT DIFFS: {len(results['reassignment_diffs'])} update(s) with diffs!")
        for d in results["reassignment_diffs"][:3]:
            print(f"    update_id: {d['update_id']}")
            for diff in d["diffs"][:5]:
                print(f"      {diff['type']} at {diff['path']}")
    elif results["reassignment_events_found"] > 0:
        print(f"\n  Reassignment events: ALL IDENTICAL between endpoints")
    else:
        print(f"\n  Reassignment events: NONE found in sample — may need larger sample")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 4: Template & Choice Coverage
# ═══════════════════════════════════════════════════════════════════════════════

def phase4_template_choice_coverage(
    client: SpliceScanClient,
    page_size: int = 200,
    num_pages: int = 20,
    migration_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Collect all unique (template_id, choice) pairs from both endpoints.
    For each unique template, do a spot-check deep diff.
    """
    banner("PHASE 4: Template & Choice Coverage")
    print(f"  Scanning {num_pages} pages (page_size={page_size}) for template/choice inventory...")

    results = {
        "templates_updates": Counter(),
        "templates_events": Counter(),
        "choices_updates": Counter(),
        "choices_events": Counter(),
        "template_choice_pairs_updates": set(),
        "template_choice_pairs_events": set(),
        "only_in_updates_pairs": set(),
        "only_in_events_pairs": set(),
        "spot_check_results": [],
    }

    if migration_ids is None:
        migration_ids = [0, 1, 2, 3, 4]

    pages_per_migration = max(1, num_pages // len(migration_ids))
    template_to_update_id = {}  # template_id → first update_id seen

    # ── Collect from /v2/updates ──
    print(f"\n  Collecting template/choice pairs from /v2/updates "
          f"({pages_per_migration} pages per migration)...")
    for mig_id in migration_ids:
        u_cursor_mig = mig_id
        u_cursor_rt = "2000-01-01T00:00:00Z"
        for p in range(pages_per_migration):
            txns, after = fetch_updates_page(client, u_cursor_mig, u_cursor_rt, page_size)
            if not txns:
                break
            print(f"    Migration {mig_id}, page {p+1}: {len(txns)} updates", flush=True)
            for t in txns:
                if t.get("migration_id") != mig_id:
                    break
                uid = t.get("update_id")
                for eid, evt in t.get("events_by_id", {}).items():
                    tid = evt.get("template_id", "unknown")
                    choice = evt.get("choice")
                    results["templates_updates"][tid] += 1
                    if choice:
                        results["choices_updates"][choice] += 1
                        pair = (tid, choice)
                    else:
                        pair = (tid, "__created__" if "create_arguments" in evt else "__other__")
                    results["template_choice_pairs_updates"].add(pair)
                    if tid not in template_to_update_id:
                        template_to_update_id[tid] = uid
            if after:
                if after.get("after_migration_id") != mig_id:
                    break  # Crossed into next migration
                u_cursor_mig = after.get("after_migration_id")
                u_cursor_rt = after.get("after_record_time")
            else:
                break
            time.sleep(0.05)

    # ── Collect from /v0/events (same migrations) ──
    print(f"\n  Collecting template/choice pairs from /v0/events "
          f"({pages_per_migration} pages per migration)...")
    for mig_id in migration_ids:
        e_cursor_mig = mig_id
        e_cursor_rt = "2000-01-01T00:00:00Z"

        for p in range(pages_per_migration):
            items, after = fetch_events_page(client, e_cursor_mig, e_cursor_rt, page_size)
            if not items:
                break
            print(f"    Migration {mig_id}, page {p+1}: {len(items)} events", flush=True)
            for item in items:
                update = item["update"]
                if update.get("migration_id") != mig_id:
                    break
                for eid, evt in update.get("events_by_id", {}).items():
                    tid = evt.get("template_id", "unknown")
                    choice = evt.get("choice")
                    results["templates_events"][tid] += 1
                    if choice:
                        results["choices_events"][choice] += 1
                        pair = (tid, choice)
                    else:
                        pair = (tid, "__created__" if "create_arguments" in evt else "__other__")
                    results["template_choice_pairs_events"].add(pair)
            if after:
                if after.get("after_migration_id") != mig_id:
                    break
                e_cursor_mig = after.get("after_migration_id")
                e_cursor_rt = after.get("after_record_time")
            else:
                break
            time.sleep(0.05)

    # ── Compare ──
    results["only_in_updates_pairs"] = (
        results["template_choice_pairs_updates"] - results["template_choice_pairs_events"]
    )
    results["only_in_events_pairs"] = (
        results["template_choice_pairs_events"] - results["template_choice_pairs_updates"]
    )

    # ── Spot-check: for each unique template, deep-diff one representative ──
    print(f"\n  Spot-checking one update per unique template...")
    unique_templates = sorted(set(results["templates_updates"].keys()) |
                               set(results["templates_events"].keys()))
    checked = 0
    for tid in unique_templates:
        uid = template_to_update_id.get(tid)
        if not uid:
            continue
        if checked >= 30:  # Cap spot checks
            break

        print(f"    [{checked+1}] {tid[:60]}...", end=" ", flush=True)
        try:
            u_resp = client.get_update_by_id(uid)
            time.sleep(REQUEST_DELAY)
            e_resp = client.get_event_by_id(uid)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        u_body = unwrap_updates_response(u_resp)
        e_body, _ = unwrap_events_response(e_resp)
        diffs = deep_diff(u_body, e_body)

        result = {
            "template_id": tid,
            "update_id": uid,
            "identical": len(diffs) == 0,
            "num_diffs": len(diffs),
            "diff_paths": [d["path"] for d in diffs[:5]],
        }
        results["spot_check_results"].append(result)
        checked += 1

        if diffs:
            print(f"{len(diffs)} diff(s)")
        else:
            print("IDENTICAL")

    _print_phase4_summary(results)
    return results


def _print_phase4_summary(results: Dict):
    sub_banner("Phase 4 Summary")

    print(f"\n  Unique templates in /v2/updates: {len(results['templates_updates'])}")
    print(f"  Unique templates in /v0/events:  {len(results['templates_events'])}")
    print(f"\n  Unique (template, choice) pairs:")
    print(f"    /v2/updates: {len(results['template_choice_pairs_updates'])}")
    print(f"    /v0/events:  {len(results['template_choice_pairs_events'])}")

    if results["only_in_updates_pairs"]:
        print(f"\n  Pairs ONLY in /v2/updates ({len(results['only_in_updates_pairs'])}):")
        for tid, ch in sorted(results["only_in_updates_pairs"]):
            print(f"    {tid} / {ch}")
    if results["only_in_events_pairs"]:
        print(f"\n  Pairs ONLY in /v0/events ({len(results['only_in_events_pairs'])}):")
        for tid, ch in sorted(results["only_in_events_pairs"]):
            print(f"    {tid} / {ch}")

    if not results["only_in_updates_pairs"] and not results["only_in_events_pairs"]:
        print(f"\n  SAME template/choice coverage in both endpoints.")

    # Top templates
    print(f"\n  Top 15 templates by frequency (/v2/updates):")
    for tid, count in results["templates_updates"].most_common(15):
        short_tid = tid.split(":")[-1] if ":" in tid else tid
        print(f"    {short_tid:50s} {count:>6}")

    # Spot check summary
    spot_ok = sum(1 for r in results["spot_check_results"] if r["identical"])
    spot_diff = sum(1 for r in results["spot_check_results"] if not r["identical"])
    print(f"\n  Spot-check results: {spot_ok} identical, {spot_diff} with differences")
    if spot_diff:
        for r in results["spot_check_results"]:
            if not r["identical"]:
                print(f"    {r['template_id']}: {r['num_diffs']} diff(s) at {r['diff_paths']}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 5: Summary Report
# ═══════════════════════════════════════════════════════════════════════════════

def phase5_summary_report(
    phase1_results: Optional[Dict],
    phase2_results: Optional[Dict],
    phase3_results: Optional[Dict],
    phase4_results: Optional[Dict],
) -> Dict[str, Any]:
    """Aggregate findings into a decision report."""
    banner("PHASE 5: FINAL SUMMARY REPORT", char="█")

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "findings": [],
        "verdict_assessment": None,
        "recommendation": None,
    }

    # ── Field inventory ──
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│  1. FIELD INVENTORY                                        │")
    print("└─────────────────────────────────────────────────────────────┘")

    if phase1_results:
        print(f"\n  Response-level keys only in /v2/updates: "
              f"{sorted(phase1_results['top_level_keys_updates'] - phase1_results['top_level_keys_events'])}")
        print(f"  Response-level keys only in /v0/events:  "
              f"{sorted(phase1_results['top_level_keys_events'] - phase1_results['top_level_keys_updates'])}")

        print(f"\n  Event-level keys only in /v2/updates: "
              f"{sorted(phase1_results['event_level_keys_updates'] - phase1_results['event_level_keys_events'])}")
        print(f"  Event-level keys only in /v0/events:  "
              f"{sorted(phase1_results['event_level_keys_events'] - phase1_results['event_level_keys_updates'])}")

        if phase1_results["verdict_keys"]:
            print(f"\n  Verdict field (exclusive to /v0/events):")
            for key in sorted(phase1_results["verdict_keys"]):
                print(f"    - {key}")

            report["verdict_assessment"] = {
                "present_in": "/v0/events only",
                "key_paths": sorted(phase1_results["verdict_keys"]),
                "contains_unique_data": True,
                "fields": [
                    "finalization_time",
                    "submitting_parties",
                    "submitting_participant_uid",
                    "verdict_result (ACCEPTED/REJECTED)",
                    "mediator_group",
                    "transaction_views (informees, confirming_parties)",
                ],
            }
    else:
        print("  (Phase 1 not run)")

    # ── Coverage ──
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│  2. TRANSACTION COVERAGE                                    │")
    print("└─────────────────────────────────────────────────────────────┘")

    if phase2_results:
        print(f"\n  Total transactions in both:    {phase2_results['total_in_both']}")
        print(f"  Only in /v2/updates:           {phase2_results['total_updates_only']}")
        print(f"  Only in /v0/events:            {phase2_results['total_events_only']}")
        print(f"  Ordering matches:              "
              f"{len(phase2_results['windows']) - phase2_results['ordering_mismatches']}/{len(phase2_results['windows'])}")

        if phase2_results["total_updates_only"] == 0:
            report["findings"].append(
                "COVERAGE: /v0/events contains ALL transactions found in /v2/updates."
            )
        else:
            report["findings"].append(
                f"COVERAGE WARNING: {phase2_results['total_updates_only']} transactions "
                "found ONLY in /v2/updates — potential data gap!"
            )
    else:
        print("  (Phase 2 not run)")

    # ── Value equality ──
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│  3. VALUE EQUALITY                                          │")
    print("└─────────────────────────────────────────────────────────────┘")

    total_diffs = 0
    if phase1_results:
        total_diffs += phase1_results["updates_with_diffs"]
        print(f"\n  Phase 1 deep diff: {phase1_results['updates_identical']}/{phase1_results['updates_compared']} identical")
        if phase1_results["diff_summary"]:
            print(f"  Diff paths found:")
            for path, count in phase1_results["diff_summary"].most_common(10):
                print(f"    {path}: {count}x")

    if phase3_results:
        created_diff_count = len(phase3_results.get("created_diffs", []))
        exercised_diff_count = len(phase3_results.get("exercised_diffs", []))
        reassign_diff_count = len(phase3_results.get("reassignment_diffs", []))
        total_diffs += created_diff_count + exercised_diff_count + reassign_diff_count

        print(f"\n  Phase 3 event type checks:")
        print(f"    Created events:      {'IDENTICAL' if created_diff_count == 0 else f'{created_diff_count} DIFFS'}")
        print(f"    Exercised events:    {'IDENTICAL' if exercised_diff_count == 0 else f'{exercised_diff_count} DIFFS'}")
        print(f"    Reassignment events: {'IDENTICAL' if reassign_diff_count == 0 else f'{reassign_diff_count} DIFFS'}"
              f" ({phase3_results.get('reassignment_events_found', 0)} found)")

    if total_diffs == 0:
        report["findings"].append(
            "VALUE EQUALITY: Update bodies are IDENTICAL between both endpoints."
        )
    else:
        report["findings"].append(
            f"VALUE DIFFERENCES: Found {total_diffs} update(s) with field-level differences."
        )

    # ── Template coverage ──
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│  4. TEMPLATE & CHOICE COVERAGE                              │")
    print("└─────────────────────────────────────────────────────────────┘")

    if phase4_results:
        only_u = phase4_results.get("only_in_updates_pairs", set())
        only_e = phase4_results.get("only_in_events_pairs", set())
        print(f"\n  Template/choice pairs only in /v2/updates: {len(only_u)}")
        print(f"  Template/choice pairs only in /v0/events:  {len(only_e)}")

        spot_ok = sum(1 for r in phase4_results.get("spot_check_results", []) if r["identical"])
        spot_total = len(phase4_results.get("spot_check_results", []))
        print(f"  Spot-check: {spot_ok}/{spot_total} templates identical")

        if not only_u and not only_e:
            report["findings"].append(
                "TEMPLATE COVERAGE: Same template/choice pairs in both endpoints."
            )
    else:
        print("  (Phase 4 not run)")

    # ── Verdict assessment ──
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│  5. VERDICT FIELD ASSESSMENT                                │")
    print("└─────────────────────────────────────────────────────────────┘")

    if phase1_results and phase1_results.get("verdict_keys"):
        print("\n  The 'verdict' field is ONLY present in /v0/events responses.")
        print("  It contains:")
        print("    - finalization_time:           When the transaction was finalized")
        print("    - submitting_parties:          Who submitted the transaction")
        print("    - submitting_participant_uid:  Which participant node submitted")
        print("    - verdict_result:              ACCEPTED/REJECTED")
        print("    - mediator_group:              Which mediator group processed it")
        print("    - transaction_views:           View decomposition (informees, confirming parties)")
        print("\n  This is EXTRA data in /v0/events that /v2/updates does NOT provide.")

        report["findings"].append(
            "VERDICT FIELD: /v0/events provides a 'verdict' field with finalization metadata "
            "that /v2/updates does not return."
        )
    elif phase1_results and phase1_results.get("verdict_samples"):
        # Verdict key exists but value was null/empty for all samples
        sample = phase1_results["verdict_samples"][0]
        print(f"\n  The 'verdict' key exists in /v0/events responses but was null/empty.")
        print(f"  Sample: {sample}")
        report["findings"].append(
            "VERDICT FIELD: Present in /v0/events response structure but null/empty for sampled data."
        )
    elif phase1_results:
        has_verdict_key = "verdict" in phase1_results.get("top_level_keys_events", set())
        if has_verdict_key:
            print(f"\n  The 'verdict' key is in /v0/events response but was None for all {phase1_results['updates_compared']} samples.")
            print("  This may be because verdict data is only available for more recent transactions,")
            print("  or it requires specific API permissions.")
            report["findings"].append(
                "VERDICT FIELD: Key present in /v0/events but value was None for all sampled transactions."
            )
        else:
            print("  (No verdict data collected)")
    else:
        print("  (Phase 1 not run)")

    # ── Final recommendation ──
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│  6. RECOMMENDATION                                          │")
    print("└─────────────────────────────────────────────────────────────┘")

    has_coverage_gap = phase2_results and phase2_results["total_updates_only"] > 0
    has_value_diffs = total_diffs > 0
    events_has_verdict = phase1_results and bool(phase1_results.get("verdict_keys"))

    if has_coverage_gap:
        rec = ("BOTH NEEDED: /v0/events is missing transactions that /v2/updates has. "
               "Both endpoints are required for complete data.")
    elif has_value_diffs:
        rec = ("INVESTIGATE: Both endpoints cover the same transactions, but some "
               "field values differ. Investigate the differences before deciding.")
    elif events_has_verdict:
        rec = ("EVENTS ONLY (PREFERRED): /v0/events returns identical transaction data "
               "AND provides the extra 'verdict' field. /v2/updates is redundant. "
               "Use /v0/events as the sole data source.")
    else:
        rec = ("EITHER ENDPOINT: Both return identical data with identical coverage. "
               "Choose based on preference or API stability.")

    report["recommendation"] = rec
    print(f"\n  {rec}")

    print(f"\n  Findings:")
    for finding in report["findings"]:
        print(f"    • {finding}")

    report["findings_count"] = len(report["findings"])
    return report


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive comparison of /v2/updates vs /v0/events"
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3, 4, 5],
        default=None,
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of individual updates to deep-diff in Phases 1 & 3 (default: 50)",
    )
    parser.add_argument(
        "--window-pages",
        type=int,
        default=10,
        help="Pages per window in Phase 2 (default: 10)",
    )
    parser.add_argument(
        "--num-windows",
        type=int,
        default=3,
        help="Number of time windows for Phase 2 (default: 3)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Page size for paginated fetches (default: 100)",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Path to save structured JSON report (e.g., output/report.json)",
    )
    parser.add_argument(
        "--migration-ids",
        type=str,
        default="0,1,2,3,4",
        help="Comma-separated list of migration IDs to sample from (default: 0,1,2,3,4)",
    )
    parser.add_argument(
        "--url",
        default=BASE_URL,
        help="Scan API base URL",
    )
    args = parser.parse_args()

    mig_ids = [int(x.strip()) for x in args.migration_ids.split(",")]

    banner("Canton Scan API: Comprehensive /v2/updates vs /v0/events Comparison", char="█")
    print(f"  Time:        {datetime.utcnow().isoformat()}Z")
    print(f"  API:         {args.url}")
    print(f"  Migrations:  {mig_ids}")
    print(f"  Sample size: {args.sample_size}")
    print(f"  Windows:     {args.num_windows} x {args.window_pages} pages")
    print(f"  Page size:   {args.page_size}")

    client = SpliceScanClient(base_url=args.url, timeout=60)

    phase1_results = None
    phase2_results = None
    phase3_results = None
    phase4_results = None
    report = None

    run_all = args.phase is None

    # Phase 1
    if run_all or args.phase == 1:
        phase1_results = phase1_schema_and_field_diff(
            client, sample_size=args.sample_size, migration_ids=mig_ids,
        )

    # Phase 2
    if run_all or args.phase == 2:
        phase2_results = phase2_transaction_coverage(
            client,
            num_windows=args.num_windows,
            window_pages=args.window_pages,
            page_size=args.page_size,
            migration_ids=mig_ids,
        )

    # Phase 3
    if run_all or args.phase == 3:
        phase3_results = phase3_event_type_coverage(
            client, sample_size=args.sample_size, migration_ids=mig_ids,
        )

    # Phase 4
    if run_all or args.phase == 4:
        phase4_results = phase4_template_choice_coverage(
            client, page_size=args.page_size, num_pages=20, migration_ids=mig_ids,
        )

    # Phase 5
    if run_all or args.phase == 5:
        report = phase5_summary_report(
            phase1_results, phase2_results, phase3_results, phase4_results
        )

    # Save JSON report
    if args.output_json and report:
        _save_json_report(args.output_json, {
            "phase1": _make_serializable(phase1_results),
            "phase2": _make_serializable(phase2_results),
            "phase3": _make_serializable(phase3_results),
            "phase4": _make_serializable(phase4_results),
            "report": report,
        })

    banner("Comparison complete.", char="█")


def _make_serializable(obj: Any) -> Any:
    """Convert sets, Counters, etc. to JSON-serializable types."""
    if obj is None:
        return None
    if isinstance(obj, set):
        return sorted(obj, key=str)
    if isinstance(obj, Counter):
        return dict(obj.most_common())
    if isinstance(obj, defaultdict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, tuple):
        return list(obj)
    return obj


def _save_json_report(path: str, data: Dict):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\n  JSON report saved to: {path}")


if __name__ == "__main__":
    main()
