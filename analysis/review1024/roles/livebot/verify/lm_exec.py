"""Independent paper-vs-live fill read for the trend bot (read-only sqlite). Matches by (symbol, side, entry within 5 min)
instead of the executor key, to check exec_vs_paper.csv. Run: python3 lm_exec.py <live-ac.db> <bybit.db> <woo.db>"""
import json
import sqlite3
import sys

import numpy as np

START = 1792591200000          # 2026-10-21 23:00 KST


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


paper, bybit, woo = sys.argv[1:4]
c = ro(paper)
P = [json.loads(d) for (d,) in c.execute("select data from trades where account_id='COMBO@mix' and entry_time >= ?",
                                          (START,))]
print("paper trades since start:", len(P))
for p in P:
    print(" paper", p["symbol"], p["side"], p["entry_time"], round(p["entry_price"], 6), p["exit_reason"], round(p["roe"], 4),
          "lev", p.get("leverage"), "pct_eq %.3f" % (100 * p["pnl"] / (p["equity_after"] - p["pnl"])))
for name, db in (("bybit", bybit), ("woo", woo)):
    e = ro(db)
    cols = [r[1] for r in e.execute("pragma table_info(trades)")]
    rows = e.execute("select symbol, side, entry_ts, entry_price, exit_ts, exit_ts, pnl, leverage, qty, data from trades "
                     "where entry_ts >= ?", (START,)).fetchall()
    print(name, "live trades since start:", len(rows))
    bps, delays, live_pct, paper_pct, roe_gap = [], [], [], [], []
    for sym, side, ets, ep, xts, xp, pnl, lev, qty, d in rows:
        dd = json.loads(d) if d else {}
        wb = dd.get("wallet_before")
        sd = 1 if str(side).lower() in ("1", "long", "buy") else -1
        m = [p for p in P if p["symbol"] == sym and abs(ets - p["entry_time"]) < 300_000]
        if not m:
            print("  unmatched", sym, side, ets); continue
        p = m[0]
        bp = 1e4 * p["side"] * (ep / p["entry_price"] - 1)
        notional_margin = qty * ep / lev if lev else np.nan
        live_roe = pnl / notional_margin if notional_margin else np.nan
        bps.append(bp); delays.append((ets - p["entry_time"]) / 1000)
        live_pct.append(100 * pnl / wb if wb else np.nan)
        paper_pct.append(100 * p["pnl"] / (p["equity_after"] - p["pnl"]))
        roe_gap.append(100 * (p["roe"] - live_roe))
        print("  %s side %s paper %+.4f live_roe %+.4f bp %.2f delay %.0fs lev %s margin/wallet %.2f" %
              (sym, side, p["roe"], live_roe, bp, (ets - p["entry_time"]) / 1000, lev,
               notional_margin / wb if wb else np.nan))
    print(name, "n=%d bp mean %.2f median %.2f, delay %.1f, paper %.2f%% eq, live %.2f%% wallet, ROE gap/trade %.2f pts"
          % (len(bps), np.mean(bps), np.median(bps), np.mean(delays), np.sum(paper_pct), np.nansum(live_pct),
             np.mean(roe_gap)))
    b = np.array(bps)
    if len(b) > 1:
        se = b.std(ddof=1) / np.sqrt(len(b))
        print(name, "bp 95%% t-interval (df=%d): %.1f .. %.1f" % (len(b) - 1, b.mean() - 4.303 * se, b.mean() + 4.303 * se))
