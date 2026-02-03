-- BigQuery Scheduled Query: Transform raw events to parsed format
-- Schedule: Every 15 minutes
--
-- This query incrementally transforms new rows from raw.events to transformed.events_parsed
-- It only processes records that don't exist in the parsed table yet.

INSERT INTO `governence-483517.transformed.events_parsed` (
    event_id,
    update_id,
    migration_id,
    record_time,
    domain_id,
    workflow_id,
    command_id,
    effective_at,
    offset,
    event_type,
    template_id,
    contract_id,
    package_name,
    choice,
    consuming,
    signatories,
    observers,
    acting_parties,
    witness_parties,
    child_event_ids,
    payload,
    contract_key,
    exercise_result,
    interface_id,
    created_at_ts,
    timestamp,
    raw_event,
    trace_context
)
SELECT
    r.event_id,
    r.update_id,
    CAST(r.migration_id AS INT64) as migration_id,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.record_time) as record_time,
    r.domain_id,
    r.workflow_id,
    r.command_id,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.effective_at) as effective_at,
    SAFE_CAST(r.offset AS INT64) as offset,
    r.event_type,
    r.template_id,
    r.contract_id,
    r.package_name,
    r.choice,
    SAFE_CAST(r.consuming AS BOOL) as consuming,
    -- Parse signatories array
    CASE
        WHEN r.signatories IS NULL THEN []
        WHEN JSON_TYPE(SAFE.PARSE_JSON(r.signatories)) = 'array' THEN
            ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(r.signatories))) AS item)
        ELSE []
    END as signatories,
    -- Parse observers array
    CASE
        WHEN r.observers IS NULL THEN []
        WHEN JSON_TYPE(SAFE.PARSE_JSON(r.observers)) = 'array' THEN
            ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(r.observers))) AS item)
        ELSE []
    END as observers,
    -- Parse acting_parties array
    CASE
        WHEN r.acting_parties IS NULL THEN []
        WHEN JSON_TYPE(SAFE.PARSE_JSON(r.acting_parties)) = 'array' THEN
            ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(r.acting_parties))) AS item)
        ELSE []
    END as acting_parties,
    -- Parse witness_parties array
    CASE
        WHEN r.witness_parties IS NULL THEN []
        WHEN JSON_TYPE(SAFE.PARSE_JSON(r.witness_parties)) = 'array' THEN
            ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(r.witness_parties))) AS item)
        ELSE []
    END as witness_parties,
    -- Parse child_event_ids array
    CASE
        WHEN r.child_event_ids IS NULL THEN []
        WHEN JSON_TYPE(SAFE.PARSE_JSON(r.child_event_ids)) = 'array' THEN
            ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(r.child_event_ids))) AS item)
        ELSE []
    END as child_event_ids,
    -- Parse JSON fields
    SAFE.PARSE_JSON(r.payload) as payload,
    SAFE.PARSE_JSON(r.contract_key) as contract_key,
    SAFE.PARSE_JSON(r.exercise_result) as exercise_result,
    r.interface_id,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.created_at_ts) as created_at_ts,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', r.timestamp) as timestamp,
    SAFE.PARSE_JSON(r.raw_event) as raw_event,
    SAFE.PARSE_JSON(r.trace_context) as trace_context
FROM `governence-483517.raw.events` r
LEFT JOIN `governence-483517.transformed.events_parsed` p
    ON r.event_id = p.event_id
WHERE p.event_id IS NULL;
