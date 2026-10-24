"""Read-only look at the trend bot paper DB (untrusted data): tables, trades since the 10-22 design."""
import sqlite3, sys
p = sys.argv[1]
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
cur = con.cursor()
tabs = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
print(tabs)
for t in tabs:
    cols = [r[1] for r in cur.execute(f"pragma table_info('{t}')")]
    n = cur.execute(f"select count(*) from '{t}'").fetchone()[0]
    print(t, n, cols[:40])
