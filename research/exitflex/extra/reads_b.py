"""Tier B extra reads of the exit study (research/exitflex/PREREG_EXITFLEX_EXTRA.md E.3; conventions C1-C17 of E.2; main file 3, 7,
8.2, 14). Appendix material (EXTRA_READS_APPENDIX_KO.md); every read is descriptive and chooses nothing (E.1).

    import reads_b
    results = reads_b.run_b(ctx)              # {read id: result}; a read that fails is returned as {'read', 'error'}, never raised
    text = reads_b.appendix_md(results)       # the Korean appendix part of these reads (committed page)
    priv = reads_b.private_md(results)        # the DeepSeek part 부록 for owner_report_extra.md ('[비공개]' lines; never committed)

One result (everything outside 'private' may be committed):
    {'read': id, 'title': Korean title,
     'core': {'pool': 'core', 'read': id, 'order': [...], 'by_arm': {arm: {count columns ..., 'money': {...} (E0 / choosable only)}}, ...},
     'ds':   {'pool': 'ds', 'read': id, 'order': [...], 'by_arm': {arm: {count columns only}}, ...},      (passes common.ds_row_check)
     'private': {'ds': {'by_arm': {arm: {'money': {...}}}, ...}},        (DeepSeek money: E0 and choosable rows only)
     'notes': [...]}
DeepSeek committed rows hold neither 'offered' nor 'no_fill' (nor any offered-derived count); those go to 'private'.

Money (C8) is computed only for E0 and the pool's choosable ids (common.money_allowed): the C4 trade record refuses any other row, and
no statistic over the money of all 88 variants is formed. Re-runs (X-002, X-005, X-041, X-043, and the standalone trades of X-026 and
X-017) use the pinned kernel (common.rerun / kernel_x.simulate_trade) with period 'select' only; their reduced arrays go to
$WORK/<pin8>/extra/reduced/<read>/ (DeepSeek: ds_private/extra/reduced/), never into A's folders.

The shared helpers of the read library (reads_lib: c5_status, c4_trade_frame, excursions, c9_split) are used through small adapters
(_frame_from_lib, _c9) that put their output in this module's record layout. Private fallbacks with the same meaning (_c5_status,
_c4_trade_frame, _excursions, _c9_split, _c4_match) are kept and used when reads_lib lacks a name (FALLBACKS_USED) or USE_LIB is False;
the tests require both paths to give identical results. Nothing here prints a figure.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
from collections import OrderedDict

import numpy as np
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
XDIR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(XDIR))
for _p in (HERE, XDIR, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as XC  # noqa: E402
import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import runner_x as RX  # noqa: E402

K = KX.K

READS = ["X-002", "X-004", "X-005", "X-008", "X-011", "X-015", "X-016", "X-017", "X-018", "X-021", "X-026", "X-028", "X-029", "X-030",
         "X-031", "X-033", "X-034", "X-038", "X-039", "X-041", "X-043"]
TITLES = {"X-002": "코인 하나 빼고 다시 돌리면", "X-004": "주말과 평일", "X-005": "주말 신규 진입 없는 계좌", "X-008": "장세별 성적표",
          "X-011": "롱과 숏 따로", "X-015": "30일 눈금과 반토막·파산 닿음", "X-016": "목표까지 필요한 것",
          "X-017": "신의 손 상한 (실제로는 불가능한 숫자)", "X-018": "버티기: 낙폭·본전 아래 기간·연속 손실",
          "X-021": "동시에 몇 개 열려 있나 (한 계좌로 합치면)", "X-026": "놓친 신호는 좋은 신호였나", "X-028": "어떻게 끝났나: 청산 이유 표",
          "X-029": "한 거래 결과 분포와 손익 모양 (R와 ROE)", "X-030": "먼저 얼마까지 갔다가 끝났나 (최고·최저)",
          "X-031": "최고점에서 얼마나 돌려줬나 (반납)", "X-033": "보유시간 꼬리와 해마다", "X-034": "비용 장부 (수수료·미끄러짐·펀딩)",
          "X-038": "큰 거래 몇 개 덕인가", "X-039": "옆 숫자도 되나 (이웃 비교)", "X-041": "비용이 오르면 (다시 돌린 계좌)",
          "X-043": "1,000달러로 시작하면"}
RERUN_READS = ("X-002", "X-005", "X-017", "X-026", "X-041", "X-043")     # the reads that need the pick's PickData (pre-pass)
REDUCED_DIR = {"X-002": "coin", "X-005": "weekend", "X-017": "hindsight", "X-026": "missed", "X-041": "cost", "X-043": "start1000"}
CAP_PARTS = {"X-041 c = 1.5": ("X-041", 1.5), "X-043 live size": ("X-043", 1.0), "X-002": ("X-002", None)}   # E.5 drops of this file
POOL_KO = {"core": "코어", "ds": "딥시크"}
MONEY_TAG = "맞춘 기간의 성적"
R_DEF_KO = "R: 한 거래의 손익(수수료·펀딩 포함)을 처음 손절까지의 거리 1칸(1R)으로 나눈 값입니다."
DS_NOTHING_KO = "이 풀은 이 읽기의 숫자를 모두 비공개 보고서에만 둡니다."
DS_COUNTS_KO = "이 풀은 거래 수·승패·보유 시간만 적고, 비율은 k/n으로 적습니다. 돈 숫자는 비공개 보고서에만 있습니다."
ERROR_KO = "이 읽기는 이번 실행에서 계산하지 못했습니다(이유는 json의 error 칸)."
DROPPED_KO = "이 읽기는 사전 등록된 시간 상한(E.5)으로 빠졌습니다."
SYMS_SHORT = {s: s[:-4] for s in DX.SYMBOLS}
YEARS = (2021, 2022, 2023)
HOLD_BUCKETS = ((0.0, 1.0), (1.0, 4.0), (4.0, 8.0), (8.0, 18.0), (18.0, 48.0), (48.0, math.inf))
HOLD_BUCKET_KO = ("1시간 미만", "1~4시간", "4~8시간", "8~18시간", "18~48시간", "48시간 이상")
TIERS = (50, 40, 30, 20)
BAR_GROUPS = (("short", ("15m", "30m"), "단타(15분·30분)"), ("long", ("1h", "4h"), "1시간·4시간"))
REASON_SHOWN = ("SL", "LOCK", "TP", "RULE", "LIQ", "END")
REASON_KO = {"SL": "손절", "LOCK": "계단 잠금", "TP": "익절", "RULE": "규칙 청산", "LIQ": "강제청산", "END": "기간 끝"}
R_CODE = {"SL": KX.R_SL, "LOCK": KX.R_LOCK, "TP": KX.R_TP, "RULE": KX.R_RULE, "LIQ": KX.R_LIQ, "END": KX.R_END, "RAND": KX.R_RAND,
          "OPEN": KX.R_OPEN}
EXIT_CLASSES = (("tp", (KX.R_TP,), "익절"), ("sl_lock", (KX.R_SL, KX.R_LOCK), "손절·잠금"), ("rule", (KX.R_RULE,), "규칙 청산"),
                ("end", (KX.R_END,), "기간 끝"))
STATE_LABELS = tuple(DX.STATE_KO[c] for c in DX.STATE_ORDER)
SIDE_LABELS = ("long", "short")
SIDE_KO = {"long": "롱", "short": "숏"}
BASKET_MIN = 5                                   # X-018: a basket of fewer than 5 accounts is not formed
N_BOOT = 2000
WINDOW_DAYS = (30, 92, 365)
W_REF = 5000.0                                   # X-017: the reference wallet of every hindsight trade
COST_MULTS = (0.0, 1.5, 2.0, 3.0)                # X-041 (c = 1 is the step-1 file)
START_SMALL = 1000.0                             # X-043
GRID_MS = 900_000                                # X-021
TARGETS = ((1.0, "본전"), (1.10, "+10%"), (1.50, "+50%"), (2.0, "x2"), (5.0, "x5"), (100.0, "x100"))
GOAL_N = (1, 3, 6, 12, 36)
DAY_MS, HOUR_MS = XC.DAY_MS, XC.HOUR_MS
LO_MS, HI_MS = XC.SELECT_LO, XC.SELECT_HI
LOG_TINY = 1e-12

# reads_lib (the shared read library) provides C5, C4, the excursions and C9; this module calls them through small adapters (its own
# record layout) and keeps private fallbacks with the same meaning (_c5_status, _c4_trade_frame, _excursions, _c9_split, _c4_match), used
# when reads_lib lacks a name or USE_LIB is False (the tests run both paths and require identical results).
try:
    import reads_lib as RL  # noqa: E402
except Exception:                                # noqa: BLE001  (pragma: no cover)
    RL = None
LIB_NAMES = ("c4_match", "c4_trade_frame", "excursions", "c5_status", "c9_split")
FALLBACKS_USED = tuple(n for n in LIB_NAMES if RL is None or not hasattr(RL, n))
USE_LIB = RL is not None and not FALLBACKS_USED


def _make_pd(ctx, p):
    """The pick's PickData: ``ctx.make_pickdata`` when a test sets it (as reads_lib and reads.py do), else ctx.pickdata (the cut)."""
    mk = ctx.__dict__.get("make_pickdata")
    return mk(p) if mk is not None else ctx.pickdata(p)


# ====================================================================================================== small helpers
def _fl(x):
    """A JSON-safe float (None for None / nan / inf)."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _clean(obj):
    """Plain JSON types: numpy scalars and arrays converted, nan / inf as None, dict keys as str."""
    if isinstance(obj, dict):
        return OrderedDict((str(k), _clean(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_clean(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _fl(obj)
    return obj


def _mean(x):
    x = np.asarray(x, float)
    return float(x.mean()) if len(x) else None


def _median(x):
    x = np.asarray(x, float)
    return float(np.median(x)) if len(x) else None


def _share(mask):
    m = np.asarray(mask, bool)
    return float(m.mean()) if len(m) else None


def _qs(x, qs, prefix="p"):
    x = np.asarray(x, float)
    return {f"{prefix}{int(q)}": (float(np.percentile(x, q)) if len(x) else None) for q in qs}


def _lw(w_end, w0) -> float:
    """ln(max(w_end, 1e-12) / w0) (C4)."""
    return math.log(max(float(w_end), LOG_TINY) / float(w0))


def _cat(arrs, dtype=float):
    arrs = [np.asarray(a) for a in arrs]
    return np.concatenate(arrs).astype(dtype) if arrs else np.zeros(0, dtype)


def _date(t_ms) -> str:
    return dt.datetime.fromtimestamp(int(t_ms) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def _month_of(t_ms) -> str:
    return dt.datetime.fromtimestamp(int(t_ms) / 1000, dt.timezone.utc).strftime("%Y-%m")


def _year_of(t_ms) -> np.ndarray:
    t = np.asarray(t_ms, np.int64).astype("datetime64[ms]")
    return t.astype("datetime64[Y]").astype(np.int64) + 1970


def _thin(n, n_picks=None, min_n=XC.THIN_MIN) -> str:
    return XC.c7_mark(int(n or 0), n_picks, min_n)


def _arms_all(ctx, pool: str) -> list:
    """Count columns (C3): E0 and every row of the pool in the select table's order (all 89 in the real run)."""
    return XC.rows_order(ctx, pool)


def _arms_money(ctx, pool: str) -> list:
    """Money columns and re-runs (C3): E0 and the pool's choosable rows, in the committed row order."""
    return [a for a in XC.rows_order(ctx, pool) if XC.money_allowed(ctx, pool, a)]


def _bust(w_end) -> bool:
    return float(w_end) < XC.BUST_W


def _runs(mask) -> np.ndarray:
    """Lengths of the runs of True in a boolean array."""
    m = np.r_[False, np.asarray(mask, bool), False].astype(np.int8)
    d = np.diff(m)
    return np.flatnonzero(d == -1) - np.flatnonzero(d == 1)


# ====================================================================================================== the run state (per run_b call)
class _State:
    """Caches of one run: the picks' offered tables, C5 statuses, trade keys, C4 frames, the re-run summaries of the pre-pass and its
    errors. Attached to the context as ctx._reads_b while run_b runs, so that the contract-shaped helpers (ctx, ...) find it."""

    def __init__(self, ctx, dropped=()):
        self.ctx = ctx
        self.dropped = set(dropped)
        self._off, self._c5, self._c5_real = {}, {}, {}
        self._tk, self._c4 = OrderedDict(), OrderedDict()
        self.rr, self.extra, self.errors, self.dup = {}, {}, {}, set()
        self.select_id = id(ctx.select_doc)

    # ---- picks and symbols
    def picks(self, pool: str) -> list:
        return self.ctx.pool_picks(pool)

    @property
    def syms(self) -> tuple:
        return tuple(self.ctx.market.symbols)

    def short(self, c: int) -> str:
        return SYMS_SHORT[self.syms[int(c)]]

    # ---- offered table (built with the pick's PickData; cached as plain arrays)
    def off(self, pick) -> dict:
        p = self.ctx.pick(pick)
        if p["id"] not in self._off:
            self.set_off(p, _make_pd(self.ctx, p))
        return self._off[p["id"]]

    def set_off(self, p, pdata) -> dict:
        off = pdata.offered("select", self.ctx.market)
        self._off[p["id"]] = {k: np.array(v, copy=True) for k, v in off.items()}
        key = off["coin"].astype(np.int64) * (1 << 50) + off["fill"].astype(np.int64)
        if len(np.unique(key)) != len(key):
            self.dup.add(p["id"])
        return self._off[p["id"]]

    def off_rec(self, pick) -> dict:
        """The offered table as a key record: coin, side, state, t_sig (= close) and the pick's tf."""
        p = self.ctx.pick(pick)
        o = self.off(p)
        return {"coin": o["coin"], "side": o["side"], "state": o["state"].astype(np.int64), "t_sig": o["close"], "tf": p["tf"],
                "pick": p["id"]}

    # ---- C5, trade keys, C4
    def c5(self, pick, arm, size) -> np.ndarray:
        p = self.ctx.pick(pick)
        key = (p["id"], arm, size)
        if key in self._c5_real:
            return self._c5_real[key]
        if key not in self._c5:
            self._c5[key] = (np.asarray(RL.c5_status(self.ctx, p, arm, size)["status"], np.int8) if USE_LIB
                             else _c5_status(self.ctx, p, arm, size))
        return self._c5[key]

    def tk(self, pick, arm, size=XC.SIZE_Q) -> dict:
        """Trade keys of any row (count class, C8): per entered trade q, t_sig, coin, side, state, hold_h, win, reason, comp, fill / exit
        times and the pick's tf. No money (no P&L, wallet or leverage)."""
        p = self.ctx.pick(pick)
        key = (p["id"], arm, size)
        if key in self._tk:
            self._tk.move_to_end(key)
            return self._tk[key]
        acc = XC.account(self.ctx, p, arm, size)
        st = self.c5(p, arm, size)
        off = self.off(p)
        q = np.flatnonzero(st == 1)
        coin, fill = acc["tr_coin"].astype(np.int64), acc["tr_fill"].astype(np.int64)
        if len(q) != len(coin) or not (np.array_equal(off["coin"][q], coin) and np.array_equal(off["fill"][q], fill)):
            raise AssertionError(f"{p['id']} {arm}: entered signals differ from the file's trades")
        rec = {"pick": p["id"], "pool": p["pool"], "tf": p["tf"], "arm": arm, "size": size, "q": q, "t_sig": off["close"][q].astype(np.int64),
               "coin": coin, "side": acc["tr_side"].astype(np.int64), "state": acc["tr_state"].astype(np.int64),
               "hold_h": np.asarray(acc["hold_h"], float), "win": np.asarray(acc["tr_pnl"]) > 0, "reason": acc["tr_reason"].astype(np.int64),
               "comp": acc["tr_comp"].astype(np.int64), "fill_ts": fill,
               "exit_ts": acc["tr_exit"].astype(np.int64)}
        self._tk[key] = rec
        if len(self._tk) > 700:
            self._tk.popitem(last=False)
        return rec

    def c4(self, pick, arm, size=XC.SIZE_Q) -> dict:
        """The C4 record with excursions of E0 or a choosable row (refused on any other row)."""
        p = self.ctx.pick(pick)
        if not XC.money_allowed(self.ctx, p["pool"], arm):
            raise XC.Refused(f"C4: no money record for {arm} in {p['pool']} (선택 불가)")
        key = (p["id"], arm, size)
        if key in self._c4:
            self._c4.move_to_end(key)
            return self._c4[key]
        acc = XC.account(self.ctx, p, arm, size)
        fr = _frame_from_lib(self.ctx, p, acc) if USE_LIB else _excursions(self.ctx, p, _c4_trade_frame(self.ctx, p, acc))
        self._c4[key] = fr
        if len(self._c4) > 400:
            self._c4.popitem(last=False)
        return fr

    def rec(self, pick, arm, size=XC.SIZE_Q) -> dict:
        """C4 on money rows, trade keys elsewhere."""
        p = self.ctx.pick(pick)
        return self.c4(p, arm, size) if XC.money_allowed(self.ctx, p["pool"], arm) else self.tk(p, arm, size)

    # ---- money of whole accounts (E0 and choosable rows only)
    def acc_money(self, pick, arm, size=XC.SIZE_Q) -> dict:
        p = self.ctx.pick(pick)
        if not XC.money_allowed(self.ctx, p["pool"], arm):
            raise XC.Refused(f"no money figure on {arm} in {p['pool']} (선택 불가)")
        return XC.account(self.ctx, p, arm, size)

    def L(self, pool, arm, size=XC.SIZE_Q) -> float:
        """Own monthly growth in log units: mean over the pool's picks of ln(w_end / w0) / 36."""
        return float(np.mean([_lw(a["w_end"], a["w0"]) for a in (self.acc_money(p, arm, size) for p in self.picks(pool))])) / XC.N_MONTHS

    def M(self, pool, arm, size=XC.SIZE_Q) -> float:
        """A's M_P(arm) against E0 at the same size (refused on a 선택 불가 row)."""
        return self.L(pool, arm, size) - self.L(pool, "E0", size)


DS_NEVER = ("offered", "n_off", "no_fill", "after_bust")     # main session decision (a): never in a committed DeepSeek row


def _ds_never_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            low = str(k).lower()
            if any(t in low for t in DS_NEVER):
                yield f"{path}{k}"
            yield from _ds_never_keys(v, f"{path}{k}.")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _ds_never_keys(v, f"{path}[{i}].")


def ds_check(ds_part: dict) -> None:
    """The committed DeepSeek part of a result: common.ds_row_check (C8) and, beyond it, no key naming offered, n_off, no_fill or
    after_bust at any depth (they would give after-bust by subtraction; main session decision a). Raises common.Refused."""
    XC.ds_row_check(ds_part)
    bad = list(_ds_never_keys(ds_part))
    if bad:
        raise XC.Refused("DeepSeek committed row holds an offered / no-fill / after-bust count: " + ", ".join(bad[:6]))


def _st(ctx) -> _State:
    s = ctx.__dict__.get("_reads_b")
    if s is None or s.select_id != id(ctx.select_doc):
        s = ctx.__dict__["_reads_b"] = _State(ctx)
    return s


# ====================================================================================================== fallbacks of reads_lib
class DupFill(AssertionError):
    """Two offered signals of one pick share (coin, fill minute): C5 cannot be rebuilt by matching; the pick uses a real re-run."""


def _c5_status(ctx, pick, arm, size) -> np.ndarray:
    """C5: the status of every offered signal of the account (0 skipped while holding, 1 entered, 2 rejected, 3 no fill, 4 after bust),
    rebuilt by the kernel's walk from the step-1 file and the offered table. Asserts that every step-1 trade is matched in order and
    that the counts of 0, 2, 3 and 4 (and the offered count) equal the file's. Raises DupFill when two offered signals share (coin, fill
    minute) (such a pick uses a real re-run)."""
    s = _st(ctx)
    p = ctx.pick(pick)
    acc = XC.account(ctx, p, arm, size)
    off = s.off(p)
    if p["id"] in s.dup:
        raise DupFill(f"{p['id']}: two offered signals share (coin, fill minute)")
    n = len(off["coin"])
    coin, fill = off["coin"].tolist(), off["fill"].astype(np.int64).tolist()
    tc, tf, tx = acc["tr_coin"].tolist(), acc["tr_fill"].astype(np.int64).tolist(), acc["tr_exit"].astype(np.int64).tolist()
    tr, pnl = acc["tr_reason"].tolist(), acc["tr_pnl"].tolist()
    out = np.zeros(n, np.int8)
    busy, entered_at, wallet, bust, k, ntr = -1, -1, float(acc["w0"]), False, 0, len(tc)
    free_codes = (KX.R_RULE, KX.R_RAND)
    for q in range(n):
        f = fill[q]
        if bust:
            out[q] = 4
            continue
        if f <= busy or f == entered_at:
            out[q] = 0
            continue
        if k < ntr and tc[k] == coin[q] and tf[k] == f:
            out[q] = 1
            wallet += pnl[k]
            busy = tx[k] - 1 if tr[k] in free_codes else tx[k]
            if tr[k] == KX.R_OPEN:
                busy = 2 ** 62
            entered_at = f
            k += 1
            if wallet < XC.BUST_W:
                bust = True
            continue
        out[q] = 2
    if k != ntr:
        raise AssertionError(f"C5 {p['id']} {arm}: {ntr - k} step-1 trades not matched in order")
    cnt = acc["counts"]
    for code, name in ((0, "skipped"), (2, "rejected"), (3, "no_fill"), (4, "after_bust")):
        if int((out == code).sum()) != int(cnt[MT.COUNT_NAMES.index(name)]):
            raise AssertionError(f"C5 {p['id']} {arm}: the count of status {code} differs from the file")
    if int(cnt[MT.COUNT_NAMES.index("offered")]) != n:
        raise AssertionError(f"C5 {p['id']} {arm}: the offered count differs from the file")
    return out


def _c4_match(acc_v: dict, acc_e0: dict) -> np.ndarray:
    """Entry-key match: for each trade of ``acc_v`` the index of the trade of ``acc_e0`` with the same (tr_coin, tr_side, tr_fill), or -1.
    Keys are unique per account (asserted)."""
    def keys(a):
        return list(zip(np.asarray(a["tr_coin"]).tolist(), np.asarray(a["tr_side"]).tolist(), np.asarray(a["tr_fill"]).astype(np.int64).tolist()))
    kv, ke = keys(acc_v), keys(acc_e0)
    if len(set(kv)) != len(kv) or len(set(ke)) != len(ke):
        raise AssertionError("entry keys are not unique in an account")
    pos = {k: i for i, k in enumerate(ke)}
    return np.array([pos.get(k, -1) for k in kv], np.int64)


def _seg_reduce(arr: np.ndarray, s, t, how: str, empty: float) -> np.ndarray:
    """Per pair (s_i, t_i): the max / min / sum of arr[s_i:t_i]; ``empty`` where s_i >= t_i."""
    s, t = np.asarray(s, np.int64), np.asarray(t, np.int64)
    out = np.full(len(s), empty, float)
    ok = t > s
    if not ok.any():
        return out
    a = np.r_[np.asarray(arr, float), 0.0]
    idx = np.ravel(np.column_stack([s[ok], t[ok]]))
    fn = {"max": np.maximum, "min": np.minimum, "sum": np.add}[how]
    out[ok] = fn.reduceat(a, idx)[::2]
    return out


