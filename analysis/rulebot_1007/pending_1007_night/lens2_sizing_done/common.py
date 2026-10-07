"""Shared sizing math for the lens2 sizing study (read-only use of the repo).

Prices are normalised to fill = 1. d = initial stop distance as a fraction of the fill (2 ATR + entry slippage,
as fy36_rerun / live replay define stop_frac). a = ATR as a fraction of price.

Rules (live settings: config.v3_settings(): taker 0.05%, slippage 0.02%, liq buffer max(1 ATR, 0.2%), max loss 15%):
  margin rule  M_L : margin = L% of equity, notional N = L * L/100 * E (paper v4 quality_v1 tiers)
  risk rule    R_r_L: notional N = r * E / loss_per_notional(d); margin = N / L (isolated)
Liquidation: paperbot.margin.liquidation_price with the brackets analyze.py inferred from the live trades.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
REPO = '/home/user/crypto-bot-research'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np  # noqa: E402

TAKER = 0.0005
SLIP = 0.0002
MAX_LOSS = 0.15
BUF_ATR = 1.0
BUF_MIN = 0.002
E0 = 5000.0
LEVS = (10, 20, 30, 40, 50)

# analyze.py INFERRED_BRACKETS (fit the live trades' liq prices exactly): (notional_cap, max_lev_seen, mmr, cum)
BR = {
    "BTC": [(1e12, 50, 0.004, 0.0)],
    "ETH": [(1e12, 50, 0.004, 0.0)],
    "SOL": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGE": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCH": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTC": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}


def coin_key(sym: str) -> str:
    for k in BR:
        if str(sym).upper().startswith(k):
            return k
    raise KeyError(sym)


def bracket(coin: str, notional):
    """(max_lev, mmr, cum) arrays for notional array."""
    notional = np.asarray(notional, float)
    ml = np.zeros_like(notional)
    mmr = np.zeros_like(notional)
    cum = np.zeros_like(notional)
    done = np.zeros(notional.shape, bool)
    for cap, lev, m, c in BR[coin]:
        sel = (~done) & (notional <= cap)
        ml[sel], mmr[sel], cum[sel] = lev, m, c
        done |= sel
    return ml, mmr, cum


def loss_per_notional(d, side=1):
    """size_position's loss at the stop per unit notional (fill = 1): stop move + exit slippage + 2 taker fees."""
    d = np.asarray(d, float)
    stop = 1 - side * d
    exit_px = stop * (1 - side * SLIP)
    return d + np.abs(stop - exit_px) + TAKER + exit_px * TAKER


def liq_frac(side, notional, margin, mmr, cum):
    """Distance fill -> liquidation as a fraction (fill = 1), Binance isolated formula (paperbot.margin)."""
    side = np.asarray(side, float)
    q = notional  # qty at fill 1
    lp = (margin + cum - side * q * 1.0) / (q * mmr - side * q)
    lp = np.maximum(lp, 0.0)
    return side * (1.0 - lp)


def check(coin, side, d, a, L, notional, equity=E0, max_loss=MAX_LOSS, use_maxloss=True):
    """Executability of one candidate (vectorised). Returns dict of bool arrays + liq distance + loss frac."""
    d = np.asarray(d, float)
    a = np.asarray(a, float)
    notional = np.broadcast_to(np.asarray(notional, float), d.shape).copy()
    margin = notional / L
    ml, mmr, cum = bracket(coin, notional)
    lq = liq_frac(side, notional, margin, mmr, cum)
    buf = np.maximum(BUF_ATR * a, BUF_MIN)
    room_ok = (lq - d) >= buf
    br_ok = ml >= L
    lossf = notional * loss_per_notional(d, side) / equity
    loss_ok = lossf <= max_loss + 1e-12 if use_maxloss else np.ones(d.shape, bool)
    marg_ok = margin <= equity
    return dict(br_ok=br_ok, room_ok=room_ok, loss_ok=loss_ok, marg_ok=marg_ok,
                ok=br_ok & room_ok & loss_ok & marg_ok, liq=lq, lossf=lossf, margin_frac=margin / equity)


def margin_rule(coin, side, d, a, L, equity=E0):
    return check(coin, side, d, a, L, L * L / 100.0 * equity, equity)


def risk_rule(coin, side, d, a, L, r, equity=E0):
    n = r * equity / loss_per_notional(d, side)
    return check(coin, side, d, a, L, n, equity, use_maxloss=False)


def atr_from_stop(stop_frac, side, k=2.0):
    """fy36 stop_frac = (raw*slip + k*atr)/fill, fill = raw*(1+side*slip) -> atr/raw."""
    return (np.asarray(stop_frac, float) * (1 + np.asarray(side) * SLIP) - SLIP) / k
