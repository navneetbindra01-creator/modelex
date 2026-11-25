"""Canonical domain types for ModelEx.

Everything inside the exchange speaks these types. Protocol mappers translate
them to/from wire formats (FIX, JSON, ...). Prices and quantities are always
``decimal.Decimal`` so tick/lot arithmetic is exact.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, ClassVar, Optional, Union


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrdStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


TERMINAL_STATUSES = frozenset({OrdStatus.FILLED, OrdStatus.CANCELED, OrdStatus.REJECTED, OrdStatus.EXPIRED})
LIVE_STATUSES = frozenset({OrdStatus.NEW, OrdStatus.PARTIALLY_FILLED})


class ExecType(StrEnum):
    NEW = "NEW"
    TRADE = "TRADE"
    CANCELED = "CANCELED"
    REPLACED = "REPLACED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RejectReason(StrEnum):
    """Canonical (protocol-neutral) reject reasons. Protocol maps translate these."""
    MISSING_OR_INVALID_FIELD = "MISSING_OR_INVALID_FIELD"
    DUPLICATE_CL_ORD_ID = "DUPLICATE_CL_ORD_ID"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    UNKNOWN_INSTRUMENT = "UNKNOWN_INSTRUMENT"
    INSTRUMENT_NOT_TRADABLE = "INSTRUMENT_NOT_TRADABLE"
    INSTRUMENT_EXPIRED = "INSTRUMENT_EXPIRED"
    EXCHANGE_CLOSED = "EXCHANGE_CLOSED"
    TIF_NOT_ALLOWED_IN_PHASE = "TIF_NOT_ALLOWED_IN_PHASE"
    ORDER_TYPE_NOT_ALLOWED_IN_PHASE = "ORDER_TYPE_NOT_ALLOWED_IN_PHASE"
    UNSUPPORTED_ORDER_TYPE = "UNSUPPORTED_ORDER_TYPE"
    UNSUPPORTED_TIF = "UNSUPPORTED_TIF"
    PRICE_REQUIRED = "PRICE_REQUIRED"
    PRICE_NOT_ALLOWED = "PRICE_NOT_ALLOWED"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    LOT_SIZE_VIOLATION = "LOT_SIZE_VIOLATION"
    QTY_BELOW_MIN = "QTY_BELOW_MIN"
    QTY_ABOVE_MAX = "QTY_ABOVE_MAX"
    INVALID_TICK = "INVALID_TICK"
    PRICE_OUTSIDE_BAND = "PRICE_OUTSIDE_BAND"
    NOTIONAL_LIMIT_EXCEEDED = "NOTIONAL_LIMIT_EXCEEDED"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    TOO_LATE_TO_CANCEL = "TOO_LATE_TO_CANCEL"
    AMEND_NOT_ALLOWED = "AMEND_NOT_ALLOWED"
    INVALID_PHASE_TRANSITION = "INVALID_PHASE_TRANSITION"
    OTHER = "OTHER"


class Phase(StrEnum):
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    CONTINUOUS = "CONTINUOUS"
    PRE_CLOSE = "PRE_CLOSE"
    POST_CLOSE = "POST_CLOSE"
    HALTED = "HALTED"
    VOLATILITY_AUCTION = "VOLATILITY_AUCTION"


class MatchingMode(StrEnum):
    CONTINUOUS = "CONTINUOUS"   # incoming orders match immediately
    CALL = "CALL"               # orders accumulate, matched at uncross (auction)
    NONE = "NONE"               # no matching


class STPMode(StrEnum):
    NONE = "NONE"
    CANCEL_RESTING = "CANCEL_RESTING"
    CANCEL_INCOMING = "CANCEL_INCOMING"
    CANCEL_BOTH = "CANCEL_BOTH"


# --------------------------------------------------------------------------- helpers

def to_dec(v: Any) -> Optional[Decimal]:
    """Convert to Decimal (via str to avoid binary float artefacts)."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError(f"not a decimal: {v!r}")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError(f"not a decimal: {v!r}")
    if not d.is_finite():
        raise ValueError(f"not a finite decimal: {v!r}")
    return d


def fmt(v: Any) -> Optional[str]:
    """Canonical string form of a Decimal (no exponent, no trailing zeros)."""
    if v is None:
        return None
    if isinstance(v, Enum):
        return v.value
    if not isinstance(v, Decimal):
        return str(v)
    if v == 0:
        return "0"
    s = format(v.normalize(), "f")
    return s


def _coerce_enum(enum_cls, v):
    if v is None or isinstance(v, enum_cls):
        return v
    try:
        return enum_cls(str(v).upper())
    except ValueError:
        return v  # leave raw; validation rejects it


def _coerce_dec(v):
    try:
        return to_dec(v)
    except ValueError:
        return v  # leave raw; validation rejects it


# --------------------------------------------------------------------------- commands (inbound)

@dataclass
class NewOrder:
    cl_ord_id: str
    participant: str
    symbol: str
    side: Any
    qty: Any
    price: Any = None
    order_type: Any = OrderType.LIMIT
    tif: Any = TimeInForce.DAY
    account: Optional[str] = None
    TYPE: ClassVar[str] = "NewOrder"

    def __post_init__(self):
        self.side = _coerce_enum(Side, self.side)
        self.order_type = _coerce_enum(OrderType, self.order_type)
        self.tif = _coerce_enum(TimeInForce, self.tif)
        self.qty = _coerce_dec(self.qty)
        self.price = _coerce_dec(self.price)


