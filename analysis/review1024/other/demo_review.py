#!/usr/bin/env python3
"""Demo lab bot (demobot) review, 10/24: every account line's forward results, the rank tables, half-to-half
persistence of the leaders, the coin-flip / random-entry controls, regime split, the 5-year comparison and what
changed since the 10/17 export.

    python3 demo_review.py --snap <new export>/snap --db <demo.db or demo_small.db> \
        [--old-snap <10/17 export>/snap --old-db <10/17 demo_small.db>] --out <folder>

Inputs are untrusted exports: they are only read (json / npz with allow_pickle=False / sqlite read-only).
Writes CSVs into --out and prints the numbers the report uses. Private strategies (pv-*) are named by account id only.
"""
from __future__ import annotations

import argparse
import csv
import filecmp
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_other as LO  # noqa: E402

LEVS = ("20", "30", "40", "50")
EXITS = ("house", "tp1R_sl1.5atr", "tp1.5R_sl1.5atr", "tp2R_sl1.5atr", "tp3R_sl1.5atr", "tp1R_sl2atr",
         "tp1.5R_sl2atr", "tp2R_sl2atr", "tp3R_sl2atr", "tp1R_sl3atr", "tp1.5R_sl3atr", "tp2R_sl3atr",
         "tp3R_sl3atr", "half1R_be_1.5R")
EXIT_KO = ["사다리(규칙봇식)"] + [f"익절{e.split('_')[0][2:]}·손절{e.split('_')[1][2:].replace('atr', 'ATR')}"
                               for e in EXITS[1:13]] + ["반익반본"]
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD", "XRPUSD")
STRATS = {"S2": ("S2_ST_ROC", 343), "N02": ("N02_ST_KST", 735), "N04": ("N04_ST_KLINGER", 588)}
# cell layout (demobot/store.py)
F_MAIN_R, F_MAIN_REASON, F_TP_R, F_HB_R, NF, NT = 0, 2, 3, 40, 43, 18
WEEK = 7 * 86400 * 1000
SEED, RUIN = 1000.0, 100.0


def label(a: dict) -> str:
    """Display name; private plug-ins by id only."""
    return a["id"] if a["kind"] == "private" else a["name"]


def line_trades(a: dict, L: str):
    """Closed trades of one line in the wallet's close order, with the account change of each trade."""
    tr = [t for t in a["trades"] if str(t["L"]) == L and t["status"] != "open"]
    tr.sort(key=lambda t: (t["exit_ms"], t["entry_ms"]))
    W = SEED
    out = []
    for t in tr:
        r = t["pnl"] / W
        out.append((t, r, W))
        W += t["pnl"]
        if W < RUIN:
            W = SEED
    return out


def per_line(snap: str, live0: int, t_end: int):
    accts = json.load(open(os.path.join(snap, "accounts.json")))["accounts"]
    rows, daily, rets = [], [], {}
    t_mid = live0 + (t_end - live0) // 2
    days = (t_end - live0) / 86400000
    for a0 in accts:
        a = json.load(open(os.path.join(snap, "acct", f"{a0['id']}.json")))
        for L in LEVS:
            ln = a["lines"][L]
            tl = line_trades(a, L)
            pnl = [t["pnl"] for t, _r, _w in tl]
            ret = [r for _t, r, _w in tl]
            side = [t["side"] for t, _r, _w in tl]
            tx = [t["exit_ms"] for t, _r, _w in tl]
            m = LO.basic(pnl, ret, side, tx, t_mid)
            rets[(a["id"], L)] = np.array(ret)
            m.update(id=a["id"], name=label(a), kind=a["kind"], sub=a["sub"], tf=a["tf"], L=int(L),
                     equity=ln["equity"], pnl_total_pct=ln["pnl_pct"], open=ln["open"], max_dd=ln["max_dd"],
                     liqs=ln["liqs"], ruins=ln["ruins"], skipped=ln["skipped"], fees=ln["parts"]["fees"],
                     gross=ln["parts"]["gross"], funding=ln["parts"]["funding"],
                     mean_R=ln["mean_R"], stops_pnl_pct=ln["stops"]["pnl_pct"], stops_trades=ln["stops"]["trades"],
                     trades_per_day=len(tl) / days, switches=a["switches"])
            rows.append(m)
            by = {}
            for t, _r, _w in tl:
                d = LO.kst_day(t["exit_ms"])
                b = by.setdefault(d, [0.0, 0])
                b[0] += t["pnl"]
                b[1] += 1
            for d, (p, n) in sorted(by.items()):
                daily.append(("demo", f"{a['id']}@{L}x", d, round(p, 4), n))
    return accts, rows, daily, rets


