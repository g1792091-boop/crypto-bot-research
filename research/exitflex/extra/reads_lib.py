"""Read-level conventions of the extra reads that common.py leaves out (research/exitflex/PREREG_EXITFLEX_EXTRA.md E.2: C4, C5, C9),
shared by reads_a.py (tier A) and reads_b.py (tier B), and the format of a read's result.

  coins(ctx)                                  the coins of the pin in league order (C1).
  arm_rows(ctx, pool) / money_rows(ctx, pool) E.1 item 8 rows (E0 first, select.json's order) / the rows that may carry money (C3, E.1 item 4).
  offered(ctx, pick)                          the pick's offered table of the select period (one PickData per pick, the table cached).
  sig_minutes(ctx, pick)                      per offered signal the fill minute e, its ts and the no-fill flag, by kernel._entry_index's rule.
  c5_status(ctx, pick, arm, size)             C5: status 0-4 of every offered signal rebuilt from the step-1 arrays by the kernel's walk.
  c5_audit(ctx, picks, arms, sizes)           C5 audit: real re-runs (C2) give the rebuilt status and the step-1 tr_* arrays exactly.
  c4_trade_frame(ctx, pick, acc)              C4: per entered trade q, t_sig, e, x (every row); fill, Rd, Wb, _size, x, l, R, ROE (money rows).
  c4_match(acc_v, acc_e0)                     C4 / X-027: an arm's trades against E0's by the entry key (coin, side, fill): SAME, EXIT, NEW, DROP.
  excursions(ctx, pick, frame)                C4: best and worst Rn0 / ROE0 over the 1m highs and lows of minutes e..x-1 plus the exit price.
  open_dd_range(frame, exc, w0)               X-019's open-position drawdown range (MDD_low, MDD_high) of one account (X-047 quotes it).
  cut_column(ctx, coin, col)                  one column of the select cut's 1m file (column c included), A5-checked and cached.
  realised_wallet(acc, t)                     the wallet just before fill time t: every exit before t plus a RULE or RAND exit at t (X-025).
  sizeable(ctx, pick, arm, size)              X-025 (c1)/(c2): per skipped signal the realised wallet W and whether kernel._size fits (money rows).
  entry_ceiling(ctx, pick, size, plus_ms)     X-025 (f): the most entries any bar-close rule can make, from E0's account.
  c9_split(ctx, pool, arm, key_fn, size)      C9: split table by any key: counts, win share, hold, reasons; money columns only where allowed.
  new_result(read_id, tier, title)            the dict every read returns (public / private / md / csv / headline / accounts ...).
  ds_public(obj)                              main session decision (a): strip offered / no_fill / after_bust keys of a DeepSeek row, then C8.
  row_rule_problems / md_rule_problems        no money key on a 선택 불가 row of a committed json / csv; no 선택 불가 id on a Korean page.
  prior(ctx, read_id) / cap_dropped(ctx, p)   an earlier read's result in this run / whether the E.5 cap dropped a part.
  fmt_* / md_table / W_KO                     Korean page formatting (C12 units, C14 k/n shares, C7 marks) and the warning sentences.

Read results (``new_result``): ``public`` = {"core": {...}, "ds": {"pool": "ds", ...}} goes into extra_reads.json (core money only on E0 and
choosable rows; the DeepSeek part count class only, through ``ds_public``); ``private`` = DeepSeek money for ds_private/extra_reads_ds.json;
``md`` / ``md_appendix`` the Korean lines (tier A: body / appendix; tier B: appendix); ``md_private`` / ``md_private_appendix`` the private
report's parts 핵심 / 부록; ``csv`` rows {read, pool, arm, ...count columns} of all 89 rows; ``headline[pool][key] = {"public": str | None,
"private": str | None}`` the sentences X-046 quotes (keys in HEADLINE_KEYS). Nothing here prints a figure.
"""

from __future__ import annotations

import copy
import math
import os
import re
import sys
from collections import OrderedDict

import numpy as np
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common as XC  # noqa: E402
from common import DX, KX, MT  # noqa: E402,F401

_size = KX._size                                      # the pinned kernel's sizing (fullgrid kernel._size), called inside numba below

# ====================================================================================================== tiers (E.3, main session at O8)
BODY_ORDER = ("X-046", "X-024", "X-025", "X-027", "X-047", "X-014", "X-001", "X-037")      # E.3: the body of EXTRA_READS_KO.md
TIER_A = BODY_ORDER
TIER_B = ("X-002", "X-004", "X-005", "X-008", "X-011", "X-015", "X-016", "X-017", "X-018", "X-021", "X-026", "X-028", "X-029", "X-030",
          "X-031", "X-033", "X-034", "X-038", "X-039", "X-041", "X-043")
TIER_C = ("X-003", "X-006", "X-007", "X-009", "X-010", "X-013", "X-019", "X-020", "X-022", "X-023", "X-032", "X-035", "X-036", "X-042",
          "X-044", "X-045")
DROP_REASON_C = "tier C, dropped at O8 for time (E.0 item 2 a)"
TITLE_KO = {"X-001": "코인별 성적표", "X-014": "한 달 눈금: 월 배수 분포", "X-024": "봉 종류별 (단타 15분·30분 묶음 먼저)",
            "X-025": "신호는 어디로 갔나 (놓친 신호와 최대 진입 수)", "X-027": "이긴 이유 나누기 (청산을 잘해서인가, 진입이 달라져서인가)",
            "X-037": "기간을 나눠도 나은가 (운 눈금 포함)", "X-046": "한 장 요약 (먼저 볼 숫자 5개, 주의 6개)",
            "X-047": "한 줄 성적표 (두 분의 말로)"}
# X-046 quotes these sentences of other reads (result["headline"][pool][key] = {"public": str | None, "private": str | None}); a missing
# key prints '-' with the read id. 'public' goes on the committed page (for DeepSeek it must hold no money: C8, C14), 'private' into the
# private report's part 핵심 (DeepSeek only).
HEADLINE_KEYS = {"X-016": "x5", "X-021": "one_account", "X-025": "funnel", "X-034": "cost_month", "X-041": "cost_2x", "X-043": "verdict",
                 "X-037": "yardstick", "X-047": "e0_growth"}

# ====================================================================================================== C1 scope, rows
REASON_COLS = ("TP", "SL", "LOCK", "RULE", "LIQ", "END")
REASON_CODE = {n: MT.REASONS.index(n) for n in MT.REASONS}
HOLD_SHARE_H = (4, 8, 18)
Q15_ON = ("1h", "4h")                                  # q15 variants equal their base on 15m and 30m picks (5.1)


def coins(ctx) -> tuple:
    """C1: the coins of the pin in league order (data_x symbols)."""
    return tuple(s for s in DX.SYMBOLS if s in (ctx.pin.get("coins") or {}))


def arm_rows(ctx, pool: str) -> list:
    """E.1 item 8: E0 first, then select.json's order (choosable first; canonical without select.json)."""
    return XC.rows_order(ctx, pool)


