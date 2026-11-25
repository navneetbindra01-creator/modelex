"""Trading session state: schedule phases, instrument-level overrides, simulated clock."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .types import Phase


class SimClock:
    """Deterministic clock. Nothing in ModelEx reads wall-clock time."""

    def __init__(self, start: dt.datetime):
        self._now = start

    def now(self) -> dt.datetime:
        return self._now

    def set(self, t: dt.datetime) -> None:
        if t < self._now:
            raise ValueError("clock cannot go backwards")
        self._now = t

    def advance(self, seconds) -> None:
        self._now += dt.timedelta(seconds=float(Decimal(str(seconds))))


@dataclass
class Override:
    phase: Phase                     # VOLATILITY_AUCTION or HALTED
    until: Optional[dt.datetime]
    reason: str


class SessionManager:
    def __init__(self, config):
        self.config = config
        self.schedule_phase: dict = {n: s.initial_phase for n, s in config.schedules.items()}
        self.overrides: dict = {}       # symbol -> Override

    def can_transition(self, old: Phase, new: Phase) -> bool:
        return new in self.config.transitions.get(old, set())

    def timeline_between(self, start: dt.datetime, end: dt.datetime, trading_date: dt.date) -> list:
        """Scheduled transitions with start < t <= end, as (t, schedule, phase)."""
        out = []
        for name, s in self.config.schedules.items():
            for tm, ph in s.timeline:
                t = dt.datetime.combine(trading_date, tm)
                if start < t <= end:
                    out.append((t, name, ph))
        return sorted(out, key=lambda x: x[0])
