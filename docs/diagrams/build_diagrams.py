"""Builds the explanatory SVG diagrams in docs/images/ (no dependencies).

    python docs/diagrams/build_diagrams.py

Every number shown comes from scenarios/collectible_orderbook.json - re-run
`python -m modelex scenario scenarios/collectible_orderbook.json -v` to confirm.
"""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "images"
SANS = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

INK, MUTED, LINE = "#0f172a", "#475569", "#cbd5e1"
C = {  # (fill, stroke, title)
    "order": ("#f1f5f9", "#64748b", "#334155"),
    "valid": ("#fffbeb", "#d97706", "#92400e"),
    "reject": ("#fef2f2", "#dc2626", "#991b1b"),
    "session": ("#eff6ff", "#2563eb", "#1e40af"),
    "match": ("#f5f3ff", "#7c3aed", "#5b21b6"),
    "book": ("#f0fdf4", "#16a34a", "#166534"),
    "monitor": ("#f8fafc", "#334155", "#0f172a"),
    "closed": ("#e2e8f0", "#64748b", "#334155"),
}


class SVG:
    def __init__(self, w, h, title):
        self.w, self.h, self.parts = w, h, []
        self.parts.append(f'<rect width="{w}" height="{h}" fill="#ffffff"/>')
        self.title = title
        self.markers = set()

    def rect(self, x, y, w, h, kind=None, fill=None, stroke=None, rx=10, dash=False, sw=1.5):
        f, s = (C[kind][0], C[kind][1]) if kind else (fill or "none", stroke or LINE)
        d = ' stroke-dasharray="6 5"' if dash else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{f}" stroke="{s}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=13, weight=400, fill=INK, anchor="start", mono=False, italic=False):
        fam = MONO if mono else SANS
        it = ' font-style="italic"' if italic else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" '
                          f'fill="{fill}" text-anchor="{anchor}"{it}>{escape(s)}</text>')

    def lines(self, x, y, rows, size=13, gap=None, **kw):
        gap = gap or round(size * 1.45)
        for i, r in enumerate(rows):
            self.text(x, y + i * gap, r, size=size, **kw)
        return y + len(rows) * gap

    def arrow(self, x1, y1, x2, y2, color="#475569", dash=False, sw=2):
        d = ' stroke-dasharray="6 5"' if dash else ""
        mid = "arr" + color.strip("#")
        if mid not in self.markers:
            self.markers.add(mid)
            self.parts.insert(0, f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                                 f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker></defs>')
        self.parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d} marker-end="url(#{mid})"/>')

    def pill(self, x, y, label, kind="valid", size=10):
        w = len(label) * size * 0.6 + 18
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="22" rx="11" fill="#ffffff" stroke="{C[kind][1]}" stroke-width="1.2"/>')
        self.text(x + w / 2, y + 15, label, size=size, mono=True, anchor="middle", fill=C[kind][2])
        return x + w + 8

    def heading(self, x, y, s, kind, size=15):
        self.text(x, y, s, size=size, weight=700, fill=C[kind][2])

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        body = "\n".join(self.parts)
        (OUT / name).write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.title)}">\n'
            f'<title>{escape(self.title)}</title>\n{body}\n</svg>\n')


def header(s, title, sub):
    s.text(40, 42, title, size=22, weight=700)
    s.text(40, 66, sub, size=13, fill=MUTED)


