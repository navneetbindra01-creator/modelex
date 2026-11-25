"""ModelEx command line.

    python -m modelex check-refdata refdata/*.json
    python -m modelex scenario scenarios/equity_orderbook.json
    python -m modelex simulate --asset-class EQUITY --steps 5000 --seed 7 --trace out.jsonl
    python -m modelex replay out.jsonl --asset-class EQUITY
    python -m modelex suite --steps 5000 --out reports
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT_DEFAULT = Path.cwd()


def _factory(root):
    from .exchange import Exchange
    return lambda acs=None, auto=False: Exchange.from_project(root, asset_classes=acs, auto_schedule=auto)


def cmd_check(args):
    from .refdata import RefDataError, RefDataStore
    try:
        store = RefDataStore.from_files(args.files)
    except RefDataError as e:
        print(e)
        return 1
    for s in store.sources:
        print(f"OK  {s['source']}: {s['count']} instruments ({s['asset_class']}, as of {s['as_of']})")
    return 0


def cmd_scenario(args):
    from .mbt.scenario import ScenarioRunner
    rc = 0
    for f in args.files:
        r = ScenarioRunner(_factory(args.root)).run(ScenarioRunner.load(f))
        p, t = r.counts
        print(f"{'PASS' if r.passed else 'FAIL'}  {f}: {p}/{t} steps, {r.trades} trades, {len(r.violations)} invariant violations")
        for s in r.steps:
            if not s.passed or args.verbose:
                print(f"   {'ok ' if s.passed else 'XX '} {s.index:>3} {s.label} {'; '.join(s.messages)}")
        for v in r.violations:
            print(f"   INVARIANT {v.invariant} @ step {v.step}: {v.message}")
        rc |= 0 if r.passed else 1
    return rc


def cmd_simulate(args):
    from .exchange import Exchange
    from .mbt.runner import SimulationRunner
    from .protocol import get_mapper
    ex = Exchange.from_project(args.root, asset_classes=[args.asset_class], auto_schedule=False)
    mapper = get_mapper(ex.config.asset_classes[args.asset_class.upper()].protocol, ex.config)
    r = SimulationRunner(ex, args.asset_class, steps=args.steps, seed=args.seed, protocol_mapper=mapper,
                         trace_path=args.trace).run()
    print(json.dumps({"asset_class": r.asset_class, "steps": r.steps, "seed": r.seed, "trades": r.trades,
                      "auction_trades": r.auction_trades, "circuit_breakers": r.circuit_breakers,
                      "exec_types": dict(r.exec_types), "reject_reasons": dict(r.reject_reasons),
                      "invariant_violations": len(r.violations), "protocol_messages": r.protocol_messages,
                      "protocol_mismatches": len(r.protocol_mismatches), "duration_s": r.duration_s}, indent=2))
    for v in r.violations[:20]:
        print(f"INVARIANT {v.invariant} @ step {v.step}: {v.message}")
    return 0 if r.passed else 1


def cmd_replay(args):
    from .codec import command_from_dict
    from .exchange import Exchange
    from .mbt.invariants import InvariantChecker
    ex = Exchange.from_project(args.root, asset_classes=[args.asset_class], auto_schedule=False)
    chk = InvariantChecker(ex)
    types = Counter()
    for i, line in enumerate(Path(args.trace).read_text().splitlines()):
        cmd = command_from_dict(json.loads(line))
        chk.before(cmd)
        evs = ex.process(cmd)
        chk.after(i, cmd, evs)
        types.update(e.TYPE for e in evs)
    print(f"replayed {i + 1} commands: {dict(types)}; {len(ex.trades)} trades; {len(chk.violations)} violations")
    return 0 if not chk.violations else 1


def cmd_suite(args):
    from .config import MarketConfig
    from .mbt.report import write_reports
    from .mbt.suite import run_suite
    reports = run_suite(args.root, steps=args.steps, seed=args.seed, out_dir=args.out,
                        asset_classes=args.asset_class or None)
    cfg = MarketConfig.from_file(Path(args.root) / "config" / "market_default.json")
    paths = write_reports(reports, cfg, args.out, args.steps, args.seed)
    for r in reports:
        p, t = r.scenario.counts
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.asset_class:<12} scenario {p}/{t}  trades {r.simulation.trades:>5}  "
              f"violations {len(r.scenario.violations) + len(r.simulation.violations)}  "
              f"protocol mismatches {len(r.simulation.protocol_mismatches)}  "
              f"rules {r.coverage['exercised']}/{r.coverage['reachable']}  "
              f"differential {sum(d['outcome'] == d['expected'] for d in r.differential)}/{len(r.differential)}")
    print("reports:", ", ".join(str(p) for p in paths.values()))
    return 0 if all(r.passed for r in reports) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modelex", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT_DEFAULT), help="project root containing config/ refdata/ scenarios/")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-refdata"); p.add_argument("files", nargs="+"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("scenario"); p.add_argument("files", nargs="+"); p.add_argument("-v", "--verbose", action="store_true"); p.set_defaults(fn=cmd_scenario)
    p = sub.add_parser("simulate"); p.add_argument("--asset-class", required=True); p.add_argument("--steps", type=int, default=5000)
    p.add_argument("--seed", type=int, default=7); p.add_argument("--trace"); p.set_defaults(fn=cmd_simulate)
    p = sub.add_parser("replay"); p.add_argument("trace"); p.add_argument("--asset-class", required=True); p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("suite"); p.add_argument("--steps", type=int, default=5000); p.add_argument("--seed", type=int, default=20261125)
    p.add_argument("--out", default="reports"); p.add_argument("--asset-class", action="append"); p.set_defaults(fn=cmd_suite)
    args = ap.parse_args(argv)
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
