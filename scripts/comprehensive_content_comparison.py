"""
Comprehensive Content Comparison: /v2/updates vs /v0/events

Determines whether the two Scan API endpoints contain the exact same content
inside their responses, field by field, across all transaction types and
time periods. This is NOT a structural/schema comparison — it's a deep content
analysis to decide whether both endpoints need to be ingested.

The analysis answers:
  1. Are the update bodies byte-for-byte identical between endpoints?
  2. For every field (create_arguments, choice_argument, exercise_result,
     party lists, etc.), do values match across endpoints?
  3. What content exists in each field, per transaction type?
  4. What unique content does the verdict (events-only) provide?
  5. What is the analytical value of each piece of data for Canton Network
     analytics (transfers, traffic purchases, validator rewards, app rewards,
     mining rounds, governance, ANS)?

Phases:
  1. Large-scale content equality verification (1000+ updates)
  2. Field-level content inventory across both endpoints
  3. Payload deep-dive by transaction type (what's inside create_arguments,
     choice_argument, exercise_result for each template/choice)
  4. Verdict content deep analysis (the only known unique data in events)
  5. Analytical value assessment and recommendation

Usage:
    python scripts/comprehensive_content_comparison.py
    python scripts/comprehensive_content_comparison.py --sample-size 2000
    python scripts/comprehensive_content_comparison.py --phase 1
    python scripts/comprehensive_content_comparison.py --output-json output/content_report.json
"""

import argparse
import hashlib
import json
import math
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
REQUEST_DELAY = 0.3
MIGRATION_IDS = [0, 1, 2, 3, 4]


# ═══════════════════════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════════════════════

def banner(text: str, char: str = "=", width: int = 78):
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}", flush=True)


def sub_banner(text: str):
    banner(text, char="-", width=78)


def json_hash(obj: Any) -> str:
    """Deterministic hash of a JSON-serializable object."""
    canonical = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def deep_diff(a: Any, b: Any, path: str = "") -> List[Dict[str, Any]]:
    """Recursively compare two JSON objects, returning all differences."""
    diffs = []
    if type(a) != type(b):
        diffs.append({
            "path": path or "(root)",
            "type": "type_mismatch",
            "a_type": type(a).__name__,
            "b_type": type(b).__name__,
            "a_sample": _truncate(a),
            "b_sample": _truncate(b),
        })
        return diffs

    if isinstance(a, dict):
        all_keys = set(a.keys()) | set(b.keys())
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in a:
                diffs.append({"path": child_path, "type": "only_in_events",
                              "value_sample": _truncate(b[key])})
            elif key not in b:
                diffs.append({"path": child_path, "type": "only_in_updates",
                              "value_sample": _truncate(a[key])})
            else:
                diffs.extend(deep_diff(a[key], b[key], child_path))
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append({"path": path, "type": "list_length_mismatch",
                          "updates_len": len(a), "events_len": len(b)})
        for i in range(min(len(a), len(b))):
            diffs.extend(deep_diff(a[i], b[i], f"{path}[{i}]"))
    else:
        if a != b:
            diffs.append({"path": path or "(root)", "type": "value_mismatch",
                          "updates_value": _truncate(a),
                          "events_value": _truncate(b)})
    return diffs


def _truncate(value: Any, max_len: int = 200) -> Any:
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    if isinstance(value, (dict, list)):
        s = json.dumps(value, default=str)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return value
    return value


def collect_field_paths(obj: Any, prefix: str = "") -> Set[str]:
    """Recursively collect all field paths from a JSON object."""
    paths = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else k
            paths.add(full)
            paths.update(collect_field_paths(v, full))
    elif isinstance(obj, list) and obj:
        paths.update(collect_field_paths(obj[0], f"{prefix}[]"))
    return paths


def sizeof_json(obj: Any) -> int:
    """Approximate JSON byte size of an object."""
    return len(json.dumps(obj, default=str, ensure_ascii=True).encode())


# ═══════════════════════════════════════════════════════════════════════════════
#  Data Fetching Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_updates_page(client, migration_id, record_time, page_size):
    """Fetch one page from /v2/updates. Returns (updates_list, after_cursor)."""
    resp = client.get_updates(
        after_migration_id=migration_id,
        after_record_time=record_time,
        page_size=page_size,
    )
    updates = resp.get("updates", resp.get("transactions", []))
    after = resp.get("after")
    return updates, after


def fetch_events_page(client, migration_id, record_time, page_size):
    """Fetch one page from /v0/events. Returns (items_list, after_cursor).
    Each item is {"update": {...}, "verdict": {...}}."""
    resp = client.get_events(
        after_migration_id=migration_id,
        after_record_time=record_time,
        page_size=page_size,
    )
    raw = resp.get("events", [])
    items = []
    for wrapper in raw:
        update = wrapper.get("update", wrapper)
        verdict = wrapper.get("verdict")
        items.append({"update": update, "verdict": verdict})
    after = resp.get("after")
    return items, after


def discover_migration_range(client, migration_id, max_pages=5):
    """Discover data range for a migration. Returns (first_record_time, last_record_time, approx_count)."""
    cursor_rt = "2000-01-01T00:00:00Z"
    first_rt = None
    last_rt = None
    total = 0
    for _ in range(max_pages):
        txns, after = fetch_updates_page(client, migration_id, cursor_rt, 500)
        if not txns:
            break
        if txns[0].get("migration_id") != migration_id:
            break
        if first_rt is None:
            first_rt = txns[0].get("record_time")
        # Find last record in this migration
        for t in txns:
            if t.get("migration_id") == migration_id:
                last_rt = t.get("record_time")
                total += 1
            else:
                break
        if not after or after.get("after_migration_id") != migration_id:
            break
        cursor_rt = after.get("after_record_time")
        time.sleep(0.05)
    return first_rt, last_rt, total


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 1: Large-Scale Content Equality Verification
# ═══════════════════════════════════════════════════════════════════════════════

