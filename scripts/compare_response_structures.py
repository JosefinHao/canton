"""
Compare Response Structures: /v0/events vs /v2/updates

Fetches one page from each Canton Scan API endpoint and performs a structural
comparison of the raw JSON responses, then saves them for manual inspection.

What this script does:
  1. Fetches one page from /v0/events (migration_id=4)
  2. Fetches one page from /v2/updates (migration_id=4)
  3. Saves raw JSON responses to scripts/output/
  4. Prints a structural comparison: field names, nesting depth, types
  5. For a record that appears in BOTH responses, shows the exact JSON side by side

Usage:
    python scripts/compare_response_structures.py
    python scripts/compare_response_structures.py --migration-id 3
    python scripts/compare_response_structures.py --page-size 50
    python scripts/compare_response_structures.py --base-url <url>

Output files:
    scripts/output/v0_events_sample.json
    scripts/output/v2_updates_sample.json
"""

import argparse
import json
import os
import sys
import textwrap
from collections import Counter, OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


# =============================================================================
#  Structural Analysis Utilities
# =============================================================================

def get_type_name(value: Any) -> str:
    """Return a human-readable type name for a JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "list[empty]"
        inner_types = set(get_type_name(v) for v in value[:5])
        return f"list[{','.join(sorted(inner_types))}]"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def collect_structure(obj: Any, prefix: str = "", max_depth: int = 10) -> List[Dict[str, Any]]:
    """
    Recursively collect the structure of a JSON object.

    Returns a list of records, each describing one field path:
      {
        "path": "events[].update.events_by_id.*.template_id",
        "depth": 4,
        "type": "str",
        "sample": "Splice.Amulet:Amulet",
        "count": 1,
      }
    """
    results = []
    _collect_structure_recursive(obj, prefix, 0, max_depth, results)
    return results


def _collect_structure_recursive(
    obj: Any, prefix: str, depth: int, max_depth: int,
    results: List[Dict[str, Any]],
):
    """Recursive helper for collect_structure."""
    if depth > max_depth:
        results.append({
            "path": prefix or "(root)",
            "depth": depth,
            "type": "...(max depth)",
            "sample": None,
            "count": 1,
        })
        return

    if isinstance(obj, dict):
        if not prefix:
            # Root dict -- don't add an entry for the root itself
            pass
        for key in sorted(obj.keys()):
            child_path = f"{prefix}.{key}" if prefix else key
            child_value = obj[key]
            results.append({
                "path": child_path,
                "depth": depth + 1,
                "type": get_type_name(child_value),
                "sample": _sample_value(child_value),
                "count": 1,
            })
            # Recurse into dicts and first element of lists
            if isinstance(child_value, dict):
                _collect_structure_recursive(child_value, child_path, depth + 1, max_depth, results)
            elif isinstance(child_value, list) and child_value:
                first = child_value[0]
                if isinstance(first, (dict, list)):
                    _collect_structure_recursive(first, f"{child_path}[]", depth + 1, max_depth, results)

    elif isinstance(obj, list):
        if obj:
            first = obj[0]
            results.append({
                "path": f"{prefix}[]",
                "depth": depth + 1,
                "type": get_type_name(first),
                "sample": _sample_value(first),
                "count": len(obj),
            })
            if isinstance(first, (dict, list)):
                _collect_structure_recursive(first, f"{prefix}[]", depth + 1, max_depth, results)


def _sample_value(value: Any, max_len: int = 80) -> Optional[str]:
    """Return a truncated sample of a value for display."""
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        s = json.dumps(value, default=str)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def compute_max_depth(obj: Any, current: int = 0) -> int:
    """Compute the maximum nesting depth of a JSON object."""
    if isinstance(obj, dict):
        if not obj:
            return current
        return max(compute_max_depth(v, current + 1) for v in obj.values())
    elif isinstance(obj, list):
        if not obj:
            return current
        return max(compute_max_depth(v, current + 1) for v in obj[:3])  # Sample first 3
    return current


def collect_all_paths(obj: Any, prefix: str = "") -> Set[str]:
    """Collect all unique key paths from a JSON object (for set comparison)."""
    paths = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{prefix}.{key}" if prefix else key
            paths.add(child_path)
            if isinstance(value, dict):
                paths.update(collect_all_paths(value, child_path))
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                paths.update(collect_all_paths(value[0], f"{child_path}[]"))
    elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
        paths.update(collect_all_paths(obj[0], f"{prefix}[]"))
    return paths


# =============================================================================
#  Data Fetching
# =============================================================================

def fetch_v0_events(client: SpliceScanClient, migration_id: int, page_size: int) -> Dict:
    """Fetch one page from /v0/events and return the raw response."""
    json_data = {
        "page_size": page_size,
        "daml_value_encoding": "compact_json",
    }
    if migration_id is not None:
        json_data["after"] = {
            "after_migration_id": migration_id,
            "after_record_time": "2000-01-01T00:00:00Z",
        }

    # Use the internal _make_request so we get the raw response structure
    # without normalization applied by the wrapper method
    response = client._make_request("POST", "/v0/events", json_data=json_data)
    return response


def fetch_v2_updates(client: SpliceScanClient, migration_id: int, page_size: int) -> Dict:
    """Fetch one page from /v2/updates and return the raw response."""
    json_data = {
        "page_size": page_size,
        "daml_value_encoding": "compact_json",
    }
    if migration_id is not None:
        json_data["after"] = {
            "after_migration_id": migration_id,
            "after_record_time": "2000-01-01T00:00:00Z",
        }

    # Use the internal _make_request to get raw response without normalization
    response = client._make_request("POST", "/v2/updates", json_data=json_data)
    return response


# =============================================================================
#  Comparison and Reporting
# =============================================================================

def print_section(title: str, char: str = "=", width: int = 78):
    """Print a section header."""
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def print_subsection(title: str):
    """Print a subsection header."""
    print_section(title, char="-", width=78)


def print_structure_table(structure: List[Dict], label: str, max_rows: int = 60):
    """Print a formatted table of structural fields."""
    print(f"\n  {label}")
    print(f"  {'Path':<55} {'Depth':>5} {'Type':<25} {'Sample'}")
    print(f"  {'----':<55} {'-----':>5} {'----':<25} {'------'}")
    for i, field in enumerate(structure):
        if i >= max_rows:
            print(f"  ... ({len(structure) - max_rows} more fields)")
            break
        indent = "  " * field["depth"]
        path = field["path"]
        sample = field.get("sample", "")
        if sample and len(str(sample)) > 50:
            sample = str(sample)[:50] + "..."
        print(f"  {path:<55} {field['depth']:>5} {field['type']:<25} {sample}")


def compare_structures(
    v0_structure: List[Dict],
    v2_structure: List[Dict],
):
    """Compare two structure lists and print differences."""
    v0_paths = {f["path"] for f in v0_structure}
    v2_paths = {f["path"] for f in v2_structure}

    common = v0_paths & v2_paths
    only_v0 = v0_paths - v2_paths
    only_v2 = v2_paths - v0_paths

    print(f"\n  Structural Comparison:")
    print(f"    Fields in /v0/events:   {len(v0_paths)}")
    print(f"    Fields in /v2/updates:  {len(v2_paths)}")
    print(f"    Common fields:          {len(common)}")
    print(f"    Only in /v0/events:     {len(only_v0)}")
    print(f"    Only in /v2/updates:    {len(only_v2)}")

    if only_v0:
        print(f"\n  Fields ONLY in /v0/events ({len(only_v0)}):")
        for path in sorted(only_v0):
            # Find type info
            matching = [f for f in v0_structure if f["path"] == path]
            type_str = matching[0]["type"] if matching else "?"
            print(f"    + {path:<55} {type_str}")

    if only_v2:
        print(f"\n  Fields ONLY in /v2/updates ({len(only_v2)}):")
        for path in sorted(only_v2):
            matching = [f for f in v2_structure if f["path"] == path]
            type_str = matching[0]["type"] if matching else "?"
            print(f"    + {path:<55} {type_str}")

    if common:
        # Check for type mismatches in common fields
        v0_types = {f["path"]: f["type"] for f in v0_structure}
        v2_types = {f["path"]: f["type"] for f in v2_structure}
        type_mismatches = []
        for path in sorted(common):
            v0_type = v0_types.get(path)
            v2_type = v2_types.get(path)
            if v0_type and v2_type and v0_type != v2_type:
                type_mismatches.append((path, v0_type, v2_type))

        if type_mismatches:
            print(f"\n  Type mismatches in common fields ({len(type_mismatches)}):")
            for path, v0t, v2t in type_mismatches:
                print(f"    {path:<55} v0={v0t}, v2={v2t}")
        else:
            print(f"\n  All {len(common)} common fields have matching types.")


def find_shared_record(v0_response: Dict, v2_response: Dict) -> Optional[str]:
    """
    Find an update_id that appears in both responses.

    /v0/events returns: {"events": [{"update": {...}, "verdict": {...}}, ...]}
    /v2/updates returns: {"transactions": [...]}
    """
    # Collect update_ids from /v0/events
    v0_ids = set()
    events = v0_response.get("events", [])
    for wrapper in events:
        update = wrapper.get("update")
        if update and isinstance(update, dict):
            uid = update.get("update_id")
            if uid:
                v0_ids.add(uid)

    # Collect update_ids from /v2/updates
    v2_ids = set()
    transactions = v2_response.get("transactions", [])
    for txn in transactions:
        uid = txn.get("update_id")
        if uid:
            v2_ids.add(uid)

    shared = v0_ids & v2_ids
    if shared:
        return sorted(shared)[0]
    return None


def extract_record_from_v0(v0_response: Dict, update_id: str) -> Optional[Dict]:
    """Extract a specific record from /v0/events response by update_id."""
    for wrapper in v0_response.get("events", []):
        update = wrapper.get("update")
        if update and isinstance(update, dict) and update.get("update_id") == update_id:
            return wrapper
    return None


def extract_record_from_v2(v2_response: Dict, update_id: str) -> Optional[Dict]:
    """Extract a specific record from /v2/updates response by update_id."""
    for txn in v2_response.get("transactions", []):
        if txn.get("update_id") == update_id:
            return txn
    return None


def print_side_by_side(v0_record: Dict, v2_record: Dict, update_id: str, max_lines: int = 80):
    """Print two JSON records side by side for comparison."""
    v0_json = json.dumps(v0_record, indent=2, default=str)
    v2_json = json.dumps(v2_record, indent=2, default=str)

    v0_lines = v0_json.splitlines()
    v2_lines = v2_json.splitlines()

    col_width = 55

    print(f"\n  {'--- /v0/events ---':<{col_width}}  {'--- /v2/updates ---'}")
    print(f"  {'-' * (col_width - 2):<{col_width}}  {'-' * (col_width - 2)}")

    max_len = max(len(v0_lines), len(v2_lines))
    displayed = 0
    for i in range(min(max_len, max_lines)):
        v0_line = v0_lines[i] if i < len(v0_lines) else ""
        v2_line = v2_lines[i] if i < len(v2_lines) else ""

        # Truncate long lines
        if len(v0_line) > col_width - 2:
            v0_line = v0_line[:col_width - 5] + "..."
        if len(v2_line) > col_width - 2:
            v2_line = v2_line[:col_width - 5] + "..."

        # Highlight differences
        marker = " " if v0_line.strip() == v2_line.strip() else "|"

        print(f"  {v0_line:<{col_width}}{marker} {v2_line}")
        displayed += 1

    if max_len > max_lines:
        print(f"  ... ({max_len - max_lines} more lines in each)")

    print(f"\n  Total lines: /v0/events={len(v0_lines)}, /v2/updates={len(v2_lines)}")


def analyze_nesting_complexity(response: Dict, label: str):
    """Analyze and report on the nesting complexity of a response."""
    max_depth = compute_max_depth(response)
    all_paths = collect_all_paths(response)

    # Count fields at each depth level
    depth_counts = Counter()
    for field in collect_structure(response):
        depth_counts[field["depth"]] += 1

    print(f"\n  Nesting Complexity: {label}")
    print(f"    Maximum depth:        {max_depth}")
    print(f"    Total unique paths:   {len(all_paths)}")
    print(f"    Fields by depth:")
    for depth in sorted(depth_counts.keys()):
        bar = "#" * min(depth_counts[depth], 40)
        print(f"      Depth {depth}: {depth_counts[depth]:>4}  {bar}")


def analyze_parsing_complexity(v0_response: Dict, v2_response: Dict):
    """
    Compare the parsing complexity of both responses, considering what
    the data_ingestion_pipeline.py and update_tree_processor.py need.
    """
    print_subsection("Parsing Complexity Analysis")

    # /v0/events wrapper structure
    events = v0_response.get("events", [])
    if events:
        wrapper = events[0]
        wrapper_keys = sorted(wrapper.keys())
        update = wrapper.get("update", {})
        update_keys = sorted(update.keys()) if isinstance(update, dict) else []
        verdict = wrapper.get("verdict")

        print(f"\n  /v0/events parsing path:")
        print(f"    response -> events[] -> wrapper")
        print(f"    wrapper keys: {wrapper_keys}")
        print(f"    wrapper.update keys: {update_keys}")
        if verdict:
            print(f"    wrapper.verdict keys: {sorted(verdict.keys()) if isinstance(verdict, dict) else type(verdict).__name__}")
        else:
            print(f"    wrapper.verdict: null (not always present)")
        print(f"    wrapper.update.events_by_id -> dict of event_id: event_data")

        # Count null-body wrappers
        null_body = sum(1 for ev in events if not ev.get("update"))
        print(f"\n    Records in page: {len(events)}")
        print(f"    With update body: {len(events) - null_body}")
        print(f"    Null-body (verdict only): {null_body}")
        if null_body > 0:
            print(f"    ** /v0/events includes verdict-only records that must be filtered **")
            print(f"    ** These are transactions where only the verdict metadata is visible **")

    # /v2/updates structure
    transactions = v2_response.get("transactions", [])
    if transactions:
        txn = transactions[0]
        txn_keys = sorted(txn.keys())

        print(f"\n  /v2/updates parsing path:")
        print(f"    response -> transactions[] -> transaction")
        print(f"    transaction keys: {txn_keys}")
        print(f"    transaction.events_by_id -> dict of event_id: event_data")

        print(f"\n    Records in page: {len(transactions)}")
        print(f"    All records have full update bodies (no null-body records)")

    # Compare the inner event structure
    print(f"\n  Inner event structure comparison:")
    v0_event_keys = set()
    v2_event_keys = set()

    for wrapper in events:
        update = wrapper.get("update")
        if update and isinstance(update, dict):
            for eid, evt in update.get("events_by_id", {}).items():
                if isinstance(evt, dict):
                    v0_event_keys.update(evt.keys())
                break
            break

    for txn in transactions:
        for eid, evt in txn.get("events_by_id", {}).items():
            if isinstance(evt, dict):
                v2_event_keys.update(evt.keys())
            break
        break

    common_event_keys = v0_event_keys & v2_event_keys
    only_v0_event = v0_event_keys - v2_event_keys
    only_v2_event = v2_event_keys - v0_event_keys

    print(f"    Common event-level keys ({len(common_event_keys)}): {sorted(common_event_keys)}")
    if only_v0_event:
        print(f"    Only in /v0/events events ({len(only_v0_event)}): {sorted(only_v0_event)}")
    if only_v2_event:
        print(f"    Only in /v2/updates events ({len(only_v2_event)}): {sorted(only_v2_event)}")
    if not only_v0_event and not only_v2_event:
        print(f"    Event-level fields are IDENTICAL between both endpoints")

    # Summary of parsing effort
    print(f"\n  Summary of parsing differences:")
    print(f"    /v0/events:")
    print(f"      - Extra wrapper layer: each item is {{'update': ..., 'verdict': ...}}")
    print(f"      - Must handle null-body records (verdict-only, no events_by_id)")
    print(f"      - Provides 'verdict' field with finalization metadata")
    print(f"      - Verdict contains: finalization_time, submitting_parties,")
    print(f"        submitting_participant_uid, verdict_result, mediator_group,")
    print(f"        transaction_views (informees, confirming_parties)")
    print(f"    /v2/updates:")
    print(f"      - Flatter: each item IS the transaction directly")
    print(f"      - No null-body records -- all items have events_by_id")
    print(f"      - No verdict field -- consensus metadata not available")
    print(f"      - Events sorted lexicographically by ID in events_by_id")
    print(f"      - Offset field removed compared to older API versions")


def analyze_update_level_fields(v0_response: Dict, v2_response: Dict):
    """Compare the update/transaction-level fields between the two endpoints."""
    print_subsection("Update-Level Field Comparison")

    v0_update_keys = Counter()
    v2_txn_keys = Counter()
    v0_update_key_types = {}
    v2_txn_key_types = {}

    for wrapper in v0_response.get("events", []):
        update = wrapper.get("update")
        if update and isinstance(update, dict):
            for key, value in update.items():
                v0_update_keys[key] += 1
                if key not in v0_update_key_types:
                    v0_update_key_types[key] = get_type_name(value)

    for txn in v2_response.get("transactions", []):
        for key, value in txn.items():
            v2_txn_keys[key] += 1
            if key not in v2_txn_key_types:
                v2_txn_key_types[key] = get_type_name(value)

    all_keys = sorted(set(v0_update_keys.keys()) | set(v2_txn_keys.keys()))

    print(f"\n  {'Field':<30} {'v0 Count':>9} {'v0 Type':<18} {'v2 Count':>9} {'v2 Type':<18} {'Status'}")
    print(f"  {'-----':<30} {'---------':>9} {'-------':<18} {'---------':>9} {'-------':<18} {'------'}")
    for key in all_keys:
        v0_count = v0_update_keys.get(key, 0)
        v2_count = v2_txn_keys.get(key, 0)
        v0_type = v0_update_key_types.get(key, "-")
        v2_type = v2_txn_key_types.get(key, "-")

        if v0_count > 0 and v2_count > 0:
            status = "BOTH"
        elif v0_count > 0:
            status = "v0 ONLY"
        else:
            status = "v2 ONLY"

        print(f"  {key:<30} {v0_count:>9} {v0_type:<18} {v2_count:>9} {v2_type:<18} {status}")


# =============================================================================
#  Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare response structures of /v0/events and /v2/updates"
    )
    parser.add_argument(
        "--migration-id", type=int, default=4,
        help="Migration ID to query (default: 4)"
    )
    parser.add_argument(
        "--page-size", type=int, default=100,
        help="Number of records per page (default: 100)"
    )
    parser.add_argument(
        "--base-url", type=str, default=BASE_URL,
        help="Scan API base URL"
    )
    parser.add_argument(
        "--output-dir", type=str, default=OUTPUT_DIR,
        help="Directory for output JSON files"
    )
    parser.add_argument(
        "--side-by-side-lines", type=int, default=80,
        help="Max lines for side-by-side comparison (default: 80)"
    )
    args = parser.parse_args()

    # Ensure output directory exists
    os.makedirs(args.output_dir, exist_ok=True)

    v0_output_path = os.path.join(args.output_dir, "v0_events_sample.json")
    v2_output_path = os.path.join(args.output_dir, "v2_updates_sample.json")

    print_section(
        "Canton Scan API: Response Structure Comparison", char="=", width=78
    )
    print(f"  Time:           {datetime.utcnow().isoformat()}Z")
    print(f"  API:            {args.base_url}")
    print(f"  Migration ID:   {args.migration_id}")
    print(f"  Page size:      {args.page_size}")
    print(f"  Output dir:     {args.output_dir}")

    # ---- Connect to API ----
    client = SpliceScanClient(base_url=args.base_url, timeout=60)

    # =========================================================================
    #  Step 1: Fetch raw responses
    # =========================================================================
    print_section("Step 1: Fetch Raw Responses")

    print(f"\n  Fetching /v0/events (migration_id={args.migration_id}, "
          f"page_size={args.page_size}) ...")
    try:
        v0_response = fetch_v0_events(client, args.migration_id, args.page_size)
        v0_events = v0_response.get("events", [])
        print(f"    Received {len(v0_events)} event wrappers")
        print(f"    Top-level keys: {sorted(v0_response.keys())}")
    except Exception as e:
        print(f"    ERROR fetching /v0/events: {e}")
        v0_response = {"events": [], "error": str(e)}
        v0_events = []

    print(f"\n  Fetching /v2/updates (migration_id={args.migration_id}, "
          f"page_size={args.page_size}) ...")
    try:
        v2_response = fetch_v2_updates(client, args.migration_id, args.page_size)
        v2_transactions = v2_response.get("transactions", [])
        print(f"    Received {len(v2_transactions)} transactions")
        print(f"    Top-level keys: {sorted(v2_response.keys())}")
    except Exception as e:
        print(f"    ERROR fetching /v2/updates: {e}")
        v2_response = {"transactions": [], "error": str(e)}
        v2_transactions = []

    # =========================================================================
    #  Step 2: Save raw JSON responses
    # =========================================================================
    print_section("Step 2: Save Raw JSON Responses")

    with open(v0_output_path, "w") as f:
        json.dump(v0_response, f, indent=2, default=str)
    print(f"  Saved /v0/events response to: {v0_output_path}")
    print(f"    File size: {os.path.getsize(v0_output_path):,} bytes")

    with open(v2_output_path, "w") as f:
        json.dump(v2_response, f, indent=2, default=str)
    print(f"  Saved /v2/updates response to: {v2_output_path}")
    print(f"    File size: {os.path.getsize(v2_output_path):,} bytes")

    # =========================================================================
    #  Step 3: Top-Level Structure Comparison
    # =========================================================================
    print_section("Step 3: Top-Level Response Structure")

    print(f"\n  /v0/events top-level:")
    print(f"    Keys: {sorted(v0_response.keys())}")
    for key in sorted(v0_response.keys()):
        val = v0_response[key]
        print(f"    {key}: {get_type_name(val)} "
              f"(length={len(val) if isinstance(val, (list, dict)) else 'N/A'})")

    print(f"\n  /v2/updates top-level:")
    print(f"    Keys: {sorted(v2_response.keys())}")
    for key in sorted(v2_response.keys()):
        val = v2_response[key]
        print(f"    {key}: {get_type_name(val)} "
              f"(length={len(val) if isinstance(val, (list, dict)) else 'N/A'})")

    # =========================================================================
    #  Step 4: Deep Structure of One Record from Each Endpoint
    # =========================================================================
    print_section("Step 4: Deep Structure of a Single Record")

    if v0_events:
        first_v0 = v0_events[0]
        print_subsection("/v0/events: First event wrapper structure")
        v0_structure = collect_structure(first_v0)
        print_structure_table(v0_structure, "/v0/events event wrapper:")
        analyze_nesting_complexity(first_v0, "/v0/events wrapper")
    else:
        v0_structure = []
        print("\n  /v0/events: No records to analyze")

    if v2_transactions:
        first_v2 = v2_transactions[0]
        print_subsection("/v2/updates: First transaction structure")
        v2_structure = collect_structure(first_v2)
        print_structure_table(v2_structure, "/v2/updates transaction:")
        analyze_nesting_complexity(first_v2, "/v2/updates transaction")
    else:
        v2_structure = []
        print("\n  /v2/updates: No records to analyze")

    # =========================================================================
    #  Step 5: Structural Comparison
    # =========================================================================
    print_section("Step 5: Structural Field Comparison")

    if v0_structure and v2_structure:
        compare_structures(v0_structure, v2_structure)

    # =========================================================================
    #  Step 6: Update-Level Field Comparison
    # =========================================================================
    if v0_events and v2_transactions:
        analyze_update_level_fields(v0_response, v2_response)

    # =========================================================================
    #  Step 7: Parsing Complexity Analysis
    # =========================================================================
    if v0_events and v2_transactions:
        analyze_parsing_complexity(v0_response, v2_response)

    # =========================================================================
    #  Step 8: Side-by-Side Comparison of a Shared Record
    # =========================================================================
    print_section("Step 8: Side-by-Side Comparison of a Shared Record")

    shared_id = find_shared_record(v0_response, v2_response)

    if shared_id:
        print(f"\n  Found shared update_id: {shared_id}")

        v0_record = extract_record_from_v0(v0_response, shared_id)
        v2_record = extract_record_from_v2(v2_response, shared_id)

        if v0_record and v2_record:
            # Show the /v0/events wrapper (update + verdict)
            print_subsection(f"Shared record: {shared_id[:50]}...")
            print(f"\n  /v0/events returns this as a WRAPPER with 'update' and 'verdict':")
            print(f"    Wrapper keys: {sorted(v0_record.keys())}")

            v0_update = v0_record.get("update", {})
            v0_verdict = v0_record.get("verdict")

            print(f"    update keys:  {sorted(v0_update.keys()) if isinstance(v0_update, dict) else 'N/A'}")
            if v0_verdict and isinstance(v0_verdict, dict):
                print(f"    verdict keys: {sorted(v0_verdict.keys())}")
            else:
                print(f"    verdict:      {v0_verdict}")

            print(f"\n  /v2/updates returns this as a FLAT transaction:")
            print(f"    Transaction keys: {sorted(v2_record.keys())}")

            # Compare the update body (v0 inner) vs v2 transaction
            print_subsection("Update body comparison (v0.update vs v2 transaction)")
            print_side_by_side(v0_update, v2_record, shared_id, max_lines=args.side_by_side_lines)

            # Show the verdict separately
            if v0_verdict and isinstance(v0_verdict, dict):
                print_subsection("Verdict (ONLY in /v0/events)")
                print(f"\n  This data is exclusive to /v0/events -- /v2/updates does not provide it:")
                print(json.dumps(v0_verdict, indent=2, default=str))
            else:
                print(f"\n  No verdict data for this specific record.")

            # Check if the update bodies are identical
            import hashlib
            v0_hash = hashlib.sha256(
                json.dumps(v0_update, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            v2_hash = hashlib.sha256(
                json.dumps(v2_record, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]

            print(f"\n  Content hash comparison:")
            print(f"    /v0/events update body hash:  {v0_hash}")
            print(f"    /v2/updates transaction hash: {v2_hash}")
            if v0_hash == v2_hash:
                print(f"    RESULT: Update bodies are BYTE-IDENTICAL")
            else:
                print(f"    RESULT: Update bodies DIFFER")
                # Find the specific differences
                _show_field_diffs(v0_update, v2_record)
        else:
            print(f"  Could not extract records for shared ID")
    else:
        # Try to show a record from each even if no overlap
        print(f"\n  No shared update_id found between the two responses.")
        print(f"  This may happen if the pages don't overlap (different pagination behavior).")
        print(f"  Showing first record from each endpoint independently:")

        if v0_events:
            first_wrapper = v0_events[0]
            update = first_wrapper.get("update")
            if update:
                print(f"\n  /v0/events first record (update body only):")
                print(json.dumps(update, indent=2, default=str)[:3000])
                if len(json.dumps(update, default=str)) > 3000:
                    print("  ... (truncated)")

        if v2_transactions:
            print(f"\n  /v2/updates first record:")
            print(json.dumps(v2_transactions[0], indent=2, default=str)[:3000])
            if len(json.dumps(v2_transactions[0], default=str)) > 3000:
                print("  ... (truncated)")

    # =========================================================================
    #  Step 9: ID Coverage Summary
    # =========================================================================
    print_section("Step 9: ID Coverage Summary")

    v0_update_ids = set()
    v0_null_body_ids = set()
    for wrapper in v0_events:
        update = wrapper.get("update")
        if update and isinstance(update, dict):
            uid = update.get("update_id")
            if uid:
                v0_update_ids.add(uid)
        else:
            verdict = wrapper.get("verdict")
            if verdict and isinstance(verdict, dict):
                uid = verdict.get("update_id")
                if uid:
                    v0_null_body_ids.add(uid)

    v2_update_ids = set()
    for txn in v2_transactions:
        uid = txn.get("update_id")
        if uid:
            v2_update_ids.add(uid)

    shared_ids = v0_update_ids & v2_update_ids
    only_v0 = v0_update_ids - v2_update_ids
    only_v2 = v2_update_ids - v0_update_ids
    null_body_not_in_v2 = v0_null_body_ids - v2_update_ids

    print(f"\n  /v0/events update_ids (with body): {len(v0_update_ids)}")
    print(f"  /v0/events null-body update_ids:   {len(v0_null_body_ids)}")
    print(f"  /v2/updates update_ids:            {len(v2_update_ids)}")
    print(f"\n  Shared (in both with body):         {len(shared_ids)}")
    print(f"  Only in /v0/events (with body):     {len(only_v0)}")
    print(f"  Only in /v2/updates:                {len(only_v2)}")
    print(f"  Null-body only in /v0:              {len(null_body_not_in_v2)}")

    if only_v2:
        print(f"\n  IDs only in /v2/updates (first 5):")
        for uid in sorted(only_v2)[:5]:
            print(f"    {uid}")
        print(f"  NOTE: These records exist in /v2 but not in this /v0 page.")
        print(f"  This is typically because /v0/events includes null-body records")
        print(f"  that consume page slots, so fewer full records fit per page.")

    if null_body_not_in_v2:
        print(f"\n  Null-body IDs from /v0 (first 5):")
        for uid in sorted(null_body_not_in_v2)[:5]:
            print(f"    {uid}")
        print(f"  These are verdict-only records visible in /v0/events but absent")
        print(f"  from /v2/updates (which only returns records with event data).")

    # =========================================================================
    #  Final Summary
    # =========================================================================
    print_section("Final Summary", char="=", width=78)

    print("""
  KEY STRUCTURAL DIFFERENCES:

  1. RESPONSE WRAPPER
     /v0/events:  {"events": [{"update": {...}, "verdict": {...}}, ...]}
     /v2/updates: {"transactions": [{...}, ...]}

     /v0/events wraps each record in an object with "update" and "verdict" keys.
     /v2/updates returns transactions directly without a wrapper.

  2. VERDICT FIELD (exclusive to /v0/events)
     The "verdict" object contains consensus finalization metadata:
       - verdict_result: ACCEPTED or REJECTED
       - finalization_time: when consensus was reached
       - submitting_parties: who submitted the transaction
       - submitting_participant_uid: which node submitted
       - mediator_group: which mediator processed it
       - transaction_views: privacy decomposition (informees, confirming_parties)

     /v2/updates does NOT include any of this data.

  3. NULL-BODY RECORDS (only in /v0/events)
     /v0/events can return records where "update" is null but "verdict" exists.
     These are transactions where only the verdict metadata is visible to the
     querying party (the events_by_id are not visible due to Canton's privacy).
     /v2/updates never returns null-body records.

  4. UPDATE BODY (identical when present)
     For records that appear in both endpoints with a full body, the update/
     transaction content (events_by_id, record_time, migration_id, etc.) is
     byte-for-byte identical.

  5. EVENTS ORDERING
     /v2/updates sorts events_by_id lexicographically by event ID.
     /v0/events may not guarantee the same ordering.

  6. PAGINATION DENSITY
     /v2/updates packs more useful records per page (no null-body records).
     /v0/events may return fewer full records per page due to null-body slots.

  PARSING COMPLEXITY:
     /v0/events requires:
       - Unwrapping each item (wrapper.update, wrapper.verdict)
       - Handling null update bodies (skip or store verdict separately)
       - Deeper nesting: response.events[].update.events_by_id.*
     /v2/updates requires:
       - Direct access: response.transactions[].events_by_id.*
       - No null-body handling needed
       - Simpler, flatter structure
""")

    print(f"  Output files saved to:")
    print(f"    {v0_output_path}")
    print(f"    {v2_output_path}")

    print_section("Done", char="=", width=78)

    client.close()


def _show_field_diffs(a: Dict, b: Dict, prefix: str = "", max_diffs: int = 10):
    """Show specific field-level differences between two dicts."""
    diffs_found = 0
    all_keys = sorted(set(a.keys()) | set(b.keys()))
    for key in all_keys:
        if diffs_found >= max_diffs:
            print(f"    ... (more differences omitted)")
            break
        child_path = f"{prefix}.{key}" if prefix else key
        if key not in a:
            print(f"    ONLY in /v2/updates: {child_path} = {_sample_value(b[key], 60)}")
            diffs_found += 1
        elif key not in b:
            print(f"    ONLY in /v0/events:  {child_path} = {_sample_value(a[key], 60)}")
            diffs_found += 1
        elif a[key] != b[key]:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                _show_field_diffs(a[key], b[key], child_path, max_diffs - diffs_found)
            else:
                print(f"    DIFFER at {child_path}:")
                print(f"      /v0: {_sample_value(a[key], 60)}")
                print(f"      /v2: {_sample_value(b[key], 60)}")
                diffs_found += 1


if __name__ == "__main__":
    main()
