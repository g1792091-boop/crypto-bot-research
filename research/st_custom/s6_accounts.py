"""Stage 6: account simulations (PREREG 'Accounts', addendum 1 seed 1,000 USD) for the default values, the friend's
values, the 3 pooled picks and the per-coin picks (main variant), per strategy x timeframe x period.

One position per coin; leverage L in 20/30/40/50 with the ladder at L; sizing 'owner' (margin = L% of the wallet) or
'risk1' (loss at the stop = 1% of the wallet); check mode 'house' (live sizing checks; failing signals skipped) or
'forced' (only the margin must be available; liquidation when the price trades through it); exchange minimums off/on.
Trade paths at L are computed once per signal (15m bars, liquidation price from the coin's first bracket tier).
DEVIATIONS.md I11.

    python3 -B research/st_custom/s6_accounts.py [procs]
"""
import heapq
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import s2_signals as S2  # noqa: E402

ACC_DIR = os.path.join(C.WORK, "accounts")
os.makedirs(ACC_DIR, exist_ok=True)
LEVS = (20, 30, 40, 50)
SEED = 1000.0
RUIN = 0.10
MINORDER = {"BTCUSD": (0.001, 100.0), "ETHUSD": (0.001, 20.0), "SOLUSD": (1.0, 5.0), "DOGEUSD": (1.0, 5.0),
            "LTCUSD": (0.001, 20.0), "BCHUSD": (0.001, 20.0), "XRPUSD": (0.1, 5.0)}
T0 = C.ts_ns("2020-01-01")
STEP = 15 * C.NS_MIN


