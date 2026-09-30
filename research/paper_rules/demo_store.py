"""Fill a v3 store by replaying past 5m bars through the account book (for looking at the
dashboard before the live run; the numbers are a replay, not paper results).

    SWEEP_DATA=<sweep data> python3 research/paper_rules/demo_store.py <scratch_dir> <out.db> [days]

Uses the full-history signals from rules_bt.py and example leverage brackets.
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from paperbot import Bar, Brackets, Signal  # noqa: E402
from paperbot.accounts import AccountBook  # noqa: E402
from paperbot.aggregate import TF_MS  # noqa: E402
from paperbot.config import V3_SYMBOLS, v3_settings  # noqa: E402
from paperbot.live3 import account_defs, random_rates  # noqa: E402
from paperbot.sigservice import TRADE_TFS  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

COINS = {"BTCUSDT": "BTCUSD", "ETHUSDT": "ETHUSD", "SOLUSDT": "SOLUSD", "DOGEUSDT": "DOGEUSD",
         "LTCUSDT": "LTCUSD", "BCHUSDT": "BCHUSD"}


def main(scratch: str, out: str, days: int = 20) -> None:
    sig_dir = os.path.join(scratch, "signals")
    z = {tf: {s: dict(np.load(os.path.join(sig_dir, f"sig_{tf}_{c}.npz"))) for s, c in COINS.items()}
         for tf in TRADE_TFS}
    five = {s: z["5m"][s] for s in COINS}
    names = [k[3:] for k in five["BTCUSDT"] if k.startswith("s__")]
    rates = random_rates()
    end = int(five["BTCUSDT"]["ts"][-1] // 1_000_000) + TF_MS["5m"]
    start = end - days * 86_400_000
    if os.path.exists(out):
        os.remove(out)
    store = Store3(out)
    S = v3_settings()
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store, equity_every_ms=3_600_000, save_every=288)
    book.open_accounts(account_defs(names, TRADE_TFS), start)
    idx5 = {s: {int(t // 1_000_000): i for i, t in enumerate(five[s]["ts"])} for s in COINS}
    t0 = time.time()
    for ts in range(start, end, TF_MS["5m"]):
        bars = {}
        for s in COINS:
            i = idx5[s].get(ts)
            if i is None:
                continue
            f = five[s]
            bars[s] = Bar(s, ts, ts + TF_MS["5m"] - 1, float(f["o"][i]), float(f["h"][i]), float(f["l"][i]),
                          float(f["c"][i]))
        book.step(ts, bars)
        boundary = ts + TF_MS["5m"]
        rows = []
        for tf in TRADE_TFS:
            if boundary % TF_MS[tf]:
                continue
            for k, s in enumerate(COINS):
                d = z[tf][s]
                j = int(np.searchsorted(d["ts"] // 1_000_000, boundary - TF_MS[tf]))
                if j >= len(d["ts"]) or d["ts"][j] // 1_000_000 != boundary - TF_MS[tf]:
                    continue
                a = float(d["atr"][j])
                px = float(d["c"][j])
                sides = {n: int(d["s__" + n][j]) for n in names}
                for seed in (1, 2, 3):
                    rng = np.random.default_rng([seed, TF_MS[tf] // 60_000, k, boundary // 60_000])
                    fire, coin = rng.random(), rng.random()
                    if fire < rates[tf]:
                        sides[f"RANDOM_{seed}"] = 1 if coin < 0.5 else -1
                for n, side in sides.items():
                    if not side:
                        continue
                    aid = f"{n}@{tf}"
                    rows.append({"bar_close": boundary, "timeframe": tf, "strategy": n, "symbol": s, "side": side,
                                 "atr": a, "ref_price": px, "ref_time": boundary + 8000, "delay_ms": 8000,
                                 "status": "SUBMITTED"})
                    book.submit(aid, Signal(ts=boundary - 1, symbol=s, timeframe=tf, strategy_id=n, side=side,
                                            stop_price=0.0, tier="best", atr=a, meta={"stop_dist": 2 * a}))
        store.log_signals(rows)
    book.save(book.last_ts)
    now = int(time.time() * 1000)
    store.put_state("heartbeat", now, {"steps": days * 288, "last_step": book.last_ts})
    store.put_state("run", now, {"settings": S.version, "taker_fee": S.taker_fee, "accounts": len(book.engines),
                                 "brackets": "EXAMPLE TABLE (replay)", "restored": False})
    store.close()
    print(f"replayed {days} days into {out} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
