"""
Comprehensive Analytics Module for Splice Network On-Chain Data

This module provides extensive analysis capabilities for Splice Network data,
organized into specialized analyzer classes for different domains.
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter, defaultdict
import statistics

# Add parent directory to path to import the client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from canton_scan_client import SpliceScanClient

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("Warning: pandas not installed. Some analyses will be limited.")

try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False
    print("Warning: matplotlib/seaborn not installed. Plotting disabled.")


# ========== Transaction & Update Analysis ==========

class TransactionAnalyzer:
    """Analyzer for transaction and update data."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def fetch_updates_batch(
        self,
        max_pages: int = 10,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch a batch of updates with pagination.

        Args:
            max_pages: Maximum number of pages to fetch
            page_size: Updates per page

        Returns:
            List of all fetched updates
        """
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

                updates = result.get('updates', [])
                if not updates:
                    break

                all_updates.extend(updates)

                # Get next page cursor
                if 'after' in result:
                    after_migration_id = result['after'].get('after_migration_id')
                    after_record_time = result['after'].get('after_record_time')
                else:
                    break

            except Exception as e:
                print(f"Error fetching page {page + 1}: {e}")
                break

        return all_updates

    def calculate_transaction_rate(
        self,
        updates: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Calculate transaction rate statistics.

        Args:
            updates: List of update records

        Returns:
            Dictionary with rate statistics
        """
        if not updates or len(updates) < 2:
            return {'error': 'Insufficient data'}

        # Parse timestamps
        timestamps = []
        for update in updates:
            try:
                ts = datetime.fromisoformat(update['record_time'].replace('Z', '+00:00'))
                timestamps.append(ts)
            except:
                continue

        if len(timestamps) < 2:
            return {'error': 'Insufficient valid timestamps'}

        timestamps.sort()
        time_span = (timestamps[-1] - timestamps[0]).total_seconds()

        if time_span == 0:
            return {'error': 'Zero time span'}

        return {
            'total_updates': len(updates),
            'time_span_seconds': time_span,
            'time_span_hours': time_span / 3600,
            'time_span_days': time_span / 86400,
            'updates_per_second': len(updates) / time_span,
            'updates_per_minute': (len(updates) / time_span) * 60,
            'updates_per_hour': (len(updates) / time_span) * 3600,
            'updates_per_day': (len(updates) / time_span) * 86400,
            'start_time': timestamps[0].isoformat(),
            'end_time': timestamps[-1].isoformat()
        }

    def analyze_update_types(
        self,
        updates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze the distribution of update types.

        Args:
            updates: List of update records

        Returns:
            Dictionary with update type statistics
        """
        type_counts = Counter()

        for update in updates:
            update_data = update.get('update', {})
            update_type = update_data.get('type', 'unknown')
            type_counts[update_type] += 1

        total = len(updates)
        type_percentages = {
            utype: (count / total * 100) for utype, count in type_counts.items()
        }

        return {
            'total_updates': total,
            'unique_types': len(type_counts),
            'type_counts': dict(type_counts),
            'type_percentages': type_percentages,
            'most_common_type': type_counts.most_common(1)[0] if type_counts else None
        }

    def detect_activity_spikes(
        self,
        updates: List[Dict[str, Any]],
        window_minutes: int = 60,
        spike_threshold: float = 2.0
    ) -> List[Dict[str, Any]]:
        """
        Detect spikes in transaction activity.

        Args:
            updates: List of update records
            window_minutes: Time window for spike detection
            spike_threshold: Multiplier above average to consider a spike

        Returns:
            List of detected spikes with timestamps and counts
        """
        if not PANDAS_AVAILABLE:
            return [{'error': 'Pandas required for spike detection'}]

        # Convert to DataFrame
        timestamps = []
        for update in updates:
            try:
                ts = pd.to_datetime(update['record_time'])
                timestamps.append(ts)
            except:
                continue

        if len(timestamps) < 10:
            return [{'error': 'Insufficient data'}]

        df = pd.DataFrame({'timestamp': timestamps})
        df['count'] = 1

        # Resample to time windows
        df = df.set_index('timestamp')
        windowed = df.resample(f'{window_minutes}min').sum()

        # Calculate statistics
        mean_count = windowed['count'].mean()
        std_count = windowed['count'].std()

        # Detect spikes
        spikes = []
        for timestamp, row in windowed.iterrows():
            if row['count'] > mean_count * spike_threshold:
                spikes.append({
                    'timestamp': timestamp.isoformat(),
                    'count': int(row['count']),
                    'avg_count': mean_count,
                    'multiplier': row['count'] / mean_count if mean_count > 0 else 0
                })

        return spikes

    def calculate_growth_rate(
        self,
        updates: List[Dict[str, Any]],
        period_days: int = 7
    ) -> Dict[str, float]:
        """
        Calculate growth rate over a period.

        Args:
            updates: List of update records
            period_days: Period to calculate growth over

        Returns:
            Dictionary with growth statistics
        """
        if not updates:
            return {'error': 'No data'}

        # Parse timestamps
        timestamps = []
        for update in updates:
            try:
                ts = datetime.fromisoformat(update['record_time'].replace('Z', '+00:00'))
                timestamps.append(ts)
            except:
                continue

        if not timestamps:
            return {'error': 'No valid timestamps'}

        timestamps.sort()

        # Split into periods
        cutoff = timestamps[-1] - timedelta(days=period_days)
        recent = [ts for ts in timestamps if ts > cutoff]
        older = [ts for ts in timestamps if ts <= cutoff]

        if not older:
            return {'error': 'Insufficient historical data'}

        recent_rate = len(recent) / period_days if recent else 0
        older_rate = len(older) / ((timestamps[-1] - timestamps[0]).days - period_days) if older else 0

        growth_rate = ((recent_rate - older_rate) / older_rate * 100) if older_rate > 0 else 0

        return {
            'recent_count': len(recent),
            'older_count': len(older),
            'recent_daily_rate': recent_rate,
            'older_daily_rate': older_rate,
            'growth_rate_percent': growth_rate,
            'period_days': period_days
        }


# ========== Mining Round Analysis ==========

class MiningRoundAnalyzer:
    """Analyzer for mining round data."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def get_all_rounds_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive summary of all mining rounds.

        Returns:
            Dictionary with mining round statistics
        """
        try:
            open_issuing = self.client.get_open_and_issuing_mining_rounds()
            closed = self.client.get_closed_rounds()

            # Validate response types
            if not isinstance(open_issuing, dict):
                open_issuing = {}
            if not isinstance(closed, dict):
                closed = {}

            open_rounds = open_issuing.get('open_mining_rounds', [])
            issuing_rounds = open_issuing.get('issuing_rounds', [])
            closed_rounds = closed.get('closed_rounds', [])

            # Validate that values are lists
            if not isinstance(open_rounds, list):
                open_rounds = []
            if not isinstance(issuing_rounds, list):
                issuing_rounds = []
            if not isinstance(closed_rounds, list):
                closed_rounds = []

            # Extract round numbers
            open_numbers = []
            for r in open_rounds:
                # Validate each round is a dict before accessing fields
                if isinstance(r, dict):
                    payload = r.get('payload', {})
                    if isinstance(payload, dict):
                        round_info = payload.get('round', {})
                        if isinstance(round_info, dict):
                            number = round_info.get('number', 0)
                            if number:
                                open_numbers.append(number)

            issuing_numbers = []
            for r in issuing_rounds:
                # Validate each round is a dict before accessing fields
                if isinstance(r, dict):
                    payload = r.get('payload', {})
                    if isinstance(payload, dict):
                        round_info = payload.get('round', {})
                        if isinstance(round_info, dict):
                            number = round_info.get('number', 0)
                            if number:
                                issuing_numbers.append(number)

            return {
                'open_rounds_count': len(open_rounds),
                'issuing_rounds_count': len(issuing_rounds),
                'closed_rounds_count': len(closed_rounds),
                'total_active_rounds': len(open_rounds) + len(issuing_rounds) + len(closed_rounds),
                'open_round_numbers': sorted(open_numbers),
                'issuing_round_numbers': sorted(issuing_numbers),
                'latest_open_round': max(open_numbers) if open_numbers else None,
                'latest_issuing_round': max(issuing_numbers) if issuing_numbers else None
            }
        except Exception as e:
            return {'error': str(e)}

    def analyze_round_timing(self) -> Dict[str, Any]:
        """
        Analyze timing patterns of mining rounds.

        Returns:
            Dictionary with timing analysis
        """
        try:
            open_issuing = self.client.get_open_and_issuing_mining_rounds()
            open_rounds = open_issuing.get('open_mining_rounds', [])

            open_times = []
            target_closes = []

            for r in open_rounds:
                payload = r.get('payload', {})
                opens_at = payload.get('opensAt')
                target_close = payload.get('targetClosesAt')

                if opens_at:
                    try:
                        open_times.append(datetime.fromisoformat(opens_at.replace('Z', '+00:00')))
                    except:
                        pass

                if target_close:
                    try:
                        target_closes.append(datetime.fromisoformat(target_close.replace('Z', '+00:00')))
                    except:
                        pass

            # Calculate durations
            durations = []
            for i in range(min(len(open_times), len(target_closes))):
                duration = (target_closes[i] - open_times[i]).total_seconds() / 3600  # hours
                durations.append(duration)

            return {
                'rounds_analyzed': len(durations),
                'avg_duration_hours': statistics.mean(durations) if durations else 0,
                'min_duration_hours': min(durations) if durations else 0,
                'max_duration_hours': max(durations) if durations else 0,
                'median_duration_hours': statistics.median(durations) if durations else 0
            }
        except Exception as e:
            return {'error': str(e)}

    def track_round_progression(
        self,
        historical_snapshots: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Track how rounds progress through states over time.

        Args:
            historical_snapshots: List of round summaries at different times

        Returns:
            Dictionary with progression analysis
        """
        if len(historical_snapshots) < 2:
            return {'error': 'Need at least 2 snapshots'}

        progressions = []

        for i in range(1, len(historical_snapshots)):
            prev = historical_snapshots[i-1]
            curr = historical_snapshots[i]

            new_open = curr.get('open_rounds_count', 0) - prev.get('open_rounds_count', 0)
            new_issuing = curr.get('issuing_rounds_count', 0) - prev.get('issuing_rounds_count', 0)
            new_closed = curr.get('closed_rounds_count', 0) - prev.get('closed_rounds_count', 0)

            progressions.append({
                'snapshot_index': i,
                'new_open_rounds': new_open,
                'new_issuing_rounds': new_issuing,
                'new_closed_rounds': new_closed
            })

        return {
            'total_snapshots': len(historical_snapshots),
            'progressions': progressions,
            'avg_new_opens': statistics.mean([p['new_open_rounds'] for p in progressions]),
            'avg_new_issuing': statistics.mean([p['new_issuing_rounds'] for p in progressions]),
            'avg_new_closed': statistics.mean([p['new_closed_rounds'] for p in progressions])
        }


# ========== ANS (Amulet Name Service) Analysis ==========

class ANSAnalyzer:
    """Analyzer for ANS entry data."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def fetch_all_ans_entries(
        self,
        max_pages: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch all ANS entries with pagination.

        Args:
            max_pages: Maximum pages to fetch

        Returns:
            List of all ANS entries
        """
        all_entries = []

        for page in range(max_pages):
            try:
                result = self.client.get_ans_entries(page_size=100)
                entries = result.get('entries', [])

                if not entries:
                    break

                all_entries.extend(entries)

                # If we got less than 100, we've reached the end
                if len(entries) < 100:
                    break

            except Exception as e:
                print(f"Error fetching ANS page {page + 1}: {e}")
                break

        return all_entries

    def analyze_name_patterns(
        self,
        entries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze naming patterns in ANS entries.

        Args:
            entries: List of ANS entries

        Returns:
            Dictionary with name pattern statistics
        """
        name_lengths = []
        char_counts = Counter()
        first_chars = Counter()

        for entry in entries:
            name = entry.get('name', '')
            if name:
                name_lengths.append(len(name))
                first_chars[name[0]] += 1
                for char in name:
                    char_counts[char] += 1

        return {
            'total_names': len(entries),
            'avg_name_length': statistics.mean(name_lengths) if name_lengths else 0,
            'min_name_length': min(name_lengths) if name_lengths else 0,
            'max_name_length': max(name_lengths) if name_lengths else 0,
            'median_name_length': statistics.median(name_lengths) if name_lengths else 0,
            'most_common_first_chars': dict(first_chars.most_common(10)),
            'most_common_chars': dict(char_counts.most_common(10)),
            'unique_first_chars': len(first_chars)
        }

    def analyze_expiration_patterns(
        self,
        entries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze ANS entry expiration patterns.

        Args:
            entries: List of ANS entries

        Returns:
            Dictionary with expiration statistics
        """
        now = datetime.utcnow()
        days_until_expiry = []
        expiry_dates = []

        for entry in entries:
            expires_at = entry.get('expires_at')
            if expires_at:
                try:
                    expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    expiry_dates.append(expiry_dt)
                    days_left = (expiry_dt - now.replace(tzinfo=expiry_dt.tzinfo)).days
                    days_until_expiry.append(days_left)
                except:
                    pass

        # Categorize by expiry time
        expiring_soon = sum(1 for d in days_until_expiry if 0 <= d <= 30)
        expiring_medium = sum(1 for d in days_until_expiry if 30 < d <= 90)
        expiring_later = sum(1 for d in days_until_expiry if d > 90)
        expired = sum(1 for d in days_until_expiry if d < 0)

        return {
            'total_entries': len(entries),
            'entries_with_expiry': len(days_until_expiry),
            'avg_days_until_expiry': statistics.mean(days_until_expiry) if days_until_expiry else 0,
            'median_days_until_expiry': statistics.median(days_until_expiry) if days_until_expiry else 0,
            'min_days_until_expiry': min(days_until_expiry) if days_until_expiry else 0,
            'max_days_until_expiry': max(days_until_expiry) if days_until_expiry else 0,
            'expiring_within_30_days': expiring_soon,
            'expiring_30_90_days': expiring_medium,
            'expiring_after_90_days': expiring_later,
            'already_expired': expired,
            'earliest_expiry': min(expiry_dates).isoformat() if expiry_dates else None,
            'latest_expiry': max(expiry_dates).isoformat() if expiry_dates else None
        }

    def analyze_namespace_saturation(
        self,
        entries: List[Dict[str, Any]],
        max_length: int = 5
    ) -> Dict[str, Any]:
        """
        Analyze saturation of short names in namespace.

        Args:
            entries: List of ANS entries
            max_length: Maximum name length to consider "short"

        Returns:
            Dictionary with namespace saturation analysis
        """
        short_names = []
        length_distribution = Counter()

        for entry in entries:
            name = entry.get('name', '')
            if name:
                length_distribution[len(name)] += 1
                if len(name) <= max_length:
                    short_names.append(name)

        # Estimate theoretical maximum
        # Assuming alphanumeric + some special chars (rough estimate)
        chars_available = 36  # a-z, 0-9
        theoretical_short = sum(chars_available ** i for i in range(1, max_length + 1))

        saturation_rate = len(short_names) / theoretical_short * 100 if theoretical_short > 0 else 0

        return {
            'total_names': len(entries),
            'short_names_count': len(short_names),
            'max_short_length': max_length,
            'theoretical_short_names': theoretical_short,
            'saturation_rate_percent': saturation_rate,
            'length_distribution': dict(sorted(length_distribution.items())),
            'avg_name_length': statistics.mean([len(e.get('name', '')) for e in entries if e.get('name')])
        }

    def find_premium_names(
        self,
        entries: List[Dict[str, Any]],
        criteria: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Identify "premium" names based on criteria.

        Args:
            entries: List of ANS entries
            criteria: Dictionary with criteria (e.g., max_length, patterns)

        Returns:
            List of premium names with details
        """
        if criteria is None:
            criteria = {'max_length': 3}

        max_length = criteria.get('max_length', 3)

        premium = []
        for entry in entries:
            name = entry.get('name', '')
            if name and len(name) <= max_length:
                premium.append({
                    'name': name,
                    'length': len(name),
                    'user': entry.get('user'),
                    'expires_at': entry.get('expires_at'),
                    'is_numeric': name.isdigit(),
                    'is_alpha': name.isalpha(),
                    'is_single_char': len(name) == 1
                })

        # Sort by length then alphabetically
        premium.sort(key=lambda x: (x['length'], x['name']))

        return premium


# ========== Validator Network Analysis ==========

class ValidatorAnalyzer:
    """Analyzer for validator network data."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def get_validator_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive validator network summary.

        Returns:
            Dictionary with validator statistics
        """
        try:
            validators = self.client.get_validator_licenses(limit=10000)
            validator_list = validators.get('validators', [])

            sponsored = sum(1 for v in validator_list if v.get('sponsored'))
            unsponsored = len(validator_list) - sponsored

            return {
                'total_validators': len(validator_list),
                'sponsored_count': sponsored,
                'unsponsored_count': unsponsored,
                'sponsorship_rate': (sponsored / len(validator_list) * 100) if validator_list else 0,
                'validators': validator_list[:10]  # Sample of first 10
            }
        except Exception as e:
            return {'error': str(e)}

    def analyze_validator_growth(
        self,
        historical_snapshots: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze validator network growth over time.

        Args:
            historical_snapshots: List of validator summaries at different times

        Returns:
            Dictionary with growth analysis
        """
        if len(historical_snapshots) < 2:
            return {'error': 'Need at least 2 snapshots'}

        growth_rates = []

        for i in range(1, len(historical_snapshots)):
            prev_count = historical_snapshots[i-1].get('total_validators', 0)
            curr_count = historical_snapshots[i].get('total_validators', 0)

            if prev_count > 0:
                growth_rate = ((curr_count - prev_count) / prev_count) * 100
                growth_rates.append(growth_rate)

        return {
            'total_snapshots': len(historical_snapshots),
            'initial_validators': historical_snapshots[0].get('total_validators', 0),
            'final_validators': historical_snapshots[-1].get('total_validators', 0),
            'net_growth': historical_snapshots[-1].get('total_validators', 0) - historical_snapshots[0].get('total_validators', 0),
            'avg_growth_rate_percent': statistics.mean(growth_rates) if growth_rates else 0,
            'total_growth_rate_percent': ((historical_snapshots[-1].get('total_validators', 0) - historical_snapshots[0].get('total_validators', 0)) / historical_snapshots[0].get('total_validators', 1)) * 100
        }

    def calculate_decentralization_score(
        self,
        validator_data: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calculate a simple decentralization score.

        Args:
            validator_data: Validator summary data

        Returns:
            Dictionary with decentralization metrics
        """
        total = validator_data.get('total_validators', 0)

        if total == 0:
            return {'error': 'No validators'}

        # Simple scoring based on count and sponsorship distribution
        count_score = min(total / 100, 1.0) * 50  # Max 50 points for 100+ validators

        sponsorship_rate = validator_data.get('sponsorship_rate', 0)
        # Ideal is around 50% sponsored
        sponsorship_score = (1 - abs(sponsorship_rate - 50) / 50) * 50

        total_score = count_score + sponsorship_score

        return {
            'decentralization_score': total_score,
            'count_score': count_score,
            'sponsorship_score': sponsorship_score,
            'interpretation': 'High' if total_score > 75 else 'Medium' if total_score > 50 else 'Low'
        }


# ========== Economic & Holdings Analysis ==========

class EconomicAnalyzer:
    """Analyzer for economic data and amulet holdings."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def get_total_supply(self, round_number: int = 0) -> Dict[str, Any]:
        """
        Get total amulet supply for a round.

        Args:
            round_number: Mining round number

        Returns:
            Dictionary with supply information
        """
        try:
            balance = self.client.get_total_amulet_balance(round_=round_number)
            return {
                'round': round_number,
                'total_balance': balance,
                'balance_data': balance
            }
        except Exception as e:
            return {'error': str(e)}

    def analyze_amulet_rules(self) -> Dict[str, Any]:
        """
        Analyze current amulet rules and configuration.

        Returns:
            Dictionary with rules analysis
        """
        try:
            rules = self.client.get_amulet_rules()

            # Extract key economic parameters
            analysis = {
                'rules_retrieved': True,
                'contract_id': rules.get('contract_id'),
                'has_config': 'contract' in rules
            }

            # Try to extract config details if available
            if 'contract' in rules:
                contract = rules['contract']
                payload = contract.get('payload', {})

                config = payload.get('configSchedule', {})
                analysis['has_config_schedule'] = bool(config)

            return analysis
        except Exception as e:
            return {'error': str(e)}

    def estimate_velocity(
        self,
        updates: List[Dict[str, Any]],
        total_supply: float
    ) -> Dict[str, float]:
        """
        Estimate token velocity (simplified).

        Args:
            updates: List of update records
            total_supply: Total amulet supply

        Returns:
            Dictionary with velocity estimates
        """
        if total_supply == 0 or not updates:
            return {'error': 'Invalid inputs'}

        # Count transfer-related updates (simplified heuristic)
        transfer_count = 0
        for update in updates:
            update_type = update.get('update', {}).get('type', '')
            if 'transfer' in update_type.lower() or 'transaction' in update_type.lower():
                transfer_count += 1

        # Calculate time span
        timestamps = []
        for update in updates:
            try:
                ts = datetime.fromisoformat(update['record_time'].replace('Z', '+00:00'))
                timestamps.append(ts)
            except:
                pass

        if len(timestamps) < 2:
            return {'error': 'Insufficient timestamp data'}

        time_span_days = (max(timestamps) - min(timestamps)).days
        if time_span_days == 0:
            time_span_days = 1

        # Very simplified velocity estimate
        annual_transfer_rate = (transfer_count / time_span_days) * 365
        velocity = annual_transfer_rate / total_supply if total_supply > 0 else 0

        return {
            'transfer_count': transfer_count,
            'time_span_days': time_span_days,
            'annual_transfer_estimate': annual_transfer_rate,
            'velocity_estimate': velocity,
            'note': 'This is a simplified estimate based on update types'
        }


# ========== Governance Analysis ==========

class GovernanceAnalyzer:
    """Analyzer for governance and voting data."""

    def __init__(self, client: SpliceScanClient):
        self.client = client

    def analyze_vote_requests(
        self,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Analyze vote request patterns.

        Args:
            limit: Maximum vote requests to analyze

        Returns:
            Dictionary with vote analysis
        """
        try:
            # Get all vote requests
            all_requests = self.client.list_vote_requests(limit=limit)
            requests = all_requests.get('vote_requests', [])

            if not requests:
                return {'total_requests': 0, 'note': 'No vote requests found'}

            # Analyze patterns
            action_types = Counter()
            acceptance_status = Counter()

            for req in requests:
                action = req.get('action', {})
                action_name = action.get('type', 'unknown')
                action_types[action_name] += 1

                accepted = req.get('accepted', False)
                acceptance_status['accepted' if accepted else 'pending'] += 1

            return {
                'total_requests': len(requests),
                'action_types': dict(action_types),
                'acceptance_status': dict(acceptance_status),
                'acceptance_rate': (acceptance_status['accepted'] / len(requests) * 100) if requests else 0,
                'most_common_action': action_types.most_common(1)[0] if action_types else None
            }
        except Exception as e:
            return {'error': str(e)}

    def calculate_governance_participation(
        self,
        vote_data: Dict[str, Any],
        validator_count: int
    ) -> Dict[str, float]:
        """
        Calculate governance participation metrics.

        Args:
            vote_data: Vote request analysis data
            validator_count: Total number of validators

        Returns:
            Dictionary with participation metrics
        """
        if validator_count == 0:
            return {'error': 'Invalid validator count'}

        total_requests = vote_data.get('total_requests', 0)
        accepted = vote_data.get('acceptance_status', {}).get('accepted', 0)

        return {
            'total_vote_requests': total_requests,
            'accepted_requests': accepted,
            'validator_count': validator_count,
            'votes_per_validator': total_requests / validator_count if validator_count > 0 else 0,
            'acceptance_rate': (accepted / total_requests * 100) if total_requests > 0 else 0
        }


# ========== Comprehensive Network Health ==========

class NetworkHealthAnalyzer:
    """Analyzer for overall network health metrics."""

    def __init__(self, client: SpliceScanClient):
        self.client = client
        self.tx_analyzer = TransactionAnalyzer(client)
        self.mining_analyzer = MiningRoundAnalyzer(client)
        self.validator_analyzer = ValidatorAnalyzer(client)
        self.ans_analyzer = ANSAnalyzer(client)

    def generate_health_score(self) -> Dict[str, Any]:
        """
        Generate an overall network health score.

        Returns:
            Dictionary with health score and metrics
        """
        scores = {}

        # Transaction activity score (0-25 points)
        try:
            updates = self.tx_analyzer.fetch_updates_batch(max_pages=5)
            tx_rate = self.tx_analyzer.calculate_transaction_rate(updates)

            if 'updates_per_hour' in tx_rate:
                # Score based on transaction rate
                tx_score = min(tx_rate['updates_per_hour'] / 10, 1.0) * 25
                scores['transaction_activity'] = tx_score
        except:
            scores['transaction_activity'] = 0

        # Mining activity score (0-25 points)
        try:
            mining_summary = self.mining_analyzer.get_all_rounds_summary()
            active_rounds = mining_summary.get('total_active_rounds', 0)
            mining_score = min(active_rounds / 10, 1.0) * 25
            scores['mining_activity'] = mining_score
        except:
            scores['mining_activity'] = 0

        # Validator network score (0-25 points)
        try:
            validator_summary = self.validator_analyzer.get_validator_summary()
            decentralization = self.validator_analyzer.calculate_decentralization_score(validator_summary)
            scores['validator_network'] = decentralization.get('decentralization_score', 0) / 100 * 25
        except:
            scores['validator_network'] = 0

        # Namespace adoption score (0-25 points)
        try:
            ans_entries = self.ans_analyzer.fetch_all_ans_entries(max_pages=5)
            ans_score = min(len(ans_entries) / 100, 1.0) * 25
            scores['namespace_adoption'] = ans_score
        except:
            scores['namespace_adoption'] = 0

        total_score = sum(scores.values())

        return {
            'overall_health_score': total_score,
            'max_score': 100,
            'component_scores': scores,
            'health_rating': 'Excellent' if total_score > 80 else 'Good' if total_score > 60 else 'Fair' if total_score > 40 else 'Poor',
            'timestamp': datetime.utcnow().isoformat()
        }

    def generate_comprehensive_report(self) -> str:
        """
        Generate a comprehensive text report of network health.

        Returns:
            Formatted text report
        """
        lines = []
        lines.append("=" * 80)
        lines.append("SPLICE NETWORK COMPREHENSIVE HEALTH REPORT")
        lines.append("=" * 80)
        lines.append(f"Generated: {datetime.utcnow().isoformat()}")
        lines.append("")

        # Health Score
        health = self.generate_health_score()
        lines.append("OVERALL HEALTH")
        lines.append("-" * 80)
        lines.append(f"Health Score: {health['overall_health_score']:.1f}/100 ({health['health_rating']})")
        lines.append("")
        lines.append("Component Scores:")
        for component, score in health['component_scores'].items():
            lines.append(f"  {component.replace('_', ' ').title()}: {score:.1f}/25")
        lines.append("")

        # Transaction Activity
        try:
            updates = self.tx_analyzer.fetch_updates_batch(max_pages=3)
            tx_rate = self.tx_analyzer.calculate_transaction_rate(updates)

            lines.append("TRANSACTION ACTIVITY")
            lines.append("-" * 80)
            lines.append(f"Recent Updates Analyzed: {tx_rate.get('total_updates', 0)}")
            lines.append(f"Updates per Hour: {tx_rate.get('updates_per_hour', 0):.2f}")
            lines.append(f"Updates per Day: {tx_rate.get('updates_per_day', 0):.2f}")
            lines.append("")
        except Exception as e:
            lines.append(f"Transaction Activity: Error - {e}")
            lines.append("")

        # Mining Rounds
        try:
            mining = self.mining_analyzer.get_all_rounds_summary()
            lines.append("MINING ROUNDS")
            lines.append("-" * 80)
            lines.append(f"Open Rounds: {mining.get('open_rounds_count', 0)}")
            lines.append(f"Issuing Rounds: {mining.get('issuing_rounds_count', 0)}")
            lines.append(f"Closed Rounds: {mining.get('closed_rounds_count', 0)}")
            lines.append(f"Latest Open Round: {mining.get('latest_open_round', 'N/A')}")
            lines.append("")
        except Exception as e:
            lines.append(f"Mining Rounds: Error - {e}")
            lines.append("")

        # Validators
        try:
            validators = self.validator_analyzer.get_validator_summary()
            lines.append("VALIDATOR NETWORK")
            lines.append("-" * 80)
            lines.append(f"Total Validators: {validators.get('total_validators', 0)}")
            lines.append(f"Sponsored: {validators.get('sponsored_count', 0)}")
            lines.append(f"Unsponsored: {validators.get('unsponsored_count', 0)}")
            lines.append(f"Sponsorship Rate: {validators.get('sponsorship_rate', 0):.1f}%")
            lines.append("")
        except Exception as e:
            lines.append(f"Validator Network: Error - {e}")
            lines.append("")

        # ANS
        try:
            ans_entries = self.ans_analyzer.fetch_all_ans_entries(max_pages=3)
            ans_patterns = self.ans_analyzer.analyze_name_patterns(ans_entries)
            lines.append("ANS NAMESPACE")
            lines.append("-" * 80)
            lines.append(f"Total Registered Names: {ans_patterns.get('total_names', 0)}")
            lines.append(f"Average Name Length: {ans_patterns.get('avg_name_length', 0):.1f}")
            lines.append(f"Shortest Name: {ans_patterns.get('min_name_length', 0)} chars")
            lines.append(f"Longest Name: {ans_patterns.get('max_name_length', 0)} chars")
            lines.append("")
        except Exception as e:
            lines.append(f"ANS Namespace: Error - {e}")
            lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)


# ========== Utility Functions ==========

def calculate_gini_coefficient(values: List[float]) -> float:
    """
    Calculate Gini coefficient for wealth distribution.

    Args:
        values: List of values (e.g., balances)

    Returns:
        Gini coefficient (0 = perfect equality, 1 = perfect inequality)
    """
    if not values or len(values) < 2:
        return 0.0

    sorted_values = sorted(values)
    n = len(sorted_values)
    cumsum = 0

    for i, val in enumerate(sorted_values):
        cumsum += (2 * (i + 1) - n - 1) * val

    return cumsum / (n * sum(sorted_values)) if sum(sorted_values) > 0 else 0.0


def export_to_csv(data: List[Dict[str, Any]], filename: str):
    """
    Export data to CSV file.

    Args:
        data: List of dictionaries
        filename: Output filename
    """
    if not PANDAS_AVAILABLE:
        print("Pandas required for CSV export")
        return

    df = pd.DataFrame(data)
    df.to_csv(filename, index=False)
    print(f"Data exported to {filename}")


# ========== Main Demo ==========

def main():
    """Demonstrate the analytics capabilities."""

    # Configuration
    BASE_URL = "https://scan.sv-1.dev.global.canton.network.sync.global/api/scan/"

    print("Initializing Splice Analytics...")
    client = SpliceScanClient(base_url=BASE_URL)

    # Initialize analyzers
    health_analyzer = NetworkHealthAnalyzer(client)

    # Generate comprehensive report
    print("\n" + "=" * 80)
    print("Generating Comprehensive Network Health Report...")
    print("=" * 80)

    report = health_analyzer.generate_comprehensive_report()
    print(report)

    # Save report
    with open('splice_network_health_report.txt', 'w') as f:
        f.write(report)
    print("\nReport saved to splice_network_health_report.txt")

    # Close client
    client.close()


if __name__ == "__main__":
    main()
