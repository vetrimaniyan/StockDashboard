"""Regenerate the operator manual from the metric registry (NFR-5.6).

METRICS.md documents the formulas for a developer. This is the same source of
truth rendered for the person *using* the dashboard: what each tab is for, what
each screen looks for, and how every number is calculated.

Both are generated rather than written so neither can drift from the code.

    python -m alpha500.tools.gen_sop
"""

from __future__ import annotations

import html

from alpha500.config import REPO_ROOT, settings
from alpha500.metrics import registry
from alpha500.screens.presets import PRESETS as _PRESETS

OUT = REPO_ROOT / "docs" / "OPERATOR-MANUAL.html"

METRICS = [
    {
        "name": m.name, "label": m.label, "formula": m.formula,
        "description": m.description, "group": m.group, "unit": m.unit,
    }
    for m in registry.REGISTRY
]
PRESETS = _PRESETS
_S = settings.model_dump()
S = {
    k: _S[k]
    for k in (
        "index_name", "liquidity_floor_inr", "min_history_days", "allowed_series",
        "gap_disqualifier_pct", "rel_volume_threshold", "momentum_lookback",
        "base_window", "support_tolerance_pct", "pullback_min_pct",
        "pullback_max_pct", "reversal_min_score", "reversal_volume_ratio",
        "atr_stop_multiple", "risk_per_trade_pct", "max_position_weight",
        "w_momentum", "w_ret_12m_1m", "w_rs_rating", "w_range_position",
        "w_atr_pct", "w_rel_volume",
    )
    if k in _S
}

GROUP_ORDER = ["Returns", "Relative strength", "Momentum", "Trend", "52-week",
               "Volatility", "Volume", "Oscillators", "Patterns", "Data quality"]

GROUP_BLURB = {
    "Returns": "How much the price has moved over a fixed number of trading sessions.",
    "Relative strength": "The same move, measured against the index rather than against zero.",
    "Momentum": "Trend strength combined with trend consistency — the core ranking.",
    "Trend": "Where price sits relative to its moving averages, and which way they point.",
    "52-week": "Position within the last year's range.",
    "Volatility": "How much the stock moves day to day. Drives stop distance and position size.",
    "Volume": "Whether participation is normal, and whether money is committed.",
    "Oscillators": "Standard indicators, included so familiar setups stay expressible.",
    "Patterns": "Named setups, computed as boolean flags plus their supporting numbers.",
    "Data quality": "Whether a row can be trusted and traded.",
}

def esc(x): return html.escape(str(x))

def rupees(v):
    v = float(v)
    return f"₹{v/1e7:,.0f} crore" if v >= 1e7 else f"₹{v:,.0f}"

# ---- glossary -------------------------------------------------------------
by_group = {}
for m in METRICS:
    by_group.setdefault(m["group"], []).append(m)

glossary = ""
for g in GROUP_ORDER:
    items = by_group.get(g, [])
    if not items:
        continue
    cards = "".join(
        f'<div class="metric" data-search="{esc((m["name"]+" "+m["label"]+" "+m["description"]).lower())}">'
        f'<div class="mhead"><code class="key">{esc(m["name"])}</code>'
        f'<span class="mlabel">{esc(m["label"])}</span></div>'
        f'<div class="formula">{esc(m["formula"])}</div>'
        f'<p class="mdesc">{esc(m["description"])}</p></div>'
        for m in sorted(items, key=lambda x: x["name"])
    )
    glossary += (
        f'<section class="ggroup" data-group="{esc(g)}">'
        f'<h3>{esc(g)} <span class="count">{len(items)}</span></h3>'
        f'<p class="gblurb">{esc(GROUP_BLURB.get(g, ""))}</p>'
        f'<div class="metrics">{cards}</div></section>'
    )

