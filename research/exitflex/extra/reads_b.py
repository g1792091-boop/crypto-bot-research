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

The shared helpers of the read library (c4_match, c4_trade_frame, excursions, c5_status, c9_split) are taken from reads_lib when it
provides them; until then the private fallbacks of this module (_c4_match, _c4_trade_frame, _excursions, _c5_status, _c9_split) with
the same contracts are used (FALLBACKS_USED). Nothing here prints a figure.
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

# reads_lib (another builder's file) provides these when present; the private fallbacks below follow the same contracts
try:                                             # pragma: no cover - depends on the other builder's file
    import reads_lib as RL  # noqa: E402
except Exception:                                # noqa: BLE001
    RL = None
LIB_NAMES = ("c4_match", "c4_trade_frame", "excursions", "c5_status", "c9_split")
FALLBACKS_USED = tuple(n for n in LIB_NAMES if RL is None or not hasattr(RL, n))


def _lib(name):
    """reads_lib's helper when it exists and READS_B_USE_LIB=1 (the main session reconciles the contracts), else the fallback."""
    if RL is not None and hasattr(RL, name) and os.environ.get("READS_B_USE_LIB") == "1":     # pragma: no cover
        return getattr(RL, name)
    return globals()["_" + name]


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
            pdata = self.ctx.pickdata(p)
            self.set_off(p, pdata)
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
            self._c5[key] = _lib("c5_status")(self.ctx, p, arm, size)
        return self._c5[key]

    def tk(self, pick, arm, size=XC.SIZE_Q) -> dict:
        """Trade keys of any row (count class): per entered trade q, t_sig, coin, side, state, hold_h, win, reason, comp, lev, fill / exit
        times and the pick's tf. No money."""
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
               "comp": acc["tr_comp"].astype(np.int64), "lev": acc["tr_lev"].astype(float), "fill_ts": fill,
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
        fr = _lib("excursions")(self.ctx, p, _lib("c4_trade_frame")(self.ctx, p, acc))
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
KEEP = ("g", "W", "w0", "w_end", "max_dd", "counts", "reasons", "hold_h", "tr_coin", "tr_side", "tr_fill", "tr_exit", "tr_pnl", "tr_reason")


def _rerun_keep(st: _State, rid: str, p: dict, pdata, arm: str, part: str, scale: float, offered=None, S=None) -> dict:
    """C2: one re-run of the pinned kernel (period 'select'); only the reduced arrays are kept."""
    res = XC.rerun(st.ctx, pdata, arm, scale, offered=offered, S=S)
    s = MT.summarize(res, st.ctx.edges)
    keep = {k: np.asarray(s[k]) for k in KEEP}
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


def _pre_x002(st: _State, p: dict, pdata) -> None:
    off = pdata.offered("select", st.ctx.market)
    for c, sym in enumerate(st.syms):
        offm = XC.mask_offered(off, off["coin"] != c)
        for arm in _arms_money(st.ctx, p["pool"]):
            _rerun_keep(st, "X-002", p, pdata, arm, sym, XC.SIZE_Q, offered=offm)
    _save_reduced(st, "X-002", p)


def _pre_x005(st: _State, p: dict, pdata) -> None:
    off = pdata.offered("select", st.ctx.market)
    offm = XC.mask_offered(off, ~XC.is_weekend(off["close"]))
    for arm in _arms_money(st.ctx, p["pool"]):
        _rerun_keep(st, "X-005", p, pdata, arm, "noweekend", XC.SIZE_Q, offered=offm)
    _save_reduced(st, "X-005", p)


def _cost_S(market, c: float) -> np.ndarray:
    """X-041: market.S(0.25) with taker S[0], slippage S[1], round trip S[5] and maker S[19] times c."""
    S0 = market.S(XC.SIZE_Q)
    return XC.settings_copy(market, XC.SIZE_Q, {i: float(S0[i]) * c for i in (0, 1, 5, 19)})


def _x041_mults(st: _State) -> tuple:
    return tuple(c for c in COST_MULTS if not (c == 1.5 and "X-041 c = 1.5" in st.dropped))


def _pre_x041(st: _State, p: dict, pdata) -> None:
    for c in _x041_mults(st):
        S = _cost_S(st.ctx.market, c)
        for arm in _arms_money(st.ctx, p["pool"]):
            _rerun_keep(st, "X-041", p, pdata, arm, f"c{c:g}", XC.SIZE_Q, S=S)
    _save_reduced(st, "X-041", p)


