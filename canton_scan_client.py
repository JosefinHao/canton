"""
Splice Network Scan API Client

A Python client for querying Splice Network on-chain data through the Scan API.
Provides methods for data retrieval and analysis.
"""

import json
import time
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class SpliceScanClient:
    """
    Client for interacting with Splice Network Scan API.

    The Scan API is completely public and requires no authentication!
    Simply provide the base URL and start querying on-chain data.
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize the Splice Scan API client.

        Args:
            base_url: Base URL of the Scan API (e.g., 'https://scan.splice.network/api/v0')
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum number of retry attempts (default: 3)
        """
        self.base_url = base_url.rstrip('/')
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
        # Note: Don't set Content-Type globally - only when actually sending JSON
        headers = {
            'Accept': 'application/json'
        }

        self.session.headers.update(headers)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Make a request to the API.

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
            # Prepare headers for this request
            # Add Content-Type header only when sending JSON data
            request_headers = None
            if json_data is not None:
                # Only set Content-Type when actually sending JSON
                request_headers = {'Content-Type': 'application/json'}

            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=self.timeout
            )
            response.raise_for_status()

            # Handle empty responses
            if response.status_code == 204 or not response.content:
                return {}

            return response.json()

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e}")
            # Print more debug info
            if e.response is not None:
                print(f"Response status: {e.response.status_code}")
                print(f"Response headers: {e.response.headers}")
                print(f"Response body: {e.response.text if e.response.text else 'Empty'}")
            else:
                print(f"No response received")
            raise
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {e}")
            raise

    # ========== DSO Queries ==========

    def get_dso(self) -> Dict[str, Any]:
        """
        Get DSO information.

        Returns:
            Dictionary containing DSO information including sv_user, sv_party_id,
            dso_party_id, voting_threshold, latest_mining_round, amulet_rules,
            dso_rules, sv_node_states, and initial_round
        """
        return self._make_request('GET', '/v0/dso')

    def get_dso_party_id(self) -> Dict[str, Any]:
        """
        Get the party ID of the DSO for the Splice network.

        Returns:
            Dictionary containing dso_party_id
        """
        return self._make_request('GET', '/v0/dso-party-id')

    # ========== Validator Queries ==========

    def get_validator_faucets(self, validator_ids: List[str]) -> Dict[str, Any]:
        """
        Get validator liveness statistics.

        For every argument that is a valid onboarded validator, return statistics
        on its liveness activity, according to on-ledger state at the time of the request.

        Args:
            validator_ids: A list of validator party IDs

        Returns:
            Dictionary containing validatorsReceivedFaucets with statistics for each validator
        """
        params = {'validator_ids': validator_ids}
        return self._make_request('GET', '/v0/validators/validator-faucets', params=params)

    def get_validator_licenses(
        self,
        after: Optional[int] = None,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        List all validators currently approved by members of the DSO, paginated, sorted newest-first.

        Args:
            after: A next_page_token from a prior response; if absent, return the first page
            limit: Maximum number of elements to return, 1000 by default

        Returns:
            Dictionary containing validator_licenses and next_page_token
        """
        params = {'limit': limit}
        if after is not None:
            params['after'] = after
        return self._make_request('GET', '/v0/admin/validator/licenses', params=params)

    def get_top_validators_by_validator_faucets(self, limit: int) -> Dict[str, Any]:
        """
        Get a list of top validators by number of rounds in which they collected faucets.

        Args:
            limit: Maximum number of validator records that may be returned

        Returns:
            Dictionary containing validatorsByReceivedFaucets
        """
        params = {'limit': limit}
        return self._make_request('GET', '/v0/top-validators-by-validator-faucets', params=params)

    # ========== Scan Configuration Queries ==========

    def get_scans(self) -> Dict[str, Any]:
        """
        Retrieve Canton scan configuration for all SVs, grouped by connected synchronizer ID.

        Returns:
            Dictionary containing scans grouped by domainId
        """
        return self._make_request('GET', '/v0/scans')

    def get_dso_sequencers(self) -> Dict[str, Any]:
        """
        Retrieve Canton sequencer configuration for all SVs, grouped by connected synchronizer ID.

        Returns:
            Dictionary containing domainSequencers
        """
        return self._make_request('GET', '/v0/dso-sequencers')

    # ========== Update History Queries ==========

    def get_updates(
        self,
        after_migration_id: Optional[int] = None,
        after_record_time: Optional[str] = None,
        page_size: int = 100,
        daml_value_encoding: str = "compact_json"
    ) -> Dict[str, Any]:
        """
        Get update history in ascending order, paged (RECOMMENDED: use /v2/updates).

        This endpoint uses /v2/updates which removes the offset field in responses
        and sorts events lexicographically in events_by_id by ID for convenience.

        Args:
            after_migration_id: Start after this migration ID
            after_record_time: Start after this record time (ISO format)
            page_size: Maximum number of updates to return
            daml_value_encoding: Encoding format for DAML values (default: compact_json)

        Returns:
            Dictionary containing transactions (list of updates)
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

        return self._make_request('POST', '/v2/updates', json_data=json_data)

    def get_update_by_id(
        self,
        update_id: str,
        daml_value_encoding: str = "compact_json"
    ) -> Dict[str, Any]:
        """
        Get a specific update by ID (RECOMMENDED: use /v2/updates/{update_id}).

        Args:
            update_id: The update ID to retrieve
            daml_value_encoding: Encoding format for DAML values (default: compact_json)

        Returns:
            Dictionary containing the update details
        """
        params = {'daml_value_encoding': daml_value_encoding}
        return self._make_request('GET', f'/v2/updates/{update_id}', params=params)

    # ========== State/ACS Queries ==========

    def get_acs_snapshot_timestamp(
        self,
        before: str,
        migration_id: int
    ) -> Dict[str, Any]:
        """
        Get the timestamp of the most recent snapshot before the given date.

        Args:
            before: ISO format datetime string
            migration_id: Migration ID

        Returns:
            Dictionary containing record_time
        """
        params = {
            'before': before,
            'migration_id': migration_id
        }
        return self._make_request('GET', '/v0/state/acs/snapshot-timestamp', params=params)

    def get_acs(
        self,
        migration_id: int,
        record_time: str,
        record_time_match: str = "exact",
        after: Optional[int] = None,
        page_size: int = 100,
        party_ids: Optional[List[str]] = None,
        templates: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get the ACS (Active Contract Set) for a given migration id and record time.

        Args:
            migration_id: Migration ID
            record_time: Record time (ISO format)
            record_time_match: Match type for record time (default: exact)
            after: Pagination token from previous response
            page_size: Maximum number of contracts to return
            party_ids: Filter by party IDs
            templates: Filter by template IDs

        Returns:
            Dictionary containing created_events, next_page_token, record_time, migration_id
        """
        json_data: Dict[str, Any] = {
            'migration_id': migration_id,
            'record_time': record_time,
            'record_time_match': record_time_match,
            'page_size': page_size
        }

        if after is not None:
            json_data['after'] = after
        if party_ids:
            json_data['party_ids'] = party_ids
        if templates:
            json_data['templates'] = templates

        return self._make_request('POST', '/v0/state/acs', json_data=json_data)

    # ========== Holdings Queries ==========

    def get_holdings_state(
        self,
        migration_id: int,
        record_time: str,
        record_time_match: str = "exact",
        after: Optional[int] = None,
        page_size: int = 100,
        owner_party_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get active amulet contracts for a given migration id and record time.

        Args:
            migration_id: Migration ID
            record_time: Record time (ISO format)
            record_time_match: Match type for record time (default: exact)
            after: Pagination token from previous response
            page_size: Maximum number of contracts to return
            owner_party_ids: Filter by owner party IDs

        Returns:
            Dictionary containing created_events, next_page_token, record_time, migration_id
        """
        json_data: Dict[str, Any] = {
            'migration_id': migration_id,
            'record_time': record_time,
            'record_time_match': record_time_match,
            'page_size': page_size
        }

        if after is not None:
            json_data['after'] = after
        if owner_party_ids:
            json_data['owner_party_ids'] = owner_party_ids

        return self._make_request('POST', '/v0/holdings/state', json_data=json_data)

    def get_holdings_summary(
        self,
        migration_id: int,
        record_time: str,
        record_time_match: str = "exact",
        owner_party_ids: Optional[List[str]] = None,
        as_of_round: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get aggregated amulet holdings summary.

        This is an aggregate of /v0/holdings/state by owner party ID with better
        performance than client-side computation.

        Args:
            migration_id: Migration ID
            record_time: Record time (ISO format)
            record_time_match: Match type for record time (default: exact)
            owner_party_ids: Filter by owner party IDs
            as_of_round: Compute as of specific round

        Returns:
            Dictionary containing summaries, record_time, migration_id, computed_as_of_round
        """
        json_data: Dict[str, Any] = {
            'migration_id': migration_id,
            'record_time': record_time,
            'record_time_match': record_time_match
        }

        if owner_party_ids:
            json_data['owner_party_ids'] = owner_party_ids
        if as_of_round is not None:
            json_data['as_of_round'] = as_of_round

        return self._make_request('POST', '/v0/holdings/summary', json_data=json_data)

    # ========== ANS (Amulet Name Service) Queries ==========

    def get_ans_entries(
        self,
        page_size: int = 100,
        name_prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all non-expired ANS entries.

        Args:
            page_size: Maximum number of results returned
            name_prefix: Filter entries by name prefix (optional)

        Returns:
            Dictionary containing entries (list of ANS entries)
        """
        params = {'page_size': page_size}
        if name_prefix:
            params['name_prefix'] = name_prefix
        return self._make_request('GET', '/v0/ans-entries', params=params)

    def get_ans_entry_by_party(self, party: str) -> Dict[str, Any]:
        """
        Get the first ANS entry for a user party.

        Args:
            party: The user party ID that holds the ANS entry

        Returns:
            Dictionary containing entry (ANS entry details)
        """
        return self._make_request('GET', f'/v0/ans-entries/by-party/{party}')

    def get_ans_entry_by_name(self, name: str) -> Dict[str, Any]:
        """
        Get ANS entry by exact name match.

        Args:
            name: The ANS entry name

        Returns:
            Dictionary containing entry (ANS entry details)
        """
        return self._make_request('GET', f'/v0/ans-entries/by-name/{name}')

    # ========== Mining Rounds Queries ==========

    def get_closed_rounds(self) -> Dict[str, Any]:
        """
        Get every closed mining round on the ledger still in post-close process.

        Returns:
            Dictionary containing rounds (list of closed mining rounds)
        """
        return self._make_request('GET', '/v0/closed-rounds')

    def get_open_and_issuing_mining_rounds(
        self,
        cached_open_mining_round_contract_ids: Optional[List[str]] = None,
        cached_issuing_round_contract_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get all current open and issuing mining rounds.

        Args:
            cached_open_mining_round_contract_ids: Cached contract IDs for efficiency
            cached_issuing_round_contract_ids: Cached contract IDs for efficiency

        Returns:
            Dictionary containing open_mining_rounds, issuing_mining_rounds, time_to_live_in_microseconds
        """
        # API requires both fields to be present in the request body
        # They can be empty arrays if no cached IDs are provided
        json_data: Dict[str, Any] = {
            'cached_open_mining_round_contract_ids': cached_open_mining_round_contract_ids or [],
            'cached_issuing_round_contract_ids': cached_issuing_round_contract_ids or []
        }

        return self._make_request('POST', '/v0/open-and-issuing-mining-rounds', json_data=json_data)

    # ========== Transfer Queries ==========

    def get_transfer_preapproval_by_party(self, party: str) -> Dict[str, Any]:
        """
        Lookup a TransferPreapproval by the receiver party.

        Args:
            party: Party ID

        Returns:
            Dictionary containing transfer_preapproval
        """
        return self._make_request('GET', f'/v0/transfer-preapprovals/by-party/{party}')

    def get_transfer_command_counter(self, party: str) -> Dict[str, Any]:
        """
        Lookup a TransferCommandCounter by the receiver party.

        Args:
            party: Party ID

        Returns:
            Dictionary containing transfer_command_counter
        """
        return self._make_request('GET', f'/v0/transfer-command-counter/{party}')

    def get_transfer_command_status(
        self,
        sender: str,
        nonce: int
    ) -> Dict[str, Any]:
        """
        Retrieve the status of all transfer commands of the given sender for the specified nonce.

        Args:
            sender: Sender party ID
            nonce: Nonce value

        Returns:
            Dictionary containing transfer_commands_by_contract_id
        """
        params = {
            'sender': sender,
            'nonce': nonce
        }
        return self._make_request('GET', '/v0/transfer-command/status', params=params)

    # ========== Event Queries ==========

    def get_events(
        self,
        after_migration_id: Optional[int] = None,
        after_record_time: Optional[str] = None,
        page_size: int = 100,
        daml_value_encoding: str = "compact_json"
    ) -> Dict[str, Any]:
        """
        Get event history in ascending order, paged.

        Args:
            after_migration_id: Start after this migration ID
            after_record_time: Start after this record time (ISO format)
            page_size: Maximum number of events to return
            daml_value_encoding: Encoding format for DAML values (default: compact_json)

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

    def get_event_by_id(
        self,
        update_id: str,
        daml_value_encoding: str = "compact_json"
    ) -> Dict[str, Any]:
        """
        Get a specific event by update ID.

        Args:
            update_id: The update ID to retrieve
            daml_value_encoding: Encoding format for DAML values (default: compact_json)

        Returns:
            Dictionary containing the event details
        """
        params = {'daml_value_encoding': daml_value_encoding}
        return self._make_request('GET', f'/v0/events/{update_id}', params=params)

    # ========== Domain/Synchronizer Queries ==========

    def get_participant_id_for_party(
        self,
        domain_id: str,
        party_id: str
    ) -> Dict[str, Any]:
        """
        Get the ID of the participant hosting a given party.

        Args:
            domain_id: The synchronizer ID to look up a mapping for
            party_id: The party ID to lookup a participant ID for

        Returns:
            Dictionary containing participant_id
        """
        return self._make_request('GET', f'/v0/domains/{domain_id}/parties/{party_id}/participant-id')

    def get_member_traffic_status(
        self,
        domain_id: str,
        member_id: str
    ) -> Dict[str, Any]:
        """
        Get a member's traffic status as reported by the sequencer.

        Args:
            domain_id: The synchronizer ID to look up traffic for
            member_id: The participant or mediator whose traffic to look up (format: code::id::fingerprint)

        Returns:
            Dictionary containing traffic_status
        """
        return self._make_request('GET', f'/v0/domains/{domain_id}/members/{member_id}/traffic-status')

    # ========== Migration Queries ==========

    def get_migration_schedule(self) -> Dict[str, Any]:
        """
        Get scheduled synchronizer upgrade information if one is scheduled.

        Returns:
            Dictionary containing time and migration_id
        """
        return self._make_request('GET', '/v0/migrations/schedule')

    # ========== Featured Apps Queries ==========

    def get_featured_apps(self) -> Dict[str, Any]:
        """
        List every FeaturedAppRight registered with the DSO on the ledger.

        Returns:
            Dictionary containing featured_apps
        """
        return self._make_request('GET', '/v0/featured-apps')

    def get_featured_app_by_provider(self, provider_party_id: str) -> Dict[str, Any]:
        """
        Get FeaturedAppRight for a specific provider if it exists.

        Args:
            provider_party_id: Provider party ID

        Returns:
            Dictionary containing featured_app_right (may be empty)
        """
        return self._make_request('GET', f'/v0/featured-apps/{provider_party_id}')

    # ========== Amulet Rules Queries ==========

    def get_amulet_rules(
        self,
        cached_amulet_rules_contract_id: Optional[str] = None,
        cached_amulet_rules_domain_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get amulet rules contract.

        Args:
            cached_amulet_rules_contract_id: Cached contract ID for efficiency
            cached_amulet_rules_domain_id: Cached domain ID for efficiency

        Returns:
            Dictionary containing amulet_rules_update
        """
        json_data: Dict[str, Any] = {}

        if cached_amulet_rules_contract_id:
            json_data['cached_amulet_rules_contract_id'] = cached_amulet_rules_contract_id
        if cached_amulet_rules_domain_id:
            json_data['cached_amulet_rules_domain_id'] = cached_amulet_rules_domain_id

        return self._make_request('POST', '/v0/amulet-rules', json_data=json_data)

    def get_ans_rules(
        self,
        cached_ans_rules_contract_id: Optional[str] = None,
        cached_ans_rules_domain_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get ANS rules contract.

        Args:
            cached_ans_rules_contract_id: Cached contract ID for efficiency
            cached_ans_rules_domain_id: Cached domain ID for efficiency

        Returns:
            Dictionary containing ans_rules_update
        """
        json_data: Dict[str, Any] = {}

        if cached_ans_rules_contract_id:
            json_data['cached_ans_rules_contract_id'] = cached_ans_rules_contract_id
        if cached_ans_rules_domain_id:
            json_data['cached_ans_rules_domain_id'] = cached_ans_rules_domain_id

        return self._make_request('POST', '/v0/ans-rules', json_data=json_data)

    # ========== Vote Queries ==========

    def get_vote_requests_by_ids(
        self,
        vote_request_contract_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Look up several VoteRequests at once by their contract IDs.

        Args:
            vote_request_contract_ids: List of vote request contract IDs

        Returns:
            Dictionary containing vote_requests
        """
        json_data = {
            'vote_request_contract_ids': vote_request_contract_ids
        }
        return self._make_request('POST', '/v0/voterequest', json_data=json_data)

    def get_vote_request_by_id(self, vote_request_contract_id: str) -> Dict[str, Any]:
        """
        Look up a VoteRequest by contract ID.

        Args:
            vote_request_contract_id: Vote request contract ID

        Returns:
            Dictionary containing dso_rules_vote_request
        """
        return self._make_request('GET', f'/v0/voterequests/{vote_request_contract_id}')

    def get_all_vote_requests(self) -> Dict[str, Any]:
        """
        List all active VoteRequests.

        Returns:
            Dictionary containing dso_rules_vote_requests
        """
        return self._make_request('GET', '/v0/admin/sv/voterequests')

    # ========== Network Information ==========

    def get_splice_instance_names(self) -> Dict[str, Any]:
        """
        Retrieve the UI names of various elements of this Splice network.

        Returns:
            Dictionary containing network_name, network_favicon_url, amulet_name,
            amulet_name_acronym, name_service_name, name_service_name_acronym
        """
        return self._make_request('GET', '/v0/splice-instance-names')

    def get_feature_support(self) -> Dict[str, Any]:
        """
        Get feature support information.

        Returns:
            Dictionary containing feature flags (e.g., no_holding_fees_on_transfers)
        """
        return self._make_request('GET', '/v0/feature-support')

    # ========== Health/Status Endpoints ==========

    def health_check(self) -> bool:
        """
        Check if the API is accessible by calling a minimal endpoint.

        Uses GET /v0/dso as a health check since there's no dedicated health endpoint
        documented in the Splice Scan API specification.

        Returns:
            True if API is healthy, False otherwise
        """
        try:
            self._make_request('GET', '/v0/dso')
            return True
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    # ========== Utility Methods ==========

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