def money_rows(ctx, pool: str) -> list:
    """C3 / E.1 item 4: the rows that may carry money: E0 and the pool's choosable ids, in row order."""
    return [a for a in arm_rows(ctx, pool) if XC.money_allowed(ctx, pool, a)]


def q15_base(vid: str) -> str | None:
    """The base id of a q15 variant ('F1.w3.a.q15' -> 'F1.w3.a'), else None."""
    return vid[:-4] if vid.endswith(".q15") else None


def _cache(ctx, name: str, maxlen: int = 0) -> OrderedDict:
    d = ctx.__dict__.get(name)
    if d is None:
        d = ctx.__dict__[name] = OrderedDict()
    if maxlen:
        while len(d) > maxlen:
            d.popitem(last=False)
    return d


def prior(ctx, read_id: str):
    """An earlier read's result in this run (reads.py stores every finished result in ctx.xr_results), or None."""
    return (ctx.__dict__.get("xr_results") or {}).get(read_id)


def cap_dropped(ctx, part: str) -> bool:
    """E.5: True when the cap dropped this part (a name of common.CAP_DROP_ORDER) in this run."""
    return part in (ctx.__dict__.get("xr_cap_dropped") or set())


def pool_accounts(ctx, pool: str, arm: str, size: float = XC.SIZE_Q) -> list:
    """The step-1 accounts (common.account) of an arm over the pool's picks, in pick order."""
    return [XC.account(ctx, p, arm, size) for p in ctx.pool_picks(pool)]


# ====================================================================================================== offered signals and fill minutes
def _pickdata(ctx, pick):
    """One PickData per pick (the last one kept): ``ctx.make_pickdata(pick)`` when a test sets it, else ctx.pickdata (the cut, C2)."""
    p = ctx.pick(pick)
    last = ctx.__dict__.get("_xr_pd")
    if last is not None and last[0] == p["id"]:
        return last[1]
    mk = ctx.__dict__.get("make_pickdata")
    pdata = mk(p) if mk is not None else ctx.pickdata(p)
    ctx.__dict__["_xr_pd"] = (p["id"], pdata)
    return pdata


def offered(ctx, pick) -> dict:
    """The pick's offered signals of the select period (PickData.offered: coin, close (= t_sig), side, atr, best, i0, fill, state, tp_idx,
    lvl), read-only, cached per pick."""
    p = ctx.pick(pick)
    c = _cache(ctx, "_xr_off")
    if p["id"] not in c:
        off = _pickdata(ctx, p).offered("select", ctx.market)
        if len(off["close"]) and int(np.max(off["close"])) >= XC.SELECT_HI:
            raise AssertionError(f"{p['id']}: an offered signal at or after 2024-01-01 (E.1 item 3)")
        off = {k: np.array(v) for k, v in off.items()}
        for v in off.values():
            v.flags.writeable = False
        c[p["id"]] = off
    return c[p["id"]]


def sig_minutes(ctx, pick) -> dict:
    """Per offered signal (kernel_x.account_x's rule): e = kernel._entry_index(ts_coin, close + 60,000 - bar_ms) on the coin's minutes before
    the period end (index inside the coin), t_fill = ts[e], nofill = no fill minute before the period's last minute (status 3)."""
    p = ctx.pick(pick)
    c = _cache(ctx, "_xr_sigmin")
    if p["id"] not in c:
        c[p["id"]] = _sig_minutes_of(ctx, offered(ctx, p))
    return c[p["id"]]


def _sig_minutes_of(ctx, off: dict) -> dict:
    mk = ctx.market
    pend = mk.period_end("select")
    n = len(off["close"])
    e = np.full(n, -1, np.int64)
    t_fill = np.full(n, -1, np.int64)
    nofill = np.ones(n, bool)
    for ci in np.unique(off["coin"]).tolist():
        sel = np.flatnonzero(off["coin"] == ci)
        tsc = mk.cat["ts"][mk.starts[ci]:pend[ci]]
        j = np.searchsorted(tsc, off["close"][sel] + (60_000 - mk.bar_ms) - 60_000, side="left") + 1
        ok = j < len(tsc) - 1
        e[sel[ok]] = j[ok]
        t_fill[sel[ok]] = tsc[j[ok]]
        nofill[sel[ok]] = False
    out = {"e": e, "t_fill": t_fill, "nofill": nofill}
    for v in out.values():
        v.flags.writeable = False
    return out


def coin_ts(ctx, ci: int) -> np.ndarray:
    """The 1m ts of coin index ``ci`` (all minutes of the cut)."""
    mk = ctx.market
    return mk.cat["ts"][mk.starts[ci]:mk.ends[ci]]


# ====================================================================================================== C5 status
@njit(cache=False)
def _c5_walk(sig_coin, t_fill, nofill, tr_coin, tr_fill, tr_exit, tr_free, tr_open, tr_pnl, w0, s9):
    n = len(sig_coin)
    m = len(tr_coin)
    status = np.zeros(n, np.int8)
    q_of = np.full(m, -1, np.int64)
    busy = -1
    entered_at = -1
    bust = False
    wallet = w0
    k = 0
    for q in range(n):
        if nofill[q]:
            status[q] = 3
            continue
        tf = t_fill[q]
        if bust:
            status[q] = 4
            continue
        if tf <= busy or tf == entered_at:
            status[q] = 0
            continue
        if k < m and tr_coin[k] == sig_coin[q] and tr_fill[k] == tf:
            status[q] = 1
            q_of[k] = q
            busy = tr_exit[k] - 1 if tr_free[k] else tr_exit[k]
            if tr_open[k]:
                busy = 2 ** 62
            entered_at = tf
            wallet += tr_pnl[k]
            k += 1
            if s9 > 0 and wallet < s9:
                bust = True
        else:
            status[q] = 2
    return status, q_of, k


def _same_trades(acc: dict, res) -> list:
    """The tr_* arrays of a re-run equal the step-1 file's (w_end to 1e-9); the names that differ."""
    s = MT.summarize(res, MT.month_edges("select"))
    bad = [k for k in ("tr_coin", "tr_side", "tr_fill", "tr_exit", "tr_reason", "tr_pnl", "tr_lev", "tr_xpx", "tr_comp", "counts", "reasons")
           if k in acc and not np.array_equal(np.asarray(s[k]), np.asarray(acc[k]))]
    if abs(float(s["w_end"]) - float(acc["w_end"])) > 1e-9:
        bad.append("w_end")
    return bad


