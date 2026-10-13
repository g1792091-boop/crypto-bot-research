"""손실 해부 (league.json key ``losses``): what kind of loss was it, where and when did the losses pile up, which were the biggest?

The rule bot's loss cards come from AI meetings and cannot be copied. This is the league's own deterministic version: it takes the CLOSED trades
of every account kind (rulex.lineup role), keeps the ones with roe < 0 (a loss), and describes them. It only COUNTS and describes; it never
advises and never tests anything (no pass / fail). Pure functions of the closed-trade book ({account id: trades in exit order},
runner.closed_trades), the account rows (runner.account_rows) and the lineup: no clock, no randomness, one pass over the trades the runner
already loaded (no extra DB scan). Fractions, not percent (0.1 = 10%).

The block, ``loss_views(...)``::

    {"min_losses", "ds_in_stats", "headline_ko", "types": [{id, ko, explain_ko}], "note_ko": [...], "kinds": [kind, ...]}
    kind = {"role", "suffix", "label_ko", "name_ko", "short_ko", "group", "live", "pooled", "accounts", "n", "small",
            "trades", "losses", "loss_share", "mean_loss_roe", "worst_loss_roe", "loss_money",
            "types": [{id, n, share, mean_roe}],               # every type, in the rule order, also with n = 0
            "by_coin" (the 12 busiest) / "by_side" / "by_lev" / "by_hour" / "by_week": [{key, label_ko, n, share, mean_roe}],
            "streak": {max, account}, "cluster": {signals, multi, biggest, multi_share},
            "worst": [the 10 biggest losses: {account, pick, name, tf, symbol, side, entry_time, exit_time, roe, type_id, exit_reason,
                      leverage, at}]}

LOSS TYPE: one per loss, FIRST MATCH WINS (the order below is the order of ``LOSS_TYPES`` and of the checks in ``classify``). R = |entry - initial
stop|; best = max(0, side x (best price - entry) / R) (how far in profit it was, in R); worst = max(0, side x (entry - worst price) / R);
end = side x (exit - entry) / R; hold = hours between entry and exit.
    1 강제청산            exit_reason is LIQ
    2 벌었다가 놓침        best >= 1R
    3 조금 벌었다가 놓침    0.3R <= best < 1R
    4 규칙 청산으로 잃음    exit_reason is RULE (the structure / switching / strategy judgement closed it)
    5 손절보다 크게 잃음    end < -1.15R (slippage or a gap)
    6 오래 끌다 잃음       hold > 12 hours
    7 처음부터 불리하게 감   anything else (the stop was hit more or less straight away)
    - 분류 못 함          a price, the stop or a time is missing (after the LIQ check, which needs none of them)
A loss with a missing roe is not a loss here (it is not classified at all). Fewer than ``MIN_LOSSES`` (30) losses is ``small``: shown with a
warning, never as a verdict. The same-signal control comparison (a 메인 loss against what 대조 did on the same signal) is NOT here: the
snapshot's ``pairs`` only carries aggregates and the newest pairs, so it cannot be had per loss without a second pass; nothing is invented.

DeepSeek money (D11): the same rule as riskview / summary.decision_views: without ``ds_money`` every DeepSeek account is left out of every
figure (counts included), so money in this block never belongs to a hidden account."""

from __future__ import annotations

import heapq
from typing import Optional

from . import riskview as RV

MIN_LOSSES = 30                       # fewer losses than this: ``small`` (a warning, never a verdict)
TOP = 10                              # the biggest losses listed per kind
COINS_SHOWN = 12                      # coins listed in the by-coin table (the busiest by losses)
HOLD_LONG_H = 12.0                    # "오래 끌다 잃음": held longer than this many hours
GAP_R = -1.15                         # "손절보다 크게 잃음": ended worse than this many R
BEST_BIG, BEST_SMALL = 1.0, 0.3       # "벌었다가 놓침" / "조금 벌었다가 놓침": best excursion in R
KST_MS = 9 * 3_600_000
HOUR_MS, DAY_MS = 3_600_000, 86_400_000
POOLED_ROLE = "all"
POOLED_KO = "모든 종류 합계"

