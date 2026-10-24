"""Paper vs live fills of the trend bot (since its first start 10-21 23:28 KST): the paper account COMBO@mix in live-ac.db
and the two live executors (Bybit, WOO X Pro), matched by the executor's trade key (COMBO@mix|SYMBOL|paper entry ms).
Run: python3 lb_exec.py <live-ac.db> <executor-bybit-live.db> <executor-wooxpro-live.db>   (all opened read-only)"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

KST = 9 * 3600_000
START = 1792591200000          # 2026-10-21 23:00 KST (first trend-bot signal; the bot started 23:28 and replayed from 23:00)
D1022 = 1792681200000          # 2026-10-23 00:00 KST (the 10-22 design)


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def main(paper_db, bybit_db, woo_db):
    c = ro(paper_db)
    P = pd.DataFrame([dict(json.loads(d), id=i) for i, d in
                      c.execute("select id, data from trades where account_id='COMBO@mix' and entry_time >= ?", (START,))])
    P["eq_before"] = P.equity_after - P.pnl
    P["paper_pct"] = 100 * P.pnl / P.eq_before
    P["key"] = "COMBO@mix|" + P.symbol + "|" + P.entry_time.astype(str)
    out = []
    for name, db in (("bybit", bybit_db), ("woo", woo_db)):
        e = ro(db)
        X = pd.DataFrame(e.execute("select key, symbol, side, qty, leverage, entry_ts, entry_price, exit_ts, exit_reason, pnl, data "
                                   "from trades").fetchall(),
                         columns=["key", "symbol", "side", "qty", "lev", "entry_ts", "entry_price", "exit_ts", "exit_reason", "pnl", "data"])
        X["wallet_before"] = [json.loads(d).get("wallet_before") for d in X.data]
        M = P.merge(X.drop(columns=["data"]), on="key", how="left", suffixes=("", "_x"))
        for _, r in M.iterrows():
            took = pd.notna(r.entry_ts)
            out.append({"exchange": name, "design": "10-22" if r.entry_time >= D1022 else "10-21",
                        "entry_kst": pd.to_datetime(r.entry_time + KST, unit="ms"), "symbol": r.symbol,
                        "member": f"{r.strategy_id}@{r.timeframe}", "side": int(r.side), "paper_exit": r.exit_reason,
                        "paper_roe": r.roe, "paper_pct_of_equity": r.paper_pct, "taken_live": took,
                        "live_pct_of_wallet": 100 * r.pnl_x / r.wallet_before if took else np.nan,
                        "entry_delay_s": (r.entry_ts - r.entry_time) / 1000 if took else np.nan,
                        "entry_bp_vs_paper": (1e4 * r.side * (r.entry_price_x / r.entry_price - 1)) if took else np.nan,
                        "live_exit": r.exit_reason_x if took else ""})
    O = pd.DataFrame(out)
    O.to_csv("exec_vs_paper.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250)
    print(O.to_string())
    T = O[O.taken_live]
    print(T.groupby("exchange").agg(n=("paper_pct_of_equity", "size"), paper=("paper_pct_of_equity", "sum"),
                                    live=("live_pct_of_wallet", "sum"), bp=("entry_bp_vs_paper", "mean"),
                                    delay=("entry_delay_s", "mean")))
    for name, db in (("bybit", bybit_db), ("woo", woo_db)):
        e = ro(db)
        a = e.execute("select equity from equity where ts >= ? order by ts limit 1", (START,)).fetchone()
        b = e.execute("select equity from equity order by ts desc limit 1").fetchone()
        print(name, "wallet at the trend bot's start", a, "-> at export", b)


if __name__ == "__main__":
    main(*sys.argv[1:4])
