"""Read-only: open position fields of each engine in the 'accounts' state row, and combo trend_since/design."""
import sqlite3, sys, json
p = sys.argv[1]
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
cur = con.cursor()
d = json.loads(cur.execute("select data from state where k='accounts'").fetchone()[0])
for name, e in d["engines"].items():
    if isinstance(e, dict):
        print(name, list(e.keys())[:30])
        for kk in ("position", "pos", "open", "positions"):
            if kk in e:
                print("  ", kk, json.dumps(e[kk])[:800])
c = json.loads(cur.execute("select data from state where k='combo'").fetchone()[0])
print("trend_since", c.get("trend_since"), "trend_design", c.get("trend_design"))
