"""Luck / multiple-testing verifier, step 4 (bot level null): would 20 cells picked by chance, run as the same one-position
bot (w35, all coins, priority = pick order, a signal reached by two cells counted once), do as well on CONFIRM as
B_sel_with20 (CONF -2.775 % per trade, -0.129 % with payback)?

Nulls (each NB bots, seed fixed):
  N1 mix_selpos   20 eligible with-cells with SELECT mean > 0, same (entry tf, trend tf) mix as B, distinct (strategy, tf)
  N2 mix_all      20 eligible with-cells (no SELECT sign filter), same mix as B
  N3 selpos       20 eligible with-cells with SELECT mean > 0, any mix
  N4 same_entries B's 20 (strategy, entry tf, trend tf) with the trend SOURCE replaced by a random eligible source
                  (with-condition) of that entry  -> does B's SELECT-picked source matter?
Eligible = the study's family rule (SELECT n >= 60 in >= 12 months, with-condition), from the rebuilt cells.pkl.
Rows are rebuilt exactly as cellsig.cell_rows (all four exits finite and closed, warm-up >= 300 on the higher bar).

    python3 lm_botnull.py [NB]   -> lm_botnull.csv (one row per null bot), lm_botnull_summary.csv"""
import os
import sys
import time

FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
MY = "/dev/shm/claude_verify_lm"
sys.path.insert(0, FY)
import fy_common                         # noqa: E402
fy_common.SHM = MY
from fy_common import *                  # noqa: E402,F401
from build_acc import judge_cols         # noqa: E402
from fy_analyze import SEL_MIN           # noqa: E402

OUTD = os.path.dirname(os.path.abspath(__file__))
PBR = 35.0 * PAYBACK
CA, CB = int(EDGES[3]), int(EDGES[6])                  # CONFIRM 2024-01-01 .. 2026-10-01
SPAN = (int(EDGES[0]), int(EDGES[-1]))
EXITS = ("w35", "w30", "w35s20", "a2")
_C = {}
_H = {}


def entry_rows(name, etf):
    """CONFIRM rows of one entry (strategy, tf), filtered exactly as cell_rows (rows of the whole SPAN first)."""
    key = (name, etf)
    if key not in _C:
        S = RD.signals(names=[name], tfs=[etf], period=SPAN)
        if len(S):
            S = RD.add_outcomes(S, list(EXITS))
            ok = np.ones(len(S), bool)
            for v in EXITS:
                for sfx in ("", "_opp"):
                    ok &= np.isfinite(S[f"{v}{sfx}_r"].to_numpy()) & (S[f"{v}{sfx}_why"].to_numpy() != 3)
            S = S[ok]
            S = S[(S.t >= CA) & (S.t < CB)].reset_index(drop=True)
            S = S[["coin", "side", "t", "e", "w35_roe", "w35_k"]].copy()
        _C[key] = S
    return _C[key]


def htf_info(name, etf, htf):
    key = (name, etf, htf)
    if key not in _H:
        S = entry_rows(name, etf)
        idx = RD.htf_index(S, htf) if len(S) else np.zeros(0, np.int64)
        _H[key] = idx
    return _H[key]


def cell_mask(name, etf, htf, kind, source):
    S = entry_rows(name, etf)
    if not len(S):
        return np.zeros(0, bool)
    idx = htf_info(name, etf, htf)
    st = np.zeros(len(S), np.int8)
    warm = np.zeros(len(S), bool)
    coin = S.coin.to_numpy()
    for ci, c in enumerate(COINS):
        m = (coin == ci) & (idx >= 1)
        if not m.any():
            continue
        Z = RD._states(c, htf)
        ii = idx[m]
        warm[m] = Z["nb"][ii] >= 300
        if kind in ("c", "l"):
            st[m] = Z[f"{kind}_{source}"][ii]
        else:
            jc, _J = judge_cols(Z, ii)
            st[m] = jc[source]
    return warm & ((st * S.side.to_numpy()) == 1)


