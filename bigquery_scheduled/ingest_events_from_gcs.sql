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
    ext.event_id, ext.update_id, ext.event_type, ext.event_type_original,
    ext.synchronizer_id, ext.effective_at, ext.recorded_at, ext.timestamp,
    ext.created_at_ts, ext.contract_id, ext.template_id, ext.package_name,
    ext.migration_id, ext.signatories, ext.observers, ext.acting_parties,
    ext.witness_parties, ext.child_event_ids, ext.choice, ext.interface_id,
    ext.consuming, ext.reassignment_counter, ext.source_synchronizer,
    ext.target_synchronizer, ext.unassign_id, ext.submitter,
    ext.payload, ext.contract_key, ext.exercise_result, ext.raw_event,
    ext.trace_context, ext.year, ext.month, ext.day,
    DATE(ext.year, ext.month, ext.day) AS event_date
FROM `governence-483517.raw.events_updates_external` ext
WHERE DATE(ext.year, ext.month, ext.day) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND NOT EXISTS (
    SELECT 1
    FROM `governence-483517.raw.events` e
    WHERE e.event_id = ext.event_id
      AND e.event_date = DATE(ext.year, ext.month, ext.day)
  );
