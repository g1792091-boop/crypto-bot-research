"""Stage 1 of the five-year role study: accumulate, for EVERY coded strategy (121) as an entry on 15m / 30m / 1h / 4h,
every trend source (52 condition states c:, 52 latch states l:, 7 judge variants j:) read on the last closed higher bar
of every valid mapping (PAIRS), and every condition (against / neutral / with), the sums of the K statistics per time
block (fy_common.BLOCKS). Also the trend-only baseline (the source's side taken at EVERY bar of the entry timeframe)
and the all-bars long / short drift baseline.

Output (RAM scratch, fy_common.SHM): acc.npy [pair, src, cond(-1,0,+1), sid*NB + block, K], accm.npy [pair, src, cond, sid*NMON + month, (n, w35, w35 opposite)] (month clusters), base.npy [pair, src, block,
K] (state != 0 bars, traded on the state's side), base0.npy [pair, src, block] (bars with state 0), bars.npy [tf, block,
side(L, S), K], meta.json.

Judge variants: RAW3 (3-of-4 raw vote), DIR (the bot's held direction), DIR_ADX20 (held direction when ADX >= 20),
V2OF4 (sign of the vote sum when |sum| >= 2), V4OF4 (all four agree), TB22 / TB21 (the trend bot's whole entry check of
paperbot/trendjudge.check as vectorised in data/build_forward.tj_check, 10-22 design: hold allowed / 10-21 design: hold
blocks; with = passes and the held direction is the signal's side, neutral = passes on a hold, against = blocked by
any check; rows the check cannot judge are left out). Warm-up: signals with bar number < 300 on their own timeframe and
higher bars with bar number < 300 are left out (all sources of that mapping), so with + against + neutral = all.

    python3 build_acc.py            (about 10-15 minutes)"""
import json
import time
import numba
from fy_common import *
from build_forward import tj_check


@numba.njit(parallel=True, cache=True)
def acc_sig(A, key, cond, stats):
    NS, n = cond.shape
    Kk = stats.shape[1]
    for s in numba.prange(NS):
        for i in range(n):
            kk = key[i]
            if kk < 0:
                continue
            c = cond[s, i]
            if c < -1 or c > 1:
                continue
            for k in range(Kk):
                A[s, c + 1, kk, k] += stats[i, k]


@numba.njit(parallel=True, cache=True)
def acc_mon(AM, key, cond, stats):
    """Monthly sums of n, w35, w35 opposite per (src, cond, sid*NMON + month): for month-clustered errors."""
    NS, n = cond.shape
    for s in numba.prange(NS):
        for i in range(n):
            kk = key[i]
            if kk < 0:
                continue
            c = cond[s, i]
            if c < -1 or c > 1:
                continue
            AM[s, c + 1, kk, 0] += 1.0
            AM[s, c + 1, kk, 1] += stats[i, 2]
            AM[s, c + 1, kk, 2] += stats[i, 4]


@numba.njit(parallel=True, cache=True)
def acc_base(B, B0, blk, state, sL, sS):
    NS, n = state.shape
    Kk = sL.shape[1]
    for s in numba.prange(NS):
        for i in range(n):
            b = blk[i]
            if b < 0:
                continue
            st = state[s, i]
            if st == 1:
                for k in range(Kk):
                    B[s, b, k] += sL[i, k]
            elif st == -1:
                for k in range(Kk):
                    B[s, b, k] += sS[i, k]
            elif st == 0:
                B0[s, b] += 1.0


def judge_cols(Z, ii):
    """Judge-derived states for higher bars ii: dict name -> int8 array (RAW3 .. V4OF4) + raw judge columns."""
    v = Z["j_V39"].astype(np.int16)[ii] + Z["j_S6"].astype(np.int16)[ii] + Z["j_OBV"].astype(np.int16)[ii] + \
        Z["j_N12"].astype(np.int16)[ii]
    adx = Z["j_adx"][ii]
    d = Z["j_dir"][ii].astype(np.int8)
    out = {"RAW3": Z["j_raw3"][ii].astype(np.int8), "DIR": d,
           "DIR_ADX20": np.where(adx >= 20.0, d, 0).astype(np.int8),
           "V2OF4": np.where(np.abs(v) >= 2, np.sign(v), 0).astype(np.int8),
           "V4OF4": np.where(np.abs(v) == 4, np.sign(v), 0).astype(np.int8)}
    J = {"dir": d.astype(float), "adx": adx, "adx_prev": Z["j_adx"][np.maximum(ii - 1, 0)],
         "ema20": Z["j_ema20"][ii], "atr": Z["j_atr"][ii]}
    return out, J


