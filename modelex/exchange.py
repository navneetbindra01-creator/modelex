"""The ModelEx exchange: a deterministic, configurable reference model.

``Exchange.process(command) -> [events]`` is the single entry point. Every
behaviour is driven by the market config + reference data, so the same engine
models an equity venue, a 24x7 crypto venue, a pro-rata futures market or an
illiquid collectibles market.
"""
from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Optional

from .config import ConfigError, MarketConfig
from .matching import compute_uncross, eligible_at, get_algorithm
from .monitor import MarketMonitor
from .orderbook import OrderBook
from .refdata import Instrument, RefDataStore
from .session import Override, SessionManager, SimClock
from .types import (TERMINAL_STATUSES, AdvanceTime, Alert, AuctionResult, CancelOrder, CancelReject, ExecType,
                    ExecutionReport, HaltInstrument, MatchingMode, NewOrder, Order, OrderType, OrdStatus, Phase,
                    PhaseChange, PhaseChangeRejected, RejectReason, ReplaceOrder, ResumeInstrument, SetPhase, Side,
                    STPMode, TimeInForce, Trade, fmt)
from .validation import Rejection, Validator


class Exchange:
    def __init__(self, config: MarketConfig, refdata: RefDataStore, clock: Optional[SimClock] = None,
                 auto_schedule: bool = True):
        self.config = config
        self.refdata = refdata
        self.clock = clock or SimClock(dt.datetime.combine(config.trading_date, dt.time(0, 0)))
        self.auto_schedule = auto_schedule
        self.sessions = SessionManager(config)
        self.validator = Validator(config)
        self.monitor = MarketMonitor(config)
        self.algorithms = {name: get_algorithm(ac.matching_algorithm) for name, ac in config.asset_classes.items()}
        self.books: dict[str, OrderBook] = {}
        for inst in refdata:
            if inst.asset_class not in config.asset_classes:
                raise ConfigError(f"no asset_classes entry for {inst.asset_class} (instrument {inst.symbol})")
            self.books[inst.symbol] = OrderBook(inst.symbol)
        self.orders: dict[str, Order] = {}
        self.order_by_clid: dict = {}
        self.seen_cl_ord_ids: set = set()
        self.recent_content: dict = {}
        self.last_trade_price: dict = {}
        self.trades: list[Trade] = []
        self.event_log: list = []
        self._listeners: list[Callable] = []
        self._seq = itertools.count(1)
        self._oid = itertools.count(1)
        self._eid = itertools.count(1)
        self._tid = itertools.count(1)

    # ------------------------------------------------------------------ construction helpers
    @classmethod
    def from_files(cls, config_path, refdata_paths: Iterable, **kw) -> "Exchange":
        cfg = MarketConfig.from_file(config_path)
        return cls(cfg, RefDataStore.from_files(refdata_paths), **kw)

    @classmethod
    def from_project(cls, root, asset_classes: Optional[Iterable[str]] = None, **kw) -> "Exchange":
        """Load config/market_default.json and refdata/*.json under *root* (optionally filtered)."""
        root = Path(root)
        files = sorted((root / "refdata").glob("*.json"))
        store = RefDataStore()
        wanted = {a.upper() for a in asset_classes} if asset_classes else None
        for f in files:
            import json
            data = json.loads(f.read_text())
            if wanted is None or str(data.get("asset_class", "")).upper() in wanted:
                store.load_dict(data, source=str(f))
        return cls(MarketConfig.from_file(root / "config" / "market_default.json"), store, **kw)

    def subscribe(self, fn: Callable) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------------ lookups
    def instrument(self, symbol) -> Optional[Instrument]:
        return self.refdata.get(symbol)

    def ac_config(self, symbol):
        inst = self.instrument(symbol)
        return self.config.asset_classes.get(inst.asset_class) if inst else None

    def schedule_of(self, symbol) -> str:
        return self.ac_config(symbol).schedule

    def phase(self, symbol) -> Phase:
        ov = self.sessions.overrides.get(symbol)
        if ov is not None:
            return ov.phase
        return self.sessions.schedule_phase[self.schedule_of(symbol)]

    def phase_rule(self, symbol):
        return self.config.phase_rules[self.phase(symbol)]

    def symbols_on_schedule(self, schedule: str) -> list:
        return [s for s in self.books if self.schedule_of(s) == schedule]

    @staticmethod
    def content_key(cmd: NewOrder):
        return (cmd.participant, cmd.symbol, cmd.side, cmd.order_type, cmd.price, cmd.qty, cmd.tif)

    def order_status(self, participant: str, cl_ord_id: str) -> Optional[Order]:
        return self.order_by_clid.get((participant, cl_ord_id))

    def book_snapshot(self, symbol: str, depth: Optional[int] = 10) -> dict:
        snap = self.books[symbol].snapshot(depth)
        snap["phase"] = self.phase(symbol).value
        snap["last_trade_price"] = fmt(self.last_trade_price.get(symbol))
        return snap

    # ------------------------------------------------------------------ dispatcher
    def process(self, cmd) -> list:
        events: list = []
        if isinstance(cmd, NewOrder):
            self._new_order(cmd, events)
        elif isinstance(cmd, CancelOrder):
            self._cancel(cmd, events)
        elif isinstance(cmd, ReplaceOrder):
            self._replace(cmd, events)
        elif isinstance(cmd, SetPhase):
            self._set_schedule_phase(cmd.schedule, cmd.phase, cmd.reason, events)
        elif isinstance(cmd, AdvanceTime):
            self._advance_time(cmd.seconds, events)
        elif isinstance(cmd, HaltInstrument):
            self._halt(cmd, events)
        elif isinstance(cmd, ResumeInstrument):
            self._resume(cmd, events)
        else:
            raise TypeError(f"unsupported command {type(cmd).__name__}")
        return events

    def _emit(self, events: list, ev) -> None:
        if getattr(ev, "timestamp", "x") is None:
            ev.timestamp = self.clock.now()
        events.append(ev)
        self.event_log.append(ev)
        for fn in self._listeners:
            fn(ev)
        for alert in self.monitor.on_event(ev, self):
            alert.timestamp = self.clock.now()
            events.append(alert)
            self.event_log.append(alert)
            for fn in self._listeners:
                fn(alert)

    def _exec(self, o: Order, exec_type: ExecType, last_qty=Decimal(0), last_px=None, trade_id=None,
              aggressor=None, text="") -> ExecutionReport:
        return ExecutionReport(
            exec_id=f"E{next(self._eid):09d}", order_id=o.order_id, cl_ord_id=o.cl_ord_id,
            orig_cl_ord_id=o.orig_cl_ord_id, participant=o.participant, symbol=o.symbol, side=o.side,
            order_type=o.order_type, tif=o.tif, exec_type=exec_type, ord_status=o.status, qty=o.qty,
            price=o.price, last_qty=last_qty, last_px=last_px, cum_qty=o.cum_qty, leaves_qty=o.leaves_qty,
            avg_px=o.avg_px, text=text, trade_id=trade_id, aggressor=aggressor)

    # ------------------------------------------------------------------ new order
    def _new_order(self, cmd: NewOrder, events: list) -> None:
        inst = self.instrument(cmd.symbol)
        ac = self.config.asset_classes.get(inst.asset_class) if inst else None
        rej = self.validator.validate_new(cmd, inst, ac, self)
        if rej is None and inst is None:
            rej = Rejection(RejectReason.UNKNOWN_INSTRUMENT, f"unknown symbol {cmd.symbol}")
        key = (cmd.participant, cmd.cl_ord_id)
        if rej is not None:
            if (self.config.duplicate_cl_ord_id_scope == "ALL" and cmd.cl_ord_id
                    and rej.reason is not RejectReason.DUPLICATE_CL_ORD_ID):
                self.seen_cl_ord_ids.add(key)
            self._emit(events, ExecutionReport(
                exec_id=f"E{next(self._eid):09d}", order_id=None, cl_ord_id=cmd.cl_ord_id, orig_cl_ord_id=None,
                participant=cmd.participant, symbol=cmd.symbol, side=cmd.side, order_type=cmd.order_type,
                tif=cmd.tif, exec_type=ExecType.REJECTED, ord_status=OrdStatus.REJECTED, qty=cmd.qty,
                price=cmd.price, leaves_qty=Decimal(0), reject_reason=rej.reason, text=rej.text))
            return
        self.seen_cl_ord_ids.add(key)
        if ac.duplicate_order_window_ms > 0:
            self.recent_content[self.content_key(cmd)] = self.clock.now()
        order = Order(order_id=f"O{next(self._oid):09d}", cl_ord_id=cmd.cl_ord_id, participant=cmd.participant,
                      symbol=cmd.symbol, side=cmd.side, order_type=cmd.order_type, tif=cmd.tif, qty=cmd.qty,
                      price=cmd.price, seq=next(self._seq), entered_at=self.clock.now(), account=cmd.account)
        self.orders[order.order_id] = order
        self.order_by_clid[key] = order
        self._emit(events, self._exec(order, ExecType.NEW))
        mode = self.phase_rule(cmd.symbol).matching
        if mode is MatchingMode.CONTINUOUS:
            self._match_continuous(order, events)
        elif mode is MatchingMode.CALL:
            self.books[cmd.symbol].add(order)
        else:
            self._terminate(order, ExecType.EXPIRED, OrdStatus.EXPIRED, events, "no matching in current phase")

    # ------------------------------------------------------------------ continuous matching
    def _breaches_cb(self, inst: Instrument, ac, price: Decimal) -> bool:
        cb = ac.circuit_breaker
        if not cb.enabled:
            return False
        pct = inst.circuit_breaker_pct if inst.circuit_breaker_pct is not None else cb.pct
        ref = self.last_trade_price.get(inst.symbol) or inst.reference_price
        if pct is None or not ref:
            return False
        return abs(price - ref) * 100 > pct * ref

    def _crosses(self, order: Order, price: Decimal) -> bool:
        if order.order_type is OrderType.MARKET:
            return True
        return price <= order.price if order.side is Side.BUY else price >= order.price

    def _fok_fillable(self, order: Order, book: OrderBook, inst, ac) -> bool:
        stp = ac.self_trade_prevention
        need, avail = order.leaves_qty, Decimal(0)
        for price, resting in book.iter_levels(order.side.opposite):
            if not self._crosses(order, price) or self._breaches_cb(inst, ac, price):
                break
            own = [o for o in resting if o.participant == order.participant]
            if own and stp in (STPMode.CANCEL_INCOMING, STPMode.CANCEL_BOTH):
                return False                         # conservative: would self-trade before completing
            for o in resting:
                if stp is STPMode.NONE or o.participant != order.participant:
                    avail += o.leaves_qty
            if avail >= need:
                return True
        return avail >= need

    def _match_continuous(self, order: Order, events: list) -> None:
        sym = order.symbol
        book, inst, ac = self.books[sym], self.instrument(sym), self.ac_config(sym)
        algo, stp = self.algorithms[inst.asset_class], ac.self_trade_prevention
        if order.tif is TimeInForce.FOK and not self._fok_fillable(order, book, inst, ac):
            self._terminate(order, ExecType.EXPIRED, OrdStatus.EXPIRED, events, "FOK could not be filled in full")
            return
        cb_hit = False
        while order.leaves_qty > 0:
            best = book.best_price(order.side.opposite)
            if best is None or not self._crosses(order, best):
                break
            if self._breaches_cb(inst, ac, best):
                self._trigger_volatility_auction(inst, ac, best, events)
                cb_hit = True
                break
            resting = book.level(order.side.opposite, best)
            allocs = algo.allocate(resting, order.leaves_qty, inst.lot_size)
            if not allocs:
                break
            stp_hit = None
            for passive, q in allocs:
                if stp is not STPMode.NONE and passive.participant == order.participant:
                    stp_hit = passive
                    break
                if q > 0:
                    if order.side is Side.BUY:
                        self._execute(order, passive, q, best, events, "CONTINUOUS", Side.BUY)
                    else:
                        self._execute(passive, order, q, best, events, "CONTINUOUS", Side.SELL)
            if stp_hit is not None:
                if stp in (STPMode.CANCEL_RESTING, STPMode.CANCEL_BOTH):
                    self._terminate(stp_hit, ExecType.CANCELED, OrdStatus.CANCELED, events,
                                    "self-trade prevention: resting order cancelled")
                if stp in (STPMode.CANCEL_INCOMING, STPMode.CANCEL_BOTH):
                    self._terminate(order, ExecType.CANCELED, OrdStatus.CANCELED, events,
                                    "self-trade prevention: incoming order cancelled")
                    return
        if order.status in TERMINAL_STATUSES or order.leaves_qty <= 0:
            return
        if cb_hit and order.tif in (TimeInForce.DAY, TimeInForce.GTC):
            book.add(order)                          # joins the volatility auction
        elif order.order_type is OrderType.MARKET:
            self._terminate(order, ExecType.EXPIRED, OrdStatus.EXPIRED, events,
                            "market order remainder: insufficient liquidity")
        elif order.tif in (TimeInForce.IOC, TimeInForce.FOK):
            self._terminate(order, ExecType.EXPIRED, OrdStatus.EXPIRED, events, f"{order.tif.value} remainder expired")
        else:
            book.add(order)

    def _execute(self, buy: Order, sell: Order, qty: Decimal, price: Decimal, events: list, match_type: str,
                 aggressor_side: Optional[Side]) -> None:
        tid = f"T{next(self._tid):09d}"
        book = self.books[buy.symbol]
        for o in (buy, sell):
            o.cum_qty += qty
            o.leaves_qty -= qty
            o.filled_notional += qty * price
            o.status = OrdStatus.FILLED if o.leaves_qty == 0 else OrdStatus.PARTIALLY_FILLED
            if o.leaves_qty == 0 and o.order_id in book:
                book.remove(o.order_id)
        trade = Trade(trade_id=tid, symbol=buy.symbol, price=price, qty=qty, buy_order_id=buy.order_id,
                      sell_order_id=sell.order_id, buy_participant=buy.participant,
                      sell_participant=sell.participant, aggressor_side=aggressor_side, match_type=match_type)
        self.trades.append(trade)
        self.last_trade_price[buy.symbol] = price
        first, second = (sell, buy) if aggressor_side is Side.SELL else (buy, sell)
        for o in (first, second):
            aggr = None if aggressor_side is None else (o.side is aggressor_side)
            self._emit(events, self._exec(o, ExecType.TRADE, qty, price, tid, aggr))
        self._emit(events, trade)

    def _terminate(self, o: Order, exec_type: ExecType, status: OrdStatus, events: list, text: str = "") -> None:
        book = self.books[o.symbol]
        if o.order_id in book:
            book.remove(o.order_id)
        o.status = status
        o.leaves_qty = Decimal(0)
        self._emit(events, self._exec(o, exec_type, text=text))

    # ------------------------------------------------------------------ auctions
    def _uncross(self, symbol: str, events: list, reason: str) -> None:
        book, inst = self.books[symbol], self.instrument(symbol)
        if len(book) == 0:
            return
        ref = self.last_trade_price.get(symbol) or inst.reference_price
        res = compute_uncross(book, ref)
        self._emit(events, AuctionResult(symbol, res.price, res.volume, res.imbalance, reason))
        if res.volume <= 0:
            return
        p = res.price
        buys = [o for o in book.auction_queue(Side.BUY) if eligible_at(o, p)]
        sells = [o for o in book.auction_queue(Side.SELL) if eligible_at(o, p)]
        remaining, i, j = res.volume, 0, 0
        while remaining > 0:
            b, s = buys[i], sells[j]
            q = min(b.leaves_qty, s.leaves_qty, remaining)
            self._execute(b, s, q, p, events, "AUCTION", None)
            remaining -= q
            if b.leaves_qty == 0:
                i += 1
            if s.leaves_qty == 0:
                j += 1

    def _apply_phase_entry(self, symbol: str, old: Phase, new: Phase, events: list) -> None:
        rule = self.config.phase_rules[new]
        if rule.uncross_on_entry and old != new:
            self._uncross(symbol, events, f"{old.value}->{new.value}")
        book = self.books[symbol]
        if rule.matching is not MatchingMode.CALL:
            for side in (Side.BUY, Side.SELL):
                for o in list(book.market_orders[side].values()):
                    self._terminate(o, ExecType.EXPIRED, OrdStatus.EXPIRED, events,
                                    "market order not executed in auction")
        if rule.expire_day_orders_on_entry:
            self._expire_day_orders(symbol, events)

    def _expire_day_orders(self, symbol: str, events: list) -> None:
        for o in list(self.books[symbol].orders()):
            if o.tif is TimeInForce.DAY or o.order_type is OrderType.MARKET:
                self._terminate(o, ExecType.EXPIRED, OrdStatus.EXPIRED, events, "DAY order expired at close")

    def _trigger_volatility_auction(self, inst, ac, price, events) -> None:
        sym = inst.symbol
        ref = self.last_trade_price.get(sym) or inst.reference_price
        pct = inst.circuit_breaker_pct if inst.circuit_breaker_pct is not None else ac.circuit_breaker.pct
        until = self.clock.now() + dt.timedelta(seconds=ac.circuit_breaker.auction_seconds)
        old = self.phase(sym)
        self.sessions.overrides[sym] = Override(Phase.VOLATILITY_AUCTION, until, "circuit breaker")
        msg = f"{sym}: trade at {fmt(price)} would move {fmt(ref)} by more than {fmt(pct)}%"
        self._emit(events, PhaseChange(sym, "INSTRUMENT", old, Phase.VOLATILITY_AUCTION, f"circuit breaker - {msg}"))
        self._emit(events, Alert("CIRCUIT_BREAKER", "WARNING", msg, symbol=sym,
                                 data={"price": fmt(price), "reference": fmt(ref), "pct": fmt(pct),
                                       "auction_until": until.isoformat()}))

    def _end_override(self, symbol: str, events: list, reason: str) -> None:
        ov = self.sessions.overrides.pop(symbol)
        new = self.sessions.schedule_phase[self.schedule_of(symbol)]
        self._emit(events, PhaseChange(symbol, "INSTRUMENT", ov.phase, new, reason))
        self._apply_phase_entry(symbol, ov.phase, new, events)

    # ------------------------------------------------------------------ session control
    def _set_schedule_phase(self, schedule: str, new, reason: str, events: list) -> None:
        if schedule not in self.sessions.schedule_phase:
            self._emit(events, PhaseChangeRejected(schedule, None, new, RejectReason.INVALID_PHASE_TRANSITION,
                                                   f"unknown schedule {schedule}"))
            return
        old = self.sessions.schedule_phase[schedule]
        if not isinstance(new, Phase) or new is Phase.VOLATILITY_AUCTION or not self.sessions.can_transition(old, new):
            self._emit(events, PhaseChangeRejected(schedule, old, new, RejectReason.INVALID_PHASE_TRANSITION,
                                                   f"transition {old.value} -> {getattr(new, 'value', new)} not allowed"))
            self._emit(events, Alert("PHASE_TRANSITION_REJECTED", "WARNING",
                                     f"{schedule}: {old.value} -> {getattr(new, 'value', new)} rejected"))
            return
        symbols = self.symbols_on_schedule(schedule)
        old_eff = {s: self.phase(s) for s in symbols}
        self.sessions.schedule_phase[schedule] = new
        self._emit(events, PhaseChange(schedule, "SCHEDULE", old, new, reason))
        for s in symbols:
            ov = self.sessions.overrides.get(s)
            if ov is not None and ov.phase is Phase.HALTED:
                if self.config.phase_rules[new].expire_day_orders_on_entry:
                    self._expire_day_orders(s, events)
                continue
            if ov is not None:              # volatility auction is superseded by the schedule
                del self.sessions.overrides[s]
                self._emit(events, PhaseChange(s, "INSTRUMENT", ov.phase, new, "schedule transition"))
            self._apply_phase_entry(s, old_eff[s], new, events)

    def _advance_time(self, seconds, events: list) -> None:
        if not isinstance(seconds, Decimal) or seconds < 0:
            raise ValueError(f"invalid AdvanceTime seconds {seconds!r}")
        now = self.clock.now()
        target = now + dt.timedelta(seconds=float(seconds))
        due = []
        if self.auto_schedule:
            due += [(t, 0, sched, ph) for t, sched, ph in
                    self.sessions.timeline_between(now, target, self.config.trading_date)]
        due += [(ov.until, 1, sym, ov.until) for sym, ov in self.sessions.overrides.items()
                if ov.until is not None and ov.until <= target]
        for t, kind, name, payload in sorted(due, key=lambda x: (x[0], x[1], x[2])):
            if t > self.clock.now():
                self.clock.set(t)
            if kind == 0:
                self._set_schedule_phase(name, payload, "schedule", events)
            else:
                ov = self.sessions.overrides.get(name)
                if ov is not None and ov.until == payload:
                    self._end_override(name, events, "volatility auction ended")
        self.clock.set(target)

    def _halt(self, cmd: HaltInstrument, events: list) -> None:
        sym = cmd.symbol
        if sym not in self.books or self.phase(sym) is Phase.HALTED:
            self._emit(events, PhaseChangeRejected(sym, self.phase(sym) if sym in self.books else None,
                                                   Phase.HALTED, RejectReason.INVALID_PHASE_TRANSITION,
                                                   "unknown symbol or already halted"))
            return
        old = self.phase(sym)
        self.sessions.overrides[sym] = Override(Phase.HALTED, None, cmd.reason)
        self._emit(events, PhaseChange(sym, "INSTRUMENT", old, Phase.HALTED, cmd.reason))
        self._emit(events, Alert("INSTRUMENT_HALT", "WARNING", f"{sym} halted: {cmd.reason}", symbol=sym))
        self._apply_phase_entry(sym, old, Phase.HALTED, events)

    def _resume(self, cmd: ResumeInstrument, events: list) -> None:
        sym = cmd.symbol
        ov = self.sessions.overrides.get(sym)
        if ov is None or ov.phase is not Phase.HALTED:
            self._emit(events, PhaseChangeRejected(sym, self.phase(sym) if sym in self.books else None,
                                                   None, RejectReason.INVALID_PHASE_TRANSITION,
                                                   "instrument is not halted"))
            return
        self._end_override(sym, events, cmd.reason)

    # ------------------------------------------------------------------ cancel / replace
    def _lookup_for_amend(self, cmd, response_to: str, events: list) -> Optional[Order]:
        def reject(reason, text, order=None):
            self._emit(events, CancelReject(cmd.cl_ord_id, cmd.orig_cl_ord_id, cmd.participant, cmd.symbol,
                                            order.order_id if order else None,
                                            order.status if order else OrdStatus.REJECTED,
                                            response_to, reason, text))
            return None
        if not cmd.cl_ord_id or not cmd.participant or not cmd.orig_cl_ord_id:
            return reject(RejectReason.MISSING_OR_INVALID_FIELD, "cl_ord_id, orig_cl_ord_id, participant required")
        key = (cmd.participant, cmd.cl_ord_id)
        if key in self.seen_cl_ord_ids:
            return reject(RejectReason.DUPLICATE_CL_ORD_ID, f"duplicate ClOrdID {cmd.cl_ord_id}")
        if self.config.duplicate_cl_ord_id_scope == "ALL":
            self.seen_cl_ord_ids.add(key)
        order = self.order_by_clid.get((cmd.participant, cmd.orig_cl_ord_id))
        if order is None or order.symbol != cmd.symbol:
            return reject(RejectReason.UNKNOWN_ORDER, f"unknown order {cmd.orig_cl_ord_id}")
        if order.status in TERMINAL_STATUSES:
            return reject(RejectReason.TOO_LATE_TO_CANCEL, f"order is {order.status.value}", order)
        if order.cl_ord_id != cmd.orig_cl_ord_id:
            return reject(RejectReason.UNKNOWN_ORDER,
                          f"{cmd.orig_cl_ord_id} superseded by {order.cl_ord_id}", order)
        rule = self.phase_rule(order.symbol)
        allowed = rule.accept_cancel if response_to == "CANCEL" else rule.accept_amend
        if not allowed:
            return reject(RejectReason.EXCHANGE_CLOSED,
                          f"{response_to.lower()} not accepted in phase {self.phase(order.symbol).value}", order)
        return order

    def _rekey(self, order: Order, new_clid: str) -> None:
        order.orig_cl_ord_id = order.cl_ord_id
        order.cl_ord_id = new_clid
        self.order_by_clid[(order.participant, new_clid)] = order
        self.seen_cl_ord_ids.add((order.participant, new_clid))

    def _cancel(self, cmd: CancelOrder, events: list) -> None:
        order = self._lookup_for_amend(cmd, "CANCEL", events)
        if order is None:
            return
        self._rekey(order, cmd.cl_ord_id)
        self._terminate(order, ExecType.CANCELED, OrdStatus.CANCELED, events, "cancelled by participant")

    def _replace(self, cmd: ReplaceOrder, events: list) -> None:
        def reject(reason, text, order):
            self._emit(events, CancelReject(cmd.cl_ord_id, cmd.orig_cl_ord_id, cmd.participant, cmd.symbol,
                                            order.order_id, order.status, "REPLACE", reason, text))
        order = self._lookup_for_amend(cmd, "REPLACE", events)
        if order is None:
            return
        if order.order_type is OrderType.MARKET:
            return reject(RejectReason.AMEND_NOT_ALLOWED, "market orders cannot be amended", order)
        if (cmd.qty is not None and not isinstance(cmd.qty, Decimal)) or \
                (cmd.price is not None and not isinstance(cmd.price, Decimal)):
            return reject(RejectReason.MISSING_OR_INVALID_FIELD, "invalid qty/price", order)
        new_qty = cmd.qty if cmd.qty is not None else order.qty
        new_px = cmd.price if cmd.price is not None else order.price
        if new_qty == order.qty and new_px == order.price:
            return reject(RejectReason.AMEND_NOT_ALLOWED, "replace changes nothing", order)
        if new_qty <= order.cum_qty:
            return reject(RejectReason.INVALID_QUANTITY,
                          f"new qty {new_qty} must exceed filled qty {order.cum_qty}", order)
        synthetic = NewOrder(cmd.cl_ord_id, cmd.participant, cmd.symbol, order.side, new_qty, new_px,
                             order.order_type, order.tif)
        rej = self.validator.validate_amend(synthetic, self.instrument(order.symbol), self.ac_config(order.symbol), self)
        if rej is not None:
            return reject(rej.reason, rej.text, order)
        loses_priority = new_px != order.price or new_qty > order.qty
        book = self.books[order.symbol]
        if loses_priority:
            book.remove(order.order_id)
        self._rekey(order, cmd.cl_ord_id)
        order.qty, order.price = new_qty, new_px
        order.leaves_qty = new_qty - order.cum_qty
        if loses_priority:
            order.seq = next(self._seq)
            order.entered_at = self.clock.now()
        self._emit(events, self._exec(order, ExecType.REPLACED,
                                      text="priority lost" if loses_priority else "priority kept"))
        if loses_priority:
            if self.phase_rule(order.symbol).matching is MatchingMode.CONTINUOUS:
                self._match_continuous(order, events)
            else:
                book.add(order)

    # ------------------------------------------------------------------ reporting
    def summary(self) -> dict:
        live = sum(1 for o in self.orders.values() if o.is_live)
        return {"exchange": self.config.exchange_name, "mic": self.config.mic,
                "time": self.clock.now().isoformat(), "orders": len(self.orders), "live_orders": live,
                "trades": len(self.trades),
                "schedules": {k: v.value for k, v in self.sessions.schedule_phase.items()},
                "monitor": self.monitor.summary()}