def _c4_trade_frame(ctx, pick, acc) -> dict:
    """C4: the trade record of an account (``acc`` = common.account of E0 or a choosable row; refused on any other row). Per entered
    trade: q (offered index, from C5), t_sig, coin, side, state, e / x (absolute minute indices of tr_fill and tr_exit, asserted exact),
    raw = o[e], fill = raw (1 + side S[1]), Rd = stop_atr x ATR14, atr, best, Wb, (lev, margin, qty, liq) = kernel._size (ok and lev ==
    tr_lev asserted), pnl, ret = x_i, l (sum asserted = ln(w_end / w0) to 1e-9), R = pnl / (qty Rd), ROE = pnl / margin, reason, xpx,
    hold_h, win, comp, fill_ts, exit_ts; plus S, w0 and w_end."""
    p = ctx.pick(pick)
    arm, size = acc["arm"], acc["size"]
    if not XC.money_allowed(ctx, p["pool"], arm):
        raise XC.Refused(f"C4: no money record for {arm} in {p['pool']} (선택 불가)")
    s = _st(ctx)
    off = s.off(p)
    q = np.flatnonzero(s.c5(p, arm, size) == 1)
    n = len(q)
    coin, side = acc["tr_coin"].astype(np.int64), acc["tr_side"].astype(np.int64)
    fts, xts = acc["tr_fill"].astype(np.int64), acc["tr_exit"].astype(np.int64)
    if n != len(coin) or not (np.array_equal(off["coin"][q], coin) and np.array_equal(off["side"][q], side)
                              and np.array_equal(off["fill"][q], fts)):
        raise AssertionError(f"C4 {p['id']} {arm}: trades do not match their offered signals")
    mk = ctx.market
    S = np.asarray(mk.S(size), float)
    e, x = np.zeros(n, np.int64), np.zeros(n, np.int64)
    for c in np.unique(coin):
        sel = coin == c
        tsc = mk.ts(int(c))
        er, xr = np.searchsorted(tsc, fts[sel]), np.searchsorted(tsc, xts[sel])
        if np.any(er >= len(tsc)) or np.any(xr >= len(tsc)) or not (np.array_equal(tsc[er], fts[sel]) and np.array_equal(tsc[xr], xts[sel])):
            raise AssertionError(f"C4 {p['id']} {arm}: a fill or exit time is not a minute of its coin")
        e[sel], x[sel] = mk.starts[int(c)] + er, mk.starts[int(c)] + xr
    raw = mk.cat["o"][e].astype(float)
    fill = raw * (1 + side * S[1])
    stop_atr = KX.exit_of_pick(p, KX.variant_by_id(arm))[0]
    atr = off["atr"][q].astype(float)
    best = off["best"][q].astype(bool)
    Rd = stop_atr * atr
    pnl = acc["tr_pnl"].astype(float)
    if abs(float(S[10]) - float(acc["w0"])) > 1e-9:
        raise AssertionError(f"C4 {p['id']} {arm}: S[10] differs from w0")
    Wb = np.cumsum(np.r_[float(S[10]), pnl])[:-1]
    lev, margin, qty, liq = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    tr_lev = acc["tr_lev"].astype(float)
    for i in range(n):
        c = int(coin[i])
        ok, lv, mg, qt, lq = K._size(S, mk.brs[c], Wb[i], int(side[i]), fill[i], raw[i] - side[i] * Rd[i], atr[i], bool(best[i]),
                                     mk.qty_steps[c], mk.min_notionals[c])
        if not ok or int(lv) != int(round(tr_lev[i])):
            raise AssertionError(f"C4 {p['id']} {arm}: the sizing of trade {i} does not give the kernel's leverage")
        lev[i], margin[i], qty[i], liq[i] = lv, mg, qt, lq
    l = np.log(np.maximum(Wb + pnl, LOG_TINY) / Wb)
    if abs(float(l.sum()) - _lw(acc["w_end"], acc["w0"])) > 1e-9:
        raise AssertionError(f"C4 {p['id']} {arm}: the sum of l_i differs from ln(w_end / w0)")
    return {"pick": p["id"], "pool": p["pool"], "tf": p["tf"], "arm": arm, "size": size, "q": q, "t_sig": off["close"][q].astype(np.int64),
            "coin": coin, "side": side, "state": acc["tr_state"].astype(np.int64), "e": e, "x": x, "raw": raw, "fill": fill, "Rd": Rd,
            "atr": atr, "best": best, "Wb": Wb, "lev": lev, "margin": margin, "qty": qty, "liq": liq, "pnl": pnl, "ret": pnl / Wb, "l": l,
            "R": pnl / (qty * Rd), "ROE": pnl / margin, "reason": acc["tr_reason"].astype(np.int64), "xpx": acc["tr_xpx"].astype(float),
            "hold_h": (xts - fts) / 3_600_000.0, "win": pnl > 0, "comp": acc["tr_comp"].astype(np.int64), "fill_ts": fts, "exit_ts": xts,
            "w0": float(acc["w0"]), "w_end": float(acc["w_end"]), "S": S}


def _excursions(ctx, pick, frame: dict) -> dict:
    """C4 excursions over the 1m last-price highs and lows of minutes e..x-1 plus the exit price (for LIQ, R_i and ROE_i replace the
    exit term): best and worst of Rn0(P) = (side (P - fill) - fill S[5]) / Rd and of ROE0(P) = lev (side (P / fill - 1) - S[5]); funding
    is not included and the exit minute's own range is never used. Returns a copy of the frame with best_R, worst_R, best_ROE, worst_ROE."""
    mk = ctx.market
    S, side, fill, Rd, lev = frame["S"], frame["side"], frame["fill"], frame["Rd"], frame["lev"]
    hi = _seg_reduce(mk.cat["h"], frame["e"], frame["x"], "max", np.nan)
    lo = _seg_reduce(mk.cat["l"], frame["e"], frame["x"], "min", np.nan)
    pb, pw = np.where(side > 0, hi, lo), np.where(side > 0, lo, hi)

    def rn(P):
        return (side * (P - fill) - fill * S[5]) / Rd

    def roe(P):
        return lev * (side * (P / fill - 1) - S[5])
    liqx = frame["reason"] == KX.R_LIQ
    with np.errstate(invalid="ignore"):
        xr = np.where(liqx, frame["R"], rn(frame["xpx"]))
        xo = np.where(liqx, frame["ROE"], roe(frame["xpx"]))
        seg = np.isfinite(pb)
        out = dict(frame)
        out["best_R"] = np.where(seg, np.fmax(rn(pb), xr), xr)
        out["worst_R"] = np.where(seg, np.fmin(rn(pw), xr), xr)
        out["best_ROE"] = np.where(seg, np.fmax(roe(pb), xo), xo)
        out["worst_ROE"] = np.where(seg, np.fmin(roe(pw), xo), xo)
    return out


def _c9_split(ctx, pool, arm, key_fn, size=XC.SIZE_Q, buckets=None, signal_level=True) -> OrderedDict:
    """C9 split columns of one pool and arm for key K. ``key_fn(rec) -> array of bucket keys`` is applied to the offered table (rec =
    _State.off_rec: coin, side, state, t_sig, tf) and to the trades (rec = trade keys or the C4 record). Per bucket b, in the order of
    ``buckets`` (default: the keys seen, sorted): n_off (signal-level keys only; the same for every arm), n_ent, n_skip, n_rej (C5),
    n (closed trades), wins, win share, median hold, share > 8 h, exit-reason counts; money (E0 and choosable rows only, under 'money'):
    mean R and its se, c(b) = 100 x mean over picks of (sum of l_i in b) / 36, dc(b) = c_A(b) - c_E0(b) with sum_b dc(b) = 100 M_P(A)
    asserted to 1e-9, and share(b) = c_A(b) / sum c_A under C17 (None when C17 forbids it)."""
    s = _st(ctx)
    picks = s.picks(pool)
    money = XC.money_allowed(ctx, pool, arm)
    offs = [np.asarray(key_fn(s.off_rec(p))) for p in picks] if signal_level else []
    stats = [s.c5(p, arm, size) for p in picks] if signal_level else []
    recs = [s.rec(p, arm, size) for p in picks]
    keys_t = [np.asarray(key_fn(r)) for r in recs]
    if buckets is None:
        seen = set()
        for k in keys_t + offs:
            seen |= set(np.asarray(k).tolist())
        buckets = sorted(seen)
    out = OrderedDict()
    for b in buckets:
        cell = OrderedDict()
        if signal_level:
            cell["n_off"] = int(sum(int((o == b).sum()) for o in offs))
            cell["n_ent"] = int(sum(int(((o == b) & (z == 1)).sum()) for o, z in zip(offs, stats)))
            cell["n_skip"] = int(sum(int(((o == b) & (z == 0)).sum()) for o, z in zip(offs, stats)))
            cell["n_rej"] = int(sum(int(((o == b) & (z == 2)).sum()) for o, z in zip(offs, stats)))
        sel = [k == b for k in keys_t]
        n = int(sum(int(m.sum()) for m in sel))
        wins = int(sum(int((r["win"] & m).sum()) for r, m in zip(recs, sel)))
        hold = _cat([r["hold_h"][m] for r, m in zip(recs, sel)])
        rs = _cat([r["reason"][m] for r, m in zip(recs, sel)], np.int64)
        cell.update({"n": n, "wins": wins, "win_share": (wins / n if n else None), "hold_median": _median(hold),
                     "hold_share_gt8": _share(hold > 8.0), "reasons": OrderedDict((r, int((rs == R_CODE[r]).sum())) for r in REASON_SHOWN)})
        if money:
            R = _cat([r["R"][m] for r, m in zip(recs, sel)])
            c = XC.c9_contrib([float(r["l"][m].sum()) for r, m in zip(recs, sel)]) if picks else 0.0
            cell["money"] = OrderedDict([("R_mean", _mean(R)), ("R_se", _fl(XC.se(R)) if len(R) > 1 else None), ("c", c)])
        out[b] = cell
    if money:
        e0 = out if arm == "E0" else _c9_split(ctx, pool, "E0", key_fn, size, list(out), signal_level=False)
        for b in out:
            out[b]["money"]["dc"] = out[b]["money"]["c"] - e0[b]["money"]["c"]
        tot = sum(out[b]["money"]["c"] for b in out)
        sh = XC.c17_shares([out[b]["money"]["c"] / 100.0 for b in out], tot / 100.0)
        for i, b in enumerate(out):
            out[b]["money"]["share"] = None if sh is None else float(sh[i])
        if abs(sum(out[b]["money"]["dc"] for b in out) - 100.0 * s.M(pool, arm, size)) > 1e-9:
            raise AssertionError(f"C9 {pool} {arm}: the sum of dc differs from 100 M_P")
    return out


# ====================================================================================================== adapters to reads_lib's layout
def _frame_from_lib(ctx, pick, acc: dict) -> dict:
    """reads_lib.c4_trade_frame + reads_lib.excursions in this module's C4 layout: absolute minute indices e / x into market.cat, ret =
    x_i, S, best, comp, tf and best_R / worst_R / best_ROE / worst_ROE. Refused on a 선택 불가 row."""
    p = ctx.pick(pick)
    if not XC.money_allowed(ctx, p["pool"], acc["arm"]):
        raise XC.Refused(f"C4: no money record for {acc['arm']} in {p['pool']} (선택 불가)")
    fr = RL.c4_trade_frame(ctx, p, acc)
    exc = RL.excursions(ctx, p, fr)
    mk = ctx.market
    coin = np.asarray(fr["coin"], np.int64)
    base = np.asarray(mk.starts, np.int64)[coin] if len(coin) else np.zeros(0, np.int64)
    off = _st(ctx).off(p)
    out = dict(fr)
    out.update(e=base + np.asarray(fr["e"], np.int64), x=base + np.asarray(fr["x"], np.int64), ret=np.asarray(fr["x_ret"], float),
               S=np.asarray(mk.S(float(acc["size"])), float), best=np.asarray(off["best"])[np.asarray(fr["q"], np.int64)].astype(bool),
               comp=np.asarray(acc["tr_comp"], np.int64), tf=p["tf"], best_R=exc["R_best"], worst_R=exc["R_worst"], best_ROE=exc["ROE_best"],
               worst_ROE=exc["ROE_worst"], pnl=np.asarray(fr["pnl"], float))
    return out


def _c9(ctx, pool, arm, key_fn, size=XC.SIZE_Q, buckets=None, signal_level=True) -> OrderedDict:
    """C9 split columns in this module's cell layout ({bucket: {n_off, n_ent, n_skip, n_rej, n, wins, win_share, hold_median,
    hold_share_gt8, reasons (counts), money: {R_mean, R_se, c, dc, share}}}): reads_lib.c9_split when used, else the fallback."""
    if not USE_LIB:
        return _c9_split(ctx, pool, arm, key_fn, size, buckets, signal_level)
    r = RL.c9_split(ctx, pool, arm, key_fn, size, buckets=buckets)
    out = OrderedDict()
    for i, cell in enumerate(r["cells"]):
        n = int(cell["n"])
        c = OrderedDict()
        if signal_level and r.get("signal_level"):
            c.update(n_off=cell["n_off"], n_ent=cell["n_ent"], n_skip=cell["n_skip"], n_rej=cell["n_rej"])
        c.update(n=n, wins=cell["wins"], win_share=cell["win_share"], hold_median=cell["hold_median"], hold_share_gt8=cell["share_gt8h"],
                 reasons=OrderedDict((x, int(round((cell["reasons"].get(x) or 0.0) * n))) for x in REASON_SHOWN))
        if r.get("money") is not None:
            m = r["money"][i]
            c["money"] = OrderedDict([("R_mean", m["mean_R"]), ("R_se", m["se_R"]), ("c", m["c"]), ("dc", m["dc"]), ("share", m["share"])])
        out[cell["bucket"]] = c
    return out


# ====================================================================================================== result skeleton and rows
def _new(rid: str) -> dict:
    return OrderedDict([("read", rid), ("title", TITLES[rid]),
                        ("core", OrderedDict([("pool", "core"), ("read", rid), ("order", []), ("by_arm", OrderedDict())])),
                        ("ds", OrderedDict([("pool", "ds"), ("read", rid), ("order", []), ("by_arm", OrderedDict())])),
                        ("private", OrderedDict([("ds", OrderedDict([("by_arm", OrderedDict())]))])), ("notes", [])])


def _put(st: _State, res: dict, pool: str, arm: str, counts: dict | None, money: dict | None = None, private: dict | None = None) -> None:
    """One row. ``counts`` (count class, C8) go to the committed row of both pools; ``money`` only on E0 and choosable rows (the core
    row's 'money', the DeepSeek private row's 'money'); ``private`` are DeepSeek-only private extras of the row (offered-derived
    counts and other C8 money-class counts)."""
    if money is not None and not XC.money_allowed(st.ctx, pool, arm):
        raise XC.Refused(f"money on a 선택 불가 row: {arm} in {pool}")
    if counts is not None:
        P = res[pool]
        P["order"].append(arm)
        P["by_arm"][arm] = OrderedDict(counts)
        if pool == "core" and money is not None:
            P["by_arm"][arm]["money"] = money
    elif pool == "core" and money is not None:
        res["core"]["order"].append(arm)
        res["core"]["by_arm"][arm] = OrderedDict([("money", money)])
    if pool == "ds" and (money is not None or private):
        if not XC.money_allowed(st.ctx, pool, arm):
            raise XC.Refused(f"private DeepSeek rows are E0 and choosable rows only: {arm}")
        row = res["private"]["ds"]["by_arm"].setdefault(arm, OrderedDict())
        if private:
            row.update(private)
        if money is not None:
            row["money"] = money


def _drop_off(cells: dict) -> tuple:
    """(cells without n_off, {bucket: n_off}) - the DeepSeek committed rows hold no offered-derived count."""
    kept, offs = OrderedDict(), OrderedDict()
    for b, c in cells.items():
        c = OrderedDict(c)
        if "n_off" in c:
            offs[b] = c.pop("n_off")
        kept[b] = c
    return kept, offs


def _strip_money(cells: dict) -> tuple:
    """(cells without 'money', {bucket: money})."""
    kept, mon = OrderedDict(), OrderedDict()
    for b, c in cells.items():
        c = OrderedDict(c)
        if "money" in c:
            mon[b] = c.pop("money")
        kept[b] = c
    return kept, mon


def _c17(parts_pct, total_pct):
    """C17 on values in '%/월 (기여)' units (100 x log): the shares, or None (print the amounts and W15)."""
    sh = XC.c17_shares([x / 100.0 for x in parts_pct], total_pct / 100.0)
    return None if sh is None else [float(x) for x in sh]


# ====================================================================================================== pre-pass: one PickData per pick
KEEP_BASE = ("g", "w0", "w_end", "max_dd", "counts", "reasons")
KEEP = {"X-002": KEEP_BASE, "X-041": KEEP_BASE, "X-043": KEEP_BASE,                      # C2: only the reduced arrays a read needs
        "X-005": KEEP_BASE + ("hold_h", "tr_coin", "tr_side", "tr_fill", "tr_exit", "tr_pnl")}


def _rerun_keep(st: _State, rid: str, p: dict, pdata, arm: str, part: str, scale: float, offered=None, S=None) -> dict:
    """C2: one re-run of the pinned kernel (period 'select'); only the reduced arrays are kept."""
    res = XC.rerun(st.ctx, pdata, arm, scale, offered=offered, S=S)
    s = MT.summarize(res, st.ctx.edges)
    keep = {k: np.asarray(s[k]) for k in KEEP[rid]}
    st.rr[(rid, p["id"], arm, part, scale)] = keep
    return keep


def _save_reduced(st: _State, rid: str, p: dict) -> None:
    """One reduced file per pick, size and read under $WORK/<pin8>/extra/reduced/<dir>/ (DeepSeek under ds_private/extra/reduced/)."""
    by_size = {}
    for (r, pid, arm, part, scale), keep in st.rr.items():
        if r == rid and pid == p["id"]:
            d = by_size.setdefault(scale, {})
            for k, v in keep.items():
                d[f"{arm}__{part}__{k}"] = v
    for (r, pid, arm), doc in st.extra.items() if rid == "X-026" else ():
        if r == rid and pid == p["id"]:
            d = by_size.setdefault(XC.SIZE_Q, {})
            for k, v in doc.items():
                d[f"{arm}__missed__{k}"] = np.asarray(v)
    for scale, doc in by_size.items():
        XC.save_reduced(st.ctx, p, REDUCED_DIR[rid], scale, doc)


def _pre_x002(st: _State, p: dict, pdata, arm: str) -> None:
    off = pdata.offered("select", st.ctx.market)
    for c, sym in enumerate(st.syms):
        _rerun_keep(st, "X-002", p, pdata, arm, sym, XC.SIZE_Q, offered=XC.mask_offered(off, off["coin"] != c))


def _pre_x005(st: _State, p: dict, pdata, arm: str) -> None:
    off = pdata.offered("select", st.ctx.market)
    _rerun_keep(st, "X-005", p, pdata, arm, "noweekend", XC.SIZE_Q, offered=XC.mask_offered(off, ~XC.is_weekend(off["close"])))


def _cost_S(market, c: float) -> np.ndarray:
    """X-041: market.S(0.25) with taker S[0], slippage S[1], round trip S[5] and maker S[19] times c."""
    S0 = market.S(XC.SIZE_Q)
    return XC.settings_copy(market, XC.SIZE_Q, {i: float(S0[i]) * c for i in (0, 1, 5, 19)})


def _x041_mults(st: _State) -> tuple:
    return tuple(c for c in COST_MULTS if not (c == 1.5 and "X-041 c = 1.5" in st.dropped))


def _pre_x041(st: _State, p: dict, pdata, arm: str) -> None:
    for c in _x041_mults(st):
        _rerun_keep(st, "X-041", p, pdata, arm, f"c{c:g}", XC.SIZE_Q, S=_cost_S(st.ctx.market, c))


def _small_S(market, scale: float) -> np.ndarray:
    """X-043: market.S(scale) with the starting wallet S[10] = 1,000 and nothing else changed (the bust line S[9] stays $10)."""
    S0 = market.S(scale)
    if float(S0[10]) != 5000.0 or float(S0[9]) != XC.BUST_W:
        raise AssertionError("X-043: the base settings do not start at $5,000 with the $10 bust line")
    return XC.settings_copy(market, scale, {10: START_SMALL})


def _x043_sizes(st: _State) -> tuple:
    return tuple(s for s in RX.SIZE_TAG if not (s == XC.SIZE_LIVE and "X-043 live size" in st.dropped))


def _pre_x043(st: _State, p: dict, pdata, arm: str) -> None:
    for scale in _x043_sizes(st):
        _rerun_keep(st, "X-043", p, pdata, arm, "w1000", scale, S=_small_S(st.ctx.market, scale))


def _wallet_before(acc: dict, f) -> np.ndarray:
    """X-025 (c1): the realised wallet just before fill minute(s) ``f``: every trade with an exit before the fill, plus a RULE or RAND
    exit at that same minute."""
    ex, pnl = acc["tr_exit"].astype(np.int64), acc["tr_pnl"].astype(float)
    cum = np.r_[0.0, np.cumsum(pnl)]
    rule = np.isin(acc["tr_reason"], (KX.R_RULE, KX.R_RAND))
    f = np.atleast_1d(np.asarray(f, np.int64))
    k = np.searchsorted(ex, f, side="left")
    for i in range(len(f)):
        while k[i] < len(ex) and ex[k[i]] == f[i] and rule[k[i]]:
            k[i] += 1
    return float(acc["w0"]) + cum[k]


def _sizeable(market, S, off: dict, q: np.ndarray, W: np.ndarray, stop_atr: float) -> np.ndarray:
    """kernel._size(S, brs[coin], W, side, o[e] (1 + side S[1]), o[e] - side stop_atr ATR14, ATR14, best, qty_step, min_notional) ok."""
    ok = np.zeros(len(q), bool)
    for i, qq in enumerate(np.asarray(q, np.int64)):
        c = int(off["coin"][qq])
        tsc = market.ts(c)
        e = int(np.searchsorted(tsc, off["fill"][qq]))
        raw = float(market.cat["o"][market.starts[c] + e])
        side, atr = int(off["side"][qq]), float(off["atr"][qq])
        ok[i] = bool(K._size(S, market.brs[c], float(W[i]), side, raw * (1 + side * S[1]), raw - side * stop_atr * atr, atr,
                             bool(off["best"][qq]), market.qty_steps[c], market.min_notionals[c])[0])
    return ok


def _pre_x026(st: _State, p: dict, pdata, arm: str) -> None:
    ctx, mk = st.ctx, st.ctx.market
    off = pdata.offered("select", mk)
    S = mk.S(XC.SIZE_Q)
    tg = pdata.targets(off) if arm in ("F11.b", "F12.b") else None
    acc = XC.account(ctx, p, arm, XC.SIZE_Q)
    v = KX.variant_by_id(arm)
    qs = np.flatnonzero(st.c5(p, arm, XC.SIZE_Q) == 0)
    W = _wallet_before(acc, off["fill"][qs]) if len(qs) else np.zeros(0)
    ok = _sizeable(mk, S, off, qs, W, KX.exit_of_pick(p, v)[0])
    r, hold = [], []
    for q, w in zip(qs[ok], W[ok]):
        c = int(off["coin"][q])
        tp = float(tg[q]) if tg is not None else float("nan")
        out = KX.simulate_trade(mk, pdata, v, off, int(q), XC.SIZE_Q, "select", equity=float(w), tp_price=tp)[0]
        if int(out[2]) == KX.R_REJECT:
            raise AssertionError(f"X-026 {p['id']} {arm}: a sizeable signal was rejected by the kernel")
        a = int(mk.starts[c])
        tsp = mk.cat["ts"][a:int(mk.period_end("select")[c])]
        r.append(float(out[0]) / float(w))
        hold.append((int(tsp[int(out[1])]) - int(off["fill"][q])) / 3_600_000.0)
    st.extra[("X-026", p["id"], arm)] = {"q": qs[ok], "W": W[ok], "r": np.asarray(r, float), "hold_h": np.asarray(hold, float),
                                         "n_skipped": np.int64(len(qs)), "n_sizeable": np.int64(int(ok.sum()))}