# =========================================================================== 1. order journey
def order_journey():
    s = SVG(1000, 1120, "How an order moves through ModelEx - collectibles example")
    header(s, "How an order moves through ModelEx",
           "Worked example from the collectibles market (scenarios/collectible_orderbook.json)")

    # 1 order
    s.rect(40, 90, 600, 78, "order")
    s.heading(58, 116, "① An order arrives", "order")
    s.text(58, 138, "INV_A wants to BUY 600 units of FRAC-CAR-1962-GT, paying up to £42.55 each (GTC)", size=13)
    s.text(58, 157, "Sent over the JSON API (or FIX) and translated into one standard internal order", size=12, fill=MUTED)
    s.arrow(340, 168, 340, 190)

    # 2 validation
    s.rect(40, 192, 600, 330, "valid")
    s.heading(58, 218, "② Validation: 16 checks, always in the same order", "valid")
    s.text(58, 238, "The first check that fails rejects the order, so the same mistake always gives the same reason.",
           size=12, fill=MUTED)
    groups = [
        ("Is it well-formed, new, and a real item?", ["REQUIRED_FIELDS", "DUPLICATE_CL_ORD_ID", "UNKNOWN_INSTRUMENT"]),
        ("Can this item trade right now, with this kind of order?", ["INSTRUMENT_STATUS", "SESSION_PHASE", "ORDER_TYPE", "TIME_IN_FORCE"]),
        ("Is there a price, and is the quantity allowed?", ["PRICE_PRESENCE", "QUANTITY_POSITIVE", "LOT_SIZE", "MIN_MAX_QTY", "UNIQUE_ITEM"]),
        ("Is the price sensible?", ["TICK_SIZE", "PRICE_BAND", "MAX_NOTIONAL"]),
        ("Is it an accidental repeat?", ["DUPLICATE_ORDER"]),
    ]
    y = 266
    for label, rules in groups:
        s.text(58, y, label, size=12, weight=600, fill="#78350f")
        x = 58
        for r in rules:
            x = s.pill(x, y + 7, r)
        y += 50
    s.text(58, 512, "Example order passes every check → accepted. INV_A receives a NEW report.", size=12, weight=600,
           fill=C["book"][2])

    # reject box
    s.arrow(640, 300, 658, 300, color=C["reject"][1])
    s.rect(660, 192, 300, 330, "reject")
    s.heading(678, 218, "✗ Rejected: real examples", "reject")
    rej = [("Buy 2 of the one-off art print", "QTY_ABOVE_MAX (max is 1)"),
           ("Art print at £4,502", "INVALID_TICK (prices go up in £5)"),
           ("Art print at £5,700", "PRICE_OUTSIDE_BAND (±25% of £4,500)"),
           ("Rookie card (suspended)", "INSTRUMENT_NOT_TRADABLE"),
           ("A market order", "UNSUPPORTED_ORDER_TYPE (limit only)"),
           ("Same order again within 2 s", "DUPLICATE_ORDER"),
           ("Reusing your own order ID", "DUPLICATE_CL_ORD_ID")]
    y = 246
    for a, b in rej:
        s.text(678, y, a, size=12)
        s.text(690, y + 16, "→ " + b, size=11.5, mono=False, weight=600, fill=C["reject"][2])
        y += 38
    s.text(678, 512, "Sender gets a REJECTED report + reason", size=11.5, fill=MUTED, italic=True)

    # 3 session
    s.arrow(340, 522, 340, 556)
    s.rect(40, 558, 600, 68, "session")
    s.heading(58, 584, "③ Session check: what phase is this item in right now?", "session")
    s.text(58, 606, "Collectibles day: 09:00 pre-open · 10:00 continuous · 20:00 pre-close · 20:30 closed",
           size=12, fill=MUTED)
    s.arrow(185, 626, 185, 662)
    s.arrow(495, 626, 495, 662)

    s.rect(40, 664, 290, 128, "session")
    s.text(58, 688, "Auction (call) phase", size=14, weight=700, fill=C["session"][2])
    s.text(58, 706, "PRE-OPEN · PRE-CLOSE · VOLATILITY AUCTION", size=10.5, fill=MUTED)
    s.lines(58, 728, ["Nothing trades yet: the order waits.",
                      "When the phase ends, all crossing",
                      "orders trade at ONE price.  → diagram 3"], size=12.5)

    s.rect(350, 664, 290, 128, "match")
    s.text(368, 688, "④ Continuous matching", size=14, weight=700, fill=C["match"][2])
    s.text(368, 706, "CONTINUOUS (10:00-20:00 for collectibles)", size=10.5, fill=MUTED)
    s.lines(368, 728, ["Trades straight away with the best",
                       "price on the other side; equal prices",
                       "go first-come-first-served. → diagram 2"], size=12.5)
    s.arrow(185, 792, 185, 828)
    s.arrow(495, 792, 495, 828)

    # 5 book
    s.rect(40, 830, 600, 138, "book")
    s.heading(58, 856, "⑤ Order-book state", "book")
    s.lines(58, 878, ["Anything not traded rests here, sorted",
                      "by price, then arrival time.",
                      "DAY orders are removed at 20:30;",
                      "GTC orders stay for the next day."], size=12.5)
    # mini book
    s.rect(352, 846, 272, 108, fill="#ffffff", stroke=C["book"][1], rx=8, sw=1)
    s.text(488, 866, "FRAC-CAR-1962-GT after the trade", size=11.5, weight=700, anchor="middle", fill=C["book"][2])
    s.parts.append(f'<line x1="488" y1="874" x2="488" y2="946" stroke="{LINE}"/>')
    s.text(420, 892, "BIDS (buy)", size=11, weight=700, anchor="middle", fill=MUTED)
    s.text(556, 892, "ASKS (sell)", size=11, weight=700, anchor="middle", fill=MUTED)
    s.text(420, 918, "(none)", size=12, anchor="middle", fill=MUTED, italic=True)
    s.text(556, 918, "£42.55 × 200", size=12.5, weight=700, anchor="middle")
    s.text(556, 936, "FRAC_SELLER_2", size=10.5, anchor="middle", fill=MUTED)
    s.arrow(340, 968, 340, 1002)

    # 6 responses
    s.rect(40, 1004, 600, 96, "order")
    s.heading(58, 1030, "⑥ Responses go back to both sides", "order")
    s.lines(58, 1052, ["Buyer:  NEW → TRADE 500 @ £42.50 → TRADE 100 @ £42.55 → FILLED (avg £42.5083)",
                       "Sellers: TRADE reports of their own. A public Trade record is published.",
                       "Each message is translated back to JSON or FIX for the participant."], size=12)

    # 7 monitoring
    s.rect(660, 558, 300, 542, "monitor", dash=True)
    s.heading(678, 584, "⑦ Monitoring sees every event", "monitor")
    s.text(678, 610, "Tracks", size=12.5, weight=700)
    s.lines(678, 630, ["•", "", "•"], size=12)
    s.lines(692, 630, ["per item: open, high, low, last,", "VWAP, volume, trades", "per firm: orders vs rejections"], size=12)
    s.text(678, 704, "Raises alerts", size=12.5, weight=700)
    alerts = [("CIRCUIT_BREAKER", "price would jump >15% → item", "pauses in a 5-minute auction"),
              ("HIGH_REJECT_RATE", "a firm has >40% of orders", "rejected (after 25 orders)"),
              ("LARGE_TRADE", "trade worth ≥ £100,000", ""),
              ("INSTRUMENT_HALT", "one item stopped by the", "exchange"),
              ("PHASE_TRANSITION_REJECTED", "an illegal session change", "was refused")]
    y = 726
    for a, b, c in alerts:
        s.text(678, y, a, size=11, mono=True, weight=700, fill=C["reject"][2])
        s.lines(690, y + 17, [b] + ([c] if c else []), size=11.5, gap=15)
        y += 36 + (15 if c else 0)
    s.text(678, 1084, "Watches ② ③ ④ ⑤ ⑥", size=11.5, fill=MUTED, italic=True)
    for yy in (592, 900, 1050):
        s.arrow(642, yy, 658, yy, dash=True, sw=1.5)
    s.save("01-order-journey.svg")


