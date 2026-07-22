import os

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_URL = "https://claude.ai/code/artifact/c01e2adb-9419-412c-932d-c9b2e917012a"

with open(os.path.join(HERE, "compute_windows.py"), encoding="utf-8") as f:
    windows_src = f.read()
with open(os.path.join(HERE, "assemble.py"), encoding="utf-8") as f:
    assemble_src = f.read()
with open(os.path.join(HERE, "build_dashboard.py"), encoding="utf-8") as f:
    build_src = f.read()

YAHOO_TICKERS = {
    "copper": "HG=F",
    "aluminum": "ALI=F",
    "steel": "HRC=F",
    "crude_oil": "CL=F",
    "natural_gas": "NG=F",
    "shipping": "BDRY",
}
BLS_SERIES = {
    "resin_broad": "WPU066",
    "resin_thermo": "WPU0662",
}

EXTRACT_PROMPT = (
    'Output ONLY the exact, complete, verbatim raw JSON text of this response, '
    'with no summarization, paraphrasing, or truncation. If the response is not '
    'valid JSON, output exactly: {"error": "<brief description of what went wrong>"}'
)

fetch_lines = []
for key, ticker in YAHOO_TICKERS.items():
    fetch_lines.append(f"""
  {key} ({ticker}):
    - current: WebFetch url=https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d
      -> save to raw/{key}_current.json
    - ytd:     WebFetch url=https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&period1=<ytd_period1>&period2=<ytd_period2>
      -> save to raw/{key}_ytd.json
    - yoy:     WebFetch url=https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&period1=<yoy_period1>&period2=<yoy_period2>
      -> save to raw/{key}_yoy.json""")
yahoo_table = "".join(fetch_lines)

bls_lines = []
for key, series_id in BLS_SERIES.items():
    bls_lines.append(f"""
  {key} ({series_id}):
    - WebFetch url=https://api.bls.gov/publicAPI/v2/timeseries/data/{series_id}?startyear=<bls_start_year>&endyear=<bls_end_year>
      -> save to raw/{key}_bls.json""")
bls_table = "".join(bls_lines)

