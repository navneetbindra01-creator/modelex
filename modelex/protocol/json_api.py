"""JSON (REST / WebSocket style) mapping, typical of crypto and digital-asset venues.

Inbound::  {"op": "new", "clientOrderId": "...", "account": "...", "symbol": "...", "side": "buy",
            "type": "limit", "timeInForce": "GTC", "quantity": "0.5", "price": "65000"}
           {"op": "cancel", "clientOrderId": "...", "origClientOrderId": "...", "account": "...", "symbol": "..."}
           {"op": "amend",  ... "quantity"/"price"}
Outbound:: {"event": "orderUpdate", "execType": "...", "status": "...", "rejectReason": "...", ...}
"""
from __future__ import annotations

import json
from typing import Optional

from ..types import CancelOrder, CancelReject, ExecutionReport, NewOrder, ReplaceOrder, fmt
from .base import ProtocolMapper, deep_merge, register_mapper
from .fix44 import fmt_s

DEFAULT_JSON_MAP = {
    "side": {"BUY": "buy", "SELL": "sell"},
    "ord_type": {"LIMIT": "limit", "MARKET": "market"},
    "time_in_force": {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC", "FOK": "FOK"},
    "exec_type": {"NEW": "new", "TRADE": "trade", "CANCELED": "canceled", "REPLACED": "amended",
                  "REJECTED": "rejected", "EXPIRED": "expired"},
    "ord_status": {"NEW": "open", "PARTIALLY_FILLED": "partially_filled", "FILLED": "filled",
                   "CANCELED": "canceled", "REJECTED": "rejected", "EXPIRED": "expired"},
    "reject_reason": {},          # canonical -> venue string; unmapped reasons pass through
}


def _inv(d):
    return {v: k for k, v in d.items()}


@register_mapper("JSON")
class JsonMapper(ProtocolMapper):
    def __init__(self, mapping: Optional[dict] = None):
        self.map = deep_merge(DEFAULT_JSON_MAP, mapping or {})
        self._inv = {k: _inv(v) for k, v in self.map.items() if isinstance(v, dict)}

    def _c(self, table, v):
        key = getattr(v, "value", v)
        return self.map[table].get(key, key)

    def _d(self, table, v):
        return self._inv[table].get(v, v) if v is not None else None

    def decode_command(self, raw):
        m = json.loads(raw) if isinstance(raw, str) else raw
        op = m.get("op")
        if op == "new":
            return NewOrder(m.get("clientOrderId"), m.get("account"), m.get("symbol"), self._d("side", m.get("side")),
                            m.get("quantity"), m.get("price"), self._d("ord_type", m.get("type", "limit")),
                            self._d("time_in_force", m.get("timeInForce", "GTC")))
        if op == "cancel":
            return CancelOrder(m.get("clientOrderId"), m.get("origClientOrderId"), m.get("account"), m.get("symbol"))
        if op == "amend":
            return ReplaceOrder(m.get("clientOrderId"), m.get("origClientOrderId"), m.get("account"),
                                m.get("symbol"), m.get("quantity"), m.get("price"))
        raise ValueError(f"unsupported op {op!r}")

    def encode_command(self, cmd):
        if isinstance(cmd, NewOrder):
            m = {"op": "new", "clientOrderId": cmd.cl_ord_id, "account": cmd.participant, "symbol": cmd.symbol,
                 "side": self._c("side", cmd.side), "type": self._c("ord_type", cmd.order_type),
                 "timeInForce": self._c("time_in_force", cmd.tif), "quantity": fmt(cmd.qty), "price": fmt(cmd.price)}
        elif isinstance(cmd, CancelOrder):
            m = {"op": "cancel", "clientOrderId": cmd.cl_ord_id, "origClientOrderId": cmd.orig_cl_ord_id,
                 "account": cmd.participant, "symbol": cmd.symbol}
        elif isinstance(cmd, ReplaceOrder):
            m = {"op": "amend", "clientOrderId": cmd.cl_ord_id, "origClientOrderId": cmd.orig_cl_ord_id,
                 "account": cmd.participant, "symbol": cmd.symbol, "quantity": fmt(cmd.qty), "price": fmt(cmd.price)}
        else:
            raise ValueError(f"{type(cmd).__name__} has no JSON order-entry representation")
        return json.dumps({k: v for k, v in m.items() if v is not None})

    def encode_event(self, ev) -> Optional[str]:
        if isinstance(ev, ExecutionReport):
            m = {"event": "orderUpdate", "orderId": ev.order_id, "clientOrderId": fmt(ev.cl_ord_id),
                 "origClientOrderId": ev.orig_cl_ord_id, "account": fmt(ev.participant), "symbol": fmt(ev.symbol),
                 "side": self._c("side", ev.side), "type": self._c("ord_type", ev.order_type),
                 "timeInForce": self._c("time_in_force", ev.tif), "quantity": fmt(ev.qty), "price": fmt(ev.price),
                 "execType": self._c("exec_type", ev.exec_type), "status": self._c("ord_status", ev.ord_status),
                 "lastQty": fmt(ev.last_qty), "lastPrice": fmt(ev.last_px), "filledQty": fmt(ev.cum_qty),
                 "remainingQty": fmt(ev.leaves_qty), "avgPrice": fmt(ev.avg_px), "tradeId": ev.trade_id,
                 "isMaker": None if ev.aggressor is None else (not ev.aggressor),
                 "rejectReason": self._c("reject_reason", ev.reject_reason) if ev.reject_reason else None,
                 "reasonCode": ev.reject_reason.value if ev.reject_reason else None,
                 "text": ev.text or None, "ts": ev.timestamp.isoformat() if ev.timestamp else None}
        elif isinstance(ev, CancelReject):
            m = {"event": "requestRejected", "request": "cancel" if ev.response_to == "CANCEL" else "amend",
                 "clientOrderId": fmt(ev.cl_ord_id), "origClientOrderId": fmt(ev.orig_cl_ord_id),
                 "account": fmt(ev.participant), "symbol": fmt(ev.symbol), "orderId": ev.order_id,
                 "rejectReason": self._c("reject_reason", ev.reject_reason), "reasonCode": ev.reject_reason.value,
                 "text": ev.text or None, "ts": ev.timestamp.isoformat() if ev.timestamp else None}
        else:
            return None
        return json.dumps({k: v for k, v in m.items() if v is not None})

    def decode_report(self, raw) -> Optional[dict]:
        m = json.loads(raw) if isinstance(raw, str) else raw
        if m.get("event") == "orderUpdate":
            return {"kind": "EXEC", "exec_type": self._d("exec_type", m.get("execType")),
                    "ord_status": self._d("ord_status", m.get("status")), "cl_ord_id": m.get("clientOrderId"),
                    "orig_cl_ord_id": m.get("origClientOrderId"), "participant": m.get("account"),
                    "symbol": m.get("symbol"), "side": self._d("side", m.get("side")),
                    "last_qty": fmt_s(m.get("lastQty", "0")), "last_px": fmt_s(m.get("lastPrice")),
                    "cum_qty": fmt_s(m.get("filledQty", "0")), "leaves_qty": fmt_s(m.get("remainingQty", "0")),
                    "reject_reason": m.get("reasonCode")}
        if m.get("event") == "requestRejected":
            return {"kind": "CXL_REJ", "cl_ord_id": m.get("clientOrderId"), "orig_cl_ord_id": m.get("origClientOrderId"),
                    "participant": m.get("account"), "symbol": m.get("symbol"),
                    "response_to": "CANCEL" if m.get("request") == "cancel" else "REPLACE",
                    "reject_reason": m.get("reasonCode")}
        return None