def coinflip(rows, rets):
    """Each line's per-trade account change against the coin-flip line of the same timeframe and leverage."""
    out = []
    for r in rows:
        if r["kind"] == "flip" or r["n"] < 3:
            r["p_vs_flip"] = float("nan")
            continue
        ref = rets.get((f"cf-{r['tf']}", str(r["L"])))
        p = LO.perm_p_mean(rets[(r["id"], str(r["L"]))], ref, iters=4000) if ref is not None else float("nan")
        r["p_vs_flip"] = p
        r["flip_ret_pct"] = float(np.mean(ref) * 100) if ref is not None and len(ref) else float("nan")
        out.append(p)
    return out


def drift(db: str, live0: int, t_end: int):
    c = LO.ro(db)
    res = {}
    for coin in COINS:
        try:
            a = c.execute("SELECT o FROM bars WHERE coin=? AND ts>=? ORDER BY ts LIMIT 1", (coin, live0)).fetchone()
            b = c.execute("SELECT c FROM bars WHERE coin=? AND ts<=? ORDER BY ts DESC LIMIT 1", (coin, t_end)).fetchone()
            h0 = c.execute("SELECT o FROM bars WHERE coin=? ORDER BY ts LIMIT 1", (coin,)).fetchone()
        except Exception:  # noqa: BLE001  (demo_small.db has no bars)
            return None
        if a and b:
            res[coin] = dict(live=(b[0] / a[0] - 1) * 100, hist=(a[0] / h0[0] - 1) * 100 if h0 else float("nan"))
    return res


def rank_tables(snap: str):
    """Summary of the 6 rank files: per strategy x tf x window x exit, settings with enough trades, how many are
    positive after costs, the best plateau pick and the luck line (best of random players, 95 %)."""
    meta = json.load(open(os.path.join(snap, "rank_meta.json")))
    rows = []
    for key, f in meta["files"].items():
        z = np.load(os.path.join(snap, f["file"]), allow_pickle=False)
        st, luck, min_n = z["stats"], z["luck95"], z["min_n"]
        for wi, w in enumerate(meta["windows"]):
            for e, ex in enumerate(meta["exits"]):
                s = st[wi, e, 0]
                n, mean, pl = s[:, 0].astype(float), s[:, 2].astype(float), s[:, 8].astype(float)
                ok = n >= min_n[wi][0]
                best = int(np.nanargmax(np.where(ok, pl, np.nan))) if ok.any() and np.isfinite(pl[ok]).any() else -1
                rows.append(dict(set=key, window=w, exit=ex, settings=len(n), eligible=int(ok.sum()),
                                 positive=int(np.sum(ok & (mean > 0))), best_mean_R=float(np.nanmax(np.where(ok, mean, np.nan))) if ok.any() else float("nan"),
                                 median_mean_R=float(np.nanmedian(np.where(ok, mean, np.nan))) if ok.any() else float("nan"),
                                 pick_combo=best, pick_mean_R=float(mean[best]) if best >= 0 else float("nan"),
                                 pick_n=int(n[best]) if best >= 0 else 0, luck95=float(luck[wi, e, 0]),
                                 beats_luck=bool(best >= 0 and mean[best] > luck[wi, e, 0]),
                                 win_rate_pick=float(s[best, 1] / n[best]) if best >= 0 and n[best] else float("nan")))
    return meta, rows


