"""Spot check of the custom-number signals (signals_all.py, full series) against paperbot/combo.py itself:
combo.resolve_members([{"pick": id}]) -> combo.CustomSignals fed the same 5m bars bar by bar (its own trailing
windows, its own frames, paramshadow / ds_defs calls), compute(boundary) at every 30m / 1h boundary of a recent window;
the (bar close, coin, side) sets are compared. Output: scratchpad newlive/validate_custom.json.
Run: python3 -I check_custom.py [--days 3] [--picks id,id,...]"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlcommon import *
import time

PICKS = ["core-N03_ADX_GC-30m-3", "core-S4_BB_BBP-1h-2", "ds-F7_RF_ONLY-30m-1", "ds-F9_FVG-1h-1"]


def main():
    from paperbot import combo as C
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3
    picks = sys.argv[sys.argv.index("--picks") + 1].split(",") if "--picks" in sys.argv else PICKS
    t0 = time.time()
    members = C.resolve_members([{"pick": p} for p in picks])
    cs = C.CustomSignals(members, COINS)
    W0, W1 = DATA_END - days * DAY, DATA_END
    F = {}
    for c in COINS:
        f = agg(load_grid(c), FIVE)
        F[c] = f
    pos = {}
    for c in COINS:
        ts = F[c]["ts"]
        start = W0 - cs.keep * FIVE
        pos[c] = int(np.searchsorted(ts, start))
    got = []
    for b in range(W0 + 1_800_000, W1 + 1, 1_800_000):
        for c in COINS:
            f = F[c]
            j = int(np.searchsorted(f["ts"], b))            # bars with open < b
            rows = [(int(f["ts"][i]), f["o"][i], f["h"][i], f["l"][i], f["c"][i], f["v"][i]) for i in range(pos[c], j)]
            cs.bootstrap(c, rows)
            pos[c] = j
        for g in cs.compute(b):
            got.append((g["member"].label, b, g["symbol"], int(g["side"])))
    errs = list(cs.errors)
    res = {"window_utc": [str(pd.Timestamp(W0, unit="ms")), str(pd.Timestamp(W1, unit="ms"))], "picks": {},
           "errors": errs[:10], "n_errors": len(errs)}
    for m in members:
        mine = set()
        z = np.load(sig_path(label_of(m.name, m.tf, m.pick)))
        k = (z["t"] > W0) & (z["t"] <= W1)
        for t, ci, s in zip(z["t"][k], z["coin"][k], z["side"][k]):
            mine.add((int(t), COINS[int(ci)], int(s)))
        live = {(b, c, s) for (lab, b, c, s) in got if lab == m.label}
        res["picks"][m.pick] = {"kind": m.kind, "name": m.name, "tf": m.tf, "numbers": m.numbers,
                                "combo_signals": len(live), "full_series_signals": len(mine),
                                "both": len(live & mine), "only_combo": sorted(live - mine)[:10],
                                "only_full_series": sorted(mine - live)[:10]}
    res["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(res, open(f"{NL}/validate_custom.json", "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
