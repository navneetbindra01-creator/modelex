# ModelEx - Model-Based Test Report

Exchange: **ModelEx Multi-Asset Demo Exchange** (XMDL) · Trading date 2026-11-25 · Seed 20261125 · 5,000 generated steps per asset class · Generated 2026-11-25 09:02

**Overall result: PASS**


## Acceptance summary

| Asset class | Scenario steps passed | Invariant violations | Protocol msgs / mismatches | Validation rules exercised | Differential verdicts as expected | Result |
|---|---|---|---|---|---|---|
| EQUITY | 65/65 | 0 | 13,428 / 0 | 13/13 | 6/6 | PASS |
| CRYPTO | 38/38 | 0 | 13,564 / 0 | 13/13 | 6/6 | PASS |
| COMMODITY | 31/31 | 0 | 13,560 / 0 | 13/13 | 6/6 | PASS |
| COLLECTIBLE | 33/33 | 0 | 11,968 / 0 | 15/15 | 6/6 | PASS |

Acceptance criteria: every scenario expectation met; zero invariant violations across scenario and simulation; every message survives a wire-protocol round trip; every reachable validation rule exercised; a clean wire-level SUT agrees with the model on every response, and every non-equivalent mutant is detected.


## EQUITY


### Test order book scenario - Equity order book - full trading day

Validation rules (incl. duplicate ClOrdID and duplicate-content rejection), opening auction uncross, price-time priority, amend priority rules, self-trade prevention (cancel resting), IOC/FOK/market behaviour, circuit breaker -> volatility auction, cancel rejects, closing sequence and DAY/GTC expiry. Instruments: VOD.L, AZN.L (banded tick), 7203.T (lot 100), AAPL.OQ (notional cap), SUSP.L (suspended).

**65/65 steps passed**, 15 trades, 0 invariant violations.

| # | Step | Result |
|---|---|---|
| 1 | Pre-open call period starts | PASS |
| 2 | IOC not allowed in a call phase | PASS |
| 3 | Off-tick price (tick 0.01) | PASS |
| 4 | Banded tick table: AZN.L >= 10000 trades in whole pence | PASS |
| 5 | Round-lot market (lot 100) | PASS |
| 6 | Suspended instrument | PASS |
| 7 | Not in golden source | PASS |
| 8 | Static collar +/-10% of 72.50 => [65.25, 79.75] | PASS |
| 9 | Max order size 500,000 | PASS |
| 10 | Notional cap 5m USD (25,000 x 228.40) | PASS |
| 11 | Market order must not carry a price | PASS |
| 12 | Limit order needs a price | PASS |
| 13 | Zero quantity | PASS |
| 14 | Pre-open book: B1 buy 1000 @ 72.60 | PASS |
| 15 | B2 buy 500 @ 72.50 | PASS |
| 16 | B3 market buy 300 (rests until uncross) | PASS |
| 17 | S1 sell 600 @ 72.40 | PASS |
| 18 | S2 sell 800 @ 72.50 | PASS |
| 19 | S3 sell 400 @ 72.70 | PASS |
| 20 | Duplicate ClOrdID B1 from FIRM_A rejected | PASS |
| 21 | Same order content as B2 within 500ms rejected (fat-finger guard) | PASS |
| 22 | Call book may be crossed | PASS |
| 23 | Open: uncross at 72.50 (max volume 1400, min imbalance) | PASS |
| 24 | check auction VOD.L | PASS |
| 25 | check order B1 | PASS |
| 26 | check order B2 | PASS |
| 27 | check book VOD.L | PASS |
| 28 | S4 joins 72.70 behind S3 | PASS |
| 29 | S5 sell 300 @ 72.80 | PASS |
| 30 | B4 sweeps: S3 then S4 (time priority) then S5 (price) | PASS |
| 31 | B5 buy 100 @ 72.40 | PASS |
| 32 | B6 buy 100 @ 72.40 (behind B5) | PASS |
| 33 | Reduce B5 to 50: keeps priority | PASS |
| 34 | S6 sells 460: B2 400 @72.50, then B5 50, then B6 10 | PASS |
| 35 | B7 buy 100 @ 72.40 (behind B6) | PASS |
| 36 | Increase B6 to 200: loses priority | PASS |
| 37 | S7 sells 150: B7 first now, then B6 | PASS |
| 38 | check order B7 | PASS |
| 39 | Self-trade prevention (CANCEL_RESTING): FIRM_B buy meets own S5 | PASS |
| 40 | check book VOD.L | PASS |
| 41 | IOC: fill 100, expire remaining 200 | PASS |
| 42 | FOK for 500 when 140 available: expires, no trades | PASS |
| 43 | FOK for 100: fills in full | PASS |
| 44 | Market IOC with no offers expires | PASS |
| 45 | Offer 5.7% away from last (72.40) | PASS |
| 46 | Buy would print 76.50 > 5% move: circuit breaker, volatility auction | PASS |
| 47 | check phase VOD.L | PASS |
| 48 | check book VOD.L | PASS |
| 49 | Other equities keep trading continuously | PASS |
| 50 | Auction ends after 120s and uncrosses (buy pressure => highest price 77.00) | PASS |
| 51 | check phase VOD.L | PASS |
| 52 | check order B10 | PASS |
| 53 | Cancel B10 | PASS |
| 54 | Cancel an already-cancelled order | PASS |
| 55 | Cancel an unknown order | PASS |
| 56 | Replace qty below filled qty | PASS |
| 57 | Closing auction call | PASS |
| 58 | GTC bid survives the close | PASS |
| 59 | DAY offer | PASS |
| 60 | Close: uncross (nothing crosses) | PASS |
| 61 | Market closed: DAY orders expire | PASS |
| 62 | check book VOD.L | PASS |
| 63 | Orders rejected while closed | PASS |
| 64 | Illegal transition CLOSED -> POST_CLOSE is rejected | PASS |
| 65 | check phase EQUITY_STD | PASS |


