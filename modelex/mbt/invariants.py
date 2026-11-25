"""Test oracles: properties that must hold after every step, whatever the input.

These are the heart of model-based testing. The generator explores the state
space; the invariants decide whether each reached state (and each emitted
event) is legal. The same checks can be pointed at a system under test's
event stream via the differential tester.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..types import (LIVE_STATUSES, TERMINAL_STATUSES, AdvanceTime, AuctionResult, CancelOrder, ExecType,
                     ExecutionReport, HaltInstrument, MatchingMode, NewOrder, OrderType, OrdStatus, Phase,
                     PhaseChange, PhaseChangeRejected, ReplaceOrder, ResumeInstrument, SetPhase, Side, STPMode,
                     TimeInForce, Trade, fmt)

ALLOWED_TRANSITIONS = {
    OrdStatus.NEW: {OrdStatus.NEW, OrdStatus.PARTIALLY_FILLED, OrdStatus.FILLED, OrdStatus.CANCELED,
                    OrdStatus.EXPIRED},
    OrdStatus.PARTIALLY_FILLED: {OrdStatus.PARTIALLY_FILLED, OrdStatus.FILLED, OrdStatus.CANCELED,
                                 OrdStatus.EXPIRED},
}

INVARIANTS = {
    "REJECT_HAS_REASON": "Every rejection carries a canonical reject reason and no order id",
    "STATUS_TRANSITION": "Order status follows the lifecycle state machine; nothing after a terminal state",
    "DUPLICATE_ACCEPTED": "No two accepted orders/requests share (participant, ClOrdID)",
    "CUM_QTY": "Cumulative quantity only moves on trades, by exactly last_qty",
    "QTY_CONSERVATION": "cum_qty + leaves_qty == order qty for live orders; never overfilled",
    "FOK_ALL_OR_NONE": "Fill-or-kill orders end fully filled or not filled at all",
    "TRADE_PAIRING": "Every trade has exactly one buy and one sell report with identical qty/price",
    "LIMIT_PRICE_RESPECTED": "No buy fills above its limit, no sell fills below its limit",
    "TRADE_ON_TICK_AND_LOT": "Trade prices are on tick and quantities are lot multiples",
    "AUCTION_SINGLE_PRICE": "All trades in one uncross print at the published auction price",
    "MATCHING_PHASE": "Continuous trades only in CONTINUOUS from order entry; auction trades only at phase events",
    "PRICE_TIME_PRIORITY": "Passive fills follow strict price-then-time priority (PRICE_TIME instruments)",
    "PRICE_PRIORITY": "Aggressive orders sweep best price first",
    "BOOK_NOT_CROSSED": "Best bid < best ask whenever the instrument is trading continuously (a call-phase book may stay crossed through a halt until it is uncrossed)",
    "BOOK_ONLY_LIVE": "Only live, well-formed orders rest in the book; every live order rests",
    "IOC_FOK_NEVER_REST": "IOC/FOK orders never rest",
    "MARKET_ORDER_RESTING": "Market orders rest only during auction call phases",
    "DAY_EXPIRED_AT_CLOSE": "No DAY order survives into CLOSED",
    "UNIQUE_ITEM": "Unique collectibles only ever carry quantity 1",
    "PHASE_TRANSITION": "Rejected transitions have no effect; applied transitions are legal",
}


@dataclass
class Violation:
    step: int
    invariant: str
    message: str


class InvariantChecker:
    def __init__(self, exchange, full_check_every: int = 100):
        self.ex = exchange
        self.full_check_every = full_check_every
        self.status: dict = {}
        self.cum: dict = {}
        self.accepted: set = set()
        self.violations: list = []
        self.checks_run = 0
        self._pre: dict = {}

    # ------------------------------------------------------------------ pre-step snapshot
    def before(self, cmd) -> None:
        ex = self.ex
        pre = {"phases": {s: ex.phase(s) for s in ex.books},
               "sched": dict(ex.sessions.schedule_phase)}
        sym = getattr(cmd, "symbol", None)
        if isinstance(cmd, (NewOrder, ReplaceOrder)) and isinstance(sym, str) and sym in ex.books:
            side = cmd.side if isinstance(cmd, NewOrder) else None
            if isinstance(cmd, ReplaceOrder):
                o = ex.order_by_clid.get((cmd.participant, cmd.orig_cl_ord_id))
                side = o.side if o else None
            if isinstance(side, Side):
                ac = ex.ac_config(sym)
                pre["aggr_side"] = side
                if ac.matching_algorithm == "PRICE_TIME":
                    pre["queue"] = [(o.order_id, o.participant) for o in ex.books[sym].priority_queue(side.opposite)]
                    pre["stp"] = ac.self_trade_prevention
                    pre["participant"] = cmd.participant
        self._pre = pre

    # ------------------------------------------------------------------ post-step checks
    def after(self, step: int, cmd, events: list) -> list:
        ex, pre = self.ex, self._pre
        found = []

        def bad(inv, msg):
            found.append(Violation(step, inv, msg))

        touched, trades_by_id, passive_fills, last_auction = set(), defaultdict(list), [], {}
        full = isinstance(cmd, (SetPhase, AdvanceTime, HaltInstrument, ResumeInstrument)) or \
            (self.full_check_every and step % self.full_check_every == 0)

        for ev in events:
            if isinstance(ev, ExecutionReport):
                if isinstance(ev.symbol, str):
                    touched.add(ev.symbol)
                if ev.exec_type is ExecType.REJECTED:
                    if ev.reject_reason is None or ev.order_id is not None:
                        bad("REJECT_HAS_REASON", f"{ev.cl_ord_id}: reason={ev.reject_reason} order_id={ev.order_id}")
                    continue
                oid, prev = ev.order_id, self.status.get(ev.order_id)
                key = (ev.participant, ev.cl_ord_id)
                if ev.exec_type is ExecType.NEW:
                    if prev is not None:
                        bad("STATUS_TRANSITION", f"{oid}: NEW after {prev.value}")
                    if key in self.accepted:
                        bad("DUPLICATE_ACCEPTED", f"{key} accepted twice")
                    self.accepted.add(key)
                else:
                    if prev is None:
                        bad("STATUS_TRANSITION", f"{oid}: {ev.exec_type.value} before NEW")
                    elif ev.ord_status not in ALLOWED_TRANSITIONS.get(prev, set()):
                        bad("STATUS_TRANSITION", f"{oid}: {prev.value} -> {ev.ord_status.value} via {ev.exec_type.value}")
                    if ev.exec_type in (ExecType.REPLACED, ExecType.CANCELED) and ev.orig_cl_ord_id is not None \
                            and ev.cl_ord_id != ev.orig_cl_ord_id and key not in self.accepted:
                        self.accepted.add(key)
                prev_cum = self.cum.get(oid, 0)
                if ev.exec_type is ExecType.TRADE:
                    if ev.last_qty <= 0 or ev.cum_qty != prev_cum + ev.last_qty:
                        bad("CUM_QTY", f"{oid}: cum {fmt(prev_cum)} + last {fmt(ev.last_qty)} != {fmt(ev.cum_qty)}")
                    trades_by_id[ev.trade_id].append(ev)
                    if ev.aggressor is False:
                        passive_fills.append(ev)
                elif ev.cum_qty != prev_cum:
                    bad("CUM_QTY", f"{oid}: cum changed on {ev.exec_type.value}")
                if ev.cum_qty > ev.qty:
                    bad("QTY_CONSERVATION", f"{oid}: overfilled {fmt(ev.cum_qty)} > {fmt(ev.qty)}")
                if ev.ord_status in LIVE_STATUSES and ev.cum_qty + ev.leaves_qty != ev.qty:
                    bad("QTY_CONSERVATION", f"{oid}: cum+leaves != qty")
                if ev.ord_status is OrdStatus.FILLED and ev.cum_qty != ev.qty:
                    bad("QTY_CONSERVATION", f"{oid}: FILLED with cum {fmt(ev.cum_qty)} != qty {fmt(ev.qty)}")
                if ev.tif is TimeInForce.FOK and ev.ord_status in TERMINAL_STATUSES and ev.cum_qty not in (0, ev.qty):
                    bad("FOK_ALL_OR_NONE", f"{oid}: FOK terminal with partial fill {fmt(ev.cum_qty)}/{fmt(ev.qty)}")
                if ev.exec_type is not ExecType.REJECTED:
                    inst = ex.instrument(ev.symbol)
                    if inst is not None and inst.unique and ev.qty != 1:
                        bad("UNIQUE_ITEM", f"{oid}: unique item with qty {fmt(ev.qty)}")
                self.status[oid], self.cum[oid] = ev.ord_status, ev.cum_qty
            elif isinstance(ev, Trade):
                touched.add(ev.symbol)
                inst = ex.instrument(ev.symbol)
                if not inst.is_on_tick(ev.price) or not inst.is_lot_multiple(ev.qty) or ev.qty <= 0:
                    bad("TRADE_ON_TICK_AND_LOT", f"{ev.trade_id}: {fmt(ev.qty)} @ {fmt(ev.price)}")
                if ev.match_type == "AUCTION":
                    if ev.price != last_auction.get(ev.symbol):
                        bad("AUCTION_SINGLE_PRICE", f"{ev.trade_id}: {fmt(ev.price)} != auction "
                                                    f"{fmt(last_auction.get(ev.symbol))}")
                    if isinstance(cmd, (NewOrder, CancelOrder, ReplaceOrder)):
                        bad("MATCHING_PHASE", f"{ev.trade_id}: auction trade triggered by order entry")
                else:
                    if not isinstance(cmd, (NewOrder, ReplaceOrder)):
                        bad("MATCHING_PHASE", f"{ev.trade_id}: continuous trade from {type(cmd).__name__}")
                    elif pre["phases"].get(ev.symbol) is not Phase.CONTINUOUS:
                        bad("MATCHING_PHASE", f"{ev.trade_id}: continuous trade in {pre['phases'].get(ev.symbol)}")
            elif isinstance(ev, AuctionResult):
                last_auction[ev.symbol] = ev.price
            elif isinstance(ev, PhaseChangeRejected):
                if isinstance(cmd, SetPhase) and ex.sessions.schedule_phase.get(cmd.schedule) != \
                        pre["sched"].get(cmd.schedule):
                    bad("PHASE_TRANSITION", f"rejected transition changed {cmd.schedule}")
            elif isinstance(ev, PhaseChange):
                full = True
                if ev.scope_type == "SCHEDULE" and not ex.sessions.can_transition(ev.old_phase, ev.new_phase):
                    bad("PHASE_TRANSITION", f"illegal {ev.old_phase.value}->{ev.new_phase.value} applied")

        # ---- trade pairing and limit prices
        for tid, reps in trades_by_id.items():
            sides = sorted(str(r.side) for r in reps)
            if len(reps) != 2 or sides != ["BUY", "SELL"]:
                bad("TRADE_PAIRING", f"{tid}: {len(reps)} reports, sides {sides}")
                continue
            buy = reps[0] if reps[0].side is Side.BUY else reps[1]
            sell = reps[1] if buy is reps[0] else reps[0]
            if buy.last_qty != sell.last_qty or buy.last_px != sell.last_px:
                bad("TRADE_PAIRING", f"{tid}: buy/sell disagree")
            if buy.order_type is OrderType.LIMIT and buy.price < buy.last_px:
                bad("LIMIT_PRICE_RESPECTED", f"{tid}: buy limit {fmt(buy.price)} < {fmt(buy.last_px)}")
            if sell.order_type is OrderType.LIMIT and sell.price > sell.last_px:
                bad("LIMIT_PRICE_RESPECTED", f"{tid}: sell limit {fmt(sell.price)} > {fmt(sell.last_px)}")

        # ---- price priority (all algorithms) and price-time priority (FIFO)
        if passive_fills and "aggr_side" in pre:
            pxs = [ev.last_px for ev in passive_fills]
            ordered = pxs == sorted(pxs) if pre["aggr_side"] is Side.BUY else pxs == sorted(pxs, reverse=True)
            if not ordered:
                bad("PRICE_PRIORITY", f"sweep prices out of order: {[fmt(p) for p in pxs]}")
        if passive_fills and "queue" in pre:
            stp, part = pre["stp"], pre["participant"]
            eligible = [oid for oid, p in pre["queue"] if not (stp is not STPMode.NONE and p == part)]
            pos = {oid: i for i, oid in enumerate(eligible)}
            last = -1
            for ev in passive_fills:
                if ev.order_id not in pos:
                    bad("PRICE_TIME_PRIORITY", f"{ev.order_id} filled but was not eligible in the queue")
                    last = -1
                    break
                if pos[ev.order_id] < last:
                    bad("PRICE_TIME_PRIORITY", f"{ev.order_id} filled out of queue order")
                    break
                last = pos[ev.order_id]
            for oid in eligible[:max(last, 0)]:
                if ex.orders[oid].status is not OrdStatus.FILLED:
                    bad("PRICE_TIME_PRIORITY", f"{oid} was ahead in the queue but not fully filled")
                    break

        # ---- book state
        symbols = list(ex.books) if full else [s for s in touched if s in ex.books]
        for sym in symbols:
            self._check_book(sym, bad)
        if full:
            for o in ex.orders.values():
                if o.is_live and o.order_id not in ex.books[o.symbol]:
                    bad("BOOK_ONLY_LIVE", f"{o.order_id} is live ({o.status.value}) but not in the book")
        self.checks_run += 1
        self.violations.extend(found)
        return found

    def _check_book(self, sym, bad) -> None:
        ex = self.ex
        book, inst, ph = ex.books[sym], ex.instrument(sym), ex.phase(sym)
        rule = ex.config.phase_rules[ph]
        if rule.matching is MatchingMode.CONTINUOUS and book.is_crossed():
            bad("BOOK_NOT_CROSSED", f"{sym} crossed in {ph.value}: bid {fmt(book.best_price(Side.BUY))} "
                                    f">= ask {fmt(book.best_price(Side.SELL))}")
        for o in book.orders():
            if not o.is_live or o.leaves_qty <= 0 or o.cum_qty + o.leaves_qty != o.qty:
                bad("BOOK_ONLY_LIVE", f"{sym} {o.order_id}: status {o.status.value} leaves {fmt(o.leaves_qty)}")
            if o.tif in (TimeInForce.IOC, TimeInForce.FOK):
                bad("IOC_FOK_NEVER_REST", f"{sym} {o.order_id} {o.tif.value} resting")
            if o.order_type is OrderType.MARKET and rule.matching is not MatchingMode.CALL:
                bad("MARKET_ORDER_RESTING", f"{sym} {o.order_id} market order resting in {ph.value}")
            if o.order_type is OrderType.LIMIT and not inst.is_on_tick(o.price):
                bad("BOOK_ONLY_LIVE", f"{sym} {o.order_id} resting off-tick {fmt(o.price)}")
            if not inst.is_lot_multiple(o.leaves_qty):
                bad("BOOK_ONLY_LIVE", f"{sym} {o.order_id} leaves not a lot multiple")
            if ph is Phase.CLOSED and o.tif is TimeInForce.DAY:
                bad("DAY_EXPIRED_AT_CLOSE", f"{sym} {o.order_id} DAY order resting while CLOSED")
            if inst.unique and o.qty != 1:
                bad("UNIQUE_ITEM", f"{sym} {o.order_id} qty {fmt(o.qty)}")
