#!/usr/bin/env python3
"""
Sample a few updates from the v2/updates endpoint and dump the raw JSON
structure so we can verify the data schema before rebuilding the pipeline.

Fetches from multiple migrations to detect schema evolution.

Usage:
    python scripts/sample_updates_schema.py
    python scripts/sample_updates_schema.py --page-size 5 --migrations 3 4
    python scripts/sample_updates_schema.py --output scripts/output/sample_schema.json
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.canton_scan_client import SpliceScanClient


DEFAULT_BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"


def collect_field_info(obj, prefix="", depth=0):
    """Recursively collect field names, types, and sample values."""
    fields = {}
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            val_type = type(val).__name__
            sample = val
            if isinstance(val, str) and len(val) > 120:
                sample = val[:120] + "..."
            elif isinstance(val, dict):
                sample = f"{{...}} ({len(val)} keys)"
            elif isinstance(val, list):
                sample = f"[...] ({len(val)} items)"

            fields[path] = {"type": val_type, "sample": sample}

            # Recurse into dicts and first list element
            if isinstance(val, dict):
                fields.update(collect_field_info(val, path, depth + 1))
            elif isinstance(val, list) and val:
                first = val[0]
                if isinstance(first, dict):
                    fields.update(collect_field_info(first, f"{path}[0]", depth + 1))
                else:
                    fields[f"{path}[0]"] = {"type": type(first).__name__, "sample": first}
    return fields


def sample_migration(client, migration_id, page_size):
    """Fetch first page of a migration and return the raw response."""
    try:
        result = client.get_updates(
            after_migration_id=migration_id,
            after_record_time="1970-01-01T00:00:00Z",
            page_size=page_size,
        )
        return result
    except Exception as e:
        print(f"  ERROR fetching migration {migration_id}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Sample v2/updates schema")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--page-size", type=int, default=3,
                        help="Updates per page (small is fine — we just need structure)")
    parser.add_argument("--migrations", nargs="+", type=int, default=[0, 3, 4],
                        help="Migration IDs to sample (default: 0 3 4)")
    parser.add_argument("--output", default=None,
                        help="Save full JSON to file (optional)")
    args = parser.parse_args()

    client = SpliceScanClient(base_url=args.base_url, timeout=30)
    all_samples = {}

    for mig in args.migrations:
        print(f"\n{'='*70}")
        print(f"  Migration {mig}  (page_size={args.page_size})")
        print(f"{'='*70}")

        result = sample_migration(client, mig, args.page_size)
        if result is None:
            continue

        updates = result.get("updates") or result.get("transactions", [])
        print(f"  Got {len(updates)} update(s)")

        if not updates:
            continue

        all_samples[f"migration_{mig}"] = updates

        # Analyze first update structure
        txn = updates[0]
        print(f"\n  --- Top-level transaction fields ---")
        for key, val in txn.items():
            val_type = type(val).__name__
            if isinstance(val, str) and len(val) > 80:
                print(f"    {key}: ({val_type}) {val[:80]}...")
            elif isinstance(val, dict):
                print(f"    {key}: ({val_type}) {len(val)} keys")
            elif isinstance(val, list):
                print(f"    {key}: ({val_type}) {len(val)} items")
            else:
                print(f"    {key}: ({val_type}) {val}")

        # Analyze events_by_id structure
        events_by_id = txn.get("events_by_id", {})
        if events_by_id:
            print(f"\n  --- events_by_id: {len(events_by_id)} event(s) ---")
            for event_id, event_data in list(events_by_id.items())[:5]:
                print(f"\n    Event: {event_id}")
                # Determine type
                if "create_arguments" in event_data:
                    etype = "CREATED"
                elif "choice" in event_data:
                    etype = "EXERCISED"
                elif event_data.get("archived"):
                    etype = "ARCHIVED"
                else:
                    etype = "UNKNOWN"
                print(f"      type: {etype}")

                for key, val in event_data.items():
                    val_type = type(val).__name__
                    if key in ("create_arguments", "choice_argument", "exercise_result"):
                        # Show just the top-level keys of large JSON payloads
                        if isinstance(val, dict):
                            top_keys = list(val.keys())[:10]
                            print(f"      {key}: ({val_type}) keys={top_keys}")
                        else:
                            print(f"      {key}: ({val_type}) {str(val)[:80]}")
                    elif isinstance(val, list):
                        print(f"      {key}: ({val_type}) {len(val)} items, first={val[0] if val else 'N/A'}")
                    elif isinstance(val, str) and len(val) > 80:
                        print(f"      {key}: ({val_type}) {val[:80]}...")
                    else:
                        print(f"      {key}: ({val_type}) {val}")

        # Collect all unique field paths across all events in this page
        print(f"\n  --- All unique event field paths (across {len(updates)} update(s)) ---")
        all_fields = set()
        event_type_counts = {"created": 0, "exercised": 0, "archived": 0, "unknown": 0}
        for u in updates:
            for eid, edata in u.get("events_by_id", {}).items():
                if "create_arguments" in edata:
                    event_type_counts["created"] += 1
                elif "choice" in edata:
                    event_type_counts["exercised"] += 1
                elif edata.get("archived"):
                    event_type_counts["archived"] += 1
                else:
                    event_type_counts["unknown"] += 1
                all_fields.update(edata.keys())

        print(f"    Event type counts: {event_type_counts}")
        print(f"    All event-level fields: {sorted(all_fields)}")

    # Save full JSON if requested
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(all_samples, f, indent=2, default=str)
        print(f"\n  Full JSON saved to: {args.output}")

    # Summary
    print(f"\n{'='*70}")
    print(f"  SCHEMA SUMMARY")
    print(f"{'='*70}")
    print(f"\n  Transaction-level fields (from /v2/updates):")
    print(f"    update_id, record_time, synchronizer_id, migration_id,")
    print(f"    effective_at, root_event_ids, events_by_id, trace_context")
    print(f"\n  Event-level fields (inside events_by_id):")

    # Collect across all migrations
    all_event_fields = set()
    for mig_key, updates in all_samples.items():
        for u in updates:
            for eid, edata in u.get("events_by_id", {}).items():
                all_event_fields.update(edata.keys())

    for field in sorted(all_event_fields):
        print(f"    - {field}")

    print(f"\n  Total unique event fields across all sampled migrations: {len(all_event_fields)}")


if __name__ == "__main__":
    main()
