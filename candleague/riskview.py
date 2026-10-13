"""위험 점검 (league.json key ``risk``): how crowded is the owner-exit league on ONE side, and what was the worst that already happened?

The owners' goal includes a low drawdown at 20-50x leverage. The loss autopsy (research/autopsy/LOSS_AUTOPSY.md, finding 5) says the real tail
risk is not one bad trade but many positions on the same side of correlated coins: same-side pair outcome correlation +0.46..+0.51, five or
six coins on one side all lose 13.5% of the time against 0.5% if they were independent. This module only COUNTS; it never advises (the owners
decide) and it never tests anything (nothing here passes or fails).

Pure functions of the closed-trade book ({account id: trades in exit order}, runner.closed_trades), the account rows (runner.account_rows:
wallet, bust flag and the open position {symbol, side, entry, stop, tp, since, lev}) and the lineup (rulex.lineup). No clock, no randomness:
the same data always gives the same numbers. Fractions, not percent (0.1 = 10%; the codebase's ``*_pct`` unit). Cheap: one pass over the
trades of the shown kinds, numpy for the curves (about a second for a million trades).

The block, ``risk_views(...)``::

    {"equity0", "ds_in_stats", "thresholds": {same_side, min_open, min_day_trades}, "headline_ko", "rules_ko": [...], "note_ko": [...],
     "kinds": [kind, ...]}      # 실전 후보 (-fq), 대조 (-ld), then the next 메인 kinds (four in all), then the pooled "메인 전체"

    kind = {"role", "suffix", "label_ko", "name_ko", "short_ko", "group", "live", "pooled", "accounts", "trades", "now", "worst", "days"}

    now   (1) the open positions: {"open", "long", "short", "same_side" (1 long / -1 short / None even), "same_side_share", "crowded" (>= 80% the
          same side AND >= 10 open), "coins": [{coin, long, short}], "cluster": {side, side_n, coins, n, text_ko} ("롱 14개 중 BTC·ETH·SOL 9개"),
          "lev_mean", "lev_max", "margin": {...}, "stop": {...}}
          margin: {"n", "missing", "sum", "wallets", "wallet_mean", "separate_pct", "shared_pct"} -- sum of the open margins over the sum of the kind's
          wallets (the accounts as they are: one wallet each) and over ONE wallet (the same positions in a single shared account).
          stop: {"n", "locked", "no_stop", "loss", "long_loss", "short_loss", "separate_pct", "shared_pct", "worst_acct_pct"} -- what the positions
          whose stop is still on the losing side would lose if every one of them hit its stop at once (stop P&L = side x qty x (stop - entry), no
          exit fee or slippage), as a share of all the wallets / of ONE wallet / of the single most hit wallet.
    worst (2) the closed trades: {"trades", "accounts", "trade": {pct, pnl, coin, side, lev, reason, exit_ms, account, pick} (the worst one: P&L over
          the wallet BEFORE it), "streak": {max, median, now_max, account} (consecutive losing trades), "dd": {basket, accounts, acct_worst,
          acct_worst_id} (max drawdown of the equal-weight average wallet / of the worst single wallet; realised wallets only), "liq_n", "bust",
          "sl_n", "lock_n", "stop_share"}
    days  (3) {"min_trades", "threshold", "total", "eligible", "crowded", "share", "long", "short", "lopsided": {day_ms, n, share, side},
          "coin_ref": {suffix, name_ko, eligible, crowded, share}}: the UTC days when >= 80% of the (>= 10) trades entered that day were the same
          side. ``coin_ref`` is the same count for the kind's coin-flip twin (what random directions give), where the lineup has one.

What the snapshot does NOT carry: the open position's size / margin (qty, margin_initial). They are rebuilt from the sizing rule exactly as
candleague/dash.py rebuild_open does without the engine's own numbers (margin fraction = leverage / 100 x size of the equity at entry, the entry
fee comes off the wallet): estimates, ``exact`` is False. Open (unrealised) P&L is not in any figure.

DeepSeek money (D11): the same rule as summary.decision_views: without ``ds_money`` every DeepSeek account is left out of every figure
(counts included); nothing about it leaves this module."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from . import exits as X

DAY_MS = 86_400_000
SAME_SIDE = 0.8                       # >= this share of the open positions (or of a day's entries) on one side is "the same side"
MIN_OPEN = 10                         # ... and only with at least this many open positions
MIN_DAY_TRADES = 10                   # a day with fewer entries says nothing about a crowd
MAX_KINDS = 4                         # 실전 후보, 대조 and the next 메인 kinds up to four (and the pooled 메인 전체 on top)
LIVE = "-fq"                          # 실전 후보
CONTROL = "-ld"                       # 대조
COIN_TWIN = {"-fq": "-fqc", "-ld": "-ldc"}
POOLED_ROLE = "main_all"
POOLED_KO = "메인 전체"
TAKER_FEE = 0.0005                    # paperbot.config.Settings.taker_fee (dash.TAKER_FEE; a test keeps them equal)
CLUSTER_COINS = 3
_PREFIX_KO = ("메인", "대조", "연구", "필터")

MINUS = "−"


# ---------------------------------------------------------------- small helpers
def _num(x) -> Optional[float]:
    """A finite float, else None (a stored NaN, a bool, text)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _sgn(x) -> int:
    v = _num(x)
    return 0 if v is None or v == 0 else (1 if v > 0 else -1)


