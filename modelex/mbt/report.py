"""Render suite results as Markdown and standalone HTML (no external deps)."""
from __future__ import annotations

import datetime as dt
import html
import json
from collections import Counter
from pathlib import Path

from .invariants import INVARIANTS


def _blocks(reports, meta: dict) -> list:
    B = []
    overall = all(r.passed for r in reports)
    B.append(("h1", "ModelEx - Model-Based Test Report"))
    B.append(("p", f"Exchange: **{meta['exchange']}** ({meta['mic']}) · Trading date {meta['trading_date']} · "
                   f"Seed {meta['seed']} · {meta['steps']:,} generated steps per asset class · "
                   f"Generated {meta['generated']}"))
    B.append(("verdict", overall))
    rows = []
    for r in reports:
        s, sim, cov = r.scenario, r.simulation, r.coverage
        p, t = s.counts
        killed = sum(1 for d in r.differential if d["expected"] == d["outcome"])
        rows.append([r.asset_class, f"{p}/{t}", f"{len(s.violations) + len(sim.violations)}",
                     f"{sim.protocol_messages:,} / {len(sim.protocol_mismatches)}",
                     f"{cov['exercised']}/{cov['reachable']}", f"{killed}/{len(r.differential)}",
                     "PASS" if r.passed else "FAIL"])
    B.append(("h2", "Acceptance summary"))
    B.append(("table", ["Asset class", "Scenario steps passed", "Invariant violations", "Protocol msgs / mismatches",
                        "Validation rules exercised", "Differential verdicts as expected", "Result"], rows))
    B.append(("p", "Acceptance criteria: every scenario expectation met; zero invariant violations across scenario and "
                   "simulation; every message survives a wire-protocol round trip; every reachable validation rule "
                   "exercised; a clean wire-level SUT agrees with the model on every response, and every non-equivalent "
                   "mutant is detected."))

    for r in reports:
        s, sim, cov = r.scenario, r.simulation, r.coverage
        B.append(("h2", f"{r.asset_class}"))
        B.append(("h3", f"Test order book scenario - {s.name}"))
        B.append(("p", s.description))
        p, t = s.counts
        B.append(("p", f"**{p}/{t} steps passed**, {s.trades} trades, {len(s.violations)} invariant violations."))
        fails = [[str(x.index), x.label, "; ".join(x.messages)] for x in s.steps if not x.passed]
        if fails:
            B.append(("table", ["Step", "Description", "Failure"], fails))
        B.append(("table", ["#", "Step", "Result"], [[str(x.index), x.label, "PASS" if x.passed else "FAIL"]
                                                    for x in s.steps]))

        B.append(("h3", "Generated trading-day simulation"))
        accepted = sim.exec_types.get("NEW", 0)
        rejected = sim.exec_types.get("REJECTED", 0)
        B.append(("table", ["Metric", "Value"], [
            ["Commands", f"{sum(sim.commands.values()):,} ({', '.join(f'{k} {v:,}' for k, v in sim.commands.most_common())})"],
            ["Orders accepted / rejected", f"{accepted:,} / {rejected:,} ({rejected * 100 / max(accepted + rejected, 1):.1f}% rejected)"],
            ["Trades (continuous / auction)", f"{sim.trades:,} ({sim.continuous_trades:,} / {sim.auction_trades:,})"],
            ["Execution reports", ", ".join(f"{k} {v:,}" for k, v in sim.exec_types.most_common())],
            ["Cancel/replace rejects", ", ".join(f"{k} {v}" for k, v in sim.cancel_rejects.most_common()) or "-"],
            ["Circuit breakers", str(sim.circuit_breakers)],
            ["Schedule phase path", " -> ".join(sim.phase_path) or "CONTINUOUS (24x7)"],
            ["Illegal transition probes rejected", str(sim.phase_rejections)],
            ["Alerts", ", ".join(f"{k} {v}" for k, v in sim.alerts.most_common()) or "-"],
            [f"Protocol round trips ({sim.protocol})", f"{sim.protocol_messages:,} messages, {len(sim.protocol_mismatches)} mismatches"],
            ["Invariant checks", f"{len(INVARIANTS)} invariants after every step; {len(sim.violations)} violations"],
            ["Runtime", f"{sim.duration_s}s"],
        ]))
        B.append(("table", ["Reject reason", "Count"], [[k, str(v)] for k, v in sim.reject_reasons.most_common()]))
        if sim.violations:
            vc = Counter(v.invariant for v in sim.violations)
            B.append(("table", ["Invariant", "Violations", "First example"],
                      [[k, str(n), next(v.message for v in sim.violations if v.invariant == k)] for k, n in vc.items()]))
        rows = []
        for sym, st in sim.symbols.items():
            fb = sim.final_books.get(sym, {})
            bid = fb.get("bids", [[None, None]])
            ask = fb.get("asks", [[None, None]])
            rows.append([sym, st["open"] or "-", st["high"] or "-", st["low"] or "-", st["last"] or "-",
                         st["vwap"] or "-", st["volume"], str(st["trades"]), str(st["circuit_breakers"]),
                         f"{bid[0][0] if bid else '-'} / {ask[0][0] if ask else '-'}"])
        B.append(("table", ["Symbol", "Open", "High", "Low", "Last", "VWAP", "Volume", "Trades", "CB", "Final bid / ask"], rows))

        B.append(("h3", "Validation rule coverage"))
        B.append(("p", f"**{cov['exercised']}/{cov['reachable']}** reachable rules produced at least one rejection "
                       f"(scenario + simulation)." + (f" Missed: {', '.join(cov['missed'])}." if cov['missed'] else "")))
        B.append(("table", ["Rule", "Rejections", "Note"],
                  [[k, str(v), cov["unreachable"].get(k, "")] for k, v in cov["hits"].items()]))

        B.append(("h3", "Differential testing (simulation trace replayed against SUTs)"))
        B.append(("table", ["System under test", "Expected", "Outcome", "Responses compared", "First divergence"],
                  [[d["sut"], d["expected"], d["outcome"] + (" ✓" if d["outcome"] == d["expected"] else " ✗"),
                    f"{d['responses']:,}",
                    (f"step {d['first_divergence_step']}: {d['detail']}" if d["first_divergence_step"] is not None
                     else (d["note"] or "-"))] for d in r.differential]))

    B.append(("h2", "Invariants checked"))
    B.append(("table", ["Invariant", "Property"], [[k, v] for k, v in INVARIANTS.items()]))
    return B


