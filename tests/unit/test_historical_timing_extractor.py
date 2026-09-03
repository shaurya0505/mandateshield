import pytest
from datetime import datetime, timezone
from services.signals.historical_timing_extractor import HistoricalTimingExtractor


def test_clear_historical_payment_timing_window():
    """Verify clean extraction when historical payments cluster around the 1st–3rd of the month."""
    # 4 historical payments on June 2, July 1, August 1, August 3
    dates = [
        datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 3, 10, 0, 0, tzinfo=timezone.utc),
    ]

    current_time_aug28 = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
    signal = HistoricalTimingExtractor.extract(dates, current_time_aug28)

    assert signal.has_timing_signal is True
    assert signal.sample_size == 4
    assert signal.matching_observations == 4
    assert signal.support_ratio == 1.0
    assert signal.confidence_score >= 0.80
    assert signal.window_start_day == 1
    assert signal.window_end_day == 3
    # On Aug 28, we are outside the window
    assert signal.in_current_window is False
    # Days until window start (Sept 1) from Aug 28: (31 - 28) + 1 = 4 days
    assert signal.days_until_next_window == 4
    assert "days 1–3" in signal.explanation


def test_sparse_history_insufficient_data():
    """Invariant: 0, 1, or 2 historical samples must explicitly report insufficient evidence."""
    current_time = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)

    # 0 samples
    sig_zero = HistoricalTimingExtractor.extract([], current_time)
    assert sig_zero.has_timing_signal is False
    assert sig_zero.sample_size == 0
    assert "Insufficient observed historical payment samples" in sig_zero.explanation

    # 2 samples
    dates_two = [
        datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
    ]
    sig_two = HistoricalTimingExtractor.extract(dates_two, current_time)
    assert sig_two.has_timing_signal is False
    assert sig_two.sample_size == 2
    assert sig_two.confidence_score == 0.0


def test_noisy_dispersed_payment_history():
    """Verify that widely scattered payment dates without a distinct cluster do not generate a false timing signal."""
    # Payments on Days 4, 12, 19, 27
    dates = [
        datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc),
    ]
    current_time = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
    signal = HistoricalTimingExtractor.extract(dates, current_time)

    assert signal.has_timing_signal is False
    assert signal.confidence_score == 0.0
    assert "high dispersion" in signal.explanation


def test_month_boundary_circular_timing_window():
    """
    Verify month-boundary clustering (e.g. Day 31 -> Day 1 -> Day 2).
    Jan 31, Mar 1, Apr 2 must cluster into a single circular window [31, 2].
    """
    dates = [
        datetime(2026, 1, 31, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 2, 10, 0, 0, tzinfo=timezone.utc),
    ]
    # Current time on Feb 1 (Day 1) -> should be inside the [31, 2] window
    current_time_feb01 = datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    signal = HistoricalTimingExtractor.extract(dates, current_time_feb01)

    assert signal.has_timing_signal is True
    assert signal.window_start_day == 31
    assert signal.window_end_day == 2
    assert signal.in_current_window is True
    assert signal.days_until_next_window == 0
