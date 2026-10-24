"""Verifier (look-ahead / time alignment / data errors) for the October numbers of B3 / B6 and a sample of B3 in
2024-01 .. 2026-10-05, by hand from raw 1m bars, without lb_core:
  * 1m data: the research grid (vwcommon via common.grid, first n_grid minutes only) and, from the rule bot's first
    live_bars minute on, the rule bot's own Binance 1m bars (live_bars.csv) -- checked equal on the overlap
  * higher bars: pandas resample (UTC bins); judge = paperbot.trendjudge.vote_arrays on the last 300 bars CLOSED at
    or before the signal time (vote3 for B3, OBV for B6), hold per htf; the same with the bar still open ('peek')
  * member signal recomputed on bars truncated at the signal bar
  * forced exit: first higher bar closing after the entry whose trailing-window raw == -side; first later opposite
    signal of the same member recomputed on truncated bars; outcome re-walked minute by minute with ComboLadder
Run (from this folder, no -I): python3 vlh_hand.py <trades_dir> <live_bars.csv> <variant> <n_conf_sample> [seed]"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "data"))
from common import *            # noqa: E402,F401,F403
from paperbot.ladder2 import ComboLadder   # noqa: E402
VDIR = os.path.dirname(os.path.abspath(__file__))   # common's HERE is the data folder

TD, LBF, VAR, NS = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
SEED = int(sys.argv[5]) if len(sys.argv) > 5 else 5
KIND = {"B3": "vote3", "B6": "obv", "B0": "vote3"}[VAR]
HTF_OF = {"30m": "1h", "1h": "4h", "4h": "1d"}
HOLD = {"1h": 2, "4h": 1, "1d": 1}
LAD = ComboLadder(first_lock=0.10, trigger_gap=0.01, step=0.05, next_trigger=0.15, next_gap=0.03)
E = libs()
TJ, fg, pi, run = E["TJ"], E["fg"], E["pi"], E["run"]
SETS = pd.read_csv(os.path.join(OUT, "signals", "names.csv"))
SET = dict(zip(SETS.name, SETS.set))
LBD = pd.read_csv(LBF, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])
FWD0 = FWD[0]

_M = {}


def minutes(coin):
    """1m o h l c v fund over T0.. : research grid (first n_grid minutes), then live_bars from its first minute."""
    if coin in _M:
        return _M[coin]
    g = grid(coin)
    ng = g["n_grid"]
    X = LBD[LBD.symbol == coin].sort_values("ts")
    X = X.drop_duplicates("ts")
    i0 = int((X.ts.iloc[0] - T0) // MIN)
    o, h, l, c, v = (g[k][:ng].copy() for k in ("o", "h", "l", "c", "v"))
    # overlap check (research grid vs the bot's own bars)
    ov = X[X.ts < T0 + ng * MIN]
    io = ((ov.ts.to_numpy() - T0) // MIN).astype(np.int64)
    dif = {k: float(np.nanmax(np.abs(arr[io] / ov[col].to_numpy() - 1))) for k, arr, col in
           (("o", o, "open"), ("h", h, "high"), ("l", l, "low"), ("c", c, "close"))}
    n = int((X.ts.iloc[-1] - T0) // MIN) + 1
    full = {k: np.full(n, np.nan) for k in ("o", "h", "l", "c", "v")}
    for k, arr in (("o", o), ("h", h), ("l", l), ("c", c), ("v", v)):
        full[k][:i0] = arr[:i0]
    ii = ((X.ts.to_numpy() - T0) // MIN).astype(np.int64)
    for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
        full[k][ii] = X[col].to_numpy(float)
    gaps = int(np.isnan(full["o"][i0:]).sum())
    fund = np.zeros(n)
    fund[:min(ng, n)] = g["fund"][:min(ng, n)]
    full["fund"] = fund
    full["cumf"] = np.cumsum(fund)
    full["i0"] = i0
    full["n"] = n
    _M[coin] = full
    print(coin, "grid vs live_bars on", len(ov), "overlap minutes, max rel diff", {k: f"{x:.1e}" for k, x in dif.items()},
          "live_bars from", pd.to_datetime(T0 + i0 * MIN, unit="ms"), "gaps after", gaps, flush=True)
    drop(coin)
    return full


_B = {}


def hbars(coin, tf):
    key = (coin, tf)
    if key not in _B:
        m = minutes(coin)
        idx = pd.to_datetime(T0 + np.arange(m["n"], dtype=np.int64) * MIN, unit="ms", utc=True)
        df = pd.DataFrame({"open": m["o"], "high": m["h"], "low": m["l"], "close": m["c"], "volume": m["v"]}, index=idx)
        rule = {"30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}[tf]
        r = df.resample(rule, label="left", closed="left", origin="epoch")
        out = pd.DataFrame({"open": r.open.first(), "high": r.high.max(), "low": r.low.min(), "close": r.close.last(),
                            "volume": r.volume.sum(), "cnt": r.close.count()})
        out = out[out.cnt == TF_MIN[tf]].drop(columns="cnt")
        out["ms"] = out.index.asi8 // 10**6
        out = out.reset_index(names="ts")
        out["ts"] = out["ts"].dt.tz_localize(None)
        _B[key] = out
    return _B[key]


def closes(df, tf):
    return df.ms.to_numpy(np.int64) + TF_MIN[tf] * MIN


def raw_of(arr):
    if KIND == "vote3":
        return TJ.raw_votes(arr, 3).astype(int)
    return np.asarray(arr["OBV"]).astype(int)


def judge_at(coin, htf, j):
    H = hbars(coin, htf)
    w = H.iloc[max(0, j - 299): j + 1][["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    if len(w) < 120:
        return np.nan, np.nan
    raw = raw_of(TJ.vote_arrays(w, fg, pi))
    h = HOLD[htf]
    d = int(raw[-1]) if (raw[-1] != 0 and (raw[-h:] == raw[-1]).all()) else 0
    return d, int(raw[-1])


def member(name, tf, coin, upto_close, nwin=1200):
    """+1 / -1 / 0 of the member at the bar closing at upto_close, on bars ENDING there (no later bar exists)."""
    Bf = hbars(coin, tf)
    bc = closes(Bf, tf)
    j = int(np.searchsorted(bc, upto_close))
    if j >= len(bc) or bc[j] != upto_close:
        return None
    w = Bf.iloc[max(0, j - nwin + 1): j + 1]
    df = as_chart(w[["ms", "open", "high", "low", "close", "volume"]].rename(columns={"ms": "ts"}).reset_index(drop=True), tf)
    if SET[name] == "core":
        run.M.clear()
        lg, sh = run.core_module(name).signals(df, tf)
        run.M.clear()
    else:
        ctx = None
        if coin != "BTCUSDT":
            Bb = hbars("BTCUSDT", tf)
            Bb = Bb[closes(Bb, tf) <= upto_close].iloc[-nwin:]
            ctx = {"BTCUSD": as_chart(Bb[["ms", "open", "high", "low", "close", "volume"]].rename(columns={"ms": "ts"}).reset_index(drop=True), tf)}
        lg, sh = run.ds_module().signals(df, tf, name, ctx=ctx, coin=coin[:-1], cache={})
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    return 1 if lg[-1] else (-1 if sh[-1] else 0)


def walk(m, e, s, lev, force):
    """net ROE, minutes, why (0 stop, 1 lock, 2 forced); stop -50 % net, ComboLadder locks armed from the next minute."""
    o, h, l, cumf = m["o"], m["h"], m["l"], m["cumf"]
    p0 = o[e]
    f0 = cumf[e - 1]
    best, lock, k = -9.0, None, 0
    while True:
        i = e + k
        if i >= m["n"] or not np.isfinite(o[i]):
            return np.nan, k, 3
        Fp, F = s * (cumf[i - 1] - f0), s * (cumf[i] - f0)
        net = lambda px, FF: lev * (s * (px / p0 - 1.0) - COST - FF)
        if k > 0 and lock is None and force >= 0 and i >= force:
            return max(net(o[i], F), -1.0), k, 2
        floor_roe = -0.5 if lock is None else max(-0.5, lock)
        adverse = l[i] if s > 0 else h[i]
        # the floor in price terms is set on the previous minute's funding (as the engine's level)
        if net(adverse, Fp) <= floor_roe + 1e-12:
            px_floor = p0 * (1 + s * (floor_roe / lev + COST + Fp))
            fill = px_floor if (s > 0 and o[i] > px_floor) or (s < 0 and o[i] < px_floor) else o[i]
            return max(net(fill, F), -1.0), k, (1 if lock is not None and lock > -0.5 else 0)
        fav = h[i] if s > 0 else l[i]
        b = net(fav, F)
        if b > best:
            best = b
            lk = LAD.lock_for(best)
            if lk is not None:
                lock = lk
        k += 1


def main():
    T = pd.read_csv(os.path.join(TD, f"trades_{VAR}.csv.gz"))
    F = T[(T.t >= FWD[0]) & (T.t < FWD[1])]
    C = T[(T.t >= ms("2024-01-01")) & (T.t < FWD[0])]
    C = C.sample(min(NS, len(C)), random_state=SEED) if NS > 0 else C.iloc[:0]
    S = pd.concat([F.assign(part="fwd"), C.assign(part="conf+late")]).sort_values("t").reset_index(drop=True)
    rows = []
    t0 = time.time()
    for q, r in S.iterrows():
        coin = COINS[int(r.coin)]
        m = minutes(coin)
        tf, htf = r.tf, HTF_OF[r.tf]
        t, e, side = int(r.t), int(r.e), int(r.side)
        H = hbars(coin, htf)
        hc = closes(H, htf)
        j = int(np.searchsorted(hc, t, side="right") - 1)
        d_cl, raw_cl = judge_at(coin, htf, j)
        d_pk, _ = judge_at(coin, htf, j + 1) if j + 1 < len(H) else (np.nan, np.nan)
        sig = member(r["name"], tf, coin, t)
        lev = 40.0 if coin == "BTCUSDT" else 30.0
        # judge exit: first higher bar closing after e with trailing-window raw == -side, scanned until the trade ends
        r0, k0, w0 = walk(m, e, side, lev, -1)                      # no forced exit: the longest possible life
        end = e + (k0 if np.isfinite(r0) else 3000)
        jm = -1
        for jj in range(j + 1, len(H)):
            cm = int((hc[jj] - T0) // MIN)
            if cm <= e:
                continue
            if cm > end:
                break
            _d, rw = judge_at(coin, htf, jj)
            if rw == -side:
                jm = cm
                break
        # own reverse: the member's next bar closes after e, each recomputed on truncated bars, until the end
        rm = -1
        Bf = hbars(coin, tf)
        bcf = closes(Bf, tf)
        lim = min(jm if jm >= 0 else end, end)
        for jj in range(int(np.searchsorted(bcf, t, side="right")), len(Bf)):
            cm = int((bcf[jj] - T0) // MIN)
            if cm > lim:
                break
            if member(r["name"], tf, coin, int(bcf[jj])) == -side:
                rm = cm
                break
        force = jm if rm < 0 else (rm if jm < 0 else min(jm, rm))
        roe, k, why = walk(m, e, side, lev, force)
        roe_o, k_o, why_o = walk(m, e, -side, lev, int(r.force))          # the twin as the study defines it
        roe_o_free, _, _ = walk(m, e, -side, lev, -1)                     # the twin without any forced exit
        rows.append(dict(part=r.part, t=pd.Timestamp(t, unit="ms"), coin=coin, tf=tf, name=r["name"], side=side,
                         t_is_bar_close=(t % (TF_MIN[tf] * MIN) == 0) and (T0 + e * MIN == t),
                         htf_close_le_t=bool(hc[j] <= t), htf_age_min=(t - int(hc[j])) // MIN,
                         j_file=r.j_dir, j_closed=d_cl, j_peek=d_pk, sig=sig,
                         force_file=int(r.force), force_mine=force, roe_file=r.tb_roe, roe_mine=roe, k_file=int(r.tb_k),
                         k_mine=k, why_file=int(r.tb_why), why_mine=why, opp_file=r.tb_opp_roe, opp_mine=roe_o,
                         opp_free=roe_o_free, roe_noforce=r0))
        if (q + 1) % 25 == 0:
            print(q + 1, "done", round(time.time() - t0), "s", flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(VDIR, f"vlh_hand_{VAR}_{NS}.csv"), index=False)
    pd.set_option("display.width", 250)
    for part, G in R.groupby("part"):
        d = (G.roe_file - G.roe_mine).abs()
        do = (G.opp_file - G.opp_mine).abs()
        print(f"\n{VAR} {part}: n={len(G)}")
        print(" signal time = a bar close and = entry minute:", G.t_is_bar_close.mean())
        print(" higher bar closed at or before t:", G.htf_close_le_t.mean(), " age min/max (min):", G.htf_age_min.min(), G.htf_age_max if False else G.htf_age_min.max())
        print(" judge (closed bar, trailing 300) == file j_dir:", (G.j_closed == G.j_file).mean(),
              " == trade side:", (G.j_closed == G.side).mean(), " peek == file:", (G.j_peek == G.j_file).mean())
        print(" member signal on truncated bars == side:", (G.sig == G.side).mean())
        end_m = (G.t.astype("int64") // 10**6 - 1577836800000) // 60000 + G.k_file
        ff = np.where((G.force_file >= 0) & (G.force_file <= end_m), G.force_file, -1)
        fm = np.where((G.force_mine >= 0) & (G.force_mine <= end_m), G.force_mine, -1)
        print(" binding forced minute (<= the exit) equal:", (ff == fm).mean(), " trades with a binding forced minute:", (ff >= 0).sum())
        print(" own roe |d|<1e-4:", (d < 1e-4).mean(), " max |d|", d.max(), " k equal", (G.k_file == G.k_mine).mean())
        print(" twin roe |d|<1e-4:", (do < 1e-4).mean(), " max |d|", do.max())
        print(" mean roe file %.3f%% mine %.3f%%; twin file %.3f%% mine %.3f%% twin-free %.3f%%" % (
            100 * G.roe_file.mean(), 100 * G.roe_mine.mean(), 100 * G.opp_file.mean(), 100 * G.opp_mine.mean(),
            100 * G.opp_free.mean()))
        sh = np.where(G.side < 0, G.roe_mine, G.opp_mine)
        sh_free = np.where(G.side < 0, G.roe_mine, G.opp_free)
        print(" always short (study twin) %.2f%%, always short (twin w/o forced exit) %.2f%%, short share %.3f" % (
            100 * sh.mean(), 100 * sh_free.mean(), (G.side < 0).mean()))
        bad = G[(G.j_closed != G.j_file) | (G.sig != G.side) | (ff != fm) | (d >= 1e-4) | (do >= 1e-4)]
        if len(bad):
            print(bad.head(25).to_string())


if __name__ == "__main__":
    main()