def _load_cells(c, coin, tf):
    rows = c.execute("SELECT ts, side, f FROM cells WHERE coin=? AND tf=? ORDER BY ts, side", (coin, tf)).fetchall()
    ts = np.fromiter((r[0] for r in rows), np.int64, len(rows))
    sd = np.fromiter((r[1] for r in rows), np.int8, len(rows))
    F = np.frombuffer(b"".join(r[2] for r in rows), np.float32).reshape(len(rows), NF)
    return ts, sd, F


def _exit_R(F):
    """(n, 14) net R per exit, NaN while open."""
    R = np.full((len(F), 14), np.nan, np.float32)
    R[:, 0] = np.where(F[:, F_MAIN_REASON] != 3, F[:, F_MAIN_R], np.nan)
    R[:, 1:13] = F[:, F_TP_R:F_TP_R + 12]
    R[:, 13] = F[:, F_HB_R]
    return R


def halves(db: str, live0: int, hist0: int):
    """Per setting x exit mean net R in three blocks: H1 = first half of the history fill, H2 = second half
    (both computed by the demo engine on past bars), LIVE = since the live start. Plus the random-entry control
    (every bar, both sides) per block. Uses the full demo.db (sigs + cells)."""
    c = LO.ro(db)
    mid = hist0 + (live0 - hist0) // 2
    blocks = (("H1", hist0, mid), ("H2", mid, live0), ("LIVE", live0, 1 << 62))
    out, ctrl = [], []
    for tf in ("15m", "30m"):
        step = (15 if tf == "15m" else 30) * 60000
        cells = {coin: _load_cells(c, coin, tf) for coin in COINS}
        # random-entry control: every cell (bar x side) entering at the next bar
        for bname, lo, hi in blocks:
            allR = []
            for coin in COINS:
                ts, sd, F = cells[coin]
                m = (ts + step >= lo) & (ts + step < hi)
                allR.append(_exit_R(F[m]))
            A = np.concatenate(allR)
            for e in range(14):
                v = A[:, e]
                v = v[np.isfinite(v)]
                ctrl.append(dict(tf=tf, block=bname, exit=EXITS[e], n=len(v), mean_R=float(v.mean()) if len(v) else float("nan"),
                                 win=float((v > 0).mean()) if len(v) else float("nan")))
        for short, (strat, nc) in STRATS.items():
            sums = {b[0]: np.zeros((nc, 14)) for b in blocks}
            cnts = {b[0]: np.zeros((nc, 14)) for b in blocks}
            wins = {b[0]: np.zeros((nc, 14)) for b in blocks}
            for coin in COINS:
                ts_c, sd_c, F = cells[coin]
                R = _exit_R(F)
                key = ts_c * 2 + (sd_c < 0)
                order = np.argsort(key)
                key_s = key[order]
                q = c.execute("SELECT ts, longs, shorts FROM sigs WHERE coin=? AND tf=? AND strat=? ORDER BY ts",
                              (coin, tf, strat)).fetchall()
                ts_l, cb_l, sd_l = [], [], []
                for t, lg, sh in q:
                    a = np.frombuffer(lg, np.int16)
                    b = np.frombuffer(sh, np.int16)
                    if len(a):
                        ts_l.append(np.full(len(a), t, np.int64)); cb_l.append(a); sd_l.append(np.zeros(len(a), np.int64))
                    if len(b):
                        ts_l.append(np.full(len(b), t, np.int64)); cb_l.append(b); sd_l.append(np.ones(len(b), np.int64))
                if not ts_l:
                    continue
                st = np.concatenate(ts_l)
                cb = np.concatenate(cb_l).astype(np.int64)
                sx = np.concatenate(sd_l)
                k = st * 2 + sx
                pos = np.searchsorted(key_s, k)
                pos = np.minimum(pos, len(key_s) - 1)
                hit = key_s[pos] == k
                row = order[pos[hit]]
                st, cb = st[hit], cb[hit]
                Rs = R[row]
                for bname, lo, hi in blocks:
                    m = (st + step >= lo) & (st + step < hi)
                    if not m.any():
                        continue
                    for e in range(14):
                        v = Rs[m, e]
                        f = np.isfinite(v)
                        sums[bname][:, e] += np.bincount(cb[m][f], weights=v[f], minlength=nc)
                        cnts[bname][:, e] += np.bincount(cb[m][f], minlength=nc)
                        wins[bname][:, e] += np.bincount(cb[m][f & (v > 0)], minlength=nc)
            for e in range(14):
                for ci in range(nc):
                    d = dict(set=f"{short}_{tf}", exit=EXITS[e], combo=ci)
                    for bname, _lo, _hi in blocks:
                        n = cnts[bname][ci, e]
                        d[f"{bname}_n"] = int(n)
                        d[f"{bname}_R"] = float(sums[bname][ci, e] / n) if n else float("nan")
                        d[f"{bname}_win"] = float(wins[bname][ci, e] / n) if n else float("nan")
                    out.append(d)
        del cells
    return out, ctrl, mid


