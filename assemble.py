"""Assemble today's commodity snapshot from pre-fetched raw JSON files.

This replaces fetch_data.py's network layer. Instead of this script calling
requests.get/post itself (blocked by this sandbox's egress proxy for every
external host except its own allowlist), the cloud agent fetches each small,
targeted window via the WebFetch tool (which runs on Anthropic's infra, not
through this sandbox's proxy) and saves the raw verbatim JSON here first.
This script only reads local files and does the exact same parsing/merging
fetch_data.py used to do, producing an identical history.json schema so
build_dashboard.py needs no changes.

Expected local files before running this:
  windows.json                     - from compute_windows.py
  raw/{key}_current.json           - Yahoo chart, range=5d
  raw/{key}_ytd.json                - Yahoo chart, period1/period2 near Jan 1
  raw/{key}_yoy.json                - Yahoo chart, period1/period2 ~365d ago
  raw/{key}_bls.json                - BLS series response, per series
Any raw file that WebFetch couldn't retrieve cleanly should contain
{"error": "<description>"} instead - this script treats that the same as a
failed fetch.
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(HERE, "history.json")
WINDOWS_PATH = os.path.join(HERE, "windows.json")
RAW_DIR = os.path.join(HERE, "raw")

YAHOO_TICKERS = {
    "copper": {"ticker": "HG=F", "label": "Copper", "unit": "$/lb", "group": "metals"},
    "aluminum": {"ticker": "ALI=F", "label": "Aluminum", "unit": "$/ton", "group": "metals"},
    "steel": {"ticker": "HRC=F", "label": "Steel (HRC)", "unit": "$/ton", "group": "metals"},
    "crude_oil": {"ticker": "CL=F", "label": "Crude Oil (WTI)", "unit": "$/bbl", "group": "energy"},
    "natural_gas": {"ticker": "NG=F", "label": "Natural Gas", "unit": "$/MMBtu", "group": "energy"},
    "shipping": {"ticker": "BDRY", "label": "Dry Bulk Shipping (proxy)", "unit": "ETF $", "group": "freight"},
}

BLS_SERIES = {
    "resin_broad": {"series_id": "WPU066", "label": "Plastic Resins & Materials (PPI)", "group": "resins"},
    "resin_thermo": {"series_id": "WPU0662", "label": "Thermoplastic Resins incl. PP/PE/ABS (PPI)", "group": "resins"},
}


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return None


def yahoo_pairs(raw):
    """Extract (timestamp, close) pairs + meta from a raw Yahoo chart response."""
    if not raw or "error" in raw:
        return None, None
    try:
        result = raw["chart"]["result"][0]
        meta = result["meta"]
        timestamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0].get("close") or []
        pairs = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
        return pairs, meta
    except Exception:
        return None, None


def assemble_yahoo(key, meta, windows):
    current_raw = load_json(os.path.join(RAW_DIR, f"{key}_current.json"))
    pairs, ymeta = yahoo_pairs(current_raw)
    if not pairs or ymeta is None:
        err = (current_raw or {}).get("error", "missing or invalid current-window raw file")
        return {**meta, "error": err}

    price = ymeta.get("regularMarketPrice")
    ts_market = ymeta.get("regularMarketTime")
    as_of = datetime.fromtimestamp(ts_market, tz=timezone.utc).isoformat() if ts_market else None
    if len(pairs) >= 2:
        prev_close = pairs[-2][1]
    else:
        prev_close = ymeta.get("chartPreviousClose") or ymeta.get("previousClose")

    ytd_base = ytd_base_date = None
    ytd_pairs, _ = yahoo_pairs(load_json(os.path.join(RAW_DIR, f"{key}_ytd.json")))
    if ytd_pairs:
        ytd_pairs.sort(key=lambda tc: tc[0])
        ytd_base_date = datetime.fromtimestamp(ytd_pairs[0][0], timezone.utc).date().isoformat()
        ytd_base = ytd_pairs[0][1]

    yoy_base = yoy_base_date = None
    yoy_pairs, _ = yahoo_pairs(load_json(os.path.join(RAW_DIR, f"{key}_yoy.json")))
    if yoy_pairs:
        yoy_target = datetime.fromisoformat(windows["yoy_target_iso"])
        yoy_pt = min(yoy_pairs, key=lambda tc: abs(datetime.fromtimestamp(tc[0], timezone.utc) - yoy_target))
        yoy_base_date = datetime.fromtimestamp(yoy_pt[0], timezone.utc).date().isoformat()
        yoy_base = yoy_pt[1]

    return {
        **meta, "price": price, "prev_close": prev_close, "as_of": as_of,
        "ytd_base": ytd_base, "ytd_base_date": ytd_base_date,
        "yoy_base": yoy_base, "yoy_base_date": yoy_base_date,
    }


def bls_point(points, year, period):
    for p in points:
        if p["year"] == str(year) and p["period"] == period:
            return p
    return None


def assemble_bls(key, meta):
    raw = load_json(os.path.join(RAW_DIR, f"{key}_bls.json"))
    if not raw or "error" in raw:
        err = (raw or {}).get("error", "missing or invalid raw file")
        return {**meta, "error": err}
    if raw.get("status") != "REQUEST_SUCCEEDED":
        return {**meta, "error": f"BLS status: {raw.get('status')} {raw.get('message')}"}
    try:
        points = raw["Results"]["series"][0]["data"]  # newest first
    except Exception as e:
        return {**meta, "error": str(e)}
    if not points:
        return {**meta, "error": "no data points"}

    latest = points[0]
    prev = points[1] if len(points) > 1 else None
    entry = {
        **meta,
        "value": float(latest["value"]),
        "period": f"{latest['periodName']} {latest['year']}",
        "prev_value": float(prev["value"]) if prev else None,
        "prev_period": f"{prev['periodName']} {prev['year']}" if prev else None,
    }
    ly, lp = int(latest["year"]), latest["period"]
    jan_this_year = bls_point(points, ly, "M01")
    same_month_last_year = bls_point(points, ly - 1, lp)
    entry["ytd_base"] = float(jan_this_year["value"]) if jan_this_year else None
    entry["ytd_base_period"] = f"{jan_this_year['periodName']} {jan_this_year['year']}" if jan_this_year else None
    entry["yoy_base"] = float(same_month_last_year["value"]) if same_month_last_year else None
    entry["yoy_base_period"] = f"{same_month_last_year['periodName']} {same_month_last_year['year']}" if same_month_last_year else None
    return entry


def load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"snapshots": []}


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def main():
    windows = load_json(WINDOWS_PATH)
    if windows is None:
        raise SystemExit("windows.json missing - run compute_windows.py first.")

    now = datetime.fromisoformat(windows["now_iso"])
    snapshot = {"fetched_at": now.isoformat(), "commodities": {}}

    for key, meta in YAHOO_TICKERS.items():
        snapshot["commodities"][key] = assemble_yahoo(key, meta, windows)

    for key, meta in BLS_SERIES.items():
        snapshot["commodities"][key] = assemble_bls(key, meta)

    history = load_history()
    today = now.isoformat()[:10]
    history["snapshots"] = [s for s in history["snapshots"] if s["fetched_at"][:10] != today]
    history["snapshots"].append(snapshot)
    history["snapshots"].sort(key=lambda s: s["fetched_at"])
    save_history(history)

    print(json.dumps(snapshot, indent=2))
    return snapshot


if __name__ == "__main__":
    main()
