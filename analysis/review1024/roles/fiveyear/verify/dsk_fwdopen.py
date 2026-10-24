"""Direction-skill verifier, part 5: the last-19-days rows of bot G that the study drops because SOME outcome (any of
w35 / w30 / w35s20 / a2, either side) was still open at the data end (2026-10-24 14:12 UTC) -- a selection made with
information after the entry. Counts them and re-reads G's last 19 days keeping every row whose w35 outcome (both sides)
is closed (the only exit the claim uses), one position at a time, same priority as the study.

    python3 dsk_fwdopen.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsk_gbot as GB                       # noqa: E402
from dsk_gbot import *                      # noqa: E402,F401
from dsk_gbot_prio import exact_cells       # noqa: E402


def rows_loose(name, etf, htf, kind, source):
    """As dsk_gbot.rows_of for the last 19 days, but only w35 (both sides) must be closed."""
    S = RD.signals(names=[name], tfs=[etf], period=FWD)
    if not len(S):
        return S
    S = RD.add_outcomes(S, ["w35", "w30", "w35s20", "a2"])
    strict = np.ones(len(S), bool)
    for v in ("w35", "w30", "w35s20", "a2"):
        for s_ in ("", "_opp"):
            strict &= np.isfinite(S[f"{v}{s_}_r"].to_numpy()) & (S[f"{v}{s_}_why"].to_numpy() != 3)
    loose = np.ones(len(S), bool)
    for s_ in ("", "_opp"):
        loose &= np.isfinite(S[f"w35{s_}_r"].to_numpy()) & (S[f"w35{s_}_why"].to_numpy() != 3)
    S["strict"], S["loose"] = strict, loose
    t = S.t.to_numpy(np.int64)
    side = S.side.to_numpy(np.int64)
    st = np.full(len(S), 99, np.int64)
    J = {k: np.full(len(S), np.nan) for k in ("dir", "adx", "adx_prev", "ema20", "atr")}
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if not m.any():
            continue
        hc = htf_close(coin, htf)
        idx = np.searchsorted(hc, t[m], side="right") - 1
        Z = RD._states(coin, htf)
        good = idx >= 1
        good[good] &= Z["nb"][idx[good]] >= 300
        ii = np.maximum(idx, 0)
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
    if kind == "j" and source in ("TB22", "TB21"):
        sp = RD.spot(S)
        w, _a, _b = tj_check(S.name.to_numpy(), S.tf.to_numpy(), side.astype(float), sp["spot_close"], J,
                             {k: sp[k] for k in ("spot_ema20", "spot_atr", "spot_rsi")}, hold_entry=(source == "TB22"))
        with_ = (w == "") & (J["dir"] == side) & (st != 99)
    else:
        with_ = (st != 99) & (st * side == 1)
    return S[with_].reset_index(drop=True)


def main():
    G = exact_cells()
    parts = []
    for p, r in G.iterrows():
        S = rows_loose(r["name"], r.etf, r.htf, r.kind, r.source)
        if len(S):
            S["prio"] = p
            parts.append(S)
    A = pd.concat(parts, ignore_index=True)
    A = A.sort_values("prio", kind="stable").drop_duplicates(["coin", "e", "side", "name", "tf"])
    A = A.sort_values(["e", "prio"], kind="stable").reset_index(drop=True)
    lines = [f"last 19 days, G with-rows: {len(A)}; kept by the study's rule (all exits closed): {int(A.strict.sum())};"
             f" w35 closed both sides: {int(A.loose.sum())}; w35 still open: {int((~A.loose).sum())}"]
    for lab, m in (("strict (study rule)", A.strict), ("loose (w35 closed)", A.loose)):
        P = A[m].reset_index(drop=True)
        T = P[one_pos(P)]
        To = P[one_pos(P, opp=True)]
        lines.append(f"  {lab}: signals {len(P)} trades {len(T)} mean {35 * T.w35_r.mean():.5f} flip {35 * To.w35_opp_r.mean():.5f}"
                     f" last entry {pd.Timestamp(int(T.t.max()), unit='ms')}")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(GB.HERE, "dsk_fwdopen.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
