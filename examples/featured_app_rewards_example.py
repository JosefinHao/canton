#!/usr/bin/env python3
"""
Featured App Rewards Analysis - Example Usage

This example demonstrates how to use the Featured App Rewards Analyzer
programmatically for custom analysis workflows.
"""

import sys
sys.path.append('..')

from src.canton_scan_client import SpliceScanClient
from src.featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer
from featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer


def example_basic_analysis():
    """Example 1: Basic analysis workflow."""
    print("Example 1: Basic Analysis")
    print("-" * 80)

    # Initialize client
    client = SpliceScanClient(
        base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
    )

    # Create analyzer
    analyzer = FeaturedAppRewardsAnalyzer(client)

    # Fetch and process data (limit to 10 pages for quick example)
    summary = analyzer.fetch_and_process_rewards(max_pages=10, page_size=100)

    print(f"Fetched {summary['updates_fetched']} updates")
    print(f"Found {summary['rewards_found']} reward coupons")
    print(f"Unique apps: {summary['unique_apps']}")
    print()

    # Get top apps
    top_apps = analyzer.get_top_apps_by_rewards(limit=5)

    print("Top 5 Apps by Rewards:")
    for i, (provider_id, stats) in enumerate(top_apps, 1):
        print(f"{i}. {provider_id[:60]}")
        print(f"   Total Rewards: {stats.total_rewards:,.2f} CC")
        print(f"   Coupons: {stats.total_coupons:,}")
        print()


def example_specific_app_analysis():
    """Example 2: Analyze a specific app."""
    print("\nExample 2: Specific App Analysis")
    print("-" * 80)

    client = SpliceScanClient(
        base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
    )
    analyzer = FeaturedAppRewardsAnalyzer(client)

    # Fetch data
    analyzer.fetch_and_process_rewards(max_pages=10, page_size=100)

    # Get a specific app (use the first one we find)
    all_stats = analyzer.get_all_stats()
    if not all_stats:
        print("No apps found in data")
        return

    provider_id = list(all_stats.keys())[0]
    stats = analyzer.get_provider_stats(provider_id)

    print(f"Analysis for: {provider_id}")
    print(f"\nTotal Rewards: {stats.total_rewards:,.2f} CC")
    print(f"Total Coupons: {stats.total_coupons:,}")
    print(f"First Round: {stats.first_round}")
    print(f"Last Round: {stats.last_round}")
    print(f"Rounds Active: {stats.rounds_active}")
    print(f"Average per Coupon: {stats.avg_reward_per_coupon:.2f} CC")
    print()

    # Show rewards by round
    print("Rewards by Round:")
    for round_num in sorted(stats.rewards_by_round.keys())[:10]:  # First 10 rounds
        amount = stats.rewards_by_round[round_num]
        coupons = stats.coupons_by_round[round_num]
        print(f"  Round {round_num}: {amount:,.2f} CC ({coupons} coupons)")


def example_generate_visualizations():
    """Example 3: Generate specific visualizations."""
    print("\nExample 3: Generate Visualizations")
    print("-" * 80)

    client = SpliceScanClient(
        base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
    )
    analyzer = FeaturedAppRewardsAnalyzer(client)

    # Fetch data
    print("Fetching data...")
    analyzer.fetch_and_process_rewards(max_pages=10, page_size=100)

    if len(analyzer.get_all_stats()) == 0:
        print("No apps found in data")
        return

    # Create visualizer
    visualizer = FeaturedAppRewardsVisualizer(analyzer)

    # Generate specific charts
    print("\nGenerating visualizations...")

    # Top apps comparison
    output = visualizer.plot_top_apps_comparison(
        limit=10,
        output_file='example_top_apps.png',
        by_metric='rewards'
    )
    print(f"✓ Top apps chart: {output}")

    # Ecosystem overview
    output = visualizer.plot_ecosystem_overview(
        output_file='example_ecosystem.png',
        top_n=10
    )
    print(f"✓ Ecosystem overview: {output}")

    # Individual app progress (for top app)
    top_apps = analyzer.get_top_apps_by_rewards(limit=1)
    if top_apps:
        provider_id = top_apps[0][0]
        output = visualizer.plot_app_progress(
            provider_party_id=provider_id,
            output_file='example_app_progress.png'
        )
        print(f"✓ App progress chart: {output}")


