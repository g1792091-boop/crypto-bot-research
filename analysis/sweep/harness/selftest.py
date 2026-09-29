"""Synthetic-only self tests for sweep_lib (no real market data is read here).
usage: python3 selftest.py [--quick]  -> out/selftest_*.csv / out/selftest.log"""
import math
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
quick = "--quick" in sys.argv
res = []


def check(name, ok, detail=""):
    res.append(dict(test=name, ok=bool(ok), detail=str(detail)))
    ds_ = str(detail)
    print(("PASS " if ok else "FAIL ") + name + ("  " + ds_ if ds_ else ""), flush=True)


# 1. tf parsing / warm-up / hurdle cost
check("tf_minutes", [L.tf_minutes(t) for t in ("5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w")] ==
      [5, 15, 30, 60, 120, 240, 1440, 10080])
check("warmup_bars", {t: L.warmup_bars(t) for t in L.TFS} == {"5m": 8640, "15m": 2880, "30m": 1440, "1h": 720,
                                                              "4h": 300, "1d": 200},
      {t: L.warmup_bars(t) for t in L.TFS})
check("cost_h", abs(L.cost_h(64, "1d") - (0.0014 + 0.0001 * 64 * 1440 / 480)) < 1e-15 and abs(L.cost_h(4, "5m") - (0.0014 + 0.0001 * 20 / 480)) < 1e-15,
      {t: [round(L.cost_h(h, t) * 100, 4) for h in L.HS] for t in L.TFS})

# 2. V4.5 generalised == original strategies.v45_exact_amb at 5m -> 15m
df5 = L.synth_ohlcv(12000, "5m", seed=11, gaps=7)
df15 = L.resample_ohlcv(df5, "15m")
lo, so = L.S.v45_exact_amb(df5, df15)
ln, sn = L.v45_amb(df5, {"15m": df15})
ln2, sn2 = L.v45_amb(df5, None)
check("v45_generalised_equals_original_5m", np.array_equal(lo, ln) and np.array_equal(so, sn) and
      np.array_equal(ln, ln2) and np.array_equal(sn, sn2), f"signals orig={int(lo.sum()+so.sum())}")
# also v45_signals dicts equal for all keys
a = L.S.v45_signals(df5, df15)
b = L.v45_signals_gen(df5, df15, "15m")
check("v45_all_subsignals_equal", all(np.array_equal(a[k], b[k]) for k in a),
      {k: int(a[k].sum()) for k in a})

# 3. DOGE: 5m params == DEFAULT; scaled params per TF (same rule as t_robust/run_tf.py)
p5 = L.doge_params("5m")
check("doge_params_5m_default", all(p5[k] == L.ds.DEFAULT[k] for k in L.DOGE_LEN_KEYS), p5)
tab = {tf: "/".join(str(L.doge_params(tf)[k]) for k in L.DOGE_LEN_KEYS) for tf in L.TFS}
# run_tf.py printed lengths (from doge/t_robust/out_tf.txt) for 15m/30m/1h
ref = {}
try:
    txt = open(os.path.join(L.SWEEP, "..", "doge", "t_robust", "out_tf.txt")).read()
    for tf in ("15m", "30m", "1h"):
        for line in txt.splitlines():
            parts = line.split()
            if parts and parts[0] == tf and "/" in line:
                ref[tf] = [p for p in parts if p.count("/") >= 9][0]
                break
except Exception as e:  # noqa: BLE001
    ref = {"err": repr(e)}
check("doge_params_match_run_tf", all(ref.get(tf) == tab[tf] for tf in ("15m", "30m", "1h")), dict(mine=tab, run_tf=ref))
d5 = df5.set_index(pd.DatetimeIndex(df5["ts"]))[["open", "high", "low", "close", "volume"]]
ind = L.ds.compute_indicators(d5)
sg = L.ds.compute_signals(d5, ind)
dl, _ = L.doge_long(df5)
_, dsh = L.doge_short(df5)
check("doge_5m_equals_port_default", np.array_equal(dl, sg["long_entry"].to_numpy()) and
      np.array_equal(dsh, sg["short_entry"].to_numpy()), f"L={int(dl.sum())} S={int(dsh.sum())}")

# 4. HTF mapping per TF (synthetic with gaps)
nmap = {"5m": 9000, "15m": 6000, "30m": 6000, "1h": 6000, "4h": 4000, "1d": 2000}
for tf in L.TFS:
    d = L.synth_ohlcv(nmap[tf], tf, seed=3, gaps=9)
    r = L.htf_mapping_check(d, tf)
    check(f"htf_mapping_{tf}", r["used_closed_before_open"] and r["next_closes_after_open"] and r["weekly_bins_monday"], r)

