#!/usr/bin/env python3
"""V3.9 1h follow-up angles (owners, 2026-10-25): the bot's own shadows as a cross-check, every V3.9 signal (the ones
the account skipped, the other timeframes, which of several simultaneous signals to take), where the wins came from
(splits), the real plan's costs ($50 at Toobit-like fees and order sizes), and a 30-day outlook.

    python3 -I extras.py <extracted_export> <five_dir> <out_dir> [--shadows FILE] [--sims 20000]

--shadows: the export's d3_shadows.csv, or a copy holding only the V39_ALL@1h rows (run_all.sh keeps only those to
save disk). Reads the export and the repository only; writes CSV / JSON into <out_dir>.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from dataclasses import replace

sys.dont_write_bytecode = True  # never write .pyc files into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v39lib as L  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import features as F  # noqa: E402
import fiveyear as FY  # noqa: E402
import sim  # noqa: E402
import variants as VR  # noqa: E402
from sim import Variant as V  # noqa: E402

MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
SMALL = 10                      # fewer trades than this: "too small to read"

# Toobit is not reachable from this workspace (its API host is blocked): fees are the owners' figures, order-size
# steps are ASSUMPTIONS. A = the Binance steps of research/fullgrid/exchange.json; B = coarser contract steps.
TOOBIT_STEPS = {
    "A": {"BTCUSDT": 0.001, "ETHUSDT": 0.001, "SOLUSDT": 0.01, "DOGEUSDT": 1.0, "LTCUSDT": 0.001, "BCHUSDT": 0.001},
    "B": {"BTCUSDT": 0.001, "ETHUSDT": 0.01, "SOLUSDT": 0.1, "DOGEUSDT": 10.0, "LTCUSDT": 0.1, "BCHUSDT": 0.01},
}
COSTS = {  # name: (taker fee per side, slippage per side)
    "paper": (0.0005, 0.0002),
    "toobit_slip2": (0.0006, 0.0002),
    "toobit_slip3": (0.0006, 0.0003),
    "toobit_slip5": (0.0006, 0.0005),
    "payback_slip2": (0.00015, 0.0002),
    "payback_slip3": (0.00015, 0.0003),
    "payback_slip5": (0.00015, 0.0005),
}
PLANS = {  # name: (label, variant)
    "rule": ("지금 규칙 (20/30배, 증거금 = 배수 %)", VR.BASE),
    "m40_40_30": ("증거금 40%, BTC 40배·나머지 30배", V("m40_40_30", lev_btc=40, lev_alt=30, frac=0.40)),
    "m40_30": ("증거금 40%, 모두 30배", V("m40_30", lev_btc=30, lev_alt=30, frac=0.40)),
    "m40_paper": ("증거금 40%, 페이퍼와 같은 배수", V("m40_paper", same_lev=True, frac=0.40)),
}


def log(*a):
    print(*a, flush=True)


def ms_kst_day(t: int) -> int:
    return int(pd.Timestamp(int(t) + 9 * HOUR, unit="ms").dayofweek)


# ------------------------------------------------------------------------------------------------ 1. shadows
def shadow_variant(kind: str, t, W):
    """The bot's nightly shadow ``kind`` (paperbot/obsshadows.py) as a kernel variant on a fresh $5,000 wallet, or
    ('REJECTED', None) when the bot's own sizing checks refuse it."""
    from paperbot import obsshadows as OS
    from paperbot.sizing import size_position
    lev = int(t.leverage)
    if kind == "base":
        return VR.BASE, lev
    if kind in OS.LOCKS:
        return V(kind, first_lock=OS.LOCKS[kind]), lev
    if kind in OS.STOP_WIDTHS:
        return V(kind, stop_atr=OS.STOP_WIDTHS[kind], same_lev=True), lev
    if kind in OS.TP_R:
        return V(kind, tp="R", tp_val=OS.TP_R[kind], ladder=kind in OS.TP_LADDER, same_lev=True), lev
    if kind in OS.FIXED_LEVERAGE or kind in OS.FIXED_LEVERAGE3 or kind in OS.MARGIN_LEVERAGE4:
        vs = OS.variant_settings(W.S, kind)
        d = W._sig
        fill = d["ref_price"] * (1 + d["side"] * vs.slippage_frac)
        stop = d["ref_price"] - d["side"] * 2.0 * d["atr"]
        dec = size_position(vs, 5000.0, d["side"], fill, stop, "best", W.brackets[t.symbol], atr=d["atr"],
                            qty_step=W.specs[t.symbol]["qty_step"], min_notional=W.specs[t.symbol]["min_notional"])
        if not dec.ok:
            return "REJECTED", None
        frac = vs.tiers[0].margin_frac
        return V(kind, lev_btc=dec.leverage, lev_alt=dec.leverage, frac=frac), dec.leverage
    return None, None