# ---- presets --------------------------------------------------------------
PRESET_PLAIN = {
    "Momentum Leaders": ("Entry", "The twenty strongest trends in the universe, ranked by a "
        "score that rewards consistency as well as speed. This is the tool's primary list."),
    "Trend Template": ("Entry", "Every stock passing all eight structural criteria for a "
        "healthy uptrend. Broader than Momentum Leaders and less time-sensitive."),
    "52-Week High Breakout": ("Entry", "Stocks closing above their previous 52-week high on "
        "heavy volume today. Time-sensitive: the signal is about this session."),
    "Volatility Contraction": ("Entry", "Stocks that have gone quiet inside a tight range after "
        "an advance — the coiling that often precedes a move. Rare by design; zero rows on a "
        "given day is normal."),
    "Pullback to Support": ("Entry", "An established uptrend resting on its 21 EMA or 50 SMA. "
        "A continuation setup: it asks for no evidence the pullback has ended."),
    "Pullback + Reversal": ("Entry", "Pulled back to an identified support level AND showing "
        "active evidence the fall has stopped. A timing signal — different from the screen "
        "above, not a variant of it."),
    "Momentum Breakdown": ("EXIT", "Holdings whose momentum rank has collapsed or that have "
        "lost the 100 SMA. This is an exit list for positions you already hold. It is never a "
        "list of stocks to short."),
}

def render_conditions(node, depth=0):
    if "conditions" not in node:
        return ""
    op = node.get("op", "AND")
    parts = []
    for c in node["conditions"]:
        if "conditions" in c:
            parts.append(f"<li>group ({c.get('op','AND')})<ul>{render_conditions(c, depth+1)}</ul></li>")
        else:
            val = c.get("value")
            val = "true" if val is True else "false" if val is False else val
            parts.append(
                f'<li><code>{esc(c["field"])}</code> '
                f'<span class="op">{esc(c["operator"])}</span> '
                f'<code>{esc(val)}</code></li>'
            )
    return f'<span class="joiner">{esc(op)}</span>' + "".join(parts)

preset_cards = ""
for name, spec in PRESETS.items():
    kind, plain = PRESET_PLAIN.get(name, ("Entry", ""))
    sort = ", ".join(
        f'{s["field"]} {"↓" if s.get("direction","desc")=="desc" else "↑"}'
        for s in spec.get("sort", [])
    ) or "—"
    preset_cards += (
        f'<div class="preset{" exit" if kind=="EXIT" else ""}">'
        f'<div class="phead"><h3>{esc(name)}</h3>'
        f'<span class="badge {"bexit" if kind=="EXIT" else "bentry"}">{kind}</span></div>'
        f'<p class="pplain">{esc(plain)}</p>'
        f'<div class="plogic"><span class="plabel">Passes when</span>'
        f'<ul>{render_conditions(spec.get("filters", {}))}</ul></div>'
        f'<div class="pmeta"><span><span class="plabel">Sorted by</span> {esc(sort)}</span>'
        f'<span><span class="plabel">Shows</span> up to {spec.get("limit","all")} rows</span></div>'
        f"</div>"
    )

weights = (f'{S["w_momentum"]} momentum score · {S["w_ret_12m_1m"]} 12m−1m return · '
           f'{S["w_rs_rating"]} RS rating · {S["w_range_position"]} 52w range position · '
           f'−{S["w_atr_pct"]} ATR% · {S["w_rel_volume"]} relative volume')

