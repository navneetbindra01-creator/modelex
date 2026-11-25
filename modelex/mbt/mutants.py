"""Deliberately faulty exchange variants ("mutants").

Used to prove the test oracle has teeth: a sound MBT harness must flag every
mutant. They are also handy training material - each mirrors a defect class
seen in real matching-engine releases.
"""
from __future__ import annotations

import copy

from ..exchange import Exchange
from ..matching import AllocationAlgorithm, register_algorithm
from ..types import RejectReason
from ..validation import Rejection, validation_rule


@register_algorithm("MUTANT_LIFO")
class _LIFO(AllocationAlgorithm):
    """Bug: newest order at a price level is filled first."""

    def allocate(self, resting, qty, lot):
        out, remaining = [], qty
        for o in reversed(resting):
            if remaining <= 0:
                break
            q = min(o.leaves_qty, remaining)
            out.append((o, q))
            remaining -= q
        return out


@validation_rule("MUTANT_TICK_SIZE", applies_to_amend=True)
def _bad_tick(ctx):
    """Bug: validates against the first tick band only (ignores banded tick tables)."""
    i, c = ctx.instrument, ctx.cmd
    if i is not None and c.price is not None and c.price > 0 and c.price % i.tick_table[0].tick != 0:
        return Rejection(RejectReason.INVALID_TICK, "off tick")


@validation_rule("MUTANT_BAND_INCLUSIVE_BUG", applies_to_amend=True)
def _bad_band(ctx):
    """Bug: off-by-one-tick band check - rejects prices exactly on the band edge."""
    i, c = ctx.instrument, ctx.cmd
    if i is None or c.price is None or i.price_band_pct is None or not i.reference_price:
        return None
    lo = i.reference_price * (1 - i.price_band_pct / 100)
    hi = i.reference_price * (1 + i.price_band_pct / 100)
    t = i.tick_for(c.price)
    if c.price < lo + t or c.price > hi - t:
        return Rejection(RejectReason.PRICE_OUTSIDE_BAND, "outside band")


MUTANTS = {
    "LIFO_MATCHING": "Price level filled newest-first instead of FIFO",
    "NO_DUPLICATE_CLORDID_CHECK": "Duplicate ClOrdID validation removed",
    "FLAT_TICK_VALIDATION": "Tick check ignores banded tick tables",
    "BAND_EDGE_OFF_BY_ONE": "Static price band rejects prices on the band edge",
    "NO_STP": "Self-trade prevention disabled",
}


def mutant_config(config, mutant: str, asset_class: str):
    cfg = copy.deepcopy(config)
    ac = cfg.asset_classes[asset_class]
    if mutant == "LIFO_MATCHING":
        ac.matching_algorithm = "MUTANT_LIFO"
    elif mutant == "NO_DUPLICATE_CLORDID_CHECK":
        cfg.global_validation_rules = [r for r in cfg.global_validation_rules if r != "DUPLICATE_CL_ORD_ID"]
    elif mutant == "FLAT_TICK_VALIDATION":
        ac.validation_rules = ["MUTANT_TICK_SIZE" if r == "TICK_SIZE" else r for r in ac.validation_rules]
    elif mutant == "BAND_EDGE_OFF_BY_ONE":
        ac.validation_rules = ["MUTANT_BAND_INCLUSIVE_BUG" if r == "PRICE_BAND" else r for r in ac.validation_rules]
    elif mutant == "NO_STP":
        from ..types import STPMode
        ac.self_trade_prevention = STPMode.NONE
    else:
        raise KeyError(mutant)
    return cfg


def mutant_factory(config, refdata, mutant: str, asset_class: str, **kw):
    cfg = mutant_config(config, mutant, asset_class)
    return lambda: Exchange(cfg, refdata, **kw)
