"""Plain-dict (JSON-friendly) encoding of commands and events.

Used for scenario files, simulation traces, and as the neutral comparison
format in differential testing.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from .types import COMMAND_TYPES, CancelReject, ExecutionReport, fmt


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return fmt(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def command_to_dict(cmd) -> dict:
    d = {"type": cmd.TYPE}
    for f in dataclasses.fields(cmd):
        v = getattr(cmd, f.name)
        if v is not None:
            d[f.name] = _plain(v)
    return d


def command_from_dict(d: dict):
    d = dict(d)
    t = d.pop("type")
    try:
        cls = COMMAND_TYPES[t]
    except KeyError:
        raise ValueError(f"unknown command type {t!r}; expected one of {sorted(COMMAND_TYPES)}") from None
    return cls(**d)


def event_to_dict(ev) -> dict:
    d = {"type": ev.TYPE}
    for f in dataclasses.fields(ev):
        d[f.name] = _plain(getattr(ev, f.name))
    return d


def normalize_event(ev) -> Optional[dict]:
    """Protocol-neutral subset used to compare a model with a system under test.

    Excludes venue-assigned identifiers and timestamps, which legitimately differ.
    """
    if isinstance(ev, ExecutionReport):
        return {"kind": "EXEC", "exec_type": _plain(ev.exec_type), "ord_status": _plain(ev.ord_status),
                "cl_ord_id": _plain(ev.cl_ord_id), "orig_cl_ord_id": _plain(ev.orig_cl_ord_id),
                "participant": _plain(ev.participant), "symbol": _plain(ev.symbol), "side": _plain(ev.side),
                "last_qty": fmt(ev.last_qty) or "0", "last_px": fmt(ev.last_px),
                "cum_qty": fmt(ev.cum_qty) or "0", "leaves_qty": fmt(ev.leaves_qty) or "0",
                "reject_reason": _plain(ev.reject_reason)}
    if isinstance(ev, CancelReject):
        return {"kind": "CXL_REJ", "cl_ord_id": _plain(ev.cl_ord_id), "orig_cl_ord_id": _plain(ev.orig_cl_ord_id),
                "participant": _plain(ev.participant), "symbol": _plain(ev.symbol),
                "response_to": ev.response_to, "reject_reason": _plain(ev.reject_reason)}
    return None
