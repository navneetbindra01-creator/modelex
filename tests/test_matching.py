import datetime as dt
from decimal import Decimal as D

from modelex import AdvanceTime, CancelOrder, NewOrder, ReplaceOrder, SetPhase
from modelex.matching import ProRata, PriceTimeFIFO, compute_uncross
from modelex.orderbook import OrderBook
from modelex.types import Order, OrderType, Side, TimeInForce
from tests.conftest import rejects, trades

T0 = dt.datetime(2026, 11, 25)


def mk(i, side, qty, price=None, otype=OrderType.LIMIT):
    return Order(f"O{i}", f"C{i}", "P", "X", side, otype, TimeInForce.DAY, D(qty),
                 D(price) if price else None, i, T0)


def test_fifo_allocation():
    rs = [mk(1, Side.SELL, 10, 1), mk(2, Side.SELL, 20, 1)]
    assert [(o.order_id, q) for o, q in PriceTimeFIFO().allocate(rs, D(15), D(1))] == [("O1", 10), ("O2", 5)]


def test_pro_rata_allocation_with_fifo_remainder():
    rs = [mk(1, Side.SELL, 5, 1), mk(2, Side.SELL, 15, 1), mk(3, Side.SELL, 30, 1)]
    got = {o.order_id: q for o, q in ProRata().allocate(rs, D(7), D(1))}
    assert got == {"O1": 1, "O2": 2, "O3": 4}
    assert sum(got.values()) == 7


def _book(orders):
    b = OrderBook("X")
    for o in orders:
        b.add(o)
    return b


def test_uncross_max_volume():
    b = _book([mk(1, Side.BUY, 1000, "72.6"), mk(2, Side.BUY, 500, "72.5"), mk(3, Side.BUY, 300, None, OrderType.MARKET),
               mk(4, Side.SELL, 600, "72.4"), mk(5, Side.SELL, 800, "72.5"), mk(6, Side.SELL, 400, "72.7")])
    r = compute_uncross(b, D("72.5"))
    assert (r.price, r.volume, r.imbalance) == (D("72.5"), 1400, 400)


def test_uncross_tie_breaks():
    # buy pressure on every tied candidate -> highest price
    b = _book([mk(1, Side.BUY, 2, "75"), mk(2, Side.SELL, 1, "74")])
    assert compute_uncross(b, D("70")).price == D("75")
    # sell pressure -> lowest
    b = _book([mk(1, Side.BUY, 1, "75"), mk(2, Side.SELL, 2, "74")])
    assert compute_uncross(b, D("70")).price == D("74")
    # balanced -> closest to reference
    b = _book([mk(1, Side.BUY, 1, "75"), mk(2, Side.SELL, 1, "74")])
    assert compute_uncross(b, D("74.9")).price == D("75")
    assert compute_uncross(b, D("70")).price == D("74")
    # nothing crosses
    b = _book([mk(1, Side.BUY, 1, "73"), mk(2, Side.SELL, 1, "74")])
    assert compute_uncross(b, D("70")).volume == 0


def test_continuous_price_time_and_trade_at_resting_price(eq):
    eq.process(NewOrder("S1", "A", "VOD.L", "SELL", 100, "72.60"))
    eq.process(NewOrder("S2", "B", "VOD.L", "SELL", 100, "72.50"))
    eq.process(NewOrder("S3", "C", "VOD.L", "SELL", 100, "72.50"))
    ev = eq.process(NewOrder("B1", "D", "VOD.L", "BUY", 250, "72.70"))
    assert trades(ev) == [("72.5", "100"), ("72.5", "100"), ("72.6", "50")]
    assert [e.cl_ord_id for e in ev if e.TYPE == "ExecutionReport" and e.aggressor is False] == ["S2", "S3", "S1"]


def test_ioc_fok_market(eq):
    eq.process(NewOrder("S1", "A", "VOD.L", "SELL", 100, "72.50"))
    ev = eq.process(NewOrder("F1", "B", "VOD.L", "BUY", 200, "72.50", tif="FOK"))
    assert trades(ev) == [] and ev[-1].exec_type.value == "EXPIRED"
    ev = eq.process(NewOrder("I1", "B", "VOD.L", "BUY", 200, "72.50", tif="IOC"))
    assert trades(ev) == [("72.5", "100")] and ev[-1].exec_type.value == "EXPIRED" and ev[-1].cum_qty == 100
    ev = eq.process(NewOrder("M1", "B", "VOD.L", "BUY", 10, None, "MARKET", "IOC"))
    assert ev[-1].exec_type.value == "EXPIRED"
    assert len(eq.books["VOD.L"]) == 0


