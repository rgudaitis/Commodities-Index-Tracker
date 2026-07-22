import os

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_URL = "https://claude.ai/code/artifact/c01e2adb-9419-412c-932d-c9b2e917012a"

with open(os.path.join(HERE, "fetch_data.py"), encoding="utf-8") as f:
    fetch_src = f.read()
with open(os.path.join(HERE, "build_dashboard.py"), encoding="utf-8") as f:
    build_src = f.read()

TEMPLATE = f'''Daily task: refresh the "Raw Materials & Commodities Index" hosted artifact with today's commodity prices. You start with an empty sandbox and no memory of previous runs — this prompt is fully self-contained. Follow these steps exactly, in order.

ARTIFACT_URL = {ARTIFACT_URL}

STEP 1 — Read back the accumulated daily history.
Call the WebFetch tool with url=ARTIFACT_URL and this exact prompt: "Find the <script type=\\"application/json\\" id=\\"history-data\\"> tag in this page's HTML source and return its exact, complete, verbatim text content (the raw JSON string inside that script tag), with no summarization, paraphrasing, or truncation. Output ONLY that raw JSON text and nothing else."
Take the JSON text returned and write it verbatim to a local file named `history.json` in your working directory. If WebFetch fails or the tag can't be found, write `{{"snapshots": []}}` to history.json instead and continue (don't fail the whole run over this — it just means today's snapshot becomes the new starting point for the sparkline; YTD/YoY badges are unaffected since those are always pulled fresh from each source's own history, not from this file).

STEP 2 — Write fetch_data.py with EXACTLY this content (copy verbatim, do not modify the logic):

```python
{fetch_src}```

Then run it: `python3 fetch_data.py`. This reads history.json (from Step 1), appends today's snapshot (removing any existing entry for today's date first, so re-runs are safe), and overwrites history.json. Each commodity gets its current value plus prev (day/month), ytd_base, and yoy_base — all fetched fresh from Yahoo Finance (2 years of daily history) and BLS (2 years of monthly PPI), not derived from our own accumulated tracking.

If `requests` is not installed, run `pip install requests` first, then retry.

STEP 3 — Write build_dashboard.py with EXACTLY this content (copy verbatim, do not modify the logic):

```python
{build_src}```

Then run it: `python3 build_dashboard.py`. This produces `dashboard.html` in your working directory, with Day/YTD/YoY comparison badges per commodity, per group, and for the overall composite, plus the full updated history re-embedded for tomorrow's run.

STEP 4 — Republish the artifact in place.
Call the Artifact tool with:
- file_path = the local path to dashboard.html you just built
- url = {ARTIFACT_URL}  (this MUST be set so it updates the existing page instead of minting a new URL)
- favicon = 📈
- description = "Daily-refreshed index of raw material and commodity prices (metals, energy, freight, resins) with day, YTD, and year-over-year comparisons"
- label = today's date, e.g. "2026-07-21 refresh"

STEP 4.5 — Verify the publish actually landed, and alert on any failure.
Re-fetch ARTIFACT_URL with WebFetch (same prompt as STEP 1: extract the raw `history-data` JSON verbatim). Parse it and confirm:
(a) the fetch succeeded and returned valid JSON,
(b) the last snapshot's `fetched_at` date (UTC, first 10 chars) equals today's UTC date, and
(c) at least half of the commodities in that snapshot do NOT have an `"error"` key (i.e. this wasn't a run where every single source failed).
If ANY of (a)/(b)/(c) fail, OR if STEP 2's fetch_data.py, STEP 3's build_dashboard.py, or STEP 4's Artifact publish raised an exception/error at any point, treat this run as FAILED. In that case, call the PushNotification tool with status="proactive" and a message under 200 characters stating what failed, e.g. "Commodities index: today's refresh failed at Yahoo fetch step, dashboard not updated — check {ARTIFACT_URL}" or "Commodities index: artifact republish didn't verify — today's snapshot missing from live page." Be specific about which step failed so it's actionable. Note: per STEP 3's build_dashboard.py, a source outage no longer blanks the whole dashboard (it falls back to the last good value per commodity, marked as stale) — the PushNotification is still required on this condition because a fallback masks the outage visually but someone still needs to know the data is stale and why.
If everything verified successfully, do NOT call PushNotification — a notification on every successful daily run would just be noise. Silence on success is correct.

STEP 5 — Report back briefly (as your final text output): today's composite Day/YTD/YoY % changes, and confirm the artifact URL was updated successfully (not a new URL) and that STEP 4.5 verification passed. If STEP 4.5 failed and you already sent a PushNotification, say so here too.

Notes:
- This index tracks: Copper, Aluminum, Steel (HRC), Crude Oil (WTI), Natural Gas, and a dry-bulk shipping ETF (BDRY, proxy for the Baltic Dry Index) daily via Yahoo Finance; plus two BLS Producer Price Index series for plastics resins (WPU066, WPU0662) which only update monthly — most days these two will show an unchanged "Mo" badge, that's expected, not a bug.
- Don't invent, estimate, or hallucinate any price/index/YTD/YoY values. If a specific source fails after retries, leave that commodity's error field as returned by the script — build_dashboard.py will fall back to the last known-good value for display and mark it stale rather than guessing a number.
- Do not modify the Python script logic — copy it verbatim. The scripts already handle retries, rounding, duplicate-day de-duplication, correct YTD/YoY baseline lookups, and stale-data fallback.
- Failure notifications (STEP 4.5) are the only way anyone finds out a daily run silently didn't get fresh data — don't skip that verification step, and don't suppress a warranted PushNotification just because the dashboard "looks fine" thanks to the fallback.
'''

out_path = os.path.join(HERE, "routine_prompt.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(TEMPLATE)
print(f"Wrote {out_path}, {len(TEMPLATE)} chars")
