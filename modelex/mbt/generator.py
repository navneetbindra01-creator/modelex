"""Stateful, seeded order-flow generator.

Reads the model's current state (books, phases, live orders) to choose the next
command, so it reaches deep states (partial fills, amend-after-fill, cancels in
auctions, circuit breakers) that static test packs rarely hit. A configurable
share of commands is deliberately invalid to exercise every validation rule.
"""
from __future__ import annotations

import random
from decimal import Decimal
from typing import Optional

from ..types import (AdvanceTime, CancelOrder, MatchingMode, NewOrder, OrderType, Phase, ReplaceOrder, Side,
                     TimeInForce)

DEFAULT_WEIGHTS = {
    "passive_limit": 30, "aggressive_limit": 12, "market": 5, "ioc": 6, "fok": 3,
    "cancel": 13, "replace": 10, "invalid": 9, "duplicate_clid": 2, "duplicate_content": 2,
    "sweep": 1, "advance_time": 3,
}

INVALID_KINDS = ["off_tick", "bad_lot", "zero_qty", "negative_price", "outside_band", "unknown_symbol",
                 "market_with_price", "limit_without_price", "unsupported_tif", "above_max", "below_min",
                 "inactive_instrument", "bad_side", "unsupported_order_type", "unknown_cancel",
                 "bad_replace_tick"]


