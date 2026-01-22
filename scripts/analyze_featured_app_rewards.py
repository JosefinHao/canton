#!/usr/bin/env python3
"""
Featured App Rewards Analysis Script

This script analyzes featured app rewards from the Canton ledger using the
round-party-totals API endpoint.

About Featured App Rewards (from Canton Coin Whitepaper):
    - Featured apps can mint up to 100x more Canton Coin than fees burned by users
    - Featured apps receive $1 additional activity weight per Canton Coin transaction
    - Unfeatured apps can only mint up to 80% (0.8x) of fees back
    - Actual rewards depend on:
      * Minting curve allocation for each round
      * Competition from other apps in the same round
      * Minting caps (cap_fa=100.0 for featured, cap_ua=0.6 for unfeatured)

    Reference: https://www.canton.network/hubfs/Canton%20Network%20Files/Documents%20
               (whitepapers,%20etc...)/Canton%20Coin_%20A%20Canton-Network-native%20
               payment%20application.pdf

Usage:
    python analyze_featured_app_rewards.py [options]

Options:
    --url URL                Base URL for the Splice Scan API
                            (default: https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/)
    --start-round N         Starting round number (default: 1)
    --end-round N           Ending round number (default: auto-detect)
    --max-rounds N          Maximum number of rounds to fetch (default: 500)
    --output-dir DIR        Output directory for reports (default: featured_app_rewards_report)
    --top-apps N            Number of top apps to analyze (default: 10)
    --no-visualizations     Skip generating visualizations
    --export-csv            Export raw data and stats to CSV files
    --verbose              Enable verbose logging

Example:
    # Analysis with default settings
    python analyze_featured_app_rewards.py

    # Analysis of first 100 rounds
    python analyze_featured_app_rewards.py --max-rounds 100 --no-visualizations

    # Analysis with CSV export
    python analyze_featured_app_rewards.py --export-csv --output-dir my_report

    # Analyze specific round range
    python analyze_featured_app_rewards.py --start-round 100 --end-round 200
"""

import argparse
import sys
import os
import logging
from datetime import datetime

