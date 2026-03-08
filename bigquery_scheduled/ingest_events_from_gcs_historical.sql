-- BigQuery: Ingest ALL historical events from GCS into raw.events
--
-- This loads from TWO GCS sources into raw.events:
--   1. raw.events_external         → gs://canton-bucket/raw/backfill/events/*
--      (historical backfill data from 2024 through ~March 3, 2026)
--   2. raw.events_updates_external → gs://canton-bucket/raw/updates/events/*
--      (ongoing updates data from ~March 3, 2026 onward)
--
-- Both external tables have the same parquet schema (nested LIST encoding
-- STRUCT<list ARRAY<STRUCT<element STRING>>> for party lists, which is
-- flattened to ARRAY<STRING> during ingest; native INT64/BOOL for typed fields).
--
-- Dedup: rows already in raw.events are skipped via NOT EXISTS on
-- (event_id, event_date).  This also handles the overlap at the
-- March 3 boundary — if the same event appears in both sources,
-- only the first INSERT succeeds.
--
-- WARNING — this query reads BOTH full external tables.  Run it only
-- for the initial historical load, then switch to the daily scheduled
-- query (ingest_events_from_gcs.sql) which reads only from
-- events_updates_external with a 1-day lookback window.

-- =====================================================================
-- Part 1: Ingest from backfill (2024 – ~March 3, 2026)
-- =====================================================================
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
FROM `governence-483517.raw.events_external` ext
WHERE NOT EXISTS (
    SELECT 1
    FROM `governence-483517.raw.events` e
    WHERE e.event_id = ext.event_id
      AND e.event_date = DATE(ext.year, ext.month, ext.day)
);

-- =====================================================================
-- Part 2: Ingest from updates (~March 3, 2026 – present)
-- =====================================================================
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
WHERE NOT EXISTS (
    SELECT 1
    FROM `governence-483517.raw.events` e
    WHERE e.event_id = ext.event_id
      AND e.event_date = DATE(ext.year, ext.month, ext.day)
);
