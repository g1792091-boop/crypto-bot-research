"""PREREG_FWD1.md: the frozen 'VWAP 개선판' (VWAP fail 30m; weekdays, no entry around US macro releases or the NYSE open,
not against the trend bot's 4h vote, not when ATR % is above its 30-day 80th percentile; stop 2 ATR, the rule bot's
ladder, 96 bars; margin 30 % at min(30, 0.5 / (2 ATR % + cost)); one position) scored only on data from 2026-10-23 00:00
UTC on, next to the paper rules (control) and a coin-flip twin of the candidate. PREREG_FWD1_AMEND1.md adds candidate B
('VWAP 엄선판': 4h vote, VWAP distance >= 0.3 ATR, ADX >= 25, the same pauses, exits and size; no volatility skip) and
moves both twins' bar to the 97.5th percentile; PREREG_FWD1_AMEND2.md adds candidate C (A + no entry when the 4h ADX is
below 20) and moves all three bars to the 98.33rd percentile.

Before a run: bash research/newlive/code/download.sh <last day>; python3 -I research/newlive/code/judge_all.py
    python3 -I vwfwd.py   -> research/vwap30/fwd1.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *
from vwfix4 import quiet_values

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
    if not parts:
        out["note"] = "앞으로 기간의 신호가 아직 없음"
        print(out)
        json.dump(out, open(os.path.join(RES_DIR, "fwd1.json"), "w"), ensure_ascii=False, indent=1)
        return
    R = pd.concat(parts, ignore_index=True)
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    done = t + (R.x.to_numpy() + 1) * MIN < DATA_END - MIN          # trades still open at the data end are not scored
    base = wd & ~usop & ~macro & done
    cand = base & ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    cand_b = base & ~(R.j4h.to_numpy() < 0) & ~(R.cva.to_numpy() < 0.3) & ~(R.adx.to_numpy() < 25)
    cand_c = cand & ~(R.adx4.to_numpy() < 20)
    lev_cap = 0.3 * np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    e9 = np.full(len(R), 0.3 * LEVP)
    r, x, ro, xo = R.r.to_numpy(), R.x.to_numpy(), R.r_o.to_numpy(), R.x_o.to_numpy()
    out["control_paper_rules"] = account2(t, coin, r, x, base, e9)
    out["months"] = {}
    mon = pd.to_datetime(t + KST, unit="ms").to_period("M").astype(str)
    for name, cm, seed in (("A_VWAP개선판", cand, SEEDF), ("B_VWAP엄선판", cand_b, SEEDF + 1),
                           ("C_VWAP개선판_횡보금지", cand_c, SEEDF + 2)):
        res = account2(t, coin, r, x, cm, lev_cap)
        rng = np.random.default_rng(seed)
        tw = []
        for _ in range(2000):
            f = rng.random(len(R)) < 0.5
            tw.append(np.log(max(account2(t, coin, np.where(f, ro, r), np.where(f, xo, x), cm, lev_cap)["mult"], 1e-12)))
        tw = np.array(tw)
        g = np.log(max(res["mult"], 1e-12))
        res["twin"] = {"p50": round(float(np.median(tw)), 4), "p98.33": round(float(np.percentile(tw, 100 - 5 / 3)), 4),
                       "share_below": round(float((tw < g).mean()), 4)}
        n = res["n"]
        if n >= DECIDE_N or DATA_END >= DECIDE_BY:
            res["verdict"] = "통함" if (res["avg_net_pct"] or 0) > 0 and g > res["twin"]["p98.33"] else "통하지 않음"
        else:
            res["verdict"] = f"중간 보고(판정 전): 거래 {n}번 / 판정은 {DECIDE_N}번 또는 2027-02-28 데이터"
        out[name] = res
        for m in sorted(set(mon)):
            k = np.asarray(mon == m)
            out["months"].setdefault(m, {})[name] = account2(t, coin, r, x, cm & k, lev_cap)
    for m in sorted(set(mon)):
        k = np.asarray(mon == m)
        out["months"][m]["control"] = account2(t, coin, r, x, base & k, e9)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open(os.path.join(RES_DIR, "fwd1.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    if "--dry-from" in sys.argv:              # code check on past data only: prints, writes nothing
        FWD0 = ms(sys.argv[sys.argv.index("--dry-from") + 1])
        RES_DIR = os.path.join(OUT, "_dry")
        os.makedirs(RES_DIR, exist_ok=True)
    main()
