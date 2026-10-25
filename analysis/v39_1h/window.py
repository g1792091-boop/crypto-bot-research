#!/usr/bin/env python3
"""V3.9 1h (rule bot account V39_ALL@1h): trade-by-trade study of the paper record, on the export's own 1m bars.

    python3 -I window.py <extracted_export> <five_dir> <out_dir> [--minute-dir DIR] [--cut-ms MS]

<extracted_export>: an export zip extracted with analysis/review1024/rulebot/scripts/extract_zip.py.
<five_dir>: fetch_bars.py five output (5m klines): 1h / 4h context bars and the V3.9 signal check.
--minute-dir: fetch_bars.py minute output: 1m bars after the export's end (how far price went after the last exits).
--cut-ms: rerun as of an earlier time (drops bars, signals and trades at or after it).

Writes CSV / JSON tables into <out_dir> (see README in REPORT_KO.md's appendix). Every what-if uses the same replay:
sim.py's kernel, first shown to reproduce the paper trades exactly (and to equal the bot's own PaperEngine).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
sys.dont_write_bytecode = True  # never write .pyc files into the repository
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v39lib as L  # noqa: E402  (sets sys.path, no bytecode)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import entries as EN  # noqa: E402
import features as F  # noqa: E402
import sim  # noqa: E402
import variants as VR  # noqa: E402

MIN, HOUR = 60_000, 3_600_000


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------------------------------- helpers
def sig_of(W, t) -> dict:
    for d in W.sigs:
        if d["symbol"] == t.symbol and d["bar_close"] == int(t.signal_ts) + 1:
            return d
    raise KeyError((t.symbol, t.signal_ts))


def same_entries(W, v, entry=("now", {}), S=None, br=None) -> pd.DataFrame:
    """The paper trades' own signals, each sized on the paper wallet before it (so 'now' equals the paper trade
    exactly) with variant ``v`` and entry rule ``entry``. Compounded = 5,000 x prod(1 + P&L / wallet before)."""
    if S is None:
        S, br = L.kernel_vectors(W)
    rows = []
    kind, p = entry
    for i, t in W.trades.iterrows():
        d = sig_of(W, t)
        sym = t.symbol
        A = W.A[sym]
        eq = float(t.equity_after - t.pnl)
        ref = d["ref_price"] if kind == "now" else d["ref_price"]
        x = EN.entry(kind, p, A, d["bar_close"], d["side"], d["atr"], ref, 60_000)
        base = {"n": i + 1, "symbol": sym, "side": int(t.side), "sig_id": d["sig_id"], "equity_before": eq,
                "next_entry": int(W.trades.entry_time.iloc[i + 1]) if i + 1 < len(W.trades) else None}
        if x is None:
            rows.append({**base, "status": "NO_ENTRY", "ret": 0.0, "pnl": 0.0})
            continue
        e, raw = x
        r = sim.run_one(S, br[sym], A, e, raw, d["side"], d["atr"], d["best"], eq, W.specs[sym], v, sym,
                        paper_lev=int(t.leverage), paper_frac=int(t.leverage) / 100.0)
        st = "REJECTED" if r["reason"] == "REJECTED" else "ENTERED"
        rows.append({**base, **r, "status": st})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, start: float = 5000.0) -> dict:
    ent = df[df["status"] == "ENTERED"]
    ret = df["ret"].fillna(0).to_numpy(float)
    eq = start * np.cumprod(1 + ret)
    out = {"entered": int(len(ent)), "skipped": int((df["status"] != "ENTERED").sum()),
           "wins": int((ent["pnl"] > 0).sum()), "losses": int((ent["pnl"] <= 0).sum()),
           "open_at_end": int((ent["reason"] == "OPEN").sum()) if len(ent) else 0,
           "sum_ret_pct": 100 * float(ret.sum()), "final": float(eq[-1]) if len(eq) else start,
           "worst_ret_pct": 100 * float(ent["ret"].min()) if len(ent) else 0.0,
           "worst_roe_pct": 100 * float(ent["roe"].min()) if len(ent) else 0.0,
           "best_ret_pct": 100 * float(ent["ret"].max()) if len(ent) else 0.0,
           "dd_closed_pct": 100 * L.max_drawdown(eq, start)}
    if len(ent) and "worst_px" in ent:
        deep = ent["side"] * ent["qty"] * (ent["worst_px"] - ent["fill"]) / ent["equity_before"]
        out["deepest_open_pct"] = 100 * float(deep.min())
    if "next_entry" in df and len(ent):
        nxt = ent["next_entry"].astype(float)
        out["overlaps"] = int(((ent["exit_ts"] > nxt) & nxt.notna()).sum())
    return out


def account_summary(k: pd.DataFrame, start: float = 5000.0) -> dict:
    ent = k[k["status"] == "ENTERED"] if len(k) else k
    if not len(ent):
        return {"acct_trades": 0, "acct_final": start}
    eq = ent["equity_after"].to_numpy(float)
    return {"acct_trades": int(len(ent)), "acct_wins": int((ent["pnl"] > 0).sum()),
            "acct_losses": int((ent["pnl"] <= 0).sum()), "acct_open": int((ent["reason"] == "OPEN").sum()),
            "acct_final": float(eq[-1]), "acct_dd_closed_pct": 100 * L.max_drawdown(eq, start),
            "acct_worst_ret_pct": 100 * float((ent["pnl"] / ent["equity_before"]).min())}


def entry_fn_for(W, kind, p):
    def f(d):
        return EN.entry(kind, p, W.A[d["symbol"]], d["bar_close"], d["side"], d["atr"], d["ref_price"], 60_000)
    return f


# ---------------------------------------------------------------------------------------------------- 1. replay
def validate(W, out: str) -> dict:
    eng = L.engine_replay(W)
    ker = L.kernel_account(W, VR.BASE)
    kc = ker[(ker["status"] == "ENTERED") & (ker["reason"] != "OPEN")].reset_index(drop=True)
    rows = []
    for i, t in W.trades.iterrows():
        a = eng.trades[i] if i < len(eng.trades) else None
        b = kc.iloc[i] if i < len(kc) else None
        rows.append({"n": i + 1, "symbol": t.symbol, "side": "롱" if t.side > 0 else "숏",
                     "entry_kst": L.kst(t.entry_time), "exit_kst": L.kst(t.exit_time), "reason": t.exit_reason,
                     "leverage": int(t.leverage), "pnl_paper": t.pnl, "roe_paper": t.roe,
                     "pnl_engine": a.pnl if a else np.nan,
                     "engine_same": bool(a and a.entry_time == t.entry_time and a.exit_time == t.exit_time
                                         and a.exit_reason == t.exit_reason and a.leverage == t.leverage),
                     "pnl_kernel": b["pnl"] if b is not None else np.nan,
                     "kernel_same": bool(b is not None and b["entry_ts"] == t.entry_time
                                         and b["exit_ts"] == t.exit_time and b["reason"] == t.exit_reason
                                         and b["lev"] == t.leverage)})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "replay_match.csv"), index=False)
    s = eng.summary()
    info = {"paper_trades": int(len(W.trades)), "engine_trades": len(eng.trades), "kernel_closed": int(len(kc)),
            "engine_same": int(R["engine_same"].sum()), "kernel_same": int(R["kernel_same"].sum()),
            "max_abs_pnl_diff_engine": float((R["pnl_engine"] - R["pnl_paper"]).abs().max()),
            "max_abs_pnl_diff_kernel": float((R["pnl_kernel"] - R["pnl_paper"]).abs().max()),
            "paper_final": float(W.trades["equity_after"].iloc[-1]), "engine_final": float(eng.wallet),
            "engine_max_dd_pct": 100 * s["max_drawdown"], "signals_submitted": len(W.sigs),
            "signals_late_not_submitted": int(len(W.late[W.late["status"] == "LATE"])),
            "skipped_in_position": int((W.outcomes["reason"] == "in position").sum()),
            "skipped_lower_score": int((W.outcomes["reason"] == "lower score than entered signal").sum()),
            "taker_fee": W.taker, "funding": W.funding_info,
            "bars_first_kst": L.kst(W.start_ms), "bars_last_kst": L.kst(W.end_ms - MIN)}
    return info


# ---------------------------------------------------------------------------------------------------- 2. per trade
def path_stats(W, t, A, rt: float) -> dict:
    """Depth and duration red, the ladder start, MFE before the exit, and price after the exit (1m bars)."""
    side, lev, fill = int(t.side), int(t.leverage), float(t.entry_price)
    e = int(np.searchsorted(A["ts"], t.entry_time))
    x = int(np.searchsorted(A["ts"], t.exit_time, side="right")) - 1
    seg = slice(e, x + 1)
    lo, hi, c = A["l"][seg], A["h"][seg], A["c"][seg]
    adverse = lo if side > 0 else hi
    fav = hi if side > 0 else lo
    worst_i = int(np.argmin(side * adverse))
    worst = float(adverse[worst_i])
    net = lambda px: lev * (side * (px / fill - 1) - rt)  # noqa: E731
    gross_close = side * (c / fill - 1)
    best_run = np.maximum.accumulate(side * fav) * side
    netbest = lev * (side * (best_run / fill - 1) - rt)
    arm = np.flatnonzero(netbest >= 0.12 - 1e-12)
    green = np.flatnonzero(lev * (gross_close - rt) > 0)
    out = {"mae_px": worst, "mae_roe_gross_pct": 100 * lev * side * (worst / fill - 1),
           "mae_roe_net_pct": 100 * net(worst), "mae_atr": side * (worst - fill) / float(t.atr_sig),
           "min_to_mae": worst_i, "red_minutes": int((gross_close < 0).sum()), "held_minutes": int(len(c)),
           "min_to_green_net": int(green[0]) if len(green) else None,
           "min_to_ladder_start": int(arm[0]) if len(arm) else None,
           "mfe_px": float(t.mfe_price), "mfe_roe_net_pct": 100 * net(float(t.mfe_price)),
           "exit_roe_pct": 100 * float(t.roe)}
    if len(arm):
        pre = adverse[: arm[0] + 1]
        out["mae_before_start_roe_net_pct"] = 100 * net(float(pre[int(np.argmin(side * pre))]))
    exit_px = float(t.exit_price)
    for H in (6, 24, 48):
        a, b = x + 1, int(np.searchsorted(A["ts"], int(t.exit_time) + H * HOUR))
        have = (A["ts"][-1] - int(t.exit_time)) / HOUR
        out[f"after{H}h_hours_available"] = round(min(H, max(0.0, have)), 1)
        if b > a:
            f2 = A["h"][a:b] if side > 0 else A["l"][a:b]
            a2 = A["l"][a:b] if side > 0 else A["h"][a:b]
            bestf = float(f2.max() if side > 0 else f2.min())
            worsta = float(a2.min() if side > 0 else a2.max())
            out[f"after{H}h_best_move_pct"] = 100 * side * (bestf / exit_px - 1)
            out[f"after{H}h_best_roe_from_entry_pct"] = 100 * net(bestf)
            out[f"after{H}h_worst_move_pct"] = 100 * side * (worsta / exit_px - 1)
            out[f"after{H}h_close_move_pct"] = 100 * side * (float(A["c"][b - 1]) / exit_px - 1)
    return out


def trade_table(W, ctxs: dict, out: str) -> pd.DataFrame:
    rt = W.S.round_trip_cost
    from paperbot.levrule import quality_score
    rows = []
    for i, t in W.trades.iterrows():
        d = sig_of(W, t)
        t = t.copy()
        t["atr_sig"] = d["atr"]
        eq = float(t.equity_after - t.pnl)
        stop_d = abs(t.entry_price - t.stop_initial) / t.entry_price
        liq_d = abs(t.entry_price - t.liq_price) / t.entry_price
        cx = W.ctx.get(d["sig_id"]) or {}
        q = quality_score((cx or {}).get("strength"), "V39_ALL", "1h")
        r = {"n": i + 1, "symbol": t.symbol.replace("USDT", ""), "side": "롱" if t.side > 0 else "숏",
             "signal_kst": L.kst(t.signal_ts + 1), "entry_kst": L.kst(t.entry_time), "exit_kst": L.kst(t.exit_time),
             "hold_min": int((t.exit_time - t.entry_time) // MIN), "entry_price": t.entry_price,
             "exit_price": t.exit_price, "reason": t.exit_reason, "leverage": int(t.leverage), "group": t.tier,
             "quality_score": q.get("score"), "margin_share_pct": 100 * t.margin / eq, "equity_before": eq,
             "pnl": t.pnl, "roe_pct": 100 * t.roe, "ret_pct": 100 * t.pnl / eq, "lock_roe_pct": 100 * (t.lock_roe or 0),
             "atr_pct": 100 * d["atr"] / t.entry_price, "stop_dist_pct": 100 * stop_d,
             "stop_loss_roe_pct": -100 * t.leverage * (stop_d + rt), "liq_dist_pct": 100 * liq_d,
             "liq_minus_stop_atr": (liq_d - stop_d) * t.entry_price / d["atr"],
             "ctx_regime": cx.get("regime"), "ctx_htf_regime": cx.get("htf_regime"), "ctx_adx": cx.get("adx"),
             "ctx_box_pos": cx.get("box_pos"), "ctx_ema20_dist_atr": cx.get("ema20_dist_atr"),
             "ctx_trend_age": cx.get("trend_age")}
        r.update(path_stats(W, t, W.A[t.symbol], rt))
        c = ctxs[t.symbol].at(int(t.signal_ts) + 1, int(t.side))
        r.update({f"ctx_{k}": v for k, v in c.items()})
        rows.append(r)
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(out, "trades.csv"), index=False)
    return T


# ---------------------------------------------------------------------------------------------------- 3. the loss
def loss_story(W, T: pd.DataFrame, out: str) -> dict:
    losers = W.trades[W.trades["pnl"] <= 0]
    info = {"n_losses": int(len(losers))}
    if not len(losers):
        return info
    t = losers.iloc[0]
    k = int(losers.index[0])
    sym = t.symbol
    rows = []
    for s in (sym, "BTCUSDT") if sym != "BTCUSDT" else (sym, "ETHUSDT"):
        A = W.A[s]
        h1 = F.agg(A["ts"], A["o"], A["h"], A["l"], A["c"], HOUR, 60_000)
        g = h1[(h1["open_ms"] >= int(t.entry_time) - 12 * HOUR) & (h1["open_ms"] <= int(t.exit_time) + 6 * HOUR)]
        for r in g.itertuples(index=False):
            rows.append({"coin": s.replace("USDT", ""), "hour_kst": L.kst(r.open_ms), "open": r.open, "high": r.high,
                         "low": r.low, "close": r.close, "chg_pct": 100 * (r.close / r.open - 1)})
    pd.DataFrame(rows).to_csv(os.path.join(out, "loss_1h.csv"), index=False)
    A = W.A[sym]
    lev, fill, side = int(t.leverage), float(t.entry_price), int(t.side)
    rt = W.S.round_trip_cost
    m = []
    for a, b, tag in ((int(t.entry_time) - 5 * MIN, int(t.entry_time) + 40 * MIN, "entry"),
                      (int(t.exit_time) - 40 * MIN, int(t.exit_time) + 5 * MIN, "stop")):
        i0, i1 = np.searchsorted(A["ts"], a), np.searchsorted(A["ts"], b)
        for j in range(i0, i1):
            m.append({"part": tag, "min_kst": L.kst(A["ts"][j]), "open": A["o"][j], "high": A["h"][j],
                      "low": A["l"][j], "close": A["c"][j],
                      "roe_close_net_pct": 100 * lev * (side * (A["c"][j] / fill - 1) - rt)})
    pd.DataFrame(m).to_csv(os.path.join(out, "loss_1m.csv"), index=False)
    row = T.iloc[k].to_dict()
    wins = T[T["pnl"] > 0]
    ladder_px = fill * (1 + side * (0.12 / lev + rt))
    info.update({"trade": {kk: (None if isinstance(v, float) and not math.isfinite(v) else v) for kk, v in row.items()},
                 "ladder_start_px": ladder_px,
                 "closest_to_ladder_pct_of_way": 100 * side * (float(t.mfe_price) - fill) / (ladder_px - fill),
                 "stop_dist_pct_rank_among_all": int((T["stop_dist_pct"] >= row["stop_dist_pct"]).sum()),
                 "atr_pct_rank_among_all": int((T["atr_pct"] >= row["atr_pct"]).sum()),
                 "wins_mae_roe_net_median_pct": float(wins["mae_roe_net_pct"].median()),
                 "wins_mae_roe_net_min_pct": float(wins["mae_roe_net_pct"].min()),
                 "wins_mae_atr_min": float(wins["mae_atr"].min()),
                 "wins_deeper_than_loss_mae_atr": int((wins["mae_atr"] <= -1.5).sum()),
                 "ctx_signal": W.ctx.get(sig_of(W, t)["sig_id"])})
    return info


def rule_table(W, ctxs: dict, out: str) -> pd.DataFrame:
    """Each simple 'skip this signal' rule on the 27 paper trades (same entries, the rest unchanged) and on the
    account replayed with the rule (the freed account may take other signals)."""
    S, br = L.kernel_vectors(W)
    base = same_entries(W, VR.BASE, S=S, br=br)
    rows = []
    for name, label, f in F.RULES:
        skip = []
        for i, t in W.trades.iterrows():
            c = ctxs[t.symbol].at(int(t.signal_ts) + 1, int(t.side))
            try:
                skip.append(bool(f(c, int(t.side))))
            except Exception:  # noqa: BLE001
                skip.append(False)
        skip = np.array(skip)
        ret = np.where(skip, 0.0, base["ret"].to_numpy(float))
        loss = (W.trades["pnl"] <= 0).to_numpy()

        def ef(d, f=f):
            c = ctxs[d["symbol"]].at(d["bar_close"], d["side"])
            if f(c, d["side"]):
                return None
            return W.entry_index(d["symbol"], d["bar_close"]), d["ref_price"]
        k = L.kernel_account(W, VR.BASE, entry_fn=ef)
        rows.append({"rule": name, "label": label, "removes_losses": int((skip & loss).sum()),
                     "losses": int(loss.sum()), "wins_removed": int((skip & ~loss).sum()),
                     "wins_removed_pnl_pct": 100 * float(base["ret"].to_numpy()[skip & ~loss].sum()),
                     "same_entries_final": 5000 * float(np.prod(1 + ret)), **account_summary(k)})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "rules_window.csv"), index=False)
    return R


# ---------------------------------------------------------------------------------------------------- 4. what-ifs
def variant_rows(W, vlist, out_name: str, out: str, per_trade_name: str | None = None) -> pd.DataFrame:
    S, br = L.kernel_vectors(W)
    rows, wide = [], {}
    for v in vlist:
        se = same_entries(W, v, S=S, br=br)
        k = L.kernel_account(W, v)
        rows.append({"variant": v.name, "label": v.label, **summarize(se), **account_summary(k)})
        wide[v.name] = 100 * se["roe"].to_numpy(float)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, out_name), index=False)
    if per_trade_name:
        P = pd.DataFrame(wide)
        P.insert(0, "n", np.arange(1, len(P) + 1))
        P.insert(1, "symbol", W.trades["symbol"].str.replace("USDT", "").to_numpy())
        P.to_csv(os.path.join(out, per_trade_name), index=False)
    return R


def entry_rows(W, out: str) -> pd.DataFrame:
    S, br = L.kernel_vectors(W)
    rows, wide = [], {}
    for name, label, kind, p in VR.ENTRY:
        se = same_entries(W, VR.BASE, entry=(kind, p), S=S, br=br)
        k = L.kernel_account(W, VR.BASE, entry_fn=entry_fn_for(W, kind, p))
        loss_paper = (W.trades["pnl"] <= 0).to_numpy()
        skipped = (se["status"] != "ENTERED").to_numpy()
        rows.append({"variant": name, "label": label, **summarize(se), **account_summary(k),
                     "skipped_paper_wins": int((skipped & ~loss_paper).sum()),
                     "skipped_paper_losses": int((skipped & loss_paper).sum())})
        wide[name] = 100 * se["roe"].to_numpy(float)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "entry_variants.csv"), index=False)
    P = pd.DataFrame(wide)
    P.insert(0, "n", np.arange(1, len(P) + 1))
    P.to_csv(os.path.join(out, "entry_per_trade_roe.csv"), index=False)
    return R


def leverage_per_trade(W, out: str) -> pd.DataFrame:
    """Per trade and leverage plan: stop distance, liquidation distance, the bot's two safety checks, loss at the
    stop as a share of the wallet."""
    from paperbot.margin import liquidation_price
    from paperbot.sizing import _round_down
    S = W.S
    rows = []
    for i, t in W.trades.iterrows():
        d = sig_of(W, t)
        eq = float(t.equity_after - t.pnl)
        fill = float(t.entry_price)
        side = int(t.side)
        stop = float(t.stop_initial)
        plans = [("실제", int(t.leverage), int(t.leverage) / 100), ]
        lb = 40 if t.symbol == "BTCUSDT" else 30
        plans += [("40/30·증거금=배수%", lb, lb / 100), ("40/30·증거금40%", lb, 0.40), ("실제배수·증거금40%", int(t.leverage), 0.40)]
        for name, lev, frac in plans:
            qty = _round_down(eq * frac * lev / fill, W.specs[t.symbol]["qty_step"])
            notional = qty * fill
            margin = notional / lev
            br = W.brackets[t.symbol].for_notional(notional)
            liq = liquidation_price(side, qty, fill, margin, br)
            exit_px = stop * (1 - side * S.slippage_frac)
            loss = qty * abs(fill - stop) + qty * abs(stop - exit_px) + notional * S.taker_fee + qty * exit_px * S.taker_fee
            buffer = max(S.liq_buffer_min_frac * fill, S.liq_buffer_atr_mult * d["atr"])
            rows.append({"n": i + 1, "symbol": t.symbol.replace("USDT", ""), "plan": name, "leverage": lev,
                         "margin_pct": 100 * frac, "stop_dist_pct": 100 * abs(fill - stop) / fill,
                         "liq_dist_pct": 100 * abs(fill - liq) / fill,
                         "stop_inside_liq": bool((stop - liq) * side > 0),
                         "room_stop_to_liq_atr": (stop - liq) * side / d["atr"],
                         "passes_liq_buffer_1atr": bool((stop - liq) * side >= buffer),
                         "loss_at_stop_pct_equity": 100 * loss / eq,
                         "passes_loss_15pct": bool(loss <= S.max_loss_frac * eq),
                         "mmr": br.mmr})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(out, "leverage_per_trade.csv"), index=False)
    return R


def signal_check(W, five_dir: str, h1s: dict, out: str) -> dict:
    """The study's V3.9 code on public 1h bars vs the bot's own signal log (same bars -> same signals?)."""
    rows = []
    live = {(d["symbol"], d["bar_close"], d["side"]): d for d in W.sigs}
    late = {(r.symbol, int(r.bar_close), int(r.side)) for r in W.late.itertuples(index=False)}
    mine = {}
    for sym, h1 in h1s.items():
        s = F.v39_signals(h1)
        s = s[(s["close_ms"] >= W.start_ms + HOUR) & (s["close_ms"] <= W.end_ms)]
        for r in s.itertuples(index=False):
            mine[(sym, int(r.close_ms), int(r.side))] = r
    both = set(mine) & set(live)
    atr_err = [abs(mine[k].atr / live[k]["atr"] - 1) for k in both]
    rows = {"bot_submitted": len(live), "bot_late_or_record": len(late), "study_signals": len(mine),
            "in_both": len(both), "only_bot": sorted([f"{k[0]} {L.kst(k[1])} {k[2]}" for k in set(live) - set(mine)]),
            "only_study": sorted([f"{k[0]} {L.kst(k[1])} {k[2]}" for k in set(mine) - set(live)]),
            "atr_max_rel_err": float(max(atr_err)) if atr_err else None}
    return rows


# ---------------------------------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export")
    ap.add_argument("five_dir")
    ap.add_argument("out")
    ap.add_argument("--minute-dir", default=None)
    ap.add_argument("--cut-ms", type=int, default=None)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    W = L.Window(a.export, a.cut_ms)
    facts: dict = {"export": os.path.basename(os.path.abspath(a.export)), "cut_ms": a.cut_ms}
    log(f"loaded: {len(W.trades)} trades, {len(W.sigs)} signals ({time.time() - t0:.0f}s)")
    facts["replay"] = validate(W, a.out)
    log("replay:", facts["replay"])
    if a.minute_dir:
        facts["extended_minutes"] = W.extend(a.minute_dir)
    h1s = {s: F.hourly(a.five_dir, s, W.A[s]) for s in L.SYMBOLS}
    ctxs = {s: F.Context(h1s[s], h1s["BTCUSDT"]) for s in L.SYMBOLS}
    facts["signal_check"] = signal_check(W, a.five_dir, h1s, a.out)
    log("signal check:", {k: v for k, v in facts["signal_check"].items() if not isinstance(v, list)})
    T = trade_table(W, ctxs, a.out)
    facts["loss"] = loss_story(W, T, a.out)
    rules = rule_table(W, ctxs, a.out)
    log(rules[["rule", "removes_losses", "wins_removed", "same_entries_final", "acct_final"]].to_string())
    tp = variant_rows(W, VR.TP, "tp_variants.csv", a.out, "tp_per_trade_roe.csv")
    log(tp[["variant", "wins", "losses", "final", "worst_roe_pct", "dd_closed_pct", "acct_final", "acct_trades"]]
        .to_string())
    sl = variant_rows(W, VR.SL_SAME + VR.SL_RULE, "sl_variants.csv", a.out, "sl_per_trade_roe.csv")
    log(sl[["variant", "entered", "wins", "losses", "final", "worst_roe_pct", "acct_final"]].to_string())
    fg = variant_rows(W, VR.FG, "fullgrid_exits_window.csv", a.out)
    en = entry_rows(W, a.out)
    log(en[["variant", "entered", "skipped", "wins", "losses", "final", "skipped_paper_wins", "acct_final"]]
        .to_string())
    lv = variant_rows(W, VR.LEV, "lev_variants.csv", a.out)
    variant_rows(W, VR.PLAN, "plan_variants.csv", a.out, "plan_per_trade_roe.csv")   # owners' plan (10-25 night)
    log(lv[["variant", "wins", "losses", "final", "worst_ret_pct", "dd_closed_pct", "deepest_open_pct",
            "acct_final", "acct_dd_closed_pct"]].to_string())
    leverage_per_trade(W, a.out)
    # market over the window: the six coins from the first to the last bar, and the trade sides
    mk = {}
    for s in L.SYMBOLS:
        A = W.A[s]
        live = A["src_live"]
        c = A["c"][live]
        mk[s.replace("USDT", "")] = 100 * (c[-1] / c[0] - 1)
    facts["market_pct"] = mk
    facts["market_mean_pct"] = float(np.mean(list(mk.values())))
    facts["sides"] = {"long": int((W.trades["side"] > 0).sum()), "short": int((W.trades["side"] < 0).sum())}
    facts["by_coin"] = W.trades.groupby("symbol")["pnl"].agg(["count", "sum"]).round(2).to_dict()
    with open(os.path.join(a.out, "facts_window.json"), "w") as fh:
        json.dump(facts, fh, indent=1, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    log(f"done in {time.time() - t0:.0f}s -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
