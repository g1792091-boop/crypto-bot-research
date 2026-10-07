"""Exhaustive coin-flip replay: at EVERY bar close of every coin, for 15m / 30m / 1h / 4h, a long AND a short signal
(the house 2 ATR stop, the ladder exits, quality_v1 leverage group 'normal' and 'best') through the repo's engine on
the run's live_bars (v3b and v4). The mean over both sides and all moments is the unconditional coin flip of that
timeframe in that market (no luck in the side draw, no luck in the moment draw); the per-trade spread gives the luck
band of an n-trade coin-flip account.

ATR: the house ATR of that bar from signal_log (all strategies share it); when no signal of that coin x tf exists at
that bar, the nearest logged ATR of the same coin x tf (atr_gap_min recorded). Reference price: the open of the 1m bar
starting at the bar close (the live ref price is ~15-35 s later).

    python3 -I cf_replay.py <export_dir> <analyze.py> <repo> <work_dir> [--procs 4]
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *  # noqa

E, AP, REPO, W = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
PROCS = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 4
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location("rb_analyze_mod", AP)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def one(i):
    d = A._G["sigs"][i]
    out = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "symbol", "side", "atr", "ref_price", "lev_group",
                             "atr_gap_min")}
    out.update(A._sim(d))
    return out


def chunk(idx):
    return [one(i) for i in idx]


rows_all = []
for rname in ("run-20261005T183457Z", "current"):
    run = A.Run(E, rname)
    rule, taker = A.detect_rule(run), A.implied_taker(run)
    settings = A.replay_settings(rule, taker)
    brackets, _ = A.make_brackets(None)
    specs = A.infer_specs(run.trades)
    rates, _ = A.infer_funding(run.trades, run.bars)
    ts_list, ssteps = A.build_steps(run.bars, rates)
    bars = run.bars
    opens = {(int(t), s): float(o) for t, s, o in zip(bars["ts"], bars["symbol"], bars["open"])}
    sig = run.sig[(run.sig["status"] == "SUBMITTED") & run.sig["atr"].notna()]
    delay = sig.groupby("timeframe")["delay_ms"].median().to_dict()
    t0, t1 = ts_list[0], ts_list[-1]
    sigs = []
    k = 0
    for tf in ("15m", "30m", "1h", "4h"):
        step = TF_MIN[tf] * MIN
        a = sig[sig["timeframe"] == tf].groupby(["symbol", "bar_close"])["atr"].median().reset_index()
        for sym in sorted(bars["symbol"].unique()):
            aa = a[a["symbol"] == sym].sort_values("bar_close")
            if not len(aa):
                continue
            bc_arr, atr_arr = aa["bar_close"].to_numpy(), aa["atr"].to_numpy()
            bc = (t0 // step + 1) * step
            while bc <= t1 - 2 * MIN:
                ref = opens.get((bc, sym))
                if ref is not None:
                    j = int(np.argmin(np.abs(bc_arr - bc)))
                    gap = abs(bc_arr[j] - bc) / MIN
                    for side in (1, -1):
                        for grp in ("normal", "best"):
                            k += 1
                            sigs.append({"sig_id": k, "bar_close": int(bc), "timeframe": tf, "strategy": "CF_EXH",
                                         "symbol": sym, "side": side, "atr": float(atr_arr[j]), "ref_price": ref,
                                         "ref_time": int(bc + delay.get(tf, 20000)),
                                         "delay_ms": int(delay.get(tf, 20000)),
                                         "data": {"lev_group": grp}, "lev_group": grp, "atr_gap_min": gap})
                bc += step
    A._G.clear()
    A._G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=settings, brackets=brackets, specs=specs,
                flip=False)
    idx = list(range(len(sigs)))
    import multiprocessing as mp
    with mp.get_context("fork").Pool(PROCS) as pool:
        parts = pool.map(chunk, [idx[q::PROCS * 4] for q in range(PROCS * 4)])
    R = pd.DataFrame([x for p in parts for x in p])
    R.insert(0, "run", rname)
    rows_all.append(R)
    print(rname, rule, taker, len(sigs), R["status"].value_counts().to_dict(), flush=True)
R = pd.concat(rows_all, ignore_index=True)
R.to_csv(os.path.join(W, "cf_exhaustive_rows.csv"), index=False)