from src.canton_scan_client import SpliceScanClient
from src.featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer
from src.featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def main():
    """Main analysis function."""
    parser = argparse.ArgumentParser(
        description='Analyze featured app rewards from Canton ledger',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--url',
        default='https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/',
        help='Base URL for Splice Scan API'
    )
    parser.add_argument(
        '--start-round',
        type=int,
        default=1,
        help='Starting round number (default: 1)'
    )
    parser.add_argument(
        '--end-round',
        type=int,
        default=None,
        help='Ending round number (default: auto-detect)'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=500,
        help='Maximum number of rounds to fetch (default: 500)'
    )
    parser.add_argument(
        '--output-dir',
        default='featured_app_rewards_report',
        help='Output directory for reports (default: featured_app_rewards_report)'
    )
    parser.add_argument(
        '--top-apps',
        type=int,
        default=10,
        help='Number of top apps to analyze in detail (default: 10)'
    )
    parser.add_argument(
        '--no-visualizations',
        action='store_true',
        help='Skip generating visualizations'
    )
    parser.add_argument(
        '--export-csv',
        action='store_true',
        help='Export raw data and stats to CSV files'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Print header
    print("=" * 80)
    print("FEATURED APP REWARDS ANALYSIS")
    print("=" * 80)
    print()
    print("About Featured App Rewards:")
    print("  - Featured apps can mint up to 100x more Canton Coin than fees burned")
    print("  - Featured apps get $1 additional activity weight per CC transaction")
    print("  - Unfeatured apps can only mint up to 80% (0.8x) of fees back")
    print("  - Rewards depend on minting curve, round allocation, and competition")
    print("  - See Canton Coin whitepaper for full details")
    print()
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API URL: {args.url}")
    print(f"Start Round: {args.start_round}")
    print(f"End Round: {args.end_round if args.end_round else 'auto-detect'}")
    print(f"Max Rounds: {args.max_rounds}")
    print(f"Output Directory: {args.output_dir}")
    print(f"Top Apps: {args.top_apps}")
    print()

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Step 1: Initialize client
    print("Step 1/5: Initializing Splice Scan API client...")
    try:
        client = SpliceScanClient(base_url=args.url)
        print("✓ Client initialized successfully\n")
    except Exception as e:
        print(f"✗ Error initializing client: {e}")
        return 1

    # Step 2: Fetch and process rewards data
    print("Step 2/5: Fetching and processing featured app rewards...")
    print(f"(Fetching rounds {args.start_round} to {args.end_round if args.end_round else 'auto-detect'})\n")

    try:
        analyzer = FeaturedAppRewardsAnalyzer(client)
        summary = analyzer.fetch_and_process_rewards(
            start_round=args.start_round,
            end_round=args.end_round,
            max_rounds=args.max_rounds
        )

        print("\n✓ Data fetched and processed successfully")
        print(f"  - Entries fetched: {summary['entries_fetched']:,}")
        print(f"  - Batches fetched: {summary['batches_fetched']}")
        print(f"  - Rewards found: {summary['rewards_found']:,}")
        print(f"  - Unique apps: {summary['unique_apps']}")
        print()

        if summary['rewards_found'] == 0:
            print("⚠ No featured app rewards found in the fetched data.")
            print("This could mean:")
            print("  - The ledger doesn't have any featured app rewards yet")
            print("  - You need to fetch more rounds (try increasing --max-rounds)")
            print("  - Try adjusting --start-round and --end-round")
            return 1

    except Exception as e:
        print(f"✗ Error fetching/processing data: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Step 3: Generate summary report
    print("Step 3/5: Generating summary report...")
    try:
        report = analyzer.generate_summary_report()

        # Print to console
        print(report)

        # Save to file
        report_file = os.path.join(args.output_dir, 'summary_report.txt')
        with open(report_file, 'w') as f:
            f.write(report)

        print(f"\n✓ Summary report saved to: {report_file}\n")
    except Exception as e:
        print(f"✗ Error generating summary report: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()

    # Step 4: Export CSV files
    if args.export_csv:
        print("Step 4/5: Exporting data to CSV files...")
        try:
            # Export raw rewards data
            rewards_csv = os.path.join(args.output_dir, 'rewards_data.csv')
            analyzer.export_to_csv(rewards_csv)
            print(f"✓ Rewards data exported to: {rewards_csv}")

            # Export statistics
            stats_csv = os.path.join(args.output_dir, 'app_statistics.csv')
            analyzer.export_stats_to_csv(stats_csv)
            print(f"✓ Statistics exported to: {stats_csv}\n")
        except Exception as e:
            print(f"✗ Error exporting CSV files: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
    else:
        print("Step 4/5: Skipping CSV export (use --export-csv to enable)\n")

    # Step 5: Generate visualizations
    if not args.no_visualizations:
        print("Step 5/5: Generating visualizations...")
        print("(This may take a few minutes)\n")

        try:
            visualizer = FeaturedAppRewardsVisualizer(analyzer)
            output_files = visualizer.generate_report(
                output_dir=args.output_dir,
                top_apps_limit=args.top_apps
            )

            print(f"\n✓ Generated {len(output_files)} visualization charts")
            print("\nGenerated files:")
            for chart_type, filename in sorted(output_files.items()):
                print(f"  - {chart_type}: {filename}")

        except Exception as e:
            print(f"✗ Error generating visualizations: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
    else:
        print("Step 5/5: Skipping visualizations (--no-visualizations specified)\n")

    # Final summary
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print(f"\nAll outputs saved to: {args.output_dir}/")
    print("\nFiles generated:")
    print("  - summary_report.txt        : Text summary of findings")

    if args.export_csv:
        print("  - rewards_data.csv          : Raw reward coupon data")
        print("  - app_statistics.csv        : Aggregated statistics per app")

    if not args.no_visualizations:
        print("  - top_apps_rewards.png      : Top apps by total rewards")
        print("  - top_apps_activity.png     : Top apps by rounds active")
        print("  - ecosystem_overview.png    : Stacked area chart of ecosystem")
        print("  - rewards_heatmap.png       : Heatmap of rewards by app/round")
        print("  - reward_distribution.png   : Distribution analysis")
        print("  - timeline_per_round.png    : Timeline comparison (per round)")
        print("  - timeline_cumulative.png   : Timeline comparison (cumulative)")
        print(f"  - app_XX_*_progress.png     : Individual progress (top {args.top_apps})")

    print("\n" + "=" * 80)
    print("UNDERSTANDING THE REWARDS")
    print("=" * 80)
    print()
    print("How to interpret the rewards data:")
    print()
    print("1. Featured vs Unfeatured Apps:")
    print("   - Featured apps: Can mint up to 100x fees burned (cap_fa = 100.0)")
    print("   - Unfeatured apps: Can mint up to 0.8x fees burned (cap_ua = 0.6)")
    print()
    print("2. Activity Weight Bonus:")
    print("   - Featured apps get $1 additional weight per Canton Coin transaction")
    print("   - This bonus increases their share of the minting pool")
    print()
    print("3. Actual vs Potential Rewards:")
    print("   - Potential = activity weight × cap (up to 100x for featured apps)")
    print("   - Actual = proportional share of round's application minting pool")
    print("   - Depends on: minting curve, round allocation, competition from other apps")
    print()
    print("4. Minting Curve Over Time:")
    print("   - Years 0-0.5: 15% to apps, 80% to SVs")
    print("   - Years 0.5-1.5: 40% to apps, 48% to SVs")
    print("   - Years 1.5-5: 62% to apps, 20% to SVs")
    print("   - Years 5-10: 69% to apps, 10% to SVs")
    print("   - Years 10+: 75% to apps, 5% to SVs")
    print()
    print("See Canton Coin whitepaper for full details on the reward mechanism.")
    print()
    print("=" * 80)
    print()

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