def main():
    t_start = time.time()
    N = RD.names()
    SRC = sources()
    NS = len(SRC)
    nsid = int(N.sid.max()) + 1
    A = np.zeros((len(PAIRS), NS, 3, nsid * NB, K))
    B = np.zeros((len(PAIRS), NS, NB, K))
    B0 = np.zeros((len(PAIRS), NS, NB))
    BARS = np.zeros((len(TFS), NB, 2, K))
    AM = np.zeros((len(PAIRS), NS, 3, nsid * NMON, 3))
    a, b = EDGES[0], EDGES[-1]
    for ci, coin in enumerate(COINS):
        S = RD.signals(tfs=TFS, period=(int(a), int(b)), coins=[coin])
        S = RD.add_outcomes(S, ["w35", "w30", "w35s20", "a2"])
        ok = np.ones(len(S), bool)
        for v in ("w35", "w30", "w35s20", "a2"):
            for sfx in ("", "_opp"):
                ok &= np.isfinite(S[f"{v}{sfx}_r"].to_numpy()) & (S[f"{v}{sfx}_why"].to_numpy() != 3)
        S = S[ok].reset_index(drop=True)
        sp = RD.spot(S)
        log(coin, "signals", len(S))
        G = RD._grid(coin)
        zsig = RD._sigfile(coin)
        for ti, tf in enumerate(TFS):
            m = (S.tf == tf).to_numpy()
            T = S[m].reset_index(drop=True)
            spt = {k: v[m] for k, v in sp.items()}
            side = T.side.to_numpy(np.int8)
            stats = row_stats(side, {c: T[c].to_numpy(float) for c in T.columns if c.endswith("_roe")})
            blk = block_of(T.t.to_numpy(np.int64))
            key0 = np.where(blk >= 0, T.sid.to_numpy(np.int64) * NB + blk, -1)
            mon = month_of(T.t.to_numpy(np.int64))
            keym0 = np.where((blk >= 0) & (mon >= 0), T.sid.to_numpy(np.int64) * NMON + mon, -1)
            # ---- all bars of this tf (trend-only / drift baselines)
            n_tf, e0, tfm = int(zsig[f"{tf}_n"]), int(zsig[f"{tf}_e0"]), TF_MIN[tf]
            nbs = np.arange(300, n_tf, dtype=np.int64)
            eb = e0 + nbs * tfm
            tb = T0 + eb * MIN
            j15 = eb // 15 - 1
            okb = (j15 >= 0) & (j15 < len(G["valid15"]))
            okb[okb] &= G["valid15"][j15[okb]]
            jj = np.clip(j15, 0, len(G["valid15"]) - 1)
            ja = np.clip(eb // tfm - 1, 0, len(G[f"a2_{tf}_L_r"]) - 1)
            outL, outS = {}, {}
            for v, lev in (("w35", 35.0), ("w30", 30.0), ("w35s20", 35.0)):
                for lab, dct in (("L", outL), ("S", outS)):
                    dct[v] = lev * G[f"{v}_{lab}_r"][jj].astype(float)
                    okb &= G[f"{v}_{lab}_why"][jj] != 3
            for lab, dct in (("L", outL), ("S", outS)):
                dct["a2"] = 30.0 * G[f"a2_{tf}_{lab}_r"][ja].astype(float)
                okb &= (G[f"a2_{tf}_{lab}_why"][ja] != 3) & np.isfinite(dct["a2"])
            okb &= np.isfinite(outL["w35"]) & np.isfinite(outS["w35"])
            blkb = np.where(okb, block_of(tb), -1)

            def bstats(me, op, longflag):
                M = np.zeros((len(eb), K))
                M[:, 0] = 1.0
                M[:, 1] = longflag
                M[:, 2], M[:, 3], M[:, 4], M[:, 5] = me["w35"], me["w35"] ** 2, op["w35"], op["w35"] ** 2
                M[:, 6], M[:, 7] = me["w35"] * op["w35"], me["w35"] > 0
                M[:, 8], M[:, 9], M[:, 10], M[:, 11] = me["w30"], op["w30"], me["w35s20"], op["w35s20"]
                M[:, 12], M[:, 13], M[:, 14] = me["a2"], op["a2"], me["a2"] ** 2
                M[~okb] = 0.0
                return M
            sL, sS = bstats(outL, outS, 1.0), bstats(outS, outL, 0.0)
            for bi in range(NB):
                q = blkb == bi
                BARS[ti, bi, 0] += sL[q].sum(0)
                BARS[ti, bi, 1] += sS[q].sum(0)
            for pi_, (etf, htf) in enumerate(PAIRS):
                if etf != tf:
                    continue
                Z = RD._states(coin, htf)
                hc = Z["ts"] + TF_MIN[htf] * MIN
                for which, tt in (("sig", T.t.to_numpy(np.int64)), ("bar", tb)):
                    idx = last_closed(hc, tt)
                    warm = (idx >= 1)
                    warm[warm] &= Z["nb"][idx[warm]] >= 300
                    ii = np.clip(idx, 0, len(hc) - 1)
                    jc, J = judge_cols(Z, ii)
                    n = len(tt)
                    st = np.full((NS, n), 9, np.int8)
                    for si, (kind, src) in enumerate(SRC):
                        if kind in ("c", "l"):
                            arr = Z.get(f"{kind}_{src}")
                            if arr is None:
                                continue
                            st[si] = arr[ii]
                        elif src in jc:
                            st[si] = jc[src]
                    if which == "sig":
                        cond = (st * side[None, :]).astype(np.int8)
                        cond[st == 9] = 9
                        for si, (kind, src) in enumerate(SRC):
                            if kind == "j" and src in ("TB22", "TB21"):
                                w, _fh, _fe = tj_check(T.name.to_numpy(), T.tf.to_numpy(), side.astype(float),
                                                       spt["spot_close"], J,
                                                       {k: spt[k] for k in ("spot_ema20", "spot_atr", "spot_rsi")},
                                                       hold_entry=(src == "TB22"))
                                c = np.full(n, -1, np.int8)
                                pas = w == ""
                                c[pas & (J["dir"] == side)] = 1
                                c[pas & (J["dir"] == 0)] = 0
                                c[w == "na"] = 9
                                cond[si] = c
                        key = np.where(warm, key0, -1)
                        acc_sig(A[pi_], key, cond, stats)
                        acc_mon(AM[pi_], np.where(warm, keym0, -1), cond, stats)
                    else:
                        bb = np.where(warm, blkb, -1)
                        acc_base(B[pi_], B0[pi_], bb, st, sL, sS)
                log(coin, tf, "->", htf, "rows", len(T), f"{time.time() - t_start:.0f}s")
        RD._GR.pop(coin, None)
        RD._SIG.pop(coin, None)
        for h in HTFS:
            RD._STATES.pop((coin, h), None)
        drop(coin)
        del S
    for nm, arr in (("acc", A), ("base", B), ("base0", B0), ("bars", BARS), ("accm", AM)):
        np.save(os.path.join(SHM, f"{nm}.npy"), arr)
    meta = {"pairs": PAIRS, "src": SRC, "blocks": BLOCKS, "edges": EDGES.tolist(), "stats": STATS,
            "sid_name": dict(zip(N.sid.astype(int).astype(str), N.name)), "made": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - t_start)}
    json.dump(meta, open(os.path.join(SHM, "meta.json"), "w"))
    log("done", round(time.time() - t_start), "s")


if __name__ == "__main__":
    main()
