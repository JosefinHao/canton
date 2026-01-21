"""
Featured App Rewards Analyzer

This module provides comprehensive analysis of featured app rewards using the
round-party-totals API endpoint.

Key Features:
- Extract reward data from round-party-totals API
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
    """Represents featured app rewards for a specific round."""
    provider_party_id: str
    round_number: int
    app_rewards: float
    cumulative_app_rewards: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppRewardStats:
    """Statistics for a featured app's rewards."""
    provider_party_id: str
    total_rewards: float
    total_coupons: int  # Number of rounds with rewards
    avg_reward_per_round: float
    first_round: int
    last_round: int
    rounds_active: int
    rewards_by_round: Dict[int, float] = field(default_factory=dict)
    cumulative_by_round: Dict[int, float] = field(default_factory=dict)


class FeaturedAppRewardsAnalyzer:
    """
    Analyzer for featured app rewards using the round-party-totals API.
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
        start_round: int = 1,
        end_round: Optional[int] = None,
        max_rounds: int = 500
    ) -> Dict[str, Any]:
        """
        Fetch app rewards data from round-party-totals API.

        Args:
            start_round: Starting round number (default: 1)
            end_round: Ending round number (None = fetch up to max_rounds)
            max_rounds: Maximum number of rounds to fetch (default: 500)

        Returns:
            Dictionary with processing summary
        """
        if end_round is None:
            # Determine the latest round by fetching a small batch
            try:
                test_result = self.client.get_round_party_totals(1, 1)
                if test_result.get('entries'):
                    # Estimate current round (this is a simplified approach)
                    end_round = start_round + max_rounds
                else:
                    end_round = start_round + 100
            except:
                end_round = start_round + 100

        logger.info(f"Fetching app rewards from round {start_round} to {end_round}...")

        all_entries = []
        current_start = start_round
        batches_fetched = 0

        # Fetch in batches of 50 (API limit)
        while current_start <= end_round:
            batch_end = min(current_start + 49, end_round)  # Max 50 rounds per request

            try:
                logger.info(f"Fetching rounds {current_start} to {batch_end}...")
                result = self.client.get_round_party_totals(current_start, batch_end)

                entries = result.get('entries', [])
                if not entries:
                    logger.info(f"No data returned for rounds {current_start}-{batch_end}")
                    break

                all_entries.extend(entries)
                batches_fetched += 1

                current_start = batch_end + 1

            except Exception as e:
                logger.error(f"Error fetching rounds {current_start}-{batch_end}: {e}")
                break

        logger.info(f"Fetched {len(all_entries)} entries from {batches_fetched} batches")

        # Process the entries to extract app rewards
        logger.info("Processing entries to extract app rewards...")
        rewards_found = self._process_entries_for_app_rewards(all_entries)

        # Calculate statistics
        logger.info("Calculating statistics...")
        self._calculate_statistics()

        return {
            'entries_fetched': len(all_entries),
            'batches_fetched': batches_fetched,
            'rewards_found': rewards_found,
            'unique_apps': len(self.rewards_by_provider),
            'providers': list(self.rewards_by_provider.keys())
        }

    def _process_entries_for_app_rewards(self, entries: List[Dict[str, Any]]) -> int:
        """
        Process entries from round-party-totals to extract app rewards.

        Args:
            entries: List of round-party-totals entries

        Returns:
            Number of reward records found
        """
        rewards_found = 0

        for entry in entries:
            try:
                party = entry.get('party', '')
                closed_round = entry.get('closed_round', 0)
                app_rewards_str = entry.get('app_rewards', '0')
                cumulative_app_rewards_str = entry.get('cumulative_app_rewards', '0')

                # Convert string amounts to float
                try:
                    app_rewards = float(app_rewards_str)
                    cumulative_app_rewards = float(cumulative_app_rewards_str)
                except (ValueError, TypeError):
                    app_rewards = 0.0
                    cumulative_app_rewards = 0.0

                # Only include entries with non-zero app rewards
                if app_rewards > 0:
                    record = AppRewardRecord(
                        provider_party_id=party,
                        round_number=closed_round,
                        app_rewards=app_rewards,
                        cumulative_app_rewards=cumulative_app_rewards,
                        metadata=entry
                    )

                    self.rewards.append(record)
                    self.rewards_by_provider[party].append(record)
                    rewards_found += 1

            except Exception as e:
                logger.warning(f"Error processing entry: {e}")
                continue

        return rewards_found

    def _calculate_statistics(self):
        """Calculate statistics for each featured app."""
        for provider_id, rewards_list in self.rewards_by_provider.items():
            if not rewards_list:
                continue

            # Aggregate by round
            rewards_by_round = {}
            cumulative_by_round = {}
            total_rewards = 0.0

            for reward in rewards_list:
                rewards_by_round[reward.round_number] = reward.app_rewards
                cumulative_by_round[reward.round_number] = reward.cumulative_app_rewards
                total_rewards += reward.app_rewards

            rounds = sorted(rewards_by_round.keys())
            first_round = min(rounds) if rounds else 0
            last_round = max(rounds) if rounds else 0

            self.stats_by_provider[provider_id] = AppRewardStats(
                provider_party_id=provider_id,
                total_rewards=total_rewards,
                total_coupons=len(rewards_list),  # Number of rounds with rewards
                avg_reward_per_round=total_rewards / len(rewards_list) if rewards_list else 0,
                first_round=first_round,
                last_round=last_round,
                rounds_active=len(rounds),
                rewards_by_round=rewards_by_round,
                cumulative_by_round=cumulative_by_round
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
        report_lines.append(f"Total Rounds with Rewards: {len(self.rewards)}")

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
            report_lines.append(f"   Rounds with Rewards: {stats.total_coupons:,}")
            report_lines.append(f"   Rounds Active: {stats.rounds_active} (Round {stats.first_round} - {stats.last_round})")
            report_lines.append(f"   Avg per Round: {stats.avg_reward_per_round:.2f} CC")
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
            report_lines.append(f"   Rounds with Rewards: {stats.total_coupons:,}")
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
                'app_rewards',
                'cumulative_app_rewards'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for reward in sorted(self.rewards, key=lambda r: (r.round_number, r.provider_party_id)):
                writer.writerow({
                    'provider_party_id': reward.provider_party_id,
                    'round_number': reward.round_number,
                    'app_rewards': reward.app_rewards,
                    'cumulative_app_rewards': reward.cumulative_app_rewards
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
                'avg_reward_per_round',
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
                    'avg_reward_per_round': stats.avg_reward_per_round,
                    'first_round': stats.first_round,
                    'last_round': stats.last_round,
                    'rounds_active': stats.rounds_active
                })

        logger.info(f"Exported statistics for {len(self.stats_by_provider)} apps to {filename}")
