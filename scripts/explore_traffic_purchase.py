"""
Canton Traffic Purchase Deep-Dive

Targeted exploration of traffic purchase transactions via the Scan API.

Traffic purchases are how parties buy synchronizer bandwidth using Canton Coin.
They involve two key templates:
  - Splice.AmuletRules:AmuletRules  (choice: AmuletRules_BuyMemberTraffic)
  - Splice.DecentralizedSynchronizer:MemberTraffic  (created events)

This script:
  1. Samples updates across migrations looking for traffic purchase exercises
  2. Extracts and documents the full event tree structure of traffic purchases
  3. Catalogs all fields in choice_argument and exercise_result payloads
  4. Identifies the parties involved and their roles
  5. Cross-references with MemberTraffic created events
  6. Compares traffic purchase structure across migrations for evolution

Strategy for finding traffic purchases in 10+ TB:
  - Traffic purchases happen regularly (every party that submits transactions
    needs bandwidth), so sampling from each migration should find them
  - We scan many pages per sample window to maximize coverage

Usage (run from whitelisted VM):
    python scripts/explore_traffic_purchase.py
    python scripts/explore_traffic_purchase.py --max-samples 50
    python scripts/explore_traffic_purchase.py --output-dir scripts/output/exploration

Output:
    - Console report with traffic purchase patterns
    - JSON file: traffic_purchase_deep_dive.json
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
REQUEST_DELAY = 0.15

TRAFFIC_TEMPLATE = "Splice.AmuletRules:AmuletRules"
TRAFFIC_CHOICE = "AmuletRules_BuyMemberTraffic"
MEMBER_TRAFFIC_TEMPLATE = "Splice.DecentralizedSynchronizer:MemberTraffic"

# Wide sampling across all migrations with many time windows
SAMPLE_WINDOWS = {
    0: [
        ("start",  "1970-01-01T00:00:00Z"),
        ("mid",    "2024-06-25T00:00:00Z"),
        ("late",   "2024-08-01T00:00:00Z"),
    ],
    1: [
        ("start",  "1970-01-01T00:00:00Z"),
        ("mid",    "2024-10-16T14:00:00Z"),
        ("late",   "2024-11-01T00:00:00Z"),
    ],
    2: [
        ("start",  "1970-01-01T00:00:00Z"),
        ("mid",    "2024-12-11T15:00:00Z"),
        ("late",   "2025-01-01T00:00:00Z"),
    ],
    3: [
        ("early",     "1970-01-01T00:00:00Z"),
        ("30min",     "2025-06-25T14:15:00Z"),
        ("1hr",       "2025-06-25T14:45:00Z"),
        ("2hr",       "2025-06-25T15:45:00Z"),
        ("4hr",       "2025-06-25T17:45:00Z"),
        ("1day",      "2025-06-26T13:45:00Z"),
        ("1week",     "2025-07-02T00:00:00Z"),
        ("1month",    "2025-07-25T00:00:00Z"),
        ("2months",   "2025-08-25T00:00:00Z"),
        ("3months",   "2025-09-25T00:00:00Z"),
        ("late",      "2025-11-01T00:00:00Z"),
    ],
    4: [
        ("early",     "1970-01-01T00:00:00Z"),
        ("30min",     "2025-12-10T16:55:00Z"),
        ("1hr",       "2025-12-10T17:25:00Z"),
        ("4hr",       "2025-12-10T20:25:00Z"),
        ("1day",      "2025-12-11T16:25:00Z"),
        ("1week",     "2025-12-17T00:00:00Z"),
        ("2weeks",    "2025-12-24T00:00:00Z"),
        ("1month",    "2026-01-10T00:00:00Z"),
        ("6weeks",    "2026-01-24T00:00:00Z"),
        ("2months",   "2026-02-10T00:00:00Z"),
        ("10weeks",   "2026-02-20T00:00:00Z"),
        ("recent",    "2026-02-27T00:00:00Z"),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Event Utilities — handles both wrapped and flat event formats
# ═══════════════════════════════════════════════════════════════════════════════
#
# /v2/updates can return events in two formats:
#   Wrapped:  {"created": {"template_id": ..., "create_arguments": ...}}
#   Flat:     {"event_type": "created_event", "template_id": ..., "create_arguments": ...}

def get_event_type(event: dict) -> str:
    """Determine event type, handling both wrapped and flat formats."""
    for k in ("created", "exercised", "archived"):
        if k in event and isinstance(event[k], dict):
            return k
    et = event.get("event_type", "")
    if et == "created_event" or "create_arguments" in event:
        return "created"
    if et == "exercised_event" or "choice" in event:
        return "exercised"
    if et == "archived_event" or event.get("archived") is True:
        return "archived"
    return "unknown"


def get_event_data(event: dict) -> dict:
    """Get the inner event data dict, handling both formats."""
    for k in ("created", "exercised", "archived"):
        if k in event and isinstance(event[k], dict):
            return event[k]
    return event


def get_update_events(update: dict) -> Tuple[list, dict]:
    """Extract root_event_ids and events_by_id from an update/transaction.

    Handles both /v2/updates flat format and /v0/events wrapped format.
    """
    root_ids = update.get("root_event_ids", [])
    events_by_id = update.get("events_by_id", {})
    if root_ids or events_by_id:
        return root_ids, events_by_id

    update_data = update.get("update", {})
    if isinstance(update_data, dict):
        root_ids = update_data.get("root_event_ids", [])
        events_by_id = update_data.get("events_by_id", {})
    return root_ids, events_by_id


def get_template_id(edata: dict) -> str:
    tid = edata.get("template_id", "")
    if isinstance(tid, dict):
        m, e = tid.get("module_name", ""), tid.get("entity_name", "")
        return f"{m}:{e}" if m and e else "unknown"
    return str(tid) if tid else "unknown"


def traverse(eid, events_by_id, depth=0):
    event = events_by_id.get(eid)
    if not event:
        return
    yield (eid, event, depth)
    edata = get_event_data(event)
    for cid in edata.get("child_event_ids", []):
        yield from traverse(cid, events_by_id, depth + 1)


def tree_shape(eid, events_by_id, depth=0):
    event = events_by_id.get(eid)
    if not event:
        return {"id": eid, "missing": True}
    etype = get_event_type(event)
    edata = get_event_data(event)
    tid = get_template_id(edata)
    choice = edata.get("choice", "") if etype == "exercised" else ""
    node = {"depth": depth, "event_type": etype, "template_id": tid}
    if choice:
        node["choice"] = choice
    children = edata.get("child_event_ids", [])
    if children:
        node["children"] = [tree_shape(c, events_by_id, depth + 1) for c in children]
    return node


def format_tree(shape, prefix=""):
    lines = []
    label = f"{shape.get('event_type', '?')}: {shape.get('template_id', '?')}"
    if shape.get("choice"):
        label += f" [{shape['choice']}]"
    lines.append(f"{prefix}{label}")
    children = shape.get("children", [])
    for i, child in enumerate(children):
        connector = "├── " if i < len(children) - 1 else "└── "
        lines.extend(format_tree(child, prefix + connector))
    return lines


def collect_fields(obj, path="", store=None):
    """Recursively collect all field paths from a dict."""
    if store is None:
        store = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            cp = f"{path}.{k}" if path else k
            store[cp] = store.get(cp, {"count": 0, "types": set(), "samples": []})
            store[cp]["count"] += 1
            store[cp]["types"].add(type(v).__name__)
            if len(store[cp]["samples"]) < 3:
                s = str(v)[:100]
                if s not in store[cp]["samples"]:
                    store[cp]["samples"].append(s)
            if isinstance(v, dict):
                collect_fields(v, cp, store)
            elif isinstance(v, list) and v:
                collect_fields(v[0], f"{cp}[]", store)
    return store


# ═══════════════════════════════════════════════════════════════════════════════
#  Traffic Purchase Accumulator
# ═══════════════════════════════════════════════════════════════════════════════

class TrafficPurchaseFindings:
    def __init__(self):
        self.buy_traffic_events = []       # full event details
        self.member_traffic_events = []    # MemberTraffic created events
        self.tree_structures = []          # full update trees containing traffic purchase
        self.choice_arg_fields = {}        # aggregated field inventory
        self.exercise_result_fields = {}   # aggregated field inventory
        self.member_traffic_fields = {}    # aggregated field inventory
        self.acting_parties = Counter()    # who buys traffic
        self.member_traffic_parties = Counter()  # provider parties
        self.co_occurring_templates = Counter()  # what else appears in same update
        self.co_occurring_choices = Counter()    # what choices co-occur
        self.events_per_update = []        # how many events in traffic purchase updates
        self.migrations_seen = set()
        self.pages_scanned = 0
        self.updates_scanned = 0
        self.total_events_scanned = 0
        self.total_traffic_updates = 0

    def process_updates(self, updates: list, migration_id: int):
        for update in updates:
            self.updates_scanned += 1
            self._check_update(update, migration_id)

    def _check_update(self, update: dict, migration_id: int):
        update_id = update.get("update_id", "")
        record_time = update.get("record_time", "")

        root_ids, events_by_id = get_update_events(update)

        if not root_ids and not events_by_id:
            return

        self.total_events_scanned += len(events_by_id)

        # Check if any event is a traffic purchase
        has_traffic_purchase = False
        update_templates = set()
        update_choices = set()

        # If we have root_ids, traverse the tree; otherwise iterate flat
        if root_ids:
            event_iter = (
                (eid, event, depth)
                for rid in root_ids
                for eid, event, depth in traverse(rid, events_by_id)
            )
        else:
            event_iter = (
                (eid, event, 0)
                for eid, event in events_by_id.items()
            )

        for eid, event, depth in event_iter:
            etype = get_event_type(event)
            edata = get_event_data(event)
            tid = get_template_id(edata)
            choice = edata.get("choice", "") if etype == "exercised" else ""

            update_templates.add(tid)
            if choice:
                update_choices.add((tid, choice))

            # Found a traffic purchase exercise
            if tid == TRAFFIC_TEMPLATE and choice == TRAFFIC_CHOICE:
                has_traffic_purchase = True
                self.migrations_seen.add(migration_id)

                # Save full event details (up to 50)
                if len(self.buy_traffic_events) < 50:
                    self.buy_traffic_events.append({
                        "update_id": update_id,
                        "record_time": record_time,
                        "migration_id": migration_id,
                        "event_id": eid,
                        "depth": depth,
                        "choice_argument": edata.get("choice_argument"),
                        "exercise_result": edata.get("exercise_result"),
                        "acting_parties": edata.get("acting_parties", []),
                        "consuming": edata.get("consuming"),
                        "child_event_ids": edata.get("child_event_ids", []),
                        "interface_id": edata.get("interface_id"),
                    })

                # Aggregate fields
                ca = edata.get("choice_argument")
                if ca and isinstance(ca, dict):
                    collect_fields(ca, store=self.choice_arg_fields)
                er = edata.get("exercise_result")
                if er and isinstance(er, dict):
                    collect_fields(er, store=self.exercise_result_fields)

                # Track acting parties
                for p in edata.get("acting_parties", []):
                    self.acting_parties[p] += 1

            # Found MemberTraffic created
            if tid == MEMBER_TRAFFIC_TEMPLATE and etype == "created":
                ca = edata.get("create_arguments", {})
                if len(self.member_traffic_events) < 50:
                    self.member_traffic_events.append({
                        "update_id": update_id,
                        "record_time": record_time,
                        "migration_id": migration_id,
                        "event_id": eid,
                        "create_arguments": ca,
                        "signatories": edata.get("signatories", []),
                        "observers": edata.get("observers", []),
                    })
                if ca and isinstance(ca, dict):
                    collect_fields(ca, store=self.member_traffic_fields)
                provider = ca.get("provider", "unknown") if isinstance(ca, dict) else "unknown"
                self.member_traffic_parties[provider] += 1

        if has_traffic_purchase:
            self.total_traffic_updates += 1
            self.events_per_update.append(len(events_by_id))

            # Track co-occurring templates/choices
            for tid in update_templates:
                if tid != TRAFFIC_TEMPLATE:
                    self.co_occurring_templates[tid] += 1
            for tid, ch in update_choices:
                if ch != TRAFFIC_CHOICE:
                    self.co_occurring_choices[(tid, ch)] += 1

            # Save tree structure (up to 20)
            if len(self.tree_structures) < 20:
                for rid in root_ids[:2]:
                    self.tree_structures.append({
                        "update_id": update_id,
                        "migration_id": migration_id,
                        "record_time": record_time,
                        "tree": tree_shape(rid, events_by_id),
                    })


# ═══════════════════════════════════════════════════════════════════════════════
#  Report
# ═══════════════════════════════════════════════════════════════════════════════

def print_traffic_report(findings: TrafficPurchaseFindings):
    print("\n" + "=" * 78)
    print("  TRAFFIC PURCHASE DEEP-DIVE REPORT")
    print("=" * 78)

    print(f"\n  Scanning Summary:")
    print(f"    Updates scanned:              {findings.updates_scanned:,}")
    print(f"    Events scanned:               {findings.total_events_scanned:,}")
    print(f"    Pages scanned:                {findings.pages_scanned}")
    print(f"    Traffic purchase updates:     {findings.total_traffic_updates}")
    print(f"    BuyMemberTraffic events:      {len(findings.buy_traffic_events)}")
    print(f"    MemberTraffic created events: {len(findings.member_traffic_events)}")
    print(f"    Migrations with traffic:      {sorted(findings.migrations_seen)}")

    if not findings.buy_traffic_events:
        print("\n  No traffic purchase events found in sampled data.")
        print("  Try increasing --pages-per-sample or --max-samples.")
        print("  Traffic purchases may be sparse in early migration pages.")
        return

    # ── Event Tree Structures ──
    print(f"\n{'─'*78}")
    print("  TRAFFIC PURCHASE EVENT TREE STRUCTURES")
    print(f"{'─'*78}")
    print("  These show what a complete traffic purchase transaction looks like.")
    shown_migs = set()
    for ts in findings.tree_structures[:10]:
        mig = ts["migration_id"]
        if mig in shown_migs and len(shown_migs) >= len(findings.migrations_seen):
            continue
        shown_migs.add(mig)
        print(f"\n  Migration {mig}, update_id={ts['update_id'][:60]}...")
        print(f"  record_time={ts['record_time'][:19]}")
        for line in format_tree(ts["tree"]):
            print(f"    {line}")

    # ── Average events per traffic purchase update ──
    if findings.events_per_update:
        avg = sum(findings.events_per_update) / len(findings.events_per_update)
        mn = min(findings.events_per_update)
        mx = max(findings.events_per_update)
        print(f"\n  Events per traffic purchase update: avg={avg:.1f}, min={mn}, max={mx}")

    # ── Choice Argument Field Inventory ──
    print(f"\n{'─'*78}")
    print("  AmuletRules_BuyMemberTraffic: choice_argument FIELDS")
    print(f"{'─'*78}")
    print("  These are the input parameters to the traffic purchase choice.\n")
    if findings.choice_arg_fields:
        print(f"  {'Field Path':<50} {'Count':>5}  Types       Samples")
        print(f"  {'─'*50} {'─'*5}  {'─'*10}  {'─'*30}")
        for path in sorted(findings.choice_arg_fields):
            info = findings.choice_arg_fields[path]
            types_str = ",".join(sorted(info["types"]))
            samples_str = " | ".join(info["samples"][:2])[:50]
            print(f"  {path:<50} {info['count']:>5}  {types_str:<10}  {samples_str}")
    else:
        print("  No choice_argument data found (may be empty or non-dict)")

    # ── Exercise Result Field Inventory ──
    print(f"\n{'─'*78}")
    print("  AmuletRules_BuyMemberTraffic: exercise_result FIELDS")
    print(f"{'─'*78}")
    print("  These are the output/return values of the traffic purchase.\n")
    if findings.exercise_result_fields:
        print(f"  {'Field Path':<50} {'Count':>5}  Types       Samples")
        print(f"  {'─'*50} {'─'*5}  {'─'*10}  {'─'*30}")
        for path in sorted(findings.exercise_result_fields):
            info = findings.exercise_result_fields[path]
            types_str = ",".join(sorted(info["types"]))
            samples_str = " | ".join(info["samples"][:2])[:50]
            print(f"  {path:<50} {info['count']:>5}  {types_str:<10}  {samples_str}")
    else:
        print("  No exercise_result data found")

    # ── MemberTraffic create_arguments ──
    print(f"\n{'─'*78}")
    print("  MemberTraffic: create_arguments FIELDS")
    print(f"{'─'*78}")
    print("  These describe the traffic record created on the ledger.\n")
    if findings.member_traffic_fields:
        print(f"  {'Field Path':<50} {'Count':>5}  Types       Samples")
        print(f"  {'─'*50} {'─'*5}  {'─'*10}  {'─'*30}")
        for path in sorted(findings.member_traffic_fields):
            info = findings.member_traffic_fields[path]
            types_str = ",".join(sorted(info["types"]))
            samples_str = " | ".join(info["samples"][:2])[:50]
            print(f"  {path:<50} {info['count']:>5}  {types_str:<10}  {samples_str}")
    else:
        print("  No MemberTraffic create_arguments found")

    # ── Parties ──
    print(f"\n{'─'*78}")
    print("  ACTING PARTIES (who initiates traffic purchases)")
    print(f"{'─'*78}")
    for party, count in findings.acting_parties.most_common(15):
        short = party[:60] + "..." if len(party) > 60 else party
        print(f"  {count:>5}  {short}")

    if findings.member_traffic_parties:
        print(f"\n  MEMBER TRAFFIC PROVIDERS:")
        for party, count in findings.member_traffic_parties.most_common(15):
            short = party[:60] + "..." if len(party) > 60 else party
            print(f"  {count:>5}  {short}")

    # ── Co-occurring templates ──
    if findings.co_occurring_templates:
        print(f"\n{'─'*78}")
        print("  CO-OCCURRING TEMPLATES (what else happens in same update)")
        print(f"{'─'*78}")
        for tid, count in findings.co_occurring_templates.most_common(20):
            print(f"  {count:>5}  {tid}")

    if findings.co_occurring_choices:
        print(f"\n  CO-OCCURRING CHOICES:")
        for (tid, ch), count in findings.co_occurring_choices.most_common(15):
            print(f"  {count:>5}  {tid} [{ch}]")

    # ── Sample Event Details ──
    print(f"\n{'─'*78}")
    print("  SAMPLE TRAFFIC PURCHASE EVENTS (full detail)")
    print(f"{'─'*78}")
    for i, evt in enumerate(findings.buy_traffic_events[:5]):
        print(f"\n  Sample {i+1}:")
        print(f"    update_id:      {evt['update_id']}")
        print(f"    migration_id:   {evt['migration_id']}")
        print(f"    record_time:    {evt['record_time']}")
        print(f"    depth:          {evt['depth']}")
        print(f"    consuming:      {evt['consuming']}")
        parties = evt.get('acting_parties', [])
        for p in parties[:2]:
            short = p[:65] + "..." if len(p) > 65 else p
            print(f"    acting_party:   {short}")
        print(f"    interface_id:   {evt.get('interface_id')}")
        if evt.get("choice_argument"):
            ca_str = json.dumps(evt['choice_argument'], indent=6, default=str)
            print(f"    choice_argument:")
            for line in ca_str[:1000].split('\n'):
                print(f"      {line}")
        if evt.get("exercise_result"):
            er_str = json.dumps(evt['exercise_result'], indent=6, default=str)
            print(f"    exercise_result:")
            for line in er_str[:1000].split('\n'):
                print(f"      {line}")


def save_traffic_json(findings: TrafficPurchaseFindings, output_dir: str):
    """Save findings as JSON for offline analysis."""
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "updates_scanned": findings.updates_scanned,
            "events_scanned": findings.total_events_scanned,
            "pages_scanned": findings.pages_scanned,
            "traffic_purchase_updates": findings.total_traffic_updates,
            "buy_traffic_events": len(findings.buy_traffic_events),
            "member_traffic_events": len(findings.member_traffic_events),
            "migrations_seen": sorted(findings.migrations_seen),
        },
        "buy_traffic_events": findings.buy_traffic_events,
        "member_traffic_events": findings.member_traffic_events,
        "tree_structures": findings.tree_structures[:10],
        "choice_arg_fields": {
            k: {"count": v["count"], "types": list(v["types"]), "samples": v["samples"]}
            for k, v in findings.choice_arg_fields.items()
        },
        "exercise_result_fields": {
            k: {"count": v["count"], "types": list(v["types"]), "samples": v["samples"]}
            for k, v in findings.exercise_result_fields.items()
        },
        "member_traffic_fields": {
            k: {"count": v["count"], "types": list(v["types"]), "samples": v["samples"]}
            for k, v in findings.member_traffic_fields.items()
        },
        "acting_parties": dict(findings.acting_parties.most_common(30)),
        "member_traffic_parties": dict(findings.member_traffic_parties.most_common(30)),
        "co_occurring_templates": dict(findings.co_occurring_templates.most_common(30)),
        "co_occurring_choices": [
            {"template_id": t, "choice": c, "count": n}
            for (t, c), n in findings.co_occurring_choices.most_common(30)
        ],
        "events_per_update": findings.events_per_update,
    }

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "traffic_purchase_deep_dive.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved to: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Deep-dive into Canton traffic purchase transactions"
    )
    parser.add_argument(
        "--pages-per-sample", type=int, default=10,
        help="Pages to fetch per sample window (default: 10)",
    )
    parser.add_argument(
        "--page-size", type=int, default=500,
        help="Updates per page (default: 500)",
    )
    parser.add_argument(
        "--max-samples", type=int, default=50,
        help="Stop after finding this many traffic purchase events (default: 50)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="scripts/output/exploration",
        help="Output directory for JSON report",
    )
    parser.add_argument(
        "--migration", type=int, nargs="*", default=None,
        help="Specific migrations to search (default: all 0-4)",
    )
    parser.add_argument(
        "--base-url", type=str, default=BASE_URL,
    )
    args = parser.parse_args()

    migrations = args.migration if args.migration is not None else list(SAMPLE_WINDOWS.keys())

    total_windows = sum(len(SAMPLE_WINDOWS.get(m, [])) for m in migrations)
    est_calls = total_windows * args.pages_per_sample

    print("=" * 78)
    print("  CANTON TRAFFIC PURCHASE DEEP-DIVE")
    print(f"  Migrations: {migrations}")
    print(f"  Sample windows: {total_windows}")
    print(f"  Pages/sample: {args.pages_per_sample}, Page size: {args.page_size}")
    print(f"  Estimated API calls: ~{est_calls}")
    print(f"  Stop after: {args.max_samples} traffic purchase events")
    print(f"  Estimated runtime: ~{est_calls * 0.5 / 60:.0f}-{est_calls * 1.0 / 60:.0f} minutes")
    print("=" * 78)

    client = SpliceScanClient(base_url=args.base_url, timeout=60)

    print("\nChecking API health...")
    if not client.health_check():
        print("ERROR: Cannot reach Scan API. Run from whitelisted VM.")
        return
    print("API is healthy.\n")

    findings = TrafficPurchaseFindings()
    start_time = time.time()
    windows_done = 0

    for mig_id in migrations:
        windows = SAMPLE_WINDOWS.get(mig_id, [("start", "1970-01-01T00:00:00Z")])

        print(f"\n{'═'*60}")
        print(f"  Migration {mig_id}: searching {len(windows)} windows")
        print(f"{'═'*60}")

        for label, after_rt in windows:
            if len(findings.buy_traffic_events) >= args.max_samples:
                print(f"  Reached {args.max_samples} samples, stopping.")
                break

            windows_done += 1
            elapsed = time.time() - start_time
            print(f"\n  [{label}] after={after_rt}  "
                  f"(window {windows_done}/{total_windows}, {elapsed:.0f}s elapsed)")

            cursor = after_rt
            for page in range(args.pages_per_sample):
                if len(findings.buy_traffic_events) >= args.max_samples:
                    break
                try:
                    resp = client.get_updates(
                        after_migration_id=mig_id,
                        after_record_time=cursor,
                        page_size=args.page_size,
                    )
                    updates = resp.get("updates", resp.get("transactions", []))
                    if not updates:
                        print(f"    page {page+1}: no data")
                        break

                    before = len(findings.buy_traffic_events)
                    findings.process_updates(updates, mig_id)
                    findings.pages_scanned += 1
                    found = len(findings.buy_traffic_events) - before
                    cursor = updates[-1].get("record_time", "")

                    print(f"    page {page+1}: {len(updates)} updates, "
                          f"{found} traffic purchases found "
                          f"(total: {len(findings.buy_traffic_events)})")

                    if len(updates) < args.page_size:
                        break  # Reached end of data for this window
                    time.sleep(REQUEST_DELAY)

                except Exception as e:
                    print(f"    page {page+1}: ERROR - {e}")
                    break

        if len(findings.buy_traffic_events) >= args.max_samples:
            break

    elapsed = time.time() - start_time
    print(f"\nSearch complete in {elapsed:.1f}s ({elapsed/60:.1f} min)")

    print_traffic_report(findings)
    save_traffic_json(findings, args.output_dir)

    client.close()
    print(f"\nDone.")


if __name__ == "__main__":
    main()
