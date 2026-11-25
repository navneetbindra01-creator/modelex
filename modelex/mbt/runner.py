"""Simulation runner: drives a full trading day of generated flow through the
model, checking invariants after every step and (optionally) verifying that
each message survives a round trip through the asset class's wire protocol.
"""
from __future__ import annotations

import json
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ..codec import command_to_dict, event_to_dict, normalize_event
from ..types import (AdvanceTime, CancelOrder, ExecType, ExecutionReport, HaltInstrument, NewOrder, Phase,
                     PhaseChangeRejected, ReplaceOrder, ResumeInstrument, SetPhase, Trade, fmt)
from .generator import OrderFlowGenerator
from .invariants import InvariantChecker

PHASE_SHARE = {Phase.CLOSED: 0.02, Phase.PRE_OPEN: 0.12, Phase.CONTINUOUS: 0.66, Phase.PRE_CLOSE: 0.09,
               Phase.POST_CLOSE: 0.03, Phase.HALTED: 0.03}


@dataclass
class SimulationResult:
    asset_class: str
    seed: int
    steps: int
    commands: Counter = field(default_factory=Counter)
    generator_kinds: dict = field(default_factory=dict)
    exec_types: Counter = field(default_factory=Counter)
    reject_reasons: Counter = field(default_factory=Counter)
    cancel_rejects: Counter = field(default_factory=Counter)
    trades: int = 0
    continuous_trades: int = 0
    auction_trades: int = 0
    phase_rejections: int = 0
    circuit_breakers: int = 0
    alerts: Counter = field(default_factory=Counter)
    violations: list = field(default_factory=list)
    protocol: Optional[str] = None
    protocol_messages: int = 0
    protocol_mismatches: list = field(default_factory=list)
    symbols: dict = field(default_factory=dict)
    final_books: dict = field(default_factory=dict)
    phase_path: list = field(default_factory=list)
    duration_s: float = 0.0
    trace: list = field(default_factory=list)       # command dicts, replayable
    rule_hits: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.violations and not self.protocol_mismatches