### Generated trading-day simulation

| Metric | Value |
|---|---|
| Commands | 5,014 (NewOrder 3,821, CancelOrder 581, ReplaceOrder 438, AdvanceTime 161, SetPhase 11, HaltInstrument 1, ResumeInstrument 1) |
| Orders accepted / rejected | 2,852 / 969 (25.4% rejected) |
| Trades (continuous / auction) | 1,610 (1,272 / 338) |
| Execution reports | TRADE 3,220, NEW 2,852, REJECTED 969, CANCELED 777, REPLACED 373, EXPIRED 270 |
| Cancel/replace rejects | UNKNOWN_ORDER 38, EXCHANGE_CLOSED 28, AMEND_NOT_ALLOWED 21, INVALID_TICK 21, TOO_LATE_TO_CANCEL 18, PRICE_OUTSIDE_BAND 1 |
| Circuit breakers | 6 |
| Schedule phase path | PRE_OPEN -> CONTINUOUS -> HALTED -> PRE_OPEN -> CONTINUOUS -> PRE_CLOSE -> POST_CLOSE -> CLOSED |
| Illegal transition probes rejected | 3 |
| Alerts | LARGE_TRADE 249, CIRCUIT_BREAKER 6, HIGH_REJECT_RATE 5, PHASE_TRANSITION_REJECTED 3, INSTRUMENT_HALT 1 |
| Protocol round trips (FIX44) | 13,428 messages, 0 mismatches |
| Invariant checks | 20 invariants after every step; 0 violations |
| Runtime | 1.32s |

| Reject reason | Count |
|---|---|
| EXCHANGE_CLOSED | 357 |
| DUPLICATE_CL_ORD_ID | 112 |
| DUPLICATE_ORDER | 79 |
| MISSING_OR_INVALID_FIELD | 69 |
| INVALID_QUANTITY | 67 |
| INSTRUMENT_NOT_TRADABLE | 35 |
| PRICE_REQUIRED | 35 |
| TIF_NOT_ALLOWED_IN_PHASE | 33 |
| INVALID_PRICE | 32 |
| INVALID_TICK | 31 |
| PRICE_OUTSIDE_BAND | 28 |
| QTY_ABOVE_MAX | 23 |
| UNKNOWN_INSTRUMENT | 23 |
| PRICE_NOT_ALLOWED | 23 |
| LOT_SIZE_VIOLATION | 22 |

| Symbol | Open | High | Low | Last | VWAP | Volume | Trades | CB | Final bid / ask |
|---|---|---|---|---|---|---|---|---|---|
| 7203.T | 2526 | 2659.5 | 2385 | 2485.5 | 2527.10958904 | 182500 | 264 | 0 | 2485.5 / 2494.5 |
| AAPL.OQ | 228.88 | 243.38 | 228.68 | 237.72 | 235.1691831 | 1420 | 233 | 1 | 236.82 / 240.65 |
| AZN.L | 11789 | 11896 | 11692 | 11896 | 11791.61838101 | 1643 | 255 | 0 | 11888 / 11965 |
| BARC.L | 283.2 | 295.2 | 274.15 | 282.8 | 283.21882118 | 1756 | 286 | 2 | 281.85 / - |
| MSFT.OQ | 417.8 | 456.72 | 373.68 | 391.94 | 429.77668233 | 2128 | 277 | 3 | 390.08 / 392.12 |
| VOD.L | 72.87 | 74.75 | 70.33 | 70.33 | 72.64272513 | 1699 | 295 | 0 | 70.33 / 74.15 |


### Validation rule coverage

**13/13** reachable rules produced at least one rejection (scenario + simulation).