def shadow_check(W, shadows: pd.DataFrame, out: str) -> dict:
    S, br = L.kernel_vectors(W)
    sh = shadows[shadows["account_id"] == L.ACCOUNT].copy()
    rows = []
    for i, t in W.trades.iterrows():
        d = next(x for x in W.sigs if x["symbol"] == t.symbol and x["bar_close"] == int(t.signal_ts) + 1)
        W._sig = d
        key_tail = f"|{L.ACCOUNT}|{t.symbol}|{int(t.signal_ts) + 1}"
        for r in sh[sh["key"].str.endswith(key_tail)].itertuples(index=False):
            if r.kind in ("limit", "skipped", "quality", "timestop"):
                continue
            v, lev = shadow_variant(r.kind, t, W)
            if v is None:
                continue
            row = {"n": i + 1, "symbol": t.symbol, "kind": r.kind, "resolved": int(r.resolved),
                   "bot_roe_pct": 100 * r.roe if r.roe == r.roe else np.nan, "bot_reason": r.exit_reason}
            if v == "REJECTED":
                row.update(my_roe_pct=np.nan, my_reason="REJECTED")
            else:
                A = W.A[t.symbol]
                e = W.entry_index(t.symbol, d["bar_close"])
                res = sim.run_one(S, br[t.symbol], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 5000.0,
                                  W.specs[t.symbol], v, t.symbol, paper_lev=lev, paper_frac=(lev or 0) / 100.0)
                row.update(my_roe_pct=100 * res["roe"] if res["reason"] != "REJECTED" else np.nan,
                           my_reason=res["reason"])
            rows.append(row)
    R = pd.DataFrame(rows)
    R["diff_pct"] = R["my_roe_pct"] - R["bot_roe_pct"]
    R.to_csv(os.path.join(out, "shadow_check.csv"), index=False)
    res = R[R["resolved"] == 1]
    summ = []
    for k, g in res.groupby("kind"):
        both = g[g["bot_roe_pct"].notna() & g["my_roe_pct"].notna()]
        rej_same = int((g["bot_roe_pct"].isna() & (g["my_reason"] == "REJECTED")).sum())
        summ.append({"kind": k, "resolved_rows": int(len(g)), "compared": int(len(both)),
                     "equal_1e-6": int((both["diff_pct"].abs() < 1e-4).sum()),
                     "within_1pt": int((both["diff_pct"].abs() < 1.0).sum()),
                     "max_abs_diff_pct": float(both["diff_pct"].abs().max()) if len(both) else np.nan,
                     "both_rejected": rej_same, "bot_mean_roe_pct": float(both["bot_roe_pct"].mean()) if len(both) else np.nan,
                     "my_mean_roe_pct": float(both["my_roe_pct"].mean()) if len(both) else np.nan})
    Ssum = pd.DataFrame(summ)
    Ssum.to_csv(os.path.join(out, "shadow_check_summary.csv"), index=False)
    return {"rows": int(len(R)), "resolved": int(len(res))}


