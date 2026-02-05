"""
Canton Scan API Client (Cloud Function Version)

Minimal client for fetching updates from the Canton Scan API.
"""

import logging
from typing import Dict, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SpliceScanClient:
    """Client for interacting with Canton Scan API."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """Initialize the Scan API client."""
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({'Accept': 'application/json'})

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make a request to the API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            request_headers = None
            if json_data is not None:
                request_headers = {'Content-Type': 'application/json'}

            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=request_headers,
                timeout=self.timeout
            )
            response.raise_for_status()

            if response.status_code == 204 or not response.content:
                return {}

            result = response.json()
            if not isinstance(result, dict):
                return {}
            return result

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error: {e}")
            raise

    def get_updates(
        self,
        after_migration_id: Optional[int] = None,
        after_record_time: Optional[str] = None,
        page_size: int = 100,
        daml_value_encoding: str = "compact_json"
    ) -> Dict[str, Any]:
        """
        Get update history in ascending order.

        Args:
            after_migration_id: Start after this migration ID
            after_record_time: Start after this record time (ISO format)
            page_size: Maximum number of updates to return
            daml_value_encoding: Encoding format for DAML values

        Returns:
            Dictionary containing transactions/updates
        """
        json_data: Dict[str, Any] = {
            'page_size': page_size,
            'daml_value_encoding': daml_value_encoding
        }

        if after_migration_id is not None and after_record_time is not None:
            json_data['after'] = {
                'after_migration_id': after_migration_id,
                'after_record_time': after_record_time
            }

        response = self._make_request('POST', '/v2/updates', json_data=json_data)

        if 'transactions' in response and 'updates' not in response:
            response['updates'] = response['transactions']

        return response

    def get_events(
        self,
        after_migration_id: Optional[int] = None,
        after_record_time: Optional[str] = None,
        page_size: int = 100,
        daml_value_encoding: str = "compact_json"
    ) -> Dict[str, Any]:
        """
        Get event history in ascending order using /v0/events endpoint.

        Args:
            after_migration_id: Start after this migration ID
            after_record_time: Start after this record time (ISO format)
            page_size: Maximum number of events to return
            daml_value_encoding: Encoding format for DAML values

        Returns:
            Dictionary containing events
        """
        json_data: Dict[str, Any] = {
            'page_size': page_size,
            'daml_value_encoding': daml_value_encoding
        }

        if after_migration_id is not None and after_record_time is not None:
            json_data['after'] = {
                'after_migration_id': after_migration_id,
                'after_record_time': after_record_time
            }

        return self._make_request('POST', '/v0/events', json_data=json_data)

    def health_check(self) -> bool:
        """Check if the API is accessible."""
        try:
            self._make_request('GET', '/v0/dso')
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