def _dup_statuses(st: _State, p: dict, pdata) -> None:
    """C5's exception: a pick whose offered table has two signals on one (coin, fill minute) takes every status from a real re-run."""
    for arm in _arms_all(st.ctx, p["pool"]):
        for size in RX.SIZE_TAG:
            res = XC.rerun(st.ctx, pdata, arm, size)
            f = XC.account(st.ctx, p, arm, size)
            ent = np.flatnonzero(res.status == 1)
            if not (np.array_equal(res.pnl[ent], f["tr_pnl"]) and np.array_equal(res.exit_ts[ent], f["tr_exit"])):
                raise AssertionError(f"C5 {p['id']} {arm}: the real re-run differs from the step-1 file")
            st._c5_real[(p["id"], arm, size)] = np.asarray(res.status, np.int8)


PRE = {"X-002": _pre_x002, "X-005": _pre_x005, "X-026": _pre_x026, "X-041": _pre_x041, "X-043": _pre_x043}   # per (pick, arm)
PRE_PICK = {}                                                                                                  # per pick (X-017)


def _err(exc) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _prepass(st: _State, reads: list) -> None:
    """C2: one PickData per pick; the pick's money arms in the outer loop (one chart set each), every re-run read's masks and settings
    inside; then the pick's reduced files; X-017 per pick. A failing part marks only its read."""
    need = [r for r in RERUN_READS if r in reads and r in PRE and r not in st.dropped]
    need_pick = [r for r in RERUN_READS if r in reads and r in PRE_PICK and r not in st.dropped]
    for p in st.ctx.picks:
        try:
            pdata = _make_pd(st.ctx, p)
            st.set_off(p, pdata)
            if p["id"] in st.dup and not USE_LIB:              # reads_lib re-runs such a pick itself
                _dup_statuses(st, p, pdata)
        except Exception as exc:                                   # noqa: BLE001
            st.errors.setdefault("*", _err(exc))
            continue
        for arm in _arms_money(st.ctx, p["pool"]):
            for rid in need:
                if rid not in st.errors:
                    try:
                        PRE[rid](st, p, pdata, arm)
                    except Exception as exc:                       # noqa: BLE001
                        st.errors[rid] = _err(exc)
        for rid in need:
            if rid not in st.errors:
                try:
                    _save_reduced(st, rid, p)
                except Exception as exc:                           # noqa: BLE001
                    st.errors[rid] = _err(exc)
        for rid in need_pick:
            if rid not in st.errors:
                try:
                    PRE_PICK[rid](st, p, pdata)
                except Exception as exc:                           # noqa: BLE001
                    st.errors[rid] = _err(exc)
        del pdata


def run_b(ctx, dropped=(), reads=None) -> dict:
    """Every tier B read on the select period: {read id: result}. ``dropped``: parts dropped by the E.5 cap ('X-041 c = 1.5', 'X-043
    live size', 'X-002'). A read that fails returns {'read', 'title', 'error'} and the others go on."""
    reads = list(READS if reads is None else reads)
    bad = [r for r in reads if r not in READS]
    if bad:
        raise KeyError(f"not a tier B read of this module: {bad}")
    st = _State(ctx, dropped)
    ctx.__dict__["_reads_b"] = st
    out = OrderedDict()
    try:
        _prepass(st, reads)
        for rid in reads:
            if rid in st.dropped:
                out[rid] = OrderedDict([("read", rid), ("title", TITLES[rid]), ("dropped", "E.5 cap")])
                continue
            try:
                if "*" in st.errors:
                    raise RuntimeError(f"pre-pass: {st.errors['*']}")
                if rid in st.errors:
                    raise RuntimeError(f"pre-pass: {st.errors[rid]}")
                res = FUNCS[rid](st)
                for pool in XC.POOLS:
                    res[pool]["label_choosable"] = [a for a in _arms_money(ctx, pool) if a != "E0"]
                res = _clean(res)
                ds_check(res["ds"])
                out[rid] = res
            except Exception as exc:                               # noqa: BLE001
                out[rid] = OrderedDict([("read", rid), ("title", TITLES[rid]), ("error", f"{type(exc).__name__}: {str(exc)[:300]}")])
    finally:
        ctx.__dict__.pop("_reads_b", None)
    return out


DROPPED_AT_O8: dict = {}                         # E.0 item 2 (a): X-017's tests are green, so nothing of tier B is dropped at O8


# ====================================================================================================== keys of the split reads
STATE_BY_CODE = np.array([DX.STATE_KO[c] for c in range(len(DX.STATE_KO))], dtype=object)


def _key_side(r):
    return np.where(np.asarray(r["side"]) > 0, "long", "short")


def _key_state(r):
    return STATE_BY_CODE[np.asarray(r["state"], np.int64)].astype(str)


def _dims(st: _State) -> tuple:
    """X-004's appendix splits, each on its own (never crossed): side, pick bar, coin, UTC year of t_sig, 장세 at entry."""
    names = np.array([st.short(c) for c in range(len(st.syms))])
    return (("side", _key_side, SIDE_LABELS),
            ("tf", lambda r: np.full(len(r["side"]), r["tf"]), DX.TFS),
            ("coin", lambda r: names[np.asarray(r["coin"], np.int64)], tuple(names)),
            ("year", lambda r: _year_of(r["t_sig"]).astype(str), tuple(str(y) for y in YEARS)),
            ("state", _key_state, STATE_LABELS))


def _cell_counts(recs: list, sels: list) -> OrderedDict:
    n = int(sum(int(m.sum()) for m in sels))
    wins = int(sum(int((r["win"] & m).sum()) for r, m in zip(recs, sels)))
    hold = _cat([r["hold_h"][m] for r, m in zip(recs, sels)])
    return OrderedDict([("n", n), ("wins", wins), ("win_share", wins / n if n else None), ("hold_median", _median(hold))])


# ====================================================================================================== X-004 weekend and weekday
def _thin_pair(by: dict) -> bool:
    """C7 / C15: a weekend-weekday cell is flagged when a non-empty cell has a bucket under 100 trades (an empty cell is '-')."""
    a, b = by["weekend"]["n"], by["weekday"]["n"]
    return max(a, b) > 0 and min(a, b) < XC.THIN_MIN


def _wk_counts(recs, sels, wks) -> OrderedDict:
    return OrderedDict([("weekend", _cell_counts(recs, [m & w for m, w in zip(sels, wks)])),
                        ("weekday", _cell_counts(recs, [m & ~w for m, w in zip(sels, wks)]))])


def _wk_money(recs, sels, wks, seed) -> OrderedDict:
    """lam(wk) = pooled mean l_i per trade; G(wk) = 100 x mean over picks of (sum of l_i in wk) / 36 (G(0) + G(1) = G(all) asserted);
    'weekend erased' = G(0); weekend share of growth G(1) / G(all) under C17; dlam = lam(1) - lam(0) with the week-bootstrap range
    (157 Monday weeks of t_sig, 2,000 draws, seed C11; draws with an empty bucket dropped and counted)."""
    out = OrderedDict()
    G = {}
    for b, name in ((1, "weekend"), (0, "weekday")):
        ms = [m & (w if b else ~w) for m, w in zip(sels, wks)]
        s = float(sum(float(r["l"][m].sum()) for r, m in zip(recs, ms)))
        n = int(sum(int(m.sum()) for m in ms))
        out["lam_" + name] = s / n if n else None
        G[b] = XC.c9_contrib([float(r["l"][m].sum()) for r, m in zip(recs, ms)])
    Gall = XC.c9_contrib([float(r["l"][m].sum()) for r, m in zip(recs, sels)])
    if abs(G[0] + G[1] - Gall) > 1e-9:
        raise AssertionError("X-004: G(weekday) + G(weekend) differs from G(all)")
    out.update(G_weekend=G[1], G_weekday=G[0], G_all=Gall, erased=G[0])
    sh = _c17([G[1], G[0]], Gall)
    out["share_weekend_growth"] = None if sh is None else sh[0]
    out["dlam"] = (out["lam_weekend"] - out["lam_weekday"]) if out["lam_weekend"] is not None and out["lam_weekday"] is not None else None
    agg = np.zeros((XC.N_WEEKS, 2, 2))
    for r, m, w in zip(recs, sels, wks):
        if m.any():
            agg += XC.week_aggregates(r["t_sig"][m], r["l"][m], w[m])
    ci = XC.week_bootstrap_ci(agg, n=N_BOOT, seed=seed, stat=XC.lam_diff)
    ok = math.isfinite(ci[0]) and math.isfinite(ci[1])
    out.update(range_lo=_fl(ci[0]), range_hi=_fl(ci[1]), n_draws_used=ci.n_used, n_draws_dropped=ci.n_dropped,
               label_chance=("우연 가능" if ok and ci.contains_zero else ("" if ok else "-")), outside=bool(ok and not ci.contains_zero))
    return out


def _r_x004(st: _State) -> dict:
    rid, ctx = "X-004", st.ctx
    res = _new(rid)
    dims = _dims(st)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        offs = [st.off(p) for p in picks]
        n_off = int(sum(len(o["coin"]) for o in offs))
        n_wk = int(sum(int(XC.is_weekend(o["close"]).sum()) for o in offs))
        offd = OrderedDict([("offered", n_off), ("offered_weekend", n_wk), ("share_offered_weekend", n_wk / n_off if n_off else None)])
        (res["core"] if pool == "core" else res["private"]["ds"]).update(offd)
        res[pool]["share_calendar_weekend"] = XC.CAL_WEEKEND_SHARE
        tables = OrderedDict((t, [0, 0, 0]) for t in ("all",) + tuple(d[0] for d in dims))     # C15: cells, thin, outside the range
        for arm in _arms_all(ctx, pool):
            ok = XC.money_allowed(ctx, pool, arm)
            recs = [st.rec(p, arm) for p in picks]
            wks = [XC.is_weekend(r["t_sig"]) for r in recs]
            sels = [np.ones(len(r["t_sig"]), bool) for r in recs]
            by = _wk_counts(recs, sels, wks)
            n = by["weekend"]["n"] + by["weekday"]["n"]
            counts = OrderedDict([("n", n), ("n_weekend", by["weekend"]["n"]), ("share_weekend", by["weekend"]["n"] / n if n else None),
                                  ("by_wk", by), ("flag", _thin(min(by["weekend"]["n"], by["weekday"]["n"])))])
            money = _wk_money(recs, sels, wks, XC.seed_c11(rid, pool, arm)) if ok else None
            if ok:
                tables["all"][0] += 1
                tables["all"][1] += int(_thin_pair(by))
                tables["all"][2] += int(money["outside"])
            for dim, fn, buckets in dims:
                keys = [fn(r) for r in recs]
                cd, md = OrderedDict(), OrderedDict()
                for b in buckets:
                    sb = [k == b for k in keys]
                    cd[b] = _wk_counts(recs, sb, wks)
                    if ok:
                        md[b] = _wk_money(recs, sb, wks, XC.seed_c11(rid, pool, arm, f"{dim}:{b}"))
                        tables[dim][0] += 1
                        tables[dim][1] += int(_thin_pair(cd[b]))
                        tables[dim][2] += int(md[b]["outside"])
                counts["by_" + dim] = cd
                if ok:
                    money["by_" + dim] = md
            _put(st, res, pool, arm, counts, money)
        res[pool]["by_table"] = OrderedDict((t, OrderedDict([("n_cells", v[0]), ("n_thin", v[1])])) for t, v in tables.items())
        outside = OrderedDict((t, v[2]) for t, v in tables.items())
        if pool == "core":
            for t in tables:
                res["core"]["by_table"][t]["n_outside"] = outside[t]
        else:
            res["private"]["ds"]["n_outside_by_table"] = outside
    res["notes"].append("weekend = Sat 00:00 <= t_sig < Mon 00:00 UTC (E.9 item 1); year split by the UTC year of t_sig; split G use the "
                        "pool's N picks as denominator so that the buckets add up")
    return res


# ====================================================================================================== X-008 market state, X-011 side
def _comp_by(recs, sels) -> OrderedDict:
    fired, alone = OrderedDict(), OrderedDict()
    for lab, bit in zip(MT.COMP_LABELS, MT.COMP_BITS):
        fired[lab] = int(sum(int((m & (r["reason"] == KX.R_RULE) & ((r["comp"] & bit) != 0)).sum()) for r, m in zip(recs, sels)))
        alone[lab] = int(sum(int((m & (r["reason"] == KX.R_RULE) & (r["comp"] == bit)).sum()) for r, m in zip(recs, sels)))
    return OrderedDict([("comp_fired", fired), ("comp_alone", alone)])


def _with_shares(cells: dict) -> dict:
    for c in cells.values():
        n = c["n"]
        c["share_reasons"] = OrderedDict((r, (k / n if n else None)) for r, k in c["reasons"].items())
        c["flag"] = _thin(n)
    return cells


def _split_put(st: _State, res: dict, pool: str, arm: str, name: str, cells: dict, extra_counts=None, extra_money=None) -> None:
    """Put a C9 split: counts committed (DeepSeek without n_off), money on E0 / choosable rows only (core row / DeepSeek private)."""
    cells, mon = _strip_money(cells)
    ok = XC.money_allowed(st.ctx, pool, arm)
    priv = None
    if pool == "ds":
        cells, offs = _drop_off(cells)
        if ok and offs:
            priv = {name + "_offered": offs}
    counts = OrderedDict([(name, cells)])
    counts.update(extra_counts or {})
    money = None
    if ok:
        money = OrderedDict([(name, mon)])
        money.update(extra_money or {})
    _put(st, res, pool, arm, counts, money, priv)


def _r_x008(st: _State) -> dict:
    rid, ctx = "X-008", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        n_thin = n_cells = 0
        for arm in _arms_all(ctx, pool):
            cells = _with_shares(_c9(ctx, pool, arm, _key_state, XC.SIZE_Q, buckets=STATE_LABELS))
            if arm.startswith("F12."):
                recs = [st.rec(p, arm) for p in picks]
                keys = [_key_state(r) for r in recs]
                for b in STATE_LABELS:
                    cells[b].update(_comp_by(recs, [k == b for k in keys]))
            em = None
            if XC.money_allowed(ctx, pool, arm):
                em = OrderedDict([("dc_sum", sum(c["money"]["dc"] for c in cells.values())), ("M100", 100.0 * st.M(pool, arm))])
                n_cells += len(cells)
                n_thin += sum(int(0 < c["n"] < XC.THIN_MIN) for c in cells.values())
            _split_put(st, res, pool, arm, "by_state", cells, extra_money=em)
        res[pool]["by_table"] = OrderedDict([("all", OrderedDict([("n_cells", n_cells), ("n_thin", n_thin)]))])
    return res


def _nest(cells: dict, outer: tuple) -> OrderedDict:
    """'long|추세장' style buckets into {long: {추세장: cell}}."""
    out = OrderedDict((o, OrderedDict()) for o in outer)
    for b, c in cells.items():
        o, i = b.split("|", 1)
        out[o][i] = c
    return out


def _r_x011(st: _State) -> dict:
    rid, ctx = "X-011", st.ctx
    res = _new(rid)
    names = [st.short(c) for c in range(len(st.syms))]
    name_arr = np.array(names)

    def k_state(r):
        return np.char.add(np.char.add(_key_side(r).astype(str), "|"), _key_state(r))

    def k_coin(r):
        return np.char.add(np.char.add(_key_side(r).astype(str), "|"), name_arr[np.asarray(r["coin"], np.int64)].astype(str))

    def k_coin_only(r):
        return name_arr[np.asarray(r["coin"], np.int64)]
    b_state = [f"{s}|{x}" for s in SIDE_LABELS for x in STATE_LABELS]
    b_coin = [f"{s}|{x}" for s in SIDE_LABELS for x in names]
    for pool in XC.POOLS:
        for arm in _arms_all(ctx, pool):
            ok = XC.money_allowed(ctx, pool, arm)
            side = _with_shares(_c9(ctx, pool, arm, _key_side, XC.SIZE_Q, buckets=SIDE_LABELS))
            cs = _c9(ctx, pool, arm, k_state, XC.SIZE_Q, buckets=b_state, signal_level=False)
            cc = _c9(ctx, pool, arm, k_coin, XC.SIZE_Q, buckets=b_coin, signal_level=False)
            keep_c = ("n", "wins", "win_share")
            cs_counts = OrderedDict((b, OrderedDict((k, c[k]) for k in keep_c)) for b, c in cs.items())
            cc_counts = OrderedDict((b, OrderedDict((k, c[k]) for k in keep_c + ("hold_median",))) for b, c in cc.items())
            em = None
            if ok:
                cs_m = OrderedDict((b, OrderedDict((k, c["money"][k]) for k in ("R_mean", "c", "dc"))) for b, c in cs.items())
                cc_m = OrderedDict((b, OrderedDict((k, c["money"][k]) for k in ("R_mean", "c", "dc"))) for b, c in cc.items())
                coin_only = _c9(ctx, pool, arm, k_coin_only, XC.SIZE_Q, buckets=names, signal_level=False)
                for k in names:
                    if abs(cc_m[f"long|{k}"]["c"] + cc_m[f"short|{k}"]["c"] - coin_only[k]["money"]["c"]) > 1e-9:
                        raise AssertionError("X-011: c_{k,long} + c_{k,short} differs from c_k")
                em = OrderedDict([("by_side_state", _nest(cs_m, SIDE_LABELS)), ("by_side_coin", _nest(cc_m, SIDE_LABELS))])
            _split_put(st, res, pool, arm, "by_side", side,
                       extra_counts=OrderedDict([("by_side_state", _nest(cs_counts, SIDE_LABELS)),
                                                 ("by_side_coin", _nest(cc_counts, SIDE_LABELS))]), extra_money=em)
    return res


# ====================================================================================================== X-028 exit reasons
def _reason_counts(rs: np.ndarray) -> OrderedDict:
    n = len(rs)
    cnt = OrderedDict((r, int((rs == R_CODE[r]).sum())) for r in REASON_SHOWN)
    return OrderedDict([("n", n), ("reasons", cnt), ("share_reasons", OrderedDict((r, (k / n if n else None)) for r, k in cnt.items())),
                        ("flag", _thin(n))])


def _reason_money(R: np.ndarray, rs: np.ndarray) -> OrderedDict:
    out = OrderedDict()
    out["R_mean_by_reason"] = OrderedDict((r, _mean(R[rs == R_CODE[r]])) for r in REASON_SHOWN)
    out["thin_by_reason"] = OrderedDict((r, bool(0 < int((rs == R_CODE[r]).sum()) < 20)) for r in REASON_SHOWN)
    sl, rule = rs == KX.R_SL, rs == KX.R_RULE
    out["share_sl_below_1_25R"] = _share(R[sl] < -1.25) if sl.any() else None
    out["n_sl"] = int(sl.sum())
    out["share_rule_nonneg"] = _share(R[rule] >= 0) if rule.any() else None
    out["n_rule"] = int(rule.sum())
    neg = rule & (R < 0)
    out["R_mean_rule_neg"] = _mean(R[neg])
    out["n_rule_neg"] = int(neg.sum())
    return out


def _select_row(ctx, pool: str, arm: str):
    """A's committed select.json row of ``arm`` in ``pool`` (E0: the pool's e0 entry), or None."""
    P = ((ctx.select_doc or {}).get("pools") or {}).get(pool) or {}
    if arm == "E0":
        return P.get("e0")
    for r in P.get("variants") or []:
        if r.get("id") == arm:
            return r
    return None


def _r_x028(st: _State) -> dict:
    rid, ctx = "X-028", st.ctx
    res = _new(rid)
    names = [st.short(c) for c in range(len(st.syms))]
    n_checked = 0
    for pool in XC.POOLS:
        picks = st.picks(pool)
        for arm in _arms_all(ctx, pool):
            ok = XC.money_allowed(ctx, pool, arm)
            recs = [st.rec(p, arm) for p in picks]
            rs = _cat([r["reason"] for r in recs], np.int64)
            if int((rs == KX.R_RAND).sum()) or int((rs == KX.R_OPEN).sum()):
                raise AssertionError(f"X-028 {pool} {arm}: RAND or OPEN exits in a real arm")
            counts = _reason_counts(rs)
            row = _select_row(ctx, pool, arm)
            if row is not None and isinstance(row.get("reasons"), dict):
                for r in REASON_SHOWN:
                    if r in row["reasons"] and int(row["reasons"][r]) != counts["reasons"][r]:
                        raise AssertionError(f"X-028 {pool} {arm}: the {r} count differs from select.json")
                counts["label_select"] = "select.json과 같음"
                n_checked += 1
            v = KX.variant_by_id(arm)
            counts["label_rule"] = RX.FAMILY_KO.get(v.famname, "") if v.famname != "E0" else ""
            if arm.startswith("F12."):
                counts.update(_comp_by(recs, [np.ones(len(r["reason"]), bool) for r in recs]))
            coins = [np.asarray(r["coin"], np.int64) for r in recs]
            counts["by_coin"] = OrderedDict((names[c], _reason_counts(_cat([r["reason"][k == c] for r, k in zip(recs, coins)], np.int64)))
                                            for c in range(len(names)))
            money = None
            if ok:
                R = _cat([r["R"] for r in recs])
                money = _reason_money(R, rs)
                money["by_coin"] = OrderedDict((names[c], _reason_money(_cat([r["R"][k == c] for r, k in zip(recs, coins)]),
                                                                        _cat([r["reason"][k == c] for r, k in zip(recs, coins)], np.int64)))
                                               for c in range(len(names)))
            _put(st, res, pool, arm, counts, money)
    res["notes"].append(f"rows checked against select.json reasons: {n_checked}")
    return res


# ====================================================================================================== X-029 one trade's result
QS7 = (5, 10, 25, 50, 75, 90, 95)


def _shape_money(R, ROE, win) -> OrderedDict:
    out = OrderedDict()
    out["R_q"] = _qs(R, QS7)
    out["ROE_q"] = _qs(ROE, QS7)
    for k, cond in (("share_roe_le_m40", ROE <= -0.40), ("share_roe_le_m60", ROE <= -0.60), ("share_roe_ge_20", ROE >= 0.20),
                    ("share_roe_ge_60", ROE >= 0.60)):
        out[k] = _share(cond)
    return out


def _r_x029(st: _State) -> dict:
    rid, ctx = "X-029", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        N = len(picks)
        for arm in _arms_all(ctx, pool):
            ok = XC.money_allowed(ctx, pool, arm)
            recs = [st.rec(p, arm) for p in picks]
            rs = _cat([r["reason"] for r in recs], np.int64)
            lev = _cat([r["lev"] for r in recs]) if ok else None
            n = len(rs)
            wins_ = int(sum(int(r["win"].sum()) for r in recs))
            counts = OrderedDict([("n", n), ("wins", wins_), ("win_share", wins_ / n if n else None), ("share_sl", _share(rs == KX.R_SL) if n else None),
                                  ("share_lock", _share(rs == KX.R_LOCK) if n else None), ("flag", _thin(n))])
            tiers = OrderedDict()
            for t in (TIERS if ok else ()):
                m = np.round(lev) == t
                k, kl = int(m.sum()), int((m & (rs == KX.R_LIQ)).sum())
                tiers[str(t)] = OrderedDict([("n", k), ("share", k / n if n else None), ("n_liq", kl), ("share_liq", kl / k if k else None),
                                             ("flag", _thin(k))])
            priv = None                                   # leverage tiers are money class (C8): E0 and choosable rows only
            if ok and pool == "core":
                counts["by_tier"] = tiers
            elif ok:
                priv = {"by_tier": tiers}
            money = None
            if ok:
                R, ROE = _cat([r["R"] for r in recs]), _cat([r["ROE"] for r in recs])
                win = _cat([r["win"] for r in recs], bool)
                money = _shape_money(R, ROE, win)
                money["by_tier"] = OrderedDict((str(t), _shape_money(R[np.round(lev) == t], ROE[np.round(lev) == t], win[np.round(lev) == t]))
                                               for t in TIERS)
                aw, al = _mean(R[win]), _mean(R[~win])
                payoff = (aw / abs(al)) if aw is not None and al not in (None, 0.0) else None
                sw, sl_ = float(R[win].sum()), float(R[~win].sum())
                ws = float(win.mean()) if n else None
                be = 1.0 / (1.0 + payoff) if payoff is not None else None
                money.update(avg_win_R=aw, avg_loss_R=al, payoff=payoff, profit_factor=(sw / abs(sl_) if sl_ != 0 and win.any() else None),
                             breakeven_win_share=be, edge_pp=(100.0 * (ws - be) if be is not None and ws is not None else None),
                             expectancy_R=_mean(R), R_per_month=float(np.mean([float(r["R"].sum()) / XC.N_MONTHS for r in recs])) if N else None,
                             thin_win=bool(int(win.sum()) < 20), thin_loss=bool(int((~win).sum()) < 20),
                             x_live_q=_qs(_cat([st.c4(p, arm, XC.SIZE_LIVE)["ret"] for p in picks]), QS7),
                             busts=int(sum(_bust(st.acc_money(p, arm)["w_end"]) for p in picks)), n_picks=N)
            _put(st, res, pool, arm, counts, money, priv)
    return res