# 5. FFT common-shift null == brute-force np.roll
rng = np.random.default_rng(5)
pan = L.synth_panel("1h", n_days=200, seed=9)
prep = L._prep_returns(pan, "1h", "is", 16) if False else None
# synth_panel starts 2021-07-01 -> in the IS window
prep = L._prep_returns(pan, "1h", "is", 16)
dsig = {}
for c, p in prep.items():
    d = np.zeros(len(pan[c]), np.int8)
    m = rng.random(p["N"]) < 0.02
    d[p["lo"]:p["hi"]] = np.where(m, rng.choice([-1, 1], p["N"]), 0)
    dsig[c] = d
n_min = min(p["N"] for p in prep.values())
shifts = L.gate_shifts("1h", 16, n_min, 50)
st = L._cell_stats(dsig, prep, shifts, None)
brute = []
n = sum(int(np.abs(dsig[c][p["lo"]:p["hi"]]).sum()) for c, p in prep.items())
for k in shifts:
    s = 0.0
    for c, p in prep.items():
        dd = np.roll(dsig[c][p["lo"]:p["hi"]].astype(float), k)
        s += float(dd @ p["r"])
    brute.append(s / n)
brute = np.array(brute)
fwd_direct = sum(float(dsig[c][p["lo"]:p["hi"]].astype(float) @ p["r"]) for c, p in prep.items()) / n
check("fft_null_equals_brute_roll", abs(st["null_mean"] - brute.mean()) < 1e-12 and abs(st["null_sd"] - brute.std(ddof=1)) < 1e-12
      and abs(st["fwd"] - fwd_direct) < 1e-15, f"null_mean {st['null_mean']:.3e} brute {brute.mean():.3e}")
st_fft = L._cell_stats(dsig, prep, shifts, np.arange(17, n_min - 16))
check("direct_gather_equals_fft", abs(st["null_sd"] - st_fft["null_sd"]) < 1e-12 and abs(st["z_vn"] - st_fft["z_vn"]) < 1e-9
      and abs(st["z"] - st_fft["z"]) < 1e-9, f"z {st['z']:.6f} vs {st_fft['z']:.6f}; z_vn {st['z_vn']:.6f} vs {st_fft['z_vn']:.6f}")
# self-normalised forward return definition
tt_ = p0 = None
c0 = next(iter(prep)); p0 = prep[c0]; o0 = pan[c0]["open"].to_numpy(); t_ = p0["lo"] + 9
rv_ = np.sqrt(np.sum(np.diff(np.log(o0[t_ + 1:t_ + 18])) ** 2))
check("vn_definition", abs(p0["rn"][9] - np.log(o0[t_ + 17] / o0[t_ + 1]) / rv_) < 1e-12)
check("shift_range", shifts.min() >= 17 and shifts.max() <= n_min - 17, (int(shifts.min()), int(shifts.max()), n_min))
# fwd definition: open[t+1+H]/open[t+1]-1 with side sign
c0 = next(iter(prep)); p0 = prep[c0]; o = pan[c0]["open"].to_numpy()
t = p0["lo"] + 5
check("fwd_definition", abs(p0["r"][5] - (o[t + 17] / o[t + 1] - 1)) < 1e-15)

# 6. Holm vs explicit reference, gate rule logic
pv = np.array([0.01, 0.04, 0.03, 0.005, 0.2])
ref_h = np.array([0.04, 0.09, 0.09, 0.025, 0.2])  # sorted .005*5, .01*4, .03*3, max(.04*2,.09), .2
check("holm", np.allclose(L.holm(pv), ref_h), L.holm(pv))
check("sympos_rule", list(L.sympos_ok([4, 3, 3, 2, 1, 5], [7, 5, 6, 3, 1, 7])) == [True, True, False, True, True, True])

