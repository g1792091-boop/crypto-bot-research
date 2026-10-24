"""Verifier: the trend bot's real paper trades (combo/live-ac.db, read-only immutable) and the wait shadow.
Usage: python3 ta_paperdb.py <live-ac.db> <shadow-trend-wait.db>"""
import sys, sqlite3
import pandas as pd
for p in sys.argv[1:3]:
    con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
    tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    print(p.split("/")[-1], tabs)
    if "trades" in tabs:
        cols = [r[1] for r in con.execute("pragma table_info(trades)")]
        print(cols)
        T = pd.read_sql("select * from trades", con)
        pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
        keep = [c for c in T.columns if any(s in c for s in ("id", "symbol", "side", "strategy", "member", "entry", "exit", "roe", "pnl", "lev", "reason", "tf", "account", "acct", "time", "open"))]
        print(T[keep].tail(30).to_string())
