#!/usr/bin/env python3
"""
Pipeline Health Monitor

Checks data freshness, row count consistency, daily volume trends, ingestion
state staleness, and API connectivity. Designed to run manually or via cron.

When run with --notify, CRITICAL/WARNING conditions are emitted as structured
JSON log entries so Cloud Logging can trigger log-based metric alerts.

Usage:
    python scripts/monitor_pipeline.py               # Human-readable
    python scripts/monitor_pipeline.py --json        # Machine-readable JSON
    python scripts/monitor_pipeline.py --notify      # Emit alerts to Cloud Logging
    python scripts/monitor_pipeline.py --days 14     # Extend lookback window

Exit codes:
    0 = All checks passed (OK)
    1 = Warnings (non-critical issues)
    2 = Critical issues detected
"""

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, List

from google.cloud import bigquery

PROJECT_ID = "governence-483517"
RAW_TABLE = "governence-483517.raw.events"
PARSED_TABLE = "governence-483517.transformed.events_parsed"

# Thresholds
FRESHNESS_WARNING_HOURS = 36    # Warn if data is >36h old
FRESHNESS_CRITICAL_HOURS = 72   # Critical if data is >72h old
ROW_DIFF_THRESHOLD = 1000       # Acceptable row difference between raw and parsed
VOLUME_DROP_PCT = 50            # Warn if daily volume drops more than 50% vs avg
VOLUME_SPIKE_PCT = 300          # Warn if daily volume spikes more than 300% vs avg
INGESTION_STATE_STALE_HOURS = 48  # Warn if ingestion state not updated in N hours


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
    """Check the ingestion state table for last processed positions and staleness."""
    query = """
    SELECT table_name, migration_id, recorded_at, updated_at
    FROM `governence-483517.raw.ingestion_state`
    ORDER BY table_name
    """
    try:
        rows = list(client.query(query).result())
        states = {}
        has_stale = False
        for row in rows:
            updated_at = row.updated_at
            if updated_at:
                age_hours = (datetime.utcnow() - updated_at.replace(tzinfo=None)).total_seconds() / 3600
                stale = age_hours > INGESTION_STATE_STALE_HOURS
            else:
                age_hours = None
                stale = True
            if stale:
                has_stale = True
            states[row.table_name] = {
                "migration_id": row.migration_id,
                "recorded_at": row.recorded_at,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "age_hours": round(age_hours, 1) if age_hours is not None else None,
                "stale": stale,
            }
        status = "WARNING" if has_stale else "OK"
        return {"states": states, "status": status}
    except Exception as e:
        return {"error": str(e), "status": "WARNING"}


