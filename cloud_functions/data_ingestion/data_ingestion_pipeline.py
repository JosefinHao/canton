"""
Data Ingestion Pipeline (Cloud Function Version)

Orchestrates data flow from Scan API to BigQuery.
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
    scan_api_base_url: str = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"
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
        logger.info(f"Pipeline initialized")

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
            start_migration_id, start_record_time = self.bq_client.get_last_processed_position()
            stats.start_position = {
                'migration_id': start_migration_id,
                'record_time': start_record_time
            }

            logger.info(f"Starting from: migration_id={start_migration_id}, record_time={start_record_time}")

            current_migration_id = start_migration_id
            current_record_time = start_record_time
            total_events_buffer = []

            for page_num in range(self.config.max_pages_per_run):
                updates_response = self._fetch_updates(current_migration_id, current_record_time)

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
                    current_record_time = last_update.get('record_time', current_record_time)

                if len(updates) < self.config.page_size:
                    break

                if self.config.api_delay_seconds > 0:
                    time.sleep(self.config.api_delay_seconds)

            if total_events_buffer:
                inserted = self.bq_client.insert_raw_events(total_events_buffer)
                stats.events_inserted += inserted

            stats.end_position = {
                'migration_id': current_migration_id,
                'record_time': current_record_time
            }

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
        after_record_time: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        try:
            return self.scan_client.get_updates(
                after_migration_id=after_migration_id,
                after_record_time=after_record_time,
                page_size=self.config.page_size
            )
        except Exception as e:
            logger.error(f"Error fetching updates: {e}")
            return None

    def _extract_events_from_updates(self, updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        events = []

        for update in updates:
            update_data = update.get('update', {})
            update_type = update_data.get('type', '')
            migration_id = update.get('migration_id')
            record_time = update.get('record_time')
            domain_id = update.get('domain_id')

            if update_type == 'transaction':
                transaction = update_data.get('transaction', {})
                events_by_id = update_data.get('events_by_id', {})

                for event_id, event_details in events_by_id.items():
                    event = {
                        'event_id': event_id,
                        'update_id': transaction.get('update_id'),
                        'migration_id': migration_id,
                        'record_time': record_time,
                        'domain_id': domain_id,
                        'workflow_id': transaction.get('workflow_id'),
                        'command_id': transaction.get('command_id'),
                        'effective_at': transaction.get('effective_at'),
                        'offset': str(transaction.get('offset', '')),
                        'event_type': self._determine_event_type(event_details),
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
                        'payload': json.dumps(
                            event_details.get('create_arguments') or
                            event_details.get('choice_argument')
                        ),
                        'contract_key': json.dumps(event_details.get('contract_key')),
                        'exercise_result': json.dumps(event_details.get('exercise_result')),
                        'interface_id': event_details.get('interface_id'),
                        'created_at_ts': transaction.get('effective_at'),
                        'timestamp': record_time,
                        'raw_event': json.dumps(event_details),
                        'trace_context': json.dumps(transaction.get('trace_context'))
                    }
                    events.append(event)

            elif update_type == 'reassignment':
                reassignment = update_data.get('reassignment', {})
                event = {
                    'event_id': f"reassign_{record_time}_{migration_id}",
                    'update_id': reassignment.get('update_id'),
                    'migration_id': migration_id,
                    'record_time': record_time,
                    'domain_id': domain_id,
                    'event_type': 'reassignment',
                    'offset': str(reassignment.get('offset', '')),
                    'timestamp': record_time,
                    'raw_event': json.dumps(update_data)
                }
                events.append(event)

        return events

    def _determine_event_type(self, event_details: Dict[str, Any]) -> str:
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