def test_stp_modes(make_ex):
    # EQUITY: CANCEL_RESTING
    ex = make_ex(["EQUITY"]); ex.process(SetPhase("EQUITY_STD", "PRE_OPEN")); ex.process(SetPhase("EQUITY_STD", "CONTINUOUS"))
    ex.process(NewOrder("S1", "A", "VOD.L", "SELL", 100, "72.50"))
    ex.process(NewOrder("S2", "B", "VOD.L", "SELL", 100, "72.50"))
    ev = ex.process(NewOrder("B1", "A", "VOD.L", "BUY", 150, "72.50"))
    assert [e.cl_ord_id for e in ev if e.TYPE == "ExecutionReport" and e.exec_type.value == "CANCELED"] == ["S1"]
    assert trades(ev) == [("72.5", "100")]
    # CRYPTO: CANCEL_INCOMING
    ex = make_ex(["CRYPTO"])
    ex.process(NewOrder("S1", "A", "ETH-USD", "SELL", "1", "3200.00", tif="GTC"))
    ev = ex.process(NewOrder("B1", "A", "ETH-USD", "BUY", "1", "3200.00", tif="GTC"))
    assert [e.cl_ord_id for e in ev if e.TYPE == "ExecutionReport" and e.exec_type.value == "CANCELED"] == ["B1"]
    assert len(ex.books["ETH-USD"]) == 1


def test_amend_priority(eq):
    eq.process(NewOrder("B1", "A", "VOD.L", "BUY", 100, "72.40"))
    eq.process(NewOrder("B2", "B", "VOD.L", "BUY", 100, "72.40"))
    ev = eq.process(ReplaceOrder("R1", "B1", "A", "VOD.L", qty=50))
    assert ev[0].text == "priority kept"
    assert [o.cl_ord_id for o in eq.books["VOD.L"].priority_queue(Side.BUY)] == ["R1", "B2"]
    ev = eq.process(ReplaceOrder("R2", "R1", "A", "VOD.L", qty=60))
    assert ev[0].text == "priority lost"
    assert [o.cl_ord_id for o in eq.books["VOD.L"].priority_queue(Side.BUY)] == ["B2", "R2"]
    # amend that crosses the spread trades immediately
    eq.process(NewOrder("S1", "C", "VOD.L", "SELL", 30, "72.60"))
    ev = eq.process(ReplaceOrder("R3", "R2", "A", "VOD.L", price="72.60"))
    assert trades(ev) == [("72.6", "30")]


def test_cancel_rejects(eq):
    eq.process(NewOrder("B1", "A", "VOD.L", "BUY", 100, "72.40"))
    assert rejects(eq.process(CancelOrder("C1", "NOPE", "A", "VOD.L"))) == ["UNKNOWN_ORDER"]
    assert rejects(eq.process(CancelOrder("C2", "B1", "OTHER", "VOD.L"))) == ["UNKNOWN_ORDER"]
    eq.process(CancelOrder("C3", "B1", "A", "VOD.L"))
    assert rejects(eq.process(CancelOrder("C4", "B1", "A", "VOD.L"))) == ["TOO_LATE_TO_CANCEL"]
    assert rejects(eq.process(CancelOrder("C3", "B1", "A", "VOD.L"))) == ["DUPLICATE_CL_ORD_ID"]


def test_circuit_breaker_and_volatility_auction(eq):
    eq.process(NewOrder("S1", "A", "VOD.L", "SELL", 100, "72.50"))
    eq.process(NewOrder("B1", "B", "VOD.L", "BUY", 100, "72.50"))       # last = 72.50
    eq.process(NewOrder("S2", "A", "VOD.L", "SELL", 100, "76.20"))      # +5.1%
    ev = eq.process(NewOrder("B2", "B", "VOD.L", "BUY", 100, "76.50"))
    assert trades(ev) == [] and eq.phase("VOD.L").value == "VOLATILITY_AUCTION"
    assert eq.phase("BARC.L").value == "CONTINUOUS"
    ev = eq.process(AdvanceTime(119))
    assert trades(ev) == []
    ev = eq.process(AdvanceTime(2))
    assert trades(ev) == [("76.2", "100")] and eq.phase("VOD.L").value == "CONTINUOUS"