def _md_inline(s: str) -> str:
    return s


def to_markdown(blocks) -> str:
    out = []
    for b in blocks:
        if b[0] == "h1":
            out.append(f"# {b[1]}\n")
        elif b[0] == "h2":
            out.append(f"\n## {b[1]}\n")
        elif b[0] == "h3":
            out.append(f"\n### {b[1]}\n")
        elif b[0] == "p":
            out.append(b[1] + "\n")
        elif b[0] == "verdict":
            out.append(f"**Overall result: {'PASS' if b[1] else 'FAIL'}**\n")
        elif b[0] == "table":
            h, rows = b[1], b[2]
            esc = lambda c: str(c).replace("|", "\\|")
            out.append("| " + " | ".join(h) + " |")
            out.append("|" + "---|" * len(h))
            for r in rows:
                out.append("| " + " | ".join(esc(c) for c in r) + " |")
            out.append("")
    return "\n".join(out) + "\n"


CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d2433;max-width:1100px;margin:32px auto;padding:0 20px;line-height:1.45}
h1{font-size:26px;margin-bottom:4px}h2{font-size:20px;margin-top:36px;border-bottom:2px solid #e3e7ef;padding-bottom:6px}
h3{font-size:16px;margin-top:22px;color:#33415c}p{margin:8px 0}
table{border-collapse:collapse;width:100%;margin:10px 0 16px;font-size:13px}
th{background:#f3f5f9;text-align:left;font-weight:600}th,td{border:1px solid #e3e7ef;padding:5px 8px;vertical-align:top}
td.pass{color:#0b7a3e;font-weight:600}td.fail{color:#b42318;font-weight:600}
.verdict{display:inline-block;padding:6px 14px;border-radius:6px;font-weight:700;margin:8px 0}
.v-pass{background:#e7f6ec;color:#0b7a3e}.v-fail{background:#fdecea;color:#b42318}
@media print{body{margin:0;max-width:none}h2{page-break-after:avoid}table{page-break-inside:auto}tr{page-break-inside:avoid}}
"""


def to_html(blocks) -> str:
    def inline(s):
        s = html.escape(str(s))
        parts = s.split("**")
        return "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))

    out = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>ModelEx MBT Report</title>",
           f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{CSS}</style></head><body>"]
    for b in blocks:
        if b[0] in ("h1", "h2", "h3"):
            out.append(f"<{b[0]}>{inline(b[1])}</{b[0]}>")
        elif b[0] == "p":
            out.append(f"<p>{inline(b[1])}</p>")
        elif b[0] == "verdict":
            out.append(f"<div class='verdict {'v-pass' if b[1] else 'v-fail'}'>Overall result: {'PASS' if b[1] else 'FAIL'}</div>")
        elif b[0] == "table":
            out.append("<table><tr>" + "".join(f"<th>{inline(h)}</th>" for h in b[1]) + "</tr>")
            for r in b[2]:
                cells = []
                for c in r:
                    cls = " class='pass'" if str(c).startswith(("PASS", "AGREE ✓", "KILLED ✓")) else \
                        " class='fail'" if str(c).startswith("FAIL") or str(c).endswith("✗") else ""
                    cells.append(f"<td{cls}>{inline(c)}</td>")
                out.append("<tr>" + "".join(cells) + "</tr>")
            out.append("</table>")
    out.append("</body></html>")
    return "\n".join(out)


def write_reports(reports, config, out_dir, steps: int, seed: int) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"exchange": config.exchange_name, "mic": config.mic, "trading_date": config.trading_date.isoformat(),
            "seed": seed, "steps": steps, "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    blocks = _blocks(reports, meta)
    (out / "mbt_report.md").write_text(to_markdown(blocks))
    (out / "mbt_report.html").write_text(to_html(blocks))
    summary = {"meta": meta, "passed": all(r.passed for r in reports), "asset_classes": {}}
    for r in reports:
        summary["asset_classes"][r.asset_class] = {
            "passed": r.passed, "scenario_steps": list(r.scenario.counts),
            "scenario_violations": len(r.scenario.violations), "sim_violations": len(r.simulation.violations),
            "trades": r.simulation.trades, "rejects": dict(r.simulation.reject_reasons),
            "protocol_mismatches": len(r.simulation.protocol_mismatches), "coverage": r.coverage,
            "differential": r.differential}
    (out / "mbt_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return {"markdown": out / "mbt_report.md", "html": out / "mbt_report.html", "json": out / "mbt_summary.json"}
