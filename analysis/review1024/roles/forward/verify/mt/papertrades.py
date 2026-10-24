"""Read-only: every trade in the trend bot paper DB (untrusted data), with design tag from data JSON if present."""
import sqlite3, sys, json, datetime as dt
p = sys.argv[1]
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
cur = con.cursor()
print(cur.execute("select account_id, strategy, timeframe, kind, created_ts, settings_version, parent from accounts").fetchall())
rows = cur.execute("select id, account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, data from trades order by entry_time").fetchall()
def ts(x):
    try:
        x = float(x)
        if x > 1e12: x /= 1000
        return (dt.datetime.utcfromtimestamp(x) + dt.timedelta(hours=9)).strftime("%m-%d %H:%M KST")
    except Exception:
        return str(x)
for r in rows:
    d = {}
    try:
        d = json.loads(r[9]) if r[9] else {}
    except Exception:
        pass
    keys = {k: d.get(k) for k in ("design", "strategy", "timeframe", "side", "member", "kind", "twin", "net_roe", "roe_net", "fee", "fees") if k in d}
    print(r[0], r[1], r[2], ts(r[3]), ts(r[4]), r[5], r[6], round(r[7] or 0, 2), round(r[8] or 0, 4), keys)
print(sorted({k for r in rows for k in (json.loads(r[9]) if r[9] else {}).keys()}))
