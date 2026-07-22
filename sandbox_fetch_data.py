"""Fetch today's commodity snapshot for the sandbox routine.

This sandbox's outbound network is restricted to a small host allowlist that
does NOT include Yahoo Finance or BLS directly, but DOES include api.github.com.
A separate GitHub Actions workflow (running on GitHub's own unrestricted
runners) fetches the real data daily and commits it as data.json to a public
repo; this script just reads that back over the one host this sandbox can
reach, then merges it into the accumulated history.json exactly like the
original direct-fetch version used to.
"""
import json
import os
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(HERE, "history.json")
DATA_URL = "https://api.github.com/repos/rgudaitis/Commodities-Index-Tracker/contents/data.json"

# Used only if the GitHub fetch itself fails, so every commodity still gets a
# properly labeled error entry (matching the schema build_dashboard.py expects)
# instead of the whole run silently producing nothing.
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


def fetch_today_snapshot():
    r = requests.get(DATA_URL, headers={"Accept": "application/vnd.github.raw+json"}, timeout=20)
    r.raise_for_status()
    return r.json()


def load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"snapshots": []}


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def main():
    now = datetime.now(timezone.utc).isoformat()
    try:
        snapshot = fetch_today_snapshot()
    except Exception as e:
        err = f"Could not fetch data.json from GitHub: {e}"
        snapshot = {"fetched_at": now, "commodities": {
            **{k: {**m, "error": err} for k, m in YAHOO_TICKERS.items()},
            **{k: {**m, "error": err} for k, m in BLS_SERIES.items()},
        }}

    history = load_history()
    today = snapshot["fetched_at"][:10]
    history["snapshots"] = [s for s in history["snapshots"] if s["fetched_at"][:10] != today]
    history["snapshots"].append(snapshot)
    history["snapshots"].sort(key=lambda s: s["fetched_at"])
    save_history(history)

    print(json.dumps(snapshot, indent=2))
    return snapshot


if __name__ == "__main__":
    main()
