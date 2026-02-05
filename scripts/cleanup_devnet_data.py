#!/usr/bin/env python3
"""
Script to clean up DevNet data and prepare for MainNet ingestion.

Run on your VM:
    python3 scripts/cleanup_devnet_data.py
"""

import sys
sys.path.insert(0, '/home/user/canton')

from google.cloud import bigquery

def main():
    client = bigquery.Client(project='governence-483517')

    # Step 1: Delete DevNet data from raw.events
    print("=" * 60)
    print("Step 1: Deleting DevNet data from raw.events")
    print("=" * 60)

    delete_query = """
    DELETE FROM `governence-483517.raw.events`
    WHERE migration_id = 1
      AND recorded_at > '2026-01-22T19:02:03.979Z'
    """

    try:
        print("Running DELETE query (this may take a moment)...")
        job = client.query(delete_query)
        result = job.result()
        print(f"✓ DevNet data deleted. Rows affected: {job.num_dml_affected_rows}")
    except Exception as e:
        print(f"✗ Error deleting data: {e}")
        print("\nIf you see 'streaming buffer' error, wait a bit longer and retry.")
        return 1

    # Step 2: Reset the ingestion state table
    print("\n" + "=" * 60)
    print("Step 2: Resetting ingestion state table")
    print("=" * 60)

    reset_state_query = """
    DELETE FROM `governence-483517.raw.ingestion_state` WHERE TRUE
    """

    try:
        print("Clearing ingestion_state table...")
        job = client.query(reset_state_query)
        result = job.result()
        print(f"✓ State table cleared. Rows affected: {job.num_dml_affected_rows}")
    except Exception as e:
        print(f"✗ Error resetting state table: {e}")
        return 1

    # Step 3: Verify cleanup
    print("\n" + "=" * 60)
    print("Step 3: Verifying cleanup")
    print("=" * 60)

    count_query = """
    SELECT
        COUNT(*) as total_rows,
        MAX(migration_id) as max_migration_id,
        MAX(recorded_at) as max_recorded_at
    FROM `governence-483517.raw.events`
    """

    try:
        job = client.query(count_query)
        results = list(job.result())
        if results:
            row = results[0]
            print(f"Total rows remaining: {row.total_rows}")
            print(f"Max migration_id: {row.max_migration_id}")
            print(f"Max recorded_at: {row.max_recorded_at}")
    except Exception as e:
        print(f"Warning: Could not verify cleanup: {e}")

    print("\n" + "=" * 60)
    print("Cleanup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Test MainNet connectivity:")
    print("   curl -s --max-time 10 https://scan.sv-1.global.canton.network.sync.global/api/scan/v0/dso")
    print("\n2. Run MainNet ingestion:")
    print("   cd /home/user/canton && python3 scripts/run_ingestion.py --page-size 10 --batch-size 10 --max-pages 2")

    return 0

if __name__ == "__main__":
    sys.exit(main())
