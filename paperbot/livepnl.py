"""Live trade P&L and trading cost from the exchange's own records (pure functions + read-only paper3.db).

P&L of one live trade = sum(realizedPnl of its fills) - sum(commission) + sum(funding)
  fills:   GET /fapi/v1/userTrades  (price, qty, realizedPnl, commission, commissionAsset, side, time), only the
           trade's own orders (the executor filters them by orderId)
  funding: GET /fapi/v1/income  FUNDING_FEE (and SPECIAL_FUNDING_FEE, INSURANCE_CLEAR: a liquidation's clearance
           fee) while the position was open (income, signed: + received, - paid)
  A record is final only when the closing fills add up to the opening fills (a fill not yet visible right after
  the close would otherwise be booked as a half trade).

Cost (paper v3.1 addendum Q6 #4: real cost / assumed cost <= 1.5):
  real cost    = commission + slippage, slippage = how much worse each fill was than the price the
                 executor saw when it decided (entry: last price just before the order; exit: the stop
                 level for an exchange stop, the last price just before a market close). Positive = worse.
  assumed cost = what the paper rules charge for the same notional: taker fee + 0.02 % slippage on the
                 entry and on the exit (paperbot/config.py: taker_fee, slippage_frac).
  ratio        = sum(real cost) / sum(assumed cost) over every measured trade.

Funding is part of the P&L, not of the cost ratio (the paper engine charges funding too).
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from typing import Optional

PAPER_TAKER_FEE = 0.0005       # paperbot/config.py Settings.taker_fee (live3 may use the account's real rate)
PAPER_SLIPPAGE = 0.0002        # paperbot/config.py Settings.slippage_frac
QUOTE_ASSETS = ("USDT", "USDC")


def balanced(side: int, fills: list, qty_step: float = 1e-9) -> bool:
    """Do the closing fills add up to the opening fills (within half a quantity step)?"""
    open_side = "BUY" if side > 0 else "SELL"
    qty_in = sum(float(f["qty"]) for f in fills if f.get("side") == open_side)
    qty_out = sum(float(f["qty"]) for f in fills if f.get("side") != open_side)
    return bool(fills) and qty_in > 0 and abs(qty_in - qty_out) <= qty_step / 2 + 1e-12


def trade_costs(side: int, fills: list, funding: list, entry_ref: Optional[float], exit_ref: Optional[float],
                taker_fee: float = PAPER_TAKER_FEE, slippage: float = PAPER_SLIPPAGE, qty_step: float = 1e-9,
                prices: Optional[dict] = None) -> dict:
    """One trade's P&L and cost from its fills (userTrades rows) and funding (income rows).

    ``ok`` is False when the record cannot be trusted as a cost measurement: no fills, a commission paid in
    another asset (e.g. BNB fee discount), a missing reference price, or fills that do not add up.
    ``final`` is False when the P&L itself cannot be trusted yet: the closing quantity does not match the opening
    one, or a commission in another asset could not be valued (``prices``: asset -> USDT price; such a
    commission is valued at that price and counted in the P&L)."""
    open_side = "BUY" if side > 0 else "SELL"
    entry = [f for f in fills if f.get("side") == open_side]
    exit_ = [f for f in fills if f.get("side") != open_side]
    qty_in = sum(float(f["qty"]) for f in entry)
    qty_out = sum(float(f["qty"]) for f in exit_)
    n_in = sum(float(f["qty"]) * float(f["price"]) for f in entry)
    n_out = sum(float(f["qty"]) * float(f["price"]) for f in exit_)
    realized = sum(float(f.get("realizedPnl") or 0) for f in fills)
    other_assets = sorted({f.get("commissionAsset") for f in fills} - set(QUOTE_ASSETS) - {None})
    prices = prices or {}
    commission = sum(float(f.get("commission") or 0) for f in fills if f.get("commissionAsset") in QUOTE_ASSETS
                     or f.get("commissionAsset") is None)
    unvalued = [a for a in other_assets if not prices.get(a)]
    commission += sum(float(f.get("commission") or 0) * float(prices[f["commissionAsset"]]) for f in fills
                      if f.get("commissionAsset") in other_assets and prices.get(f["commissionAsset"]))
    fund = sum(float(r.get("income") or 0) for r in funding)
    whole = balanced(side, fills, qty_step)
    avg_in = n_in / qty_in if qty_in else None
    avg_out = n_out / qty_out if qty_out else None
    slip = 0.0
    problems = []
    if avg_in is not None:
        if entry_ref:
            slip += qty_in * side * (avg_in - entry_ref)
        else:
            problems.append("진입 기준가 없음")
    if avg_out is not None:
        if exit_ref:
            slip += qty_out * side * (exit_ref - avg_out)
        else:
            problems.append("청산 기준가 없음")
    if not fills:
        problems.append("체결 기록 없음")
    elif not whole:
        problems.append(f"체결 수량이 맞지 않음(들어감 {qty_in:g}, 나감 {qty_out:g}): 나중에 다시 읽음")
    if other_assets:
        problems.append(f"수수료가 {', '.join(other_assets)}로 나감("
                        + ("지금 가격으로 USDT 환산" if not unvalued else f"{', '.join(unvalued)} 환산 못 함") + ")")
    assumed = (n_in + n_out) * (taker_fee + slippage)
    return {"pnl": realized - commission + fund, "realized": realized, "commission": commission, "funding": fund,
            "slippage": slip, "real_cost": commission + slip, "assumed_cost": assumed,
            "notional_in": n_in, "notional_out": n_out, "qty_in": qty_in, "qty_out": qty_out,
            "avg_in": avg_in, "avg_out": avg_out, "ok": not problems, "problems": problems,
            "final": whole and not unvalued, "balanced": whole,
            "fills": len(fills), "assumed_rates": {"taker_fee": taker_fee, "slippage": slippage}}


def cost_ratio(rows: list) -> dict:
    """Sum of real cost / sum of assumed cost over the trades whose cost was measured (``ok``)."""
    ok = [r for r in rows if r.get("ok") and r.get("assumed_cost")]
    real = sum(float(r["real_cost"]) for r in ok)
    assumed = sum(float(r["assumed_cost"]) for r in ok)
    return {"ratio": (real / assumed) if assumed > 0 else None, "real": real, "assumed": assumed,
            "measured": len(ok), "trades": len(rows)}


# ---------------------------------------------------------------- paper3.db (read-only)
def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def paper_pnl(paper_db: str, account: str, start_ms: int, end_ms: int) -> Optional[dict]:
    """The paper account's closed-trade P&L over the same days (trades that exited in [start, end])."""
    try:
        conn = _ro(paper_db)
    except sqlite3.Error:
        return None
    try:
        n, pnl = conn.execute("SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM trades WHERE account_id = ? "
                              "AND exit_time >= ? AND exit_time <= ?", (account, start_ms, end_ms)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return {"trades": int(n), "pnl": float(pnl)}


def paper_taker_fee(paper_db: str, account: Optional[str] = None, default: float = PAPER_TAKER_FEE) -> float:
    """The taker fee the paper run actually charges (live3 uses the account's real commission rate when it
    has a key): median of fees / (entry + exit notional) over recent non-liquidation trades."""
    try:
        conn = _ro(paper_db)
    except sqlite3.Error:
        return default
    try:
        q = "SELECT data FROM trades WHERE exit_reason != 'LIQ'" + (" AND account_id = ?" if account else "") + \
            " ORDER BY id DESC LIMIT 200"
        rows = conn.execute(q, (account,) if account else ()).fetchall()
    except sqlite3.Error:
        return default
    finally:
        conn.close()
    rates = []
    for (data,) in rows:
        try:
            d = json.loads(data)
            notional = float(d["qty"]) * (float(d["entry_price"]) + float(d["exit_price"]))
            if notional > 0:
                rates.append(float(d["fees"]) / notional)
        except (ValueError, KeyError, TypeError):
            continue
    return statistics.median(rates) if rates else default
