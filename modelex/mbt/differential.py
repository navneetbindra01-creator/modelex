"""Differential (model-vs-SUT) testing.

Replays one command stream against the ModelEx model and against a system
under test, normalizes both response streams to the protocol-neutral form in
``codec.normalize_event`` and reports every divergence. Plug a real venue in by
writing a ``SUTAdapter`` (e.g. a FIX session to a UAT environment).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from ..codec import command_from_dict, command_to_dict, normalize_event
from ..protocol.base import ProtocolGateway, ProtocolMapper
from ..types import CancelOrder, NewOrder, ReplaceOrder


class SUTAdapter(ABC):
    name = "SUT"

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def send(self, cmd) -> list:
        """Deliver a command; return normalized response dicts in arrival order."""


class InProcessAdapter(SUTAdapter):
    """Any Exchange-compatible object in the same process (the model itself, or a mutant)."""

    def __init__(self, factory: Callable, name: str = "in-process"):
        self.factory, self.name = factory, name
        self.reset()

    def reset(self):
        self.ex = self.factory()

    def send(self, cmd) -> list:
        return [n for ev in self.ex.process(cmd) if (n := normalize_event(ev)) is not None]


class WireAdapter(SUTAdapter):
    """Drives a SUT through a wire protocol.

    ``transport(raw) -> [raw]`` carries order-entry messages; ``control(cmd) -> [raw]``
    carries session/clock control (phase changes, time) that is out-of-band for
    order-entry protocols, e.g. an admin API or a test harness hook.
    """

    def __init__(self, mapper: ProtocolMapper, transport: Callable, control: Callable,
                 reset: Optional[Callable] = None, name: str = "wire"):
        self.mapper, self.transport, self.control, self._reset, self.name = mapper, transport, control, reset, name

    def reset(self):
        if self._reset:
            self._reset()

    def send(self, cmd) -> list:
        if isinstance(cmd, (NewOrder, CancelOrder, ReplaceOrder)):
            raws = self.transport(self.mapper.encode_command(cmd))
        else:
            raws = self.control(cmd)
        return [d for r in raws if (d := self.mapper.decode_report(r)) is not None]


def gateway_adapter(exchange_factory: Callable, mapper: ProtocolMapper, name: str = "gateway") -> WireAdapter:
    """Wrap an in-process exchange behind a protocol gateway (round-trips every message on the wire)."""
    state = {}

    def reset():
        state["ex"] = exchange_factory()
        state["gw"] = ProtocolGateway(state["ex"], mapper)

    def control(cmd):
        return [m for ev in state["ex"].process(cmd) if (m := mapper.encode_event(ev)) is not None]

    reset()
    return WireAdapter(mapper, lambda raw: state["gw"].handle(raw), control, reset, name)


@dataclass
class Divergence:
    index: int
    command: dict
    model: list
    sut: list


@dataclass
class DiffResult:
    sut_name: str
    commands: int = 0
    responses_compared: int = 0
    divergences: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.divergences


class DifferentialTester:
    def __init__(self, model_factory: Callable, sut: SUTAdapter, max_divergences: int = 25):
        self.model_factory = model_factory
        self.sut = sut
        self.max_divergences = max_divergences

    def run(self, commands: Iterable) -> DiffResult:
        model = InProcessAdapter(self.model_factory, "model")
        self.sut.reset()
        res = DiffResult(self.sut.name)
        for i, c in enumerate(commands):
            cmd = command_from_dict(c) if isinstance(c, dict) else c
            m, s = model.send(cmd), self.sut.send(cmd)
            res.commands += 1
            res.responses_compared += len(m)
            if m != s:
                res.divergences.append(Divergence(i, command_to_dict(cmd), m, s))
                if len(res.divergences) >= self.max_divergences:
                    break
        return res


def first_difference(d: Divergence) -> str:
    """One-line human summary of a divergence."""
    for i in range(max(len(d.model), len(d.sut))):
        a = d.model[i] if i < len(d.model) else None
        b = d.sut[i] if i < len(d.sut) else None
        if a != b:
            if a is None or b is None:
                return f"response #{i}: model={a and a.get('exec_type') or a} sut={b and b.get('exec_type') or b}"
            keys = [k for k in a if a.get(k) != b.get(k)]
            return f"response #{i} ({a.get('cl_ord_id')}): " + ", ".join(f"{k} model={a.get(k)} sut={b.get(k)}" for k in keys)
    return "responses differ"
