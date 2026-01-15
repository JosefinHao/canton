"""
Canton Network Scan API Client

A Python client for querying Canton Network on-chain data through the Scan API.
Handles JWT authentication and provides methods for data retrieval and analysis.
"""

import json
import time
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CantonScanClient:
    """
    Client for interacting with Canton Network Scan API.

    Handles authentication, request management, and data retrieval from
    Canton Network's on-chain data API.
    """

    def __init__(
        self,
        base_url: str,
        jwt_token: str,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize the Canton Scan API client.

        Args:
            base_url: Base URL of the Scan API (e.g., 'https://scan.example.com/api/v1')
            jwt_token: JWT token with proper subject (ledgerApiUserId) and audience
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum number of retry attempts (default: 3)
        """
        self.base_url = base_url.rstrip('/')
        self.jwt_token = jwt_token
        self.timeout = timeout

        # Configure session with retry strategy
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

        # Set default headers
        self.session.headers.update({
            'Authorization': f'Bearer {jwt_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            params: URL parameters
            data: Form data
            json_data: JSON data for POST/PUT requests

        Returns:
            Response data as dictionary

        Raises:
            requests.exceptions.RequestException: For request failures
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                timeout=self.timeout
            )
            response.raise_for_status()

            # Handle empty responses
            if response.status_code == 204 or not response.content:
                return {}

            return response.json()

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e}")
            print(f"Response: {e.response.text if e.response else 'No response'}")
            raise
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {e}")
            raise

    # ========== Transaction Queries ==========

    def get_transactions(
        self,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        party_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve transactions from the ledger.

        Args:
            limit: Maximum number of transactions to return
            offset: Number of transactions to skip
            start_time: Filter transactions after this time (ISO format)
            end_time: Filter transactions before this time (ISO format)
            party_id: Filter by specific party ID

        Returns:
            Dictionary containing transactions and metadata
        """
        params = {
            'limit': limit,
            'offset': offset
        }

        if start_time:
            params['start_time'] = start_time
        if end_time:
            params['end_time'] = end_time
        if party_id:
            params['party_id'] = party_id

        return self._make_request('GET', '/transactions', params=params)

    def get_transaction_by_id(self, transaction_id: str) -> Dict[str, Any]:
        """
        Retrieve a specific transaction by ID.

        Args:
            transaction_id: Transaction ID

        Returns:
            Transaction details
        """
        return self._make_request('GET', f'/transactions/{transaction_id}')

    def get_transaction_tree(
        self,
        limit: int = 100,
        offset: int = 0,
        party_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve transaction trees (complete transaction structure).

        Args:
            limit: Maximum number of transaction trees to return
            offset: Number of transaction trees to skip
            party_id: Filter by specific party ID

        Returns:
            Dictionary containing transaction trees
        """
        params = {
            'limit': limit,
            'offset': offset
        }

        if party_id:
            params['party_id'] = party_id

        return self._make_request('GET', '/transaction-trees', params=params)

    # ========== Contract Queries ==========

    def get_active_contracts(
        self,
        template_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Retrieve active contracts from the ledger.

        Args:
            template_id: Filter by template ID
            limit: Maximum number of contracts to return
            offset: Number of contracts to skip

        Returns:
            Dictionary containing active contracts
        """
        params = {
            'limit': limit,
            'offset': offset
        }

        if template_id:
            params['template_id'] = template_id

        return self._make_request('GET', '/contracts/active', params=params)

    def get_contract_by_id(self, contract_id: str) -> Dict[str, Any]:
        """
        Retrieve a specific contract by ID.

        Args:
            contract_id: Contract ID

        Returns:
            Contract details
        """
        return self._make_request('GET', f'/contracts/{contract_id}')

    def search_contracts(
        self,
        query: Dict[str, Any],
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Search contracts with custom query parameters.

        Args:
            query: Search query parameters
            limit: Maximum number of results

        Returns:
            Search results
        """
        params = {'limit': limit}
        return self._make_request('POST', '/contracts/search', params=params, json_data=query)

    # ========== Party Queries ==========

    def get_parties(self) -> Dict[str, Any]:
        """
        Retrieve all parties on the ledger.

        Returns:
            Dictionary containing party information
        """
        return self._make_request('GET', '/parties')

    def get_party_by_id(self, party_id: str) -> Dict[str, Any]:
        """
        Retrieve a specific party by ID.

        Args:
            party_id: Party ID

        Returns:
            Party details
        """
        return self._make_request('GET', f'/parties/{party_id}')

    # ========== Event Queries ==========

    def get_events(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve events from the ledger.

        Args:
            event_type: Filter by event type (created, archived, exercised)
            limit: Maximum number of events to return
            offset: Number of events to skip
            start_time: Filter events after this time (ISO format)
            end_time: Filter events before this time (ISO format)

        Returns:
            Dictionary containing events
        """
        params = {
            'limit': limit,
            'offset': offset
        }

        if event_type:
            params['event_type'] = event_type
        if start_time:
            params['start_time'] = start_time
        if end_time:
            params['end_time'] = end_time

        return self._make_request('GET', '/events', params=params)

    # ========== Template Queries ==========

    def get_templates(self) -> Dict[str, Any]:
        """
        Retrieve all contract templates.

        Returns:
            Dictionary containing template information
        """
        return self._make_request('GET', '/templates')

    def get_template_by_id(self, template_id: str) -> Dict[str, Any]:
        """
        Retrieve a specific template by ID.

        Args:
            template_id: Template ID

        Returns:
            Template details
        """
        return self._make_request('GET', f'/templates/{template_id}')

    # ========== Statistics & Analytics ==========

    def get_ledger_stats(self) -> Dict[str, Any]:
        """
        Retrieve overall ledger statistics.

        Returns:
            Dictionary containing ledger statistics
        """
        return self._make_request('GET', '/stats/ledger')

    def get_party_stats(self, party_id: str) -> Dict[str, Any]:
        """
        Retrieve statistics for a specific party.

        Args:
            party_id: Party ID

        Returns:
            Party statistics
        """
        return self._make_request('GET', f'/stats/party/{party_id}')

    def get_template_stats(self, template_id: str) -> Dict[str, Any]:
        """
        Retrieve statistics for a specific template.

        Args:
            template_id: Template ID

        Returns:
            Template statistics
        """
        return self._make_request('GET', f'/stats/template/{template_id}')

    # ========== Utility Methods ==========

    def get_ledger_time(self) -> Dict[str, Any]:
        """
        Get current ledger time.

        Returns:
            Dictionary containing ledger time information
        """
        return self._make_request('GET', '/ledger/time')

    def get_ledger_identity(self) -> Dict[str, Any]:
        """
        Get ledger identity information.

        Returns:
            Dictionary containing ledger identity
        """
        return self._make_request('GET', '/ledger/identity')

    def health_check(self) -> bool:
        """
        Check if the API is accessible.

        Returns:
            True if API is healthy, False otherwise
        """
        try:
            self._make_request('GET', '/health')
            return True
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    # ========== Batch Operations ==========

    def get_all_transactions_paginated(
        self,
        batch_size: int = 100,
        max_items: Optional[int] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all transactions using pagination.

        Args:
            batch_size: Number of items per batch
            max_items: Maximum total items to retrieve (None for all)
            **kwargs: Additional parameters for get_transactions

        Returns:
            List of all transactions
        """
        all_transactions = []
        offset = 0

        while True:
            response = self.get_transactions(
                limit=batch_size,
                offset=offset,
                **kwargs
            )

            transactions = response.get('transactions', [])
            if not transactions:
                break

            all_transactions.extend(transactions)
            offset += len(transactions)

            if max_items and len(all_transactions) >= max_items:
                return all_transactions[:max_items]

            # Check if we've retrieved all available data
            total = response.get('total', len(transactions))
            if offset >= total:
                break

        return all_transactions

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