| Rule | Rejections | Note |
|---|---|---|
| REQUIRED_FIELDS | 69 |  |
| DUPLICATE_CL_ORD_ID | 113 |  |
| UNKNOWN_INSTRUMENT | 24 |  |
| INSTRUMENT_STATUS | 36 |  |
| SESSION_PHASE | 392 |  |
| ORDER_TYPE | 0 | every order type is enabled |
| TIME_IN_FORCE | 0 | every TIF is enabled |
| PRICE_PRESENCE | 92 |  |
| QUANTITY_POSITIVE | 68 |  |
| LOT_SIZE | 23 |  |
| MIN_MAX_QTY | 24 |  |
| TICK_SIZE | 54 |  |
| PRICE_BAND | 30 |  |
| MAX_NOTIONAL | 1 |  |
| DUPLICATE_ORDER | 80 |  |


### Differential testing (simulation trace replayed against SUTs)

| System under test | Expected | Outcome | Responses compared | First divergence |
|---|---|---|---|---|
| Same engine behind FIX44 gateway | AGREE | AGREE ✓ | 8,588 | - |
| Mutant: LIFO_MATCHING | KILLED | KILLED ✓ | 1,209 | step 754: response #2 (C0000567): ord_status model=PARTIALLY_FILLED sut=FILLED, cl_ord_id model=C0000567 sut=A0000573, participant model=FIRM_C sut=FIRM_A, cum_qty model=2600 sut=500, leaves_qty model=2400 sut=0 |
| Mutant: NO_DUPLICATE_CLORDID_CHECK | KILLED | KILLED ✓ | 285 | step 133: response #0 (C0000004): exec_type model=REJECTED sut=NEW, ord_status model=REJECTED sut=NEW, leaves_qty model=0 sut=10, reject_reason model=DUPLICATE_CL_ORD_ID sut=None |
| Mutant: FLAT_TICK_VALIDATION | KILLED | KILLED ✓ | 480 | step 215: response #0 (F0000204): kind model=CXL_REJ sut=EXEC, response_to model=REPLACE sut=None, reject_reason model=INVALID_TICK sut=None |
| Mutant: BAND_EDGE_OFF_BY_ONE | KILLED | KILLED ✓ | 653 | step 120: response #0 (E0000115): exec_type model=NEW sut=REJECTED, ord_status model=NEW sut=REJECTED, leaves_qty model=160 sut=0, reject_reason model=None sut=PRICE_OUTSIDE_BAND |
| Mutant: NO_STP | KILLED | KILLED ✓ | 1,075 | step 753: response #3 (C0000670): exec_type model=CANCELED sut=TRADE, ord_status model=CANCELED sut=PARTIALLY_FILLED, cl_ord_id model=C0000670 sut=C0000714, orig_cl_ord_id model=C0000265 sut=None, side model=SELL sut=BUY, last_qty model=0 sut=1, last_px model=None sut=229, cum_qty model=0 sut=40, leaves_qty model=0 sut=10 |


## CRYPTO


### Test order book scenario - Crypto order book - 24x7 continuous

Fractional quantities (lot 0.0001 BTC), GTC/IOC/FOK only, notional cap, market orders, self-trade prevention (cancel incoming), circuit breaker -> 60s volatility auction, instrument halt/resume and per-participant ClOrdID uniqueness.

**38/38 steps passed**, 8 trades, 0 invariant violations.

| # | Step | Result |
|---|---|---|
| 1 | 24x7 venue starts continuous | PASS |
| 2 | DAY not offered on this venue | PASS |
| 3 | Below lot size 0.0001 | PASS |
| 4 | Off tick 0.01 | PASS |
| 5 | Above max qty 100 | PASS |
| 6 | Notional 80 x 65,000 = 5.2m > 5m cap | PASS |
| 7 | Outside +/-20% band | PASS |
| 8 | ETH lot 0.001 | PASS |
| 9 | Delisted token | PASS |
| 10 | NewOrder S1 | PASS |
| 11 | NewOrder S2 | PASS |
| 12 | NewOrder S3 | PASS |
| 13 | NewOrder B1 | PASS |
| 14 | NewOrder B2 | PASS |
| 15 | check book BTC-USD | PASS |
| 16 | IOC taker lifts 0.6: S1 0.5 then S2 0.1 (FIFO) | PASS |
| 17 | Market sell 1.0 walks the bids | PASS |
| 18 | B4 takes remaining 0.15 of S2 and rests 0.05 | PASS |
| 19 | STP cancel-incoming: MM_1 buy would hit own S3 | PASS |
| 20 | check book BTC-USD | PASS |
| 21 | FOK 2.0 > 1.0 available: expires | PASS |
| 22 | FOK 0.4 fills | PASS |
| 23 | Amend price on a partially-filled order | PASS |
| 24 | Amend qty below filled qty | PASS |
| 25 | Offer 9% above last trade | PASS |
| 26 | Sweep: fills 0.6 @ 65050 then breaches 8% breaker | PASS |
| 27 | check phase BTC-USD | PASS |
| 28 | IOC rejected during auction call | PASS |
| 29 | 60s later the auction uncrosses | PASS |
| 30 | check auction BTC-USD | PASS |
| 31 | check phase BTC-USD | PASS |
| 32 | Regulatory halt of one instrument | PASS |
| 33 | New orders rejected while halted | PASS |
| 34 | ...but cancels are accepted | PASS |
| 35 | ETH unaffected | PASS |
| 36 | ResumeInstrument  | PASS |
| 37 | ClOrdID B1 reused by MM_2: duplicate | PASS |
| 38 | Same ClOrdID from a different participant is fine | PASS |


