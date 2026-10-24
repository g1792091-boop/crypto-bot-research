"""Forward sample sizes per rule-bot account (strategy@tf) for the role map: signals in signal_log.csv and closed trades in
trades.csv of the rule bot export's current/ folder (paper v4, since 2026-10-05), plus the trend bot's members
(combo live-ac.db signal_log, read only) by status. Counts only, no outcome.

    python3 forward_counts.py <rule current dir> <live-ac.db> <out csv>"""
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict

csv.field_size_limit(10 ** 9)


def main(cur, db, out):
    sig = Counter()
    first = {}
    for r in csv.DictReader(open(f"{cur}/signal_log.csv")):
        k = f"{r['strategy']}@{r['timeframe']}"
        sig[k] += 1
        first[k] = min(first.get(k, 10 ** 15), int(r["bar_close"]))
    tr = Counter()
    trn = defaultdict(float)
    for r in csv.DictReader(open(f"{cur}/trades.csv")):
        tr[r["account_id"]] += 1
    acc = {}
    for r in csv.DictReader(open(f"{cur}/accounts.csv")):
        d = json.loads(r["data"]) if r["data"] else {}
        acc[r["account_id"]] = (r["strategy"], r["timeframe"], r["kind"], d.get("group"))
    rows = []
    for aid, (st, tf, kind, grp) in sorted(acc.items()):
        rows.append({"account_id": aid, "strategy": st, "tf": tf, "kind": kind, "group": grp,
                     "fwd_signals": sig.get(f"{st}@{tf}", 0), "fwd_trades": tr.get(aid, 0)})
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tb = defaultdict(Counter)
    for tf, st, status in con.execute("select timeframe, strategy, status from signal_log"):
        base = st.split("#")[0]
        tb[base][status] += 1
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    json.dump({k: dict(v) for k, v in tb.items()}, open(out.replace(".csv", "_trendbot.json"), "w"), indent=1, sort_keys=True)
    print(len(rows), "accounts;", sum(tr.values()), "trades;", sum(sig.values()), "signals")


if __name__ == "__main__":
    main(*sys.argv[1:4])
