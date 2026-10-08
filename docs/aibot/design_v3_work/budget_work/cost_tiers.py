"""Tier S / tier M monthly cost estimates from simulated call counts (no API calls).
python3 -I cost_tiers.py <calls_live.csv> <calls_live_events.json>"""
import sys, csv, json, collections, math
CALLS, EVJ = sys.argv[1:3]
DAYS = 30.4
P = dict(S=dict(i=2.0, o=10.0, r=0.20, w5=2.5, w1=4.0), O=dict(i=4.0, o=20.0, r=0.20, w5=5.0, w1=8.0))
SCR = dict(C=4435, UE=970, UH=1157, L1=1639, L2=1724, L3=1072)       # spec_decision 3-4, mixed-key screen, B mid
TH = dict(low=(300, 100), mid=(800, 300), high=(2000, 800)); ANS_E, ANS_H = 150, 120
def call(model, kind, th, tok=1.0):
    p = P[model]; te, thh = TH[th]
    u = SCR["UE"] if kind == "E" else SCR["UH"]; out = (te + ANS_E) if kind == "E" else (thh + ANS_H)
    return (SCR["C"] * tok * p["r"] + u * tok * p["i"] + out * tok * p["o"]) / 1e6
rows = {(r["strategy"], float(r["pe"])): r for r in csv.DictReader(open(CALLS)) if r["run"] == "v4"}
W1 = ["N10_HA_PSAR", "F16_FIB382", "F9_FVG", "N18_VWMA_MACD", "S4_BB_BBP", "N25_DST_CCI", "F6_VWAP_CROSS", "N23_HA_ST", "F4_FAN", "V39_ALL"]
W2 = ["F16_FIB500", "F7_RF_TRIPLE", "S2_ST_ROC", "N02_ST_KST", "N07_ICHI_CMO", "DOGE", "N13_3OUTSIDE", "N04_ST_KLINGER"]
SH_S = ["N10_HA_PSAR", "F16_FIB382", "F9_FVG", "N18_VWMA_MACD", "F6_VWAP_CROSS"]
def per_day(strat, tier, pe):
    r = rows[(strat, pe)]; E = float(r["E"]); HW = float(r["tot_" + tier]) - E; G = float(r["G"])
    return E, HW, G
print("== per-call cost (USD) ==")
for m in "SO":
    for k in "EH":
        print(m, k, {t: round(call(m, k, t), 5) for t in TH}, "opus tok1.3 mid" if m == "O" else "", round(call(m, k, "mid", 1.3), 5) if m == "O" else "")
def writes(model, ns, l1, l2, l3, tok=1.0):
    p = P[model]
    return ns * (l1 * SCR["L1"] * p["w1"] + l2 * SCR["L2"] * p["w1"] + l3 * SCR["L3"] * p["w5"]) * tok / 1e6
print("Sonnet writes/day per ns", round(writes("S", 1, 3, 24, 96), 3), "Opus writes/day (S twin, 1ns)", round(writes("O", 1, 4, 20, 30), 3), "(M twins)", round(writes("O", 1, 4, 22, 45), 3))
def tier_cost(tier, th, pe, judged, shadows, twins, gcap, busy=1.0, opus_tok=1.0):
    d = collections.OrderedDict()
    E = HW = 0.0; detail = {}
    for s in judged:
        e, hw, g = per_day(s, tier, pe); E += e; HW += hw
        detail[s] = (e, hw, e * call("S", "E", th) + hw * call("S", "H", th))
    d["traders"] = (E * call("S", "E", th) + HW * call("S", "H", th)) * busy
    G = sum(min(per_day(s, tier, pe)[2], gcap) for s in shadows)
    d["shadows"] = G * call("S", "E", th) * busy
    tw = 0.0
    for s in twins:
        e, hw, g = per_day(s, tier, pe); tw += e * call("O", "E", th, opus_tok) + hw * call("O", "H", th, opus_tok)
    d["twins"] = tw * busy
    d["sonnet_writes"] = writes("S", 1.5, 3, 24, 96) + 0.06      # 1-2 namespaces (mid 1.5) + mid-window misses
    d["opus_writes"] = (writes("O", 1.3, 4, 20, 30, opus_tok) if len(twins) == 1 else writes("O", 1.3, 4, 22, 45, opus_tok)) if twins else 0.0
    d["late_failed"] = 0.03 * (d["traders"] + d["shadows"] + d["twins"]) * (2.0 if th == "high" else 1.0)
    return d, dict(E=E, HW=HW, G=G), detail