### Generated trading-day simulation

| Metric | Value |
|---|---|
| Commands | 5,008 (NewOrder 3,731, CancelOrder 620, ReplaceOrder 474, AdvanceTime 176, SetPhase 5, HaltInstrument 1, ResumeInstrument 1) |
| Orders accepted / rejected | 3,138 / 593 (15.9% rejected) |
| Trades (continuous / auction) | 1,721 (1,721 / 0) |
| Execution reports | TRADE 3,442, NEW 3,138, CANCELED 896, REJECTED 593, REPLACED 425, EXPIRED 133 |
| Cancel/replace rejects | UNKNOWN_ORDER 44, INVALID_TICK 30, TOO_LATE_TO_CANCEL 19, EXCHANGE_CLOSED 17, AMEND_NOT_ALLOWED 2 |
| Circuit breakers | 0 |
| Schedule phase path | HALTED -> CONTINUOUS |
| Illegal transition probes rejected | 3 |
| Alerts | PHASE_TRANSITION_REJECTED 3, INSTRUMENT_HALT 1 |
| Protocol round trips (JSON) | 13,564 messages, 0 mismatches |
| Invariant checks | 20 invariants after every step; 0 violations |
| Runtime | 1.48s |

| Reject reason | Count |
|---|---|
| DUPLICATE_CL_ORD_ID | 95 |
| INVALID_QUANTITY | 77 |
| EXCHANGE_CLOSED | 66 |
| MISSING_OR_INVALID_FIELD | 48 |
| PRICE_OUTSIDE_BAND | 37 |
| INVALID_TICK | 34 |
| UNKNOWN_INSTRUMENT | 34 |
| PRICE_REQUIRED | 31 |
| QTY_ABOVE_MAX | 30 |
| LOT_SIZE_VIOLATION | 30 |
| UNSUPPORTED_TIF | 29 |
| INVALID_PRICE | 28 |
| PRICE_NOT_ALLOWED | 28 |
| INSTRUMENT_NOT_TRADABLE | 26 |

| Symbol | Open | High | Low | Last | VWAP | Volume | Trades | CB | Final bid / ask |
|---|---|---|---|---|---|---|---|---|---|
| BTC-USD | 64760.66 | 65861.8 | 64760.66 | 65571.05 | 65423.95419109 | 13.4211 | 476 | 0 | 65844.1 / 65870.35 |
| ETH-USD | 3206.77 | 3230.12 | 3145.15 | 3164.52 | 3162.30505534 | 110.958 | 392 | 0 | 3157.51 / 3164.52 |
| SOL-USD | 149.693 | 150.551 | 148.07 | 149.77 | 149.51785636 | 998.21 | 408 | 0 | 149.018 / 149.77 |
| XRP-USD | 0.5956 | 0.5983 | 0.5861 | 0.5892 | 0.59002047 | 2834 | 445 | 0 | 0.5871 / 0.589 |


### Validation rule coverage

**13/13** reachable rules produced at least one rejection (scenario + simulation).

| Rule | Rejections | Note |
|---|---|---|
| REQUIRED_FIELDS | 48 |  |
| DUPLICATE_CL_ORD_ID | 96 |  |
| UNKNOWN_INSTRUMENT | 34 |  |
| INSTRUMENT_STATUS | 27 |  |
| SESSION_PHASE | 68 |  |
| ORDER_TYPE | 0 | every order type is enabled |
| TIME_IN_FORCE | 30 |  |
| PRICE_PRESENCE | 87 |  |
| QUANTITY_POSITIVE | 77 |  |
| LOT_SIZE | 32 |  |
| MIN_MAX_QTY | 31 |  |
| TICK_SIZE | 65 |  |
| PRICE_BAND | 38 |  |
| MAX_NOTIONAL | 1 |  |


### Differential testing (simulation trace replayed against SUTs)

