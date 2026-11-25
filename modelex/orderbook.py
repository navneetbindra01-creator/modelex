"""Central limit order book state for one instrument."""
from __future__ import annotations

from bisect import bisect_left, insort
from collections import OrderedDict
from decimal import Decimal
from typing import Iterator, Optional

from .types import Order, OrderType, Side, fmt


class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._levels: dict = {Side.BUY: {}, Side.SELL: {}}     # price -> OrderedDict[order_id, Order]
        self._prices: dict = {Side.BUY: [], Side.SELL: []}     # ascending
        self.market_orders: dict = {Side.BUY: OrderedDict(), Side.SELL: OrderedDict()}  # auction phases only
        self._index: dict[str, Order] = {}

    # ------------------------------------------------------------------ mutation
    def add(self, order: Order) -> None:
        if order.order_id in self._index:
            raise ValueError(f"order {order.order_id} already in book")
        if order.order_type is OrderType.MARKET:
            self.market_orders[order.side][order.order_id] = order
        else:
            levels = self._levels[order.side]
            lvl = levels.get(order.price)
            if lvl is None:
                lvl = OrderedDict()
                levels[order.price] = lvl
                insort(self._prices[order.side], order.price)
            lvl[order.order_id] = order
        self._index[order.order_id] = order

    def remove(self, order_id: str) -> Order:
        o = self._index.pop(order_id)
        if o.order_type is OrderType.MARKET:
            del self.market_orders[o.side][order_id]
        else:
            lvl = self._levels[o.side][o.price]
            del lvl[order_id]
            if not lvl:
                del self._levels[o.side][o.price]
                prices = self._prices[o.side]
                prices.pop(bisect_left(prices, o.price))
        return o

    # ------------------------------------------------------------------ queries
    def __contains__(self, order_id) -> bool:
        return order_id in self._index

    def __len__(self) -> int:
        return len(self._index)

    def get(self, order_id) -> Optional[Order]:
        return self._index.get(order_id)

    def prices(self, side: Side) -> list:
        p = self._prices[side]
        return list(reversed(p)) if side is Side.BUY else list(p)

    def best_price(self, side: Side) -> Optional[Decimal]:
        p = self._prices[side]
        if not p:
            return None
        return p[-1] if side is Side.BUY else p[0]

    def level(self, side: Side, price: Decimal) -> list:
        lvl = self._levels[side].get(price)
        return list(lvl.values()) if lvl else []

    def iter_levels(self, side: Side) -> Iterator:
        for p in self.prices(side):
            yield p, list(self._levels[side][p].values())

    def depth(self, side: Side, n: Optional[int] = None) -> list:
        out = []
        for p, orders in self.iter_levels(side):
            out.append((p, sum((o.leaves_qty for o in orders), Decimal(0)), len(orders)))
            if n is not None and len(out) >= n:
                break
        return out

    def priority_queue(self, side: Side) -> list:
        """Limit orders in strict price-time priority (best first)."""
        return [o for _, orders in self.iter_levels(side) for o in orders]

    def auction_queue(self, side: Side) -> list:
        """Market orders (time priority) followed by limit orders in price-time priority."""
        return list(self.market_orders[side].values()) + self.priority_queue(side)

    def market_qty(self, side: Side) -> Decimal:
        return sum((o.leaves_qty for o in self.market_orders[side].values()), Decimal(0))

    def orders(self) -> list:
        return list(self._index.values())

    def is_crossed(self) -> bool:
        bb, ba = self.best_price(Side.BUY), self.best_price(Side.SELL)
        return bb is not None and ba is not None and bb >= ba

    def snapshot(self, depth: Optional[int] = 10) -> dict:
        return {
            "symbol": self.symbol,
            "bids": [[fmt(p), fmt(q), c] for p, q, c in self.depth(Side.BUY, depth)],
            "asks": [[fmt(p), fmt(q), c] for p, q, c in self.depth(Side.SELL, depth)],
            "market_buy_qty": fmt(self.market_qty(Side.BUY)),
            "market_sell_qty": fmt(self.market_qty(Side.SELL)),
            "order_count": len(self._index),
        }
