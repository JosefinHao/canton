"""
Advanced Insights & Visualization Module for Splice Network

This module provides senior-level data science insights with comprehensive
visualizations to answer critical business and operational questions.

Key Insight Areas:
1. Network Health & Growth Trajectories
2. User Behavior & Engagement Patterns
3. Economic Health & Wealth Distribution
4. Decentralization & Security Metrics
5. Governance Effectiveness
6. Anomaly Detection & Risk Assessment
7. Predictive Analytics
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter, defaultdict
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from canton_scan_client import SpliceScanClient
from splice_analytics import (
    TransactionAnalyzer,
    MiningRoundAnalyzer,
    ANSAnalyzer,
    ValidatorAnalyzer,
    EconomicAnalyzer,
    GovernanceAnalyzer,
    calculate_gini_coefficient
)

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import seaborn as sns
    PLOTTING_AVAILABLE = True

    # Set style for professional visualizations
    sns.set_style("whitegrid")
    plt.rcParams['figure.figsize'] = (14, 8)
    plt.rcParams['font.size'] = 10
except ImportError:
    PLOTTING_AVAILABLE = False


# ========== Network Health & Growth Insights ==========

class NetworkGrowthInsights:
    """Extract growth and health insights from network data."""

    def __init__(self, client: SpliceScanClient):
        self.client = client
        self.tx_analyzer = TransactionAnalyzer(client)

    def analyze_growth_trajectory(
        self,
        max_pages: int = 20
    ) -> Dict[str, Any]:
        """
        Analyze network growth trajectory to predict sustainability.

        INSIGHTS:
        - Is growth accelerating or decelerating?
        - What's the projected user base in 30/90/180 days?
        - Are we on a sustainable path?

        Returns:
            Dictionary with growth insights
        """
        if not PANDAS_AVAILABLE:
            return {'error': 'Pandas required'}

        # Fetch updates
        updates = self.tx_analyzer.fetch_updates_batch(max_pages=max_pages)

        if not updates:
            return {'error': 'No data'}

        # Convert to DataFrame
        timestamps = []
        for update in updates:
            try:
                ts = pd.to_datetime(update['record_time'])
                timestamps.append(ts)
            except:
                continue

        df = pd.DataFrame({'timestamp': timestamps})
        df['count'] = 1
        df = df.set_index('timestamp').sort_index()

        # Daily aggregation
        daily = df.resample('D').sum()
        daily['cumulative'] = daily['count'].cumsum()
        daily['ma_7'] = daily['count'].rolling(window=7, min_periods=1).mean()

        # Calculate growth rates
        daily['growth_rate'] = daily['count'].pct_change()

        # Trend analysis
        x = np.arange(len(daily))
        y = daily['count'].values

        if len(x) > 1:
            # Linear fit
            z = np.polyfit(x, y, 1)
            trend_slope = z[0]

            # Is growth accelerating or decelerating?
            recent_avg = daily['count'][-7:].mean() if len(daily) >= 7 else 0
            older_avg = daily['count'][-14:-7].mean() if len(daily) >= 14 else recent_avg

            acceleration = ((recent_avg - older_avg) / older_avg * 100) if older_avg > 0 else 0
        else:
            trend_slope = 0
            acceleration = 0

        # Projections (simple linear extrapolation)
        current_rate = daily['count'][-7:].mean() if len(daily) >= 7 else 0
        projection_30d = current_rate * 30
        projection_90d = current_rate * 90
        projection_180d = current_rate * 180

        return {
            'total_days_analyzed': len(daily),
            'total_updates': int(daily['count'].sum()),
            'current_daily_avg': current_rate,
            'trend_slope': trend_slope,
            'growth_acceleration_pct': acceleration,
            'is_accelerating': acceleration > 5,
            'is_decelerating': acceleration < -5,
            'projection_30d': projection_30d,
            'projection_90d': projection_90d,
            'projection_180d': projection_180d,
            'sustainability_score': min((current_rate / 100) * 100, 100),  # Score out of 100
            'daily_data': daily.to_dict() if PANDAS_AVAILABLE else {},
            'interpretation': self._interpret_growth(acceleration, current_rate)
        }

    def _interpret_growth(self, acceleration: float, daily_rate: float) -> str:
        """Generate human-readable interpretation."""
        if daily_rate < 10:
            return " CONCERN: Low activity levels."
        elif acceleration > 10:
            return " EXCELLENT: Strong accelerating growth."
        elif acceleration > 0:
            return " GOOD: Positive growth trend."
        elif acceleration > -10:
            return " WATCH: Growth slowing."
        else:
            return " CRITICAL: Declining activity."

    def detect_viral_events(
        self,
        updates: List[Dict[str, Any]],
        spike_threshold: float = 3.0
    ) -> List[Dict[str, Any]]:
        """
        Detect viral events or anomalous activity spikes.

        Identifies traffic spikes and provides severity classification.

        Args:
            updates: List of update records
            spike_threshold: Multiplier above average to consider viral

        Returns:
            List of viral event periods with context
        """
        spikes = self.tx_analyzer.detect_activity_spikes(
            updates,
            window_minutes=60,
            spike_threshold=spike_threshold
        )

        # Enrich with context
        for spike in spikes:
            if isinstance(spike, dict) and 'multiplier' in spike:
                spike['severity'] = (
                    'CRITICAL' if spike['multiplier'] > 5 else
                    'HIGH' if spike['multiplier'] > 3 else
                    'MODERATE'
                )
                spike['likely_cause'] = self._infer_spike_cause(spike['multiplier'])

        return spikes

    def _infer_spike_cause(self, multiplier: float) -> str:
        """Infer likely cause of spike."""
        if multiplier > 10:
            return "Possible attack, system issue, or major viral event"
        elif multiplier > 5:
            return "Major feature launch, marketing campaign, or significant news"
        elif multiplier > 3:
            return "Increased organic activity or minor campaign"
        else:
            return "Normal variance"


# ========== User Behavior & Engagement Insights ==========

class UserBehaviorInsights:
    """Extract insights about user behavior patterns."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def analyze_temporal_patterns(
        self,
        updates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze when users are most active.

        INSIGHTS:
        - Peak activity hours (optimize infrastructure)
        - Weekend vs weekday patterns
        - Geographic distribution hints (timezone analysis)

        Returns:
            Dictionary with temporal pattern insights
        """
        if not PANDAS_AVAILABLE:
            return {'error': 'Pandas required'}

        timestamps = []
        for update in updates:
            try:
                ts = pd.to_datetime(update['record_time'])
                timestamps.append(ts)
            except:
                continue

        if not timestamps:
            return {'error': 'No valid timestamps'}

        df = pd.DataFrame({'timestamp': timestamps})

        # Extract temporal features
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek  # 0=Monday
        df['is_weekend'] = df['day_of_week'].isin([5, 6])

        # Hourly distribution
        hourly_counts = df['hour'].value_counts().sort_index()
        peak_hour = hourly_counts.idxmax()

        # Day of week distribution
        dow_counts = df['day_of_week'].value_counts().sort_index()
        peak_day = dow_counts.idxmax()

        # Weekend vs weekday
        weekend_count = df[df['is_weekend']].shape[0]
        weekday_count = df[~df['is_weekend']].shape[0]

        weekend_pct = (weekend_count / len(df) * 100) if len(df) > 0 else 0

        return {
            'total_updates_analyzed': len(df),
            'peak_hour_utc': int(peak_hour),
            'peak_hour_activity_pct': (hourly_counts[peak_hour] / len(df) * 100),
            'peak_day': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][peak_day],
            'weekend_activity_pct': weekend_pct,
            'is_weekend_heavy': weekend_pct > 40,
            'hourly_distribution': hourly_counts.to_dict(),
            'dow_distribution': dow_counts.to_dict(),
            'infrastructure_insight': self._infrastructure_recommendation(int(peak_hour), hourly_counts),
            'user_pattern_insight': self._user_pattern_interpretation(weekend_pct)
        }

    def _infrastructure_recommendation(self, peak_hour: int, hourly_counts) -> str:
        """Describe infrastructure patterns."""
        total = hourly_counts.sum()
        peak_pct = (hourly_counts[peak_hour] / total * 100) if total > 0 else 0

        if peak_pct > 20:
            return f"High concentration at {peak_hour}:00 UTC ({peak_pct:.1f}%)."
        else:
            return "Activity is well-distributed across hours."

    def _user_pattern_interpretation(self, weekend_pct: float) -> str:
        """Interpret user behavior patterns."""
        if weekend_pct > 50:
            return "Casual/consumer user base (weekend heavy)."
        elif weekend_pct < 30:
            return "Professional/developer user base (weekday heavy)."
        else:
            return "Balanced user base across weekdays and weekends."

    def analyze_power_users(
        self,
        updates: List[Dict[str, Any]],
        top_n: int = 20
    ) -> Dict[str, Any]:
        """
        Identify power users and their behavior patterns.

        Analyzes user activity concentration and distribution.

        Args:
            updates: List of update records
            top_n: Number of top users to identify

        Returns:
            Dictionary with power user insights
        """
        # Try to extract party/user identifiers from updates
        user_activity = Counter()

        for update in updates:
            # Try multiple fields that might contain user identifiers
            update_data = update.get('update', {})

            # Look for party IDs in various places
            parties = []
            if 'party' in update_data:
                parties.append(update_data['party'])
            if 'parties' in update_data:
                parties.extend(update_data.get('parties', []))

            for party in parties:
                if party:
                    user_activity[str(party)] += 1

        if not user_activity:
            return {
                'note': 'Unable to extract user identifiers from updates',
                'total_updates': len(updates)
            }

        # Calculate concentration
        top_users = user_activity.most_common(top_n)
        total_activity = sum(user_activity.values())
        top_users_activity = sum(count for _, count in top_users)

        concentration_ratio = (top_users_activity / total_activity * 100) if total_activity > 0 else 0

        # Gini coefficient for user activity distribution
        activity_values = list(user_activity.values())
        gini = calculate_gini_coefficient(activity_values)

        return {
            'total_unique_users': len(user_activity),
            'total_activity': total_activity,
            'top_users_count': len(top_users),
            'top_users_activity_pct': concentration_ratio,
            'activity_gini_coefficient': gini,
            'is_highly_concentrated': concentration_ratio > 50,
            'top_users': [{'user': user, 'activity_count': count, 'pct_of_total': (count/total_activity*100)}
                          for user, count in top_users[:10]],
            'risk_assessment': self._assess_concentration_risk(concentration_ratio, gini),
            'diversity_score': (1 - gini) * 100  # 0-100, higher is more diverse
        }

    def _assess_concentration_risk(self, concentration_pct: float, gini: float) -> str:
        """Assess risk of user concentration."""
        if concentration_pct > 70:
            return "HIGH RISK: Network depends heavily on few users."
        elif concentration_pct > 50:
            return "MODERATE RISK: Some concentration detected."
        elif gini > 0.7:
            return "WATCH: Activity inequality high."
        else:
            return "LOW RISK: User diversity is high."


# ========== Economic Health Insights ==========

class EconomicHealthInsights:
    """Extract insights about economic health and sustainability."""

    def __init__(self, client: SpliceScanClient):
        self.client = client
        self.economic_analyzer = EconomicAnalyzer(client)

    def analyze_wealth_distribution(
        self,
        holdings_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze wealth distribution and inequality.

        INSIGHTS:
        - Is wealth concentrating dangerously?
        - Income inequality trends
        - Risk of plutocracy

        Args:
            holdings_data: Holdings summary data

        Returns:
            Dictionary with wealth distribution insights
        """
        # Extract holder balances (this would need actual holdings data)
        # For now, provide framework for analysis

        return {
            'note': 'Wealth distribution analysis framework',
            'metrics_to_track': {
                'gini_coefficient': 'Measure inequality (0=equal, 1=unequal)',
                'top_1_pct_holdings': 'Percentage of wealth controlled by top 1%',
                'top_10_pct_holdings': 'Percentage of wealth controlled by top 10%',
                'median_vs_mean_ratio': 'Ratio < 1 indicates right skew',
                'herfindahl_index': 'Market concentration index'
            },
            'target_ranges': {
                'gini_coefficient': '<0.5, 0.5-0.7, >0.7',
                'top_10_pct_holdings': '<50%, 50-70%, >70%'
            }
        }

    def analyze_token_velocity(
        self,
        updates: List[Dict[str, Any]],
        total_supply: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Analyze token velocity to assess economic health.

        INSIGHTS:
        - High velocity = speculation, low utility
        - Low velocity = hoarding, low economic activity
        - Optimal velocity depends on use case

        Args:
            updates: List of update records
            total_supply: Total token supply

        Returns:
            Dictionary with velocity insights
        """
        if total_supply:
            velocity = self.economic_analyzer.estimate_velocity(updates, total_supply)
        else:
            velocity = {'note': 'Total supply needed for velocity calculation'}

        return {
            'velocity_estimate': velocity,
            'interpretation': {
                'very_high_velocity': '>10: Excessive speculation',
                'high_velocity': '5-10: Active usage',
                'healthy_velocity': '2-5: Balanced holding and transacting',
                'low_velocity': '0.5-2: Conservative holding',
                'very_low_velocity': '<0.5: Hoarding pattern'
            }
        }


# ========== Validator Network & Decentralization Insights ==========

class DecentralizationInsights:
    """Extract insights about network decentralization and security."""

    def __init__(self, client: SpliceScanClient):
        self.client = client
        self.validator_analyzer = ValidatorAnalyzer(client)

    def assess_decentralization_risk(
        self,
        validator_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Assess decentralization and security risks.

        INSIGHTS:
        - Is the network at risk of centralization?
        - What's the Nakamoto coefficient?
        - Geographic/entity concentration risks?

        Args:
            validator_data: Validator summary data

        Returns:
            Dictionary with decentralization risk assessment
        """
        total_validators = validator_data.get('total_validators', 0)

        # Calculate decentralization score
        decentral_score = self.validator_analyzer.calculate_decentralization_score(validator_data)

        # Estimate Nakamoto coefficient (simplified - assumes equal stake)
        # Real calculation would need stake distribution
        nakamoto_estimate = total_validators // 3 + 1  # Simplified estimate

        # Risk thresholds
        is_high_risk = total_validators < 10
        is_medium_risk = 10 <= total_validators < 50
        is_low_risk = total_validators >= 50

        return {
            'total_validators': total_validators,
            'decentralization_score': decentral_score.get('decentralization_score', 0),
            'nakamoto_coefficient_estimate': nakamoto_estimate,
            'risk_level': (
                'HIGH' if is_high_risk else
                'MEDIUM' if is_medium_risk else
                'LOW'
            ),
            'security_assessment': self._security_assessment(total_validators, nakamoto_estimate),
            'metrics_to_monitor': {
                'validator_count_trend': 'Growing or shrinking?',
                'validator_churn_rate': 'Are validators leaving?',
                'geographic_distribution': 'Cloud provider concentration?',
                'entity_concentration': 'Are validators independent?'
            }
        }

    def _security_assessment(self, validator_count: int, nakamoto: int) -> str:
        """Assess security based on validator count."""
        if validator_count < 10:
            return f"HIGH RISK: {validator_count} validators. Network vulnerable to collusion. Nakamoto coefficient: {nakamoto}"
        elif validator_count < 50:
            return f"MODERATE RISK: {validator_count} validators. Nakamoto coefficient: {nakamoto}"
        else:
            return f"GOOD: {validator_count} validators. Strong decentralization. Nakamoto coefficient: {nakamoto}"

# ========== Governance Effectiveness Insights ==========

class GovernanceInsights:
    """Extract insights about governance effectiveness."""

    def __init__(self, client: SpliceScanClient):
        self.client = client
        self.gov_analyzer = GovernanceAnalyzer(client)

    def analyze_governance_health(
        self,
        vote_data: Dict[str, Any],
        validator_count: int
    ) -> Dict[str, Any]:
        """
        Analyze governance system health and participation.

        INSIGHTS:
        - Is participation sufficient?
        - Are proposals passing at healthy rates?
        - What do communities want changed?

        Args:
            vote_data: Vote request analysis data
            validator_count: Total validator count

        Returns:
            Dictionary with governance health insights
        """
        participation = self.gov_analyzer.calculate_governance_participation(
            vote_data,
            validator_count
        )

        acceptance_rate = vote_data.get('acceptance_rate', 0)
        total_requests = vote_data.get('total_requests', 0)

        # Health assessment
        participation_healthy = participation.get('votes_per_validator', 0) > 0.1
        acceptance_healthy = 20 < acceptance_rate < 80

        return {
            'participation_metrics': participation,
            'acceptance_rate': acceptance_rate,
            'total_proposals': total_requests,
            'participation_healthy': participation_healthy,
            'acceptance_healthy': acceptance_healthy,
            'overall_health': 'GOOD' if (participation_healthy and acceptance_healthy) else 'NEEDS_IMPROVEMENT',
            'insights': self._governance_insights(acceptance_rate, participation),
            'action_types': vote_data.get('action_types', {}),
            'community_priorities': self._infer_priorities(vote_data.get('action_types', {}))
        }

    def _governance_insights(self, acceptance_rate: float, participation: Dict) -> List[str]:
        """Generate governance insights."""
        insights = []

        if acceptance_rate < 20:
            insights.append("Very low acceptance rate detected.")
        elif acceptance_rate > 80:
            insights.append("Very high acceptance rate detected.")
        else:
            insights.append("Balanced acceptance rate.")

        votes_per_validator = participation.get('votes_per_validator', 0)
        if votes_per_validator < 0.05:
            insights.append("Low participation rate.")
        elif votes_per_validator < 0.2:
            insights.append("Moderate participation rate.")
        else:
            insights.append("High participation rate.")

        return insights

    def _infer_priorities(self, action_types: Dict[str, int]) -> str:
        """Infer community priorities from proposal types."""
        if not action_types:
            return "Insufficient data"

        top_action = max(action_types.items(), key=lambda x: x[1])[0] if action_types else None

        interpretations = {
            'config_change': 'Community focused on protocol parameters',
            'upgrade': 'Focus on technical improvements',
            'validator': 'Focus on validator management',
            'economic': 'Focus on economic policy'
        }

        return interpretations.get(top_action, f"Primary focus: {top_action}")


# ========== Comprehensive Visualization Suite ==========

class InsightVisualizer:
    """Create comprehensive visualizations of network insights."""

    def __init__(self, client: SpliceScanClient):
        self.client = client
        self.growth_insights = NetworkGrowthInsights(client)
        self.behavior_insights = UserBehaviorInsights(client)
        self.economic_insights = EconomicHealthInsights(client)
        self.decentral_insights = DecentralizationInsights(client)
        self.gov_insights = GovernanceInsights(client)

    def create_executive_dashboard(
        self,
        output_file: str = 'splice_executive_dashboard.png'
    ):
        """
        Create a comprehensive executive dashboard with key metrics.

        This is the "one pager" for executives - all critical insights at a glance.
        """
        if not PLOTTING_AVAILABLE:
            print("Plotting libraries required")
            return

        print("Generating Executive Dashboard...")

        # Fetch data
        tx_analyzer = TransactionAnalyzer(self.client)
        updates = tx_analyzer.fetch_updates_batch(max_pages=10)

        # Create figure with subplots
        fig = plt.figure(figsize=(20, 12))
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)

        # 1. Growth Trajectory
        ax1 = fig.add_subplot(gs[0, :2])
        self._plot_growth_trajectory(ax1, updates)

        # 2. Activity Heatmap (hour x day)
        ax2 = fig.add_subplot(gs[0, 2])
        self._plot_activity_heatmap(ax2, updates)

        # 3. Update Type Distribution
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_update_types(ax3, updates)

        # 4. Health Score Gauge
        ax4 = fig.add_subplot(gs[1, 1])
        self._plot_health_score(ax4)

        # 5. Validator Count Trend
        ax5 = fig.add_subplot(gs[1, 2])
        self._plot_validator_trend(ax5)

        # 6. Key Metrics Table
        ax6 = fig.add_subplot(gs[2, :])
        self._plot_key_metrics_table(ax6, updates)

        plt.suptitle('Splice Network - Executive Dashboard', fontsize=20, fontweight='bold', y=0.995)
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Dashboard saved to {output_file}")
        plt.close()

    def _plot_growth_trajectory(self, ax, updates):
        """Plot growth trajectory with trend line."""
        if not updates or not PANDAS_AVAILABLE:
            ax.text(0.5, 0.5, 'Insufficient data', ha='center', va='center')
            ax.set_title('Growth Trajectory')
            return

        timestamps = []
        for update in updates:
            try:
                ts = pd.to_datetime(update['record_time'])
                timestamps.append(ts)
            except:
                continue

        if not timestamps:
            ax.text(0.5, 0.5, 'No valid timestamps', ha='center', va='center')
            return

        df = pd.DataFrame({'timestamp': timestamps})
        df['count'] = 1
        df = df.set_index('timestamp').sort_index()
        daily = df.resample('D').sum()

        # Plot actual data
        ax.plot(daily.index, daily['count'], marker='o', linewidth=2, markersize=4, label='Daily Updates')

        # Add 7-day moving average
        ma_7 = daily['count'].rolling(window=7, min_periods=1).mean()
        ax.plot(daily.index, ma_7, linewidth=3, alpha=0.7, label='7-day MA', color='orange')

        # Trend line
        x_numeric = np.arange(len(daily))
        z = np.polyfit(x_numeric, daily['count'].values, 1)
        p = np.poly1d(z)
        ax.plot(daily.index, p(x_numeric), "--", alpha=0.8, linewidth=2, label=f'Trend (slope: {z[0]:.2f})', color='red')

        ax.set_title('Network Activity Growth Trajectory', fontsize=14, fontweight='bold')
        ax.set_xlabel('Date')
        ax.set_ylabel('Daily Updates')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Add growth annotation
        if len(daily) > 7:
            recent_avg = daily['count'][-7:].mean()
            older_avg = daily['count'][-14:-7].mean() if len(daily) >= 14 else recent_avg
            growth_pct = ((recent_avg - older_avg) / older_avg * 100) if older_avg > 0 else 0

            color = 'green' if growth_pct > 0 else 'red'
            ax.text(0.02, 0.98, f'7d Growth: {growth_pct:+.1f}%',
                   transform=ax.transAxes, fontsize=12, fontweight='bold',
                   verticalalignment='top', color=color,
                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    def _plot_activity_heatmap(self, ax, updates):
        """Plot hourly activity heatmap."""
        if not PANDAS_AVAILABLE or not updates:
            ax.text(0.5, 0.5, 'Insufficient data', ha='center', va='center')
            ax.set_title('Activity Heatmap')
            return

        behavior = self.behavior_insights.analyze_temporal_patterns(updates)

        if 'error' in behavior:
            ax.text(0.5, 0.5, 'Data unavailable', ha='center', va='center')
            return

        # Create hourly distribution bar chart
        hourly = behavior.get('hourly_distribution', {})
        hours = sorted(hourly.keys())
        counts = [hourly[h] for h in hours]

        bars = ax.bar(hours, counts, color='steelblue', alpha=0.7)

        # Highlight peak hour
        peak_hour = behavior.get('peak_hour_utc', 0)
        if peak_hour in hours:
            peak_idx = hours.index(peak_hour)
            bars[peak_idx].set_color('orange')

        ax.set_title(f'Activity by Hour (Peak: {peak_hour}:00 UTC)', fontsize=12, fontweight='bold')
        ax.set_xlabel('Hour (UTC)')
        ax.set_ylabel('Count')
        ax.set_xticks(range(0, 24, 4))
        ax.grid(True, alpha=0.3, axis='y')

    def _plot_update_types(self, ax, updates):
        """Plot update type distribution."""
        tx_analyzer = TransactionAnalyzer(self.client)
        type_analysis = tx_analyzer.analyze_update_types(updates)

        if 'error' in type_analysis or not type_analysis.get('type_counts'):
            ax.text(0.5, 0.5, 'Insufficient data', ha='center', va='center')
            ax.set_title('Update Types')
            return

        types = list(type_analysis['type_counts'].keys())[:5]  # Top 5
        counts = [type_analysis['type_counts'][t] for t in types]

        # Truncate long type names
        types_short = [t[:15] + '...' if len(t) > 15 else t for t in types]

        ax.pie(counts, labels=types_short, autopct='%1.1f%%', startangle=90)
        ax.set_title('Top Update Types', fontsize=12, fontweight='bold')

    def _plot_health_score(self, ax):
        """Plot health score as a gauge."""
        from splice_analytics import NetworkHealthAnalyzer

        try:
            health_analyzer = NetworkHealthAnalyzer(self.client)
            health = health_analyzer.generate_health_score()
            score = health.get('overall_health_score', 0)
        except:
            score = 0

        # Create gauge chart
        categories = ['Poor\n(0-40)', 'Fair\n(40-60)', 'Good\n(60-80)', 'Excellent\n(80-100)']
        colors = ['#ff4444', '#ffaa00', '#88cc00', '#00cc44']

        # Determine color based on score
        if score < 40:
            score_color = colors[0]
        elif score < 60:
            score_color = colors[1]
        elif score < 80:
            score_color = colors[2]
        else:
            score_color = colors[3]

        ax.text(0.5, 0.6, f'{score:.0f}', ha='center', va='center', fontsize=60, fontweight='bold', color=score_color)
        ax.text(0.5, 0.35, 'Health Score', ha='center', va='center', fontsize=16, fontweight='bold')
        ax.text(0.5, 0.2, f'({health.get("health_rating", "Unknown")})', ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.set_title('Network Health', fontsize=12, fontweight='bold')

    def _plot_validator_trend(self, ax):
        """Plot validator count."""
        validator_analyzer = ValidatorAnalyzer(self.client)

        try:
            validators = validator_analyzer.get_validator_summary()
            total = validators.get('total_validators', 0)
            sponsored = validators.get('sponsored_count', 0)
            unsponsored = validators.get('unsponsored_count', 0)
        except:
            total = 0
            sponsored = 0
            unsponsored = 0

        # Bar chart
        categories = ['Total', 'Sponsored', 'Unsponsored']
        values = [total, sponsored, unsponsored]
        colors_list = ['steelblue', 'green', 'orange']

        bars = ax.bar(categories, values, color=colors_list, alpha=0.7)

        # Add value labels on bars
        for bar, value in zip(bars, values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(value)}',
                   ha='center', va='bottom', fontweight='bold')

        ax.set_title('Validator Network', fontsize=12, fontweight='bold')
        ax.set_ylabel('Count')
        ax.grid(True, alpha=0.3, axis='y')

    def _plot_key_metrics_table(self, ax, updates):
        """Plot key metrics as a table."""
        # Gather key metrics
        metrics = []

        # Transaction metrics
        if updates:
            tx_analyzer = TransactionAnalyzer(self.client)
            tx_rate = tx_analyzer.calculate_transaction_rate(updates)
            metrics.append(['Updates/Day', f"{tx_rate.get('updates_per_day', 0):.1f}"])
            metrics.append(['Updates/Hour', f"{tx_rate.get('updates_per_hour', 0):.1f}"])

        # Growth
        try:
            growth = self.growth_insights.analyze_growth_trajectory(max_pages=5)
            metrics.append(['30d Projection', f"{growth.get('projection_30d', 0):.0f}"])
        except:
            pass

        # Add spacing
        while len(metrics) < 3:
            metrics.append(['', ''])

        # Create table
        table = ax.table(cellText=metrics, colLabels=['Metric', 'Value'],
                        cellLoc='left', loc='center',
                        colWidths=[0.7, 0.3])
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 2.5)

        # Style header
        for i in range(2):
            table[(0, i)].set_facecolor('#4472C4')
            table[(0, i)].set_text_props(weight='bold', color='white')

        ax.axis('off')
        ax.set_title('Key Metrics Summary', fontsize=12, fontweight='bold', pad=20)