| System under test | Expected | Outcome | Responses compared | First divergence |
|---|---|---|---|---|
| Same engine behind JSON gateway | AGREE | AGREE ✓ | 8,739 | - |
| Mutant: LIFO_MATCHING | KILLED | KILLED ✓ | 1,177 | step 25: response #2 (D0000014): cl_ord_id model=D0000014 sut=D0000015 |
| Mutant: NO_DUPLICATE_CLORDID_CHECK | KILLED | KILLED ✓ | 494 | step 41: response #0 (F0000003): exec_type model=REJECTED sut=NEW, ord_status model=REJECTED sut=NEW, leaves_qty model=0 sut=50, reject_reason model=DUPLICATE_CL_ORD_ID sut=None |
| Mutant: FLAT_TICK_VALIDATION | AGREE | AGREE ✓ | 8,739 | all crypto instruments use a single tick size |
| Mutant: BAND_EDGE_OFF_BY_ONE | KILLED | KILLED ✓ | 241 | step 44: response #0 (C0000041): exec_type model=NEW sut=REJECTED, ord_status model=NEW sut=REJECTED, leaves_qty model=1000 sut=0, reject_reason model=None sut=PRICE_OUTSIDE_BAND |
| Mutant: NO_STP | KILLED | KILLED ✓ | 91 | step 44: response #1 (C0000041): exec_type model=CANCELED sut=TRADE, ord_status model=CANCELED sut=PARTIALLY_FILLED, last_qty model=0 sut=50, last_px model=None sut=0.5984, cum_qty model=0 sut=50, leaves_qty model=0 sut=950 |


## COMMODITY


### Test order book scenario - Commodity futures order book - pro-rata matching

Futures with contract multipliers, expiry checks, notional cap, opening auction, PRO-RATA allocation with FIFO remainder, self-trade prevention (cancel both), FOK, circuit breaker and DAY expiry. Instrument: CL-JAN27 (1,000 bbl, tick 0.01).

**31/31 steps passed**, 16 trades, 0 invariant violations.

| # | Step | Result |
|---|---|---|
| 1 | SetPhase PRE_OPEN | PASS |
| 2 | Expired contract | PASS |
| 3 | Notional 150 x 2650.0 x 100 oz = 39.75m > 30m | PASS |
| 4 | Max 500 lots | PASS |
| 5 | Suspended contract | PASS |
| 6 | Off tick | PASS |
| 7 | NewOrder B1 | PASS |
| 8 | NewOrder B2 | PASS |
| 9 | NewOrder S1 | PASS |
| 10 | NewOrder S2 | PASS |
| 11 | Open: 71.30 maximises volume (50) | PASS |
| 12 | check auction CL-JAN27 | PASS |
| 13 | check book CL-JAN27 | PASS |
| 14 | Level 71.40: 10 / 30 / 60 lots | PASS |
| 15 | NewOrder S4 | PASS |
| 16 | NewOrder S5 | PASS |
| 17 | Buy 100: 50 @ 71.30, then 50 shared pro-rata 5/15/30 | PASS |
| 18 | Buy 7 vs 5/15/30: floor shares 0/2/4, remainder 1 to oldest (S3) | PASS |
| 19 | STP cancel-both: FIRM_G buy allocated against own S5 | PASS |
| 20 | check book CL-JAN27 | PASS |
| 21 | Market sell 20 hits B2 | PASS |
| 22 | FOK 50 vs 10 available: expires | PASS |
| 23 | FOK 10 fills | PASS |
| 24 | Offer 4.3% above last (71.40 after next fill) | PASS |
| 25 | Sweep 71.40 level then breaker trips at 74.50 | PASS |
| 26 | check phase CL-JAN27 | PASS |
| 27 | Volatility auction uncross after 120s | PASS |
| 28 | check order B6 | PASS |
| 29 | SetPhase POST_CLOSE | PASS |
| 30 | Close expires DAY orders | PASS |
| 31 | check book CL-JAN27 | PASS |


### Generated trading-day simulation

| Metric | Value |
|---|---|
| Commands | 5,013 (NewOrder 3,802, CancelOrder 580, ReplaceOrder 458, AdvanceTime 161, SetPhase 10, HaltInstrument 1, ResumeInstrument 1) |
| Orders accepted / rejected | 2,932 / 870 (22.9% rejected) |
| Trades (continuous / auction) | 1,550 (1,378 / 172) |
| Execution reports | TRADE 3,100, NEW 2,932, CANCELED 1,034, REJECTED 870, REPLACED 380, EXPIRED 260 |
| Cancel/replace rejects | UNKNOWN_ORDER 40, EXCHANGE_CLOSED 35, INVALID_TICK 27, AMEND_NOT_ALLOWED 21, TOO_LATE_TO_CANCEL 21 |
| Circuit breakers | 1 |
| Schedule phase path | PRE_OPEN -> CONTINUOUS -> HALTED -> PRE_OPEN -> CONTINUOUS -> POST_CLOSE -> CLOSED |
| Illegal transition probes rejected | 3 |
| Alerts | LARGE_TRADE 136, HIGH_REJECT_RATE 5, PHASE_TRANSITION_REJECTED 3, CIRCUIT_BREAKER 1, INSTRUMENT_HALT 1 |
| Protocol round trips (FIX44) | 13,560 messages, 0 mismatches |
| Invariant checks | 20 invariants after every step; 0 violations |
| Runtime | 1.39s |

