#!/usr/bin/env python3
"""
Pipeline Health Monitor

Checks data freshness, row count consistency, scheduled query status,
and API connectivity. Designed to be run manually or via cron for alerting.

Usage:
    python scripts/monitor_pipeline.py
    python scripts/monitor_pipeline.py --json  # Machine-readable output

Exit codes:
    0 = All checks passed
    1 = Warnings (non-critical issues)
    2 = Critical issues detected
"""

import argparse
import json
import sys
import time
from datetime import datetime

from google.cloud import bigquery

PROJECT_ID = "governence-483517"
RAW_TABLE = "governence-483517.raw.events"
PARSED_TABLE = "governence-483517.transformed.events_parsed"

# Thresholds
FRESHNESS_WARNING_HOURS = 36   # Warn if data is >36h old
FRESHNESS_CRITICAL_HOURS = 72  # Critical if data is >72h old
ROW_DIFF_THRESHOLD = 1000      # Acceptable row difference between raw and parsed


def check_data_freshness(client: bigquery.Client) -> dict:
    """Check how fresh the data is in both tables."""
    results = {}
    for label, table_id in [("raw", RAW_TABLE), ("parsed", PARSED_TABLE)]:
        dataset_ref = table_id.rsplit('.', 1)[0]
        table_name = table_id.rsplit('.', 1)[1]
        query = f"""
        SELECT MAX(partition_id) as latest_partition
        FROM `{dataset_ref}.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = @table_name
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("table_name", "STRING", table_name),
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())
        if rows and rows[0].latest_partition:
            partition_str = rows[0].latest_partition
            latest_date = datetime.strptime(partition_str, '%Y%m%d')
            lag_hours = (datetime.utcnow() - latest_date).total_seconds() / 3600
            if lag_hours > FRESHNESS_CRITICAL_HOURS:
                status = "CRITICAL"
            elif lag_hours > FRESHNESS_WARNING_HOURS:
                status = "WARNING"
            else:
                status = "OK"
            results[label] = {
                "latest_partition": partition_str,
                "lag_hours": round(lag_hours, 1),
                "status": status,
            }
        else:
            results[label] = {"latest_partition": None, "lag_hours": None, "status": "CRITICAL"}
    return results


def check_row_consistency(client: bigquery.Client) -> dict:
    """Compare row counts between raw and parsed tables for recent partitions."""
    query = """
    WITH raw_counts AS (
        SELECT partition_id, total_rows
        FROM `governence-483517.raw.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = 'events'
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
          AND partition_id >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
    ),
    parsed_counts AS (
        SELECT partition_id, total_rows
        FROM `governence-483517.transformed.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = 'events_parsed'
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
          AND partition_id >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
    )
    SELECT
        r.partition_id,
        r.total_rows as raw_rows,
        COALESCE(p.total_rows, 0) as parsed_rows,
        r.total_rows - COALESCE(p.total_rows, 0) as row_difference
    FROM raw_counts r
    LEFT JOIN parsed_counts p ON r.partition_id = p.partition_id
    ORDER BY r.partition_id DESC
    """
    rows = list(client.query(query).result())
    partitions = []
    total_diff = 0
    for row in rows:
        total_diff += row.row_difference
        partitions.append({
            "partition": row.partition_id,
            "raw_rows": row.raw_rows,
            "parsed_rows": row.parsed_rows,
            "difference": row.row_difference,
        })

    if total_diff > ROW_DIFF_THRESHOLD:
        status = "WARNING"
    elif total_diff == 0:
        status = "OK"
    else:
        status = "OK"  # Small differences are normal during ingestion

    return {
        "partitions": partitions,
        "total_row_difference": total_diff,
        "status": status,
    }


def check_table_stats(client: bigquery.Client) -> dict:
    """Get basic table statistics."""
    results = {}
    for label, table_id in [("raw", RAW_TABLE), ("parsed", PARSED_TABLE)]:
        table = client.get_table(table_id)
        results[label] = {
            "num_rows": table.num_rows,
            "size_gb": round(table.num_bytes / (1024**3), 2) if table.num_bytes else 0,
            "last_modified": table.modified.isoformat() if table.modified else None,
        }
    return results


def check_ingestion_state(client: bigquery.Client) -> dict:
    """Check the ingestion state table for last processed positions."""
    query = """
    SELECT table_name, migration_id, recorded_at, updated_at
    FROM `governence-483517.raw.ingestion_state`
    ORDER BY table_name
    """
    try:
        rows = list(client.query(query).result())
        states = {}
        for row in rows:
            updated_at = row.updated_at
            if updated_at:
                age_hours = (datetime.utcnow() - updated_at.replace(tzinfo=None)).total_seconds() / 3600
            else:
                age_hours = None
            states[row.table_name] = {
                "migration_id": row.migration_id,
                "recorded_at": row.recorded_at,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "age_hours": round(age_hours, 1) if age_hours else None,
            }
        return {"states": states, "status": "OK"}
    except Exception as e:
        return {"error": str(e), "status": "WARNING"}


def check_api_connectivity() -> dict:
    """Quick check if the primary API URL is reachable."""
    import requests
    url = "https://scan.sv-1.global.canton.network.sync.global/api/scan/v0/dso"
    start = time.time()
    try:
        resp = requests.get(url, timeout=15, headers={"Accept": "application/json"})
        elapsed = time.time() - start
        if resp.status_code == 200:
            return {"url": url, "status": "OK", "response_time_s": round(elapsed, 2)}
        else:
            return {"url": url, "status": "WARNING", "http_status": resp.status_code, "response_time_s": round(elapsed, 2)}
    except requests.exceptions.Timeout:
        return {"url": url, "status": "WARNING", "error": "timeout"}
    except Exception as e:
        return {"url": url, "status": "CRITICAL", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Pipeline Health Monitor")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    checks = {}
    overall_status = "OK"

    # Run all checks
    print("Running pipeline health checks..." if not args.json else "", file=sys.stderr)

    checks["data_freshness"] = check_data_freshness(client)
    checks["row_consistency"] = check_row_consistency(client)
    checks["table_stats"] = check_table_stats(client)
    checks["ingestion_state"] = check_ingestion_state(client)
    checks["api_connectivity"] = check_api_connectivity()
    checks["checked_at"] = datetime.utcnow().isoformat() + "Z"

    # Determine overall status
    for check_name, check_result in checks.items():
        if isinstance(check_result, dict):
            status = check_result.get("status")
            if status == "CRITICAL":
                overall_status = "CRITICAL"
            elif status == "WARNING" and overall_status != "CRITICAL":
                overall_status = "WARNING"
            # Check nested statuses (e.g., freshness has raw/parsed sub-checks)
            for val in check_result.values():
                if isinstance(val, dict):
                    nested_status = val.get("status")
                    if nested_status == "CRITICAL":
                        overall_status = "CRITICAL"
                    elif nested_status == "WARNING" and overall_status != "CRITICAL":
                        overall_status = "WARNING"

    checks["overall_status"] = overall_status

    if args.json:
        print(json.dumps(checks, indent=2, default=str))
    else:
        print("=" * 70)
        print("PIPELINE HEALTH MONITOR")
        print(f"Checked at: {checks['checked_at']}")
        print("=" * 70)

        # Data Freshness
        print("\n--- Data Freshness ---")
        for label in ["raw", "parsed"]:
            info = checks["data_freshness"].get(label, {})
            status = info.get("status", "UNKNOWN")
            marker = {"OK": "+", "WARNING": "!", "CRITICAL": "X"}.get(status, "?")
            lag = info.get("lag_hours", "N/A")
            partition = info.get("latest_partition", "N/A")
            print(f"  [{marker}] {label:7s}: latest={partition}, lag={lag}h [{status}]")

        # Row Consistency
        print("\n--- Row Consistency (last 7 days) ---")
        consistency = checks["row_consistency"]
        for p in consistency.get("partitions", []):
            diff = p["difference"]
            marker = "+" if diff == 0 else "!"
            print(f"  [{marker}] {p['partition']}: raw={p['raw_rows']:>12,}  parsed={p['parsed_rows']:>12,}  diff={diff:>8,}")
        print(f"  Total difference: {consistency.get('total_row_difference', 0):,} [{consistency.get('status', 'UNKNOWN')}]")

        # Table Stats
        print("\n--- Table Statistics ---")
        for label in ["raw", "parsed"]:
            info = checks["table_stats"].get(label, {})
            print(f"  {label:7s}: {info.get('num_rows', 0):>15,} rows, {info.get('size_gb', 0):>8.2f} GB, modified={info.get('last_modified', 'N/A')}")

        # Ingestion State
        print("\n--- Ingestion State ---")
        state_info = checks["ingestion_state"]
        if "states" in state_info:
            for name, state in state_info["states"].items():
                age = state.get("age_hours", "N/A")
                print(f"  {name:15s}: migration_id={state.get('migration_id')}, age={age}h")
        else:
            print(f"  Error: {state_info.get('error', 'unknown')}")

        # API Connectivity
        print("\n--- API Connectivity ---")
        api = checks["api_connectivity"]
        status = api.get("status", "UNKNOWN")
        marker = {"OK": "+", "WARNING": "!", "CRITICAL": "X"}.get(status, "?")
        if "response_time_s" in api:
            print(f"  [{marker}] Primary URL: {api.get('response_time_s')}s [{status}]")
        else:
            print(f"  [{marker}] Primary URL: {api.get('error', 'unknown')} [{status}]")

        # Overall
        print("\n" + "=" * 70)
        marker = {"OK": "+", "WARNING": "!", "CRITICAL": "X"}.get(overall_status, "?")
        print(f"  [{marker}] OVERALL STATUS: {overall_status}")
        print("=" * 70)

    # Exit code based on status
    if overall_status == "CRITICAL":
        sys.exit(2)
    elif overall_status == "WARNING":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