class SimulationRunner:
    def __init__(self, exchange, asset_class: str, steps: int = 5000, seed: int = 7, weights=None,
                 protocol_mapper=None, trace_path=None, full_check_every: int = 100):
        self.ex = exchange
        self.asset_class = asset_class.upper()
        self.steps = steps
        self.seed = seed
        self.ac = exchange.config.asset_classes[self.asset_class]
        self.gen = OrderFlowGenerator(exchange, self.asset_class, seed=seed, weights=weights)
        self.checker = InvariantChecker(exchange, full_check_every)
        self.mapper = protocol_mapper
        self.trace_path = Path(trace_path) if trace_path else None
        self.rng = random.Random(seed * 7919)
        self.result = SimulationResult(self.asset_class, seed, steps,
                                       protocol=getattr(protocol_mapper, "name", None))

    # ------------------------------------------------------------------ day plan
    def _plan(self) -> dict:
        sched_name = self.ac.schedule
        sched = self.ex.config.schedules[sched_name]
        phases = [sched.initial_phase] + [ph for _, ph in sched.timeline]
        plan: dict = {}

        def add(step, cmd):
            plan.setdefault(max(0, min(step, self.steps - 1)), []).append(cmd)

        cont_start, cont_end = 0, self.steps
        if len(phases) > 1:
            shares = [PHASE_SHARE.get(p, 0.03) for p in phases]
            total, acc = sum(shares), 0.0
            for idx, (ph, sh) in enumerate(zip(phases, shares)):
                start = int(acc / total * self.steps)
                if idx > 0:
                    add(start, SetPhase(sched_name, ph, "planned"))
                if ph is Phase.CONTINUOUS:
                    cont_start, cont_end = start, int((acc + sh) / total * self.steps)
                acc += sh
        span = max(cont_end - cont_start, 10)
        k = max(span // 60, 2)
        # schedule-wide halt and auction resumption
        h = cont_start + int(span * 0.40)
        add(h, SetPhase(sched_name, Phase.HALTED, "market-wide halt"))
        if len(phases) > 1:
            add(h + k, SetPhase(sched_name, Phase.PRE_OPEN, "resume via auction"))
            add(h + 2 * k, SetPhase(sched_name, Phase.CONTINUOUS, "resume"))
        else:
            add(h + k, SetPhase(sched_name, Phase.CONTINUOUS, "resume"))
        # single-instrument halt
        sym = self.rng.choice(self.gen.active).symbol
        add(cont_start + int(span * 0.6), HaltInstrument(sym, "news pending"))
        add(cont_start + int(span * 0.6) + k, ResumeInstrument(sym, "news released"))
        # illegal transition probes (decided at run time against the then-current phase)
        for frac in (0.1, 0.5, 0.9):
            add(int(self.steps * frac), ("ILLEGAL_PROBE", sched_name))
        return plan

    def _illegal(self, sched_name) -> SetPhase:
        cur = self.ex.sessions.schedule_phase[sched_name]
        options = [p for p in Phase if p != cur and p not in self.ex.config.transitions.get(cur, set())]
        return SetPhase(sched_name, self.rng.choice(options), "illegal transition probe")

    # ------------------------------------------------------------------ execution
    def _do(self, step: int, cmd) -> list:
        r = self.result
        self.checker.before(cmd)
        events = self.ex.process(cmd)
        r.violations.extend(self.checker.after(step, cmd, events))
        r.commands[cmd.TYPE] += 1
        r.trace.append(command_to_dict(cmd))
        for ev in events:
            if isinstance(ev, ExecutionReport):
                r.exec_types[ev.exec_type.value] += 1
                if ev.exec_type is ExecType.REJECTED:
                    r.reject_reasons[ev.reject_reason.value] += 1
            elif isinstance(ev, Trade):
                r.trades += 1
                if ev.match_type == "AUCTION":
                    r.auction_trades += 1
                else:
                    r.continuous_trades += 1
            elif isinstance(ev, PhaseChangeRejected):
                r.phase_rejections += 1
            elif ev.TYPE == "CancelReject":
                r.cancel_rejects[ev.reject_reason.value] += 1
            elif ev.TYPE == "Alert":
                r.alerts[ev.kind] += 1
                if ev.kind == "CIRCUIT_BREAKER":
                    r.circuit_breakers += 1
            elif ev.TYPE == "PhaseChange" and ev.scope_type == "SCHEDULE":
                r.phase_path.append(ev.new_phase.value)
        if self.mapper is not None:
            self._protocol_check(step, cmd, events)
        return events

    def _protocol_check(self, step, cmd, events) -> None:
        r, m = self.result, self.mapper
        if isinstance(cmd, (NewOrder, CancelOrder, ReplaceOrder)):
            back = m.decode_command(m.encode_command(cmd))
            r.protocol_messages += 1
            if command_to_dict(back) != command_to_dict(cmd):
                r.protocol_mismatches.append({"step": step, "direction": "inbound",
                                              "sent": command_to_dict(cmd), "decoded": command_to_dict(back)})
        for ev in events:
            norm = normalize_event(ev)
            if norm is None:
                continue
            wire = m.encode_event(ev)
            r.protocol_messages += 1
            dec = m.decode_report(wire)
            if dec != norm:
                diff = {k: (norm.get(k), dec.get(k)) for k in norm if norm.get(k) != (dec or {}).get(k)}
                r.protocol_mismatches.append({"step": step, "direction": "outbound", "diff": diff})

    def run(self) -> SimulationResult:
        t0 = time.perf_counter()
        plan = self._plan()
        for step in range(self.steps):
            for c in plan.get(step, []):
                self._do(step, self._illegal(c[1]) if isinstance(c, tuple) else c)
            self._do(step, self.gen.next())
        # let any open volatility auctions complete
        self._do(self.steps, AdvanceTime(Decimal(self.ac.circuit_breaker.auction_seconds + 1)))
        r = self.result
        r.generator_kinds = dict(sorted(self.gen.kind_counts.items()))
        r.rule_hits = dict(self.ex.validator.hits)
        mon = self.ex.monitor.summary()
        r.symbols = {s: v for s, v in mon["symbols"].items()
                     if self.ex.instrument(s).asset_class == self.asset_class}
        r.final_books = {i.symbol: self.ex.book_snapshot(i.symbol, 3) for i in self.ex.refdata.by_asset_class(self.asset_class)}
        r.duration_s = round(time.perf_counter() - t0, 2)
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("w") as fh:
                for c in r.trace:
                    fh.write(json.dumps(c) + "\n")
        return r