# 7. engine TIME_H exit == open-to-open-ish forward return (close[e+H-1] ~ open[e+H]) and cost
pan1 = {"BTCUSD": L.synth_ohlcv(3000, "1h", seed=21)}
dd = np.zeros(3000, np.int8); dd[1000] = 1; dd[1500] = -1
sigs = {"X": {"BTCUSD": dd}}
ex = L.exit_set(16)
atr = {"BTCUSD": L.fg.atr(pan1["BTCUSD"], 14).to_numpy(float)}
tr = L._run_exits_panel(pan1, sigs["X"], "1h", "is", 16, atr, {"BTCUSD": (720, 2999)}, 0, ex)["TIME_H"]
dfp = pan1["BTCUSD"]
e = 1001
g_exp = (dfp["close"].iloc[e + 15] * (1 - 0.0002)) / (dfp["open"].iloc[e] * 1.0002) - 1
check("engine_time_exit", len(tr) == 2 and int(tr["hold"].iloc[0]) == 16 and abs(tr["gross"].iloc[0] - g_exp) < 1e-12
      and abs(tr["funding"].iloc[0] - 0.0001 * 16 * 60 / 480) < 1e-15 and tr["reason"].iloc[0] == "TIME",
      tr[["side", "entry_idx", "exit_idx", "gross", "net", "hold", "reason"]].to_dict("records"))

# 8. truncation tests on synthetic data, every registry entry at every TF (+ canaries)
ntr = {"5m": 7000, "15m": 6000, "30m": 6000, "1h": 6000, "4h": 4000, "1d": 2200}
allrows = []
for tf in L.TFS:
    for seed in ((101,) if quick else (101, 202)):
        d = L.synth_ohlcv(ntr[tf], tf, seed=seed, gaps=6)
        t0 = time.time()
        tr_rows = L.truncation_test(d, tf, n_even=3 if quick else 4, n_at_signal=2 if quick else 3, seed=seed)
        tr_rows["data"] = f"synthetic_seed{seed}"
        allrows.append(tr_rows)
        reg = tr_rows[~tr_rows["canary"]]
        can = tr_rows[tr_rows["canary"]]
        bad = reg[~reg["identical_prefix"]]
        check(f"truncation_{tf}_seed{seed}", bad.empty,
              f"{len(reg)} checks, {reg.strategy.nunique()} strategies, failures={sorted(bad.strategy.unique())} "
              f"vacuous(no signals)={sorted(reg[reg.sig_full == 0].strategy.unique())} {time.time() - t0:.0f}s")
        cfail = can.groupby(["strategy", "mode"])["identical_prefix"].apply(lambda x: (~x).any())
        need = [("CANARY_LOOKAHEAD", "plain"), ("CANARY_V45_CURRENT_HTF", "components_explicit")]
        check(f"canaries_detected_{tf}_seed{seed}", all(bool(cfail.get(k, False)) for k in need),
              {f"{k[0]}|{k[1]}": bool(v) for k, v in cfail.items()})
# 8b. rare-signal strategies: jumpier / choppier synthetic regimes to make the test non-vacuous
rare = ["N14_ICHI_RSI", "N15_KC_AO", "N21_ST_RSI_ADX", "S1_EMA_RSI_CHOP", "N03_ADX_GC", "S5_DONCHIAN_MFI",
        "N08_ICHI_WR", "N11_BREAKAWAY", "V45_AMB", "DOGE_L", "DOGE_S", "N06_MACD_ORB"]
for tf in L.TFS:
    parts = []
    for seed, tail, drift in ((303, 2.5, 0.02), (404, 3.0, 0.2), (505, 2.2, 0.0), (606, 2.5, 0.35)):
        d = L.synth_ohlcv(ntr[tf], tf, seed=seed, gaps=4, tail_df=tail, drift=drift)
        r = L.truncation_test(d, tf, names=rare, n_even=2, n_at_signal=4, seed=seed, include_canaries=False)
        r["data"] = f"synthetic_rare_seed{seed}_t{tail}_d{drift}"
        parts.append(r)
    rr = pd.concat(parts, ignore_index=True)
    allrows.append(rr)
    bad = rr[~rr["identical_prefix"]]
    fired = rr[rr["mode"].isin(["plain", "explicit", "resample"])].groupby("strategy")["sig_full"].max()
    check(f"truncation_rare_{tf}", bad.empty, f"failures={sorted(bad.strategy.unique())} "
          f"still_vacuous={sorted(fired[fired == 0].index)} max_signals={fired.to_dict()}")
tt = pd.concat(allrows, ignore_index=True)
tt.to_csv(os.path.join(OUT, "truncation_synthetic.csv"), index=False)
pd.DataFrame(res).to_csv(os.path.join(OUT, "selftest_results.csv"), index=False)
print("\nALL PASS" if all(r["ok"] for r in res) else "\nSOME FAILED", sum(r["ok"] for r in res), "/", len(res))
