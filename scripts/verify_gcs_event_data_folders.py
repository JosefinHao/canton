#!/usr/bin/env python3
"""
Verify that GCS event parquet files are stored in the correct year/month/day
folders based on their effective_at timestamps.

Reads only the effective_at column from each parquet file for efficiency.
Compares the UTC date from effective_at to the folder's year/month/day partition.

Usage:
    pip install google-cloud-storage pyarrow
    python scripts/verify_gcs_event_data_folders.py \
        --bucket YOUR_BUCKET \
        --prefix raw/backfill/events/migration=0
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


def parse_effective_at(value: str):
    """Parse effective_at string like '2024-12-12 12:37:59.259000 UTC' to (year, month, day)."""
    # Strip trailing " UTC" and parse
    clean = value.strip()
    if clean.endswith(" UTC"):
        clean = clean[:-4]
    # Handle variable microsecond precision
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(clean, fmt)
            return (dt.year, dt.month, dt.day)
        except ValueError:
            continue
    return None


def verify_bucket(bucket_name: str, prefix: str, start_month: int = 6, start_day: int = 24):
    """Verify all 2024 event data from the given start date."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Stats
    total_files = 0
    total_rows = 0
    correct_rows = 0
    mismatched_rows = 0
    mismatches = []  # List of (blob_name, folder_date, effective_at_date, count)
    errors = []

    # Iterate over months June (6) through December (12) of 2024
    for month in range(start_month, 13):
        day_start = start_day if month == start_month else 1
        # List all blobs for this month
        month_prefix = f"{prefix}/year=2024/month={month}/"
        blobs = list(bucket.list_blobs(prefix=month_prefix))
        parquet_blobs = [b for b in blobs if b.name.endswith(".parquet")]

        if not parquet_blobs:
            print(f"  month={month}: no parquet files found")
            continue

        print(f"  month={month}: {len(parquet_blobs)} parquet file(s)")

        for blob in parquet_blobs:
            folder_date = parse_folder_date(blob.name)
            if folder_date is None:
                errors.append((blob.name, "Could not parse folder date"))
                continue

            # Skip days before start_day in the start_month
            if month == start_month and folder_date[2] < day_start:
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

                    row_date = parse_effective_at(str(s))
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
        default="raw/backfill/events/migration=0",
        help="GCS prefix before year= partition (default: raw/backfill/events/migration=0)",
    )
    parser.add_argument(
        "--start-month", type=int, default=6, help="Start month (default: 6 for June)"
    )
    parser.add_argument(
        "--start-day", type=int, default=24, help="Start day in start month (default: 24)"
    )
    args = parser.parse_args()

    print(f"Bucket:  {args.bucket}")
    print(f"Prefix:  {args.prefix}")
    print(f"Range:   2024-{args.start_month:02d}-{args.start_day:02d} through 2024-12-31")
    print("-" * 70)

    ok = verify_bucket(args.bucket, args.prefix, args.start_month, args.start_day)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
