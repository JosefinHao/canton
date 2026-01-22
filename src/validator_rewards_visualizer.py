"""
Validator Rewards Visualizer

This module provides visualization capabilities for validator rewards analysis,
including individual validator progress charts, comparison charts, and ecosystem overviews.
"""

from typing import Dict, List, Optional, Tuple, Any
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
from collections import defaultdict

from validator_rewards_analyzer import ValidatorRewardsAnalyzer, ValidatorRewardStats


class ValidatorRewardsVisualizer:
    """
    Visualizer for validator rewards data.
    """

    def __init__(self, analyzer: ValidatorRewardsAnalyzer):
        """
        Initialize the visualizer.

        Args:
            analyzer: ValidatorRewardsAnalyzer instance with processed data
        """
        self.analyzer = analyzer

    def plot_app_progress(
        self,
        validator_party_id: str,
        output_file: Optional[str] = None,
        show_coupons: bool = True
    ) -> str:
        """
        Plot reward progression for a single validator.

        Args:
            validator_party_id: Provider party ID
            output_file: Optional output filename (defaults to provider_id_progress.png)
            show_coupons: Whether to show coupon count as secondary axis

        Returns:
            Output filename
        """
        stats = self.analyzer.get_validator_stats(validator_party_id)
        if not stats:
            raise ValueError(f"No data found for provider {validator_party_id}")

        # Prepare data
        rounds = sorted(stats.rewards_by_round.keys())
        rewards = [stats.rewards_by_round[r] for r in rounds]
        coupons = [stats.coupons_by_round[r] for r in rounds] if show_coupons else None

        # Create figure
        fig, ax1 = plt.subplots(figsize=(14, 7))

        # Plot rewards
        color1 = 'tab:blue'
        ax1.set_xlabel('Mining Round', fontsize=12)
        ax1.set_ylabel('Rewards (CC)', color=color1, fontsize=12)
        line1 = ax1.plot(rounds, rewards, color=color1, linewidth=2, marker='o',
                         markersize=4, label='Total Rewards per Round')
        ax1.tick_params(axis='y', labelcolor=color1)
        ax1.grid(True, alpha=0.3)

        # Plot coupons on secondary axis
        if show_coupons and coupons:
            ax2 = ax1.twinx()
            color2 = 'tab:orange'
            ax2.set_ylabel('Reward Coupons Count', color=color2, fontsize=12)
            line2 = ax2.plot(rounds, coupons, color=color2, linewidth=2, marker='s',
                            markersize=4, linestyle='--', label='Coupon Count per Round')
            ax2.tick_params(axis='y', labelcolor=color2)

            # Combine legends
            lines = line1 + line2
            labels = [l.get_label() for l in lines]
            ax1.legend(lines, labels, loc='upper left', fontsize=10)
        else:
            ax1.legend(loc='upper left', fontsize=10)

        # Title and formatting
        provider_display = self._format_validator_id(validator_party_id, max_length=50)
        plt.title(f'Validator Rewards Progress\n{provider_display}',
                 fontsize=14, fontweight='bold', pad=20)

        # Add statistics text box
        stats_text = (
            f"Total Rewards: {stats.total_rewards:,.2f} CC\n"
            f"Total Coupons: {stats.total_coupons:,}\n"
            f"Rounds Active: {stats.rounds_active}\n"
            f"Avg per Coupon: {stats.avg_reward_per_coupon:.2f} CC"
        )
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax1.text(0.98, 0.97, stats_text, transform=ax1.transAxes, fontsize=10,
                verticalalignment='top', horizontalalignment='right', bbox=props)

        plt.tight_layout()

        # Save figure
        if not output_file:
            safe_name = validator_party_id.replace(':', '_').replace('/', '_')[:50]
            output_file = f'{safe_name}_progress.png'

        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        return output_file

    def plot_top_apps_comparison(
        self,
        limit: int = 10,
        output_file: str = 'top_apps_rewards.png',
        by_metric: str = 'rewards'
    ) -> str:
        """
        Plot comparison of top validators.

        Args:
            limit: Number of top validators to show
            output_file: Output filename
            by_metric: Metric to sort by ('rewards', 'activity', 'coupons')

        Returns:
            Output filename
        """
        # Get top validators
        if by_metric == 'rewards':
            top_apps = self.analyzer.get_top_validators_by_rewards(limit=limit)
            ylabel = 'Total Rewards (CC)'
            title_metric = 'Total Rewards'
        elif by_metric == 'activity':
            top_apps = self.analyzer.get_top_validators_by_activity(limit=limit)
            ylabel = 'Rounds Active'
            title_metric = 'Activity (Rounds)'
        else:  # coupons
            top_apps = sorted(
                self.analyzer.get_all_stats().items(),
                key=lambda x: x[1].total_coupons,
                reverse=True
            )[:limit]
            ylabel = 'Total Reward Coupons'
            title_metric = 'Coupon Count'

        # Prepare data
        providers = [self._format_validator_id(p_id, 30) for p_id, _ in top_apps]

        if by_metric == 'rewards':
            values = [stats.total_rewards for _, stats in top_apps]
        elif by_metric == 'activity':
            values = [stats.rounds_active for _, stats in top_apps]
        else:
            values = [stats.total_coupons for _, stats in top_apps]

        # Create horizontal bar chart
        fig, ax = plt.subplots(figsize=(12, max(8, limit * 0.6)))

        colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(providers)))
        bars = ax.barh(providers, values, color=colors, edgecolor='black', linewidth=0.5)

        # Add value labels
        for i, (bar, value) in enumerate(zip(bars, values)):
            if by_metric == 'rewards':
                label = f'{value:,.0f} CC'
            else:
                label = f'{value:,}'
            ax.text(value, bar.get_y() + bar.get_height()/2, f' {label}',
                   va='center', ha='left', fontsize=9, fontweight='bold')

        ax.set_xlabel(ylabel, fontsize=12, fontweight='bold')
        ax.set_title(f'Top {limit} Featured Apps by {title_metric}',
                    fontsize=14, fontweight='bold', pad=20)
        ax.grid(axis='x', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        return output_file

    def plot_app_comparison_timeline(
        self,
        provider_ids: List[str],
        output_file: str = 'apps_comparison_timeline.png',
        cumulative: bool = False
    ) -> str:
        """
        Plot reward timeline comparison for multiple apps.

        Args:
            provider_ids: List of provider party IDs to compare
            output_file: Output filename
            cumulative: If True, show cumulative rewards over time

        Returns:
            Output filename
        """
        fig, ax = plt.subplots(figsize=(16, 8))

        colors = plt.cm.tab10(np.linspace(0, 0.9, len(provider_ids)))

        for i, provider_id in enumerate(provider_ids):
            stats = self.analyzer.get_validator_stats(provider_id)
            if not stats:
                continue

            rounds = sorted(stats.rewards_by_round.keys())
            rewards = [stats.rewards_by_round[r] for r in rounds]

            if cumulative:
                rewards = np.cumsum(rewards)

            label = self._format_validator_id(provider_id, 40)
            ax.plot(rounds, rewards, color=colors[i], linewidth=2, marker='o',
                   markersize=5, label=label, alpha=0.8)

        ax.set_xlabel('Mining Round', fontsize=12, fontweight='bold')
        ylabel = 'Cumulative Rewards (CC)' if cumulative else 'Rewards per Round (CC)'
        ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')

        title = 'Featured Apps Rewards Comparison - ' + ('Cumulative' if cumulative else 'Per Round')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

        ax.legend(loc='best', fontsize=9, framealpha=0.9)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        return output_file

    def plot_ecosystem_overview(
        self,
        output_file: str = 'ecosystem_overview.png',
        top_n: int = 15
    ) -> str:
        """
        Plot stacked area chart showing ecosystem growth with top N apps.

        Args:
            output_file: Output filename
            top_n: Number of top validators to show individually (others grouped as "Other")

        Returns:
            Output filename
        """
        # Get top N apps by total rewards
        top_apps = self.analyzer.get_top_validators_by_rewards(limit=top_n)
        top_provider_ids = [p_id for p_id, _ in top_apps]

        # Get all rounds
        all_rounds = set()
        for stats in self.analyzer.get_all_stats().values():
            all_rounds.update(stats.rewards_by_round.keys())
        rounds = sorted(all_rounds)

        # Build data matrix
        data_matrix = []
        labels = []

        for provider_id in top_provider_ids:
            stats = self.analyzer.get_validator_stats(provider_id)
            rewards_series = [stats.rewards_by_round.get(r, 0) for r in rounds]
            data_matrix.append(rewards_series)
            labels.append(self._format_validator_id(provider_id, 30))

        # Add "Other" category for remaining apps
        other_series = [0] * len(rounds)
        for provider_id, stats in self.analyzer.get_all_stats().items():
            if provider_id not in top_provider_ids:
                for i, r in enumerate(rounds):
                    other_series[i] += stats.rewards_by_round.get(r, 0)

        if sum(other_series) > 0:
            data_matrix.append(other_series)
            labels.append(f'Other ({len(self.analyzer.get_all_stats()) - top_n} apps)')

        # Create stacked area chart
        fig, ax = plt.subplots(figsize=(16, 9))

        colors = plt.cm.Spectral(np.linspace(0, 1, len(data_matrix)))
        ax.stackplot(rounds, *data_matrix, labels=labels, colors=colors, alpha=0.8)

        ax.set_xlabel('Mining Round', fontsize=12, fontweight='bold')
        ax.set_ylabel('Total Rewards (CC)', fontsize=12, fontweight='bold')
        ax.set_title('Validator Rewards Ecosystem Overview',
                    fontsize=14, fontweight='bold', pad=20)

        # Legend outside plot
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9, framealpha=0.9)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        return output_file

    def plot_rewards_heatmap(
        self,
        output_file: str = 'rewards_heatmap.png',
        top_n: int = 20
    ) -> str:
        """
        Plot heatmap of rewards by validator and round.

        Args:
            output_file: Output filename
            top_n: Number of top validators to include

        Returns:
            Output filename
        """
        # Get top N apps
        top_apps = self.analyzer.get_top_validators_by_rewards(limit=top_n)

        # Get all rounds
        all_rounds = set()
        for _, stats in top_apps:
            all_rounds.update(stats.rewards_by_round.keys())
        rounds = sorted(all_rounds)

        # Build data matrix
        data_matrix = []
        app_labels = []

        for provider_id, stats in top_apps:
            rewards_series = [stats.rewards_by_round.get(r, 0) for r in rounds]
            data_matrix.append(rewards_series)
            app_labels.append(self._format_validator_id(provider_id, 35))

        # Create heatmap
        fig, ax = plt.subplots(figsize=(max(12, len(rounds) * 0.3), max(8, top_n * 0.4)))

        im = ax.imshow(data_matrix, cmap='YlOrRd', aspect='auto', interpolation='nearest')

        # Set ticks
        ax.set_xticks(np.arange(len(rounds)))
        ax.set_yticks(np.arange(len(app_labels)))
        ax.set_xticklabels(rounds, fontsize=8)
        ax.set_yticklabels(app_labels, fontsize=8)

        # Rotate round labels
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Rewards (CC)', rotation=270, labelpad=20, fontsize=10)

        ax.set_title('Validator Rewards Heatmap by Round',
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Mining Round', fontsize=11, fontweight='bold')
        ax.set_ylabel('Featured App', fontsize=11, fontweight='bold')

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        return output_file

    def plot_reward_distribution(
        self,
        output_file: str = 'reward_distribution.png'
    ) -> str:
        """
        Plot distribution of rewards across all apps (pie chart and histogram).

        Args:
            output_file: Output filename

        Returns:
            Output filename
        """
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

        # Get top 10 for pie chart
        top_apps = self.analyzer.get_top_validators_by_rewards(limit=10)

        # Pie chart data
        pie_labels = []
        pie_values = []
        other_value = 0

        for provider_id, stats in top_apps:
            pie_labels.append(self._format_validator_id(provider_id, 25))
            pie_values.append(stats.total_rewards)

        # Add "Other" category
        all_stats = self.analyzer.get_all_stats()
        top_ids = [p_id for p_id, _ in top_apps]
        for provider_id, stats in all_stats.items():
            if provider_id not in top_ids:
                other_value += stats.total_rewards

        if other_value > 0:
            pie_labels.append(f'Other ({len(all_stats) - len(top_apps)} apps)')
            pie_values.append(other_value)

        # Pie chart
        colors = plt.cm.Set3(np.linspace(0, 1, len(pie_labels)))
        wedges, texts, autotexts = ax1.pie(pie_values, labels=pie_labels, autopct='%1.1f%%',
                                            colors=colors, startangle=90)
        for autotext in autotexts:
            autotext.set_color('black')
            autotext.set_fontsize(9)
            autotext.set_fontweight('bold')

        ax1.set_title('Rewards Distribution by App', fontsize=12, fontweight='bold', pad=15)

        # Histogram
        all_rewards = [stats.total_rewards for stats in all_stats.values()]
        ax2.hist(all_rewards, bins=30, color='skyblue', edgecolor='black', alpha=0.7)
        ax2.set_xlabel('Total Rewards (CC)', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Number of Apps', fontsize=11, fontweight='bold')
        ax2.set_title('Distribution of Total Rewards Across All Apps',
                     fontsize=12, fontweight='bold', pad=15)
        ax2.grid(axis='y', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        return output_file

    def generate_report(
        self,
        output_dir: str = 'featured_app_rewards_report',
        top_apps_limit: int = 10
    ) -> Dict[str, str]:
        """
        Generate visualization report with all charts.

        Args:
            output_dir: Output directory for report files
            top_apps_limit: Number of top validators to include in analysis

        Returns:
            Dictionary mapping chart types to output filenames
        """
        import os
        os.makedirs(output_dir, exist_ok=True)

        output_files = {}

        print("Generating visualization report...")

        # 1. Top apps comparison (by rewards)
        print("  - Generating top validators by rewards chart...")
        output_files['top_apps_rewards'] = self.plot_top_apps_comparison(
            limit=top_apps_limit,
            output_file=os.path.join(output_dir, 'top_apps_rewards.png'),
            by_metric='rewards'
        )

        # 2. Top apps comparison (by activity)
        print("  - Generating top validators by activity chart...")
        output_files['top_apps_activity'] = self.plot_top_apps_comparison(
            limit=top_apps_limit,
            output_file=os.path.join(output_dir, 'top_apps_activity.png'),
            by_metric='activity'
        )

        # 3. Ecosystem overview
        print("  - Generating ecosystem overview chart...")
        output_files['ecosystem_overview'] = self.plot_ecosystem_overview(
            output_file=os.path.join(output_dir, 'ecosystem_overview.png'),
            top_n=15
        )

        # 4. Rewards heatmap
        print("  - Generating rewards heatmap...")
        output_files['rewards_heatmap'] = self.plot_rewards_heatmap(
            output_file=os.path.join(output_dir, 'rewards_heatmap.png'),
            top_n=20
        )

        # 5. Reward distribution
        print("  - Generating reward distribution chart...")
        output_files['reward_distribution'] = self.plot_reward_distribution(
            output_file=os.path.join(output_dir, 'reward_distribution.png')
        )

        # 6. Timeline comparison of top validators
        print("  - Generating timeline comparison (per round)...")
        top_apps = self.analyzer.get_top_validators_by_rewards(limit=min(10, top_apps_limit))
        top_ids = [p_id for p_id, _ in top_apps]

        output_files['timeline_per_round'] = self.plot_app_comparison_timeline(
            provider_ids=top_ids,
            output_file=os.path.join(output_dir, 'timeline_per_round.png'),
            cumulative=False
        )

        # 7. Timeline comparison (cumulative)
        print("  - Generating timeline comparison (cumulative)...")
        output_files['timeline_cumulative'] = self.plot_app_comparison_timeline(
            provider_ids=top_ids,
            output_file=os.path.join(output_dir, 'timeline_cumulative.png'),
            cumulative=True
        )

        # 8. Individual progress charts for top validators
        print(f"  - Generating individual progress charts for top {top_apps_limit} apps...")
        for i, (provider_id, _) in enumerate(top_apps[:top_apps_limit], 1):
            safe_name = provider_id.replace(':', '_').replace('/', '_')[:50]
            output_file = os.path.join(output_dir, f'app_{i:02d}_{safe_name}_progress.png')
            output_files[f'app_{i}_progress'] = self.plot_app_progress(
                validator_party_id=provider_id,
                output_file=output_file,
                show_coupons=True
            )

        print(f"\nReport generated successfully in: {output_dir}/")
        print(f"Total charts created: {len(output_files)}")

        return output_files

    def _format_validator_id(self, provider_id: str, max_length: int = 60) -> str:
        """Format provider ID for display."""
        if len(provider_id) <= max_length:
            return provider_id
        return provider_id[:max_length-3] + "..."
