#!/usr/bin/env python3
"""
Canton Data Pipeline - Data Quality Verification Suite

Runs a comprehensive set of automated data quality checks across the
raw.events and transformed.events_parsed BigQuery tables, and optionally
validates the live Scan API schema against the expected field set.

Checks performed:
  1. Row count validation      - raw.events vs events_parsed per partition (last N days)
  2. Data freshness            - How old is the latest partition in each table?
  3. Timestamp consistency     - No future dates, no nulls on critical timestamp columns
  4. Duplicate detection       - Duplicate event_ids within the same partition
  5. Null field checks         - Critical columns must not be null above a threshold
  6. Partition continuity      - No missing daily partitions between first and last
  7. Schema drift detection    - Live API response keys vs expected schema

Exit codes:
  0  All checks passed (OK)
  1  Warning conditions detected (non-critical)
  2  Critical issues detected

Usage:
  python scripts/data_quality_checks.py
  python scripts/data_quality_checks.py --json
  python scripts/data_quality_checks.py --days 7
  python scripts/data_quality_checks.py --skip-api-check
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

# ── Configuration ──────────────────────────────────────────────────────────────
PROJECT_ID = "governence-483517"
RAW_TABLE = "governence-483517.raw.events"
PARSED_TABLE = "governence-483517.transformed.events_parsed"

# How many recent days to inspect for most checks
DEFAULT_LOOKBACK_DAYS = 7

# Thresholds
FRESHNESS_WARNING_HOURS = 36    # Warn if latest partition is older than this
FRESHNESS_CRITICAL_HOURS = 72   # Critical if older than this
MAX_ROW_DIFF_PCT = 5.0          # Warn if raw vs parsed differ by more than 5%
MAX_NULL_PCT = 1.0              # Warn if critical fields have >1% nulls
MAX_DUP_PER_PARTITION = 0       # Zero tolerance for duplicate event_ids
MAX_TIMESTAMP_FUTURE_ROWS = 0   # Zero tolerance for future-dated records

# Fields that must not be null
CRITICAL_NON_NULL_FIELDS = [
    "event_id",
    "update_id",
    "template_id",
    "event_type",
    "recorded_at",
    "event_date",
]

# Expected top-level fields in /v2/updates API response items
EXPECTED_API_FIELDS = {
    "update_id",
    "migration_id",
    "record_time",
    "synchronizer_id",
    "effective_at",
    "events_by_id",
}

# Expected fields within each event in events_by_id
EXPECTED_EVENT_FIELDS = {
    "event_type",
    "contract_id",
    "template_id",
}

# Scan API URL for schema check
SCAN_API_URLS = [
    "https://scan.sv-1.global.canton.network.cumberland.io/api/scan/",
    "https://scan.sv-2.global.canton.network.cumberland.io/api/scan/",
    "https://scan.sv-1.global.canton.network.proofgroup.xyz/api/scan/",
    "https://scan.sv-1.global.canton.network.digitalasset.com/api/scan/",
]


# ── Check Functions ─────────────────────────────────────────────────────────────

def check_row_count_by_partition(
    client: bigquery.Client, lookback_days: int
) -> Dict[str, Any]:
    """
    Compare raw.events vs transformed.events_parsed row counts per partition
    for the last N days. Detects transformation lag and missing data.
    """
    query = """
    WITH raw_counts AS (
        SELECT partition_id, total_rows
        FROM `governence-483517.raw.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = 'events'
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
          AND partition_id >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY))
    ),
    parsed_counts AS (
        SELECT partition_id, total_rows
        FROM `governence-483517.transformed.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = 'events_parsed'
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
          AND partition_id >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY))
    )
    SELECT
        r.partition_id,
        r.total_rows                          AS raw_rows,
        COALESCE(p.total_rows, 0)             AS parsed_rows,
        r.total_rows - COALESCE(p.total_rows, 0) AS row_difference,
        SAFE_DIVIDE(
            ABS(r.total_rows - COALESCE(p.total_rows, 0)) * 100.0,
            r.total_rows
        )                                     AS diff_pct
    FROM raw_counts r
    LEFT JOIN parsed_counts p ON r.partition_id = p.partition_id
    ORDER BY r.partition_id DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", lookback_days)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    partitions = []
    total_diff = 0
    max_diff_pct = 0.0
    warnings = []

    for row in rows:
        diff = row.row_difference
        diff_pct = row.diff_pct or 0.0
        total_diff += diff
        max_diff_pct = max(max_diff_pct, diff_pct)
        partitions.append({
            "partition": row.partition_id,
            "raw_rows": row.raw_rows,
            "parsed_rows": row.parsed_rows,
            "difference": diff,
            "diff_pct": round(diff_pct, 2),
        })
        if diff_pct > MAX_ROW_DIFF_PCT:
            warnings.append(
                f"Partition {row.partition_id}: raw={row.raw_rows:,} "
                f"parsed={row.parsed_rows:,} diff={diff_pct:.1f}%"
            )

    if max_diff_pct > MAX_ROW_DIFF_PCT:
        status = "WARNING"
    else:
        status = "OK"

    return {
        "status": status,
        "partitions_checked": len(partitions),
        "total_row_difference": total_diff,
        "max_diff_pct": round(max_diff_pct, 2),
        "partitions": partitions,
        "warnings": warnings,
    }