def example_export_data():
    """Example 4: Export data to CSV."""
    print("\nExample 4: Export Data to CSV")
    print("-" * 80)

    client = SpliceScanClient(
        base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
    )
    analyzer = FeaturedAppRewardsAnalyzer(client)

    # Fetch data
    print("Fetching data...")
    analyzer.fetch_and_process_rewards(max_pages=10, page_size=100)

    # Export to CSV
    print("\nExporting data...")
    analyzer.export_to_csv('example_rewards_data.csv')
    analyzer.export_stats_to_csv('example_app_stats.csv')

    print("✓ Data exported successfully")


def example_custom_analysis():
    """Example 5: Custom analysis workflow."""
    print("\nExample 5: Custom Analysis")
    print("-" * 80)

    client = SpliceScanClient(
        base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
    )
    analyzer = FeaturedAppRewardsAnalyzer(client)

    # Fetch data
    analyzer.fetch_and_process_rewards(max_pages=10, page_size=100)

    all_stats = analyzer.get_all_stats()
    if not all_stats:
        print("No apps found in data")
        return

    # Custom analysis: Find apps with highest average reward per coupon
    apps_by_avg = sorted(
        all_stats.items(),
        key=lambda x: x[1].avg_reward_per_coupon,
        reverse=True
    )

    print("Top 5 Apps by Average Reward per Coupon:")
    for i, (provider_id, stats) in enumerate(apps_by_avg[:5], 1):
        print(f"{i}. {provider_id[:60]}")
        print(f"   Avg per Coupon: {stats.avg_reward_per_coupon:.2f} CC")
        print(f"   Total Coupons: {stats.total_coupons:,}")
        print(f"   Total Rewards: {stats.total_rewards:,.2f} CC")
        print()

    # Custom analysis: Find most consistent apps (active in most rounds)
    most_consistent = analyzer.get_top_apps_by_activity(limit=5)

    print("\nMost Consistent Apps (Active in Most Rounds):")
    for i, (provider_id, stats) in enumerate(most_consistent, 1):
        consistency_pct = (stats.rounds_active / (stats.last_round - stats.first_round + 1)) * 100
        print(f"{i}. {provider_id[:60]}")
        print(f"   Rounds Active: {stats.rounds_active}/{stats.last_round - stats.first_round + 1}")
        print(f"   Consistency: {consistency_pct:.1f}%")
        print()


def example_timeline_analysis():
    """Example 6: Timeline analysis."""
    print("\nExample 6: Timeline Analysis")
    print("-" * 80)

    client = SpliceScanClient(
        base_url='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/'
    )
    analyzer = FeaturedAppRewardsAnalyzer(client)

    # Fetch data
    analyzer.fetch_and_process_rewards(max_pages=10, page_size=100)

    # Get rewards timeline
    timeline = analyzer.get_rewards_timeline()

    if not timeline:
        print("No timeline data found")
        return

    print("Rewards Timeline Summary:")
    print(f"Total Rounds: {len(timeline)}")

    # Analyze each round
    for round_num in sorted(timeline.keys())[:10]:  # First 10 rounds
        round_data = timeline[round_num]
        total_rewards = sum(round_data.values())
        num_apps = len(round_data)

        print(f"\nRound {round_num}:")
        print(f"  Apps rewarded: {num_apps}")
        print(f"  Total rewards: {total_rewards:,.2f} CC")
        print(f"  Avg per app: {total_rewards/num_apps:.2f} CC")


if __name__ == '__main__':
    # Run all examples
    print("=" * 80)
    print("FEATURED APP REWARDS ANALYSIS - EXAMPLES")
    print("=" * 80)
    print()

    try:
        # Run basic examples
        example_basic_analysis()
        example_specific_app_analysis()
        example_custom_analysis()
        example_timeline_analysis()

        # Optional: Run export and visualization examples
        # (Commented out by default to avoid creating files)

        # example_export_data()
        # example_generate_visualizations()

        print("\n" + "=" * 80)
        print("All examples completed successfully!")
        print("=" * 80)

    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()
