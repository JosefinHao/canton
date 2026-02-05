-- BigQuery Scheduled Query: Transform raw events to parsed format
-- Schedule: Every 15 minutes
--
-- This query incrementally transforms new rows from raw.events to transformed.events_parsed
-- It only processes records that don't exist in the parsed table yet.
--
-- Schema notes:
-- - Raw table uses 'recorded_at' (STRING) for timestamp, 'synchronizer_id' for domain
-- - Party arrays use nested format: {list: [{element: "party1"}, {element: "party2"}]}
-- - Parsed table converts timestamps to TIMESTAMP type and flattens arrays

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
    day
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
    -- Flatten nested arrays (list[].element structure)
    ARRAY(SELECT e.element FROM UNNEST(r.signatories.list) AS e) as signatories,
    ARRAY(SELECT e.element FROM UNNEST(r.observers.list) AS e) as observers,
    ARRAY(SELECT e.element FROM UNNEST(r.acting_parties.list) AS e) as acting_parties,
    ARRAY(SELECT e.element FROM UNNEST(r.witness_parties.list) AS e) as witness_parties,
    ARRAY(SELECT e.element FROM UNNEST(r.child_event_ids.list) AS e) as child_event_ids,
    -- Other fields
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
    r.day
FROM `governence-483517.raw.events` r
LEFT JOIN `governence-483517.transformed.events_parsed` p
    ON r.event_id = p.event_id
WHERE p.event_id IS NULL;