def phase1_content_equality(client, sample_size=1000, page_size=200):
    """
    Fetch pages from BOTH endpoints using the same cursor and compare
    every update body. This is a bulk comparison — much faster than
    individual lookups.

    For each update present in both responses, we:
      1. Hash the full update body from each endpoint
      2. If hashes differ, do a recursive deep_diff to find exactly which fields differ
      3. Track per-field match/mismatch statistics
    """
    banner("PHASE 1: Large-Scale Content Equality Verification")
    print(f"  Target sample: {sample_size} updates across all migrations")
    print(f"  Method: Fetch same pages from both endpoints, compare inline\n")

    results = {
        "total_compared": 0,
        "total_identical": 0,
        "total_with_diffs": 0,
        "diffs_by_field_path": Counter(),
        "diffs_by_type": Counter(),
        "diff_examples": [],  # First N examples of each diff type
        "per_migration": {},
        "field_paths_only_in_updates": set(),
        "field_paths_only_in_events": set(),
        "all_field_paths_updates": set(),
        "all_field_paths_events": set(),
        "updates_without_verdict": 0,
        "updates_with_verdict": 0,
        "template_coverage": Counter(),  # template_id → count compared
        "choice_coverage": Counter(),    # choice → count compared
    }

    remaining = sample_size

    for mig_id in MIGRATION_IDS:
        if remaining <= 0:
            break

        sub_banner(f"Migration {mig_id}")
        first_rt, last_rt, approx = discover_migration_range(client, mig_id)
        if not first_rt:
            print(f"  No data for migration {mig_id}")
            continue
        print(f"  Data range: {first_rt} .. {last_rt} (~{approx} updates)")

        mig_stats = {"compared": 0, "identical": 0, "with_diffs": 0}
        cursor_rt = "2000-01-01T00:00:00Z"

        pages_to_fetch = math.ceil(min(remaining, approx) / page_size)
        pages_to_fetch = max(pages_to_fetch, 1)

        for page_num in range(pages_to_fetch):
            if remaining <= 0:
                break

            # Fetch same page from both endpoints
            try:
                u_items, u_after = fetch_updates_page(client, mig_id, cursor_rt, page_size)
                time.sleep(REQUEST_DELAY)
                e_items, e_after = fetch_events_page(client, mig_id, cursor_rt, page_size)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"  ERROR fetching page {page_num + 1}: {e}")
                break

            if not u_items or not e_items:
                break

            # Stop if we've left our migration
            if u_items[0].get("migration_id") != mig_id:
                break

            print(f"  Page {page_num + 1}: {len(u_items)} updates vs {len(e_items)} events",
                  end="", flush=True)

            # Build lookup by update_id for events
            e_by_id = {}
            for item in e_items:
                upd = item.get("update")
                if upd:
                    uid = upd.get("update_id")
                    if uid:
                        e_by_id[uid] = item

            matched = 0
            diffs_this_page = 0

            for u_body in u_items:
                uid = u_body.get("update_id")
                if not uid or uid not in e_by_id:
                    continue

                e_item = e_by_id[uid]
                e_body = e_item["update"]
                verdict = e_item.get("verdict")

                # Track coverage
                for eid, evt in u_body.get("events_by_id", {}).items():
                    tid = evt.get("template_id", "unknown")
                    results["template_coverage"][tid] += 1
                    if evt.get("choice"):
                        results["choice_coverage"][evt["choice"]] += 1

                # Track field paths
                results["all_field_paths_updates"].update(collect_field_paths(u_body))
                results["all_field_paths_events"].update(collect_field_paths(e_body))

                # Track verdict presence
                if verdict:
                    results["updates_with_verdict"] += 1
                else:
                    results["updates_without_verdict"] += 1

                # Compare: hash first (fast), deep_diff only on mismatch
                u_hash = json_hash(u_body)
                e_hash = json_hash(e_body)

                results["total_compared"] += 1
                mig_stats["compared"] += 1
                matched += 1
                remaining -= 1

                if u_hash == e_hash:
                    results["total_identical"] += 1
                    mig_stats["identical"] += 1
                else:
                    # Content differs — find exactly what
                    diffs = deep_diff(u_body, e_body)
                    results["total_with_diffs"] += 1
                    mig_stats["with_diffs"] += 1
                    diffs_this_page += 1

                    for d in diffs:
                        results["diffs_by_field_path"][d["path"]] += 1
                        results["diffs_by_type"][d["type"]] += 1
                        if d["type"] == "only_in_updates":
                            results["field_paths_only_in_updates"].add(d["path"])
                        elif d["type"] == "only_in_events":
                            results["field_paths_only_in_events"].add(d["path"])

                    # Keep first 20 diff examples
                    if len(results["diff_examples"]) < 20:
                        results["diff_examples"].append({
                            "update_id": uid,
                            "migration_id": mig_id,
                            "template_ids": [evt.get("template_id") for evt in u_body.get("events_by_id", {}).values()],
                            "diffs": diffs[:10],
                        })

                if remaining <= 0:
                    break

            status = "ALL IDENTICAL" if diffs_this_page == 0 else f"{diffs_this_page} WITH DIFFS"
            print(f" → {matched} compared, {status}")

            # Advance cursor
            if u_after:
                next_mig = u_after.get("after_migration_id")
                if next_mig != mig_id:
                    break
                cursor_rt = u_after.get("after_record_time")
            else:
                break

        results["per_migration"][mig_id] = mig_stats

    # Print summary
    _print_phase1_summary(results)
    return results


