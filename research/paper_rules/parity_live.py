"""Does the live signal service (trailing windows built from 5m bars) give the same
signals as the backtest code on full history?

    SWEEP_DATA=<sweep data> python3 research/paper_rules/parity_live.py <scratch_dir> [bars_per_tf]

Reference: the full-history signals written by rules_bt.py (<scratch>/signals/sig_<tf>_<coin>.npz).
For random closed bars in the confirmation window, the service is fed the 5m bars up to that
close and asked for the signals of that bar. Every strategy's side is compared (zeros included).
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from paperbot import sweepsig  # noqa: E402
from paperbot.aggregate import TF_MS  # noqa: E402
from paperbot.sigservice import SignalService  # noqa: E402

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("5m", "15m", "30m", "1h", "4h", "1d")


def main(scratch: str, per_tf: int = 20) -> None:
    L = sweepsig.lib()
    sig_dir = os.path.join(scratch, "signals")
    five = {}
    for c in COINS:
        d = L.read_ohlcv(L._resolve_path("5m", c, "full", None))
        five[c] = np.column_stack([d["ts"].astype("int64").to_numpy() // 1_000_000, d["open"], d["high"],
                                   d["low"], d["close"], d["volume"]])
    svc = SignalService(COINS, procs=4, lib=L)
    rng = np.random.default_rng(11)
    rows = []
    for tf in TFS:
        ref = {c: np.load(os.path.join(sig_dir, f"sig_{tf}_{c}.npz")) for c in COINS}
        ts_ns = ref["BTCUSD"]["ts"]
        span = TF_MS[tf]
        closes = ts_ns // 1_000_000 + span
        ok = closes >= pd.Timestamp("2024-07-01").value // 1_000_000
        ok &= closes <= five["BTCUSD"][-1, 0] + 300_000
        pick = rng.choice(np.flatnonzero(ok), size=min(per_tf, int(ok.sum())), replace=False)
        for i in sorted(pick):
            boundary = int(closes[i])
            for c in COINS:
                h = svc.hist[c]
                h.clear()
                a = five[c]
                k = int(np.searchsorted(a[:, 0], boundary, side="left"))
                svc.bootstrap(c, [tuple(r) for r in a[max(0, k - svc.hist[c].maxlen):k]])
            t0 = time.time()
            res = {r["symbol"]: r for r in svc._map(svc._jobs(boundary, tf))}
            for c in COINS:
                r = res[c]
                z = ref[c]
                j = int(np.searchsorted(z["ts"] // 1_000_000, boundary - span))
                if not r["ready"] or j >= len(z["ts"]) or z["ts"][j] // 1_000_000 != boundary - span:
                    rows.append(dict(tf=tf, coin=c, boundary=boundary, strategy="*", ok=False,
                                     why=r.get("why", "reference bar missing")))
                    continue
                for n in svc.names:
                    live = int(r["sides"].get(n, 0))
                    full = int(z["s__" + n][j])
                    rows.append(dict(tf=tf, coin=c, boundary=boundary, strategy=n, live=live, full=full,
                                     ok=live == full))
                atr_full = float(z["atr"][j])
                rows.append(dict(tf=tf, coin=c, boundary=boundary, strategy="ATR", live=r["atr"], full=atr_full,
                                 ok=abs(r["atr"] - atr_full) <= 1e-6 * max(1.0, abs(atr_full))))
            print(f"{tf} {pd.Timestamp(boundary, unit='ms')}: {time.time() - t0:.1f}s", flush=True)
    svc.close()
    df = pd.DataFrame(rows)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    df.to_csv(os.path.join(out, "parity_live.csv"), index=False)
    s = df[df["strategy"] != "*"]
    summ = {
        "checks": int(len(s)), "mismatches": int((~s["ok"]).sum()),
        "not_ready": int((df["strategy"] == "*").sum()),
        "by_tf": {tf: {"checks": int(len(g)), "mismatch": int((~g["ok"]).sum()),
                       "nonzero_full": int((g["full"].fillna(0) != 0).sum()) if "full" in g else 0}
                  for tf, g in s.groupby("tf")},
        "mismatch_rows": s[~s["ok"]].head(40).to_dict("records"),
    }
    with open(os.path.join(out, "parity_live.json"), "w") as fh:
        json.dump(summ, fh, indent=1, default=str)
    print(json.dumps({k: v for k, v in summ.items() if k != "mismatch_rows"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20)
