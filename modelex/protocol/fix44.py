"""FIX 4.4 order-entry mapping (NewOrderSingle / OrderCancelRequest /
OrderCancelReplaceRequest in; ExecutionReport / OrderCancelReject out).

All code tables are overridable via ``protocol_maps/fix44.json`` so the model
can mirror a specific venue's Rules of Engagement.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ..types import (CancelOrder, CancelReject, ExecutionReport, NewOrder, ReplaceOrder, fmt)
from .base import ProtocolMapper, deep_merge, register_mapper

SOH = "\x01"

DEFAULT_FIX44_MAP = {
    "side": {"BUY": "1", "SELL": "2"},
    "ord_type": {"MARKET": "1", "LIMIT": "2"},
    "time_in_force": {"DAY": "0", "GTC": "1", "IOC": "3", "FOK": "4"},
    "exec_type": {"NEW": "0", "TRADE": "F", "CANCELED": "4", "REPLACED": "5", "REJECTED": "8", "EXPIRED": "C"},
    "ord_status": {"NEW": "0", "PARTIALLY_FILLED": "1", "FILLED": "2", "CANCELED": "4", "REJECTED": "8",
                   "EXPIRED": "C"},
    "ord_rej_reason": {"default": "99"},
    "cxl_rej_reason": {"default": "99"},
    "cxl_rej_response_to": {"CANCEL": "1", "REPLACE": "2"},
    "reason_in_text": True,
    "participant_tag": "49",
}


def _inv(d: dict) -> dict:
    return {v: k for k, v in d.items() if k != "default"}


@register_mapper("FIX44")
class Fix44Mapper(ProtocolMapper):
    def __init__(self, mapping: Optional[dict] = None, sender_comp_id: str = "MODELEX",
                 begin_string: str = "FIX.4.4"):
        self.map = deep_merge(DEFAULT_FIX44_MAP, mapping or {})
        self.sender_comp_id = sender_comp_id
        self.begin_string = begin_string
        self._seq = defaultdict(int)
        self._inv = {k: _inv(v) for k, v in self.map.items() if isinstance(v, dict)}

    # ------------------------------------------------------------------ framing
    def build(self, msg_type: str, fields: list, sender: str, target: str, sending_time: str = "") -> str:
        self._seq[(sender, target)] += 1
        hdr = [("35", msg_type), ("49", sender), ("56", target), ("34", str(self._seq[(sender, target)]))]
        if sending_time:
            hdr.append(("52", sending_time))
        body = "".join(f"{t}={v}{SOH}" for t, v in hdr + [(t, v) for t, v in fields if v is not None and v != ""])
        head = f"8={self.begin_string}{SOH}9={len(body.encode())}{SOH}"
        cks = sum((head + body).encode()) % 256
        return f"{head}{body}10={cks:03d}{SOH}"

    @staticmethod
    def parse(raw: str, verify: bool = True) -> dict:
        parts = [p for p in raw.split(SOH) if p]
        tags = {}
        for p in parts:
            t, _, v = p.partition("=")
            tags[t] = v
        if verify and "10" in tags:
            body = raw[: raw.rindex(f"10={tags['10']}{SOH}")]
            if sum(body.encode()) % 256 != int(tags["10"]):
                raise ValueError("FIX checksum mismatch")
            if "9" in tags:
                start = raw.index(f"9={tags['9']}{SOH}") + len(f"9={tags['9']}{SOH}")
                if len(body[start:].encode()) != int(tags["9"]):
                    raise ValueError("FIX BodyLength mismatch")
        return tags

    @staticmethod
    def _ts(ev) -> str:
        t = getattr(ev, "timestamp", None)
        return t.strftime("%Y%m%d-%H:%M:%S.") + f"{t.microsecond // 1000:03d}" if t else ""

    def _code(self, table: str, v) -> str:
        key = getattr(v, "value", v)
        return self.map[table].get(key, str(key) if key is not None else "")

    def _decode_code(self, table: str, code):
        return self._inv[table].get(code, code) if code is not None else None

    # ------------------------------------------------------------------ inbound
    def decode_command(self, raw: str):
        t = self.parse(raw)
        mt = t.get("35")
        participant = t.get(self.map["participant_tag"]) or t.get("49")
        if mt == "D":
            return NewOrder(cl_ord_id=t.get("11"), participant=participant, symbol=t.get("55"),
                            side=self._decode_code("side", t.get("54")), qty=t.get("38"), price=t.get("44"),
                            order_type=self._decode_code("ord_type", t.get("40", "2")),
                            tif=self._decode_code("time_in_force", t.get("59", "0")), account=t.get("1"))
        if mt == "F":
            return CancelOrder(t.get("11"), t.get("41"), participant, t.get("55"))
        if mt == "G":
            return ReplaceOrder(t.get("11"), t.get("41"), participant, t.get("55"), qty=t.get("38"),
                                price=t.get("44"))
        raise ValueError(f"unsupported FIX MsgType {mt!r}")

    def encode_command(self, cmd, target: str = "MODELEX") -> str:
        p = cmd.participant
        if isinstance(cmd, NewOrder):
            f = [("11", cmd.cl_ord_id), ("1", cmd.account), ("55", cmd.symbol), ("54", self._code("side", cmd.side)),
                 ("38", fmt(cmd.qty)), ("40", self._code("ord_type", cmd.order_type)), ("44", fmt(cmd.price)),
                 ("59", self._code("time_in_force", cmd.tif))]
            return self.build("D", f, p, target)
        if isinstance(cmd, CancelOrder):
            return self.build("F", [("11", cmd.cl_ord_id), ("41", cmd.orig_cl_ord_id), ("55", cmd.symbol)], p, target)
        if isinstance(cmd, ReplaceOrder):
            f = [("11", cmd.cl_ord_id), ("41", cmd.orig_cl_ord_id), ("55", cmd.symbol), ("38", fmt(cmd.qty)),
                 ("44", fmt(cmd.price))]
            return self.build("G", f, p, target)
        raise ValueError(f"{type(cmd).__name__} has no FIX order-entry representation")

    # ------------------------------------------------------------------ outbound
    def _text(self, reason, text) -> str:
        if reason is not None and self.map.get("reason_in_text", True):
            return f"{reason.value}: {text}" if text else reason.value
        return text

    def encode_event(self, ev) -> Optional[str]:
        if isinstance(ev, ExecutionReport):
            f = [("37", ev.order_id or "NONE"), ("11", fmt(ev.cl_ord_id)), ("41", ev.orig_cl_ord_id),
                 ("17", ev.exec_id), ("150", self._code("exec_type", ev.exec_type)),
                 ("39", self._code("ord_status", ev.ord_status)), ("55", fmt(ev.symbol)),
                 ("54", self._code("side", ev.side)), ("38", fmt(ev.qty)),
                 ("40", self._code("ord_type", ev.order_type)), ("44", fmt(ev.price)),
                 ("59", self._code("time_in_force", ev.tif)),
                 ("32", fmt(ev.last_qty) or "0"), ("31", fmt(ev.last_px)), ("14", fmt(ev.cum_qty) or "0"),
                 ("151", fmt(ev.leaves_qty) or "0"), ("6", fmt(ev.avg_px) or "0"), ("880", ev.trade_id),
                 ("1057", None if ev.aggressor is None else ("Y" if ev.aggressor else "N")),
                 ("60", self._ts(ev))]
            if ev.reject_reason is not None:
                rej = self.map["ord_rej_reason"]
                f.append(("103", rej.get(ev.reject_reason.value, rej.get("default", "99"))))
            f.append(("58", self._text(ev.reject_reason, ev.text)))
            return self.build("8", f, self.sender_comp_id, fmt(ev.participant) or "", self._ts(ev))
        if isinstance(ev, CancelReject):
            rej = self.map["cxl_rej_reason"]
            f = [("37", ev.order_id or "NONE"), ("11", fmt(ev.cl_ord_id)), ("41", fmt(ev.orig_cl_ord_id)),
                 ("39", self._code("ord_status", ev.ord_status)),
                 ("434", self.map["cxl_rej_response_to"][ev.response_to]),
                 ("102", rej.get(ev.reject_reason.value, rej.get("default", "99"))), ("55", fmt(ev.symbol)),
                 ("58", self._text(ev.reject_reason, ev.text)), ("60", self._ts(ev))]
            return self.build("9", f, self.sender_comp_id, fmt(ev.participant) or "", self._ts(ev))
        return None

    def _reason_from_text(self, text: Optional[str]) -> Optional[str]:
        if not text or not self.map.get("reason_in_text", True):
            return None
        head = text.split(":", 1)[0].strip()
        return head if head.isupper() and " " not in head else None

    def decode_report(self, raw: str) -> Optional[dict]:
        t = self.parse(raw)
        mt = t.get("35")
        if mt == "8":
            et = self._decode_code("exec_type", t.get("150"))
            return {"kind": "EXEC", "exec_type": et, "ord_status": self._decode_code("ord_status", t.get("39")),
                    "cl_ord_id": t.get("11"), "orig_cl_ord_id": t.get("41"), "participant": t.get("56"),
                    "symbol": t.get("55"), "side": self._decode_code("side", t.get("54")),
                    "last_qty": fmt_s(t.get("32", "0")), "last_px": fmt_s(t.get("31")),
                    "cum_qty": fmt_s(t.get("14", "0")), "leaves_qty": fmt_s(t.get("151", "0")),
                    "reject_reason": self._reason_from_text(t.get("58")) if et == "REJECTED" else None}
        if mt == "9":
            inv434 = _inv(self.map["cxl_rej_response_to"])
            return {"kind": "CXL_REJ", "cl_ord_id": t.get("11"), "orig_cl_ord_id": t.get("41"),
                    "participant": t.get("56"), "symbol": t.get("55"), "response_to": inv434.get(t.get("434")),
                    "reject_reason": self._reason_from_text(t.get("58"))}
        return None


def fmt_s(s: Optional[str]) -> Optional[str]:
    from decimal import Decimal, InvalidOperation
    if s is None:
        return None
    try:
        return fmt(Decimal(s))
    except InvalidOperation:
        return s


def pretty(raw: str) -> str:
    """Human-readable FIX (SOH -> '|')."""
    return raw.replace(SOH, "|")
