"""Each watch pick (its numbers, its exit), 2021-01..2026-09: trend ratio (share of entries in the direction of the
previous 20 bars, the strategy-profile definition) and results by market state (장세: 추세장 / 횡보장 / 급변장 / 보통)."""
import json
import os
import sys
FG = "/home/user/crypto-bot-research/research/fullgrid"
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np  # noqa
import run as R  # noqa
import regimes as RG  # noqa
SP = os.environ["WORKROOT"]
DATA, WORK = SP + "/fg1m", SP + "/fgwork"
R.FRAME_DIR[0] = WORK + "/frames"
EXN = [e[0] for e in R.K.EXITS]
CANDS = json.load(open("/home/user/crypto-bot-research/candleague/data/candidates.json"))["candidates"]
_st = {}


def job(c):
    e = EXN.index(c["exit"])
    combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in c["combo"].items()}
    T = R.cell_trades(DATA, WORK, c["kind"], c["name"], c["tf"], [(combo, e)])[0]
    ok = np.isfinite(T["x"]) & ((T["pid"] == 0) | (T["pid"] == 1))
    trend = []
    for ci, sym in enumerate(R.SYMBOLS):
        m = ok & (T["coin"] == ci)
        if not m.any():
            continue
        df, close_ms = R.frame(DATA, sym, c["tf"])
        cl = df["close"].to_numpy(float)
        idx = np.searchsorted(close_ms, T["close"][m])
        idx = np.clip(idx, 0, len(cl) - 1)
        prev = np.clip(idx - 20, 0, None)
        d = np.sign(cl[idx] - cl[prev])
        trend.extend(list((d == T["side"][m]) & (d != 0)))
    if c["tf"] not in _st:
        _st[c["tf"]] = [RG.coin_states(DATA, s, c["tf"]) for s in R.SYMBOLS]
    lab = RG.tag(T, _st[c["tf"]])
    st = np.array([s if s is not None else "모름" for s in lab["장세"]], object)
    by = {}
    for s in ("추세장", "횡보장", "급변장", "보통"):
        x = T["x"][ok & (st == s)]
        by[s] = {"n": int(len(x)), "win": float((x > 0).mean()) if len(x) else None, "mean": float(x.mean()) if len(x) else None}
    x = T["x"][ok]
    return {"id": c["id"], "kind": c["kind"], "name": c["name"], "tf": c["tf"], "exit": c["exit"],
            "trend_ratio": float(np.mean(trend)) if trend else None, "n": int(len(x)), "mean": float(x.mean()),
            "win": float((x > 0).mean()), "states": by}


out = []
for k, r in enumerate(R.run_pool(job, CANDS, 4, "char")):
    out.append(r)
    print(k, r["id"], round(r["trend_ratio"], 2), flush=True)
json.dump(out, open(SP + "/interim/pick_character.json", "w"), ensure_ascii=False, indent=1)
print("done")
