"""
Featured App Rewards Analyzer

This module provides comprehensive analysis of featured app rewards by processing
AppRewardCoupon contract creation events from the Canton ledger update stream.

Key Features:
- Extract reward data from AppRewardCoupon creation events
- Organize rewards by featured app (provider party ID)
- Track reward progression through mining rounds
- Calculate statistics and metrics for each app
- Generate visualizations for individual apps and comparisons
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
import logging

from canton_scan_client import SpliceScanClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AppRewardRecord:
    """Represents a single featured app reward coupon."""
    provider_party_id: str
    round_number: int
    amount: float
    weight: float
    contract_id: str
    record_time: str
    event_id: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppRewardStats:
    """Statistics for a featured app's rewards."""
    provider_party_id: str
    total_rewards: float
    total_coupons: int
    total_weight: float
    avg_reward_per_coupon: float
    avg_weight_per_coupon: float
    first_round: int
    last_round: int
    rounds_active: int
    rewards_by_round: Dict[int, float] = field(default_factory=dict)
    coupons_by_round: Dict[int, int] = field(default_factory=dict)
    weight_by_round: Dict[int, float] = field(default_factory=dict)


class FeaturedAppRewardsAnalyzer:
    """
    Analyzer for featured app rewards from AppRewardCoupon contract creation events.
    """

    def __init__(self, client: SpliceScanClient):
        """
        Initialize the analyzer.

        Args:
            client: SpliceScanClient instance for API access
        """
        self.client = client
        self.rewards: List[AppRewardRecord] = []
        self.rewards_by_provider: Dict[str, List[AppRewardRecord]] = defaultdict(list)
        self.stats_by_provider: Dict[str, AppRewardStats] = {}

    def fetch_and_process_rewards(
        self,
        max_pages: int = 100,
        page_size: int = 100
    ) -> Dict[str, Any]:
        """
        Fetch updates from the ledger and process AppRewardCoupon creation events.

        Args:
            max_pages: Maximum number of pages to fetch
            page_size: Updates per page

        Returns:
            Dictionary with processing summary
        """
        logger.info(f"Fetching updates (max_pages={max_pages}, page_size={page_size})...")

        all_updates = []
        after_migration_id = None
        after_record_time = None
        pages_fetched = 0

        for page in range(max_pages):
            try:
                result = self.client.get_updates(
                    after_migration_id=after_migration_id,
                    after_record_time=after_record_time,
                    page_size=page_size
                )

                updates = result.get('updates', [])
                if not updates:
                    if page == 0:
                        logger.warning("No updates returned on first page")
                    break

                all_updates.extend(updates)
                pages_fetched += 1

                # Log progress
                if pages_fetched % 10 == 0:
                    logger.info(f"Fetched {pages_fetched} pages, {len(all_updates)} updates so far...")

                # Get next page cursor
                if 'after' in result:
                    after_migration_id = result['after'].get('after_migration_id')
                    after_record_time = result['after'].get('after_record_time')
                else:
                    break

            except Exception as e:
                logger.error(f"Error fetching page {page + 1}: {e}")
                break

        logger.info(f"Fetched {len(all_updates)} updates from {pages_fetched} pages")

        # Process the updates to extract AppRewardCoupon events
        logger.info("Processing updates to extract AppRewardCoupon events...")
        rewards_found = self._process_updates_for_rewards(all_updates)

        # Calculate statistics
        logger.info("Calculating statistics...")
        self._calculate_statistics()

        return {
            'updates_fetched': len(all_updates),
            'pages_fetched': pages_fetched,
            'rewards_found': rewards_found,
            'unique_apps': len(self.rewards_by_provider),
            'providers': list(self.rewards_by_provider.keys())
        }

    def _process_updates_for_rewards(self, updates: List[Dict[str, Any]]) -> int:
        """
        Process updates to extract AppRewardCoupon creation events.

        Args:
            updates: List of update records

        Returns:
            Number of reward coupons found
        """
        rewards_found = 0

        for update in updates:
            try:
                update_data = update.get('update', {})
                root_event_ids = update_data.get('root_event_ids', [])
                events_by_id = update_data.get('events_by_id', {})
                record_time = update.get('record_time', '')

                if not root_event_ids or not events_by_id:
                    continue

                # Traverse event tree to find AppRewardCoupon creation events
                for root_id in root_event_ids:
                    found = self._traverse_for_rewards(
                        event_id=root_id,
                        events_by_id=events_by_id,
                        record_time=record_time
                    )
                    rewards_found += found

            except Exception as e:
                logger.warning(f"Error processing update: {e}")
                continue

        return rewards_found

    def _traverse_for_rewards(
        self,
        event_id: str,
        events_by_id: Dict[str, Any],
        record_time: str
    ) -> int:
        """
        Recursively traverse event tree to find AppRewardCoupon creation events.

        Args:
            event_id: Current event ID to process
            events_by_id: Map of event IDs to event data
            record_time: Record time of the update

        Returns:
            Number of reward coupons found in this subtree
        """
        if event_id not in events_by_id:
            return 0

        event = events_by_id[event_id]
        rewards_found = 0

        # Check if this is a created event with AppRewardCoupon template
        if event.get('created'):
            created = event['created']
            template_id = created.get('template_id', '')

            if 'AppRewardCoupon' in template_id:
                # Extract reward data
                reward = self._extract_reward_data(
                    created=created,
                    event_id=event_id,
                    record_time=record_time
                )
                if reward:
                    self.rewards.append(reward)
                    self.rewards_by_provider[reward.provider_party_id].append(reward)
                    rewards_found += 1

        # Process exercised events (which may have child events)
        if event.get('exercised'):
            exercised = event['exercised']
            child_event_ids = exercised.get('child_event_ids', [])

            for child_id in child_event_ids:
                found = self._traverse_for_rewards(
                    event_id=child_id,
                    events_by_id=events_by_id,
                    record_time=record_time
                )
                rewards_found += found

        return rewards_found

    def _extract_reward_data(
        self,
        created: Dict[str, Any],
        event_id: str,
        record_time: str
    ) -> Optional[AppRewardRecord]:
        """
        Extract reward data from an AppRewardCoupon creation event.

        Args:
            created: The created event data
            event_id: Event ID
            record_time: Record time

        Returns:
            AppRewardRecord if extraction successful, None otherwise
        """
        try:
            contract_id = created.get('contract_id', '')
            create_arguments = created.get('create_arguments', {})

            # Extract fields from the payload
            # The exact structure may vary, so we use defensive parsing
            provider_party_id = self._extract_field(create_arguments, ['provider', 'featured_app_provider', 'party'])
            round_number = self._extract_field(create_arguments, ['round', 'roundNumber', 'mining_round'])
            amount = self._extract_field(create_arguments, ['amount', 'reward', 'amuletAmount'])
            weight = self._extract_field(create_arguments, ['weight', 'appWeight'])

            if not provider_party_id:
                logger.warning(f"Could not extract provider from event {event_id}")
                return None

            # Convert to appropriate types
            try:
                round_number = int(round_number) if round_number is not None else 0
            except (ValueError, TypeError):
                round_number = 0

            try:
                amount = float(amount) if amount is not None else 0.0
            except (ValueError, TypeError):
                amount = 0.0

            try:
                weight = float(weight) if weight is not None else 0.0
            except (ValueError, TypeError):
                weight = 0.0

            return AppRewardRecord(
                provider_party_id=provider_party_id,
                round_number=round_number,
                amount=amount,
                weight=weight,
                contract_id=contract_id,
                record_time=record_time,
                event_id=event_id,
                payload=create_arguments
            )

        except Exception as e:
            logger.warning(f"Error extracting reward data from event {event_id}: {e}")
            return None

    def _extract_field(self, data: Any, field_names: List[str]) -> Any:
        """
        Try multiple field names to extract a value (defensive parsing).

        Args:
            data: The data structure to search
            field_names: List of possible field names to try

        Returns:
            The value if found, None otherwise
        """
        if not isinstance(data, dict):
            return None

        for field_name in field_names:
            if field_name in data:
                value = data[field_name]
                # If it's a nested dict with a value field, extract it
                if isinstance(value, dict) and 'value' in value:
                    return value['value']
                return value

        return None

    def _calculate_statistics(self):
        """Calculate statistics for each featured app."""
        for provider_id, rewards_list in self.rewards_by_provider.items():
            if not rewards_list:
                continue

            # Aggregate by round
            rewards_by_round = defaultdict(float)
            coupons_by_round = defaultdict(int)
            weight_by_round = defaultdict(float)

            total_rewards = 0.0
            total_weight = 0.0

            for reward in rewards_list:
                rewards_by_round[reward.round_number] += reward.amount
                coupons_by_round[reward.round_number] += 1
                weight_by_round[reward.round_number] += reward.weight
                total_rewards += reward.amount
                total_weight += reward.weight

            rounds = sorted(rewards_by_round.keys())
            first_round = min(rounds) if rounds else 0
            last_round = max(rounds) if rounds else 0

            self.stats_by_provider[provider_id] = AppRewardStats(
                provider_party_id=provider_id,
                total_rewards=total_rewards,
                total_coupons=len(rewards_list),
                total_weight=total_weight,
                avg_reward_per_coupon=total_rewards / len(rewards_list) if rewards_list else 0,
                avg_weight_per_coupon=total_weight / len(rewards_list) if rewards_list else 0,
                first_round=first_round,
                last_round=last_round,
                rounds_active=len(rounds),
                rewards_by_round=dict(rewards_by_round),
                coupons_by_round=dict(coupons_by_round),
                weight_by_round=dict(weight_by_round)
            )

    def get_provider_stats(self, provider_party_id: str) -> Optional[AppRewardStats]:
        """
        Get statistics for a specific featured app.

        Args:
            provider_party_id: Provider party ID

        Returns:
            AppRewardStats if found, None otherwise
        """
        return self.stats_by_provider.get(provider_party_id)

    def get_all_stats(self) -> Dict[str, AppRewardStats]:
        """
        Get statistics for all featured apps.

        Returns:
            Dictionary mapping provider IDs to their stats
        """
        return self.stats_by_provider

    def get_top_apps_by_rewards(self, limit: int = 10) -> List[Tuple[str, AppRewardStats]]:
        """
        Get top featured apps by total rewards.

        Args:
            limit: Maximum number of apps to return

        Returns:
            List of (provider_id, stats) tuples sorted by total rewards
        """
        sorted_apps = sorted(
            self.stats_by_provider.items(),
            key=lambda x: x[1].total_rewards,
            reverse=True
        )
        return sorted_apps[:limit]

    def get_top_apps_by_activity(self, limit: int = 10) -> List[Tuple[str, AppRewardStats]]:
        """
        Get top featured apps by activity (number of rounds active).

        Args:
            limit: Maximum number of apps to return

        Returns:
            List of (provider_id, stats) tuples sorted by rounds active
        """
        sorted_apps = sorted(
            self.stats_by_provider.items(),
            key=lambda x: x[1].rounds_active,
            reverse=True
        )
        return sorted_apps[:limit]

    def get_rewards_timeline(self) -> Dict[int, Dict[str, float]]:
        """
        Get rewards timeline showing all apps' rewards by round.

        Returns:
            Dictionary mapping round numbers to provider rewards
        """
        timeline = defaultdict(dict)

        for provider_id, stats in self.stats_by_provider.items():
            for round_num, amount in stats.rewards_by_round.items():
                timeline[round_num][provider_id] = amount

        return dict(timeline)

    def generate_summary_report(self) -> str:
        """
        Generate a text summary report of featured app rewards.

        Returns:
            Formatted summary report
        """
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("FEATURED APP REWARDS ANALYSIS SUMMARY")
        report_lines.append("=" * 80)
        report_lines.append("")

        # Overall statistics
        report_lines.append(f"Total Featured Apps: {len(self.stats_by_provider)}")
        report_lines.append(f"Total Reward Coupons: {len(self.rewards)}")

        total_rewards = sum(stats.total_rewards for stats in self.stats_by_provider.values())
        report_lines.append(f"Total Rewards Distributed: {total_rewards:,.2f} CC")
        report_lines.append("")

        # Top apps by rewards
        report_lines.append("-" * 80)
        report_lines.append("TOP 10 FEATURED APPS BY TOTAL REWARDS")
        report_lines.append("-" * 80)
        report_lines.append("")

        top_apps = self.get_top_apps_by_rewards(limit=10)
        for i, (provider_id, stats) in enumerate(top_apps, 1):
            report_lines.append(f"{i}. {self._format_provider_id(provider_id)}")
            report_lines.append(f"   Total Rewards: {stats.total_rewards:,.2f} CC")
            report_lines.append(f"   Reward Coupons: {stats.total_coupons:,}")
            report_lines.append(f"   Rounds Active: {stats.rounds_active} (Round {stats.first_round} - {stats.last_round})")
            report_lines.append(f"   Avg per Coupon: {stats.avg_reward_per_coupon:.2f} CC")
            report_lines.append("")

        # Top apps by activity
        report_lines.append("-" * 80)
        report_lines.append("TOP 10 FEATURED APPS BY ACTIVITY (Rounds Active)")
        report_lines.append("-" * 80)
        report_lines.append("")

        top_active = self.get_top_apps_by_activity(limit=10)
        for i, (provider_id, stats) in enumerate(top_active, 1):
            report_lines.append(f"{i}. {self._format_provider_id(provider_id)}")
            report_lines.append(f"   Rounds Active: {stats.rounds_active} (Round {stats.first_round} - {stats.last_round})")
            report_lines.append(f"   Total Rewards: {stats.total_rewards:,.2f} CC")
            report_lines.append(f"   Reward Coupons: {stats.total_coupons:,}")
            report_lines.append("")

        report_lines.append("=" * 80)

        return "\n".join(report_lines)

    def _format_provider_id(self, provider_id: str, max_length: int = 60) -> str:
        """Format provider ID for display."""
        if len(provider_id) <= max_length:
            return provider_id
        return provider_id[:max_length-3] + "..."

    def export_to_csv(self, filename: str):
        """
        Export reward data to CSV file.

        Args:
            filename: Output CSV filename
        """
        import csv

        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'provider_party_id',
                'round_number',
                'amount',
                'weight',
                'contract_id',
                'record_time',
                'event_id'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for reward in sorted(self.rewards, key=lambda r: (r.round_number, r.provider_party_id)):
                writer.writerow({
                    'provider_party_id': reward.provider_party_id,
                    'round_number': reward.round_number,
                    'amount': reward.amount,
                    'weight': reward.weight,
                    'contract_id': reward.contract_id,
                    'record_time': reward.record_time,
                    'event_id': reward.event_id
                })

        logger.info(f"Exported {len(self.rewards)} reward records to {filename}")

    def export_stats_to_csv(self, filename: str):
        """
        Export statistics to CSV file.

        Args:
            filename: Output CSV filename
        """
        import csv

        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'provider_party_id',
                'total_rewards',
                'total_coupons',
                'total_weight',
                'avg_reward_per_coupon',
                'avg_weight_per_coupon',
                'first_round',
                'last_round',
                'rounds_active'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for provider_id, stats in sorted(
                self.stats_by_provider.items(),
                key=lambda x: x[1].total_rewards,
                reverse=True
            ):
                writer.writerow({
                    'provider_party_id': provider_id,
                    'total_rewards': stats.total_rewards,
                    'total_coupons': stats.total_coupons,
                    'total_weight': stats.total_weight,
                    'avg_reward_per_coupon': stats.avg_reward_per_coupon,
                    'avg_weight_per_coupon': stats.avg_weight_per_coupon,
                    'first_round': stats.first_round,
                    'last_round': stats.last_round,
                    'rounds_active': stats.rounds_active
                })

        logger.info(f"Exported statistics for {len(self.stats_by_provider)} apps to {filename}")