def c5_status(ctx, pick, arm: str, size: float = XC.SIZE_Q, acc: dict | None = None, off: dict | None = None) -> dict:
    """C5: the status of every offered signal (0 skipped while holding, 1 entered, 2 rejected, 3 no fill, 4 after bust) rebuilt from the
    step-1 file and the offered table by the kernel's walk; e_q by kernel._entry_index; after a RULE or RAND exit busy_until = exit - 1 ms.
    Asserted: every step-1 trade matched in order; offered, entered and the counts of 0, 2, 3 and 4 equal the file's. A pick whose offered
    signals share (coin, fill minute) uses a real re-run (C2) instead, whose trades must equal the file's. Returns {status, q (offered index
    of each trade), t_sig, t_fill, e, rerun}; cached. ``acc`` / ``off`` replace the file and the table (tests)."""
    p = ctx.pick(pick)
    key = (p["id"], arm, float(size))
    cache = _cache(ctx, "_xr_c5", 8192)
    if acc is None and off is None and key in cache:
        return cache[key]
    acc = XC.account(ctx, p, arm, size) if acc is None else acc
    own_off = off is None
    off = offered(ctx, p) if own_off else off
    sm = sig_minutes(ctx, p) if own_off else _sig_minutes_of(ctx, off)
    S = ctx.market.S(size)
    if float(acc["w0"]) != float(S[10]):
        raise AssertionError(f"{p['id']} {arm}: w0 differs from S[10]")
    cnt = {n: MT.count(acc, n) for n in MT.COUNT_NAMES}
    if cnt["offered"] != len(off["close"]):
        raise AssertionError(f"{p['id']} {arm}: offered {len(off['close'])} != the file's {cnt['offered']}")
    fill_rows = ~sm["nofill"]
    keys = off["coin"][fill_rows] * (1 << 50) + sm["t_fill"][fill_rows]
    dup = len(keys) != len(np.unique(keys))
    rsn = np.asarray(acc["tr_reason"])
    if dup:                                           # C5: such a pick uses a real re-run
        res = XC.rerun(ctx, _pickdata(ctx, p), arm, size, offered=dict(off) if not own_off else None)
        bad = _same_trades(acc, res)
        if bad:
            raise AssertionError(f"{p['id']} {arm}: the re-run differs from the step-1 file in {bad}")
        status = np.asarray(res.status, np.int8)
        q_of = np.flatnonzero(status == 1)
    else:
        status, q_of, k = _c5_walk(off["coin"].astype(np.int64), sm["t_fill"], sm["nofill"], acc["tr_coin"].astype(np.int64),
                                   acc["tr_fill"].astype(np.int64), acc["tr_exit"].astype(np.int64),
                                   (rsn == KX.R_RULE) | (rsn == KX.R_RAND), rsn == KX.R_OPEN, acc["tr_pnl"].astype(float),
                                   float(S[10]), float(S[9]))
        if k != len(acc["tr_pnl"]) or np.any(q_of < 0):
            raise AssertionError(f"{p['id']} {arm}: a step-1 trade is not matched in order by the C5 walk")
    got = {n: int((status == c).sum()) for c, n in enumerate(XC.STATUS)}
    want = {"skipped": cnt["skipped"], "entered": cnt["entered"], "rejected": cnt["rejected"], "no_fill": cnt["no_fill"],
            "after_bust": cnt["after_bust"]}
    if got != want:
        raise AssertionError(f"{p['id']} {arm} {size}: C5 status counts differ from the file's")
    out = {"status": np.asarray(status, np.int8), "q": np.asarray(q_of, np.int64), "t_sig": np.asarray(off["close"], np.int64),
           "t_fill": np.asarray(sm["t_fill"]), "e": np.asarray(sm["e"]), "rerun": bool(dup)}
    for v in out.values():
        if isinstance(v, np.ndarray):
            v.flags.writeable = False
    if own_off:
        cache[key] = out
    return out


C5_AUDIT_ARMS = ("E0", "F12.a")


def c5_audit(ctx, picks=None, arms=C5_AUDIT_ARMS, sizes=(XC.SIZE_Q, XC.SIZE_LIVE), save: bool = True) -> dict:
    """C5 audit: per pick, arm and size a real re-run (C2: kernel_x.simulate with the full offered table and an unchanged S copy) gives the
    rebuilt status and the step-1 tr_* arrays identically (w_end to 1e-9). Reduced arrays (status, w_end) go to reduced/c5audit/.
    Returns {accounts, bad: [...], bytes}; the caller stops the stage when bad is not empty (14)."""
    picks = list(picks if picks is not None else ctx.picks)
    n, bad, nbytes = 0, [], 0
    for p in picks:
        p = ctx.pick(p)
        pdata = _pickdata(ctx, p)
        for arm in arms:
            for size in sizes:
                acc = XC.account(ctx, p, arm, size)
                st = c5_status(ctx, p, arm, size)
                res = XC.rerun(ctx, pdata, arm, size, offered=dict(offered(ctx, p)), S=XC.settings_copy(ctx.market, size))
                n += 1
                diff = _same_trades(acc, res)
                if not np.array_equal(np.asarray(res.status, np.int8), st["status"]):
                    diff.append("status")
                if diff:
                    bad.append(f"{p['id']} {arm} {size}: {','.join(diff)}")
                if save:
                    path = XC.save_reduced(ctx, p, "c5audit", size, {"status": np.asarray(res.status, np.int8),
                                                                     "w_end": np.float64(res.wallet)}, part=arm.replace(".", "_"))
                    nbytes += os.path.getsize(path)
    return {"accounts": n, "bad": bad, "bytes": nbytes}


# ====================================================================================================== C4 trade record
@njit(cache=False)
def _size_batch(S, brs, coin, W, side, fill, stop, atr, best, qty_steps, min_notionals):
    n = len(coin)
    ok = np.zeros(n, np.bool_)
    lev = np.zeros(n)
    margin = np.zeros(n)
    qty = np.zeros(n)
    liq = np.zeros(n)
    for i in range(n):
        c = coin[i]
        o_, lv, mg, q_, lq = _size(S, brs[c], W[i], side[i], fill[i], stop[i], atr[i], best[i], qty_steps[c], min_notionals[c])
        ok[i] = o_
        lev[i] = lv
        margin[i] = mg
        qty[i] = q_
        liq[i] = lq
    return ok, lev, margin, qty, liq


def size_at(ctx, size: float, coin, W, side, fill, stop, atr, best) -> tuple:
    """kernel._size for many (coin, wallet, side, fill, stop, ATR14, best) at once: (ok, lev, margin, qty, liq) arrays."""
    mk = ctx.market
    f = lambda a, t: np.ascontiguousarray(np.asarray(a, t))  # noqa: E731
    return _size_batch(mk.S(size), mk.brs, f(coin, np.int64), f(W, float), f(side, np.int64), f(fill, float), f(stop, float), f(atr, float),
                       f(best, np.bool_), np.asarray(mk.qty_steps, float), np.asarray(mk.min_notionals, float))


def _stop_atr(pick: dict, arm: str) -> float:
    return float(KX.exit_of_pick(pick, KX.variant_by_id(arm))[0])


