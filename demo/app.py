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
from statistics import median
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


def sparkline_svg(vals: list, sel_i: int, w: int = 110, h: int = 26):
    """Tiny trend line across all days; selected day as an accent dot."""
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not pts:
        return NotStr(f"<svg class='spark' width='{w}' height='{h}'></svg>")
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    rng = (hi - lo) or 1.0
    n = len(vals)

    def X(i):
        return 2 + (i * (w - 4) / (n - 1)) if n > 1 else w / 2

    def Y(v):
        return h - 3 - (v - lo) * (h - 6) / rng

    pl = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in pts)
    sel = (f"<circle cx='{X(sel_i):.1f}' cy='{Y(vals[sel_i]):.1f}' r='3.2' "
           f"fill='{BLUE}' stroke='{SURFACE}' stroke-width='1.5'/>"
           if vals[sel_i] is not None else "")
    return NotStr(
        f"<svg class='spark' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
        f"<polyline points='{pl}' fill='none' stroke='#898781' "
        f"stroke-width='1.5' stroke-linejoin='round' stroke-linecap='round'/>"
        f"{sel}</svg>")


def strip_svg(vals: list, sel_i: int, days: list, fmt, w: int = 640, h: int = 32):
    """Distribution dot-strip: every day a muted dot, selected day accent."""
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not pts:
        return Div(cls="strip-empty")
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    rng = (hi - lo) or 1.0
    pad = 46

    def X(v):
        return pad + (v - lo) * (w - 2 * pad) / rng

    med = median(v for _, v in pts)
    dots = "".join(
        f"<circle cx='{X(v):.1f}' cy='{h/2}' r='{5 if i == sel_i else 3.5}' "
        f"fill='{BLUE if i == sel_i else MUTED}' "
        f"stroke='{SURFACE if i == sel_i else 'none'}' stroke-width='2'>"
        f"<title>{days[i]}: {fmt(v)}</title></circle>"
        for i, v in pts
    )
    tick = (f"<line x1='{X(med):.1f}' y1='7' x2='{X(med):.1f}' y2='{h-7}' "
            f"stroke='{AXIS}' stroke-width='1'/>")
    lo_txt, hi_txt = fmt(lo), fmt(hi)
    return NotStr(
        f"<svg class='strip' viewBox='0 0 {w} {h}' preserveAspectRatio='xMidYMid meet'>"
        f"<text x='4' y='{h/2+3.5}' fill='{MUTED}' font-size='10.5' "
        f"text-anchor='start'>{lo_txt}</text>"
        f"<text x='{w-4}' y='{h/2+3.5}' fill='{MUTED}' font-size='10.5' "
        f"text-anchor='end'>{hi_txt}</text>"
        f"{tick}{dots}</svg>")


# --------------------------------------------------------------------------
# ECharts helpers


