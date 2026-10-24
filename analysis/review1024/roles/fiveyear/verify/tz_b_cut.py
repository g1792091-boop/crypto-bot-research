"""Verifier (lens: look-ahead) -- step 3: CUT tests at the B_sel_with20 bot's own CONFIRM trades. For a seeded sample of
taken trades per cell:

  entry   the cell's entry strategy is recomputed by the data layer's own code (build_signals.coin_signals) on the
          entry-timeframe bars s .. i (cut at the signal bar i: no later bar exists) and on s .. i + 300 (with the
          future). A difference on the last 300 bars <= i = the signal at a bar depends on later bars (look-ahead).
          Also: the cut run must give the trade's side at bar i (the trade is reproducible from past data only).
  source  the cell's trend source on the higher timeframe: condition state (build_states.cond_states), latch (the
          source strategy's own signals on htf, latched) or the four judges (build_states.judge_arrays, V4OF4), on the
          higher bars cut at the bar the study read (j = last closed at the signal time) vs with 50 later bars; the cut
          value at j must equal the stored state and the trade's side.
    python3 tz_b_cut.py <workdir> [per_cell]"""
import os
import sys
DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
import build_states as BS       # noqa: E402
import build_signals as BG      # noqa: E402
from common import *            # noqa: E402,F401

WD = sys.argv[1]
PER = int(sys.argv[2]) if len(sys.argv) > 2 else 12
VH = os.path.dirname(os.path.abspath(__file__))
W_ENTRY = {"15m": 3000, "30m": 3000, "1h": 3000, "4h": 2000}
W_HTF = {"1h": 3000, "4h": 3000, "1d": 100000}       # 1d: the whole history up to the cut
_B = {}


def B(coin, tf):
    if (coin, tf) not in _B:
        _B[(coin, tf)] = bars(coin, tf)
    return _B[(coin, tf)]


def sig(coin, tf, df, name):
    df = df.reset_index(drop=True)
    out = BG.coin_signals(coin, tf, df, df, {}, only={name})
    lg, sh = out[name]
    lg = np.asarray(lg, bool)
    sh = np.asarray(sh, bool) & ~lg
    return lg.astype(np.int8) - sh.astype(np.int8)


def v4(J):
    s = sum(np.asarray(J[f"j_{k}"], int) for k in ("V39", "S6", "OBV", "N12"))
    return np.where(np.abs(s) == 4, np.sign(s), 0)


def state(coin, htf, df, kind, src):
    df = df.reset_index(drop=True)
    if kind == "j":
        J = BS.judge_arrays(df, htf)
        assert src == "V4OF4"
        return v4(J)
    if kind == "l":
        return BS.latch_of(*[(x > 0) for x in (sig(coin, htf, df, src),)], *[(x < 0) for x in (sig(coin, htf, df, src),)])
    nx = BS.NEXT_HTF[htf]
    nxt = None
    if nx is not None:
        dn = B(coin, nx)
        cl = close_ms(df, htf)[-1]
        nxt = (nx, dn[close_ms(dn, nx) <= cl].reset_index(drop=True))
    return np.asarray(BS.cond_states(df, htf, nxt)[src], int)


def stored(coin, htf, kind, src, j):
    Z = RD._states(coin, htf)
    if kind == "j":
        return int(v4({k: Z[k] for k in Z if k.startswith("j_")})[j])
    return int(Z[f"{kind}_{src}"][j])


def run_cell(arg):
    cell, rows = arg
    name, rest = cell.split("@", 1)
    etf = rest.split("|")[0]
    kind, src = rest.split("|")[1].split("@")[0].split(":")
    htf = rest.split("|")[1].split("@")[1]
    res = []
    for _, r in rows.iterrows():
        coin = COINS[int(r.coin)]
        t = int(r.t)
        df = B(coin, etf)
        cl = close_ms(df, etf)
        i = int(np.searchsorted(cl, t))
        assert cl[i] == t
        s = max(0, i - W_ENTRY[etf])
        cut = sig(coin, etf, df.iloc[s:i + 1], name)
        fut = sig(coin, etf, df.iloc[s:i + 301], name)
        n = i + 1 - s
        lo = max(0, n - 300)
        ent_diff = int((cut[lo:n] != fut[lo:n]).sum())
        dh = B(coin, htf)
        ch = close_ms(dh, htf)
        j = int(np.searchsorted(ch, t, side="right") - 1)
        sh_ = max(0, j - W_HTF[htf])
        sc = state(coin, htf, dh.iloc[sh_:j + 1], kind, src)
        sf = state(coin, htf, dh.iloc[sh_:j + 51], kind, src)
        m = j + 1 - sh_
        lo2 = max(0, m - 50)
        res.append({"cell": cell, "coin": coin, "t": t, "side": int(r.side), "entry_cut_side": int(cut[n - 1]),
                    "entry_cut_vs_future_diffs": ent_diff, "htf_bar_close_le_t": bool(ch[j] <= t),
                    "next_htf_close_gt_t": bool(j + 1 >= len(ch) or ch[j + 1] > t),
                    "state_cut": int(sc[m - 1]), "state_stored": stored(coin, htf, kind, src, j),
                    "state_cut_vs_future_diffs": int((sc[lo2:m] != sf[lo2:m]).sum())})
    log(cell, len(res))
    return res


if __name__ == "__main__":
    from multiprocessing import get_context
    T = pd.read_pickle(os.path.join(WD, "B_taken_CONF.pkl"))
    rng = np.random.default_rng(20261024)
    jobs = []
    for cell, g in T.groupby("cell"):
        g = g.iloc[np.sort(rng.choice(len(g), min(PER, len(g)), replace=False))]
        jobs.append((cell, g))
    BG.NAMES = None
    with get_context("fork").Pool(4) as pool:
        out = [x for part in pool.imap_unordered(run_cell, jobs) for x in part]
    D = pd.DataFrame(out)
    D.to_csv(os.path.join(VH, "tz_b_cut.csv"), index=False)
    D["entry_ok"] = D.entry_cut_side == D.side
    D["state_ok"] = (D.state_cut == D.state_stored) & (D.state_cut == D.side)
    print(D.groupby("cell")[["entry_ok", "entry_cut_vs_future_diffs", "state_ok", "state_cut_vs_future_diffs"]]
          .agg(["mean", "sum"]).to_string())
    print("TOTAL trades", len(D), "entry reproduced from cut data", int(D.entry_ok.sum()),
          "entry future diffs", int(D.entry_cut_vs_future_diffs.sum()), "state reproduced", int(D.state_ok.sum()),
          "state future diffs", int(D.state_cut_vs_future_diffs.sum()),
          "htf alignment ok", int((D.htf_bar_close_le_t & D.next_htf_close_gt_t).sum()))