def c4_trade_frame(ctx, pick, acc: dict) -> dict:
    """C4 trade record of one account (``acc`` = common.account): per entered trade in exit order q (the offered index from C5), t_sig =
    off.close[q], e and x (positions of tr_fill and tr_exit in the coin's 1m ts, asserted exact), coin, side, fill_ts, exit_ts, reason,
    hold_h, win. On a money row (acc['money_ok']) also raw = o[e], fill = raw (1 + side S[1]), Rd = stop_atr x off.atr[q], Wb (cumsum of
    [S[10], tr_pnl][:-1]), kernel._size's (lev, margin, qty, liq) with ok and lev == tr_lev asserted, pnl, xpx, x = pnl / Wb, l (sum asserted
    to ln(w_end / w0) within 1e-9), R = pnl / (qty Rd), ROE = pnl / margin. Cached per (pick, arm, size)."""
    p = ctx.pick(pick)
    arm, size = acc["arm"], float(acc["size"])
    key = (p["id"], arm, size)
    cache = _cache(ctx, "_xr_c4", 1024)
    if key in cache:
        return cache[key]
    st = c5_status(ctx, p, arm, size)
    off = offered(ctx, p)
    q = st["q"]
    coin = np.asarray(acc["tr_coin"], np.int64)
    side = np.asarray(acc["tr_side"], np.int64)
    fi, ex = np.asarray(acc["tr_fill"], np.int64), np.asarray(acc["tr_exit"], np.int64)
    if not (np.array_equal(off["coin"][q], coin) and np.array_equal(off["side"][q], side) and np.array_equal(st["t_fill"][q], fi)):
        raise AssertionError(f"{p['id']} {arm}: C4 matching of trades to offered signals failed")
    e = np.asarray(st["e"][q], np.int64)
    x = np.zeros(len(q), np.int64)
    for ci in np.unique(coin).tolist():
        sel = np.flatnonzero(coin == ci)
        ts = coin_ts(ctx, ci)
        xi = np.searchsorted(ts, ex[sel], side="left")
        if np.any(xi >= len(ts)) or not np.array_equal(ts[np.minimum(xi, len(ts) - 1)], ex[sel]) or not np.array_equal(ts[e[sel]], fi[sel]):
            raise AssertionError(f"{p['id']} {arm}: a fill or exit time is not a minute of the coin")
        x[sel] = xi
    rsn = np.asarray(acc["tr_reason"], np.int64)
    pnl = np.asarray(acc["tr_pnl"], float)
    fr = {"pick": p["id"], "pool": p["pool"], "arm": arm, "size": size, "money_ok": bool(acc["money_ok"]), "q": q,
          "t_sig": np.asarray(off["close"][q], np.int64), "e": e, "x": x, "coin": coin, "side": side, "fill_ts": fi, "exit_ts": ex,
          "reason": rsn, "hold_h": (ex - fi) / XC.HOUR_MS, "win": pnl > 0, "state": np.asarray(off["state"][q], np.int64)}
    if acc["money_ok"]:
        mk = ctx.market
        S = mk.S(size)
        if float(acc["w0"]) != float(S[10]):
            raise AssertionError(f"{p['id']} {arm}: w0 differs from S[10]")
        raw = mk.cat["o"][mk.starts[coin] + e] if len(q) else np.zeros(0)
        fill = raw * (1 + side * S[1])
        atr = np.asarray(off["atr"][q], float)
        Rd = _stop_atr(p, arm) * atr
        Wb = np.cumsum(np.r_[S[10], pnl])[:-1]
        ok, lev, margin, qty, liq = size_at(ctx, size, coin, Wb, side, fill, raw - side * Rd, atr, off["best"][q])
        if not ok.all() or not np.array_equal(lev, np.asarray(acc["tr_lev"], float)):
            raise AssertionError(f"{p['id']} {arm} {size}: C4 sizing differs from the kernel's (ok / lev)")
        l = np.log(np.maximum(Wb + pnl, 1e-12) / Wb)
        if abs(float(l.sum()) - math.log(max(float(acc["w_end"]), 1e-12) / float(acc["w0"]))) > 1e-9:
            raise AssertionError(f"{p['id']} {arm}: C4 sum of l_i differs from ln(w_end / w0)")
        fr.update(raw=raw, fill=fill, atr=atr, Rd=Rd, Wb=Wb, lev=lev, margin=margin, qty=qty, liq=liq, pnl=pnl,
                  xpx=np.asarray(acc["tr_xpx"], float), x_ret=pnl / Wb, l=l, R=pnl / (qty * Rd), ROE=pnl / margin,
                  w0=float(acc["w0"]), w_end=float(acc["w_end"]))
    for v in fr.values():
        if isinstance(v, np.ndarray):
            v.flags.writeable = False
    cache[key] = fr
    return fr


SAME, EXIT, NEW = 0, 1, 2


def _entry_keys(acc: dict) -> np.ndarray:
    fi = np.asarray(acc["tr_fill"], np.int64)
    return (fi << 4) | (np.asarray(acc["tr_coin"], np.int64) << 1) | (np.asarray(acc["tr_side"], np.int64) > 0).astype(np.int64)


def c4_match(acc_v: dict, acc_e0: dict) -> dict:
    """X-027 / C4: the trades of an arm against E0's on the same pick and size by the entry key (tr_coin, tr_side, tr_fill), unique per
    account (asserted). Per V trade the E0 index (-1 none) and the class SAME (0: same key, exit minute and reason), EXIT (1: same key, other
    exit or reason) or NEW (2: key not in E0); per E0 trade drop (its key is not a V key); the counts n_v, n_e0, n_same, n_exit, n_new,
    n_drop. EXIT + NEW equals metrics.changed_trades (asserted)."""
    kv, ke = _entry_keys(acc_v), _entry_keys(acc_e0)
    if len(np.unique(kv)) != len(kv) or len(np.unique(ke)) != len(ke):
        raise AssertionError("C4: the entry key (coin, side, fill) is not unique in an account")
    j = np.full(len(kv), -1, np.int64)
    same = np.zeros(len(kv), bool)
    if len(ke) and len(kv):
        order = np.argsort(ke, kind="stable")
        pos = np.minimum(np.searchsorted(ke[order], kv), len(ke) - 1)
        hit = ke[order][pos] == kv
        j = np.where(hit, order[pos], -1).astype(np.int64)
        jj = np.maximum(j, 0)
        same = hit & (np.asarray(acc_v["tr_exit"]) == np.asarray(acc_e0["tr_exit"])[jj]) \
            & (np.asarray(acc_v["tr_reason"]) == np.asarray(acc_e0["tr_reason"])[jj])
    hit = j >= 0
    cls = np.where(~hit, NEW, np.where(same, SAME, EXIT)).astype(np.int8)
    drop = ~np.isin(ke, kv)
    out = {"e0_idx": j.astype(np.int64), "cls": cls, "drop": drop, "n_v": int(len(kv)), "n_e0": int(len(ke)), "n_same": int((cls == SAME).sum()),
           "n_exit": int((cls == EXIT).sum()), "n_new": int((cls == NEW).sum()), "n_drop": int(drop.sum())}
    if out["n_exit"] + out["n_new"] != MT.changed_trades(acc_v, acc_e0):
        raise AssertionError("C4: EXIT + NEW differs from the contract's trades changed")
    return out