def check_data_freshness(
    client: bigquery.Client
) -> Dict[str, Any]:
    """
    Check how old the latest partition is in raw.events and events_parsed.
    Detects pipeline stalls.
    """
    results = {}
    for label, dataset, table in [
        ("raw", "raw", "events"),
        ("parsed", "transformed", "events_parsed"),
    ]:
        query = """
        SELECT MAX(partition_id) AS latest_partition
        FROM `governence-483517.{dataset}.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = @table_name
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
        """.format(dataset=dataset)
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("table_name", "STRING", table)
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())

        if rows and rows[0].latest_partition:
            partition_str = rows[0].latest_partition
            latest_date = datetime.strptime(partition_str, "%Y%m%d")
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
            results[label] = {
                "latest_partition": None,
                "lag_hours": None,
                "status": "CRITICAL",
            }

    overall = "OK"
    for v in results.values():
        if v["status"] == "CRITICAL":
            overall = "CRITICAL"
        elif v["status"] == "WARNING" and overall != "CRITICAL":
            overall = "WARNING"

    results["status"] = overall
    return results


def check_timestamp_consistency(
    client: bigquery.Client, lookback_days: int
) -> Dict[str, Any]:
    """
    Check for invalid timestamps in raw.events:
      - Future-dated recorded_at values
      - recorded_at more than 30 days older than event_date partition
    Uses partition pruning to limit scan cost.
    """
    query = """
    SELECT
        COUNT(*) AS total_rows,
        COUNTIF(
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', recorded_at)
            > CURRENT_TIMESTAMP()
        ) AS future_recorded_at,
        COUNTIF(recorded_at IS NULL) AS null_recorded_at,
        COUNTIF(
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', recorded_at)
            < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 400 DAY)
        ) AS very_old_recorded_at,
        COUNTIF(timestamp IS NULL) AS null_timestamp
    FROM `governence-483517.raw.events`
    WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", lookback_days)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    if not rows:
        return {"status": "OK", "message": "No rows in lookback window"}

    row = rows[0]
    issues = []

    if row.future_recorded_at > MAX_TIMESTAMP_FUTURE_ROWS:
        issues.append(f"{row.future_recorded_at:,} rows have future recorded_at")
    if row.null_recorded_at > 0:
        issues.append(f"{row.null_recorded_at:,} rows have NULL recorded_at")
    if row.null_timestamp > 0:
        issues.append(f"{row.null_timestamp:,} rows have NULL timestamp")

    status = "CRITICAL" if issues else "OK"
    return {
        "status": status,
        "total_rows_checked": row.total_rows,
        "future_recorded_at": row.future_recorded_at,
        "null_recorded_at": row.null_recorded_at,
        "null_timestamp": row.null_timestamp,
        "very_old_recorded_at": row.very_old_recorded_at,
        "issues": issues,
    }


def check_duplicate_events(
    client: bigquery.Client, lookback_days: int
) -> Dict[str, Any]:
    """
    Detect duplicate event_ids within the same event_date partition in raw.events.
    Duplicates indicate a bug in deduplication logic.
    """
    query = """
    SELECT
        event_date,
        event_id,
        COUNT(*) AS cnt
    FROM `governence-483517.raw.events`
    WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    GROUP BY event_date, event_id
    HAVING cnt > 1
    ORDER BY event_date DESC, cnt DESC
    LIMIT 100
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", lookback_days)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    duplicates = [
        {"event_date": str(r.event_date), "event_id": r.event_id, "count": r.cnt}
        for r in rows
    ]
    total_dup_rows = sum(r.cnt - 1 for r in rows)  # Extra copies

    status = "CRITICAL" if duplicates else "OK"
    return {
        "status": status,
        "duplicate_event_ids_found": len(duplicates),
        "total_extra_rows": total_dup_rows,
        "sample_duplicates": duplicates[:10],
    }