def persistence(hrows, min_h=100, min_live=20):
    """Do the half-1 leaders stay ahead in half 2 and live? Per set x exit: Spearman correlation of setting means
    H1 vs H2, the top-10 of H1 in H2 (mean rank percentile), positive-in-both counts vs. independence."""
    from collections import defaultdict
    g = defaultdict(list)
    for r in hrows:
        g[(r["set"], r["exit"])].append(r)
    out = []
    for (s, e), rs in g.items():
        ok = [r for r in rs if r["H1_n"] >= min_h and r["H2_n"] >= min_h]
        if len(ok) < 20:
            continue
        a = np.array([r["H1_R"] for r in ok])
        b = np.array([r["H2_R"] for r in ok])
        lv = np.array([r["LIVE_R"] if r["LIVE_n"] >= min_live else np.nan for r in ok])
        ra, rb = a.argsort().argsort(), b.argsort().argsort()
        rho = float(np.corrcoef(ra, rb)[0, 1])
        top = np.argsort(-a)[:10]
        pct_b = float(np.mean(rb[top]) / (len(ok) - 1))
        fl = np.isfinite(lv)
        rl = np.full(len(ok), np.nan)
        if fl.sum() >= 20:
            rl[fl] = lv[fl].argsort().argsort() / (fl.sum() - 1)
        best26 = np.argsort(-(a + b))[:10]
        out.append(dict(set=s, exit=e, settings=len(ok), rho_h1_h2=rho, top10_h1_pct_in_h2=pct_b,
                        pos_h1=int((a > 0).sum()), pos_h2=int((b > 0).sum()), pos_both=int(((a > 0) & (b > 0)).sum()),
                        pos_both_expected=float((a > 0).mean() * (b > 0).mean() * len(ok)),
                        best_h1h2_R_live=float(np.nanmean(lv[best26])) if np.isfinite(lv[best26]).any() else float("nan"),
                        all_live_R=float(np.nanmean(lv)) if fl.any() else float("nan"),
                        top10_h1h2_pct_in_live=float(np.nanmean(rl[best26])) if np.isfinite(rl[best26]).any() else float("nan"),
                        mean_h1=float(a.mean()), mean_h2=float(b.mean()), best_h1=float(a.max()), h2_of_best_h1=float(b[np.argmax(a)])))
    return out


def regime(snap: str, accts):
    """Per-trade net R by the trend label at entry (up / down / range) and side, all lines pooled, by account kind."""
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    for a0 in accts:
        a = json.load(open(os.path.join(snap, "acct", f"{a0['id']}.json")))
        for t in a["trades"]:
            if t["status"] == "open":
                continue
            for k in ((a["kind"], t["trend"], t["side"]), ("all", t["trend"], t["side"]), ("all", t["trend"], 0),
                      ("all", "vol:" + str(t["vol"]), 0)):
                x = agg[k]
                x[0] += 1
                x[1] += t["R"]
                x[2] += t["pnl"]
    return [dict(kind=k[0], trend=k[1], side=k[2], n=v[0], mean_R=v[1] / v[0], pnl=v[2]) for k, v in sorted(agg.items(), key=str)]