# ====================================================================================================== excursions (C4)
@njit(cache=False)
def _seg_minmax(h, l, a, b):
    n = len(a)
    hi = np.full(n, -np.inf)
    lo = np.full(n, np.inf)
    for i in range(n):
        for j in range(a[i], b[i]):
            if h[j] > hi[i]:
                hi[i] = h[j]
            if l[j] < lo[i]:
                lo[i] = l[j]
    return hi, lo


def excursions(ctx, pick, frame: dict) -> dict:
    """C4 excursions of a money frame: over the 1m last-price highs and lows of minutes e..x - 1 (the exit minute's own range is never used)
    plus the exit price xpx (for LIQ, R and ROE replace the exit term): Rn0(P) = (side (P - fill) - fill S[5]) / Rd and ROE0(P) = lev
    (side (P / fill - 1) - S[5]); best and worst of each. Funding is not included. Returns R_best, R_worst, ROE_best, ROE_worst, fav_px,
    adv_px (NaN when the range is empty)."""
    if not frame["money_ok"]:
        raise XC.Refused("excursions are money (C8): E0 and choosable rows only")
    mk = ctx.market
    S = mk.S(frame["size"])
    base = np.asarray(mk.starts, np.int64)[frame["coin"]] if len(frame["coin"]) else np.zeros(0, np.int64)
    hi, lo = _seg_minmax(mk.cat["h"], mk.cat["l"], base + frame["e"], base + frame["x"])
    side, fill, Rd, lev = frame["side"], frame["fill"], frame["Rd"], frame["lev"]
    empty = frame["x"] <= frame["e"]
    fav = np.where(side > 0, hi, lo)
    adv = np.where(side > 0, lo, hi)
    rn = lambda P: (side * (P - fill) - fill * S[5]) / Rd  # noqa: E731
    roe = lambda P: lev * (side * (P / fill - 1.0) - S[5])  # noqa: E731
    liq = frame["reason"] == KX.R_LIQ
    xr = np.where(liq, frame["R"], rn(frame["xpx"]))
    xo = np.where(liq, frame["ROE"], roe(frame["xpx"]))
    with np.errstate(invalid="ignore"):
        rb, rw = np.where(empty, xr, np.maximum(rn(fav), xr)), np.where(empty, xr, np.minimum(rn(adv), xr))
        ob, ow = np.where(empty, xo, np.maximum(roe(fav), xo)), np.where(empty, xo, np.minimum(roe(adv), xo))
    return {"R_best": rb, "R_worst": rw, "ROE_best": ob, "ROE_worst": ow, "fav_px": np.where(empty, np.nan, fav),
            "adv_px": np.where(empty, np.nan, adv)}


def open_dd_range(frame: dict, exc: dict, w0: float) -> tuple:
    """X-019's range of one account: U_i = Wb_i + margin_i max(-1, worst ROE_i), H_(i-1) = max(w0, Wb_1..Wb_i); MDD_low = max_i 1 - U_i /
    H_(i-1); MDD_high = max_i 1 - U_i / max(H_(i-1), Wb_i + margin_i best ROE_i). (0, 0) without trades."""
    if not len(frame["Wb"]):
        return 0.0, 0.0
    Wb, mg = frame["Wb"], frame["margin"]
    U = Wb + mg * np.maximum(-1.0, exc["ROE_worst"])
    H = np.maximum.accumulate(np.maximum(Wb, w0))
    top = np.maximum(H, Wb + mg * exc["ROE_best"])
    return max(0.0, float(np.max(1 - U / H))), max(0.0, float(np.max(1 - U / top)))


def cut_column(ctx, coin: str, col: str) -> np.ndarray:
    """One column of the select cut's 1m file of ``coin`` (columns ts, o, h, l, c, v, mo, mh, ml, mc, fund; 'c' is not in the Market),
    with assert_no_minute_at_or_after on its ts (A5). Cached, read-only."""
    cache = _cache(ctx, "_xr_cut", 24)
    key = (coin, col)
    if key not in cache:
        if not ctx.cut_dir:
            raise XC.Refused("no verified cut folder in this context")
        with np.load(os.path.join(ctx.cut_dir, "1m", f"{coin}.npz")) as z:
            DX.assert_no_minute_at_or_after({coin: {"ts": z["ts"]}}, DX.SELECT_CUT_MS)
            a = np.array(z[col])
        a.flags.writeable = False
        cache[key] = a
    return cache[key]


# ====================================================================================================== X-025 helpers (shared with X-026)
def realised_wallet(acc: dict, t) -> np.ndarray:
    """The realised wallet just before fill time(s) t: w0 plus every trade that exited before t, plus a RULE or RAND exit at t (its minute
    is free); the kernel's sequential sum."""
    t = np.asarray(t, np.int64)
    ex = np.asarray(acc["tr_exit"], np.int64)
    cum = np.cumsum(np.r_[float(acc["w0"]), np.asarray(acc["tr_pnl"], float)])
    k = np.searchsorted(ex, t, side="left")
    rsn = np.asarray(acc["tr_reason"])
    kk = np.minimum(k, max(len(ex) - 1, 0))
    at = (k < len(ex)) & (ex[kk] == t) & np.isin(rsn[kk], (KX.R_RULE, KX.R_RAND)) if len(ex) else np.zeros(len(t), bool)
    return cum[k + at.astype(np.int64)]


def _sizeable_at(ctx, p: dict, size: float, q, W) -> np.ndarray:
    off, sm, mk = offered(ctx, p), sig_minutes(ctx, p), ctx.market
    q = np.asarray(q, np.int64)
    coin, side = off["coin"][q], off["side"][q]
    raw = mk.cat["o"][np.asarray(mk.starts, np.int64)[coin] + sm["e"][q]] if len(q) else np.zeros(0)
    fill = raw * (1 + side * mk.S(size)[1])
    stop = raw - side * _stop_atr(p, "E0") * off["atr"][q]
    return size_at(ctx, size, coin, W, side, fill, stop, off["atr"][q], off["best"][q])[0]


def sizeable(ctx, pick, arm: str, size: float = XC.SIZE_Q) -> dict:
    """X-025 (c1)/(c2) (money, C8: E0 and choosable rows only): for each skipped signal q (status 0) the account's realised wallet W just
    before its fill and whether kernel._size(S, brs[coin], W, side, fill = o[e](1 + side S[1]), stop = o[e] - side stop_atr ATR14, ATR14,
    best, qty_step, min_notional) fits. {q, W, sizeable}."""
    p = ctx.pick(pick)
    if not XC.money_allowed(ctx, p["pool"], arm):
        raise XC.Refused(f"sizeable flags are money (C8): not on {arm} in {p['pool']}")
    st = c5_status(ctx, p, arm, size)
    q = np.flatnonzero(st["status"] == 0)
    acc = XC.account(ctx, p, arm, size)
    W = realised_wallet(acc, st["t_fill"][q])
    return {"q": q, "W": W, "sizeable": _sizeable_at(ctx, p, size, q, W)}