# ------------------------------------------------------------------------------------------------ 2. all signals
def skipped_signals(W, shadows: pd.DataFrame, out: str) -> dict:
    """Every SUBMITTED signal the account did not take, alone on a fresh $5,000 wallet with the house exits."""
    S, br = L.kernel_vectors(W)
    taken = {(t.symbol, int(t.signal_ts) + 1) for t in W.trades.itertuples(index=False)}
    oc = W.outcomes.set_index(["symbol", "sig_ts"])
    sk = shadows[(shadows["account_id"] == L.ACCOUNT) & (shadows["kind"] == "skipped")]
    skr = {r.key.split("|")[2] + "|" + r.key.split("|")[3]: r for r in sk.itertuples(index=False)}
    rows = []
    for d in W.sigs:
        if (d["symbol"], d["bar_close"]) in taken:
            continue
        try:
            why = oc.loc[(d["symbol"], d["bar_close"] - 1), "reason"]
            why = why.iloc[0] if isinstance(why, pd.Series) else why
        except KeyError:
            why = "?"
        A = W.A[d["symbol"]]
        e = W.entry_index(d["symbol"], d["bar_close"])
        res = sim.run_one(S, br[d["symbol"]], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 5000.0,
                          W.specs[d["symbol"]], VR.BASE, d["symbol"])
        b = skr.get(f"{d['symbol']}|{d['bar_close']}")
        rows.append({"signal_kst": L.kst(d["bar_close"]), "symbol": d["symbol"].replace("USDT", ""),
                     "side": "롱" if d["side"] > 0 else "숏", "why_skipped": why, "reason": res["reason"],
                     "roe_pct": 100 * res["roe"], "ret_pct": 100 * res["ret"], "lev": res["lev"],
                     "bot_shadow_roe_pct": 100 * b.roe if (b is not None and b.roe == b.roe) else np.nan})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "skipped_signals.csv"), index=False)
    out_d = {}
    for why, g in R.groupby("why_skipped"):
        ok = g[g["reason"] != "REJECTED"]
        out_d[why] = {"signals": int(len(g)), "wins": int((ok["roe_pct"] > 0).sum()),
                      "losses": int((ok["roe_pct"] <= 0).sum()), "open": int((ok["reason"] == "OPEN").sum()),
                      "mean_ret_pct": float(ok["ret_pct"].mean()), "sum_ret_pct": float(ok["ret_pct"].sum())}
    ok = R[R["reason"] != "REJECTED"]
    both = ok[ok["bot_shadow_roe_pct"].notna()]
    out_d["bot_shadow_compared"] = int(len(both))
    out_d["bot_shadow_equal"] = int(((both["roe_pct"] - both["bot_shadow_roe_pct"]).abs() < 1e-4).sum())
    return out_d


def other_timeframes(export: str, out: str) -> list:
    t = pd.read_csv(os.path.join(export, "current", "trades.csv"),
                    usecols=["account_id", "pnl", "side", "equity_after", "exit_time"])
    v = t[t["account_id"].str.startswith("V39_ALL@")]
    rows = []
    for aid, g in v.groupby("account_id"):
        g = g.sort_values("exit_time")
        eq = g["equity_after"].to_numpy(float)
        rows.append({"account": aid, "trades": int(len(g)), "wins": int((g["pnl"] > 0).sum()),
                     "losses": int((g["pnl"] <= 0).sum()), "shorts": int((g["side"] < 0).sum()),
                     "pnl": float(g["pnl"].sum()), "final": float(eq[-1]),
                     "max_dd_closed_pct": 100 * L.max_drawdown(eq, 5000.0)})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "other_timeframes.csv"), index=False)
    return rows


TIE_RULES = {
    "priority": ("지금: 코인 순서 BTC·ETH·SOL·DOGE·LTC·BCH", None),
    "reverse": ("반대 순서 (BCH부터)", lambda d, x: -x["prio"]),
    "best_first": ("품질 '최상' 신호 먼저", lambda d, x: (0 if x["best"] else 1, x["prio"])),
    "atr_high": ("변동성(ATR%) 큰 코인 먼저", lambda d, x: -x["atr_pct"]),
    "atr_low": ("변동성(ATR%) 작은 코인 먼저", lambda d, x: x["atr_pct"]),
}


