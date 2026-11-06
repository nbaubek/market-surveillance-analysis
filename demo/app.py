"""Market Surveillance — zero-AWS demo dashboard.

FastHTML + MonsterUI chrome, ECharts rendering, DuckDB over the Parquet
snapshot in ./data (exported by src/export/gold_snapshot.py). No AWS
credentials, no network calls beyond CDN assets.

Design: the chart system follows the project dataviz method —
entity-fixed categorical colors (never re-assigned by filter state),
diverging blue/red around a neutral zero for polarity data (order flow
imbalance, book imbalance, premium), 2px lines, capped rounded bars,
hairline solid grids, no dual axes, one tooltip listing every series,
and a table twin for every chart family. Status colors are reserved for
alerts and never used as series colors.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from fasthtml.common import (
    A,
    Body,
    Details,
    Div,
    Form,
    H1,
    H3,
    Head,
    Html,
    Main,
    Meta,
    Nav,
    NotStr,
    Option,
    P,
    Select,
    Span,
    Summary,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Title,
    Tr,
    fast_app,
    serve,
)
from monsterui.all import Theme

# --------------------------------------------------------------------------
# Palette (dark reference instance) — see the dataviz method docs.
SURFACE = "#1a1a19"
PAGE = "#0d0d0d"
INK = "#f0efec"
INK2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"
BLUE = "#3987e5"  # slot 1 — price, buys, bids, positive pole
ORANGE = "#d95926"  # slot 2 — VWAP, secondary series
AQUA = "#199e70"  # slot 3
YELLOW = "#c98500"  # slot 4 — spread (magnitude)
RED = "#e66767"  # slot 8 — sells, asks, cancels, negative pole
STATUS_WARN = "#fab219"

CAT_ORDER = [BLUE, ORANGE, AQUA, YELLOW, "#d55181", "#008300", "#9085e9", RED]

# --------------------------------------------------------------------------
DATA = Path(__file__).parent / "data"
con = duckdb.connect()
for _f in sorted(DATA.glob("*.parquet")):
    con.execute(f"create view {_f.stem} as select * from read_parquet('{_f}')")


def q(sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        r = {}
        for c, v in zip(cols, row):
            if isinstance(v, Decimal):
                v = float(v)
            elif isinstance(v, (date, datetime)):
                v = v.isoformat()
            r[c] = v
        rows.append(r)
    return rows


def mm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


# --------------------------------------------------------------------------
# ECharts helpers


def base_opt(x: list, series: list, legend: bool, y_fmt: str | None = None) -> dict:
    opt: dict = {
        "backgroundColor": "transparent",
        "animationDuration": 350,
        "grid": {"left": 58, "right": 16, "top": 34 if legend else 22, "bottom": 42},
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "line", "lineStyle": {"color": MUTED, "width": 1}},
            "backgroundColor": "#232322",
            "borderColor": AXIS,
            "borderWidth": 1,
            "textStyle": {"color": INK, "fontSize": 12},
        },
        "xAxis": {
            "type": "category",
            "data": x,
            "axisLine": {"lineStyle": {"color": AXIS, "width": 1}},
            "axisTick": {"show": False},
            "axisLabel": {"color": MUTED, "fontSize": 11},
        },
        "yAxis": {
            "splitLine": {"lineStyle": {"color": GRID, "width": 1}},
            "axisLine": {"show": False},
            "axisLabel": {"color": MUTED, "fontSize": 11},
        },
        "series": series,
    }
    if y_fmt:
        opt["yAxis"]["axisLabel"]["formatter"] = y_fmt
    if legend:
        opt["legend"] = {
            "textStyle": {"color": INK2, "fontSize": 12},
            "top": 0,
            "icon": "roundRect",
            "itemWidth": 12,
            "itemHeight": 4,
        }
    return opt


def line(name: str, ys: list, color: str = BLUE, width: int = 2, area: bool = False) -> dict:
    s: dict = {
        "name": name,
        "type": "line",
        "data": ys,
        "symbol": "none",
        "lineStyle": {"color": color, "width": width},
        "itemStyle": {"color": color},
        "connectNulls": True,
    }
    if area:
        s["areaStyle"] = {"color": color, "opacity": 0.1}
    return s


def bar(name: str, ys: list, color: str, *, stack: str | None = None,
        radius: str = "[3,3,0,0]") -> dict:
    return {
        "name": name,
        "type": "bar",
        "data": ys,
        "stack": stack,
        "barMaxWidth": 18,
        "itemStyle": {"color": color, "borderRadius": radius},
        "emphasis": {"itemStyle": {"color": color, "opacity": 0.82}},
    }


_chart_n = 0


def chart(opt: dict, height: int = 300) -> Div:
    global _chart_n
    _chart_n += 1
    cid = f"chart{_chart_n}"
    js = json.dumps(opt, separators=(",", ":"))
    return Div(
        Div(id=cid, style=f"width:100%;height:{height}px;"),
        NotStr(
            f"<script>(function(){{var el=document.getElementById('{cid}');"
            f"var c=echarts.init(el);c.setOption({js});"
            f"new ResizeObserver(function(){{c.resize();}}).observe(el);}})();</script>"
        ),
    )


# --------------------------------------------------------------------------
# Layout components


def shell(title: str, *content, active: str = "") -> Html:
    def navlink(href: str, label: str, key: str):
        cls = "navlink active" if key == active else "navlink"
        return A(label, href=href, cls=cls)

    return Html(
        Head(
            Title(f"{title} — Market Surveillance"),
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            *Theme.blue.headers(),
            NotStr("<script src='https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js'></script>"),
            NotStr(
                "<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
            ),
            NotStr("<style>" + CSS + "</style>"),
        ),
        Body(
            Div(
                Nav(
                    Span("MARKET SURVEILLANCE", cls="brand"),
                    Span(
                        navlink("/", "Overview", "ov"),
                        navlink("/surveillance", "Surveillance", "sv"),
                        navlink("/methodology", "Methodology", "mt"),
                        cls="navlinks",
                    ),
                    cls="topnav",
                ),
                Main(*content, id="main", cls="page"),
                cls="page-wrap",
            ),
            data_theme="dark",
            cls="body",
        ),
        lang="en",
    )


def card(title: str, subtitle: str | None, *body, guide: str | None = None) -> Div:
    guide_el = (
        Details(
            Summary("How to read this", cls="guide-summary"),
            P(guide, cls="guide-text"),
            cls="guide",
        )
        if guide
        else None
    )
    return Div(
        Div(
            H3(title, cls="card-title"),
            (P(subtitle, cls="card-sub") if subtitle else None),
            guide_el,
            cls="card-head",
        ),
        Div(*body, cls="card-body"),
        cls="card",
    )


def tile(label: str, value: str, sub: str | None = None) -> Div:
    return Div(
        P(label, cls="tile-label"),
        P(value, cls="tile-value"),
        (P(sub, cls="tile-sub") if sub else None),
        cls="tile",
    )


def lens_badge(n: int, name: str) -> Span:
    return Span(f"{n} · {name}", cls="lens-badge")


def data_table(headers: list[str], rows: list[list], foot: bool = False) -> Table:
    return Table(
        Thead(Tr(*[Th(h, cls="th") for h in headers])),
        Tbody(*[Tr(*[Td(str(c), cls="td num" if isinstance(c, (int, float)) else "td")
                     for c in r]) for r in rows]),
        cls="dtable",
    )


def filters_row(path: str, sym: str, day: str, syms: list[str], days: list[str]) -> Form:
    def sel(name: str, options: list[str], current: str) -> Select:
        return Select(
            *[Option(o, value=o, selected=(o == current)) for o in options],
            name=name,
            cls="sel",
            hx_get=path,
            hx_target="#main",
            hx_trigger="change",
            hx_include="closest form",
        )

    return Form(
        Div(
            Span("Symbol", cls="flabel"), sel("sym", syms, sym), cls="fgroup"
        ),
        Div(
            Span("Trading day", cls="flabel"),
            sel("day", days, day),
            cls="fgroup",
        ),
        cls="filters",
    )


# --------------------------------------------------------------------------
# Routes

app, rt = fast_app(hdrs=Theme.blue.headers())

META = q("select symbol, strftime(ts_event_day, '%Y-%m-%d') as day "
         "from daily_summary order by symbol, day")
SYMBOLS = sorted({r["symbol"] for r in META})
DAYS = sorted({r["day"] for r in META})


def _pick(req, sym: str | None, day: str | None) -> tuple[str, str, bool]:
    sym = sym if sym in SYMBOLS else SYMBOLS[0]
    day = day if day in DAYS else DAYS[-1]
    return sym, day, bool(req.headers.get("hx-request")) if req else False


def _px(sym: str, day: str, table: str) -> list[dict]:
    return q(
        f"select * from {table} where symbol = ? and strftime(ts_event_day, '%Y-%m-%d') = ? "
        f"order by event_minute",
        [sym, day],
    )


@rt("/")
def home(req, sym: str | None = None, day: str | None = None):
    sym, day, hx = _pick(req, sym, day)
    daily = q(
        "select * from daily_summary where symbol = ? and strftime(ts_event_day,'%Y-%m-%d') = ?",
        [sym, day],
    )[0]
    minutes = _px(sym, day, "minute_metrics")
    book = _px(sym, day, "minute_book")
    prof = q(
        "select price_bucket_floor as b, trade_volume as v from volume_profile "
        "where symbol = ? and strftime(ts_event_day,'%Y-%m-%d') = ? "
        "order by price_bucket_floor",
        [sym, day],
    )
    daysum = q(
        "select * from daily_summary where symbol = ? order by ts_event_day", [sym]
    )

    x = [mm(r["event_minute"]) for r in minutes]
    closes = [r["close"] for r in minutes]
    vwaps = [r["vwap"] for r in minutes]
    buys = [r["taker_buy_volume"] for r in minutes]
    sells = [-r["taker_sell_volume"] for r in minutes]

    med_spread = sorted(b["spread"] for b in book if b["spread"] is not None)
    med_spread = med_spread[len(med_spread) // 2] if med_spread else None

    price_opt = base_opt(x, [
        line("Last print", closes, BLUE),
        line("VWAP", vwaps, ORANGE),
    ], legend=True, y_fmt="{value:.2f}")

    vol_opt = base_opt(x, [
        bar("Buy-initiated", buys, BLUE),
        bar("Sell-initiated", sells, RED, radius="[0,0,3,3]"),
    ], legend=True)

    prof_opt = {
        "backgroundColor": "transparent",
        "grid": {"left": 58, "right": 16, "top": 22, "bottom": 42},
        "tooltip": {"trigger": "axis", "backgroundColor": "#232322",
                    "borderColor": AXIS, "textStyle": {"color": INK}},
        "xAxis": {"type": "value", "splitLine": {"lineStyle": {"color": GRID}},
                  "axisLabel": {"color": MUTED}},
        "yAxis": {"type": "category",
                  "data": [f"{r['b']:.2f}" for r in prof],
                  "axisLine": {"lineStyle": {"color": AXIS}},
                  "axisTick": {"show": False},
                  "axisLabel": {"color": MUTED, "fontSize": 11}},
        "series": [bar("Shares traded", [r["v"] for r in prof], BLUE,
                       radius="[0,3,3,0]")],
    }

    dtable = data_table(
        ["Metric"] + [r["ts_event_day"] for r in daysum],
        [
            ["VWAP", *[f"{r['vwap']:.2f}" for r in daysum]],
            ["Volume (M sh)", *[f"{r['trade_volume']/1e6:.2f}" for r in daysum]],
            ["Notional ($B)", *[f"{r['notional_volume']/1e9:.2f}" for r in daysum]],
            ["Range (bps)", *[f"{r['range_bps']:.0f}" for r in daysum]],
            ["Realized vol (bps)", *[f"{r['realized_vol_bps']:.0f}" for r in daysum]],
            ["Order-flow imbalance", *[f"{r['order_flow_imbalance']:+.3f}" for r in daysum]],
            ["Cancel / trade", *[f"{r['cancel_to_trade_ratio']:.1f}" for r in daysum]],
        ],
    )

    content = [
        filters_row("/", sym, day, SYMBOLS, DAYS),
        P(
            f"Everything below describes {sym} on {day}, reconstructed "
            "order-by-order from Nasdaq's TotalView-ITCH feed. Change the "
            "symbol or day above — every chart and number re-renders.",
            cls="intro",
        ),
        Div(
            tile("Close", f"{daily['close']:.2f}",
                 f"premium to VWAP {daily['vwap_premium']*100:+.2f}%"),
            tile("VWAP / TWAP", f"{daily['vwap']:.2f}",
                 f"twap {daily['twap']:.2f}"),
            tile("Volume", f"{daily['trade_volume']/1e6:.2f}M sh",
                 f"${daily['notional_volume']/1e9:.2f}B notional"),
            tile("Order-flow imbalance", f"{daily['order_flow_imbalance']:+.3f}",
                 "aggressor buy − sell / total"),
            tile("Realized vol", f"{daily['realized_vol_bps']:.0f} bps",
                 f"range {daily['range_bps']:.0f} bps"),
            tile("Median spread", f"{med_spread*100:.0f}¢" if med_spread is not None
                 else "—", "reconstructed touch"),
            cls="kpi-row",
        ),
        Div(
            card("Price and VWAP", "Minute grain, tape prints (crosses included)",
                 chart(price_opt, 320),
                 guide="Two lines: the last traded price each minute, and VWAP — "
                      "the volume-weighted average price, i.e. what the average "
                      "participant actually paid. Price holding far ABOVE VWAP "
                      "means buying pressure arrived late; far BELOW means late "
                      "selling. Worth a look: price detaching from VWAP in the "
                      "final minutes — who was paying up, and why then?"),
            card("Aggressor flow", "Buy-initiated up, sell-initiated down, per minute",
                 chart(vol_opt, 280),
                 guide="Every trade has an aggressor — the side that crossed the "
                      "spread. Blue up-bars are shares bought aggressively that "
                      "minute, red down-bars shares sold. Big one-sided bars that "
                      "barely move price can mean someone is absorbing quietly; "
                      "sustained one-sided bars into the close move the closing "
                      "price (see the third surveillance lens)."),
            cls="grid2",
        ),
        Div(
            card("Volume profile", "Shares traded by 10-cent price bucket",
                 chart(prof_opt, 340),
                 guide="Where volume actually traded, by price. Fat bars are "
                      "'value areas' where the market genuinely agreed on price; "
                      "thin stretches are pockets price moved through without "
                      "commitment. Pushing price through a thin pocket — "
                      "especially near the close — costs little, which is exactly "
                      "why close-markers like thin sessions."),
            card("Days side by side", "Same metrics across all days in the snapshot",
                 dtable,
                 guide="The same day-level metrics for every day in the snapshot, "
                      "so outliers jump out: a range or realized-vol spike that "
                      "the news doesn't explain, a cancel-to-trade ratio far "
                      "above the other days, a close far from VWAP."),
            cls="grid2",
        ),
    ]
    return (Div(*content, cls="fadein") if hx
            else shell(f"{sym} {day}", *content, active="ov"))


@rt("/surveillance")
def surveillance(req, sym: str | None = None, day: str | None = None):
    sym, day, hx = _pick(req, sym, day)
    minutes = _px(sym, day, "minute_metrics")
    book = _px(sym, day, "minute_book")
    spoof = _px(sym, day, "spoof_minute")
    lifetimes = q(
        "select * from lifetimes_day where symbol = ? "
        "and strftime(ts_event_day,'%Y-%m-%d') = ?", [sym, day])
    lifetimes = lifetimes[0] if lifetimes else {}
    daysum = q("select * from daily_summary where symbol = ? order by ts_event_day", [sym])

    x = [mm(r["event_minute"]) for r in minutes]

    # --- spoofing lens
    sx = [mm(r["event_minute"]) for r in spoof]
    spoof_opt = base_opt(sx, [
        bar("Large adds", [r["large_adds"] for r in spoof], BLUE),
        bar("Cancelled < 60s", [r["large_cancelled_60s"] for r in spoof], RED,
            stack="s"),
    ], legend=True)
    # stacked with a hairline gap: overlay transparent spacer
    spoof_opt["series"].append({
        "name": "", "type": "bar", "stack": "s", "data": [0] * len(spoof),
        "barWidth": 2, "itemStyle": {"color": "transparent"}, "tooltip": {"show": False},
    })
    cx_opt = base_opt(x, [
        line("Standalone cancels", [r["standalone_cancels"] for r in minutes], RED),
        line("Trades", [r["trades"] for r in minutes], BLUE),
    ], legend=True)

    lt_total = lifetimes.get("standalone_cancelled_orders") or 0
    w60 = lifetimes.get("within_60s") or 0
    spoof_tiles = Div(
        tile("Cancelled orders", f"{lt_total:,}", "fully standalone-cancelled"),
        tile("Median lifetime", f"{lifetimes.get('p50_lifetime_s', 0):.1f}s",
             f"p90 {lifetimes.get('p90_lifetime_s', 0):.0f}s"),
        tile("Gone within 60s", f"{(100*w60/lt_total if lt_total else 0):.1f}%",
             "of standalone-cancelled orders"),
        cls="kpi-row small",
    )

    # --- layering lens
    imb = [r["book_imbalance"] for r in book]
    imb_opt = base_opt(x, [
        bar("Bid-heavy", [v if v and v > 0 else 0 for v in imb], BLUE),
        bar("Ask-heavy", [v if v and v < 0 else 0 for v in imb], RED, radius="[0,0,3,3]"),
    ], legend=True)
    depth_opt = base_opt(x, [
        line("Bid depth", [r["bid_depth_total"] for r in book], BLUE, area=True),
        line("Ask depth", [r["ask_depth_total"] for r in book], RED, area=True),
    ], legend=True)
    avg_imb = sum(v for v in imb if v is not None) / max(1, len([v for v in imb if v is not None]))
    layer_tiles = Div(
        tile("Avg book imbalance", f"{avg_imb:+.3f}", "top-of-book, [−1, 1]"),
        tile("Live levels", f"{max((r['live_levels'] or 0) for r in book):,}",
             "daily peak"),
        cls="kpi-row small",
    )

    # --- close-marking lens (19:30 UTC onward = last 30 min)
    late = [r for r in minutes if r["event_minute"] >= 1170]
    tot_buy = sum(r["taker_buy_volume"] for r in minutes)
    tot_sell = sum(r["taker_sell_volume"] for r in minutes)
    late_buy = sum(r["taker_buy_volume"] for r in late)
    late_sell = sum(r["taker_sell_volume"] for r in late)
    late_ofi = ((late_buy - late_sell) / (late_buy + late_sell)
                if (late_buy + late_sell) else 0)
    day_ofi = ((tot_buy - tot_sell) / (tot_buy + tot_sell)
               if (tot_buy + tot_sell) else 0)
    late_share = ((late_buy + late_sell) / max(1, tot_buy + tot_sell)) * 100

    ofi_series = [
        (r["taker_buy_volume"] - r["taker_sell_volume"]) /
        max(1, r["taker_buy_volume"] + r["taker_sell_volume"])
        for r in minutes
    ]
    close_opt = base_opt(x, [
        bar("OFI", ofi_series, BLUE),
    ], legend=False)
    close_opt["series"][0]["data"] = [
        v if v >= 0 else 0 for v in ofi_series]
    close_opt["series"].append(
        bar("OFI", [v if v < 0 else 0 for v in ofi_series], RED, radius="[0,0,3,3]"))
    close_opt["series"][1]["name"] = "OFI (sell)"
    close_opt["series"][0]["name"] = "OFI (buy)"
    close_opt["legend"] = {"textStyle": {"color": INK2}, "top": 0}
    close_opt["markArea"] = None
    premium_opt = base_opt(
        [r["ts_event_day"] for r in daysum],
        [
            bar("Premium", [r["vwap_premium"] * 100 for r in daysum], BLUE),
        ],
        legend=False,
    )
    premium_opt["series"].append(bar("Discount",
                                     [0] * len(daysum), RED, radius="[0,0,3,3]"))
    for i, r in enumerate(daysum):
        if r["vwap_premium"] < 0:
            premium_opt["series"][0]["data"][i] = 0
            premium_opt["series"][1]["data"][i] = r["vwap_premium"] * 100

    close_tiles = Div(
        tile("Last-30m OFI", f"{late_ofi:+.3f}", f"full day {day_ofi:+.3f}"),
        tile("Last-30m volume share", f"{late_share:.1f}%", "of day's directional volume"),
        tile("Close vs VWAP", f"{daysum[-1]['vwap_premium']*100:+.2f}%",
             "close / vwap − 1"),
        cls="kpi-row small",
    )

    content = [
        filters_row("/surveillance", sym, day, SYMBOLS, DAYS),
        P(
            "Three screens, one per manipulative strategy the data can "
            "actually support. Each compares behaviour against the symbol's "
            "own patterns — nothing here is an accusation, and intent is "
            "never provable from a feed (see Methodology). Open a card's "
            "'How to read this' for what to look for.",
            cls="intro",
        ),
        Div(
            lens_badge(1, "SPOOFING — flickering large orders"),
            card(
                "Large-order cancel behaviour",
                "Genuine (non-replace) adds above the day's p95 size; red = fully "
                "removed by standalone cancels within 60s of placement",
                spoof_tiles,
                chart(spoof_opt, 260),
                guide="Spoofing places big orders it intends to cancel, to fake "
                      "supply or demand. 'Large' is defined per symbol-day: the "
                      "95th-percentile add size (replaces excluded — a modify is "
                      "not a new order). Blue bars count large orders placed each "
                      "minute; red counts those fully cancelled by a trader "
                      "initiated cancel within 60 seconds. A red fraction that "
                      "sticks near the blue bars, repeating through the day, is "
                      "the flicker signature. The tiles say how long cancelled "
                      "orders actually rested — genuine big interest usually "
                      "waits; sub-5-second lifetimes on one side are the classic "
                      "tell.",
            ),
            card(
                "Cancel pressure vs execution",
                "Standalone (trader-initiated) cancels against tape trades, per minute",
                chart(cx_opt, 260),
                guide="'Standalone' cancels exclude the mechanical ones — the "
                      "cancel inside every trade message and the cancel-leg of "
                      "every order replace — leaving only cancels a human or "
                      "algorithm chose. When the red line towers over the blue "
                      "one for long stretches, the book is churning: liquidity "
                      "being advertised and withdrawn rather than offered. "
                      "Compare against the spoofing panel — the same behaviour "
                      "seen from the cancel side.",
            ),
            cls="stack",
        ),
        Div(
            lens_badge(2, "LAYERING — stacked displayed depth"),
            card(
                "Top-of-book imbalance",
                "(bid depth − ask depth) / their sum at the touch; blue = bid-heavy",
                layer_tiles,
                chart(imb_opt, 260),
                guide="Layering stacks multiple orders across price levels on one "
                      "side to manufacture the look of depth. This is the "
                      "displayed balance at the best prices: blue above zero = "
                      "heavy bids, red below = heavy asks. Extreme, sustained "
                      "readings while price refuses to move are suspicious — "
                      "real one-sided demand usually trades; displayed-only "
                      "demand evaporates.",
            ),
            card(
                "Displayed depth by side",
                "Total live displayed quantity per side, per minute",
                chart(depth_opt, 260),
                guide="The raw quantity behind the imbalance chart, per side. The "
                      "layering signature here is one side repeatedly ballooning "
                      "and then collapsing — the cancel cascade — while the "
                      "other side stays comparatively stable. Both sides "
                      "breathing together is just an active market.",
            ),
            cls="stack",
        ),
        Div(
            lens_badge(3, "MARKING THE CLOSE — late-session pressure"),
            card(
                "Order-flow imbalance through the day",
                "Per-minute aggressor balance; sustained one-sided flow into the "
                "close moves the reference price",
                close_tiles,
                chart(close_opt, 260),
                guide="The closing print feeds benchmarks, index NAVs and "
                      "option strikes — which is what makes it worth marking. "
                      "Each bar is that minute's buy-minus-sell aggression, "
                      "normalized. Watch the final 30 minutes: strong one-sided "
                      "blue that also leaves a large positive close-vs-VWAP "
                      "premium is the pattern; the same shape from index "
                      "rebalancing is the honest explanation a longer baseline "
                      "would separate.",
            ),
            card(
                "Close vs VWAP by day",
                "Where each day's final print landed relative to its "
                "volume-weighted average",
                chart(premium_opt, 240),
                guide="One bar per day: how far the close ended from the day's "
                      "VWAP, in percent. Closes near VWAP are unremarkable — "
                      "that is just where supply met demand. A large positive "
                      "premium, especially on a thin day, means the last prints "
                      "were lifted away from fair value: either real news, or a "
                      "deliberate push.",
            ),
            cls="stack",
        ),
        P(
          "Conduct, not intent: these panels flag behaviour consistent with the "
          "named strategies against each symbol's own patterns. Single venue "
          "(XNAS), displayed size only. See Methodology.",
          cls="caveat",
        ),
    ]
    return (Div(*content, cls="fadein") if hx
            else shell(f"Surveillance — {sym} {day}", *content, active="sv"))


@rt("/methodology")
def methodology():
    content = [
        H1("Methodology", cls="page-title"),
        Div(
            card(
                "Pipeline",
                "Databento XNAS.ITCH MBO → contract-validated streaming ingestion → "
                "Apache Iceberg medallion (bronze / silver / gold) on S3 + Glue, "
                "queried with Athena, transformed with dbt. This demo reads a "
                "Parquet snapshot of the gold layer — zero live AWS dependency.",
            ),
            card(
                "Verified message semantics",
                "Every metric rests on empirically verified feed semantics: "
                "executions are T+F+C message groups where the C record alone "
                "mutates book state; replaces are C+A pairs; a standalone cancel "
                "(no execution, no replace in its group) is the trader-initiated "
                "cancel every surveillance ratio uses. The order book is "
                "reconstructed from price-level intervals and validated to the "
                "touch: 95–99% of prints land exactly on the reconstructed best "
                "bid / ask at the event instant.",
            ),
            card(
                "The three screens",
                "Spoofing: large adds (day p95) fully removed by standalone "
                "cancels within 60s. Layering: top-of-book imbalance with "
                "one-sided depth inflation and its cancel cascade. Marking the "
                "close: last-30-minute order-flow imbalance, volume share, and "
                "close-to-VWAP premium.",
            ),
            card(
                "Honest limits",
                "One venue (Nasdaq), displayed size only (reserve/hidden depth "
                "invisible), no participant identities — so wash trading is out "
                "of scope by design. The data shows conduct consistent with a "
                "strategy, never intent; thresholds become alerts only as "
                "per-symbol, per-time-of-day baselines once a longer window is "
                "ingested.",
            ),
            cls="stack narrow",
        ),
    ]
    return shell("Methodology", *content, active="mt")


CSS = """
* { box-sizing: border-box; }
.body { margin: 0; background: %(page)s; color: %(ink)s;
        font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; }