# (id, plain name, plain explanation); the order IS the order of the rules (first match wins)
LOSS_TYPES = (
    ("liq", "강제청산", "증거금이 모자라 거래소가 강제로 닫은 거래입니다."),
    ("gave_back", "벌었다가 놓침", "한때 손절폭(R)의 1배 이상 이익이었는데 되돌아와서 결국 손실로 끝났습니다."),
    ("gave_back_small", "조금 벌었다가 놓침", "한때 손절폭의 0.3배 ~ 1배 이익이었다가 되돌아와서 손실로 끝났습니다."),
    ("rule_exit", "규칙 청산으로 잃음", "손절선에 닿기 전에 구조 · 스위칭 · 매매법 판단으로 나갔는데 손실이었습니다."),
    ("gap", "손절보다 크게 잃음", "손절폭보다 1.15배 넘게 잃었습니다. 미끄러짐이나 가격 갭 때문입니다."),
    ("slow", "오래 끌다 잃음", "12시간을 넘게 들고 있다가 손실로 끝났습니다."),
    ("direct", "처음부터 불리하게 감", "들어가자마자 반대로 가서 손절선에 닿았습니다 (손절 직행)."),
    ("unknown", "분류 못 함", "가격이나 손절선, 시간 기록이 빠져 있어 유형을 나누지 못했습니다."),
)
TYPE_IDS = tuple(t[0] for t in LOSS_TYPES)
TYPE_KO = {t[0]: t[1] for t in LOSS_TYPES}

HOUR_BANDS = ((0, 6), (6, 12), (12, 18), (18, 24))
SIDE_KO = {1: "롱", -1: "숏"}
WEEK_KO = {"weekday": "평일", "weekend": "주말"}

_num, _r = RV._num, RV._r


def classify(t: dict) -> str:
    """The loss type id of ONE losing trade (see the module doc for the order; first match wins)."""
    why = t.get("exit_reason")
    if why == "LIQ":
        return "liq"
    side = RV._sgn(t.get("side"))
    en, ex = _num(t.get("entry_price")), _num(t.get("exit_price"))
    stop = _num(t.get("stop_initial"))
    mfe = _num(t.get("mfe_price"))
    t_in, t_out = _num(t.get("entry_time")), _num(t.get("exit_time"))
    if not side or en is None or ex is None or stop is None or mfe is None or t_in is None or t_out is None:
        return "unknown"
    r = abs(en - stop)
    if not r > 0:
        return "unknown"
    best = max(0.0, side * (mfe - en) / r)
    end = side * (ex - en) / r
    if best >= BEST_BIG:
        return "gave_back"
    if best >= BEST_SMALL:
        return "gave_back_small"
    if why == "RULE":
        return "rule_exit"
    if end < GAP_R:
        return "gap"
    if (t_out - t_in) / HOUR_MS > HOLD_LONG_H:
        return "slow"
    return "direct"


class _Cell:
    __slots__ = ("n", "s")

    def __init__(self) -> None:
        self.n, self.s = 0, 0.0

    def add(self, roe: float) -> None:
        self.n += 1
        self.s += roe

    def merge(self, o: "_Cell") -> None:
        self.n += o.n
        self.s += o.s


class _Acc:
    """The running numbers of one group of accounts (a kind, or all kinds); mergeable, so the pooled group costs no second pass."""

    __slots__ = ("trades", "losses", "sum_roe", "worst_roe", "money", "types", "dims", "streak", "streak_acct", "sig", "cands")

    def __init__(self) -> None:
        self.trades = self.losses = 0
        self.sum_roe = 0.0
        self.worst_roe: Optional[float] = None
        self.money = 0.0
        self.types = {i: _Cell() for i in TYPE_IDS}
        self.dims = {d: {} for d in ("coin", "side", "lev", "hour", "week")}
        self.streak, self.streak_acct = 0, None
        self.sig: dict = {}                       # (symbol, side, entry_time) -> accounts that lost on it
        self.cands: list = []                     # (roe, -exit_time, account id, trade) of the losses, trimmed to the TOP biggest

    def cell(self, dim: str, key) -> _Cell:
        d = self.dims[dim]
        c = d.get(key)
        if c is None:
            c = d[key] = _Cell()
        return c

    def trim(self) -> None:
        if len(self.cands) > 4 * TOP:
            self.cands = heapq.nsmallest(TOP, self.cands, key=lambda c: c[:3])


