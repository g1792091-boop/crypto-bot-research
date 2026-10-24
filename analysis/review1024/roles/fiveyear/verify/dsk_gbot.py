"""Direction-skill verifier (lens: look-ahead / alignment / data errors), part 3: bot G re-derived with our own code path
(not cellsig.cell_rows / RD.one_position / RD.account / RD.goal_bootstrap):
  cells    the 321 rows of flip_picked.csv with SELECT mean + payback > 0, priority = SELECT paired t (descending)
  signals  the data layer's bitmaps (RD.signals, warm-up 300 own bars), outcomes looked up in the outcome grid npz by
           our own index arithmetic (15m bar j = e // 15 - 1), rows open at the data end or off the grid dropped
  states   our own higher-bar index: bars(coin, htf).ts + htf = close, last close <= signal close (searchsorted),
           higher bar number >= 300 and index >= 1; c:/l: from the state table, judges derived from the four votes;
           TB21 / TB22 through data/build_forward.tj_check (the same vectorised check the study used)
  bot      one position at a time over all coins: sort by (entry minute, priority), take when entry minute > the
           previous exit minute; the coin flip = the same with the opposite side's exits
  goal     30-day day-block bootstrap at margin 0.40 with the payback, 4000 draws (our own loop)
Outputs dsk_gbot_trades.csv (taken trades of every period) and dsk_gbot.txt (comparison with goalpath_G.csv,
goal_boot_G.csv).

    python3 dsk_gbot.py"""
import os
import sys

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
from common import *            # noqa: E402,F401
from build_forward import tj_check   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PB35 = 35.0 * PAYBACK
EDG = {"SEL": (ms("2021-01-01"), ms("2024-01-01")), "CONF": (ms("2024-01-01"), ms("2026-10-01")),
       "LATE": (ms("2026-01-01"), GRID_END), "FWD": (FWD[0], FWD[1])}
SPAN = (ms("2021-01-01"), FWD[1])


def cells():
    F = pd.read_csv(os.path.join(FY, "flip_picked.csv"))
    G = F[F.SEL_mW + PB35 > 0].sort_values("SEL_tFlip", ascending=False, kind="stable").reset_index(drop=True)
    return G


_HB = {}


def htf_close(coin, htf):
    if (coin, htf) not in _HB:
        df = bars(coin, htf)
        _HB[(coin, htf)] = df.ts.to_numpy(np.int64) + TF_MIN[htf] * MIN
        drop(coin)
    return _HB[(coin, htf)]


_GRD = {}


def outcome(coin, e, side):
    """(r, k, why) of w35 for entries e (minutes from T0) and sides; NaN / -1 off the grid; plus a2, w30, s20 finiteness."""
    if coin not in _GRD:
        z = np.load(os.path.join(OUT, "grid", f"{coin}.npz"))
        _GRD[coin] = {k: z[k] for k in z.files}
    G = _GRD[coin]
    return G


