from datetime import datetime, timedelta, timezone
from typing import Optional


class SimulationClock:
    """
    Deterministic virtual clock for reproducible time-stepped simulation.
    Ensures that historical payment timing, cooldowns, and scheduled retries
    behave identically across experiment runs.
    """

    def __init__(self, initial_time: Optional[datetime] = None):
        if initial_time is None:
            self._current_time = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
        else:
            if initial_time.tzinfo is None:
                self._current_time = initial_time.replace(tzinfo=timezone.utc)
            else:
                self._current_time = initial_time

    def now(self) -> datetime:
        """Returns the current simulation timestamp in UTC."""
        return self._current_time

    def advance(self, seconds: int = 0, minutes: int = 0, hours: int = 0, days: int = 0) -> datetime:
        """Advances the virtual clock forward by the given delta."""
        delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        if delta < timedelta(0):
            raise ValueError("Simulation clock cannot move backwards.")
        self._current_time += delta
        return self._current_time

    def set_time(self, target_time: datetime) -> None:
        """Sets the virtual clock to an explicit target timestamp."""
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)
        if target_time < self._current_time:
            raise ValueError("Target time cannot be earlier than current simulation time.")
        self._current_time = target_time