class OrderFlowGenerator:
    def __init__(self, exchange, asset_class: str, seed: int = 1, weights: Optional[dict] = None,
                 participants: Optional[list] = None):
        self.ex = exchange
        self.ac = exchange.config.asset_classes[asset_class.upper()]
        self.rng = random.Random(seed)
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.participants = participants or [f"FIRM_{c}" for c in "ABCDEF"]
        insts = exchange.refdata.by_asset_class(asset_class)
        today = exchange.clock.now().date()
        self.active = [i for i in insts if i.tradable and not (i.expiry and i.expiry < today)]
        self.inactive = [i for i in insts if i not in self.active]
        if not self.active:
            raise ValueError(f"no tradable instruments for {asset_class}")
        self._n = 0
        self.sent: list = []            # (participant, cl_ord_id, symbol) of generated new orders
        self.last_new: Optional[NewOrder] = None
        self.kind_counts: dict = {}

    # ------------------------------------------------------------------ helpers
    def _clid(self, participant: str) -> str:
        self._n += 1
        return f"{participant[-1]}{self._n:07d}"

    def _dec(self, lo: float, hi: float) -> Decimal:
        return Decimal(str(round(self.rng.uniform(lo, hi), 6)))

    def _band(self, inst):
        if inst.price_band_pct is None or not inst.reference_price:
            return None, None
        r, b = inst.reference_price, inst.price_band_pct / 100
        return inst.round_to_tick(r * (1 - b), "up"), inst.round_to_tick(r * (1 + b), "down")

    def _mid(self, inst) -> Decimal:
        book = self.ex.books[inst.symbol]
        bb, ba = book.best_price(Side.BUY), book.best_price(Side.SELL)
        if bb is not None and ba is not None:
            mid = (bb + ba) / 2
        else:
            mid = self.ex.last_trade_price.get(inst.symbol) or inst.reference_price
        lo, hi = self._band(inst)
        if lo is not None:   # keep the flow inside the inner part of the static collar
            r = inst.reference_price
            mid = min(max(mid, r - (r - lo) * Decimal("0.6")), r + (hi - r) * Decimal("0.6"))
        return mid

    def _price(self, inst, side: Side, aggressive: bool, spread_pct: float = 0.6) -> Decimal:
        mid = self._mid(inst)
        u = self._dec(0, spread_pct) / 100
        if aggressive:
            px = mid * (1 + u) if side is Side.BUY else mid * (1 - u)
            px = inst.round_to_tick(px, "up" if side is Side.BUY else "down")
        else:
            px = mid * (1 - u) if side is Side.BUY else mid * (1 + u)
            px = inst.round_to_tick(px, "down" if side is Side.BUY else "up")
        lo, hi = self._band(inst)
        if lo is not None:
            px = min(max(px, lo), hi)
        return px

    def _qty(self, inst, px: Optional[Decimal] = None, big: bool = False) -> Decimal:
        if inst.unique:
            return Decimal(1)
        lots = self.rng.choice([1, 1, 2, 3, 5, 8, 10, 20, 50]) * (self.rng.choice([5, 10, 20]) if big else 1)
        unit = inst.min_qty if inst.min_qty >= inst.lot_size else inst.lot_size
        if unit < 1 and unit * 100 <= (inst.max_qty or Decimal(10 ** 9)):
            unit = unit * self.rng.choice([10, 50, 100])        # fractional assets: meaningful sizes
        q = unit * lots
        if inst.max_qty is not None:
            q = min(q, inst.max_qty)
        limit = inst.max_notional if inst.max_notional is not None else self.ac.max_notional
        px = px or inst.reference_price
        if limit is not None and px:
            cap = (limit / (px * inst.multiplier)) // inst.lot_size * inst.lot_size
            q = min(q, max(cap, inst.min_qty))
        return max((q // inst.lot_size) * inst.lot_size, inst.min_qty)

    def _tifs(self, sym, prefer=None) -> list:
        rule = self.ex.phase_rule(sym)
        allowed = [t for t in self.ac.time_in_force if rule.allowed_tif is None or t in rule.allowed_tif]
        if prefer and prefer in allowed:
            return [prefer]
        return sorted(allowed, key=lambda t: t.value) or sorted(self.ac.time_in_force, key=lambda t: t.value)

    def _resting_tif(self, sym) -> TimeInForce:
        opts = [t for t in self._tifs(sym) if t in (TimeInForce.DAY, TimeInForce.GTC)]
        return self.rng.choice(opts) if opts else self.rng.choice(sorted(self.ac.time_in_force, key=lambda t: t.value))

    def _live_order(self, limit_only=False):
        for _ in range(8):
            if not self.sent:
                return None
            p, clid, sym = self.sent[self.rng.randrange(max(0, len(self.sent) - 300), len(self.sent))]
            o = self.ex.order_by_clid.get((p, clid))
            if o is not None and o.is_live and o.cl_ord_id == clid and (not limit_only or o.order_type is OrderType.LIMIT):
                return o
        return None

    def _new(self, inst, side, px, qty, otype=OrderType.LIMIT, tif=None, participant=None) -> NewOrder:
        p = participant or self.rng.choice(self.participants)
        cmd = NewOrder(self._clid(p), p, inst.symbol, side, qty, px, otype, tif or self._resting_tif(inst.symbol))
        self.sent.append((p, cmd.cl_ord_id, inst.symbol))
        self.last_new = cmd
        return cmd

    # ------------------------------------------------------------------ main entry
    def next(self):
        kinds, w = zip(*self.weights.items())
        kind = self.rng.choices(kinds, weights=w)[0]
        cmd = getattr(self, f"_g_{kind}")()
        if cmd is None:
            kind, cmd = "passive_limit", self._g_passive_limit()
        self.kind_counts[kind] = self.kind_counts.get(kind, 0) + 1
        return cmd

    def _inst(self):
        return self.rng.choice(self.active)

    def _side(self):
        return self.rng.choice([Side.BUY, Side.SELL])

    def _g_passive_limit(self):
        inst, side = self._inst(), self._side()
        px = self._price(inst, side, False)
        return self._new(inst, side, px, self._qty(inst, px))

    def _g_aggressive_limit(self):
        inst, side = self._inst(), self._side()
        px = self._price(inst, side, True, 1.0)
        return self._new(inst, side, px, self._qty(inst, px))

    def _g_market(self):
        if OrderType.MARKET not in self.ac.order_types:
            return None
        inst, side = self._inst(), self._side()
        cont = self.ex.phase_rule(inst.symbol).matching is MatchingMode.CONTINUOUS
        tif = TimeInForce.IOC if cont and TimeInForce.IOC in self._tifs(inst.symbol) else self._resting_tif(inst.symbol)
        return self._new(inst, side, None, self._qty(inst), OrderType.MARKET, tif)

    def _g_ioc(self, tif=TimeInForce.IOC):
        if tif not in self.ac.time_in_force:
            return None
        inst, side = self._inst(), self._side()
        if tif not in self._tifs(inst.symbol) and self.rng.random() < 0.8:
            return None
        px = self._price(inst, side, True, 0.8)
        return self._new(inst, side, px, self._qty(inst, px), tif=tif)

    def _g_fok(self):
        return self._g_ioc(TimeInForce.FOK)

    def _g_cancel(self):
        o = self._live_order()
        if o is None:
            return None
        if self.rng.random() < 0.05:   # occasionally cancel something already finished
            p, clid, sym = self.rng.choice(self.sent)
            return CancelOrder(self._clid(p), clid, p, sym)
        return CancelOrder(self._clid(o.participant), o.cl_ord_id, o.participant, o.symbol)

    def _g_replace(self):
        o = self._live_order(limit_only=True)
        if o is None:
            return None
        inst = self.ex.instrument(o.symbol)
        r = self.rng.random()
        qty, px = None, None
        if r < 0.4 or inst.unique:
            ticks = self.rng.choice([-3, -2, -1, 1, 2, 3])
            px = o.price + inst.tick_for(o.price) * ticks
            px = inst.round_to_tick(px, "nearest")
        elif r < 0.7:
            qty = max(o.cum_qty + inst.lot_size, o.qty - inst.lot_size * self.rng.choice([1, 2]))
            qty = max(qty, inst.min_qty)
        else:
            qty = o.qty + inst.lot_size * self.rng.choice([1, 5])
            if inst.max_qty is not None:
                qty = min(qty, inst.max_qty)
            px = self._price(inst, o.side, self.rng.random() < 0.3)
        return ReplaceOrder(self._clid(o.participant), o.cl_ord_id, o.participant, o.symbol, qty, px)

    def _g_duplicate_clid(self):
        if not self.sent:
            return None
        p, clid, sym = self.rng.choice(self.sent[-200:])
        inst = self.ex.instrument(sym)
        side = self._side()
        px = self._price(inst, side, False)
        return NewOrder(clid, p, sym, side, self._qty(inst, px), px, OrderType.LIMIT, self._resting_tif(sym))

    def _g_duplicate_content(self):
        c = self.last_new
        if c is None:
            return None
        dup = NewOrder(self._clid(c.participant), c.participant, c.symbol, c.side, c.qty, c.price, c.order_type, c.tif)
        self.sent.append((c.participant, dup.cl_ord_id, c.symbol))
        return dup

    def _g_sweep(self):
        inst, side = self._inst(), self._side()
        lo, hi = self._band(inst)
        if lo is None:
            return None
        px = hi if side is Side.BUY else lo
        tif = self._resting_tif(inst.symbol)
        return self._new(inst, side, px, self._qty(inst, px, big=True), tif=tif)

    def _g_advance_time(self):
        auctions = [ov.until for s, ov in self.ex.sessions.overrides.items()
                    if ov.until is not None and s in {i.symbol for i in self.active}]
        if auctions and self.rng.random() < 0.6:
            secs = max((min(auctions) - self.ex.clock.now()).total_seconds(), 0) + 1
            return AdvanceTime(Decimal(str(round(secs, 3))))
        return AdvanceTime(self.rng.choice([0.2, 1, 2, 5, 15, 30]))

    def _g_invalid(self):
        kind = self.rng.choice(INVALID_KINDS)
        inst, side = self._inst(), self._side()
        px = self._price(inst, side, False)
        q = self._qty(inst, px)
        p = self.rng.choice(self.participants)
        tif = self._resting_tif(inst.symbol)
        mk = lambda **kw: NewOrder(**{**dict(cl_ord_id=self._clid(p), participant=p, symbol=inst.symbol, side=side,
                                             qty=q, price=px, order_type=OrderType.LIMIT, tif=tif), **kw})
        if kind == "off_tick":
            return mk(price=px + inst.tick_for(px) / 2)
        if kind == "bad_lot":
            return mk(qty=q + inst.lot_size / 2)
        if kind == "zero_qty":
            return mk(qty=Decimal(0))
        if kind == "negative_price":
            return mk(price=-px)
        if kind == "outside_band":
            lo, hi = self._band(inst)
            if hi is None:
                return mk(price=px * 10)
            return mk(price=inst.round_to_tick(hi * Decimal("1.05"), "up") if side is Side.BUY
                      else inst.round_to_tick(lo * Decimal("0.95"), "down"))
        if kind == "unknown_symbol":
            return mk(symbol="NOSUCH-" + inst.symbol)
        if kind == "market_with_price":
            return mk(order_type=OrderType.MARKET)
        if kind == "limit_without_price":
            return mk(price=None)
        if kind == "unsupported_tif":
            bad = [t for t in TimeInForce if t not in self.ac.time_in_force]
            return mk(tif=bad[0]) if bad else mk(tif=TimeInForce.IOC) if self.ex.phase_rule(inst.symbol).matching is MatchingMode.CALL else mk(qty=Decimal(0))
        if kind == "above_max":
            return mk(qty=(inst.max_qty or Decimal(10 ** 9)) + inst.lot_size)
        if kind == "below_min":
            return mk(qty=inst.min_qty - inst.lot_size) if inst.min_qty > inst.lot_size else mk(qty=-inst.lot_size)
        if kind == "inactive_instrument":
            if not self.inactive:
                return mk(symbol="")
            i = self.rng.choice(self.inactive)
            return mk(symbol=i.symbol, price=i.reference_price, qty=i.min_qty)
        if kind == "bad_side":
            return mk(side="SHORT")
        if kind == "unsupported_order_type":
            if OrderType.MARKET not in self.ac.order_types:
                return mk(order_type=OrderType.MARKET, price=None)
            return mk(order_type="STOP")
        if kind == "unknown_cancel":
            return CancelOrder(self._clid(p), "NO-SUCH-ORDER", p, inst.symbol)
        if kind == "bad_replace_tick":
            o = self._live_order(limit_only=True)
            if o is None:
                return mk(price=px + inst.tick_for(px) / 2)
            i = self.ex.instrument(o.symbol)
            return ReplaceOrder(self._clid(o.participant), o.cl_ord_id, o.participant, o.symbol,
                                price=o.price + i.tick_for(o.price) / 2)
        raise AssertionError(kind)