def _shown(row: dict, ds_money: bool) -> bool:
    """summary._shown: a DeepSeek account counts only with ``ds_money``."""
    return row.get("kind") != "ds" or bool(ds_money)


def _group(label_ko) -> str:
    """summary.kind_group: "main" | "control" | "research" by the label's first word."""
    s = str(label_ko or "").lstrip()
    return "main" if s.startswith("메인") else "control" if s.startswith("대조") else "research"


def _name(k: dict) -> str:
    """The kind's short Korean name without its group word and the 실전 후보 mark ("빠른 손절")."""
    s = str(k.get("short_ko") or k.get("label_ko") or k.get("role") or "").strip()
    for p in _PREFIX_KO:
        if s.startswith(p):
            s = s[len(p):].lstrip(" ·").strip()
            break
    s = s.replace("(실전 후보)", "").strip()
    return s or str(k.get("role") or "")


def _coin(symbol) -> str:
    s = str(symbol or "")
    return s[:-4] if s.endswith("USDT") else s


def _r(x: Optional[float], d: int = 6) -> Optional[float]:
    return None if x is None else round(float(x), d)


def _div(a, b) -> Optional[float]:
    return None if b is None or not b else float(a) / float(b)


def _pct_ko(f: Optional[float], dec: int = 1) -> str:
    """0.0821 -> "8.2%", -0.0821 -> "−8.2%"; None -> "—"."""
    if f is None:
        return "—"
    t = f"{abs(f) * 100:.{dec}f}"
    return (MINUS if f < 0 and any(c in "123456789" for c in t) else "") + t + "%"


def _threshold_ko() -> str:
    return f"{int(round(SAME_SIDE * 100))}%"


# ---------------------------------------------------------------- one account's closed trades
def _arrays(trades: list) -> dict:
    """The columns of one account's closed trades (exit order): pnl, entry / exit ms (NaN / inf when missing), side, and the reason counts."""
    pnl, t_in, t_out, side = [], [], [], []
    liq = sl = lock = 0
    for t in trades:
        pnl.append(_num(t.get("pnl")) or 0.0)
        e, x = _num(t.get("entry_time")), _num(t.get("exit_time"))
        t_in.append(math.nan if e is None else e)
        t_out.append(math.inf if x is None else x)
        side.append(_sgn(t.get("side")))
        why = t.get("exit_reason")
        if why == "LIQ":
            liq += 1
        elif why == "SL":
            sl += 1
        elif why == "LOCK":
            lock += 1
    return {"pnl": np.array(pnl, dtype=float), "t_in": np.array(t_in, dtype=float), "t_out": np.array(t_out, dtype=float),
            "side": np.array(side, dtype=np.int8), "liq": liq, "sl": sl, "lock": lock}


