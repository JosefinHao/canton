#!/usr/bin/env python3
"""
Verify that GCS event parquet files are stored in the correct year/month/day
folders based on their effective_at timestamps.

Reads only the effective_at column from each parquet file for efficiency.
Compares the UTC date from effective_at to the folder's year/month/day partition.

Usage:
    pip install google-cloud-storage pyarrow

    # Single migration:
    python scripts/verify_gcs_event_data_folders.py \
        --bucket YOUR_BUCKET \
        --prefix raw/backfill/events/migration=0

    # Multiple migrations (0 through 4):
    python scripts/verify_gcs_event_data_folders.py \
        --bucket YOUR_BUCKET \
        --migrations 0 1 2 3 4
"""

import argparse
import io
import re
import sys
from collections import defaultdict
from datetime import datetime

from google.cloud import storage

# Lazy import - pyarrow.parquet
import pyarrow.parquet as pq


def parse_folder_date(blob_name: str):
    """Extract year, month, day from the blob path like .../year=2024/month=7/day=15/..."""
    match = re.search(
        r"year=(\d{4})/month=(\d{1,2})/day=(\d{1,2})/", blob_name
    )
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def parse_effective_at(value):
    """Parse effective_at to (year, month, day).

    Handles:
      - datetime / Timestamp objects (from pyarrow)
      - ISO 8601 strings like '2024-06-24T23:59:52.172Z'
      - BigQuery-style strings like '2024-12-12 12:37:59.259000 UTC'
    """
    # If pyarrow already decoded it to a datetime-like object, use it directly
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return (value.year, value.month, value.day)

    # Otherwise treat as string
    clean = str(value).strip()

    # Strip timezone suffixes
    if clean.endswith("Z"):
        clean = clean[:-1]
    if clean.endswith(" UTC"):
        clean = clean[:-4]

    # Normalise ISO separator
    clean = clean.replace("T", " ")

    # Handle variable precision
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(clean, fmt)
            return (dt.year, dt.month, dt.day)
        except ValueError:
            continue
    return None


