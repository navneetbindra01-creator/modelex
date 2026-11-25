import copy
from decimal import Decimal as D

import pytest

from modelex import Exchange, MarketConfig, NewOrder, RefDataStore, register_algorithm, validation_rule
from modelex.codec import command_from_dict
from modelex.matching import AllocationAlgorithm
from modelex.mbt.differential import DifferentialTester, InProcessAdapter, gateway_adapter
from modelex.mbt.invariants import InvariantChecker
from modelex.mbt.mutants import mutant_factory
from modelex.mbt.runner import SimulationRunner
from modelex.mbt.scenario import ScenarioRunner
from modelex.protocol import get_mapper
from modelex.types import RejectReason
from modelex.validation import Rejection

SCENARIOS = ["equity_orderbook.json", "crypto_orderbook.json", "commodity_orderbook.json", "collectible_orderbook.json"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenarios_pass(root, make_ex, name):
    r = ScenarioRunner(lambda acs, auto: make_ex(acs, auto)).run(ScenarioRunner.load(root / "scenarios" / name))
    assert r.passed, [(s.index, s.label, s.messages) for s in r.steps if not s.passed] + r.violations


def test_scenario_runner_detects_wrong_expectation(root, make_ex):
    sc = ScenarioRunner.load(root / "scenarios" / "equity_orderbook.json")
    sc = copy.deepcopy(sc)
    for st in sc["steps"]:
        if "check_auction" in st:
            st["check_auction"]["price"] = "72.60"
            break
    r = ScenarioRunner(lambda acs, auto: make_ex(acs, auto)).run(sc)
    assert not r.passed


@pytest.mark.parametrize("ac", ["EQUITY", "CRYPTO", "COMMODITY", "COLLECTIBLE"])
def test_simulation_holds_all_invariants(make_ex, ac):
    ex = make_ex([ac])
    r = SimulationRunner(ex, ac, steps=1500, seed=99, protocol_mapper=get_mapper(ex.config.asset_classes[ac].protocol, ex.config)).run()
    assert r.violations == [] and r.protocol_mismatches == []
    assert r.trades > 100 and r.reject_reasons


def test_simulation_is_deterministic(make_ex):
    a = SimulationRunner(make_ex(["EQUITY"]), "EQUITY", steps=500, seed=5).run()
    b = SimulationRunner(make_ex(["EQUITY"]), "EQUITY", steps=500, seed=5).run()
    assert a.trace == b.trace and a.trades == b.trades


class _LIFO(AllocationAlgorithm):
    def allocate(self, resting, qty, lot):
        out = []
        for o in reversed(resting):
            if qty <= 0:
                break
            q = min(o.leaves_qty, qty); out.append((o, q)); qty -= q
        return out


def test_invariants_catch_priority_bug(make_ex):
    """Oracle sensitivity: secretly swap FIFO for LIFO and the invariants must notice."""
    ex = make_ex(["EQUITY"])
    ex.algorithms["EQUITY"] = _LIFO()
    r = SimulationRunner(ex, "EQUITY", steps=1500, seed=3).run()
    assert any(v.invariant == "PRICE_TIME_PRIORITY" for v in r.violations)


def test_invariants_catch_resting_ioc(make_ex):
    ex = make_ex(["CRYPTO"])
    orig = ex._terminate

    def buggy(o, et, st, events, text=""):
        if "IOC remainder" in text:          # bug: IOC remainder left in the book
            ex.books[o.symbol].add(o)
            return
        return orig(o, et, st, events, text)
    ex._terminate = buggy
    r = SimulationRunner(ex, "CRYPTO", steps=1500, seed=4).run()
    assert {"IOC_FOK_NEVER_REST"} & {v.invariant for v in r.violations}


def test_differential_agrees_through_wire_and_kills_mutants(root):
    cfg = MarketConfig.from_file(root / "config" / "market_default.json")
    store = RefDataStore.from_files([root / "refdata" / "equities.json"])
    factory = lambda: Exchange(cfg, store, auto_schedule=False)
    trace = SimulationRunner(factory(), "EQUITY", steps=1500, seed=8).run().trace
    clean = DifferentialTester(factory, gateway_adapter(factory, get_mapper("FIX44", cfg))).run(trace)
    assert clean.passed and clean.responses_compared > 1000
    for m in ["LIFO_MATCHING", "NO_DUPLICATE_CLORDID_CHECK", "FLAT_TICK_VALIDATION", "BAND_EDGE_OFF_BY_ONE", "NO_STP"]:
        res = DifferentialTester(factory, InProcessAdapter(mutant_factory(cfg, store, m, "EQUITY", auto_schedule=False))).run(trace)
        assert not res.passed, f"mutant {m} survived"


def test_extensibility_custom_rule_algorithm_and_asset_class():
    @validation_rule("NO_ODD_LOTS_ABOVE_100", applies_to_amend=True)
    def _rule(ctx):
        if ctx.cmd.qty > 100 and ctx.cmd.qty % 2:
            return Rejection(RejectReason.INVALID_QUANTITY, "odd lots above 100 not allowed")

    @register_algorithm("TEST_LIFO")
    class _Alg(_LIFO):
        pass

    cfg = MarketConfig.from_dict({
        "exchange": {"trading_date": "2026-11-25"},
        "schedules": {"FX_24X5": {"initial_phase": "CONTINUOUS"}},
        "asset_classes": {"FX": {"schedule": "FX_24X5", "matching_algorithm": "TEST_LIFO",
                                 "validation_rules": ["SESSION_PHASE", "PRICE_PRESENCE", "QUANTITY_POSITIVE",
                                                      "LOT_SIZE", "TICK_SIZE", "NO_ODD_LOTS_ABOVE_100"]}}})
    store = RefDataStore()
    store.load_dict({"asset_class": "FX", "instruments": [{"symbol": "EURUSD", "tick_size": "0.00001", "lot_size": "1",
                                                           "reference_price": "1.08000"}]})
    ex = Exchange(cfg, store)
    assert ex.process(NewOrder("A", "P", "EURUSD", "BUY", 101, "1.08"))[0].reject_reason.value == "INVALID_QUANTITY"
    ex.process(NewOrder("S1", "M1", "EURUSD", "SELL", 10, "1.08"))
    ex.process(NewOrder("S2", "M2", "EURUSD", "SELL", 10, "1.08"))
    ev = ex.process(NewOrder("B", "T", "EURUSD", "BUY", 10, "1.08"))
    assert [e.cl_ord_id for e in ev if e.TYPE == "ExecutionReport" and e.aggressor is False] == ["S2"]
