"""Walk an equity opening auction and a continuous trade, printing FIX output."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modelex import Exchange, NewOrder, SetPhase  # noqa: E402
from modelex.protocol import get_mapper, pretty  # noqa: E402

ex = Exchange.from_project(ROOT, asset_classes=["EQUITY"], auto_schedule=False)
fix = get_mapper("FIX44", ex.config)


def send(cmd):
    for ev in ex.process(cmd):
        msg = fix.encode_event(ev)
        print("  ", pretty(msg) if msg else f"[{ev.TYPE}] {getattr(ev, 'new_phase', '')} {getattr(ev, 'price', '')}")


print("PRE_OPEN"); send(SetPhase("EQUITY_STD", "PRE_OPEN"))
print("Orders"); send(NewOrder("B1", "FIRM_A", "VOD.L", "BUY", 1000, "72.60"))
send(NewOrder("S1", "FIRM_B", "VOD.L", "SELL", 600, "72.40"))
send(NewOrder("S2", "FIRM_C", "VOD.L", "SELL", 800, "72.50"))
send(NewOrder("X1", "FIRM_C", "VOD.L", "SELL", 800, "72.505"))      # off tick -> reject
print("Open (uncross)"); send(SetPhase("EQUITY_STD", "CONTINUOUS"))
print(ex.book_snapshot("VOD.L"))
