"""
BigQuery Client Module for Canton Blockchain Data Pipeline

Matches the actual schema of:
- Raw table: governence-483517.raw.events
- Parsed table: governence-483517.transformed.events_parsed
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
    """Client for interacting with Google BigQuery for Canton blockchain data."""

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
        SELECT migration_id, recorded_at
        FROM `{self.raw_table_id}`
        ORDER BY migration_id DESC, recorded_at DESC
        LIMIT 1
        """

        try:
            query_job = self.client.query(query)
            results = list(query_job.result())

            if results:
                row = results[0]
                migration_id = row.migration_id
                recorded_at = row.recorded_at
                # Handle both string and datetime types
                if isinstance(recorded_at, datetime):
                    recorded_at = recorded_at.isoformat() + "Z"
                elif recorded_at and not recorded_at.endswith("Z"):
                    recorded_at = recorded_at + "Z"
                logger.info(f"Last processed: migration_id={migration_id}, recorded_at={recorded_at}")
                return migration_id, recorded_at

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
        SELECT migration_id, recorded_at
        FROM `{self.parsed_table_id}`
        ORDER BY migration_id DESC, recorded_at DESC
        LIMIT 1
        """

        try:
            query_job = self.client.query(query)
            results = list(query_job.result())

            if results:
                row = results[0]
                migration_id = row.migration_id
                recorded_at = row.recorded_at
                if isinstance(recorded_at, datetime):
                    recorded_at = recorded_at.isoformat() + "Z"
                return migration_id, recorded_at

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
        """
        Run transformation query for incremental processing.

        Transforms from raw.events to transformed.events_parsed:
        - Converts STRING timestamps to TIMESTAMP
        - Flattens nested arrays (signatories.list[].element -> signatories[])
        - Parses JSON string fields to JSON type
        """
        last_migration_id, last_recorded_at = self.get_last_transformed_position()

        where_clause = ""
        if last_migration_id is not None and last_recorded_at is not None:
            where_clause = f"""
            WHERE (migration_id > {last_migration_id})
               OR (migration_id = {last_migration_id} AND recorded_at > '{last_recorded_at}')
            """

        transformation_query = f"""
        INSERT INTO `{self.parsed_table_id}` (
            event_id, update_id, contract_id, template_id, package_name,
            event_type, event_type_original, synchronizer_id, migration_id,
            choice, interface_id, consuming,
            effective_at, recorded_at, timestamp, created_at_ts,
            signatories, observers, acting_parties, witness_parties, child_event_ids,
            reassignment_counter, source_synchronizer, target_synchronizer,
            unassign_id, submitter,
            payload, contract_key, exercise_result, raw_event, trace_context,
            year, month, day
        )
        SELECT
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
            -- Parse timestamps
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', effective_at) as effective_at,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', recorded_at) as recorded_at,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', timestamp) as timestamp,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', created_at_ts) as created_at_ts,
            -- Flatten nested arrays (list[].element structure)
            ARRAY(SELECT e.element FROM UNNEST(signatories.list) AS e) as signatories,
            ARRAY(SELECT e.element FROM UNNEST(observers.list) AS e) as observers,
            ARRAY(SELECT e.element FROM UNNEST(acting_parties.list) AS e) as acting_parties,
            ARRAY(SELECT e.element FROM UNNEST(witness_parties.list) AS e) as witness_parties,
            ARRAY(SELECT e.element FROM UNNEST(child_event_ids.list) AS e) as child_event_ids,
            -- Other fields
            reassignment_counter,
            source_synchronizer,
            target_synchronizer,
            unassign_id,
            submitter,
            -- Parse JSON fields
            SAFE.PARSE_JSON(payload) as payload,
            SAFE.PARSE_JSON(contract_key) as contract_key,
            SAFE.PARSE_JSON(exercise_result) as exercise_result,
            SAFE.PARSE_JSON(raw_event) as raw_event,
            SAFE.PARSE_JSON(trace_context) as trace_context,
            -- Date parts
            year,
            month,
            day
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
        if raw_pos[0] == parsed_pos[0] and raw_pos[1] and parsed_pos[1]:
            if raw_pos[1] > parsed_pos[1]:
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
                'last_position': dict(zip(['migration_id', 'recorded_at'], self.get_last_processed_position()))
            },
            'parsed_table': {
                'table_id': self.parsed_table_id,
                'stats': self.get_table_stats(self.parsed_table_id),
                'last_position': dict(zip(['migration_id', 'recorded_at'], self.get_last_transformed_position()))
            },
            'needs_transformation': self.check_for_new_raw_data()
        }

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