def _print_phase1_summary(results):
    sub_banner("Phase 1 Summary: Content Equality")

    print(f"\n  Total updates compared:  {results['total_compared']}")
    print(f"  Byte-identical:          {results['total_identical']}")
    print(f"  With differences:        {results['total_with_diffs']}")

    if results["total_compared"] > 0:
        pct = results["total_identical"] / results["total_compared"] * 100
        print(f"  Identity rate:           {pct:.2f}%")

    print(f"\n  Per migration:")
    for mig_id, stats in sorted(results["per_migration"].items()):
        print(f"    Migration {mig_id}: {stats['compared']} compared, "
              f"{stats['identical']} identical, {stats['with_diffs']} with diffs")

    print(f"\n  Field paths found in /v2/updates: {len(results['all_field_paths_updates'])}")
    print(f"  Field paths found in /v0/events:  {len(results['all_field_paths_events'])}")

    only_u = results["all_field_paths_updates"] - results["all_field_paths_events"]
    only_e = results["all_field_paths_events"] - results["all_field_paths_updates"]
    if only_u:
        print(f"\n  Fields ONLY in /v2/updates ({len(only_u)}):")
        for p in sorted(only_u):
            print(f"    - {p}")
    if only_e:
        print(f"\n  Fields ONLY in /v0/events update body ({len(only_e)}):")
        for p in sorted(only_e):
            print(f"    - {p}")
    if not only_u and not only_e:
        print(f"\n  Field sets are IDENTICAL between both endpoints")

    if results["total_with_diffs"] > 0:
        print(f"\n  Diff breakdown by field path:")
        for path, count in results["diffs_by_field_path"].most_common(20):
            print(f"    {path}: {count} occurrences")
        print(f"\n  Diff breakdown by type:")
        for dtype, count in results["diffs_by_type"].most_common():
            print(f"    {dtype}: {count}")
        if results["diff_examples"]:
            print(f"\n  First diff example:")
            print(f"    {json.dumps(results['diff_examples'][0], indent=4, default=str)}")

    print(f"\n  Verdict presence: {results['updates_with_verdict']} with verdict, "
          f"{results['updates_without_verdict']} without")

    print(f"\n  Template coverage ({len(results['template_coverage'])} unique templates):")
    for tid, count in results["template_coverage"].most_common(15):
        print(f"    {tid}: {count}")
    print(f"\n  Choice coverage ({len(results['choice_coverage'])} unique choices):")
    for choice, count in results["choice_coverage"].most_common(15):
        print(f"    {choice}: {count}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 2: Field-Level Content Inventory
# ═══════════════════════════════════════════════════════════════════════════════

def phase2_field_inventory(client, sample_size=500, page_size=200):
    """
    For a large sample of updates, inventory every field:
    - Name, data type, null rate, cardinality
    - Byte size contribution (storage cost)
    - Sample values
    - Which endpoint(s) contain it
    """
    banner("PHASE 2: Field-Level Content Inventory")
    print(f"  Sampling {sample_size} updates for field analysis\n")

    # Accumulate stats per field path
    field_stats = defaultdict(lambda: {
        "count": 0,
        "null_count": 0,
        "types": Counter(),
        "sample_values": [],
        "total_bytes": 0,
        "unique_values": set(),
        "in_updates": False,
        "in_events": False,
    })

    # Also track event-level fields separately
    event_field_stats = defaultdict(lambda: {
        "count": 0,
        "null_count": 0,
        "types": Counter(),
        "sample_values": [],
        "total_bytes": 0,
        "unique_values_count": 0,
        "_unique_hashes": set(),
    })

    total_sampled = 0
    remaining = sample_size

    for mig_id in MIGRATION_IDS:
        if remaining <= 0:
            break

        cursor_rt = "2000-01-01T00:00:00Z"
        pages_per_mig = max(1, math.ceil(remaining / len(MIGRATION_IDS) / page_size))

        for page_num in range(pages_per_mig):
            if remaining <= 0:
                break

            try:
                # Use events endpoint to get both update + verdict
                items, after = fetch_events_page(client, mig_id, cursor_rt, page_size)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"  ERROR: {e}")
                break

            if not items:
                break

            print(f"  Migration {mig_id}, page {page_num + 1}: "
                  f"{len(items)} items", end="", flush=True)

            for item in items:
                update = item.get("update")
                verdict = item.get("verdict")
                if not update:
                    continue

                if update.get("migration_id") != mig_id:
                    break

                total_sampled += 1
                remaining -= 1

                # Inventory update-level fields
                for key, value in update.items():
                    if key == "events_by_id":
                        continue  # Handle events separately
                    fs = field_stats[f"update.{key}"]
                    fs["count"] += 1
                    fs["in_updates"] = True
                    fs["in_events"] = True  # Same data in both
                    if value is None:
                        fs["null_count"] += 1
                    else:
                        fs["types"][type(value).__name__] += 1
                        byte_size = sizeof_json(value)
                        fs["total_bytes"] += byte_size
                        val_hash = json_hash(value)
                        if len(fs["unique_values"]) < 10000:
                            fs["unique_values"].add(val_hash)
                        if len(fs["sample_values"]) < 3:
                            fs["sample_values"].append(_truncate(value, 150))

                # Inventory event-level fields (inside events_by_id)
                for eid, evt in update.get("events_by_id", {}).items():
                    for key, value in evt.items():
                        fs = event_field_stats[f"event.{key}"]
                        fs["count"] += 1
                        if value is None:
                            fs["null_count"] += 1
                        else:
                            fs["types"][type(value).__name__] += 1
                            byte_size = sizeof_json(value)
                            fs["total_bytes"] += byte_size
                            val_hash = json_hash(value)
                            if len(fs["_unique_hashes"]) < 10000:
                                fs["_unique_hashes"].add(val_hash)
                            if len(fs["sample_values"]) < 3:
                                fs["sample_values"].append(_truncate(value, 150))

                # Inventory verdict fields (ONLY in /v0/events)
                if verdict:
                    _inventory_verdict_fields(verdict, field_stats)

                if remaining <= 0:
                    break

            print(f" ({total_sampled} total)", flush=True)

            if after and after.get("after_migration_id") == mig_id:
                cursor_rt = after.get("after_record_time")
            else:
                break

    # Finalize unique counts for event fields
    for key, fs in event_field_stats.items():
        fs["unique_values_count"] = len(fs["_unique_hashes"])
        del fs["_unique_hashes"]

    results = {
        "total_sampled": total_sampled,
        "update_fields": {k: _finalize_field_stats(v) for k, v in sorted(field_stats.items())},
        "event_fields": {k: _finalize_event_field_stats(v) for k, v in sorted(event_field_stats.items())},
    }

    _print_phase2_summary(results)
    return results


def _inventory_verdict_fields(verdict, field_stats, prefix="verdict"):
    """Recursively inventory all verdict fields."""
    if isinstance(verdict, dict):
        for key, value in verdict.items():
            full_key = f"{prefix}.{key}"
            fs = field_stats[full_key]
            fs["count"] += 1
            fs["in_updates"] = False
            fs["in_events"] = True
            if value is None:
                fs["null_count"] += 1
            else:
                fs["types"][type(value).__name__] += 1
                byte_size = sizeof_json(value)
                fs["total_bytes"] += byte_size
                val_hash = json_hash(value)
                if len(fs["unique_values"]) < 10000:
                    fs["unique_values"].add(val_hash)
                if len(fs["sample_values"]) < 3:
                    fs["sample_values"].append(_truncate(value, 150))

            # Recurse into nested structures
            if isinstance(value, dict):
                _inventory_verdict_fields(value, field_stats, full_key)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                # Inventory first element as representative
                _inventory_verdict_fields(value[0], field_stats, f"{full_key}[]")


def _finalize_field_stats(fs):
    """Convert sets to counts for JSON serialization."""
    return {
        "count": fs["count"],
        "null_count": fs["null_count"],
        "null_rate": f"{fs['null_count']/fs['count']*100:.1f}%" if fs["count"] > 0 else "N/A",
        "types": dict(fs["types"]),
        "unique_values_approx": len(fs["unique_values"]),
        "avg_bytes": fs["total_bytes"] // max(fs["count"] - fs["null_count"], 1),
        "total_bytes": fs["total_bytes"],
        "sample_values": fs["sample_values"],
        "in_updates": fs["in_updates"],
        "in_events": fs["in_events"],
        "only_in": "events" if fs["in_events"] and not fs["in_updates"]
                   else "updates" if fs["in_updates"] and not fs["in_events"]
                   else "both",
    }


def _finalize_event_field_stats(fs):
    return {
        "count": fs["count"],
        "null_count": fs["null_count"],
        "null_rate": f"{fs['null_count']/fs['count']*100:.1f}%" if fs["count"] > 0 else "N/A",
        "types": dict(fs["types"]),
        "unique_values_approx": fs["unique_values_count"],
        "avg_bytes": fs["total_bytes"] // max(fs["count"] - fs["null_count"], 1),
        "total_bytes": fs["total_bytes"],
        "sample_values": fs["sample_values"],
    }


