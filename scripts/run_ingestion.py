#!/usr/bin/env python3
"""
Standalone Data Ingestion Script for Canton Blockchain Data

Run this script manually or via cron to ingest data from Scan API to BigQuery.

Usage:
    # Run ingestion
    python run_ingestion.py

    # Run transformation only
    python run_ingestion.py --transform-only

    # Check status
    python run_ingestion.py --status

    # Custom settings
    python run_ingestion.py --max-pages 50 --page-size 1000

Cron example (every 15 minutes):
    */15 * * * * cd /path/to/canton && python scripts/run_ingestion.py >> /var/log/canton-ingestion.log 2>&1

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS - Path to service account JSON file
    BQ_PROJECT_ID - BigQuery project ID (default: governence-483517)
    SCAN_API_BASE_URL - Scan API URL
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_ingestion_pipeline import DataIngestionPipeline, PipelineConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def get_config(args) -> PipelineConfig:
    """Build configuration from environment and command line args."""
    return PipelineConfig(
        scan_api_base_url=os.environ.get(
            'SCAN_API_BASE_URL',
            'https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
        ),
        scan_api_timeout=int(os.environ.get('SCAN_API_TIMEOUT', '60')),
        scan_api_max_retries=int(os.environ.get('SCAN_API_MAX_RETRIES', '3')),
        bq_project_id=os.environ.get('BQ_PROJECT_ID', 'governence-483517'),
        bq_raw_dataset=os.environ.get('BQ_RAW_DATASET', 'raw'),
        bq_transformed_dataset=os.environ.get('BQ_TRANSFORMED_DATASET', 'transformed'),
        bq_raw_table=os.environ.get('BQ_RAW_TABLE', 'events'),
        bq_parsed_table=os.environ.get('BQ_PARSED_TABLE', 'events_parsed'),
        page_size=args.page_size,
        max_pages_per_run=args.max_pages,
        batch_size=args.batch_size,
        auto_transform=not args.no_transform,
        transform_batch_threshold=args.transform_threshold,
        api_delay_seconds=args.api_delay
    )


def run_ingestion(args):
    """Run the data ingestion pipeline."""
    logger.info("=" * 50)
    logger.info("Canton Data Ingestion Pipeline")
    logger.info("=" * 50)
    logger.info(f"Started at: {datetime.utcnow().isoformat()}")

    config = get_config(args)

    logger.info(f"Project: {config.bq_project_id}")
    logger.info(f"Page size: {config.page_size}")
    logger.info(f"Max pages: {config.max_pages_per_run}")
    logger.info(f"Auto transform: {config.auto_transform}")

    with DataIngestionPipeline(config) as pipeline:
        stats = pipeline.run()

    logger.info("")
    logger.info("=" * 50)
    logger.info("Results")
    logger.info("=" * 50)
    logger.info(f"Success: {stats.success}")
    logger.info(f"Pages fetched: {stats.pages_fetched}")
    logger.info(f"Events fetched: {stats.events_fetched}")
    logger.info(f"Events inserted: {stats.events_inserted}")
    logger.info(f"Rows transformed: {stats.rows_transformed}")

    if stats.errors:
        logger.error(f"Errors: {stats.errors}")

    logger.info(f"Completed at: {stats.completed_at}")

    return 0 if stats.success else 1


def run_transform_only(args):
    """Run transformation only."""
    logger.info("Running transformation only...")

    config = get_config(args)

    with DataIngestionPipeline(config) as pipeline:
        rows = pipeline.run_transformation_only()

    logger.info(f"Transformed {rows} rows")
    return 0


def show_status(args):
    """Show pipeline status."""
    config = get_config(args)

    with DataIngestionPipeline(config) as pipeline:
        status = pipeline.get_status()

    print(json.dumps(status, indent=2, default=str))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Canton Blockchain Data Ingestion Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--transform-only', action='store_true',
        help='Only run transformation, skip data fetching'
    )
    mode_group.add_argument(
        '--status', action='store_true',
        help='Show pipeline status'
    )

    # Pipeline settings
    parser.add_argument(
        '--page-size', type=int, default=500,
        help='Number of updates per API call (default: 500)'
    )
    parser.add_argument(
        '--max-pages', type=int, default=100,
        help='Maximum pages to process per run (default: 100)'
    )
    parser.add_argument(
        '--batch-size', type=int, default=100,
        help='Number of events per BigQuery insert batch (default: 100)'
    )
    parser.add_argument(
        '--no-transform', action='store_true',
        help='Skip automatic transformation after ingestion'
    )
    parser.add_argument(
        '--transform-threshold', type=int, default=1000,
        help='Transform after this many new rows (default: 1000)'
    )
    parser.add_argument(
        '--api-delay', type=float, default=0.1,
        help='Delay between API calls in seconds (default: 0.1)'
    )

    args = parser.parse_args()

    try:
        if args.status:
            return show_status(args)
        elif args.transform_only:
            return run_transform_only(args)
        else:
            return run_ingestion(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
