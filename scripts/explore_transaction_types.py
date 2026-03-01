"""
Canton On-Chain Data Exploration: Thorough Sampling Strategy

With 10+ TB of historical data across migrations 0-4, we use deep targeted sampling
to build a comprehensive understanding of the transaction type landscape.

Sampling Strategy:
  1. MIGRATION BOUNDARY SAMPLING - Multiple pages from each migration (0-4)
     to discover which templates/choices exist at the start of each epoch.
     Short-lived migrations (0-2) are scanned more fully.

  2. TEMPORAL SAMPLING - For long-running migrations (3 and 4), sample at
     many time windows spread across the full timeline to capture the
     evolution of the transaction mix.

  3. SCHEMA EVOLUTION DETECTION - Compare the same template_id's payload
     structure across different migrations to detect field changes. This is
     critical because migrations often introduce new contract versions.

  4. FREQUENCY ESTIMATION - For each sample window, compute template/choice
     frequency distributions. These are local estimates, not global counts.

Output:
  - Console report with transaction type catalog and frequency estimates
  - JSON report saved to scripts/output/exploration/ for offline analysis
  - Raw API response samples saved for reference

Usage (run from whitelisted VM):
    python scripts/explore_transaction_types.py
    python scripts/explore_transaction_types.py --pages-per-sample 20
    python scripts/explore_transaction_types.py --output-dir scripts/output/exploration

Design Notes:
  - Default: ~10 sample points × 10 pages × 500 updates = ~50,000 updates sampled
  - Runtime: ~10-20 minutes depending on network latency
  - No BigQuery dependency — works entirely against the Scan API
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

# ═══════════════════════════════════════════════════════════════════════════════
#  Sample Point Definitions
# ═══════════════════════════════════════════════════════════════════════════════
#
# Each migration has known approximate time ranges (from prior pipeline runs).
# We sample at strategic points within each.
#
# Migrations 0-2 are short — we scan deeper from the start to get more coverage.
# Migrations 3-4 are long-running — we sample many time windows across the full span.

SAMPLE_POINTS = {
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
        ("2weeks",    "2025-07-09T00:00:00Z"),
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
#  Event Parsing Utilities
# ═══════════════════════════════════════════════════════════════════════════════
#
# Per UPDATES_VS_EVENTS_INVESTIGATION.md, /v2/updates returns events in flat format:
#   {"template_id": "...", "create_arguments": {...}, ...}    (created event)
#   {"template_id": "...", "choice": "...", ...}              (exercised event)
#   {"template_id": "...", "archived": true, ...}             (archived event)
#
# Event type is determined by which fields are present.
# We also handle the wrapped format ({"created": {...}}) for robustness with
# /v0/events or future format changes.

def get_event_type(event: dict) -> str:
    """Determine event type from an event object.

    Flat format (what /v2/updates returns):
      - "create_arguments" present → created
      - "choice" present → exercised
      - "archived" truthy → archived

    Wrapped format (fallback):
      - {"created": {...}} → created
      - {"exercised": {...}} → exercised
      - {"archived": {...}} → archived
    """
    # Flat format: check presence of distinguishing fields
    if "create_arguments" in event:
        return "created"
    if "choice" in event:
        return "exercised"
    if event.get("archived"):
        return "archived"
    # Wrapped format fallback
    for k in ("created", "exercised", "archived"):
        if k in event and isinstance(event[k], dict):
            return k
    return "unknown"


def get_event_data(event: dict) -> dict:
    """Get the inner event data dict, handling both formats."""
    # Wrapped format: return the inner dict
    for k in ("created", "exercised", "archived"):
        if k in event and isinstance(event[k], dict):
            return event[k]
    # Flat format: the event itself contains all fields
    return event


def get_update_events(update: dict) -> Tuple[list, dict]:
    """Extract root_event_ids and events_by_id from an update/transaction.

    Handles both:
      - /v2/updates flat format: root_event_ids and events_by_id are top-level
      - /v0/events wrapped format: nested under update.update
    """
    # Try flat format first (what /v2/updates returns via get_updates())
    root_ids = update.get("root_event_ids", [])
    events_by_id = update.get("events_by_id", {})
    if root_ids or events_by_id:
        return root_ids, events_by_id

    # Fall back to wrapped format (what /v0/events uses)
    update_data = update.get("update", {})
    if isinstance(update_data, dict):
        root_ids = update_data.get("root_event_ids", [])
        events_by_id = update_data.get("events_by_id", {})
    return root_ids, events_by_id


def get_template_id(event_data: dict) -> str:
    tid = event_data.get("template_id", "")
    if isinstance(tid, dict):
        module = tid.get("module_name", "")
        entity = tid.get("entity_name", "")
        return f"{module}:{entity}" if module and entity else "unknown"
    return str(tid) if tid else "unknown"


def traverse_tree(event_id: str, events_by_id: dict, depth: int = 0):
    """Preorder traversal yielding (event_id, event, depth)."""
    event = events_by_id.get(event_id)
    if not event:
        return
    yield (event_id, event, depth)
    edata = get_event_data(event)
    for child_id in edata.get("child_event_ids", []):
        yield from traverse_tree(child_id, events_by_id, depth + 1)


def get_tree_shape(event_id: str, events_by_id: dict, depth: int = 0) -> dict:
    """Build tree shape showing template + event_type + choice at each node."""
    event = events_by_id.get(event_id)
    if not event:
        return {"id": event_id, "missing": True}
    etype = get_event_type(event)
    edata = get_event_data(event)
    tid = get_template_id(edata)
    choice = edata.get("choice", "") if etype == "exercised" else ""
    node = {"depth": depth, "event_type": etype, "template_id": tid}
    if choice:
        node["choice"] = choice
    children = edata.get("child_event_ids", [])
    if children:
        node["children"] = [
            get_tree_shape(cid, events_by_id, depth + 1) for cid in children
        ]
    return node


def flatten_tree_shape(shape: dict, lines: list = None, prefix: str = "") -> list:
    """Convert tree shape dict to printable lines."""
    if lines is None:
        lines = []
    label = f"{shape.get('event_type', '?')}: {shape.get('template_id', '?')}"
    if shape.get("choice"):
        label += f" [{shape['choice']}]"
    if shape.get("missing"):
        label = f"(missing: {shape['id']})"
    lines.append(f"{prefix}{label}")
    children = shape.get("children", [])
    for i, child in enumerate(children):
        connector = "├── " if i < len(children) - 1 else "└── "
        flatten_tree_shape(child, lines, prefix + connector)
    return lines


def inventory_payload_fields(obj, path: str, store: dict, max_samples: int = 3):
    """Recursively catalog fields in a payload, storing types and samples."""
    if obj is None:
        return
    if isinstance(obj, dict):
        for key, val in obj.items():
            child_path = f"{path}.{key}" if path else key
            entry = store[child_path]
            entry["count"] = entry.get("count", 0) + 1
            if "types" not in entry:
                entry["types"] = Counter()
            entry["types"][type(val).__name__] += 1
            if "samples" not in entry:
                entry["samples"] = []
            if len(entry["samples"]) < max_samples:
                s = _trunc(val)
                if s not in entry["samples"]:
                    entry["samples"].append(s)
            if isinstance(val, dict):
                inventory_payload_fields(val, child_path, store, max_samples)
            elif isinstance(val, list) and val:
                inventory_payload_fields(val[0], f"{child_path}[]", store, max_samples)


def _trunc(val, n=80):
    s = str(val)
    return s[:n] + "..." if len(s) > n else s


# ═══════════════════════════════════════════════════════════════════════════════
#  Sample Window Result
# ═══════════════════════════════════════════════════════════════════════════════

class SampleResult:
    """Accumulates findings from a single sample window."""

    def __init__(self, migration_id: int, label: str):
        self.migration_id = migration_id
        self.label = label
        self.updates_count = 0
        self.events_count = 0
        self.updates_with_events = 0
        self.updates_without_events = 0
        self.time_range = {"earliest": None, "latest": None}
        self.template_counts = Counter()
        self.template_event_counts = Counter()  # (template, event_type) -> count
        self.choice_counts = Counter()           # (template, choice) -> count
        self.package_names = Counter()
        self.synchronizer_ids = Counter()
        self.tree_depths = Counter()
        self.payload_fields = defaultdict(dict)  # template_key -> {field -> info}
        self.sample_trees = []                   # up to 5 full tree shapes per window
        self.raw_updates = []                    # first few raw updates for reference

    def process_updates(self, updates: list):
        for update in updates:
            self._process_one(update)
            if len(self.raw_updates) < 3:
                self.raw_updates.append(update)

    def _process_one(self, update: dict):
        self.updates_count += 1
        record_time = update.get("record_time", "")
        sync_id = update.get("synchronizer_id", "")
        if sync_id:
            self.synchronizer_ids[sync_id] += 1
        if record_time:
            if not self.time_range["earliest"] or record_time < self.time_range["earliest"]:
                self.time_range["earliest"] = record_time
            if not self.time_range["latest"] or record_time > self.time_range["latest"]:
                self.time_range["latest"] = record_time

        root_ids, events_by_id = get_update_events(update)

        if not root_ids and not events_by_id:
            self.updates_without_events += 1
            # Even without tree structure, try to count events from flat events_by_id
            # (some updates may have events_by_id but no root_event_ids)
            return

        if events_by_id and not root_ids:
            # Has events but no root IDs — process all events flat
            self.updates_with_events += 1
            for event_id, event in events_by_id.items():
                self._process_event(event_id, event, 0)
            return

        self.updates_with_events += 1

        # Save tree shapes (up to 5 per sample)
        if len(self.sample_trees) < 5:
            for rid in root_ids[:2]:  # max 2 roots per update
                self.sample_trees.append(get_tree_shape(rid, events_by_id))

        for rid in root_ids:
            for event_id, event, depth in traverse_tree(rid, events_by_id):
                self._process_event(event_id, event, depth)

    def _process_event(self, event_id: str, event: dict, depth: int):
        self.events_count += 1
        self.tree_depths[depth] += 1

        etype = get_event_type(event)
        edata = get_event_data(event)
        tid = get_template_id(edata)
        choice = edata.get("choice", "") if etype == "exercised" else ""
        pkg = edata.get("package_name", "")

        self.template_counts[tid] += 1
        self.template_event_counts[(tid, etype)] += 1
        if choice:
            self.choice_counts[(tid, choice)] += 1
        if pkg:
            self.package_names[pkg] += 1

        # Payload field inventory for top templates
        template_key = f"{tid}:{etype}"
        if choice:
            template_key = f"{tid}:{choice}"
        if etype == "created":
            args = edata.get("create_arguments", {})
            if args and isinstance(args, dict):
                inventory_payload_fields(args, "", self.payload_fields[template_key])
        elif etype == "exercised" and choice:
            cargs = edata.get("choice_argument", {})
            if cargs and isinstance(cargs, dict):
                inventory_payload_fields(
                    cargs, "", self.payload_fields[f"{template_key}:choice_arg"]
                )
            eres = edata.get("exercise_result", {})
            if eres and isinstance(eres, dict):
                inventory_payload_fields(
                    eres, "", self.payload_fields[f"{template_key}:result"]
                )


# ═══════════════════════════════════════════════════════════════════════════════
#  Fetching & Sampling
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_sample(
    client: SpliceScanClient,
    migration_id: int,
    after_record_time: str,
    pages: int = 10,
    page_size: int = 500,
) -> list:
    """Fetch multiple pages starting at a time point."""
    all_updates = []
    cursor_time = after_record_time

    for page in range(pages):
        try:
            resp = client.get_updates(
                after_migration_id=migration_id,
                after_record_time=cursor_time,
                page_size=page_size,
            )
            updates = resp.get("updates", resp.get("transactions", []))
            if not updates:
                break
            all_updates.extend(updates)
            cursor_time = updates[-1].get("record_time", "")
            if len(updates) < page_size:
                # Got fewer than requested — reached end of data for this window
                break
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"    ERROR on page {page+1}: {e}")
            break

    return all_updates


# ═══════════════════════════════════════════════════════════════════════════════
#  Cross-Migration Schema Evolution Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_schema_evolution(all_results: List[SampleResult]):
    """Compare payload field structures for the same template across migrations."""
    print(f"\n{'═'*78}")
    print("  SCHEMA EVOLUTION DETECTION")
    print(f"{'═'*78}")
    print("  Comparing payload fields for the same template across migrations.")
    print("  Differences indicate contract version changes.\n")

    # Collect all template keys across all samples, grouped by migration
    migration_fields = defaultdict(lambda: defaultdict(set))
    # migration_id -> template_key -> set of field paths

    for result in all_results:
        for template_key, fields in result.payload_fields.items():
            for field_path in fields:
                migration_fields[result.migration_id][template_key].add(field_path)

    # For each template key, compare across migrations
    all_template_keys = set()
    for mig_data in migration_fields.values():
        all_template_keys.update(mig_data.keys())

    evolutions_found = 0
    for tkey in sorted(all_template_keys):
        migs_with_template = {
            mig_id: fields
            for mig_id, mig_data in migration_fields.items()
            if tkey in mig_data
            for fields in [mig_data[tkey]]
        }

        if len(migs_with_template) < 2:
            continue  # Can't compare with only one migration

        mig_ids = sorted(migs_with_template.keys())
        all_fields_union = set()
        for fields in migs_with_template.values():
            all_fields_union.update(fields)

        # Check if any migration is missing fields present in others
        has_diff = False
        for mid in mig_ids:
            missing = all_fields_union - migs_with_template[mid]
            if missing:
                has_diff = True
                break

        if has_diff:
            evolutions_found += 1
            print(f"  {tkey}:")
            for mid in mig_ids:
                present = migs_with_template[mid]
                missing = all_fields_union - present
                extra_label = f" (missing: {', '.join(sorted(missing)[:5])})" if missing else ""
                print(f"    migration {mid}: {len(present)} fields{extra_label}")
            print()

    if evolutions_found == 0:
        print("  No schema differences detected across migrations for sampled data.")
        print("  (Note: this is based on sampled pages — full data may reveal more.)")


# ═══════════════════════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════════════════════

def print_report(all_results: List[SampleResult]):
    """Print comprehensive exploration report."""

    print("\n" + "=" * 78)
    print("  CANTON ON-CHAIN DATA EXPLORATION REPORT")
    print("  Thorough Sampling Across Migrations 0-4")
    print("=" * 78)

    # ── Aggregate across all samples ──
    total_updates = sum(r.updates_count for r in all_results)
    total_events = sum(r.events_count for r in all_results)
    total_with = sum(r.updates_with_events for r in all_results)
    total_without = sum(r.updates_without_events for r in all_results)
    all_templates = Counter()
    all_template_events = Counter()
    all_choices = Counter()
    all_packages = Counter()
    all_syncs = Counter()

    for r in all_results:
        all_templates += r.template_counts
        all_template_events += r.template_event_counts
        all_choices += r.choice_counts
        all_packages += r.package_names
        all_syncs += r.synchronizer_ids

    print(f"\n  Sampling Summary:")
    print(f"    Total sample windows:       {len(all_results)}")
    print(f"    Total updates sampled:      {total_updates:,}")
    print(f"    Updates with events:        {total_with:,}")
    print(f"    Updates without events:     {total_without:,}")
    print(f"    Total events sampled:       {total_events:,}")
    print(f"    Unique template IDs:        {len(all_templates)}")
    print(f"    Unique choices:             {len(all_choices)}")
    print(f"    Unique synchronizer IDs:    {len(all_syncs)}")
    print(f"    Unique package names:       {len(all_packages)}")

    # ── Per-Migration Summaries ──
    print(f"\n{'─'*78}")
    print("  PER-MIGRATION SAMPLE RESULTS")
    print(f"{'─'*78}")

    current_mig = None
    for r in all_results:
        if r.migration_id != current_mig:
            current_mig = r.migration_id
            print(f"\n  Migration {current_mig}:")

        earliest = r.time_range["earliest"][:19] if r.time_range["earliest"] else "N/A"
        latest = r.time_range["latest"][:19] if r.time_range["latest"] else "N/A"
        print(f"    [{r.label:>10}]  {r.updates_count:>5} updates, "
              f"{r.events_count:>7} events  "
              f"({r.updates_with_events} w/ events, {r.updates_without_events} w/o)  "
              f"{earliest} → {latest}")
        if r.template_counts:
            top = ", ".join(f"{tid}({c})" for tid, c in r.template_counts.most_common(3))
            print(f"               top: {top}")

    # ── Synchronizer IDs ──
    if all_syncs:
        print(f"\n{'─'*78}")
        print("  SYNCHRONIZER IDs")
        print(f"{'─'*78}")
        for sid, count in all_syncs.most_common():
            short = sid[:65] + "..." if len(sid) > 65 else sid
            print(f"  {count:>8,}  {short}")

    # ── Template Frequency (Aggregated from Samples) ──
    if all_templates:
        print(f"\n{'─'*78}")
        print("  TEMPLATE IDs BY FREQUENCY (aggregated across all samples)")
        print(f"  Note: These are SAMPLE frequencies, not total counts over 10+ TB.")
        print(f"{'─'*78}")
        print(f"  {'Count':>10}  {'Pct':>6}  Template ID")
        print(f"  {'─'*10}  {'─'*6}  {'─'*50}")
        for tid, count in all_templates.most_common(40):
            pct = 100.0 * count / total_events if total_events else 0
            print(f"  {count:>10,}  {pct:>5.1f}%  {tid}")

    # ── Template × Event Type ──
    if all_template_events:
        print(f"\n{'─'*78}")
        print("  TEMPLATE x EVENT TYPE DISTRIBUTION")
        print(f"{'─'*78}")
        print(f"  {'Count':>10}  {'Type':<12}  Template ID")
        print(f"  {'─'*10}  {'─'*12}  {'─'*50}")
        for (tid, etype), count in all_template_events.most_common(50):
            print(f"  {count:>10,}  {etype:<12}  {tid}")

    # ── Choice Distribution ──
    if all_choices:
        print(f"\n{'─'*78}")
        print("  CHOICE DISTRIBUTION (exercised events)")
        print(f"{'─'*78}")
        print(f"  {'Count':>10}  Template ID  --  Choice")
        print(f"  {'─'*10}  {'─'*60}")
        for (tid, choice), count in all_choices.most_common(40):
            print(f"  {count:>10,}  {tid}  --  {choice}")

    # ── Template Presence by Migration ──
    print(f"\n{'─'*78}")
    print("  TEMPLATE PRESENCE BY MIGRATION")
    print(f"  (which templates appear in which migration's samples)")
    print(f"{'─'*78}")

    mig_template_presence = defaultdict(set)
    for r in all_results:
        for tid in r.template_counts:
            mig_template_presence[tid].add(r.migration_id)

    mig_ids_seen = sorted(set(r.migration_id for r in all_results))
    header = f"  {'Template ID':<55} " + " ".join(f"M{m}" for m in mig_ids_seen)
    print(header)
    print(f"  {'─'*55} " + "─" * (3 * len(mig_ids_seen)))

    for tid, count in all_templates.most_common(30):
        present = mig_template_presence[tid]
        flags = " ".join(("Y " if m in present else ". ") for m in mig_ids_seen)
        print(f"  {tid:<55} {flags}")

    # ── Tree Structure Stats ──
    all_depths = Counter()
    for r in all_results:
        all_depths += r.tree_depths

    if all_depths:
        print(f"\n{'─'*78}")
        print("  EVENT TREE DEPTH DISTRIBUTION")
        print(f"{'─'*78}")
        max_count = max(all_depths.values()) if all_depths else 1
        for depth in sorted(all_depths.keys()):
            count = all_depths[depth]
            bar_len = int(60 * count / max_count) if max_count > 0 else 0
            bar = "█" * bar_len
            print(f"    depth {depth:>2}: {count:>8,}  {bar}")

    # ── Sample Tree Shapes ──
    print(f"\n{'─'*78}")
    print("  SAMPLE EVENT TREE STRUCTURES (from each migration)")
    print(f"{'─'*78}")
    shown_migs = set()
    for r in all_results:
        if r.sample_trees and r.migration_id not in shown_migs:
            shown_migs.add(r.migration_id)
            print(f"\n  Migration {r.migration_id} [{r.label}]:")
            for tree in r.sample_trees[:2]:
                lines = flatten_tree_shape(tree)
                for line in lines:
                    print(f"    {line}")
                print()

    # ── Package Names ──
    if all_packages:
        print(f"\n{'─'*78}")
        print("  PACKAGE NAMES")
        print(f"{'─'*78}")
        for pkg, count in all_packages.most_common(15):
            print(f"  {count:>10,}  {pkg}")


def print_categorization(all_results: List[SampleResult]):
    """Print categorized view of transaction types discovered."""

    all_templates = Counter()
    all_choices = Counter()
    for r in all_results:
        all_templates += r.template_counts
        all_choices += r.choice_counts

    total_events = sum(r.events_count for r in all_results)

    CATEGORIES = {
        "Token Operations (CC)": {
            "templates": ["Splice.Amulet:Amulet", "Splice.AmuletRules:AmuletRules"],
            "desc": "Canton Coin creation, transfer, burning, and rules governance",
        },
        "Traffic Purchases": {
            "templates": ["Splice.DecentralizedSynchronizer:MemberTraffic"],
            "choices": [("Splice.AmuletRules:AmuletRules", "AmuletRules_BuyMemberTraffic")],
            "desc": "Buying synchronizer bandwidth with CC ($17/MB)",
        },
        "Mining Rounds": {
            "templates": [
                "Splice.Round:OpenMiningRound",
                "Splice.Round:IssuingMiningRound",
                "Splice.Round:ClosedMiningRound",
                "Splice.Round:SummarizingMiningRound",
            ],
            "desc": "Mining round lifecycle (open -> issuing -> closed, ~10 min intervals)",
        },
        "Rewards (Coupons)": {
            "templates": [
                "Splice.Amulet:AppRewardCoupon",
                "Splice.Amulet:ValidatorRewardCoupon",
                "Splice.Amulet:ValidatorFaucetCoupon",
                "Splice.Amulet:SvRewardCoupon",
            ],
            "desc": "Reward coupons for validators, apps, SVs, faucets",
        },
        "Validators": {
            "templates": [
                "Splice.ValidatorLicense:ValidatorLicense",
                "Splice.Validator:ValidatorRight",
            ],
            "desc": "Validator onboarding and license management",
        },
        "Governance (DSO)": {
            "templates": [
                "Splice.DsoRules:VoteRequest",
                "Splice.DsoRules:Vote",
                "Splice.DsoRules:DsoRules",
                "Splice.DsoRules:Confirmation",
            ],
            "desc": "DSO governance proposals and voting",
        },
        "Name Service (ANS)": {
            "templates": [
                "Splice.Ans:AnsEntry",
                "Splice.AnsRules:AnsRules",
                "Splice.Ans:AnsEntryContext",
            ],
            "desc": "Amulet Name Service registrations and rules",
        },
        "CC Transfers": {
            "choices": [("Splice.AmuletRules:AmuletRules", "AmuletRules_Transfer")],
            "desc": "CC token transfers between parties (tiered fees)",
        },
        "CC Minting": {
            "choices": [("Splice.AmuletRules:AmuletRules", "AmuletRules_Mint")],
            "desc": "CC token minting/issuance at round close",
        },
    }

    print(f"\n{'═'*78}")
    print("  TRANSACTION TYPE CATEGORIZATION (from samples)")
    print(f"{'═'*78}")

    categorized_templates = set()
    for cat, info in CATEGORIES.items():
        cat_count = 0
        for tid in info.get("templates", []):
            cat_count += all_templates.get(tid, 0)
            categorized_templates.add(tid)
        for tid, ch in info.get("choices", []):
            cat_count += all_choices.get((tid, ch), 0)

        if cat_count > 0:
            pct = 100.0 * cat_count / total_events if total_events else 0
            print(f"\n  {cat}  ({cat_count:,} events, {pct:.1f}%)")
            print(f"    {info['desc']}")
            for tid in info.get("templates", []):
                c = all_templates.get(tid, 0)
                if c:
                    print(f"      {tid}: {c:,}")
            for tid, ch in info.get("choices", []):
                c = all_choices.get((tid, ch), 0)
                if c:
                    print(f"      {tid} [{ch}]: {c:,}")

    # Uncategorized
    uncategorized = {
        tid: c for tid, c in all_templates.items()
        if tid not in categorized_templates and tid != "unknown" and c >= 2
    }
    if uncategorized:
        print(f"\n  UNCATEGORIZED TEMPLATES:")
        for tid in sorted(uncategorized, key=uncategorized.get, reverse=True):
            print(f"    {uncategorized[tid]:>8,}  {tid}")


def save_json_report(all_results: List[SampleResult], output_dir: str):
    """Save structured JSON report."""

    all_templates = Counter()
    all_choices = Counter()
    for r in all_results:
        all_templates += r.template_counts
        all_choices += r.choice_counts

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "strategy": "thorough_sampling",
        "description": (
            "Transaction type exploration via thorough sampling across migrations 0-4. "
            "Frequencies are sample-based estimates, not global counts."
        ),
        "sampling_summary": {
            "total_windows": len(all_results),
            "total_updates_sampled": sum(r.updates_count for r in all_results),
            "total_events_sampled": sum(r.events_count for r in all_results),
            "updates_with_events": sum(r.updates_with_events for r in all_results),
            "updates_without_events": sum(r.updates_without_events for r in all_results),
        },
        "per_migration_samples": [
            {
                "migration_id": r.migration_id,
                "label": r.label,
                "updates": r.updates_count,
                "events": r.events_count,
                "updates_with_events": r.updates_with_events,
                "updates_without_events": r.updates_without_events,
                "time_range": r.time_range,
                "top_templates": [
                    {"template_id": tid, "count": c}
                    for tid, c in r.template_counts.most_common(20)
                ],
                "top_choices": [
                    {"template_id": tid, "choice": ch, "count": c}
                    for (tid, ch), c in r.choice_counts.most_common(15)
                ],
                "synchronizer_ids": dict(r.synchronizer_ids),
                "sample_trees": r.sample_trees[:3],
            }
            for r in all_results
        ],
        "aggregated_template_frequency": [
            {"template_id": tid, "sample_count": c}
            for tid, c in all_templates.most_common()
        ],
        "aggregated_choice_frequency": [
            {"template_id": tid, "choice": ch, "sample_count": c}
            for (tid, ch), c in all_choices.most_common()
        ],
        "payload_field_inventories": {},
    }

    # Add payload field inventories for key templates
    for r in all_results:
        for tkey, fields in r.payload_fields.items():
            if tkey not in report["payload_field_inventories"]:
                report["payload_field_inventories"][tkey] = {}
            for fpath, info in fields.items():
                entry = report["payload_field_inventories"][tkey].get(fpath, {
                    "count": 0, "types": {}, "samples": [], "migrations_seen": []
                })
                entry["count"] += info.get("count", 0)
                for t, c in info.get("types", {}).items():
                    entry["types"][t] = entry["types"].get(t, 0) + c
                for s in info.get("samples", []):
                    if s not in entry["samples"] and len(entry["samples"]) < 3:
                        entry["samples"].append(s)
                if r.migration_id not in entry.get("migrations_seen", []):
                    entry.setdefault("migrations_seen", []).append(r.migration_id)
                report["payload_field_inventories"][tkey][fpath] = entry

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "transaction_type_exploration.json")
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  JSON report saved to: {output_path}")

    # Also save raw update samples for offline reference
    raw_path = os.path.join(output_dir, "raw_update_samples.json")
    raw_samples = {}
    for r in all_results:
        key = f"migration_{r.migration_id}_{r.label}"
        raw_samples[key] = {
            "migration_id": r.migration_id,
            "label": r.label,
            "updates": r.raw_updates,
        }
    with open(raw_path, "w") as f:
        json.dump(raw_samples, f, indent=2, default=str)
    print(f"  Raw update samples saved to: {raw_path}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Thorough sampling exploration of Canton on-chain data"
    )
    parser.add_argument(
        "--pages-per-sample", type=int, default=10,
        help="Pages to fetch per sample window (default: 10)",
    )
    parser.add_argument(
        "--page-size", type=int, default=500,
        help="Updates per page (default: 500, max: 500)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="scripts/output/exploration",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--migration", type=int, nargs="*", default=None,
        help="Specific migrations to explore (default: all 0-4)",
    )
    parser.add_argument(
        "--base-url", type=str, default=BASE_URL,
        help="Scan API base URL",
    )
    args = parser.parse_args()

    migrations = args.migration if args.migration is not None else list(SAMPLE_POINTS.keys())

    total_points = sum(len(SAMPLE_POINTS.get(m, [])) for m in migrations)
    est_calls = total_points * args.pages_per_sample
    est_updates = est_calls * args.page_size

    print("=" * 78)
    print("  CANTON ON-CHAIN DATA EXPLORATION")
    print("  Strategy: Thorough Sampling Across Migrations")
    print(f"  Migrations: {migrations}")
    print(f"  Sample windows: {total_points}")
    print(f"  Pages/sample: {args.pages_per_sample}, Page size: {args.page_size}")
    print(f"  Estimated API calls: ~{est_calls}")
    print(f"  Estimated updates to sample: ~{est_updates:,}")
    print(f"  Estimated runtime: ~{est_calls * 0.5 / 60:.0f}-{est_calls * 1.0 / 60:.0f} minutes")
    print("=" * 78)

    client = SpliceScanClient(base_url=args.base_url, timeout=60)

    # Health check
    print("\nChecking API health...")
    if not client.health_check():
        print("ERROR: Cannot reach Scan API. Ensure you're running from a whitelisted VM.")
        return
    print("API is healthy.\n")

    all_results = []
    start_time = time.time()
    windows_done = 0

    for mig_id in migrations:
        points = SAMPLE_POINTS.get(mig_id, [("start", "1970-01-01T00:00:00Z")])

        print(f"\n{'═'*60}")
        print(f"  Migration {mig_id}: {len(points)} sample point(s)")
        print(f"{'═'*60}")

        for label, after_rt in points:
            windows_done += 1
            elapsed = time.time() - start_time
            print(f"\n  [{label}] after_record_time={after_rt}  "
                  f"(window {windows_done}/{total_points}, {elapsed:.0f}s elapsed)")

            updates = fetch_sample(
                client, mig_id, after_rt,
                pages=args.pages_per_sample,
                page_size=args.page_size,
            )

            result = SampleResult(mig_id, label)
            result.process_updates(updates)
            all_results.append(result)

            if result.updates_count > 0:
                earliest = result.time_range["earliest"][:19] if result.time_range["earliest"] else "N/A"
                latest = result.time_range["latest"][:19] if result.time_range["latest"] else "N/A"
                print(f"    -> {result.updates_count} updates, {result.events_count} events "
                      f"({result.updates_with_events} w/ events, {result.updates_without_events} w/o)")
                print(f"    -> time: {earliest} -> {latest}")
                print(f"    -> templates: {len(result.template_counts)} unique")
                if result.template_counts:
                    top = ", ".join(f"{tid}({c})" for tid, c in result.template_counts.most_common(3))
                    print(f"    -> top: {top}")
            else:
                print(f"    -> No data (migration may not have started/ended at this time)")

    elapsed = time.time() - start_time
    print(f"\n\nSampling complete in {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # Reports
    print_report(all_results)
    print_categorization(all_results)
    detect_schema_evolution(all_results)
    save_json_report(all_results, args.output_dir)

    client.close()
    print(f"\nExploration complete.")


if __name__ == "__main__":
    main()
