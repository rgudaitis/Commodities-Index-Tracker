"""Build the commodities index dashboard HTML from history.json.
Each commodity/group/composite shows three comparisons: Day, YTD, and YoY.
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(HERE, "history.json")
OUT_PATH = os.path.join(HERE, "dashboard.html")

GROUP_LABELS = {
    "metals": "Metals",
    "energy": "Energy",
    "freight": "Freight",
    "resins": "Resins (PPI, monthly)",
}
GROUP_ORDER = ["metals", "energy", "freight", "resins"]

# fixed categorical slot per group, in palette order (never cycled/reassigned)
GROUP_COLOR_SLOT = {
    "metals": 1,   # blue
    "energy": 8,   # orange
    "freight": 2,  # aqua
    "resins": 5,   # violet
}

SERIES_COLORS_LIGHT = {
    1: "#2a78d6", 2: "#1baf7a", 3: "#eda100", 4: "#008300",
    5: "#4a3aa7", 6: "#e34948", 7: "#e87ba4", 8: "#eb6834",
}
SERIES_COLORS_DARK = {
    1: "#3987e5", 2: "#199e70", 3: "#c98500", 4: "#008300",
    5: "#9085e9", 6: "#e66767", 7: "#d55181", 8: "#d95926",
}


def load_history():
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def is_monthly(c):
    return "price" not in c


def get_value(c):
    return c.get("price") if not is_monthly(c) else c.get("value")


def get_prev(c):
    return c.get("prev_close") if not is_monthly(c) else c.get("prev_value")


def fmt_price(v, unit):
    if v is None:
        return "—"
    if unit and "$" in unit:
        return f"${v:,.2f}"
    return f"{v:,.2f}"


def fmt_pct(cur, base):
    if cur is None or base is None or base == 0:
        return None
    return (cur - base) / base * 100


def pct_badge(pct, label=None):
    prefix = f'<span class="chg-label">{label}</span>' if label else ""
    if pct is None:
        return f'{prefix}<span class="chg chg-flat">—</span>'
    sign = "+" if pct >= 0 else ""
    cls = "chg-up" if pct > 0 else ("chg-down" if pct < 0 else "chg-flat")
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "–")
    return f'{prefix}<span class="chg {cls}">{arrow} {sign}{pct:.2f}%</span>'


def sparkline_svg(values, slot, w=180, h=44):
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return '<div class="spark-empty">Building daily history… check back tomorrow</div>'
    vmin, vmax = min(pts), max(pts)
    rng = (vmax - vmin) or 1
    n = len(values)
    step = w / (n - 1) if n > 1 else w
    coords = []
    for i, v in enumerate(values):
        if v is None:
            continue
        x = i * step
        y = h - ((v - vmin) / rng) * (h - 8) - 4
        coords.append((x, y))
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
    lx, ly = coords[-1]
    color_var = f"var(--series-{slot})"
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" class="spark">'
        f'<path d="{path}" fill="none" stroke="{color_var}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="{color_var}"/>'
        f'</svg>'
    )


def commodity_pcts(c):
    """Return (day_pct, ytd_pct, yoy_pct, day_label) for one commodity dict."""
    cur = get_value(c)
    day_pct = fmt_pct(cur, get_prev(c))
    ytd_pct = fmt_pct(cur, c.get("ytd_base"))
    yoy_pct = fmt_pct(cur, c.get("yoy_base"))
    day_label = "Mo" if is_monthly(c) else "Day"
    return day_pct, ytd_pct, yoy_pct, day_label


def build_group_section(group_key, group_of, last_snap, own_history_series):
    members = [k for k, g in group_of.items() if g == group_key]
    slot = GROUP_COLOR_SLOT[group_key]

    rows = []
    for k in members:
        c = last_snap["commodities"].get(k, {})
        label = c.get("label", k)
        unit = c.get("unit", "")
        cur = get_value(c)
        period = c.get("period")
        sub = f'<div class="tile-sub">{period}</div>' if period else ""
        day_pct, ytd_pct, yoy_pct, day_label = commodity_pcts(c)

        rows.append(f"""
        <div class="tile">
          <div class="tile-head">
            <div class="tile-label">{label}</div>
          </div>
          <div class="tile-value">{fmt_price(cur, unit)}<span class="tile-unit">{unit}</span></div>
          {sub}
          <div class="badge-row">
            {pct_badge(day_pct, day_label)}
            {pct_badge(ytd_pct, "YTD")}
            {pct_badge(yoy_pct, "YoY")}
          </div>
          {sparkline_svg(own_history_series.get(k, []), slot)}
        </div>""")

    return f"""
    <section class="group">
      <h2 class="group-title"><span class="dot" style="background:var(--series-{slot})"></span>{GROUP_LABELS[group_key]}</h2>
      <div class="tile-grid">{''.join(rows)}</div>
    </section>"""


def own_tracked_series(snapshots):
    """Base-100 index per commodity using OUR OWN accumulated daily snapshots
    (only goes back to when tracking started — used for the sparkline only,
    NOT for the YTD/YoY badges, which use each source's full history instead)."""
    keys = set()
    for snap in snapshots:
        keys.update(snap["commodities"].keys())
    base_values = {}
    series = {k: [] for k in keys}
    for snap in snapshots:
        for k in keys:
            c = snap["commodities"].get(k, {})
            v = get_value(c) if c else None
            if v is None:
                series[k].append(None)
                continue
            if k not in base_values:
                base_values[k] = v
            series[k].append((v / base_values[k]) * 100 if base_values[k] else None)
    return series


def build_html():
    history = load_history()
    snapshots = history["snapshots"]
    if not snapshots:
        raise SystemExit("No snapshots in history.json — run fetch_data.py first.")

    last_snap = snapshots[-1]
    group_of = {k: c.get("group") for k, c in last_snap["commodities"].items()}
    own_series = own_tracked_series(snapshots)

    # composite = equal-weighted average of each commodity's own pct across all members
    all_day, all_ytd, all_yoy = [], [], []
    group_pcts = {}
    for g in GROUP_ORDER:
        members = [k for k, gg in group_of.items() if gg == g]
        gday, gytd, gyoy = [], [], []
        for k in members:
            c = last_snap["commodities"].get(k, {})
            if not c or "error" in c:
                continue
            d, y1, y2, _ = commodity_pcts(c)
            if d is not None:
                gday.append(d); all_day.append(d)
            if y1 is not None:
                gytd.append(y1); all_ytd.append(y1)
            if y2 is not None:
                gyoy.append(y2); all_yoy.append(y2)
        group_pcts[g] = {
            "day": sum(gday) / len(gday) if gday else None,
            "ytd": sum(gytd) / len(gytd) if gytd else None,
            "yoy": sum(gyoy) / len(gyoy) if gyoy else None,
        }

    composite_day = sum(all_day) / len(all_day) if all_day else None
    composite_ytd = sum(all_ytd) / len(all_ytd) if all_ytd else None
    composite_yoy = sum(all_yoy) / len(all_yoy) if all_yoy else None

    group_tiles = []
    for g in GROUP_ORDER:
        slot = GROUP_COLOR_SLOT[g]
        gp = group_pcts[g]
        group_tiles.append(f"""
        <div class="mini-tile">
          <div class="mini-dot" style="background:var(--series-{slot})"></div>
          <div>
            <div class="mini-label">{GROUP_LABELS[g]}</div>
            <div class="mini-badges">
              {pct_badge(gp['day'], 'Mo' if g == 'resins' else 'Day')}
              {pct_badge(gp['ytd'], 'YTD')}
              {pct_badge(gp['yoy'], 'YoY')}
            </div>
          </div>
        </div>""")

    sections = "".join(build_group_section(g, group_of, last_snap, own_series) for g in GROUP_ORDER)

    fetched_at = last_snap["fetched_at"]
    fetched_dt = datetime.fromisoformat(fetched_at)
    as_of_str = fetched_dt.strftime("%B %d, %Y · %I:%M %p UTC")
    n_days = len(snapshots)
    history_note = (
        "First snapshot — daily sparkline trend lines will appear starting tomorrow. YTD and YoY comparisons are accurate from day one (pulled from each source's full history)."
        if n_days == 1 else f"{n_days} days of daily tracking accumulated (sparklines). YTD/YoY always pulled from full source history."
    )

    series_color_vars_light = "\n".join(f"    --series-{s}: {c};" for s, c in SERIES_COLORS_LIGHT.items())
    series_color_vars_dark = "\n".join(f"      --series-{s}: {c};" for s, c in SERIES_COLORS_DARK.items())

    history_json = json.dumps(history, separators=(",", ":"))

    html = f"""<title>Raw Materials &amp; Commodities Index</title>
<script type="application/json" id="history-data">{history_json}</script>
<style>
  :root {{
    color-scheme: light;
{series_color_vars_light}
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
{series_color_vars_dark}
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
{series_color_vars_dark}
  }}

  :root {{
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --gridline: #e1e0d9;
    --border: rgba(11,11,11,0.10);
    --good: #006300;
    --bad: #b3261e;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --gridline: #2c2c2a;
      --border: rgba(255,255,255,0.10);
      --good: #0ca30c;
      --bad: #e66767;
    }}
  }}
  :root[data-theme="dark"] {{
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --gridline: #2c2c2a;
    --border: rgba(255,255,255,0.10);
    --good: #0ca30c;
    --bad: #e66767;
  }}

  * {{ box-sizing: border-box; }}
  body {{
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    margin: 0;
    padding: 2rem 1.25rem 4rem;
  }}
  .wrap {{ max-width: 1020px; margin: 0 auto; }}

  header {{ margin-bottom: 1.75rem; }}
  .eyebrow {{
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.35rem;
  }}
  h1 {{ font-size: 1.5rem; margin: 0 0 0.25rem; }}
  .asof {{ font-size: 0.82rem; color: var(--text-secondary); }}
  .history-note {{ font-size: 0.78rem; color: var(--text-muted); margin-top: 0.15rem; max-width: 640px; }}

  .hero {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1.5rem 1.75rem;
    margin: 1.25rem 0 1.5rem;
  }}
  .hero-label {{ font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.9rem; }}
  .hero-badges {{ display: flex; flex-wrap: wrap; gap: 1.75rem; }}
  .hero-stat {{ display: flex; flex-direction: column; gap: 0.25rem; }}
  .hero-stat-label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); }}
  .hero-stat .chg {{ font-size: 1.5rem; }}

  .mini-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.75rem;
    margin-bottom: 2rem;
  }}
  .mini-tile {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.85rem 1rem;
    display: flex;
    align-items: flex-start;
    gap: 0.65rem;
  }}
  .mini-dot {{ width: 10px; height: 10px; border-radius: 50%; flex: none; margin-top: 0.3rem; }}
  .mini-label {{ font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.3rem; }}
  .mini-badges {{ display: flex; flex-wrap: wrap; gap: 0.55rem; }}

  .group {{ margin-bottom: 2.1rem; }}
  .group-title {{
    font-size: 1.02rem; font-weight: 650; margin: 0 0 0.85rem;
    display: flex; align-items: center; gap: 0.55rem;
  }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex: none; }}

  .tile-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 0.9rem;
  }}
  .tile {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem 1.1rem 0.9rem;
  }}
  .tile-head {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 0.35rem;
  }}
  .tile-label {{ font-size: 0.82rem; color: var(--text-secondary); font-weight: 600; }}
  .tile-value {{ font-size: 1.4rem; font-weight: 700; }}
  .tile-unit {{ font-size: 0.72rem; font-weight: 500; color: var(--text-muted); margin-left: 0.35rem; }}
  .tile-sub {{ font-size: 0.72rem; color: var(--text-muted); margin-top: 0.1rem; }}

  .badge-row {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.55rem; }}
  .chg-label {{ font-size: 0.68rem; color: var(--text-muted); margin-right: 0.15rem; }}
  .chg {{ font-size: 0.76rem; font-weight: 600; white-space: nowrap; }}
  .chg-up {{ color: var(--good); }}
  .chg-down {{ color: var(--bad); }}
  .chg-flat {{ color: var(--text-muted); }}

  .spark {{ display: block; margin-top: 0.6rem; }}
  .spark-empty {{
    font-size: 0.72rem; color: var(--text-muted); margin-top: 0.6rem;
    padding: 0.6rem 0; border-top: 1px dashed var(--gridline);
  }}

  footer {{
    margin-top: 2.5rem; padding-top: 1.25rem; border-top: 1px solid var(--gridline);
    font-size: 0.74rem; color: var(--text-muted);
  }}
  footer a {{ color: inherit; }}
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">Daily Index &middot; Refreshes 7:00 AM ET</div>
    <h1>Raw Materials &amp; Commodities Index</h1>
    <div class="asof">As of {as_of_str}</div>
    <div class="history-note">{history_note}</div>
  </header>

  <div class="hero">
    <div class="hero-label">Composite (equal-weighted average across all tracked commodities)</div>
    <div class="hero-badges">
      <div class="hero-stat"><span class="hero-stat-label">Day / Mo</span>{pct_badge(composite_day)}</div>
      <div class="hero-stat"><span class="hero-stat-label">YTD</span>{pct_badge(composite_ytd)}</div>
      <div class="hero-stat"><span class="hero-stat-label">YoY</span>{pct_badge(composite_yoy)}</div>
    </div>
  </div>

  <div class="mini-grid">
    {''.join(group_tiles)}
  </div>

  {sections}

  <footer>
    Day/Mo = vs prior trading day (metals/energy/freight) or prior month (resins, PPI is monthly). YTD = vs first trading day/month of {fetched_dt.year}. YoY = vs ~12 months ago (same trading day or same month last year). Sources: metals &amp; energy &mdash; Yahoo Finance daily futures (Copper HG=F, Aluminum ALI=F, Steel HRC=F, WTI Crude CL=F, Natural Gas NG=F); freight &mdash; BDRY dry-bulk shipping ETF (proxy for Baltic Dry Index, which has no free feed); resins &mdash; U.S. Bureau of Labor Statistics Producer Price Index, series WPU066 &amp; WPU0662 (monthly, no PVC-specific series exists free). Not investment advice.
  </footer>
</div>
"""
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    return OUT_PATH


if __name__ == "__main__":
    path = build_html()
    print(f"Wrote {path}")