.page-wrap { max-width: 1180px; margin: 0 auto; padding: 0 20px 60px; }
.topnav { display: flex; align-items: center; justify-content: space-between;
          padding: 18px 0 14px; border-bottom: 1px solid %(grid)s; }
.brand { font-size: 13px; letter-spacing: 0.18em; font-weight: 700;
         color: %(ink)s; }
.navlinks { display: flex; gap: 4px; }
.navlink { color: %(ink2)s; text-decoration: none; font-size: 14px;
           padding: 6px 12px; border-radius: 8px; }
.navlink:hover { color: %(ink)s; background: %(surface)s; }
.navlink.active { color: %(ink)s; background: %(surface)s; }
.page { padding-top: 18px; }
.page-title { font-size: 24px; font-weight: 700; margin: 8px 0 16px; }
.fadein { animation: fade 240ms ease; }
@keyframes fade { from { opacity: 0.35; } to { opacity: 1; } }

.filters { display: flex; gap: 18px; align-items: end; margin: 4px 0 18px; }
.fgroup { display: flex; flex-direction: column; gap: 5px; }
.flabel { font-size: 11px; letter-spacing: 0.08em; color: %(muted)s;
          text-transform: uppercase; }
.sel { background: %(surface)s; color: %(ink)s; border: 1px solid %(axis)s;
       border-radius: 8px; padding: 7px 10px; font-size: 14px; min-width: 140px; }

