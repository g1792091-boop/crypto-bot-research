"""Direction-skill verifier (lens: look-ahead / alignment / data errors), part 2: causal CUT tests aimed at the 374
direction-skill cells (flip_picked.csv) -- the parts an earlier cut test (la_causal.py) did not cover: trend-role
strategies used as ENTRIES, the trend strategies whose own signals make the LATCH states (l:) on 1h / 4h / 1d, the 1d
timeframe, all six coins, and cuts placed AT stored signal bars (a look-ahead signal can only show at the bar where it
fires, so random cuts rarely catch rare signals).

For every coin and timeframe (15m 30m 1h 4h 1d) and every strategy that is an entry (etf) or a latch source (htf) of
those cells:
  cut      bars s .. i only (s = i - W, W = 1500 bars; 1d from the first bar), i = a stored signal bar of one of the
           strategies (or a random bar); the strategy code (data/build_signals.coin_signals) recomputes every strategy of
           the timeframe on the cut window; the last 5 bars (i-4 .. i) are compared with the stored bitmaps
  future   when a cut differs from the stored bitmap: the same window + 200 future bars (same start) -> a difference
           between future and cut = look-ahead; equal = only a warm-up / window-start effect
  states   at 1h / 4h / 1d cuts: the condition states (c:) and the judges of the cells (data/build_states.cond_states /
           judge_arrays on the cut window, next frame cut at the same close) vs the stored state table at bar i
  latch    every l_ state of every trend source, coin and higher timeframe re-derived independently from the stored
           signal bitmaps (side of the last signal at or before the bar) and compared on ALL bars
Outputs dsk_stream.csv (one row per coin x tf x cut x strategy compared) and dsk_stream.log.

    python3 dsk_stream.py [procs]"""
import os
import sys
import time

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
import build_signals as BG      # noqa: E402
import build_states as BS       # noqa: E402
from common import *            # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
W = 1500
NCUT = 100             # cuts per coin x tf (at least one per strategy of that tf, up to 4 each)
LO_T, HI_T = ms("2021-01-01"), ms("2026-10-23")


def plan():
    F = pd.read_csv(os.path.join(FY, "flip_picked.csv"))
    ent = {tf: sorted(set(F.name[F.etf == tf])) for tf in TFS}
    lat = {h: sorted(set(F.source[(F.kind == "l") & (F.htf == h)])) for h in HTFS}
    cnd = {h: sorted(set(F.source[(F.kind == "c") & (F.htf == h)])) for h in HTFS}
    jud = {h: sorted(set(F.source[(F.kind == "j") & (F.htf == h)])) for h in HTFS}
    names = {tf: sorted(set(ent.get(tf, [])) | set(lat.get(tf, []))) for tf in TFS + ("1d",)}
    return names, cnd, jud


def latch_check(coin, out):
    """Independent re-derivation of every stored l_ state from the stored bitmaps (all bars)."""
    trend = roles()["roles"]["trend_incl_dual"]
    N = RD.names()
    sset = dict(zip(N.name, N.set))
    for h in HTFS:
        Z = RD._states(coin, h)
        df = bars(coin, h)
        assert len(df) == len(Z["ts"]) and (df.ts.to_numpy() == Z["ts"]).all() and (Z["nb"] == np.arange(len(df))).all()
        for src in trend:
            key = f"l_{src}"
            if key not in Z:
                assert h == "1d" and sset[src] in ("ds", "friend"), (coin, h, src)
                continue
            L, S, e0 = RD.signal_bits(src, h, coin)
            if L is None:
                mine = np.zeros(len(df), np.int8)
            else:
                assert len(L) == len(df)
                assert e0 == (int(df.ts.iloc[0]) + TF_MIN[h] * MIN - T0) // MIN
                ev = np.where(L, 1, np.where(S, -1, 0))
                idx = np.where(ev != 0, np.arange(len(ev)), -1)
                last = np.maximum.accumulate(idx)
                mine = np.where(last >= 0, ev[np.maximum(last, 0)], 0).astype(np.int8)
            d = int((mine != Z[key]).sum())
            out.append({"part": "latch_all_bars", "coin": coin, "tf": h, "cut": -1, "name": src, "n_cmp": len(mine),
                        "diff_last": 0, "diff_5": d, "diff_future": -1})