def verify_bucket(bucket_name: str, prefix: str, start_month: int = 6, start_day: int = 24):
    """Verify event data across all years found under *prefix*."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Stats
    total_files = 0
    total_rows = 0
    correct_rows = 0
    mismatched_rows = 0
    mismatches = []  # List of (blob_name, folder_date, effective_at_date, count)
    errors = []

    # Discover which year= partitions exist under this prefix
    all_blobs = list(bucket.list_blobs(prefix=f"{prefix}/year="))
    parquet_blobs_all = [b for b in all_blobs if b.name.endswith(".parquet")]

    # Collect unique (year, month) pairs from blob paths
    year_months = set()
    for blob in parquet_blobs_all:
        folder_date = parse_folder_date(blob.name)
        if folder_date:
            year_months.add((folder_date[0], folder_date[1]))

    if not year_months:
        print("  No parquet files found under this prefix.")
        return True

    first_year = min(ym[0] for ym in year_months)

    for year, month in sorted(year_months):
        # Apply start filter: skip months/days before the start date in the first year
        if year == first_year and month < start_month:
            continue
        day_start = start_day if (year == first_year and month == start_month) else 1

        month_prefix = f"{prefix}/year={year}/month={month}/"
        blobs = [b for b in parquet_blobs_all if b.name.startswith(month_prefix)]

        if not blobs:
            continue

        print(f"  year={year} month={month}: {len(blobs)} parquet file(s)")

        for blob in blobs:
            folder_date = parse_folder_date(blob.name)
            if folder_date is None:
                errors.append((blob.name, "Could not parse folder date"))
                continue

            # Skip days before start_day in the start year/month
            if folder_date[2] < day_start:
                continue

            total_files += 1

            try:
                # Download blob into memory and read only the effective_at column
                data = blob.download_as_bytes()
                table = pq.read_table(io.BytesIO(data), columns=["effective_at"])
                effective_at_col = table.column("effective_at")

                file_correct = 0
                file_mismatched = 0
                mismatch_dates = defaultdict(int)

                for val in effective_at_col:
                    s = val.as_py()
                    if s is None:
                        errors.append((blob.name, "NULL effective_at"))
                        continue

                    row_date = parse_effective_at(s)
                    if row_date is None:
                        errors.append((blob.name, f"Unparseable: {s}"))
                        continue

                    total_rows += 1
                    if row_date == folder_date:
                        file_correct += 1
                    else:
                        file_mismatched += 1
                        mismatch_dates[row_date] += 1

                correct_rows += file_correct
                mismatched_rows += file_mismatched

                if file_mismatched > 0:
                    for actual_date, count in sorted(mismatch_dates.items()):
                        mismatches.append((blob.name, folder_date, actual_date, count))
                    print(
                        f"    MISMATCH {blob.name.split('/')[-1]}: "
                        f"folder=({folder_date}) but {file_mismatched} rows have wrong dates"
                    )

            except Exception as e:
                errors.append((blob.name, str(e)))
                print(f"    ERROR reading {blob.name}: {e}")

    # --- Report ---
    print("\n" + "=" * 70)
    print("VERIFICATION REPORT")
    print("=" * 70)
    print(f"Total parquet files checked: {total_files}")
    print(f"Total rows checked:          {total_rows}")
    print(f"Correctly placed rows:       {correct_rows}")
    print(f"Mismatched rows:             {mismatched_rows}")
    if total_rows > 0:
        pct = correct_rows / total_rows * 100
        print(f"Accuracy:                    {pct:.4f}%")

    if mismatches:
        print(f"\n--- Mismatches ({len(mismatches)} distinct file/date combos) ---")
        for blob_name, folder_date, actual_date, count in mismatches:
            short_name = "/".join(blob_name.split("/")[-4:])
            print(
                f"  File: {short_name}  "
                f"folder=({folder_date[0]:04d}-{folder_date[1]:02d}-{folder_date[2]:02d})  "
                f"actual=({actual_date[0]:04d}-{actual_date[1]:02d}-{actual_date[2]:02d})  "
                f"count={count}"
            )

    if errors:
        print(f"\n--- Errors ({len(errors)}) ---")
        for blob_name, msg in errors[:20]:
            short_name = "/".join(blob_name.split("/")[-4:])
            print(f"  {short_name}: {msg}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors")

    print("=" * 70)

    return mismatched_rows == 0 and len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Verify GCS event data folder placement against effective_at timestamps"
    )
    parser.add_argument("--bucket", required=True, help="GCS bucket name")
    parser.add_argument(
        "--prefix",
        default=None,
        help="GCS prefix before year= partition (e.g. raw/backfill/events/migration=0)",
    )
    parser.add_argument(
        "--migrations",
        nargs="+",
        type=int,
        default=None,
        help="Migration IDs to verify (e.g. --migrations 0 1 2 3 4). "
             "Builds prefixes as raw/backfill/events/migration=<N>.",
    )
    parser.add_argument(
        "--start-month", type=int, default=6, help="Start month (default: 6 for June)"
    )
    parser.add_argument(
        "--start-day", type=int, default=24, help="Start day in start month (default: 24)"
    )
    args = parser.parse_args()

    # Build list of prefixes to verify
    if args.migrations is not None:
        prefixes = [f"raw/backfill/events/migration={m}" for m in args.migrations]
    elif args.prefix is not None:
        prefixes = [args.prefix]
    else:
        prefixes = ["raw/backfill/events/migration=0"]

    all_ok = True
    for prefix in prefixes:
        print("")
        print(f"Bucket:  {args.bucket}")
        print(f"Prefix:  {prefix}")
        print(f"Start:   month={args.start_month:02d} day={args.start_day:02d} (all years)")
        print("-" * 70)

        ok = verify_bucket(args.bucket, prefix, args.start_month, args.start_day)
        if not ok:
            all_ok = False

    if len(prefixes) > 1:
        print("")
        print("=" * 70)
        print("OVERALL RESULT")
        print("=" * 70)
        if all_ok:
            print("ALL migrations passed verification.")
        else:
            print("ONE OR MORE migrations had mismatches or errors.")
        print("=" * 70)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
