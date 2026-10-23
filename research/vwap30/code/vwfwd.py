"""PREREG_FWD1.md: the frozen 'VWAP 개선판' (VWAP fail 30m; weekdays, no entry around US macro releases or the NYSE open,
not against the trend bot's 4h vote, not when ATR % is above its 30-day 80th percentile; stop 2 ATR, the rule bot's
ladder, 96 bars; margin 30 % at min(30, 0.5 / (2 ATR % + cost)); one position) scored only on data from 2026-10-23 00:00
UTC on, next to the paper rules (control) and a coin-flip twin of the candidate. PREREG_FWD1_AMEND1.md adds candidate B
('VWAP 엄선판': 4h vote, VWAP distance >= 0.3 ATR, ADX >= 25, the same pauses, exits and size; no volatility skip) and
moves both twins' bar to the 97.5th percentile; PREREG_FWD1_AMEND2.md adds candidate C (A + no entry when the 4h ADX is
below 20) and moves all three bars to the 98.33rd percentile; PREREG_FWD1_AMEND3.md adds candidate D (A + CMO
sandwich 1h with A's two gates, one position, VWAP first: the live bot the owners chose on 10/23) and moves all four bars
to the 98.75th percentile.

Before a run: bash research/newlive/code/download.sh <last day>; python3 -I research/newlive/code/judge_all.py
    python3 -I vwfwd.py   -> research/vwap30/fwd1.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *
from vwfix4 import quiet_values
from vwacct import _take
import vwadd as AD
from vwadd import rows_of, outcomes_k, gates
from multiprocessing import Pool

AD.PHOTO = [("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들 1시간")]
TWIN_Q = 100 - 5 / 4                                                 # four candidates (AMEND3)
TWIN_K = "p98.75"


def account_prio(t, coin, prio, ret, tx, mask, expo):
    """account2 with a member order at the same minute (D: VWAP first, then CMO; then BTC .. BCH)."""
    o = np.lexsort((coin, prio, t))
    ext = t[o] + (tx[o] + 1) * MIN
    k = _take(t[o], ext, mask[o])                     # positions in the sorted order
    r = ret[o][k]
    x = expo[o][k] * r
    eq = np.exp(np.cumsum(np.log1p(np.maximum(x, -1 + 1e-12))))
    dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()) if len(eq) else 0.0
    roe = LEVP * r
    w, l = roe[roe > 0], roe[roe <= 0]
    return {"n": int(len(r)), "wins": int((r > 0).sum()), "losses": int((r <= 0).sum()),
            "win": round(float((r > 0).mean()), 4) if len(r) else None,
            "avg_win_roe": round(float(w.mean() * 100), 1) if len(w) else None,
            "avg_loss_roe": round(float(l.mean() * 100), 1) if len(l) else None,
            "avg_net_pct": round(float(r.mean() * 100), 4) if len(r) else None,
            "mult": round(float(eq[-1]), 4) if len(eq) else 1.0, "maxdd": round(dd, 4)}


def cmo_rows():
    """CMO sandwich 1h signals from the forward start (the rule bot's code on 5m-built frames, vwadd.sig_job), with the
    outcome of the signal's side and of the other side (the twins)."""
    with Pool(2) as pool:
        sig = dict(pool.map(AD.sig_job, COINS))
    parts = []
    for coin in COINS:
        R = rows_of(coin, "1h", sig[coin][("S3_CMO_SANDWICH", "1h")])
        R = R[R.t >= FWD0].reset_index(drop=True)
        if not len(R):
            continue
        Rf = R.copy()
        Rf["side"] = -Rf["side"]
        R["r"], R["x"] = outcomes_k(coin, R, 60)
        R["r_o"], R["x_o"] = outcomes_k(coin, Rf, 60)
        parts.append(R)
    return pd.concat(parts, ignore_index=True) if parts else None

FWD0 = ms("2026-10-23")
DECIDE_N, DECIDE_BY = 300, ms("2027-03-01")
SEEDF = 20261106


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        R = R[R.t >= FWD0].reset_index(drop=True)
        if not len(R):
            continue
        O = outcomes_tf(coin, R, 30)
        Rf = R.copy()
        Rf["side"] = -Rf["side"]
        Of = outcomes_tf(coin, Rf, 30)
        R["r"], R["x"] = O["base"]
        R["r_o"], R["x_o"] = Of["base"]
        R["adx4"] = quiet_values(coin, R.t.to_numpy())[0]
        parts.append(R)
    out = {"forward_from_utc": str(pd.Timestamp(FWD0, unit="ms")), "data_end_utc": str(pd.Timestamp(DATA_END, unit="ms"))}
    X = cmo_rows()
    if not parts and X is None:
        out["note"] = "앞으로 기간의 신호가 아직 없음"
        print(out)
        json.dump(out, open(os.path.join(RES_DIR, "fwd1.json"), "w"), ensure_ascii=False, indent=1)
        return
    R = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=list(dict.fromkeys(X.columns.tolist() + ["adx4"])))
    R = R.assign(prio=0)
    if X is not None:                                 # D: the CMO rows after the VWAP rows (A's own masks stay on VWAP)
        X = X.assign(prio=1, adx4=np.nan)
        R = pd.concat([R, X[[c for c in R.columns if c in X.columns]]], ignore_index=True)
    R = R.astype({"t": np.int64, "coin": np.int64, "x": np.int64, "x_o": np.int64})
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    done = t + (R.x.to_numpy() + 1) * MIN < DATA_END - MIN          # trades still open at the data end are not scored
    base = wd & ~usop & ~macro & done
    vw = R.prio.to_numpy() == 0
    gate = ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    cand = base & vw & gate
    cand_d = base & gate                              # VWAP rows as A, CMO rows with the same two gates
    cand_b = base & vw & ~(R.j4h.to_numpy() < 0) & ~(R.cva.to_numpy() < 0.3) & ~(R.adx.to_numpy() < 25)
    cand_c = cand & ~(R.adx4.to_numpy() < 20)
    lev_cap = 0.3 * np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    e9 = np.full(len(R), 0.3 * LEVP)
    r, x, ro, xo = R.r.to_numpy(), R.x.to_numpy(), R.r_o.to_numpy(), R.x_o.to_numpy()
    out["control_paper_rules"] = account2(t, coin, r, x, base & vw, e9)
    prio = R.prio.to_numpy()
    out["months"] = {}
    mon = pd.to_datetime(t + KST, unit="ms").to_period("M").astype(str)
    for name, cm, seed in (("A_VWAP개선판", cand, SEEDF), ("B_VWAP엄선판", cand_b, SEEDF + 1),
                           ("C_VWAP개선판_횡보금지", cand_c, SEEDF + 2), ("D_VWAP개선판_CMO1시간", cand_d, SEEDF + 3)):
        res = account_prio(t, coin, prio, r, x, cm, lev_cap)
        rng = np.random.default_rng(seed)
        tw = []
        for _ in range(2000):
            f = rng.random(len(R)) < 0.5
            tw.append(np.log(max(account_prio(t, coin, prio, np.where(f, ro, r), np.where(f, xo, x), cm, lev_cap)["mult"],
                                 1e-12)))
        tw = np.array(tw)
        g = np.log(max(res["mult"], 1e-12))
        res["twin"] = {"p50": round(float(np.median(tw)), 4), TWIN_K: round(float(np.percentile(tw, TWIN_Q)), 4),
                       "share_below": round(float((tw < g).mean()), 4)}
        n = res["n"]
        if n >= DECIDE_N or DATA_END >= DECIDE_BY:
            res["verdict"] = "통함" if (res["avg_net_pct"] or 0) > 0 and g > res["twin"][TWIN_K] else "통하지 않음"
        else:
            res["verdict"] = f"중간 보고(판정 전): 거래 {n}번 / 판정은 {DECIDE_N}번 또는 2027-02-28 데이터"
        out[name] = res
        for m in sorted(set(mon)):
            k = np.asarray(mon == m)
            out["months"].setdefault(m, {})[name] = account_prio(t, coin, prio, r, x, cm & k, lev_cap)
    for m in sorted(set(mon)):
        k = np.asarray(mon == m)
        out["months"][m]["control"] = account2(t, coin, r, x, base & vw & k, e9)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open(os.path.join(RES_DIR, "fwd1.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    if "--dry-from" in sys.argv:              # code check on past data only: prints, writes nothing
        FWD0 = ms(sys.argv[sys.argv.index("--dry-from") + 1])
        RES_DIR = os.path.join(OUT, "_dry")
        os.makedirs(RES_DIR, exist_ok=True)
    main()