def work(coin):
    t0 = time.time()
    rng = np.random.default_rng(1024 + COINS.index(coin))
    names, cnd, jud = plan()
    out = []
    latch_check(coin, out)
    log(coin, "latch re-derivation done")
    B = {tf: bars(coin, tf) for tf in TFS + ("1d",)}
    btc = {tf: bars("BTCUSDT", tf) for tf in TFS} if coin != "BTCUSDT" else None
    drop(coin)
    drop("BTCUSDT")
    for tf in TFS + ("1d",):
        nm = names[tf]
        if not nm:
            continue
        raw = B[tf]
        n = len(raw)
        cl = close_ms(raw, tf)
        bits = {}
        for name in nm:
            L, S, _e0 = RD.signal_bits(name, tf, coin)
            if L is not None:
                bits[name] = (L, S)
        lo_i = W + 10 if tf != "1d" else 400
        okrange = (np.arange(n) >= lo_i) & (cl >= LO_T) & (cl < HI_T)
        first, second = [], []
        for name, (L, S) in bits.items():
            cand = np.flatnonzero((L | S) & okrange)
            if len(cand):
                pk = rng.choice(cand, min(4, len(cand)), replace=False).tolist()
                first.append(pk[0])
                second += pk[1:]
        rng.shuffle(second)
        cuts = first + second[:max(0, NCUT - len(first))] + rng.choice(np.flatnonzero(okrange), 3, replace=False).tolist()
        for i in sorted(set(int(x) for x in cuts)):
            s = 0 if tf == "1d" else i - W
            tcut = int(cl[i])
            Bc = {h: B[h][close_ms(B[h], h) <= tcut].reset_index(drop=True) for h in ("1h", "4h", "1d")}

            def run(end):
                rw = raw.iloc[s:end].reset_index(drop=True)
                bt = None
                if btc is not None and tf in btc:
                    bb = btc[tf]
                    bt = bb[(bb.ts >= rw.ts.iloc[0]) & (bb.ts <= rw.ts.iloc[-1])].reset_index(drop=True)
                return BG.coin_signals(coin, tf, rw, bt, Bc, only=set(nm))
            sig = run(i + 1)
            fut = None
            for name, (L, S) in bits.items():
                if name not in sig:
                    out.append({"part": "signal", "coin": coin, "tf": tf, "cut": i, "name": name, "n_cmp": 0,
                                "diff_last": -9, "diff_5": -9, "diff_future": -9})
                    continue
                lb, sb = (np.asarray(x, bool) for x in sig[name])
                k = i - s                        # position of bar i in the window
                rr = slice(k - 4, k + 1)
                st = slice(i - 4, i + 1)
                dl = int((lb[k] != L[i]) + (sb[k] != S[i]))
                d5 = int((lb[rr] != L[st]).sum() + (sb[rr] != S[st]).sum())
                df_ = -1
                if d5:
                    if fut is None:
                        Bc_f = {h: B[h][close_ms(B[h], h) <= int(cl[min(i + 200, n - 1)])].reset_index(drop=True)
                                for h in ("1h", "4h", "1d")}
                        rwf = raw.iloc[s:min(i + 201, n)].reset_index(drop=True)
                        bt = None
                        if btc is not None and tf in btc:
                            bb = btc[tf]
                            bt = bb[(bb.ts >= rwf.ts.iloc[0]) & (bb.ts <= rwf.ts.iloc[-1])].reset_index(drop=True)
                        fut = BG.coin_signals(coin, tf, rwf, bt, Bc_f, only=set(nm))
                    lf, sf = (np.asarray(x, bool) for x in fut[name])
                    df_ = int((lf[rr] != lb[rr]).sum() + (sf[rr] != sb[rr]).sum())
                out.append({"part": "signal", "coin": coin, "tf": tf, "cut": i, "name": name, "n_cmp": 5,
                            "sig_at_cut": int(L[i] or S[i]), "diff_last": dl, "diff_5": d5, "diff_future": df_})
            # condition states / judges of the cells at this higher-tf cut
            if tf in HTFS and (cnd[tf] or jud[tf]):
                Z = RD._states(coin, tf)
                cut = raw.iloc[s:i + 1].reset_index(drop=True)
                nx = BS.NEXT_HTF[tf]
                nxt = None if nx is None else (nx, B[nx][close_ms(B[nx], nx) <= tcut].reset_index(drop=True))
                S_ = BS.cond_states(cut, tf, nxt)
                for src in cnd[tf]:
                    v = int(np.asarray(S_[src])[-1])
                    out.append({"part": "cstate", "coin": coin, "tf": tf, "cut": i, "name": src, "n_cmp": 1,
                                "diff_last": int(v != Z[f"c_{src}"][i]), "diff_5": int(
                                    (np.asarray(S_[src])[-5:] != Z[f"c_{src}"][i - 4:i + 1]).sum()), "diff_future": -1})
                if jud[tf]:
                    J = BS.judge_arrays(cut, tf)
                    for k_ in ("j_V39", "j_S6", "j_OBV", "j_N12", "j_raw3", "j_dir"):
                        out.append({"part": "judge", "coin": coin, "tf": tf, "cut": i, "name": k_, "n_cmp": 1,
                                    "diff_last": int(np.asarray(J[k_])[-1] != Z[k_][i]),
                                    "diff_5": int((np.asarray(J[k_])[-5:] != Z[k_][i - 4:i + 1]).sum()),
                                    "diff_future": -1})
        log(coin, tf, "cuts", len(set(cuts)), "strategies", len(bits), f"{time.time() - t0:.0f}s")
        pd.DataFrame(out).to_csv(os.path.join(HERE, f"dsk_stream_{coin}.csv"), index=False)
    return coin


def main():
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    coins = sys.argv[2:] or list(COINS)
    from multiprocessing import get_context
    libs()
    with get_context("fork").Pool(procs) as pool:
        for c in pool.imap_unordered(work, coins):
            log("done", c)
    D = pd.concat([pd.read_csv(os.path.join(HERE, f"dsk_stream_{c}.csv")) for c in coins], ignore_index=True)
    D.to_csv(os.path.join(HERE, "dsk_stream.csv" if len(coins) == len(COINS) else "dsk_stream_part.csv"), index=False)
    print(D.groupby(["part", "tf"]).agg(rows=("n_cmp", "size"), cmp=("n_cmp", "sum"), diff_last=("diff_last", lambda x: int((x > 0).sum())),
                                        diff_5=("diff_5", lambda x: int((x > 0).sum())),
                                        lookahead=("diff_future", lambda x: int((x > 0).sum())),
                                        missing=("diff_last", lambda x: int((x == -9).sum()))).to_string())
    sg = D[D.part == "signal"]
    print("signal comparisons at a stored signal bar:", int((sg.sig_at_cut == 1).sum()))
    bad = D[(D.diff_5 > 0) | (D.diff_last != 0)]
    print("rows with a difference:", len(bad))
    if len(bad):
        print(bad.groupby(["part", "tf", "name"]).agg(rows=("cut", "size"), lookahead=("diff_future", lambda x: int((x > 0).sum()))).to_string())


if __name__ == "__main__":
    main()