| Reject reason | Count |
|---|---|
| EXCHANGE_CLOSED | 378 |
| DUPLICATE_CL_ORD_ID | 113 |
| INVALID_QUANTITY | 62 |
| MISSING_OR_INVALID_FIELD | 47 |
| INVALID_PRICE | 34 |
| INVALID_TICK | 34 |
| QTY_ABOVE_MAX | 31 |
| UNKNOWN_INSTRUMENT | 30 |
| PRICE_REQUIRED | 26 |
| PRICE_NOT_ALLOWED | 24 |
| TIF_NOT_ALLOWED_IN_PHASE | 22 |
| INSTRUMENT_EXPIRED | 18 |
| LOT_SIZE_VIOLATION | 18 |
| PRICE_OUTSIDE_BAND | 18 |
| INSTRUMENT_NOT_TRADABLE | 15 |

| Symbol | Open | High | Low | Last | VWAP | Volume | Trades | CB | Final bid / ask |
|---|---|---|---|---|---|---|---|---|---|
| AH-3M | 2599 | 2621.5 | 2586 | 2596 | 2603.05359477 | 2295 | 425 | 0 | 2596 / 2608.5 |
| CL-JAN27 | 68.03 | 78.37 | 67.85 | 75.13 | 72.34164271 | 2435 | 390 | 1 | 75.11 / 75.49 |
| GC-FEB27 | 2673.7 | 2768.2 | 2663 | 2677.8 | 2690.47849939 | 2479 | 367 | 0 | 2683.6 / 2699.2 |
| ZW-MAR27 | 551.75 | 554.5 | 547.75 | 549.75 | 551.03231018 | 1857 | 368 | 0 | 549.75 / 553 |


### Validation rule coverage

**13/13** reachable rules produced at least one rejection (scenario + simulation).

| Rule | Rejections | Note |
|---|---|---|
| REQUIRED_FIELDS | 47 |  |
| DUPLICATE_CL_ORD_ID | 113 |  |
| UNKNOWN_INSTRUMENT | 30 |  |
| INSTRUMENT_STATUS | 16 |  |
| INSTRUMENT_EXPIRY | 19 |  |
| SESSION_PHASE | 400 |  |
| ORDER_TYPE | 0 | every order type is enabled |
| TIME_IN_FORCE | 0 | every TIF is enabled |
| PRICE_PRESENCE | 84 |  |
| QUANTITY_POSITIVE | 62 |  |
| LOT_SIZE | 18 |  |
| MIN_MAX_QTY | 32 |  |
| TICK_SIZE | 62 |  |
| PRICE_BAND | 18 |  |
| MAX_NOTIONAL | 1 |  |


### Differential testing (simulation trace replayed against SUTs)

| System under test | Expected | Outcome | Responses compared | First divergence |
|---|---|---|---|---|
| Same engine behind FIX44 gateway | AGREE | AGREE ✓ | 8,720 | - |
| Mutant: LIFO_MATCHING | KILLED | KILLED ✓ | 1,203 | step 828: response #1 (E0000780): ord_status model=PARTIALLY_FILLED sut=FILLED, last_qty model=3 sut=5, cum_qty model=3 sut=5, leaves_qty model=2 sut=0 |
| Mutant: NO_DUPLICATE_CLORDID_CHECK | KILLED | KILLED ✓ | 215 | step 56: response #0 (D0000034): reject_reason model=DUPLICATE_CL_ORD_ID sut=EXCHANGE_CLOSED |
| Mutant: FLAT_TICK_VALIDATION | AGREE | AGREE ✓ | 8,720 | all futures use a single tick size |
| Mutant: BAND_EDGE_OFF_BY_ONE | KILLED | KILLED ✓ | 638 | step 218: response #0 (E0000206): exec_type model=NEW sut=REJECTED, ord_status model=NEW sut=REJECTED, leaves_qty model=10 sut=0, reject_reason model=None sut=PRICE_OUTSIDE_BAND |
| Mutant: NO_STP | KILLED | KILLED ✓ | 1,117 | step 826: response #1 (F0000652): exec_type model=CANCELED sut=TRADE, ord_status model=CANCELED sut=PARTIALLY_FILLED, cl_ord_id model=F0000652 sut=F0000778, side model=BUY sut=SELL, last_qty model=0 sut=3, last_px model=None sut=68.02, cum_qty model=0 sut=3, leaves_qty model=0 sut=47 |


## COLLECTIBLE


### Test order book scenario - Collectibles order book - unique, fungible and fractional items

Limit-only, DAY/GTC market for collectibles. A unique art print sold by auction, fractional units of a classic car traded continuously, cases of wine with self-trade prevention and a circuit breaker, a 2-second duplicate-order guard, and GTC persistence through the close.

**33/33 steps passed**, 7 trades, 0 invariant violations.

