"""simulate_position (vectorised) against the repo's own engine (paperbot.trendbot.TrendEngine = ComboEngine +
PaperEngine: sizing, net-ROE stop, ladder2, funding on the mark open, liquidation, supervisor close at the open) on
random entries 2021-2026 with real funding, with and without a supervisor event. Output: out/engine_check.json"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine5y import *
from paperbot.trendbot import TrendEngine
from paperbot.margin import Brackets
from paperbot.models import Bar, Signal

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
mk = markets()
rng = np.random.default_rng(11)
rows = []
for case in range(N):
    coin = COINS[case % 6]
    M = mk[coin]
    side = int(rng.choice([-1, 1]))
    lv = [40, 30, 20, 10][case % 4] if coin == "BTCUSDT" else [30, 20, 10][case % 3]
    lad = dict(CFG["ladder"]) if case % 3 else {**CFG["ladder"], "first_lock": 0.2, "next_trigger": 0.25}
    stop_roe = 0.5 if case % 2 else 0.35
    v = variant(lev={"default": lv}, ladder=lad, stop_roe=stop_roe)
    cfgd = {k: x for k, x in CFG.items()}
    cfgd.update(leverage={"default": lv}, ladder=v["ladder"], stop={"mode": "roe", "roe": stop_roe, "net": True})
    cfg = C.ComboConfig.from_dict(cfgd)
    S = C.settings_of(cfg)
    e = TrendEngine(S, {c: Brackets.example() for c in COINS}, combo=cfg)
    et = int(rng.integers(ms("2021-01-01"), ms("2026-09-25")) // MIN * MIN)
    ei = M.i(et)
    ref = float(M.o[ei])
    ev_i = ei + int(rng.integers(30, 900)) if case % 2 == 0 else None
    P = {"slip": S.slippage_frac, "rt": S.round_trip_cost, "ladder": ComboLadder.of(v["ladder"]), "stop_roe": stop_roe,
         "taker": S.taker_fee, "maker": S.maker_fee, "funding": True}
    mine = simulate_position(M, side, ei, ref, lv, ev_i, P)
    sig = Signal(ts=et - 1, symbol=coin, timeframe="30m", strategy_id="X", side=side, stop_price=0.0, tier="best",
                 score=1.0, atr=1.0, meta={"ref_price": ref, "member": "X@30m", "stop_dist": 0.0, "ctx": {}})
    e.submit(sig)
    k = ei
    while True:
        if ev_i is not None and k == ev_i:
            e.supervise("JUDGE", "test")
        bar = Bar(coin, T0 + k * MIN, T0 + (k + 1) * MIN - 1, float(M.o[k]), float(M.h[k]), float(M.l[k]), float(M.c[k]),
                  float(M.mo[k]), float(M.mh[k]), float(M.ml[k]), float(M.mo[k]))
        f = float(M.fund[k])
        e.step({coin: bar}, {coin: f} if f != 0 else None)
        if e.trades:
            break
        k += 1
    t = e.trades[0]
    rr = {"coin": coin, "side": side, "lev": lv, "entry": et, "ev": ev_i is not None,
          "engine": (t.exit_reason, int((t.exit_time - T0) // MIN), round(t.roe, 10), t.lock_roe),
          "mine": ("JUDGE" if mine["reason"] == "EVENT" else mine["reason"], int(mine["x"]), round(mine["roe"], 10), mine["lock"])}
    rr["funding_paid"] = float(t.funding)
    rr["same"] = (rr["engine"][0] == rr["mine"][0] and rr["engine"][1] == rr["mine"][1]
                  and abs(rr["engine"][2] - rr["mine"][2]) < 1e-8)
    rows.append(rr)
same = sum(r["same"] for r in rows)
out = {"n": len(rows), "same": same, "bad": [r for r in rows if not r["same"]][:20],
       "reasons": pd.Series([r["engine"][0] for r in rows]).value_counts().to_dict(),
       "with_funding": int(sum(1 for r in rows if r["funding_paid"] != 0))}
json.dump(out, open(f"{OUT}/engine_check.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
