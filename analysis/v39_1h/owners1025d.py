"""Owners 10-25 night, 20 days only (no 5-year): the owners' plan (owners1025c: 40 % margin, BTC 40x / others 30x,
stop 2.5 ATR, ladder 15->13, 20->17, 25->22, ..., liquidation guard, Toobit costs from $50) with entry blocks:
- Nasdaq open: 30 min before / after the NYSE open (09:30 New York; weekdays) — a 1h signal enters ~30 s after the
  hour, so only the 22:00 KST signal (13:00 UTC while New York is on summer time) falls inside;
- US economic releases (data/macro_events.csv: CPI, FOMC, NFP, PCE): 30 min before / after.
Each blocked signal alone (on a fresh $50, same plan) and the account with the block."""
import json
import os
import sys

import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
EXPORT, OUT = sys.argv[1], sys.argv[2]
import owners1025c as C  # noqa: E402  (the plan, the signals and the one-position account)
import sim  # noqa: E402
import v39lib as L  # noqa: E402

MIN = 60_000
ev = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(H)), "data", "macro_events.csv"), comment="#")
ev["ms"] = pd.to_datetime(ev["ts_utc"], utc=True).astype("int64") // 10**6


def ny_open_ms(ms: int) -> int:
    """The NYSE open (09:30 America/New_York) of the New York day of ``ms``."""
    t = pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert("America/New_York")
    return int(t.normalize().replace(hour=9, minute=30).tz_convert("UTC").value // 10**6)


def fill_ms(d):
    return d["bar_close"] + 30_000                    # the paper's entry: about 30 s after the bar close


def in_nasdaq(d):
    t = fill_ms(d)
    o = ny_open_ms(t)
    wd = pd.Timestamp(t, unit="ms", tz="UTC").tz_convert("America/New_York").dayofweek
    return wd < 5 and o - 30 * MIN <= t <= o + 30 * MIN


def in_macro(d):
    t = fill_ms(d)
    return bool(((ev["ms"] - 30 * MIN <= t) & (t <= ev["ms"] + 30 * MIN)).any())


sigs = C.signals(("1h",))
rows = []
for d in sigs:
    A = C.W.A[d["symbol"]]
    e = C.W.entry_index(d["symbol"], d["bar_close"])
    r = sim.run_one(C.S, C.br[d["symbol"]], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 50.0,
                    C.specs[d["symbol"]], C.V, d["symbol"])
    rows.append({"kst": L.kst(d["bar_close"]), "symbol": d["symbol"][:-4], "side": "롱" if d["side"] > 0 else "숏",
                 "nasdaq": in_nasdaq(d), "macro": in_macro(d), "beyond_liq": C.beyond_liq(d), "reason": r["reason"],
                 "ret_pct": round(100 * r["ret"], 2), "lock_roe_pct": round(100 * r["lock_roe"], 0) if r["lock_roe"] == r["lock_roe"] else None})
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "blocks_signals.csv"), index=False)
res = {"signals": len(R), "macro_events_in_window": ev[(ev["ms"] >= C.W.start_ms) & (ev["ms"] < C.W.end_ms)][["ts_utc", "kind"]].to_dict("records")}
for name, m in (("nasdaq", R["nasdaq"]), ("macro", R["macro"])):
    g = R[m]
    res[f"{name}_signals"] = g.to_dict("records")
for label, keep in (("막기 없음 (지금 계획)", lambda d: True), ("나스닥 개장 앞뒤 30분 막기", lambda d: not in_nasdaq(d)),
                    ("경제 발표 앞뒤 30분 막기", lambda d: not in_macro(d)),
                    ("둘 다 막기", lambda d: not in_nasdaq(d) and not in_macro(d))):
    out, ent = C.account([d for d in sigs if keep(d)])
    res[label] = out
    print(label, json.dumps(out, ensure_ascii=False))
print(json.dumps({k: v for k, v in res.items() if k.endswith("_signals") or k.startswith("macro_events")}, ensure_ascii=False, indent=0))
json.dump(res, open(os.path.join(OUT, "blocks.json"), "w"), ensure_ascii=False, indent=1, default=str)
