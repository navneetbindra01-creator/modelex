"""Order validation rule engine.

Each rule is a small function registered by name. The market config lists which
rules run, and in what order, globally and per asset class - so an exchange can
reorder, drop or add rules without touching the engine::

    from modelex.validation import validation_rule, Rejection
    from modelex.types import RejectReason

    @validation_rule("NO_PENNY_STOCKS", applies_to_amend=True)
    def no_penny(ctx):
        if ctx.cmd.price is not None and ctx.cmd.price < 1:
            return Rejection(RejectReason.INVALID_PRICE, "penny prices not permitted")

then add "NO_PENNY_STOCKS" to an asset class's ``validation_rules``.
The first failing rule wins (deterministic reject reason for testing).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, Optional

from .types import NewOrder, OrderType, RejectReason, Side, TimeInForce

if TYPE_CHECKING:  # pragma: no cover
    from .config import AssetClassConfig
    from .exchange import Exchange
    from .refdata import Instrument


@dataclass
class Rejection:
    reason: RejectReason
    text: str = ""


@dataclass
class ValidationContext:
    cmd: NewOrder
    instrument: Optional["Instrument"]
    ac: Optional["AssetClassConfig"]
    exchange: "Exchange"
    is_amend: bool = False

    @property
    def now(self):
        return self.exchange.clock.now()


@dataclass
class RuleSpec:
    name: str
    func: Callable
    applies_to_amend: bool
    description: str


RULES: dict = {}


def validation_rule(name: str, applies_to_amend: bool = False, description: str = ""):
    def deco(fn):
        RULES[name] = RuleSpec(name, fn, applies_to_amend, description or (fn.__doc__ or "").strip())
        return fn
    return deco


class Validator:
    def __init__(self, config):
        from collections import Counter
        self.config = config
        self.hits = Counter()          # rule name -> rejections produced (rule coverage)
        names = list(config.global_validation_rules)
        for ac in config.asset_classes.values():
            names += ac.validation_rules
        unknown = sorted({n for n in names if n not in RULES})
        if unknown:
            raise KeyError(f"unknown validation rule(s) {unknown}. Registered: {sorted(RULES)}")

    def _run(self, names, ctx) -> Optional[Rejection]:
        for name in names:
            spec = RULES[name]
            if ctx.is_amend and not spec.applies_to_amend:
                continue
            r = spec.func(ctx)
            if r is not None:
                self.hits[name] += 1
                return r
        return None

    def validate_new(self, cmd, instrument, ac, exchange) -> Optional[Rejection]:
        ctx = ValidationContext(cmd, instrument, ac, exchange)
        r = self._run(self.config.global_validation_rules, ctx)
        if r is None and ac is not None:
            r = self._run(ac.validation_rules, ctx)
        return r

    def validate_amend(self, cmd, instrument, ac, exchange) -> Optional[Rejection]:
        ctx = ValidationContext(cmd, instrument, ac, exchange, is_amend=True)
        r = self._run(self.config.global_validation_rules, ctx)
        if r is None and ac is not None:
            r = self._run(ac.validation_rules, ctx)
        return r


# =========================================================================== built-in rules

@validation_rule("REQUIRED_FIELDS", applies_to_amend=True)
def _required(ctx):
    """ClOrdID, participant, symbol present; side/type/TIF/qty/price well-formed."""
    c = ctx.cmd
    missing = [f for f in ("cl_ord_id", "participant", "symbol") if not getattr(c, f)]
    if missing:
        return Rejection(RejectReason.MISSING_OR_INVALID_FIELD, f"missing {', '.join(missing)}")
    if not isinstance(c.side, Side):
        return Rejection(RejectReason.MISSING_OR_INVALID_FIELD, f"invalid side {c.side!r}")
    if not isinstance(c.order_type, OrderType):
        return Rejection(RejectReason.MISSING_OR_INVALID_FIELD, f"invalid order_type {c.order_type!r}")
    if not isinstance(c.tif, TimeInForce):
        return Rejection(RejectReason.MISSING_OR_INVALID_FIELD, f"invalid tif {c.tif!r}")
    if not isinstance(c.qty, Decimal):
        return Rejection(RejectReason.MISSING_OR_INVALID_FIELD, f"invalid qty {c.qty!r}")
    if c.price is not None and not isinstance(c.price, Decimal):
        return Rejection(RejectReason.MISSING_OR_INVALID_FIELD, f"invalid price {c.price!r}")


@validation_rule("DUPLICATE_CL_ORD_ID")
def _dup_clid(ctx):
    """ClOrdID must be unique per participant per trading day."""
    if (ctx.cmd.participant, ctx.cmd.cl_ord_id) in ctx.exchange.seen_cl_ord_ids:
        return Rejection(RejectReason.DUPLICATE_CL_ORD_ID, f"duplicate ClOrdID {ctx.cmd.cl_ord_id}")


@validation_rule("UNKNOWN_INSTRUMENT")
def _unknown(ctx):
    """Symbol must exist in the reference data golden source."""
    if ctx.instrument is None:
        return Rejection(RejectReason.UNKNOWN_INSTRUMENT, f"unknown symbol {ctx.cmd.symbol}")


@validation_rule("INSTRUMENT_STATUS")
def _status(ctx):
    """Instrument status must be ACTIVE."""
    if ctx.instrument is not None and not ctx.instrument.tradable:
        return Rejection(RejectReason.INSTRUMENT_NOT_TRADABLE, f"instrument status {ctx.instrument.status}")


@validation_rule("INSTRUMENT_EXPIRY")
def _expiry(ctx):
    """Dated instruments (futures) cannot trade after expiry."""
    i = ctx.instrument
    if i is not None and i.expiry is not None and i.expiry < ctx.now.date():
        return Rejection(RejectReason.INSTRUMENT_EXPIRED, f"instrument expired {i.expiry.isoformat()}")


@validation_rule("SESSION_PHASE")
def _phase(ctx):
    """Trading phase must accept new orders and the TIF/order type."""
    if ctx.instrument is None:
        return None
    ph = ctx.exchange.phase(ctx.cmd.symbol)
    rule = ctx.exchange.config.phase_rules[ph]
    if not rule.accept_new:
        return Rejection(RejectReason.EXCHANGE_CLOSED, f"new orders not accepted in phase {ph.value}")
    if rule.allowed_tif is not None and ctx.cmd.tif not in rule.allowed_tif:
        return Rejection(RejectReason.TIF_NOT_ALLOWED_IN_PHASE, f"{ctx.cmd.tif.value} not allowed in {ph.value}")
    if rule.allowed_order_types is not None and ctx.cmd.order_type not in rule.allowed_order_types:
        return Rejection(RejectReason.ORDER_TYPE_NOT_ALLOWED_IN_PHASE,
                         f"{ctx.cmd.order_type.value} not allowed in {ph.value}")


@validation_rule("ORDER_TYPE")
def _otype(ctx):
    """Order type must be enabled for the asset class."""
    if ctx.ac is not None and ctx.cmd.order_type not in ctx.ac.order_types:
        return Rejection(RejectReason.UNSUPPORTED_ORDER_TYPE, f"{ctx.cmd.order_type.value} not supported for {ctx.ac.name}")


@validation_rule("TIME_IN_FORCE")
def _tif(ctx):
    """TIF must be enabled for the asset class."""
    if ctx.ac is not None and ctx.cmd.tif not in ctx.ac.time_in_force:
        return Rejection(RejectReason.UNSUPPORTED_TIF, f"{ctx.cmd.tif.value} not supported for {ctx.ac.name}")


@validation_rule("PRICE_PRESENCE", applies_to_amend=True)
def _price_presence(ctx):
    """LIMIT needs a positive price; MARKET must not carry one."""
    c = ctx.cmd
    if c.order_type is OrderType.LIMIT:
        if c.price is None:
            return Rejection(RejectReason.PRICE_REQUIRED, "limit order requires a price")
        if c.price <= 0:
            return Rejection(RejectReason.INVALID_PRICE, f"price must be > 0 (got {c.price})")
    elif c.order_type is OrderType.MARKET and c.price is not None:
        return Rejection(RejectReason.PRICE_NOT_ALLOWED, "market order must not carry a price")


@validation_rule("QUANTITY_POSITIVE", applies_to_amend=True)
def _qty_pos(ctx):
    """Quantity must be > 0."""
    if ctx.cmd.qty <= 0:
        return Rejection(RejectReason.INVALID_QUANTITY, f"quantity must be > 0 (got {ctx.cmd.qty})")


@validation_rule("LOT_SIZE", applies_to_amend=True)
def _lot(ctx):
    """Quantity must be a multiple of the instrument lot size."""
    i = ctx.instrument
    if i is not None and not i.is_lot_multiple(ctx.cmd.qty):
        return Rejection(RejectReason.LOT_SIZE_VIOLATION, f"qty {ctx.cmd.qty} not a multiple of lot {i.lot_size}")


@validation_rule("MIN_MAX_QTY", applies_to_amend=True)
def _minmax(ctx):
    """Quantity within instrument min/max order size."""
    i = ctx.instrument
    if i is None:
        return None
    if ctx.cmd.qty < i.min_qty:
        return Rejection(RejectReason.QTY_BELOW_MIN, f"qty {ctx.cmd.qty} < min {i.min_qty}")
    if i.max_qty is not None and ctx.cmd.qty > i.max_qty:
        return Rejection(RejectReason.QTY_ABOVE_MAX, f"qty {ctx.cmd.qty} > max {i.max_qty}")


@validation_rule("UNIQUE_ITEM", applies_to_amend=True)
def _unique(ctx):
    """Unique collectibles trade exactly one unit."""
    i = ctx.instrument
    if i is not None and i.unique and ctx.cmd.qty != 1:
        return Rejection(RejectReason.INVALID_QUANTITY, "unique item: quantity must be exactly 1")


@validation_rule("TICK_SIZE", applies_to_amend=True)
def _tick(ctx):
    """Limit price must sit on the tick grid (supports banded tick tables)."""
    i, c = ctx.instrument, ctx.cmd
    if i is not None and c.order_type is OrderType.LIMIT and c.price is not None and not i.is_on_tick(c.price):
        return Rejection(RejectReason.INVALID_TICK, f"price {c.price} not on tick {i.tick_for(c.price)}")


@validation_rule("PRICE_BAND", applies_to_amend=True)
def _band(ctx):
    """Static collar: limit price within +/- price_band_pct of the reference price."""
    i, c = ctx.instrument, ctx.cmd
    if i is None or c.order_type is not OrderType.LIMIT or c.price is None:
        return None
    if i.price_band_pct is None or not i.reference_price:
        return None
    lo = i.reference_price * (1 - i.price_band_pct / 100)
    hi = i.reference_price * (1 + i.price_band_pct / 100)
    if c.price < lo or c.price > hi:
        return Rejection(RejectReason.PRICE_OUTSIDE_BAND,
                         f"price {c.price} outside band [{lo.normalize()}, {hi.normalize()}]")


@validation_rule("MAX_NOTIONAL", applies_to_amend=True)
def _notional(ctx):
    """Order notional (price x qty x multiplier) within the instrument/asset-class limit."""
    i, c = ctx.instrument, ctx.cmd
    if i is None:
        return None
    limit = i.max_notional if i.max_notional is not None else (ctx.ac.max_notional if ctx.ac else None)
    if limit is None:
        return None
    px = c.price if c.price is not None else i.reference_price
    if px is None:
        return None
    notional = px * c.qty * i.multiplier
    if notional > limit:
        return Rejection(RejectReason.NOTIONAL_LIMIT_EXCEEDED, f"notional {notional.normalize()} > limit {limit}")


@validation_rule("DUPLICATE_ORDER")
def _dup_content(ctx):
    """Fat-finger guard: identical order from same participant within the configured window."""
    if ctx.ac is None or ctx.ac.duplicate_order_window_ms <= 0:
        return None
    last = ctx.exchange.recent_content.get(ctx.exchange.content_key(ctx.cmd))
    if last is not None and (ctx.now - last).total_seconds() * 1000 <= ctx.ac.duplicate_order_window_ms:
        return Rejection(RejectReason.DUPLICATE_ORDER,
                         f"identical order received within {ctx.ac.duplicate_order_window_ms}ms")
