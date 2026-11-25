"""Reference data (golden source) loading and validation.

A ref-data file is JSON::

    {
      "asset_class": "EQUITY",            # default for every instrument in the file
      "as_of": "2026-11-25",
      "tick_tables": {"EQ_STD": [{"from_price": "0", "tick": "0.001"}, ...]},
      "defaults": {"currency": "GBP", "lot_size": "1", ...},   # merged into every instrument
      "instruments": [ {"symbol": "VOD.L", "tick_table": "EQ_STD", "reference_price": "72.50", ...} ]
    }

Known instrument fields (anything else is kept in ``Instrument.attributes`` so
asset-class specific data - contract months, grades, certificates - survives):

    symbol*, asset_class*, name, currency, status, tick_size | tick_table,
    lot_size, min_qty, max_qty, reference_price, price_band_pct,
    circuit_breaker_pct, max_notional, multiplier | contract_size, expiry, unique
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .types import to_dec


class RefDataError(Exception):
    pass


@dataclass(frozen=True)
class TickBand:
    from_price: Decimal
    tick: Decimal


@dataclass
class Instrument:
    symbol: str
    asset_class: str
    name: str = ""
    currency: str = "USD"
    status: str = "ACTIVE"
    tick_table: list = field(default_factory=lambda: [TickBand(Decimal(0), Decimal("0.01"))])
    lot_size: Decimal = Decimal(1)
    min_qty: Decimal = Decimal(1)
    max_qty: Optional[Decimal] = None
    reference_price: Optional[Decimal] = None
    price_band_pct: Optional[Decimal] = None
    circuit_breaker_pct: Optional[Decimal] = None
    max_notional: Optional[Decimal] = None
    multiplier: Decimal = Decimal(1)
    expiry: Optional[dt.date] = None
    unique: bool = False
    attributes: dict = field(default_factory=dict)

    # ---- tick helpers
    def tick_for(self, price: Decimal) -> Decimal:
        tick = self.tick_table[0].tick
        for band in self.tick_table:
            if price >= band.from_price:
                tick = band.tick
            else:
                break
        return tick

    def is_on_tick(self, price: Decimal) -> bool:
        if price is None or price <= 0:
            return False
        return price % self.tick_for(price) == 0

    def round_to_tick(self, price: Decimal, mode: str = "nearest") -> Decimal:
        rounding = {"nearest": ROUND_HALF_UP, "down": ROUND_FLOOR, "up": ROUND_CEILING}[mode]
        p = price
        for _ in range(3):
            t = self.tick_for(p if p > 0 else self.tick_table[0].tick)
            p = (price / t).to_integral_value(rounding=rounding) * t
            if p <= 0:
                p = t
            if self.is_on_tick(p):
                return p
        return p

    def is_lot_multiple(self, qty: Decimal) -> bool:
        return qty % self.lot_size == 0

    @property
    def tradable(self) -> bool:
        return self.status.upper() == "ACTIVE"


_KNOWN = {"symbol", "asset_class", "name", "currency", "status", "tick_size", "tick_table", "lot_size",
          "min_qty", "max_qty", "reference_price", "price_band_pct", "circuit_breaker_pct", "max_notional",
          "multiplier", "contract_size", "expiry", "unique"}


class RefDataStore:
    """In-memory golden source, keyed by symbol."""

    def __init__(self):
        self.instruments: dict[str, Instrument] = {}
        self.sources: list[dict] = []

    # ---- loading
    @classmethod
    def from_files(cls, paths: Iterable) -> "RefDataStore":
        store = cls()
        for p in paths:
            store.load_file(p)
        return store

    def load_file(self, path) -> list[Instrument]:
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise RefDataError(f"{path}: invalid JSON: {e}") from e
        return self.load_dict(data, source=str(path))

    def load_dict(self, data: dict, source: str = "<dict>") -> list[Instrument]:
        if not isinstance(data, dict) or not isinstance(data.get("instruments"), list):
            raise RefDataError(f"{source}: expected an object with an 'instruments' list")
        ac_default = data.get("asset_class")
        defaults = data.get("defaults", {}) or {}
        tick_tables = data.get("tick_tables", {}) or {}
        errors, built = [], []
        for i, raw in enumerate(data["instruments"]):
            rec = {**defaults, **raw}
            try:
                inst = self._build(rec, ac_default, tick_tables)
            except (RefDataError, ValueError, KeyError, TypeError) as e:
                errors.append(f"{source} instruments[{i}] ({raw.get('symbol')}): {e}")
                continue
            if inst.symbol in self.instruments or any(b.symbol == inst.symbol for b in built):
                errors.append(f"{source} instruments[{i}]: duplicate symbol {inst.symbol}")
                continue
            built.append(inst)
        if errors:
            raise RefDataError("Reference data failed validation:\n  " + "\n  ".join(errors))
        for inst in built:
            self.instruments[inst.symbol] = inst
        self.sources.append({"source": source, "asset_class": ac_default, "as_of": data.get("as_of"),
                             "golden_source": data.get("golden_source"), "count": len(built)})
        return built

    @staticmethod
    def _tick_table(rec, tick_tables) -> list:
        if "tick_table" in rec and rec["tick_table"] is not None:
            tt = rec["tick_table"]
            if isinstance(tt, str):
                if tt not in tick_tables:
                    raise RefDataError(f"unknown tick_table '{tt}'")
                tt = tick_tables[tt]
            bands = [TickBand(to_dec(b["from_price"]), to_dec(b["tick"])) for b in tt]
        elif "tick_size" in rec:
            bands = [TickBand(Decimal(0), to_dec(rec["tick_size"]))]
        else:
            raise RefDataError("tick_size or tick_table required")
        if not bands or bands[0].from_price != 0:
            raise RefDataError("tick table must start at from_price 0")
        for a, b in zip(bands, bands[1:]):
            if b.from_price <= a.from_price:
                raise RefDataError("tick table from_price must be strictly ascending")
        if any(b.tick <= 0 for b in bands):
            raise RefDataError("tick must be > 0")
        return bands

    def _build(self, rec: dict, ac_default, tick_tables) -> Instrument:
        symbol = rec.get("symbol")
        if not symbol or not isinstance(symbol, str):
            raise RefDataError("symbol is required")
        ac = rec.get("asset_class") or ac_default
        if not ac:
            raise RefDataError("asset_class is required")
        unique = bool(rec.get("unique", False))
        inst = Instrument(
            symbol=symbol,
            asset_class=str(ac).upper(),
            name=rec.get("name", ""),
            currency=rec.get("currency", "USD"),
            status=str(rec.get("status", "ACTIVE")).upper(),
            tick_table=self._tick_table(rec, tick_tables),
            lot_size=to_dec(rec.get("lot_size", 1)),
            min_qty=to_dec(rec.get("min_qty", rec.get("lot_size", 1))),
            max_qty=to_dec(rec.get("max_qty")),
            reference_price=to_dec(rec.get("reference_price")),
            price_band_pct=to_dec(rec.get("price_band_pct")),
            circuit_breaker_pct=to_dec(rec.get("circuit_breaker_pct")),
            max_notional=to_dec(rec.get("max_notional")),
            multiplier=to_dec(rec.get("multiplier", rec.get("contract_size", 1))),
            expiry=dt.date.fromisoformat(rec["expiry"]) if rec.get("expiry") else None,
            unique=unique,
            attributes={k: v for k, v in rec.items() if k not in _KNOWN},
        )
        if inst.lot_size <= 0:
            raise RefDataError("lot_size must be > 0")
        if inst.min_qty <= 0 or not inst.is_lot_multiple(inst.min_qty):
            raise RefDataError("min_qty must be > 0 and a multiple of lot_size")
        if inst.max_qty is not None and (inst.max_qty < inst.min_qty or not inst.is_lot_multiple(inst.max_qty)):
            raise RefDataError("max_qty must be >= min_qty and a multiple of lot_size")
        if inst.reference_price is not None and not inst.is_on_tick(inst.reference_price):
            raise RefDataError(f"reference_price {inst.reference_price} is not on tick")
        if inst.multiplier <= 0:
            raise RefDataError("multiplier/contract_size must be > 0")
        if unique and not (inst.lot_size == 1 and inst.min_qty == 1 and inst.max_qty == 1):
            raise RefDataError("unique items require lot_size = min_qty = max_qty = 1")
        return inst

    # ---- access
    def get(self, symbol) -> Optional[Instrument]:
        return self.instruments.get(symbol) if isinstance(symbol, str) else None

    def __contains__(self, symbol) -> bool:
        return symbol in self.instruments

    def __iter__(self) -> Iterator[Instrument]:
        return iter(self.instruments.values())

    def __len__(self) -> int:
        return len(self.instruments)

    def by_asset_class(self, asset_class: str) -> list[Instrument]:
        return [i for i in self.instruments.values() if i.asset_class == asset_class.upper()]

    def asset_classes(self) -> list[str]:
        return sorted({i.asset_class for i in self.instruments.values()})