# =========================================================================== 2. continuous matching
def continuous():
    s = SVG(1000, 660, "Continuous matching - price first, then time")
    header(s, "Continuous matching: best price first, then first-come-first-served",
           "Example: fractional units of a 1962 classic GT (FRAC-CAR-1962-GT), during the 10:00-20:00 continuous session")
    xs = [40, 355, 670]
    titles = ["1 · Book before", "2 · The engine walks the sellers", "3 · Book after"]
    for x, t in zip(xs, titles):
        s.rect(x, 96, 290, 330, "match" if "walks" in t else "book")
        s.heading(x + 18, 122, t, "match" if "walks" in t else "book")
    for x0, x1 in ((330, 353), (645, 668)):
        s.arrow(x0, 260, x1, 260)

    def ask_table(x, y, rows):
        s.text(x + 18, y, "SELL orders (asks), cheapest first", size=11.5, weight=700, fill=MUTED)
        y += 10
        for price, qty, who, note, hi in rows:
            s.rect(x + 14, y, 262, 46, fill="#ffffff" if not hi else "#fefce8", stroke=LINE, rx=6, sw=1)
            s.text(x + 26, y + 20, f"£{price}  ×  {qty}", size=14, weight=700)
            s.text(x + 26, y + 37, f"{who} · {note}", size=11, fill=MUTED)
            y += 54
        return y

    y = ask_table(40, 150, [("42.50", "500", "FRAC_SELLER_1", "arrived 1st", True),
                            ("42.55", "300", "FRAC_SELLER_2", "arrived 2nd", False)])
    s.text(58, y + 8, "BUY orders (bids): none", size=11.5, weight=700, fill=MUTED)
    s.rect(54, 312, 262, 96, fill="#ffffff", stroke=C["match"][1], rx=8)
    s.text(70, 336, "Incoming order", size=12, weight=700, fill=C["match"][2])
    s.lines(70, 357, ["INV_A: BUY 600", "pay at most £42.55 each"], size=13.5, weight=600)

    steps = [("a", "Cheapest ask £42.50 ≤ £42.55 ✓", "TRADE 500 @ £42.50", "Seller 1 sold out; 100 still wanted"),
             ("b", "Next ask £42.55 ≤ £42.55 ✓", "TRADE 100 @ £42.55", "Seller 2 has 200 left"),
             ("c", "600 of 600 bought: stop", "Average £42.5083", "Never above the £42.55 limit")]
    y = 146
    for k, a, b, c in steps:
        s.rect(369, y, 262, 82, fill="#ffffff", stroke=LINE, rx=8, sw=1)
        s.text(383, y + 22, f"{k})  {a}", size=12.5)
        s.text(383, y + 46, b, size=15, weight=700, fill=C["match"][2])
        s.text(383, y + 66, c, size=11.5, fill=MUTED)
        y += 92

    y = ask_table(670, 150, [("42.55", "200", "FRAC_SELLER_2", "still waiting", False)])
    s.text(688, y + 8, "BUY orders (bids): none", size=11.5, weight=700, fill=MUTED)
    s.lines(688, 290, ["Each trade happens at the price", "of the order that was already", "waiting, so the buyer got 500",
                       "units cheaper than their limit."], size=12.5)

    cards = [
        ("Why seller 1 went first", "match",
         ["Lower asking price wins (price priority).", "At the same price, the order that",
          "arrived first is filled first (time", "priority). Futures in this model use",
          "pro-rata instead: same-price orders", "share the fill in proportion to size."]),
        ("3 seconds later: leftovers rest", "book",
         ["INV_A sends the same buy for 600 again.", "(Within 2 s it would have been",
          "rejected as DUPLICATE_ORDER.)", "It takes the last 200 @ £42.55; the",
          "other 400 rest in the book as the", "best bid: BUY 400 @ £42.55 (GTC)."]),
        ("No trading with yourself", "reject",
         ["MERCHANT_1 offers 5 cases of", "Bordeaux 2010 at £3,200, then sends",
          "a BUY for 2 at £3,200. That would be", "a trade with itself, so the incoming",
          "buy is cancelled and nothing trades", "(self-trade prevention)."]),
    ]
    for x, (t, k, rows) in zip(xs, cards):
        s.rect(x, 448, 290, 186, k)
        s.heading(x + 18, 474, t, k, size=14)
        s.lines(x + 18, 500, rows, size=12.5, gap=19)
    s.save("02-continuous-matching.svg")


