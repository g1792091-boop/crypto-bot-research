#!/usr/bin/env python3
"""The rule bot's side records from the 10/24 extra export: nightly checks and their "what if" shadows (daily3.db),
the custom-value shadow (paramshadow.db), the 30-day verdict (checkpoint.db) and its weekly rehearsals, the DeepSeek
200 forward shadow (shadow200.db: coverage only, see D11) and the v4 staging install (staging/paper4.db).

    python3 shadows_review.py --db-root <extract>/db/paperbot --out <folder>

Read-only. DeepSeek (F*) account money is not reported (owners' rule D11); shadow200 performance is not computed
before its 30-day stage (2026-11-04).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_other as LO  # noqa: E402

MID_DAY = "2026-10-14"     # first half 10/05-10/14, second half 10/15-10/23
TRADE_VARIANTS = ("lock15", "lock20", "lock30", "timestop", "lev10", "lev20", "lev30", "lev40", "lev50", "stopw1.5",
                  "stopw2.5", "stopw3", "tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R", "lev20m20", "lev30m30",
                  "lev40m40", "lev50m50")
VARIANT_KO = {"lock15": "첫 잠금 +15%부터", "lock20": "첫 잠금 +20%부터", "lock30": "첫 잠금 +30%부터", "timestop": "시간 손절",
              "lev10": "10배", "lev20": "20배", "lev30": "30배", "lev40": "40배", "lev50": "50배", "stopw1.5": "손절 1.5ATR",
              "stopw2.5": "손절 2.5ATR", "stopw3": "손절 3ATR", "tp1R": "고정 익절 1R", "tp1.5R": "고정 익절 1.5R",
              "tp2R": "고정 익절 2R", "tp3R": "고정 익절 3R", "ladder_cap2R": "계단 + 2R 상한", "lev20m20": "20배·증거금 20%",
              "lev30m30": "30배·증거금 30%", "lev40m40": "40배·증거금 40%", "lev50m50": "50배·증거금 50%"}


def group(acc: str) -> str:
    s = acc.split("@")[0]
    if re.match(r"F\d+_", s):
        return "ds200"
    if s.startswith("RANDOM_"):
        return "flip"
    if s.startswith("REEL"):
        return "reel"
    return "core"


def daily3(path, out):
    c = LO.ro(path)
    print("\n==== NIGHTLY CHECKS (daily3.db)")
    days = c.execute("SELECT day, data FROM reports ORDER BY day").fetchall()
    par = [(d, json.loads(x)["parity"]) for d, x in days]
    mism = [(d, p["mismatched_accounts"], p["accounts"]) for d, p in par if isinstance(p, dict)]
    print(f"reports {days[0][0]} ~ {days[-1][0]} ({len(days)} nights, {len(mism)} with a replay); parity mismatched accounts per night: "
          f"{sorted({m for _d, m, _a in mism})}, accounts {sorted({a for _d, _m, a in mism})}")
    last = json.loads(days[-1][1])
    print("stop slippage (last night):", last["stop_slippage"]["overall"])
    # per-trade shadows: variant vs actual on the same trades
    base = {}
    for key, day, acc, roe, data in c.execute("SELECT key, day, account_id, roe, data FROM shadows WHERE kind='base' AND resolved=1"):
        d = json.loads(data)
        base[key.split("|", 1)[1]] = (day, acc, d.get("pnl_equity"), roe)
    rows = []
    for v in TRADE_VARIANTS:
        acc_d = defaultdict(lambda: defaultdict(list))
        for key, day, acc, roe, data in c.execute("SELECT key, day, account_id, roe, data FROM shadows WHERE kind=? AND resolved=1", (v,)):
            b = base.get(key.split("|", 1)[1])
            if b is None:
                continue
            d = json.loads(data)
            pe = d.get("pnl_equity")
            if pe is None or b[2] is None:
                continue
            g = group(acc)
            h = "H1" if day <= MID_DAY else "H2"
            acc_d[g][h].append((pe, b[2]))
        for g in ("core", "flip"):
            r = dict(variant=v, variant_ko=VARIANT_KO[v], group=g)
            for h in ("H1", "H2"):
                x = np.array(acc_d[g][h]) if acc_d[g][h] else np.zeros((0, 2))
                r[f"{h}_n"] = len(x)
                r[f"{h}_var_pct"] = float(x[:, 0].mean() * 100) if len(x) else float("nan")
                r[f"{h}_base_pct"] = float(x[:, 1].mean() * 100) if len(x) else float("nan")
                r[f"{h}_diff_pct"] = r[f"{h}_var_pct"] - r[f"{h}_base_pct"] if len(x) else float("nan")
            r["better_both_halves"] = bool(r["H1_diff_pct"] > 0 and r["H2_diff_pct"] > 0)
            rows.append(r)
    print("variant vs actual, mean account change per trade (%), core = the 36 strategies, flip = coin flips:")
    for r in rows:
        print(f"  {r['group']:4s} {r['variant']:12s} H1 {r['H1_var_pct']:+.2f} vs {r['H1_base_pct']:+.2f} (n {r['H1_n']}) | "
              f"H2 {r['H2_var_pct']:+.2f} vs {r['H2_base_pct']:+.2f} (n {r['H2_n']}) {'BOTH+' if r['better_both_halves'] else ''}")
    write(os.path.join(out, "daily3_variants.csv"), rows)
    # quality tiers ("good place" vs normal) — the agents' recurring claim
    q = defaultdict(list)
    for day, acc, roe, data in c.execute("SELECT day, account_id, roe, data FROM shadows WHERE kind='quality' AND resolved=1"):
        d = json.loads(data)
        g = group(acc)
        if g == "ds200":
            continue
        q[(g, d.get("tier") or d.get("quality_tier"), "H1" if day <= MID_DAY else "H2")].append(d.get("actual_pnl_equity", 0) or 0)
    qrows = [dict(group=k[0], tier=k[1], half=k[2], n=len(v), mean_pct=float(np.mean(v) * 100)) for k, v in sorted(q.items(), key=str)]
    print("quality tier of the entry (actual result per trade, % of account):")
    for r in qrows:
        print("  ", r)
    write(os.path.join(out, "daily3_quality.csv"), qrows)
    # limit-entry and skipped-signal shadows
    lim = defaultdict(list)
    for day, acc, filled, roe in c.execute("SELECT day, account_id, filled, roe FROM shadows WHERE kind='limit' AND resolved=1"):
        g = group(acc)
        if g == "ds200":
            continue
        lim[(g, "H1" if day <= MID_DAY else "H2", int(filled or 0))].append(roe if roe is not None else np.nan)
    sk = defaultdict(list)
    for day, acc, roe in c.execute("SELECT day, account_id, roe FROM shadows WHERE kind='skipped' AND resolved=1"):
        g = group(acc)
        if g == "ds200":
            continue
        sk[(g, "H1" if day <= MID_DAY else "H2")].append(roe)
    br = defaultdict(list)
    for key, (day, acc, pe, roe) in base.items():
        g = group(acc)
        if g != "ds200":
            br[(g, "H1" if day <= MID_DAY else "H2")].append(roe)
    print("limit entry (0.25 ATR better, one bar) filled share and mean net ROE of filled; skipped-in-position signals; actual:")
    for g in ("core", "flip"):
        for h in ("H1", "H2"):
            f1 = np.array(lim[(g, h, 1)], float)
            f0 = len(lim[(g, h, 0)])
            s = np.array(sk[(g, h)], float)
            b = np.array(br[(g, h)], float)
            print(f"  {g} {h}: limit filled {len(f1)}/{len(f1) + f0} mean ROE {np.nanmean(f1) * 100:+.2f}% | skipped n {len(s)} mean ROE "
                  f"{np.nanmean(s) * 100:+.2f}% | actual n {len(b)} mean ROE {np.nanmean(b) * 100:+.2f}%")
    return rows


def paramshadow(path, out, last_json=None):
    c = LO.ro(path)
    print("\n==== CUSTOM-VALUE SHADOW (paramshadow.db)")
    acc_cell = {}
    sums = defaultdict(lambda: [0.0, 0.0, 0, 0])
    for acc, et, pnl, eqa in c.execute("SELECT account, exit_time, pnl, equity_after FROM trades"):
        h = 0 if LO.kst_day(et) <= MID_DAY else 1
        s = sums[acc]
        s[h] += pnl / (eqa - pnl)
        s[2 + h] += 1
    cells = defaultdict(dict)
    for acc, s in sums.items():
        cell, var = acc.split("#", 1)
        cells[cell][var] = s
    n_cells = len(cells)
    b1 = b2 = both = tot = 0
    for cell, vs in cells.items():
        base = vs.get("base")
        if base is None:
            continue
        for var, s in vs.items():
            if var == "base" or s[2] < 10 or s[3] < 10:
                continue
            tot += 1
            x1, x2 = s[0] > base[0], s[1] > base[1]
            b1 += x1
            b2 += x2
            both += x1 and x2
    exp = b1 / tot * b2 / tot * tot if tot else 0
    print(f"cells {n_cells}, variants with >=10 trades in both halves {tot}: better than default in H1 {b1}, H2 {b2}, both {both} "
          f"(expected if no persistence {exp:.0f})")
    res = dict(cells=n_cells, variants=tot, better_h1=b1, better_h2=b2, better_both=both, expected_both=exp)
    if last_json and os.path.exists(last_json):
        o = json.load(open(last_json))
        print("server summary:", o.get("line_ko"), "| overview", o.get("overview"))
        res.update({f"server_{k}": v for k, v in o.get("overview", {}).items()})
    write(os.path.join(out, "paramshadow_halves.csv"), [res])
    return res


def verdicts(root):
    print("\n==== 30-DAY VERDICT (checkpoint.db) AND WEEKLY REHEARSALS")
    c = LO.ro(os.path.join(root, "checkpoint.db"))
    print("checkpoint.db rows:", {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("snapshots", "verdicts", "verdict_accounts", "job_log")})
    for p in sorted(glob.glob(os.path.join(root, "rehearsal", "*.db"))):
        r = LO.ro(p)
        date, _ts, _sha, data = r.execute("SELECT * FROM verdicts").fetchone()
        d = json.loads(data)
        print(f"  {os.path.basename(p)}: day {d['day']} counts {d['counts']} tested {d['tested']} passed {d['luck_passed']} "
              f"(uncorrected luck would pass {d['lucky_if_uncorrected']})")


def shadow200(path):
    print("\n==== DEEPSEEK 200 FORWARD SHADOW (shadow200.db) — coverage only (D11: no performance before 2026-11-04)")
    c = LO.ro(path)
    meta = dict(c.execute("SELECT key, value FROM meta").fetchall())
    print("meta keys:", sorted(meta))
    print("runs:", c.execute("SELECT count(*), min(ts), max(ts) FROM runs").fetchone(), "kinds", c.execute("SELECT kind, count(*) FROM runs GROUP BY kind").fetchall())
    lo, hi = c.execute("SELECT min(ts), max(ts) FROM runs").fetchone()
    print(f"  first run {LO.kst(lo)} last run {LO.kst(hi)}")
    print("signals:", c.execute("SELECT count(*), count(DISTINCT def), min(open_ms), max(open_ms) FROM signals").fetchone())
    print("trades (closed, not read):", c.execute("SELECT count(*) FROM trades").fetchone()[0], "open:", c.execute("SELECT count(*) FROM open_trades").fetchone()[0])
    print("bars:", c.execute("SELECT tf, count(*), max(open_ms) FROM bars GROUP BY tf").fetchall())
    print("events:", c.execute("SELECT count(*) FROM events").fetchone()[0], "snapshots:", c.execute("SELECT count(*) FROM snapshots").fetchone()[0])


def staging(path):
    c = LO.ro(path)
    print("\n==== v4 staging (staging/paper4.db)")
    print("accounts", c.execute("SELECT count(*) FROM accounts").fetchone()[0], "trades", c.execute("SELECT count(*), min(entry_time), max(exit_time) FROM trades").fetchone(),
          "heartbeat", LO.kst(c.execute("SELECT ts FROM state WHERE k='heartbeat'").fetchone()[0]))


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
    ap.add_argument("--db-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--paramshadow-last", help="paramshadow/last.json from the demo export (server summary)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    daily3(os.path.join(a.db_root, "daily3.db"), a.out)
    paramshadow(os.path.join(a.db_root, "paramshadow", "paramshadow.db"), a.out, a.paramshadow_last)
    verdicts(a.db_root)
    shadow200(os.path.join(a.db_root, "shadow200", "shadow200.db"))
    staging(os.path.join(a.db_root, "staging", "paper4.db"))
    for name in ("shadow_league.db", "ghcoin.db", "combo/vwap.db", "combo/friend.db", "exec/executor-deepcoin-live.db"):
        print(f"{name}: {'present' if os.path.exists(os.path.join(a.db_root, name)) else 'NOT in the export'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
