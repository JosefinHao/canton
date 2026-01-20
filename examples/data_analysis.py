"""
Data Analysis Examples for Splice Network On-Chain Data

This script demonstrates how to analyze on-chain data retrieved from
the Splice Network Scan API using pandas and visualization libraries.
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import Counter, defaultdict

# Add parent directory to path to import the client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canton_scan_client import SpliceScanClient

try:
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns
    ANALYSIS_AVAILABLE = True
except ImportError:
    ANALYSIS_AVAILABLE = False
    print("Warning: pandas, matplotlib, or seaborn not installed.")
    print("Install with: pip install pandas matplotlib seaborn")


class SpliceDataAnalyzer:
    """Analyzer for Splice Network on-chain data."""

    def __init__(self, client: SpliceScanClient):
        """
        Initialize the analyzer.

        Args:
            client: Initialized Splice Scan API client
        """
        self.client = client

    def analyze_update_volume(
        self,
        max_pages: int = 10,
        page_size: int = 100
    ) -> pd.DataFrame:
        """
        Analyze update (transaction) volume over time.

        Args:
            max_pages: Maximum number of pages to fetch
            page_size: Number of updates per page

        Returns:
            DataFrame with update volume analysis
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Pandas required for analysis")

        print(f"Fetching updates (max {max_pages} pages)...")

        all_updates = []
        after_migration_id = None
        after_record_time = None

        for page in range(max_pages):
            try:
                result = self.client.get_updates(
                    after_migration_id=after_migration_id,
                    after_record_time=after_record_time,
                    page_size=page_size
                )

                # Try both 'transactions' and 'updates' keys for backward compatibility
                updates = result.get('transactions', result.get('updates', []))
                if not updates:
                    break

                all_updates.extend(updates)

                # Get cursor for next page
                if 'after' in result:
                    after_migration_id = result['after'].get('after_migration_id')
                    after_record_time = result['after'].get('after_record_time')
                else:
                    break

                print(f"  Fetched page {page + 1}: {len(updates)} updates")

            except Exception as e:
                print(f"  Error fetching page {page + 1}: {e}")
                break

        if not all_updates:
            print("No updates found")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(all_updates)

        # Parse timestamps
        df['timestamp'] = pd.to_datetime(df['record_time'])
        df['date'] = df['timestamp'].dt.date
        df['hour'] = df['timestamp'].dt.floor('h')

        # Calculate volume by hour
        volume_df = df.groupby('hour').agg({
            'migration_id': 'count'
        }).rename(columns={'migration_id': 'update_count'})

        return volume_df

    def analyze_mining_rounds(self) -> Dict[str, Any]:
        """
        Analyze mining round statistics.

        Returns:
            Dictionary with mining round analysis
        """
        print("Fetching mining round data...")

        try:
            # Get open and issuing rounds
            open_issuing = self.client.get_open_and_issuing_mining_rounds()

            # Validate response type
            if not isinstance(open_issuing, dict):
                print(f"Warning: Expected dict, got {type(open_issuing)}: {open_issuing}")
                return {}

            open_rounds = open_issuing.get('open_mining_rounds', [])
            # Handle both list and dict formats (API may return dict with contract IDs as keys)
            if isinstance(open_rounds, dict):
                # Extract values from dict format
                open_rounds = list(open_rounds.values())
            elif not isinstance(open_rounds, list):
                print(f"Warning: open_mining_rounds is not a list or dict, got {type(open_rounds)}")
                open_rounds = []

            # Try both possible key names for issuing rounds
            issuing_rounds = open_issuing.get('issuing_mining_rounds', open_issuing.get('issuing_rounds', []))
            # Handle both list and dict formats
            if isinstance(issuing_rounds, dict):
                # Extract values from dict format
                issuing_rounds = list(issuing_rounds.values())
            elif not isinstance(issuing_rounds, list):
                print(f"Warning: issuing_rounds is not a list or dict, got {type(issuing_rounds)}")
                issuing_rounds = []

            # Get closed rounds
            closed = self.client.get_closed_rounds()

            # Validate response type
            if not isinstance(closed, dict):
                print(f"Warning: Expected dict from get_closed_rounds, got {type(closed)}: {closed}")
                closed_rounds = []
            else:
                # Try both possible key names for closed rounds
                closed_rounds = closed.get('rounds', closed.get('closed_rounds', []))
                # Handle both list and dict formats
                if isinstance(closed_rounds, dict):
                    # Extract values from dict format
                    closed_rounds = list(closed_rounds.values())
                elif not isinstance(closed_rounds, list):
                    print(f"Warning: closed_rounds is not a list or dict, got {type(closed_rounds)}")
                    closed_rounds = []

            analysis = {
                'open_rounds_count': len(open_rounds),
                'issuing_rounds_count': len(issuing_rounds),
                'closed_rounds_count': len(closed_rounds),
                'total_active_rounds': len(open_rounds) + len(issuing_rounds) + len(closed_rounds)
            }

            # Extract round numbers
            if open_rounds:
                round_numbers = []
                for r in open_rounds:
                    # Validate each round is a dict before accessing fields
                    if isinstance(r, dict):
                        # Handle both direct payload format and nested contract format
                        if 'contract' in r:
                            # Nested format: payload is under 'contract'
                            contract = r.get('contract', {})
                            if isinstance(contract, dict):
                                payload = contract.get('payload', {})
                            else:
                                payload = {}
                        else:
                            # Direct format: payload is at top level
                            payload = r.get('payload', {})

                        if isinstance(payload, dict):
                            round_info = payload.get('round', {})
                            if isinstance(round_info, dict):
                                number = round_info.get('number', 0)
                                if number:
                                    round_numbers.append(number)
                    else:
                        print(f"Warning: open_round item is not a dict: {type(r)}")

                if round_numbers:
                    analysis['latest_open_round'] = max(round_numbers)

            return analysis

        except Exception as e:
            print(f"Error analyzing mining rounds: {e}")
            return {}

    def analyze_ans_entries(self) -> pd.DataFrame:
        """
        Analyze ANS (Amulet Name Service) entry statistics.

        Returns:
            DataFrame with ANS entry analysis
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Pandas required for analysis")

        print("Fetching ANS entries...")

        all_entries = []
        max_pages = 10

        for page in range(max_pages):
            try:
                result = self.client.get_ans_entries(page_size=100)
                entries = result.get('entries', [])

                if not entries:
                    break

                all_entries.extend(entries)
                print(f"  Fetched page {page + 1}: {len(entries)} entries")

                # Check if there are more pages
                if len(entries) < 100:
                    break

            except Exception as e:
                print(f"  Error fetching ANS entries: {e}")
                break

        if not all_entries:
            print("No ANS entries found")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(all_entries)

        # Parse expiration times if available
        if 'expires_at' in df.columns:
            df['expires_at_dt'] = pd.to_datetime(df['expires_at'], errors='coerce')
            # Use UTC timezone to match the timezone-aware datetime from API
            now = pd.Timestamp.now(tz='UTC')
            # If expires_at_dt is timezone-naive, localize it to UTC
            if df['expires_at_dt'].dt.tz is None:
                df['expires_at_dt'] = df['expires_at_dt'].dt.tz_localize('UTC')
            df['days_until_expiry'] = (df['expires_at_dt'] - now).dt.days

        return df

    def analyze_validator_activity(self) -> Dict[str, Any]:
        """
        Analyze validator activity and licensing.

        Returns:
            Dictionary with validator analysis
        """
        print("Fetching validator data...")

        try:
            # Get validator licenses
            validators = self.client.get_validator_licenses(limit=1000)
            # Try both possible key names for backward compatibility
            validator_list = validators.get('validator_licenses', validators.get('validators', []))

            analysis = {
                'total_validators': len(validator_list),
                'sponsored_count': sum(1 for v in validator_list if v.get('sponsored')),
                'unsponsored_count': sum(1 for v in validator_list if not v.get('sponsored'))
            }

            return analysis

        except Exception as e:
            print(f"Error analyzing validators: {e}")
            return {}

    def analyze_holdings_summary(
        self,
        migration_id: int,
        record_time: str
    ) -> Dict[str, Any]:
        """
        Analyze amulet holdings at a specific point in time.

        Args:
            migration_id: Migration ID for the snapshot
            record_time: Record time for the snapshot

        Returns:
            Dictionary with holdings analysis
        """
        print(f"Fetching holdings summary at migration_id={migration_id}, record_time={record_time}...")

        try:
            holdings = self.client.get_holdings_summary(
                migration_id=migration_id,
                record_time=record_time
            )

            # Extract summary statistics
            analysis = {
                'total_holders': holdings.get('total_holders', 0),
                'total_amulets': holdings.get('total_amulets', 0),
                'total_locked_amulets': holdings.get('total_locked_amulets', 0),
                'total_unlocked_amulets': holdings.get('total_unlocked_amulets', 0)
            }

            return analysis

        except Exception as e:
            print(f"Error analyzing holdings: {e}")
            return {}

    def create_update_volume_plot(
        self,
        volume_df: pd.DataFrame,
        output_file: str = 'update_volume.png'
    ):
        """
        Create a plot of update volume over time.

        Args:
            volume_df: DataFrame from analyze_update_volume
            output_file: Output file path for the plot
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Matplotlib required for plotting")

        if volume_df.empty:
            print("No data to plot")
            return

        plt.figure(figsize=(12, 6))
        plt.plot(volume_df.index, volume_df['update_count'], marker='o')
        plt.xlabel('Time')
        plt.ylabel('Update Count')
        plt.title('Splice Network Update Volume Over Time')
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_file, dpi=300)
        print(f"Plot saved to {output_file}")
        plt.close()

    def create_ans_analysis_plot(
        self,
        ans_df: pd.DataFrame,
        output_file: str = 'ans_analysis.png'
    ):
        """
        Create visualizations of ANS entry data.

        Args:
            ans_df: DataFrame from analyze_ans_entries
            output_file: Output file path for the plot
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Matplotlib required for plotting")

        if ans_df.empty or 'days_until_expiry' not in ans_df.columns:
            print("No ANS data available for plotting")
            return

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Plot 1: Distribution of days until expiry
        ans_df['days_until_expiry'].hist(bins=30, ax=ax1)
        ax1.set_xlabel('Days Until Expiry')
        ax1.set_ylabel('Number of Entries')
        ax1.set_title('ANS Entry Expiration Distribution')
        ax1.grid(True, alpha=0.3)

        # Plot 2: Expiry timeline
        expiry_counts = ans_df.groupby(ans_df['expires_at_dt'].dt.date).size()
        ax2.plot(expiry_counts.index, expiry_counts.values, marker='o')
        ax2.set_xlabel('Expiration Date')
        ax2.set_ylabel('Number of Entries Expiring')
        ax2.set_title('ANS Entry Expiration Timeline')
        ax2.tick_params(axis='x', rotation=45)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300)
        print(f"Plot saved to {output_file}")
        plt.close()

    def generate_summary_report(self) -> str:
        """
        Generate a comprehensive summary report of the Splice Network.

        Returns:
            Formatted summary report as string
        """
        report = []
        report.append("=" * 70)
        report.append("SPLICE NETWORK ON-CHAIN DATA SUMMARY REPORT")
        report.append("=" * 70)
        report.append(f"Generated at: {datetime.utcnow().isoformat()}")
        report.append("")

        try:
            # DSO Information
            dso = self.client.get_dso()
            report.append("DSO INFORMATION")
            report.append("-" * 70)
            for key, value in dso.items():
                if not isinstance(value, dict):  # Skip nested objects
                    report.append(f"  {key}: {value}")
            report.append("")

        except Exception as e:
            report.append(f"Error fetching DSO info: {e}")
            report.append("")

        try:
            # Network Names
            names = self.client.get_splice_instance_names()
            report.append("NETWORK CONFIGURATION")
            report.append("-" * 70)
            for key, value in names.items():
                report.append(f"  {key}: {value}")
            report.append("")

        except Exception as e:
            report.append(f"Error fetching network names: {e}")
            report.append("")

        try:
            # Mining Rounds
            mining_stats = self.analyze_mining_rounds()
            report.append("MINING ROUNDS")
            report.append("-" * 70)
            for key, value in mining_stats.items():
                report.append(f"  {key}: {value}")
            report.append("")

        except Exception as e:
            report.append(f"Error analyzing mining rounds: {e}")
            report.append("")

        try:
            # Validator Activity
            validator_stats = self.analyze_validator_activity()
            report.append("VALIDATOR STATISTICS")
            report.append("-" * 70)
            for key, value in validator_stats.items():
                report.append(f"  {key}: {value}")
            report.append("")

        except Exception as e:
            report.append(f"Error analyzing validators: {e}")
            report.append("")

        report.append("=" * 70)

        return "\n".join(report)


def main():
    """Run data analysis examples."""

    BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"

    print("Initializing Splice Scan API client...")
    client = SpliceScanClient(base_url=BASE_URL)

    # Initialize analyzer
    analyzer = SpliceDataAnalyzer(client)

    # Generate summary report
    print("\n" + "=" * 70)
    print("Generating Summary Report...")
    print("=" * 70)
    report = analyzer.generate_summary_report()
    print(report)

    # Save report to file
    with open('splice_summary_report.txt', 'w') as f:
        f.write(report)
    print("\nReport saved to splice_summary_report.txt")

    if not ANALYSIS_AVAILABLE:
        print("\nSkipping advanced analytics (pandas/matplotlib not installed)")
        client.close()
        return

    # Analyze update volume
    print("\n" + "=" * 70)
    print("Analyzing Update Volume...")
    print("=" * 70)
    try:
        volume_df = analyzer.analyze_update_volume(max_pages=5, page_size=100)
        if not volume_df.empty:
            print("\nUpdate Volume Statistics:")
            print(volume_df.describe())

            # Create plot
            analyzer.create_update_volume_plot(volume_df)

            # Save to CSV
            volume_df.to_csv('update_volume.csv')
            print("Data saved to update_volume.csv")
        else:
            print("No update data available")

    except Exception as e:
        print(f"Error: {e}")

    # Analyze ANS entries
    print("\n" + "=" * 70)
    print("Analyzing ANS Entries...")
    print("=" * 70)
    try:
        ans_df = analyzer.analyze_ans_entries()
        if not ans_df.empty:
            print(f"\nTotal ANS Entries: {len(ans_df)}")

            if 'name' in ans_df.columns:
                print(f"Sample ANS Names:")
                for name in ans_df['name'].head(10):
                    print(f"  - {name}")

            # Create plots if expiry data available
            if 'days_until_expiry' in ans_df.columns:
                analyzer.create_ans_analysis_plot(ans_df)

            # Save to CSV
            ans_df.to_csv('ans_entries.csv', index=False)
            print("\nData saved to ans_entries.csv")
        else:
            print("No ANS entry data available")

    except Exception as e:
        print(f"Error: {e}")

    # Analyze mining rounds
    print("\n" + "=" * 70)
    print("Analyzing Mining Rounds...")
    print("=" * 70)
    try:
        mining_stats = analyzer.analyze_mining_rounds()
        if mining_stats:
            print("\nMining Round Statistics:")
            for key, value in mining_stats.items():
                print(f"  {key}: {value}")
        else:
            print("No mining round data available")

    except Exception as e:
        print(f"Error: {e}")

    # Analyze validators
    print("\n" + "=" * 70)
    print("Analyzing Validators...")
    print("=" * 70)
    try:
        validator_stats = analyzer.analyze_validator_activity()
        if validator_stats:
            print("\nValidator Statistics:")
            for key, value in validator_stats.items():
                print(f"  {key}: {value}")
        else:
            print("No validator data available")

    except Exception as e:
        print(f"Error: {e}")

    # Close the client
    client.close()

    print("\n" + "=" * 70)
    print("Analysis completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