# =========================================================================== 3. auction
def auction():
    s = SVG(1000, 640, "Auction uncross - everyone trades at one price")
    header(s, "Auctions: orders collect first, then everyone trades at one price",
           "Example: the one-off art print ART-PRINT-0001 during the 09:00-10:00 pre-open")

    # ladder
    s.rect(40, 96, 330, 420, "session")
    s.heading(58, 122, "1 · Orders collected (09:00-10:00)", "session")
    s.text(58, 142, "Nothing trades yet, so buyers may bid above", size=12, fill=MUTED)
    s.text(58, 158, "the seller's price (the book is 'crossed').", size=12, fill=MUTED)
    s.text(110, 190, "BUYERS", size=11.5, weight=700, anchor="middle", fill=C["book"][2])
    s.text(205, 190, "PRICE", size=11.5, weight=700, anchor="middle", fill=MUTED)
    s.text(300, 190, "SELLER", size=11.5, weight=700, anchor="middle", fill=C["reject"][2])
    rows = [("4,500", "COLL_B", ""), ("4,450", "COLL_A", ""), ("4,400", "", "OWNER_1"), ("4,380", "COLL_C", "")]
    y = 204
    for p, b, a in rows:
        s.rect(60, y, 290, 52, fill="#ffffff", stroke=LINE, rx=6, sw=1)
        s.text(205, y + 32, f"£{p}", size=15, weight=700, anchor="middle")
        if b:
            s.rect(70, y + 12, 82, 28, fill=C["book"][0], stroke=C["book"][1], rx=14, sw=1)
            s.text(111, y + 31, b, size=11.5, weight=600, anchor="middle", fill=C["book"][2])
        if a:
            s.rect(258, y + 12, 84, 28, fill=C["reject"][0], stroke=C["reject"][1], rx=14, sw=1)
            s.text(300, y + 31, a, size=11.5, weight=600, anchor="middle", fill=C["reject"][2])
        y += 60
    s.lines(58, 460, ["Each order is for exactly 1 item", "(a unique item cannot be split)."], size=12, fill=MUTED)
    s.arrow(372, 300, 394, 300)

    # table
    s.rect(396, 96, 564, 420, "session")
    s.heading(414, 122, "2 · At 10:00 the engine tests every price", "session")
    cols = [(414, "Price"), (488, "Buyers willing"), (600, "Sellers willing"), (720, "Items traded"), (828, "Left over")]
    for x, h in cols:
        s.text(x, 154, h, size=12, weight=700, fill=MUTED)
    s.text(488, 170, "(bid ≥ price)", size=10.5, fill=MUTED)
    s.text(600, 170, "(ask ≤ price)", size=10.5, fill=MUTED)
    data = [("£4,380", "3", "0", "0", "3 buyers", False), ("£4,400", "2", "1", "1", "1 buyer", False),
            ("£4,450", "2", "1", "1", "1 buyer", False), ("£4,500", "1", "1", "1", "0  ✓ chosen", True)]
    y = 182
    for p, b, a, t, l, win in data:
        s.rect(406, y, 544, 34, fill="#dcfce7" if win else "#ffffff", stroke=C["book"][1] if win else LINE, rx=6,
               sw=1.5 if win else 1)
        for (x, _), v in zip(cols, (p, b, a, t, l)):
            s.text(x + 4, y + 22, v, size=13, weight=700 if win else 400, fill=C["book"][2] if win else INK)
        y += 40
    s.text(414, 368, "How the price is chosen (each rule only breaks ties left by the one before):", size=12.5,
           weight=700)
    s.lines(414, 392, ["1. Trade the most items → £4,400, £4,450 and £4,500 tie (1 each)",
                       "2. Leave the fewest unmatched → £4,500 wins (0 left over)",
                       "3. Still tied? Follow the pressure: more buyers → the higher price",
                       "4. Still tied? Pick the price closest to the reference price"], size=12.5, gap=22)
    s.arrow(500, 516, 500, 540)

    s.rect(40, 542, 920, 80, "book")
    s.heading(58, 568, "3 · Result at 10:00", "book")
    s.lines(58, 590, ["COLL_B buys the print from OWNER_1 at £4,500 (one price for the whole auction). COLL_A (£4,450) and COLL_C (£4,380) keep",
                      "waiting as bids in continuous trading. They are DAY orders, so they expire at 20:30. The same method runs the 20:05 closing auction."],
            size=12.5, gap=19)
    s.save("03-auction-uncross.svg")


