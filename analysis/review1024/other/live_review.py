#!/usr/bin/env python3
"""The combined paper bots (combo/*.db) and the live executors (exec/*.db) from the 10/24 extra export, plus the
live watcher's records (livecheck.db): forward results, coin-twin comparison, real fills vs paper, missed entries,
costs, and the signals the bot skipped.

    python3 live_review.py --db-root <extract>/db/paperbot --out <folder>

Everything is read-only (sqlite mode=ro&immutable=1). No order, key or server is touched. Order ids and API request
parameters are never printed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_other as LO  # noqa: E402

# KST boundaries of the designs that wrote into combo/live-ac.db (docs/live15-start-ko.md, docs/trend-bot-ko.md,
# executor start lines "페이퍼 DB ...")
T_R15 = 1792490400000      # 10/20 19:00 KST: A+C combined -> 규칙봇 15 (-50 %)
T_TREND = 1792592880000    # 10/21 23:28 KST: 추세판단 봇 (10/21 design, then the 10/22 design)
SEGMENTS = {"live-ac": [("A+C 합본", 0, T_R15), ("규칙봇 15 (−50%)", T_R15, T_TREND), ("추세판단 봇", T_TREND, 1 << 62)]}
PAPERS = {"live-ac": "combo/live-ac.db", "live15-mexc": "combo/live15-mexc.db",
          "shadow-trend-wait": "combo/shadow-trend-wait.db", "staging-paper4": "staging/paper4.db"}
PAPER_NAME = {"live-ac": "live-ac (A+C → 규칙봇15 −50% → 추세판단 봇)", "live15-mexc": "규칙봇 15 −35% (MEXC/WOO X용)",
              "shadow-trend-wait": "추세판단 그림자: 되돌림 기다림", "staging-paper4": "v4 시험 설치(staging)"}
EXECS = {"bybit": "exec/executor-bybit-live.db", "mexc": "exec/executor-mexc-live.db",
         "wooxpro": "exec/executor-wooxpro-live.db"}


def paper_trades(path):
    c = LO.ro(path)
    out = []
    for (tid, acc, sym, et, xt, xr, lev, pnl, roe, eqa, data) in c.execute(
            "SELECT id, account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data "
            "FROM trades ORDER BY exit_time, id"):
        d = json.loads(data)
        out.append(dict(id=tid, account=acc, symbol=sym, entry=et, exit=xt, reason=xr, lev=lev, pnl=pnl, roe=roe,
                        eq_after=eqa, eq_before=eqa - pnl, side=d.get("side"), strategy=d.get("strategy_id"),
                        tf=d.get("timeframe"), entry_price=d.get("entry_price"), exit_price=d.get("exit_price"),
                        margin=d.get("margin"), fees=d.get("fees"), funding=d.get("funding")))
    eq = defaultdict(list)
    for acc, ts, e in c.execute("SELECT account_id, ts, equity FROM equity ORDER BY ts"):
        eq[acc].append((ts, e))
    return out, eq


def seg_of(name, t):
    for label, lo, hi in SEGMENTS.get(name, [("전체", 0, 1 << 62)]):
        if lo <= t < hi:
            return label
    return "?"


def paper_section(root, out_rows, daily, goal):
    print("\n==== PAPER BOTS")
    allp = {}
    for name, rel in PAPERS.items():
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            print(name, "missing")
            continue
        tr, eq = paper_trades(p)
        allp[name] = tr
        c = LO.ro(p)
        hb = c.execute("SELECT ts FROM state WHERE k='heartbeat'").fetchone()
        run = c.execute("SELECT ts FROM state WHERE k='run'").fetchone()
        print(f"\n{name}: {PAPER_NAME[name]} | run since {LO.kst(run[0]) if run else '?'} | last heartbeat {LO.kst(hb[0]) if hb else '?'} | trades {len(tr)}")
        accs = sorted({t["account"] for t in tr})
        if name == "staging-paper4":
            print(f"  accounts {c.execute('SELECT count(*) FROM accounts').fetchone()[0]}, trades {len(tr)} between "
                  f"{LO.kst(min(t['entry'] for t in tr))} and {LO.kst(max(t['exit'] for t in tr))}: a 3-hour install test, not a forward record")
            continue
        segs = ([s[0] for s in SEGMENTS[name]] + ["전체"]) if name in SEGMENTS else ["전체"]
        for acc in accs:
            for sg in segs:
                ts = [t for t in tr if t["account"] == acc and (sg == "전체" or seg_of(name, t["entry"]) == sg)]
                if not ts:
                    continue
                ts.sort(key=lambda t: (t["exit"], t["id"]))
                pnl = [t["pnl"] for t in ts]
                ret = [t["pnl"] / t["eq_before"] for t in ts]
                mid = ts[0]["exit"] + (ts[-1]["exit"] - ts[0]["exit"]) // 2
                m = LO.basic(pnl, ret, [t["side"] for t in ts], [t["exit"] for t in ts], mid)
                e = [x[1] for x in eq[acc]]
                days = max((ts[-1]["exit"] - ts[0]["entry"]) / 86400000, 1e-9)
                m.update(bot=name, account=acc, segment=sg, first=LO.kst(ts[0]["entry"]), last=LO.kst(ts[-1]["exit"]),
                         days=days, trades_per_day=len(ts) / days,
                         eq_start=ts[0]["eq_before"], eq_end=ts[-1]["eq_after"],
                         max_dd_curve=LO.max_dd(e) if sg == "전체" else float("nan"),
                         lock=sum(t["reason"] == "LOCK" for t in ts), sl=sum(t["reason"] == "SL" for t in ts),
                         fees=sum(t["fees"] or 0 for t in ts))
                out_rows.append(m)
                print(f"  {acc:14s} {sg:16s} n {m['n']:2d} win {m['win_rate'] * 100:5.1f}% avgW {m['avg_win_pct']:+.1f}% "
                      f"avgL {m['avg_loss_pct']:+.1f}% PF {m['pf']:.2f} P&L {m['pnl']:+.0f} ({ts[0]['eq_before']:.0f}→{ts[-1]['eq_after']:.0f}) "
                      f"ret/trade {m['ret_mean_pct']:+.2f}% L/S {m.get('long_n')}/{m.get('short_n')} streak {m['streak']} "
                      f"LOCK {m['lock']} SL {m['sl']} {m['trades_per_day']:.1f}/day")
            by = defaultdict(lambda: [0.0, 0])
            for t in tr:
                if t["account"] == acc:
                    b = by[LO.kst_day(t["exit"])]
                    b[0] += t["pnl"]
                    b[1] += 1
            for d, (pp, n) in sorted(by.items()):
                daily.append(dict(bot=f"paper:{name}", account_id=acc, day_kst=d, pnl=round(pp, 4), trades=n))
        # coin twin: same entries, random side
        bot = {(t["symbol"], t["entry"]): t for t in tr if t["account"] == "COMBO@mix"}
        twin = {(t["symbol"], t["entry"]): t for t in tr if t["account"] == "COMBOFLIP@mix"}
        both = sorted(set(bot) & set(twin))
        same = sum(bot[k]["side"] == twin[k]["side"] for k in both)
        diff = [k for k in both if bot[k]["side"] != twin[k]["side"]]
        bw = sum(bot[k]["pnl"] > 0 for k in diff)
        tw = sum(twin[k]["pnl"] > 0 for k in diff)
        print(f"  coin twin: shared entries {len(both)}, same side {same}, opposite side {len(diff)}: bot won {bw}, twin won {tw}; "
              f"bot-only entries {len(set(bot) - set(twin))}, twin-only {len(set(twin) - set(bot))}")
        bt = [t for t in tr if t["account"] == "COMBO@mix"]
        if bt:
            ret = np.array([t["pnl"] / t["eq_before"] for t in bt])
            days = (max(t["exit"] for t in bt) - min(t["entry"] for t in bt)) / 86400000
            tpd = len(bt) / days
            g = dict(item=f"paper:{name}", n=len(ret), trades_per_day=tpd, ret_mean_pct=float(ret.mean() * 100),
                     **LO.goal_need(ret, tpd), **LO.bootstrap_goal(ret, tpd, sims=10000))
            goal.append(g)
    return allp


def exec_section(root, allp, out_rows, daily, goal):
    print("\n==== LIVE EXECUTORS (real money)")
    cost_rows = []
    for ex, rel in EXECS.items():
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            print(ex, "missing")
            continue
        c = LO.ro(p)
        meta = json.loads(c.execute("SELECT data FROM state WHERE k='meta'").fetchone()[0])
        eq = c.execute("SELECT ts, equity, wallet, coalesce(transfers, 0) FROM equity ORDER BY ts").fetchall()
        starts = [(t, x) for t, x in c.execute("SELECT ts, text FROM events WHERE kind='start' ORDER BY ts")]
        late = [(t, x) for t, x in c.execute("SELECT ts, text FROM events WHERE kind='late' ORDER BY ts")]
        rows = c.execute("SELECT key, symbol, side, qty, leverage, entry_ts, entry_price, exit_ts, exit_reason, pnl, data, "
                         "realized, commission, funding, slippage, real_cost, assumed_cost FROM trades ORDER BY exit_ts").fetchall()
        # which paper DB was followed when (from the start lines)
        follow = []
        for t, x in starts:
            pdb = "live15-mexc" if "live15-mexc.db" in x else "live-ac"
            follow.append((t, pdb))

        def paper_for(t):
            cur = follow[0][1] if follow else "live-ac"
            for ts, pdb in follow:
                if ts <= t:
                    cur = pdb
            return cur
        trs = []
        for (key, sym, side, qty, lev, ets, ep, xts, xr, pnl, data, realized, comm, fund, slip, rc, ac) in rows:
            d = json.loads(data)
            et_paper = int(key.split("|")[-1])
            pdb = paper_for(ets)
            pt = next((t for t in allp.get(pdb, []) if t["account"] == "COMBO@mix" and t["symbol"] == sym
                       and t["entry"] == et_paper), None)
            margin = qty * ep / lev
            wb = d.get("wallet_before")
            r = dict(exchange=ex, key_time=LO.kst(et_paper), symbol=sym, side=side, lev=lev, paper=pdb,
                     real_entry=ep, paper_entry=pt["entry_price"] if pt else None,
                     entry_slip_bps=(side * (ep - pt["entry_price"]) / pt["entry_price"] * 1e4) if pt else None,
                     entry_delay_s=(ets - et_paper) / 1000, real_pnl=pnl, wallet_before=wb,
                     real_acct_pct=pnl / wb * 100 if wb else None, real_roe=pnl / margin * 100,
                     paper_roe=pt["roe"] * 100 if pt else None, paper_acct_pct=pt["pnl"] / pt["eq_before"] * 100 if pt else None,
                     paper_reason=pt["reason"] if pt else None, real_reason=xr, commission=comm, funding=fund,
                     real_cost=rc, assumed_cost=ac, hold_min=(xts - ets) / 60000, exit_ts=xts, entry_ts=ets)
            trs.append(r)
            cost_rows.append(r)
        # missed paper entries while following
        t0 = eq[0][0] if eq else 0
        t1 = eq[-1][0] if eq else 0
        taken = {(r["symbol"], r["key_time"]) for r in trs}
        missed = []
        for pdb in ("live-ac", "live15-mexc"):
            for t in allp.get(pdb, []):
                if t["account"] != "COMBO@mix" or not (t0 <= t["entry"] <= t1) or paper_for(t["entry"]) != pdb:
                    continue
                if (t["symbol"], LO.kst(t["entry"])) not in taken:
                    missed.append(t)
        pnl = [r["real_pnl"] for r in trs]
        ret = [r["real_pnl"] / r["wallet_before"] for r in trs]
        e = [x[1] for x in eq]
        m = LO.basic(pnl, ret, [r["side"] for r in trs])
        m.update(bot=f"live:{ex}", account=meta.get("account"), segment="실거래", first=LO.kst(t0), last=LO.kst(t1),
                 eq_start=e[0] if e else None, eq_end=e[-1] if e else None, eq_peak=max(e) if e else None,
                 max_dd_curve=LO.max_dd(e), transfers=sum(x[3] for x in eq[-1:]) if eq else 0,
                 missed=len(missed), missed_paper_pnl_pct=sum(t["pnl"] / t["eq_before"] * 100 for t in missed),
                 entry_slip_bps_mean=float(np.nanmean([r["entry_slip_bps"] for r in trs if r["entry_slip_bps"] is not None])) if trs else None,
                 real_cost=sum(r["real_cost"] or 0 for r in trs), assumed_cost=sum(r["assumed_cost"] or 0 for r in trs),
                 commission=sum(r["commission"] or 0 for r in trs))
        out_rows.append(m)
        print(f"\n{ex}: {meta.get('exchange')} {meta.get('mode')} since {LO.kst(meta.get('live_since'))}, equity rows {len(eq)} "
              f"{LO.kst(t0)} → {LO.kst(t1)}: ${e[0]:.2f} → ${e[-1]:.2f} (peak ${max(e):.2f}, max fall {LO.max_dd(e) * 100:.1f}%)")
        print(f"  trades {m['n']}, wins {m.get('wins')}, P&L ${m.get('pnl', 0):+.2f}, avg win {m.get('avg_win_pct', 0):+.2f}% avg loss "
              f"{m.get('avg_loss_pct', 0):+.2f}% of wallet, PF {m.get('pf', 0):.2f}, streak {m.get('streak')}")
        print(f"  entry vs paper: mean {m['entry_slip_bps_mean']:+.1f} bps adverse; real cost ${m['real_cost']:.2f} vs assumed ${m['assumed_cost']:.2f}; "
              f"commission ${m['commission']:.2f}")
        for x in late:
            print("  late (not followed):", LO.kst(x[0]), x[1][:80])
        eq_ts = np.array([x[0] for x in eq])

        def running(t):
            """Executor alive at t: an equity row (written every ~5 min) within 20 minutes before t."""
            k = np.searchsorted(eq_ts, t, side="right") - 1
            return k >= 0 and t - eq_ts[k] <= 20 * 60000
        for t in missed:
            t["why"] = "실행기 꺼져 있음" if not running(t["entry"]) else "늦음(재시작 때 오래된 신호)"
            if not running(t["entry"]) and any(abs(lt - t["entry"]) < 4 * 3600000 for lt, _x in late):
                t["why"] = "실행기 꺼져 있다 다시 켜졌을 때 늦은 신호"
            print(f"  missed paper entry {LO.kst(t['entry'])} {t['symbol']} side {t['side']} {t['strategy']} paper {t['reason']} "
                  f"{t['pnl'] / t['eq_before'] * 100:+.1f}% of paper account | {t['why']}")
            cost_rows.append(dict(exchange=ex, key_time=LO.kst(t["entry"]), symbol=t["symbol"], side=t["side"], paper="missed",
                                  paper_acct_pct=t["pnl"] / t["eq_before"] * 100, paper_reason=t["reason"], real_reason=t["why"]))
        for r in trs:
            print(f"   {r['key_time']} {r['symbol'][:4]} {'L' if r['side'] > 0 else 'S'} {r['paper']:11s} real {r['real_acct_pct']:+6.2f}% "
                  f"(ROE {r['real_roe']:+6.1f}%, {r['real_reason'][:14]}) paper {r['paper_acct_pct'] if r['paper_acct_pct'] is not None else float('nan'):+6.2f}% "
                  f"(ROE {r['paper_roe'] if r['paper_roe'] is not None else float('nan'):+6.1f}%, {r['paper_reason']}) entry {r['entry_slip_bps'] if r['entry_slip_bps'] is not None else float('nan'):+5.1f}bps "
                  f"delay {r['entry_delay_s']:.0f}s")
        by = defaultdict(lambda: [0.0, 0])
        for r in trs:
            b = by[LO.kst_day(r["exit_ts"])]
            b[0] += r["real_pnl"]
            b[1] += 1
        for d, (pp, n) in sorted(by.items()):
            daily.append(dict(bot=f"live:{ex}", account_id=meta.get("account", "COMBO@mix"), day_kst=d, pnl=round(pp, 4), trades=n))
        if len(ret) >= 2:
            days = max((t1 - t0) / 86400000, 1e-9)
            tpd = len(ret) / days
            goal.append(dict(item=f"live:{ex}", n=len(ret), trades_per_day=tpd, ret_mean_pct=float(np.mean(ret) * 100),
                             **LO.goal_need(np.array(ret), tpd), **LO.bootstrap_goal(np.array(ret), tpd, sims=10000)))
    return cost_rows


def livecheck_section(root, out):
    p = os.path.join(root, "livecheck.db")
    if not os.path.exists(p):
        return
    c = LO.ro(p)
    print("\n==== LIVE WATCHER (livecheck.db)")
    print("days:", [(d, lv) for d, lv in c.execute("SELECT day, level FROM days ORDER BY day")])
    for d, txt in c.execute("SELECT day, text FROM days ORDER BY day"):
        first = [ln for ln in txt.split("\n") if ln.startswith("- ")][:4]
        print(" ", d, " / ".join(first)[:300])
    print("parity:", c.execute("SELECT kind, verdict, count(*) FROM parity GROUP BY kind, verdict").fetchall())
    # signals the bot did not take: hypothetical outcome by reason
    rows = c.execute("SELECT why_kind, state, roe_net, pnl, wallet, side, strategy, tf, t FROM missed").fetchall()
    agg = defaultdict(list)
    for why, st, roe, pnl, w, side, s, tf, t in rows:
        if st == "closed" and roe is not None:
            agg[why].append((roe, side))
    res = []
    for why, v in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        r = np.array([x[0] for x in v])
        res.append(dict(why=why, n=len(r), win=float((r > 0).mean()), mean_roe_net=float(r.mean() * 100),
                        sl_share=float((r <= -0.3).mean())))
    ac = LO.ro(os.path.join(root, "combo/live-ac.db"))
    tk = np.array([r[0] for r in ac.execute("SELECT roe FROM trades WHERE account_id='COMBO@mix'")])
    tw = np.array([r[0] for r in ac.execute("SELECT roe FROM trades WHERE account_id='COMBOFLIP@mix'")])
    print(f"taken by the paper bot (live-ac COMBO): n {len(tk)} win {np.mean(tk > 0) * 100:.0f}% mean net ROE {tk.mean() * 100:+.1f}%; "
          f"coin twin n {len(tw)} win {np.mean(tw > 0) * 100:.0f}% mean {tw.mean() * 100:+.1f}%")
    res.append(dict(why="TAKEN(live-ac COMBO)", n=len(tk), win=float(np.mean(tk > 0)), mean_roe_net=float(tk.mean() * 100),
                    sl_share=float(np.mean(tk <= -0.3))))
    res.append(dict(why="COIN TWIN(live-ac)", n=len(tw), win=float(np.mean(tw > 0)), mean_roe_net=float(tw.mean() * 100),
                    sl_share=float(np.mean(tw <= -0.3))))
    print("skipped signals (hypothetical, closed):")
    for r in res:
        print(f"   {r['why']:8s} n {r['n']:3d} win {r['win'] * 100:4.0f}% mean net ROE {r['mean_roe_net']:+6.1f}% stop-like {r['sl_share'] * 100:.0f}%")
    with open(os.path.join(out, "live_skipped_signals.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0]))
        w.writeheader()
        w.writerows(res)
    print("loss cards:", [(k[:40], lv) for k, lv in c.execute("SELECT key, label FROM loss_cards")])


def write(path, rows):
    if not rows:
        return
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-root", required=True, help="<extract>/db/paperbot")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rows, daily, goal = [], [], []
    allp = paper_section(a.db_root, rows, daily, goal)
    cost = exec_section(a.db_root, allp, rows, daily, goal)
    livecheck_section(a.db_root, a.out)
    write(os.path.join(a.out, "live_paper_exec_summary.csv"), rows)
    write(os.path.join(a.out, "live_fills_vs_paper.csv"), cost)
    write(os.path.join(a.out, "daily_pnl_live.csv"), daily)
    write(os.path.join(a.out, "live_goal.csv"), goal)
    print("\ngoal path:")
    for g in goal:
        print(f"  {g['item']}: n {g['n']} {g['trades_per_day']:.1f}/day ret {g['ret_mean_pct']:+.2f}% x@1 {g['x_at_1']:.2g} "
              f"P(x6) {g['p_x6']:.3f} P(-50% first) {g['p_dd50']:.3f} P(-90%) {g['p_dd90']:.3f} need_k {g['need_k']}"
              + ("  (표본 30건 미만)" if g["n"] < 30 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