def check_null_critical_fields(
    client: bigquery.Client, lookback_days: int
) -> Dict[str, Any]:
    """
    Check that critical fields are not null above a threshold in raw.events.
    """
    # Build a query that counts nulls for each critical field
    null_counts_select = ",\n        ".join(
        f"COUNTIF({f} IS NULL) AS null_{f}" for f in CRITICAL_NON_NULL_FIELDS
    )
    query = f"""
    SELECT
        COUNT(*) AS total_rows,
        {null_counts_select}
    FROM `governence-483517.raw.events`
    WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", lookback_days)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    if not rows:
        return {"status": "OK", "message": "No rows in lookback window"}

    row = rows[0]
    total = row.total_rows
    field_results = {}
    warnings = []

    for f in CRITICAL_NON_NULL_FIELDS:
        null_count = getattr(row, f"null_{f}", 0)
        null_pct = (null_count / total * 100) if total > 0 else 0.0
        field_results[f] = {"null_count": null_count, "null_pct": round(null_pct, 3)}
        if null_pct > MAX_NULL_PCT:
            warnings.append(f"{f}: {null_count:,} nulls ({null_pct:.2f}%)")

    status = "WARNING" if warnings else "OK"
    return {
        "status": status,
        "total_rows_checked": total,
        "fields": field_results,
        "warnings": warnings,
    }


def check_partition_continuity(
    client: bigquery.Client, lookback_days: int
) -> Dict[str, Any]:
    """
    Check for missing daily partitions in raw.events over the last N days.
    Gaps indicate pipeline downtime.
    """
    query = """
    WITH expected AS (
        SELECT FORMAT_DATE('%Y%m%d', d) AS expected_partition
        FROM UNNEST(
            GENERATE_DATE_ARRAY(
                DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY),
                DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- Exclude today (may not be complete)
            )
        ) AS d
    ),
    actual AS (
        SELECT DISTINCT partition_id
        FROM `governence-483517.raw.INFORMATION_SCHEMA.PARTITIONS`
        WHERE table_name = 'events'
          AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')
          AND partition_id >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY))
    )
    SELECT
        e.expected_partition,
        a.partition_id AS actual_partition
    FROM expected e
    LEFT JOIN actual a ON e.expected_partition = a.partition_id
    WHERE a.partition_id IS NULL
    ORDER BY e.expected_partition DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", lookback_days)]
    )
    rows = list(client.query(query, job_config=job_config).result())

    missing = [r.expected_partition for r in rows]
    status = "WARNING" if missing else "OK"
    return {
        "status": status,
        "missing_partitions": missing,
        "missing_count": len(missing),
        "lookback_days": lookback_days,
    }