def vs5y(snap: str):
    o = json.load(open(os.path.join(snap, "vs5y.json")))
    out = []
    for r in o["rows"]:
        d = dict(id=r["id"] if not r["id"].startswith("pv-") else r["id"], exit=r.get("exit_ko"), live_n=r["live"]["n"],
                 live_R=r["live"]["mean_R"], live_win=r["live"]["win_rate"])
        for k, v in (r.get("past") or {}).items():
            if isinstance(v, dict):
                d[f"past_{k}_R"] = v.get("mean_R")
                d[f"past_{k}_n"] = v.get("n")
        out.append(d)
    return out


def pair_compare(rows):
    """Account families against the fixed default account of the same strategy, timeframe and leverage."""
    key = lambda r: (r["id"].split("-")[-2], r["tf"], r["L"])  # noqa: E731
    fx = {key(r): r["equity"] for r in rows if r["kind"] == "fixed" and r["sub"] == "default"}
    out = {}
    for name, sel in (("자동 교체(전체)", lambda r: r["kind"] == "adaptive"),
                      ("자동 r26", lambda r: r["sub"] == "r26"), ("자동 r4", lambda r: r["sub"] == "r4"),
                      ("자동 r26c", lambda r: r["sub"] == "r26c"), ("자동 wk", lambda r: r["sub"] == "wk"),
                      ("5년 1등 값", lambda r: r["sub"] == "pick"), ("친구 값", lambda r: r["kind"] == "fixed" and r["sub"] == "friend"),
                      ("친구 규칙", lambda r: r["kind"] == "friend")):
        xs = [(r["equity"], fx[key(r)]) for r in rows if sel(r) and key(r) in fx]
        out[name] = dict(pairs=len(xs), better=sum(a > b for a, b in xs), mean_diff=float(np.mean([a - b for a, b in xs])) if xs else float("nan"))
    st = [(r["stops_pnl_pct"], r["pnl_total_pct"]) for r in rows]
    out["정지 규칙 줄"] = dict(pairs=len(st), better=sum(a > b for a, b in st), mean_diff=float(np.mean([a - b for a, b in st])),
                           positive=sum(a > 0 for a, _b in st))
    return out


def vs5y_corr(v):
    out = {}
    for k in sorted({k for r in v for k in r if k.startswith("past_") and k.endswith("_R")}):
        xs = [(r["live_R"], r[k]) for r in v if r.get(k) is not None and r.get("live_R") is not None]
        if len(xs) >= 5:
            a = np.array(xs, float)
            out[k] = dict(n=len(a), corr=float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), live=float(a[:, 0].mean()),
                          past=float(a[:, 1].mean()), live_worse=int((a[:, 0] < a[:, 1]).sum()))
    return out


def vs_random(hrows, ctrl):
    """Average setting of each strategy x tf x exit against random entries (same exit, same block)."""
    from collections import defaultdict
    rr = {(c["tf"], c["exit"], c["block"]): c["mean_R"] for c in ctrl}
    g = defaultdict(lambda: defaultdict(list))
    for r in hrows:
        for b in ("H1", "H2", "LIVE"):
            if r[f"{b}_n"]:
                g[(r["set"], r["exit"])][b].append(r[f"{b}_R"])
    res = {b: [] for b in ("H1", "H2", "LIVE")}
    for (s, e), d in g.items():
        tf = s.split("_")[1]
        for b in res:
            if d[b]:
                res[b].append(np.mean(d[b]) - rr[(tf, e, b)])
    return {b: dict(groups=len(v), mean_minus_random=float(np.mean(v)), share_better=float(np.mean(np.array(v) > 0)))
            for b, v in res.items()}


def changed(new_snap, old_snap, new_db, old_db):
    if not old_snap or not os.path.isdir(old_snap):
        return None
    files = sorted({os.path.relpath(p, new_snap) for p in glob.glob(os.path.join(new_snap, "**", "*"), recursive=True)
                    if os.path.isfile(p)} | {os.path.relpath(p, old_snap) for p in glob.glob(os.path.join(old_snap, "**", "*"), recursive=True)
                                             if os.path.isfile(p)})
    diff = [f for f in files if not (os.path.exists(os.path.join(new_snap, f)) and os.path.exists(os.path.join(old_snap, f))
                                     and filecmp.cmp(os.path.join(new_snap, f), os.path.join(old_snap, f), shallow=False))]
    same_db = bool(old_db and new_db and os.path.exists(old_db) and filecmp.cmp(new_db, old_db, shallow=False))
    return dict(files=len(files), differ=diff, small_db_identical=same_db)