def tie_breaks(W, X, out: str, seeds: int = 50) -> dict:
    """Which of several signals at one bar close the account takes: 20 days (account replay) and five years
    (one position, each trade on $5,000)."""
    prio = {s: k for k, s in enumerate(W.S.symbol_priority)}

    def info(d):
        return {"prio": prio[d["symbol"]], "best": d["best"], "atr_pct": d["atr"] / d["ref_price"]}
    res = {}
    rows = []
    for name, (label, key) in TIE_RULES.items():
        sigs = list(W.sigs) if key is None else sorted(W.sigs, key=lambda d: (d["bar_close"], key(d, info(d))))
        k = L.kernel_account(W, VR.BASE, sigs=sigs)
        ent = k[k["status"] == "ENTERED"]
        rows.append({"rule": name, "label": label, "trades": int(len(ent)), "wins": int((ent["pnl"] > 0).sum()),
                     "losses": int((ent["pnl"] <= 0).sum()), "final": float(ent["equity_after"].iloc[-1])})
    rng = np.random.default_rng(20261025)
    finals = []
    for s in range(seeds):
        r = rng.random(len(W.sigs))
        order = sorted(range(len(W.sigs)), key=lambda i: (W.sigs[i]["bar_close"], r[i]))
        k = L.kernel_account(W, VR.BASE, sigs=[W.sigs[i] for i in order])
        finals.append(float(k[k["status"] == "ENTERED"]["equity_after"].iloc[-1]))
    rows.append({"rule": "random", "label": f"무작위 ({seeds}번 평균)", "trades": np.nan, "wins": np.nan, "losses": np.nan,
                 "final": float(np.mean(finals)), "final_min": float(np.min(finals)), "final_max": float(np.max(finals))})
    T20 = pd.DataFrame(rows)
    T20.to_csv(os.path.join(out, "tie_break_window.csv"), index=False)
    multi = pd.Series([d["bar_close"] for d in W.sigs]).value_counts()
    res["window_bar_closes_with_2plus_signals"] = int((multi >= 2).sum())
    # five years
    G0 = X.G
    G0 = G0.assign(atr_pct=G0["atr"] / G0["close"])
    rows = []
    for name, (label, key) in list(TIE_RULES.items()):
        if key is None:
            G = G0
        elif name == "reverse":
            G = G0.sort_values(["close_ms", "prio"], ascending=[True, False])
        elif name == "best_first":
            G = G0.assign(_b=~G0["best"]).sort_values(["close_ms", "_b", "prio"]).drop(columns="_b")
        elif name == "atr_high":
            G = G0.sort_values(["close_ms", "atr_pct"], ascending=[True, False])
        else:
            G = G0.sort_values(["close_ms", "atr_pct"])
        X.G = G
        row = {"rule": name, "label": label}
        for p in ("pick", "check"):
            a = X.account(VR.BASE, p, compound=False)
            row[f"{p}_trades"] = int(len(a))
            row[f"{p}_per_trade_pct"] = 100 * float(a["ret"].mean())
            row[f"{p}_win_pct"] = 100 * float((a["pnl"] > 0).mean())
        rows.append(row)
    X.G = G0.drop(columns="atr_pct")
    T5 = pd.DataFrame(rows)
    T5.to_csv(os.path.join(out, "tie_break_5y.csv"), index=False)
    mc = X.G.groupby("close_ms").size()
    res["fiveyear_share_of_bar_closes_with_2plus"] = float((mc >= 2).mean())
    return res


# ------------------------------------------------------------------------------------------------ 3. splits
def split_rows(df: pd.DataFrame, col: str, label: str, ret: str = "ret_pct") -> list:
    out = []
    for val, g in df.groupby(col):
        n = len(g)
        out.append({"split": label, "group": str(val), "trades": n, "wins": int((g[ret] > 0).sum()),
                    "losses": int((g[ret] <= 0).sum()), "sum_ret_pct": float(g[ret].sum()),
                    "mean_ret_pct": float(g[ret].mean()), "too_small": n < SMALL})
    return out


def add_split_cols(df: pd.DataFrame, t_col: str, side_col: str, ctx: list) -> pd.DataFrame:
    df = df.copy()
    c = pd.DataFrame(ctx, index=df.index)
    s = df[side_col].to_numpy()
    hk = c["hour_kst"].to_numpy()
    df["coin"] = df["symbol"].str.replace("USDT", "")
    df["side_ko"] = np.where(s > 0, "롱", "숏")
    df["hour_kst"] = pd.cut(hk, [-1, 5, 11, 17, 23], labels=["00-05시", "06-11시", "12-17시", "18-23시"]).astype(str)
    wd = np.array([ms_kst_day(t) for t in df[t_col]])
    df["weekday"] = np.where(wd >= 5, "주말", "평일")
    df["btc24"] = np.where(c["btc_24h"] > 0, "BTC 24시간 상승", "BTC 24시간 하락")
    df["btc7d"] = np.where(c["btc_7d"] > 0, "BTC 7일 상승", "BTC 7일 하락")
    df["btc24_with"] = np.where(c["btc_24h"] * s > 0, "BTC 24시간 흐름과 같은 쪽", "BTC 24시간 흐름과 반대")
    df["h4_ema50"] = np.where(c["h4_ema50"] * s > 0, "4시간봉 EMA50 같은 쪽", "4시간봉 EMA50 반대")
    df["h4_st"] = np.where(c["h4_st"] * s > 0, "4시간봉 슈퍼트렌드 같은 쪽", "4시간봉 슈퍼트렌드 반대")
    return df


