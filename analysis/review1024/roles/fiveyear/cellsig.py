"""Signal-level rows of chosen cells (for accounts and goal paths), built with the data layer's loader exactly as the
accumulators of build_acc.py count them: entry strategy `name` on timeframe `etf`, trend source (kind, source) read on
the last closed `htf` bar (bar number >= 300, warm-up), condition W (with) / A (against) / N (neutral) / P (passes the
trend bot's check = W or N, for TB22) / ALL. Rows whose outcome is still open at the data end (any exit, either side) are
dropped, as in the accumulators."""
from fy_common import *
from build_acc import judge_cols

SPAN = (int(EDGES[0]), int(EDGES[-1]))


def cell_rows(name, etf, htf, kind, source, cond, span=SPAN, exits=("w35", "w30", "w35s20", "a2"), payback=False):
    S = RD.signals(names=[name], tfs=[etf], period=span)
    if not len(S):
        return S
    S = RD.add_outcomes(S, list(exits), payback=payback)
    ok = np.ones(len(S), bool)
    for v in exits:
        for sfx in ("", "_opp"):
            ok &= np.isfinite(S[f"{v}{sfx}_r"].to_numpy()) & (S[f"{v}{sfx}_why"].to_numpy() != 3)
    S = S[ok].reset_index(drop=True)
    if cond == "ALL" and kind is None:
        return RD.add_blocks(S)
    idx = RD.htf_index(S, htf)
    st = np.zeros(len(S), np.int8)
    warm = np.zeros(len(S), bool)
    J = {k: np.full(len(S), np.nan) for k in ("dir", "adx", "adx_prev", "ema20", "atr")}
    for ci, coin in enumerate(COINS):
        m = (S.coin.to_numpy() == ci) & (idx >= 1)
        if not m.any():
            continue
        Z = RD._states(coin, htf)
        ii = idx[m]
        warm[m] = Z["nb"][ii] >= 300
        jc, Jc = judge_cols(Z, ii)
        for k in J:
            J[k][m] = Jc[k]
        if kind in ("c", "l"):
            st[m] = Z[f"{kind}_{source}"][ii]
        elif source in jc:
            st[m] = jc[source]
    side = S.side.to_numpy()
    if kind == "j" and source in ("TB22", "TB21"):
        from build_forward import tj_check
        sp = RD.spot(S)
        w, _a, _b = tj_check(S.name.to_numpy(), S.tf.to_numpy(), side.astype(float), sp["spot_close"], J,
                             {k: sp[k] for k in ("spot_ema20", "spot_atr", "spot_rsi")}, hold_entry=(source == "TB22"))
        c = np.full(len(S), -1, np.int8)
        c[(w == "") & (J["dir"] == side)] = 1
        c[(w == "") & (J["dir"] == 0)] = 0
        c[w == "na"] = 9
    else:
        c = (st * side).astype(np.int8)
    S["cond"] = c
    S = S[warm]
    keep = {"W": [1], "A": [-1], "N": [0], "P": [0, 1], "ALL": [-1, 0, 1]}[cond]
    S = S[S.cond.isin(keep)].reset_index(drop=True)
    S["cell"] = f"{name}@{etf}|{kind}:{source}@{htf}|{cond}"
    return RD.add_blocks(S)


def period_rows(S, per):
    a, b = {"SEL": (EDGES[0], EDGES[3]), "CONF": (EDGES[3], EDGES[6]), "LATE": (EDGES[5], EDGES[8]),
            "FWD": (EDGES[7], EDGES[9]), "ALL": (EDGES[0], EDGES[9])}[per]
    return S[(S.t >= a) & (S.t < b)]


PER_SPAN = {"SEL": (int(EDGES[0]), int(EDGES[3])), "CONF": (int(EDGES[3]), int(EDGES[6])),
            "LATE": (int(EDGES[5]), int(EDGES[8])), "FWD": (int(EDGES[7]), int(EDGES[9]))}
