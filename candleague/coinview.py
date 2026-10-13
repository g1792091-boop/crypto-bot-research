"""코인별 (league.json key ``coins``): in which coin does each kind earn or lose? The owner-exit league's picks trade six coins; this block counts the closed
trades per coin for the 실전 후보 (-fq), the 대조 (-ld) and their coin-flip twins (-fqc / -ldc), and sets each real kind beside its twin IN THE SAME COIN.

Pure function of the closed-trade book ({account id: trades in exit order}, runner.closed_trades), the account rows (runner.account_rows) and the lineup
(rulex.lineup); no clock, no randomness. Fractions, not percent (0.1 = 10%). Counts and means only: no confidence interval, no test, no advice. A coin
with fewer than ``MIN_N`` closed trades (either side of a difference) is flagged ``few`` ("적음": the mean may be luck).

The block, ``coin_views(...)``::

    {"equity0", "ds_in_stats", "min_n": 30, "headline_ko", "rules_ko": [...], "note_ko": [...], "coins": [coin, ...],
     "kinds": [kind, ...]}      # -fq, its twin -fqc, -ld, its twin -ldc (those the lineup has and that have an account)

    kind = {"role", "suffix", "label_ko", "name_ko", "live", "twin": {"suffix", "name_ko"} | None, "accounts", "skipped",
            "total": {"n", "pnl", "mean_roe"}, "rows": [row, ...]}          # one row per coin, in ``coins`` order
    row  = {"coin", "n", "wins", "win_rate", "mean_roe", "long", "short", "pnl", "share", "few",
            "twin": {"n", "mean_roe", "few"} | None, "diff", "diff_few"}

``mean_roe`` is the mean of the trades' ROE (the engine's net return on the margin, fees included); ``pnl`` the sum of the trades' P&L in dollars;
``share`` = the coin's pnl over the kind's total pnl, only when that total is above zero (else None); ``diff`` = mean_roe(kind) - mean_roe(twin) in
the same coin (means of all picks' trades pooled, NOT paired trade by trade: the paired, tested version is the 판정 screen's). A figure the data
cannot give is None, never a zero.

DeepSeek money (D11): without ``ds_money`` every DeepSeek account is left out of every figure (counts included)."""

from __future__ import annotations

from typing import Optional

from . import exits as X
from .riskview import COIN_TWIN, CONTROL, LIVE, _coin, _name, _num, _r, _shown

MIN_N = 30
KIND_ORDER = (LIVE, COIN_TWIN[LIVE], CONTROL, COIN_TWIN[CONTROL])
TWIN_OF = {v: k for k, v in COIN_TWIN.items()}


def coin_rules_ko() -> list:
    return [
        "무엇을 보여 주나: 코인마다 닫힌 거래의 수 · 이긴 비율 · 거래당 평균 수익률 · 롱과 숏 개수 · 손익 비중을 보여 주고, 같은 코인에서 동전 던지기 짝과의 평균 차이를 붙입니다.",
        f"거래가 {MIN_N}건 미만이면 ‘적음’으로 표시합니다. 적은 숫자는 우연일 수 있어 그 코인의 차이는 믿지 않는 편이 좋습니다.",
        "거래당 평균 수익률은 수수료를 뺀 값(ROE)의 평균입니다. 모든 후보의 거래를 한데 모아 셉니다.",
        "차이는 두 평균의 뺄셈일 뿐입니다 (거래를 하나씩 짝지은 판정이 아닙니다). 신뢰구간이나 통과 · 실패는 없고, 무엇을 하라는 말도 없습니다.",
    ]


def coin_notes_ko(eq0: float, ds_money: bool) -> list:
    out = [
        f"계좌마다 ${eq0:,.0f}에서 시작하는 모의 지갑입니다. 손익 비중은 그 종류의 손익 합계가 플러스일 때만 계산합니다.",
        "코인별로 나누면 거래가 얇아집니다. 한 코인의 몇십 건으로는 그 코인이 원래 잘 맞는다고 말할 수 없습니다.",
        "열려 있는 거래의 평가손익은 들어 있지 않습니다 (닫힌 거래만).",
        "같은 시기의 같은 신호가 여러 후보에 겹쳐 들어 있을 수 있어, 거래 수만큼 독립적인 증거는 아닙니다.",
    ]
    if not ds_money:
        out.append("딥시크 계좌는 금액이 숨김 설정이라 이 숫자에서 뺐습니다.")
    return out


def _empty_row(coin: str) -> dict:
    return {"coin": coin, "n": 0, "wins": 0, "roe_sum": 0.0, "long": 0, "short": 0, "pnl": 0.0}