@njit(cache=False)
def _ceiling_walk(ok, nofill, t_fill, nxt):
    busy = -1
    n = 0
    for q in range(len(ok)):
        if nofill[q] or t_fill[q] <= busy or not ok[q]:
            continue
        n += 1
        busy = nxt[q] - 1
    return n


def entry_ceiling(ctx, pick, size: float = XC.SIZE_Q, plus_ms: int | None = None) -> int:
    """X-025 (f) (money: E0's wallet): walk the offered list; count a signal that is sizeable at E0's realised wallet and fills after
    busy-until; then busy-until = (the ts of the minute kernel._entry_index(ts, C0 + plus_ms), at least e + 1; the period-end minute when
    beyond the data) - 1 ms. ``plus_ms`` = the pick's bar (default) or 15 minutes (q15 on 1h / 4h picks)."""
    p = ctx.pick(pick)
    off, sm, mk = offered(ctx, p), sig_minutes(ctx, p), ctx.market
    acc = XC.account(ctx, p, "E0", size)
    n = len(off["close"])
    fill_q = np.flatnonzero(~sm["nofill"])
    ok = np.zeros(n, bool)
    ok[fill_q] = _sizeable_at(ctx, p, size, fill_q, realised_wallet(acc, sm["t_fill"][fill_q]))
    dt = DX.TF_MS[p["tf"]] if plus_ms is None else int(plus_ms)
    pend = mk.period_end("select")
    nxt = np.zeros(n, np.int64)
    for ci in np.unique(off["coin"]).tolist():
        sel = np.flatnonzero(off["coin"] == ci)
        tsc = mk.cat["ts"][mk.starts[ci]:pend[ci]]
        m = np.searchsorted(tsc, off["close"][sel] + dt - mk.bar_ms, side="left") + 1
        m = np.where(m >= len(tsc), len(tsc) - 1, m)
        m = np.maximum(m, np.minimum(sm["e"][sel] + 1, len(tsc) - 1))
        nxt[sel] = tsc[m]
    return int(_ceiling_walk(ok, sm["nofill"], sm["t_fill"], nxt))


# ====================================================================================================== C9 split tables
def _sig_cols(off: dict, sm: dict, p: dict) -> dict:
    n = len(off["close"])
    return {"coin": off["coin"], "side": off["side"], "t_sig": off["close"], "state": off["state"].astype(np.int64), "i0": off["i0"],
            "fill": sm["t_fill"], "tf": np.full(n, p["tf"], dtype=object), "pick": np.full(n, p["id"], dtype=object)}


def trade_cols(ctx, pick, arm: str, size: float = XC.SIZE_Q) -> dict:
    """The per-trade columns a C9 key reads: the signal's columns through C5's q (coin, side, t_sig, state, i0, fill, tf, pick) plus exit,
    hold_h, reason, win, year (UTC of the exit) and month (select month of the exit)."""
    p = ctx.pick(pick)
    st = c5_status(ctx, p, arm, size)
    acc = XC.account(ctx, p, arm, size)
    sc = _sig_cols(offered(ctx, p), sig_minutes(ctx, p), p)
    out = {k: v[st["q"]] for k, v in sc.items()}
    ex = np.asarray(acc["tr_exit"], np.int64)
    out.update(exit=ex, hold_h=np.asarray(acc["hold_h"], float), reason=np.asarray(acc["tr_reason"], np.int64),
               win=np.asarray(acc["tr_pnl"]) > 0, year=ex.astype("datetime64[ms]").astype("datetime64[Y]").astype(int) + 1970,
               month=XC.month_index(ex, ctx.edges))
    return out


def _keys(key_fn, cols: dict) -> np.ndarray:
    k = key_fn(cols)
    k = np.asarray(k, dtype=object) if not isinstance(k, np.ndarray) or k.dtype.kind not in "iub" else k
    return k