# =========================================================================== 4. session + monitoring
def session():
    s = SVG(1000, 760, "Trading day, circuit breaker and monitoring")
    header(s, "The trading day, circuit breakers and monitoring",
           "Collectibles schedule (COLLECTIBLE_DAILY in config/market_default.json; every time and rule is configurable)")
    segs = [("CLOSED", "00:00", "closed", "✗", "✗", "none"),
            ("PRE-OPEN", "09:00", "session", "✓", "✓", "auction"),
            ("CONTINUOUS", "10:00", "match", "✓", "✓", "continuous"),
            ("PRE-CLOSE", "20:00", "session", "✓", "✓", "auction"),
            ("POST-CLOSE", "20:05", "order", "✗", "✓", "none"),
            ("CLOSED", "20:30", "closed", "✗", "✗", "none")]
    x0, w = 150, 135
    s.text(40, 128, "Phase", size=12, weight=700, fill=MUTED)
    s.text(40, 166, "New orders", size=12, weight=700, fill=MUTED)
    s.text(40, 192, "Cancels", size=12, weight=700, fill=MUTED)
    s.text(40, 218, "Matching", size=12, weight=700, fill=MUTED)
    for i, (n, t, k, new, cxl, m) in enumerate(segs):
        x = x0 + i * w
        s.rect(x + 2, 104, w - 4, 38, k, rx=6)
        s.text(x + w / 2, 128, n, size=12.5, weight=700, anchor="middle", fill=C[k][2])
        s.text(x + 4, 98, t, size=11.5, fill=MUTED)
        for yy, v in ((166, new), (192, cxl)):
            s.text(x + w / 2, yy, v, size=15, weight=700, anchor="middle",
                   fill=C["book"][2] if v == "✓" else C["reject"][2])
        s.text(x + w / 2, 218, m, size=12, anchor="middle")
    s.text(40, 250, "On entry", size=12, weight=700, fill=MUTED)
    events = {2: ["opening auction", "uncross"], 4: ["closing auction", "uncross"], 5: ["DAY orders expire,", "GTC orders stay"]}
    for i, rows in events.items():
        s.lines(x0 + i * w + w / 2, 250, rows, size=11.5, weight=600, fill=C["session"][2], anchor="middle", gap=16)
    for i in (0, 1, 3):
        s.text(x0 + i * w + w / 2, 250, "-", size=11.5, anchor="middle", fill=MUTED)
    s.text(40, 316, "Illegal moves are refused: e.g. CLOSED → POST-CLOSE is rejected (INVALID_PHASE_TRANSITION) and raises an alert.",
           size=12, fill=MUTED, italic=True)

    # circuit breaker
    s.rect(40, 340, 560, 400, "reject")
    s.heading(58, 366, "Circuit breaker example: Bordeaux 2010 case", "reject")
    s.text(58, 386, "Limit: no trade may move the price more than 15% from the last trade.", size=12, fill=MUTED)
    # price scale
    top, bot, pmax, pmin = 410, 700, 3800, 3150
    py = lambda p: top + (pmax - p) / (pmax - pmin) * (bot - top)
    s.parts.append(f'<line x1="120" y1="{top}" x2="120" y2="{bot}" stroke="{LINE}" stroke-width="2"/>')
    for p in (3200, 3400, 3600, 3800):
        s.text(112, py(p) + 4, f"£{p:,}", size=11, anchor="end", fill=MUTED)
    s.parts.append(f'<line x1="120" y1="{py(3200)}" x2="270" y2="{py(3200)}" stroke="{C["book"][1]}" stroke-width="3"/>')
    s.text(126, py(3200) - 8, "last trade £3,200", size=11.5, weight=600, fill=C["book"][2])
    s.parts.append(f'<line x1="120" y1="{py(3680)}" x2="270" y2="{py(3680)}" stroke="{C["reject"][1]}" stroke-width="2" stroke-dasharray="6 4"/>')
    s.text(126, py(3680) + 16, "+15% limit £3,680", size=11.5, weight=600, fill=C["reject"][2])
    s.parts.append(f'<circle cx="230" cy="{py(3700)}" r="7" fill="{C["reject"][1]}"/>')
    s.text(126, py(3700) - 10, "ask £3,700 (+15.6%)", size=11.5, weight=700, fill=C["reject"][2])
    steps = [("1", "BUYER_Y bids for 4 cases up to £3,750", "2 trade at £3,200 (within the limit)"),
             ("2", "Next seller asks £3,700: over the limit", "Matching stops before that trade"),
             ("3", "Only this wine pauses for 5 minutes", "Other items keep trading; alert raised"),
             ("4", "Auction at +5 min: 2 cases @ £3,700", "Price is now accepted; trading resumes")]
    y = 412
    for n, a, b in steps:
        s.rect(290, y, 296, 62, fill="#ffffff", stroke=LINE, rx=8, sw=1)
        s.text(304, y + 24, f"{n}.  {a}", size=12, weight=700)
        s.text(322, y + 44, b, size=11.5, fill=MUTED)
        if n != "4":
            s.arrow(438, y + 62, 438, y + 76, sw=1.5)
        y += 78

    # monitoring
    s.rect(620, 340, 340, 400, "monitor", dash=True)
    s.heading(638, 366, "Monitoring (surveillance)", "monitor")
    s.text(638, 386, "Listens to every event the exchange emits.", size=12, fill=MUTED)
    rows = [("Price stats per item", "open, high, low, last, VWAP, volume"),
            ("Reject rate per firm", "alert if >40% rejected after 25 orders"),
            ("Large trades", "alert at ≥ £100,000 for collectibles"),
            ("Circuit breakers", "alert + item enters volatility auction"),
            ("Halts", "alert when one item is stopped"),
            ("Session changes", "every phase change logged; illegal ones alerted")]
    y = 418
    for a, b in rows:
        s.text(638, y, a, size=12.5, weight=700)
        s.text(650, y + 18, b, size=11.5, fill=MUTED)
        y += 48
    s.text(638, 718, "All thresholds live in config → \"monitoring\"", size=11.5, fill=MUTED, italic=True)
    s.save("04-session-and-monitoring.svg")


if __name__ == "__main__":
    order_journey()
    continuous()
    auction()
    session()
    print("written to", OUT)
