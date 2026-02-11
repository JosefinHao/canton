-- BigQuery Scheduled Query: Ingest new events from GCS into raw.events
-- Schedule: Daily
--
-- This query loads new event data from the GCS external table
-- (canton-bucket/raw/updates/events/) into the native raw.events table.
-- It deduplicates to prevent inserting rows that already exist.
--
-- Prerequisites:
-- - External table `raw.events_updates_external` must exist pointing
--   at gs://canton-bucket/raw/updates/events/*
--
-- How it works:
-- 1. Scans yesterday and today from the GCS external table (partition pruning)
-- 2. Uses NOT EXISTS to skip rows already in raw.events (dedup on event_id + event_date)
-- 3. Inserts only truly new rows into the native partitioned table
-- The 1-day lookback window keeps daily costs minimal (~80 GB for both stages).

INSERT INTO `governence-483517.raw.events` (
    event_id, update_id, event_type, event_type_original,
    synchronizer_id, effective_at, recorded_at, timestamp,
    created_at_ts, contract_id, template_id, package_name,
    migration_id, signatories, observers, acting_parties,
    witness_parties, child_event_ids, choice, interface_id,
    consuming, reassignment_counter, source_synchronizer,
    target_synchronizer, unassign_id, submitter,
    payload, contract_key, exercise_result, raw_event,
    trace_context, year, month, day, event_date
)
SELECT
    event_id, update_id, event_type, event_type_original,
    synchronizer_id, effective_at, recorded_at, timestamp,
    created_at_ts, contract_id, template_id, package_name,
    migration_id, signatories, observers, acting_parties,
    witness_parties, child_event_ids, choice, interface_id,
    consuming, reassignment_counter, source_synchronizer,
    target_synchronizer, unassign_id, submitter,
    payload, contract_key, exercise_result, raw_event,
    trace_context, year, month, day,
    DATE(year, month, day) AS event_date
FROM `governence-483517.raw.events_updates_external`
WHERE DATE(year, month, day) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND NOT EXISTS (
    SELECT 1
    FROM `governence-483517.raw.events` e
    WHERE e.event_id = event_id
      AND e.event_date = DATE(year, month, day)
  );
