"""
Data Analysis Examples for Canton Network On-Chain Data

This script demonstrates how to analyze on-chain data retrieved from
the Canton Network Scan API using pandas and visualization libraries.

The Scan API is completely PUBLIC - no authentication required!
Just provide the API URL and start analyzing on-chain data immediately.
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import Counter, defaultdict

# Add parent directory to path to import the client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canton_scan_client import CantonScanClient

try:
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns
    ANALYSIS_AVAILABLE = True
except ImportError:
    ANALYSIS_AVAILABLE = False
    print("Warning: pandas, matplotlib, or seaborn not installed.")
    print("Install with: pip install pandas matplotlib seaborn")


class CantonDataAnalyzer:
    """Analyzer for Canton Network on-chain data."""

    def __init__(self, client: CantonScanClient):
        """
        Initialize the analyzer.

        Args:
            client: Initialized Canton Scan API client
        """
        self.client = client

    def analyze_transaction_volume(
        self,
        days: int = 7,
        granularity: str = 'hour'
    ) -> pd.DataFrame:
        """
        Analyze transaction volume over time.

        Args:
            days: Number of days to analyze
            granularity: Time granularity ('hour', 'day')

        Returns:
            DataFrame with transaction volume analysis
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Pandas required for analysis")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        print(f"Fetching transactions from {start_time} to {end_time}...")

        # Fetch all transactions in the time range
        transactions = self.client.get_all_transactions_paginated(
            batch_size=100,
            start_time=start_time.isoformat() + 'Z',
            end_time=end_time.isoformat() + 'Z'
        )

        if not transactions:
            print("No transactions found in the specified time range")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(transactions)

        # Parse timestamps
        df['timestamp'] = pd.to_datetime(df['effective_at'])
        df['date'] = df['timestamp'].dt.date

        if granularity == 'hour':
            df['time_bucket'] = df['timestamp'].dt.floor('H')
        else:
            df['time_bucket'] = df['timestamp'].dt.floor('D')

        # Calculate volume
        volume_df = df.groupby('time_bucket').agg({
            'transaction_id': 'count'
        }).rename(columns={'transaction_id': 'transaction_count'})

        return volume_df

    def analyze_contract_lifecycle(
        self,
        template_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze contract creation and archival patterns.

        Args:
            template_id: Optionally filter by template ID

        Returns:
            Dictionary with lifecycle analysis
        """
        print("Fetching events...")

        # Fetch creation and archival events
        created_events = self.client.get_events(
            event_type='created',
            limit=1000
        )

        archived_events = self.client.get_events(
            event_type='archived',
            limit=1000
        )

        created_count = len(created_events.get('events', []))
        archived_count = len(archived_events.get('events', []))

        # Get active contracts
        active_contracts = self.client.get_active_contracts(
            template_id=template_id,
            limit=1000
        )

        active_count = len(active_contracts.get('contracts', []))

        analysis = {
            'created_contracts': created_count,
            'archived_contracts': archived_count,
            'active_contracts': active_count,
            'net_change': created_count - archived_count,
            'archival_rate': archived_count / created_count if created_count > 0 else 0
        }

        return analysis

    def analyze_party_activity(self) -> pd.DataFrame:
        """
        Analyze activity levels by party.

        Returns:
            DataFrame with party activity analysis
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Pandas required for analysis")

        print("Fetching party data...")

        # Get all parties
        parties_response = self.client.get_parties()
        parties = parties_response.get('parties', [])

        party_stats = []

        for party in parties:
            party_id = party.get('party_id')
            print(f"Analyzing party: {party_id}")

            try:
                # Get party statistics
                stats = self.client.get_party_stats(party_id)

                party_stats.append({
                    'party_id': party_id,
                    'display_name': party.get('display_name', party_id),
                    **stats
                })
            except Exception as e:
                print(f"  Error fetching stats for {party_id}: {e}")
                party_stats.append({
                    'party_id': party_id,
                    'display_name': party.get('display_name', party_id),
                    'error': str(e)
                })

        return pd.DataFrame(party_stats)

    def analyze_template_usage(self) -> pd.DataFrame:
        """
        Analyze usage patterns of different contract templates.

        Returns:
            DataFrame with template usage analysis
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Pandas required for analysis")

        print("Fetching template data...")

        # Get all templates
        templates_response = self.client.get_templates()
        templates = templates_response.get('templates', [])

        template_stats = []

        for template in templates:
            template_id = template.get('template_id')
            print(f"Analyzing template: {template_id}")

            try:
                # Get active contracts for this template
                contracts = self.client.get_active_contracts(
                    template_id=template_id,
                    limit=10000
                )

                # Get template statistics if available
                try:
                    stats = self.client.get_template_stats(template_id)
                except:
                    stats = {}

                template_stats.append({
                    'template_id': template_id,
                    'module_name': template.get('module_name', 'N/A'),
                    'entity_name': template.get('entity_name', 'N/A'),
                    'active_contracts': len(contracts.get('contracts', [])),
                    **stats
                })
            except Exception as e:
                print(f"  Error analyzing {template_id}: {e}")

        df = pd.DataFrame(template_stats)

        if not df.empty and 'active_contracts' in df.columns:
            df = df.sort_values('active_contracts', ascending=False)

        return df

    def create_transaction_volume_plot(
        self,
        volume_df: pd.DataFrame,
        output_file: str = 'transaction_volume.png'
    ):
        """
        Create a plot of transaction volume over time.

        Args:
            volume_df: DataFrame from analyze_transaction_volume
            output_file: Output file path for the plot
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Matplotlib required for plotting")

        plt.figure(figsize=(12, 6))
        plt.plot(volume_df.index, volume_df['transaction_count'], marker='o')
        plt.xlabel('Time')
        plt.ylabel('Transaction Count')
        plt.title('Transaction Volume Over Time')
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_file, dpi=300)
        print(f"Plot saved to {output_file}")
        plt.close()

    def create_template_usage_plot(
        self,
        template_df: pd.DataFrame,
        output_file: str = 'template_usage.png'
    ):
        """
        Create a bar plot of template usage.

        Args:
            template_df: DataFrame from analyze_template_usage
            output_file: Output file path for the plot
        """
        if not ANALYSIS_AVAILABLE:
            raise ImportError("Matplotlib required for plotting")

        if template_df.empty or 'active_contracts' not in template_df.columns:
            print("No data available for plotting")
            return

        # Take top 10 templates
        top_templates = template_df.head(10)

        plt.figure(figsize=(12, 6))
        plt.bar(range(len(top_templates)), top_templates['active_contracts'])
        plt.xlabel('Template')
        plt.ylabel('Active Contracts')
        plt.title('Top 10 Templates by Active Contracts')
        plt.xticks(
            range(len(top_templates)),
            top_templates['entity_name'].tolist(),
            rotation=45,
            ha='right'
        )
        plt.tight_layout()
        plt.savefig(output_file, dpi=300)
        print(f"Plot saved to {output_file}")
        plt.close()

    def generate_summary_report(self) -> str:
        """
        Generate a comprehensive summary report of the ledger.

        Returns:
            Formatted summary report as string
        """
        report = []
        report.append("=" * 70)
        report.append("CANTON NETWORK ON-CHAIN DATA SUMMARY REPORT")
        report.append("=" * 70)
        report.append(f"Generated at: {datetime.utcnow().isoformat()}")
        report.append("")

        try:
            # Ledger Identity
            identity = self.client.get_ledger_identity()
            report.append("LEDGER IDENTITY")
            report.append("-" * 70)
            for key, value in identity.items():
                report.append(f"  {key}: {value}")
            report.append("")

        except Exception as e:
            report.append(f"Error fetching ledger identity: {e}")
            report.append("")

        try:
            # Ledger Statistics
            stats = self.client.get_ledger_stats()
            report.append("LEDGER STATISTICS")
            report.append("-" * 70)
            for key, value in stats.items():
                report.append(f"  {key}: {value}")
            report.append("")

        except Exception as e:
            report.append(f"Error fetching ledger stats: {e}")
            report.append("")

        try:
            # Contract Lifecycle
            lifecycle = self.analyze_contract_lifecycle()
            report.append("CONTRACT LIFECYCLE")
            report.append("-" * 70)
            report.append(f"  Total Created: {lifecycle['created_contracts']}")
            report.append(f"  Total Archived: {lifecycle['archived_contracts']}")
            report.append(f"  Currently Active: {lifecycle['active_contracts']}")
            report.append(f"  Net Change: {lifecycle['net_change']}")
            report.append(f"  Archival Rate: {lifecycle['archival_rate']:.2%}")
            report.append("")

        except Exception as e:
            report.append(f"Error analyzing contract lifecycle: {e}")
            report.append("")

        report.append("=" * 70)

        return "\n".join(report)


