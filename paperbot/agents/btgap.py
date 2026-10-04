"""Backtest vs live gap (백테스트와 실전의 차이, owners' request 2026-10-04). Code only, read-only on paper3.db and on
the 5-year strategy cards (research/strategy_profiles/out_binance/cards.json, installed with the code tree by
deploy/install.sh; agents.packets3.CARDS). The staff read the numbers; nothing here trades or changes an account.

What the cards hold per strategy x timeframe (research/strategy_profiles/profiles.py ``summarise`` -> report.py):
``signals_per_day`` (2021-08-01 .. 2026-09-30, six coins), ``sized_share`` (signals the v3 sizing could open),
``win_rate`` (share of closed trades with ROE > 0), ``mean_roe`` and its t-value ``mean_roe_t`` (mean / (sd / sqrt n)),
``lock_share``, ``median_hold_hours`` and the one-account results. Every signal is taken on its own (no
one-position-at-a-time limit, $1,000 sizing equity), under the paper v3 rules (2 ATR stop, the v3 leverage tiers,
the stepped lock, real costs).

Units (the conversion): both sides are compared per closed trade in **net ROE on margin** (P&L after fees,
slippage and funding / the margin put up): the cards' ``mean_roe`` is leverage x (price move - round-trip cost -
funding) of each closed signal, and a live trade's ``roe`` is the engine's net P&L / initial margin (engine.py). Not in
equity terms: the cards keep no per-trade margin share. Win rate: share of trades with P&L > 0 on both sides.

Tests (per strategy x timeframe with >= ``MIN_LIVE`` live trades on its strategy account):
- win rate: exact two-sided binomial test of the live wins against the backtest win rate (the backtest's own
  sampling error is left out: its samples are 10-100x larger);
- mean ROE: z = (live mean - backtest mean) / sqrt(live sd^2 / n + backtest se^2), backtest se = |mean_roe /
  mean_roe_t| (when the card has a t-value), normal two-sided p;
- flag: 'worse' (실전이 백테스트보다 유의하게 나쁨) when a test has p < ``ALPHA`` with live below and none says live is
  significantly above; 'better' (유의하게 좋음) the other way round; 'similar' (비슷함) otherwise (also when the two tests
  point opposite ways: ``mixed``); 'too_few' under ``MIN_LIVE`` live trades, or a backtest row with under ``MIN_BT``
  (estimated: signals_per_day x days x sized_share) trades or a win rate of 0 or 1 (no reference); 'no_backtest'
  without a card row.
Per strategy (its four accounts pooled; 5m was removed on 2026-10-04 and the cards' 5m rows are left out): the same tests against the backtest numbers weighted by the live trades
per timeframe (expected win rate sum n_tf p_tf / n with a normal approximation, variance sum n_tf p_tf (1 - p_tf);
expected mean sum n_tf m_tf / n). The aggregate share of strategies significantly worse is a code fact: about
``ALPHA`` (one side of two tests) is what chance alone gives; at ``TRUST_WARN_SHARE`` or more the packet says the
5-year tests should not be trusted blindly. Trades of one month share the same market, so the p-values are
optimistic (descriptive, not a verdict: the 30-day verdict is paperbot/checkpoint.py).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from typing import Any, Iterable, Optional

from ..config import V3_TRADE_TFS

TFS = V3_TRADE_TFS                   # the run's timeframes (5m removed 2026-10-04, docs/paper-v3-rules-change-1.md)
MIN_LIVE = 20
MIN_BT = 30                      # a backtest row with fewer (estimated) trades is no reference: 'too_few'
ALPHA = 0.05
TRUST_WARN_SHARE = 0.25
FLAG_KO = {"worse": "실전이 백테스트보다 유의하게 나쁨", "similar": "비슷함", "better": "유의하게 좋음",
           "too_few": f"거래 부족(실전 {MIN_LIVE}건 미만)", "bt_few": f"거래 부족(백테스트 {MIN_BT}건 미만)",
           "no_backtest": "백테스트 자료 없음"}
UNITS_NOTE = ("단위: 거래 1건의 증거금 대비 순 ROE(수수료·슬리피지·펀딩 뺀 손익 ÷ 증거금). 5년 카드의 mean_roe도 같은 정의"
              "(research/strategy_profiles/profiles.py: 레버리지 × (가격 움직임 − 왕복 비용 − 펀딩), 끝난 거래만). 카드에는 "
              "거래마다의 증거금 비율이 없어 자금 대비로는 바꾸지 않음. 승률은 둘 다 손익 > 0인 거래 비율. 5년 시험은 신호를 "
              "모두 따로 잡았고(한 번에 한 포지션 제한 없음, $1,000 기준 크기) 실전 계좌는 한 번에 한 포지션이라 실전 거래는 그중 "
              "일부")


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and math.isfinite(v) else None


def _r(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


def resolve_cards(path: Optional[str] = None) -> str:
    """The cards file: ``path``, else agents.packets3.CARDS (the Binance futures cards, spot as fallback)."""
    if path:
        return path
    from .packets3 import CARDS
    return CARDS


def _days(meta: dict) -> Optional[float]:
    """Days the cards cover (meta.windows: is start .. cf end)."""
    import datetime as dt
    try:
        w = meta["windows"]
        a = dt.date.fromisoformat(w["is"][0])
        b = dt.date.fromisoformat(w["cf"][1])
        return float((b - a).days)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def load_cards(path: Optional[str] = None) -> dict:
    """{strategy: {tf: {win_rate, mean_roe, mean_se, trades_approx, ...}}} from the cards file ({} when missing)."""
    p = resolve_cards(path)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        doc = json.load(fh)
    days = _days(doc.get("meta") or {})
    out: dict = {}
    for c in doc.get("cards") or []:
        rows = {}
        for r in c.get("rows") or []:
            wr, m, t = _f(r.get("win_rate")), _f(r.get("mean_roe")), _f(r.get("mean_roe_t"))
            if wr is None or m is None:
                continue
            spd, sized = _f(r.get("signals_per_day")), _f(r.get("sized_share"))
            n = None if spd is None or days is None else spd * days * (sized if sized is not None else 1.0)
            rows[r["tf"]] = {"win_rate": wr, "mean_roe": m, "mean_roe_t": t,
                             "mean_se": abs(m / t) if t not in (None, 0.0) else None,
                             "trades_approx": None if n is None else int(round(n)),
                             "lock_share": _f(r.get("lock_share"))}
        out[c["strategy"]] = rows
    return out


# ---------------------------------------------------------------- tests
def bt_small(bt: dict) -> bool:
    """A backtest row with fewer than ``MIN_BT`` estimated trades (or a win rate of 0 or 1) is no reference."""
    n = bt.get("trades_approx")
    return (n is not None and n < MIN_BT) or bt["win_rate"] in (0.0, 1.0)


def binom_two_sided(k: int, n: int, p: float) -> float:
    """Exact two-sided binomial test p-value (the sum of the outcomes no more likely than k, as scipy's)."""
    if n <= 0:
        return 1.0
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    lg = math.lgamma
    logs = [lg(n + 1) - lg(i + 1) - lg(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p) for i in range(n + 1)]
    lk = logs[k] + 1e-7                       # relative tolerance 1 + 1e-7 as scipy (on the log scale)
    top = max(logs)
    tot = sum(math.exp(v - top) for v in logs if v <= lk + 1e-12)
    return min(1.0, tot * math.exp(top))


def norm_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def _mean_sd(xs: list[float]) -> tuple:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd


def flag_of(wr_p: Optional[float], wr_diff: Optional[float], m_p: Optional[float], m_diff: Optional[float],
            alpha: float = ALPHA) -> tuple:
    """('worse' | 'better' | 'similar', mixed?) from the two tests (p, live - backtest)."""
    worse = any(p is not None and d is not None and p < alpha and d < 0 for p, d in ((wr_p, wr_diff), (m_p, m_diff)))
    better = any(p is not None and d is not None and p < alpha and d > 0 for p, d in ((wr_p, wr_diff), (m_p, m_diff)))
    if worse and not better:
        return "worse", False
    if better and not worse:
        return "better", False
    return "similar", worse and better


def compare_cell(live: list[tuple], bt: Optional[dict], min_live: int = MIN_LIVE, alpha: float = ALPHA) -> dict:
    """live: [(win, roe)] of one strategy x timeframe account; bt: its card row (``load_cards``)."""
    n = len(live)
    out: dict = {"live_trades": n}
    if bt is None:
        return {**out, "flag": "no_backtest", "flag_ko": FLAG_KO["no_backtest"]}
    out.update(bt_win_rate=_r(bt["win_rate"]), bt_mean_roe=_r(bt["mean_roe"]), bt_trades_approx=bt.get("trades_approx"))
    if n < min_live:
        return {**out, "flag": "too_few", "flag_ko": FLAG_KO["too_few"]}
    if bt_small(bt):
        return {**out, "flag": "too_few", "flag_ko": FLAG_KO["bt_few"]}
    wins = sum(1 for w, _r_ in live if w)
    wr = wins / n
    m, sd = _mean_sd([x for _w, x in live])
    p_wr = binom_two_sided(wins, n, bt["win_rate"])
    se = math.sqrt(sd ** 2 / n + (bt.get("mean_se") or 0.0) ** 2)
    z = (m - bt["mean_roe"]) / se if se > 0 else 0.0
    p_m = norm_two_sided(z) if se > 0 else 1.0
    flag, mixed = flag_of(p_wr, wr - bt["win_rate"], p_m, m - bt["mean_roe"], alpha)
    out.update(live_win_rate=_r(wr), win_rate_diff_pp=round((wr - bt["win_rate"]) * 100, 1), win_rate_p=_r(p_wr),
               live_mean_roe=_r(m), live_sd_roe=_r(sd), mean_roe_diff=_r(m - bt["mean_roe"]), z=_r(z, 2),
               mean_roe_p=_r(p_m), flag=flag, flag_ko=FLAG_KO[flag])
    if mixed:
        out["mixed"] = True
    return out


def compare_strategy(cells: dict, bt_rows: dict, min_live: int = MIN_LIVE, alpha: float = ALPHA) -> dict:
    """A strategy's four accounts pooled against the backtest weighted by the live trades per timeframe.
    cells: {tf: [(win, roe)]}."""
    used = {tf: v for tf, v in cells.items() if v and tf in bt_rows and not bt_small(bt_rows[tf])}
    n = sum(len(v) for v in used.values())
    out: dict = {"live_trades": n, "timeframes": sorted(used, key=lambda tf: TFS.index(tf) if tf in TFS else 9)}
    if not bt_rows:
        return {**out, "flag": "no_backtest", "flag_ko": FLAG_KO["no_backtest"]}
    if n < min_live:
        return {**out, "flag": "too_few", "flag_ko": FLAG_KO["too_few"]}
    wins = sum(1 for v in used.values() for w, _x in v if w)
    exp_w = sum(len(v) * bt_rows[tf]["win_rate"] for tf, v in used.items())
    var_w = sum(len(v) * bt_rows[tf]["win_rate"] * (1 - bt_rows[tf]["win_rate"]) for tf, v in used.items())
    exp_m = sum(len(v) * bt_rows[tf]["mean_roe"] for tf, v in used.items()) / n
    se_bt2 = sum((len(v) / n) ** 2 * (bt_rows[tf].get("mean_se") or 0.0) ** 2 for tf, v in used.items())
    m, sd = _mean_sd([x for v in used.values() for _w, x in v])
    if var_w > 0:
        zc = (abs(wins - exp_w) - 0.5) / math.sqrt(var_w)      # continuity correction
        p_wr = 1.0 if zc <= 0 else norm_two_sided(zc)
    else:
        p_wr = 1.0
    se = math.sqrt(sd ** 2 / n + se_bt2)
    z = (m - exp_m) / se if se > 0 else 0.0
    p_m = norm_two_sided(z) if se > 0 else 1.0
    flag, mixed = flag_of(p_wr, wins - exp_w, p_m, m - exp_m, alpha)
    out.update(live_win_rate=_r(wins / n), bt_win_rate=_r(exp_w / n),
               win_rate_diff_pp=round((wins - exp_w) / n * 100, 1), win_rate_p=_r(p_wr), live_mean_roe=_r(m), bt_mean_roe=_r(exp_m), mean_roe_diff=_r(m - exp_m),
               z=_r(z, 2), mean_roe_p=_r(p_m), flag=flag, flag_ko=FLAG_KO[flag])
    if mixed:
        out["mixed"] = True
    return out


# ---------------------------------------------------------------- reading paper3.db
def live_trades(paper_ro: sqlite3.Connection, until_ms: int, strategies: Optional[Iterable[str]] = None) -> dict:
    """{strategy: {tf: [(win, roe)]}} of the closed trades of the strategy accounts (kind 'strategy') before
    ``until_ms``. Read-only."""
    sql = ("SELECT a.strategy, a.timeframe, t.pnl, t.roe FROM trades t JOIN accounts a ON a.account_id = t.account_id "
           "WHERE a.kind = 'strategy' AND t.exit_time < ?")
    args: list = [int(until_ms)]
    ss = list(strategies or [])
    if ss:
        sql += f" AND a.strategy IN ({','.join('?' * len(ss))})"
        args += ss
    out: dict = {}
    for s, tf, pnl, roe in paper_ro.execute(sql + " ORDER BY t.exit_time, t.id", args):
        if pnl is None or roe is None:
            continue
        out.setdefault(s, {}).setdefault(tf, []).append((float(pnl) > 0, float(roe)))
    return out


def gap_table(paper_ro: sqlite3.Connection, now_ms: int, cards: Optional[dict] = None,
              cards_path_: Optional[str] = None, strategies: Optional[Iterable[str]] = None,
              min_live: int = MIN_LIVE, alpha: float = ALPHA) -> dict:
    """{"strategies": {s: {"total": compare_strategy, "by_tf": {tf: compare_cell}}}, "summary": {...}}."""
    cards = load_cards(cards_path_) if cards is None else cards
    ss = list(strategies) if strategies is not None else None
    live = live_trades(paper_ro, now_ms, ss)
    if ss is None:
        ss = sorted(r[0] for r in paper_ro.execute("SELECT DISTINCT strategy FROM accounts WHERE kind = 'strategy'"))
    out: dict = {}
    for s in ss:
        bt = cards.get(s) or {}
        cells = live.get(s) or {}
        # the cards' 5m rows are history: 5m is not traded in this run (docs/paper-v3-rules-change-1.md)
        tfs = sorted(set(cells) | (set(bt) & set(TFS)), key=lambda tf: TFS.index(tf) if tf in TFS else 9)
        out[s] = {"total": compare_strategy(cells, bt, min_live, alpha),
                  "by_tf": {tf: compare_cell(cells.get(tf, []), bt.get(tf), min_live, alpha) for tf in tfs}}
    return {"strategies": out, "summary": summarise(out, alpha), "cards_found": bool(cards)}


def summarise(per: dict, alpha: float = ALPHA) -> dict:
    """Counts of the flags per strategy (pooled) and per strategy x timeframe, the share significantly worse, and the
    code's plain statement about trusting the 5-year tests."""
    def count(flags: list[str]) -> dict:
        tested = [f for f in flags if f in ("worse", "similar", "better")]
        c = {k: sum(1 for f in flags if f == k) for k in ("worse", "similar", "better", "too_few", "no_backtest")}
        c["tested"] = len(tested)
        c["worse_share"] = _r(c["worse"] / len(tested), 3) if tested else None
        return c
    st = count([v["total"]["flag"] for v in per.values()])
    cl = count([c["flag"] for v in per.values() for c in v["by_tf"].values()])
    out = {"strategies_tested": st["tested"], "strategies_worse": st["worse"], "strategies_similar": st["similar"],
           "strategies_better": st["better"], "strategies_too_few": st["too_few"] + st["no_backtest"],
           "strategies_worse_share": st["worse_share"], "cells": cl, "alpha": alpha,
           "chance_share": alpha, "trust_warn_share": TRUST_WARN_SHARE}
    sh = st["worse_share"]
    if sh is None:
        out["trust_warning"] = None
        out["statement_ko"] = f"아직 비교할 수 없음: 실전 거래 {MIN_LIVE}건 이상인 매매법이 없음"
    elif sh >= TRUST_WARN_SHARE:
        out["trust_warning"] = True
        out["statement_ko"] = (f"코드 사실: 비교한 매매법 {st['tested']}개 중 {st['worse']}개({sh * 100:.0f}%)가 실전이 5년 "
                               f"백테스트보다 유의하게 나쁨(우연이면 약 {alpha * 100:.0f}%). 5년 시험 결과를 그대로 믿으면 안 됨"
                               "(시험 통과도 실전에서 같은 차이로 나빠질 수 있음)")
    else:
        out["trust_warning"] = False
        out["statement_ko"] = (f"코드 사실: 비교한 매매법 {st['tested']}개 중 {st['worse']}개({sh * 100:.0f}%)가 실전이 5년 "
                               f"백테스트보다 유의하게 나쁨(우연이면 약 {alpha * 100:.0f}%, 경고선 "
                               f"{TRUST_WARN_SHARE * 100:.0f}%)")
    return out


SHORT_KEYS = ("live_trades", "live_win_rate", "bt_win_rate", "win_rate_diff_pp", "win_rate_p", "live_mean_roe",
              "bt_mean_roe", "mean_roe_diff", "mean_roe_p", "flag", "mixed")
TINY_KEYS = ("live_trades", "win_rate_diff_pp", "win_rate_p", "mean_roe_diff", "mean_roe_p", "flag", "mixed")


def _short(c: dict, keys: tuple = SHORT_KEYS) -> dict:
    return {k: c[k] for k in keys if k in c}


HOW_TO_READ = (f"실전(이 매매법 계좌의 끝난 거래) 대 5년 백테스트 카드. win_rate_p = 승률 이항검정 p(양쪽), mean_roe_p = 거래당 "
               f"평균 ROE 차이의 z 검정 p(실전 표준편차와 카드의 표준오차 사용). flag: worse = p < {ALPHA}이고 실전이 낮음, "
               f"better = p < {ALPHA}이고 실전이 높음, similar = 그 밖(mixed = 두 검정이 반대 방향), too_few = 실전 "
               f"{MIN_LIVE}건 미만 또는 백테스트 {MIN_BT}건 미만. 매매법 전체(total)는 4개 봉을 합쳐 봉별 실전 거래 수로 가중한 백테스트 숫자와 비교. 한 달 "
               "거래는 같은 시장을 겪어 서로 닮았으므로 p는 실제보다 작게 나올 수 있음(설명용, 판정 아님). " + UNITS_NOTE)


def packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, cards_path: Optional[str] = None,
           names_ko: Optional[dict] = None) -> dict:
    """The meeting packet's backtest gap: the summary (with the code's statement), the strategies flagged worse or
    better (pooled, and their flagged timeframes), the per-strategy flags in short."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    cards = load_cards(cards_path)
    if not cards:
        return {"error": "5년 카드 파일(cards.json)을 찾지 못함", "summary": summarise({})}
    tab = gap_table(paper_ro, now_ms, cards=cards)
    names = names_ko or {}
    flagged, flags = [], {}
    for s, v in tab["strategies"].items():
        flags[s] = {"total": v["total"]["flag"],
                    "by_tf": {tf: c["flag"] for tf, c in v["by_tf"].items()
                              if c["flag"] not in ("too_few", "no_backtest")}}
        sig = ("worse", "better")
        if v["total"]["flag"] in sig or any(c["flag"] in sig for c in v["by_tf"].values()):
            flagged.append({"strategy": s, "name_ko": names.get(s, s), "total": _short(v["total"]),
                            "by_tf": {tf: _short(c, TINY_KEYS) for tf, c in v["by_tf"].items()
                                      if c["flag"] in ("worse", "better")}})
    flagged.sort(key=lambda r: (r["total"].get("flag") != "worse", r["total"].get("mean_roe_diff") or 0.0))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = os.path.abspath(resolve_cards(cards_path))
    return {"summary": tab["summary"], "flagged": flagged, "flags": flags, "min_live": MIN_LIVE,
            "how_to_read": HOW_TO_READ,
            "cards": os.path.relpath(src, root) if src.startswith(root + os.sep) else os.path.basename(src)}


def summary_brief(paper_ro: Optional[sqlite3.Connection], now_ms: int, cards_path: Optional[str] = None) -> dict:
    """The Saturday learning packet's short form: the counts, the code's statement and the strategies worse."""
    pk = packet(paper_ro, now_ms, cards_path)
    if "error" in pk:
        return pk
    return {"summary": pk["summary"],
            "worse": [r["strategy"] for r in pk["flagged"] if r["total"].get("flag") == "worse"],
            "better": [r["strategy"] for r in pk["flagged"] if r["total"].get("flag") == "better"],
            "note": "실전 대 5년 백테스트(코드 계산, 설명용): 매매법별 승률·거래당 ROE 검정. 자세한 숫자는 금요일 낙폭·파산 위험 회의"}


def strategy_flags(paper_ro: Optional[sqlite3.Connection], strategy: str, now_ms: int,
                   cards_path: Optional[str] = None) -> dict:
    """A strategy specialist's own backtest gap: pooled and per timeframe, in short."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    cards = load_cards(cards_path)
    if not cards:
        return {"error": "5년 카드 파일(cards.json)을 찾지 못함"}
    v = gap_table(paper_ro, now_ms, cards=cards, strategies=[strategy])["strategies"][strategy]
    return {"total": _short(v["total"]), "by_tf": {tf: _short(c) for tf, c in v["by_tf"].items()},
            "note": ("실전 대 5년 백테스트(코드 계산): worse = 실전이 유의하게 나쁨(p < 0.05), similar = 비슷함, better = "
                     f"유의하게 좋음, too_few = 실전 {MIN_LIVE}건 미만(또는 백테스트 {MIN_BT}건 미만). 단위는 거래당 증거금 대비 순 ROE. 설명용")}
