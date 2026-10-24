"""Look-ahead / time-alignment verifier, part C (by hand from the raw 1m grid, independent of lb_core's code paths).

For a random sample of TAKEN trades of a variant in 2024-01 .. 2026-10-05 (trades/trades_<v>.csv.gz):
  1. higher bars rebuilt here with pandas resample from the 1m grid; the judge recomputed with paperbot.trendjudge
     .vote_arrays on a TRAILING window of 300 bars that ends at the last bar with close <= t (exactly what the live bot
     sees), for the variant's judge kind (vote3 / vote4 / obv) and hold; compared with the file's j_dir. As a
     look-ahead detector, the same is done with the bar that was still OPEN at t (the 'peek' judge).
  2. the member's own signal recomputed on bars TRUNCATED at the signal bar (no future bar exists), compared with the
     side of the trade (catches strategies whose full-series bitmap uses later bars).
  3. the forced exit minute recomputed (first higher bar closing after the entry with the judge against the side, from
     trailing windows; first later opposite signal of the same member, recomputed on truncated bars), and the outcome
     re-walked with a plain-Python minute loop and paperbot.ladder2.ComboLadder.
Run (from this folder, no -I): python3 vla_hand.py <trades_dir> <variant> <n_sample> [seed]"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "data"))
from common import *            # noqa: E402,F401,F403  (grid, libs, as_chart, constants)
import rolesdata as RD          # noqa: E402  (names table only)

TD, VAR, NS = sys.argv[1], sys.argv[2], int(sys.argv[3])
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 7
A, B = ms("2024-01-01"), ms("2026-10-05 15:00")
HTF_OF = {"30m": "1h", "1h": "4h", "4h": "1d"}
HOLD = {"1h": 2, "4h": 1, "1d": 1}
KIND = {"B0": "vote3", "B1": "vote3", "B2": "vote3", "B3": "vote3", "B4": "vote3", "B5": "vote4", "B6": "obv",
        "B7": "obv", "B8": "vote3", "B9": "vote3"}[VAR]
EXITS = VAR != "B8"
LEV = {0: 40.0}
E = libs()
TJ, fg, pi, run, lib = E["TJ"], E["fg"], E["pi"], E["run"], E["lib"]
import ds_defs as DSD            # noqa: E402
from paperbot.ladder2 import ComboLadder   # noqa: E402
LAD = ComboLadder(first_lock=0.10, trigger_gap=0.01, step=0.05, next_trigger=0.15, next_gap=0.03)
NM = RD.names()
SET = dict(zip(NM.name, NM.set))

# ------------------------------------------------------------------ bars rebuilt here (pandas resample, UTC bins)
_BARS = {}


def my_bars(coin, tf):
    key = (coin, tf)
    if key not in _BARS:
        g = grid(coin)
        n = g["n"]
        idx = pd.to_datetime(T0 + np.arange(n, dtype=np.int64) * MIN, unit="ms", utc=True)
        df = pd.DataFrame({"open": g["o"], "high": g["h"], "low": g["l"], "close": g["c"], "volume": g["v"]}, index=idx)
        rule = {"30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}[tf]
        r = df.resample(rule, label="left", closed="left", origin="epoch")
        out = pd.DataFrame({"open": r.open.first(), "high": r.high.max(), "low": r.low.min(), "close": r.close.last(),
                            "volume": r.volume.sum(), "cnt": r.close.count()})
        out = out[out.cnt == TF_MIN[tf]].drop(columns="cnt")
        out["ts_ms"] = out.index.asi8 // 10**6
        out = out.reset_index().rename(columns={"index": "ts"})
        _BARS[key] = out
    return _BARS[key]


def closes(df, tf):
    return df.ts_ms.to_numpy(np.int64) + TF_MIN[tf] * MIN


def chart(df, tf):
    d = df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).copy()
    d.attrs["tf"] = tf
    return d


def raw_of(arr, kind):
    if kind == "vote3":
        return TJ.raw_votes(arr, 3).astype(int)
    V = np.vstack([arr[k] for k in ("V39", "S6", "OBV", "N12")]).astype(int)
    if kind == "vote4":
        return np.where((V == 1).all(0), 1, np.where((V == -1).all(0), -1, 0))
    return np.asarray(arr["OBV"]).astype(int)


def judge_at(coin, htf, j, kind):
    """dir and raw of higher bar number j (index into my_bars) from a trailing 300-bar window ending at j."""
    H = my_bars(coin, htf)
    w = H.iloc[max(0, j - 299): j + 1]
    if len(w) < 120:
        return np.nan, np.nan
    arr = TJ.vote_arrays(chart(w, htf), fg, pi)
    raw = raw_of(arr, kind)
    h = HOLD[htf]
    held = raw[-h:]
    d = int(raw[-1]) if (raw[-1] != 0 and (held == raw[-1]).all()) else 0
    return d, int(raw[-1])


_FULL = {}


def full_raw(coin, htf, kind):
    """raw per higher bar from the whole series (used only for the exit scan; its equality with the trailing-window
    raw is checked on the sample)."""
    key = (coin, htf, kind)
    if key not in _FULL:
        H = my_bars(coin, htf)
        _FULL[key] = raw_of(TJ.vote_arrays(chart(H, htf), fg, pi), kind)
    return _FULL[key]


# ------------------------------------------------------------------ member signals on truncated bars
def member_sig(name, tf, coin, upto_close, nwin=1500):
    """(long, short) of the member at the bar closing at upto_close, computed on bars that END there."""
    Bf = my_bars(coin, tf)
    bc = closes(Bf, tf)
    j = int(np.searchsorted(bc, upto_close))
    if j >= len(bc) or bc[j] != upto_close:
        return None
    w = Bf.iloc[max(0, j - nwin + 1): j + 1]
    st = SET[name]
    if st == "core":
        run.M.clear()
        df = as_chart(w[["ts_ms", "open", "high", "low", "close", "volume"]].rename(columns={"ts_ms": "ts"}), tf)
        lg, sh = run.core_module(name).signals(df, tf)
        run.M.clear()
    elif st == "ds":
        df = as_chart(w[["ts_ms", "open", "high", "low", "close", "volume"]].rename(columns={"ts_ms": "ts"}), tf)
        ctx = None
        if coin != "BTCUSDT":
            Bb = my_bars("BTCUSDT", tf)
            Bb = Bb[closes(Bb, tf) <= upto_close].iloc[-nwin:]
            ctx = {"BTCUSD": as_chart(Bb[["ts_ms", "open", "high", "low", "close", "volume"]].rename(columns={"ts_ms": "ts"}), tf)}
        lg, sh = run.ds_module().signals(df, tf, name, ctx=ctx, coin=coin[:-1], cache={})
    elif st == "lib":
        dfl = w[["ts_ms", "open", "high", "low", "close", "volume"]].rename(columns={"ts_ms": "ts"}).reset_index(drop=True)
        dfl.attrs["tf"] = tf
        ent = lib.entries(dfl, fg, pi)
        lg, sh = ent[name]
    elif st == "friend":
        import build_signals as BS
        raw = w[["ts_ms", "open", "high", "low", "close", "volume"]].rename(columns={"ts_ms": "ts"}).reset_index(drop=True)
        Bh = {}
        for h in ("1h", "4h", "1d"):
            X = my_bars(coin, h)
            X = X[closes(X, h) <= upto_close].iloc[-600:]
            Bh[h] = X[["ts_ms", "open", "high", "low", "close", "volume"]].rename(columns={"ts_ms": "ts"}).reset_index(drop=True)
        lg, sh = BS.friend_signals(raw, coin, tf, Bh)
    else:
        return None
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    if st == "lib":
        sh = sh & ~lg
    return int(lg[-1]) - int(sh[-1] & ~lg[-1])


# ------------------------------------------------------------------ plain-Python exit walk
def walk_py(g, cumf, e, s, lev, force):
    o, h, l = g["o"], g["h"], g["l"]
    p0 = o[e]
    f0 = cumf[e - 1]
    best = -1e9
    lock = None
    k = 0
    while True:
        i = e + k
        F = s * (cumf[i] - f0)
        Fp = s * (cumf[i - 1] - f0)
        op = s * (o[i] / p0 - 1.0)
        if k > 0 and lock is None and force >= 0 and i >= force:
            return max(op - COST - F, -1.0 / lev) * lev, k, 2
        level = -0.5 / lev + COST + Fp
        rs = 0
        if lock is not None and lock / lev + COST + Fp > level:
            level = lock / lev + COST + Fp
            rs = 1
        up = (h[i] / p0 - 1.0) if s > 0 else (1.0 - l[i] / p0)
        dn = (l[i] / p0 - 1.0) if s > 0 else (1.0 - h[i] / p0)
        if dn <= level:
            fill = min(level, op)
            return max(fill - COST - F, -1.0 / lev) * lev, k, rs
        r_up = lev * (up - COST - F)
        if r_up > best:
            best = r_up
            lk = LAD.lock_for(best)
            lock = lk if lk is not None else lock
        k += 1


def main():
    T = pd.read_csv(os.path.join(TD, f"trades_{VAR}.csv.gz"))
    T = T[(T.t >= A) & (T.t < B)].reset_index(drop=True)
    S = T.sample(min(NS, len(T)), random_state=SEED).sort_values("t").reset_index(drop=True)
    rows = []
    t0 = time.time()
    for q, r in S.iterrows():
        coin = COINS[int(r.coin)]
        htf = HTF_OF[r.tf]
        H = my_bars(coin, htf)
        hc = closes(H, htf)
        j = int(np.searchsorted(hc, int(r.t), side="right") - 1)       # last higher bar closed at or before t
        d_cl, raw_cl = judge_at(coin, htf, j, KIND)
        d_pk, _ = judge_at(coin, htf, j + 1, KIND) if j + 1 < len(H) else (np.nan, np.nan)   # bar still open at t
        fr = full_raw(coin, htf, KIND)
        # member signal on truncated bars
        sig = member_sig(r["name"], r.tf, coin, int(r.t))
        # forced exit minute, recomputed
        e = int(r.e)
        side = int(r.side)
        f = -1
        if EXITS:
            cm = (hc - T0) // MIN
            jj = np.flatnonzero((cm > e) & (fr == -side))
            jm = int(cm[jj[0]]) if len(jj) else -1
            # check the exit bar's raw also from a trailing window (causal)
            jm_ok = True
            if len(jj):
                _d, rw = judge_at(coin, htf, int(jj[0]), KIND)
                jm_ok = rw == -side
            # own reverse: first later opposite signal of the same member from the bitmap, then that signal itself
            # recomputed on truncated bars (it must exist without any later bar)
            L_, S_, e0 = RD.signal_bits(r["name"], r.tf, coin)
            opp = S_ if side > 0 else L_
            mo = e0 + np.flatnonzero(opp).astype(np.int64) * TF_MIN[r.tf]
            jx = np.searchsorted(mo, e, side="right")
            rm = int(mo[jx]) if jx < len(mo) else -1
            rev_ok = True
            if rm >= 0 and (jm < 0 or rm < jm) and rm <= e + int(r.tb_k):
                rev_ok = member_sig(r["name"], r.tf, coin, int(T0 + rm * MIN)) == -side
            f = jm if rm < 0 else (rm if jm < 0 else min(jm, rm))
        g = grid(coin)
        cumf = np.cumsum(g["fund"])
        lev = LEV.get(int(r.coin), 30.0)
        roe, k, why = walk_py(g, cumf, e, side, lev, f)
        rows.append(dict(t=pd.Timestamp(int(r.t), unit="ms"), coin=coin, tf=r.tf, name=r["name"], side=side,
                         htf_close_le_t=bool(hc[j] <= r.t), htf_close_age_min=(int(r.t) - int(hc[j])) // MIN,
                         j_file=r.j_dir, j_closed=d_cl, j_peek=d_pk, full_eq_window=int(fr[j]) == raw_cl,
                         sig_trunc=sig, sig_eq_side=(sig == side) if VAR != "B4" else (sig is not None and sig != 0), force_file=int(r.force), force_mine=f,
                         jm_window_ok=jm_ok if EXITS else True, rev_sig_ok=rev_ok if EXITS else True,
                         roe_file=r.tb_roe, roe_mine=roe, k_file=int(r.tb_k), k_mine=k, why_file=int(r.tb_why), why_mine=why))
        if (q + 1) % 25 == 0:
            print(q + 1, "done", round(time.time() - t0), "s", flush=True)
    R = pd.DataFrame(rows)
    out = os.path.join(HERE, f"vla_hand_{VAR}.csv")
    R.to_csv(out, index=False)
    side_rule = (R.j_closed == R.side) if VAR not in ("B0",) else R.j_closed.isin([0]) | (R.j_closed == R.side)
    print(VAR, "kind", KIND, "n", len(R))
    print(" higher bar closed at or before signal:", R.htf_close_le_t.mean())
    print(" judge dir (trailing window, closed bar) == file j_dir:", (R.j_closed == R.j_file).mean())
    print(" judge allows the trade side (closed bar):", side_rule.mean())
    print(" judge with the still-open bar (peek) == file j_dir:", (R.j_peek == R.j_file).mean())
    print(" full-series raw == trailing-window raw:", R.full_eq_window.mean())
    print(" member signal on truncated bars == trade side:", R.sig_eq_side.mean(), " (None:", R.sig_trunc.isna().sum(), ")")
    print(" forced minute equal:", (R.force_file == R.force_mine).mean(), " exit bar raw from window ok:", R.jm_window_ok.mean(), " binding reverse signal causal:", R.rev_sig_ok.mean())
    d = (R.roe_file - R.roe_mine).abs()
    print(" roe equal (|d|<1e-6):", (d < 1e-6).mean(), " max |d|:", d.max(), " k equal:", (R.k_file == R.k_mine).mean())
    print(" mean roe file", R.roe_file.mean(), "mine", R.roe_mine.mean())
    bad = R[(R.j_closed != R.j_file) | (~R.sig_eq_side) | (R.force_file != R.force_mine) | (d >= 1e-6)]
    if len(bad):
        pd.set_option("display.width", 250)
        print(bad.head(20).to_string())


if __name__ == "__main__":
    main()