TEMPLATE = f'''Daily task: refresh the "Raw Materials & Commodities Index" hosted artifact with today's commodity prices. You start with an empty sandbox and no memory of previous runs — this prompt is fully self-contained. Follow these steps exactly, in order.

ARTIFACT_URL = {ARTIFACT_URL}

BACKGROUND — why this run uses WebFetch instead of Python `requests` for data fetching:
This sandbox's outbound network proxy only allows a small allowlist of hosts (confirmed via diagnostic: only api.github.com reachable; Yahoo Finance, BLS, and every other external host tested returned "Tunnel connection failed: 403 Forbidden"). The WebFetch tool runs on Anthropic's own infrastructure, not through this sandbox's local network, so it reaches these sources fine. Do NOT attempt to fetch Yahoo Finance or BLS URLs with Python `requests`/`urllib`/`curl` from within this sandbox — it will fail. Use the WebFetch tool for every external data fetch in this routine.

STEP 1 — Read back the accumulated daily history.
Call the WebFetch tool with url=ARTIFACT_URL and this exact prompt: "Find the <script type=\\"application/json\\" id=\\"history-data\\"> tag in this page's HTML source and return its exact, complete, verbatim text content (the raw JSON string inside that script tag), with no summarization, paraphrasing, or truncation. Output ONLY that raw JSON text and nothing else."
Take the JSON text returned and write it verbatim to a local file named `history.json` in your working directory. If WebFetch fails or the tag can't be found, write `{{"snapshots": []}}` to history.json instead and continue (don't fail the whole run over this — it just means today's snapshot becomes the new starting point for the sparkline; YTD/YoY badges are unaffected since those are always pulled fresh from each source's own history, not from this file).

STEP 2 — Compute today's date windows (no network).
Write compute_windows.py with EXACTLY this content (copy verbatim, do not modify the logic):

```python
{windows_src}```

Run it: `python3 compute_windows.py`. This writes `windows.json` with the numeric period1/period2 boundaries you'll need for the YTD and YoY WebFetch calls below (a small window near the start of this year, and a small window near ~365 days ago), plus the BLS start/end year. Read windows.json after running it so you have `ytd_period1`, `ytd_period2`, `yoy_period1`, `yoy_period2`, `bls_start_year`, `bls_end_year` available for STEP 3.

STEP 3 — Fetch each data point individually via WebFetch, and save the raw response.
For every call below, use this exact extraction prompt: "{EXTRACT_PROMPT}"

Create a `raw/` subdirectory and save each result to the exact filename shown, substituting the real numeric values from windows.json for the <ytd_period1>/<ytd_period2>/<yoy_period1>/<yoy_period2>/<bls_start_year>/<bls_end_year> placeholders in the URLs below. This is 18 Yahoo calls (3 per ticker x 6 tickers) + 2 BLS calls = 20 WebFetch calls total.

IMPORTANT — pace these calls, don't fire them in a rapid burst: run `sleep 6` (via Bash) between each WebFetch call in this step (so roughly 6 seconds between every one of the 20 calls). A prior run sent all 20 back-to-back with no pacing and every single one came back "HTTP 403 Forbidden" — almost certainly Yahoo/BLS's anti-bot rate limiting reacting to the burst pattern, since manual one-off calls to these same URLs succeed fine. Spacing them out is cheap insurance against that. Don't skip the sleep to save time.

Yahoo Finance (metals/energy/freight), key (ticker):{yahoo_table}

BLS PPI (resins, monthly), key (series id):{bls_table}

If any individual WebFetch call fails, times out, or doesn't return valid JSON, write `{{"error": "<brief description>"}}` to that specific raw file and move on to the next one — do NOT abort the whole run over one failed call. Each commodity's assembly step (STEP 4) handles missing/error raw files gracefully on its own.

STEP 4 — Assemble today's snapshot from the raw files (no network).
Write assemble.py with EXACTLY this content (copy verbatim, do not modify the logic):

```python
{assemble_src}```

Run it: `python3 assemble.py`. This reads windows.json, every raw/*.json file from STEP 3, and history.json (from STEP 1), then produces today's snapshot and merges it into history.json (removing any existing entry for today's date first, so re-runs are safe) — identical schema to before, so STEP 5 needs no changes.

STEP 5 — Write build_dashboard.py with EXACTLY this content (copy verbatim, do not modify the logic):

```python
{build_src}```

Then run it: `python3 build_dashboard.py`. This produces `dashboard.html` in your working directory, with Day/YTD/YoY comparison badges per commodity, per group, and for the overall composite, plus the full updated history re-embedded for tomorrow's run.

STEP 6 — Republish the artifact in place.
Call the Artifact tool with:
- file_path = the local path to dashboard.html you just built
- url = {ARTIFACT_URL}  (this MUST be set so it updates the existing page instead of minting a new URL)
- favicon = 📈
- description = "Daily-refreshed index of raw material and commodity prices (metals, energy, freight, resins) with day, YTD, and year-over-year comparisons"
- label = today's date, e.g. "2026-07-21 refresh"

STEP 6.5 — Verify the publish actually landed, and alert on any failure.
Re-fetch ARTIFACT_URL with WebFetch (same prompt as STEP 1: extract the raw `history-data` JSON verbatim). Parse it and confirm:
(a) the fetch succeeded and returned valid JSON,
(b) the last snapshot's `fetched_at` date (UTC, first 10 chars) equals today's UTC date, and
(c) at least half of the commodities in that snapshot do NOT have an `"error"` key (i.e. this wasn't a run where every single source failed).
If ANY of (a)/(b)/(c) fail, OR if STEP 2-5's scripts or STEP 6's Artifact publish raised an exception/error at any point, treat this run as FAILED. In that case, call the PushNotification tool with status="proactive" and a message under 200 characters stating what failed, e.g. "Commodities index: today's refresh failed at Yahoo fetch step, dashboard not updated — check {ARTIFACT_URL}" or "Commodities index: artifact republish didn't verify — today's snapshot missing from live page." Be specific about which step failed so it's actionable. Note: per STEP 5's build_dashboard.py, a source outage no longer blanks the whole dashboard (it falls back to the last good value per commodity, marked as stale) — the PushNotification is still required on this condition because a fallback masks the outage visually but someone still needs to know the data is stale and why.
If everything verified successfully, do NOT call PushNotification — a notification on every successful daily run would just be noise. Silence on success is correct.

STEP 7 — Report back briefly (as your final text output): today's composite Day/YTD/YoY % changes, how many of the 8 commodities fetched cleanly vs fell back to stale data, and confirm the artifact URL was updated successfully (not a new URL) and that STEP 6.5 verification passed. If STEP 6.5 failed and you already sent a PushNotification, say so here too.

Notes:
- This index tracks: Copper, Aluminum, Steel (HRC), Crude Oil (WTI), Natural Gas, and a dry-bulk shipping ETF (BDRY, proxy for the Baltic Dry Index) daily via Yahoo Finance; plus two BLS Producer Price Index series for plastics resins (WPU066, WPU0662) which only update monthly — most days these two will show an unchanged "Mo" badge, that's expected, not a bug.
- Don't invent, estimate, or hallucinate any price/index/YTD/YoY values. If a specific WebFetch call fails after being attempted once, record the error in that raw file per STEP 3 and move on — assemble.py and build_dashboard.py already handle turning that into a graceful stale-data fallback rather than a guessed number.
- Do not modify the Python script logic in compute_windows.py, assemble.py, or build_dashboard.py — copy each verbatim. They already handle windowing, parsing, rounding, duplicate-day de-duplication, correct YTD/YoY baseline lookups, and stale-data fallback.
- Each WebFetch call in STEP 3 should be small and fast (each response is a handful of data points, not a bulk historical dump) — this is deliberate, so responses stay well under any size where WebFetch might summarize/truncate them. Do not "optimize" by requesting a larger date range in one call instead of the three separate small windows.
- Failure notifications (STEP 6.5) are the only way anyone finds out a daily run silently didn't get fresh data — don't skip that verification step, and don't suppress a warranted PushNotification just because the dashboard "looks fine" thanks to the fallback.
'''

out_path = os.path.join(HERE, "routine_prompt.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(TEMPLATE)
print(f"Wrote {out_path}, {len(TEMPLATE)} chars")
