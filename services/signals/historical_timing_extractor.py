import calendar
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from domain.models.historical_timing_signal import HistoricalPaymentTimingSignal


class HistoricalTimingExtractor:
    """
    Deterministic algorithm for extracting recurring payment timing windows
    with circular month-boundary handling and exact calendar-aware day calculation.
    """

    MIN_SAMPLE_SIZE = 3          # Minimum historical successful payments needed
    MAX_WINDOW_SPAN_DAYS = 5     # Maximum allowable window span to qualify as a cluster
    MIN_SUPPORT_THRESHOLD = 0.60 # Minimum proportion of observations in cluster

    @classmethod
    def is_day_in_window(cls, day: int, start_day: int, end_day: int) -> bool:
        """Determines if a day-of-month falls inside a circular [start_day, end_day] window."""
        if start_day <= end_day:
            return start_day <= day <= end_day
        else:
            # Wraps around month boundary (e.g. 30 to 3)
            return day >= start_day or day <= end_day

    @classmethod
    def calculate_days_until_window(cls, current_time: datetime, start_day: int, end_day: int) -> int:
        """
        Calculates exact days remaining until the next occurrence of the window start day,
        respecting real calendar month lengths (e.g. 28, 29, 30, 31 days).
        """
        current_day = current_time.day
        if cls.is_day_in_window(current_day, start_day, end_day):
            return 0

        # If start_day is later in the current month
        if start_day > current_day:
            return start_day - current_day

        # Otherwise, calculate days to end of current month + start_day in next month
        days_in_month = calendar.monthrange(current_time.year, current_time.month)[1]
        days_left_in_current_month = days_in_month - current_day
        return days_left_in_current_month + start_day

    @classmethod
    def extract(
        cls,
        successful_payment_timestamps: List[datetime],
        current_time: datetime,
    ) -> HistoricalPaymentTimingSignal:
        """
        Extracts historical payment timing window from observed successful payment dates.
        """
        sample_size = len(successful_payment_timestamps)

        # 1. Sparse History Check
        if sample_size < cls.MIN_SAMPLE_SIZE:
            return HistoricalPaymentTimingSignal(
                has_timing_signal=False,
                sample_size=sample_size,
                matching_observations=sample_size,
                support_ratio=0.0,
                confidence_score=0.0,
                in_current_window=False,
                days_until_next_window=None,
                explanation=(
                    f"Insufficient observed historical payment samples (found {sample_size}, "
                    f"minimum {cls.MIN_SAMPLE_SIZE} required for timing pattern)."
                ),
            )

        # Extract day of month for each successful payment
        days = [ts.day for ts in successful_payment_timestamps]

        # 2. Circular Window Clustering Evaluation
        best_window: Optional[Tuple[int, int]] = None
        max_matches = 0
        min_span = cls.MAX_WINDOW_SPAN_DAYS + 1

        for span in range(1, cls.MAX_WINDOW_SPAN_DAYS + 1):
            for start_d in range(1, 32):
                end_d = ((start_d + span - 2) % 31) + 1
                matches = sum(1 for d in days if cls.is_day_in_window(d, start_d, end_d))

                if matches > max_matches or (matches == max_matches and span < min_span):
                    max_matches = matches
                    min_span = span
                    best_window = (start_d, end_d)

        support_ratio = round(max_matches / sample_size, 3)

        # 3. Check if cluster meets support threshold
        if support_ratio < cls.MIN_SUPPORT_THRESHOLD or not best_window:
            return HistoricalPaymentTimingSignal(
                has_timing_signal=False,
                sample_size=sample_size,
                matching_observations=max_matches,
                support_ratio=support_ratio,
                confidence_score=0.0,
                in_current_window=False,
                days_until_next_window=None,
                explanation=(
                    f"Payment dates exhibit high dispersion with no dominant historical timing window "
                    f"(best cluster captured only {round(support_ratio * 100, 1)}% of payments)."
                ),
            )

        start_day, end_day = best_window
        current_day = current_time.day
        in_window = cls.is_day_in_window(current_day, start_day, end_day)
        days_until = cls.calculate_days_until_window(current_time, start_day, end_day)

        # Deterministic confidence formula: scales with support ratio and sample size
        # 3 samples: sample_weight=0.5 -> confidence = support * 0.75
        # 6+ samples: sample_weight=1.0 -> confidence = support * 1.0
        sample_weight = min(1.0, sample_size / 6.0)
        confidence_score = round(support_ratio * (0.5 + 0.5 * sample_weight), 2)

        return HistoricalPaymentTimingSignal(
            has_timing_signal=True,
            window_start_day=start_day,
            window_end_day=end_day,
            sample_size=sample_size,
            matching_observations=max_matches,
            support_ratio=support_ratio,
            confidence_score=confidence_score,
            in_current_window=in_window,
            days_until_next_window=days_until,
            explanation=(
                f"Historically observed successful recurring payments cluster on days {start_day}–{end_day} "
                f"of the month ({max_matches}/{sample_size} observed payments, {round(support_ratio * 100, 1)}% support)."
            ),
        )