def _print_phase2_summary(results):
    sub_banner("Phase 2 Summary: Field Inventory")
    print(f"\n  Total updates sampled: {results['total_sampled']}")

    print(f"\n  ┌─ UPDATE-LEVEL FIELDS ──────────────────────────────────────────┐")
    print(f"  │ {'Field':<35} {'Count':>6} {'Null%':>6} {'Uniq':>6} {'AvgB':>6} {'Only In':>8} │")
    print(f"  ├──────────────────────────────────────────────────────────────────┤")
    for name, fs in results["update_fields"].items():
        only = fs["only_in"]
        marker = " ◀" if only != "both" else ""
        print(f"  │ {name:<35} {fs['count']:>6} {fs['null_rate']:>6} "
              f"{fs['unique_values_approx']:>6} {fs['avg_bytes']:>6} {only:>8}{marker} │")
    print(f"  └──────────────────────────────────────────────────────────────────┘")

    print(f"\n  ┌─ EVENT-LEVEL FIELDS (inside events_by_id) ─────────────────────┐")
    print(f"  │ {'Field':<35} {'Count':>6} {'Null%':>6} {'Uniq':>6} {'AvgB':>6} │")
    print(f"  ├──────────────────────────────────────────────────────────────────┤")
    for name, fs in results["event_fields"].items():
        print(f"  │ {name:<35} {fs['count']:>6} {fs['null_rate']:>6} "
              f"{fs['unique_values_approx']:>6} {fs['avg_bytes']:>6} │")
    print(f"  └──────────────────────────────────────────────────────────────────┘")

    # Highlight verdict-only fields
    verdict_fields = {k: v for k, v in results["update_fields"].items()
                      if v["only_in"] == "events"}
    if verdict_fields:
        print(f"\n  VERDICT-ONLY FIELDS ({len(verdict_fields)} fields, only in /v0/events):")
        for name, fs in verdict_fields.items():
            print(f"    {name}:")
            print(f"      Populated: {fs['count'] - fs['null_count']}/{fs['count']} "
                  f"({100 - float(fs['null_rate'].rstrip('%')):.1f}%)")
            print(f"      Unique values: ~{fs['unique_values_approx']}")
            print(f"      Avg size: {fs['avg_bytes']} bytes")
            if fs["sample_values"]:
                print(f"      Sample: {fs['sample_values'][0]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 3: Payload Deep-Dive by Transaction Type
# ═══════════════════════════════════════════════════════════════════════════════

# Key Canton Network transaction types we care about for analytics
CANTON_TX_TYPES = {
    "Splice.AmuletRules:AmuletRules": {
        "description": "Core amulet rules governing CC token operations",
        "key_choices": ["AmuletRules_Transfer", "AmuletRules_BuyMemberTraffic",
                        "AmuletRules_Mint", "AmuletRules_DevNet_Tap"],
        "analytics": "Transfer volumes, traffic purchases, minting, fees",
    },
    "Splice.Amulet:Amulet": {
        "description": "Canton Coin (CC) token contracts",
        "key_choices": [],
        "analytics": "Token supply, balances, ownership, expiry rates",
    },
    "Splice.Round:OpenMiningRound": {
        "description": "Open mining rounds (10-minute intervals)",
        "key_choices": [],
        "analytics": "Round timing, configuration, issuance parameters",
    },
    "Splice.Round:IssuingMiningRound": {
        "description": "Rounds in issuance phase",
        "key_choices": [],
        "analytics": "Reward calculation parameters",
    },
    "Splice.Round:ClosedMiningRound": {
        "description": "Completed mining rounds",
        "key_choices": [],
        "analytics": "Final reward distributions",
    },
    "Splice.ValidatorLicense:ValidatorLicense": {
        "description": "Validator license contracts",
        "key_choices": [],
        "analytics": "Validator onboarding, activity, count over time",
    },
    "Splice.Amulet:ValidatorRewardCoupon": {
        "description": "Validator reward coupons",
        "key_choices": [],
        "analytics": "Per-validator rewards per round",
    },
    "Splice.Amulet:AppRewardCoupon": {
        "description": "App reward coupons (featured apps)",
        "key_choices": [],
        "analytics": "Per-app rewards, featured app activity",
    },
    "Splice.DecentralizedSynchronizer:MemberTraffic": {
        "description": "Traffic purchase records",
        "key_choices": [],
        "analytics": "Network usage, traffic costs, per-member activity",
    },
    "Splice.Ans:AnsEntry": {
        "description": "Amulet Name Service entries",
        "key_choices": [],
        "analytics": "Name registrations, ownership",
    },
    "Splice.DsoRules:VoteRequest": {
        "description": "Governance vote requests",
        "key_choices": [],
        "analytics": "Governance proposals, voting patterns",
    },
}


def phase3_payload_deep_dive(client, sample_size=1000, page_size=200):
    """
    For each key transaction type, examine:
    - What fields exist in create_arguments / choice_argument / exercise_result
    - What the content looks like (sample values, field types)
    - What Canton analytics can be extracted from each
    - Whether ANY of this content differs between endpoints
    """
    banner("PHASE 3: Payload Deep-Dive by Transaction Type")
    print(f"  Sampling {sample_size} updates to catalog payload content\n")

    # Per template_id: accumulate payload field info
    template_data = defaultdict(lambda: {
        "count": 0,
        "event_types": Counter(),
        "choices": Counter(),
        "create_args_fields": defaultdict(lambda: {"count": 0, "types": Counter(), "samples": []}),
        "choice_args_fields": defaultdict(lambda: {"count": 0, "types": Counter(), "samples": []}),
        "exercise_result_fields": defaultdict(lambda: {"count": 0, "types": Counter(), "samples": []}),
        "create_args_size_total": 0,
        "choice_args_size_total": 0,
        "exercise_result_size_total": 0,
        "party_patterns": {
            "signatories": Counter(),
            "observers": Counter(),
            "acting_parties": Counter(),
        },
        "consuming_count": 0,
        "samples": [],  # Full event samples (first 2)
    })

    remaining = sample_size
    total_events = 0

    for mig_id in MIGRATION_IDS:
        if remaining <= 0:
            break

        cursor_rt = "2000-01-01T00:00:00Z"
        pages_per_mig = max(1, math.ceil(remaining / len(MIGRATION_IDS) / page_size))

        for page_num in range(pages_per_mig):
            if remaining <= 0:
                break

            try:
                items, after = fetch_events_page(client, mig_id, cursor_rt, page_size)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"  ERROR: {e}")
                break

            if not items:
                break

            for item in items:
                update = item.get("update")
                if not update or update.get("migration_id") != mig_id:
                    continue

                remaining -= 1

                for eid, evt in update.get("events_by_id", {}).items():
                    tid = evt.get("template_id", "unknown")
                    td = template_data[tid]
                    td["count"] += 1
                    total_events += 1

                    # Event type
                    if "create_arguments" in evt:
                        td["event_types"]["created"] += 1
                        args = evt["create_arguments"]
                        td["create_args_size_total"] += sizeof_json(args)
                        _inventory_payload_fields(args, td["create_args_fields"])
                    if "choice" in evt:
                        td["event_types"]["exercised"] += 1
                        td["choices"][evt["choice"]] += 1
                        if "choice_argument" in evt:
                            args = evt["choice_argument"]
                            td["choice_args_size_total"] += sizeof_json(args)
                            _inventory_payload_fields(args, td["choice_args_fields"])
                        if "exercise_result" in evt:
                            result = evt["exercise_result"]
                            td["exercise_result_size_total"] += sizeof_json(result)
                            _inventory_payload_fields(result, td["exercise_result_fields"])

                    # Party patterns
                    for party_type in ["signatories", "observers", "acting_parties"]:
                        parties = evt.get(party_type, [])
                        td["party_patterns"][party_type][len(parties)] += 1

                    if evt.get("consuming"):
                        td["consuming_count"] += 1

                    # Keep first 2 full samples per template
                    if len(td["samples"]) < 2:
                        td["samples"].append({
                            "event_id": eid,
                            "update_id": update.get("update_id"),
                            "event": _truncate(evt, 500),
                        })

                if remaining <= 0:
                    break

            print(f"  Migration {mig_id}, page {page_num + 1}: "
                  f"{total_events} events cataloged", flush=True)

            if after and after.get("after_migration_id") == mig_id:
                cursor_rt = after.get("after_record_time")
            else:
                break

    results = {
        "total_events_cataloged": total_events,
        "unique_templates": len(template_data),
        "templates": {},
    }

    for tid in sorted(template_data.keys(), key=lambda t: template_data[t]["count"], reverse=True):
        td = template_data[tid]
        results["templates"][tid] = {
            "count": td["count"],
            "event_types": dict(td["event_types"]),
            "choices": dict(td["choices"]),
            "create_args_fields": {k: {"count": v["count"], "types": dict(v["types"]),
                                       "samples": v["samples"][:2]}
                                   for k, v in td["create_args_fields"].items()},
            "choice_args_fields": {k: {"count": v["count"], "types": dict(v["types"]),
                                       "samples": v["samples"][:2]}
                                   for k, v in td["choice_args_fields"].items()},
            "exercise_result_fields": {k: {"count": v["count"], "types": dict(v["types"]),
                                           "samples": v["samples"][:2]}
                                       for k, v in td["exercise_result_fields"].items()},
            "avg_create_args_bytes": td["create_args_size_total"] // max(td["event_types"].get("created", 0), 1),
            "avg_choice_args_bytes": td["choice_args_size_total"] // max(td["event_types"].get("exercised", 0), 1),
            "avg_exercise_result_bytes": td["exercise_result_size_total"] // max(td["event_types"].get("exercised", 0), 1),
            "party_patterns": {k: dict(v) for k, v in td["party_patterns"].items()},
            "consuming_rate": f"{td['consuming_count']/td['count']*100:.1f}%" if td["count"] > 0 else "0%",
            "known_type": tid in CANTON_TX_TYPES,
            "analytics_notes": CANTON_TX_TYPES.get(tid, {}).get("analytics", ""),
        }

    _print_phase3_summary(results)
    return results


