"""Verifier: paper vs live fills of the trend bot (read-only sqlite; only the trades / equity tables, selected fields).
Recomputes entry bp, delay, % of equity, and the margin share used live vs paper (are the % comparable?), and the
exit-side gap. Run: python3 vlh_exec.py <live-ac.db> <bybit.db> <woo.db>"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

START = 1792591200000
KST = 9 * 3600_000


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


paper_db, by_db, woo_db = sys.argv[1:4]
c = ro(paper_db)
rows = []
for i, d, ent, ext, er, lev, pnl, roe in c.execute(
        "select id, data, entry_time, exit_time, exit_reason, leverage, pnl, roe from trades where account_id='COMBO@mix' and entry_time >= ?",
        (START,)):
    j = json.loads(d)
    rows.append(dict(id=i, entry_time=ent, exit_time=ext, exit_reason=er, lev=lev, pnl=pnl, roe=roe,
                     symbol=j.get("symbol"), side=j.get("side"), entry_price=j.get("entry_price"),
                     exit_price=j.get("exit_price"), qty=j.get("qty"), margin=j.get("margin"),
                     equity_after=j.get("equity_after"), strategy=j.get("strategy_id"), tf=j.get("timeframe")))
P = pd.DataFrame(rows)
P["eq_before"] = P.equity_after - P.pnl
P["paper_pct"] = 100 * P.pnl / P.eq_before
P["paper_margin_share"] = P.margin / P.eq_before if P.margin.notna().all() else np.nan
P["key"] = "COMBO@mix|" + P.symbol + "|" + P.entry_time.astype(str)
print(P[["entry_time", "symbol", "strategy", "tf", "side", "entry_price", "exit_price", "exit_reason", "roe", "paper_pct",
         "paper_margin_share", "lev"]].assign(entry_time=lambda x: pd.to_datetime(x.entry_time + KST, unit="ms")).to_string())
print("paper mean ROE of", len(P), "trades: %.2f%%" % (100 * P.roe.mean()))
for name, db in (("bybit", by_db), ("woo", woo_db)):
    e = ro(db)
    X = pd.DataFrame(e.execute("select key, side, qty, leverage, entry_ts, entry_price, exit_ts, exit_reason, pnl, data from trades").fetchall(),
                     columns=["key", "side", "qty", "lev", "entry_ts", "entry_price", "exit_ts", "exit_reason", "pnl", "data"])
    X["wallet_before"] = [json.loads(d).get("wallet_before") for d in X.data]
    X["exit_price"] = [json.loads(d).get("exit_price") for d in X.data]
    M = P.merge(X.drop(columns=["data"]), on="key", suffixes=("", "_x"))
    M["live_pct"] = 100 * M.pnl_x / M.wallet_before
    M["live_margin_share"] = M.qty_x * M.entry_price_x / M.lev_x / M.wallet_before if "qty_x" in M else np.nan
    M["entry_bp"] = 1e4 * M.side * (M.entry_price_x / M.entry_price - 1)
    M["exit_bp"] = 1e4 * M.side * (M.exit_price_x.astype(float) / M.exit_price - 1)   # + = live exit better
    M["delay_s"] = (M.entry_ts - M.entry_time) / 1000
    M["live_roe_on_margin"] = M.pnl_x / (M.qty_x * M.entry_price_x / M.lev_x)
    print(f"\n{name}: matched {len(M)}")
    print(M[["symbol", "side", "paper_pct", "live_pct", "paper_margin_share", "live_margin_share", "lev", "lev_x",
             "entry_bp", "exit_bp", "delay_s", "roe", "live_roe_on_margin", "exit_reason_x"]].round(4).to_string())
    print(f"sum paper %.2f  live %.2f  mean entry bp %.2f  median %.2f  mean delay %.1f s  mean ROE gap (paper-live) %.2f pts" % (
        M.paper_pct.sum(), M.live_pct.sum(), M.entry_bp.mean(), M.entry_bp.median(), M.delay_s.mean(),
        100 * (M.roe - M.live_roe_on_margin).mean()))