SPLITS = [("coin", "코인"), ("side_ko", "방향"), ("hour_kst", "시간대 (한국)"), ("weekday", "평일/주말"),
          ("btc24", "BTC 24시간"), ("btc7d", "BTC 7일"), ("btc24_with", "BTC 흐름과 방향"),
          ("h4_ema50", "그 코인 4시간 추세 (EMA50)"), ("h4_st", "그 코인 4시간 추세 (슈퍼트렌드)")]


def splits(W, X, ctxs, out: str) -> None:
    T = W.trades.copy()
    T["ret_pct"] = 100 * T["pnl"] / (T["equity_after"] - T["pnl"])
    ctx = [ctxs[t.symbol].at(int(t.signal_ts) + 1, int(t.side)) for t in T.itertuples(index=False)]
    T["t"] = T["signal_ts"] + 1
    T = add_split_cols(T, "t", "side", ctx)
    rows = []
    for col, label in SPLITS:
        rows += split_rows(T, col, label)
    R = pd.DataFrame(rows)
    # five years: the trades a one-position bot takes with the current rules, each on $5,000
    seq = X.account(VR.BASE, None, compound=False)
    seq = seq[seq["entry_ts"] >= FY.ms("2021-01-01")].copy()
    G = X.G
    seq["close_ms"] = G.loc[seq["idx"], "close_ms"].to_numpy()
    seq["period"] = G.loc[seq["idx"], "period"].to_numpy()
    seq["ret_pct"] = 100 * seq["ret"]
    ctx5 = [X.ctx[r.symbol].at(int(r.close_ms), int(r.side)) for r in seq.itertuples(index=False)]
    seq = add_split_cols(seq, "close_ms", "side", ctx5)
    five = []
    for p in ("pick", "check"):
        sp = seq[seq["period"] == p]
        for col, label in SPLITS:
            for r in split_rows(sp, col, label):
                five.append({**r, "period": p})
    Fv = pd.DataFrame(five)
    keep = ["split", "group", "trades", "mean_ret_pct", "wins"]
    a = Fv[Fv["period"] == "pick"][keep].rename(columns={"trades": "pick_trades", "mean_ret_pct": "pick_mean_ret_pct",
                                                          "wins": "pick_wins"})
    b = Fv[Fv["period"] == "check"][keep].rename(columns={"trades": "check_trades",
                                                           "mean_ret_pct": "check_mean_ret_pct", "wins": "check_wins"})
    R = R.merge(a, on=["split", "group"], how="left").merge(b, on=["split", "group"], how="left")
    R["pick_win_pct"] = 100 * R["pick_wins"] / R["pick_trades"]
    R["check_win_pct"] = 100 * R["check_wins"] / R["check_trades"]
    R.drop(columns=["pick_wins", "check_wins"]).to_csv(os.path.join(out, "splits.csv"), index=False)


# ------------------------------------------------------------------------------------------------ 4. costs, $50
def plan_settings(W, cost: str):
    tk, sl = COSTS[cost]
    return replace(W.S, taker_fee=tk, slippage_frac=sl)


def plan_specs(steps: str) -> dict:
    return {s: {"qty_step": q, "min_notional": 5.0} for s, q in TOOBIT_STEPS[steps].items()}


