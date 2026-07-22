"""Compute the small date windows needed for YTD and YoY baseline lookups.
Written once per run so the WebFetch URLs built from these boundaries and the
later assembly step agree on the exact same target dates. No network calls.
"""
import json
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
yoy_target = now - timedelta(days=365)

windows = {
    "now_iso": now.isoformat(),
    "ytd_period1": int(year_start.timestamp()),
    "ytd_period2": int((year_start + timedelta(days=9)).timestamp()),
    "yoy_period1": int((yoy_target - timedelta(days=7)).timestamp()),
    "yoy_period2": int((yoy_target + timedelta(days=7)).timestamp()),
    "yoy_target_iso": yoy_target.isoformat(),
    "bls_start_year": now.year - 1,
    "bls_end_year": now.year,
}
with open("windows.json", "w") as f:
    json.dump(windows, f, indent=2)
print(json.dumps(windows, indent=2))
