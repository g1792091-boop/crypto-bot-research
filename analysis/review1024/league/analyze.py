"""Candidate league (커스텀값봇, server name "후보 리그"): every account's forward record, read-only. Writes out/results.json + CSVs.

    python3 analyze.py --zip LEAGUE_EXPORT.zip --work NEW_EMPTY_DIR [--rulebot-zip PAPERBOT_EXPORT.zip] [--prev-zip OLDER.zip]
                       [--market-cache DIR] [--out DIR]

- The zip is untrusted: unpacked by lg_lib.safe_extract into WORK/league (new, empty), sqlite opened read-only/immutable.
- --rulebot-zip (optional): the rule bot export of the same time; only current/trades.csv and current/accounts.csv are unpacked
  (WORK/rulebot) for the custom-value vs default-value comparison (the owner-exit league has no default-value accounts).
- --prev-zip (optional): an older league export; used only to check that the older record is the same as the start of this one.
- Prices: the six coins' 1-minute bars from data.binance.vision (market.py), cached in --market-cache (default WORK/market).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import zlib

import numpy as np
import pandas as pd

import lg_lib as L
import extras as XT
import market as M

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
READ_1017_CUT = 1792193700000            # 10/16 23:35 UTC: the record the 10/17 report read (docs/live1019-analysis-ko.md 7-3)
READ_1017 = {"trades": 1166, "traded_accounts": 415, "kinds_losing": 24, "kinds": 26,
             "fq_wallet": -0.0130, "ld_wallet": -0.0085, "fqc_wallet": -0.0018, "ldt_wallet": 0.0055,
             "fq_minus_ld": -0.0055}
MIN_N_TEST = 10                           # an account needs this many closed trades for its own luck test
SESSIONS = [("아시아(09~17시)", 9, 17), ("유럽(17~22시)", 17, 22), ("미국(22~06시)", 22, 30), ("새벽(06~09시)", 6, 9)]


def names_ko() -> dict:
    p = os.path.join(REPO, "candleague", "data", "native_ko.json")
    try:
        d = L.read_json(p)["strategies"]
        return {k: v.get("name_ko", k) for k, v in d.items()}
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------------------------------------ DBs
def classify(dbs: list, env: dict) -> tuple:
    cur_name = os.path.basename(env.get("CANDLEAGUE_DB", "league_exits.db"))
    cur = next((d for d in dbs if d["name"] == cur_name), None) or max(dbs, key=lambda d: d["meta"].get("done", 0))
    fp, st = cur["meta"].get("fingerprint"), cur["meta"].get("start_ms")
    rows = []
    for d in dbs:
        m = d["meta"]
        row = {"name": d["name"], "start_ms": m.get("start_ms"), "done_ms": m.get("done"), "fingerprint": (m.get("fingerprint") or "")[:12],
               "accounts": len(d["engines"]), "trades": int(len(d["trades"])),
               "pnl": float(d["trades"]["pnl"].sum()) if len(d["trades"]) else 0.0,
               "open_positions": sum(1 for e in d["engines"].values() if e.get("position")),
               "offered": int(d["day"]["offered"].sum()) if len(d["day"]) else 0,
               "entered": int(d["day"]["entered"].sum()) if len(d["day"]) else 0,
               "rejected": int(d["day"]["rejected"].sum()) if len(d["day"]) else 0}
        if d is cur:
            row["role"] = "current"
        elif m.get("fingerprint") == fp and m.get("start_ms") == st:
            row["role"] = "backup"
            row["same_as_current_prefix"] = prefix_same(d, cur)
        else:
            row["role"] = "set_aside"
            sfx = {}
            for a in d["engines"]:
                p = L.parse_id(a)
                if p:
                    sfx[p["suffix"]] = sfx.get(p["suffix"], 0) + 1
            row["kinds"] = sfx
            row["open_detail"] = [{"account": a, "symbol": e["position"]["symbol"], "side": e["position"]["side"],
                                   "lev": e["position"].get("leverage")} for a, e in d["engines"].items() if e.get("position")][:20]
            if len(d["trades"]):
                row["trade_detail"] = d["trades"][["account", "symbol", "side", "leverage", "exit_reason", "pnl", "roe"]].to_dict("records")
        rows.append(row)
    # set-aside leagues: the longest record of a fingerprint is that league, the shorter ones its copies
    sa = [(r, d) for r, d in zip(rows, dbs) if r["role"] == "set_aside"]
    for r, d in sa:
        same = [(r2, d2) for r2, d2 in sa if d2["meta"].get("fingerprint") == d["meta"].get("fingerprint")]
        main = max(same, key=lambda x: x[1]["meta"].get("done", 0))
        if main[1] is not d:
            r["role"] = "set_aside_copy"
            r["copy_of"] = main[1]["name"]
            r["same_as_prefix"] = prefix_same(d, main[1])
    rows.sort(key=lambda r: (r["role"] != "current", r["start_ms"] or 0, r["done_ms"] or 0))
    return cur, rows


def prefix_same(old: dict, cur: dict) -> dict:
    """Is the older DB the same record as the start of the current one (same trades, same money)?"""
    key = ["account", "entry_time", "symbol", "side"]
    a = old["trades"]
    b = cur["trades"]
    done = old["meta"].get("done", 0)
    if len(a) == 0:
        bb = b[b["exit_time"] < done] if len(b) else b
        return {"old_trades": 0, "current_trades_before": int(len(bb)), "same": len(bb) == 0}
    bb = b[b["exit_time"] <= a["exit_time"].max()]
    ia, ib = a.set_index(key)["pnl"], bb.set_index(key)["pnl"]
    common = ia.index.intersection(ib.index)
    diff = float((ia.loc[common] - ib.loc[common]).abs().max()) if len(common) else 0.0
    same = len(common) == len(ia) == len(ib) and diff < 1e-6
    return {"old_trades": int(len(ia)), "current_trades_before": int(len(ib)), "common": int(len(common)), "max_pnl_diff": diff, "same": bool(same)}


# ------------------------------------------------------------------------------------------------ market
def market_block(t: pd.DataFrame, start_ms: int, done_ms: int, last_close: dict, cache: str) -> tuple:
    d0 = time.strftime("%Y-%m-%d", time.gmtime(start_ms / 1000))
    d1 = time.strftime("%Y-%m-%d", time.gmtime(done_ms / 1000))
    try:
        bars, missing = M.load(d0, d1, cache)
    except Exception as e:  # noqa: BLE001  no prices: the rest of the report still works
        return {"error": f"{type(e).__name__}: {e}"}, t
    out = {"coins": [], "days": [], "missing_days": sorted({d for _s, d in missing}), "archive_end_ms": None}
    ends = []
    for s in L.SYMBOLS:
        df = bars.get(s)
        if df is None:
            continue
        ends.append(int(df["t"].max()) + 60_000)
        p0 = M.price_at(df, start_ms, "o")
        p1 = last_close.get(s)
        hi = float(df[(df.t >= start_ms) & (df.t < done_ms)]["h"].max())
        lo = float(df[(df.t >= start_ms) & (df.t < done_ms)]["l"].min())
        out["coins"].append({"symbol": s, "start": p0, "end": p1, "ret": (p1 / p0 - 1) if (p0 and p1) else None,
                             "high": hi, "low": lo})
    out["archive_end_ms"] = min(ends) if ends else None
    rets = [c["ret"] for c in out["coins"] if c["ret"] is not None]
    out["index_ret"] = float(np.mean(rets)) if rets else None
    # day by day (UTC day = KST 09:00 .. 09:00), equal-weight index of the six coins
    day = (start_ms // L.DAY_MS) * L.DAY_MS
    while day < done_ms:
        a, b = max(day, start_ms), min(day + L.DAY_MS, done_ms)
        r = {}
        for s in L.SYMBOLS:
            df = bars.get(s)
            if df is None:
                continue
            p0 = M.price_at(df, a, "o")
            p1 = M.price_at(df, b, "o") if b <= out["archive_end_ms"] else (last_close.get(s) if b >= done_ms else None)
            if p0 and p1:
                r[s] = p1 / p0 - 1
        out["days"].append({"day": day, "from_ms": a, "to_ms": b, "coins": r, "index": float(np.mean(list(r.values()))) if r else None})
        day += L.DAY_MS
    # BTC 4h trend share (close above EMA50 of 4h closes) over the period
    btc = bars.get("BTCUSDT")
    if btc is not None:
        c4 = btc.assign(b=(btc.t // (4 * 3600_000))).groupby("b")["c"].last()
        out["btc_4h_bars"] = int(((c4.index * 4 * 3600_000 >= start_ms)).sum())
    # each trade: the six-coin index move between its entry and exit (market part of its result)
    idx = np.zeros(len(t))
    cnt = np.zeros(len(t))
    for s in L.SYMBOLS:
        df = bars.get(s)
        if df is None:
            continue
        tt, oo = df["t"].values, df["o"].values
        i0 = np.searchsorted(tt, t["entry_time"].values, side="right") - 1
        i1 = np.searchsorted(tt, t["exit_time"].values + 1, side="right") - 1
        ok = (i0 >= 0) & (i1 >= 0) & (t["exit_time"].values + 1 <= tt[-1]) & (t["entry_time"].values >= tt[0])
        ok &= (t["entry_time"].values - tt[np.clip(i0, 0, None)] < 180_000) & (t["exit_time"].values + 1 - tt[np.clip(i1, 0, None)] < 180_000)
        r = np.where(ok, oo[np.clip(i1, 0, None)] / oo[np.clip(i0, 0, None)] - 1, np.nan)
        good = np.isfinite(r)
        idx[good] += r[good]
        cnt[good] += 1
    t = t.copy()
    t["idx_ret"] = np.where(cnt == len(L.SYMBOLS), idx / np.maximum(cnt, 1), np.nan)
    t["mkt_usd"] = t["side"] * t["idx_ret"] * t["notional"]
    t["resid_usd"] = t["gross"] - t["mkt_usd"]
    out["trades_with_index"] = int(t["idx_ret"].notna().sum())
    return out, t


# ------------------------------------------------------------------------------------------------ accounts
def account_rows(cur: dict, cands: dict, nko: dict) -> pd.DataFrame:
    t = cur["trades"]
    meta = cur["meta"]
    start, done = meta["start_ms"], meta["done"]
    mid = (start + done) / 2
    last3 = done - 3 * L.DAY_MS
    unreal = L.unrealized(cur["engines"], cur["last_close"])
    day = cur["day"].groupby("account")[["offered", "entered", "skipped", "rejected", "closed"]].sum()
    g_all = dict(tuple(t.groupby("account"))) if len(t) else {}
    rows = []
    for a, e in cur["engines"].items():
        p = L.parse_id(a) or {}
        g = g_all.get(a)
        cand = cands.get(p.get("pick"), {})
        r = {"account": a, "pick": p.get("pick"), "pool": p.get("pool"), "strategy": p.get("strategy"),
             "strategy_ko": nko.get(p.get("strategy"), p.get("strategy")), "tf": p.get("tf"), "suffix": p.get("suffix"),
             "kind_ko": L.KINDS.get(p.get("suffix"), ("?",))[0], "group": L.KINDS.get(p.get("suffix"), ("", "?"))[1],
             "tier": cand.get("source", {}).get("tier", "watch"), "cand_exit": cand.get("exit"),
             "wallet": float(e["wallet"]), "unreal": float(unreal.get(a, 0.0)), "open": bool(e.get("position")),
             "mdd_engine": float(e.get("max_drawdown", 0.0)), "bust": bool(e.get("bust"))}
        r["equity"] = r["wallet"] + r["unreal"]
        r["ret"] = r["equity"] / L.EQUITY0 - 1
        for k in ("offered", "entered", "skipped", "rejected", "closed"):
            r[k] = int(day.loc[a, k]) if a in day.index else 0
        if g is None or len(g) == 0:
            r.update(n=0)
            rows.append(r)
            continue
        g = g.sort_values("exit_time")
        pnl = g["pnl"].values
        w = pnl > 0
        r.update(
            n=int(len(g)), wins=int(w.sum()), win_rate=float(w.mean()),
            avg_win_roe=float(g.loc[w, "roe"].mean()) if w.any() else None,
            avg_loss_roe=float(g.loc[~w, "roe"].mean()) if (~w).any() else None,
            avg_win_usd=float(pnl[w].mean()) if w.any() else None, avg_loss_usd=float(pnl[~w].mean()) if (~w).any() else None,
            pf=L.profit_factor(pnl), pnl=float(pnl.sum()), mean_roe=float(g["roe"].mean()),
            mean_wallet=float(g["wallet_ret"].mean()), mean_r=float(g["net_r"].mean()),
            med_hold_h=float(g["hold_h"].median()), lev_mean=float(g["leverage"].mean()),
            mdd_closed=L.max_drawdown(g["equity_after"].values), loss_streak=L.longest_streak(w, False),
            win_streak=L.longest_streak(w, True),
            n_long=int((g["side"] > 0).sum()), n_short=int((g["side"] < 0).sum()),
            pnl_long=float(g.loc[g["side"] > 0, "pnl"].sum()), pnl_short=float(g.loc[g["side"] < 0, "pnl"].sum()),
            n_h1=int((g["exit_time"] < mid).sum()), n_h2=int((g["exit_time"] >= mid).sum()),
            pnl_h1=float(g.loc[g["exit_time"] < mid, "pnl"].sum()), pnl_h2=float(g.loc[g["exit_time"] >= mid, "pnl"].sum()),
            wal_h1=float(g.loc[g["exit_time"] < mid, "wallet_ret"].mean()) if (g["exit_time"] < mid).any() else None,
            wal_h2=float(g.loc[g["exit_time"] >= mid, "wallet_ret"].mean()) if (g["exit_time"] >= mid).any() else None,
            n_last3=int((g["exit_time"] >= last3).sum()), pnl_last3=float(g.loc[g["exit_time"] >= last3, "pnl"].sum()),
            fees=float(g["fees"].sum()), slip=float(g["slip_cost"].sum()), funding=float(g["funding"].sum()),
            gross=float(g["gross"].sum()), mkt_usd=float(g["mkt_usd"].sum()) if "mkt_usd" in g else None,
            n_lock=int((g["exit_reason"] == "LOCK").sum()), n_sl=int((g["exit_reason"] == "SL").sum()),
            n_rule=int((g["exit_reason"] == "RULE").sum()), n_tp=int((g["exit_reason"] == "TP").sum()),
            n_liq=int((g["exit_reason"] == "LIQ").sum()),
            worst_wallet=float(g["wallet_ret"].min()), best_wallet=float(g["wallet_ret"].max()),
            stop_pct_med=float(g["stop_pct"].median()),
        )
        if r["n"] >= MIN_N_TEST:
            b = L.boot_mean(g["day"].values, g["wallet_ret"].values, seed=L.SEED + zlib.crc32(a.encode()) % 1000)
            r.update(p_pos=b["p_pos"], ci_lo=b["lo"], ci_hi=b["hi"], n_days=b["days"])
        rows.append(r)
    df = pd.DataFrame(rows)
    tested = df["p_pos"].notna() if "p_pos" in df else pd.Series(False, index=df.index)
    q = L.bh(df.loc[tested, "p_pos"].tolist()) if tested.any() else []
    df["q"] = None
    if tested.any():
        df.loc[tested, "q"] = q
    return df


# ------------------------------------------------------------------------------------------------ group tables
def agg(t: pd.DataFrame) -> dict:
    if len(t) == 0:
        return {"n": 0}
    pnl = t["pnl"].values
    return {"n": int(len(t)), "win": float((pnl > 0).mean()), "mean_roe": float(t["roe"].mean()),
            "mean_wallet": float(t["wallet_ret"].mean()), "mean_r": float(t["net_r"].mean()), "pnl": float(pnl.sum()),
            "pf": L.profit_factor(pnl), "fees": float(t["fees"].sum()), "slip": float(t["slip_cost"].sum()),
            "funding": float(t["funding"].sum()), "gross": float(t["gross"].sum()),
            "short_share": float((t["side"] < 0).mean()), "med_hold_h": float(t["hold_h"].median())}


def by(t: pd.DataFrame, key, order=None) -> list:
    rows = []
    keys = order if order is not None else sorted(t[key].dropna().unique().tolist())
    for k in keys:
        g = t[t[key] == k]
        if len(g) == 0:
            continue
        r = {"key": k, "all": agg(g)}
        for name, sfx in (("ld", ["ld"]), ("fq", ["fq"]), ("coin", ["fqc", "ldc"])):
            r[name] = agg(g[g["suffix"].isin(sfx)])
        rows.append(r)
    return rows


def kinds_table(t: pd.DataFrame, acc: pd.DataFrame) -> list:
    rows = []
    for sfx in L.KIND_ORDER:
        a = acc[acc["suffix"] == sfx]
        g = t[t["suffix"] == sfx]
        r = {"suffix": sfx, "name": L.KINDS[sfx][0], "group": L.KINDS[sfx][1], "desc": L.KINDS[sfx][2],
             "accounts": int(len(a)), "traded": int((a["n"] > 0).sum()), "pos_accounts": int((a["ret"] > 0).sum()),
             "neg_accounts": int((a["ret"] < 0).sum()), "unreal": float(a["unreal"].sum()),
             "total": float((a["equity"] - L.EQUITY0).sum()), "ret_med_traded": float(a.loc[a["n"] > 0, "ret"].median()) if (a["n"] > 0).any() else None,
             "ret_mean_all": float(a["ret"].mean()), "mdd_med": float(a.loc[a["n"] > 0, "mdd_engine"].median()) if (a["n"] > 0).any() else None,
             "offered": int(a["offered"].sum()), "entered": int(a["entered"].sum()), "skipped": int(a["skipped"].sum()),
             "rejected": int(a["rejected"].sum()), "busts": int(a["bust"].sum())}
        r.update(agg(g))
        if len(g):
            b = L.boot_mean(g["day"].values, g["wallet_ret"].values)
            r.update(ci_lo=b["lo"], ci_hi=b["hi"], p_pos=b["p_pos"], n_days=b["days"])
            if "mkt_usd" in g:
                r.update(mkt_usd=float(g["mkt_usd"].sum(skipna=True)), resid_usd=float(g["resid_usd"].sum(skipna=True)),
                         n_mkt=int(g["mkt_usd"].notna().sum()))
            best = a.sort_values("ret").iloc[-1]
            worst = a.sort_values("ret").iloc[0]
            r.update(best=best["account"], best_ret=float(best["ret"]), worst=worst["account"], worst_ret=float(worst["ret"]))
        rows.append(r)
    return rows


# ------------------------------------------------------------------------------------------------ same-signal pairs
def pairs(t: pd.DataFrame, a: str, b: str, coin: bool = False) -> pd.DataFrame:
    key = ["pick", "symbol", "entry_time"] + ([] if coin else ["side"])
    cols = key + ["roe", "wallet_ret", "pnl", "exit_time", "day", "side", "net_r", "hold_h"]
    x = t[t["suffix"] == a][list(dict.fromkeys(cols))]
    y = t[t["suffix"] == b][list(dict.fromkeys(cols))]
    m = x.merge(y, on=key, suffixes=("_a", "_b"))
    if coin and "side_a" not in m:
        m["side_a"] = m["side"]
    m["d_roe"] = m["roe_a"] - m["roe_b"]
    m["d_wallet"] = m["wallet_ret_a"] - m["wallet_ret_b"]
    m["d_pnl"] = m["pnl_a"] - m["pnl_b"]
    m["day"] = m["day_a"]
    return m.sort_values("exit_time_a")


def pair_stats(m: pd.DataFrame, seed: int) -> dict:
    if len(m) == 0:
        return {"n": 0}
    tol = 0.0005                     # candleague/summary.py SAME_DIFF: |ROE difference| under 0.05 points of margin is 'same'
    out = {"n": int(len(m)), "n_days": int(m["day"].nunique()),
           "mean_d_roe": float(m["d_roe"].mean()), "mean_d_wallet": float(m["d_wallet"].mean()), "sum_d_pnl": float(m["d_pnl"].sum()),
           "better": int((m["d_roe"] >= tol).sum()), "worse": int((m["d_roe"] <= -tol).sum()),
           "same": int((m["d_roe"].abs() < tol).sum())}
    b = L.boot_mean(m["day"].values, m["d_wallet"].values, seed=seed)
    out.update(ci_lo=b["lo"], ci_hi=b["hi"])
    br = L.boot_mean(m["day"].values, m["d_roe"].values, seed=seed)
    out.update(ci_lo_roe=br["lo"], ci_hi_roe=br["hi"])
    dz = np.where(m["d_roe"].abs() < tol, 0.0, m["d_wallet"].values)       # 'same' trades (same exit, rounding only) count as 0
    pg = L.signflip_p(m["day"].values, dz)
    pl = L.signflip_p(m["day"].values, -dz)
    out.update(p_better=pg, p_worse=pl, p2=(min(1.0, 2 * min(pg, pl)) if pg is not None else None))
    h = len(m) // 2
    out.update(half1=float(m["d_wallet"].iloc[:h].mean()) if h else None, half2=float(m["d_wallet"].iloc[h:].mean()))
    return out


def variant_block(t: pd.DataFrame, acc: pd.DataFrame) -> dict:
    rows = []
    for v, c in L.CONTROL_OF.items():
        m = pairs(t, v, c)
        s = pair_stats(m, L.SEED + len(v) * 7 + len(c))
        s.update(variant=v, control=c, name=L.KINDS[v][0], control_name=L.KINDS[c][0])
        # account-level (all trades, not only shared signals): per pick total result, variant vs control
        av = acc[acc["suffix"] == v].set_index("pick")
        ac = acc[acc["suffix"] == c].set_index("pick")
        common = av.index.intersection(ac.index)
        both = [p for p in common if av.loc[p, "n"] > 0 or ac.loc[p, "n"] > 0]
        s.update(picks=len(both), picks_better=int(sum(av.loc[p, "ret"] > ac.loc[p, "ret"] + 1e-9 for p in both)),
                 picks_worse=int(sum(av.loc[p, "ret"] < ac.loc[p, "ret"] - 1e-9 for p in both)),
                 total_v=float((av.loc[common, "equity"] - L.EQUITY0).sum()), total_c=float((ac.loc[common, "equity"] - L.EQUITY0).sum()))
        rows.append(s)
    # a filter (or the weekend switch) has the same exit as its base: on shared signals the difference is 0 by construction, so those
    # comparisons are shown but kept out of the correction's family (their effect is which signals they drop: protocol test 4)
    same_exit = {"fqt", "fqv", "ldt", "ldv", "wk"}
    for r in rows:
        r["same_exit"] = r["variant"] in same_exit
    fam = [i for i, r in enumerate(rows) if not r["same_exit"]]
    q = L.bh([rows[i].get("p2") for i in fam])
    for r in rows:
        r["q"] = None
    for i, qq in zip(fam, q):
        rows[i]["q"] = qq
    return {"rows": rows, "family": len(fam)}


def coin_block(t: pd.DataFrame, acc: pd.DataFrame) -> dict:
    out = {"kinds": [], "picks": []}
    for real, coin in (("fq", "fqc"), ("ld", "ldc")):
        m = pairs(t, real, coin, coin=True)
        s = pair_stats(m, L.SEED + 11 + len(real))
        s.update(real=real, coin=coin)
        ar = acc[acc["suffix"] == real].set_index("pick")
        ac = acc[acc["suffix"] == coin].set_index("pick")
        both = [p for p in ar.index if p in ac.index and (ar.loc[p, "n"] > 0 or ac.loc[p, "n"] > 0)]
        s.update(picks=len(both), picks_better=int(sum(ar.loc[p, "ret"] > ac.loc[p, "ret"] + 1e-9 for p in both)),
                 picks_worse=int(sum(ar.loc[p, "ret"] < ac.loc[p, "ret"] - 1e-9 for p in both)))
        # how often the real side and the coin side agreed (same direction), and their results by agreement
        if len(m):
            agree = m["side_a"] == m["side_b"]
            s.update(agree_share=float(agree.mean()), d_wallet_disagree=float(m.loc[~agree, "d_wallet"].mean()) if (~agree).any() else None,
                     n_disagree=int((~agree).sum()))
        out["kinds"].append(s)
        for p, g in m.groupby("pick"):
            ps = pair_stats(g, L.SEED + 13)
            ps.update(pick=p, real=real, real_ret=float(ar.loc[p, "ret"]) if p in ar.index else None,
                      coin_ret=float(ac.loc[p, "ret"]) if p in ac.index else None)
            out["picks"].append(ps)
    q = L.bh([r.get("p2") for r in out["picks"]])
    for r, qq in zip(out["picks"], q):
        r["q"] = qq
    # luck reference: coin-flip accounts' own totals
    coins = acc[acc["suffix"].isin(["fqc", "ldc"]) & (acc["n"] > 0)]["ret"]
    out["coin_ret"] = {"n": int(len(coins)), "max": float(coins.max()) if len(coins) else None,
                       "p90": float(coins.quantile(0.9)) if len(coins) else None, "median": float(coins.median()) if len(coins) else None,
                       "pos": int((coins > 0).sum())}
    return out


def protocol_block(t: pd.DataFrame, snap_decision: dict | None) -> dict:
    """The league's own four pre-set decision comparisons (docs/candleague-decision-protocol-ko.md), recomputed here."""
    rows = []

    def boot(days, x, kept=None, seed=0):
        u = np.unique(days)
        rng = np.random.default_rng(seed)
        bs = []
        for _ in range(2000):
            pick = rng.choice(u, size=len(u), replace=True)
            sel = np.concatenate([np.flatnonzero(days == d) for d in pick])
            if kept is None:
                bs.append(x[sel].mean())
            else:
                k = kept[sel]
                if k.any() and (~k).any():
                    bs.append(x[sel][k].mean() - x[sel][~k].mean())
        bs = np.array(bs)
        return float(np.quantile(bs, 0.05)), float(np.quantile(bs, 0.95)), float((1 + (bs <= 0).sum()) / (len(bs) + 1))

    for name, a, b, coin in (("① 빠른 손절 − 대조", "fq", "ld", False), ("② 빠른 손절 − 그 동전 짝", "fq", "fqc", True),
                             ("③ 대조 − 그 동전 짝", "ld", "ldc", True)):
        m = pairs(t, a, b, coin=coin)
        if len(m) == 0:
            rows.append({"name": name, "n": 0})
            continue
        lo, hi, p = boot(m["day"].values, m["d_roe"].values, seed=17)
        h = len(m) // 2
        rows.append({"name": name, "n": int(len(m)), "n_days": int(m["day"].nunique()), "mean": float(m["d_roe"].mean()), "lo": lo, "hi": hi,
                     "p": p, "half1": float(m["d_roe"].iloc[:h].mean()), "half2": float(m["d_roe"].iloc[h:].mean())})
    key = ["pick", "symbol", "side", "entry_time"]
    ld = t[t["suffix"] == "ld"].sort_values("exit_time")
    took = set(map(tuple, t[t["suffix"] == "ldt"][key].values.tolist()))
    kept = np.array([tuple(x) in took for x in ld[key].values.tolist()])
    x = ld["roe"].values
    lo, hi, p = boot(ld["day"].values, x, kept=kept, seed=19)
    h = len(ld) // 2
    k1, k2 = kept[:h], kept[h:]
    rows.append({"name": "④ BTC 추세 필터가 남긴 신호 − 버린 신호(대조 기준)", "n": int(min(kept.sum(), (~kept).sum())), "n_kept": int(kept.sum()),
                 "n_dropped": int((~kept).sum()), "mean": float(x[kept].mean() - x[~kept].mean()), "lo": lo, "hi": hi, "p": p,
                 "mean_kept": float(x[kept].mean()), "mean_dropped": float(x[~kept].mean()),
                 "half1": float(x[:h][k1].mean() - x[:h][~k1].mean()), "half2": float(x[h:][k2].mean() - x[h:][~k2].mean()),
                 "n_days": int(ld["day"].nunique())})
    hp = L.holm([r.get("p") for r in rows])
    for r, q in zip(rows, hp):
        r["p_holm"] = q
        r["pass_now"] = bool(r.get("n", 0) >= 300 and q is not None and q < 0.05 and r["mean"] > 0
                            and (r.get("half1") or 0) > 0 and (r.get("half2") or 0) > 0)
    snap_rows = []
    if snap_decision:
        for r in snap_decision.get("rows", []):
            if r.get("primary"):
                snap_rows.append({k: r.get(k) for k in ("suffix", "vs_suffix", "test", "n", "n_days", "mean_diff", "ci_lo", "ci_hi",
                                                        "p_one_sided", "p_holm", "half1", "half2", "verdict_ko")})
    return {"rows": rows, "snapshot": snap_rows, "days": (snap_decision or {}).get("days"),
            "decide_ms": (snap_decision or {}).get("decide_ms"), "observe_ms": (snap_decision or {}).get("observe_ms")}


