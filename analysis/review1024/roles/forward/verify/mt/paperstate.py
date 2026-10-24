"""Read-only: state keys and open positions in the trend bot paper DB (untrusted data). Prints only position-like fields."""
import sqlite3, sys, json
p = sys.argv[1]
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
cur = con.cursor()
for k, ts, d in cur.execute("select k, ts, data from state"):
    s = d if isinstance(d, str) else str(d)
    try:
        j = json.loads(s)
    except Exception:
        j = None
    if isinstance(j, dict):
        print(k, ts, list(j.keys())[:30])
        for kk in ("positions", "open", "position", "pos"):
            if kk in j:
                print("  ", kk, json.dumps(j[kk])[:1500])
    else:
        print(k, ts, s[:200])
print(cur.execute("select max(ts) from equity").fetchone(), cur.execute("select max(bar_close) from signal_log").fetchone())