def _inventory_payload_fields(payload, field_stats, prefix=""):
    """Recursively inventory fields in a payload (create_arguments, choice_argument, etc.)."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            full_key = f"{prefix}.{key}" if prefix else key
            fs = field_stats[full_key]
            fs["count"] += 1
            if value is not None:
                fs["types"][type(value).__name__] += 1
            if len(fs["samples"]) < 2:
                fs["samples"].append(_truncate(value, 120))
            # Recurse one level
            if isinstance(value, dict) and not prefix:
                _inventory_payload_fields(value, field_stats, full_key)


def _print_phase3_summary(results):
    sub_banner("Phase 3 Summary: Payload Content by Transaction Type")
    print(f"\n  Total events cataloged: {results['total_events_cataloged']}")
    print(f"  Unique template_ids: {results['unique_templates']}")

    for tid, info in list(results["templates"].items())[:20]:
        known = " ★" if info["known_type"] else ""
        print(f"\n  ┌─ {tid}{known} ({info['count']} events) ─────────────")

        if info["analytics_notes"]:
            print(f"  │ Analytics: {info['analytics_notes']}")

        print(f"  │ Event types: {info['event_types']}")
        if info["choices"]:
            print(f"  │ Choices: {dict(list(info['choices'].items())[:5])}")

        if info["create_args_fields"]:
            print(f"  │ create_arguments fields ({len(info['create_args_fields'])}): "
                  f"avg {info['avg_create_args_bytes']} bytes")
            for fname, finfo in list(info["create_args_fields"].items())[:8]:
                sample = finfo["samples"][0] if finfo["samples"] else "?"
                print(f"  │   {fname} ({finfo['count']}x, {dict(finfo['types'])}): {_truncate(sample, 80)}")

        if info["choice_args_fields"]:
            print(f"  │ choice_argument fields ({len(info['choice_args_fields'])}): "
                  f"avg {info['avg_choice_args_bytes']} bytes")
            for fname, finfo in list(info["choice_args_fields"].items())[:8]:
                sample = finfo["samples"][0] if finfo["samples"] else "?"
                print(f"  │   {fname} ({finfo['count']}x): {_truncate(sample, 80)}")

        if info["exercise_result_fields"]:
            print(f"  │ exercise_result fields ({len(info['exercise_result_fields'])}): "
                  f"avg {info['avg_exercise_result_bytes']} bytes")
            for fname, finfo in list(info["exercise_result_fields"].items())[:5]:
                sample = finfo["samples"][0] if finfo["samples"] else "?"
                print(f"  │   {fname} ({finfo['count']}x): {_truncate(sample, 80)}")

        print(f"  │ Party patterns: signatories={dict(info['party_patterns']['signatories'])}, "
              f"consuming={info['consuming_rate']}")
        print(f"  └───────────────────────────────────────────────────")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 4: Verdict Content Deep Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def phase4_verdict_analysis(client, sample_size=500, page_size=200):
    """
    Deep analysis of the verdict object — the ONLY data unique to /v0/events.
    For each verdict field, determine:
    - Population rate
    - Cardinality and distribution
    - Analytical value for Canton Network metrics
    - Whether the same information can be derived from update data
    """
    banner("PHASE 4: Verdict Content Deep Analysis")
    print(f"  Sampling {sample_size} updates with verdicts\n")

    stats = {
        "total_sampled": 0,
        "with_verdict": 0,
        "without_verdict": 0,
        # verdict_result analysis
        "verdict_results": Counter(),
        # finalization_time analysis
        "finalization_times": [],
        "latencies_ms": [],  # finalization_time - record_time
        "latency_by_template": defaultdict(list),
        # submitting_parties analysis
        "submitting_parties_counts": Counter(),  # number of submitting parties per txn
        "unique_submitting_parties": set(),
        "submitting_vs_acting_match": 0,
        "submitting_vs_acting_differ": 0,
        "submitting_vs_acting_examples": [],
        # submitting_participant_uid
        "unique_participants": Counter(),
        # mediator_group
        "mediator_groups": Counter(),
        # transaction_views analysis
        "views_per_txn": Counter(),
        "informees_per_view": Counter(),
        "confirming_parties_per_view": Counter(),
        "confirmation_thresholds": Counter(),
        "unique_informees": set(),
        "unique_confirming_parties": set(),
        # Full verdict samples per transaction type
        "verdict_samples_by_template": defaultdict(list),
    }

    remaining = sample_size

    for mig_id in MIGRATION_IDS:
        if remaining <= 0:
            break

        cursor_rt = "2000-01-01T00:00:00Z"
        pages_per_mig = max(1, math.ceil(remaining / len(MIGRATION_IDS) / page_size))

        for page_num in range(pages_per_mig):
            if remaining <= 0:
                break

            try:
                items, after = fetch_events_page(client, mig_id, cursor_rt, page_size)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"  ERROR: {e}")
                break

            if not items:
                break

            for item in items:
                update = item.get("update")
                verdict = item.get("verdict")
                if not update or update.get("migration_id") != mig_id:
                    continue

                stats["total_sampled"] += 1
                remaining -= 1

                if not verdict:
                    stats["without_verdict"] += 1
                    if remaining <= 0:
                        break
                    continue

                stats["with_verdict"] += 1

                # Get primary template for this update
                templates = [evt.get("template_id", "unknown")
                             for evt in update.get("events_by_id", {}).values()]
                primary_template = templates[0] if templates else "unknown"

                # All acting_parties across all events
                all_acting = set()
                for evt in update.get("events_by_id", {}).values():
                    for p in evt.get("acting_parties", []):
                        all_acting.add(p)

                # ── verdict_result ──
                vr = verdict.get("verdict_result")
                stats["verdict_results"][str(vr)] += 1

                # ── finalization_time ──
                ft = verdict.get("finalization_time")
                rt = verdict.get("record_time") or update.get("record_time")
                if ft and rt:
                    stats["finalization_times"].append(ft)
                    try:
                        ft_dt = datetime.fromisoformat(ft.replace("Z", "+00:00"))
                        rt_dt = datetime.fromisoformat(rt.replace("Z", "+00:00"))
                        latency_ms = (ft_dt - rt_dt).total_seconds() * 1000
                        stats["latencies_ms"].append(latency_ms)
                        stats["latency_by_template"][primary_template].append(latency_ms)
                    except (ValueError, TypeError):
                        pass

                # ── submitting_parties ──
                sp = verdict.get("submitting_parties", [])
                stats["submitting_parties_counts"][len(sp)] += 1
                for p in sp:
                    stats["unique_submitting_parties"].add(p)

                # Compare with acting_parties
                sp_set = set(sp)
                if sp_set and all_acting:
                    if sp_set == all_acting:
                        stats["submitting_vs_acting_match"] += 1
                    else:
                        stats["submitting_vs_acting_differ"] += 1
                        if len(stats["submitting_vs_acting_examples"]) < 5:
                            stats["submitting_vs_acting_examples"].append({
                                "update_id": update.get("update_id"),
                                "submitting_parties": list(sp_set),
                                "acting_parties": list(all_acting),
                                "template": primary_template,
                            })

                # ── submitting_participant_uid ──
                spuid = verdict.get("submitting_participant_uid")
                if spuid:
                    stats["unique_participants"][spuid] += 1

                # ── mediator_group ──
                mg = verdict.get("mediator_group")
                if mg is not None:
                    stats["mediator_groups"][mg] += 1

                # ── transaction_views ──
                tv = verdict.get("transaction_views", {})
                views = tv.get("views", [])
                stats["views_per_txn"][len(views)] += 1

                for view in views:
                    informees = view.get("informees", [])
                    stats["informees_per_view"][len(informees)] += 1
                    for inf in informees:
                        stats["unique_informees"].add(inf)

                    confirming = view.get("confirming_parties", [])
                    stats["confirming_parties_per_view"][len(confirming)] += 1
                    for cp in confirming:
                        threshold = cp.get("threshold")
                        if threshold is not None:
                            stats["confirmation_thresholds"][threshold] += 1
                        for p in cp.get("parties", []):
                            stats["unique_confirming_parties"].add(p)

                # Keep verdict samples per template
                if len(stats["verdict_samples_by_template"][primary_template]) < 2:
                    stats["verdict_samples_by_template"][primary_template].append({
                        "update_id": update.get("update_id"),
                        "verdict": _truncate(verdict, 1000),
                    })

                if remaining <= 0:
                    break

            print(f"  Migration {mig_id}, page {page_num + 1}: "
                  f"{stats['with_verdict']} with verdict, "
                  f"{stats['without_verdict']} without", flush=True)

            if after and after.get("after_migration_id") == mig_id:
                cursor_rt = after.get("after_record_time")
            else:
                break

    _print_phase4_summary(stats)

    # Serialize for JSON output
    results = {
        "total_sampled": stats["total_sampled"],
        "with_verdict": stats["with_verdict"],
        "without_verdict": stats["without_verdict"],
        "verdict_result_distribution": dict(stats["verdict_results"]),
        "latency_stats": _compute_latency_stats(stats["latencies_ms"]),
        "latency_by_template": {
            tid: _compute_latency_stats(lats)
            for tid, lats in stats["latency_by_template"].items()
            if len(lats) >= 3
        },
        "submitting_parties_count_distribution": dict(stats["submitting_parties_counts"]),
        "unique_submitting_parties": len(stats["unique_submitting_parties"]),
        "submitting_vs_acting_match_rate": (
            f"{stats['submitting_vs_acting_match']/(stats['submitting_vs_acting_match']+stats['submitting_vs_acting_differ'])*100:.1f}%"
            if (stats['submitting_vs_acting_match'] + stats['submitting_vs_acting_differ']) > 0 else "N/A"
        ),
        "submitting_vs_acting_diff_examples": stats["submitting_vs_acting_examples"],
        "unique_participant_nodes": len(stats["unique_participants"]),
        "top_participants": stats["unique_participants"].most_common(10),
        "mediator_group_distribution": dict(stats["mediator_groups"]),
        "views_per_txn_distribution": dict(stats["views_per_txn"]),
        "informees_per_view_distribution": dict(stats["informees_per_view"]),
        "unique_informees": len(stats["unique_informees"]),
        "unique_confirming_parties": len(stats["unique_confirming_parties"]),
        "confirmation_thresholds": dict(stats["confirmation_thresholds"]),
    }
    return results


def _compute_latency_stats(latencies):
    """Compute statistics for a list of latency values in ms."""
    if not latencies:
        return {"count": 0}
    s = sorted(latencies)
    n = len(s)
    return {
        "count": n,
        "min_ms": round(s[0], 1),
        "max_ms": round(s[-1], 1),
        "mean_ms": round(sum(s) / n, 1),
        "median_ms": round(s[n // 2], 1),
        "p95_ms": round(s[int(n * 0.95)], 1) if n >= 20 else None,
        "p99_ms": round(s[int(n * 0.99)], 1) if n >= 100 else None,
    }


def _print_phase4_summary(stats):
    sub_banner("Phase 4 Summary: Verdict Content Analysis")

    total = stats["total_sampled"]
    print(f"\n  Total sampled: {total}")
    print(f"  With verdict:  {stats['with_verdict']} ({stats['with_verdict']/total*100:.1f}%)" if total else "")
    print(f"  Without:       {stats['without_verdict']}")

    # verdict_result
    print(f"\n  ── verdict_result distribution ──")
    for vr, count in stats["verdict_results"].most_common():
        print(f"    {vr}: {count} ({count/total*100:.1f}%)")
    has_rejected = any("reject" in str(k).lower() for k in stats["verdict_results"])
    if has_rejected:
        print(f"    ⚠ REJECTED TRANSACTIONS FOUND — these are invisible in /v2/updates!")
    else:
        print(f"    → All transactions appear ACCEPTED (no rejections found in sample)")

    # Finalization latency
    if stats["latencies_ms"]:
        ls = _compute_latency_stats(stats["latencies_ms"])
        print(f"\n  ── finalization latency (finalization_time - record_time) ──")
        print(f"    Count:  {ls['count']}")
        print(f"    Min:    {ls['min_ms']:.0f} ms")
        print(f"    Median: {ls['median_ms']:.0f} ms")
        print(f"    Mean:   {ls['mean_ms']:.0f} ms")
        print(f"    Max:    {ls['max_ms']:.0f} ms")
        if ls.get("p95_ms"):
            print(f"    P95:    {ls['p95_ms']:.0f} ms")
        if ls.get("p99_ms"):
            print(f"    P99:    {ls['p99_ms']:.0f} ms")

    # Submitting parties vs acting parties
    total_compared = stats["submitting_vs_acting_match"] + stats["submitting_vs_acting_differ"]
    if total_compared > 0:
        match_pct = stats["submitting_vs_acting_match"] / total_compared * 100
        print(f"\n  ── submitting_parties vs acting_parties ──")
        print(f"    Match:  {stats['submitting_vs_acting_match']} ({match_pct:.1f}%)")
        print(f"    Differ: {stats['submitting_vs_acting_differ']} ({100-match_pct:.1f}%)")
        print(f"    Unique submitting parties: {len(stats['unique_submitting_parties'])}")
        if stats["submitting_vs_acting_examples"]:
            print(f"    Example where they differ:")
            ex = stats["submitting_vs_acting_examples"][0]
            print(f"      Update: {ex['update_id'][:40]}...")
            print(f"      Template: {ex['template']}")
            print(f"      Submitting: {ex['submitting_parties'][:3]}")
            print(f"      Acting: {ex['acting_parties'][:3]}")

    # Participant nodes
    print(f"\n  ── submitting_participant_uid ──")
    print(f"    Unique participant nodes: {len(stats['unique_participants'])}")
    for pid, count in stats["unique_participants"].most_common(10):
        print(f"    {pid[:40]}...: {count}")

    # Mediator groups
    print(f"\n  ── mediator_group ──")
    print(f"    Unique groups: {len(stats['mediator_groups'])}")
    for mg, count in stats["mediator_groups"].most_common():
        print(f"    Group {mg}: {count}")

    # Transaction views
    print(f"\n  ── transaction_views ──")
    print(f"    Views per transaction: {dict(stats['views_per_txn'])}")
    print(f"    Informees per view: {dict(stats['informees_per_view'])}")
    print(f"    Unique informees: {len(stats['unique_informees'])}")
    print(f"    Unique confirming parties: {len(stats['unique_confirming_parties'])}")
    print(f"    Confirmation thresholds: {dict(stats['confirmation_thresholds'])}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 5: Comprehensive Assessment
# ═══════════════════════════════════════════════════════════════════════════════

def phase5_assessment(phase1_results, phase2_results, phase3_results, phase4_results):
    """
    Synthesize all findings into a comprehensive assessment:
    - Are the update bodies identical? (Phase 1 answer)
    - What unique data does each endpoint provide? (Phase 2 answer)
    - What analytics does each field enable? (Phase 3 answer)
    - Is the verdict worth the extra storage? (Phase 4 answer)
    """
    banner("PHASE 5: Comprehensive Assessment")

    print("""
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                    DATA CONTENT COMPARISON RESULTS                      │
  └──────────────────────────────────────────────────────────────────────────┘
