#!/usr/bin/env python3
"""
Featured App Rewards Analysis Script

This script performs comprehensive analysis of featured app rewards from the Canton
ledger by processing AppRewardCoupon contract creation events.

Usage:
    python analyze_featured_app_rewards.py [options]

Options:
    --url URL                Base URL for the Splice Scan API
                            (default: https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/)
    --max-pages N           Maximum number of pages to fetch (default: 100)
    --page-size N           Updates per page (default: 100)
    --output-dir DIR        Output directory for reports (default: featured_app_rewards_report)
    --top-apps N            Number of top apps to analyze in detail (default: 10)
    --no-visualizations     Skip generating visualizations
    --export-csv            Export raw data and stats to CSV files
    --verbose              Enable verbose logging

Example:
    # Full analysis with default settings
    python analyze_featured_app_rewards.py

    # Quick analysis of first 10 pages
    python analyze_featured_app_rewards.py --max-pages 10 --no-visualizations

    # Full analysis with CSV export
    python analyze_featured_app_rewards.py --export-csv --output-dir my_report
"""

import argparse
import sys
import os
import logging
from datetime import datetime

from canton_scan_client import SpliceScanClient
from featured_app_rewards_analyzer import FeaturedAppRewardsAnalyzer
from featured_app_rewards_visualizer import FeaturedAppRewardsVisualizer


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
        '--max-pages',
        type=int,
        default=100,
        help='Maximum number of pages to fetch (default: 100)'
    )
    parser.add_argument(
        '--page-size',
        type=int,
        default=100,
        help='Updates per page (default: 100)'
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
    print(f"\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API URL: {args.url}")
    print(f"Max Pages: {args.max_pages}")
    print(f"Page Size: {args.page_size}")
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
    print("Step 2/5: Fetching and processing AppRewardCoupon events...")
    print(f"(This may take several minutes for {args.max_pages} pages)\n")

    try:
        analyzer = FeaturedAppRewardsAnalyzer(client)
        summary = analyzer.fetch_and_process_rewards(
            max_pages=args.max_pages,
            page_size=args.page_size
        )

        print("\n✓ Data fetched and processed successfully")
        print(f"  - Updates fetched: {summary['updates_fetched']:,}")
        print(f"  - Pages fetched: {summary['pages_fetched']}")
        print(f"  - Rewards found: {summary['rewards_found']:,}")
        print(f"  - Unique apps: {summary['unique_apps']}")
        print()

        if summary['rewards_found'] == 0:
            print("⚠ No AppRewardCoupon events found in the fetched data.")
            print("This could mean:")
            print("  - The ledger doesn't have any featured app rewards yet")
            print("  - You need to fetch more pages (try increasing --max-pages)")
            print("  - The API endpoint may require authentication")
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
            output_files = visualizer.generate_comprehensive_report(
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