@dataclass
class CancelOrder:
    cl_ord_id: str
    orig_cl_ord_id: str
    participant: str
    symbol: str
    TYPE: ClassVar[str] = "CancelOrder"


@dataclass
class ReplaceOrder:
    cl_ord_id: str
    orig_cl_ord_id: str
    participant: str
    symbol: str
    qty: Any = None
    price: Any = None
    TYPE: ClassVar[str] = "ReplaceOrder"

    def __post_init__(self):
        self.qty = _coerce_dec(self.qty)
        self.price = _coerce_dec(self.price)


@dataclass
class SetPhase:
    schedule: str
    phase: Any
    reason: str = "manual"
    TYPE: ClassVar[str] = "SetPhase"

    def __post_init__(self):
        self.phase = _coerce_enum(Phase, self.phase)


@dataclass
class AdvanceTime:
    seconds: Any
    TYPE: ClassVar[str] = "AdvanceTime"

    def __post_init__(self):
        self.seconds = _coerce_dec(self.seconds)


@dataclass
class HaltInstrument:
    symbol: str
    reason: str = "regulatory halt"
    TYPE: ClassVar[str] = "HaltInstrument"


@dataclass
class ResumeInstrument:
    symbol: str
    reason: str = "resume"
    TYPE: ClassVar[str] = "ResumeInstrument"


Command = Union[NewOrder, CancelOrder, ReplaceOrder, SetPhase, AdvanceTime, HaltInstrument, ResumeInstrument]
COMMAND_TYPES = {c.TYPE: c for c in (NewOrder, CancelOrder, ReplaceOrder, SetPhase, AdvanceTime,
                                      HaltInstrument, ResumeInstrument)}


# --------------------------------------------------------------------------- live order state

@dataclass
class Order:
    order_id: str
    cl_ord_id: str
    participant: str
    symbol: str
    side: Side
    order_type: OrderType
    tif: TimeInForce
    qty: Decimal
    price: Optional[Decimal]
    seq: int
    entered_at: dt.datetime
    leaves_qty: Optional[Decimal] = None
    cum_qty: Decimal = Decimal(0)
    filled_notional: Decimal = Decimal(0)
    status: OrdStatus = OrdStatus.NEW
    orig_cl_ord_id: Optional[str] = None
    account: Optional[str] = None

    def __post_init__(self):
        if self.leaves_qty is None:
            self.leaves_qty = self.qty

    @property
    def avg_px(self) -> Decimal:
        if not self.cum_qty:
            return Decimal(0)
        return (self.filled_notional / self.cum_qty).quantize(Decimal("1E-10")).normalize()

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_STATUSES


# --------------------------------------------------------------------------- events (outbound)

@dataclass
class ExecutionReport:
    exec_id: str
    order_id: Optional[str]
    cl_ord_id: Any
    orig_cl_ord_id: Optional[str]
    participant: Any
    symbol: Any
    side: Any
    order_type: Any
    tif: Any
    exec_type: ExecType
    ord_status: OrdStatus
    qty: Any
    price: Any
    last_qty: Decimal = Decimal(0)
    last_px: Optional[Decimal] = None
    cum_qty: Decimal = Decimal(0)
    leaves_qty: Decimal = Decimal(0)
    avg_px: Decimal = Decimal(0)
    reject_reason: Optional[RejectReason] = None
    text: str = ""
    trade_id: Optional[str] = None
    aggressor: Optional[bool] = None
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "ExecutionReport"


@dataclass
class CancelReject:
    cl_ord_id: Any
    orig_cl_ord_id: Any
    participant: Any
    symbol: Any
    order_id: Optional[str]
    ord_status: OrdStatus
    response_to: str              # "CANCEL" | "REPLACE"
    reject_reason: RejectReason
    text: str = ""
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "CancelReject"


@dataclass
class Trade:
    trade_id: str
    symbol: str
    price: Decimal
    qty: Decimal
    buy_order_id: str
    sell_order_id: str
    buy_participant: str
    sell_participant: str
    aggressor_side: Optional[Side]
    match_type: str               # "CONTINUOUS" | "AUCTION"
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "Trade"


@dataclass
class AuctionResult:
    symbol: str
    price: Optional[Decimal]
    volume: Decimal
    imbalance: Decimal
    reason: str = ""
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "AuctionResult"


@dataclass
class PhaseChange:
    scope: str
    scope_type: str               # "SCHEDULE" | "INSTRUMENT"
    old_phase: Phase
    new_phase: Phase
    reason: str = ""
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "PhaseChange"


@dataclass
class PhaseChangeRejected:
    scope: str
    current_phase: Optional[Phase]
    requested_phase: Any
    reject_reason: RejectReason
    text: str = ""
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "PhaseChangeRejected"


@dataclass
class Alert:
    kind: str
    severity: str
    message: str
    symbol: Optional[str] = None
    participant: Optional[str] = None
    data: dict = field(default_factory=dict)
    timestamp: Optional[dt.datetime] = None
    TYPE: ClassVar[str] = "Alert"


Event = Union[ExecutionReport, CancelReject, Trade, AuctionResult, PhaseChange, PhaseChangeRejected, Alert]
