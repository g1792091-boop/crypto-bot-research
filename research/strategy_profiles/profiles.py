"""Strategy profile cards: what kind of strategy each of the 36 is, per timeframe.

    python3 research/strategy_profiles/profiles.py <signals_dir> [procs] [--out DIR] [--accounts CSV]

Outputs go to research/strategy_profiles/out/ and the account columns come from
research/paper_rules/out/accounts.csv unless ``--out`` / ``--accounts`` (or $PROFILES_OUT /
$PROFILES_ACCOUNTS) name others: a re-run on another signal cache (e.g. the Binance futures cache)
writes beside the original, e.g. out_binance/ with research/paper_rules/out_binance/accounts.csv.

``signals_dir`` holds the ``sig_<tf>_<coin>.npz`` files written by
``research/paper_rules/rules_bt.py signals`` (bars, ATR14 and every strategy's signal
array from the locked backtest code). Nothing is optimised or selected here: this
describes each strategy so the per-strategy specialist and the owners know what they
are looking at.

For every signal of every strategy (six coins, 2021-08-01 .. 2026-09-30, no account,
no position limit, fixed $1,000 equity for sizing) under the paper v3 rules:
entry at the next bar's open + slippage, stop 2 x ATR14, leverage from the same
``size_position`` tiers, stepped profit lock from ``paperbot.ladder``, real costs.

Per strategy x timeframe:
  style      share of signals that follow the last 20 bars' move (trend) or go against it
  horizon    mean net forward return after 1..128 bars: where it peaks, with a t-value
  exits      stop / lock / liquidation shares, hold time, time to best point, mean ROE
  hold more  for trades closed by the profit lock: the mean ROE change had they been held
             4, 16 or 64 bars longer (positive and clear = the ladder cuts winners early)
  accounts   the one-account results from research/paper_rules/out/accounts.csv (k = 2)
"""

from __future__ import annotations

import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))

import rules_bt as RB  # noqa: E402
from paperbot import sweepsig  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

TFS = ("5m", "15m", "30m", "1h", "4h")
HORIZONS = (1, 2, 4, 8, 16, 32, 64, 128)
K_STOP = 2.0
MOMENTUM_BARS = 20
HOLD_MORE = (4, 16, 64)
EQUITY = 1000.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
ACCOUNTS = os.path.join(ROOT, "research", "paper_rules", "out", "accounts.csv")
SOURCE = None           # set by the command line when --out / --accounts differ: recorded in the meta
REASONS = ("stop", "lock", "liquidation", "open")


# ------------------------------------------------------------------ sizing lookup
def _sizer(k_stop: float = K_STOP):
    """Leverage and liquidation distance by (side, ATR / price) for a k_stop x ATR stop.
    The default is the paper v3 stop; paperbot/agents/labtests.py passes the stop_atr variants."""
    cache = {}

    def lev_liq(side: int, atr_frac: float):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * RB.SETTINGS.slippage_frac)
            d = size_position(RB.SETTINGS, EQUITY, side, fill, raw - side * k_stop * a, "best", RB.BRACKETS,
                              atr=a, min_notional=RB.MIN_NOTIONAL)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return lev_liq


