-- BigQuery Scheduled Query: Ingest new events from GCS into raw.events
-- Schedule: Daily at 00:00 UTC
--
-- This query loads new event data from the GCS updates external table
-- (canton-bucket/raw/updates/events/) into the native raw.events table.
-- It deduplicates to prevent inserting rows that already exist.
--
-- Data source: raw.events_updates_external
--   Points to: gs://canton-bucket/raw/updates/events/*
--   Parquet files use nested LIST encoding (STRUCT<list ARRAY<STRUCT<element STRING>>>)
--   for party lists, which is flattened to ARRAY<STRING> during ingest.
--   Native types for migration_id (INT64), consuming (BOOL), reassignment_counter (INT64).
--
-- Prerequisites:
-- - External table `raw.events_updates_external` must exist pointing
--   at gs://canton-bucket/raw/updates/events/*
--
-- How it works:
-- 1. Scans yesterday and today from the GCS external table (partition pruning)
-- 2. Uses NOT EXISTS to skip rows already in raw.events (dedup on event_id + event_date)
-- 3. Inserts only truly new rows into the native partitioned table

INSERT INTO `governence-483517.raw.events` (
    event_id, update_id, event_type, event_type_original,
    synchronizer_id, effective_at, recorded_at, timestamp,
    created_at_ts, contract_id, template_id, package_name,
    migration_id, signatories, observers, acting_parties,
    witness_parties, child_event_ids, choice, interface_id,
    consuming, reassignment_counter, source_synchronizer,
    target_synchronizer, unassign_id, submitter,
    payload, contract_key, exercise_result, raw_event,
    trace_context, year, month, day, migration, event_date
)
SELECT
    ext.event_id, ext.update_id, ext.event_type, ext.event_type_original,
    ext.synchronizer_id, ext.effective_at, ext.recorded_at, ext.timestamp,
    ext.created_at_ts, ext.contract_id, ext.template_id, ext.package_name,
    ext.migration_id,
    ARRAY(SELECT element FROM UNNEST(ext.signatories.list)) AS signatories,
    ARRAY(SELECT element FROM UNNEST(ext.observers.list)) AS observers,
    ARRAY(SELECT element FROM UNNEST(ext.acting_parties.list)) AS acting_parties,
    ARRAY(SELECT element FROM UNNEST(ext.witness_parties.list)) AS witness_parties,
    ARRAY(SELECT element FROM UNNEST(ext.child_event_ids.list)) AS child_event_ids,
    ext.choice, ext.interface_id,
    ext.consuming, ext.reassignment_counter, ext.source_synchronizer,
    ext.target_synchronizer, ext.unassign_id, ext.submitter,
    ext.payload, ext.contract_key, ext.exercise_result, ext.raw_event,
    ext.trace_context, ext.year, ext.month, ext.day, ext.migration,
    DATE(ext.year, ext.month, ext.day) AS event_date
FROM `governence-483517.raw.events_updates_external` ext
WHERE
  -- Filter on raw Hive partition columns so BigQuery can prune files.
  -- DATE() wrapping prevents pruning, so we match yesterday + today explicitly.
  (   (ext.year = EXTRACT(YEAR FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
       AND ext.month = EXTRACT(MONTH FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
       AND ext.day = EXTRACT(DAY FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)))
   OR (ext.year = EXTRACT(YEAR FROM CURRENT_DATE())
       AND ext.month = EXTRACT(MONTH FROM CURRENT_DATE())
       AND ext.day = EXTRACT(DAY FROM CURRENT_DATE()))
  )
  AND NOT EXISTS (
    SELECT 1
    FROM `governence-483517.raw.events` e
    WHERE e.event_id = ext.event_id
      AND e.event_date = DATE(ext.year, ext.month, ext.day)
  );