def check_schema_drift(skip_api: bool = False) -> Dict[str, Any]:
    """
    Fetch a small sample from the Scan API and verify that all expected
    top-level transaction fields and event fields are present.
    Detects API format changes before they break the pipeline.
    """
    if skip_api:
        return {"status": "SKIPPED", "reason": "--skip-api-check flag set"}

    import requests

    for url in SCAN_API_URLS:
        try:
            resp = requests.post(
                f"{url.rstrip('/')}/v2/updates",
                json={"page_size": 1, "daml_value_encoding": "compact_json"},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception:
            continue
    else:
        return {
            "status": "WARNING",
            "message": "Could not reach any Scan API node for schema check",
            "urls_tried": len(SCAN_API_URLS),
        }

    updates = data.get("updates") or data.get("transactions") or []
    if not updates:
        return {"status": "WARNING", "message": "API returned 0 updates for schema check"}

    txn = updates[0]
    actual_top_fields = set(txn.keys())
    missing_top = EXPECTED_API_FIELDS - actual_top_fields
    extra_top = actual_top_fields - EXPECTED_API_FIELDS

    event_issues = []
    events_by_id = txn.get("events_by_id", {})
    for event_id, event_data in list(events_by_id.items())[:5]:
        actual_event_fields = set(event_data.keys())
        missing = EXPECTED_EVENT_FIELDS - actual_event_fields
        if missing:
            event_issues.append({"event_id": event_id, "missing_fields": list(missing)})

    warnings = []
    if missing_top:
        warnings.append(f"Missing top-level fields from API: {sorted(missing_top)}")
    if event_issues:
        warnings.append(f"Missing event fields in {len(event_issues)} events")

    # Extra fields are informational (new fields added to API — fine to track)
    status = "WARNING" if warnings else "OK"
    return {
        "status": status,
        "api_url_used": url,
        "expected_fields_present": sorted(EXPECTED_API_FIELDS - missing_top),
        "missing_top_level_fields": sorted(missing_top),
        "new_top_level_fields": sorted(extra_top),
        "event_field_issues": event_issues,
        "warnings": warnings,
    }


def check_daily_volume_trend(
    client: bigquery.Client, lookback_days: int
) -> Dict[str, Any]:
    """
    Compare today's raw.events row count to the rolling N-day average.
    Significant drops may indicate data loss; spikes may indicate duplicates.
    Only checks partitions where data is expected to be complete (not today).
    """
    query = """
    SELECT
        partition_id,
        total_rows
    FROM `governence-483517.raw.INFORMATION_SCHEMA.PARTITIONS`
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

    counts = [r.total_rows for r in rows]
    avg = sum(counts[1:]) / len(counts[1:])  # Exclude most recent day from average
    latest = counts[0]
    latest_partition = rows[0].partition_id

    pct_change = ((latest - avg) / avg * 100) if avg > 0 else 0.0
    daily = [{"partition": r.partition_id, "rows": r.total_rows} for r in rows]

    warnings = []
    if pct_change < -50:
        warnings.append(
            f"Partition {latest_partition} has {pct_change:.1f}% fewer rows than "
            f"the {len(counts)-1}-day average ({avg:,.0f}). Possible data loss."
        )
    elif pct_change > 300:
        warnings.append(
            f"Partition {latest_partition} has {pct_change:.1f}% more rows than "
            f"the {len(counts)-1}-day average ({avg:,.0f}). Possible duplicates."
        )

    status = "WARNING" if warnings else "OK"
    return {
        "status": status,
        "latest_partition": latest_partition,
        "latest_rows": latest,
        "rolling_avg_rows": round(avg, 0),
        "pct_change_vs_avg": round(pct_change, 1),
        "daily_counts": daily,
        "warnings": warnings,
    }


# ── Report Formatting ───────────────────────────────────────────────────────────

def _status_marker(status: str) -> str:
    return {"OK": "+", "WARNING": "!", "CRITICAL": "X", "SKIPPED": "-"}.get(status, "?")


def print_human_report(checks: Dict[str, Any]) -> None:
    print("=" * 70)
    print("CANTON DATA QUALITY CHECKS")
    print(f"Checked at: {checks['checked_at']}")
    print("=" * 70)

    # 1. Row counts
    print("\n--- 1. Row Count Validation (raw vs parsed) ---")
    rc = checks.get("row_count_by_partition", {})
    m = _status_marker(rc.get("status", "UNKNOWN"))
    print(f"  [{m}] {rc.get('partitions_checked', 0)} partitions checked  "
          f"max_diff={rc.get('max_diff_pct', 0):.1f}%  "
          f"[{rc.get('status', 'UNKNOWN')}]")
    for part in rc.get("partitions", [])[:7]:
        diff_marker = "+" if part["difference"] == 0 else "!"
        print(f"       [{diff_marker}] {part['partition']}: "
              f"raw={part['raw_rows']:>12,}  "
              f"parsed={part['parsed_rows']:>12,}  "
              f"diff={part['difference']:>8,}  ({part['diff_pct']:.1f}%)")
    for w in rc.get("warnings", []):
        print(f"       [!] {w}")

    # 2. Freshness
    print("\n--- 2. Data Freshness ---")
    fr = checks.get("data_freshness", {})
    for label in ["raw", "parsed"]:
        info = fr.get(label, {})
        m = _status_marker(info.get("status", "UNKNOWN"))
        lag = info.get("lag_hours", "N/A")
        partition = info.get("latest_partition", "N/A")
        print(f"  [{m}] {label:7s}: latest={partition}  lag={lag}h  [{info.get('status', 'UNKNOWN')}]")

    # 3. Timestamp consistency
    print("\n--- 3. Timestamp Consistency ---")
    ts = checks.get("timestamp_consistency", {})
    m = _status_marker(ts.get("status", "UNKNOWN"))
    print(f"  [{m}] {ts.get('total_rows_checked', 0):,} rows checked  [{ts.get('status', 'UNKNOWN')}]")
    for issue in ts.get("issues", []):
        print(f"       [!] {issue}")
    if not ts.get("issues"):
        print(f"       [+] No invalid timestamps found")

    # 4. Duplicates
    print("\n--- 4. Duplicate Event Detection ---")
    dup = checks.get("duplicate_events", {})
    m = _status_marker(dup.get("status", "UNKNOWN"))
    n = dup.get("duplicate_event_ids_found", 0)
    extras = dup.get("total_extra_rows", 0)
    print(f"  [{m}] {n} duplicate event_ids found  ({extras} extra rows)  [{dup.get('status', 'UNKNOWN')}]")
    for d in dup.get("sample_duplicates", [])[:3]:
        print(f"       [!] event_date={d['event_date']}  event_id={d['event_id'][:20]}...  count={d['count']}")

    # 5. Null fields
    print("\n--- 5. Critical Field Null Checks ---")
    nf = checks.get("null_critical_fields", {})
    m = _status_marker(nf.get("status", "UNKNOWN"))
    print(f"  [{m}] {nf.get('total_rows_checked', 0):,} rows  [{nf.get('status', 'UNKNOWN')}]")
    for field, info in nf.get("fields", {}).items():
        null_m = "+" if info["null_count"] == 0 else "!"
        print(f"       [{null_m}] {field:20s}: {info['null_count']:>8,} nulls  ({info['null_pct']:.3f}%)")
    for w in nf.get("warnings", []):
        print(f"       [!] {w}")

    # 6. Partition continuity
    print("\n--- 6. Partition Continuity ---")
    pc = checks.get("partition_continuity", {})
    m = _status_marker(pc.get("status", "UNKNOWN"))
    missing = pc.get("missing_partitions", [])
    print(f"  [{m}] {pc.get('missing_count', 0)} missing partition(s)  [{pc.get('status', 'UNKNOWN')}]")
    for mp in missing[:5]:
        print(f"       [!] Missing partition: {mp}")

    # 7. Schema drift
    print("\n--- 7. Schema Drift Detection ---")
    sd = checks.get("schema_drift", {})
    m = _status_marker(sd.get("status", "UNKNOWN"))
    print(f"  [{m}] [{sd.get('status', 'UNKNOWN')}]")
    if sd.get("api_url_used"):
        print(f"       API URL: {sd.get('api_url_used')}")
    for w in sd.get("warnings", []):
        print(f"       [!] {w}")
    if sd.get("new_top_level_fields"):
        print(f"       [i] New fields in API (may need schema update): "
              f"{sd['new_top_level_fields']}")
    if sd.get("status") == "OK":
        print(f"       [+] All expected fields present in API response")

    # 8. Volume trend
    print("\n--- 8. Daily Volume Trend ---")
    vt = checks.get("daily_volume_trend", {})
    m = _status_marker(vt.get("status", "UNKNOWN"))
    print(f"  [{m}] latest={vt.get('latest_partition', 'N/A')}  "
          f"rows={vt.get('latest_rows', 0):,}  "
          f"avg={vt.get('rolling_avg_rows', 0):,.0f}  "
          f"change={vt.get('pct_change_vs_avg', 0):+.1f}%  "
          f"[{vt.get('status', 'UNKNOWN')}]")
    for w in vt.get("warnings", []):
        print(f"       [!] {w}")
    for dc in vt.get("daily_counts", [])[:7]:
        print(f"       {dc['partition']}: {dc['rows']:>12,} rows")

    # Overall
    print("\n" + "=" * 70)
    overall = checks.get("overall_status", "UNKNOWN")
    m = _status_marker(overall)
    print(f"  [{m}] OVERALL STATUS: {overall}")
    print("=" * 70)


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Canton Data Pipeline - Data Quality Verification Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback window in days (default: {DEFAULT_LOOKBACK_DAYS})"
    )
    parser.add_argument(
        "--skip-api-check", action="store_true",
        help="Skip the live API schema drift check"
    )
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    checks: Dict[str, Any] = {}
    overall_status = "OK"

    if not args.json:
        print(f"Running data quality checks (lookback={args.days} days)...",
              file=sys.stderr)

    checks["checked_at"] = datetime.utcnow().isoformat() + "Z"
    checks["lookback_days"] = args.days

    # Run all checks
    check_fns = [
        ("row_count_by_partition", lambda: check_row_count_by_partition(client, args.days)),
        ("data_freshness",         lambda: check_data_freshness(client)),
        ("timestamp_consistency",  lambda: check_timestamp_consistency(client, args.days)),
        ("duplicate_events",       lambda: check_duplicate_events(client, args.days)),
        ("null_critical_fields",   lambda: check_null_critical_fields(client, args.days)),
        ("partition_continuity",   lambda: check_partition_continuity(client, args.days)),
        ("schema_drift",           lambda: check_schema_drift(skip_api=args.skip_api_check)),
        ("daily_volume_trend",     lambda: check_daily_volume_trend(client, args.days)),
    ]

    for name, fn in check_fns:
        try:
            checks[name] = fn()
        except Exception as exc:
            checks[name] = {"status": "CRITICAL", "error": str(exc)}

    # Determine overall status by scanning all nested statuses
    def _extract_statuses(obj) -> List[str]:
        """Recursively find all 'status' values in a nested dict."""
        statuses = []
        if isinstance(obj, dict):
            if "status" in obj:
                statuses.append(obj["status"])
            for v in obj.values():
                statuses.extend(_extract_statuses(v))
        return statuses

    for check_name, check_result in checks.items():
        if check_name in ("checked_at", "lookback_days", "overall_status"):
            continue
        for status in _extract_statuses(check_result):
            if status == "CRITICAL":
                overall_status = "CRITICAL"
            elif status == "WARNING" and overall_status != "CRITICAL":
                overall_status = "WARNING"

    checks["overall_status"] = overall_status

    if args.json:
        print(json.dumps(checks, indent=2, default=str))
    else:
        print_human_report(checks)

    # Exit code
    if overall_status == "CRITICAL":
        sys.exit(2)
    elif overall_status == "WARNING":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