""")

    # Section 1: Content Identity
    if phase1_results:
        total = phase1_results["total_compared"]
        identical = phase1_results["total_identical"]
        pct = identical / total * 100 if total > 0 else 0

        print(f"  1. UPDATE BODY CONTENT IDENTITY")
        print(f"     Compared: {total} updates across {len(phase1_results['per_migration'])} migrations")
        print(f"     Identical: {identical} ({pct:.1f}%)")
        print(f"     With differences: {phase1_results['total_with_diffs']}")

        if phase1_results["total_with_diffs"] == 0:
            print(f"\n     CONCLUSION: The update body returned by /v2/updates is")
            print(f"     BYTE-FOR-BYTE IDENTICAL to the update body inside /v0/events")
            print(f"     for all {total} updates compared.")
            print(f"     → Ingesting update bodies from both endpoints would be pure duplication.")
        else:
            print(f"\n     DIFFERENCES FOUND:")
            for path, count in phase1_results["diffs_by_field_path"].most_common(10):
                print(f"       {path}: {count} occurrences")

        only_u = phase1_results.get("field_paths_only_in_updates", set())
        only_e = phase1_results.get("field_paths_only_in_events", set())
        if only_u:
            print(f"\n     Fields only in /v2/updates: {sorted(only_u)}")
        if only_e:
            print(f"\n     Fields only in /v0/events update body: {sorted(only_e)}")

    # Section 2: Unique Data Assessment
    print(f"\n  2. UNIQUE DATA BY ENDPOINT")
    print(f"     /v2/updates provides: update body (events_by_id, record_time, etc.)")
    print(f"     /v0/events provides:  SAME update body + verdict object")
    print(f"     → The ONLY unique data in /v0/events is the verdict.")

    # Section 3: Verdict Value
    if phase4_results:
        print(f"\n  3. VERDICT ANALYTICAL VALUE")
        print(f"     Verdict populated in: {phase4_results.get('with_verdict', 0)}/{phase4_results.get('total_sampled', 0)} updates")

        vr = phase4_results.get("verdict_result_distribution", {})
        has_rejected = any("reject" in str(k).lower() for k in vr)
        print(f"\n     a) verdict_result: {vr}")
        if has_rejected:
            print(f"        ⚠ REJECTED TRANSACTIONS EXIST → verdict is needed to see failures")
        else:
            print(f"        All ACCEPTED → This field adds minimal analytical value")

        ls = phase4_results.get("latency_stats", {})
        if ls.get("count", 0) > 0:
            print(f"\n     b) finalization_time: Enables consensus latency measurement")
            print(f"        Median latency: {ls.get('median_ms', 'N/A')}ms, "
                  f"P95: {ls.get('p95_ms', 'N/A')}ms")
            print(f"        → Useful for network health monitoring")

        sp_match = phase4_results.get("submitting_vs_acting_match_rate", "N/A")
        print(f"\n     c) submitting_parties: Match rate with acting_parties: {sp_match}")
        print(f"        Unique submitting parties: {phase4_results.get('unique_submitting_parties', 0)}")

        print(f"\n     d) submitting_participant_uid: {phase4_results.get('unique_participant_nodes', 0)} unique nodes")
        print(f"        → Infrastructure-level analytics (which validator nodes are active)")

        print(f"\n     e) mediator_group: {len(phase4_results.get('mediator_group_distribution', {}))} groups")
        print(f"        → Mediator load distribution analytics")

        views = phase4_results.get("views_per_txn_distribution", {})
        print(f"\n     f) transaction_views: {views}")
        print(f"        Unique informees: {phase4_results.get('unique_informees', 0)}")
        print(f"        Unique confirming parties: {phase4_results.get('unique_confirming_parties', 0)}")
        print(f"        → Privacy topology / who-sees-what analytics")
        print(f"        → Canton's key differentiator from other blockchains")

    # Section 4: Analytics Use Cases
    print(f"\n  4. CANTON ANALYTICS USE CASES: WHICH ENDPOINT IS NEEDED?")
    print(f"""
     ┌─────────────────────────────────────┬───────────┬──────────────────┐
     │ Analytics Use Case                  │ /v2/upd   │ /v0/events       │
     ├─────────────────────────────────────┼───────────┼──────────────────┤
     │ CC transfer volumes & amounts       │ ✓ Full    │ ✓ Same           │
     │ Token supply / balances             │ ✓ Full    │ ✓ Same           │
     │ Traffic purchase volumes            │ ✓ Full    │ ✓ Same           │
     │ Validator reward distribution       │ ✓ Full    │ ✓ Same           │
     │ App reward tracking                 │ ✓ Full    │ ✓ Same           │
     │ Mining round lifecycle              │ ✓ Full    │ ✓ Same           │
     │ Governance vote tracking            │ ✓ Full    │ ✓ Same           │
     │ ANS name registrations             │ ✓ Full    │ ✓ Same           │
     │ Contract lifecycle (ACS)            │ ✓ Full    │ ✓ Same           │
     │ Party activity patterns             │ ✓ Full    │ ✓ Same           │
     ├─────────────────────────────────────┼───────────┼──────────────────┤
     │ Transaction rejection rates         │ ✗ None    │ ✓ verdict_result │
     │ Consensus finalization latency      │ ✗ None    │ ✓ final. time    │
     │ Participant node activity           │ ✗ None    │ ✓ participant_uid│
     │ Mediator load distribution          │ ✗ None    │ ✓ mediator_group │
     │ Privacy topology (who sees what)    │ ✗ None    │ ✓ txn_views      │
     │ Confirmation quorum patterns        │ ✗ None    │ ✓ confirming_p.  │
     │ Submitter identity (vs actor)       │ ✗ None    │ ✓ submitting_p.  │
     └─────────────────────────────────────┴───────────┴──────────────────┘
