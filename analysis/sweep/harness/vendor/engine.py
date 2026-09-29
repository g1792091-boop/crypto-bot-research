"""Bar-level futures backtest engine (long + short).

Conventions
-----------
* signal on bar i close  -> market entry at bar i+1 open (+ slippage)
* SL / trailing / ladder stops are stop-market orders: filled at the stop
  level (or the bar open if the bar gaps through it) minus slippage
* TP is a resting limit order: filled at the TP level (or a better open)
* if SL and TP are both touched inside one bar, SL is assumed first
* trailing / ladder stop levels are computed from the peak up to the
  PREVIOUS bar (a stop raised by bar j cannot be hit by bar j itself)
* costs: taker fee per side, slippage per market side, funding per 8h
* results are in PRICE fraction terms; leverage / margin are applied
  afterwards by `leverage_layer` (liquidation via MAE)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class ExitCfg:
    name: str
    mode: str = "FIXED"        # FIXED | TRAIL | LADDER
    sl_atr: float = 1.5        # FIXED / TRAIL: stop distance in ATR14 multiples
    tp_atr: float = 2.0        # FIXED: target distance in ATR14 multiples
    trail_atr: float = 2.0     # TRAIL: distance from peak
    lev: float = 50.0          # LADDER: leverage used to translate ROE -> price
    sl_roe: float = 20.0       # LADDER: gross ROE stop (%)
    ladder: tuple = ((12.0, 11.0), (16.0, 15.0), (21.0, 20.0))  # (trigger, lock) gross ROE %
    ladder_step: float = 5.0   # after last rung: every +step, lock = trigger-1


@dataclass
class CostCfg:
    fee_side: float = 0.0005     # taker 0.05 %
    slip_side: float = 0.0002    # 0.02 % per market fill
    funding_8h: float = 0.0001   # 0.01 % per 8h, charged to both sides
    bar_minutes: int = 15
    max_hold: int = 1000
    warmup: int = 1000


def ladder_lock(peak_roe: np.ndarray, cfg: ExitCfg) -> np.ndarray:
    """Vectorised protective lock level (gross ROE %) for a given running peak ROE.
    Returns -inf where no rung is reached."""
    lock = np.full(peak_roe.shape, -np.inf)
    for trig, lk in cfg.ladder:
        lock = np.where(peak_roe >= trig, lk, lock)
    last_trig, last_lock = cfg.ladder[-1]
    beyond = peak_roe >= last_trig + cfg.ladder_step
    k = np.floor((peak_roe - last_trig) / cfg.ladder_step)
    lock = np.where(beyond, last_lock + k * cfg.ladder_step, lock)
    return lock


def _simulate_one(side: int, e: int, o, h, l, c, atr_e: float, cfg: ExitCfg, cost: CostCfg, n: int):
    """Simulate a single trade entered at bar e open. Returns dict."""
    entry_raw = o[e]
    entry = entry_raw * (1.0 + side * cost.slip_side)
    last = min(n - 1, e + cost.max_hold - 1)
    oo, hh, ll, cc = o[e:last + 1], h[e:last + 1], l[e:last + 1], c[e:last + 1]
    m = len(oo)
    if cfg.mode == "LADDER":
        sl_dist = cfg.sl_roe / 100.0 / cfg.lev
    else:
        sl_dist = cfg.sl_atr * atr_e / entry
    sl_px = entry * (1.0 - side * sl_dist)
    # adverse / favourable extremes per bar
    adverse = ll if side > 0 else hh
    favour = hh if side > 0 else ll
    hit_sl = (adverse <= sl_px) if side > 0 else (adverse >= sl_px)
    reason = None
    j_exit = None
    exit_px = None
    if cfg.mode == "FIXED":
        tp_px = entry * (1.0 + side * cfg.tp_atr * atr_e / entry)
        hit_tp = (favour >= tp_px) if side > 0 else (favour <= tp_px)
        any_hit = hit_sl | hit_tp
        if any_hit.any():
            j = int(np.argmax(any_hit))
            if hit_sl[j]:
                reason = "SL"
                fill = min(oo[j], sl_px) if side > 0 else max(oo[j], sl_px)
                exit_px = fill * (1.0 - side * cost.slip_side)
            else:
                reason = "TP"
                fill = max(oo[j], tp_px) if side > 0 else min(oo[j], tp_px)
                exit_px = fill
            j_exit = j
    else:
        # dynamic stop from running peak up to previous bar
        peak = np.maximum.accumulate(favour) if side > 0 else np.minimum.accumulate(favour)
        peak_prev = np.concatenate([[entry], peak[:-1]])
        if cfg.mode == "TRAIL":
            trail = peak_prev - side * cfg.trail_atr * atr_e
            stop = np.maximum(sl_px, trail) if side > 0 else np.minimum(sl_px, trail)
        elif cfg.mode == "LADDER":
            peak_roe = side * (peak_prev / entry - 1.0) * 100.0 * cfg.lev
            lock = ladder_lock(peak_roe, cfg)
            lock_px = entry * (1.0 + side * lock / 100.0 / cfg.lev)
            stop = np.where(np.isfinite(lock), np.maximum(sl_px, lock_px) if side > 0 else np.minimum(sl_px, lock_px), sl_px)
        else:
            raise ValueError(cfg.mode)
        hit = (adverse <= stop) if side > 0 else (adverse >= stop)
        if hit.any():
            j = int(np.argmax(hit))
            st = stop[j]
            fill = min(oo[j], st) if side > 0 else max(oo[j], st)
            exit_px = fill * (1.0 - side * cost.slip_side)
            reason = "SL" if (abs(st - sl_px) < 1e-12) else ("LOCK" if cfg.mode == "LADDER" else "TRAIL")
            j_exit = j
    if j_exit is None:
        j_exit = m - 1
        reason = "TIME" if last < n - 1 else "EOD"
        exit_px = cc[j_exit] * (1.0 - side * cost.slip_side)
    hold = j_exit + 1
    seg_adv = adverse[: j_exit + 1]
    seg_fav = favour[: j_exit + 1]
    mae = side * (seg_adv.min() / entry - 1.0) if side > 0 else side * (seg_adv.max() / entry - 1.0)
    mfe = side * (seg_fav.max() / entry - 1.0) if side > 0 else side * (seg_fav.min() / entry - 1.0)
    gross = side * (exit_px / entry - 1.0)
    fee = 2.0 * cost.fee_side
    funding = cost.funding_8h * (hold * cost.bar_minutes / 480.0)
    net = gross - fee - funding
    return dict(side=side, entry_idx=e, exit_idx=e + j_exit, entry_px=entry, exit_px=exit_px,
                gross=gross, fee=fee, funding=funding, net=net, mae=mae, mfe=mfe,
                reason=reason, hold=hold, sl_dist=sl_dist)


def run_backtest(bars: pd.DataFrame, atr: np.ndarray, long_sig: np.ndarray, short_sig: np.ndarray,
                 cfg: ExitCfg, cost: CostCfg, start_idx: int = 0, end_idx: Optional[int] = None) -> pd.DataFrame:
    """Sequential single-position simulation. Entries only for signal bars in [start_idx, end_idx)."""
    o = bars["open"].to_numpy(dtype=float)
    h = bars["high"].to_numpy(dtype=float)
    l = bars["low"].to_numpy(dtype=float)
    c = bars["close"].to_numpy(dtype=float)
    n = len(o)
    end_idx = n if end_idx is None else end_idx
    start_idx = max(start_idx, cost.warmup)
    sig_idx = np.where((long_sig | short_sig)[start_idx:end_idx])[0] + start_idx
    trades: List[dict] = []
    next_free = -1
    for i in sig_idx:
        if i <= next_free:
            continue
        if i + 1 >= n:
            break
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        side = 1 if long_sig[i] else -1
        t = _simulate_one(side, i + 1, o, h, l, c, float(atr[i]), cfg, cost, n)
        t["signal_idx"] = int(i)
        trades.append(t)
        next_free = t["exit_idx"]  # a signal on the exit bar itself is allowed (entry next open)
    if not trades:
        return pd.DataFrame(columns=["side", "entry_idx", "exit_idx", "entry_px", "exit_px", "gross", "fee",
                                     "funding", "net", "mae", "mfe", "reason", "hold", "sl_dist", "signal_idx"])
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# metrics + leverage layer
# ---------------------------------------------------------------------------
def leverage_layer(trades: pd.DataFrame, lev: float, margin_frac: float = 0.40, mmr: float = 0.005):
    """Compound a ledger. Liquidation if MAE reaches the liquidation distance."""
    if len(trades) == 0:
        return dict(final=1.0, mdd=0.0, liq=0, min_equity=1.0)
    liq_dist = 1.0 / lev - mmr
    net = trades["net"].to_numpy(dtype=float)
    mae = trades["mae"].to_numpy(dtype=float)
    liq = mae <= -liq_dist
    roe = np.where(liq, -1.0, lev * net)
    roe = np.maximum(roe, -1.0)
    growth = 1.0 + margin_frac * roe
    equity = np.cumprod(growth)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    dd = 1.0 - equity / peak
    return dict(final=float(equity[-1]), mdd=float(dd.max()), liq=int(liq.sum()), min_equity=float(equity.min()))


def summarize(trades: pd.DataFrame, levs=(5, 10, 20, 50)) -> dict:
    n = len(trades)
    out = dict(trades=n)
    if n == 0:
        return out
    net = trades["net"].to_numpy(dtype=float)
    gross = trades["gross"].to_numpy(dtype=float)
    wins = net > 0
    out["wr"] = float(wins.mean())
    gp = net[wins].sum()
    gl = -net[~wins].sum()
    out["pf"] = float(gp / gl) if gl > 0 else float("inf")
    out["exp_net_pct"] = float(net.mean() * 100)
    out["exp_gross_pct"] = float(gross.mean() * 100)
    out["avg_win_pct"] = float(net[wins].mean() * 100) if wins.any() else 0.0
    out["avg_loss_pct"] = float(net[~wins].mean() * 100) if (~wins).any() else 0.0
    out["payoff"] = float(-out["avg_win_pct"] / out["avg_loss_pct"]) if out["avg_loss_pct"] < 0 else float("inf")
    out["sum_net_pct"] = float(net.sum() * 100)
    out["avg_hold"] = float(trades["hold"].mean())
    out["long_share"] = float((trades["side"] > 0).mean())
    out["wr_long"] = float(wins[trades["side"].to_numpy() > 0].mean()) if (trades["side"] > 0).any() else float("nan")
    out["wr_short"] = float(wins[trades["side"].to_numpy() < 0].mean()) if (trades["side"] < 0).any() else float("nan")
    out["net_long_pct"] = float(net[trades["side"].to_numpy() > 0].sum() * 100)
    out["net_short_pct"] = float(net[trades["side"].to_numpy() < 0].sum() * 100)
    for r in ("SL", "TP", "TRAIL", "LOCK", "TIME", "EOD"):
        out[f"n_{r}"] = int((trades["reason"] == r).sum())
    for L in levs:
        ll = leverage_layer(trades, float(L))
        out[f"eq_L{L}"] = ll["final"]
        out[f"mdd_L{L}"] = ll["mdd"]
        out[f"liq_L{L}"] = ll["liq"]
    return out


def default_exit_configs() -> List[ExitCfg]:
    cfgs = []
    for sl in (1.0, 1.5, 2.0):
        for tp in (1.5, 2.0, 3.0):
            cfgs.append(ExitCfg(name=f"F_sl{sl}_tp{tp}", mode="FIXED", sl_atr=sl, tp_atr=tp))
    for tr in (1.5, 2.5):
        cfgs.append(ExitCfg(name=f"T_sl1.5_tr{tr}", mode="TRAIL", sl_atr=1.5, trail_atr=tr))
    cfgs.append(ExitCfg(name="L50_sl15", mode="LADDER", lev=50.0, sl_roe=15.0))
    cfgs.append(ExitCfg(name="L50_sl20", mode="LADDER", lev=50.0, sl_roe=20.0))
    return cfgs