# ------------------------------------------------------------------------------------------------ custom vs default (rule bot)
def rulebot_block(rb_dir: str, t: pd.DataFrame, start: int, done: int, nko: dict) -> dict:
    path = os.path.join(rb_dir, "current", "trades.csv")
    if not os.path.exists(path):
        return {"error": "규칙봇 거래 파일 없음"}
    cols = ["account_id", "strategy_id", "symbol", "timeframe", "side", "entry_time", "entry_price", "exit_time", "exit_price",
            "exit_reason", "qty", "leverage", "margin", "fees", "funding", "pnl", "roe", "equity_after", "stop_initial"]
    rb = pd.read_csv(path, usecols=cols)
    rb_end = int(rb["exit_time"].max())
    rb = rb[(rb["entry_time"] >= start) & (rb["exit_time"] <= done)].copy()
    rb["wallet_ret"] = rb["pnl"] / (rb["equity_after"] - rb["pnl"])
    risk = (rb["entry_price"] - rb["stop_initial"]).abs() * rb["qty"]
    rb["net_r"] = rb["pnl"] / risk.where(risk > 0)
    rb["day"] = (rb["exit_time"] // L.DAY_MS) * L.DAY_MS
    lg = t[(t["suffix"] == "ld") & (t["exit_time"] <= rb_end)].copy()
    picks = sorted(lg["pick"].unique().tolist() + [p for p in t["pick"].unique() if p not in set(lg["pick"])])
    rows = []
    allc, alld = [], []
    for p in sorted(set(t["pick"].unique())):
        info = L.parse_id(p + "-ld")
        acct = f"{info['strategy']}@{info['tf']}"
        c = lg[lg["pick"] == p]
        d = rb[rb["account_id"] == acct]
        r = {"pick": p, "rb_account": acct, "strategy_ko": nko.get(info["strategy"], info["strategy"]), "n_custom": int(len(c)),
             "n_default": int(len(d)), "r_custom": float(c["net_r"].mean()) if len(c) else None,
             "r_default": float(d["net_r"].mean()) if len(d) else None,
             "w_custom": float(c["wallet_ret"].mean()) if len(c) else None, "w_default": float(d["wallet_ret"].mean()) if len(d) else None,
             "win_custom": float((c["pnl"] > 0).mean()) if len(c) else None, "win_default": float((d["pnl"] > 0).mean()) if len(d) else None}
        if len(c) and len(d):
            b = L.boot_diff_two(c["day"].values, c["net_r"].values, d["day"].values, d["net_r"].values, seed=L.SEED + len(p))
            r.update(diff_r=b["diff"], lo=b["lo"], hi=b["hi"], p_pos=b["p_pos"])
            if b["p_pos"] is not None:
                r["p2"] = min(1.0, 2 * min(b["p_pos"], 1 - b["p_pos"] + 1 / 4001))
        # the same signal in both (same coin, side and entry minute): custom and default fired together
        if len(c) and len(d):
            mm = c.merge(d, on=["symbol", "side", "entry_time"], suffixes=("_c", "_d"))
            r["same_signal"] = int(len(mm))
        allc.append(c.assign(pick=p))
        alld.append(d.assign(pick=p))
        rows.append(r)
    q = L.bh([r.get("p2") for r in rows])
    for r, qq in zip(rows, q):
        r["q"] = qq
    C = pd.concat(allc) if allc else pd.DataFrame()
    D = pd.concat(alld) if alld else pd.DataFrame()
    pooled = L.boot_diff_two(C["day"].values, C["net_r"].values, D["day"].values, D["net_r"].values) if len(C) and len(D) else {}
    pooled_w = L.boot_diff_two(C["day"].values, C["wallet_ret"].values, D["day"].values, D["wallet_ret"].values) if len(C) and len(D) else {}
    days = (done - start) / L.DAY_MS
    return {"rows": rows, "pooled_r": pooled, "pooled_wallet": pooled_w, "n_custom": int(len(C)), "n_default": int(len(D)),
            "per_day_custom": len(C) / days, "per_day_default": len(D) / days, "rb_end_ms": rb_end,
            "rb_lev": D["leverage"].value_counts().to_dict() if len(D) else {},
            "mean_r_custom": float(C["net_r"].mean()) if len(C) else None, "mean_r_default": float(D["net_r"].mean()) if len(D) else None,
            "win_custom": float((C["pnl"] > 0).mean()) if len(C) else None, "win_default": float((D["pnl"] > 0).mean()) if len(D) else None,
            "picks_better": int(sum(1 for r in rows if r.get("diff_r") is not None and r["diff_r"] > 0)),
            "picks_compared": int(sum(1 for r in rows if r.get("diff_r") is not None))}


# ------------------------------------------------------------------------------------------------ stability
def stability_block(t: pd.DataFrame, acc: pd.DataFrame, start: int, done: int, mkt: dict) -> dict:
    out = {}
    mid = (start + done) / 2
    out["mid_ms"] = mid
    rows = []
    for sfx in L.KIND_ORDER:
        g = t[t["suffix"] == sfx]
        rows.append({"suffix": sfx, "name": L.KINDS[sfx][0],
                     "h1": agg(g[g["exit_time"] < mid]), "h2": agg(g[g["exit_time"] >= mid]),
                     "last3": agg(g[g["exit_time"] >= done - 3 * L.DAY_MS])})
    out["kinds_halves"] = rows
    a = acc[(acc["n_h1"].fillna(0) >= 5) & (acc["n_h2"].fillna(0) >= 5)]
    out["rank_corr_halves"] = L.spearman(a["wal_h1"], a["wal_h2"])
    out["rank_corr_n"] = int(len(a))
    top = a.sort_values("wal_h1", ascending=False).head(10)
    out["top10_h1"] = top[["account", "wal_h1", "wal_h2", "pnl_h1", "pnl_h2"]].to_dict("records")
    out["top10_h1_pos_h2"] = int((top["pnl_h2"] > 0).sum())
    out["both_halves_pos"] = int(((acc["pnl_h1"].fillna(0) > 0) & (acc["pnl_h2"].fillna(0) > 0) & (acc["n"].fillna(0) >= 10)).sum())
    out["n10"] = int((acc["n"].fillna(0) >= 10).sum())
    # day by day
    days = []
    mk = {d["day"]: d for d in (mkt.get("days") or [])} if isinstance(mkt, dict) else {}
    for d, g in t.groupby("day"):
        r = {"day": int(d), "all": agg(g), "index": (mk.get(d) or {}).get("index"), "coins": (mk.get(d) or {}).get("coins")}
        for sfx in ("fq", "ld", "fqc", "ldc", "ldt", "sw", "tp10", "l5"):
            r[sfx] = agg(g[g["suffix"] == sfx])
        days.append(r)
    out["days"] = days
    return out


# ------------------------------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--work", required=True, help="새 빈 폴더 (압축을 여기에 풉니다)")
    ap.add_argument("--rulebot-zip")
    ap.add_argument("--prev-zip")
    ap.add_argument("--market-cache")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--exports", default=HERE, help="daily_pnl.csv · trades_norm.csv 를 쓸 폴더")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    work = os.path.abspath(a.work)
    hashes = L.safe_extract(a.zip, os.path.join(work, "league"))
    base = os.path.join(work, "league")
    env = {}
    envf = os.path.join(base, "etc", "candleague_env_safe.txt")
    if os.path.exists(envf):
        for ln in open(envf, encoding="utf-8"):
            if "=" in ln:
                k, v = ln.strip().split("=", 1)
                env[k] = v
    manifest = open(os.path.join(base, "manifest.txt"), encoding="utf-8").read().splitlines() if os.path.exists(os.path.join(base, "manifest.txt")) else []
    dbs = [L.load_db(p) for p in sorted(glob.glob(os.path.join(base, "db", "*.db")))]
    cur, db_rows = classify(dbs, env)
    cands = {c["id"]: c for c in L.read_json(os.path.join(base, "etc", "candidates.json"))["candidates"]}
    rules = L.read_json(os.path.join(base, "etc", "rules.json"))
    snap = L.read_json(os.path.join(base, "snap", "league.json")) if os.path.exists(os.path.join(base, "snap", "league.json")) else {}
    nko = names_ko()
    meta = cur["meta"]
    start, done = int(meta["start_ms"]), int(meta["done"])
    t = cur["trades"]
    # market
    cache = a.market_cache or os.path.join(work, "market")
    mkt, t = market_block(t, start, done, cur["last_close"], cache)
    cur["trades"] = t
    acc = account_rows(cur, cands, nko)
    res = {"generated_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "zip": os.path.basename(a.zip),
           "zip_manifest": manifest[:1], "env": env, "hashes": hashes, "dbs": db_rows,
           "period": {"start_ms": start, "done_ms": done, "days": (done - start) / L.DAY_MS,
                      "first_exit": int(t["exit_time"].min()), "last_exit": int(t["exit_time"].max())},
           "rules_kinds": [o["suffix"] for o in rules.get("owner_exits", [])], "n_cands": len(cands),
           "cands_tier": {"watch": sum(1 for c in cands.values() if c.get("source", {}).get("watch")),
                          "weak": sum(1 for c in cands.values() if c.get("source", {}).get("tier") == "weak")},
           "market": mkt}
    # coverage
    res["coverage"] = {"accounts": int(len(acc)), "traded": int((acc["n"] > 0).sum()), "trades": int(len(t)),
                       "open": int(acc["open"].sum()), "core_accounts": int((acc["pool"] == "core").sum()),
                       "ds_accounts": int((acc["pool"] == "ds").sum()),
                       "by_group": acc.groupby("group").size().to_dict(),
                       "picks": int(acc["pick"].nunique()), "strategies": int(acc["strategy"].nunique()),
                       "offered": int(acc["offered"].sum()), "entered": int(acc["entered"].sum()),
                       "skipped": int(acc["skipped"].sum()), "rejected": int(acc["rejected"].sum())}
    # whole league
    res["league"] = {"realized": float(t["pnl"].sum()), "unreal": float(acc["unreal"].sum()),
                     "total": float((acc["equity"] - L.EQUITY0).sum()), "fees": float(t["fees"].sum()),
                     "slip": float(t["slip_cost"].sum()), "funding": float(t["funding"].sum()), "gross": float(t["gross"].sum()),
                     "pos_accounts": int((acc["ret"] > 0).sum()), "neg_accounts": int((acc["ret"] < 0).sum()),
                     "pos_traded": int(((acc["ret"] > 0) & (acc["n"] > 0)).sum()), "busts": int(acc["bust"].sum()),
                     "mkt_usd": float(t["mkt_usd"].sum(skipna=True)) if "mkt_usd" in t else None,
                     "resid_usd": float(t["resid_usd"].sum(skipna=True)) if "resid_usd" in t else None,
                     "liq": int((t["exit_reason"] == "LIQ").sum()), **agg(t)}
    res["kinds"] = kinds_table(t, acc)
    res["kinds_losing"] = int(sum(1 for k in res["kinds"] if k.get("n", 0) and k["total"] < 0))
    res["kinds_with_trades"] = int(sum(1 for k in res["kinds"] if k.get("n", 0)))
    t["family_ko"] = t["strategy"].map(lambda s: nko.get(s, s))
    res["by_family"] = by(t, "strategy")
    for r in res["by_family"]:
        r["name_ko"] = nko.get(r["key"], r["key"])
        r["pool"] = "core" if any(p.startswith("core-" + r["key"] + "-") for p in cands) else "ds"
    res["by_tf"] = by(t, "tf", L.TF_ORDER)
    res["by_side"] = by(t, "side_ko", ["롱", "숏"])
    res["by_pool"] = by(t, "pool", ["core", "ds"])
    res["by_coin"] = by(t, "symbol", list(L.SYMBOLS))
    t["hour3"] = (t["entry_hour_kst"] // 3) * 3
    res["by_hour"] = by(t, "hour3", [0, 3, 6, 9, 12, 15, 18, 21])

    def sess(h):
        for name, a0, a1 in SESSIONS:
            if a0 <= h < a1 or (a1 > 24 and (h >= a0 or h < a1 - 24)):
                return name
        return "?"
    t["session"] = t["entry_hour_kst"].map(sess)
    res["by_session"] = by(t, "session", [s[0] for s in SESSIONS])
    t["wk_ko"] = np.where(t["weekend"], "주말(토 09시~월 09시)", "평일")
    res["by_weekend"] = by(t, "wk_ko", ["평일", "주말(토 09시~월 09시)"])
    t["dow_ko"] = t["entry_dow_kst"].map(dict(enumerate("월화수목금토일")))
    res["by_dow"] = by(t, "dow_ko", list("월화수목금토일"))
    res["by_exit"] = by(t, "exit_reason", ["LOCK", "SL", "RULE", "TP", "LIQ"])
    res["by_lev"] = by(t, "leverage", sorted(t["leverage"].unique().tolist()))
    res["by_tier"] = by(t, "tier")
    # per pick (49): all kinds together
    pk = []
    for p, g in acc.groupby("pick"):
        tr = g[g["n"] > 0]
        info = L.parse_id(p + "-ld")
        pk.append({"pick": p, "strategy_ko": nko.get(info["strategy"], info["strategy"]), "tf": info["tf"], "pool": info["pool"],
                   "tier": g["tier"].iloc[0], "accounts": int(len(g)), "traded": int(len(tr)), "trades": int(g["n"].sum()),
                   "total": float((g["equity"] - L.EQUITY0).sum()), "kinds_pos": int((tr["ret"] > 0).sum()),
                   "ld_ret": float(g.loc[g["suffix"] == "ld", "ret"].iloc[0]) if (g["suffix"] == "ld").any() else None,
                   "fq_ret": float(g.loc[g["suffix"] == "fq", "ret"].iloc[0]) if (g["suffix"] == "fq").any() else None,
                   "ldc_ret": float(g.loc[g["suffix"] == "ldc", "ret"].iloc[0]) if (g["suffix"] == "ldc").any() else None,
                   "ld_n": int(g.loc[g["suffix"] == "ld", "n"].fillna(0).iloc[0]) if (g["suffix"] == "ld").any() else 0,
                   "fq_n": int(g.loc[g["suffix"] == "fq", "n"].fillna(0).iloc[0]) if (g["suffix"] == "fq").any() else 0,
                   "ldc_n": int(g.loc[g["suffix"] == "ldc", "n"].fillna(0).iloc[0]) if (g["suffix"] == "ldc").any() else 0,
                   "offered_ld": int(g.loc[g["suffix"] == "ld", "offered"].iloc[0]) if (g["suffix"] == "ld").any() else 0,
                   "rejected_ld": int(g.loc[g["suffix"] == "ld", "rejected"].iloc[0]) if (g["suffix"] == "ld").any() else 0,
                   "test_mean_5y": cands.get(p, {}).get("source", {}).get("test_mean"), "test_n_5y": cands.get(p, {}).get("source", {}).get("test_n"),
                   "cand_exit": cands.get(p, {}).get("exit")})
    res["picks"] = pk
    # market explanation per side among coin twins vs real
    res["variants"] = variant_block(t, acc)
    res["coin"] = coin_block(t, acc)
    res["protocol"] = protocol_block(t, snap.get("decision"))
    res["stability"] = stability_block(t, acc, start, done, mkt)
    # luck: accounts tested one by one
    tested = acc[acc["p_pos"].notna()] if "p_pos" in acc else acc.iloc[0:0]
    res["luck"] = {"tested": int(len(tested)), "raw_p05": int((tested["p_pos"] < 0.05).sum()),
                   "expected_by_chance": 0.05 * len(tested), "q05": int((tested["q"].astype(float) < 0.05).sum()),
                   "q10": int((tested["q"].astype(float) < 0.10).sum()), "positive_mean": int((tested["mean_wallet"] > 0).sum()),
                   "raw_p05_accounts": tested[tested["p_pos"] < 0.05].sort_values("p_pos")[["account", "n", "mean_wallet", "p_pos", "q", "ret"]].to_dict("records")}
    # what looks good: positive total, >=10 trades, both halves positive
    good = acc[(acc["ret"] > 0) & (acc["n"].fillna(0) >= 10) & (acc["pnl_h1"].fillna(0) > 0) & (acc["pnl_h2"].fillna(0) > 0)]
    res["good"] = good.sort_values("ret", ascending=False)["account"].tolist()
    # windows: the 10/17 read and everything after it
    cut = READ_1017_CUT
    old = t[t["exit_time"] <= cut]
    new = t[t["exit_time"] > cut]

    def win_kinds(x):
        out = {}
        for sfx in L.KIND_ORDER:
            g = x[x["suffix"] == sfx]
            out[sfx] = agg(g)
        return out
    res["vs1017"] = {"cut_ms": cut, "read": READ_1017, "recomputed": {"trades": int(len(old)), "traded_accounts": int(old["account"].nunique()),
                     "kinds": win_kinds(old)}, "after": {"trades": int(len(new)), "kinds": win_kinds(new), "days": (done - cut) / L.DAY_MS},
                     "kinds_losing_before": int(sum(1 for s in L.KIND_ORDER if len(old[old.suffix == s]) and old[old.suffix == s].pnl.sum() < 0)),
                     "kinds_losing_after": int(sum(1 for s in L.KIND_ORDER if len(new[new.suffix == s]) and new[new.suffix == s].pnl.sum() < 0))}
    # account-level: did the 10/17 leaders stay?
    o_acc = old.groupby("account").agg(n=("pnl", "size"), pnl=("pnl", "sum"))
    n_acc = new.groupby("account").agg(n=("pnl", "size"), pnl=("pnl", "sum"))
    j = o_acc.join(n_acc, lsuffix="_old", rsuffix="_new", how="inner")
    j = j[(j["n_old"] >= 3) & (j["n_new"] >= 3)]
    res["vs1017"]["rank_corr"] = L.spearman(j["pnl_old"], j["pnl_new"])
    res["vs1017"]["rank_n"] = int(len(j))
    top = j.sort_values("pnl_old", ascending=False).head(10)
    res["vs1017"]["top10_old_pos_new"] = int((top["pnl_new"] > 0).sum())
    res["vs1017"]["top10_old"] = top.reset_index()[["account", "n_old", "pnl_old", "n_new", "pnl_new"]].to_dict("records")
    # optional: rule bot (default values)
    if a.rulebot_zip:
        rb_dir = os.path.join(work, "rulebot")
        L.safe_extract(a.rulebot_zip, rb_dir, allowed=(".csv", ".txt"), only={"current/trades.csv", "current/accounts.csv", "manifest.txt"})
        res["custom_vs_default"] = rulebot_block(rb_dir, t, start, done, nko)
    # optional: older export, same record?
    if a.prev_zip:
        pdir = os.path.join(work, "prev")
        L.safe_extract(a.prev_zip, pdir)
        p = os.path.join(pdir, "db", os.path.basename(cur["path"]))
        if os.path.exists(p):
            old_db = L.load_db(p)
            res["prev"] = {"zip": os.path.basename(a.prev_zip), "done_ms": old_db["meta"].get("done"), **prefix_same(old_db, cur)}
            pc = old_db["meta"].get("done")
            seg = t[t["exit_time"] > pc]
            res["prev"]["after"] = {s: agg(seg[seg["suffix"] == s]) for s in L.KIND_ORDER}
            res["prev"]["after_all"] = agg(seg)
            res["prev"]["after_days"] = (done - pc) / L.DAY_MS
    # snapshot extras the dashboard already computed (for cross-checks in the report)
    res["snap"] = {k: snap.get(k, {}).get("headline_ko") for k in ("monthsim", "risk", "losses", "costs", "coins") if isinstance(snap.get(k), dict)}
    # owners' 10/24 evening requests: conditional reads, goal path, flat exports, every other record of the export
    cond = XT.cond_block(t, acc, start, done)
    cdf = cond.pop("_df", None)
    if cdf is not None:
        cdf.to_csv(os.path.join(a.out, "cond_cells.csv"), index=False)
    res["cond"] = cond
    big = acc.loc[acc["n"].fillna(0) >= 10, "account"].tolist()
    res["goal"] = XT.goal_block(t, acc, start, done, big)
    pd.DataFrame([{**{k: v for k, v in r.items() if k not in ("sims", "need")},
                   **{f"{s}_{k}": v for s, d in r["sims"].items() for k, v in d.items()},
                   **({f"need_{k}": v for k, v in r["need"].items()} if r.get("need") else {})} for r in res["goal"]["rows"]]
                 ).to_csv(os.path.join(a.out, "goal_path.csv"), index=False)
    res["exports"] = XT.write_exports(t, acc, start, done, a.exports)
    tele = L.read_json(os.path.join(base, "snap", "telegram.json")) if os.path.exists(os.path.join(base, "snap", "telegram.json")) else {}
    res["records"] = XT.records_block(base, snap, tele, rules, cands, env)
    res["runtime_s"] = time.time() - t0
    # files
    acc.to_csv(os.path.join(a.out, "accounts.csv"), index=False)
    keep = ["account", "pick", "suffix", "strategy", "tf", "symbol", "side", "entry_time", "exit_time", "exit_reason", "leverage", "tier",
            "margin", "pnl", "roe", "wallet_ret", "net_r", "fees", "slip_cost", "funding", "gross", "hold_h", "stop_pct", "idx_ret", "mkt_usd"]
    t[[c for c in keep if c in t]].to_csv(os.path.join(a.out, "trades.csv"), index=False)
    pd.DataFrame(res["variants"]["rows"]).to_csv(os.path.join(a.out, "variants_vs_control.csv"), index=False)
    pd.DataFrame(res["coin"]["picks"]).to_csv(os.path.join(a.out, "coin_twin_by_pick.csv"), index=False)
    if "custom_vs_default" in res and "rows" in res["custom_vs_default"]:
        pd.DataFrame(res["custom_vs_default"]["rows"]).to_csv(os.path.join(a.out, "custom_vs_default.csv"), index=False)
    res["accounts"] = acc.to_dict("records")
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(L.jsonable(res), f, ensure_ascii=False, indent=1)
    print(f"끝: 계좌 {len(acc)}, 거래 {len(t)}, {res['period']['days']:.2f}일, {time.time() - t0:.0f}초 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
