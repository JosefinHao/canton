-- BigQuery Scheduled Query: Check GCS upstream data freshness
-- Schedule: Daily at 23:30 UTC (before ingest at 00:00 UTC)
--
-- Asserts that the upstream GCS data source has parquet files for yesterday
-- or today. If the upstream pipeline that writes to GCS has stalled, this
-- query FAILS — triggering the existing "Canton: Scheduled Query Failures"
-- alert policy, which sends an email notification.
--
-- This catches the silent failure scenario where ingest_events_from_gcs.sql
-- runs successfully but ingests 0 rows because no new files exist in GCS.
--
-- Display name: Canton: check_gcs_freshness

ASSERT (
  SELECT MAX(DATE(year, month, day)) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  FROM `governence-483517.raw.events_updates_external`
  WHERE year >= EXTRACT(YEAR FROM DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY))
    AND month >= EXTRACT(MONTH FROM DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY))
) AS 'GCS upstream data is stale: no new parquet files found for yesterday or today. The upstream process writing to gs://canton-bucket/raw/updates/events/ may have stopped.';
