"""Fetch daily commodity prices (Yahoo Finance) and monthly PPI resin data (BLS).
Runs on GitHub Actions, which has normal unrestricted internet access - the
downstream sandbox routine can't reach these hosts directly, so it reads the
data.json this script produces via the GitHub API instead.
"""
import json
import time
from datetime import datetime, timedelta, timezone

import requests

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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; commodities-index/1.0)"}


def fetch_yahoo(ticker, retries=3):
    """Current price + day-over-day prev close, plus YTD-start and ~1-year-ago
    closes pulled straight from 2y of daily history (no dependency on our own
    accumulated tracking, so YTD/YoY are correct from day one)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    for attempt in range(retries):
        try:
            r = requests.get(url, params={"interval": "1d", "range": "2y"}, headers=HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            ts_market = meta.get("regularMarketTime")
            as_of = datetime.fromtimestamp(ts_market, tz=timezone.utc).isoformat() if ts_market else None

            timestamps = result.get("timestamp") or []
            closes = result["indicators"]["quote"][0].get("close") or []
            pairs = [(t, c) for t, c in zip(timestamps, closes) if c is not None]

            # NOTE: meta.chartPreviousClose is NOT reliable here — with a long
            # range like 2y, Yahoo sets it relative to the start of the range,
            # not to yesterday. Derive true day-over-day from the daily closes
            # series itself (second-to-last bar), falling back to meta only if
            # the series is too short.
            if len(pairs) >= 2:
                prev_close = pairs[-2][1]
            else:
                prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")

            ytd_base = ytd_base_date = None
            yoy_base = yoy_base_date = None
            if pairs:
                now = datetime.now(timezone.utc)
                year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
                yoy_target = now - timedelta(days=365)

                ytd_pt = next(((t, c) for t, c in pairs if datetime.fromtimestamp(t, timezone.utc) >= year_start), None)
                if ytd_pt:
                    ytd_base_date = datetime.fromtimestamp(ytd_pt[0], timezone.utc).date().isoformat()
                    ytd_base = ytd_pt[1]

                yoy_pt = min(pairs, key=lambda tc: abs(datetime.fromtimestamp(tc[0], timezone.utc) - yoy_target))
                yoy_base_date = datetime.fromtimestamp(yoy_pt[0], timezone.utc).date().isoformat()
                yoy_base = yoy_pt[1]

            return {
                "price": price, "prev_close": prev_close, "as_of": as_of,
                "ytd_base": ytd_base, "ytd_base_date": ytd_base_date,
                "yoy_base": yoy_base, "yoy_base_date": yoy_base_date,
            }
        except Exception as e:
            if attempt == retries - 1:
                return {"error": str(e)}
            time.sleep(2)


def fetch_bls(series_ids, retries=3):
    """Monthly PPI series, pulling the last ~2 calendar years so we can find
    latest, prior-month, start-of-year, and same-month-last-year in one call."""
    now_year = datetime.now(timezone.utc).year
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    for attempt in range(retries):
        try:
            r = requests.post(
                url,
                json={"seriesid": series_ids, "startyear": str(now_year - 1), "endyear": str(now_year)},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError(f"BLS status: {data.get('status')} {data.get('message')}")
            out = {}
            for series in data["Results"]["series"]:
                out[series["seriesID"]] = series["data"]  # newest first
            return out
        except Exception as e:
            if attempt == retries - 1:
                return {"error": str(e)}
            time.sleep(2)


def bls_point(points, year, period):
    for p in points:
        if p["year"] == str(year) and p["period"] == period:
            return p
    return None


def main():
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {"fetched_at": now, "commodities": {}}

    for key, meta in YAHOO_TICKERS.items():
        res = fetch_yahoo(meta["ticker"])
        snapshot["commodities"][key] = {**meta, **res}

    bls_ids = [v["series_id"] for v in BLS_SERIES.values()]
    bls_data = fetch_bls(bls_ids)

    for key, meta in BLS_SERIES.items():
        sid = meta["series_id"]
        if isinstance(bls_data, dict) and sid in bls_data:
            points = bls_data[sid]  # newest first
            latest = points[0] if points else None
            prev = points[1] if len(points) > 1 else None
            entry = {
                **meta,
                "value": float(latest["value"]) if latest else None,
                "period": f"{latest['periodName']} {latest['year']}" if latest else None,
                "prev_value": float(prev["value"]) if prev else None,
                "prev_period": f"{prev['periodName']} {prev['year']}" if prev else None,
            }
            if latest:
                ly, lp = int(latest["year"]), latest["period"]
                jan_this_year = bls_point(points, ly, "M01")
                same_month_last_year = bls_point(points, ly - 1, lp)
                entry["ytd_base"] = float(jan_this_year["value"]) if jan_this_year else None
                entry["ytd_base_period"] = f"{jan_this_year['periodName']} {jan_this_year['year']}" if jan_this_year else None
                entry["yoy_base"] = float(same_month_last_year["value"]) if same_month_last_year else None
                entry["yoy_base_period"] = f"{same_month_last_year['periodName']} {same_month_last_year['year']}" if same_month_last_year else None
            snapshot["commodities"][key] = entry
        else:
            snapshot["commodities"][key] = {**meta, "error": bls_data.get("error", "unknown")}

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    print(json.dumps(snapshot, indent=2))
    return snapshot


if __name__ == "__main__":
    main()