def rows_of(name, etf, htf, kind, source):
    S = RD.signals(names=[name], tfs=[etf], period=SPAN)
    if not len(S):
        return S
    e = S.e.to_numpy(np.int64)
    side = S.side.to_numpy(np.int64)
    n = len(S)
    cols = {f"{v}{s_}_{q}": np.full(n, np.nan) for v in ("w35", "w30", "w35s20") for s_ in ("", "_opp")
            for q in ("r", "k", "why")}
    a2ok = np.zeros(n, bool)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if not m.any():
            continue
        G = outcome(coin, None, None)
        j = e[m] // 15 - 1
        assert (e[m] % 15 == 0).all()
        ok = (j >= 0) & (j < len(G["valid15"]))
        jj = np.clip(j, 0, len(G["valid15"]) - 1)
        for v in ("w35", "w30", "w35s20"):
            for s_, sg in (("", 1), ("_opp", -1)):
                sd = side[m] * sg
                for q in ("r", "k", "why"):
                    x = np.where(sd > 0, G[f"{v}_L_{q}"][jj], G[f"{v}_S_{q}"][jj]).astype(float)
                    x[~ok] = np.nan
                    cols[f"{v}{s_}_{q}"][m] = x
        tfm = TF_MIN[etf]
        ja = e[m] // tfm - 1
        na = len(G[f"a2_{etf}_L_r"])
        oka = (ja >= 0) & (ja < na)
        jaa = np.clip(ja, 0, na - 1)
        good = oka.copy()
        for lab in ("L", "S"):
            good &= np.isfinite(G[f"a2_{etf}_{lab}_r"][jaa]) & (G[f"a2_{etf}_{lab}_why"][jaa] != 3)
        a2ok[m] = good
    for k_, v_ in cols.items():
        S[k_] = v_
    keep = a2ok.copy()
    for v in ("w35", "w30", "w35s20"):
        for s_ in ("", "_opp"):
            keep &= np.isfinite(S[f"{v}{s_}_r"].to_numpy()) & (S[f"{v}{s_}_why"].to_numpy() != 3)
    S = S[keep].reset_index(drop=True)
    # trend state of the last CLOSED higher bar
    t = S.t.to_numpy(np.int64)
    side = S.side.to_numpy(np.int64)
    st = np.full(len(S), 99, np.int64)
    J = {k: np.full(len(S), np.nan) for k in ("dir", "adx", "adx_prev", "ema20", "atr")}
    hidx = np.full(len(S), -1, np.int64)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if not m.any():
            continue
        hc = htf_close(coin, htf)
        idx = np.searchsorted(hc, t[m], side="right") - 1
        assert ((idx < 0) | (hc[np.maximum(idx, 0)] <= t[m])).all()
        assert ((idx + 1 >= len(hc)) | (hc[np.minimum(idx + 1, len(hc) - 1)] > t[m])).all()
        Z = RD._states(coin, htf)
        assert len(Z["ts"]) == len(hc) and (Z["ts"] + TF_MIN[htf] * MIN == hc).all()
        good = (idx >= 1)
        good[good] &= Z["nb"][idx[good]] >= 300
        ii = np.maximum(idx, 0)
        hidx[m] = np.where(good, idx, -1)
        if kind in ("c", "l"):
            val = Z[f"{kind}_{source}"][ii].astype(np.int64)
        else:
            v4 = sum(Z[f"j_{x}"][ii].astype(np.int64) for x in ("V39", "S6", "OBV", "N12"))
            d = Z["j_dir"][ii].astype(np.int64)
            adx = Z["j_adx"][ii]
            val = {"RAW3": Z["j_raw3"][ii].astype(np.int64), "DIR": d, "DIR_ADX20": np.where(adx >= 20.0, d, 0),
                   "V2OF4": np.where(np.abs(v4) >= 2, np.sign(v4), 0), "V4OF4": np.where(np.abs(v4) == 4, np.sign(v4), 0),
                   "TB22": d, "TB21": d}[source]
            J["dir"][m], J["adx"][m] = d, adx
            J["adx_prev"][m] = Z["j_adx"][np.maximum(ii - 1, 0)]
            J["ema20"][m], J["atr"][m] = Z["j_ema20"][ii], Z["j_atr"][ii]
        st[m] = np.where(good, val, 99)
    S["hidx"] = hidx
    S["state"] = st
    if kind == "j" and source in ("TB22", "TB21"):
        sp = RD.spot(S)
        w, _a, _b = tj_check(S.name.to_numpy(), S.tf.to_numpy(), side.astype(float), sp["spot_close"], J,
                             {k: sp[k] for k in ("spot_ema20", "spot_atr", "spot_rsi")}, hold_entry=(source == "TB22"))
        with_ = (w == "") & (J["dir"] == side) & (st != 99)
    else:
        with_ = (st != 99) & (st * side == 1)
    S = S[with_].reset_index(drop=True)
    S["cell"] = f"{name}@{etf}|{kind}:{source}@{htf}"
    return S


def one_pos(P, opp=False):
    k = P[f"w35{'_opp' if opp else ''}_k"].to_numpy(np.int64)
    e = P.e.to_numpy(np.int64)
    order = np.lexsort((P.prio.to_numpy(), e))
    took = np.zeros(len(P), bool)
    busy = -1
    for q in order:
        if e[q] > busy:
            took[q] = True
            busy = e[q] + k[q]
    return took


