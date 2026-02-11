"""
Cloud Function for Canton Blockchain Data Ingestion

This function is triggered by Cloud Scheduler every 15 minutes to:
1. Fetch new updates from Canton Scan API
2. Insert raw events into BigQuery
3. Transform raw events to parsed format

Entry points:
- ingest_data: HTTP trigger for Cloud Scheduler
- transform_data: HTTP trigger for manual transformation
- get_status: HTTP trigger to check pipeline status
"""

import json
import logging
import os
import functions_framework
from flask import Request, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import pipeline components
# Note: In Cloud Functions, we need to handle imports carefully
# since the function may be in a different package structure
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    from src.data_ingestion_pipeline import DataIngestionPipeline, PipelineConfig, PipelineStats
except ImportError:
    # Fallback for when running as standalone Cloud Function
    from data_ingestion_pipeline import DataIngestionPipeline, PipelineConfig, PipelineStats


def get_config_from_env() -> PipelineConfig:
    """
    Load pipeline configuration from environment variables.

    Environment variables:
    - SCAN_API_BASE_URL: Scan API base URL
    - SCAN_API_TIMEOUT: API timeout in seconds
    - BQ_PROJECT_ID: BigQuery project ID
    - BQ_RAW_DATASET: Raw events dataset
    - BQ_TRANSFORMED_DATASET: Transformed events dataset
    - BQ_RAW_TABLE: Raw events table name
    - BQ_PARSED_TABLE: Parsed events table name
    - PAGE_SIZE: Updates per API call
    - MAX_PAGES_PER_RUN: Maximum pages per execution
    - AUTO_TRANSFORM: Whether to auto-transform after ingestion
    """
    return PipelineConfig(
        scan_api_base_url=os.environ.get(
            'SCAN_API_BASE_URL',
            'https://scan.sv-1.global.canton.network.sync.global/api/scan/'
        ),
        scan_api_timeout=int(os.environ.get('SCAN_API_TIMEOUT', '60')),
        scan_api_max_retries=int(os.environ.get('SCAN_API_MAX_RETRIES', '3')),
        bq_project_id=os.environ.get('BQ_PROJECT_ID', 'governence-483517'),
        bq_raw_dataset=os.environ.get('BQ_RAW_DATASET', 'raw'),
        bq_transformed_dataset=os.environ.get('BQ_TRANSFORMED_DATASET', 'transformed'),
        bq_raw_table=os.environ.get('BQ_RAW_TABLE', 'events'),
        bq_parsed_table=os.environ.get('BQ_PARSED_TABLE', 'events_parsed'),
        page_size=int(os.environ.get('PAGE_SIZE', '500')),
        max_pages_per_run=int(os.environ.get('MAX_PAGES_PER_RUN', '100')),
        batch_size=int(os.environ.get('BATCH_SIZE', '100')),
        auto_transform=os.environ.get('AUTO_TRANSFORM', 'true').lower() == 'true',
        transform_batch_threshold=int(os.environ.get('TRANSFORM_BATCH_THRESHOLD', '1000')),
        api_delay_seconds=float(os.environ.get('API_DELAY_SECONDS', '0.1'))
    )


@functions_framework.http
def ingest_data(request: Request):
    """
    Main entry point for data ingestion Cloud Function.

    Triggered by Cloud Scheduler every 15 minutes.

    Request body (optional JSON):
    {
        "transform_only": false,  // Only run transformation
        "max_pages": 100,         // Override max pages
        "page_size": 500          // Override page size
    }

    Returns:
        JSON response with pipeline statistics
    """
    logger.info("Data ingestion function triggered")

    try:
        # Parse request body if present
        request_json = request.get_json(silent=True) or {}
        transform_only = request_json.get('transform_only', False)

        # Get configuration
        config = get_config_from_env()

        # Override config from request if provided
        if 'max_pages' in request_json:
            config.max_pages_per_run = request_json['max_pages']
        if 'page_size' in request_json:
            config.page_size = request_json['page_size']
        if 'auto_transform' in request_json:
            config.auto_transform = request_json['auto_transform']

        # Run pipeline
        with DataIngestionPipeline(config) as pipeline:
            if transform_only:
                stats = PipelineStats()
                stats.rows_transformed = pipeline.run_transformation_only()
                stats.success = True
            else:
                stats = pipeline.run()

        # Return results
        response_data = {
            'status': 'success' if stats.success else 'error',
            'statistics': stats.to_dict()
        }

        logger.info(f"Pipeline completed: {stats.events_inserted} events inserted, "
                    f"{stats.rows_transformed} rows transformed")

        return jsonify(response_data), 200 if stats.success else 500

    except Exception as e:
        logger.error(f"Pipeline failed with error: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@functions_framework.http
def transform_data(request: Request):
    """
    Entry point for transformation-only Cloud Function.

    Useful for catching up transformation after large batch ingestions.

    Returns:
        JSON response with transformation statistics
    """
    logger.info("Transform data function triggered")

    try:
        config = get_config_from_env()

        with DataIngestionPipeline(config) as pipeline:
            rows_transformed = pipeline.run_transformation_only()

        return jsonify({
            'status': 'success',
            'rows_transformed': rows_transformed
        }), 200

    except Exception as e:
        logger.error(f"Transformation failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@functions_framework.http
def get_status(request: Request):
    """
    Entry point for status check Cloud Function.

    Returns pipeline status including:
    - Raw table statistics
    - Parsed table statistics
    - Last processed positions
    - API health status

    Returns:
        JSON response with pipeline status
    """
    logger.info("Status check function triggered")

    try:
        config = get_config_from_env()

        with DataIngestionPipeline(config) as pipeline:
            status = pipeline.get_status()

        return jsonify({
            'status': 'success',
            'pipeline_status': status
        }), 200

    except Exception as e:
        logger.error(f"Status check failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# For local testing
if __name__ == '__main__':
    from flask import Flask, request as flask_request

    app = Flask(__name__)

    @app.route('/ingest', methods=['POST', 'GET'])
    def test_ingest():
        return ingest_data(flask_request)

    @app.route('/transform', methods=['POST', 'GET'])
    def test_transform():
        return transform_data(flask_request)

    @app.route('/status', methods=['GET'])
    def test_status():
        return get_status(flask_request)

    print("Starting local test server on http://localhost:8080")
    app.run(host='0.0.0.0', port=8080, debug=True)
