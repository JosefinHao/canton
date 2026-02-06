"""
Canton Scan API Client (Cloud Function Version)

Minimal client for fetching updates from the Canton Scan API.
Supports multiple SV node URLs with automatic failover.
"""

import logging
from typing import Dict, Optional, Any, List
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# MainNet SV Node URLs - try these in order if primary fails
MAINNET_SV_URLS = [
    "https://scan.sv-1.global.canton.network.sync.global/api/scan/",
    "https://scan.sv-1.global.canton.network.digitalasset.com/api/scan/",
    "https://scan.sv-2.global.canton.network.digitalasset.com/api/scan/",
    "https://scan.sv-1.global.canton.network.cumberland.io/api/scan/",
    "https://scan.sv-2.global.canton.network.cumberland.io/api/scan/",
    "https://scan.sv-1.global.canton.network.tradeweb.com/api/scan/",
    "https://scan.sv-1.global.canton.network.mpch.io/api/scan/",
    "https://scan.sv-1.global.canton.network.fivenorth.io/api/scan/",
    "https://scan.sv-1.global.canton.network.proofgroup.xyz/api/scan/",
    "https://scan.sv-1.global.canton.network.c7.digital/api/scan/",
    "https://scan.sv-1.global.canton.network.lcv.mpch.io/api/scan/",
    "https://scan.sv-1.global.canton.network.orb1lp.mpch.io/api/scan/",
    "https://scan.sv.global.canton.network.sv-nodeops.com/api/scan/",
]


class SpliceScanClient:
    """Client for interacting with Canton Scan API with failover support."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3,
        use_failover: bool = True,
        failover_timeout: int = 10  # Shorter timeout for failover attempts
    ):
        """Initialize the Scan API client."""
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.failover_timeout = failover_timeout
        self.use_failover = use_failover
        self._working_url: Optional[str] = None

        self.session = requests.Session()
        # Reduced retries for faster failover
        retry_strategy = Retry(
            total=1,  # Only 1 retry per URL for faster failover
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({'Accept': 'application/json'})

    def _make_single_request(
        self,
        base_url: str,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Make a single request to a specific base URL."""
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        use_timeout = timeout or self.timeout

        request_headers = None
        if json_data is not None:
            request_headers = {'Content-Type': 'application/json'}

        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=json_data,
            headers=request_headers,
            timeout=use_timeout
        )
        response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return {}

        result = response.json()
        if not isinstance(result, dict):
            return {}
        return result

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make a request to the API with failover support."""
        # If we have a working URL from previous requests, try it first
        if self._working_url:
            try:
                logger.info(f"Trying cached working URL: {self._working_url}")
                result = self._make_single_request(
                    self._working_url, method, endpoint, params, json_data,
                    timeout=self.timeout
                )
                return result
            except Exception as e:
                logger.warning(f"Cached URL failed: {e}, will try other URLs")
                self._working_url = None

        # Try the primary base_url first
        urls_to_try = [self.base_url]

        # Add failover URLs if enabled
        if self.use_failover:
            for url in MAINNET_SV_URLS:
                if url.rstrip('/') != self.base_url.rstrip('/') and url.rstrip('/') not in [u.rstrip('/') for u in urls_to_try]:
                    urls_to_try.append(url.rstrip('/'))

        last_error = None
        for i, base_url in enumerate(urls_to_try):
            # Use shorter timeout for failover attempts (not the first URL)
            use_timeout = self.failover_timeout if i > 0 else self.timeout
            try:
                logger.info(f"Trying SV node ({i+1}/{len(urls_to_try)}): {base_url} (timeout={use_timeout}s)")
                result = self._make_single_request(
                    base_url, method, endpoint, params, json_data,
                    timeout=use_timeout
                )
                # Success! Cache this URL for future requests
                self._working_url = base_url
                logger.info(f"Successfully connected to: {base_url}")
                return result
            except requests.exceptions.Timeout as e:
                logger.warning(f"Timeout connecting to {base_url}")
                last_error = e
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error to {base_url}")
                last_error = e
            except requests.exceptions.HTTPError as e:
                logger.warning(f"HTTP error from {base_url}: {e.response.status_code if e.response else 'unknown'}")
                last_error = e
            except Exception as e:
                logger.warning(f"Error from {base_url}: {type(e).__name__}")
                last_error = e

        # All URLs failed
        logger.error(f"All {len(urls_to_try)} SV node URLs failed. Last error: {last_error}")
        raise last_error or Exception("All SV node URLs failed")

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
