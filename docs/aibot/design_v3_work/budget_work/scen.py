"""Calendar spend Oct-Dec per tier and futility scenarios (mid/high thinking, pe 1.0, G sampled ~10/day).
python3 -I scen.py <cost_out.json-dir>  (imports cost_tiers functions by exec)"""
import sys, json, math, datetime as dt
W = sys.argv[1]
src = open(W + "/cost_tiers.py").read().split("cfg = dict(")[0]
sys.argv = ["x", W + "/calls_live.csv", W + "/calls_live_events.json"]
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()): exec(src)
D0 = dt.datetime(2026, 10, 17, 12, 0); T_W2 = dt.datetime(2026, 10, 31, 12, 0); END = dt.datetime(2026, 12, 26, 0, 0)
F16 = dt.datetime(2026, 11, 16, 12, 0)
def stop_frac(day):                     # share of zero-skill traders stopped by the -15% review (assumption)
    if day <= 30: return 0.69 * (day / 30) ** 2
    return min(0.95, 0.69 + 0.26 * (day - 30) / 30)
def daily(tier_name, th, scenario):
    """yield (date, usd) per 1h step"""
    tw1 = ["N10_HA_PSAR"] if tier_name == "S" else ["N10_HA_PSAR", "F16_FIB382"]
    sh = SH_S if tier_name == "S" else W1
    w2 = [] if tier_name == "S" else W2
    def comp(judged, shadows, twins):
        d, _, _ = tier_cost(tier_name, th, 1.0, judged, shadows, twins, 10)
        return d
    t = D0; tot = {}
    while t < END:
        day1 = (t - D0).total_seconds() / 86400; act1 = 1.0
        if scenario == "futility1116" and t >= F16: act1 = 0.0
        if scenario == "zero_skill": act1 = 1 - stop_frac(day1)
        c1 = comp(W1, sh, tw1)
        v = act1 * (c1["traders"] + c1["shadows"] + c1["twins"] + c1["late_failed"])
        fixed_writes = c1["sonnet_writes"] + c1["opus_writes"]
        if act1 == 0.0: fixed_writes = 0.0
        v += fixed_writes * (1.0 if act1 > 0.05 else 0.3)
        if w2 and t >= T_W2:
            day2 = (t - T_W2).total_seconds() / 86400; act2 = 1.0
            if scenario == "futility1116" and t >= F16: act2 = 0.0
            if scenario == "zero_skill": act2 = 1 - stop_frac(day2)
            c2 = comp(w2, [], [])
            v += act2 * (c2["traders"] + c2["late_failed"])
        an = FIX[tier_name]["analyst"] / DAYS * (0.3 if (scenario == "futility1116" and t >= F16) else 1.0)
        v += an
        m = t.strftime("%m"); tot[m] = tot.get(m, 0) + v / 24
        t += dt.timedelta(hours=1)
    for m in tot: tot[m] += FIX[tier_name]["server"] * (0.5 if m == "10" else 1.0)
    return tot
for tn in ("S", "M"):
    for th in ("mid", "high"):
        for sc in ("full", "futility1116", "zero_skill"):
            r = daily(tn, th, sc); s = sum(r.values())
            print(tn, th, sc, {k: round(v) for k, v in sorted(r.items())}, "sum", round(s))
