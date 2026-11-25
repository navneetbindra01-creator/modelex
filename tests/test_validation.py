import pytest

from modelex import NewOrder, SetPhase
from tests.conftest import rejects


@pytest.mark.parametrize("kw,reason", [
    (dict(symbol="NOPE"), "UNKNOWN_INSTRUMENT"),
    (dict(symbol="SUSP.L", price="1.250"), "INSTRUMENT_NOT_TRADABLE"),
    (dict(side="SHORT"), "MISSING_OR_INVALID_FIELD"),
    (dict(cl_ord_id=""), "MISSING_OR_INVALID_FIELD"),
    (dict(qty="abc"), "MISSING_OR_INVALID_FIELD"),
    (dict(order_type="STOP"), "MISSING_OR_INVALID_FIELD"),
    (dict(price=None), "PRICE_REQUIRED"),
    (dict(price="-1"), "INVALID_PRICE"),
    (dict(order_type="MARKET"), "PRICE_NOT_ALLOWED"),
    (dict(qty="0"), "INVALID_QUANTITY"),
    (dict(qty="10.5"), "LOT_SIZE_VIOLATION"),
    (dict(qty="500001"), "QTY_ABOVE_MAX"),
    (dict(price="72.555"), "INVALID_TICK"),
    (dict(price="65.24"), "PRICE_OUTSIDE_BAND"),
    (dict(price="79.76"), "PRICE_OUTSIDE_BAND"),
    (dict(symbol="AAPL.OQ", price="228.40", qty="30000"), "NOTIONAL_LIMIT_EXCEEDED"),
    (dict(symbol="7203.T", price="2650.0", qty="150"), "LOT_SIZE_VIOLATION"),
    (dict(symbol="AZN.L", price="11250.5"), "INVALID_TICK"),
])
def test_rejections(eq, kw, reason):
    base = dict(cl_ord_id="X", participant="P", symbol="VOD.L", side="BUY", qty="100", price="72.50")
    base.update(kw)
    assert rejects(eq.process(NewOrder(**base))) == [reason]


def test_band_edges_are_inclusive(eq):
    assert not rejects(eq.process(NewOrder("A", "P", "VOD.L", "BUY", 100, "65.25")))
    assert not rejects(eq.process(NewOrder("B", "P", "VOD.L", "SELL", 100, "79.75")))


def test_duplicate_clordid_per_participant(eq):
    assert not rejects(eq.process(NewOrder("A", "P1", "VOD.L", "BUY", 100, "72.00")))
    assert rejects(eq.process(NewOrder("A", "P1", "VOD.L", "BUY", 200, "71.00"))) == ["DUPLICATE_CL_ORD_ID"]
    assert not rejects(eq.process(NewOrder("A", "P2", "VOD.L", "BUY", 100, "72.00")))


def test_duplicate_scope_all_includes_rejected(eq):
    assert rejects(eq.process(NewOrder("A", "P1", "VOD.L", "BUY", 100, "72.555"))) == ["INVALID_TICK"]
    assert rejects(eq.process(NewOrder("A", "P1", "VOD.L", "BUY", 100, "72.55"))) == ["DUPLICATE_CL_ORD_ID"]


def test_duplicate_content_window(eq):
    from modelex import AdvanceTime
    assert not rejects(eq.process(NewOrder("A", "P1", "VOD.L", "BUY", 100, "72.00")))
    assert rejects(eq.process(NewOrder("B", "P1", "VOD.L", "BUY", 100, "72.00"))) == ["DUPLICATE_ORDER"]
    eq.process(AdvanceTime("0.6"))
    assert not rejects(eq.process(NewOrder("C", "P1", "VOD.L", "BUY", 100, "72.00")))


def test_phase_rules(make_ex):
    ex = make_ex(["EQUITY"])
    assert rejects(ex.process(NewOrder("A", "P", "VOD.L", "BUY", 100, "72.50"))) == ["EXCHANGE_CLOSED"]
    ex.process(SetPhase("EQUITY_STD", "PRE_OPEN"))
    assert rejects(ex.process(NewOrder("B", "P", "VOD.L", "BUY", 100, "72.50", tif="IOC"))) == ["TIF_NOT_ALLOWED_IN_PHASE"]


def test_first_failing_rule_wins(eq):
    # off tick AND outside band: TICK_SIZE is configured before PRICE_BAND
    assert rejects(eq.process(NewOrder("A", "P", "VOD.L", "BUY", 100, "90.001"))) == ["INVALID_TICK"]