# ------------------------------------------------------------------ exits, vectorised over signals
def _scan(b, idx, side, lev, liq_frac, H, n, f_bar, k_stop=K_STOP, ladder=None):
    """Ladder exit for signals entering at idx+1, looking at most H bars ahead.
    Returns dict of arrays; ``done`` is False where no exit happened inside H bars.
    ``k_stop`` (initial stop, x ATR) and ``ladder`` (a paperbot.ladder.LadderSpec; None = the
    paper v3 ladder) default to the paper v3 rules; paperbot/agents/labtests.py varies them."""
    lad = RB.LADDER if ladder is None else ladder
    rt, fee, slip = RB.SETTINGS.round_trip_cost, RB.SETTINGS.taker_fee, RB.SETTINGS.slippage_frac
    m = len(idx)
    off = np.arange(1, H + 1)
    J = idx[:, None] + off[None, :]                       # bars after the signal bar
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    fill = raw * (1 + side * slip)
    stop0 = raw - side * k_stop * a
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fund = f_bar * off[None, :]
    fav = np.where(s == 1, h, -lo)                        # favourable extreme, sign-adjusted
    best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
    roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - rt - fund)
    first = lad.first_lock + lad.trigger_gap
    nstep = np.floor((roe_best - first) / lad.step + 1e-9)
    lock_roe = np.where(roe_best >= first - 1e-12, lad.first_lock + lad.step * nstep, np.nan)
    lock_px = fill[:, None] * (1 + s * (lock_roe / lev[:, None] + rt + fund))
    lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)       # sign-adjusted: higher = tighter
    lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
    stop_eff = np.maximum((side * stop0)[:, None], lock_cum)      # sign-adjusted
    adverse = np.where(s == 1, lo, -h)
    hit = (adverse <= stop_eff) & valid
    done = hit.any(axis=1)
    q = np.where(done, hit.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gap = (side * oq) <= (side * st)
    liq_gap = done & gap & ((side * oq) <= (side * liq))
    exit_raw = np.where(done, np.where(gap, oq, st), c[r, q])
    exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * slip))
    held = q + 1
    roe = lev * (side * (exit_px / fill - 1) - fee * (1 + exit_px / fill) - f_bar * held)
    roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
    is_lock = done & ~liq_gap & (side * st > side * stop0 + 1e-12)
    reason = np.where(~done, 3, np.where(liq_gap, 2, np.where(is_lock, 1, 0)))
    upto = np.arange(H)[None, :] <= q[:, None]
    mfe = np.where(upto, roe_best, -np.inf).max(axis=1)
    mfe_bar = np.where(upto, roe_best, -np.inf).argmax(axis=1) + 1
    return dict(done=done, q=q, held=held, roe=roe, reason=reason, mfe=mfe, mfe_bar=mfe_bar, fill=fill,
                exit_j=idx + held, exit_px=exit_px)


def _continuation(b, side, lev, fill, exit_j, exit_px, n, f_bar):
    """ROE change from holding HOLD_MORE bars longer instead of the lock exit (same fill,
    same exit costs, extra funding). NaN where the data ends first."""
    out = np.full((len(side), len(HOLD_MORE)), np.nan)
    for k, hm in enumerate(HOLD_MORE):
        j = exit_j + hm
        v = j < n
        later = b["c"][np.minimum(j, n - 1)] * (1 - side * RB.SETTINGS.slippage_frac)
        d = lev * (side * (later - exit_px) / fill - RB.SETTINGS.taker_fee * (later - exit_px) / fill - f_bar * hm)
        out[v, k] = d[v]
    return out


# ------------------------------------------------------------------ one timeframe x coin
def _job(args):
    tf, coin, sig_dir = args
    L = sweepsig.lib()
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    wins = {w: RB.window_bounds(L, b, tf, w) for w in RB.WINDOWS}
    lo_all, n_end = wins["is"][0], wins["cf"][1]
    sizer = _sizer()
    out = {}
    for key in (k for k in z.files if k.startswith("s__")):
        name = key[3:]
        sg = z[key]
        idx = np.nonzero(sg[lo_all:n_end - 1])[0] + lo_all
        a = b["atr"][idx]
        ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        side = sg[idx].astype(int)
        raw = b["o"][idx + 1]
        ll = np.array([sizer(int(s), float(x)) for s, x in zip(side, b["atr"][idx] / raw)]).reshape(-1, 2)
        lev, liq_frac = ll[:, 0], ll[:, 1]
        sized = lev > 0
        # forward net returns (price terms, round-trip cost included), sign-adjusted
        fwd = np.full((len(idx), len(HORIZONS)), np.nan)
        for k, hz in enumerate(HORIZONS):
            j = idx + hz
            v = j < n
            fwd[v, k] = side[v] * (b["c"][j[v]] / raw[v] - 1) - RB.SETTINGS.round_trip_cost
        mom = np.full(len(idx), np.nan)
        pj = idx - MOMENTUM_BARS
        v = pj >= 0
        mom[v] = np.sign(side[v] * (b["c"][idx[v]] - b["c"][pj[v]]))
        # ladder exits for the sized signals, in growing look-ahead passes
        res = {k: np.full(len(idx), np.nan) for k in ("held", "roe", "reason", "mfe", "mfe_bar")}
        more = np.full((len(idx), len(HOLD_MORE)), np.nan)
        todo = np.nonzero(sized)[0]
        for H in (64, 512, 4096):
            if not len(todo):
                break
            nxt = []
            step = max(32, 256_000 // H)
            for c0 in range(0, len(todo), step):
                sel = todo[c0:c0 + step]
                r = _scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar)
                last = H == 4096
                keep = r["done"] | last | (idx[sel] + H >= n - 1)
                for k in ("held", "roe", "reason", "mfe", "mfe_bar"):
                    res[k][sel[keep]] = r[k][keep]
                lk = keep & (r["reason"] == 1)
                if lk.any():
                    more[sel[lk]] = _continuation(b, side[sel][lk], lev[sel][lk], r["fill"][lk],
                                                  r["exit_j"][lk], r["exit_px"][lk], n, f_bar)
                nxt.append(sel[~keep])
            todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
        win = np.where(b["ts"][idx] < pd.Timestamp(RB.WINDOWS["cf"][0]).value, 0, 1)
        out[name] = dict(side=side.astype(np.int8), lev=lev.astype(np.int16), fwd=fwd.astype(np.float32),
                         mom=mom.astype(np.float32), win=win.astype(np.int8), more=more.astype(np.float32),
                         **{k: v.astype(np.float32) for k, v in res.items()})
    days = (n_end - lo_all) * L.tf_minutes(tf) / 1440.0
    return tf, coin, out, days


