"""Per-trader AI call counts for the v3 design (tier S / tier M), one position at a time, on live replay.
python3 -I sim_calls.py <replay_signals.csv> <export_dir> <out_csv>
Policy (design v3 / analysis 15-9, 16-7(나)):
  E  entry bundle: flat + >=1 eligible signal of the trader's fixed entry timeframes at a bar-close moment (one call).
     4h eligible only if 1.5 x stop_frac <= 0.045 (stop + 1 ATR inside ~20x liquidation).
     tie: longer tf first, then widest stop, then symbol. AI enters with prob pe (pe 1.0 / 0.5).
  H  hold check at bar closes strictly inside the hold: tier M = held tf; tier S = max(held tf, 30m).
  W  wakes: (1) 1.0R grid touch (levels 0,+1,+2.. relative to entry, -1R = stop) with 15-min cooldown, 1m bars;
            (2) same-coin opposite own signal on tf >= held; (3) same-coin same-side own signal on tf > held;
     merged with H when at the same minute. Macro wakes added separately (not simulated).
  G  shadow ask: one per bar-close moment with >=1 eligible signal while holding.
Hold = replayed rule exit (UNRESOLVED -> run end). No AI early exits modelled."""
import sys, os, csv, collections, math, random
import numpy as np
REP, EXP, OUT = sys.argv[1:4]
RUNS = {"run-20261005T183457Z": ("v3b", "run-20261005T183457Z"), "current": ("v4", "current")}
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BCHUSDT", "LTCUSDT", "DOGEUSDT"]
MIN = 60000
SCOPE = {  # trader -> (entry tfs, 4h allowed)
 "N10_HA_PSAR": ("15m 30m 1h", 0), "F16_FIB382": ("15m 1h", 0), "F9_FVG": ("15m 30m", 0),
 "N18_VWMA_MACD": ("15m 30m", 0), "S4_BB_BBP": ("30m 1h", 1), "N25_DST_CCI": ("15m 1h", 0),
 "F6_VWAP_CROSS": ("15m 30m 1h", 1), "N23_HA_ST": ("15m 30m 1h", 1), "F4_FAN": ("15m 30m 1h", 1),
 "V39_ALL": ("15m 30m", 1),
 "F16_FIB500": ("15m", 0), "F7_RF_TRIPLE": ("30m 1h", 0), "S2_ST_ROC": ("15m", 1), "N02_ST_KST": ("15m", 1),
 "N07_ICHI_CMO": ("15m 30m", 0), "DOGE": ("15m 30m 1h", 0), "N13_3OUTSIDE": ("15m 1h", 0),
 "N01_ST_EMA": ("15m", 1), "N04_ST_KLINGER": ("15m", 1)}
import json
EVT = {}
WAVE1 = list(SCOPE)[:10]

def load_bars(p):
    d = collections.defaultdict(list)
    with open(os.path.join(p, "live_bars.csv")) as fh:
        h = fh.readline().strip().split(","); it, isym, ih, il, ic = (h.index(x) for x in ("ts", "symbol", "high", "low", "close"))
        for line in fh:
            v = line.rstrip("\n").split(",")
            d[v[isym]].append((int(v[it]), float(v[ih]), float(v[il]), float(v[ic])))
    out = {}
    for s, L in d.items():
        a = np.array(sorted(set(L))); out[s] = (a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3])
    return out

def grid_wakes(bars, sym, t0, t1, entry, R, side, cd_min=15):
    ts, hi, lo, cl = bars[sym]
    i0, i1 = np.searchsorted(ts, t0), np.searchsorted(ts, t1)
    last_lvl, last_t, out = 0, -10**18, []
    for i in range(i0, i1):
        a, b = side * (hi[i] - entry) / R, side * (lo[i] - entry) / R
        rlo, rhi = min(a, b), max(a, b)
        c = side * (cl[i] - entry) / R
        lv = [L for L in range(max(0, math.ceil(rlo)), math.floor(rhi) + 1)]
        if not lv: continue
        L = min(lv, key=lambda x: abs(x - c))
        if L != last_lvl and ts[i] + MIN - last_t >= cd_min * MIN:
            out.append(int(ts[i] + MIN)); last_lvl = L; last_t = ts[i] + MIN
    return out

rows_in = collections.defaultdict(list)
for r in csv.DictReader(open(REP)):
    if r["run"] not in RUNS or r["symbol"] not in COINS or r["timeframe"] not in TFM: continue
    if r["strategy"] not in SCOPE: continue
    rows_in[r["run"]].append(r)