.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; margin: 6px 0 18px; }
.kpi-row.small { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
.tile { background: %(surface)s; border: 1px solid rgba(255,255,255,0.07);
        border-radius: 12px; padding: 12px 14px; }
.tile-label { margin: 0; font-size: 11px; letter-spacing: 0.06em;
              color: %(muted)s; text-transform: uppercase; }
.tile-value { margin: 4px 0 0; font-size: 24px; font-weight: 650; color: %(ink)s; }
.tile-sub { margin: 3px 0 0; font-size: 12px; color: %(ink2)s; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
.stack { display: flex; flex-direction: column; gap: 14px; margin-bottom: 20px; }
.stack.narrow { max-width: 860px; }
.card { background: %(surface)s; border: 1px solid rgba(255,255,255,0.07);
        border-radius: 14px; overflow: hidden; }
.card-head { padding: 14px 16px 0; }
.card-title { margin: 0; font-size: 15px; font-weight: 650; }
.card-sub { margin: 4px 0 0; font-size: 12.5px; color: %(ink2)s;
            max-width: 60ch; }
.card-body { padding: 10px 12px 12px; }

.lens-badge { display: inline-block; font-size: 11px; font-weight: 700;
              letter-spacing: 0.1em; color: %(warn)s; margin-bottom: -4px; }
.caveat { color: %(muted)s; font-size: 12.5px; max-width: 90ch; }
.intro { color: %(ink2)s; font-size: 14px; max-width: 88ch;
         margin: 2px 0 16px; line-height: 1.55; }
.guide { margin-top: 10px; border-top: 1px solid %(grid)s; padding-top: 8px; }
.guide-summary { cursor: pointer; font-size: 12px; color: %(muted)s;
                 letter-spacing: 0.04em; list-style: none; }
.guide-summary::before { content: "▸ "; }
.guide[open] .guide-summary::before { content: "▾ "; }
.guide-summary:hover { color: %(ink2)s; }
.guide-text { margin: 8px 0 4px; font-size: 13px; color: %(ink2)s;
              line-height: 1.6; max-width: 72ch; }

.dtable { width: 100%%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.th { text-align: right; color: %(muted)s; font-weight: 600; padding: 6px 8px;
      border-bottom: 1px solid %(axis)s; }
.th:first-child { text-align: left; }
.td { padding: 7px 8px; border-bottom: 1px solid %(grid)s; color: %(ink2)s;
      text-align: right; }
.td:first-child { text-align: left; color: %(ink)s; }
.td.num { font-variant-numeric: tabular-nums; }
""" % {
    "page": PAGE, "ink": INK, "ink2": INK2, "muted": MUTED,
    "grid": GRID, "axis": AXIS, "surface": SURFACE, "warn": STATUS_WARN,
}


if __name__ == "__main__":
    serve(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