def costs_plan(W, out: str) -> pd.DataFrame:
    rows = []
    for plan, (label, v) in PLANS.items():
        for cost in COSTS:
            for steps in ("A", "B"):
                if cost == "paper" and steps == "B":
                    continue
                for eq0 in ((5000.0, 50.0) if cost == "paper" else (50.0,)):
                    Sset = plan_settings(W, cost)
                    specs = W.specs if (cost == "paper" and eq0 == 5000.0) else plan_specs(steps)
                    k = L.kernel_account(W, v, equity0=eq0, settings=Sset, specs=specs)
                    ent = k[k["status"] == "ENTERED"]
                    eq = ent["equity_after"].to_numpy(float)
                    fees = (ent["qty"] * ent["fill"] * Sset.taker_fee).sum() * 2
                    rows.append({"plan": plan, "plan_label": label, "cost": cost, "taker_pct": 100 * COSTS[cost][0],
                                 "slip_pct": 100 * COSTS[cost][1], "steps": steps if eq0 == 50.0 else "binance",
                                 "start": eq0, "trades": int(len(ent)), "wins": int((ent["pnl"] > 0).sum()),
                                 "losses": int((ent["pnl"] <= 0).sum()), "open_at_end": int((ent["reason"] == "OPEN").sum()),
                                 "final": float(eq[-1]) if len(eq) else eq0,
                                 "ret_pct": 100 * (float(eq[-1]) / eq0 - 1) if len(eq) else 0.0,
                                 "dd_closed_pct": 100 * L.max_drawdown(eq, eq0) if len(eq) else 0.0,
                                 "worst_trade_pct": 100 * float((ent["pnl"] / ent["equity_before"]).min()) if len(ent) else 0.0,
                                 "fees_approx": float(fees)})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "costs_plan.csv"), index=False)
    return R


def per_trade_returns_window(W, v, cost: str, steps: str = "A", eq0: float = 50.0) -> np.ndarray:
    k = L.kernel_account(W, v, equity0=eq0, settings=plan_settings(W, cost),
                         specs=W.specs if cost == "paper" and eq0 == 5000.0 else plan_specs(steps))
    ent = k[k["status"] == "ENTERED"]
    return (ent["pnl"] / ent["equity_before"]).to_numpy(float)


# ------------------------------------------------------------------------------------------------ 5. 30-day outlook
def mc(rets: np.ndarray, lam: float, sims: int, rng) -> dict:
    """Months of Poisson(lam) trades drawn with replacement from ``rets`` (each a share of the wallet)."""
    n = rng.poisson(lam, sims)
    m = int(n.max()) if len(n) else 0
    idx = rng.integers(0, len(rets), (sims, max(m, 1)))
    r = rets[idx]
    r[np.arange(max(m, 1))[None, :] >= n[:, None]] = 0.0
    path = np.cumprod(1 + r, axis=1)
    end = path[:, -1]
    low = np.minimum(1.0, path.min(axis=1))
    return summarize_months(end, low)


def summarize_months(end: np.ndarray, low: np.ndarray) -> dict:
    return {"months": int(len(end)), "median_x": float(np.median(end)), "mean_x": float(np.mean(end)),
            "p_x2": float((end >= 2).mean()), "p_x3": float((end >= 3).mean()), "p_x6": float((end >= 6).mean()),
            "p_gain": float((end > 1).mean()), "p_half_any": float((low <= 0.5).mean()),
            "p_ruin_any": float((low <= 0.1).mean()), "p10_x": float(np.quantile(end, 0.1)),
            "p90_x": float(np.quantile(end, 0.9))}


def rolling_months(seq: pd.DataFrame, a: int, b: int) -> dict:
    """Every real 30-day stretch (daily starts) of a trade sequence: compounded in its real order."""
    t = seq["entry_ts"].to_numpy(np.int64)
    r = seq["ret"].to_numpy(float)
    ends, lows = [], []
    for d0 in range(a, b - 30 * DAY, DAY):
        m = (t >= d0) & (t < d0 + 30 * DAY)
        p = np.cumprod(1 + r[m]) if m.any() else np.ones(1)
        ends.append(p[-1])
        lows.append(min(1.0, p.min()))
    return summarize_months(np.array(ends), np.array(lows))