def _band(t_in: Optional[float]) -> tuple:
    """(hour band key, weekday / weekend key) of an entry time in KST; (None, None) without one."""
    if t_in is None:
        return None, None
    k = int(t_in + KST_MS)
    hour = (k // HOUR_MS) % 24
    day = (k // DAY_MS + 3) % 7                   # 1970-01-01 was a Thursday: Monday = 0
    return next(f"{a}-{b}" for a, b in HOUR_BANDS if a <= hour < b), "weekend" if day >= 5 else "weekday"


def _add_account(acc: _Acc, aid, trades: list) -> None:
    run = 0
    best_run = 0
    for t in trades:
        acc.trades += 1
        roe = _num(t.get("roe"))
        if roe is None or not roe < 0:
            run = 0
            continue
        run += 1
        best_run = max(best_run, run)
        acc.losses += 1
        acc.sum_roe += roe
        acc.worst_roe = roe if acc.worst_roe is None else min(acc.worst_roe, roe)
        pnl = _num(t.get("pnl"))
        if pnl is not None:
            acc.money += pnl
        tid = classify(t)
        acc.types[tid].add(roe)
        side = RV._sgn(t.get("side"))
        t_in = _num(t.get("entry_time"))
        coin = RV._coin(t.get("symbol"))
        lev = _num(t.get("leverage"))
        hb, wk = _band(t_in)
        for dim, key in (("coin", coin or None), ("side", side or None), ("lev", None if lev is None else int(round(lev))), ("hour", hb), ("week", wk)):
            if key is not None:
                acc.cell(dim, key).add(roe)
        if t_in is not None and side and coin:
            acc.sig.setdefault((coin, side, int(t_in)), set()).add(aid)
        ex = _num(t.get("exit_time"))
        acc.cands.append((roe, -(ex if ex is not None else 0.0), str(aid), t))
        acc.trim()
    if best_run > acc.streak or (best_run == acc.streak and best_run and str(aid) < str(acc.streak_acct)):
        acc.streak, acc.streak_acct = best_run, aid


def _cluster(sig_groups: list) -> dict:
    """{"signals", "multi", "biggest", "multi_share"} from per-kind signal dicts: a signal = the same coin + side + entry time; ``multi`` = the
    ones several accounts of the same kind lost on at once. (Kinds are never mixed: the same pick in two kinds is not a crowd.)"""
    signals = multi = biggest = multi_losses = losses = 0
    for sig in sig_groups:
        for accts in sig.values():
            n = len(accts)
            signals += 1
            losses += n
            biggest = max(biggest, n)
            if n >= 2:
                multi += 1
                multi_losses += n
    return {"signals": signals, "multi": multi, "biggest": biggest or None, "multi_share": _r(multi_losses / losses) if losses else None}


def _rows_out(cells: dict, total: int, label, order=None, limit: Optional[int] = None) -> list:
    keys = list(cells) if order is None else [k for k in order if k in cells]
    if order is None:
        keys.sort(key=lambda k: (-cells[k].n, str(k)))
    if limit:
        keys = keys[:limit]
    return [{"key": k, "label_ko": label(k), "n": cells[k].n, "share": _r(cells[k].n / total) if total else None,
             "mean_roe": _r(cells[k].s / cells[k].n) if cells[k].n else None} for k in keys]


def _worst_out(cands: list, info: dict) -> list:
    out = []
    for roe, _x, aid, t in heapq.nsmallest(TOP, cands, key=lambda c: c[:3]):
        row = info.get(aid) or {}
        out.append({"account": aid, "pick": row.get("pick") or aid, "name": row.get("name"), "tf": row.get("tf"), "symbol": t.get("symbol"),
                    "side": RV._sgn(t.get("side")) or None, "entry_time": _int(t.get("entry_time")), "exit_time": _int(t.get("exit_time")),
                    "roe": _r(roe), "type_id": classify(t), "exit_reason": t.get("exit_reason"), "leverage": _r(_num(t.get("leverage")), 2),
                    "at": _int(t.get("entry_time"))})
    return out


def _int(x) -> Optional[int]:
    v = _num(x)
    return None if v is None else int(v)


def loss_types_ko() -> list:
    return [{"id": i, "ko": ko, "explain_ko": why} for i, ko, why in LOSS_TYPES]


def loss_notes_ko(ds_money: bool) -> list:
    out = [
        "진 거래는 닫힌 거래 중 수익률(ROE)이 0보다 작은 것입니다. 열려 있는 거래의 평가손익은 들어 있지 않습니다.",
        "유형은 거래 기록(손절선 · 가장 유리했던 가격 · 청산 이유)만으로 정한 설명용 이름입니다. 위에서부터 먼저 맞는 하나만 붙입니다. 원인을 증명하지는 않습니다.",
        f"진 거래가 {MIN_LOSSES}건 미만이면 ‘표본 적음’입니다. 우연일 수 있어서 어떤 결론도 내지 않습니다.",
        "‘같은 신호’는 코인 · 방향 · 들어간 시각이 같은 것입니다. 같은 종류의 계좌 여러 개가 한꺼번에 진 것을 세며, 종류가 다른 계좌끼리는 섞지 않습니다.",
        "시간대와 요일은 한국 시간(KST)으로 들어간 때를 기준으로 합니다. 배수는 거래에 기록된 값 그대로입니다.",
        "메인 계좌와 대조 계좌가 같은 신호에서 어떻게 달랐는지는 ‘짝 비교’ 화면에서 봅니다 (이 화면은 거래마다 짝을 짓지 않습니다).",
        "기록은 짧고 모의 거래입니다. 앞으로를 약속하지 않으며, 어떤 행동도 권하지 않습니다.",
    ]
    if not ds_money:
        out.append("딥시크 계좌는 금액 숨김 설정이라 모든 숫자에서 뺐습니다.")
    return out


def _headline(kinds: list) -> str:
    if not kinds:
        return "아직 보여 줄 계좌 종류가 없습니다"
    k = next((x for x in kinds if x["live"]), kinds[0])
    if not k["losses"]:
        return f"{k['name_ko']}: 아직 진 거래가 없습니다 (닫힌 거래 {k['trades']:,}건)."
    top = max((t for t in k["types"] if t["n"]), key=lambda t: (t["n"], -TYPE_IDS.index(t["id"])))
    small = " 표본 적음, 참고만 하세요." if k["small"] else ""
    return (f"{k['name_ko']}: 닫힌 거래 {k['trades']:,}건 중 {k['losses']:,}건이 손실 ({RV._pct_ko(k['loss_share'], 0)}). "
            f"가장 많은 유형은 ‘{TYPE_KO[top['id']]}’ {top['n']:,}건 ({RV._pct_ko(top['share'], 0)}).{small}")


def _kind_block(k: dict, acc: _Acc, accounts: int, pooled: bool, sig_groups: list, info: dict) -> dict:
    n = acc.losses
    return {
        "role": k["role"], "suffix": k.get("suffix"), "label_ko": k.get("label_ko"), "name_ko": k.get("name_ko") or RV._name(k),
        "short_ko": k.get("short_ko"), "group": RV._group(k.get("label_ko")), "live": k.get("suffix") == RV.LIVE, "pooled": pooled,
        "accounts": accounts, "n": n, "small": n < MIN_LOSSES, "trades": acc.trades, "losses": n,
        "loss_share": _r(n / acc.trades) if acc.trades else None, "mean_loss_roe": _r(acc.sum_roe / n) if n else None,
        "worst_loss_roe": _r(acc.worst_roe), "loss_money": _r(acc.money, 2) if n else None,
        "types": [{"id": i, "n": acc.types[i].n, "share": _r(acc.types[i].n / n) if n else None,
                   "mean_roe": _r(acc.types[i].s / acc.types[i].n) if acc.types[i].n else None} for i in TYPE_IDS],
        "by_coin": _rows_out(acc.dims["coin"], n, lambda c: c, limit=COINS_SHOWN),
        "by_side": _rows_out(acc.dims["side"], n, lambda s: SIDE_KO[s], order=(1, -1)),
        "by_lev": _rows_out(acc.dims["lev"], n, lambda v: f"{v}배", order=sorted(acc.dims["lev"])),
        "by_hour": _rows_out(acc.dims["hour"], n, lambda b: "{}~{}시".format(*b.split("-")), order=[f"{a}-{b}" for a, b in HOUR_BANDS]),
        "by_week": _rows_out(acc.dims["week"], n, lambda w: WEEK_KO[w], order=("weekday", "weekend")),
        "streak": {"max": acc.streak or None, "account": acc.streak_acct if acc.streak else None},
        "cluster": _cluster(sig_groups), "worst": _worst_out(acc.cands, info)}


def loss_views(book: dict, rows: list, lineup: Optional[list], ds_money: bool = False) -> dict:
    """The snapshot's ``losses`` block (see the module doc). ``book``: {account id: closed trades in exit order}; ``rows``: runner.account_rows;
    ``lineup``: rulex.lineup. Every lineup kind with a shown account gets a group, in the lineup's order, then "모든 종류 합계" when there are two
    or more. DeepSeek accounts are left out of every figure unless ``ds_money``."""
    lu = [k for k in lineup or [] if k.get("role") and k.get("suffix")]
    by_role: dict = {k["role"]: [] for k in lu}
    info: dict = {}
    for r in sorted(rows or [], key=lambda r: str(r.get("id"))):
        if r.get("role") in by_role and RV._shown(r, ds_money):
            by_role[r["role"]].append(r)
            info[str(r.get("id"))] = r
    kinds: list = []
    pool, pool_sig, pool_accts = _Acc(), [], 0
    for k in lu:
        rs = by_role[k["role"]]
        if not rs:
            continue
        acc = _Acc()
        for r in rs:
            _add_account(acc, r.get("id"), (book or {}).get(r.get("id")) or [])
        kinds.append(_kind_block(k, acc, len(rs), False, [acc.sig], info))
        pool_accts += len(rs)
        pool_sig.append(acc.sig)
        pool.trades += acc.trades
        pool.losses += acc.losses
        pool.sum_roe += acc.sum_roe
        pool.money += acc.money
        if acc.worst_roe is not None:
            pool.worst_roe = acc.worst_roe if pool.worst_roe is None else min(pool.worst_roe, acc.worst_roe)
        for i in TYPE_IDS:
            pool.types[i].merge(acc.types[i])
        for d, cells in acc.dims.items():
            for key, c in cells.items():
                pool.cell(d, key).merge(c)
        if acc.streak > pool.streak:
            pool.streak, pool.streak_acct = acc.streak, acc.streak_acct
        pool.cands = heapq.nsmallest(TOP, pool.cands + acc.cands, key=lambda c: c[:3])
    if len(kinds) >= 2:
        kinds.append(_kind_block({"role": POOLED_ROLE, "suffix": None, "label_ko": "메인 · " + POOLED_KO, "name_ko": POOLED_KO, "short_ko": POOLED_KO},
                                 pool, pool_accts, True, pool_sig, info))
        kinds[-1]["group"] = "all"
    return {"min_losses": MIN_LOSSES, "ds_in_stats": bool(ds_money), "headline_ko": _headline(kinds), "types": loss_types_ko(),
            "note_ko": loss_notes_ko(ds_money), "kinds": kinds}