def c9_split(ctx, pool: str, arm: str, key_fn, size: float = XC.SIZE_Q, buckets=None, min_n: int = XC.THIN_MIN) -> dict:
    """C9 split columns for key K (``key_fn(cols) -> bucket per row``; cols as ``trade_cols``, or the signal columns alone, where a key that
    reads only coin, side, t_sig, state, i0, fill, tf or pick is a signal-level key), pool P, arm A, at ``size``:
      cells (count class, every arm): n_off (signal-level keys only; the same for every arm), n_ent, n_skip and n_rej (C5; signal-level keys
      only), n (closed trades), wins, win_share, hold_median, share_gt8h, reasons (shares of TP SL LOCK RULE LIQ END), flag (C7);
      money (only where money_allowed, else None): mean_R and se_R, c = 100 x mean over picks of (sum of l_i in b) / 36, dc = c_A - c_E0
      (sum of dc = 100 M_P(A) asserted to 1e-9), share = c / sum c under C17 (None otherwise).
    ``buckets`` fixes the order (every key must lie in it); default: the keys seen, sorted. Returns {pool, arm, size, cells, money, n_cells,
    n_thin}."""
    picks = ctx.pool_picks(pool)
    money = XC.money_allowed(ctx, pool, arm)
    per = []
    signal_level = True
    for p in picks:
        off, sm = offered(ctx, p), sig_minutes(ctx, p)
        st = c5_status(ctx, p, arm, size)
        try:
            ks = _keys(key_fn, _sig_cols(off, sm, p))
        except KeyError:
            ks, signal_level = None, False
        kt = _keys(key_fn, trade_cols(ctx, p, arm, size))
        rec = {"p": p, "ks": ks, "st": st["status"], "kt": kt, "acc": XC.account(ctx, p, arm, size)}
        if money:
            rec["fr"] = c4_trade_frame(ctx, p, rec["acc"])
            e0 = XC.account(ctx, p, "E0", size)
            rec["kt0"] = _keys(key_fn, trade_cols(ctx, p, "E0", size))
            rec["l0"] = c4_trade_frame(ctx, p, e0)["l"]
        per.append(rec)
    seen = set()
    for r in per:
        seen |= set(np.asarray(r["kt"]).tolist())
        if signal_level and r["ks"] is not None:
            seen |= set(np.asarray(r["ks"]).tolist())
        if money:
            seen |= set(np.asarray(r["kt0"]).tolist())
    if buckets is None:
        buckets = sorted(seen, key=lambda b: (str(type(b)), b))
    else:
        buckets = list(buckets)
        out_of = seen - set(buckets)
        if out_of:
            raise ValueError(f"C9: keys outside the buckets: {sorted(map(str, out_of))[:5]}")
    cells, mon = [], [] if money else None
    for b in buckets:
        n_off = n_ent = n_skip = n_rej = 0
        n = wins = 0
        hold, rcount = [], np.zeros(len(REASON_COLS), np.int64)
        Rs, sums, sums0 = [], [], []
        for r in per:
            if signal_level:
                ins = np.asarray(r["ks"] == b, bool) if len(r["ks"]) else np.zeros(0, bool)
                n_off += int(ins.sum())
                n_ent += int((ins & (r["st"] == 1)).sum())
                n_skip += int((ins & (r["st"] == 0)).sum())
                n_rej += int((ins & (r["st"] == 2)).sum())
            it = np.asarray(r["kt"] == b, bool) if len(r["kt"]) else np.zeros(0, bool)
            a = r["acc"]
            closed = it & (np.asarray(a["tr_reason"]) != KX.R_OPEN)
            n += int(closed.sum())
            wins += int((closed & (np.asarray(a["tr_pnl"]) > 0)).sum())
            hold.append(np.asarray(a["hold_h"], float)[closed])
            rr = np.asarray(a["tr_reason"])[closed]
            rcount += np.array([int((rr == REASON_CODE[x]).sum()) for x in REASON_COLS])
            if money:
                Rs.append(r["fr"]["R"][it])
                sums.append(float(r["fr"]["l"][it].sum()))
                it0 = np.asarray(r["kt0"] == b, bool) if len(r["kt0"]) else np.zeros(0, bool)
                sums0.append(float(r["l0"][it0].sum()))
        hh = np.concatenate(hold) if hold else np.zeros(0)
        cell = {"bucket": b, "n_off": n_off if signal_level else None, "n_ent": n_ent if signal_level else None,
                "n_skip": n_skip if signal_level else None, "n_rej": n_rej if signal_level else None, "n": n, "wins": wins,
                "win_share": wins / n if n else None, "hold_median": float(np.median(hh)) if len(hh) else None,
                "share_gt8h": float((hh > 8).mean()) if len(hh) else None,
                "reasons": {x: (int(c) / n if n else None) for x, c in zip(REASON_COLS, rcount)}, "flag": XC.c7_mark(n, None, min_n)}
        cells.append(cell)
        if money:
            RR = np.concatenate(Rs) if Rs else np.zeros(0)
            c_a, c_0 = XC.c9_contrib(sums), XC.c9_contrib(sums0)
            mon.append({"bucket": b, "mean_R": float(RR.mean()) if len(RR) else None, "se_R": XC.se(RR) if len(RR) > 1 else None,
                        "c": c_a, "dc": c_a - c_0})
    if money and picks:
        tot = sum(m["dc"] for m in mon)
        M = XC.pooled_M(ctx, pool, arm, size)
        if abs(tot - 100.0 * M) > 1e-9:
            raise AssertionError(f"C9: the sum of dc differs from 100 M_P ({pool} {arm})")
        csum = sum(m["c"] for m in mon)
        sh = XC.c17_shares([m["c"] / 100.0 for m in mon], csum / 100.0)
        for i, m in enumerate(mon):
            m["share"] = None if sh is None else float(sh[i])
    n_thin = sum(1 for c in cells if c["n"] and c["n"] < min_n)
    return {"pool": pool, "arm": arm, "size": size, "cells": cells, "money": mon, "n_cells": len(cells), "n_thin": n_thin,
            "signal_level": signal_level}


# ====================================================================================================== results, guards
def jsonable(obj):
    """Plain JSON values: numpy scalars and arrays to Python, NaN and inf to None, tuples to lists, keys to str."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(float(obj)) else None
    return obj


def new_result(read_id: str, tier: str, title: str | None = None) -> dict:
    """The dict every read returns (see the module docstring)."""
    return {"id": read_id, "tier": tier, "title": title or TITLE_KO.get(read_id, read_id), "public": {"core": {}, "ds": {"pool": "ds"}},
            "private": {}, "md": [], "md_appendix": [], "md_private": [], "md_private_appendix": [], "csv": [],
            "headline": {"core": {}, "ds": {}}, "accounts": 0, "bytes": 0, "parts_dropped": [], "notes": []}


DS_STRIP = re.compile(r"offered|n_off|no_?fill|after_?bust|take_rate", re.I)


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if not (isinstance(k, str) and DS_STRIP.search(k))}
    if isinstance(obj, (list, tuple)):
        return [_strip(v) for v in obj]
    return obj


def ds_strip_problems(obj, where: str = "", ds: bool = False) -> list:
    """Decision (a) on a committed object: no dict tagged pool 'ds' (or inside one) holds a non-empty offered / no_fill / after_bust key."""
    bad = []
    if isinstance(obj, dict):
        ds = ds or obj.get("pool") == "ds"
        for k, x in obj.items():
            if ds and isinstance(k, str) and DS_STRIP.search(k) and x not in (None, ""):
                bad.append(f"{where}{k}")
            bad += ds_strip_problems(x, f"{where}{k}.", ds)
    elif isinstance(obj, (list, tuple)):
        for i, x in enumerate(obj):
            bad += ds_strip_problems(x, f"{where}[{i}].", ds)
    return bad


def ds_public(obj: dict) -> dict:
    """Main session decision (a): a DeepSeek row of a committed extra output carries neither offered nor no_fill (with entered, skipped and
    rejected they would give after_bust): keys matching DS_STRIP are removed at every depth, the row is tagged pool 'ds', and it must pass
    common.ds_row_check (C8). Returns the stripped copy."""
    out = _strip(copy.deepcopy(obj))
    out["pool"] = "ds"
    XC.ds_row_check(out)
    return out


def _is_money_key(k) -> bool:
    if not isinstance(k, str):
        return False
    return XC._money_key(k) or k in ("mean_R", "se_R", "share_growth", "contrib", "dd", "ceiling")


def row_rule_problems(ctx, obj, path: str = "") -> list:
    """E.1 item 4 on a committed json / csv object: a dict naming an arm (key 'arm') that is 선택 불가 in its pool (key 'pool') holds no money
    key at any depth; nor does any dict keyed by such an arm id inside a pool's part."""
    bad = []

    def money_inside(v, where):
        out = []
        if isinstance(v, dict):
            for k, x in v.items():
                if _is_money_key(k) and x not in (None, ""):
                    out.append(f"{where}{k}")
                out += money_inside(x, f"{where}{k}.")
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                out += money_inside(x, f"{where}[{i}].")
        return out

    def walk(v, where, pool):
        if isinstance(v, dict):
            pool = v.get("pool", pool) if v.get("pool") in XC.POOLS else pool
            arm = v.get("arm")
            if isinstance(arm, str) and pool in XC.POOLS and not XC.money_allowed(ctx, pool, arm):
                bad.extend(f"{arm} ({pool}): {m}" for m in money_inside({k: x for k, x in v.items() if k not in ("arm", "pool")}, where))
                return
            for k, x in v.items():
                if pool in XC.POOLS and isinstance(k, str) and re.match(r"^F\d+h?\.[\w.]+$", k) and not XC.money_allowed(ctx, pool, k):
                    bad.extend(f"{k} ({pool}): {m}" for m in money_inside(x, f"{where}{k}."))
                else:
                    walk(x, f"{where}{k}.", k if k in XC.POOLS else pool)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                walk(x, f"{where}[{i}].", pool)

    walk(obj, path, None)
    return bad