# ====================================================================================================== X-033 hold tails and years
def _hold_tail(hold: np.ndarray) -> OrderedDict:
    n = len(hold)
    return OrderedDict([("n", n), ("hold_p10", float(np.percentile(hold, 10)) if n else None),
                        ("hold_share_gt24", _share(hold > 24.0)), ("hold_share_gt72", _share(hold > 72.0)),
                        ("hold_longest", float(hold.max()) if n else None), ("flag", _thin(n))])


def _r_x033(st: _State) -> dict:
    rid, ctx = "X-033", st.ctx
    res = _new(rid)
    names = [st.short(c) for c in range(len(st.syms))]
    for pool in XC.POOLS:
        picks = st.picks(pool)
        e0 = [st.tk(p, "E0") for p in picks]
        e0_y = {y: _cat([r["hold_h"][_year_of(r["exit_ts"]) == y] for r in e0]) for y in YEARS}
        for arm in _arms_all(ctx, pool):
            recs = [st.tk(p, arm) for p in picks]
            hold = _cat([r["hold_h"] for r in recs])
            win = _cat([r["win"] for r in recs], bool)
            rs = _cat([r["reason"] for r in recs], np.int64)
            c = _hold_tail(hold)
            c["hold_median"] = _median(hold)
            row = _select_row(ctx, pool, arm)
            if row is not None and isinstance(row.get("hold"), dict) and row["hold"].get("p90") is not None:
                c["hold_p90"], c["label_p90"] = float(row["hold"]["p90"]), "select.json과 같음"
            else:
                c["hold_p90"], c["label_p90"] = (float(np.percentile(hold, 90)) if len(hold) else None), "다시 계산(select.json 값 없음)"
            c["hold_median_win"], c["hold_median_rest"] = _median(hold[win]), _median(hold[~win])
            for key, codes, _ko in EXIT_CLASSES:
                c["hold_median_" + key] = _median(hold[np.isin(rs, codes)])
            by_year = OrderedDict()
            ent_ge = shorter = 0
            for y in YEARS:
                hy = _cat([r["hold_h"][_year_of(r["exit_ts"]) == y] for r in recs])
                med, med0 = _median(hy), _median(e0_y[y])
                by_year[str(y)] = OrderedDict([("n", len(hy)), ("hold_median", med), ("entered", len(hy)), ("entered_e0", len(e0_y[y])),
                                               ("hold_median_e0", med0), ("flag", _thin(len(hy)))])
                ent_ge += int(len(hy) >= len(e0_y[y]))
                shorter += int(med is not None and med0 is not None and med < med0)
            c["by_year"] = by_year
            c["label_entered_years"] = f"E0 이상 진입 {ent_ge}/3해"
            c["label_shorter_years"] = f"더 짧은 해 {shorter}/3해"
            coins = [np.asarray(r["coin"], np.int64) for r in recs]
            c["by_coin"] = OrderedDict((names[k], _hold_tail(_cat([r["hold_h"][cc == k] for r, cc in zip(recs, coins)])))
                                       for k in range(len(names)))
            _put(st, res, pool, arm, c)
    return res