def write_csv(path, rows, cols=None):
    if not rows:
        return
    import gzip
    cols = cols or list(dict.fromkeys(k for r in rows for k in r))
    opener = (lambda: gzip.open(path, "wt", newline="", encoding="utf-8")) if path.endswith(".gz") else \
        (lambda: open(path, "w", newline="", encoding="utf-8"))
    with opener() as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", required=True)
    ap.add_argument("--db", required=True, help="full demo.db (for bars, sigs, cells) or demo_small.db")
    ap.add_argument("--small-db", help="demo_small.db of the same export (for the 10/17 comparison)")
    ap.add_argument("--old-snap")
    ap.add_argument("--old-db")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-halves", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    status = json.load(open(os.path.join(a.snap, "status.json")))
    live0 = int(status["live_start_ms"])
    t_end = int(status["last_tick_ms"])
    hist0 = int(status["history_start_ms"])
    print(f"live {LO.kst(live0)} ~ {LO.kst(t_end)} KST = {(t_end - live0) / 86400000:.2f} days; history from {LO.kst(hist0)}")
    print("last bar 15m:", LO.kst(status["last_bar_ms"]["15m"]), "counts:", status["counts"])
    ch = changed(a.snap, a.old_snap, a.small_db, a.old_db)
    print("changed vs old export:", ch)
    c = LO.ro(a.db)
    try:
        lb = c.execute("SELECT max(ts) FROM bars").fetchone()[0]
        print("db last bar (UTC open ms):", lb, LO.kst(lb), "KST")
    except Exception as e:  # noqa: BLE001
        print("db bars:", e)

    accts, rows, daily, rets = per_line(a.snap, live0, t_end)
    ps = coinflip(rows, rets)
    write_csv(os.path.join(a.out, "demo_lines.csv"), rows)
    write_csv(os.path.join(a.out, "daily_pnl_demo.csv"), [dict(bot=b, account_id=i, day_kst=d, pnl=p, trades=n)
                                                          for b, i, d, p, n in daily])
    ps = np.array([p for p in ps if np.isfinite(p)])
    print(f"\nlines {len(rows)}; vs coin flip p<0.05: {int((ps < 0.05).sum())} of {len(ps)} (luck alone ~{0.05 * len(ps):.0f})")
    up = [r for r in rows if r.get("pnl", 0) > 0]
    print(f"lines up (closed P&L > 0): {len(up)} / {len(rows)}; equity > 1000: {sum(r['equity'] > 1000 for r in rows)}")
    tot = sum(r.get("n", 0) for r in rows)
    print("closed trades all lines:", tot, " fees:", round(sum(r["fees"] for r in rows)), " gross:", round(sum(r["gross"] for r in rows)))
    # by kind x L
    from collections import defaultdict
    g = defaultdict(list)
    for r in rows:
        g[(r["kind"], r["L"])].append(r)
    print("\nkind L lines mean_equity_change% median win% per-trade% (trades)")
    for k in sorted(g):
        rs = g[k]
        print(k, len(rs), round(np.mean([r["equity"] / 10 - 100 for r in rs]), 1), round(np.median([r["equity"] / 10 - 100 for r in rs]), 1),
              round(np.nanmean([r.get("win_rate", np.nan) for r in rs]) * 100, 1),
              round(np.nanmean([r.get("ret_mean_pct", np.nan) for r in rs]), 2), sum(r.get("n", 0) for r in rs))
    best = sorted(rows, key=lambda r: -r["equity"])[:12]
    print("\nbest lines by equity:")
    for r in best:
        print(f"  {r['id']}@{r['L']} eq {r['equity']:.0f} n {r.get('n')} win {r.get('win_rate', 0) * 100:.0f}% PF {r.get('pf', 0):.2f} "
              f"ret/trade {r.get('ret_mean_pct', 0):+.2f}% dd {r['max_dd'] * 100:.0f}% L/S {r.get('long_n')}/{r.get('short_n')} "
              f"S pnl {r.get('short_pnl', 0):+.0f} L pnl {r.get('long_pnl', 0):+.0f} h1 {r.get('h1_pnl', 0):+.0f} h2 {r.get('h2_pnl', 0):+.0f} "
              f"p_flip {r.get('p_vs_flip', float('nan')):.2f} streak {r.get('streak')}")
    # long vs short overall
    L_n = sum(r.get("long_n", 0) for r in rows)
    S_n = sum(r.get("short_n", 0) for r in rows)
    print("\nlong trades", L_n, "pnl", round(sum(r.get("long_pnl", 0) for r in rows)), " short trades", S_n, "pnl",
          round(sum(r.get("short_pnl", 0) for r in rows)))
    h1 = sum(r.get("h1_pnl", 0) for r in rows)
    h2 = sum(r.get("h2_pnl", 0) for r in rows)
    print("all lines pnl half1", round(h1), "half2", round(h2))
    pos_both = sum(1 for r in rows if r.get("h1_pnl", 0) > 0 and r.get("h2_pnl", 0) > 0)
    print("lines positive in both halves:", pos_both, "of", len(rows))
    # goal path for the best lines (and the coin flips for reference)
    goal = []
    days = (t_end - live0) / 86400000
    cand = {(r["id"], r["L"]): r for r in rows if (r.get("n", 0) >= 5 and r.get("pnl", 0) > 0) or r["kind"] == "flip"}
    for r in sorted(cand.values(), key=lambda r: -r.get("log_growth", -9)):
        ret = rets[(r["id"], str(r["L"]))]
        tpd = len(ret) / days
        gn = LO.goal_need(ret, tpd)
        bs = LO.bootstrap_goal(ret, tpd, sims=10000)
        # luck-adjusted: same spread of outcomes, but the average set to the coin flip's (same tf and leverage)
        ref = rets.get((f"cf-{r['tf']}", str(r["L"])))
        shift = (float(np.mean(ref)) - float(np.mean(ret))) if ref is not None and len(ref) else 0.0
        bl = LO.bootstrap_goal(ret + shift, tpd, sims=10000)
        goal.append(dict(id=r["id"], L=r["L"], n=len(ret), trades_per_day=tpd, ret_mean_pct=r["ret_mean_pct"],
                         margin_pct=r["L"], exposure=r["L"] * r["L"] / 100, **gn, **bs,
                         luck_p_x6=bl["p_x6"], luck_p_dd50=bl["p_dd50"], luck_p_dd90=bl["p_dd90"],
                         small_sample=len(ret) < 30, p_vs_flip=r.get("p_vs_flip")))
    write_csv(os.path.join(a.out, "demo_goal.csv"), goal)
    print("\ngoal path (bootstrap of the line's own trades, 30 days):")
    for x in goal:
        print(f"  {x['id']}@{x['L']} n {x['n']} {x['trades_per_day']:.1f}/day ret {x['ret_mean_pct']:+.2f}% x@1 {x['x_at_1']:.2g} "
              f"P(x6) {x['p_x6']:.3f} P(-50%) {x['p_dd50']:.3f} P(-90%) {x['p_dd90']:.3f} med {x['med_x']:.2f} need_k {x['need_k']} "
              f"| luck-adj P(x6) {x['luck_p_x6']:.3f} P(-50%) {x['luck_p_dd50']:.3f}" + ("  SMALL" if x["small_sample"] else ""))

    meta, rk = rank_tables(a.snap)
    write_csv(os.path.join(a.out, "demo_rank_summary.csv"), rk)
    print("\nrank tables: windows", meta["windows"], "bounds")
    for w in meta["windows"]:
        sub = [r for r in rk if r["window"] == w]
        print(f"  {w}: set x exit cells {len(sub)}, eligible settings {sum(r['eligible'] for r in sub)}, "
              f"positive after costs {sum(r['positive'] for r in sub)}, picks beating luck {sum(r['beats_luck'] for r in sub)}")
        top = sorted([r for r in sub if r["eligible"]], key=lambda r: -r["best_mean_R"])[:6]
        for r in top:
            print(f"     {r['set']} {r['exit']}: best {r['best_mean_R']:+.3f}R median {r['median_mean_R']:+.3f}R pos {r['positive']}/{r['eligible']} "
                  f"pick {r['pick_mean_R']:+.3f}R n {r['pick_n']} luck95 {r['luck95']:+.3f}")
    reg = regime(a.snap, accts)
    write_csv(os.path.join(a.out, "demo_regime.csv"), reg)
    print("\nregime (all lines pooled):")
    for r in reg:
        if r["kind"] in ("all", "flip"):
            print("  ", r)
    v = vs5y(a.snap)
    write_csv(os.path.join(a.out, "demo_vs5y.csv"), v)
    print("\nfamilies vs fixed default (equity):", json.dumps(pair_compare(rows), ensure_ascii=False))
    print("live vs 5-year mean R per line:", json.dumps(vs5y_corr(v)))
    try:
        cs = json.load(open(os.path.join(a.snap, "costs.json")))
        ln = cs["lines"]
        print(f"order-book cost: mean {np.mean([x['mean_cost_bps'] for x in ln if x.get('mean_cost_bps') is not None]):.2f} bps vs assumed "
              f"{cs['assumed_bps']} bps; P&L {sum(x['pnl'] for x in ln):,.0f} -> with real book cost {sum(x['pnl_adj'] for x in ln):,.0f}")
        jd = json.load(open(os.path.join(a.snap, "judge.json")))
        print("judge:", jd["verdict_ko"], "| lines", jd["lines_judged"], "| confirming", len(jd["confirm"]), "| candidates", len(jd["candidates"]))
    except (OSError, KeyError) as e:
        print("costs/judge:", e)
    dr = drift(a.db, live0, t_end)
    print("\nprice change of the coins (live window / history to live start, %):", {k: (round(x["live"], 1), round(x["hist"], 1)) for k, x in (dr or {}).items()})
    if not a.no_halves:
        hrows, ctrl, mid = halves(a.db, live0, hist0)
        write_csv(os.path.join(a.out, "demo_settings_by_block.csv.gz"), hrows)
        write_csv(os.path.join(a.out, "demo_random_entry.csv"), ctrl)
        print("settings vs random entries:", json.dumps(vs_random(hrows, ctrl)))
        per = persistence(hrows)
        write_csv(os.path.join(a.out, "demo_persistence.csv"), per)
        print(f"\nhalves: H1 {LO.kst(hist0)} ~ {LO.kst(mid)}, H2 ~ {LO.kst(live0)}, LIVE ~ {LO.kst(t_end)}")
        rho = np.array([p["rho_h1_h2"] for p in per])
        print(f"  set x exit groups {len(per)}; Spearman H1 vs H2 median {np.median(rho):+.2f} (min {rho.min():+.2f}, max {rho.max():+.2f})")
        print(f"  H1 top-10 average percentile in H2: {np.mean([p['top10_h1_pct_in_h2'] for p in per]):.2f} (0.5 = no better than random)")
        print(f"  settings positive in H1: {sum(p['pos_h1'] for p in per)}, H2: {sum(p['pos_h2'] for p in per)}, both: {sum(p['pos_both'] for p in per)} "
              f"(expected if independent {sum(p['pos_both_expected'] for p in per):.0f}) of {sum(p['settings'] for p in per)}")
        lp = [p["top10_h1h2_pct_in_live"] for p in per if np.isfinite(p["top10_h1h2_pct_in_live"])]
        print(f"  26-week (H1+H2) top-10 average percentile LIVE: {np.mean(lp):.2f} over {len(lp)} groups")
        for p in sorted(per, key=lambda p: -p["rho_h1_h2"])[:5]:
            print("   ", {k: (round(x, 3) if isinstance(x, float) else x) for k, x in p.items()})
        print("  random-entry control (every bar, both sides) mean R:")
        for r in ctrl:
            if r["exit"] in ("house", "tp1R_sl1.5atr", "tp2R_sl2atr", "half1R_be_1.5R"):
                print(f"     {r['tf']} {r['block']} {r['exit']}: n {r['n']} mean {r['mean_R']:+.3f}R win {r['win'] * 100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
