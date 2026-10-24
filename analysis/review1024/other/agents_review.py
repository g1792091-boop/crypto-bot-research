#!/usr/bin/env python3
"""Agent rooms (agents3.db), debate room (debate.db), owners' inbox (inbox.db), live analysis team (liveteam.db) and the
Telegram send counter (tgsends.db): what the AI staff claimed and how the claims scored, how much they ran, and whether
they still run. Also the market drift of the forward windows (from shadow200.db 1h bars: prices only).

    python3 agents_review.py --db-root <extract>/db/paperbot --out <folder>

Read-only. Message texts are summarised, not copied in bulk.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_other as LO  # noqa: E402


def binom_p_ge(k, n, p=0.5):
    from math import comb
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def agents(root, out):
    c = LO.ro(os.path.join(root, "agents3.db"))
    print("==== AGENT ROOMS (agents3.db)")
    print("rooms:", dict(Counter(r[0] for r in c.execute("SELECT kind FROM rooms"))))
    rs = defaultdict(Counter)
    for st, ts in c.execute("SELECT status, started_ts FROM rounds"):
        rs[LO.kst_day(ts)][st] += 1
    print("rounds by day:", {d: dict(v) for d, v in sorted(rs.items())})
    calls = c.execute("SELECT count(*), sum(tokens), min(day), max(day) FROM agent_calls").fetchone()
    print("AI calls:", calls, dict(Counter(r[0] for r in c.execute("SELECT model FROM agent_calls"))))
    last = {}
    for tid, ts, st, res in c.execute("SELECT trial_id, ts, status, result FROM trial_results ORDER BY ts"):
        last[tid] = (st, json.loads(res) if res else {})
    kinds = dict(c.execute("SELECT id, kind FROM trials").fetchall())
    rows = []
    for tid, kind in sorted(kinds.items()):
        st, r = last.get(tid, ("open", {}))
        spec = json.loads(c.execute("SELECT spec FROM trials WHERE id=?", (tid,)).fetchone()[0])
        typ = kind
        if kind == "hypothesis" and r.get("prediction"):
            p = r["prediction"]
            typ = ("패턴(손실 특징)" if p["metric"] == "loss_tag_share" else
                   ("나빠진다(운 되돌림)" if p["direction"] == "below" else "좋아진다/버틴다"))
        rows.append(dict(source="agents3", id=tid, kind=kind, type=typ, status=st, correct=r.get("correct"),
                         metric=(r.get("prediction") or {}).get("metric"), value=r.get("value"), n=r.get("n"),
                         by=r.get("by"), text=(spec.get("text") or json.dumps(spec.get("entry") or spec.get("template") or ""))[:160]))
    sc = Counter((r["type"], r["correct"]) for r in rows if r["status"] == "graded")
    print("hypothesis scorecard:", dict(sc))
    print("newlab / test trials:", dict(Counter((r["kind"], r["status"]) for r in rows if r["kind"] != "hypothesis")))
    com = c.execute("SELECT ts, symbol, direction, ref_price, end_price, move, correct FROM committee_calls ORDER BY ts").fetchall()
    ok = sum(1 for x in com if x[6])
    print(f"committee direction calls (24 h): {len(com)}, correct {ok} ({ok / len(com) * 100:.0f}%), "
          f"P(>= {ok} by coin flip) = {binom_p_ge(ok, len(com)):.2f}")
    for x in com:
        rows.append(dict(source="committee", id=LO.kst(x[0]), kind="direction_24h", type=x[2], status="graded",
                         correct=bool(x[6]), metric="move", value=x[5], n=1, by=x[1], text=""))
    fails = Counter(t[:40] for (t,) in c.execute("SELECT text FROM messages WHERE kind='system' AND text LIKE 'AI를 부르지 못해%'"))
    lastok = c.execute("SELECT max(started_ts) FROM rounds WHERE status='done'").fetchone()[0]
    print("rounds failing with 'AI를 부르지 못해':", sum(fails.values()), "| last successful round:", LO.kst(lastok))
    return rows


def debate(root, out):
    c = LO.ro(os.path.join(root, "debate", "debate.db"))
    print("\n==== DEBATE ROOM (debate.db)")
    n, tin, tout, lo, hi = c.execute("SELECT count(*), sum(in_tokens), sum(out_tokens), min(ts), max(ts) FROM debate_rounds").fetchone()
    st = dict(c.execute("SELECT k, v FROM debate_state").fetchall())
    spend = sum(float(v) for k, v in st.items() if k.startswith("spend:day:"))
    print(f"rounds {n} ({LO.kst(lo)} ~ {LO.kst(hi)}), tokens in {tin:,} out {tout:,}, spend recorded ${spend:.2f} "
          f"(month {st.get('spend:month:2026-10')}), model {json.loads(st.get('run', '{}')).get('model')}")
    print("hypotheses:", dict(Counter(r[0] for r in c.execute("SELECT status FROM debate_hypotheses"))),
          "dropped because:", dict(Counter(r[0] for r in c.execute("SELECT outcome FROM debate_hypotheses WHERE status='dropped'"))))
    g = defaultdict(Counter)
    rows = []
    for hid, ts, kind, params, outcome in c.execute("SELECT id, ts, kind, params_json, outcome FROM debate_hypotheses WHERE status='graded'"):
        hit = outcome.split()[0] == "hit"
        g[kind][hit] += 1
        rows.append(dict(source="debate", id=hid, kind=kind, type=kind, status="graded", correct=hit, metric=kind,
                         value=None, n=None, by="", text=params[:160]))
    for kind, v in g.items():
        k, n2 = v[True], v[True] + v[False]
        print(f"  {kind}: {k}/{n2} hit, P(>= {k} by coin flip) = {binom_p_ge(k, n2):.2f}")
    print("open:", dict(Counter(r[0] for r in c.execute("SELECT kind FROM debate_hypotheses WHERE status='open'"))))
    ideas = Counter(r[0] for r in c.execute("SELECT status FROM debate_ideas"))
    tags = Counter(r[0] for r in c.execute("SELECT tag FROM debate_ideas")).most_common(8)
    print("ideas:", dict(ideas), "top tags:", tags)
    return rows


def misc(root):
    print("\n==== INBOX / LIVE TEAM / TELEGRAM COUNTER")
    i = LO.ro(os.path.join(root, "inbox.db"))
    print("owner messages:", i.execute("SELECT count(*), min(ts), max(ts) FROM owner_messages").fetchone(),
          "proposals approved/rejected:", i.execute("SELECT count(*) FROM approvals").fetchone()[0],
          "price alerts:", i.execute("SELECT count(*) FROM price_alerts").fetchone()[0])
    lt = LO.ro(os.path.join(root, "liveteam.db"))
    print("liveteam meetings:", lt.execute("SELECT kind, key, title FROM meetings").fetchall(),
          "messages:", lt.execute("SELECT count(*) FROM messages").fetchone()[0], "ideas:", lt.execute("SELECT count(*) FROM ideas").fetchone()[0])
    t = LO.ro(os.path.join(root, "tgsends.db"))
    print("telegram sends by level:", t.execute("SELECT kind, sum(n), min(day), max(day) FROM tg_sends GROUP BY kind").fetchall())


def drift(root):
    """Price change of the 6 coins over the forward windows (1h closes from shadow200.db; prices only)."""
    c = LO.ro(os.path.join(root, "shadow200", "shadow200.db"))
    wins = {"규칙봇·그림자 10/05~10/23": (1791158400000, 1792800000000),
            "데모봇 10/09 18:45~10/13 14:17": (1791539100000, 1791868646567),
            "실거래 10/19 13:41~10/24 23:25": (1792384904087, 1792851947855)}
    out = {}
    for name, (a, b) in wins.items():
        ch = {}
        for coin in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"):
            x = c.execute("SELECT open FROM bars WHERE coin=? AND tf='1h' AND open_ms>=? ORDER BY open_ms LIMIT 1", (coin, a)).fetchone()
            y = c.execute("SELECT close FROM bars WHERE coin=? AND tf='1h' AND open_ms<=? ORDER BY open_ms DESC LIMIT 1", (coin, b)).fetchone()
            if x and y:
                ch[coin[:-3]] = (y[0] / x[0] - 1) * 100
        out[name] = ch
        print(f"{name}: " + ", ".join(f"{k} {v:+.1f}%" for k, v in ch.items()) + f" | mean {np.mean(list(ch.values())):+.1f}%")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rows = agents(a.db_root, a.out) + debate(a.db_root, a.out)
    misc(a.db_root)
    print("\n==== MARKET DRIFT")
    drift(a.db_root)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(a.out, "agents_scorecard.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