# ------------------------------------------------------------------ summary
def _t(x):
    x = x[np.isfinite(x)]
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else float("nan")


def summarise(tf: str, parts: list[dict], days: float, tf_min: int) -> dict:
    cat = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    n = len(cat["side"])
    sized = cat["lev"] > 0
    fwd_mean = np.nanmean(cat["fwd"], axis=0) if n else np.full(len(HORIZONS), np.nan)
    k_best = int(np.nanargmax(fwd_mean)) if n and np.isfinite(fwd_mean).any() else 0
    mom = cat["mom"][np.isfinite(cat["mom"])]
    rs = cat["reason"][sized]
    done = rs < 3
    roe = cat["roe"][sized]
    lock = rs == 1
    more = cat["more"][sized][lock]
    out = {
        "signals": int(n), "signals_per_day": n / days if days else None,
        "long_share": float((cat["side"] > 0).mean()) if n else None,
        "trend_share": float((mom > 0).mean()) if len(mom) else None,
        "fwd_mean_pct": {str(h): (None if not np.isfinite(v) else float(v * 100)) for h, v in zip(HORIZONS, fwd_mean)},
        "peak_horizon_bars": HORIZONS[k_best], "peak_horizon_hours": HORIZONS[k_best] * tf_min / 60,
        "peak_t": _t(cat["fwd"][:, k_best]) if n else None,
        "sized_share": float(sized.mean()) if n else None,
        "lev_mix": {str(x): int((cat["lev"] == x).sum()) for x in (50, 40, 30, 20)},
        "exit_share": {r: float((rs == i).mean()) if len(rs) else None for i, r in enumerate(REASONS)},
        "mean_roe": float(np.nanmean(roe[done])) if done.any() else None,
        "mean_roe_t": _t(roe[done]) if done.any() else None,
        "mean_roe_by_window": {w: (float(np.nanmean(roe[done & (cat["win"][sized] == i)]))
                                   if (done & (cat["win"][sized] == i)).any() else None)
                               for i, w in enumerate(RB.WINDOWS)},
        "win_rate": float((roe[done] > 0).mean()) if done.any() else None,
        "median_hold_hours": float(np.nanmedian(cat["held"][sized][done]) * tf_min / 60) if done.any() else None,
        "median_hours_to_best": float(np.nanmedian(cat["mfe_bar"][sized][done]) * tf_min / 60) if done.any() else None,
        "mean_best_roe": float(np.nanmean(cat["mfe"][sized][done])) if done.any() else None,
        "lock_exits": int(lock.sum()),
        "hold_more_roe": {str(h): (float(np.nanmean(more[:, k])) if np.isfinite(more[:, k]).any() else None)
                          for k, h in enumerate(HOLD_MORE)},
        "hold_more_t": {str(h): (_t(more[:, k]) if np.isfinite(more[:, k]).sum() > 2 else None)
                        for k, h in enumerate(HOLD_MORE)},
    }
    return out


