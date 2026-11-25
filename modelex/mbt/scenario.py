"""Declarative scenario runner - readable by business analysts, trainers and QA.

A scenario is JSON::

    {"name": "...", "description": "...", "asset_classes": ["EQUITY"], "auto_schedule": false,
     "steps": [
        {"note": "Open the pre-open call",
         "do": {"type": "SetPhase", "schedule": "EQUITY_STD", "phase": "PRE_OPEN"}},
        {"do": {"type": "NewOrder", "cl_ord_id": "B1", "participant": "FIRM_A", "symbol": "VOD.L",
                "side": "BUY", "qty": "1000", "price": "72.50", "tif": "DAY"},
         "expect": [{"type": "ExecutionReport", "exec_type": "NEW"}]},
        {"do": {...}, "expect_reject": "INVALID_TICK"},
        {"do": {...}, "expect_trades": [{"price": "72.50", "qty": "400"}]},
        {"check_book": {"symbol": "VOD.L", "bids": [["72.50", "600"]], "asks": []}},
        {"check_order": {"participant": "FIRM_A", "cl_ord_id": "B1", "status": "PARTIALLY_FILLED",
                         "cum_qty": "400"}},
        {"check_phase": {"symbol": "VOD.L", "phase": "CONTINUOUS"}},
        {"check_auction": {"symbol": "VOD.L", "price": "72.50", "volume": "1300"}}
     ]}

``expect`` entries are partial matches applied as an ordered subsequence of the
step's events. Numbers compare by value ("72.5" == "72.50").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from ..codec import command_from_dict, event_to_dict
from ..types import AuctionResult, Trade, fmt
from .invariants import InvariantChecker


def _eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return str(a) == str(b)


def _match(expected: dict, actual: dict) -> bool:
    return all(_eq(v, actual.get(k)) for k, v in expected.items())


@dataclass
class StepResult:
    index: int
    label: str
    passed: bool
    messages: list = field(default_factory=list)


@dataclass
class ScenarioResult:
    name: str
    description: str
    steps: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    trades: int = 0
    rule_hits: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps) and not self.violations

    @property
    def counts(self):
        return sum(s.passed for s in self.steps), len(self.steps)


class ScenarioRunner:
    def __init__(self, exchange_factory: Callable):
        """exchange_factory(asset_classes: list|None, auto_schedule: bool) -> Exchange"""
        self.factory = exchange_factory

    @staticmethod
    def load(path) -> dict:
        return json.loads(Path(path).read_text())

    def run(self, scenario: dict) -> ScenarioResult:
        ex = self.factory(scenario.get("asset_classes"), scenario.get("auto_schedule", False))
        checker = InvariantChecker(ex, full_check_every=1)
        res = ScenarioResult(scenario.get("name", "unnamed"), scenario.get("description", ""))
        last_auction: dict = {}
        for i, step in enumerate(scenario["steps"], 1):
            label = step.get("note") or step.get("label") or ""
            msgs = []
            if "do" in step:
                cmd = command_from_dict(step["do"])
                label = label or f"{cmd.TYPE} {getattr(cmd, 'cl_ord_id', '') or getattr(cmd, 'phase', '')}"
                checker.before(cmd)
                events = ex.process(cmd)
                res.violations += checker.after(i, cmd, events)
                evd = [event_to_dict(e) for e in events]
                for e in events:
                    if isinstance(e, AuctionResult):
                        last_auction[e.symbol] = e
                    if isinstance(e, Trade):
                        res.trades += 1
                if "expect" in step:
                    pos = 0
                    for exp in step["expect"]:
                        while pos < len(evd) and not _match(exp, evd[pos]):
                            pos += 1
                        if pos == len(evd):
                            msgs.append(f"expected event not found (in order): {exp}")
                            break
                        pos += 1
                if "expect_reject" in step:
                    want = step["expect_reject"]
                    got = [d.get("reject_reason") for d in evd if d.get("reject_reason")]
                    if want not in got:
                        msgs.append(f"expected reject {want}, got {got or 'no rejection'}")
                if "expect_trades" in step:
                    got = [{"price": d["price"], "qty": d["qty"]} for d in evd if d["type"] == "Trade"]
                    want = step["expect_trades"]
                    if len(got) != len(want) or not all(_match(w, g) for w, g in zip(want, got)):
                        msgs.append(f"expected trades {want}, got {got}")
                if step.get("expect_no_trades") and any(d["type"] == "Trade" for d in evd):
                    msgs.append("expected no trades")
            if "check_book" in step:
                cb = step["check_book"]
                snap = ex.book_snapshot(cb["symbol"], None)
                for side in ("bids", "asks"):
                    if side in cb:
                        want = cb[side]
                        got = snap[side]
                        ok = len(want) == len(got) and all(
                            all(_eq(w[k], g[k]) for k in range(len(w))) for w, g in zip(want, got))
                        if not ok:
                            msgs.append(f"{cb['symbol']} {side}: expected {want}, got {[g[:len(want[0])] if want else g for g in got]}")
                label = label or f"check book {cb['symbol']}"
            if "check_order" in step:
                co = step["check_order"]
                o = ex.order_status(co["participant"], co["cl_ord_id"])
                if o is None:
                    msgs.append(f"order {co['cl_ord_id']} not found")
                else:
                    actual = {"status": o.status.value, "cum_qty": o.cum_qty, "leaves_qty": o.leaves_qty,
                              "avg_px": o.avg_px, "price": o.price, "qty": o.qty}
                    for k, v in co.items():
                        if k in actual and not _eq(v, fmt(actual[k])):
                            msgs.append(f"order {co['cl_ord_id']} {k}: expected {v}, got {fmt(actual[k])}")
                label = label or f"check order {co['cl_ord_id']}"
            if "check_phase" in step:
                cp = step["check_phase"]
                got = ex.phase(cp["symbol"]).value if "symbol" in cp else ex.sessions.schedule_phase[cp["schedule"]].value
                if got != cp["phase"]:
                    msgs.append(f"phase: expected {cp['phase']}, got {got}")
                label = label or f"check phase {cp.get('symbol') or cp.get('schedule')}"
            if "check_auction" in step:
                ca = step["check_auction"]
                a = last_auction.get(ca["symbol"])
                if a is None:
                    msgs.append(f"no auction for {ca['symbol']}")
                else:
                    for k in ("price", "volume", "imbalance"):
                        if k in ca and not _eq(ca[k], fmt(getattr(a, k))):
                            msgs.append(f"auction {k}: expected {ca[k]}, got {fmt(getattr(a, k))}")
                label = label or f"check auction {ca['symbol']}"
            res.steps.append(StepResult(i, label, not msgs, msgs))
        res.rule_hits = dict(ex.validator.hits)
        return res