def base_opt(x: list, series: list, legend: bool,
            zoom: str | None = "inside") -> dict:
    opt: dict = {
        "backgroundColor": "transparent",
        "animation": True,
        "animationDuration": 600,
        "animationEasing": "cubicOut",
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
    if zoom == "slider":
        opt["grid"]["bottom"] = 64
        opt["dataZoom"] = [
            {"type": "slider", "height": 18, "bottom": 10,
             "borderColor": AXIS, "backgroundColor": "transparent",
             "fillerColor": "rgba(57,135,229,0.12)",
             "handleStyle": {"color": INK2}, "textStyle": {"color": MUTED},
             "dataBackground": {"lineStyle": {"color": AXIS},
                                 "areaStyle": {"color": "rgba(255,255,255,0.04)"}}},
            {"type": "inside"},
        ]
    elif zoom == "inside":
        opt["dataZoom"] = [{"type": "inside"}]
    if legend:
        opt["legend"] = {
            "textStyle": {"color": INK2, "fontSize": 12},
            "top": 0,
            "icon": "roundRect",
            "itemWidth": 12,
            "itemHeight": 4,
        }
    return opt


def line(name: str, ys: list, color: str = BLUE, width: int = 2, area: bool = False,
         opacity: float | None = None) -> dict:
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
    if opacity is not None:
        s["lineStyle"]["opacity"] = opacity
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
                "<script>"
                "(function(){var d=null;"
                "function tip(){if(!d){d=document.createElement('div');"
                "d.className='js-tip';document.body.appendChild(d);}return d;}"
                "function show(e){var el=e.target;"
                "if(!el||!el.querySelector||!el.closest('svg')){return;}"
                "var t=el.querySelector(':scope > title');"
                "if(!t){tip().classList.remove('show');return;}"
                "var x=tip();x.textContent=t.textContent;"
                "x.style.left=(e.clientX+14)+'px';"
                "x.style.top=(e.clientY-30)+'px';"
                "x.classList.add('show');}"
                "function hide(){if(d){d.classList.remove('show');}}"
                "function move(e){if(d&&d.classList.contains('show')){"
                "d.style.left=(e.clientX+14)+'px';"
                "d.style.top=(e.clientY-30)+'px';}}"
                "document.addEventListener('pointerover',show);"
                "document.addEventListener('pointermove',move);"
                "document.addEventListener('pointerout',hide);"
                "document.addEventListener('scroll',hide,true);"
                "})();</script>"
            ),
            NotStr(
                "<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
            ),
            NotStr("<style>" + CSS + "</style>"),
        ),
        Body(
            Div(
                Nav(
                    Span(
                        NotStr(
                            "<svg width='20' height='20' viewBox='0 0 24 24' "
                            "fill='none' aria-hidden='true'>"
                            "<path d='M2 14l4-7 4 5 3-10 3 8 4-4 2 2' "
                            "stroke='url(#brandgrad)' stroke-width='2' "
                            "stroke-linecap='round' stroke-linejoin='round'/>"
                            "<defs><linearGradient id='brandgrad' x1='0' y1='0' "
                            "x2='24' y2='0'><stop stop-color='#3987e5'/>"
                            "<stop offset='1' stop-color='#199e70'/></linearGradient>"
                            "</defs></svg>"
                        ),
                        "MARKET SURVEILLANCE",
                        cls="brand",
                    ),
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


def card(title: str, subtitle: str | None, *body, guide: str | None = None,
         guide_open: bool = False, tag: str | None = None) -> Div:
    guide_el = (
        Details(
            Summary("How to read this", cls="guide-summary"),
            P(guide, cls="guide-text"),
            cls="guide",
            **({"open": True} if guide_open else {}),
        )
        if guide
        else None
    )
    return Div(
        Div(
            Div(
                H3(title, cls="card-title"),
                (Span(tag.upper(), cls="card-tag") if tag else None),
                cls="card-title-row",
            ),
            (P(subtitle, cls="card-sub") if subtitle else None),
            guide_el,
            cls="card-head",
        ),
        Div(*body, cls="card-body"),
        cls="card",
    )


def page_hdr(sym: str, day: str, note: str | None = None) -> Div:
    return Div(
        H1(sym, cls="hdr-sym"),
        Div(
            Span(day, cls="hdr-day"),
            (Span(note, cls="hdr-note") if note else None),
            cls="hdr-meta",
        ),
        cls="page-hdr",
    )


def strip_legend(day: str, n_days: int) -> Div:
    def dot(fill, ring=False):
        stroke = f" stroke='{SURFACE}' stroke-width='1.5'" if ring else ""
        return (f"<svg width='11' height='11' viewBox='0 0 11 11'>"
                f"<circle cx='5.5' cy='5.5' r='{4.5 if ring else 3.8}' "
                f"fill='{fill}'{stroke}/></svg>")
    return Div(
        NotStr(
            f"<span class='lg-item'>{dot(MUTED)} every dot is one trading day "
            f"({n_days} in the snapshot)</span>"
            f"<span class='lg-item'>{dot(BLUE, ring=True)} {day} — selected</span>"
            f"<span class='lg-item'><span class='lg-tick'></span> median</span>"
        ),
        cls="strip-legend",
    )


def tile(label: str, value: str, sub: str | None = None,
         alert: bool = False) -> Div:
    return Div(
        P(label, cls="tile-label"),
        P(value, cls="tile-value"),
        (P(sub, cls="tile-sub") if sub else None),
        cls="tile alert" if alert else "tile",
    )


# Known event context for the snapshot's days (demo-scoped, hardcoded):
# both symbols reported earnings after the close on 2019-07-30, so 07-31
# is the event day for each.
EVENTS: dict[tuple[str, str], str] = {
    ("MSFT", "2019-07-31"):
        "Earnings day (reported 07-30 after close) — expect elevated "
        "volatility and one-sided flow; not every spike is manipulation.",
    ("AAPL", "2019-07-31"):
        "Earnings day (reported 07-30 after close) — expect elevated "
        "volatility and one-sided flow; not every spike is manipulation.",
}


def event_chip(sym: str, day: str):
    note = EVENTS.get((sym, day))
    if not note:
        return None
    return Div(Span("EARNINGS DAY", cls="chip-tag"), Span(note, cls="chip-note"),
               cls="chip")


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
    closes = [round(r["close"], 2) if r["close"] is not None else None
              for r in minutes]
    vwaps = [round(r["vwap"], 2) if r["vwap"] is not None else None
             for r in minutes]
    buys = [r["taker_buy_volume"] for r in minutes]
    sells = [-r["taker_sell_volume"] for r in minutes]

    med_spread = sorted(b["spread"] for b in book if b["spread"] is not None)
    med_spread = med_spread[len(med_spread) // 2] if med_spread else None

    # cumulative intraday realized volatility from minute close-to-close log
    # returns (sparse-minute approximation, same as the gold layer)
    volrows = q(
        """
        with mc as (
            select event_minute, close,
                   lag(close) over (order by event_minute) as prev
            from minute_metrics
            where symbol = ? and strftime(ts_event_day, '%Y-%m-%d') = ?
              and close is not null
        )
        select event_minute,
               sqrt(sum(power(ln(close / prev), 2))
                    over (order by event_minute)) * 10000 as cum_rvol
        from mc
        where prev is not null
        """,
        [sym, day],
    )
    cum_vol_opt = base_opt([mm(r["event_minute"]) for r in volrows], [
        line("Cumulative realized vol",
             [round(r["cum_rvol"], 1) for r in volrows], AQUA, area=True),
    ], legend=False)

    price_opt = base_opt(x, [
        line("VWAP", vwaps, ORANGE, width=3, opacity=0.65),
        line("Last print", closes, BLUE, width=2),
    ], legend=True, zoom="slider")

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

    # ---- day panel: metrics x (trend sparkline, selected, prior, median)
    day_labels = [r["ts_event_day"] for r in daysum]
    sel_i = day_labels.index(day) if day in day_labels else len(day_labels) - 1
    prior_i = sel_i - 1 if sel_i > 0 else None

    spreads = {
        r["day"]: r["med"]
        for r in q(
            "select strftime(ts_event_day, '%Y-%m-%d') as day, "
            "approx_quantile(spread, 0.5) as med from minute_book "
            "where symbol = ? and spread is not null group by 1 order by 1",
            [sym],
        )
    }

    def row_vals(get):
        return [get(r) for r in daysum]

    metrics = [
        ("VWAP", lambda r: r["vwap"], lambda v: f"{v:.2f}", "pct"),
        ("Volume (M sh)", lambda r: r["trade_volume"] / 1e6,
         lambda v: f"{v:.2f}", "pct"),
        ("Notional ($B)", lambda r: r["notional_volume"] / 1e9,
         lambda v: f"{v:.2f}", "pct"),
        ("Range (bps)", lambda r: r["range_bps"], lambda v: f"{v:.0f}", "pct"),
        ("Realized vol (bps)", lambda r: r["realized_vol_bps"],
         lambda v: f"{v:.0f}", "pct"),
        ("Order-flow imbalance", lambda r: r["order_flow_imbalance"],
         lambda v: f"{v:+.3f}", "diff"),
        ("Cancel / trade", lambda r: r["cancel_to_trade_ratio"],
         lambda v: f"{v:.1f}", "pct"),
        ("Median spread (cents)", lambda r: spreads.get(r["ts_event_day"]),
         lambda v: f"{v*100:.0f}", "pct"),
        ("Cancel / add", lambda r: r["cancel_to_add_ratio"],
         lambda v: f"{v:.2f}", "pct"),
        ("Large-order share of adds", lambda r: r["large_order_share"],
         lambda v: f"{v*100:.1f}%", "pct"),
        ("Burst ratio (peak / mean minute)", lambda r: r["burst_ratio"],
         lambda v: f"{v:.1f}\u00d7", "pct"),
    ]

    panel_rows = []
    strip_rows = []
    for label, get, fmt, dmode in metrics:
        vals = row_vals(get)
        clean = [v for v in vals if v is not None]
        med = median(clean) if clean else None
        sel_v = vals[sel_i]
        prior_v = vals[prior_i] if prior_i is not None else None
        if sel_v is not None and med not in (None, 0):
            delta = ((sel_v - med) / abs(med)) * 100 if dmode == "pct" else sel_v - med
            delta_s = f"{delta:+.0f}%" if dmode == "pct" else f"{delta:+.3f}"
        else:
            delta_s = "—"
        panel_rows.append(
            Tr(
                Td(label, cls="td"),
                Td(sparkline_svg(vals, sel_i), cls="td sparkcell"),
                Td(fmt(sel_v) if sel_v is not None else "—", cls="td num"),
                Td(fmt(prior_v) if prior_v is not None else "—", cls="td num"),
                Td(fmt(med) if med is not None else "—", cls="td num"),
                Td(delta_s, cls="td num"),
            )
        )
        strip_rows.append(
            Div(
                Span(label, cls="strip-label"),
                strip_svg(vals, sel_i, day_labels, fmt),
                cls="strip-row",
            )
        )

    dtable = Table(
        Thead(Tr(Th("Metric", cls="th"), Th("Trend (all days)", cls="th"),
                 Th(f"Selected ({day})", cls="th"),
                 Th("Prior day", cls="th"), Th("Window median", cls="th"),
                 Th("vs median", cls="th"))),
        Tbody(*panel_rows),
        cls="dtable",
    )
    strips = Div(*strip_rows, cls="strips")

    content = [
        page_hdr(sym, day, "Overview"),
        filters_row("/", sym, day, SYMBOLS, DAYS),
        event_chip(sym, day),
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
        card("Price and VWAP", "Minute grain, tape prints (crosses included)",
             chart(price_opt, 400),
             guide_open=True,
             tag="tape",
                 guide="Two lines: the last traded price each minute, and VWAP — "
                      "the volume-weighted average price, i.e. what the average "
                      "participant actually paid. Price holding far ABOVE VWAP "
                      "means buying pressure arrived late; far BELOW means late "
                      "selling. Worth a look: price detaching from VWAP in the "
                      "final minutes — who was paying up, and why then?"),
        card("Aggressor flow", "Buy-initiated up, sell-initiated down, per minute",
             chart(vol_opt, 320),
             tag="tape",
                 guide="Every trade has an aggressor — the side that crossed the "
                      "spread. Blue up-bars are shares bought aggressively that "
                      "minute, red down-bars shares sold. Big one-sided bars that "
                      "barely move price can mean someone is absorbing quietly; "
                      "sustained one-sided bars into the close move the closing "
                      "price (see the third surveillance lens)."),
        Div(
            card("Intraday volatility",
                 "Cumulative realized volatility, bps — how far price has "
                 "travelled minute-by-minute by this point in the day",
                 chart(cum_vol_opt, 340),
                 tag="derived",
                 guide="Each step adds that minute's close-to-close move "
                      "(squared, then square-rooted cumulatively — the standard "
                      "'realized volatility' measure, in basis points). Steep "
                      "sections are turbulent; flat sections are quiet. A burst "
                      "of steepness in the final minutes on a thin day is worth "
                      "pairing with the close-marking lens."),
            card("Volume profile", "Shares traded by 10-cent price bucket",
                 chart(prof_opt, 340),
                 tag="tape",
                 guide="Where volume actually traded, by price. Fat bars are "
                      "'value areas' where the market genuinely agreed on price; "
                      "thin stretches are pockets price moved through without "
                      "commitment. Pushing price through a thin pocket — "
                      "especially near the close — costs little, which is exactly "
                      "why close-markers like thin sessions."),
            cls="grid2",
        ),
        card("Day panel", "Every metric for the selected day against the "
             "whole snapshot: trend, prior day, and window median",
             dtable,
             tag="derived",
             guide="One row per metric. The sparkline shows every day in the "
                  "snapshot (selected day as the blue dot); the columns give "
                  "the exact numbers for the selected day, the prior day, and "
                  "the median of all days — the last column is how far today "
                  "sits from typical. At two months of data this becomes a "
                  "proper baseline read: 'vs median' is the embryo of the "
                  "z-score alert layer."),
        card("This day vs. all days", "Where the selected day sits in each "
             "metric's distribution. End labels are the lowest and highest "
             "day; every dot in between — including around the median bar — "
             "is simply another trading day.",
             strip_legend(day, len(day_labels)),
             strips,
             tag="derived",
             guide_open=True,
             guide="Every dot is a trading day. The blue dot is the selected "
                  "day. A blue dot sitting alone at the end of a strip is an "
                  "outlier day for that metric — pair it with the Day panel "
                  "numbers and the event chip before concluding anything."),
    ]
    return (content if hx
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
    sel_daily = next((r for r in daysum if r["ts_event_day"] == day), daysum[-1])

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
    w60_share = 100 * w60 / lt_total if lt_total else 0
    spoof_tiles = Div(
        tile("Cancelled orders", f"{lt_total:,}", "fully standalone-cancelled"),
        tile("Median lifetime", f"{lifetimes.get('p50_lifetime_s', 0):.1f}s",
             f"p90 {lifetimes.get('p90_lifetime_s', 0):.0f}s"),
        tile("Gone within 60s", f"{w60_share:.1f}%",
             "of standalone-cancelled orders",
             alert=w60_share > 30),
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
        page_hdr(sym, day, "Surveillance"),
        filters_row("/surveillance", sym, day, SYMBOLS, DAYS),
        event_chip(sym, day),
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
                f"Genuine (non-replace) adds above the day's p95 size "
                f"(large = >{int(sel_daily['large_order_threshold']):,} shares today); "
                "red = fully removed by standalone cancels within 60s of placement",
                spoof_tiles,
                chart(spoof_opt, 260),
                tag="derived",
                guide_open=True,
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
                      "tell — an indicator to investigate, never proof: market "
                      "makers cancel fast for a living.",
            ),
            card(
                "Cancel pressure vs execution",
                "Standalone (trader-initiated) cancels against tape trades, per minute",
                chart(cx_opt, 260),
                tag="derived",
                guide="'Standalone' cancels exclude the mechanical ones — the "
                      "cancel inside every trade message and the cancel-leg of "
                      "every order replace — leaving only cancels a human or "
                      "algorithm chose. When the red line towers over the blue "
                      "one for long stretches, the book is churning: liquidity "
                      "being advertised and withdrawn rather than offered. "
                      "Compare against the spoofing panel — the same behaviour "
                      "seen from the cancel side.",
            ),
            cls="lens-section",
        ),
        Div(
            lens_badge(2, "LAYERING — stacked displayed depth"),
            card(
                "Top-of-book imbalance",
                "(best-bid depth − best-ask depth) / their sum — top of book only; "
                "the chart below shows depth across ALL levels; blue = bid-heavy",
                layer_tiles,
                chart(imb_opt, 260),
                tag="book",
                guide_open=True,
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
                "Total live displayed quantity per side, across all price levels",
                chart(depth_opt, 260),
                tag="book",
                guide="The raw quantity behind the imbalance chart, per side. The "
                      "layering signature here is one side repeatedly ballooning "
                      "and then collapsing — the cancel cascade — while the "
                      "other side stays comparatively stable. Both sides "
                      "breathing together is just an active market.",
            ),
            cls="lens-section",
        ),
        Div(
            lens_badge(3, "MARKING THE CLOSE — late-session pressure"),
            card(
                "Order-flow imbalance through the day",
                "Per-minute aggressor balance; sustained one-sided flow into the "
                "close moves the reference price",
                close_tiles,
                chart(close_opt, 260),
                tag="tape",
                guide_open=True,
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
                tag="derived",
                guide="One bar per day: how far the close ended from the day's "
                      "VWAP, in percent. Closes near VWAP are unremarkable — "
                      "that is just where supply met demand. A large positive "
                      "premium, especially on a thin day, means the last prints "
                      "were lifted away from fair value: either real news, or a "
                      "deliberate push.",
            ),
            cls="lens-section",
        ),
        P(
          "Indicators, not evidence: a high cancel ratio or short order "
          "lifetime is a signal to investigate, not proof of manipulation — "
          "market makers legitimately cancel fast and often. What elevates a "
          "signal is repetition, one-sidedness, and context. Single venue "
          "(XNAS), displayed size only. See Methodology.",
          cls="caveat",
        ),
    ]
    return (content if hx
            else shell(f"Surveillance — {sym} {day}", *content, active="sv"))


METHODOLOGY = [
    ("The pipeline", "data flow athena iceberg s3 glue dbt bronze silver gold parquet duckdb",
     "Databento XNAS.ITCH market-by-order data streams through a contract-validated "
     "Python ingestion into an Apache Iceberg bronze table on S3 (Glue catalog). "
     "dbt transforms build silver (deduplicated, cleaned) and gold (aggregates) "
     "layers on Athena. This demo reads a Parquet snapshot of gold — zero live "
     "AWS dependency."),
    ("What MBO data is", "market by order itch level3 order book nasdaq totalview message",
     "Market-by-order ('L3') data: one record per order-book event — every order "
     "added, executed, modified or cancelled on Nasdaq, with its price, size and "
     "side. Unlike trade data, it shows what was *displayed*, which is what "
     "displayed-liquidity manipulation distorts."),
    ("Message groups — the verified rules", "sequence group t f c execution replace cancel verified semantics",
     "One exchange message can emit several records sharing a sequence number. "
     "Verified empirically: an execution is a T (trade) + F (fill) + C (cancel) "
     "group where only the C changes the book; an order replace is a C (old "
     "order) + A (new order) pair. Knowing this is what separates real cancels "
     "from mechanical bookkeeping."),
    ("Standalone cancels", "trader initiated cancel churn mechanical filter spoofing numerator",
     "A cancel with no execution and no replace in its message group — the only "
     "kind a human or algorithm deliberately chose. All surveillance ratios use "
     "it; raw cancel counts would be inflated ~15% by mechanical legs."),
    ("Book reconstruction", "order book replay spread depth touch best bid ask validation price-level",
     "The displayed book is rebuilt by applying every add and cancel to price "
     "levels, minute by minute. Validated against the tape: 95–99% of prints "
     "land exactly on the reconstructed best bid/ask at the event instant "
     "— and book metrics are distinct from tape metrics: the imbalance uses "
     "top-of-book depth only, while depth totals span all displayed levels "
     "(a deliberately wrong book scores 2%). Spread, depth and imbalance come "
     "from this reconstruction."),
    ("VWAP, TWAP and the close premium", "vwap twap premium fair value benchmark close marking",
     "VWAP is the volume-weighted average price — what the average participant "
     "paid. TWAP is the simple time-average. The close premium (close / VWAP − 1) "
     "measures how far the final print strayed from fair value; large premiums "
     "on thin days are the marking-the-close signature."),
    ("Order-flow imbalance (OFI)", "aggressor imbalance buy sell flow direction polarity",
     "Every trade has an aggressor — the side that crossed the spread. OFI is "
     "(buy volume − sell volume) / total: +1 = all buying, −1 = all selling. "
     "Sustained extremes, especially into the close, move prices."),
    ("Realized volatility", "volatility realized returns bps turbulence risk",
     "Computed from minute-to-minute percentage moves, cumulated over the day "
     "and expressed in basis points. Steep sections of the intraday chart are "
     "turbulent minutes; the day-level figure compares across days."),
    ("Volume profile", "volume by price value area pockets buckets distribution",
     "Shares traded at each price level (10-cent buckets). Fat bars are value "
     "areas where the market agreed; thin stretches are pockets price crossed "
     "without commitment — cheap to push through, which close-markers exploit."),
    ("Screen 1 — Spoofing", "spoofing flickering large orders cancel 60 seconds p95 lifetime",
     "Large orders (above the day's 95th-percentile size) that are fully "
     "cancelled within 60 seconds of placement. Repeating flicker — big size "
     "appearing and vanishing without intent to trade — fakes supply or demand. "
     "Order-lifetime percentiles tell you how long cancelled orders really rested."),
    ("Screen 2 — Layering", "layering stacked depth levels imbalance cascade one-sided",
     "Multiple orders stacked across price levels on one side to manufacture "
     "depth. Signature: top-of-book imbalance pinned near ±1 while price "
     "refuses to move, then the depth collapses in a cancel cascade."),
    ("Screen 3 — Marking the close", "marking the close final minutes reference price nav index",
     "The closing print feeds benchmarks and index NAVs, making it worth "
     "manipulating. Signature: strong one-sided order flow in the last 30 "
     "minutes plus a large close-vs-VWAP premium. Honest alternative: index "
     "rebalancing — baselines over a longer window separate them."),
    ("Honest limits", "limits intent conduct single venue displayed identities wash trading",
     "One venue (Nasdaq), displayed size only, no participant identities — so "
     "wash trading is out of scope by design. The data shows conduct consistent "
     "with a strategy, never intent — every screen here produces "
     "indicators to investigate, not evidence; thresholds become alerts only "
     "as per-symbol "
     "baselines once a longer window is ingested."),
]


@rt("/methodology")
def methodology():
    cards = [
        Div(
            Div(H3(t, cls="card-title"), cls="card-head"),
            Div(P(body, cls="meth-text"), cls="card-body"),
            cls="card meth-card",
            data_search=f"{t} {keys}",
        )
        for t, keys, body in METHODOLOGY
    ]
    content = [
        H1("Methodology", cls="page-title"),
        P(
            "What this dashboard is built on, in plain language. Type to "
            "filter — e.g. 'vwap', 'cancel', 'close', 'book'.",
            cls="intro",
        ),
        Div(
            NotStr(
                "<input id='methsearch' type='search' placeholder='Search terms and topics…' "
                "autocomplete='off' aria-label='Search methodology' />"
                "<span id='methcount' class='search-count'></span>"
            ),
            cls="searchbox",
        ),
        Div(*cards, id="methgrid", cls="meth-list"),
        NotStr(METH_SEARCH_JS),
    ]
    return shell("Methodology", *content, active="mt")


METH_SEARCH_JS = """
<script>
(function () {
  var input = document.getElementById('methsearch');
  if (!input) return;
  var cards = Array.prototype.slice.call(
    document.querySelectorAll('.meth-card'));
  var count = document.getElementById('methcount');
  function apply() {
    var q = input.value.trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (c) {
      var hay = (c.getAttribute('data-search') + ' ' +
                 c.textContent).toLowerCase();
      var hit = !q || hay.indexOf(q) !== -1;
      c.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    count.textContent = q ? shown + ' of ' + cards.length : '';
  }
  input.addEventListener('input', apply);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { input.value = ''; apply(); }
  });
  apply();
})();
</script>
"""

CSS = """
* { box-sizing: border-box; }
.body { margin: 0; background: %(page)s; color: %(ink)s;
        font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; }
.page-wrap { max-width: 1180px; margin: 0 auto; padding: 0 20px 60px; }
.topnav { display: flex; align-items: center; justify-content: space-between;
          padding: 18px 0 14px; border-bottom: 1px solid %(grid)s; }
.brand { font-size: 13px; letter-spacing: 0.18em; font-weight: 700;
         color: %(ink)s; display: flex; align-items: center; gap: 9px; }
.brand svg { display: block; filter: drop-shadow(0 0 6px rgba(57,135,229,0.45)); }
.navlinks { display: flex; gap: 4px; }
.navlink { color: %(ink2)s; text-decoration: none; font-size: 14px;
           padding: 6px 12px; border-radius: 8px; }
.navlink:hover { color: %(ink)s; background: %(surface)s; }
.navlink.active { color: %(ink)s; background: %(surface)s; }
.page { padding-top: 18px; }
.page-title { font-size: 24px; font-weight: 700; margin: 8px 0 16px; }
main.page > * { animation: fade 240ms ease; }
@keyframes fade { from { opacity: 0.35; } to { opacity: 1; } }

main.page { display: flex; flex-direction: column; gap: 14px; }
.filters { display: flex; gap: 18px; align-items: end; }
.fgroup { display: flex; flex-direction: column; gap: 5px; }
.flabel { font-size: 11px; letter-spacing: 0.08em; color: %(muted)s;
          text-transform: uppercase; }
.sel { background: %(surface)s; color: %(ink)s; border: 1px solid %(axis)s;
       border-radius: 8px; padding: 7px 10px; font-size: 14px; min-width: 140px; }

.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; }
.kpi-row.small { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
.tile { background: %(surface)s; border: 1px solid rgba(255,255,255,0.07);
        border-radius: 12px; padding: 12px 14px; }
.tile-label { margin: 0; font-size: 11px; letter-spacing: 0.06em;
              color: %(muted)s; text-transform: uppercase; }
.tile-value { margin: 4px 0 0; font-size: 24px; font-weight: 650;
              background: linear-gradient(100deg, %(ink)s 55%%, #7fa8e8);
              -webkit-background-clip: text; background-clip: text;
              color: transparent;
              filter: drop-shadow(0 0 10px rgba(57,135,229,0.18)); }
.tile-sub { margin: 3px 0 0; font-size: 12px; color: %(ink2)s; }
.tile.alert { border-color: rgba(250,178,25,0.45); animation: pulse 2.2s ease-in-out infinite; }
.tile.alert .tile-value { background: linear-gradient(100deg, %(ink)s 40%%, %(warn)s);
                          -webkit-background-clip: text; background-clip: text; }
@keyframes pulse {
  0%%, 100%% { box-shadow: 0 0 0 0 rgba(250,178,25,0.0); }
  50%% { box-shadow: 0 0 14px 2px rgba(250,178,25,0.22); }
}

.chip { display: flex; align-items: center; gap: 10px; margin: 0;
        background: rgba(250,178,25,0.07); border: 1px solid rgba(250,178,25,0.35);
        border-radius: 10px; padding: 8px 12px; max-width: 88ch; }
.chip-tag { font-size: 10.5px; font-weight: 700; letter-spacing: 0.12em;
            color: %(warn)s; white-space: nowrap; }
.chip-note { font-size: 12.5px; color: %(ink2)s; line-height: 1.5; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
         align-items: stretch; }
@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
.lens-section { display: flex; flex-direction: column; gap: 10px; }
/* equal-height pills: cards fill their grid cell, body stretches so
   shorter content pads instead of shrinking the card */
.grid2 > .card { height: 100%%; }
.meth-list { display: flex; flex-direction: column; gap: 14px; }
.card { background: %(surface)s; border: 1px solid rgba(255,255,255,0.07);
        border-radius: 14px; overflow: hidden;
        display: flex; flex-direction: column; }
.card-head { padding: 14px 16px 0; }
.card-title-row { display: flex; align-items: center; gap: 10px; }
.card-tag { font-size: 9.5px; font-weight: 700; letter-spacing: 0.12em;
            color: %(muted)s; border: 1px solid %(axis)s; border-radius: 5px;
            padding: 2px 7px; flex: 0 0 auto; }
.card-title { margin: 0; font-size: 15px; font-weight: 650; }
.card-sub { margin: 4px 0 0; font-size: 12.5px; color: %(ink2)s;
            max-width: 60ch; }
.card-body { padding: 10px 12px 12px; flex: 1 1 auto; }


.page-hdr { display: flex; align-items: baseline; gap: 14px; }
.hdr-sym { margin: 0; font-size: 30px; font-weight: 750; letter-spacing: 0.02em;
           background: linear-gradient(100deg, %(ink)s 60%%, #7fa8e8);
           -webkit-background-clip: text; background-clip: text;
           color: transparent; }
.hdr-meta { display: flex; align-items: center; gap: 10px; }
.hdr-day { font-size: 15px; color: %(ink2)s; font-variant-numeric: tabular-nums; }
.hdr-note { font-size: 11px; font-weight: 700; letter-spacing: 0.12em;
            color: %(muted)s; border: 1px solid %(axis)s; border-radius: 6px;
            padding: 2px 8px; }

.sparkcell svg { display: block; }
.strips { display: flex; flex-direction: column; }
.strip { cursor: crosshair; }
.js-tip { position: fixed; display: none; background: #232322;
          border: 1px solid #383835; color: #f0efec; font-size: 12px;
          padding: 4px 9px; border-radius: 6px; pointer-events: none;
          z-index: 50; white-space: nowrap; }
.js-tip.show { display: block; }
.strip-legend { display: flex; align-items: center; gap: 20px;
                font-size: 12px; color: %(ink2)s; padding: 2px 4px 8px;
                flex-wrap: wrap; }
.lg-item { display: inline-flex; align-items: center; gap: 7px; }
.lg-item svg { display: block; }
.lg-tick { display: inline-block; width: 2px; height: 12px;
           background: %(axis)s; }
.strip-row { display: flex; align-items: center; gap: 14px; padding: 7px 4px;
             border-bottom: 1px solid %(grid)s; }
.strip-row:last-child { border-bottom: none; }
.strip-label { flex: 0 0 170px; font-size: 12.5px; color: %(ink2)s; }
.strip-row svg { flex: 1 1 auto; max-height: 34px; }
.strip-empty { flex: 1; height: 30px; }
.meth-text { margin: 0; font-size: 13.5px; color: %(ink2)s; line-height: 1.65; }
.searchbox { display: flex; align-items: center; gap: 12px; margin: 0 0 16px;
             max-width: 860px; }
.searchbox input { flex: 0 1 380px; background: %(surface)s; color: %(ink)s;
                   border: 1px solid %(axis)s; border-radius: 10px;
                   padding: 9px 12px; font-size: 14px; }
.searchbox input:focus { outline: none; border-color: %(blue)s; }
.search-count { font-size: 12.5px; color: %(muted)s; }

.lens-badge { display: inline-flex; align-items: center; gap: 8px;
              font-size: 11px; font-weight: 700;
              letter-spacing: 0.1em; color: %(warn)s; margin-bottom: -4px; }
.lens-badge::before { content: ""; width: 22px; height: 3px; border-radius: 2px;
                      background: linear-gradient(90deg, %(warn)s, rgba(250,178,25,0.15)); }
.caveat { color: %(muted)s; font-size: 12.5px; max-width: 90ch; }
.intro { color: %(ink2)s; font-size: 14px; max-width: 88ch;
         margin: 0; line-height: 1.55; }
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
    "blue": BLUE,
}


if __name__ == "__main__":
    serve(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
