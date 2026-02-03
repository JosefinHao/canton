"""
BigQuery Client Module for Canton Blockchain Data Pipeline (Cloud Function Version)

This is a standalone version for deployment with Cloud Functions.
"""

import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
from google.api_core import retry

logger = logging.getLogger(__name__)


class BigQueryClient:
    """
    Client for interacting with Google BigQuery for Canton blockchain data.
    """

    def __init__(
        self,
        project_id: str = "governence-483517",
        raw_dataset: str = "raw",
        transformed_dataset: str = "transformed",
        raw_table: str = "events",
        parsed_table: str = "events_parsed"
    ):
        """Initialize BigQuery client."""
        self.project_id = project_id
        self.raw_dataset = raw_dataset
        self.transformed_dataset = transformed_dataset
        self.raw_table = raw_table
        self.parsed_table = parsed_table

        self.raw_table_id = f"{project_id}.{raw_dataset}.{raw_table}"
        self.parsed_table_id = f"{project_id}.{transformed_dataset}.{parsed_table}"

        self.client = bigquery.Client(project=project_id)
        logger.info(f"BigQuery client initialized for project: {project_id}")

    def get_last_processed_position(self) -> Tuple[Optional[int], Optional[str]]:
        """Get the last processed position from the raw events table."""
        query = f"""
        SELECT migration_id, record_time
        FROM `{self.raw_table_id}`
        ORDER BY migration_id DESC, record_time DESC
        LIMIT 1
        """

        try:
            query_job = self.client.query(query)
            results = list(query_job.result())

            if results:
                row = results[0]
                migration_id = row.migration_id
                record_time = row.record_time
                if isinstance(record_time, datetime):
                    record_time = record_time.isoformat()
                logger.info(f"Last processed: migration_id={migration_id}, record_time={record_time}")
                return migration_id, record_time

            logger.info("No existing data found")
            return None, None

        except NotFound:
            logger.warning(f"Table {self.raw_table_id} not found")
            return None, None
        except Exception as e:
            logger.error(f"Error getting last processed position: {e}")
            raise

    def get_last_transformed_position(self) -> Tuple[Optional[int], Optional[str]]:
        """Get the last transformed position from the parsed events table."""
        query = f"""
        SELECT migration_id, record_time
        FROM `{self.parsed_table_id}`
        ORDER BY migration_id DESC, record_time DESC
        LIMIT 1
        """

        try:
            query_job = self.client.query(query)
            results = list(query_job.result())

            if results:
                row = results[0]
                migration_id = row.migration_id
                record_time = row.record_time
                if isinstance(record_time, datetime):
                    record_time = record_time.isoformat()
                return migration_id, record_time

            return None, None

        except NotFound:
            return None, None
        except Exception as e:
            logger.error(f"Error getting last transformed position: {e}")
            raise

    def insert_raw_events(self, events: List[Dict[str, Any]]) -> int:
        """Insert raw events into BigQuery using streaming insert."""
        if not events:
            return 0

        errors = self.client.insert_rows_json(
            self.raw_table_id,
            events,
            retry=retry.Retry(deadline=60)
        )

        if errors:
            logger.error(f"Errors inserting rows: {errors}")
            return len(events) - len(errors)

        logger.info(f"Inserted {len(events)} events")
        return len(events)

    def run_transformation_query(self) -> int:
        """Run transformation query for incremental processing."""
        last_migration_id, last_record_time = self.get_last_transformed_position()

        where_clause = ""
        if last_migration_id is not None and last_record_time is not None:
            where_clause = f"""
            WHERE (migration_id > {last_migration_id})
               OR (migration_id = {last_migration_id} AND record_time > '{last_record_time}')
            """

        transformation_query = f"""
        INSERT INTO `{self.parsed_table_id}` (
            event_id, update_id, migration_id, record_time, domain_id,
            workflow_id, command_id, effective_at, offset, event_type,
            template_id, contract_id, package_name, choice, consuming,
            signatories, observers, acting_parties, witness_parties,
            child_event_ids, payload, contract_key, exercise_result,
            interface_id, created_at_ts, timestamp, raw_event, trace_context
        )
        SELECT
            event_id, update_id,
            CAST(migration_id AS INT64) as migration_id,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', record_time) as record_time,
            domain_id, workflow_id, command_id,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', effective_at) as effective_at,
            SAFE_CAST(offset AS INT64) as offset,
            event_type, template_id, contract_id, package_name, choice,
            SAFE_CAST(consuming AS BOOL) as consuming,
            CASE
                WHEN signatories IS NULL THEN []
                WHEN JSON_TYPE(SAFE.PARSE_JSON(signatories)) = 'array' THEN
                    ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(signatories))) AS item)
                ELSE []
            END as signatories,
            CASE
                WHEN observers IS NULL THEN []
                WHEN JSON_TYPE(SAFE.PARSE_JSON(observers)) = 'array' THEN
                    ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(observers))) AS item)
                ELSE []
            END as observers,
            CASE
                WHEN acting_parties IS NULL THEN []
                WHEN JSON_TYPE(SAFE.PARSE_JSON(acting_parties)) = 'array' THEN
                    ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(acting_parties))) AS item)
                ELSE []
            END as acting_parties,
            CASE
                WHEN witness_parties IS NULL THEN []
                WHEN JSON_TYPE(SAFE.PARSE_JSON(witness_parties)) = 'array' THEN
                    ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(witness_parties))) AS item)
                ELSE []
            END as witness_parties,
            CASE
                WHEN child_event_ids IS NULL THEN []
                WHEN JSON_TYPE(SAFE.PARSE_JSON(child_event_ids)) = 'array' THEN
                    ARRAY(SELECT JSON_VALUE(item) FROM UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(child_event_ids))) AS item)
                ELSE []
            END as child_event_ids,
            SAFE.PARSE_JSON(payload) as payload,
            SAFE.PARSE_JSON(contract_key) as contract_key,
            SAFE.PARSE_JSON(exercise_result) as exercise_result,
            interface_id,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', created_at_ts) as created_at_ts,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', timestamp) as timestamp,
            SAFE.PARSE_JSON(raw_event) as raw_event,
            SAFE.PARSE_JSON(trace_context) as trace_context
        FROM `{self.raw_table_id}`
        {where_clause}
        """

        try:
            query_job = self.client.query(transformation_query)
            query_job.result()
            rows_affected = query_job.num_dml_affected_rows or 0
            logger.info(f"Transformed {rows_affected} rows")
            return rows_affected
        except Exception as e:
            logger.error(f"Transformation error: {e}")
            raise

    def check_for_new_raw_data(self) -> bool:
        """Check if there's new raw data that needs to be transformed."""
        raw_pos = self.get_last_processed_position()
        parsed_pos = self.get_last_transformed_position()

        if raw_pos[0] is None:
            return False
        if parsed_pos[0] is None:
            return True
        if raw_pos[0] > parsed_pos[0]:
            return True
        if raw_pos[0] == parsed_pos[0] and raw_pos[1] > parsed_pos[1]:
            return True
        return False

    def get_table_stats(self, table_id: str) -> Dict[str, Any]:
        """Get statistics for a BigQuery table."""
        try:
            table = self.client.get_table(table_id)
            return {
                'num_rows': table.num_rows,
                'num_bytes': table.num_bytes,
                'modified': table.modified.isoformat() if table.modified else None
            }
        except NotFound:
            return {'error': f'Table {table_id} not found'}
        except Exception as e:
            return {'error': str(e)}

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get overall pipeline status."""
        return {
            'raw_table': {
                'table_id': self.raw_table_id,
                'stats': self.get_table_stats(self.raw_table_id),
                'last_position': dict(zip(['migration_id', 'record_time'], self.get_last_processed_position()))
            },
            'parsed_table': {
                'table_id': self.parsed_table_id,
                'stats': self.get_table_stats(self.parsed_table_id),
                'last_position': dict(zip(['migration_id', 'record_time'], self.get_last_transformed_position()))
            },
            'needs_transformation': self.check_for_new_raw_data()
        }

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