_ID = re.compile(r"(?<![\w.=])(F\d+h?\.[A-Za-z0-9_.]*[A-Za-z0-9])")


def md_rule_problems(ctx, md: str) -> list:
    """E.1 item 4 on a committed Korean page: under a pool heading ('코어' / '딥시크' in a heading of level 2 or more) no id of a variant that
    is 선택 불가 in that pool appears; outside pool sections no id that is 선택 불가 in both pools. '= F3.a' marks (C13) are labels."""
    bad, pool = [], None
    allowed = {p: set(ctx.choosable.get(p, set())) for p in XC.POOLS}
    for ln in md.splitlines():
        s = ln.lstrip()
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            if "딥시크" in s:
                pool = "ds"
            elif "코어" in s:
                pool = "core"
            elif level <= 2:
                pool = None
        for vid in _ID.findall(ln.replace("= F3.a", "").replace("= F3.b", "")):
            ok = vid in allowed[pool] if pool else (vid in allowed["core"] or vid in allowed["ds"])
            if not ok:
                bad.append(f"{vid}: {ln.strip()[:60]}")
    return bad


# ====================================================================================================== Korean formatting (C7, C12, C14)
W_KO = dict(XC.W)
# E.1 item 2's box W1 and the warnings X-046 names without verbatim text in E.3 (W18, W22-W24): composed at O8 by this file's code.
W_KO.update({
    "W1": "이 문서의 표는 모두 참고용입니다. 픽·코인·봉·롱숏·요일·시간대·장세·변동성·크기·비용 수준별로 청산을 따로 고르지 않으며, "
          "고르는 기준은 고르기 표(SELECT_KO)의 기준뿐입니다.",
    "W18": "이 풀의 돈과 관련된 숫자는 이 문서에 적지 않습니다. 소유자 두 분께 대화로만 보여 드리는 비공개 보고서에 있습니다. "
           "아래 주의 문장은 그대로 적용됩니다.",
    "W22": "88개 중에서 기준을 넘은 방식은 실력이 아니라 운이 좋아서 넘었을 수도 있습니다(승자의 저주). 같은 방식이 앞으로는 2021~2023년보다 "
           "낮게 나오는 것이 보통입니다.",
    "W23": "2024~2026년도 완전히 처음 보는 기간이 아닙니다. 전체 격자와 리그에서 이 기간의 숫자 일부를 이미 보았습니다(계약의 알려진 한계 1, 2).",
    "W24": "비용(수수료·미끄러짐·펀딩)이 오르면 성적이 줄어듭니다. 짧게 드는 청산일수록 사고파는 횟수가 늘어 비용의 영향이 큽니다.",
})
W_DS = {"W0": XC.W["W0"], "W1": W_KO["W1"], "W22": "88개 중에서 기준을 넘은 방식은 운이 좋아서 넘었을 수도 있습니다(승자의 저주).",
        "W23": W_KO["W23"], "W9": "1/1 크기는 1/4 크기보다 크게 흔들리고 계좌가 망가질 수도 있습니다. 연구와 리그는 1/4 크기로 판정합니다.",
        "W24": W_KO["W24"], "W11": XC.W["W11"]}
TAG = XC.TAG_TABLE
EMPTY = XC.EMPTY


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and not math.isfinite(x))


def fmt_n(x) -> str:
    """An integer count with thousands separators."""
    return EMPTY if _bad(x) else f"{int(round(float(x))):,}"


def fmt_f(x, nd: int = 2) -> str:
    return EMPTY if _bad(x) else f"{float(x):.{nd}f}"


def _z(v: float, nd: int) -> float:
    """No negative zero in print."""
    return 0.0 if round(v, nd) == 0 else v


def fmt_share(x, nd: int = 1) -> str:
    """A share as a percent (core pages only; C14: DeepSeek prints k/n)."""
    return EMPTY if _bad(x) else f"{_z(100.0 * float(x), nd):.{nd}f}%"


def fmt_kn(k, n) -> str:
    """C6 / C14: 'k/N'."""
    return EMPTY if _bad(k) or _bad(n) or not n else XC.k_of_n(k, n)


def fmt_growth(M, sign: bool = True) -> str:
    """C12: a monthly log level or difference as '%/월' = 100 (e^M - 1)."""
    if _bad(M):
        return EMPTY
    v = _z(XC.pct_month(float(M)), 2)
    return (f"{v:+.2f}" if sign else f"{v:.2f}") + XC.U_GROWTH


def fmt_contrib(logpart) -> str:
    """C12: an additive contribution '%/월 기여(근사)' (100 x the log part); the unit is printed in the column head."""
    return EMPTY if _bad(logpart) else f"{_z(XC.contrib_pct(float(logpart)), 2):+.2f}"


def fmt_x(m, nd: int = 2) -> str:
    """C12: a multiple 'x1.23'."""
    return EMPTY if _bad(m) else f"x{float(m):.{nd}f}"


def fmt_h(h) -> str:
    return EMPTY if _bad(h) else f"{float(h):.1f}시간"


def fmt_roe(r) -> str:
    """C12: ROE in % per trade."""
    return EMPTY if _bad(r) else f"{_z(100.0 * float(r), 1):+.1f}%"


def mark(n, n_picks=None, min_n: int = XC.THIN_MIN) -> str:
    """C7 flag in brackets for a table cell ('' when none)."""
    m = XC.c7_mark(n, n_picks, min_n) if n else ""
    return f" ({m})" if m and m != EMPTY else ""


def md_table(head: list, rows: list) -> list:
    """A Markdown table with the C2 tag line above it (E.1 item 2)."""
    out = [f"_{TAG}_", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


def pool_head(pool: str, n_picks: int, level: int = 3) -> str:
    """The pool heading of a read section (C14: the DeepSeek pool name appears only in a heading; the DeepSeek part comes last)."""
    return "#" * level + (f" 코어 ({n_picks}개 픽)" if pool == "core" else f" 딥시크 ({n_picks}개 픽)")


def arm_label(ctx, pool: str, arm: str, pick: dict | None = None) -> str:
    """The row label: 'E0 (지금 청산)' or the id with the q15 mark on 15m / 30m picks and the C13 mark on a one-pick cell."""
    if arm == "E0":
        return "E0 (지금 청산)"
    lab = arm
    if pick is not None:
        m = XC.c13_mark(pick, arm)
        if m:
            lab += f" ({m})"
    return lab
