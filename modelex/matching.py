"""Matching algorithms.

Continuous matching walks the opposite side level by level (best price first,
trade at the resting price). *Within* a price level the quantity is shared out
by a pluggable ``AllocationAlgorithm``:

* ``PRICE_TIME`` - strict FIFO (equities, crypto, collectibles by default)
* ``PRO_RATA``   - proportional to resting size, lot-rounded, FIFO remainder
                   (common on futures / commodities)

Register your own with ``@register_algorithm("MY_ALGO")``.

Auctions (opening, closing, volatility) use ``compute_uncross``: the single
price that maximises executable volume, then minimises imbalance, then follows
market pressure, then sits closest to the reference price.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .orderbook import OrderBook
from .types import Order, Side

ALGORITHMS: dict = {}


def register_algorithm(name: str):
    def deco(cls):
        cls.name = name
        ALGORITHMS[name.upper()] = cls
        return cls
    return deco


def get_algorithm(name: str) -> "AllocationAlgorithm":
    try:
        return ALGORITHMS[name.upper()]()
    except KeyError:
        raise KeyError(f"unknown matching algorithm '{name}'. Registered: {sorted(ALGORITHMS)}") from None


class AllocationAlgorithm(ABC):
    name = "BASE"

    @abstractmethod
    def allocate(self, resting: list, qty: Decimal, lot: Decimal) -> list:
        """Return [(order, fill_qty), ...] in execution order. Sum must be <= qty."""


@register_algorithm("PRICE_TIME")
class PriceTimeFIFO(AllocationAlgorithm):
    def allocate(self, resting, qty, lot):
        out, remaining = [], qty
        for o in resting:
            if remaining <= 0:
                break
            q = min(o.leaves_qty, remaining)
            out.append((o, q))
            remaining -= q
        return out


@register_algorithm("PRO_RATA")
class ProRata(AllocationAlgorithm):
    def allocate(self, resting, qty, lot):
        total = sum((o.leaves_qty for o in resting), Decimal(0))
        if total <= 0:
            return []
        if qty >= total:
            return [(o, o.leaves_qty) for o in resting]
        alloc = {}
        for o in resting:
            share = (o.leaves_qty * qty / total) // lot * lot
            alloc[o.order_id] = min(share, o.leaves_qty)
        remainder = qty - sum(alloc.values())
        for o in resting:                      # FIFO remainder
            if remainder <= 0:
                break
            extra = min(o.leaves_qty - alloc[o.order_id], remainder)
            alloc[o.order_id] += extra
            remainder -= extra
        return [(o, alloc[o.order_id]) for o in resting if alloc[o.order_id] > 0]


@dataclass
class UncrossResult:
    price: Optional[Decimal]
    volume: Decimal
    imbalance: Decimal


def compute_uncross(book: OrderBook, reference_price: Optional[Decimal]) -> UncrossResult:
    bids = book.depth(Side.BUY)
    asks = book.depth(Side.SELL)
    mb, ms = book.market_qty(Side.BUY), book.market_qty(Side.SELL)
    prices = sorted({p for p, _, _ in bids} | {p for p, _, _ in asks})
    if not prices:
        if mb > 0 and ms > 0 and reference_price:
            prices = [reference_price]
        else:
            return UncrossResult(None, Decimal(0), mb - ms)
    best, best_key = [], None
    for p in prices:
        bv = mb + sum((q for bp, q, _ in bids if bp >= p), Decimal(0))
        sv = ms + sum((q for ap, q, _ in asks if ap <= p), Decimal(0))
        ev, imb = min(bv, sv), bv - sv
        key = (ev, -abs(imb))
        if best_key is None or key > best_key:
            best_key, best = key, [(p, ev, imb)]
        elif key == best_key:
            best.append((p, ev, imb))
    if best_key[0] <= 0:
        return UncrossResult(None, Decimal(0), best[0][2])
    if len(best) == 1:
        p, ev, imb = best[0]
    elif all(c[2] > 0 for c in best):          # buy pressure -> highest price
        p, ev, imb = max(best, key=lambda c: c[0])
    elif all(c[2] < 0 for c in best):          # sell pressure -> lowest price
        p, ev, imb = min(best, key=lambda c: c[0])
    else:
        ref = reference_price if reference_price is not None else (best[0][0] + best[-1][0]) / 2
        p, ev, imb = min(best, key=lambda c: (abs(c[0] - ref), c[0]))
    return UncrossResult(p, ev, imb)


def eligible_at(order: Order, price: Decimal) -> bool:
    if order.price is None:            # market order
        return True
    return order.price >= price if order.side is Side.BUY else order.price <= price
