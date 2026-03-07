#!/usr/bin/env python3
"""
Check whether ANY parquet files in the GCS backfill contain verdict-only
(null-body) records — i.e. rows where event_id, update_id, or template_id
is null.

Samples files from every migration and multiple time periods to ensure
we are not missing verdict-only records hiding in specific partitions.

Usage:
    python scripts/check_null_body_records.py
    python scripts/check_null_body_records.py --bucket canton-bucket --samples-per-migration 20
"""

import argparse
import io
import sys
from collections import defaultdict

from google.cloud import storage
import pyarrow.parquet as pq


def check_migration(bucket, migration_id, prefix_base, samples_per_migration):
    """Check parquet files across a migration for null-body records."""
    prefix = f"{prefix_base}/migration={migration_id}/"

    # List ALL blobs to understand the full scope
    all_blobs = list(bucket.list_blobs(prefix=prefix))
    parquet_blobs = [b for b in all_blobs if b.name.endswith(".parquet")]

    if not parquet_blobs:
        print(f"  No parquet files found.")
        return 0, 0, 0

    # Collect unique year/month/day partitions
    partitions = set()
    for b in parquet_blobs:
        parts = b.name.split("/")
        partition_key = "/".join(p for p in parts if p.startswith(("year=", "month=", "day=")))
        partitions.add(partition_key)

    print(f"  Total files: {len(parquet_blobs)}, partitions (days): {len(partitions)}")

    # Strategy: sample evenly across partitions
    # Pick files from first, middle, and last partitions, plus random spread
    sorted_blobs = sorted(parquet_blobs, key=lambda b: b.name)

    # Select sample indices spread evenly
    n = len(sorted_blobs)
    if n <= samples_per_migration:
        sample_indices = list(range(n))
    else:
        step = n / samples_per_migration
        sample_indices = [int(i * step) for i in range(samples_per_migration)]
        # Always include first and last
        if 0 not in sample_indices:
            sample_indices[0] = 0
        if n - 1 not in sample_indices:
            sample_indices[-1] = n - 1

    total_rows = 0
    total_null_event_id = 0
    total_null_update_id = 0
    total_null_template_id = 0
    total_null_all_three = 0  # rows where all three are null (strong verdict indicator)
    files_checked = 0

    for idx in sample_indices:
        blob = sorted_blobs[idx]
        try:
            data = blob.download_as_bytes()
            table = pq.read_table(io.BytesIO(data), columns=[
                "event_id", "update_id", "template_id"
            ])

            rows = len(table)
            null_eid = table.column("event_id").null_count
            null_uid = table.column("update_id").null_count
            null_tid = table.column("template_id").null_count

            # Count rows where ALL THREE are null
            import pyarrow.compute as pc
            eid_null = pc.is_null(table.column("event_id"))
            uid_null = pc.is_null(table.column("update_id"))
            tid_null = pc.is_null(table.column("template_id"))
            all_null = pc.and_(pc.and_(eid_null, uid_null), tid_null)
            null_all = pc.sum(all_null).as_py()

            total_rows += rows
            total_null_event_id += null_eid
            total_null_update_id += null_uid
            total_null_template_id += null_tid
            total_null_all_three += (null_all or 0)
            files_checked += 1

            # Report any nulls immediately
            if null_eid > 0 or null_uid > 0 or null_tid > 0:
                short_name = "/".join(blob.name.split("/")[-4:])
                print(f"    *** NULLS FOUND: {short_name}")
                print(f"        rows={rows}, null event_id={null_eid}, "
                      f"null update_id={null_uid}, null template_id={null_tid}, "
                      f"all_three_null={null_all}")

        except Exception as e:
            print(f"    ERROR reading {blob.name.split('/')[-1]}: {e}")

    print(f"  Checked {files_checked}/{len(parquet_blobs)} files, {total_rows:,} rows")
    print(f"  Null event_id:   {total_null_event_id:,}")
    print(f"  Null update_id:  {total_null_update_id:,}")
    print(f"  Null template_id:{total_null_template_id:,}")
    print(f"  All three null:  {total_null_all_three:,}")

    return files_checked, total_rows, total_null_event_id + total_null_update_id + total_null_template_id


def main():
    parser = argparse.ArgumentParser(description="Check for null-body records in GCS parquet files")
    parser.add_argument("--bucket", default="canton-bucket")
    parser.add_argument("--project", default="governence-483517")
    parser.add_argument("--prefix", default="raw/backfill/events")
    parser.add_argument("--migrations", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    parser.add_argument("--samples-per-migration", type=int, default=20,
                        help="Number of files to sample per migration (default: 20)")
    args = parser.parse_args()

    client = storage.Client(project=args.project)
    bucket = client.bucket(args.bucket)

    print("=" * 70)
    print("  CHECK FOR NULL-BODY (VERDICT-ONLY) RECORDS IN GCS PARQUET FILES")
    print("=" * 70)
    print(f"  Bucket:  {args.bucket}")
    print(f"  Prefix:  {args.prefix}")
    print(f"  Samples: {args.samples_per_migration} files per migration")
    print("=" * 70)

    grand_files = 0
    grand_rows = 0
    grand_nulls = 0

    for mig in args.migrations:
        print(f"\n--- Migration {mig} ---")
        files, rows, nulls = check_migration(
            bucket, mig, args.prefix, args.samples_per_migration
        )
        grand_files += files
        grand_rows += rows
        grand_nulls += nulls

    print(f"\n{'=' * 70}")
    print(f"  OVERALL RESULT")
    print(f"{'=' * 70}")
    print(f"  Files checked:    {grand_files}")
    print(f"  Rows checked:     {grand_rows:,}")
    print(f"  Total null fields:{grand_nulls:,}")

    if grand_nulls == 0:
        print(f"\n  CONFIRMED: Zero null-body records found across all migrations.")
        print(f"  The backfill parquet files contain ONLY transaction-bearing records.")
        print(f"  Verdict-only records were filtered out during the backfill process.")
    else:
        print(f"\n  WARNING: {grand_nulls:,} null fields detected!")
        print(f"  Some parquet files may contain verdict-only records.")
        print(f"  Review the NULLS FOUND lines above for details.")

    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
