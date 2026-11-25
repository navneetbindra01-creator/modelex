import json

from modelex import AdvanceTime, HaltInstrument, NewOrder, ResumeInstrument, SetPhase
from modelex.codec import normalize_event
from modelex.protocol import Fix44Mapper, JsonMapper, ProtocolGateway, get_mapper, pretty
from modelex.protocol.fix44 import SOH
from tests.conftest import rejects, trades


def test_auto_schedule_runs_the_day(make_ex):
    ex = make_ex(["EQUITY"], auto=True)
    ev = ex.process(AdvanceTime(7 * 3600 + 55 * 60))
    assert ex.sessions.schedule_phase["EQUITY_STD"].value == "PRE_OPEN"
    ex.process(NewOrder("B", "A", "VOD.L", "BUY", 100, "72.50"))
    ex.process(NewOrder("S", "B", "VOD.L", "SELL", 100, "72.50"))
    ev = ex.process(AdvanceTime(5 * 60))     # 08:00 open
    assert trades(ev) == [("72.5", "100")]
    ex.process(NewOrder("G", "A", "VOD.L", "BUY", 100, "72.00", tif="GTC"))
    ex.process(NewOrder("D", "A", "VOD.L", "BUY", 100, "71.00"))
    ex.process(AdvanceTime(10 * 3600))       # through the close
    assert ex.sessions.schedule_phase["EQUITY_STD"].value == "CLOSED"
    assert [o.cl_ord_id for o in ex.books["VOD.L"].orders()] == ["G"]


def test_illegal_transition_rejected(make_ex):
    ex = make_ex(["EQUITY"])
    ev = ex.process(SetPhase("EQUITY_STD", "POST_CLOSE"))
    assert rejects(ev) == ["INVALID_PHASE_TRANSITION"]
    assert ex.sessions.schedule_phase["EQUITY_STD"].value == "CLOSED"
    assert rejects(ex.process(SetPhase("NOPE", "PRE_OPEN"))) == ["INVALID_PHASE_TRANSITION"]


def test_halt_resume_uncrosses(make_ex):
    ex = make_ex(["CRYPTO"])
    ex.process(HaltInstrument("SOL-USD"))
    assert rejects(ex.process(NewOrder("A", "P", "SOL-USD", "BUY", "1", "150.000", tif="GTC"))) == ["EXCHANGE_CLOSED"]
    assert rejects(ex.process(HaltInstrument("SOL-USD"))) == ["INVALID_PHASE_TRANSITION"]
    ex.process(ResumeInstrument("SOL-USD"))
    assert ex.phase("SOL-USD").value == "CONTINUOUS"


def test_fix_framing_and_checksum():
    m = Fix44Mapper()
    raw = m.encode_command(NewOrder("C1", "FIRM_A", "VOD.L", "BUY", 100, "72.50"))
    tags = m.parse(raw)
    assert tags["35"] == "D" and tags["54"] == "1" and tags["44"] == "72.5" and tags["49"] == "FIRM_A"
    bad = raw.replace("38=100", "38=900")
    try:
        m.parse(bad)
        raise AssertionError("checksum not verified")
    except ValueError:
        pass


def test_fix_gateway_end_to_end(eq):
    m = get_mapper("FIX44", eq.config)
    gw = ProtocolGateway(eq, m)
    out = gw.handle(m.encode_command(NewOrder("C1", "FIRM_A", "VOD.L", "BUY", 100, "72.555")))
    t = m.parse(out[0])
    assert t["35"] == "8" and t["150"] == "8" and t["39"] == "8" and t["103"] == "18"
    assert t["58"].startswith("INVALID_TICK")
    gw.handle(m.encode_command(NewOrder("S1", "FIRM_B", "VOD.L", "SELL", 100, "72.50")))
    out = gw.handle(m.encode_command(NewOrder("B1", "FIRM_A", "VOD.L", "BUY", 40, "72.50")))
    fills = [m.parse(x) for x in out if m.parse(x)["150"] == "F"]
    assert len(fills) == 2 and {f["1057"] for f in fills} == {"Y", "N"}
    assert "|35=8|" in pretty(out[0]) and SOH not in pretty(out[0])


def test_roundtrip_normalized(eq):
    eq.process(NewOrder("S1", "FIRM_B", "VOD.L", "SELL", 100, "72.50"))
    evs = eq.process(NewOrder("B1", "FIRM_A", "VOD.L", "BUY", 40, "72.50")) + \
        eq.process(NewOrder("X", "FIRM_A", "VOD.L", "BUY", 0, "72.50"))
    for mapper in (get_mapper("FIX44", eq.config), get_mapper("JSON", eq.config)):
        for e in evs:
            n = normalize_event(e)
            if n:
                assert mapper.decode_report(mapper.encode_event(e)) == n


def test_json_mapping_vocabulary(eq):
    m = get_mapper("JSON", eq.config)
    ev = eq.process(NewOrder("X", "FIRM_A", "VOD.L", "BUY", 100, "72.555"))[0]
    msg = json.loads(m.encode_event(ev))
    assert msg["status"] == "rejected" and msg["rejectReason"] == "PRICE_FILTER" and msg["reasonCode"] == "INVALID_TICK"
    cmd = m.decode_command(json.dumps({"op": "new", "clientOrderId": "A", "account": "P", "symbol": "ETH-USD",
                                       "side": "sell", "type": "limit", "timeInForce": "GTC",
                                       "quantity": "1.5", "price": "3200.00"}))
    assert cmd.side.value == "SELL" and str(cmd.qty) == "1.5"
