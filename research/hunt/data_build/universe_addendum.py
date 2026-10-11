#!/usr/bin/env python3
"""Append a coverage addendum (from manifest.json) to UNIVERSE.md. Coverage only; no trading outcomes."""
import json, os, time, calendar
OUT = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/coins30"
p = os.path.join(OUT, "UNIVERSE.md")
txt = open(p).read()
mark = "\n## Coverage addendum (written after the download"
if mark in txt:
    txt = txt[: txt.index(mark)]
m = json.load(open(os.path.join(OUT, "manifest.json")))
S = m["symbols"]
def t(s): return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))
L = [mark.strip("\n") + "; the list above was not changed)", ""]
L.append(f"Written {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC. Source: manifest.json. "
         "\"Traded until\" is the last 5m bar with volume > 0; after it the archive may hold flat zero-volume bars.")
L.append("")
L.append("| symbol | first bar | traded until | archive ends | flat tail (days) | funding rows after trading stopped |")
L.append("|---|---|---|---|---:|---:|")
for r in S:
    if r["traded_to_range_end"]:
        continue
    L.append(f"| {r['symbol']} | {r['first_bar']} | {r['last_nonzero_volume_bar']} | {r['last_bar']} | "
             f"{r['trailing_zero_volume_days']} | {r['funding_rows_after_last_traded_bar']} |")
live_end = [r["symbol"] for r in S if r["traded_to_range_end"]]
L.append("")
L.append(f"The other {len(live_end)} coins trade through 2026-09-30 23:55.")
L.append("")
L.append("Coins with real trading on each date (first bar <= date <= traded until):")
L.append("")
L.append("| date | coins |")
L.append("|---|---:|")
for d in ["2020-01-01", "2020-07-01", "2021-01-01", "2021-07-01", "2022-01-01", "2023-01-01", "2024-01-01",
          "2025-01-01", "2026-01-01", "2026-09-30"]:
    x = calendar.timegm(time.strptime(d + " 12:00", "%Y-%m-%d %H:%M"))
    n = sum(1 for r in S if t(r["first_bar"]) <= x <= t(r["last_nonzero_volume_bar"]))
    L.append(f"| {d} | {n} |")
L.append("")
L.append("Whole days missing from the monthly archives were filled from the daily archives (checksums verified); "
         "after that no coin has a missing 5m bar inside its span, and at most 15 bars per coin lack a mark price while trading. "
         "No funding gap over 8h while trading.")
open(p, "w").write(txt.rstrip("\n") + "\n" + "\n".join(L) + "\n")
print("\n".join(L))