def outlook(W, X, out: str, sims: int) -> pd.DataFrame:
    rng = np.random.default_rng(20261025)
    days = (W.end_ms - W.start_ms) / DAY
    lam27 = len(W.trades) / days * 30
    plans = {
        "paper_rule": ("페이퍼 그대로 (지금 규칙·페이퍼 비용, $5,000)", VR.BASE, "paper", 5000.0),
        "live_m40_40_30": ("실거래 계획: $50, 증거금 40%, BTC 40배·나머지 30배, Toobit 0.06% + 미끄러짐 0.03%",
                           PLANS["m40_40_30"][1], "toobit_slip3", 50.0),
        "live_m40_40_30_payback": ("같은 계획, 페이백 들어오면 (0.015%)", PLANS["m40_40_30"][1], "payback_slip3", 50.0),
        "live_m40_30": ("$50, 증거금 40%, 모두 30배, Toobit 0.06% + 0.03%", PLANS["m40_30"][1], "toobit_slip3", 50.0),
        "live_rule": ("$50, 지금 규칙 크기 (20/30배·증거금 = 배수 %), Toobit 0.06% + 0.03%", VR.BASE, "toobit_slip3", 50.0),
        "live_rule_roe15": ("$50, 지금 규칙 크기 + 고정 익절 +15%, Toobit 0.06% + 0.03%",
                            V("roe15", ladder=False, tp="ROE", tp_val=0.15), "toobit_slip3", 50.0),
    }
    rows = []
    for name, (label, v, cost, eq0) in plans.items():
        r27 = per_trade_returns_window(W, v, cost, eq0=eq0)
        row = {"plan": name, "label": label, "trades_per_30d_window": lam27}
        row.update({f"w27_{k}": val for k, val in mc(r27, lam27, sims, rng).items()})
        # five years: the trades a one-position bot takes under the plan, each sized on $5,000 (no rounding)
        Sv0 = X.Sv
        X.Sv = sim.settings_vector(plan_settings(W, cost))
        seq = X.account(v, None, compound=False)
        X.Sv = Sv0
        seq = seq[seq["entry_ts"] >= FY.ms("2021-01-01")]
        for p, a_, b_ in FY.PERIODS[:2]:
            s = seq[(seq["entry_ts"] >= FY.ms(a_)) & (seq["entry_ts"] < FY.ms(b_))]
            lam = len(s) / ((FY.ms(b_) - FY.ms(a_)) / DAY) * 30
            row[f"{p}_trades_per_30d"] = lam
            row[f"{p}_per_trade_pct"] = 100 * float(s["ret"].mean())
            row.update({f"{p}_boot_{k}": val for k, val in mc(s["ret"].to_numpy(float), lam, sims, rng).items()})
            row.update({f"{p}_real_{k}": val for k, val in rolling_months(s, FY.ms(a_), FY.ms(b_)).items()})
        rows.append(row)
        log("outlook", name, {k: round(v_, 3) for k, v_ in row.items() if isinstance(v_, float) and
                              ("median_x" in k or "p_x6" in k or "per_trade" in k)})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "outlook_30d.csv"), index=False)
    return R


# ------------------------------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export")
    ap.add_argument("five_dir")
    ap.add_argument("out")
    ap.add_argument("--shadows", default=None)
    ap.add_argument("--sims", type=int, default=20000)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    W = L.Window(a.export)
    facts = {}
    sh_path = a.shadows or os.path.join(a.export, "current", "d3_shadows.csv")
    shadows = pd.read_csv(sh_path) if os.path.exists(sh_path) else pd.DataFrame(
        columns=["key", "kind", "account_id", "roe", "exit_reason", "resolved"])
    facts["shadows"] = shadow_check(W, shadows, a.out)
    log("shadows", facts["shadows"], f"{time.time() - t0:.0f}s")
    facts["skipped"] = skipped_signals(W, shadows, a.out)
    log("skipped", facts["skipped"])
    facts["other_timeframes"] = other_timeframes(a.export, a.out)
    X = FY.Five(a.five_dir)
    log(f"five years loaded {time.time() - t0:.0f}s")
    facts["tie"] = tie_breaks(W, X, a.out)
    log("tie", facts["tie"])
    h1s = {s: F.hourly(a.five_dir, s, W.A[s]) for s in L.SYMBOLS}
    ctxs = {s: F.Context(h1s[s], h1s["BTCUSDT"]) for s in L.SYMBOLS}
    splits(W, X, ctxs, a.out)
    log(f"splits {time.time() - t0:.0f}s")
    costs_plan(W, a.out)
    log(f"costs {time.time() - t0:.0f}s")
    outlook(W, X, a.out, a.sims)
    with open(os.path.join(a.out, "facts_extras.json"), "w") as fh:
        json.dump(facts, fh, indent=1, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    log(f"done in {time.time() - t0:.0f}s -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
