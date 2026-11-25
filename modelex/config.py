"""Market configuration: everything an exchange customises without touching code.

See ``config/market_default.json`` for a fully annotated example.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .types import MatchingMode, OrderType, Phase, STPMode, TimeInForce, to_dec


class ConfigError(Exception):
    pass


@dataclass
class PhaseRule:
    accept_new: bool
    accept_cancel: bool
    accept_amend: bool
    matching: MatchingMode
    allowed_tif: Optional[frozenset] = None          # None = whatever the asset class allows
    allowed_order_types: Optional[frozenset] = None
    uncross_on_entry: bool = False                  # run an auction uncross when entering this phase
    expire_day_orders_on_entry: bool = False


def _pr(new, cxl, amend, matching, tif=None, types=None, uncross=False, expire=False):
    return PhaseRule(new, cxl, amend, matching,
                     frozenset(TimeInForce(t) for t in tif) if tif else None,
                     frozenset(OrderType(t) for t in types) if types else None, uncross, expire)


DEFAULT_PHASE_RULES = {
    Phase.CLOSED: _pr(False, False, False, MatchingMode.NONE, expire=True),
    Phase.PRE_OPEN: _pr(True, True, True, MatchingMode.CALL, tif=["DAY", "GTC"]),
    Phase.CONTINUOUS: _pr(True, True, True, MatchingMode.CONTINUOUS, uncross=True),
    Phase.PRE_CLOSE: _pr(True, True, True, MatchingMode.CALL, tif=["DAY", "GTC"]),
    Phase.POST_CLOSE: _pr(False, True, False, MatchingMode.NONE, uncross=True),
    Phase.HALTED: _pr(False, True, False, MatchingMode.NONE),
    Phase.VOLATILITY_AUCTION: _pr(True, True, True, MatchingMode.CALL, tif=["DAY", "GTC"]),
}

DEFAULT_TRANSITIONS = {
    Phase.CLOSED: {Phase.PRE_OPEN, Phase.CONTINUOUS, Phase.HALTED},
    Phase.PRE_OPEN: {Phase.CONTINUOUS, Phase.HALTED, Phase.CLOSED},
    Phase.CONTINUOUS: {Phase.PRE_CLOSE, Phase.POST_CLOSE, Phase.HALTED, Phase.CLOSED},
    Phase.PRE_CLOSE: {Phase.POST_CLOSE, Phase.HALTED, Phase.CLOSED},
    Phase.POST_CLOSE: {Phase.CLOSED},
    Phase.HALTED: {Phase.PRE_OPEN, Phase.CONTINUOUS, Phase.CLOSED},
    Phase.VOLATILITY_AUCTION: set(),  # instrument-level only; managed by circuit breaker
}

DEFAULT_GLOBAL_RULES = ["REQUIRED_FIELDS", "DUPLICATE_CL_ORD_ID", "UNKNOWN_INSTRUMENT"]
DEFAULT_ASSET_RULES = ["INSTRUMENT_STATUS", "INSTRUMENT_EXPIRY", "SESSION_PHASE", "ORDER_TYPE",
                       "TIME_IN_FORCE", "PRICE_PRESENCE", "QUANTITY_POSITIVE", "LOT_SIZE", "MIN_MAX_QTY",
                       "UNIQUE_ITEM", "TICK_SIZE", "PRICE_BAND", "MAX_NOTIONAL", "DUPLICATE_ORDER"]


@dataclass
class CircuitBreakerConfig:
    enabled: bool = True
    pct: Optional[Decimal] = None        # instrument circuit_breaker_pct overrides this
    auction_seconds: int = 300


@dataclass
class AssetClassConfig:
    name: str
    schedule: str
    matching_algorithm: str = "PRICE_TIME"
    order_types: frozenset = frozenset({OrderType.LIMIT, OrderType.MARKET})
    time_in_force: frozenset = frozenset(TimeInForce)
    self_trade_prevention: STPMode = STPMode.NONE
    validation_rules: list = field(default_factory=lambda: list(DEFAULT_ASSET_RULES))
    duplicate_order_window_ms: int = 0
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    protocol: str = "FIX44"
    max_notional: Optional[Decimal] = None


@dataclass
class ScheduleConfig:
    name: str
    initial_phase: Phase
    timeline: list = field(default_factory=list)   # [(datetime.time, Phase)]


@dataclass
class MarketConfig:
    exchange_name: str = "ModelEx"
    mic: str = "XMDL"
    trading_date: dt.date = field(default_factory=dt.date.today)
    global_validation_rules: list = field(default_factory=lambda: list(DEFAULT_GLOBAL_RULES))
    duplicate_cl_ord_id_scope: str = "ALL"     # ALL = every ClOrdID received today; ACCEPTED = accepted only
    phase_rules: dict = field(default_factory=lambda: dict(DEFAULT_PHASE_RULES))
    transitions: dict = field(default_factory=lambda: {k: set(v) for k, v in DEFAULT_TRANSITIONS.items()})
    schedules: dict = field(default_factory=dict)
    asset_classes: dict = field(default_factory=dict)
    monitoring: dict = field(default_factory=dict)
    protocols: dict = field(default_factory=dict)
    base_dir: Optional[Path] = None

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_file(cls, path) -> "MarketConfig":
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path}: invalid JSON: {e}") from e
        return cls.from_dict(data, base_dir=path.parent)

    @classmethod
    def from_dict(cls, d: dict, base_dir=None) -> "MarketConfig":
        ex = d.get("exchange", {})
        cfg = cls(
            exchange_name=ex.get("name", "ModelEx"),
            mic=ex.get("mic", "XMDL"),
            trading_date=dt.date.fromisoformat(ex["trading_date"]) if ex.get("trading_date") else dt.date.today(),
            duplicate_cl_ord_id_scope=ex.get("duplicate_cl_ord_id_scope", "ALL").upper(),
            monitoring=d.get("monitoring", {}),
            protocols=d.get("protocols", {}),
            base_dir=Path(base_dir) if base_dir else None,
        )
        if "global_validation_rules" in d:
            cfg.global_validation_rules = list(d["global_validation_rules"])
        for name, pr in (d.get("phase_rules") or {}).items():
            base = DEFAULT_PHASE_RULES.get(Phase(name))
            cfg.phase_rules[Phase(name)] = PhaseRule(
                accept_new=pr.get("accept_new", base.accept_new if base else False),
                accept_cancel=pr.get("accept_cancel", base.accept_cancel if base else True),
                accept_amend=pr.get("accept_amend", base.accept_amend if base else False),
                matching=MatchingMode(pr.get("matching", base.matching if base else "NONE")),
                allowed_tif=frozenset(TimeInForce(t) for t in pr["allowed_tif"]) if pr.get("allowed_tif")
                else (base.allowed_tif if base else None),
                allowed_order_types=frozenset(OrderType(t) for t in pr["allowed_order_types"])
                if pr.get("allowed_order_types") else (base.allowed_order_types if base else None),
                uncross_on_entry=pr.get("uncross_on_entry", base.uncross_on_entry if base else False),
                expire_day_orders_on_entry=pr.get("expire_day_orders_on_entry",
                                                  base.expire_day_orders_on_entry if base else False),
            )
        for old, news in (d.get("transitions") or {}).items():
            cfg.transitions[Phase(old)] = {Phase(n) for n in news}
        for name, s in (d.get("schedules") or {}).items():
            timeline = []
            for entry in s.get("timeline", []):
                timeline.append((dt.time.fromisoformat(entry["time"]), Phase(entry["phase"])))
            timeline.sort(key=lambda x: x[0])
            cfg.schedules[name] = ScheduleConfig(name, Phase(s.get("initial_phase", "CLOSED")), timeline)
        for name, a in (d.get("asset_classes") or {}).items():
            cb = a.get("circuit_breaker", {})
            ac = AssetClassConfig(
                name=name.upper(),
                schedule=a["schedule"],
                matching_algorithm=a.get("matching_algorithm", "PRICE_TIME").upper(),
                order_types=frozenset(OrderType(t) for t in a.get("order_types", ["LIMIT", "MARKET"])),
                time_in_force=frozenset(TimeInForce(t) for t in a.get("time_in_force", [t.value for t in TimeInForce])),
                self_trade_prevention=STPMode(a.get("self_trade_prevention", "NONE")),
                validation_rules=list(a.get("validation_rules", DEFAULT_ASSET_RULES)),
                duplicate_order_window_ms=int(a.get("duplicate_order_window_ms", 0)),
                circuit_breaker=CircuitBreakerConfig(
                    enabled=cb.get("enabled", True), pct=to_dec(cb.get("pct")),
                    auction_seconds=int(cb.get("auction_seconds", 300))),
                protocol=a.get("protocol", "FIX44"),
                max_notional=to_dec(a.get("max_notional")),
            )
            if ac.schedule not in cfg.schedules:
                raise ConfigError(f"asset class {name}: unknown schedule '{ac.schedule}'")
            cfg.asset_classes[ac.name] = ac
        cfg.validate()
        return cfg

    def validate(self):
        for phase in Phase:
            if phase not in self.phase_rules:
                raise ConfigError(f"missing phase rule for {phase}")
        for s in self.schedules.values():
            prev = s.initial_phase
            for _, ph in s.timeline:
                if ph not in self.transitions.get(prev, set()):
                    raise ConfigError(f"schedule {s.name}: illegal timeline transition {prev} -> {ph}")
                prev = ph
        if self.duplicate_cl_ord_id_scope not in ("ALL", "ACCEPTED"):
            raise ConfigError("duplicate_cl_ord_id_scope must be ALL or ACCEPTED")

    def resolve_path(self, p) -> Path:
        p = Path(p)
        if not p.is_absolute() and self.base_dir is not None:
            p = (self.base_dir / p).resolve()
        return p
