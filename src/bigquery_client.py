"""
BigQuery Client Module for Canton Blockchain Data Pipeline

Provides functionality for:
- Connecting to BigQuery
- Querying data (get last processed timestamp)
- Inserting/streaming data
- Running transformation queries
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
        """
        Initialize BigQuery client.

        Args:
            project_id: GCP project ID
            raw_dataset: Dataset containing raw events
            transformed_dataset: Dataset containing transformed events
            raw_table: Table name for raw events
            parsed_table: Table name for parsed events
        """
        self.project_id = project_id
        self.raw_dataset = raw_dataset
        self.transformed_dataset = transformed_dataset
        self.raw_table = raw_table
        self.parsed_table = parsed_table

        # Full table references
        self.raw_table_id = f"{project_id}.{raw_dataset}.{raw_table}"
        self.parsed_table_id = f"{project_id}.{transformed_dataset}.{parsed_table}"

        # Initialize BigQuery client
        self.client = bigquery.Client(project=project_id)

        logger.info(f"BigQuery client initialized for project: {project_id}")

    def get_last_processed_position(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Get the last processed position from the raw events table.

        Returns:
            Tuple of (migration_id, record_time) for the last processed event,
            or (None, None) if table is empty.
        """
        query = f"""
        SELECT
            migration_id,
            record_time
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

                # Ensure record_time is in ISO format string
                if isinstance(record_time, datetime):
                    record_time = record_time.isoformat()

                logger.info(f"Last processed position: migration_id={migration_id}, record_time={record_time}")
                return migration_id, record_time

            logger.info("No existing data found, starting from beginning")
            return None, None

        except NotFound:
            logger.warning(f"Table {self.raw_table_id} not found")
            return None, None
        except Exception as e:
            logger.error(f"Error getting last processed position: {e}")
            raise

    def get_last_transformed_position(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Get the last transformed position from the parsed events table.

        Returns:
            Tuple of (migration_id, record_time) for the last transformed event,
            or (None, None) if table is empty.
        """
        query = f"""
        SELECT
            migration_id,
            record_time
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

                logger.info(f"Last transformed position: migration_id={migration_id}, record_time={record_time}")
                return migration_id, record_time

            logger.info("No transformed data found")
            return None, None

        except NotFound:
            logger.warning(f"Table {self.parsed_table_id} not found")
            return None, None
        except Exception as e:
            logger.error(f"Error getting last transformed position: {e}")
            raise

    def insert_raw_events(self, events: List[Dict[str, Any]]) -> int:
        """
        Insert raw events into BigQuery using streaming insert.

        Args:
            events: List of event dictionaries from Scan API

        Returns:
            Number of events inserted successfully
        """
        if not events:
            logger.info("No events to insert")
            return 0

        # Transform events to match BigQuery schema
        rows_to_insert = []
        for event in events:
            row = self._transform_event_for_insert(event)
            if row:
                rows_to_insert.append(row)

        if not rows_to_insert:
            logger.warning("No valid rows to insert after transformation")
            return 0

        # Use streaming insert for real-time data
        errors = self.client.insert_rows_json(
            self.raw_table_id,
            rows_to_insert,
            retry=retry.Retry(deadline=60)
        )

        if errors:
            logger.error(f"Errors inserting rows: {errors}")
            # Count successful inserts
            successful = len(rows_to_insert) - len(errors)
            return successful

        logger.info(f"Successfully inserted {len(rows_to_insert)} events")
        return len(rows_to_insert)

    def _transform_event_for_insert(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Transform a raw API event to match BigQuery raw table schema.

        Args:
            event: Event dictionary from Scan API

        Returns:
            Transformed row dictionary or None if invalid
        """
        try:
            # Extract update data
            update_data = event.get('update', {})
            update_type = update_data.get('type', '')

            # Handle different update types
            if update_type == 'transaction':
                return self._transform_transaction_event(event, update_data)
            elif update_type == 'reassignment':
                return self._transform_reassignment_event(event, update_data)
            else:
                # For other types, store minimal info
                return self._transform_generic_event(event, update_data)

        except Exception as e:
            logger.error(f"Error transforming event: {e}")
            return None

    def _transform_transaction_event(
        self,
        event: Dict[str, Any],
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Transform a transaction event for BigQuery insertion."""
        transaction = update_data.get('transaction', {})
        events_by_id = update_data.get('events_by_id', {})

        # Create a row for each event in the transaction
        rows = []
        for event_id, event_details in events_by_id.items():
            row = {
                'event_id': event_id,
                'update_id': transaction.get('update_id'),
                'migration_id': event.get('migration_id'),
                'record_time': event.get('record_time'),
                'domain_id': event.get('domain_id'),
                'workflow_id': transaction.get('workflow_id'),
                'command_id': transaction.get('command_id'),
                'effective_at': transaction.get('effective_at'),
                'offset': str(transaction.get('offset', '')),
                'event_type': self._get_event_type(event_details),
                'template_id': event_details.get('template_id'),
                'contract_id': event_details.get('contract_id'),
                'package_name': event_details.get('package_name'),
                'choice': event_details.get('choice'),
                'consuming': event_details.get('consuming'),
                'signatories': json.dumps(event_details.get('signatories', [])),
                'observers': json.dumps(event_details.get('observers', [])),
                'acting_parties': json.dumps(event_details.get('acting_parties', [])),
                'witness_parties': json.dumps(event_details.get('witness_parties', [])),
                'child_event_ids': json.dumps(event_details.get('child_event_ids', [])),
                'payload': json.dumps(event_details.get('create_arguments', event_details.get('choice_argument'))),
                'contract_key': json.dumps(event_details.get('contract_key')),
                'exercise_result': json.dumps(event_details.get('exercise_result')),
                'interface_id': event_details.get('interface_id'),
                'created_at_ts': transaction.get('effective_at'),
                'timestamp': event.get('record_time'),
                'raw_event': json.dumps(event_details),
                'trace_context': json.dumps(transaction.get('trace_context'))
            }
            rows.append(row)

        # Return first row or single combined row for simplicity
        # In production, you might want to batch these differently
        return rows[0] if rows else None

    def _transform_reassignment_event(
        self,
        event: Dict[str, Any],
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Transform a reassignment event for BigQuery insertion."""
        reassignment = update_data.get('reassignment', {})

        return {
            'event_id': reassignment.get('update_id', f"reassign_{event.get('record_time')}"),
            'update_id': reassignment.get('update_id'),
            'migration_id': event.get('migration_id'),
            'record_time': event.get('record_time'),
            'domain_id': event.get('domain_id'),
            'event_type': 'reassignment',
            'offset': str(reassignment.get('offset', '')),
            'timestamp': event.get('record_time'),
            'raw_event': json.dumps(update_data)
        }

    def _transform_generic_event(
        self,
        event: Dict[str, Any],
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Transform a generic event for BigQuery insertion."""
        return {
            'event_id': f"generic_{event.get('record_time')}_{event.get('migration_id')}",
            'migration_id': event.get('migration_id'),
            'record_time': event.get('record_time'),
            'domain_id': event.get('domain_id'),
            'event_type': update_data.get('type', 'unknown'),
            'timestamp': event.get('record_time'),
            'raw_event': json.dumps(update_data)
        }

    def _get_event_type(self, event_details: Dict[str, Any]) -> str:
        """Determine the event type from event details."""
        if 'create_arguments' in event_details:
            return 'created'
        elif 'choice' in event_details:
            return 'exercised'
        elif event_details.get('archived'):
            return 'archived'
        return 'unknown'

    def run_transformation_query(self) -> int:
        """
        Run the transformation query to update events_parsed from raw events.
        Only transforms new records that don't exist in parsed table.

        Returns:
            Number of rows transformed
        """
        # Get last transformed position to determine what needs processing
        last_migration_id, last_record_time = self.get_last_transformed_position()

        # Build WHERE clause for incremental processing
        where_clause = ""
        if last_migration_id is not None and last_record_time is not None:
            where_clause = f"""
            WHERE (migration_id > {last_migration_id})
               OR (migration_id = {last_migration_id} AND record_time > '{last_record_time}')
            """

        transformation_query = f"""
        INSERT INTO `{self.parsed_table_id}` (
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
            event_id,
            update_id,
            CAST(migration_id AS INT64) as migration_id,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', record_time) as record_time,
            domain_id,
            workflow_id,
            command_id,
            SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', effective_at) as effective_at,
            SAFE_CAST(offset AS INT64) as offset,
            event_type,
            template_id,
            contract_id,
            package_name,
            choice,
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
            result = query_job.result()

            rows_affected = query_job.num_dml_affected_rows or 0
            logger.info(f"Transformation complete: {rows_affected} rows transformed")
            return rows_affected

        except Exception as e:
            logger.error(f"Error running transformation query: {e}")
            raise

    def check_for_new_raw_data(self) -> bool:
        """
        Check if there's new raw data that needs to be transformed.

        Returns:
            True if there's new data to transform, False otherwise
        """
        raw_migration_id, raw_record_time = self.get_last_processed_position()
        parsed_migration_id, parsed_record_time = self.get_last_transformed_position()

        if raw_migration_id is None:
            return False

        if parsed_migration_id is None:
            return True

        # Compare positions
        if raw_migration_id > parsed_migration_id:
            return True
        if raw_migration_id == parsed_migration_id and raw_record_time > parsed_record_time:
            return True

        return False

    def get_table_stats(self, table_id: str) -> Dict[str, Any]:
        """
        Get statistics for a BigQuery table.

        Args:
            table_id: Full table reference

        Returns:
            Dictionary with table statistics
        """
        try:
            table = self.client.get_table(table_id)
            return {
                'num_rows': table.num_rows,
                'num_bytes': table.num_bytes,
                'created': table.created.isoformat() if table.created else None,
                'modified': table.modified.isoformat() if table.modified else None,
                'partitioning_type': table.time_partitioning.type_ if table.time_partitioning else None,
                'clustering_fields': table.clustering_fields
            }
        except NotFound:
            return {'error': f'Table {table_id} not found'}
        except Exception as e:
            return {'error': str(e)}

    def get_pipeline_status(self) -> Dict[str, Any]:
        """
        Get overall pipeline status including both tables.

        Returns:
            Dictionary with pipeline status
        """
        raw_stats = self.get_table_stats(self.raw_table_id)
        parsed_stats = self.get_table_stats(self.parsed_table_id)

        raw_pos = self.get_last_processed_position()
        parsed_pos = self.get_last_transformed_position()

        return {
            'raw_table': {
                'table_id': self.raw_table_id,
                'stats': raw_stats,
                'last_position': {
                    'migration_id': raw_pos[0],
                    'record_time': raw_pos[1]
                }
            },
            'parsed_table': {
                'table_id': self.parsed_table_id,
                'stats': parsed_stats,
                'last_position': {
                    'migration_id': parsed_pos[0],
                    'record_time': parsed_pos[1]
                }
            },
            'needs_transformation': self.check_for_new_raw_data()
        }

    def close(self):
        """Close the BigQuery client."""
        self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