def _small_S(market, scale: float) -> np.ndarray:
    """X-043: market.S(scale) with the starting wallet S[10] = 1,000 and nothing else changed (the bust line S[9] stays $10)."""
    S0 = market.S(scale)
    if float(S0[10]) != 5000.0 or float(S0[9]) != XC.BUST_W:
        raise AssertionError("X-043: the base settings do not start at $5,000 with the $10 bust line")
    return XC.settings_copy(market, scale, {10: START_SMALL})


def _x043_sizes(st: _State) -> tuple:
    return tuple(s for s in RX.SIZE_TAG if not (s == XC.SIZE_LIVE and "X-043 live size" in st.dropped))


def _pre_x043(st: _State, p: dict, pdata) -> None:
    for scale in _x043_sizes(st):
        S = _small_S(st.ctx.market, scale)
        for arm in _arms_money(st.ctx, p["pool"]):
            _rerun_keep(st, "X-043", p, pdata, arm, "w1000", scale, S=S)
    _save_reduced(st, "X-043", p)


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


def _pre_x026(st: _State, p: dict, pdata) -> None:
    ctx, mk = st.ctx, st.ctx.market
    off = pdata.offered("select", mk)
    S = mk.S(XC.SIZE_Q)
    tg = pdata.targets(off)
    for arm in _arms_money(ctx, p["pool"]):
        acc = XC.account(ctx, p, arm, XC.SIZE_Q)
        v = KX.variant_by_id(arm)
        qs = np.flatnonzero(st.c5(p, arm, XC.SIZE_Q) == 0)
        W = _wallet_before(acc, off["fill"][qs]) if len(qs) else np.zeros(0)
        ok = _sizeable(mk, S, off, qs, W, KX.exit_of_pick(p, v)[0])
        r, hold = [], []
        for q, w in zip(qs[ok], W[ok]):
            c = int(off["coin"][q])
            tp = float(tg[q]) if arm in ("F11.b", "F12.b") else float("nan")
            out = KX.simulate_trade(mk, pdata, v, off, int(q), XC.SIZE_Q, "select", equity=float(w), tp_price=tp)[0]
            if int(out[2]) == KX.R_REJECT:
                raise AssertionError(f"X-026 {p['id']} {arm}: a sizeable signal was rejected by the kernel")
            a = int(mk.starts[c])
            tsp = mk.cat["ts"][a:int(mk.period_end("select")[c])]
            r.append(float(out[0]) / float(w))
            hold.append((int(tsp[int(out[1])]) - int(off["fill"][q])) / 3_600_000.0)
        st.extra[("X-026", p["id"], arm)] = {"q": qs[ok], "W": W[ok], "r": np.asarray(r, float), "hold_h": np.asarray(hold, float),
                                             "n_skipped": np.int64(len(qs)), "n_sizeable": np.int64(int(ok.sum()))}
    _save_reduced(st, "X-026", p)


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


PRE = {"X-002": _pre_x002, "X-005": _pre_x005, "X-026": _pre_x026, "X-041": _pre_x041, "X-043": _pre_x043}


def _prepass(st: _State, reads: list) -> None:
    need = [r for r in RERUN_READS if r in reads and r in PRE and r not in st.dropped]
    for p in st.ctx.picks:
        try:
            pdata = st.ctx.pickdata(p)
            st.set_off(p, pdata)
            if p["id"] in st.dup:
                _dup_statuses(st, p, pdata)
        except Exception as exc:                                   # noqa: BLE001
            st.errors.setdefault("*", f"{type(exc).__name__}: {str(exc)[:200]}")
            continue
        for rid in need:
            if rid in st.errors:
                continue
            try:
                PRE[rid](st, p, pdata)
            except Exception as exc:                               # noqa: BLE001
                st.errors[rid] = f"{type(exc).__name__}: {str(exc)[:200]}"
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
                out[rid] = _clean(res)
            except Exception as exc:                               # noqa: BLE001
                out[rid] = OrderedDict([("read", rid), ("title", TITLES[rid]), ("error", f"{type(exc).__name__}: {str(exc)[:300]}")])
    finally:
        ctx.__dict__.pop("_reads_b", None)
    return out
