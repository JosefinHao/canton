"""
Update Tree Processor for Canton Scan API

This module provides functionality for processing updates from the Canton Scan API
by traversing the update tree in preorder and accumulating state changes.

Key Features:
- Preorder traversal of event trees starting from root event IDs
- Selective parsing based on template IDs
- State accumulation for contracts, balances, mining rounds, and governance
- Defensive parsing that doesn't break on new fields or templates
"""

from typing import Dict, Any, List, Optional, Set, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ContractState:
    """Represents the state of a contract."""
    contract_id: str
    template_id: str
    created_at: str
    archived_at: Optional[str] = None
    is_active: bool = True
    created_event_id: Optional[str] = None
    archived_event_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BalanceRecord:
    """Represents a Canton Coin balance record."""
    owner: str
    amount: float
    record_time: str
    round_number: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MiningRoundState:
    """Represents the state of a mining round."""
    round_number: int
    contract_id: str
    status: str  # 'open', 'issuing', 'closed'
    opened_at: Optional[str] = None
    issuing_at: Optional[str] = None
    closed_at: Optional[str] = None
    configuration: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernanceDecision:
    """Represents a governance decision or vote."""
    vote_request_id: str
    action_name: str
    requested_at: str
    accepted: Optional[bool] = None
    votes: List[Dict[str, Any]] = field(default_factory=list)
    outcome: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessorState:
    """Accumulates state changes from processing updates."""
    # Contract tracking
    contracts: Dict[str, ContractState] = field(default_factory=dict)
    active_contracts: Set[str] = field(default_factory=set)

    # Balance tracking
    balances: Dict[str, List[BalanceRecord]] = field(default_factory=lambda: defaultdict(list))

    # Mining round tracking
    mining_rounds: Dict[int, MiningRoundState] = field(default_factory=dict)
    current_round: Optional[int] = None

    # Governance tracking
    governance_decisions: Dict[str, GovernanceDecision] = field(default_factory=dict)

    # Statistics
    events_processed: int = 0
    updates_processed: int = 0
    errors_encountered: List[str] = field(default_factory=list)


