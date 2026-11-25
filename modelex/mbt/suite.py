"""End-to-end acceptance suite: per asset class run the scenario order book,
a generated trading-day simulation with invariants and protocol round-trips,
rule-coverage analysis, and differential testing against a wire-level SUT and
a set of mutants.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import MarketConfig
from ..exchange import Exchange
from ..protocol import get_mapper
from ..refdata import RefDataStore
from ..types import OrderType, TimeInForce
from .differential import DifferentialTester, InProcessAdapter, first_difference, gateway_adapter
from .mutants import MUTANTS, mutant_factory
from .runner import SimulationRunner
from .scenario import ScenarioRunner

SCENARIO_FILES = {"EQUITY": "equity_orderbook.json", "CRYPTO": "crypto_orderbook.json",
                  "COMMODITY": "commodity_orderbook.json", "COLLECTIBLE": "collectible_orderbook.json"}

# Mutants that are *equivalent* (cannot change behaviour) under a given asset-class config
EQUIVALENT = {("FLAT_TICK_VALIDATION", "CRYPTO"): "all crypto instruments use a single tick size",
              ("FLAT_TICK_VALIDATION", "COMMODITY"): "all futures use a single tick size"}


@dataclass
class AssetClassReport:
    asset_class: str
    scenario: object = None
    simulation: object = None
    coverage: dict = field(default_factory=dict)
    differential: list = field(default_factory=list)   # dicts

    @property
    def passed(self) -> bool:
        ok = self.scenario.passed and self.simulation.passed
        ok = ok and all(d["expected"] == d["outcome"] for d in self.differential)
        ok = ok and not self.coverage.get("missed")
        return ok


def _store(root: Path, asset_class: str) -> RefDataStore:
    store = RefDataStore()
    for f in sorted((root / "refdata").glob("*.json")):
        data = json.loads(f.read_text())
        if str(data.get("asset_class", "")).upper() == asset_class:
            store.load_dict(data, source=str(f))
    return store


def coverage(config: MarketConfig, asset_class: str, hits: dict, refdata=None) -> dict:
    ac = config.asset_classes[asset_class]
    rules = list(config.global_validation_rules) + list(ac.validation_rules)
    unreachable = {}
    if set(ac.order_types) == set(OrderType):
        unreachable["ORDER_TYPE"] = "every order type is enabled"
    if set(ac.time_in_force) == set(TimeInForce):
        unreachable["TIME_IN_FORCE"] = "every TIF is enabled"
    if "UNIQUE_ITEM" in rules and "MIN_MAX_QTY" in rules:
        unreachable["UNIQUE_ITEM"] = "shadowed by MIN_MAX_QTY (unique items have max_qty 1); defence in depth"
    insts = [i for i in refdata if i.asset_class == asset_class] if refdata is not None else []
    if refdata is not None and "INSTRUMENT_EXPIRY" in rules and not any(i.expiry for i in insts):
        unreachable["INSTRUMENT_EXPIRY"] = "no dated instruments"
    if refdata is not None and "MAX_NOTIONAL" in rules and ac.max_notional is None and \
            not any(i.max_notional is not None for i in insts):
        unreachable["MAX_NOTIONAL"] = "no notional limit configured"
    if refdata is not None and "INSTRUMENT_STATUS" in rules and all(i.tradable for i in insts):
        unreachable["INSTRUMENT_STATUS"] = "no non-ACTIVE instruments in ref data"
    reachable = [r for r in rules if r not in unreachable]
    hit = [r for r in reachable if hits.get(r)]
    return {"rules": rules, "hits": {r: hits.get(r, 0) for r in rules}, "unreachable": unreachable,
            "reachable": len(reachable), "exercised": len(hit),
            "missed": [r for r in reachable if not hits.get(r)]}


def run_suite(root, steps: int = 5000, seed: int = 20261125, out_dir=None,
              asset_classes: Optional[list] = None) -> list:
    root = Path(root)
    out = Path(out_dir) if out_dir else root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    config = MarketConfig.from_file(root / "config" / "market_default.json")
    reports = []
    for i, ac in enumerate(asset_classes or list(SCENARIO_FILES)):
        ac = ac.upper()
        store = _store(root, ac)
        factory = lambda store=store: Exchange(config, store, auto_schedule=False)
        rep = AssetClassReport(ac)

        # 1. deterministic scenario order book
        sc_runner = ScenarioRunner(lambda acs, auto, store=store: Exchange(config, store, auto_schedule=auto))
        rep.scenario = sc_runner.run(ScenarioRunner.load(root / "scenarios" / SCENARIO_FILES[ac]))

        # 2. generated trading-day simulation
        mapper = get_mapper(config.asset_classes[ac].protocol, config)
        sim = SimulationRunner(factory(), ac, steps=steps, seed=seed + i, protocol_mapper=mapper,
                               trace_path=out / f"trace_{ac.lower()}.jsonl")
        rep.simulation = sim.run()

        # 3. validation rule coverage (scenario + simulation)
        hits = dict(rep.scenario.rule_hits)
        for k, v in rep.simulation.rule_hits.items():
            hits[k] = hits.get(k, 0) + v
        rep.coverage = coverage(config, ac, hits, store)

        # 4. differential testing: replay the simulation trace
        trace = rep.simulation.trace
        suts = [("Same engine behind %s gateway" % mapper.name, gateway_adapter(factory, get_mapper(mapper.name, config)), "AGREE")]
        for m in MUTANTS:
            expected = "AGREE" if (m, ac) in EQUIVALENT else "KILLED"
            suts.append((f"Mutant: {m}", InProcessAdapter(mutant_factory(config, store, m, ac, auto_schedule=False), m), expected))
        for label, sut, expected in suts:
            res = DifferentialTester(factory, sut, max_divergences=5).run(trace)
            outcome = "AGREE" if res.passed else "KILLED"
            rep.differential.append({
                "sut": label, "expected": expected, "outcome": outcome, "commands": res.commands,
                "responses": res.responses_compared,
                "first_divergence_step": res.divergences[0].index if res.divergences else None,
                "detail": first_difference(res.divergences[0]) if res.divergences else "",
                "note": EQUIVALENT.get((label.replace("Mutant: ", ""), ac), MUTANTS.get(label.replace("Mutant: ", ""), "")),
            })
        reports.append(rep)
    return reports