def _tally(accts: list, book: dict) -> tuple:
    """({coin: counters}, skipped): the closed trades of the given accounts by coin."""
    by: dict = {}
    skipped = 0
    for a in accts:
        for t in book.get(a.get("id")) or []:
            pnl, roe = _num(t.get("pnl")), _num(t.get("roe"))
            coin = _coin(t.get("symbol"))
            if pnl is None or roe is None or not coin:
                skipped += 1
                continue
            c = by.setdefault(coin, _empty_row(coin))
            c["n"] += 1
            c["wins"] += pnl > 0
            c["roe_sum"] += roe
            c["pnl"] += pnl
            s = _num(t.get("side"))
            if s is not None and s > 0:
                c["long"] += 1
            elif s is not None and s < 0:
                c["short"] += 1
    return by, skipped


def _mean(c: Optional[dict]) -> Optional[float]:
    return c["roe_sum"] / c["n"] if c and c["n"] else None


def _headline(kinds: list) -> str:
    bits = []
    for k in kinds:
        if not k.get("twin"):
            continue
        ok = [r for r in k["rows"] if r["diff"] is not None and not r["diff_few"]]
        if not ok:
            bits.append(f"{k['name_ko']}: 동전 짝과 비교할 만큼 거래가 쌓인 코인이 아직 없습니다")
            continue
        up = sum(r["diff"] > 0 for r in ok)
        bits.append(f"{k['name_ko']}: 거래 {MIN_N}건 이상인 코인 {len(ok)}개 중 {up}개에서 거래당 평균이 동전 짝보다 높음")
    return "; ".join(bits)


def coin_views(book: dict, rows: list, lineup: Optional[list], equity0: Optional[float] = None, ds_money: bool = False) -> dict:
    """The snapshot's ``coins`` block (see the module doc)."""
    eq0 = _num(equity0)
    eq0 = X.start_equity() if eq0 is None or eq0 <= 0 else eq0
    lu = {k["suffix"]: k for k in lineup or [] if k.get("role") and k.get("suffix")}
    by_role: dict = {k["role"]: [] for k in lu.values()}
    for r in sorted(rows or [], key=lambda r: str(r.get("id"))):
        if r.get("role") in by_role and _shown(r, ds_money):
            by_role[r["role"]].append(r)
    tallies: dict = {}
    for sfx in KIND_ORDER:
        k = lu.get(sfx)
        if k is not None and by_role[k["role"]]:
            tallies[sfx] = _tally(by_role[k["role"]], book or {})
    coins: dict = {}
    for sfx in (LIVE, CONTROL):                       # the order of the coins: most closed trades of the two real kinds first
        for c, v in (tallies.get(sfx, ({}, 0))[0]).items():
            coins[c] = coins.get(c, 0) + v["n"]
    for sfx, (by, _s) in tallies.items():
        for c in by:
            coins.setdefault(c, 0)
    order = sorted(coins, key=lambda c: (-coins[c], c))
    kinds = []
    for sfx in KIND_ORDER:
        if sfx not in tallies:
            continue
        k, (by, skipped) = lu[sfx], tallies[sfx]
        twin_sfx = COIN_TWIN.get(sfx)
        twin_by = tallies[twin_sfx][0] if twin_sfx in tallies else None
        total_pnl = sum(v["pnl"] for v in by.values())
        total_n = sum(v["n"] for v in by.values())
        out_rows = []
        for c in order:
            v = by.get(c) or _empty_row(c)
            n = v["n"]
            m = _mean(v)
            tw = None
            diff, diff_few = None, False
            if twin_by is not None:
                tv = twin_by.get(c) or _empty_row(c)
                tm = _mean(tv)
                tw = {"n": tv["n"], "mean_roe": _r(tm), "few": tv["n"] < MIN_N}
                if m is not None and tm is not None:
                    diff, diff_few = _r(m - tm), n < MIN_N or tv["n"] < MIN_N
            out_rows.append({"coin": c, "n": n, "wins": v["wins"], "win_rate": _r(v["wins"] / n) if n else None, "mean_roe": _r(m),
                             "long": v["long"], "short": v["short"], "pnl": _r(v["pnl"], 2) if n else None,
                             "share": _r(v["pnl"] / total_pnl) if n and total_pnl > 0 else None, "few": n < MIN_N,
                             "twin": tw, "diff": diff, "diff_few": diff_few})
        tm_all = sum(v["roe_sum"] for v in by.values()) / total_n if total_n else None
        kinds.append({"role": k["role"], "suffix": sfx, "label_ko": k.get("label_ko"), "name_ko": _name(k), "live": sfx == LIVE,
                      "twin": ({"suffix": twin_sfx, "name_ko": _name(lu[twin_sfx])} if twin_by is not None else None),
                      "is_twin": sfx in TWIN_OF, "accounts": len(by_role[k["role"]]), "skipped": skipped,
                      "total": {"n": total_n, "pnl": _r(total_pnl, 2) if total_n else None, "mean_roe": _r(tm_all)}, "rows": out_rows})
    return {"equity0": _r(eq0, 2), "ds_in_stats": bool(ds_money), "min_n": MIN_N, "headline_ko": _headline(kinds), "rules_ko": coin_rules_ko(),
            "note_ko": coin_notes_ko(eq0, ds_money), "coins": order, "kinds": kinds}