def check_daily_volume_trend(client: bigquery.Client, lookback_days: int = 14) -> dict:
    """
    Compare the most recent complete day's row count to the rolling average.
    Significant drops or spikes are flagged as warnings.
    """
    query = f"""
    SELECT partition_id, total_rows
    FROM `{PROJECT_ID}.raw.INFORMATION_SCHEMA.PARTITIONS`
    WHERE table_name = 'events'
      AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
      AND partition_id >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY))
      AND partition_id < FORMAT_DATE('%Y%m%d', CURRENT_DATE())
    ORDER BY partition_id DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", lookback_days)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    if len(rows) < 2:
        return {"status": "OK", "message": "Insufficient history for trend analysis"}

    daily = [{"partition": r.partition_id, "rows": r.total_rows} for r in rows]
    counts = [r.total_rows for r in rows]
    avg = sum(counts[1:]) / len(counts[1:])
    latest = counts[0]
    latest_partition = rows[0].partition_id
    pct_change = ((latest - avg) / avg * 100) if avg > 0 else 0.0

    warnings = []
    if pct_change < -VOLUME_DROP_PCT:
        warnings.append(
            f"Volume drop: partition {latest_partition} has {pct_change:.1f}% "
            f"fewer rows than {len(counts)-1}-day avg ({avg:,.0f}). Possible stall."
        )
    elif pct_change > VOLUME_SPIKE_PCT:
        warnings.append(
            f"Volume spike: partition {latest_partition} has +{pct_change:.1f}% "
            f"more rows than {len(counts)-1}-day avg ({avg:,.0f}). Possible duplicates."
        )

    status = "WARNING" if warnings else "OK"
    return {
        "status": status,
        "latest_partition": latest_partition,
        "latest_rows": latest,
        "rolling_avg_rows": round(avg, 0),
        "pct_change_vs_avg": round(pct_change, 1),
        "daily_counts": daily[:14],
        "warnings": warnings,
    }


def check_api_connectivity() -> dict:
    """
    Check if any Scan API node is reachable.
    Tries multiple SV nodes in order, returns OK if any responds.
    """
    import requests

    urls_to_try = [
        "https://scan.sv-1.global.canton.network.cumberland.io/api/scan/",
        "https://scan.sv-1.global.canton.network.proofgroup.xyz/api/scan/",
        "https://scan.sv-1.global.canton.network.digitalasset.com/api/scan/",
        "https://scan.sv-1.global.canton.network.sync.global/api/scan/",
    ]

    for base_url in urls_to_try:
        url = f"{base_url.rstrip('/')}/v0/dso"
        start = time.time()
        try:
            resp = requests.get(url, timeout=15, headers={"Accept": "application/json"})
            elapsed = round(time.time() - start, 2)
            if resp.status_code == 200:
                return {"url": base_url, "status": "OK", "response_time_s": elapsed}
        except requests.exceptions.Timeout:
            continue
        except Exception:
            continue

    return {
        "status": "CRITICAL",
        "error": "All Scan API nodes unreachable",
        "urls_tried": urls_to_try,
    }


def emit_cloud_logging_alert(overall_status: str, checks: dict) -> None:
    """
    Emit a structured JSON log entry at ERROR/WARNING severity.
    Cloud Logging captures this from stdout when running in Cloud Run,
    enabling log-based metric alerts.
    """
    if overall_status == "OK":
        return

    severity = "ERROR" if overall_status == "CRITICAL" else "WARNING"
    issues: List[str] = []

    # Collect specific issues
    freshness = checks.get("data_freshness", {})
    for label in ("raw", "parsed"):
        info = freshness.get(label, {})
        if info.get("status") in ("WARNING", "CRITICAL"):
            issues.append(
                f"Data freshness {info['status']}: {label} table lag "
                f"{info.get('lag_hours')}h (partition {info.get('latest_partition')})"
            )

    row_cons = checks.get("row_consistency", {})
    if row_cons.get("status") not in ("OK", None):
        issues.append(
            f"Row consistency {row_cons['status']}: "
            f"{row_cons.get('total_row_difference', 0):,} total row difference"
        )

    state = checks.get("ingestion_state", {})
    for name, s in state.get("states", {}).items():
        if s.get("stale"):
            issues.append(
                f"Ingestion state stale: {name} not updated for {s.get('age_hours')}h"
            )

    api = checks.get("api_connectivity", {})
    if api.get("status") not in ("OK", None):
        issues.append(f"API {api.get('status')}: {api.get('error', 'unreachable')}")

    for w in checks.get("daily_volume_trend", {}).get("warnings", []):
        issues.append(w)

    alert = {
        "severity": severity,
        "message": (
            f"Canton pipeline monitor: {overall_status} — "
            f"{len(issues)} issue(s) detected"
        ),
        "pipeline_monitor": {
            "overall_status": overall_status,
            "issues": issues,
            "checked_at": checks.get("checked_at"),
        },
    }
    print(json.dumps(alert))


def main():
    parser = argparse.ArgumentParser(description="Pipeline Health Monitor")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--notify", action="store_true",
        help="Emit Cloud Logging structured alerts on issues (for log-based metrics)"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Lookback window in days for row consistency and trend checks (default: 7)"
    )
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    checks: Dict[str, Any] = {}
    overall_status = "OK"

    if not args.json:
        print("Running pipeline health checks...", file=sys.stderr)

    checks["data_freshness"] = check_data_freshness(client)
    checks["row_consistency"] = check_row_consistency(client)
    checks["table_stats"] = check_table_stats(client)
    checks["ingestion_state"] = check_ingestion_state(client)
    checks["daily_volume_trend"] = check_daily_volume_trend(client, args.days)
    checks["api_connectivity"] = check_api_connectivity()
    checks["checked_at"] = datetime.utcnow().isoformat() + "Z"

    # Determine overall status (scan all nested dicts for "status" keys)
    def _scan(obj) -> List[str]:
        statuses: List[str] = []
        if isinstance(obj, dict):
            if "status" in obj:
                statuses.append(obj["status"])
            for v in obj.values():
                statuses.extend(_scan(v))
        return statuses

    for check_name, check_result in checks.items():
        if check_name in ("checked_at", "overall_status"):
            continue
        for s in _scan(check_result):
            if s == "CRITICAL":
                overall_status = "CRITICAL"
            elif s == "WARNING" and overall_status != "CRITICAL":
                overall_status = "WARNING"

    checks["overall_status"] = overall_status

    if args.notify:
        emit_cloud_logging_alert(overall_status, checks)

    if args.json:
        print(json.dumps(checks, indent=2, default=str))
    else:
        m = lambda s: {"OK": "+", "WARNING": "!", "CRITICAL": "X"}.get(s, "?")

        print("=" * 70)
        print("PIPELINE HEALTH MONITOR")
        print(f"Checked at: {checks['checked_at']}")
        print("=" * 70)

        # Data Freshness
        print("\n--- Data Freshness ---")
        for label in ["raw", "parsed"]:
            info = checks["data_freshness"].get(label, {})
            status = info.get("status", "UNKNOWN")
            lag = info.get("lag_hours", "N/A")
            partition = info.get("latest_partition", "N/A")
            print(f"  [{m(status)}] {label:7s}: latest={partition}, lag={lag}h [{status}]")

        # Row Consistency
        print(f"\n--- Row Consistency (last {args.days} days) ---")
        consistency = checks["row_consistency"]
        for p in consistency.get("partitions", []):
            diff = p["difference"]
            marker = "+" if diff == 0 else "!"
            print(f"  [{marker}] {p['partition']}: raw={p['raw_rows']:>12,}  parsed={p['parsed_rows']:>12,}  diff={diff:>8,}")
        total_diff = consistency.get("total_row_difference", 0)
        print(f"  Total difference: {total_diff:,} [{consistency.get('status', 'UNKNOWN')}]")

        # Table Stats
        print("\n--- Table Statistics ---")
        for label in ["raw", "parsed"]:
            info = checks["table_stats"].get(label, {})
            if "error" in info:
                print(f"  {label:7s}: ERROR - {info['error']}")
            else:
                print(f"  {label:7s}: {info.get('num_rows', 0):>15,} rows, "
                      f"{info.get('size_gb', 0):>8.2f} GB, "
                      f"modified={info.get('last_modified', 'N/A')}")

        # Ingestion State
        print("\n--- Ingestion State ---")
        state_info = checks["ingestion_state"]
        if "states" in state_info:
            for name, state in state_info["states"].items():
                age = state.get("age_hours", "N/A")
                stale_marker = "!" if state.get("stale") else "+"
                print(f"  [{stale_marker}] {name:20s}: migration_id={state.get('migration_id')}, age={age}h")
        else:
            print(f"  Error: {state_info.get('error', 'unknown')}")

        # Daily Volume Trend
        print(f"\n--- Daily Volume Trend (last {args.days} days) ---")
        vt = checks["daily_volume_trend"]
        if "message" in vt:
            print(f"  {vt['message']}")
        else:
            avg = vt.get("rolling_avg_rows", 0)
            pct = vt.get("pct_change_vs_avg", 0)
            status = vt.get("status", "OK")
            print(f"  [{m(status)}] latest={vt.get('latest_partition', 'N/A')}  "
                  f"rows={vt.get('latest_rows', 0):,}  "
                  f"avg={avg:,.0f}  change={pct:+.1f}%  [{status}]")
            for dc in vt.get("daily_counts", [])[:7]:
                print(f"         {dc['partition']}: {dc['rows']:>12,}")
            for w in vt.get("warnings", []):
                print(f"  [!] {w}")

        # API Connectivity
        print("\n--- API Connectivity ---")
        api = checks["api_connectivity"]
        status = api.get("status", "UNKNOWN")
        if "response_time_s" in api:
            print(f"  [{m(status)}] {api.get('url', '')}: {api.get('response_time_s')}s [{status}]")
        else:
            print(f"  [{m(status)}] {api.get('error', 'unknown')} [{status}]")

        # Overall
        print("\n" + "=" * 70)
        print(f"  [{m(overall_status)}] OVERALL STATUS: {overall_status}")
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
