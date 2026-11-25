# Customising ModelEx for your market

ModelEx keeps market behaviour in data wherever it can. Code is needed only for genuinely new behaviour (a new rule, allocation algorithm or protocol), and each of those plugs in through a one-line registration.

## 1. Golden-source reference data

Each file under `refdata/` holds one asset class. `defaults` are merged into every instrument, and `tick_tables` can be shared by name.

```json
{
  "asset_class": "EQUITY",
  "tick_tables": {"EQ_STD": [{"from_price": "0", "tick": "0.001"}, {"from_price": "10", "tick": "0.01"}]},
  "defaults": {"currency": "GBX", "lot_size": "1", "price_band_pct": "10"},
  "instruments": [
    {"symbol": "VOD.L", "tick_table": "EQ_STD", "reference_price": "72.50", "isin": "GB00BH4HKS39"}
  ]
}
```

Load-time checks reject:
- tick tables that do not start at 0 or are not strictly ascending
- a non-positive tick
- `min_qty`/`max_qty` that are not multiples of the lot size
- a reference price that is off-tick
- duplicate symbols
- unique items with a quantity other than 1

All errors in a file are reported together. Unknown fields (ISIN, grade, custodian, delivery month) are kept in `Instrument.attributes`.

## 2. Adding an asset class (example: FX spot, 24x5)

`config/market_default.json`:

```json
"schedules": {"FX_24X5": {"initial_phase": "CONTINUOUS", "timeline": []}},
"asset_classes": {
  "FX": {
    "schedule": "FX_24X5",
    "matching_algorithm": "PRICE_TIME",
    "order_types": ["LIMIT", "MARKET"],
    "time_in_force": ["GTC", "IOC", "FOK"],
    "self_trade_prevention": "CANCEL_INCOMING",
    "circuit_breaker": {"enabled": true, "pct": "2", "auction_seconds": 30},
    "protocol": "FIX44",
    "validation_rules": ["INSTRUMENT_STATUS", "SESSION_PHASE", "ORDER_TYPE", "TIME_IN_FORCE",
                         "PRICE_PRESENCE", "QUANTITY_POSITIVE", "LOT_SIZE", "MIN_MAX_QTY",
                         "TICK_SIZE", "PRICE_BAND", "MAX_NOTIONAL"]
  }
}
```

Then create `refdata/fx.json` with `"asset_class": "FX"`. Nothing else changes. `tests/test_mbt.py::test_extensibility_custom_rule_algorithm_and_asset_class` builds exactly this in code.

## 3. A custom validation rule

```python
from modelex import validation_rule, Rejection
from modelex.types import RejectReason

@validation_rule("MIN_RESTING_NOTIONAL", applies_to_amend=True)
def min_notional(ctx):
    """Orders must be worth at least 1,000 in quote currency."""
    c, i = ctx.cmd, ctx.instrument
    if c.price is not None and i is not None and c.price * c.qty * i.multiplier < 1000:
        return Rejection(RejectReason.NOTIONAL_LIMIT_EXCEEDED, "below minimum notional")
```

Add `"MIN_RESTING_NOTIONAL"` to an asset class's `validation_rules` list, at the position where it should be checked. `ctx` gives you the command, instrument, asset-class config and exchange (for its phase, books and clock). Rule coverage is counted automatically and shown in the report.

## 4. A custom matching (allocation) algorithm

```python
from modelex import register_algorithm, AllocationAlgorithm

@register_algorithm("PRO_RATA_TOP_ORDER")
class ProRataTopOrder(AllocationAlgorithm):
    def allocate(self, resting, qty, lot):
        first = resting[0]
        top = min(first.leaves_qty, qty)           # first order gets priority fill
        rest = ...                                 # pro-rata the remainder over resting[1:]
        return [(first, top)] + rest
```

Set `"matching_algorithm": "PRO_RATA_TOP_ORDER"`. The engine handles price levels, the resting-price rule, STP, circuit breakers and IOC/FOK around your allocator.

## 5. Sessions and phases

- `phase_rules` decides, per phase, whether new orders, cancels and amends are accepted, the matching mode (`CONTINUOUS` / `CALL` / `NONE`), which TIFs and order types are allowed, whether to uncross on entry, and whether DAY orders expire on entry.
- `transitions` lists the legal phase changes. The model rejects anything else and raises an alert.
- `schedules` give each asset class its own day. With `auto_schedule=True`, `AdvanceTime` fires the timeline. With `False`, you drive phases yourself through `SetPhase`, which is how the simulator works.

## 6. Protocol maps

Override any code in `protocol_maps/fix44.json`, for example a venue that sends `OrdRejReason=99` for band breaches, or `ExecType=4` instead of `C` for IOC remainders:

```json
{"ord_rej_reason": {"PRICE_OUTSIDE_BAND": "99"}, "exec_type": {"EXPIRED": "4"}}
```

Set `"reason_in_text": true` (the default) to prefix tag 58 with the canonical reason. The decoder uses that prefix to recover the precise reason when several reasons share one FIX code.

A new protocol (binary, a venue's REST API) is a subclass of `ProtocolMapper` registered with `@register_mapper("NAME")`. It implements `decode_command`, `encode_command`, `encode_event` and `decode_report`.

## 7. Monitoring

`monitoring.reject_rate_alert_pct` / `reject_rate_min_orders` set the threshold for the per-participant reject-rate alert. `monitoring.large_trade_notional` sets the large-trade threshold per asset class. Subscribe to every event with `ex.subscribe(fn)`.