HTML = f"""<title>Alpha-500 Operator Manual</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {{
  --bg:#fbfcfe; --surface:#ffffff; --surface-2:#f2f5f9; --line:#dce3ed;
  --ink:#141a22; --ink-2:#4a5769; --ink-3:#6f7f94;
  --accent:#1f5fbf; --accent-soft:#e7effb;
  --up:#1c7a4d; --down:#b3323e; --warn:#8a6410; --warn-soft:#fdf4e1;
  --display:'Spectral',Georgia,serif;
  --ui:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
  --mono:'JetBrains Mono',ui-monospace,Consolas,monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#0d1219; --surface:#141b25; --surface-2:#1b2431; --line:#28323f;
    --ink:#e8eef6; --ink-2:#a9b8ca; --ink-3:#7d8da1;
    --accent:#6aa6ff; --accent-soft:#16263d;
    --up:#3fbe7f; --down:#ef6b76; --warn:#e0a84a; --warn-soft:#2a2213;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#0d1219; --surface:#141b25; --surface-2:#1b2431; --line:#28323f;
  --ink:#e8eef6; --ink-2:#a9b8ca; --ink-3:#7d8da1;
  --accent:#6aa6ff; --accent-soft:#16263d;
  --up:#3fbe7f; --down:#ef6b76; --warn:#e0a84a; --warn-soft:#2a2213;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--ui);
  font-size:15px;line-height:1.62;-webkit-font-smoothing:antialiased}}
.shell{{max-width:1180px;margin:0 auto;padding:0 24px 96px;
  display:grid;grid-template-columns:212px minmax(0,1fr);gap:44px;align-items:start}}
@media(max-width:900px){{.shell{{grid-template-columns:1fr;gap:0}} nav.toc{{display:none}}}}

header.top{{grid-column:1/-1;padding:56px 0 34px;border-bottom:1px solid var(--line);margin-bottom:36px}}
.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent);margin-bottom:12px}}
h1{{font-family:var(--display);font-size:40px;font-weight:600;margin:0 0 10px;
  letter-spacing:-.015em;text-wrap:balance;line-height:1.15}}
.sub{{color:var(--ink-2);max-width:62ch;margin:0;font-size:16px}}

nav.toc{{position:sticky;top:24px;font-size:13.5px}}
nav.toc a{{display:block;padding:4px 0;color:var(--ink-2);text-decoration:none;
  border-left:2px solid transparent;padding-left:11px}}
nav.toc a:hover{{color:var(--accent);border-left-color:var(--accent)}}
nav.toc .tt{{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink-3);margin:20px 0 7px;padding-left:11px}}
nav.toc .tt:first-child{{margin-top:0}}

main{{min-width:0}}
section.block{{margin-bottom:52px;scroll-margin-top:20px}}
h2{{font-family:var(--display);font-size:26px;font-weight:600;margin:0 0 6px;
  letter-spacing:-.01em;text-wrap:balance}}
h2+.lede{{color:var(--ink-2);margin:0 0 22px;max-width:66ch}}
h3{{font-size:16px;font-weight:600;margin:0 0 4px}}
p{{max-width:68ch}}

.card{{background:var(--surface);border:1px solid var(--line);border-radius:9px;
  padding:18px 20px;margin-bottom:14px}}
.card h3{{margin-bottom:6px}}
.card p:last-child{{margin-bottom:0}}
.tab-num{{font-family:var(--mono);font-size:11px;color:var(--accent);
  letter-spacing:.1em;text-transform:uppercase;display:block;margin-bottom:4px}}

.note{{border-left:3px solid var(--accent);background:var(--accent-soft);
  padding:13px 17px;border-radius:0 7px 7px 0;margin:18px 0}}
.note p{{margin:0}}
.caution{{border-left:3px solid var(--warn);background:var(--warn-soft);
  padding:13px 17px;border-radius:0 7px 7px 0;margin:18px 0}}
.caution p{{margin:0}}
.caution strong{{color:var(--warn)}}

table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px}}
th{{text-align:left;font-weight:600;color:var(--ink-2);font-size:12px;
  letter-spacing:.05em;text-transform:uppercase;padding:8px 12px 8px 0;
  border-bottom:1px solid var(--line)}}
td{{padding:9px 12px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}}
td code,li code{{font-family:var(--mono);font-size:12.5px;background:var(--surface-2);
  padding:1px 5px;border-radius:3px;color:var(--ink)}}
.scroll{{overflow-x:auto}}

.preset{{background:var(--surface);border:1px solid var(--line);border-radius:9px;
  padding:17px 20px;margin-bottom:13px}}
.preset.exit{{border-color:var(--down)}}
.phead{{display:flex;align-items:center;gap:10px;margin-bottom:5px}}
.badge{{font-family:var(--mono);font-size:9.5px;letter-spacing:.11em;padding:2px 7px;
  border-radius:3px;font-weight:500}}
.bentry{{background:var(--accent-soft);color:var(--accent)}}
.bexit{{background:var(--down);color:#fff}}
.pplain{{color:var(--ink-2);margin:0 0 11px}}
.plogic ul{{margin:5px 0 0;padding-left:17px}}
.plogic li{{margin:2px 0;font-size:13.5px}}
.plabel{{font-family:var(--mono);font-size:10px;letter-spacing:.11em;text-transform:uppercase;
  color:var(--ink-3);margin-right:6px}}
.joiner{{font-family:var(--mono);font-size:10px;color:var(--accent);letter-spacing:.1em}}
.op{{color:var(--ink-3)}}
.pmeta{{display:flex;gap:22px;flex-wrap:wrap;margin-top:11px;padding-top:10px;
  border-top:1px solid var(--line);font-size:13px;color:var(--ink-2)}}

#search{{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:8px;
  background:var(--surface);color:var(--ink);font:inherit;font-size:14.5px;margin-bottom:6px}}
#search:focus{{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}}
.shint{{color:var(--ink-3);font-size:12.5px;margin:0 0 22px}}
.ggroup{{margin-bottom:32px}}
.ggroup h3{{font-family:var(--display);font-size:19px;display:flex;align-items:baseline;gap:9px}}
.count{{font-family:var(--mono);font-size:11px;color:var(--ink-3);font-weight:400}}
.gblurb{{color:var(--ink-2);margin:0 0 12px;font-size:14px}}
.metrics{{display:grid;gap:9px}}
.metric{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 15px}}
.mhead{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:5px}}
.key{{font-family:var(--mono);font-size:12.5px;color:var(--accent);font-weight:500}}
.mlabel{{font-weight:600;font-size:14px}}
.formula{{font-family:var(--mono);font-size:12.5px;background:var(--surface-2);
  padding:6px 10px;border-radius:5px;color:var(--ink-2);overflow-x:auto;margin-bottom:6px}}
.mdesc{{margin:0;color:var(--ink-2);font-size:13.5px;max-width:none}}
.empty{{color:var(--ink-3);padding:18px 0;display:none}}

ol.routine{{padding-left:20px}}
ol.routine li{{margin-bottom:9px;max-width:66ch}}
footer{{grid-column:1/-1;border-top:1px solid var(--line);padding-top:20px;
  color:var(--ink-3);font-size:13px}}
footer code{{font-family:var(--mono);background:var(--surface-2);padding:1px 5px;border-radius:3px}}
</style>

<div class="shell">
<header class="top">
  <div class="eyebrow">Alpha-500 · Operator manual</div>
  <h1>What every tab, screen and number means</h1>
  <p class="sub">A reference for the person using the dashboard: what each tab is for, what
  each preset looks for, and exactly how all {len(METRICS)} metrics are calculated. Generated
  from the running metric registry, so it cannot drift from the code.</p>
</header>

<nav class="toc">
  <div class="tt">Start here</div>
  <a href="#conventions">Three conventions</a>
  <a href="#tabs">The three tabs</a>
  <div class="tt">Using it</div>
  <a href="#dashboard">Reading the dashboard</a>
  <a href="#presets">The seven screens</a>
  <a href="#filters">Filters &amp; columns</a>
  <a href="#backtest">The backtest tab</a>
  <div class="tt">Reference</div>
  <a href="#glossary">Metric glossary</a>
  <a href="#rules">Rules that bind</a>
  <a href="#routine">Daily routine</a>
</nav>

<main>

<section class="block" id="conventions">
  <h2>Three conventions that explain most confusion</h2>
  <p class="lede">Nearly every "why does this number look wrong" question resolves to one of
  these three.</p>

  <div class="card">
    <h3>1. Periods are trading sessions, never calendar days</h3>
    <p>"1 month" means <strong>21 sessions</strong>, not 30 days. A week is 5 sessions, a
    quarter 63, a year 252. This keeps a holiday cluster from making one month look shorter
    than another. A "3-month return" measured on 28 August looks back 63 sessions, which is
    usually further than three calendar months.</p>
  </div>

  <div class="card">
    <h3>2. Every price is adjusted for splits and bonuses — but not dividends</h3>
    <p>An unadjusted 1:2 split shows as a −50% day and would corrupt every metric downstream.
    Prices are therefore adjusted. Ordinary cash dividends are <em>not</em> adjusted out,
    because you trade price and price-return momentum is the convention. A large special
    dividend can produce a real-looking gap; the stock detail flags it.</p>
  </div>

  <div class="card">
    <h3>3. Blank means "cannot be computed", not zero</h3>
    <p>A stock with 200 sessions of history has no 12-month return, so the cell is blank
    rather than 0. This matters when filtering: <code>ret_12m &gt; 0</code> excludes blanks
    rather than treating them as failures, and a screen using a metric a stock cannot yet
    produce will simply not list it.</p>
  </div>
</section>

<section class="block" id="tabs">
  <h2>The three tabs</h2>
  <p class="lede">Each answers a different question.</p>

  <div class="card">
    <span class="tab-num">Tab 1</span>
    <h3>Dashboard — “what needs my attention tonight?”</h3>
    <p>The landing page. Exits come first, then market context, then candidates. Read it
    top to bottom once per evening; it is designed so the important things are above the
    fold and nothing needs hunting for.</p>
  </div>

  <div class="card">
    <span class="tab-num">Tab 2</span>
    <h3>Screener — “show me every stock matching these conditions”</h3>
    <p>Pick one of seven built-in screens, then narrow further with your own filters. The
    grid is fully sortable and its columns are yours to choose and reorder. Export to Excel,
    CSV or a self-contained HTML file.</p>
  </div>

  <div class="card">
    <span class="tab-num">Tab 3</span>
    <h3>Backtest — “would this screen actually have made money?”</h3>
    <p>Replays a screen across history with realistic costs and the tax an NRI actually
    pays. Slower than the other tabs — it runs two full simulations — and deliberately
    shows its warnings above its results.</p>
  </div>
</section>

<section class="block" id="dashboard">
  <h2>Reading the dashboard</h2>
  <p class="lede">In the order the page presents them, which is the order they matter.</p>

  <div class="scroll"><table>
    <thead><tr><th>Panel</th><th>What it tells you</th><th>How it is decided</th></tr></thead>
    <tbody>
      <tr><td><strong>Data status bar</strong></td>
        <td>Whether what you are looking at is current.</td>
        <td>Green when the served date equals the last completed session. Any warning names
        the reason — pipeline failed, not yet run, or metrics computed by an older build of
        the engine.</td></tr>
      <tr><td><strong>Market regime</strong></td>
        <td>Whether the wind is behind long positions.</td>
        <td><em>Risk-on</em>: index above its 200 SMA, 50 SMA above 200 SMA, and more new
        highs than new lows. <em>Risk-off</em>: index below its 200 SMA. <em>Neutral</em>:
        above the 200 SMA but the rest mixed.</td></tr>
      <tr><td><strong>Exit signals</strong></td>
        <td>Holdings that have broken down. Shown first, deliberately.</td>
        <td>The Momentum Breakdown screen, run against everything. Momentum tools bias hard
        toward finding entries, so exits are given the more prominent position.</td></tr>
      <tr><td><strong>Breadth</strong></td>
        <td>Whether a rise is broad or carried by a handful of names.</td>
        <td>Counts of advances, declines, new 52-week highs and new lows across the
        eligible universe.</td></tr>
      <tr><td><strong>Pullback + reversal</strong></td>
        <td>The top ten pulled back to support and showing signs of turning.</td>
        <td>Ranked by reversal score, then RS rating, then closeness to support. Ties break
        deterministically, so the same data always yields the same ten in the same order.</td></tr>
      <tr><td><strong>Momentum leaders</strong></td>
        <td>The strongest trends right now.</td>
        <td>Top ten by momentum score.</td></tr>
      <tr><td><strong>Sector heatmap</strong></td>
        <td>Where strength is concentrated.</td>
        <td>Median 1-week return per industry, for industries with at least three eligible
        members.</td></tr>
    </tbody>
  </table></div>

  <div class="caution"><p><strong>On the regime banner.</strong> In a Risk-off regime the
  dashboard shows a standing advisory rather than hiding candidates. Long momentum
  strategies take their deepest drawdowns in exactly that state. The tool will not stop you
  — but it will not let you miss the context either.</p></div>
</section>

<section class="block" id="presets">
  <h2>The seven screens</h2>
  <p class="lede">Six find entries. One finds exits, and is marked in red everywhere it
  appears.</p>
  {preset_cards}
  <div class="note"><p><strong>Two pullback screens, on purpose.</strong> “Pullback to
  Support” finds a perfect uptrend resting on a moving average and asks for no evidence the
  dip has ended — a continuation setup. “Pullback + Reversal” requires an identified support
  level <em>and</em> active confirmation that the fall has stopped — a timing signal. A stock
  can appear in either without the other.</p></div>
</section>

<section class="block" id="filters">
  <h2>Filters and columns</h2>
  <p class="lede">Narrowing a preset, and shaping what you see.</p>

  <h3 style="margin-top:22px">Adding your own conditions</h3>
  <p>The <strong>Filters</strong> button opens a condition builder. Each row is
  <em>field · operator · value</em>, and rows combine with AND. These are applied in the
  browser against the rows already loaded, so results update as you type.</p>

  <div class="scroll"><table>
    <thead><tr><th>Operator</th><th>Meaning</th><th>Example</th></tr></thead>
    <tbody>
      <tr><td><code>&gt;</code> <code>&gt;=</code> <code>&lt;</code> <code>&lt;=</code></td>
        <td>Numeric comparison.</td><td><code>rs_rating &gt;= 80</code></td></tr>
      <tr><td><code>=</code> <code>!=</code></td><td>Exact match; also used for true/false
        flags.</td><td><code>is_trend_template = true</code></td></tr>
      <tr><td><code>between</code></td><td>Inclusive range.</td>
        <td><code>atr_pct_14 between 0.02 and 0.06</code></td></tr>
      <tr><td><code>in</code> / <code>not in</code></td><td>Membership in a list.</td>
        <td><code>industry in Banks, Pharma</code></td></tr>
      <tr><td><code>is null</code> / <code>is not null</code></td>
        <td>Whether the metric could be computed at all.</td>
        <td><code>delivery_pct is not null</code></td></tr>
      <tr><td><code>top N</code> / <code>bottom N</code> / <code>top N%</code></td>
        <td>Rank within the current results.</td><td><code>momentum_score top 25</code></td></tr>
    </tbody>
  </table></div>

  <h3 style="margin-top:26px">Choosing and reordering columns</h3>
  <p>The <strong>Columns</strong> button sits beside Filters and opens on its own. Each
  column is a chip: <strong>drag</strong> it to move, or focus it and press
  <code>←</code> / <code>→</code> to shift it and <code>Delete</code> to remove it. Tick a
  metric lower in the panel to add it. Your choice and order are remembered
  <em>per screen</em>, so Momentum Leaders and Trend Template can each carry their own
  layout.</p>
  <p>Below 768&nbsp;px the grid becomes a card list showing symbol, close, 1-day and 1-week
  change, RS rating and momentum rank. Column controls do not appear there — widen the
  window to get them back.</p>
</section>

<section class="block" id="backtest">
  <h2>The backtest tab</h2>
  <p class="lede">What its numbers mean, and which of them to trust.</p>

  <div class="scroll"><table>
    <thead><tr><th>Figure</th><th>Meaning</th></tr></thead>
    <tbody>
      <tr><td><strong>Gross of tax</strong></td><td>After brokerage, STT, exchange charges,
        stamp duty, GST and slippage — but before withholding.</td></tr>
      <tr><td><strong>Net of tax</strong></td><td>The same run with TDS deducted at each
        profitable exit. This is the one that reflects your account. The two come from
        separate simulations, because withholding shrinks the balance you compound on.</td></tr>
      <tr><td><strong>CAGR</strong></td><td>Annualised growth rate. Over short windows this
        exaggerates — read total return instead.</td></tr>
      <tr><td><strong>Max drawdown</strong></td><td>Deepest peak-to-trough fall. Often the
        number that decides whether a strategy is actually livable.</td></tr>
      <tr><td><strong>Hit rate / avg win / avg loss</strong></td><td>Closed trades only.
        A ~30% hit rate is normal for momentum; it survives on win size.</td></tr>
      <tr><td><strong>Stop sweep</strong></td><td>Re-runs the test at several stop widths. A
        best value whose neighbours also work is trustworthy; an isolated spike is not, and
        the page says so.</td></tr>
      <tr><td><strong>Walk-forward</strong></td><td>Picks the stop on older data, then measures
        it on data it never saw. The gap between the two is the honest estimate of how much
        was fitting.</td></tr>
    </tbody>
  </table></div>

  <div class="caution"><p><strong>Every backtest here is biased upward.</strong> The universe
  is today's NIFTY 500, and stocks dropped from the index over the years were never loaded.
  Every symbol tested is therefore a survivor. Compare screens <em>against each other</em>
  over the same window — that is meaningful. Do not read any absolute return as achievable.</p></div>
</section>

<section class="block" id="glossary">
  <h2>Metric glossary</h2>
  <p class="lede">All {len(METRICS)} metrics, with the exact formula. <code>C_0</code> is the
  latest adjusted close; <code>C_N</code> the close N sessions earlier.</p>
  <input id="search" type="search" placeholder="Search — try “volume”, “52”, “rsi”, “support”…"
    aria-label="Search metrics">
  <p class="shint">Searches names, labels and descriptions.</p>
  <div id="results">{glossary}</div>
  <p class="empty" id="empty">No metric matches that.</p>
</section>

<section class="block" id="rules">
  <h2>Rules that bind what the tool may suggest</h2>
  <p class="lede">This dashboard is configured for a non-resident Indian tax-resident in
  France, trading an NRO non-PIS account. Those rules are built in, not advisory.</p>

  <div class="scroll"><table>
    <thead><tr><th>Rule</th><th>Effect on what you see</th></tr></thead>
    <tbody>
      <tr><td><strong>Delivery-based only</strong></td><td>No intraday, no BTST. No signal
        implies a round trip shorter than settlement, and every logged entry shows the
        earliest date it may be sold.</td></tr>
      <tr><td><strong>Long only</strong></td><td>Every screen finds buys. Momentum Breakdown
        is an exit list for holdings and is never a short list.</td></tr>
      <tr><td><strong>Cash only</strong></td><td>No margin or pledged collateral on an NRI
        account, so position sizing assumes 100% cash and offers no leverage input.</td></tr>
      <tr><td><strong>TDS at each exit</strong></td><td>Tax is withheld when each profitable
        trade settles, not at filing. Roughly 23.9% short-term, 15% after twelve months.
        Frequent trading compounds this into a materially lower net return.</td></tr>
      <tr><td><strong>Universe floor</strong></td><td>Screens exclude anything below
        {rupees(S["liquidity_floor_inr"])} of 20-day median traded value, outside series
        {esc("/".join(S["allowed_series"]))}, under surveillance, or with fewer than
        {S["min_history_days"]} sessions of history.</td></tr>
    </tbody>
  </table></div>

  <div class="caution"><p><strong>Not advice.</strong> Tax figures are computed estimates for
  planning. Confirm rates and mechanics with a cross-border chartered accountant and a French
  <em>conseiller fiscal</em> before relying on them for filing. This tool places no orders in
  any circumstance.</p></div>
</section>

<section class="block" id="routine">
  <h2>A working evening routine</h2>
  <p class="lede">The pipeline runs itself at 18:45 IST. This is what to do afterwards.</p>
  <ol class="routine">
    <li><strong>Check the status bar first.</strong> If it is not green, nothing below it is
    today's data. The reason is written next to it.</li>
    <li><strong>Read the exit signals before anything else.</strong> Managing what you own
    outranks finding something new.</li>
    <li><strong>Note the regime.</strong> In Risk-off, expect fewer and weaker candidates,
    and size accordingly.</li>
    <li><strong>Work the entry screens</strong> that suit the regime — breakouts when
    trending, Pullback + Reversal when the market is choppy.</li>
    <li><strong>Open a candidate's detail</strong> for the chart, the suggested stop, the
    position size, and the break-even move that trade must clear after costs and
    withholding.</li>
    <li><strong>Check sector concentration.</strong> A top-20 momentum list in a hot sector
    is frequently one bet expressed twenty ways.</li>
    <li><strong>Export the shortlist</strong> if you want it outside the tool. Every export
    carries its as-of date, so it can never be mistaken for a fresher one later.</li>
  </ol>

  <div class="note"><p><strong>Key defaults in force.</strong> Momentum regression looks back
  {S["momentum_lookback"]} sessions; a single session moving more than
  {S["gap_disqualifier_pct"]:.0%} disqualifies a stock from momentum ranking; breakouts need
  {S["rel_volume_threshold"]}× normal volume; "at support" means within
  {S["support_tolerance_pct"]:.0%}; a pullback counts between {S["pullback_min_pct"]:.0%} and
  {S["pullback_max_pct"]:.0%}; reversal needs {S["reversal_min_score"]} of 5 checks; stops
  default to {S["atr_stop_multiple"]}× ATR risking {S["risk_per_trade_pct"]:.2%} of the
  portfolio, capped at {S["max_position_weight"]:.0%} per position. Composite score weights:
  {weights}.</p></div>
</section>

</main>

<footer>
  Generated from the live metric registry — {len(METRICS)} metrics, {len(PRESETS)} screens.
  Regenerate with <code>alpha500</code>'s registry after any metric change so this manual and
  the application cannot disagree. Decision support only; no orders are placed.
</footer>
</div>

<script>
(function(){{
  var box=document.getElementById('search');
  var empty=document.getElementById('empty');
  var cards=[].slice.call(document.querySelectorAll('.metric'));
  var groups=[].slice.call(document.querySelectorAll('.ggroup'));
  box.addEventListener('input',function(){{
    var q=box.value.trim().toLowerCase();
    var shown=0;
    cards.forEach(function(c){{
      var hit=!q||c.dataset.search.indexOf(q)>=0;
      c.style.display=hit?'':'none';
      if(hit) shown++;
    }});
    groups.forEach(function(g){{
      var any=[].slice.call(g.querySelectorAll('.metric'))
        .some(function(c){{return c.style.display!=='none'}});
      g.style.display=any?'':'none';
    }});
    empty.style.display=shown?'none':'block';
  }});
}})();
</script>
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML, encoding="utf-8")
    print(f"Wrote {OUT} ({len(METRICS)} metrics, {len(PRESETS)} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
