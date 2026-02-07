"""
Data Ingestion Pipeline for Canton Blockchain Data (Cloud Function Version)

Orchestrates data flow from Scan API to BigQuery.
Matches the actual schema of governence-483517.raw.events
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from canton_scan_client import SpliceScanClient
from bigquery_client import BigQueryClient

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the data ingestion pipeline."""
    scan_api_base_url: str = "https://scan.sv-1.global.canton.network.cumberland.io/api/scan/"
    scan_api_timeout: int = 60
    scan_api_max_retries: int = 3
    bq_project_id: str = "governence-483517"
    bq_raw_dataset: str = "raw"
    bq_transformed_dataset: str = "transformed"
    bq_raw_table: str = "events"
    bq_parsed_table: str = "events_parsed"
    page_size: int = 500
    max_pages_per_run: int = 100
    batch_size: int = 100
    auto_transform: bool = True
    transform_batch_threshold: int = 1000
    api_delay_seconds: float = 0.1


@dataclass
class PipelineStats:
    """Statistics from a pipeline run."""
    started_at: str = ""
    completed_at: str = ""
    pages_fetched: int = 0
    events_fetched: int = 0
    events_inserted: int = 0
    rows_transformed: int = 0
    errors: List[str] = field(default_factory=list)
    start_position: Dict[str, Any] = field(default_factory=dict)
    end_position: Dict[str, Any] = field(default_factory=dict)
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DataIngestionPipeline:
    """Pipeline for ingesting Canton blockchain data."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self._scan_client: Optional[SpliceScanClient] = None
        self._bq_client: Optional[BigQueryClient] = None
        logger.info("Pipeline initialized")

    @property
    def scan_client(self) -> SpliceScanClient:
        if self._scan_client is None:
            self._scan_client = SpliceScanClient(
                base_url=self.config.scan_api_base_url,
                timeout=self.config.scan_api_timeout,
                max_retries=self.config.scan_api_max_retries
            )
        return self._scan_client

    @property
    def bq_client(self) -> BigQueryClient:
        if self._bq_client is None:
            self._bq_client = BigQueryClient(
                project_id=self.config.bq_project_id,
                raw_dataset=self.config.bq_raw_dataset,
                transformed_dataset=self.config.bq_transformed_dataset,
                raw_table=self.config.bq_raw_table,
                parsed_table=self.config.bq_parsed_table
            )
        return self._bq_client

    def run(self) -> PipelineStats:
        """Execute the data ingestion pipeline."""
        stats = PipelineStats(started_at=datetime.utcnow().isoformat())

        try:
            # Get last processed position (uses recorded_at)
            start_migration_id, start_recorded_at = self.bq_client.get_last_processed_position()
            stats.start_position = {
                'migration_id': start_migration_id,
                'recorded_at': start_recorded_at
            }

            logger.info(f"Starting from: migration_id={start_migration_id}, recorded_at={start_recorded_at}")

            current_migration_id = start_migration_id
            current_recorded_at = start_recorded_at
            total_events_buffer = []

            for page_num in range(self.config.max_pages_per_run):
                updates_response = self._fetch_updates(current_migration_id, current_recorded_at)

                if not updates_response:
                    break

                updates = updates_response.get('updates', updates_response.get('transactions', []))
                if not updates:
                    break

                stats.pages_fetched += 1
                stats.events_fetched += len(updates)

                events_to_insert = self._extract_events_from_updates(updates)
                total_events_buffer.extend(events_to_insert)

                if len(total_events_buffer) >= self.config.batch_size:
                    inserted = self.bq_client.insert_raw_events(total_events_buffer)
                    stats.events_inserted += inserted
                    total_events_buffer = []

                if updates:
                    last_update = updates[-1]
                    current_migration_id = last_update.get('migration_id', current_migration_id)
                    # API uses record_time, we map to recorded_at
                    current_recorded_at = last_update.get('record_time', current_recorded_at)

                if len(updates) < self.config.page_size:
                    break

                if self.config.api_delay_seconds > 0:
                    time.sleep(self.config.api_delay_seconds)

            if total_events_buffer:
                inserted = self.bq_client.insert_raw_events(total_events_buffer)
                stats.events_inserted += inserted

            stats.end_position = {
                'migration_id': current_migration_id,
                'recorded_at': current_recorded_at
            }

            # Update state table for fast future lookups
            if stats.events_inserted > 0 and current_migration_id and current_recorded_at:
                self.bq_client.update_raw_state(current_migration_id, current_recorded_at)

            if self.config.auto_transform and stats.events_inserted > 0:
                if stats.events_inserted >= self.config.transform_batch_threshold or \
                   self.bq_client.check_for_new_raw_data():
                    logger.info("Running transformation...")
                    stats.rows_transformed = self.bq_client.run_transformation_query()

            stats.success = True
            logger.info(f"Completed: {stats.events_inserted} inserted, {stats.rows_transformed} transformed")

        except Exception as e:
            error_msg = f"Pipeline error: {str(e)}"
            logger.error(error_msg)
            stats.errors.append(error_msg)
            stats.success = False

        finally:
            stats.completed_at = datetime.utcnow().isoformat()

        return stats

    def _fetch_updates(
        self,
        after_migration_id: Optional[int],
        after_recorded_at: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        try:
            return self.scan_client.get_updates(
                after_migration_id=after_migration_id,
                after_record_time=after_recorded_at,  # API uses record_time parameter
                page_size=self.config.page_size
            )
        except Exception as e:
            logger.error(f"Error fetching updates: {e}")
            return None

    def _to_nested_array(self, items: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """
        Convert a list to the nested array format used by BigQuery schema.
        ["a", "b"] -> {"list": [{"element": "a"}, {"element": "b"}]}
        """
        if not items:
            return {"list": []}
        return {"list": [{"element": item} for item in items]}

    def _extract_events_from_updates(self, updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract events from API updates, matching raw.events schema.

        API returns transactions directly with structure:
        {
            "update_id": "...",
            "migration_id": 1,
            "record_time": "...",
            "synchronizer_id": "...",
            "effective_at": "...",
            "events_by_id": {...}
        }
        """
        events = []

        for txn in updates:
            migration_id = txn.get('migration_id')
            record_time = txn.get('record_time')  # Maps to recorded_at in BQ
            synchronizer_id = txn.get('synchronizer_id')  # Direct field in API
            update_id = txn.get('update_id')
            effective_at = txn.get('effective_at')
            events_by_id = txn.get('events_by_id', {})

            # Parse timestamp for date parts
            dt = None
            if record_time:
                try:
                    dt = datetime.fromisoformat(record_time.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass

            # Process each event in the transaction
            for event_id, event_details in events_by_id.items():
                event_type = self._determine_event_type(event_details)
                event = {
                    'event_id': event_id,
                    'update_id': update_id,
                    'event_type': event_type,
                    'event_type_original': event_details.get('event_type'),
                    'synchronizer_id': synchronizer_id,
                    'effective_at': effective_at,
                    'recorded_at': record_time,
                    'timestamp': record_time,
                    'created_at_ts': effective_at,
                    'contract_id': event_details.get('contract_id'),
                    'template_id': event_details.get('template_id'),
                    'package_name': event_details.get('package_name'),
                    'migration_id': migration_id,
                    # Nested array format for party lists
                    'signatories': self._to_nested_array(event_details.get('signatories', [])),
                    'observers': self._to_nested_array(event_details.get('observers', [])),
                    'acting_parties': self._to_nested_array(event_details.get('acting_parties', [])),
                    'witness_parties': self._to_nested_array(event_details.get('witness_parties', [])),
                    'child_event_ids': self._to_nested_array(event_details.get('child_event_ids', [])),
                    'choice': event_details.get('choice'),
                    'interface_id': event_details.get('interface_id'),
                    'consuming': event_details.get('consuming'),
                    'reassignment_counter': event_details.get('reassignment_counter'),
                    'source_synchronizer': event_details.get('source_synchronizer'),
                    'target_synchronizer': event_details.get('target_synchronizer'),
                    'unassign_id': event_details.get('unassign_id'),
                    'submitter': event_details.get('submitter'),
                    # JSON string fields
                    'payload': json.dumps(
                        event_details.get('create_arguments') or
                        event_details.get('choice_argument')
                    ),
                    'contract_key': json.dumps(event_details.get('contract_key')),
                    'exercise_result': json.dumps(event_details.get('exercise_result')),
                    'raw_event': json.dumps(event_details),
                    'trace_context': json.dumps(txn.get('trace_context')),
                    # Date parts
                    'year': dt.year if dt else None,
                    'month': dt.month if dt else None,
                    'day': dt.day if dt else None,
                }
                events.append(event)

        return events

    def _determine_event_type(self, event_details: Dict[str, Any]) -> str:
        """Determine event type from event details."""
        if 'create_arguments' in event_details:
            return 'created'
        elif 'choice' in event_details:
            return 'exercised'
        elif event_details.get('archived'):
            return 'archived'
        return 'unknown'

    def run_transformation_only(self) -> int:
        """Run only the transformation step."""
        logger.info("Running transformation only...")
        return self.bq_client.run_transformation_query()

    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status."""
        pipeline_status = self.bq_client.get_pipeline_status()

        try:
            api_healthy = self.scan_client.health_check()
        except Exception:
            api_healthy = False

        pipeline_status['scan_api'] = {
            'base_url': self.config.scan_api_base_url,
            'healthy': api_healthy
        }

        return pipeline_status

    def close(self):
        if self._scan_client:
            self._scan_client.close()
        if self._bq_client:
            self._bq_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