def bot_conf(cells):
    """cells: list of (name, etf, htf, kind, source) in priority order -> (trades, mean roe) on CONFIRM."""
    parts = []
    for i, (nm, etf, htf, kind, src) in enumerate(cells):
        S = entry_rows(nm, etf)
        if not len(S):
            continue
        m = cell_mask(nm, etf, htf, kind, src)
        if not m.any():
            continue
        P = S[m].assign(prio=i, name=nm, tf=etf)
        parts.append(P)
    if not parts:
        return 0, np.nan, np.nan
    P = pd.concat(parts, ignore_index=True)
    P = P.sort_values("prio").drop_duplicates(["coin", "e", "side", "name", "tf"])
    took = RD.one_position(P, "w35", priority="prio")
    T = P[took]
    return len(T), T.w35_roe.mean(), (T.w35_roe > 0).mean()


def main(NB=300):
    t0 = time.time()
    D = pd.read_pickle(os.path.join(MY, "cells.pkl"))
    E = D[(D.SEL_nW >= SEL_MIN) & (D.SEL_MW >= 12)].copy()
    E = E[~((E.kind == "j") & E.source.isin(["TB22", "TB21"]))]     # the trend bot's whole check: not rebuilt here
    E["key"] = E["name"] + "@" + E.etf
    sel = pd.read_csv(os.path.join(FY, "shortlist.csv"))
    B = [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1]) for _, r in
         sel[sel.cond == "W"].iterrows()]
    n, mu, win = bot_conf(B)
    print(f"B rebuilt with the cached path: trades {n}, CONF mean {mu:.5f} (study -0.02775, 2487), win {win:.4f}",
          flush=True)
    mix = pd.Series([(b[1], b[2]) for b in B]).value_counts().to_dict()
    rng = np.random.default_rng(20261024)
    rows = []

    def draw_mix(pool):
        used, pick = set(), []
        for (etf, htf), c in mix.items():
            g = pool[(pool.etf == etf) & (pool.htf == htf)]
            g = g.iloc[rng.permutation(len(g))]
            got = 0
            for _, r in g.iterrows():
                if r.key in used:
                    continue
                used.add(r.key)
                pick.append((r["name"], r.etf, r.htf, r.kind, r.source))
                got += 1
                if got == c:
                    break
        rng.shuffle(pick)
        return pick

    Epos = E[E.SEL_mW > 0]
    Emix = E[[(a, b) in mix for a, b in zip(E.etf, E.htf)]]
    Epos_mix = Epos[[(a, b) in mix for a, b in zip(Epos.etf, Epos.htf)]]
    print("pools: eligible", len(E), "selpos", len(Epos), "mix-groups eligible", len(Emix), "selpos mix", len(Epos_mix),
          flush=True)
    for b in range(NB):
        for lab in ("mix_selpos", "mix_all", "selpos", "same_entries"):
            if lab == "mix_selpos":
                cells = draw_mix(Epos_mix)
            elif lab == "mix_all":
                cells = draw_mix(Emix)
            elif lab == "selpos":
                uk = Epos.key.unique()
                ks = rng.choice(uk, 20, replace=False)
                cells = []
                for k in ks:
                    g = Epos[Epos.key == k]
                    r = g.iloc[rng.integers(len(g))]
                    cells.append((r["name"], r.etf, r.htf, r.kind, r.source))
            else:
                cells = []
                for (nm, etf, htf, kind, src) in B:
                    g = E[(E["name"] == nm) & (E.etf == etf) & (E.htf == htf)]
                    r = g.iloc[rng.integers(len(g))]
                    cells.append((nm, etf, htf, r.kind, r.source))
            n, mu, win = bot_conf(cells)
            rows.append({"null": lab, "b": b, "trades": n, "mean_roe": mu, "win": win})
        if b % 25 == 0:
            print(b, f"{time.time() - t0:.0f}s", "cache", len(_C), flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(OUTD, "lm_botnull.csv"), index=False, float_format="%.6g")
    Bm = -0.027747                                  # the study's B (our cached path gives -0.02702: tie order)
    S = R.groupby("null").agg(bots=("mean_roe", "size"), trades_med=("trades", "median"),
                              mean=("mean_roe", "mean"), p05=("mean_roe", lambda x: x.quantile(0.05)),
                              p50=("mean_roe", "median"), p95=("mean_roe", lambda x: x.quantile(0.95)),
                              share_ge_B=("mean_roe", lambda x: (x >= Bm).mean()),
                              share_pb_ge_0=("mean_roe", lambda x: (x + PBR >= -0.00129).mean())).reset_index()
    S["B_conf"] = Bm
    S.to_csv(os.path.join(OUTD, "lm_botnull_summary.csv"), index=False, float_format="%.6g")
    print(S.round(5).to_string())
    print(f"done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