def main():
    """Run data analysis examples."""

    # Configuration - Replace with your actual Scan API URL
    # No authentication required - the API is completely public!
    BASE_URL = "https://scan.canton.network/api/v1"

    # Initialize client - no authentication needed!
    print("Initializing Canton Scan API client (no auth required!)...")
    client = CantonScanClient(base_url=BASE_URL)

    # Initialize analyzer
    analyzer = CantonDataAnalyzer(client)

    # Generate summary report
    print("\n" + "=" * 70)
    print("Generating Summary Report...")
    print("=" * 70)
    report = analyzer.generate_summary_report()
    print(report)

    # Save report to file
    with open('canton_summary_report.txt', 'w') as f:
        f.write(report)
    print("\nReport saved to canton_summary_report.txt")

    if not ANALYSIS_AVAILABLE:
        print("\nSkipping advanced analytics (pandas/matplotlib not installed)")
        return

    # Analyze transaction volume
    print("\n" + "=" * 70)
    print("Analyzing Transaction Volume...")
    print("=" * 70)
    try:
        volume_df = analyzer.analyze_transaction_volume(days=7, granularity='hour')
        if not volume_df.empty:
            print("\nTransaction Volume Statistics:")
            print(volume_df.describe())

            # Create plot
            analyzer.create_transaction_volume_plot(volume_df)

            # Save to CSV
            volume_df.to_csv('transaction_volume.csv')
            print("Data saved to transaction_volume.csv")
        else:
            print("No transaction data available")

    except Exception as e:
        print(f"Error: {e}")

    # Analyze template usage
    print("\n" + "=" * 70)
    print("Analyzing Template Usage...")
    print("=" * 70)
    try:
        template_df = analyzer.analyze_template_usage()
        if not template_df.empty:
            print("\nTop Templates by Active Contracts:")
            print(template_df.head(10).to_string(index=False))

            # Create plot
            analyzer.create_template_usage_plot(template_df)

            # Save to CSV
            template_df.to_csv('template_usage.csv', index=False)
            print("\nData saved to template_usage.csv")
        else:
            print("No template data available")

    except Exception as e:
        print(f"Error: {e}")

    # Analyze party activity
    print("\n" + "=" * 70)
    print("Analyzing Party Activity...")
    print("=" * 70)
    try:
        party_df = analyzer.analyze_party_activity()
        if not party_df.empty:
            print("\nParty Activity Summary:")
            print(party_df.to_string(index=False))

            # Save to CSV
            party_df.to_csv('party_activity.csv', index=False)
            print("\nData saved to party_activity.csv")
        else:
            print("No party data available")

    except Exception as e:
        print(f"Error: {e}")

    # Close the client
    client.close()

    print("\n" + "=" * 70)
    print("Analysis completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
