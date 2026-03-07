-- BigQuery: Transform ALL historical raw events to parsed format
--
-- This is the full-backfill variant of transform_events.sql.
-- It scans the ENTIRE raw.events table (no date filter) so that all
-- historical partitions are transformed.  Dedup logic is identical:
-- rows already in transformed.events_parsed are skipped.
--
-- WARNING — this query reads the full raw.events table.  Run it only
-- after the historical ingest is complete, then switch to the daily
-- scheduled query (transform_events.sql) which has a 1-day lookback.

INSERT INTO `governence-483517.transformed.events_parsed` (
    event_id,
    update_id,
    contract_id,
    template_id,
    package_name,
    event_type,
    event_type_original,
    synchronizer_id,
    migration_id,
    choice,
    interface_id,
    consuming,
    effective_at,
    recorded_at,
    timestamp,
    created_at_ts,
    signatories,
    observers,
    acting_parties,
    witness_parties,
    child_event_ids,
    reassignment_counter,
    source_synchronizer,
    target_synchronizer,
    unassign_id,
    submitter,
    payload,
    contract_key,
    exercise_result,
    raw_event,
    trace_context,
    year,
    month,
    day,
    migration,
    event_date
)
SELECT
    r.event_id,
    r.update_id,
    r.contract_id,
    r.template_id,
    r.package_name,
    r.event_type,
    r.event_type_original,
    r.synchronizer_id,
    r.migration_id,
    r.choice,
    r.interface_id,
    r.consuming,
    -- Parse timestamps
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.effective_at) as effective_at,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.recorded_at) as recorded_at,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.timestamp) as timestamp,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.created_at_ts) as created_at_ts,
    -- Party arrays are already flat ARRAY<STRING> — pass through directly
    r.signatories,
    r.observers,
    r.acting_parties,
    r.witness_parties,
    r.child_event_ids,
    -- Other fields (already properly typed in raw)
    r.reassignment_counter,
    r.source_synchronizer,
    r.target_synchronizer,
    r.unassign_id,
    r.submitter,
    -- Parse JSON fields
    SAFE.PARSE_JSON(r.payload) as payload,
    SAFE.PARSE_JSON(r.contract_key) as contract_key,
    SAFE.PARSE_JSON(r.exercise_result) as exercise_result,
    SAFE.PARSE_JSON(r.raw_event) as raw_event,
    SAFE.PARSE_JSON(r.trace_context) as trace_context,
    -- Date parts
    r.year,
    r.month,
    r.day,
    r.migration,
    r.event_date
FROM `governence-483517.raw.events` r
WHERE NOT EXISTS (
    SELECT 1
    FROM `governence-483517.transformed.events_parsed` p
    WHERE p.event_id = r.event_id
      AND p.event_date = r.event_date
);
