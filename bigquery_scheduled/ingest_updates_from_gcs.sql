-- BigQuery Scheduled Query: Ingest new events from GCS updates
-- Schedule: Daily
--
-- This query loads new event data from the GCS updates external table
-- into the native raw.events table. It only loads days that don't
-- already exist in the native table, preventing duplicates.
--
-- Prerequisites:
-- - External table `raw.events_updates_external` must exist pointing
--   at gs://canton-bucket/raw/updates/events/*
--
-- How it works:
-- 1. Gets the latest event_date already in raw.events (very fast, partition metadata)
-- 2. Reads only newer days from the external table (GCS)
-- 3. Inserts into the native partitioned table

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
WHERE DATE(year, month, day) > (
    SELECT COALESCE(MAX(event_date), DATE('1970-01-01'))
    FROM `governence-483517.raw.events`
);