| # | Step | Result |
|---|---|---|
| 1 | SetPhase PRE_OPEN | PASS |
| 2 | Unique item: only 1 unit can trade | PASS |
| 3 | Market orders not offered | PASS |
| 4 | Suspended pending authentication | PASS |
| 5 | Tick 5 above 1,000 | PASS |
| 6 | Band +/-25% of 4,500 => max 5,625 | PASS |
| 7 | Owner offers the print at 4,400 | PASS |
| 8 | NewOrder B1 | PASS |
| 9 | NewOrder B2 | PASS |
| 10 | NewOrder B3 | PASS |
| 11 | Auction: 4,500 executes 1 with zero imbalance; highest bidder wins | PASS |
| 12 | check auction ART-PRINT-0001 | PASS |
| 13 | check order B2 | PASS |
| 14 | Fractional units | PASS |
| 15 | NewOrder S3 | PASS |
| 16 | NewOrder B4 | PASS |
| 17 | Identical order within 2s: duplicate guard | PASS |
| 18 | AdvanceTime  | PASS |
| 19 | After the window it is accepted | PASS |
| 20 | IOC not offered | PASS |
| 21 | Asset-class notional cap 100,000 (2,400 x 42.55 = 102,120) | PASS |
| 22 | NewOrder W1 | PASS |
| 23 | STP cancel-incoming | PASS |
| 24 | NewOrder W3 | PASS |
| 25 | Offer 15.6% above last | PASS |
| 26 | Breaker (15%) trips after the 3,200 level is consumed | PASS |
| 27 | Uncross after 300s: tie broken toward reference (last trade 3,200) => 3,700 | PASS |
| 28 | SetPhase PRE_CLOSE | PASS |
| 29 | SetPhase POST_CLOSE | PASS |
| 30 | DAY bids on the print expire; GTC fractional bid survives | PASS |
| 31 | check book ART-PRINT-0001 | PASS |
| 32 | check book FRAC-CAR-1962-GT | PASS |
| 33 | NewOrder X7 | PASS |


### Generated trading-day simulation

| Metric | Value |
|---|---|
| Commands | 5,014 (NewOrder 3,679, CancelOrder 639, ReplaceOrder 510, AdvanceTime 173, SetPhase 11, HaltInstrument 1, ResumeInstrument 1) |
| Orders accepted / rejected | 2,744 / 935 (25.4% rejected) |
| Trades (continuous / auction) | 871 (628 / 243) |
| Execution reports | NEW 2,744, TRADE 1,742, REJECTED 935, CANCELED 701, EXPIRED 452, REPLACED 431 |
| Cancel/replace rejects | EXCHANGE_CLOSED 40, UNKNOWN_ORDER 32, INVALID_TICK 24, AMEND_NOT_ALLOWED 20, TOO_LATE_TO_CANCEL 16, NOTIONAL_LIMIT_EXCEEDED 3 |
| Circuit breakers | 0 |
| Schedule phase path | PRE_OPEN -> CONTINUOUS -> HALTED -> PRE_OPEN -> CONTINUOUS -> PRE_CLOSE -> POST_CLOSE -> CLOSED |
| Illegal transition probes rejected | 3 |
| Alerts | HIGH_REJECT_RATE 6, PHASE_TRANSITION_REJECTED 3, INSTRUMENT_HALT 1 |
| Protocol round trips (JSON) | 11,968 messages, 0 mismatches |
| Invariant checks | 20 invariants after every step; 0 violations |
| Runtime | 1.68s |

| Reject reason | Count |
|---|---|
| EXCHANGE_CLOSED | 334 |
| DUPLICATE_ORDER | 114 |
| DUPLICATE_CL_ORD_ID | 97 |
| UNSUPPORTED_ORDER_TYPE | 55 |
| INSTRUMENT_NOT_TRADABLE | 47 |
| INVALID_QUANTITY | 45 |
| LOT_SIZE_VIOLATION | 34 |
| MISSING_OR_INVALID_FIELD | 31 |
| INVALID_PRICE | 30 |
| PRICE_REQUIRED | 28 |
| UNKNOWN_INSTRUMENT | 27 |
| PRICE_OUTSIDE_BAND | 24 |
| QTY_ABOVE_MAX | 22 |
| UNSUPPORTED_TIF | 20 |
| INVALID_TICK | 15 |
| TIF_NOT_ALLOWED_IN_PHASE | 12 |

| Symbol | Open | High | Low | Last | VWAP | Volume | Trades | CB | Final bid / ask |
|---|---|---|---|---|---|---|---|---|---|
| ART-PRINT-0001 | 4465 | 4480 | 4455 | 4470 | 4466.26262626 | 99 | 99 | 0 | 4465 / 4475 |
| COIN-SOV-1911-MS65 | 656.5 | 661 | 656.5 | 661 | 659.09527559 | 1270 | 215 | 0 | 660 / 661 |
| FRAC-CAR-1962-GT | 47.8 | 48.02 | 47.72 | 47.91 | 47.88176056 | 1846 | 243 | 0 | 47.86 / 47.91 |
| WATCH-CHR-0007 | 28750 | 28750 | 28500 | 28600 | 28606.8627451 | 102 | 102 | 0 | 28600 / 28650 |
| WINE-BDX-2010-CS12 | 2980 | 2995 | 2980 | 2995 | 2988.7755102 | 1078 | 212 | 0 | 2980 / 2995 |