res, burst = [], collections.Counter()
for run, L in rows_in.items():
    tag, d = RUNS[run]; p = os.path.join(EXP, d)
    st = min(int(r["started_ts"]) for r in csv.DictReader(open(os.path.join(p, "runs.csv"))))
    bars = load_bars(p); end = max(a[0][-1] for a in bars.values()) + MIN
    days = (end - st) / 86400000
    bys = collections.defaultdict(list)
    for r in L: bys[r["strategy"]].append(r)
    for strat, S in sorted(bys.items()):
        tfs, allow4 = SCOPE[strat]; tfs = set(tfs.split())
        sigs = []
        for r in S:
            bc = int(r["bar_close"]); tf = r["timeframe"]
            ok = r["status"] in ("TRADED", "UNRESOLVED") and r["entry_time"] not in ("", "nan")
            et = float(r["entry_time"]) if ok else None
            xt = float(r["exit_time"]) if ok and r["exit_time"] not in ("", "nan") else end
            ep = float(r["entry_price"]) if ok else None; sp = float(r["stop_initial"]) if ok else None
            sf = 2 * float(r["atr"]) / float(r["ref_price"])
            sigs.append(dict(bc=bc, tf=tf, m=TFM[tf], sym=r["symbol"], side=int(float(r["side"])), ok=ok, et=et, xt=xt, ep=ep, sp=sp, sf=sf))
        sigs.sort(key=lambda s: s["bc"])
        def elig(s):
            if not s["ok"]: return False
            if s["tf"] == "4h": return bool(allow4) and 1.5 * s["sf"] <= 0.045
            return s["tf"] in tfs
        offered = [s for s in sigs if elig(s)]
        bym = collections.defaultdict(list)
        for s in offered: bym[s["bc"]].append(s)
        moments = sorted(bym)
        for pe in (1.0, 0.5):
            rng = random.Random(hash(strat) & 0xffff if False else sum(map(ord, strat)))
            c = collections.Counter(); held = 0.0; pos = None
            ev = collections.defaultdict(list)
            for m in moments:
                if pos is not None and m >= pos["t1"]: pos = None
                if pos is not None:
                    c["G"] += 1; ev["G"].append(m); continue
                c["E"] += 1; ev["E"].append(m)
                if pe < 1.0 and rng.random() >= pe: continue
                s = sorted(bym[m], key=lambda x: (-x["m"], -x["sf"], COINS.index(x["sym"])))[0]
                t0, t1 = s["et"], min(s["xt"], end); pos = dict(t1=t1)
                c["trades"] += 1; held += max(0, t1 - t0); R = abs(s["ep"] - s["sp"])
                gw = grid_wakes(bars, s["sym"], t0, t1, s["ep"], R, s["side"])
                sw = [x["bc"] for x in sigs if x["sym"] == s["sym"] and t0 < x["bc"] < t1 and
                      ((x["side"] != s["side"] and x["m"] >= s["m"]) or (x["side"] == s["side"] and x["m"] > s["m"]))]
                for tier, step in (("M", s["m"]), ("S", max(s["m"], 30))):
                    k0 = math.floor(t0 / (step * MIN)) + 1; k1 = math.ceil(t1 / (step * MIN)) - 1
                    hb = set(k * step * MIN for k in range(k0, k1 + 1))
                    wk = set(gw) | set(sw)
                    c["H_" + tier] += len(hb); c["W_" + tier] += len(wk - hb)
                    ev["HW_" + tier].extend(sorted(hb | wk))
                    if pe == 1.0 and tag == "v4":
                        for b in hb: burst[(tier, b)] += 1
                c["Wgrid"] += len(gw); c["Wsig"] += len(set(sw))
            if pe == 1.0 and tag == "v4": EVT[strat] = {k: v for k, v in ev.items()}
            row = dict(run=tag, strategy=strat, wave=1 if strat in WAVE1 else 2, pe=pe, days=round(days, 3), occupancy=round(held / (end - st), 3))
            for k, v in c.items(): row[k] = round(v / days, 2)
            row["tot_S"] = round(row.get("E", 0) + row.get("H_S", 0) + row.get("W_S", 0), 2)
            row["tot_M"] = round(row.get("E", 0) + row.get("H_M", 0) + row.get("W_M", 0), 2)
            res.append(row)
keys = ["run", "strategy", "wave", "pe", "days", "occupancy", "E", "H_S", "W_S", "tot_S", "H_M", "W_M", "tot_M", "G", "Wgrid", "Wsig", "trades"]
with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=keys, restval=0, extrasaction="ignore"); w.writeheader(); w.writerows(res)
print(len(res), "rows")
json.dump(dict(start=None, events=EVT), open(OUT.replace(".csv", "_events.json"), "w"))
