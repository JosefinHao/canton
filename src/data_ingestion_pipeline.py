"""
Data Ingestion Pipeline for Canton Blockchain Data

Orchestrates the flow of data from Scan API to BigQuery:
1. Fetch incremental updates from Scan API (/v2/updates)
2. Insert raw events into BigQuery raw.events table
3. Trigger transformation to parsed table
4. Track state for incremental processing
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

from .canton_scan_client import SpliceScanClient
from .bigquery_client import BigQueryClient

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the data ingestion pipeline."""
    # Scan API configuration
    scan_api_base_url: str = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"
    scan_api_timeout: int = 60
    scan_api_max_retries: int = 3

    # BigQuery configuration
    bq_project_id: str = "governence-483517"
    bq_raw_dataset: str = "raw"
    bq_transformed_dataset: str = "transformed"
    bq_raw_table: str = "events"
    bq_parsed_table: str = "events_parsed"

    # Pipeline configuration
    page_size: int = 500  # Number of updates per API call
    max_pages_per_run: int = 100  # Maximum pages to process per run
    batch_size: int = 100  # Number of events to insert per BigQuery batch
    auto_transform: bool = True  # Automatically run transformation after ingestion
    transform_batch_threshold: int = 1000  # Transform after this many new rows

    # Rate limiting
    api_delay_seconds: float = 0.1  # Delay between API calls


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
    """
    Pipeline for ingesting Canton blockchain data from Scan API to BigQuery.
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """
        Initialize the data ingestion pipeline.

        Args:
            config: Pipeline configuration (uses defaults if not provided)
        """
        self.config = config or PipelineConfig()

        # Initialize clients lazily
        self._scan_client: Optional[SpliceScanClient] = None
        self._bq_client: Optional[BigQueryClient] = None

        logger.info(f"Pipeline initialized with config: {self.config}")

    @property
    def scan_client(self) -> SpliceScanClient:
        """Lazily initialize Scan API client."""
        if self._scan_client is None:
            self._scan_client = SpliceScanClient(
                base_url=self.config.scan_api_base_url,
                timeout=self.config.scan_api_timeout,
                max_retries=self.config.scan_api_max_retries
            )
        return self._scan_client

    @property
    def bq_client(self) -> BigQueryClient:
        """Lazily initialize BigQuery client."""
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
        """
        Execute the data ingestion pipeline.

        Returns:
            PipelineStats with results of the run
        """
        stats = PipelineStats(started_at=datetime.utcnow().isoformat())

        try:
            # Step 1: Get starting position
            start_migration_id, start_record_time = self.bq_client.get_last_processed_position()
            stats.start_position = {
                'migration_id': start_migration_id,
                'record_time': start_record_time
            }

            logger.info(f"Starting ingestion from position: migration_id={start_migration_id}, record_time={start_record_time}")

            # Step 2: Fetch and insert updates
            current_migration_id = start_migration_id
            current_record_time = start_record_time
            total_events_buffer = []

            for page_num in range(self.config.max_pages_per_run):
                # Fetch updates from API
                updates_response = self._fetch_updates(current_migration_id, current_record_time)

                if not updates_response:
                    logger.info("No more updates available")
                    break

                updates = updates_response.get('updates', updates_response.get('transactions', []))
                if not updates:
                    logger.info("Empty updates response")
                    break

                stats.pages_fetched += 1
                stats.events_fetched += len(updates)

                # Process each update
                events_to_insert = self._extract_events_from_updates(updates)
                total_events_buffer.extend(events_to_insert)

                # Insert in batches
                if len(total_events_buffer) >= self.config.batch_size:
                    inserted = self.bq_client.insert_raw_events(total_events_buffer)
                    stats.events_inserted += inserted
                    total_events_buffer = []

                # Update cursor for next page
                if updates:
                    last_update = updates[-1]
                    current_migration_id = last_update.get('migration_id', current_migration_id)
                    current_record_time = last_update.get('record_time', current_record_time)

                # Check if we've caught up (fewer results than page size)
                if len(updates) < self.config.page_size:
                    logger.info("Reached end of available updates")
                    break

                # Rate limiting
                if self.config.api_delay_seconds > 0:
                    time.sleep(self.config.api_delay_seconds)

            # Insert any remaining events
            if total_events_buffer:
                inserted = self.bq_client.insert_raw_events(total_events_buffer)
                stats.events_inserted += inserted

            # Update end position
            stats.end_position = {
                'migration_id': current_migration_id,
                'record_time': current_record_time
            }

            # Step 3: Run transformation if enabled
            if self.config.auto_transform and stats.events_inserted > 0:
                if stats.events_inserted >= self.config.transform_batch_threshold or \
                   self.bq_client.check_for_new_raw_data():
                    logger.info("Running transformation...")
                    stats.rows_transformed = self.bq_client.run_transformation_query()

            stats.success = True
            logger.info(f"Pipeline run completed successfully: {stats.events_inserted} events inserted, {stats.rows_transformed} rows transformed")

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
        """
        Fetch updates from the Scan API.

        Args:
            after_migration_id: Start after this migration ID
            after_record_time: Start after this record time

        Returns:
            API response or None on error
        """
        try:
            response = self.scan_client.get_updates(
                after_migration_id=after_migration_id,
                after_record_time=after_record_time,
                page_size=self.config.page_size
            )
            return response

        except Exception as e:
            logger.error(f"Error fetching updates: {e}")
            return None

    def _extract_events_from_updates(self, updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract individual events from update responses.

        Each update may contain multiple events in events_by_id.
        We flatten these into individual event records for insertion.

        Args:
            updates: List of update objects from API

        Returns:
            List of flattened event records
        """
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
        """Determine event type from event details."""
        if 'create_arguments' in event_details:
            return 'created'
        elif 'choice' in event_details:
            return 'exercised'
        elif event_details.get('archived'):
            return 'archived'
        return 'unknown'

    def run_transformation_only(self) -> int:
        """
        Run only the transformation step without fetching new data.

        Returns:
            Number of rows transformed
        """
        logger.info("Running transformation only...")
        return self.bq_client.run_transformation_query()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current pipeline status.

        Returns:
            Dictionary with pipeline status information
        """
        pipeline_status = self.bq_client.get_pipeline_status()

        # Add API health check
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
        """Clean up resources."""
        if self._scan_client:
            self._scan_client.close()
        if self._bq_client:
            self._bq_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def run_pipeline(
    config: Optional[PipelineConfig] = None,
    transform_only: bool = False
) -> PipelineStats:
    """
    Convenience function to run the pipeline.

    Args:
        config: Pipeline configuration
        transform_only: If True, only run transformation step

    Returns:
        Pipeline statistics
    """
    with DataIngestionPipeline(config) as pipeline:
        if transform_only:
            stats = PipelineStats(started_at=datetime.utcnow().isoformat())
            stats.rows_transformed = pipeline.run_transformation_only()
            stats.completed_at = datetime.utcnow().isoformat()
            stats.success = True
            return stats
        return pipeline.run()


# CLI interface for manual execution
if __name__ == '__main__':
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Canton Blockchain Data Ingestion Pipeline')
    parser.add_argument('--transform-only', action='store_true',
                        help='Only run transformation, skip data fetching')
    parser.add_argument('--status', action='store_true',
                        help='Show pipeline status')
    parser.add_argument('--page-size', type=int, default=500,
                        help='Number of updates per API call (default: 500)')
    parser.add_argument('--max-pages', type=int, default=100,
                        help='Maximum pages to process (default: 100)')
    parser.add_argument('--no-transform', action='store_true',
                        help='Skip automatic transformation after ingestion')
    parser.add_argument('--scan-url', type=str,
                        default="https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/",
                        help='Scan API base URL')

    args = parser.parse_args()

    config = PipelineConfig(
        scan_api_base_url=args.scan_url,
        page_size=args.page_size,
        max_pages_per_run=args.max_pages,
        auto_transform=not args.no_transform
    )

    with DataIngestionPipeline(config) as pipeline:
        if args.status:
            status = pipeline.get_status()
            print(json.dumps(status, indent=2, default=str))
            sys.exit(0)

        if args.transform_only:
            rows = pipeline.run_transformation_only()
            print(f"Transformed {rows} rows")
            sys.exit(0)

        stats = pipeline.run()
        print(json.dumps(stats.to_dict(), indent=2))
        sys.exit(0 if stats.success else 1)