### Validation rule coverage

**15/15** reachable rules produced at least one rejection (scenario + simulation).

| Rule | Rejections | Note |
|---|---|---|
| REQUIRED_FIELDS | 31 |  |
| DUPLICATE_CL_ORD_ID | 97 |  |
| UNKNOWN_INSTRUMENT | 27 |  |
| INSTRUMENT_STATUS | 48 |  |
| SESSION_PHASE | 347 |  |
| ORDER_TYPE | 56 |  |
| TIME_IN_FORCE | 21 |  |
| PRICE_PRESENCE | 58 |  |
| QUANTITY_POSITIVE | 45 |  |
| LOT_SIZE | 34 |  |
| MIN_MAX_QTY | 23 |  |
| UNIQUE_ITEM | 0 | shadowed by MIN_MAX_QTY (unique items have max_qty 1); defence in depth |
| TICK_SIZE | 40 |  |
| PRICE_BAND | 25 |  |
| MAX_NOTIONAL | 4 |  |
| DUPLICATE_ORDER | 115 |  |


### Differential testing (simulation trace replayed against SUTs)

| System under test | Expected | Outcome | Responses compared | First divergence |
|---|---|---|---|---|
| Same engine behind JSON gateway | AGREE | AGREE ✓ | 7,140 | - |
| Mutant: LIFO_MATCHING | KILLED | KILLED ✓ | 974 | step 758: response #2 (E0000216): cl_ord_id model=E0000216 sut=E0000712, orig_cl_ord_id model=E0000195 sut=None |
| Mutant: NO_DUPLICATE_CLORDID_CHECK | KILLED | KILLED ✓ | 139 | step 1: response #0 (D0000001): reject_reason model=DUPLICATE_CL_ORD_ID sut=EXCHANGE_CLOSED |
| Mutant: FLAT_TICK_VALIDATION | KILLED | KILLED ✓ | 890 | step 174: response #0 (D0000161): kind model=CXL_REJ sut=EXEC, response_to model=REPLACE sut=None, reject_reason model=INVALID_TICK sut=None |
| Mutant: BAND_EDGE_OFF_BY_ONE | KILLED | KILLED ✓ | 632 | step 128: response #0 (C0000119): exec_type model=NEW sut=REJECTED, ord_status model=NEW sut=REJECTED, leaves_qty model=5 sut=0, reject_reason model=None sut=PRICE_OUTSIDE_BAND |
| Mutant: NO_STP | KILLED | KILLED ✓ | 1,142 | step 845: response #11 (B0000790): exec_type model=CANCELED sut=TRADE, ord_status model=CANCELED sut=PARTIALLY_FILLED, last_qty model=0 sut=3, last_px model=None sut=658, cum_qty model=35 sut=38, leaves_qty model=0 sut=2 |


## Invariants checked

| Invariant | Property |
|---|---|
| REJECT_HAS_REASON | Every rejection carries a canonical reject reason and no order id |
| STATUS_TRANSITION | Order status follows the lifecycle state machine; nothing after a terminal state |
| DUPLICATE_ACCEPTED | No two accepted orders/requests share (participant, ClOrdID) |
| CUM_QTY | Cumulative quantity only moves on trades, by exactly last_qty |
| QTY_CONSERVATION | cum_qty + leaves_qty == order qty for live orders; never overfilled |
| FOK_ALL_OR_NONE | Fill-or-kill orders end fully filled or not filled at all |
| TRADE_PAIRING | Every trade has exactly one buy and one sell report with identical qty/price |
| LIMIT_PRICE_RESPECTED | No buy fills above its limit, no sell fills below its limit |
| TRADE_ON_TICK_AND_LOT | Trade prices are on tick and quantities are lot multiples |
| AUCTION_SINGLE_PRICE | All trades in one uncross print at the published auction price |
| MATCHING_PHASE | Continuous trades only in CONTINUOUS from order entry; auction trades only at phase events |
| PRICE_TIME_PRIORITY | Passive fills follow strict price-then-time priority (PRICE_TIME instruments) |
| PRICE_PRIORITY | Aggressive orders sweep best price first |
| BOOK_NOT_CROSSED | Best bid < best ask whenever the instrument is trading continuously (a call-phase book may stay crossed through a halt until it is uncrossed) |
| BOOK_ONLY_LIVE | Only live, well-formed orders rest in the book; every live order rests |
| IOC_FOK_NEVER_REST | IOC/FOK orders never rest |
| MARKET_ORDER_RESTING | Market orders rest only during auction call phases |
| DAY_EXPIRED_AT_CLOSE | No DAY order survives into CLOSED |
| UNIQUE_ITEM | Unique collectibles only ever carry quantity 1 |
| PHASE_TRANSITION | Rejected transitions have no effect; applied transitions are legal |

