"""Template: differential-test a real venue (UAT) against ModelEx.

1. Implement `transport` - send one FIX message to your venue's order-entry
   session and return the FIX messages it sends back for that request.
2. Implement `control` - out-of-band hook for phase changes and clock moves
   (an admin API, a test-harness endpoint, or a scheduler you trigger).
3. Generate a trace with the simulator (or write a scenario) and run.

Run as-is to see the template exercised against an in-process ModelEx behind a
FIX gateway (which must agree 100%).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modelex import Exchange, MarketConfig, RefDataStore  # noqa: E402
from modelex.mbt.differential import DifferentialTester, WireAdapter, first_difference  # noqa: E402
from modelex.mbt.runner import SimulationRunner  # noqa: E402
from modelex.protocol import ProtocolGateway, get_mapper  # noqa: E402

cfg = MarketConfig.from_file(ROOT / "config" / "market_default.json")
store = RefDataStore.from_files([ROOT / "refdata" / "equities.json"])
model_factory = lambda: Exchange(cfg, store, auto_schedule=False)
fix = get_mapper("FIX44", cfg)

# ---- replace these three with your venue connectivity -------------------------
_venue = {}


def reset():                      # e.g. reset UAT books / start of day
    _venue["ex"] = model_factory()
    _venue["gw"] = ProtocolGateway(_venue["ex"], fix)


def transport(raw_fix: str) -> list:
    return _venue["gw"].handle(raw_fix)


def control(cmd) -> list:         # SetPhase / AdvanceTime / HaltInstrument / ResumeInstrument
    return [m for e in _venue["ex"].process(cmd) if (m := fix.encode_event(e))]
# --------------------------------------------------------------------------------


if __name__ == "__main__":
    trace = SimulationRunner(model_factory(), "EQUITY", steps=2000, seed=42).run().trace
    sut = WireAdapter(fix, transport, control, reset, name="UAT venue")
    res = DifferentialTester(model_factory, sut).run(trace)
    print(f"{res.commands} commands, {res.responses_compared} responses compared, "
          f"{len(res.divergences)} divergences")
    for d in res.divergences[:5]:
        print(f"  step {d.index}: {first_difference(d)}")