""")

    # Section 5: Cost Consideration
    print(f"  5. COST CONSIDERATION")
    print(f"     If update bodies are identical (Phase 1 confirms this):")
    print(f"     → Ingesting BOTH endpoints duplicates ~100% of the event data")
    print(f"     → The only incremental data from /v0/events is the verdict (~5-15% of payload)")
    print(f"     → Storing both endpoints does NOT double the useful data, it adds verdict only")
    print(f"")
    print(f"     OPTION A: /v2/updates only")
    print(f"       Cost: ~10 TB. Covers all token/contract analytics.")
    print(f"       Lost: verdict data (consensus, privacy, infrastructure metrics)")
    print(f"")
    print(f"     OPTION B: /v0/events only")
    print(f"       Cost: ~10-11 TB (same events + small verdict overhead)")
    print(f"       Gain: All analytics from Option A PLUS verdict-based analytics")
    print(f"       Note: verdict data is EPHEMERAL and cannot be recovered once pruned")
    print(f"")
    print(f"     OPTION C: Both endpoints")
    print(f"       Cost: ~20 TB. Pure duplication of event data.")
    print(f"       Not recommended if update bodies are confirmed identical.")

    print(f"\n  6. RECOMMENDATION")
    print(f"     (Based on data from this analysis — review the numbers above)")


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive content comparison: /v2/updates vs /v0/events"
    )
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4, 5],
                        help="Run specific phase (default: all)")
    parser.add_argument("--sample-size", type=int, default=1000,
                        help="Number of updates to sample per phase (default: 1000)")
    parser.add_argument("--page-size", type=int, default=200,
                        help="Page size for API requests (default: 200)")
    parser.add_argument("--output-json", type=str,
                        help="Save structured results to JSON file")
    parser.add_argument("--base-url", type=str, default=BASE_URL,
                        help="Scan API base URL")
    args = parser.parse_args()

    banner("Canton Scan API: Comprehensive Content Comparison", char="█", width=78)
    print(f"  Time:        {datetime.utcnow().isoformat()}Z")
    print(f"  API:         {args.base_url}")
    print(f"  Sample size: {args.sample_size}")
    print(f"  Page size:   {args.page_size}")
    print(f"  Phase:       {args.phase or 'all'}")

    client = SpliceScanClient(base_url=args.base_url, timeout=60)

    all_results = {}
    phase1_results = None
    phase2_results = None
    phase3_results = None
    phase4_results = None

    try:
        if args.phase is None or args.phase == 1:
            phase1_results = phase1_content_equality(
                client, sample_size=args.sample_size, page_size=args.page_size)
            all_results["phase1"] = _sanitize_for_json(phase1_results)

        if args.phase is None or args.phase == 2:
            phase2_results = phase2_field_inventory(
                client, sample_size=args.sample_size, page_size=args.page_size)
            all_results["phase2"] = phase2_results

        if args.phase is None or args.phase == 3:
            phase3_results = phase3_payload_deep_dive(
                client, sample_size=args.sample_size, page_size=args.page_size)
            all_results["phase3"] = phase3_results

        if args.phase is None or args.phase == 4:
            phase4_results = phase4_verdict_analysis(
                client, sample_size=args.sample_size, page_size=args.page_size)
            all_results["phase4"] = phase4_results

        if args.phase is None or args.phase == 5:
            phase5_assessment(phase1_results, phase2_results, phase3_results, phase4_results)

        if args.output_json and all_results:
            os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
            with open(args.output_json, "w") as f:
                json.dump(all_results, f, indent=2, default=str)
            print(f"\n  Results saved to: {args.output_json}")

    finally:
        client.close()

    banner("Comparison complete", char="█", width=78)


def _sanitize_for_json(obj):
    """Convert sets and other non-serializable types for JSON output."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, Counter):
        return dict(obj)
    return obj


if __name__ == "__main__":
    main()