def k_of(ts):
    return ((np.asarray(ts, np.int64) - T0) // STEP).astype(np.int64)


def first_tier_liq_frac(coin, side, L):
    """Isolated-margin liquidation distance (fraction of the fill) with the coin's first bracket tier (cum 0)."""
    t = C.BR[coin].tiers[0]
    qty, entry = 1.0, 100.0
    margin = qty * entry / L
    liq = C.liquidation_price(side, qty, entry, margin, t)
    return side * (entry - liq) / entry


def account_sets(strat, tf, picks):
    d = C.combo_index(strat, C.DEFAULT_IDX[strat])
    sets = {"default": {c: d for c in C.COINS}}
    if strat in C.FRIEND_IDX:
        f = C.combo_index(strat, C.FRIEND_IDX[strat])
        sets["friend"] = {c: f for c in C.COINS}
    g = picks[(picks.strategy == strat) & (picks.tf == tf) & (picks.variant == "main")]
    for r in g[g.scope == "pooled"].itertuples():
        sets[f"pick{r.rank}"] = {c: int(r.combo) for c in C.COINS}
    cp = g[g.scope == "coin"]
    if len(cp):
        sets["coinpicks"] = {r.coin: int(r.combo) for r in cp.itertuples()}
    return sets


def build_events(strat, tf, sets):
    """Per set: event table over all periods (sorted by entry): coin, ke, ks(signal), per, side, fill, risk, atr,
    and per L: kx, roe, R."""
    combos_by_coin = {}
    for s in sets.values():
        for coin, c in s.items():
            combos_by_coin.setdefault(coin, set()).add(c)
    paths = {}            # (coin, c) -> dict of arrays
    for ci, coin in enumerate(C.COINS):
        if coin not in combos_by_coin:
            continue
        z = np.load(os.path.join(C.OUTC_DIR, f"{coin}_{tf}.npz"))
        O = {k: z[k] for k in ("e", "atr", "valid")}
        b15 = C.load_bars(coin, "15m")
        bt = C.load_bars(coin, tf)
        per_codes = []
        for per in C.PERIOD_ORDER:
            p = S2.sig_path(coin, tf, per)
            lo = int(np.load(p)["lo"][0])
            codes, offs = C.load_signals(p, strat)
            per_codes.append((per, lo, codes, offs))
        rows = {}
        for c in combos_by_coin[coin]:
            gi_l, sd_l, pe_l = [], [], []
            for per, lo, codes, offs in per_codes:
                cc = codes[offs[c]:offs[c + 1]]
                gi_l.append(lo + cc // 2)
                sd_l.append(np.where(cc % 2 == 1, 1, -1))
                pe_l.append(np.full(len(cc), C.PERIOD_ORDER.index(per)))
            rows[c] = (np.concatenate(gi_l), np.concatenate(sd_l), np.concatenate(pe_l))
        # unique (bar, side) over the combos of this coin
        allk = np.unique(np.concatenate([g * 2 + (s > 0) for g, s, _p in rows.values()]))
        ug, us = allk // 2, np.where(allk % 2 == 1, 1, -1)
        e = O["e"][ug].astype(np.int64)
        atr = O["atr"][ug]
        res = {}
        for L in LEVS:
            lf = np.where(us > 0, first_tier_liq_frac(coin, 1, L), first_tier_liq_frac(coin, -1, L))
            r = C.run_scan(b15, e, us.astype(np.int64), np.full(len(ug), float(L)), lf, C.K_STOP * atr,
                           liq_touch=True)
            res[L] = r
        base = dict(ke=k_of(b15["ts"][e]), ks=k_of(bt["ts"][ug]), side=us, fill=res[20]["fill"],
                    risk=res[20]["risk"], atr=atr)
        for L in LEVS:
            base[f"kx{L}"] = k_of(b15["ts"][np.clip(res[L]["x"], 0, len(b15["ts"]) - 1)])
            base[f"roe{L}"] = res[L]["roe"]
            base[f"done{L}"] = res[L]["done"]
            base[f"liq{L}"] = res[L]["reason"] == 2
        for c, (g, s, pe) in rows.items():
            pos = np.searchsorted(allk, g * 2 + (s > 0))
            paths[(coin, c)] = dict({k: v[pos] for k, v in base.items()}, per=pe)
    ev = {}
    for name, s in sets.items():
        parts = []
        for coin, c in s.items():
            p = paths[(coin, c)]
            ci = C.COINS.index(coin)
            parts.append(pd.DataFrame(dict(p, coin=ci)))
        t = pd.concat(parts, ignore_index=True).sort_values(["ke", "coin"], kind="mergesort").reset_index(drop=True)
        ev[name] = t
    return ev


def simulate(t, L, sizing, mode, minorder):
    """One account over the event table t (one period). Returns metrics dict and the closed-trade curve."""
    W = SEED
    peak = SEED
    used = np.zeros(len(C.COINS))
    busy = np.full(len(C.COINS), -1, np.int64)
    heap = []
    curve_t, curve_w = [], []
    taken = skipped_busy = skipped_check = skipped_margin = skipped_min = liqs = 0
    streak = worst = 0
    ruin_at = None
    max_dd = 0.0
    rec_start = None
    longest_rec = 0
    ke, coin, side = t["ke"].to_numpy(), t["coin"].to_numpy(), t["side"].to_numpy()
    fill, risk, atr = t["fill"].to_numpy(), t["risk"].to_numpy(), t["atr"].to_numpy()
    kx, roe = t[f"kx{L}"].to_numpy(), t[f"roe{L}"].to_numpy()
    done, liq = t[f"done{L}"].to_numpy(), t[f"liq{L}"].to_numpy()
    fee, slip = C.TAKER, C.SLIP

    def close_until(k):
        nonlocal W, peak, streak, worst, max_dd, rec_start, longest_rec, ruin_at, liqs
        while heap and heap[0][0] < k:
            kx_, ci, pnl, margin, isliq = heapq.heappop(heap)
            W += pnl
            used[ci] -= margin
            liqs += isliq
            curve_t.append(kx_ + 1)
            curve_w.append(W)
            streak = streak + 1 if pnl < 0 else 0
            worst = max(worst, streak)
            if W > peak:
                if rec_start is not None:
                    longest_rec = max(longest_rec, kx_ + 1 - rec_start)
                    rec_start = None
                peak = W
            else:
                if rec_start is None and W < peak:
                    rec_start = kx_ + 1
                max_dd = max(max_dd, 1 - W / peak)
            if ruin_at is None and W < RUIN * SEED:
                ruin_at = kx_ + 1

    for j in range(len(ke)):
        if not done[j]:
            continue
        close_until(ke[j])
        if ruin_at is not None:
            break
        ci = coin[j]
        if busy[ci] >= ke[j]:
            skipped_busy += 1
            continue
        f = fill[j]
        sd = side[j]
        stop = f - sd * risk[j]          # risk = |fill - stop0|
        exit_px = stop * (1 - sd * slip)
        per_qty_loss = risk[j] + abs(stop - exit_px) + fee * f + fee * exit_px
        if sizing == "owner":
            margin = W * L / 100.0
            qty = margin * L / f
        else:
            qty = 0.01 * W / per_qty_loss
        cname = C.COINS[ci]
        if minorder:
            stp, mn = MINORDER[cname]
            qty = np.floor(qty / stp + 1e-9) * stp
        else:
            mn = 5.0
        notional = qty * f
        if qty <= 0 or notional < mn:
            skipped_min += 1
            continue
        margin = notional / L
        if mode == "house":
            br = C.BR[cname].for_notional(notional)
            if L > br.max_leverage:
                skipped_check += 1
                continue
            lp = C.liquidation_price(sd, qty, f, margin, br)
            buffer = max(C.S.liq_buffer_atr_mult * atr[j], C.S.liq_buffer_min_frac * f)
            if (stop - lp) * sd < buffer:
                skipped_check += 1
                continue
            if qty * per_qty_loss > C.S.max_loss_frac * W:
                skipped_check += 1
                continue
        if used.sum() + margin > W + 1e-9:
            skipped_margin += 1
            continue
        pnl = roe[j] * margin
        used[ci] += margin
        busy[ci] = kx[j]
        heapq.heappush(heap, (int(kx[j]), int(ci), float(pnl), float(margin), int(liq[j])))
        taken += 1
    close_until(np.iinfo(np.int64).max)
    if rec_start is not None and len(curve_t):
        longest_rec = max(longest_rec, curve_t[-1] - rec_start)
    return dict(final=W, mult=W / SEED, max_dd=max_dd, worst_streak=worst, longest_recovery_days=longest_rec / 96.0,
                ruin=ruin_at is not None, ruin_day=(None if ruin_at is None else
                                                    str(pd.Timestamp(T0 + ruin_at * STEP, tz="UTC").date())),
                trades=taken, skipped_busy=skipped_busy, skipped_check=skipped_check, skipped_margin=skipped_margin,
                skipped_min=skipped_min, liquidations=liqs), (np.array(curve_t), np.array(curve_w))


def job(args):
    strat, tf, picks = args
    path = os.path.join(ACC_DIR, f"{strat}_{tf}.csv")
    if os.path.exists(path):
        return strat, tf, "cached", 0
    t0 = time.time()
    try:
        os.nice(5)
    except OSError:
        pass
    sets = account_sets(strat, tf, picks)
    ev = build_events(strat, tf, sets)
    rows = []
    curves = {}
    for name, t in ev.items():
        for per in C.PERIOD_ORDER:
            a, b = C.PERIODS[per]
            ka, kb = int(k_of([C.ts_ns(a)])[0]), int(k_of([C.ts_ns(b)])[0])
            tp = t[(t["per"] == C.PERIOD_ORDER.index(per)) & (t["ks"] >= ka) & (t["ks"] < kb)]
            for L in LEVS:
                for sizing in ("owner", "risk1"):
                    for mode in ("house", "forced"):
                        for mo in (False, True):
                            m, (ct, cw) = simulate(tp, L, sizing, mode, mo)
                            rows.append(dict(strategy=strat, tf=tf, set=name, period=per, lev=L, sizing=sizing,
                                             mode=mode, minorder=mo, signals=len(tp), **m))
                            if mo and mode == "house":
                                curves[f"{name}|{per}|{L}|{sizing}"] = np.stack([ct, cw]) if len(ct) else \
                                    np.zeros((2, 0))
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    C.save_npz(os.path.join(ACC_DIR, f"{strat}_{tf}_curves.npz"), **curves)
    return strat, tf, f"{len(rows)} runs", round(time.time() - t0, 1)


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    picks = pd.read_csv(os.path.join(C.OUT, "picks.csv"))
    jobs = [(s, tf, picks) for s in C.STRATS for tf in C.TFS]
    with Pool(procs, maxtasksperchild=1) as p:
        for r in p.imap_unordered(job, jobs):
            C.log(*r)