FIX = dict(S=dict(analyst=11.0, server=10.0), M=dict(analyst=24.0, server=10.0))
def month(tier_name, tier, th, pe, judged, shadows, twins, gcap, busy=1.0, opus_tok=1.0, days=DAYS):
    d, n, det = tier_cost(tier, th, pe, judged, shadows, twins, gcap, busy, opus_tok)
    m = {k: v * days for k, v in d.items()}
    m["analyst_coach"] = FIX[tier_name]["analyst"] * days / DAYS; m["server"] = FIX[tier_name]["server"] * days / DAYS
    m["TOTAL"] = sum(m.values()); return m, n, det
cfg = dict(S=dict(tier="S", judged=W1, shadows=SH_S, twins=["N10_HA_PSAR"]),
           M=dict(tier="M", judged=W1 + W2, shadows=W1, twins=["N10_HA_PSAR", "F16_FIB382"]),
           M1=dict(tier="M", judged=W1, shadows=W1, twins=["N10_HA_PSAR", "F16_FIB382"]))
out = {}
for name, c in cfg.items():
    tn = "S" if name == "S" else "M"
    for gcap in (10, 999):
        for pe in (1.0, 0.5):
            for th in TH:
                m, n, det = month(tn, c["tier"], th, pe, c["judged"], c["shadows"], c["twins"], gcap)
                out[(name, gcap, pe, th)] = m
                if th == "mid" and gcap == 10:
                    print(f"\n== {name} pe={pe} gcap={gcap} calls/day E={n['E']:.0f} HW={n['HW']:.0f} G={n['G']:.0f} total judged={n['E']+n['HW']:.0f}")
                print(name, "gcap", gcap, "pe", pe, th, {k: round(v, 1) for k, v in m.items()})
    if name in ("S", "M"):
        _, _, det = month(tn, c["tier"], "mid", 1.0, c["judged"], c["shadows"], c["twins"], 10)
        print("per-trader $/month mid pe1:", {k: (round(v[0], 1), round(v[1], 1), round(v[2] * DAYS, 1)) for k, v in det.items()})
        _, _, deth = month(tn, c["tier"], "high", 1.0, c["judged"], c["shadows"], c["twins"], 10)
        print("per-trader $/month high pe1:", {k: round(v[2] * DAYS, 1) for k, v in deth.items()})
# busy p90 day x30 and opus tokenizer x1.3
for name in ("S", "M"):
    c = cfg[name]; tn = name
    for th in TH:
        m, _, _ = month(tn, c["tier"], th, 1.0, c["judged"], c["shadows"], c["twins"], 10, busy=1.17, opus_tok=1.3)
        print("STRESS", name, th, "busy1.17+opus_tok1.3 TOTAL", round(m["TOTAL"], 1))
# bursts per boundary (v4, pe 1, raw G and sampled ~10/day, twins mirror pair)
ev = json.load(open(EVJ))["events"]
for name in ("S", "M"):
    c = cfg[name]; cnt = collections.Counter()
    for s in c["judged"]:
        e = ev[s]
        for t in e.get("E", []) + e.get("HW_" + c["tier"], []): cnt[(t // 60000) * 60000] += 1
        if s in c["twins"]:
            for t in e.get("E", []) + e.get("HW_" + c["tier"], []): cnt[(t // 60000) * 60000] += 1
    for s in c["shadows"]:
        for t in ev[s].get("G", []): cnt[(t // 60000) * 60000] += 1
    v = sorted(cnt.values()); q = lambda f: v[min(len(v) - 1, int(f * len(v)))]
    b15 = [x for t, x in cnt.items() if (t // 60000) % 15 == 0]; b15.sort()
    print("BURST", name, "minutes with calls", len(v), "median", q(.5), "p90", q(.9), "p99", q(.99), "max", v[-1], "| at 15m boundaries median", b15[len(b15)//2], "p90", b15[int(.9*len(b15))], "max", b15[-1])
json.dump({"|".join(map(str, k)): v for k, v in out.items()}, open(CALLS.replace("calls_live.csv", "cost_out.json"), "w"), indent=0)
