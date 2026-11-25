"""Market surveillance / monitoring.

Consumes every event the exchange emits, keeps per-instrument and
per-participant statistics, and raises ``Alert`` events (high reject rate,
large trade, ...). Circuit-breaker and halt alerts are raised by the exchange.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .types import (Alert, AuctionResult, CancelReject, ExecType, ExecutionReport, PhaseChange,
                    PhaseChangeRejected, Trade, fmt, to_dec)


@dataclass
class SymbolStats:
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    last: Optional[Decimal] = None
    volume: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    trades: int = 0
    auction_trades: int = 0
    auctions: int = 0
    circuit_breakers: int = 0

    @property
    def vwap(self) -> Optional[Decimal]:
        return (self.notional / self.volume).quantize(Decimal("1E-8")).normalize() if self.volume else None

    def as_dict(self):
        return {k: fmt(v) if isinstance(v, Decimal) else v for k, v in {
            "open": self.open, "high": self.high, "low": self.low, "last": self.last, "vwap": self.vwap,
            "volume": self.volume, "notional": self.notional, "trades": self.trades,
            "auction_trades": self.auction_trades, "auctions": self.auctions,
            "circuit_breakers": self.circuit_breakers}.items()}


@dataclass
class ParticipantStats:
    orders: int = 0
    rejects: int = 0
    alerted: bool = False


class MarketMonitor:
    def __init__(self, config):
        m = config.monitoring or {}
        self.reject_rate_pct = to_dec(m.get("reject_rate_alert_pct", 50))
        self.reject_rate_min_orders = int(m.get("reject_rate_min_orders", 20))
        self.large_trade_notional = {k.upper(): to_dec(v) for k, v in (m.get("large_trade_notional") or {}).items()}
        self.symbols: dict = defaultdict(SymbolStats)
        self.participants: dict = defaultdict(ParticipantStats)
        self.exec_types: Counter = Counter()
        self.reject_reasons: Counter = Counter()
        self.cancel_rejects: Counter = Counter()
        self.phase_changes: list = []
        self.phase_rejections: int = 0
        self.alerts: list = []

    def on_event(self, ev, exchange) -> list:
        new_alerts = []
        if isinstance(ev, ExecutionReport):
            self.exec_types[ev.exec_type.value] += 1
            if ev.exec_type in (ExecType.NEW, ExecType.REJECTED) and isinstance(ev.participant, str):
                ps = self.participants[ev.participant]
                ps.orders += 1
                if ev.exec_type is ExecType.REJECTED:
                    ps.rejects += 1
                    self.reject_reasons[ev.reject_reason.value] += 1
                    if (not ps.alerted and ps.orders >= self.reject_rate_min_orders
                            and ps.rejects * 100 > self.reject_rate_pct * ps.orders):
                        ps.alerted = True
                        new_alerts.append(Alert("HIGH_REJECT_RATE", "WARNING",
                                                f"{ev.participant} reject rate {ps.rejects}/{ps.orders}",
                                                participant=ev.participant,
                                                data={"orders": ps.orders, "rejects": ps.rejects}))
        elif isinstance(ev, CancelReject):
            self.cancel_rejects[ev.reject_reason.value] += 1
        elif isinstance(ev, Trade):
            s = self.symbols[ev.symbol]
            if s.open is None:
                s.open = ev.price
            s.high = ev.price if s.high is None else max(s.high, ev.price)
            s.low = ev.price if s.low is None else min(s.low, ev.price)
            s.last = ev.price
            s.volume += ev.qty
            s.trades += 1
            inst = exchange.refdata.get(ev.symbol)
            notional = ev.price * ev.qty * (inst.multiplier if inst else 1)
            s.notional += ev.price * ev.qty
            if ev.match_type == "AUCTION":
                s.auction_trades += 1
            if inst is not None:
                limit = self.large_trade_notional.get(inst.asset_class)
                if limit is not None and notional >= limit:
                    new_alerts.append(Alert("LARGE_TRADE", "INFO", f"{ev.symbol} trade notional {fmt(notional)}",
                                            symbol=ev.symbol, data={"trade_id": ev.trade_id, "notional": fmt(notional)}))
        elif isinstance(ev, AuctionResult):
            if ev.volume > 0:
                self.symbols[ev.symbol].auctions += 1
        elif isinstance(ev, PhaseChange):
            self.phase_changes.append((ev.scope, ev.old_phase.value, ev.new_phase.value))
        elif isinstance(ev, PhaseChangeRejected):
            self.phase_rejections += 1
        elif isinstance(ev, Alert):
            self.alerts.append(ev)
            if ev.kind == "CIRCUIT_BREAKER" and ev.symbol:
                self.symbols[ev.symbol].circuit_breakers += 1
        self.alerts.extend(new_alerts)
        return new_alerts

    def summary(self) -> dict:
        return {
            "exec_types": dict(self.exec_types),
            "reject_reasons": dict(self.reject_reasons.most_common()),
            "cancel_rejects": dict(self.cancel_rejects.most_common()),
            "symbols": {k: v.as_dict() for k, v in sorted(self.symbols.items())},
            "alerts": Counter(a.kind for a in self.alerts),
            "phase_changes": len(self.phase_changes),
            "phase_rejections": self.phase_rejections,
        }