def boot(roe, t, a, b, margin=0.4, n_boot=4000, seed=7, horizon=30, target=6.0):
    d = t // DAY
    lo, hi = a // DAY, (b - 1) // DAY
    nd = int(hi - lo + 1)
    by = [np.maximum(roe[d == lo + i], -1.0) for i in range(nd)]
    rng = np.random.default_rng(seed)
    hit = l50 = l90 = 0
    fin = np.empty(n_boot)
    for bi in range(n_boot):
        eq, half, done = 1.0, False, False
        for di in rng.integers(0, nd, horizon):
            for x in by[di]:
                eq *= 1.0 + margin * x
                if not done:
                    if eq >= target:
                        hit += 1
                        done = True
                    else:
                        if eq <= 0.5 and not half:
                            l50 += 1
                            half = True
                        if eq <= 0.1:
                            l90 += 1
                            done = True
        fin[bi] = eq
    return hit / n_boot, l50 / n_boot, l90 / n_boot, float(np.median(fin))


def main():
    G = cells()
    parts = []
    for p, r in G.iterrows():
        S = rows_of(r["name"], r.etf, r.htf, r.kind, r.source)
        if len(S):
            S["prio"] = p
            parts.append(S)
        if p % 40 == 0:
            log("cell", p, r["name"], r.etf, r.htf, r.kind, r.source, len(S))
    A = pd.concat(parts, ignore_index=True)
    A = A.sort_values("prio", kind="stable").drop_duplicates(["coin", "e", "side", "name", "tf"])
    A = A.sort_values(["e", "prio"], kind="stable").reset_index(drop=True)
    log("rows", len(A))
    ref = pd.read_csv(os.path.join(FY, "goalpath_G.csv")).set_index("period")
    rb = pd.read_csv(os.path.join(FY, "goal_boot_G.csv"))
    lines, taken = [], []
    for per, (a, b) in EDG.items():
        P = A[(A.t >= a) & (A.t < b)].reset_index(drop=True)
        tk = one_pos(P)
        T = P[tk]
        To = P[one_pos(P, opp=True)]
        roe = 35.0 * T.w35_r.to_numpy()
        roe_o = 35.0 * To.w35_opp_r.to_numpy()
        days = (b - a) / DAY
        o = {"period": per, "signals": len(P), "trades": len(T), "per_day": len(T) / days, "mean_roe": roe.mean(),
             "mean_roe_pb": roe.mean() + PB35, "win": (roe > 0).mean(), "opp_mean_roe": roe_o.mean(),
             "long_share": (T.side > 0).mean()}
        rr = ref.loc[per]
        lines.append(f"{per}: mine signals {o['signals']} trades {o['trades']} per_day {o['per_day']:.3f} mean {o['mean_roe']:.5f}"
                     f" (pb {o['mean_roe_pb']:.5f}) win {o['win']:.4f} flip {o['opp_mean_roe']:.5f} | study signals"
                     f" {int(rr.signals)} trades {int(rr.trades)} per_day {rr.per_day:.3f} mean {rr.mean_roe:.5f} (pb"
                     f" {rr.mean_roe_pb:.5f}) win {rr.win:.4f} flip {rr.opp_mean_roe:.5f}")
        T = T.assign(period=per)
        taken.append(T)
        if per in ("CONF", "FWD"):
            p6, p50, p90, med = boot(roe + PB35, T.t.to_numpy(np.int64), a, b)
            q = rb[(rb.period == per) & (rb.margin == 0.4) & (rb.payback)].iloc[0]
            lines.append(f"  bootstrap m0.4 payback: mine P(x6) {p6:.4f} P(-50 first) {p50:.4f} P(-90 first) {p90:.4f}"
                         f" median {med:.4f} | study {q.p_target:.4f} {q.p_lose50_first:.4f} {q.p_lose90_first:.4f}"
                         f" {q.median_final_x:.4f}")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(HERE, "dsk_gbot.txt"), "w").write(txt + "\n")
    keep = ["period", "cell", "prio", "name", "tf", "coin", "side", "t", "e", "nb", "hidx", "state", "w35_r", "w35_k",
            "w35_why", "w35_opp_r", "w35_opp_k", "w35_opp_why"]
    pd.concat(taken)[keep].to_csv(os.path.join(HERE, "dsk_gbot_trades.csv"), index=False)


if __name__ == "__main__":
    main()