class UpdateTreeProcessor:
    """
    Processes updates from Canton Scan API by traversing the event tree
    and accumulating state changes.
    """

    # Template ID patterns for selective parsing
    TEMPLATE_PATTERNS = {
        'amulet': [
            'Splice.Amulet:Amulet',
            'Splice.AmuletRules:AmuletRules',
        ],
        'mining_round': [
            'Splice.Round:OpenMiningRound',
            'Splice.Round:IssuingMiningRound',
            'Splice.Round:ClosedMiningRound',
        ],
        'ans': [
            'Splice.Ans:AnsEntry',
            'Splice.AnsRules:AnsRules',
        ],
        'validator': [
            'Splice.ValidatorLicense:ValidatorLicense',
            'Splice.ValidatorRight:ValidatorRight',
        ],
        'governance': [
            'Splice.DsoRules:VoteRequest',
            'Splice.DsoRules:Vote',
            'Splice.DsoRules:DsoRules',
        ],
    }

    def __init__(self, custom_handlers: Optional[Dict[str, Callable]] = None):
        """
        Initialize the processor.

        Args:
            custom_handlers: Optional dict mapping template patterns to handler functions
        """
        self.state = ProcessorState()
        self.custom_handlers = custom_handlers or {}

    def process_updates(
        self,
        updates: List[Dict[str, Any]],
        filter_templates: Optional[List[str]] = None
    ) -> ProcessorState:
        """
        Process a list of updates by traversing their event trees.

        Args:
            updates: List of update records from Canton Scan API
            filter_templates: Optional list of template patterns to filter on

        Returns:
            ProcessorState containing accumulated state changes
        """
        for update in updates:
            try:
                self._process_update(update, filter_templates)
            except Exception as e:
                error_msg = f"Error processing update {self._safe_get(update, 'update_id')}: {str(e)}"
                logger.warning(error_msg)
                self.state.errors_encountered.append(error_msg)
                continue

        return self.state

    def _process_update(
        self,
        update: Dict[str, Any],
        filter_templates: Optional[List[str]] = None
    ):
        """Process a single update by traversing its event tree."""
        update_id = self._safe_get(update, 'update_id', 'unknown')
        record_time = self._safe_get(update, 'record_time')

        # Get the update data
        update_data = self._safe_get(update, 'update', {})

        # Get root event IDs and events map
        root_event_ids = self._safe_get(update_data, 'root_event_ids', [])
        events_by_id = self._safe_get(update_data, 'events_by_id', {})

        if not root_event_ids or not events_by_id:
            # No events to process, skip
            return

        # Traverse the event tree in preorder starting from root events
        for root_id in root_event_ids:
            self._traverse_event_tree(
                event_id=root_id,
                events_by_id=events_by_id,
                update_id=update_id,
                record_time=record_time,
                filter_templates=filter_templates
            )

        self.state.updates_processed += 1

    def _traverse_event_tree(
        self,
        event_id: str,
        events_by_id: Dict[str, Any],
        update_id: str,
        record_time: str,
        filter_templates: Optional[List[str]] = None
    ):
        """
        Traverse the event tree in preorder (process node, then children).

        Args:
            event_id: Current event ID to process
            events_by_id: Map of event IDs to event data
            update_id: The update ID this event belongs to
            record_time: Record time of the update
            filter_templates: Optional list of template patterns to filter on
        """
        # Get the event data (defensive: check if event exists)
        event = events_by_id.get(event_id)
        if not event:
            logger.debug(f"Event {event_id} not found in events_by_id")
            return

        # Process this event (preorder: process before children)
        self._process_event(event, event_id, update_id, record_time, filter_templates)

        # Get child event IDs for recursive traversal
        child_event_ids = self._get_child_event_ids(event)

        # Recursively process children in order (preorder traversal)
        for child_id in child_event_ids:
            self._traverse_event_tree(
                event_id=child_id,
                events_by_id=events_by_id,
                update_id=update_id,
                record_time=record_time,
                filter_templates=filter_templates
            )

    def _process_event(
        self,
        event: Dict[str, Any],
        event_id: str,
        update_id: str,
        record_time: str,
        filter_templates: Optional[List[str]] = None
    ):
        """
        Process a single event based on its type and template.

        Args:
            event: Event data
            event_id: Event ID
            update_id: Update ID
            record_time: Record time
            filter_templates: Optional list of template patterns to filter on
        """
        self.state.events_processed += 1

        # Determine event type (created, archived, exercised)
        event_type = self._get_event_type(event)

        if event_type == 'created':
            self._process_created_event(event, event_id, record_time, filter_templates)
        elif event_type == 'archived':
            self._process_archived_event(event, event_id, record_time, filter_templates)
        elif event_type == 'exercised':
            self._process_exercised_event(event, event_id, record_time, filter_templates)
        else:
            logger.debug(f"Unknown event type for event {event_id}")

    def _process_created_event(
        self,
        event: Dict[str, Any],
        event_id: str,
        record_time: str,
        filter_templates: Optional[List[str]] = None
    ):
        """Process a contract creation event."""
        created = self._safe_get(event, 'created', {})

        # Get template ID
        template_id = self._get_template_id(created)

        # Check if we should process this template
        if filter_templates and not self._matches_templates(template_id, filter_templates):
            return

        # Get contract ID
        contract_id = self._safe_get(created, 'contract_id', '')

        # Create contract state record
        contract_state = ContractState(
            contract_id=contract_id,
            template_id=template_id,
            created_at=record_time,
            is_active=True,
            created_event_id=event_id,
            payload=self._safe_get(created, 'create_arguments', {})
        )

        # Store contract state
        self.state.contracts[contract_id] = contract_state
        self.state.active_contracts.add(contract_id)

        # Process specific contract types
        self._process_contract_creation(template_id, contract_id, created, record_time)

    def _process_archived_event(
        self,
        event: Dict[str, Any],
        event_id: str,
        record_time: str,
        filter_templates: Optional[List[str]] = None
    ):
        """Process a contract archival event."""
        archived = self._safe_get(event, 'archived', {})

        # Get template ID
        template_id = self._get_template_id(archived)

        # Check if we should process this template
        if filter_templates and not self._matches_templates(template_id, filter_templates):
            return

        # Get contract ID
        contract_id = self._safe_get(archived, 'contract_id', '')

        # Update contract state if we're tracking it
        if contract_id in self.state.contracts:
            self.state.contracts[contract_id].is_active = False
            self.state.contracts[contract_id].archived_at = record_time
            self.state.contracts[contract_id].archived_event_id = event_id
            self.state.active_contracts.discard(contract_id)

        # Process specific contract type archival
        self._process_contract_archival(template_id, contract_id, archived, record_time)

    def _process_exercised_event(
        self,
        event: Dict[str, Any],
        event_id: str,
        record_time: str,
        filter_templates: Optional[List[str]] = None
    ):
        """Process a choice exercise event."""
        exercised = self._safe_get(event, 'exercised', {})

        # Get template ID and choice
        template_id = self._get_template_id(exercised)
        choice = self._safe_get(exercised, 'choice', '')

        # Check if we should process this template
        if filter_templates and not self._matches_templates(template_id, filter_templates):
            return

        # Process specific choices
        self._process_choice_exercise(template_id, choice, exercised, record_time)

    def _process_contract_creation(
        self,
        template_id: str,
        contract_id: str,
        created: Dict[str, Any],
        record_time: str
    ):
        """Process contract creation for specific template types."""

        # Process Canton Coin (Amulet) contracts
        if 'Amulet' in template_id:
            self._process_amulet_creation(contract_id, created, record_time)

        # Process mining round contracts
        elif 'MiningRound' in template_id:
            self._process_mining_round_creation(template_id, contract_id, created, record_time)

        # Process governance contracts
        elif 'VoteRequest' in template_id:
            self._process_vote_request_creation(contract_id, created, record_time)

        # Allow custom handlers
        for pattern, handler in self.custom_handlers.items():
            if pattern in template_id:
                try:
                    handler('created', template_id, created, record_time, self.state)
                except Exception as e:
                    logger.warning(f"Custom handler error for {pattern}: {e}")

    def _process_contract_archival(
        self,
        template_id: str,
        contract_id: str,
        archived: Dict[str, Any],
        record_time: str
    ):
        """Process contract archival for specific template types."""

        # Process mining round transitions
        if 'MiningRound' in template_id:
            self._process_mining_round_archival(template_id, contract_id, record_time)

    def _process_choice_exercise(
        self,
        template_id: str,
        choice: str,
        exercised: Dict[str, Any],
        record_time: str
    ):
        """Process choice exercises for specific templates and choices."""

        # Process governance votes
        if 'VoteRequest' in template_id and 'Vote' in choice:
            self._process_vote(exercised, record_time)

        # Process Amulet transfers
        elif 'Amulet' in template_id and 'Transfer' in choice:
            self._process_amulet_transfer(exercised, record_time)

    def _process_amulet_creation(
        self,
        contract_id: str,
        created: Dict[str, Any],
        record_time: str
    ):
        """Process Amulet (Canton Coin) creation to track balances."""
        try:
            args = self._safe_get(created, 'create_arguments', {})
            owner = self._safe_get(args, 'owner', 'unknown')
            amount = float(self._safe_get(args, 'amount', {}).get('amount', 0))

            balance_record = BalanceRecord(
                owner=owner,
                amount=amount,
                record_time=record_time,
                details={'contract_id': contract_id, 'type': 'created'}
            )

            self.state.balances[owner].append(balance_record)

        except Exception as e:
            logger.debug(f"Error processing amulet creation: {e}")

    def _process_amulet_transfer(
        self,
        exercised: Dict[str, Any],
        record_time: str
    ):
        """Process Amulet transfer to track balance changes."""
        try:
            args = self._safe_get(exercised, 'choice_argument', {})
            from_party = self._safe_get(exercised, 'acting_parties', ['unknown'])[0]
            to_party = self._safe_get(args, 'receiver', 'unknown')
            amount = float(self._safe_get(args, 'amount', {}).get('amount', 0))

            # Record outgoing transfer
            self.state.balances[from_party].append(BalanceRecord(
                owner=from_party,
                amount=-amount,
                record_time=record_time,
                details={'type': 'transfer_out', 'to': to_party}
            ))

            # Record incoming transfer
            self.state.balances[to_party].append(BalanceRecord(
                owner=to_party,
                amount=amount,
                record_time=record_time,
                details={'type': 'transfer_in', 'from': from_party}
            ))

        except Exception as e:
            logger.debug(f"Error processing amulet transfer: {e}")

    def _process_mining_round_creation(
        self,
        template_id: str,
        contract_id: str,
        created: Dict[str, Any],
        record_time: str
    ):
        """Process mining round creation."""
        try:
            args = self._safe_get(created, 'create_arguments', {})
            round_number = int(self._safe_get(args, 'round', {}).get('number', 0))

            # Determine status from template
            status = 'open'
            if 'IssuingMiningRound' in template_id:
                status = 'issuing'
            elif 'ClosedMiningRound' in template_id:
                status = 'closed'

            # Create or update mining round state
            if round_number not in self.state.mining_rounds:
                self.state.mining_rounds[round_number] = MiningRoundState(
                    round_number=round_number,
                    contract_id=contract_id,
                    status=status,
                    configuration=args
                )
            else:
                # Update existing round
                round_state = self.state.mining_rounds[round_number]
                round_state.status = status
                round_state.contract_id = contract_id

            # Set timestamps based on status
            round_state = self.state.mining_rounds[round_number]
            if status == 'open' and not round_state.opened_at:
                round_state.opened_at = record_time
            elif status == 'issuing' and not round_state.issuing_at:
                round_state.issuing_at = record_time
            elif status == 'closed' and not round_state.closed_at:
                round_state.closed_at = record_time

            # Track current round
            if status == 'open':
                self.state.current_round = round_number

        except Exception as e:
            logger.debug(f"Error processing mining round creation: {e}")

    def _process_mining_round_archival(
        self,
        template_id: str,
        contract_id: str,
        record_time: str
    ):
        """Process mining round archival (transition to next state)."""
        # Find the round by contract ID and mark transition time
        for round_state in self.state.mining_rounds.values():
            if round_state.contract_id == contract_id:
                if round_state.status == 'open':
                    round_state.issuing_at = record_time
                elif round_state.status == 'issuing':
                    round_state.closed_at = record_time
                break

    def _process_vote_request_creation(
        self,
        contract_id: str,
        created: Dict[str, Any],
        record_time: str
    ):
        """Process governance vote request creation."""
        try:
            args = self._safe_get(created, 'create_arguments', {})
            action_name = self._safe_get(args, 'action', {}).get('tag', 'unknown')
            vote_request_id = self._safe_get(args, 'trackingCid', contract_id)

            decision = GovernanceDecision(
                vote_request_id=vote_request_id,
                action_name=action_name,
                requested_at=record_time,
                details=args
            )

            self.state.governance_decisions[vote_request_id] = decision

        except Exception as e:
            logger.debug(f"Error processing vote request creation: {e}")

    def _process_vote(
        self,
        exercised: Dict[str, Any],
        record_time: str
    ):
        """Process a governance vote."""
        try:
            args = self._safe_get(exercised, 'choice_argument', {})
            vote_request_id = self._safe_get(args, 'trackingCid', 'unknown')
            voter = self._safe_get(exercised, 'acting_parties', ['unknown'])[0]
            accept = self._safe_get(args, 'accept', None)

            if vote_request_id in self.state.governance_decisions:
                decision = self.state.governance_decisions[vote_request_id]
                decision.votes.append({
                    'voter': voter,
                    'accept': accept,
                    'voted_at': record_time
                })

        except Exception as e:
            logger.debug(f"Error processing vote: {e}")

    def _get_event_type(self, event: Dict[str, Any]) -> Optional[str]:
        """Determine the type of event (created, archived, exercised)."""
        if 'created' in event:
            return 'created'
        elif 'archived' in event:
            return 'archived'
        elif 'exercised' in event:
            return 'exercised'
        return None

    def _get_child_event_ids(self, event: Dict[str, Any]) -> List[str]:
        """Get child event IDs from an event (defensive parsing)."""
        # Check exercised events for child_event_ids
        if 'exercised' in event:
            return self._safe_get(event['exercised'], 'child_event_ids', [])

        # Other event types don't have children
        return []

    def _get_template_id(self, event_data: Dict[str, Any]) -> str:
        """Extract template ID from event data (defensive parsing)."""
        # Try different possible locations for template_id
        template_id = self._safe_get(event_data, 'template_id')

        if not template_id:
            # Try nested structure
            template_id_obj = self._safe_get(event_data, 'template_id', {})
            if isinstance(template_id_obj, dict):
                # Format: {package_id, module_name, entity_name}
                module = self._safe_get(template_id_obj, 'module_name', '')
                entity = self._safe_get(template_id_obj, 'entity_name', '')
                template_id = f"{module}:{entity}" if module and entity else 'unknown'
            else:
                template_id = str(template_id_obj) if template_id_obj else 'unknown'

        return template_id

    def _matches_templates(self, template_id: str, patterns: List[str]) -> bool:
        """Check if template ID matches any of the given patterns."""
        for pattern in patterns:
            if pattern in template_id:
                return True
        return False

    def _safe_get(self, data: Any, key: str, default: Any = None) -> Any:
        """Safely get a value from a dict (defensive parsing)."""
        if not isinstance(data, dict):
            return default
        return data.get(key, default)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of processed data."""
        return {
            'updates_processed': self.state.updates_processed,
            'events_processed': self.state.events_processed,
            'total_contracts': len(self.state.contracts),
            'active_contracts': len(self.state.active_contracts),
            'unique_balance_owners': len(self.state.balances),
            'mining_rounds_tracked': len(self.state.mining_rounds),
            'current_round': self.state.current_round,
            'governance_decisions': len(self.state.governance_decisions),
            'errors_encountered': len(self.state.errors_encountered)
        }

    def get_contract_states(self) -> Dict[str, ContractState]:
        """Get all tracked contract states."""
        return self.state.contracts

    def get_active_contracts(self) -> List[ContractState]:
        """Get all currently active contracts."""
        return [
            self.state.contracts[cid]
            for cid in self.state.active_contracts
            if cid in self.state.contracts
        ]

    def get_balance_history(self, owner: Optional[str] = None) -> Dict[str, List[BalanceRecord]]:
        """Get balance history for an owner or all owners."""
        if owner:
            return {owner: self.state.balances.get(owner, [])}
        return dict(self.state.balances)

    def get_mining_rounds(self) -> Dict[int, MiningRoundState]:
        """Get all mining round states."""
        return self.state.mining_rounds

    def get_governance_decisions(self) -> Dict[str, GovernanceDecision]:
        """Get all governance decisions."""
        return self.state.governance_decisions