# ========== Main Demo ==========

def main():
    """Demonstrate advanced insights and visualizations."""

    BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"

    print("=" * 80)
    print("SPLICE NETWORK - DATA ANALYTICS INSIGHTS")
    print("=" * 80)
    print()

    client = SpliceScanClient(base_url=BASE_URL)

    # Initialize insight generators
    print(" Initializing insight analyzers...")
    growth_insights = NetworkGrowthInsights(client)
    behavior_insights = UserBehaviorInsights(client)
    visualizer = InsightVisualizer(client)

    # 1. Growth Trajectory Analysis
    print("\n" + "=" * 80)
    print(" GROWTH TRAJECTORY ANALYSIS")
    print("=" * 80)
    try:
        growth = growth_insights.analyze_growth_trajectory(max_pages=10)
        print(f"Days Analyzed: {growth.get('total_days_analyzed', 0)}")
        print(f"Total Updates: {growth.get('total_updates', 0)}")
        print(f"Current Daily Avg: {growth.get('current_daily_avg', 0):.1f}")
        print(f"Growth Acceleration: {growth.get('growth_acceleration_pct', 0):.1f}%")
        print(f"\n{growth.get('interpretation', '')}")
        print(f"\nProjections:")
        print(f"  30 days: {growth.get('projection_30d', 0):.0f} updates")
        print(f"  90 days: {growth.get('projection_90d', 0):.0f} updates")
        print(f"  180 days: {growth.get('projection_180d', 0):.0f} updates")
    except Exception as e:
        print(f"Error: {e}")

    # 2. User Behavior Patterns
    print("\n" + "=" * 80)
    print(" USER BEHAVIOR PATTERNS")
    print("=" * 80)
    try:
        tx_analyzer = TransactionAnalyzer(client)
        updates = tx_analyzer.fetch_updates_batch(max_pages=5)

        temporal = behavior_insights.analyze_temporal_patterns(updates)
        print(f"Peak Hour: {temporal.get('peak_hour_utc', 0)}:00 UTC ({temporal.get('peak_hour_activity_pct', 0):.1f}% of activity)")
        print(f"Peak Day: {temporal.get('peak_day', 'N/A')}")
        print(f"Weekend Activity: {temporal.get('weekend_activity_pct', 0):.1f}%")
        print(f"\n{temporal.get('infrastructure_insight', '')}")
        print(f"{temporal.get('user_pattern_insight', '')}")
    except Exception as e:
        print(f"Error: {e}")

    # 3. Create Executive Dashboard
    print("\n" + "=" * 80)
    print(" GENERATING EXECUTIVE DASHBOARD")
    print("=" * 80)
    try:
        visualizer.create_executive_dashboard('splice_executive_dashboard.png')
    except Exception as e:
        print(f"Error generating dashboard: {e}")

    # Close client
    client.close()

    print("\n" + "=" * 80)
    print(" INSIGHTS ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