def label(p: dict) -> dict:
    """Plain-Korean labels. Thresholds are descriptive, fixed here, not tuned."""
    ts = p["trend_share"]
    style = None if ts is None else ("추세 따라가기" if ts >= 0.6 else "되돌림 노리기" if ts <= 0.4 else "섞임")
    h = p["peak_horizon_hours"]
    clear = p["peak_t"] is not None and np.isfinite(p["peak_t"]) and p["peak_t"] >= 2.0
    hold = None if not clear else ("짧게 (1시간 이하)" if h <= 1 else "중간 (1~8시간)" if h <= 8 else "길게 (8시간 이상)")
    m, t = p["hold_more_roe"].get("16"), p["hold_more_t"].get("16")
    cuts = None if m is None or t is None or not np.isfinite(t) else bool(m > 0 and t >= 2.0)
    return {"style": style, "hold": hold or "뚜렷한 방향 없음 (비용 빼면 0 근처)", "ladder_cuts_early": cuts}


def main(sig_dir: str, procs: int = 4) -> None:
    L = sweepsig.lib()
    acc = pd.read_csv(ACCOUNTS)
    acc = acc[acc["k"] == K_STOP]
    profiles: dict = {}
    t0 = time.time()
    for tf in TFS:
        jobs = [(tf, c, sig_dir) for c in RB.COINS]
        with Pool(procs) as pool:
            got = pool.map(_job, jobs)
        days = got[0][3]
        names = list(got[0][2])
        for nm in names:
            p = summarise(tf, [g[2][nm] for g in got], days, L.tf_minutes(tf))
            a = acc[(acc["tf"] == tf) & (acc["strategy"] == nm)].set_index("window")
            p["account"] = {w: ({"final": float(a.loc[w, "final"]), "bust": bool(a.loc[w, "bust"]),
                                 "trades": int(a.loc[w, "trades"])} if w in a.index else None) for w in RB.WINDOWS}
            p["labels"] = label(p)
            profiles.setdefault(nm, {})[tf] = p
        print(f"{tf}: {len(names)} strategies, {time.time() - t0:.0f}s", flush=True)
    for nm, byt in profiles.items():
        ranked = sorted((tf for tf in byt if byt[tf]["mean_roe"] is not None and byt[tf]["signals"] >= 100),
                        key=lambda tf: -byt[tf]["mean_roe"])
        byt["_summary"] = {"least_bad_tf": ranked[0] if ranked else None, "tf_order": ranked,
                           "any_positive_mean_roe": any(byt[tf]["mean_roe"] > 0 for tf in ranked)}
    os.makedirs(OUT, exist_ok=True)
    meta = {"windows": RB.WINDOWS, "k_stop": K_STOP, "horizons": HORIZONS, "momentum_bars": MOMENTUM_BARS,
            "hold_more_bars": HOLD_MORE, "equity_for_sizing": EQUITY,
            "brackets": "example tiers (as in rules_bt)", "signal_lock": sweepsig.verify()["prereg_sha256_file"]}
    if SOURCE:
        meta["source"] = dict(SOURCE, signals_dir=os.path.abspath(sig_dir), accounts=ACCOUNTS, out=OUT)
    with open(os.path.join(OUT, "profiles.json"), "w") as fh:
        json.dump({"meta": meta, "profiles": profiles}, fh, indent=1, default=float)
    print("wrote", os.path.join(OUT, "profiles.json"))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="profiles.py")
    ap.add_argument("sig_dir")
    ap.add_argument("procs", nargs="?", type=int, default=4)
    ap.add_argument("--out", default=os.environ.get("PROFILES_OUT") or None,
                    help="output directory (default research/strategy_profiles/out, or $PROFILES_OUT)")
    ap.add_argument("--accounts", default=os.environ.get("PROFILES_ACCOUNTS") or None,
                    help="rules_bt accounts.csv to join (default research/paper_rules/out/accounts.csv, "
                         "or $PROFILES_ACCOUNTS)")
    a = ap.parse_args()
    if a.out:
        OUT = os.path.abspath(a.out)
    if a.accounts:
        ACCOUNTS = os.path.abspath(a.accounts)
    if a.out or a.accounts:
        SOURCE = {"note": "re-run with --out / --accounts (not the default profiles)"}
    main(a.sig_dir, a.procs)
