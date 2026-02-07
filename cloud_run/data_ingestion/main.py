"""
Cloud Run Service for Canton Blockchain Data Ingestion

Flask application that provides HTTP endpoints for:
- Data ingestion from Scan API to BigQuery
- Transformation of raw data to parsed format
- Pipeline status monitoring

Triggered by Cloud Scheduler every 15 minutes.
"""

import json
import logging
import os
from flask import Flask, request, jsonify

from data_ingestion_pipeline import DataIngestionPipeline, PipelineConfig, PipelineStats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)


def get_config_from_env() -> PipelineConfig:
    """Load pipeline configuration from environment variables."""
    return PipelineConfig(
        scan_api_base_url=os.environ.get(
            'SCAN_API_BASE_URL',
            'https://scan.sv-1.global.canton.network.cumberland.io/api/scan/'
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


@app.route('/', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'service': 'canton-data-ingestion'}), 200


@app.route('/ingest', methods=['POST', 'GET'])
def ingest_data():
    """
    Main data ingestion endpoint.

    Triggered by Cloud Scheduler every 15 minutes.

    Request body (optional JSON):
    {
        "transform_only": false,
        "max_pages": 100,
        "page_size": 500
    }
    """
    logger.info("Data ingestion triggered")

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

        response_data = {
            'status': 'success' if stats.success else 'error',
            'statistics': stats.to_dict()
        }

        logger.info(f"Pipeline completed: {stats.events_inserted} events inserted, "
                    f"{stats.rows_transformed} rows transformed")

        return jsonify(response_data), 200 if stats.success else 500

    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/transform', methods=['POST', 'GET'])
def transform_data():
    """Run transformation only (no data fetching)."""
    logger.info("Transform triggered")

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


@app.route('/status', methods=['GET'])
def get_status():
    """Get pipeline status."""
    logger.info("Status check triggered")

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


if __name__ == '__main__':
    # Run locally for testing
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