def _runs(loss: np.ndarray) -> tuple:
    """(longest run of True, the run that is still going at the end) of a boolean array."""
    if not loss.any():
        return 0, 0
    d = np.diff(np.concatenate(([0], loss.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    lens = ends - starts
    return int(lens.max()), int(lens[-1]) if ends[-1] == len(loss) else 0


def _account_stats(a: dict, eq0: float) -> dict:
    """Worst trade (P&L over the wallet before it), longest losing streak, the account's own max drawdown (realised wallet)."""
    pnl = a["pnl"]
    n = len(pnl)
    if n == 0:
        return {"n": 0}
    cum = np.cumsum(pnl)
    before = eq0 + cum - pnl
    ok = before > 0
    pct = np.where(ok, pnl / np.where(ok, before, 1.0), 0.0)
    i = int(np.argmin(pct))
    streak, now = _runs(pnl < 0)
    wallet = eq0 + cum
    peak = np.maximum.accumulate(np.maximum(wallet, eq0))
    dd = float(np.max((peak - wallet) / peak))
    return {"n": n, "worst_i": i, "worst_pct": float(pct[i]), "streak": streak, "streak_now": now, "dd": min(1.0, max(0.0, dd))}


class _Acct:
    """One shown account: its row, its closed-trade columns and per-account numbers (built once; the pooled group reuses them)."""

    __slots__ = ("row", "id", "trades", "cols", "st")

    def __init__(self, row: dict, trades: list, eq0: float) -> None:
        self.row, self.id, self.trades = row, row.get("id"), trades
        self.cols = _arrays(trades)
        self.st = _account_stats(self.cols, eq0)


# ---------------------------------------------------------------- (1) the open positions now
def _position(row: dict) -> Optional[dict]:
    """The account's open position: {coin, side, lev, margin, wallet, stop_pnl}; margin and stop_pnl None where the snapshot lacks what they need.

    margin = E x lev / 100 x size with E = wallet / (1 - frac x lev x taker fee) (the wallet is what is left after the entry fee: dash.rebuild_open
    without the order-size rounding); stop_pnl = side x qty x (stop - entry) = margin x lev x side x (stop - entry) / entry."""
    o = row.get("open")
    if not o:
        return None
    side = _sgn(o.get("side"))
    if not side:
        return None
    p = {"coin": _coin(o.get("symbol")) or "기타", "side": side, "lev": None, "margin": None, "wallet": None, "stop_pnl": None, "has_stop": False}
    lev, entry, wallet = _num(o.get("lev")), _num(o.get("entry")), _num(row.get("wallet"))
    size = _num(row.get("size"))
    size = 1.0 if size is None or size <= 0 else size
    if lev is not None and lev > 0:
        p["lev"] = lev
    if not (lev and lev > 0 and entry and entry > 0 and wallet and wallet > 0):
        return p
    frac = round(lev / 100.0 * size, 6)
    denom = 1.0 - frac * lev * TAKER_FEE
    if denom <= 0:
        return p
    margin = wallet / denom * frac
    p["margin"], p["wallet"] = margin, wallet
    stop = _num(o.get("stop"))
    if stop is not None and stop > 0:
        p["has_stop"] = True
        p["stop_pnl"] = margin * lev * side * (stop - entry) / entry
    return p


def _cluster(coins: dict) -> Optional[dict]:
    """The largest same-side cluster: the side whose CLUSTER_COINS busiest coins hold the most positions ("롱 14개 중 BTC·ETH·SOL 9개")."""
    best = None
    for si, side in ((0, 1), (1, -1)):
        lst = sorted(((c, v[si]) for c, v in coins.items() if v[si] > 0), key=lambda x: (-x[1], x[0]))
        if not lst:
            continue
        total = sum(n for _c, n in lst)
        top = lst[:CLUSTER_COINS]
        top_n = sum(n for _c, n in top)
        key = (top_n, total, side)
        if best is None or key > best[0]:
            best = (key, side, total, [c for c, _n in top], top_n)
    if best is None:
        return None
    _k, side, total, names, top_n = best
    word = "롱" if side > 0 else "숏"
    text = f"{word} {total}개 모두 {'·'.join(names)}" if top_n == total else f"{word} {total}개 중 {'·'.join(names)} {top_n}개"
    return {"side": side, "side_n": total, "coins": names, "n": top_n, "text_ko": text}


def _now(accts: list) -> dict:
    longs = shorts = 0
    coins: dict = {}
    levs = []
    n_priced = n_missing = 0
    msum = 0.0
    n_loss = n_locked = n_nostop = 0
    loss = {1: 0.0, -1: 0.0}
    worst_acct = None
    wallets = [w for w in (_num(a.row.get("wallet")) for a in accts) if w is not None and w > 0]
    for a in accts:
        p = _position(a.row)
        if p is None:
            continue
        c = coins.setdefault(p["coin"], [0, 0])
        if p["side"] > 0:
            longs += 1
            c[0] += 1
        else:
            shorts += 1
            c[1] += 1
        if p["lev"] is not None:
            levs.append(p["lev"])
        if p["margin"] is None:
            n_missing += 1
            continue
        n_priced += 1
        msum += p["margin"]
        if not p["has_stop"]:
            n_nostop += 1
        elif p["stop_pnl"] < 0:
            n_loss += 1
            loss[p["side"]] += -p["stop_pnl"]
            worst_acct = max(worst_acct or 0.0, -p["stop_pnl"] / p["wallet"])
        else:
            n_locked += 1
    n_open = longs + shorts
    wsum = float(sum(wallets))
    wmean = wsum / len(wallets) if wallets else None
    big = max(longs, shorts)
    share = big / n_open if n_open else None
    total_loss = loss[1] + loss[-1]
    # a figure the snapshot cannot give (open positions, but none with a size / none with a stop) is None, never a zero that reads as "safe"
    m_known = not n_open or n_priced > 0
    s_known = not n_open or (n_loss + n_locked) > 0
    return {
        "open": n_open, "long": longs, "short": shorts,
        "same_side": None if not n_open or longs == shorts else (1 if longs > shorts else -1),
        "same_side_share": _r(share), "crowded": bool(n_open >= MIN_OPEN and share is not None and share >= SAME_SIDE - 1e-9),
        "coins": [{"coin": c, "long": v[0], "short": v[1]} for c, v in sorted(coins.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0]))],
        "cluster": _cluster(coins), "lev_mean": _r(sum(levs) / len(levs), 2) if levs else None, "lev_max": _r(max(levs), 2) if levs else None,
        "margin": {"n": n_priced, "missing": n_missing, "exact": False, "sum": _r(msum, 2) if m_known else None, "wallets": _r(wsum, 2), "wallet_mean": _r(wmean, 2),
                   "separate_pct": _r(_div(msum, wsum)) if m_known else None, "shared_pct": _r(_div(msum, wmean)) if m_known else None},
        "stop": {"n": n_loss, "locked": n_locked, "no_stop": n_nostop, "loss": _r(total_loss, 2) if s_known else None,
                 "long_loss": _r(loss[1], 2) if s_known else None, "short_loss": _r(loss[-1], 2) if s_known else None,
                 "separate_pct": _r(_div(total_loss, wsum)) if s_known else None, "shared_pct": _r(_div(total_loss, wmean)) if s_known else None,
                 "long_shared_pct": _r(_div(loss[1], wmean)) if s_known else None, "short_shared_pct": _r(_div(loss[-1], wmean)) if s_known else None,
                 "worst_acct_pct": _r(worst_acct) if s_known else None},
    }


# ---------------------------------------------------------------- (2) the worst that already happened
def _basket_dd(accts: list, eq0: float) -> Optional[float]:
    """Max drawdown of the equal-weight average wallet: B(t) = eq0 + (sum of every account's realised P&L up to t) / N, the accounts without a
    trade still count as N (a wallet that did not move)."""
    n = len(accts)
    parts = [a.cols for a in accts if len(a.cols["pnl"])]
    if not n or not parts:
        return None
    t = np.concatenate([c["t_out"] for c in parts])
    p = np.concatenate([c["pnl"] for c in parts])
    order = np.argsort(t, kind="stable")
    t, p = t[order], p[order]
    first = np.concatenate(([True], t[1:] != t[:-1]))                     # trades of the same instant are one step
    step = np.add.reduceat(p, np.flatnonzero(first))
    basket = eq0 + np.cumsum(step) / n
    peak = np.maximum.accumulate(np.maximum(basket, eq0))
    return float(min(1.0, max(0.0, np.max((peak - basket) / peak))))


def _median(xs: list) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def _worst(accts: list, eq0: float) -> dict:
    have = [a for a in accts if a.st["n"] > 0]
    n_trades = sum(a.st["n"] for a in have)
    out = {"trades": n_trades, "accounts": len(have), "trade": None,
           "streak": {"max": None, "median": None, "now_max": None, "account": None},
           "dd": {"basket": None, "accounts": len(accts), "acct_worst": None, "acct_worst_id": None},
           "liq_n": sum(a.cols["liq"] for a in accts), "bust": sum(bool(a.row.get("bust")) for a in accts),
           "sl_n": sum(a.cols["sl"] for a in accts), "lock_n": sum(a.cols["lock"] for a in accts), "stop_share": None}
    if not have:
        return out
    out["stop_share"] = _r(out["sl_n"] / n_trades)
    w = min(have, key=lambda a: (a.st["worst_pct"], str(a.id)))
    t = w.trades[w.st["worst_i"]]
    out["trade"] = {"pct": _r(w.st["worst_pct"]), "pnl": _r(_num(t.get("pnl")), 2), "coin": _coin(t.get("symbol")) or None, "side": _sgn(t.get("side")) or None,
                    "lev": _r(_num(t.get("leverage")), 2), "reason": t.get("exit_reason"), "exit_ms": None if _num(t.get("exit_time")) is None else int(t["exit_time"]),
                    "account": w.id, "pick": w.row.get("pick") or w.id}
    streaks = [a.st["streak"] for a in have]
    longest = max(streaks)
    out["streak"] = {"max": longest, "median": _r(_median(streaks), 1), "now_max": max(a.st["streak_now"] for a in have),
                     "account": min((a.id for a in have if a.st["streak"] == longest), key=str)}
    top = max(a.st["dd"] for a in have)
    out["dd"] = {"basket": _r(_basket_dd(accts, eq0)), "accounts": len(accts), "acct_worst": _r(top),
                 "acct_worst_id": min((a.id for a in have if a.st["dd"] == top), key=str)}
    return out


# ---------------------------------------------------------------- (3) the days the entries piled up on one side
def _day_counts(accts: list) -> Optional[tuple]:
    """(days, long entries, short entries) per UTC day of ENTRY over the accounts' closed trades; None without a dated entry."""
    ts, ss = [], []
    for a in accts:
        c = a.cols
        ok = (c["side"] != 0) & np.isfinite(c["t_in"])
        if ok.any():
            ts.append(c["t_in"][ok])
            ss.append(c["side"][ok])
    if not ts:
        return None
    t, s = np.concatenate(ts), np.concatenate(ss)
    day = np.floor(t / DAY_MS).astype(np.int64)
    days, inv = np.unique(day, return_inverse=True)
    inv = inv.reshape(-1)
    total = np.bincount(inv, minlength=len(days))
    long_n = np.bincount(inv, weights=(s > 0).astype(float), minlength=len(days)).round().astype(np.int64)
    return days, long_n, total - long_n


def _days(accts: list) -> dict:
    base = {"min_trades": MIN_DAY_TRADES, "threshold": SAME_SIDE, "total": 0, "eligible": 0, "crowded": 0, "share": None, "long": 0, "short": 0,
            "lopsided": None}
    c = _day_counts(accts)
    if c is None:
        return base
    days, lg, sh = c
    tot = lg + sh
    big = np.maximum(lg, sh)
    elig = tot >= MIN_DAY_TRADES
    crowd = elig & (big >= SAME_SIDE * tot - 1e-9)
    n_e, n_c = int(elig.sum()), int(crowd.sum())
    base.update(total=int(len(days)), eligible=n_e, crowded=n_c, share=_r(n_c / n_e) if n_e else None,
                long=int((crowd & (lg > sh)).sum()), short=int((crowd & (sh > lg)).sum()))
    if n_e:
        idx = np.flatnonzero(elig)
        share = big[idx] / tot[idx]
        order = np.lexsort((days[idx], tot[idx], share))                  # the largest share, then the most entries, then the later day
        i = int(idx[order[-1]])
        base["lopsided"] = {"day_ms": int(days[i]) * DAY_MS, "n": int(tot[i]), "share": _r(big[i] / tot[i]), "side": 1 if lg[i] >= sh[i] else -1}
    return base


# ---------------------------------------------------------------- the block
def risk_rules_ko() -> list:
    """The "what this is" box of the screen: "head: text" lines (the screen keeps the same text as its fallback; a test keeps them equal)."""
    t = _threshold_ko()
    return [
        "무엇을 보여 주나: 포지션이 한쪽 방향에 몰려 있는지, 지금까지 가장 나빴던 일이 얼마였는지를 숫자로만 보여 줍니다. 무엇을 하라는 말은 없습니다.",
        f"쏠림 표시: 열린 포지션이 {MIN_OPEN}개 이상이고 그중 {t} 이상이 같은 방향(롱 또는 숏)이면 표시합니다.",
        "한 지갑이면: 계좌는 모두 따로인 모의 지갑입니다. ‘한 지갑이면’은 같은 포지션들을 지갑 하나에 모두 담았다고 가정한 계산입니다.",
        "가장 나빴던 것: 닫힌 거래만으로 셉니다 (지갑 대비 한 거래 최악 · 연속으로 진 횟수 · 낙폭 · 강제청산). 열려 있는 거래의 평가손익은 들어 있지 않습니다.",
        f"같은 방향이 몰린 날: 그날 들어간 거래가 {MIN_DAY_TRADES}건 이상이고 {t} 이상이 같은 방향인 날의 비율입니다 (UTC 날짜 기준).",
        "모든 숫자 옆에 거래 수나 계좌 수를 같이 씁니다. 적으면 우연일 수 있습니다.",
    ]


def risk_notes_ko(eq0: float, ds_money: bool) -> list:
    out = [
        f"계좌는 모두 따로인 모의 지갑입니다 (각각 ${eq0:,.0f}에서 시작). 실제로 계좌 하나에 같은 포지션을 모두 담으면 증거금이 모자라 일부는 못 들어갑니다. "
        "‘한 지갑이면’ 숫자는 그 경우를 가정한 계산이고, 실제 공유 계좌는 다르게 움직일 수 있습니다.",
        "열린 포지션의 증거금 · 손절 손실은 저장된 값이 아니라 크기 규칙(배수 ÷ 100 × 잔고)으로 다시 계산한 추정입니다. 수수료 · 미끄러짐은 뺐고, 손절선이 없거나 이미 이익 쪽으로 올라간 포지션은 손실에 넣지 않았습니다.",
        "낙폭은 닫힌 거래로 만든 잔고로만 계산합니다. 열려 있는 포지션의 평가손익은 들어 있지 않아서, 실제 낙폭은 이보다 클 수 있습니다.",
        f"같은 방향이 몰린 날은 닫힌 거래만 셉니다. 아직 열려 있는 거래는 빠지고, 그날 들어간 거래가 {MIN_DAY_TRADES}건 미만인 날은 세지 않습니다.",
        "계좌 종류들은 같은 신호를 나눠 쓰므로 서로 독립이 아닙니다. ‘메인 전체’는 같은 신호가 여러 종류에서 반복된 합입니다.",
        "기록은 짧습니다. 가장 나빴던 일은 아직 오지 않았을 수 있고, 모의 기록은 앞으로를 약속하지 않습니다.",
    ]
    if not ds_money:
        out.append("딥시크 계좌는 금액 숨김 설정이라 모든 숫자에서 뺐습니다.")
    return out


def _headline(kinds: list) -> str:
    """One sentence of counts about the 실전 후보 (else the first kind shown). Never advice."""
    if not kinds:
        return "아직 보여 줄 계좌 종류가 없습니다"
    f = next((k for k in kinds if k["live"]), kinds[0])
    n, w = f["now"], f["worst"]
    if n["open"]:
        share = f" (한 방향 {_pct_ko(n['same_side_share'], 0)})" if n["same_side_share"] is not None else ""
        now = f"열린 포지션 {n['open']}개 중 롱 {n['long']}개 · 숏 {n['short']}개{share}"
    else:
        now = f"지금 열린 포지션이 없습니다 (계좌 {f['accounts']}개)"
    if w["trades"]:
        past = f"지금까지 한 거래 최악은 지갑의 {_pct_ko(w['trade']['pct'])}, 연속으로 진 최다는 {w['streak']['max']}번 (닫힌 거래 {w['trades']:,}건 기준)"
    else:
        past = "아직 닫힌 거래가 없습니다"
    return f"{f['name_ko']}: {now}, {past}."


def _kind_block(k: dict, accts: list, eq0: float, pooled: bool, coin_ref: Optional[dict]) -> dict:
    days = _days(accts)
    days["coin_ref"] = coin_ref
    return {"role": k["role"], "suffix": k.get("suffix"), "label_ko": k.get("label_ko"), "name_ko": k.get("name_ko") or _name(k),
            "short_ko": k.get("short_ko"), "group": _group(k.get("label_ko")), "live": k.get("suffix") == LIVE, "pooled": pooled,
            "accounts": len(accts), "trades": sum(a.st["n"] for a in accts), "now": _now(accts), "worst": _worst(accts, eq0), "days": days}


def risk_views(book: dict, rows: list, lineup: Optional[list], equity0: Optional[float] = None, ds_money: bool = False) -> dict:
    """The snapshot's ``risk`` block (see the module doc). ``book``: {account id: closed trades in exit order}; ``rows``: runner.account_rows (the
    wallet, the bust flag and the open position of every account); ``lineup``: rulex.lineup; ``equity0``: the start wallet (default
    exits.start_equity). The kinds shown: 실전 후보 (-fq), 대조 (-ld), then the next 메인 kinds of the lineup up to four, and 메인 전체 (all the
    lineup's 메인 kinds pooled) when there are two or more of them. A kind with no shown account is left out."""
    eq0 = _num(equity0)
    eq0 = X.start_equity() if eq0 is None or eq0 <= 0 else eq0
    lu = [k for k in lineup or [] if k.get("role") and k.get("suffix")]
    by_role: dict = {k["role"]: [] for k in lu}
    for r in sorted(rows or [], key=lambda r: str(r.get("id"))):
        if r.get("role") in by_role and _shown(r, ds_money):
            by_role[r["role"]].append(r)
    cache: dict = {}

    def accts_of(role: str) -> list:
        out = []
        for r in by_role.get(role, []):
            if r.get("id") not in cache:
                cache[r.get("id")] = _Acct(r, (book or {}).get(r.get("id")) or [], eq0)
            out.append(cache[r.get("id")])
        return out

    have = [k for k in lu if by_role[k["role"]]]
    main = [k for k in have if _group(k.get("label_ko")) == "main"]
    chosen: list = []
    for sfx in (LIVE, CONTROL):
        k = next((k for k in have if k["suffix"] == sfx), None)
        if k is not None:
            chosen.append(k)
    chosen += [k for k in main if k not in chosen][:max(0, MAX_KINDS - len(chosen))]
    kinds = []
    for k in chosen:
        twin = next((x for x in have if x["suffix"] == COIN_TWIN.get(k["suffix"])), None)
        ref = None
        if twin is not None:
            d = _days(accts_of(twin["role"]))
            ref = {"suffix": twin["suffix"], "name_ko": _name(twin), "eligible": d["eligible"], "crowded": d["crowded"], "share": d["share"]}
        kinds.append(_kind_block(k, accts_of(k["role"]), eq0, False, ref))
    if len(main) >= 2:
        pooled = [a for k in main for a in accts_of(k["role"])]
        kinds.append(_kind_block({"role": POOLED_ROLE, "suffix": None, "label_ko": "메인 · " + POOLED_KO, "name_ko": POOLED_KO, "short_ko": POOLED_KO},
                                 pooled, eq0, True, None))
    return {"equity0": _r(eq0, 2), "ds_in_stats": bool(ds_money),
            "thresholds": {"same_side": SAME_SIDE, "min_open": MIN_OPEN, "min_day_trades": MIN_DAY_TRADES},
            "headline_ko": _headline(kinds), "rules_ko": risk_rules_ko(), "note_ko": risk_notes_ko(eq0, ds_money), "kinds": kinds}