# ====================================================================================================== X-015 30-day windows, half / bust touches
def _windows(acc: dict, H: int, edges) -> tuple:
    """Windows (D_j, D_j + H days], D_j = each UTC midnight from 2021-01-01 with D_j + H <= 2024-01-01; those starting in a dead month
    (C6) are left out. Returns (D, R, P, half, bust): R = W(D + H) / W(D), P = max(1, max over exits in the window of W(t) / W(D)), half =
    a realised wallet at an exit in the window <= W(D) / 2, bust = an exit in the window leaves W < $10. W(t) = w0 + the P&L of the
    trades with tr_exit <= t (realised wallet)."""
    J = int((HI_MS - LO_MS) // DAY_MS - H) + 1
    D = LO_MS + np.arange(J, dtype=np.int64) * DAY_MS
    ex, pnl, w0 = acc["tr_exit"].astype(np.int64), acc["tr_pnl"].astype(float), float(acc["w0"])
    cum = np.r_[w0, w0 + np.cumsum(pnl)]
    k0 = np.searchsorted(ex, D, side="right")
    k1 = np.searchsorted(ex, D + H * DAY_MS, side="right")
    W0 = np.maximum(cum[k0], LOG_TINY)
    R = cum[k1] / W0
    mx = _seg_reduce(cum[1:], k0, k1, "max", np.nan)
    mn = _seg_reduce(cum[1:], k0, k1, "min", np.nan)
    P = np.where(np.isfinite(mx), np.maximum(1.0, mx / W0), 1.0)
    half = np.isfinite(mn) & (mn <= 0.5 * W0)
    bust = np.isfinite(mn) & (mn < XC.BUST_W)
    keep = XC.alive_months(acc)[XC.month_index(D, edges)]
    return D[keep], R[keep], P[keep], half[keep], bust[keep]


def _hits(D: np.ndarray, hit: np.ndarray) -> OrderedDict:
    """k/n of a share, the number of distinct start months holding a hit, and the largest single month's share of the hits."""
    k, n = int(hit.sum()), int(len(hit))
    months = [_month_of(t) for t in D[hit]]
    top = (max(months.count(m) for m in set(months)) / k) if k else None
    return OrderedDict([("k", k), ("n", n), ("share", k / n if n else None), ("n_months", len(set(months))), ("top_month_share", top)])


def _r_x015(st: _State) -> dict:
    rid, ctx = "X-015", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        for arm in _arms_money(ctx, pool):
            m = OrderedDict()
            accs = {s: [st.acc_money(p, arm, s) for p in picks] for s in RX.SIZE_TAG}
            n_tr = int(sum(len(a["tr_pnl"]) for a in accs[XC.SIZE_Q]))
            parts = [_windows(a, 30, ctx.edges) for a in accs[XC.SIZE_Q]]
            D, R, P = _cat([x[0] for x in parts], np.int64), _cat([x[1] for x in parts]), _cat([x[2] for x in parts])
            m["n_pairs"], m["flag"] = int(len(R)), _thin(min(n_tr, len(R)))
            m["R_q"] = _qs(R, (5, 10, 25, 50, 75, 90, 95))
            for key, cond in (("ge_1_1", R >= 1.1), ("ge_1_5", R >= 1.5), ("ge_2", R >= 2), ("ge_5", R >= 5), ("lt_1", R < 1),
                              ("lt_0_5", R < 0.5), ("touch_2", P >= 2), ("touch_5", P >= 5), ("touch_10", P >= 10)):
                m[key] = _hits(D, cond)
            if len(R):
                iw, ib = int(np.argmin(R)), int(np.argmax(R))
                m["worst"], m["worst_start"], m["best"], m["best_start"] = float(R[iw]), _date(D[iw]), float(R[ib]), _date(D[ib])
            touch = OrderedDict()
            for s, tag in RX.SIZE_TAG.items():
                for H in WINDOW_DAYS:
                    w = [_windows(a, H, ctx.edges) for a in accs[s]]
                    half, bust = _cat([x[3] for x in w], bool), _cat([x[4] for x in w], bool)
                    touch[f"{tag}_{H}"] = OrderedDict([("n", int(len(half))), ("half", _share(half)), ("bust", _share(bust))])
                touch[f"{tag}_busts"] = int(sum(_bust(a["w_end"]) for a in accs[s]))
            m["touch"], m["n_picks"] = touch, len(picks)
            _put(st, res, pool, arm, None, m)
    return res


# ====================================================================================================== X-016 what the goal needs
def _ceiling_count(st: _State, p: dict, size=XC.SIZE_Q, q15=False) -> int:
    """X-025 (f): the most entries any bar-close rule can make on the pick: walk the offered list; count a signal that is sizeable at
    E0's realised wallet and fills after busy-until; then busy-until = (ts of the minute kernel._entry_index(ts, C0 + tf), at least e + 1)
    - 1 ms (the period's end when beyond the data). ``q15``: C0 + 15 min."""
    ctx, mk = st.ctx, st.ctx.market
    off = st.off(p)
    acc = XC.account(ctx, p, "E0", size)
    n = len(off["coin"])
    if not n:
        return 0
    W = _wallet_before(acc, off["fill"])
    ok = _sizeable(mk, mk.S(size), off, np.arange(n), W, KX.exit_of_pick(p, KX.E0)[0])
    step = 900_000 if q15 else DX.TF_MS[p["tf"]]
    pend = mk.period_end("select")
    tsp = [mk.cat["ts"][mk.starts[c]:pend[c]] for c in range(len(mk.symbols))]
    busy, count = -1, 0
    for q in range(n):
        f = int(off["fill"][q])
        if f <= busy or not ok[q]:
            continue
        count += 1
        t = tsp[int(off["coin"][q])]
        e = int(np.searchsorted(t, f))
        j = int(np.searchsorted(t, int(off["close"][q]) + step - 60_000)) + 1
        busy = 2 ** 62 if j >= len(t) else int(t[max(j, e + 1)]) - 1 if max(j, e + 1) < len(t) else 2 ** 62
    return count


def _goal_rows(w, a, b, nrate, ceiling) -> list:
    rows = []
    for T, lab in TARGETS:
        g = math.log(T)
        row = OrderedDict([("target", lab)])
        if None in (w, a, b) or not nrate or a == b:
            row.update(win_share_need=None, label_win="-", entries_need=None, label_entries="-", typical_win_need=None)
        else:
            pn = (g / nrate - b) / (a - b)
            row["win_share_need"] = pn
            row["label_win"] = "불가능" if pn > 1 else ("이미 넘음" if pn < 0 else "")
            L = w * a + (1 - w) * b
            if L > 0:
                row["entries_need"] = g / L
                row["label_entries"] = "신호가 모자람" if (ceiling is not None and g / L > ceiling) else ""
            else:
                row["entries_need"], row["label_entries"] = None, "불가능: 거래당 평균이 0 이하"
            row["typical_win_need"] = math.expm1((g / nrate - (1 - w) * b) / w) if w > 0 else None
        rows.append(row)
    return rows


def _months_to(m) -> OrderedDict:
    if m is None or not m > 1:
        return OrderedDict([("x5", "도달 안 함"), ("x100", "도달 안 함")])
    return OrderedDict([("x5", int(math.ceil(math.log(5) / math.log(m)))), ("x100", int(math.ceil(math.log(100) / math.log(m))))])


def _r_x016(st: _State) -> dict:
    rid, ctx = "X-016", st.ctx
    res = _new(rid)
    res["constants"] = [OrderedDict([("months", N), ("x5_per_month", 5 ** (1 / N)), ("x100_per_month", 100 ** (1 / N))]) for N in GOAL_N]
    for pool in XC.POOLS:
        picks = st.picks(pool)
        N = len(picks)
        ceil_n = sum(_ceiling_count(st, p) for p in picks)
        ceiling = ceil_n / (N * XC.N_MONTHS) if N else None
        (res["core"] if pool == "core" else res["private"]["ds"])["entries_ceiling_per_account_month"] = ceiling
        for arm in _arms_money(ctx, pool):
            accs = [st.acc_money(p, arm) for p in picks]
            x = _cat([a["ret"] for a in accs])
            win = _cat([a["win"] for a in accs], bool)
            ent = int(sum(MT.count(a, "entered") for a in accs))
            nrate = ent / (N * XC.N_MONTHS) if N else None
            n = len(x)
            w = float(win.mean()) if n else None
            counts = OrderedDict([("n", n), ("entered", ent), ("n_entries_per_account_month", nrate), ("win_share", w), ("flag", _thin(n))])
            lg = np.log(np.maximum(1.0 + x, LOG_TINY))
            a, b = _mean(lg[win]), _mean(lg[~win])
            thin_ab = int(win.sum()) < XC.THIN_MIN or int((~win).sum()) < XC.THIN_MIN
            L = (w * a + (1 - w) * b) if None not in (w, a, b) else None
            alive_g = _cat([a_["g"][XC.alive_months(a_)] for a_ in accs])
            m_med = float(np.median(np.exp(alive_g))) if len(alive_g) else None
            m_geo = float(math.exp(alive_g.mean())) if len(alive_g) else None
            money = OrderedDict([("a", a), ("b", b), ("typical_win", math.expm1(a) if a is not None else None),
                                 ("typical_loss", math.expm1(b) if b is not None else None), ("L", L),
                                 ("model_month_log", (nrate * L) if L is not None and nrate else None), ("actual_month_log", st.L(pool, arm)),
                                 ("ceiling_all_wins", math.exp(nrate * a) if a is not None and nrate else None), ("thin_ab", bool(thin_ab)),
                                 ("targets", _goal_rows(w, a, b, nrate, ceiling)), ("m_med", m_med), ("m_geo", m_geo),
                                 ("months_med", _months_to(m_med)), ("months_geo", _months_to(m_geo))])
            _put(st, res, pool, arm, counts, money)
    return res


# ====================================================================================================== X-018 endurance
def _underwater(t: np.ndarray, v: np.ndarray, end_ms: int) -> tuple:
    """The longest stretch of v below its running peak: (days, start ms, end ms or None when still open at the period end)."""
    peak = np.maximum.accumulate(v)
    under = v < peak - 1e-15
    best = (0.0, None, None)
    i, n = 0, len(v)
    while i < n:
        if not under[i]:
            i += 1
            continue
        j = i
        while j < n and under[j]:
            j += 1
        stop = int(t[j]) if j < n else end_ms
        days = (stop - int(t[i])) / DAY_MS
        if days > best[0]:
            best = (days, int(t[i]), int(t[j]) if j < n else None)
        i = j
    return best


def _basket(accs: list, edges) -> OrderedDict:
    """B(t) = mean over the accounts of W_a(t) / w0 at every exit time of any account (separate wallets; a dead account stays at its
    last wallet): max drawdown with peak, trough and recovery dates, the longest stretch under a previous peak, final B, worst month and
    the months in which B fell."""
    times = np.unique(_cat([a["tr_exit"] for a in accs], np.int64))
    vals = np.ones((len(accs), len(times)))
    for i, a in enumerate(accs):
        cum = float(a["w0"]) + np.cumsum(a["tr_pnl"].astype(float))
        k = np.searchsorted(a["tr_exit"].astype(np.int64), times, side="right")
        vals[i] = np.where(k > 0, cum[np.maximum(k - 1, 0)] if len(cum) else float(a["w0"]), float(a["w0"])) / float(a["w0"])
    t = np.r_[np.int64(LO_MS), times]
    B = np.r_[1.0, vals.mean(axis=0)]
    peak = np.maximum.accumulate(B)
    dd = 1.0 - B / peak
    itr = int(np.argmax(dd))
    out = OrderedDict([("max_dd", float(dd[itr]))])
    if dd[itr] > 0:
        ipk = int(np.flatnonzero(B[:itr + 1] >= peak[itr])[-1])
        rec = np.flatnonzero(B[itr:] >= peak[itr])
        out.update(peak_date=_date(t[ipk]), trough_date=_date(t[itr]), recovery_date=(_date(t[itr + int(rec[0])]) if len(rec) else "미회복"))
    days, s, e = _underwater(t, B, HI_MS)
    out.update(under_days=days, under_start=(_date(s) if s is not None else None), under_end=(_date(e) if e is not None else ("진행 중" if s else None)),
               final=float(B[-1]))
    idx = np.searchsorted(t, edges[1:], side="left") - 1
    Bm = B[idx]
    prev = np.r_[1.0, Bm[:-1]]
    ch = Bm / prev - 1.0
    iw = int(np.argmin(ch))
    out.update(worst_month=_month_of(edges[iw]), worst_month_change=float(ch[iw]), months_fell=int((Bm < prev).sum()), n_months=len(Bm))
    return out


def _single(accs: list) -> OrderedDict:
    dd = np.array([float(a["max_dd"]) for a in accs])
    uw = []
    for a in accs:
        cum = np.r_[float(a["w0"]), float(a["w0"]) + np.cumsum(a["tr_pnl"].astype(float))]
        t = np.r_[np.int64(LO_MS), a["tr_exit"].astype(np.int64)]
        uw.append(_underwater(t, cum, HI_MS)[0])
    uw = np.asarray(uw)
    return OrderedDict([("max_dd_p50", _median(dd)), ("max_dd_p90", float(np.percentile(dd, 90)) if len(dd) else None),
                        ("max_dd_max", float(dd.max()) if len(dd) else None), ("under_days_p50", _median(uw)),
                        ("under_days_p90", float(np.percentile(uw, 90)) if len(uw) else None), ("under_days_max", float(uw.max()) if len(uw) else None),
                        ("busts", int(sum(_bust(a["w_end"]) for a in accs))), ("n_picks", len(accs))])


def _streaks(accs: list) -> OrderedDict:
    longest, ratio, in5, n_all, runs8 = [], [], 0, 0, 0
    for a in accs:
        loss = a["tr_pnl"].astype(float) <= 0
        runs = _runs(loss)
        n = len(loss)
        n_all += n
        lg = int(runs.max()) if len(runs) else 0
        longest.append(lg)
        in5 += int(runs[runs >= 5].sum())
        runs8 += int((runs >= 8).sum())
        q = float(loss.mean()) if n else 1.0
        if 0 < q < 1 and n * (1 - q) > 1:
            lexp = math.log(n * (1 - q)) / math.log(1 / q)
            if lexp > 0:
                ratio.append(lg / lexp)
    return OrderedDict([("longest_p50", _median(longest)), ("longest_max", int(max(longest)) if longest else None),
                        ("share_in_runs_ge5", in5 / n_all if n_all else None), ("runs_ge8", runs8),
                        ("ratio_to_expected_p50", _median(ratio)), ("n_ratio", len(ratio)), ("n_trades", n_all), ("flag", _thin(n_all))])


def _together(accs: list) -> OrderedDict:
    G = np.array([np.asarray(a["g"], float) for a in accs])
    N = len(accs)
    rhos = []
    for i in range(N):
        for j in range(i + 1, N):
            if np.std(G[i]) > 0 and np.std(G[j]) > 0:
                rhos.append(float(np.corrcoef(G[i], G[j])[0, 1]))
    rho = _mean(rhos)
    neff = (N / (1 + (N - 1) * rho)) if rho is not None and N > 1 and (1 + (N - 1) * rho) > 0 else None
    return OrderedDict([("rho_mean", rho), ("n_pairs", len(rhos)), ("n_eff", neff),
                        ("flag_rho", bool(rho is not None and N > 1 and rho <= -1.0 / (N - 1)))])


def _r_x018(st: _State) -> dict:
    rid, ctx = "X-018", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        sel_e0 = (_select_row(ctx, pool, "E0") or {}).get("max_dd_median")
        for arm in _arms_money(ctx, pool):
            m = OrderedDict()
            for s, tag in RX.SIZE_TAG.items():
                accs = [st.acc_money(p, arm, s) for p in picks]
                part = OrderedDict()
                part["basket"] = _basket(accs, ctx.edges) if len(accs) >= BASKET_MIN else None
                part["single"] = _single(accs)
                part["streaks"] = _streaks(accs)
                part["together"] = _together(accs)
                m[tag] = part
            if arm == "E0":
                m["e0_max_dd_median_select"] = sel_e0
                m["label_e0_max_dd"] = "select.json과 같음" if sel_e0 is not None else "다시 계산(select.json 값 없음)"
            _put(st, res, pool, arm, None, m)
    res["notes"].append("closed-trade (realised) wallets only; open-position swings are in X-019")
    return res


# ====================================================================================================== X-021 positions open at once
def _grid() -> np.ndarray:
    return LO_MS + np.arange((HI_MS - LO_MS) // GRID_MS, dtype=np.int64) * GRID_MS


def _open_at(rec: dict, grid: np.ndarray) -> tuple:
    """(point mask, trade index) of the grid points at which the account holds a position: tr_fill <= t_g < tr_exit."""
    if not len(rec["fill_ts"]):
        return np.zeros(len(grid), bool), np.zeros(len(grid), np.int64)
    idx = np.searchsorted(rec["fill_ts"], grid, side="right") - 1
    ok = idx >= 0
    ok[ok] = grid[ok] < rec["exit_ts"][idx[ok]]
    return ok, np.maximum(idx, 0)


def _concurrency(st: _State, recs: list, grid: np.ndarray) -> OrderedDict:
    ns = len(st.syms)
    cnt = np.zeros((len(grid), 2 * ns), np.int32)
    for r in recs:
        ok, idx = _open_at(r, grid)
        if ok.any():
            code = 2 * np.asarray(r["coin"], np.int64)[idx[ok]] + (np.asarray(r["side"])[idx[ok]] > 0).astype(np.int64)
            np.add.at(cnt, (np.flatnonzero(ok), code), 1)
    m = cnt.sum(axis=1)
    pos = m >= 1
    out = OrderedDict([("n_points", int(len(grid))), ("share_open_ge1", _share(pos)), ("n_open_mean", float(m.mean())),
                       ("n_open_p90", float(np.percentile(m, 90))), ("n_open_max", int(m.max()) if len(m) else 0)])
    for k in (3, 5, 10):
        out[f"share_open_ge{k}"] = _share(m >= k)
    if pos.any():
        out["share_pairs_mean"] = float(((cnt[pos] > 0).sum(axis=1) / m[pos]).mean())
        out["share_top_group_mean"] = float((cnt[pos].max(axis=1) / m[pos]).mean())
    else:
        out["share_pairs_mean"] = out["share_top_group_mean"] = None
    by = OrderedDict()
    for c in range(ns):
        on = cnt[:, 2 * c] + cnt[:, 2 * c + 1]
        inm = on >= 1
        by[st.short(c)] = OrderedDict([("n_points", int(inm.sum())), ("share_two_plus", _share(on[inm] >= 2) if inm.any() else None),
                                       ("flag", _thin(int(inm.sum())))])
    out["by_coin"] = by
    top = cnt.max(axis=1) if len(grid) else np.zeros(0)
    mx = int(top.max()) if len(top) else 0
    out["n_max_same"] = mx
    out["label_max_same_date"] = _date(grid[int(np.argmax(top == mx))]) if mx > 0 else "-"
    return out


def _r_x021(st: _State) -> dict:
    rid, ctx = "X-021", st.ctx
    res = _new(rid)
    grid = _grid()
    for pool in XC.POOLS:
        picks = st.picks(pool)
        for arm in _arms_all(ctx, pool):
            ok = XC.money_allowed(ctx, pool, arm)
            counts = _concurrency(st, [st.tk(p, arm, XC.SIZE_Q) for p in picks], grid)
            counts["counts_live"] = _concurrency(st, [st.tk(p, arm, XC.SIZE_LIVE) for p in picks], grid)
            money = None
            if ok:
                mm = np.zeros(len(grid))
                for p in picks:
                    f = st.c4(p, arm, XC.SIZE_LIVE)
                    o, idx = _open_at(f, grid)
                    mm[o] += (f["margin"] / f["Wb"])[idx[o]]
                money = OrderedDict([("margin_p50", float(np.percentile(mm, 50))), ("margin_p90", float(np.percentile(mm, 90))),
                                     ("margin_max", float(mm.max())), ("share_over_100", _share(mm > 1.0)),
                                     ("busts_live", int(sum(_bust(st.acc_money(p, arm, XC.SIZE_LIVE)["w_end"]) for p in picks))),
                                     ("n_picks", len(picks))])
            _put(st, res, pool, arm, counts, money)
    return res


# ====================================================================================================== X-026 missed signals
def _qual(r: np.ndarray, hold: np.ndarray) -> OrderedDict:
    lg = np.log(np.maximum(1.0 + np.asarray(r, float), LOG_TINY))
    n = len(lg)
    return OrderedDict([("n", n), ("win_share", _share(np.asarray(r) > 0) if n else None), ("mean_log", _mean(lg)),
                        ("hold_median", _median(hold)), ("flag", _thin(n))])


def _r_x026(st: _State) -> dict:
    rid, ctx = "X-026", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        for arm in _arms_money(ctx, pool):
            ex = [st.extra[("X-026", p["id"], arm)] for p in picks]
            accs = [st.acc_money(p, arm) for p in picks]
            missed = _qual(_cat([e["r"] for e in ex]), _cat([e["hold_h"] for e in ex]))
            entered = _qual(_cat([a["ret"] for a in accs]), _cat([a["hold_h"] for a in accs]))
            m = OrderedDict([("missed", missed), ("entered", entered),
                             ("diff_mean_log", (missed["mean_log"] - entered["mean_log"]) if None not in (missed["mean_log"], entered["mean_log"]) else None),
                             ("n_skipped", int(sum(int(e["n_skipped"]) for e in ex))), ("n_sizeable", int(sum(int(e["n_sizeable"]) for e in ex)))])
            _put(st, res, pool, arm, None, m)
    res["notes"].append("standalone trades overlap the trade that was open: the quality of what was missed, not an achievable account")
    return res


# ====================================================================================================== X-030 excursions, X-031 giveback
def _exc_cell(f: dict, S) -> OrderedDict:
    bR, wR, bO, wO = f["best_R"], f["worst_R"], f["best_ROE"], f["worst_ROE"]
    R, ROE, rs, win = f["R"], f["ROE"], f["reason"], f["win"]
    n = len(R)
    out = OrderedDict([("n", n), ("flag", _thin(n))])
    for k in (1, 2, 3):
        out[f"reach_{k}R"] = _share(bR >= k)
    for k in (12, 17, 22, 60):
        out[f"touch_roe_{k}"] = _share(bO >= k / 100.0)
    sl = rs == KX.R_SL
    out["n_sl"], out["sl_reach_1R"], out["sl_reach_2R"] = int(sl.sum()), _share(bR[sl] >= 1), _share(bR[sl] >= 2)
    out["n_win"], out["win_dip_0_5"], out["win_dip_0_75"], out["win_worst_R_median"] = (int(win.sum()), _share(wR[win] <= -0.5),
                                                                                         _share(wR[win] <= -0.75), _median(wR[win]))
    t12 = bO >= 0.12
    with np.errstate(invalid="ignore", divide="ignore"):
        out["n_touch12"], out["touch12_closed_ge10"], out["touch12_closed_loss"] = int(t12.sum()), _share(ROE[t12] >= 0.10), _share(R[t12] < 0)
        out["touch12_roe_ratio_median"] = _median(ROE[t12] / bO[t12])
    d40 = wO <= -0.40
    out["n_dip40"], out["dip40_closed_pos"], out["dip40_closed_sl"], out["dip40_roe_median"] = (int(d40.sum()), _share(ROE[d40] > 0),
                                                                                                 _share(rs[d40] == KX.R_SL), _median(ROE[d40]))
    d12 = (0.12 / f["lev"] + S[5]) * f["fill"] / f["atr"]
    out["d12_q"] = _qs(d12, (10, 50, 90))
    out["d12_lt_1"], out["d12_lt_0_5"] = _share(d12 < 1), _share(d12 < 0.5)
    return out


def _frame_cat(frames: list) -> dict:
    keys = ("best_R", "worst_R", "best_ROE", "worst_ROE", "R", "ROE", "reason", "win", "lev", "fill", "atr", "l")
    return {k: _cat([f[k] for f in frames], bool if k == "win" else (np.int64 if k == "reason" else float)) for k in keys}


def _sub(f: dict, m: np.ndarray) -> dict:
    return {k: v[m] for k, v in f.items()}


def _r_x030(st: _State) -> dict:
    rid, ctx = "X-030", st.ctx
    res = _new(rid)
    S = ctx.market.S(XC.SIZE_Q)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        for arm in _arms_money(ctx, pool):
            frames = [st.c4(p, arm) for p in picks]
            allf = _frame_cat(frames)
            m = OrderedDict([("all", _exc_cell(allf, S))])
            lev = np.round(allf["lev"])
            m["by_tier"] = OrderedDict((str(t), _exc_cell(_sub(allf, lev == t), S)) for t in TIERS)
            m["by_bar"] = OrderedDict((g, _exc_cell(_frame_cat([f for f in frames if f["tf"] in tfs]), S)) for g, tfs, _ko in BAR_GROUPS)
            _put(st, res, pool, arm, None, m)
    return res


def _give(f: dict) -> OrderedDict:
    pop = f["best_R"] >= 1
    bR, R = f["best_R"][pop], f["R"][pop]
    n = int(pop.sum())
    gb = (bR - R) / bR if n else np.zeros(0)
    return OrderedDict([("n", n), ("giveback_median", _median(gb)), ("share_ge_half", _share(gb >= 0.5) if n else None),
                        ("share_gave_all", _share(R <= 0) if n else None), ("capture", float(R.sum() / bR.sum()) if n and bR.sum() > 0 else None),
                        ("flag", _thin(n))])


def _r_x031(st: _State) -> dict:
    rid, ctx = "X-031", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        for arm in _arms_money(ctx, pool):
            f = _frame_cat([st.c4(p, arm) for p in st.picks(pool)])
            m = OrderedDict([("all", _give(f))])
            m["by_class"] = OrderedDict((key, _give(_sub(f, np.isin(f["reason"], codes)))) for key, codes, _ko in EXIT_CLASSES)
            _put(st, res, pool, arm, None, m)
    return res


# ====================================================================================================== X-034 cost ledger
def _cost_parts(st: _State, f: dict) -> dict:
    """X-034 per closed trade: fee_in, fee_out, slip, fund (positive = paid), settlements crossed; the identity move = side qty (X -
    raw) is asserted to 1e-9 x notional on every non-LIQ trade."""
    mk = st.ctx.market
    if "mofund" not in st.extra:
        st.extra["mofund"] = np.asarray(mk.cat["mo"], float) * np.asarray(mk.cat["fund"], float)
        st.extra["fundnz"] = (np.asarray(mk.cat["fund"], float) != 0).astype(float)
    S, side, qty, fill, raw, xpx, rs = f["S"], f["side"], f["qty"], f["fill"], f["raw"], f["xpx"], f["reason"]
    tp, liq = rs == KX.R_TP, rs == KX.R_LIQ
    mkt = np.isin(rs, (KX.R_SL, KX.R_LOCK, KX.R_RULE, KX.R_END))
    fee_in = qty * fill * S[0]
    fee_out = np.where(liq, 0.0, qty * xpx * np.where(tp, S[19], S[0]))
    X = np.where(mkt, xpx / (1 - side * S[1]), xpx)
    slip = qty * raw * S[1] + np.where(mkt, qty * X * S[1], 0.0)
    fund = side * qty * _seg_reduce(st.extra["mofund"], f["e"] + 1, f["x"] + 1, "sum", 0.0)
    nset = _seg_reduce(st.extra["fundnz"], f["e"] + 1, f["x"] + 1, "sum", 0.0)
    move = f["pnl"] + fee_in + fee_out + slip + fund
    bad = ~liq & (np.abs(move - side * qty * (X - raw)) > 1e-9 * qty * fill)
    if bad.any():
        raise AssertionError(f"X-034 {f['pick']} {f['arm']}: the cost identity fails on {int(bad.sum())} trades")
    return {"fee_in": fee_in, "fee_out": fee_out, "slip": slip, "fund": fund, "nset": nset}


def _cost_size(st: _State, pool: str, arm: str, size: float) -> tuple:
    picks = st.picks(pool)
    N = len(picks)
    frames = [st.c4(p, arm, size) for p in picks]
    parts = [_cost_parts(st, f) for f in frames]
    cost_m, fund_m = [], []
    for p, f, c in zip(picks, frames, parts):
        acc = st.acc_money(p, arm, size)
        mi = XC.month_index(f["exit_ts"], st.ctx.edges)
        cm = np.bincount(mi, (c["fee_in"] + c["fee_out"] + c["slip"]) / f["Wb"], minlength=XC.N_MONTHS)[:XC.N_MONTHS]
        fm = np.bincount(mi, c["fund"] / f["Wb"], minlength=XC.N_MONTHS)[:XC.N_MONTHS]
        alive = XC.alive_months(acc)
        cost_m.append(cm[alive])
        fund_m.append(fm[alive])
    cat = {k: _cat([c[k] for c in parts]) for k in ("fee_in", "fee_out", "slip", "fund", "nset")}
    fr = {k: _cat([f[k] for f in frames], bool if k == "win" else (np.int64 if k == "reason" else float))
          for k in ("R", "ROE", "qty", "Rd", "margin", "Wb", "fill", "hold_h", "win", "l", "side", "reason")}
    n = len(fr["R"])
    cost = cat["fee_in"] + cat["fee_out"] + cat["slip"]
    hb = OrderedDict()
    hb_money = OrderedDict()
    sums = []
    for i, (lo, hi) in enumerate(HOLD_BUCKETS):
        m = (fr["hold_h"] >= lo) & (fr["hold_h"] < hi)
        k = int(m.sum())
        hb[str(i)] = OrderedDict([("n", k), ("wins", int(fr["win"][m].sum())), ("win_share", (int(fr["win"][m].sum()) / k) if k else None),
                                  ("flag", _thin(k))])
        sums.append(XC.c9_contrib([float(f["l"][(f["hold_h"] >= lo) & (f["hold_h"] < hi)].sum()) for f in frames]) if N else 0.0)
        hb_money[str(i)] = OrderedDict([("ROE_mean", _mean(fr["ROE"][m])), ("fund_roe", _mean(cat["fund"][m] / fr["margin"][m])),
                                        ("cost_roe", _mean(cost[m] / fr["margin"][m])), ("c", sums[-1])])
    sh = _c17(sums, sum(sums))
    for i, k in enumerate(hb_money):
        hb_money[k]["share"] = None if sh is None else sh[i]
    sides, sides_money = OrderedDict(), OrderedDict()
    for lab, sgn in (("long", 1), ("short", -1)):
        m = fr["side"] == sgn
        k = int(m.sum())
        sides[lab] = OrderedDict([("n", k), ("n_settlements_per_trade", _mean(cat["nset"][m]))])
        sides_money[lab] = OrderedDict([("share_receive", _share(cat["fund"][m] < 0) if k else None),
                                        ("fund_pct_notional", _mean(100.0 * cat["fund"][m] / (fr["qty"][m] * fr["fill"][m])))])
    counts = OrderedDict([("n", n), ("n_round_trips_per_account_month", n / (N * XC.N_MONTHS) if N else None), ("by_hold", hb),
                          ("by_side", sides), ("flag", _thin(n))])
    qR = fr["qty"] * fr["Rd"]
    costR, fundR = cost / qR, cat["fund"] / qR
    gross = fr["R"] + costR + fundR
    mg, mc, mf = _mean(gross), _mean(costR), _mean(fundR)
    money = OrderedDict([("cost_month_pct", _mean(100.0 * _cat(cost_m))), ("fund_month_pct", _mean(100.0 * _cat(fund_m))),
                         ("cost_per_trip_pct", _mean(100.0 * cost / fr["Wb"])), ("costR_mean", mc), ("fundR_mean", mf), ("gross_R_mean", mg),
                         ("cost_share_of_gross", (mc / mg) if mg is not None and mg > 0 and mc is not None else None),
                         ("c_star", ((mg - mf) / mc) if None not in (mg, mf, mc) and mc > 0 else None), ("by_hold", hb_money),
                         ("by_side", sides_money)])
    return counts, money


def _r_x034(st: _State) -> dict:
    rid, ctx = "X-034", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        for arm in _arms_money(ctx, pool):
            cq, mq = _cost_size(st, pool, arm, XC.SIZE_Q)
            cl, ml = _cost_size(st, pool, arm, XC.SIZE_LIVE)
            mq["live"] = ml
            if pool == "core":
                cq["counts_live"] = cl
                _put(st, res, pool, arm, cq, mq)
            else:
                _put(st, res, pool, arm, cq, mq, {"counts_live": cl})
    return res


# ====================================================================================================== X-038 the largest trades
def _top(l: np.ndarray, k: int) -> float:
    return float(np.sort(l)[-k:].sum()) if len(l) else 0.0


def _r_x038(st: _State) -> dict:
    rid, ctx = "X-038", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        N = len(picks)
        e0 = [st.acc_money(p, "E0") for p in picks]
        for arm in _arms_money(ctx, pool):
            accs = [st.acc_money(p, arm) for p in picks]
            m5, m1, pos5, thin_p, t5v, sv = [], [], 0, 0, [], []
            for a, b in zip(accs, e0):
                lv, le = np.asarray(a["l"], float), np.asarray(b["l"], float)
                m5.append(((lv.sum() - _top(lv, 5)) - (le.sum() - _top(le, 5))) / XC.N_MONTHS)
                m1.append(((lv.sum() - _top(lv, 1)) - (le.sum() - _top(le, 1))) / XC.N_MONTHS)
                t5v.append(_top(lv, 5))
                sv.append(float(lv.sum()))
                if len(lv) < 30 or len(le) < 30:
                    thin_p += 1
                elif m5[-1] > 0:
                    pos5 += 1
            M5, M1, M = float(np.mean(m5)), float(np.mean(m1)), st.M(pool, arm)
            kept = _c17([100 * M5], 100 * M) if arm != "E0" else None
            own = _c17([100 * float(np.mean(t5v)) / XC.N_MONTHS], 100 * float(np.mean(sv)) / XC.N_MONTHS)
            n_tr = int(sum(len(a["l"]) for a in accs))
            m = OrderedDict([("M5", M5), ("M1", M1), ("M", M), ("own", st.L(pool, arm)), ("picks_pos5", pos5), ("n_picks", N),
                             ("n_thin_picks", thin_p),
                             ("gain_kept", kept[0] if kept else None), ("own_top5_share", own[0] if own else None),
                             ("trades_per_account", n_tr / N if N else None),
                             ("trades_per_account_e0", sum(len(b["l"]) for b in e0) / N if N else None), ("flag", _thin(n_tr))])
            _put(st, res, pool, arm, None, m)
    return res


# ====================================================================================================== X-039 neighbours
GRIDS = {"F1": {"w": (2, 3, 5)}, "F2": {"n": (10, 20, 50)}, "F4": {"m": (1.5, 2, 3)}, "F5": {"P": (1, 1.5, 2), "g": (0.25, 0.5)},
         "F6": {"w": (2, 3, 5), "d": (0, 0.5)}, "F7": {"N": (12, 24, 48)}, "F7h": {"H": (4, 8, 16)}, "F8": {"w": (2, 3, 5), "P": (1, 2)},
         "F10": {"N": (6, 12)}}


def neighbours(v, allv: list):
    """X-039: the variants of the same family, mode and q15 flag whose parameters differ from v's in exactly one parameter by one step
    of its grid; None for a family without a grid (F3, F9, F11, F12, F13)."""
    g = GRIDS.get(v.famname)
    if g is None:
        return None
    out = []
    for u in allv:
        if u.id == v.id or u.famname != v.famname or u.mode != v.mode or bool(u.q15) != bool(v.q15):
            continue
        diff = [k for k in g if u.params.get(k) != v.params.get(k)]
        if len(diff) == 1 and abs(g[diff[0]].index(u.params[diff[0]]) - g[diff[0]].index(v.params[diff[0]])) == 1:
            out.append(u.id)
    return out


def neighbour_census(allv: list) -> dict:
    """{'none': 12, 1: 32, 2: 34, 3: 10} on the 88 variants (asserted by the read)."""
    c = {"none": 0}
    for v in allv:
        nb = neighbours(v, allv)
        if nb is None:
            c["none"] += 1
        else:
            c[len(nb)] = c.get(len(nb), 0) + 1
    return c


def _edge(v) -> bool:
    g = GRIDS.get(v.famname) or {}
    return any(v.params.get(k) in (vals[0], vals[-1]) for k, vals in g.items())


def _r_x039(st: _State) -> dict:
    rid, ctx = "X-039", st.ctx
    res = _new(rid)
    allv = list(ctx.variants)
    if len(allv) == 88 and neighbour_census(allv) != {"none": 12, 1: 32, 2: 34, 3: 10}:
        raise AssertionError("X-039: the neighbour counts differ from E.3 (12 none, 32 / 34 / 10)")
    byid = {v.id: v for v in allv}
    for pool in XC.POOLS:
        for arm in _arms_money(ctx, pool):
            if arm == "E0":
                continue
            v = byid[arm]
            nb = neighbours(v, allv)
            row = OrderedDict()
            if nb is None:
                row.update(n_neighbours=0, label="이웃 없음")
            else:
                info = OrderedDict()
                for u in nb:
                    r = _select_row(ctx, pool, u) or {}
                    g1 = ((r.get("gates") or {}).get("g1"))
                    info[u] = OrderedDict([("g1", g1 or "-"), ("label", "선택 가능" if XC.money_allowed(ctx, pool, u) else "선택 불가"),
                                           ("few", bool(r.get("closed") is not None and int(r["closed"]) < XC.THIN_MIN))])
                k = len(nb)
                n1 = sum(1 for u in nb if info[u]["g1"] == "pass")
                row.update(n_neighbours=k, n_pass_g1=n1, n_choosable=sum(1 for u in nb if info[u]["label"] == "선택 가능"),
                           flag_edge=_edge(v), by_arm=info,
                           label=("이웃 모두 통과" if n1 == k else ("이웃 모두 탈락" if n1 == 0 else "이웃 일부 탈락")))
            _put(st, res, pool, arm, row)
    res["notes"].append("only select.json's gate-1 marks and labels are read; no neighbour's growth figure is used; grids of 3 values "
                        "are a weak basis")
    return res


# ====================================================================================================== re-run reads: X-002, X-005, X-041, X-043
def _rr(st: _State, rid: str, p: dict, arm: str, part: str, scale=XC.SIZE_Q) -> dict:
    key = (rid, p["id"], arm, part, scale)
    if key not in st.rr:
        raise RuntimeError(f"{rid}: the re-run of {p['id']} {arm} {part} is missing")
    return st.rr[key]


def _Lk(d: dict) -> float:
    return _lw(d["w_end"], d["w0"]) / XC.N_MONTHS


def _r_x002(st: _State) -> dict:
    rid, ctx = "X-002", st.ctx
    res = _new(rid)
    syms = st.syms
    for pool in XC.POOLS:
        picks = st.picks(pool)
        N = len(picks)
        arms = _arms_money(ctx, pool)
        Lfull = {a: np.array([_Lk(st.acc_money(p, a)) for p in picks]) for a in arms}
        Lk = {a: {s: np.array([_Lk(_rr(st, rid, p, a, s)) for p in picks]) for s in syms} for a in arms}
        for arm in arms:
            recs = [st.c4(p, arm) for p in picks]
            m = OrderedDict()
            ck = OrderedDict()
            thin = OrderedDict()
            for c, s in enumerate(syms):
                ck[s] = XC.c9_contrib([float(r["l"][r["coin"] == c].sum()) for r in recs]) if N else 0.0
                thin[SYMS_SHORT[s]] = _thin(int(sum(int((r["coin"] == c).sum()) for r in recs)))
            m["own_full"] = float(Lfull[arm].mean()) if N else None
            m["own_without"] = OrderedDict((SYMS_SHORT[s], float(Lk[arm][s].mean()) if N else None) for s in syms)
            m["crowd"] = OrderedDict((SYMS_SHORT[s], (float(Lk[arm][s].mean() - Lfull[arm].mean()) + ck[s] / 100.0) if N else None) for s in syms)
            m["thin_by_coin"] = thin
            if arm != "E0":
                Mk = OrderedDict((SYMS_SHORT[s], float(np.mean(Lk[arm][s] - Lk["E0"][s])) if N else None) for s in syms)
                M = st.M(pool, arm)
                m.update(M=M, M_without=Mk, n_hold=sum(1 for v in Mk.values() if v is not None and v > 0), n_coins=len(syms),
                         label_one_coin=bool(M > 0 and min(v for v in Mk.values()) <= 0) if Mk else False,
                         picks_pos=OrderedDict((SYMS_SHORT[s], int((Lk[arm][s] - Lk["E0"][s] > 0).sum())) for s in syms), n_picks=N)
            _put(st, res, pool, arm, None, m)
    res["notes"].append("the mask removes trading in a coin, not its data; no coin is chosen or dropped")
    return res


def _keyset(d: dict) -> set:
    return set(zip(np.asarray(d["tr_coin"]).tolist(), np.asarray(d["tr_side"]).tolist(), np.asarray(d["tr_fill"]).astype(np.int64).tolist()))


def _r_x005(st: _State) -> dict:
    rid, ctx = "X-005", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        N = len(picks)
        for arm in _arms_money(ctx, pool):
            ent_nw = ent_full = removed = new = dropped = wins = 0
            holds, d_own, d_e0, Dm, G1, dd_nw, dd_full, b_nw, b_full, own_nw, own_full = [], [], [], [], [], [], [], 0, 0, [], []
            for p in picks:
                full = st.acc_money(p, arm)
                e0 = st.acc_money(p, "E0")
                nw = _rr(st, rid, p, arm, "noweekend")
                tk = st.tk(p, arm)
                wk = XC.is_weekend(tk["t_sig"])
                ent_nw += len(nw["tr_pnl"])
                ent_full += len(full["tr_pnl"])
                removed += int(wk.sum())
                kn, kf = _keyset(nw), _keyset(full)
                fk = list(zip(tk["coin"].tolist(), tk["side"].tolist(), tk["fill_ts"].tolist()))
                kf_weekday = {k for k, w in zip(fk, wk.tolist()) if not w}
                new += len(kn - kf)
                dropped += len(kf_weekday - kn)
                wins += int((np.asarray(nw["tr_pnl"]) > 0).sum())
                holds.append(np.asarray(nw["hold_h"], float))
                d_own.append((_lw(nw["w_end"], nw["w0"]) - _lw(full["w_end"], full["w0"])) / XC.N_MONTHS)
                d_e0.append((_lw(nw["w_end"], nw["w0"]) - _lw(e0["w_end"], e0["w0"])) / XC.N_MONTHS)
                own_nw.append(_lw(nw["w_end"], nw["w0"]) / XC.N_MONTHS)
                own_full.append(_lw(full["w_end"], full["w0"]) / XC.N_MONTHS)
                Dm.append(np.asarray(nw["g"], float) - np.asarray(full["g"], float))
                G1.append(float(np.asarray(full["l"])[wk].sum()))
                dd_nw.append(float(nw["max_dd"]))
                dd_full.append(float(full["max_dd"]))
                b_nw += int(_bust(nw["w_end"]))
                b_full += int(_bust(full["w_end"]))
            hold = _cat(holds)
            counts = OrderedDict([("entered", ent_nw), ("entered_full", ent_full), ("n_removed_weekend", removed), ("n_new", new),
                                  ("n_dropped", dropped), ("wins", wins), ("win_share", wins / ent_nw if ent_nw else None),
                                  ("hold_median", _median(hold)), ("flag", _thin(ent_nw))])
            D = np.mean(Dm, axis=0) if N else np.zeros(XC.N_MONTHS)
            lo, hi = MT.block_bootstrap_ci(D, seed=XC.seed_c11(rid, pool, arm), n_boot=N_BOOT, block=3, level=95.0)
            g1 = XC.c9_contrib(G1) if N else 0.0
            m = OrderedDict([("d_own", float(np.mean(d_own)) if N else None), ("d_vs_e0", float(np.mean(d_e0)) if N else None),
                             ("own_month_log", float(np.mean(own_nw)) if N else None),
                             ("own_full_month_log", float(np.mean(own_full)) if N else None), ("months_better", int((D > 0).sum())),
                             ("n_months", len(D)), ("interval_lo", lo), ("interval_hi", hi), ("G_weekend_full", g1),
                             ("free_slot", (100.0 * float(np.mean(d_own)) + g1) if N else None), ("max_dd_median", _median(dd_nw)),
                             ("max_dd_median_full", _median(dd_full)), ("busts", b_nw), ("busts_full", b_full), ("n_picks", N)])
            _put(st, res, pool, arm, counts, m)
    res["notes"].append("no new entries at the weekend, not flat on Friday night; rule exits still read weekend bars; 36 months make the "
                        "interval wide")
    return res


C_TAG = {0.0: "c0", 1.0: "c1", 1.5: "c15", 2.0: "c2", 3.0: "c3"}


def crossing(Mc: dict):
    """X-041: the cost multiple where M_P(V; c) turns <= 0, by linear interpolation over c = 1, 1.5, 2, 3 (those present); '1 미만' when
    M_P(V; 1) <= 0, '3 이상' when it never crosses."""
    seq = sorted(c for c in Mc if c >= 1.0)
    if Mc[1.0] <= 0:
        return "1 미만"
    for c0, c1 in zip(seq[:-1], seq[1:]):
        a0, a1 = Mc[c0], Mc[c1]
        if a0 > 0 >= a1:
            return c0 + (c1 - c0) * a0 / (a0 - a1)
    return "3 이상"


def _r_x041(st: _State) -> dict:
    rid, ctx = "X-041", st.ctx
    res = _new(rid)
    cs = tuple(sorted(set(_x041_mults(st)) | {1.0}))
    for pool in XC.POOLS:
        picks = st.picks(pool)
        arms = _arms_money(ctx, pool)

        def summ(p, a, c):
            return st.acc_money(p, a) if c == 1.0 else _rr(st, rid, p, a, f"c{c:g}")
        L = {(a, c): np.array([_Lk(summ(p, a, c)) for p in picks]) for a in arms for c in cs}
        for arm in arms:
            counts = OrderedDict()
            for c in cs:
                counts["entered_" + C_TAG[c]] = int(sum(MT.count(summ(p, arm, c), "entered") for p in picks))
                counts["rejected_" + C_TAG[c]] = int(sum(MT.count(summ(p, arm, c), "rejected") for p in picks))
            counts["flag"] = _thin(min(counts["entered_" + C_TAG[c]] for c in cs))
            m = OrderedDict([("own", OrderedDict((C_TAG[c], float(L[(arm, c)].mean())) for c in cs))])
            if arm != "E0":
                Mc = OrderedDict((C_TAG[c], float(np.mean(L[(arm, c)] - L[("E0", c)]))) for c in cs)
                m["M"] = Mc
                m["crossing"] = crossing({c: Mc[C_TAG[c]] for c in cs})
            _put(st, res, pool, arm, counts, m)
    res["notes"].append("c multiplies taker, slippage, round trip and maker; funding, margins, brackets and leverages unchanged")
    return res


def _r_x043(st: _State) -> dict:
    rid, ctx = "X-043", st.ctx
    res = _new(rid)
    sizes = _x043_sizes(st)
    verdict_ok, verdict_counts_ok, diffs = True, {"core": True, "ds": True}, []
    for pool in XC.POOLS:
        picks = st.picks(pool)
        arms = _arms_money(ctx, pool)
        L = {}
        for s in sizes:
            for a in arms:
                L[(a, s, "big")] = np.array([_Lk(st.acc_money(p, a, s)) for p in picks])
                L[(a, s, "small")] = np.array([_Lk(_rr(st, rid, p, a, "w1000", s)) for p in picks])
        for arm in arms:
            counts, m = OrderedDict(), OrderedDict()
            for s in sizes:
                tag = RX.SIZE_TAG[s]
                big = [st.acc_money(p, arm, s) for p in picks]
                small = [_rr(st, rid, p, arm, "w1000", s) for p in picks]
                eb, es = sum(MT.count(b, "entered") for b in big), sum(MT.count(x, "entered") for x in small)
                rb, rs_ = sum(MT.count(b, "rejected") for b in big), sum(MT.count(x, "rejected") for x in small)
                counts.update({f"entered_{tag}_w5000": eb, f"entered_{tag}_w1000": es, f"rejected_{tag}_w5000": rb, f"rejected_{tag}_w1000": rs_})
                ent_ok = abs(es - eb) <= 0.01 * eb if eb else es == 0
                verdict_counts_ok[pool] &= bool(ent_ok)
                part = OrderedDict([("busts_differ", int(sum(_bust(b["w_end"]) != _bust(x["w_end"]) for b, x in zip(big, small)))),
                                    ("final_multiple_median_w5000", _median([float(b["w_end"]) / float(b["w0"]) for b in big])),
                                    ("final_multiple_median_w1000", _median([float(x["w_end"]) / float(x["w0"]) for x in small]))])
                M_ok = True
                part.update(own_w5000=float(L[(arm, s, "big")].mean()) if len(picks) else None,
                            own_w1000=float(L[(arm, s, "small")].mean()) if len(picks) else None)
                if arm != "E0":
                    Mb = float(np.mean(L[(arm, s, "big")] - L[("E0", s, "big")]))
                    Ms = float(np.mean(L[(arm, s, "small")] - L[("E0", s, "small")]))
                    part.update(M_w5000=Mb, M_w1000=Ms)
                    M_ok = abs(XC.pct_month(Ms) - XC.pct_month(Mb)) <= 0.1
                if pool == "core":
                    verdict_ok &= bool(ent_ok and M_ok)
                    if not (ent_ok and M_ok):
                        diffs.append(f"{arm} {tag}")
                m[tag] = part
            _put(st, res, pool, arm, counts, m)
        if pool == "ds":
            res["ds"]["label_verdict"] = ("진입·거절 수는 1,000달러도 5,000달러와 거의 같습니다" if verdict_counts_ok["ds"]
                                          else "진입 수가 1% 넘게 다른 줄이 있습니다")
    res["core"]["label_verdict"] = ("1,000달러도 5,000달러와 거의 같습니다" if verdict_ok else "다릅니다: " + ", ".join(diffs))
    res["notes"].append("only the starting wallet S[10] changes; the $10 bust line S[9] stays")
    return res


# ====================================================================================================== X-017 hindsight ceiling
NH = 5                                           # horizons (i) <= own E0 exit, (ii) 24 h, (iii) 48 h, (iv) none, (v) none + 1m limits
H_KEYS = ("i_e0", "ii_24h", "iii_48h", "iv_none", "v_limit")
CK_CHECK, CK_TP, CK_LIMIT, CK_SL, CK_LIQ, CK_END = 0, 1, 2, 3, 4, 5
_INF = 2 ** 62


@njit(cache=False)
def _hind_value(price, fee, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref):
    """ln(1 + wallet change / W_ref) of a price exit by the kernel's formulas (a gross loss beyond the margin is a liquidation)."""
    gross = side * qty * (price - fill)
    if gross < -mg:
        d = dliq
    else:
        d = -notional * taker - fpaid + gross - qty * price * fee
    x = 1.0 + d / W_ref
    return math.log(x if x > 1e-12 else 1e-12), d


@njit(cache=False)
def _hind_dp(S, brs, ts, o, h, l, mo, mh, ml, fund, starts, pend, sc, scl, ssd, satr, sbest, se, sfill, qsteps, mnot,
             stop_atr, tp_kind, tp_val, tf_ms, lim1, W_ref, collect, buf):
    """X-017: the backward DP over the offered list for the five horizons. Signal i (sizeable at W_ref with quality_v1, else skipped
    without blocking) is walked minute by minute in kernel_x's step order from its fill minute e (funding at the open, mark-open
    liquidation, stop gap, TP gap, check-minute exit, period end; then the range: hard stop, mark liquidation, TP). Candidates: a market
    exit at the open of the check minute of every close C0 + m tf (busy until its minute - 1 ms), the take-profit at its first touch
    (maker; the path also holds on past it), and under (v) a maker limit at the 1m high (long) / low (short) of every minute after e;
    forced ends SL, LIQ and END close the path. V[k, i] = max over the candidates of horizon k of value + V[k, first j > i whose fill
    > busy-until]. Returns (V, sizeable, next of the best (iv) choice, its exit ms, its win flag, fallbacks per horizon, candidates written
    to ``buf`` for signal ``collect``)."""
    n = len(sc)
    V = np.zeros((NH, n + 1))
    take = np.zeros(n, np.bool_)
    bnext = np.arange(1, n + 1).astype(np.int64)
    bts = np.zeros(n, np.int64)
    bwin = np.zeros(n, np.bool_)
    nfall = np.zeros(NH, np.int64)
    nb = 0
    taker, slip, rt, maker = S[0], S[1], S[5], S[19]
    kinds = np.zeros(4, np.int64)                      # the candidates of one minute (at most four), reused
    vals = np.zeros(4)
    dels = np.zeros(4)
    nxts = np.zeros(4, np.int64)
    best = np.zeros(NH)
    fb = np.zeros(NH)
    lims = np.zeros(NH, np.int64)
    for i in range(n - 1, -1, -1):
        for k in range(NH):
            V[k, i] = V[k, i + 1]
        c = sc[i]
        a = starts[c]
        b = pend[c]
        e = se[i]
        side = ssd[i]
        atr = satr[i]
        raw = o[e]
        fill = raw * (1.0 + side * slip)
        sd = stop_atr * atr
        stop = raw - side * sd
        ok, lev, margin0, qty, liq0 = K._size(S, brs[c], W_ref, side, fill, stop, atr, sbest[i], qsteps[c], mnot[c])
        if not ok:
            continue
        take[i] = True
        has_tp = tp_kind != K.TP_NONE
        tp = 0.0
        if tp_kind == K.TP_R:
            tp = raw + side * tp_val * sd
        elif tp_kind == K.TP_ROE:
            tp = fill * (1.0 + side * (tp_val / lev + rt))
        notional = qty * fill
        kb = K._bracket(brs[c], notional)
        mmr = brs[c][kb, 2]
        cumv = brs[c][kb, 3]
        fpaid = 0.0
        mg = margin0
        lq = liq0
        dliq = -notional * taker - margin0
        for k in range(NH):
            best[k] = -np.inf
            fb[k] = np.nan
        lims[0], lims[1], lims[2], lims[3], lims[4] = lim1[i], scl[i] + 86_400_000, scl[i] + 172_800_000, _INF, _INF
        p = i + 1
        tp_done = False
        mchk = 1
        tsc = ts[a:b]
        jc = a + np.searchsorted(tsc, scl[i] + mchk * tf_ms - 60_000) + 1
        if jc <= e:
            jc = e + 1
        if jc >= b:
            jc = _INF
        for j in range(e, b):
            tj = ts[j]
            while p < n and sfill[p] <= tj - 1:
                p += 1
            p2 = p
            while p2 < n and sfill[p2] <= tj:
                p2 += 1
            # candidates of this minute: up to four (kind, value, delta, next index), and whether the path ends here
            nk = 0
            forced = False
            if j > e:
                if fund[j] != 0.0:
                    pay = side * qty * mo[j] * fund[j]
                    mg -= pay
                    fpaid += pay
                    lq = K._liq(side, qty, fill, mg, mmr, cumv)
                if (mo[j] - lq) * side <= 0:
                    kinds[nk] = CK_LIQ
                    dels[nk] = dliq
                    xx = 1.0 + dliq / W_ref
                    vals[nk] = math.log(xx if xx > 1e-12 else 1e-12)
                    nxts[nk] = p2
                    nk += 1
                    forced = True
                elif (o[j] - stop) * side <= 0:
                    v_, d_ = _hind_value(o[j] * (1 - side * slip), taker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                    kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_SL, v_, d_, p2
                    nk += 1
                    forced = True
                else:
                    if has_tp and (not tp_done) and (o[j] - tp) * side > 0:
                        v_, d_ = _hind_value(o[j], maker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                        kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_TP, v_, d_, p2
                        nk += 1
                        tp_done = True
                    if j == jc:
                        v_, d_ = _hind_value(o[j] * (1 - side * slip), taker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                        kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_CHECK, v_, d_, p
                        nk += 1
                    while jc <= j:
                        mchk += 1
                        jc = a + np.searchsorted(tsc, scl[i] + mchk * tf_ms - 60_000) + 1
                        if jc >= b:
                            jc = _INF
                    if j == b - 1:
                        v_, d_ = _hind_value(o[j] * (1 - side * slip), taker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                        kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_END, v_, d_, p2
                        nk += 1
                        forced = True
            if not forced:
                hit_stop = (l[j] <= stop) if side > 0 else (h[j] >= stop)
                hit_liq = (ml[j] <= lq) if side > 0 else (mh[j] >= lq)
                if hit_stop:
                    v_, d_ = _hind_value(stop * (1 - side * slip), taker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                    kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_SL, v_, d_, p2
                    nk += 1
                    forced = True
                elif hit_liq:
                    kinds[nk] = CK_LIQ
                    dels[nk] = dliq
                    xx = 1.0 + dliq / W_ref
                    vals[nk] = math.log(xx if xx > 1e-12 else 1e-12)
                    nxts[nk] = p2
                    nk += 1
                    forced = True
                else:
                    if has_tp and (not tp_done) and ((h[j] > tp) if side > 0 else (l[j] < tp)):
                        v_, d_ = _hind_value(tp, maker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                        kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_TP, v_, d_, p2
                        nk += 1
                        tp_done = True
                    if j > e:
                        v_, d_ = _hind_value(h[j] if side > 0 else l[j], maker, side, qty, fill, notional, taker, fpaid, mg, dliq, W_ref)
                        kinds[nk], vals[nk], dels[nk], nxts[nk] = CK_LIMIT, v_, d_, p2
                        nk += 1
            for u in range(nk):
                hm = 0
                for k in range(NH):
                    if kinds[u] == CK_LIMIT and k < 4:
                        continue
                    tot = vals[u] + V[k, nxts[u]]
                    if np.isnan(fb[k]):
                        fb[k] = tot
                    if tj <= lims[k]:
                        hm |= 1 << k
                        if tot > best[k]:
                            best[k] = tot
                            if k == 3:
                                bnext[i] = nxts[u]
                                bts[i] = tj
                                bwin[i] = dels[u] > 0
                if collect == i and nb < buf.shape[0]:
                    buf[nb, 0] = tj
                    buf[nb, 1] = tj - 1 if kinds[u] == CK_CHECK else tj
                    buf[nb, 2] = vals[u]
                    buf[nb, 3] = hm
                    buf[nb, 4] = kinds[u]
                    buf[nb, 5] = nxts[u]
                    nb += 1
            if forced:
                break
        for k in range(NH):
            if best[k] > -np.inf:
                V[k, i] = best[k]
            else:
                V[k, i] = fb[k]
                nfall[k] += 1
    return V, take, bnext, bts, bwin, nfall, nb


def _hind_inputs(st: _State, p: dict, pdata, size: float) -> tuple:
    """The arrays of _hind_dp for one pick and size: E0's offered signals with their fill minutes (absolute) and, per signal, the exit
    time of E0's standalone trade at equity 5,000 (KX.simulate_trade, horizon (i))."""
    mk = st.ctx.market
    off = pdata.offered("select", mk)
    n = len(off["coin"])
    pend = mk.period_end("select")
    se = np.zeros(n, np.int64)
    lim1 = np.zeros(n, np.int64)
    for q in range(n):
        c = int(off["coin"][q])
        a = int(mk.starts[c])
        tsp = mk.cat["ts"][a:int(pend[c])]
        e = int(np.searchsorted(tsp, off["fill"][q]))
        if e >= len(tsp) or tsp[e] != off["fill"][q]:
            raise AssertionError(f"X-017 {p['id']}: a fill minute is not a minute of its coin")
        se[q] = a + e
        out = KX.simulate_trade(mk, pdata, KX.E0, off, q, size, "select", equity=W_REF)[0]
        lim1[q] = int(tsp[int(out[1])])
    stop_atr, tp_kind, tp_val, ladder = KX.exit_of_pick(p, KX.E0)[:4]
    if ladder:
        raise AssertionError("X-017: a pick with a lock exit is not covered (none of the 38 has one)")
    return off, se, lim1, float(stop_atr), int(tp_kind), float(tp_val)


def hind_run(st: _State, p: dict, pdata, size: float, collect: int = -1, buf_rows: int = 1) -> dict:
    """X-017 for one pick and size: G* per horizon, the best (iv) path's trades, holds and wins, and (``collect``) the candidates of one
    signal as rows (exit ms, busy-until ms, value, horizon bit mask, kind, next index)."""
    mk = st.ctx.market
    off, se, lim1, stop_atr, tp_kind, tp_val = _hind_inputs(st, p, pdata, size)
    buf = np.zeros((max(1, buf_rows), 6))
    S = np.asarray(mk.S(size), float)
    V, take, bnext, bts, bwin, nfall, nb = _hind_dp(
        S, mk.brs, mk.cat["ts"], mk.cat["o"], mk.cat["h"], mk.cat["l"], mk.cat["mo"], mk.cat["mh"], mk.cat["ml"], mk.cat["fund"],
        mk.starts, mk.period_end("select"), off["coin"].astype(np.int64), off["close"].astype(np.int64), off["side"].astype(np.int64),
        off["atr"].astype(float), off["best"].astype(np.bool_), se, off["fill"].astype(np.int64), mk.qty_steps, mk.min_notionals,
        stop_atr, tp_kind, tp_val, int(DX.TF_MS[p["tf"]]), lim1, W_REF, int(collect), buf)
    holds, wins, i, n = [], [], 0, len(take)
    while i < n:
        if not take[i]:
            i += 1
            continue
        holds.append((int(bts[i]) - int(off["fill"][i])) / 3_600_000.0)
        wins.append(bool(bwin[i]))
        i = int(bnext[i])
    return {"G": V[:, 0].copy(), "V": V, "take": take, "n_take": int(take.sum()), "path_hold": np.asarray(holds, float),
            "path_win": np.asarray(wins, bool), "nfall": nfall, "cands": buf[:int(nb)].copy(), "lim1": lim1, "se": se}


def _pre_x017(st: _State, p: dict, pdata) -> None:
    for size in RX.SIZE_TAG:
        r = hind_run(st, p, pdata, size)
        st.extra[("X-017", p["id"], size)] = {k: r[k] for k in ("G", "path_hold", "path_win", "nfall", "n_take")}
        XC.save_reduced(st.ctx, p, REDUCED_DIR["X-017"], size, {k: np.asarray(r[k]) for k in ("G", "path_hold", "path_win", "nfall")})


PRE_PICK["X-017"] = _pre_x017


def _capture_sum(st: _State, p: dict, arm: str, size: float) -> float:
    """Sum over the arm's own trades of ln(1 + pnl_i x qty_ref_i / qty_i / 5,000), qty_ref_i = kernel._size at 5,000 for that trade."""
    f = st.c4(p, arm, size)
    mk = st.ctx.market
    S = f["S"]
    tot = 0.0
    for i in range(len(f["pnl"])):
        c = int(f["coin"][i])
        ok, _lv, _mg, qref, _lq = K._size(S, mk.brs[c], W_REF, int(f["side"][i]), f["fill"][i], f["raw"][i] - f["side"][i] * f["Rd"][i],
                                          f["atr"][i], bool(f["best"][i]), mk.qty_steps[c], mk.min_notionals[c])
        if ok:
            tot += math.log(max(1.0 + f["pnl"][i] * qref / f["qty"][i] / W_REF, LOG_TINY))
    return tot


def _r_x017(st: _State) -> dict:
    rid, ctx = "X-017", st.ctx
    res = _new(rid)
    for pool in XC.POOLS:
        picks = st.picks(pool)
        N = len(picks)
        pool_out = OrderedDict()
        for size, tag in RX.SIZE_TAG.items():
            ex = [st.extra[(rid, p["id"], size)] for p in picks]
            G = np.array([e["G"] for e in ex]) if N else np.zeros((0, NH))
            pooled = G.mean(axis=0) / XC.N_MONTHS if N else np.zeros(NH)
            hold = _cat([e["path_hold"] for e in ex])
            win = _cat([e["path_win"] for e in ex], bool)
            part = OrderedDict([("pooled_month_log", OrderedDict(zip(H_KEYS, pooled.tolist()))),
                                ("month_multiple", OrderedDict(zip(H_KEYS, np.exp(pooled).tolist()))),
                                ("path_trades", int(len(hold))), ("path_hold_median", _median(hold)),
                                ("path_win_share", _share(win) if len(win) else None), ("flag", _thin(len(hold))),
                                ("n_fallback", OrderedDict(zip(H_KEYS, np.sum([e["nfall"] for e in ex], axis=0).astype(int).tolist()))
                                 if N else None),
                                ("e0_own_month_log", st.L(pool, "E0", size))])
            cap = OrderedDict()
            for arm in _arms_money(ctx, pool):
                gi = float(pooled[3])
                s_ = float(np.mean([_capture_sum(st, p, arm, size) for p in picks])) / XC.N_MONTHS if N else 0.0
                cap[arm] = (s_ / gi) if gi > 0 else None
            part["capture"] = cap
            pool_out[tag] = part
        if pool == "core":
            res["core"]["ceiling"] = pool_out
        else:
            res["private"]["ds"]["ceiling"] = pool_out
    res["notes"].append("hindsight on exit times only (E0's entries, stop, sizing at a fixed $5,000, no compounding); not achievable")
    return res


FUNCS = {"X-002": _r_x002, "X-004": _r_x004, "X-005": _r_x005, "X-008": _r_x008, "X-011": _r_x011, "X-015": _r_x015, "X-016": _r_x016,
         "X-017": _r_x017, "X-018": _r_x018, "X-021": _r_x021, "X-026": _r_x026, "X-028": _r_x028, "X-029": _r_x029, "X-030": _r_x030,
         "X-031": _r_x031, "X-033": _r_x033, "X-034": _r_x034, "X-038": _r_x038, "X-039": _r_x039, "X-041": _r_x041, "X-043": _r_x043}


# ====================================================================================================== Korean appendix (committed)
def _f(x, nd=2, unit="") -> str:
    return "-" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}{unit}"


def _pc(x, nd=1) -> str:
    """A share as a percent (core pages only)."""
    return "-" if x is None else f"{100.0 * x:.{nd}f}%"


def _gm(M) -> str:
    """C12: a monthly log growth level or difference as '%/월' = 100 (e^M - 1)."""
    return "-" if M is None else f"{XC.pct_month(M):+.2f}%/월"


def _ct(c) -> str:
    """C12: an additive contribution already x 100 ('%/월 기여(근사)')."""
    return "-" if c is None else f"{c:+.2f}"


def _x(m, nd=2) -> str:
    return "-" if m is None else f"x{m:.{nd}f}"


def _h(x) -> str:
    return "-" if x is None else f"{x:.1f}시간"


def _kn(share, n) -> str:
    """A share as k/n (DeepSeek pages, C14)."""
    if share is None or not n:
        return f"0/{int(n or 0)}"
    return f"{int(round(share * n))}/{int(n)}"


def _R(x) -> str:
    return "-" if x is None else f"{x:+.2f}R"


def _fl_mark(flag) -> str:
    return f" ({flag})" if flag and flag != "-" else ""


def _tbl(head: list, rows: list) -> list:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


def _head(rid: str, pool: str, title: str, money: bool = False) -> list:
    if pool == "ds":
        return [f"## {rid} · 딥시크 풀", "", XC.TAG_TABLE, ""]
    out = [f"## {rid} {title} · 코어 풀", "", XC.TAG_TABLE + (f" · 꼬리표: {MONEY_TAG}" if money else ""), ""]
    return out


def _rows(r: dict, pool: str) -> list:
    """Printed rows: E0 and the pool's choosable rows (label_choosable), in the committed order (the json holds all 89 where the read
    counts them)."""
    P = r.get(pool) or {}
    keep = set(P.get("label_choosable") or ())
    return [(a, P["by_arm"][a]) for a in P.get("order", []) if a in P["by_arm"] and (a == "E0" or a in keep)]


def _money_rows(r: dict) -> list:
    return [(a, row) for a, row in _rows(r, "core") if "money" in row]


def _w12(own_log) -> str:
    return " ※" if own_log is not None and XC.pct_month(own_log) <= 0 else ""


def _w12_line(flagged: bool) -> list:
    return [f"※ {XC.W['W12']}", ""] if flagged else []


def _ds_rows(r: dict) -> list:
    return _rows(r, "ds")


def _md_x002(r):
    L = _head("X-002", "core", r["title"], True)
    rows = _money_rows(r)
    if not rows:
        return L + ["-", ""] + _ds_nothing("X-002")
    coins = list(rows[0][1]["money"]["own_without"])
    e0 = rows[0][1]["money"]
    L += ["다시 돌린 계좌입니다. 칸은 'E0 대비 %/월'이고, 맨 위 줄은 E0 자신의 성장입니다.", ""]
    head = ["방식", "6코인 전체"] + [f"{c} 뺌" for c in coins] + ["빼도 남는 경우", "표시", "자기 성장"]
    body = [["E0 자신의 성장", _gm(e0["own_full"])] + [_gm(e0["own_without"][c]) for c in coins] + ["", "", _gm(e0["own_full"])]]
    flag = False
    for a, row in rows[1:]:
        m = row["money"]
        body.append([a, _gm(m["M"])] + [_gm(m["M_without"][c]) + _fl_mark(m["thin_by_coin"][c]) for c in coins]
                    + [f"{m['n_hold']}/{m['n_coins']}", "한 코인 의존" if m["label_one_coin"] else "", _gm(m["own_full"]) + _w12(m["own_full"])])
        flag |= bool(_w12(m["own_full"]))
    return L + _tbl(head, body) + _w12_line(flag) + [XC.W["W3"], ""] + _ds_nothing("X-002")


def _ds_nothing(rid: str) -> list:
    return _head(rid, "ds", "") + [DS_NOTHING_KO, ""]


def _md_x004(r):
    out = []
    for pool in XC.POOLS:
        P = r[pool]
        L = _head("X-004", pool, r["title"], pool == "core")
        dims = [k[3:] for k in (P["by_arm"].get("E0") or {}) if k.startswith("by_") and k != "by_wk"]
        if pool == "core":
            sh = P.get("share_offered_weekend")
            L += [f"주말 = 신호 봉이 닫힌 시각 기준 토 00:00~월 00:00 UTC(한국 토 09:00~월 09:00). 달력의 주말 몫은 {_pc(XC.CAL_WEEKEND_SHARE)}이고, "
                  f"나온 신호 중 주말 신호는 {_pc(sh)}입니다(모든 방식이 같습니다).", ""]
            head = ["방식", "거래 수", "주말 매매 비율", "승률 주말 · 평일", "보유 중앙값 주말 · 평일", "월 성장 기여 주말 · 평일",
                    "주말 거래를 지우면", "주말 몫", "주말-평일 거래당 차이(우연 범위)"]
            body = []
            for a, row in _rows(r, "core"):
                w, d = row["by_wk"]["weekend"], row["by_wk"]["weekday"]
                m = row.get("money") or {}
                body.append([a, f"{row['n']}{_fl_mark(row['flag'])}", _pc(row["share_weekend"]), f"{_pc(w['win_share'])} · {_pc(d['win_share'])}",
                             f"{_h(w['hold_median'])} · {_h(d['hold_median'])}", f"{_ct(m.get('G_weekend'))} · {_ct(m.get('G_weekday'))}",
                             _ct(m.get("erased")), _pc(m.get("share_weekend_growth")) if m.get("share_weekend_growth") is not None else "W15",
                             _dl(m)])
            L += _tbl(head, body)
            bt = P["by_table"]["all"]
            L += [XC.c15_line(bt["n_cells"], bt["n_thin"], bt.get("n_outside")), "", XC.CONTRIB_NOTE_KO, DLAM_NOTE_KO, ""]
            for dim in dims:
                L += [f"### X-004 나눠 보기: {DIM_KO.get(dim, dim)}", "", XC.TAG_TABLE, ""]
                body = []
                for a, row in _rows(r, "core"):
                    for b, cell in row["by_" + dim].items():
                        mb = (row.get("money") or {}).get("by_" + dim, {}).get(b, {})
                        w, d = cell["weekend"], cell["weekday"]
                        body.append([a, BUCKET_KO.get(b, b), f"{w['n']} · {d['n']}" + _fl_mark(_thin(min(w["n"], d["n"]))),
                                     f"{_pc(w['win_share'])} · {_pc(d['win_share'])}", f"{_ct(mb.get('G_weekend'))} · {_ct(mb.get('G_weekday'))}",
                                     _dl(mb)])
                L += _tbl(["방식", "칸", "거래 주말 · 평일", "승률 주말 · 평일", "월 성장 기여 주말 · 평일", "주말-평일 거래당 차이(우연 범위)"], body)
                bt = P["by_table"][dim]
                L += [XC.c15_line(bt["n_cells"], bt["n_thin"], bt.get("n_outside")), ""]
            L += [XC.W["W4"], ""]
        else:
            L += [DS_COUNTS_KO, ""]
            body = []
            for a, row in _ds_rows(r):
                w, d = row["by_wk"]["weekend"], row["by_wk"]["weekday"]
                body.append([a, f"{row['n']}{_fl_mark(row['flag'])}", f"{w['n']}/{row['n']}", f"{w['wins']}/{w['n']} · {d['wins']}/{d['n']}",
                             f"{_h(w['hold_median'])} · {_h(d['hold_median'])}"])
            L += _tbl(["방식", "거래 수", "주말 매매", "이긴 거래 주말 · 평일", "보유 중앙값 주말 · 평일"], body)
            bt = P["by_table"]["all"]
            L += [XC.c15_line(bt["n_cells"], bt["n_thin"]), ""]
            for dim in dims:
                body = []
                for a, row in _ds_rows(r):
                    for b, cell in row["by_" + dim].items():
                        w, d = cell["weekend"], cell["weekday"]
                        body.append([a, BUCKET_KO.get(b, b), f"{w['n']} · {d['n']}", f"{w['wins']}/{w['n']} · {d['wins']}/{d['n']}"])
                L += [f"### X-004 나눠 보기: {DIM_KO.get(dim, dim)}", ""] + _tbl(["방식", "칸", "거래 주말 · 평일", "이긴 거래 주말 · 평일"], body)
                bt = P["by_table"][dim]
                L += [XC.c15_line(bt["n_cells"], bt["n_thin"]), ""]
            L += [XC.W["W4"], ""]
        out += L
    return out


DIM_KO = {"side": "롱·숏", "tf": "봉", "coin": "코인", "year": "해", "state": "장세"}
DLAM_NOTE_KO = "거래당 차이 = 주말 거래와 평일 거래의 거래당 평균 로그 성장 차이에 100을 곱한 값(지갑 %, 근사)이고, 괄호는 주를 통째로 다시 뽑아 만든 우연 범위입니다."


def _dl(m: dict) -> str:
    if not m or m.get("dlam") is None:
        return XC.EMPTY
    return f"{100 * m['dlam']:+.3f} [{_f(100 * m['range_lo'] if m.get('range_lo') is not None else None, 3)} ~ " \
           f"{_f(100 * m['range_hi'] if m.get('range_hi') is not None else None, 3)}] {m.get('label_chance', '')}".rstrip()
BUCKET_KO = {"long": "롱", "short": "숏", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}


def _md_x005(r):
    L = _head("X-005", "core", r["title"], True)
    L += ["**새 진입만 쉬는 경우이며 금요일 밤에 정리하는 경우가 아닙니다.**", "",
          "다시 돌린 계좌입니다. 차이의 범위는 36달로 만든 것이라 넓습니다.", ""]
    body, flag = [], False
    for a, row in _money_rows(r):
        m = row["money"]
        body.append([a, _gm(m["own_full_month_log"]), _gm(m["own_month_log"]) + _w12(m["own_month_log"]),
                     f"{_gm(m['d_own'])} [{_gm(m['interval_lo'])} ~ {_gm(m['interval_hi'])}]", _gm(m["d_vs_e0"]), row["n_removed_weekend"],
                     row["n_new"], row["n_dropped"], _ct(m["free_slot"]), f"{m['months_better']}/{m['n_months']}",
                     f"{_pc(m['max_dd_median_full'])} → {_pc(m['max_dd_median'])}", f"파산 {m['busts_full']}/{m['n_picks']} → {m['busts']}/{m['n_picks']}",
                     f"{row['entered_full']} → {row['entered']}{_fl_mark(row['flag'])}"])
        flag |= bool(_w12(m["own_month_log"]))
    L += _tbl(["방식", "지금 %/월", "주말 신규 진입 없는 계좌 %/월", "차이(범위)", "지금 E0 대비", "빠진 주말 거래 수", "대신 새로 들어간 거래 수",
               "빠진 평일 거래 수", "빈자리 효과(%/월 기여)", "더 나은 달", "최대 하락 중앙값", "파산", "진입"], body)
    L += _w12_line(flag) + [XC.CONTRIB_NOTE_KO, "", XC.W["W4"], ""]
    D = _head("X-005", "ds", "") + [DS_COUNTS_KO, ""]
    body = [[a, f"{row['entered_full']} → {row['entered']}{_fl_mark(row['flag'])}", row["n_removed_weekend"], row["n_new"], row["n_dropped"],
             f"{row['wins']}/{row['entered']}", _h(row["hold_median"])] for a, row in _ds_rows(r)]
    D += _tbl(["방식", "진입(지금 → 이 계좌)", "빠진 주말 거래", "대신 새로 들어간 거래", "빠진 평일 거래", "이긴 거래", "보유 중앙값"], body)
    return L + D + [XC.W["W4"], ""]


def _state_cell_core(c) -> str:
    if not c["n"]:
        return XC.EMPTY
    m = c.get("money") or {}
    s = f"{c['n']} / {_pc(c['win_share'])}"
    if m:
        s += f" / {_R(m.get('R_mean'))}(±{_f(m.get('R_se'), 2)}) / {_ct(m.get('c'))}(E0 대비 {_ct(m.get('dc'))})"
    return s + _fl_mark(c.get("flag"))


def _split_md(r, rid, key, labels, title_ds, note=None):
    L = _head(rid, "core", r["title"], True)
    if note:
        L += [note, ""]
    rows = _money_rows(r)
    head = ["방식"] + [BUCKET_KO.get(b, b) for b in labels]
    body, rbody = [], []
    for a, row in rows:
        cells = row[key]
        mon = row["money"][key]
        body.append([a] + [_state_cell_core({**cells[b], "money": mon.get(b)}) for b in labels])
        rbody.append([a] + [(" · ".join(f"{REASON_KO[x]} {_pc(cells[b]['share_reasons'][x], 0)}" for x in REASON_SHOWN) if cells[b]["n"]
                             else XC.EMPTY) for b in labels])
    L += ["칸 = 건수 / 승률 / 평균 R(±) / 월 기여(E0 대비 ±)", ""] + _tbl(head, body)
    L += [f"끝난 이유({' · '.join(REASON_KO[x] for x in REASON_SHOWN)}) 비율", ""] + _tbl(head, rbody)
    bt = (r["core"].get("by_table") or {}).get("all")
    if bt:
        L += [XC.c15_line(bt["n_cells"], bt["n_thin"]), ""]
    L += [R_DEF_KO, XC.CONTRIB_NOTE_KO, ""]
    D = _head(rid, "ds", "") + [DS_COUNTS_KO, ""]
    body = []
    for a, row in _ds_rows(r):
        cells = row[key]
        body.append([a] + [(f"{cells[b]['n']} / {cells[b]['wins']}/{cells[b]['n']}{_fl_mark(cells[b]['flag'])}" if cells[b]["n"] else XC.EMPTY)
                           for b in labels])
    D += ["칸 = 건수 / 이긴 거래", ""] + _tbl(head, body)
    bt = (r["ds"].get("by_table") or {}).get("all")
    if bt:
        D += [XC.c15_line(bt["n_cells"], bt["n_thin"]), ""]
    return L, D


def _md_x008(r):
    L, D = _split_md(r, "X-008", "by_state", STATE_LABELS, "", "들어갈 때의 장세 기준입니다. 장세별 보유 시간은 고르기 표의 둘째 표에 있습니다.")
    return L + D


def _md_x011(r):
    note = "고르는 기간에는 2021년 상승장과 2022년 하락장이 함께 있어, 롱·숏 차이는 대부분 그 해의 시장 방향을 따릅니다."
    L, D = _split_md(r, "X-011", "by_side", SIDE_LABELS, "", note)
    for a, row in _money_rows(r):
        ss, sc = row["by_side_state"], row["by_side_coin"]
        ms, mc = row["money"]["by_side_state"], row["money"]["by_side_coin"]
        L += [f"### X-011 {a}: 롱/숏 x 장세, 롱/숏 x 코인", ""]
        L += _tbl(["쪽"] + list(STATE_LABELS), [[SIDE_KO[s]] + [f"{ss[s][x]['n']} / {_pc(ss[s][x]['win_share'])} / {_R(ms[s][x]['R_mean'])} / "
                                                              f"{_ct(ms[s][x]['c'])}" for x in STATE_LABELS] for s in SIDE_LABELS])
        coins = list(sc["long"])
        L += _tbl(["쪽"] + coins, [[SIDE_KO[s]] + [f"{sc[s][k]['n']} / {_pc(sc[s][k]['win_share'])} / {_h(sc[s][k]['hold_median'])} / "
                                                   f"{_ct(mc[s][k]['c'])}" for k in coins] for s in SIDE_LABELS])
    L += [XC.TAG_TABLE, ""]
    for a, row in _ds_rows(r):
        ss, sc = row["by_side_state"], row["by_side_coin"]
        D += [f"### X-011 {a}: 롱/숏 x 장세, 롱/숏 x 코인", ""]
        D += _tbl(["쪽"] + list(STATE_LABELS), [[SIDE_KO[s]] + [f"{ss[s][x]['n']} / {ss[s][x]['wins']}/{ss[s][x]['n']}" for x in STATE_LABELS]
                                                for s in SIDE_LABELS])
        coins = list(sc["long"])
        D += _tbl(["쪽"] + coins, [[SIDE_KO[s]] + [f"{sc[s][k]['n']} / {sc[s][k]['wins']}/{sc[s][k]['n']} / {_h(sc[s][k]['hold_median'])}"
                                                   for k in coins] for s in SIDE_LABELS])
    return L + D


def _hit(h: dict) -> str:
    """A share as k/n with the distinct start months holding a hit and the largest single month's share of the hits."""
    s = f"{_pc(h['share'])} ({h['k']}/{h['n']}"
    if h["k"]:
        s += f", {h['n_months']}개 달에 몰림, 가장 많은 달 {_pc(h['top_month_share'], 0)}"
    return s + ")"


def _md_x015(r):
    L = _head("X-015", "core", r["title"], True)
    body, tb = [], []
    for a, row in _money_rows(r):
        m = row["money"]
        q = m["R_q"]
        body.append([a, _x(q["p50"]), _x(q["p90"]), _x(q["p10"]), f"{_x(m.get('worst'))}({m.get('worst_start', '-')})",
                     f"{_x(m.get('best'))}({m.get('best_start', '-')})", _hit(m["ge_2"]), _hit(m["touch_5"]), _hit(m["lt_0_5"]) + _fl_mark(m["flag"])])
        t = m["touch"]
        for tag, ko in (("q25", "1/4 크기"), ("q100", "1/1 크기")):
            cells = [f"{_pc(t[f'{tag}_{H}']['half'])} · {_pc(t[f'{tag}_{H}']['bust'])}" for H in WINDOW_DAYS]
            if tag == "q100":
                cells = [c + f" ({XC.bust_cell(t['q100_busts'], m['n_picks'])})" for c in cells]
            tb.append([a, ko] + cells)
    L += _tbl(["방식", "보통 30일", "좋은 30일(10번 중 1번)", "나쁜 30일(10번 중 1번)", "가장 나빴던 30일(시작일)", "가장 좋았던 30일(시작일)",
               "30일 뒤 x2 이상", "30일 안에 x5에 닿은 비율", "30일 뒤 절반 이하"], body)
    L += ["겹치는 창이라 서로 독립인 표본은 약 36달입니다.", "", "반토막·파산 닿음(지갑이 절반 이하로 내려간 적이 있는 경우 · 파산)", ""]
    L += _tbl(["방식", "크기", "30일 안", "92일 안", "365일 안"], tb) + [XC.W["W7"], XC.W["W9"], ""]
    return L + _ds_nothing("X-015")


def _md_x016(r):
    L = _head("X-016", "core", r["title"], True)
    L += [f"신호 최대치(어떤 청산으로도 탈 수 있는 한 달 진입 수): {_f(r['core'].get('entries_ceiling_per_account_month'), 2)}번", ""]
    for a, row in _money_rows(r):
        m = row["money"]
        L += [f"### X-016 {a}: 한 달 진입 {_f(row['n_entries_per_account_month'], 2)}번 · 승률 {_pc(row['win_share'])} · 보통 이익 "
              f"{_pc(m['typical_win'])} · 보통 손실 {_pc(m['typical_loss'])}" + (" (건수 적음)" if m["thin_ab"] else ""), ""]
        body = []
        for t in m["targets"]:
            tw = t["typical_win_need"]
            body.append([t["target"], t["label_win"] or _pc(t["win_share_need"]), t["label_entries"] if t["entries_need"] is None
                         else f"{_f(t['entries_need'], 1)}번 {t['label_entries']}".strip(),
                         ("1만% 넘음" if tw is not None and tw > 100 else _pc(tw)), _x(m["ceiling_all_wins"])])
        L += _tbl(["한 달 목표", "필요한 승률", "필요한 한 달 진입", "필요한 보통 이익", "다 이겨도 한 달 최대"], body)
        mo = lambda v: f"{v}달" if isinstance(v, int) else v      # noqa: E731
        L += [f"몇 달이면(1/4 크기, 보통 달 {_x(m['m_med'], 3)} 기준) x5 {mo(m['months_med']['x5'])} · x100 {mo(m['months_med']['x100'])}; "
              f"평균 달 {_x(m['m_geo'], 3)} 기준 x5 {mo(m['months_geo']['x5'])} · x100 {mo(m['months_geo']['x100'])}. {XC.W['W6']}", ""]
    L += ["상수표(데이터 없음): 몇 달에 x5·x100이 되려면 한 달에 몇 배여야 하나", ""]
    L += _tbl(["달 수", "x5", "x100"], [[c["months"], _x(c["x5_per_month"], 3), _x(c["x100_per_month"], 3)] for c in r.get("constants", [])])
    D = _head("X-016", "ds", "") + [DS_COUNTS_KO, ""]
    D += _tbl(["방식", "한 달 진입(번)", "이긴 거래"], [[a, _f(row["n_entries_per_account_month"], 2), f"{_kn(row['win_share'], row['n'])}"
                                                    + _fl_mark(row["flag"])] for a, row in _ds_rows(r)])
    return L + D


def _md_x017(r):
    L = _head("X-017", "core", r["title"], True)
    c = r["core"].get("ceiling") or {}
    body = []
    for tag, ko in (("q25", "1/4 크기"), ("q100", "1/1 크기")):
        p = c.get(tag)
        if not p:
            continue
        mm = p["month_multiple"]
        body.append([ko, f"{_x(mm['i_e0'])} (E0 {_x(math.exp(p['e0_own_month_log']), 3)})", _x(mm["iv_none"]), _x(mm["ii_24h"]),
                     _x(mm["iii_48h"]), _x(mm["v_limit"]), f"{p['path_trades']}건 · {_h(p['path_hold_median'])} · {_pc(p['path_win_share'])}"
                     + _fl_mark(p["flag"])])
    L += _tbl(["크기", "① 지금 청산보다 오래 들지 않을 때", "④ 시간 제한 없이", "② 24시간", "③ 48시간", "⑤ 최고가에 팔 때", "④ 길의 거래 수·보유 중앙값·승률"], body)
    L += [XC.W["W5"], ""]
    return L + _ds_nothing("X-017")


def _md_x018(r):
    L = _head("X-018", "core", r["title"], True)
    body = []
    for a, row in _money_rows(r):
        for tag, ko in (("q25", "1/4 크기"), ("q100", "1/1 크기")):
            m = row["money"][tag]
            b, s, k, t = m["basket"], m["single"], m["streaks"], m["together"]
            bc = "-" if b is None else (f"{_pc(b['max_dd'])} ({b.get('peak_date', '-')} → {b.get('trough_date', '-')} → {b.get('recovery_date', '-')}) "
                                        f"· 가장 오래 본전 아래 {_f(b['under_days'], 0)}일({b.get('under_start') or '-'} ~ {b.get('under_end') or '-'}) "
                                        f"· 끝 {_x(b['final'])} · 가장 나쁜 달 {b['worst_month']}({_pc(b['worst_month_change'])}) "
                                        f"· 떨어진 달 {b['months_fell']}/{b['n_months']}")
            busts = XC.bust_cell(s["busts"], s["n_picks"])
            body.append([a, ko, bc, f"{_pc(s['max_dd_p50'])} · {_pc(s['max_dd_p90'])} · {_pc(s['max_dd_max'])}", f"{_f(s['under_days_p50'], 0)}일",
                         busts, f"{_f(k['longest_p50'], 0)} · {k['longest_max']}{_fl_mark(k['flag'])}", _f(t["n_eff"], 1)])
        e0 = row["money"].get("label_e0_max_dd")
        if e0:
            v = row["money"].get("e0_max_dd_median_select")
            L += [f"E0의 1/4 크기 최대 하락 중앙값: {_pc(v) if v is not None else _pc(row['money']['q25']['single']['max_dd_p50'])} ({e0})", ""]
    L += _tbl(["방식", "크기", "합친 바구니의 가장 깊은 하락(고점 → 바닥 → 회복)", "계좌 하나로 보면 하락 보통 · 나쁜 경우 · 최악",
               "가장 오래 본전 아래(보통)", "파산 계좌", "연속으로 진 횟수 보통 · 최대", "사실상 독립 베팅 수"], body)
    L += ["닫힌 거래 기준이라 들고 있는 동안의 흔들림은 빠져 있습니다(X-019 참고).", XC.W["W9"], ""]
    return L + _ds_nothing("X-018")


def _md_x021(r):
    L = _head("X-021", "core", r["title"], True)
    body = []
    for a, row in _rows(r, "core"):
        coins = " · ".join(f"{k} {_pc(v['share_two_plus'])}" for k, v in row["by_coin"].items())
        m = row.get("money")
        mc = "-" if not m else (f"평소 {_pc(m['margin_p50'], 0)} · 90% {_pc(m['margin_p90'], 0)} · 최대 {_pc(m['margin_max'], 0)}, "
                                f"100% 초과 {_pc(m['share_over_100'])} ({XC.bust_cell(m['busts_live'], m['n_picks'])})")
        body.append([a, f"{_f(row['n_open_mean'], 1)} · {_f(row['n_open_p90'], 0)} · {row['n_open_max']}", _pc(row["share_open_ge1"]),
                     _pc(row["share_pairs_mean"]), coins, f"{row['n_max_same']}개 ({row['label_max_same_date']})", mc])
    L += _tbl(["방식", "동시에 열림 평소 · 많을 때(90%) · 최대", "포지션 중인 시간", "서로 다른 베팅 비율", "같은 코인에 2개 이상 겹친 시간",
               "같은 코인·방향 최대 겹침(처음 날)", "한 계좌로 합치면 증거금(1/1 크기)"], body)
    L += [XC.W["W13"], ""]
    D = _head("X-021", "ds", "") + [DS_COUNTS_KO, ""]
    body = []
    for a, row in _ds_rows(r):
        n = row["n_points"]
        coins = " · ".join(f"{k} {_kn(v['share_two_plus'], v['n_points'])}" for k, v in row["by_coin"].items())
        body.append([a, f"{_f(row['n_open_mean'], 1)} · {_f(row['n_open_p90'], 0)} · {row['n_open_max']}", _kn(row["share_open_ge1"], n), coins,
                     f"{row['n_max_same']}개 ({row['label_max_same_date']})"])
    D += _tbl(["방식", "동시에 열림 평소 · 많을 때 · 최대", "포지션 중인 시점", "같은 코인에 2개 이상 겹친 시점", "같은 코인·방향 최대 겹침(처음 날)"], body)
    return L + D


def _md_x026(r):
    L = _head("X-026", "core", r["title"], True)
    L += ["놓친 신호를 혼자 탔다면의 성적이며, 동시에 다 탈 수는 없습니다.", ""]
    body = []
    for a, row in _money_rows(r):
        m = row["money"]
        for k, ko in (("missed", "놓친 신호"), ("entered", "탄 신호")):
            c = m[k]
            body.append([a, ko, f"{c['n']}{_fl_mark(c['flag'])}", _pc(c["win_share"]), _pc(math.expm1(c["mean_log"]) if c["mean_log"] is not None else None, 3),
                         _h(c["hold_median"])])
    L += _tbl(["방식", "묶음", "건수", "이긴 비율", "한 번 평균(지갑 대비)", "보유 중앙값"], body)
    return L + _ds_nothing("X-026")


def _md_x028(r):
    L = _head("X-028", "core", r["title"], True)
    body = []
    for a, row in _money_rows(r):
        m = row["money"]
        cells = [f"{_pc(row['share_reasons'][x])} · {_R(m['R_mean_by_reason'][x])}" + (" (건수 적음)" if m["thin_by_reason"][x] else "")
                 for x in REASON_SHOWN]
        body.append([a + (f" ({row['label_rule']})" if row.get("label_rule") else ""), f"{row['n']}{_fl_mark(row['flag'])}"] + cells
                    + [_pc(m["share_sl_below_1_25R"]), _pc(m["share_rule_nonneg"]), _R(m["R_mean_rule_neg"]), row.get("label_select", "")])
    L += _tbl(["방식", "거래 수"] + [REASON_KO[x] for x in REASON_SHOWN] + ["손절이 -1.25R보다 나빠진 비율", "규칙 청산 중 수익으로 끝난 비율",
                                                                         "규칙 청산 손실 평균(손절은 -1R)", "건수"], body)
    L += [R_DEF_KO, ""]
    cb = []
    for a, row in _money_rows(r):
        for k, c in row["by_coin"].items():
            cb.append([a, k, c["n"]] + [_pc(c["share_reasons"][x], 0) for x in REASON_SHOWN])
    L += ["코인별 끝난 이유 비율", ""] + _tbl(["방식", "코인", "거래 수"] + [REASON_KO[x] for x in REASON_SHOWN], cb)
    D = _head("X-028", "ds", "") + [DS_COUNTS_KO, ""]
    D += _tbl(["방식", "거래 수"] + [REASON_KO[x] for x in REASON_SHOWN],
              [[a, f"{row['n']}{_fl_mark(row['flag'])}"] + [f"{row['reasons'][x]}/{row['n']}" for x in REASON_SHOWN] for a, row in _ds_rows(r)])
    return L + D


def _md_x029(r):
    L = _head("X-029", "core", r["title"], True)
    for a, row in _money_rows(r):
        m = row["money"]
        L += [f"### X-029 {a}", ""]
        body = []
        for t in (20, 30, 40, 50):
            c, q = row["by_tier"][str(t)], m["by_tier"][str(t)]
            body.append([f"{t}배", f"{c['n']} ({_pc(c['share'])}){_fl_mark(c['flag'])}", c["n_liq"],
                         f"{_pc(q['ROE_q']['p10'])} · {_pc(q['ROE_q']['p50'])} · {_pc(q['ROE_q']['p90'])}", _pc(q["share_roe_le_m40"]),
                         _pc(q["share_roe_ge_60"])])
        body.append(["전체", f"{row['n']}{_fl_mark(row['flag'])}", sum(row["by_tier"][str(t)]["n_liq"] for t in TIERS),
                     f"{_pc(m['ROE_q']['p10'])} · {_pc(m['ROE_q']['p50'])} · {_pc(m['ROE_q']['p90'])}", _pc(m["share_roe_le_m40"]),
                     _pc(m["share_roe_ge_60"])])
        L += _tbl(["레버리지", "거래 수(%)", "강제청산 수", "ROE 하위10% · 중앙 · 상위10%", "-40% 이하 비율", "+60% 이상 비율"], body)
        L += [f"손익 모양: 승률 {_pc(row['win_share'])} / 이길 때 평균 {_R(m['avg_win_R'])} / 질 때 평균 {_R(m['avg_loss_R'])} / 손익비 {_f(m['payoff'], 2)} / 본전 승률 "
              f"{_pc(m['breakeven_win_share'])} / 본전보다 {_f(m['edge_pp'], 1)}%p 위 / 거래 1건 기대 {_R(m['expectancy_R'])} / "
              f"1/4 크기 파산 {m['busts']}/{m['n_picks']}" + (" (이긴 거래나 진 거래가 20건 미만: 건수 적음)" if m["thin_win"] or m["thin_loss"] else ""), ""]
    L += ["R은 가격 기준 단위라 계좌 성장 숫자와 같지 않습니다.", R_DEF_KO, XC.W["W14"], ""]
    D = _head("X-029", "ds", "") + [DS_COUNTS_KO, ""]
    D += _tbl(["방식", "거래 수", "손절", "계단 잠금"], [[a, f"{row['n']}{_fl_mark(row['flag'])}", _kn(row["share_sl"], row["n"]),
                                                     _kn(row["share_lock"], row["n"])] for a, row in _ds_rows(r)])
    return L + D


def _md_x030(r):
    L = _head("X-030", "core", r["title"], True)
    body = []
    for a, row in _money_rows(r):
        m = row["money"]
        cells = [("전체", m["all"])] + [(f"{t}배", m["by_tier"][str(t)]) for t in TIERS] + [(ko, m["by_bar"][g]) for g, _t, ko in BAR_GROUPS]
        for lab, c in cells:
            body.append([a, lab, f"{c['n']}{_fl_mark(c['flag'])}", " · ".join(_pc(c[f"reach_{k}R"], 0) for k in (1, 2, 3)),
                         " · ".join(_pc(c[f"touch_roe_{k}"], 0) for k in (12, 17, 22, 60)),
                         f"{_pc(c['sl_reach_1R'], 0)} · {_pc(c['sl_reach_2R'], 0)} (손절 {c['n_sl']})",
                         f"{_pc(c['win_dip_0_5'], 0)} (이긴 {c['n_win']})", f"{_pc(c['touch12_closed_loss'], 0)} (닿은 {c['n_touch12']})",
                         f"{_pc(c['dip40_closed_pos'], 0)} (닿은 {c['n_dip40']})", f"{_f(c['d12_q']['p50'], 2)}배 (1배 미만 {_pc(c['d12_lt_1'], 0)})"])
    L += _tbl(["방식", "칸", "거래 수", "+1R·+2R·+3R까지 간 거래", "12%·17%·22%·60%에 닿은 거래", "손절 거래 중 먼저 +1R·+2R",
               "이긴 거래 중 손절선 절반 이상 밀림", "12%에 닿은 거래 중 손실로 끝남", "-40%까지 갔다가 +로 끝남", "잠금이 걸리려면 ATR의 몇 배"], body)
    L += ["E0 줄이 기준선입니다. 최고·최저는 1분봉 고가·저가로 쟀고 펀딩은 넣지 않았습니다.", R_DEF_KO, ""]
    return L + _ds_nothing("X-030")


def _md_x031(r):
    L = _head("X-031", "core", r["title"], True)
    body = []
    for a, row in _money_rows(r):
        m = row["money"]
        for key, ko in [("all", "전체")] + [(k, ko) for k, _c, ko in EXIT_CLASSES]:
            c = m["all"] if key == "all" else m["by_class"][key]
            body.append([a, ko, f"{c['n']}{_fl_mark(c['flag'])}", _f(c["giveback_median"], 2), _pc(c["share_ge_half"]), _pc(c["share_gave_all"]),
                         _pc(c["capture"])])
    L += _tbl(["방식", "끝난 이유", "+1R 넘게 간 거래 수", "돌려준 몫 중앙값", "번 것의 절반 이상 돌려준 비율", "다 돌려주고 손실로 끝난 비율",
               "챙긴 비율(최고점 대비 실제 R)"], body)
    return L + [R_DEF_KO, ""] + _ds_nothing("X-031")


def _md_x033(r):
    out = []
    for pool in XC.POOLS:
        L = _head("X-033", pool, r["title"])
        rows = _rows(r, "core") if pool == "core" else _ds_rows(r)
        if pool == "ds":
            L += [DS_COUNTS_KO, ""]
        body, yb = [], []
        for a, row in rows:
            n = row["n"]
            share = (lambda s: _pc(s)) if pool == "core" else (lambda s, n=n: _kn(s, n))
            body.append([a, f"{n}{_fl_mark(row['flag'])}", _h(row["hold_p10"]), _h(row["hold_median"]), f"{_h(row['hold_p90'])} ({row['label_p90']})",
                         share(row["hold_share_gt24"]), share(row["hold_share_gt72"]), _h(row["hold_longest"]),
                         f"{_h(row['hold_median_win'])} · {_h(row['hold_median_rest'])}",
                         " · ".join(f"{ko} {_h(row['hold_median_' + k])}" for k, _c, ko in EXIT_CLASSES)])
            yb.append([a] + [f"{_h(c['hold_median'])}(E0 {_h(c['hold_median_e0'])}) · 진입 {c['entered']}(E0 {c['entered_e0']}){_fl_mark(c['flag'])}"
                             for c in row["by_year"].values()] + [f"{row['label_entered_years']} · {row['label_shorter_years']}"])
        tail = ("짧은 쪽 10%", "긴 쪽 10%") if pool == "core" else ("짧은 쪽 10분위", "긴 쪽 10분위")
        L += _tbl(["방식", "거래 수", tail[0], "중앙값", tail[1], "24시간 넘게 든 비율", "3일 넘게 든 비율", "가장 길게 든 시간",
                   "이긴 거래 · 진 거래 중앙값", "청산 이유별 중앙값"], body)
        L += ["해마다(끝난 해 기준)", ""] + _tbl(["방식"] + [str(y) for y in YEARS] + ["세 해"], yb)
        out += L
    return out


def _md_x034(r):
    L = _head("X-034", "core", r["title"], True)
    body, hb, sb = [], [], []
    for a, row in _money_rows(r):
        m = row["money"]
        live = m.get("live") or {}
        body.append([a, _f(row["n_round_trips_per_account_month"], 2), f"{_f(m['cost_month_pct'], 2)}% (1/1 {_f(live.get('cost_month_pct'), 2)}%)",
                     f"{_f(m['fund_month_pct'], 2)}%", f"{_f(m['cost_per_trip_pct'], 3)}%", _R(m["costR_mean"]),
                     "1 미만(지금 비용에서도 평균 거래가 손해)" if m["c_star"] is not None and m["c_star"] < 1 else _f(m["c_star"], 2) + "배"])
        for i, ko in enumerate(HOLD_BUCKET_KO):
            c, cm = row["by_hold"][str(i)], m["by_hold"][str(i)]
            hb.append([a, ko, f"{c['n']}{_fl_mark(c['flag'])}", _pc(c["win_share"]), XC.EMPTY if not c["n"] else
                       (_pc(cm["share"]) if cm["share"] is not None else _ct(cm["c"])),
                       _pc(cm["ROE_mean"]), f"{_pc(cm['fund_roe'], 2)} · {_pc(cm['cost_roe'], 2)}"])
        for s in SIDE_LABELS:
            c, cm = row["by_side"][s], m["by_side"][s]
            sb.append([a, SIDE_KO[s], c["n"], _f(c["n_settlements_per_trade"], 1), _pc(cm["share_receive"]), _f(cm["fund_pct_notional"], 3) + "%"])
    L += _tbl(["방식", "한 달 거래 수", "한 달 수수료+미끄러짐(지갑의 %)", "한 달 펀딩(지갑의 %)", "한 번 사고팔 때 비용(지갑의 %)",
               "거래 1건당 비용", "비용이 몇 배까지 올라도 본전인가"], body)
    L += ["보유 시간대별(성장 몫은 C17이면 비율, 아니면 %/월 기여)", ""] + _tbl(["방식", "보유", "거래 수", "승률", "성장 몫", "평균 ROE",
                                                                    "펀딩 · 비용(ROE 포인트)"], hb)
    L += ["롱·숏 펀딩", ""] + _tbl(["방식", "쪽", "거래 수", "거래당 펀딩 정산 횟수", "펀딩을 받은 거래 비율", "펀딩(명목 금액의 %)"], sb)
    L += [R_DEF_KO, XC.CONTRIB_NOTE_KO, ""]
    D = _head("X-034", "ds", "") + [DS_COUNTS_KO, ""]
    body = []
    for a, row in _ds_rows(r):
        body.append([a, _f(row["n_round_trips_per_account_month"], 2)] + [f"{row['by_hold'][str(i)]['n']} ({row['by_hold'][str(i)]['wins']}승)"
                                                                          for i in range(len(HOLD_BUCKETS))]
                    + [" · ".join(f"{SIDE_KO[s]} {_f(row['by_side'][s]['n_settlements_per_trade'], 1)}" for s in SIDE_LABELS)])
    D += _tbl(["방식", "한 달 거래 수"] + list(HOLD_BUCKET_KO) + ["거래당 펀딩 정산 횟수"], body)
    return L + D


def _md_x038(r):
    L = _head("X-038", "core", r["title"], True)
    lines, flag = [], False
    for a, row in _money_rows(r):
        m = row["money"]
        if a == "E0":
            lines.append(f"- E0: 성장 중 큰 5거래 몫 {_pc(m['own_top5_share']) if m['own_top5_share'] is not None else 'W15'}, 계좌당 거래 "
                         f"{_f(m['trades_per_account'], 1)}건")
            continue
        kept = _pc(m["gain_kept"]) if m["gain_kept"] is not None else "W15"
        lines.append(f"- {a}: 각자 가장 큰 5거래씩 빼도 E0보다 {_gm(m['M5'])} (원래 {_gm(m['M'])}, 1거래만 빼면 {_gm(m['M1'])}), 이득 중 남는 몫 {kept}, "
                     f"{m['picks_pos5']}/{m['n_picks'] - m['n_thin_picks']}개 픽에서 여전히 + (30건 미만 픽 {m['n_thin_picks']}개 제외), 계좌당 거래 "
                     f"{_f(m['trades_per_account'], 1)}건(E0 {_f(m['trades_per_account_e0'], 1)}건), 자기 성장 {_gm(m['own'])}{_w12(m['own'])}"
                     + _fl_mark(m["flag"]))
        flag |= bool(_w12(m["own"]))
    L += lines + [""] + _w12_line(flag) + [XC.W["W15"] + " (W15 표시가 있는 칸)", ""]
    return L + _ds_nothing("X-038")


def _md_x039(r):
    out = []
    for pool in XC.POOLS:
        L = _head("X-039", pool, r["title"])
        P = r[pool]
        lines = []
        for a in P.get("order", []):
            row = P["by_arm"][a]
            if row.get("n_neighbours", 0) == 0:
                lines.append(f"- {a}: 이웃 없음")
                continue
            few = sum(1 for c in row["by_arm"].values() if c.get("few"))       # no 선택 불가 id is named on a page (E.1 item 4)
            lines.append(f"- {a}: 이웃 {row['n_neighbours']}개 중 {row['n_pass_g1']}개 통과, 선택 가능 {row['n_choosable']}개, "
                         f"{'격자 끝' if row['flag_edge'] else '격자 끝 아님'} → {row['label']}" + (f" (그중 건수 적음 {few}개)" if few else ""))
        L += (lines or ["- 선택 가능 방식 없음"]) + ["", "격자가 3칸이라 약한 근거입니다.", ""]
        out += L
    return out


def _md_x041(r):
    L = _head("X-041", "core", r["title"], True)
    rows = _money_rows(r)
    if not rows:
        return L + ["-", ""] + _ds_nothing("X-041")
    tags = list(rows[0][1]["money"]["own"])
    ko = {"c0": "비용 0", "c1": "지금", "c15": "1.5배", "c2": "2배", "c3": "3배"}
    body = [["E0 자체 성장"] + [_gm(rows[0][1]["money"]["own"][t]) for t in tags] + ["", ""]]
    flag = False
    for a, row in rows[1:]:
        m = row["money"]
        cr = m["crossing"]
        body.append([a] + [_gm(m["M"][t]) for t in tags] + [_gm(m["own"]["c1"]) + _w12(m["own"]["c1"]),
                                                            cr if isinstance(cr, str) else f"{cr:.2f}배"])
        flag |= bool(_w12(m["own"]["c1"]))
    L += ["다시 돌린 계좌입니다. 칸은 그 비용에서 지금 청산(E0)보다 %/월입니다.", ""]
    L += _tbl(["방식"] + [ko[t] for t in tags] + ["자기 성장(지금 비용)", "이 방식이 E0보다 못해지는 비용 배수"], body) + _w12_line(flag)
    L += _tbl(["방식"] + [f"{ko[t]} 진입 · 거절" for t in tags],
              [[a] + [f"{row['entered_' + t]} · {row['rejected_' + t]}" for t in tags] for a, row in rows])
    D = _head("X-041", "ds", "") + [DS_COUNTS_KO, ""]
    D += _tbl(["방식"] + [f"{ko[t]} 진입 · 거절" for t in tags],
              [[a] + [f"{row['entered_' + t]} · {row['rejected_' + t]}" for t in tags] for a, row in _ds_rows(r)])
    return L + D


def _md_x043(r):
    L = _head("X-043", "core", r["title"], True)
    L += [f"판정: {r['core'].get('label_verdict', '-')}", ""]
    body, flag = [], False
    for a, row in _money_rows(r):
        for tag, ko in (("q25", "1/4 크기"), ("q100", "1/1 크기")):
            m = row["money"].get(tag)
            if not m:
                continue
            own = m.get("own_w1000")
            cell = f"{_gm(m.get('M_w1000'))} vs {_gm(m.get('M_w5000'))}" if a != "E0" else "-"
            body.append([a, ko, f"{row[f'entered_{tag}_w1000']} vs {row[f'entered_{tag}_w5000']}",
                         f"{row[f'rejected_{tag}_w1000']} vs {row[f'rejected_{tag}_w5000']}", cell,
                         f"{_gm(own)}{_w12(own) if a != 'E0' else ''} vs {_gm(m.get('own_w5000'))}", f"{_x(m['final_multiple_median_w1000'])} vs {_x(m['final_multiple_median_w5000'])}",
                         f"{m['busts_differ']}개 픽"])
            flag |= bool(a != "E0" and _w12(own))
    L += _tbl(["방식", "크기", "진입 1,000 vs 5,000달러", "거절", "E0 대비 %/월", "자기 성장", "최종 배수 중앙값", "파산 여부가 달라진 픽"], body)
    L += _w12_line(flag) + [XC.W["W13"], ""]
    D = _head("X-043", "ds", "") + [DS_COUNTS_KO, "", f"판정(진입·거절 수만): {r['ds'].get('label_verdict', '-')}", ""]
    body = []
    for a, row in _ds_rows(r):
        for tag, ko in (("q25", "1/4 크기"), ("q100", "1/1 크기")):
            if f"entered_{tag}_w1000" in row:
                body.append([a, ko, f"{row[f'entered_{tag}_w1000']} vs {row[f'entered_{tag}_w5000']}",
                             f"{row[f'rejected_{tag}_w1000']} vs {row[f'rejected_{tag}_w5000']}"])
    D += _tbl(["방식", "크기", "진입 1,000 vs 5,000달러", "거절"], body)
    return L + D


MD = {"X-002": _md_x002, "X-004": _md_x004, "X-005": _md_x005, "X-008": _md_x008, "X-011": _md_x011, "X-015": _md_x015, "X-016": _md_x016,
      "X-017": _md_x017, "X-018": _md_x018, "X-021": _md_x021, "X-026": _md_x026, "X-028": _md_x028, "X-029": _md_x029, "X-030": _md_x030,
      "X-031": _md_x031, "X-033": _md_x033, "X-034": _md_x034, "X-038": _md_x038, "X-039": _md_x039, "X-041": _md_x041, "X-043": _md_x043}
APPENDIX_INTRO = ("이 부록의 표는 모두 2021~2023년(고르기 기간) 백테스트에서 나온 참고 숫자입니다. 아무것도 고르지 않고, 고르기 표의 기준을 바꾸지 "
                  "않습니다. 돈 숫자는 지금 청산(E0)과 고르기 표의 '선택 가능' 줄에만 적었습니다.")


def appendix_md(results: dict) -> str:
    """The Korean appendix part of the tier B reads (EXTRA_READS_APPENDIX_KO.md): beginner wording, the W sentences of common.W, the
    display rules C12-C17, the tag '참고용 · 고르는 데 안 씀' under every table heading; DeepSeek sections (headings with 딥시크) hold counts,
    hours and k/n only (C14). Rows: E0 and the choosable rows in the committed order."""
    L = ["## 부록 B: 추가 읽기 (B 묶음)", "", APPENDIX_INTRO, "", XC.CONTRIB_NOTE_KO, ""]
    for rid in READS:
        r = results.get(rid)
        if r is None:
            continue
        if "error" in r or "dropped" in r:
            L += [f"## {rid} {TITLES[rid]} · 코어 풀", "", ERROR_KO if "error" in r else DROPPED_KO, ""]
            continue
        L += MD[rid](r)
    return "\n".join(L).rstrip("\n") + "\n"


# ====================================================================================================== private DeepSeek appendix (never committed)
def _flat(prefix: str, obj, out: list) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flat(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj):
            out.append((prefix, ", ".join(_pv(v) for v in obj)))
        else:
            for i, v in enumerate(obj):
                _flat(f"{prefix}[{i}]", v, out)
    else:
        out.append((prefix, _pv(obj)))


def _pv(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return "-" if v is None else str(v)


def private_md(results: dict) -> str:
    """The DeepSeek money of the tier B reads for owner_report_extra.md, part 부록: E0 and the choosable rows in the committed order, no
    ranking, no p value; every heading carries '[비공개]', every table row's first cell reads '비공개' (never equal to a committed line)."""
    L = ["## [비공개] 부록 B: 딥시크 풀 돈 숫자(추가 읽기 B 묶음)", "", "[비공개] 지금 청산(E0)과 선택 가능 줄만, 고르기 표 순서대로 적었습니다.", ""]
    for rid in READS:
        r = results.get(rid)
        if not r or "error" in r or "dropped" in r:
            continue
        priv = (r.get("private") or {}).get("ds") or {}
        if not priv:
            continue
        L += [f"### [비공개] {rid} {TITLES[rid]}", "", "| 비공개 | 방식 | 항목 | 값 |", "|---|---|---|---|"]
        for k, v in priv.items():
            if k == "by_arm":
                continue
            items = []
            _flat(k, v, items)
            L += [f"| 비공개 | 풀 | {a} | {b} |" for a, b in items]
        for arm, row in (priv.get("by_arm") or {}).items():
            items = []
            _flat("", row, items)
            L += [f"| 비공개 | {arm} | {a} | {b} |" for a, b in items]
        L += [""]
    return "\n".join(L).rstrip("\n") + "\n"
