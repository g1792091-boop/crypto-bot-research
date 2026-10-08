import sys, io, contextlib
W = sys.argv[1]
src = open(W + "/cost_tiers.py").read().split("cfg = dict(")[0]
sys.argv = ["x", W + "/calls_live.csv", W + "/calls_live_events.json"]
with contextlib.redirect_stdout(io.StringIO()): exec(src)
W2b = [s for s in W2 if s != "N04_ST_KLINGER"]
for th in TH:
    # M-lite: 18 traders under the S hold policy, 10 shadows, 2 twins (S policy)
    m, n, _ = month("M", "S", th, 1.0, W1 + W2, W1, ["N10_HA_PSAR", "F16_FIB382"], 10)
    # M with slot 8 = H3A-like (approx 2 E + 7 HW per day) instead of N04
    m2, _, _ = month("M", "M", th, 1.0, W1 + W2b, W1, ["N10_HA_PSAR", "F16_FIB382"], 10)
    h3a = (2 * call("S", "E", th) + 7 * call("S", "H", th)) * DAYS
    print(th, "M-lite(S policy,18)", round(m["TOTAL"], 1), "| M with H3A slot", round(m2["TOTAL"] + h3a, 1), "h3a", round(h3a, 1))
# ladder savings (mid, pe1)
for th in ("mid", "high"):
    for tn, judged, sh, tw in (("S", W1, SH_S, ["N10_HA_PSAR"]), ("M", W1 + W2, W1, ["N10_HA_PSAR", "F16_FIB382"])):
        tier = tn
        def tw_parts(s):
            e, hw, g = per_day(s, tier, 1.0)
            return e * call("O", "E", th) * DAYS, hw * call("O", "H", th) * DAYS
        parts = {s: tw_parts(s) for s in tw}
        G = sum(min(per_day(s, tier, 1.0)[2], 10) for s in sh) * call("S", "E", th) * DAYS
        base, _, _ = month(tn, tier, th, 1.0, judged, sh, tw, 10)
        print(th, tn, "base", round(base["TOTAL"], 1), "twin hold", {s: round(v[1], 1) for s, v in parts.items()}, "twin entry", {s: round(v[0], 1) for s, v in parts.items()},
              "opus writes", round(base["opus_writes"], 1), "shadows(10/day)", round(G, 1), "floor", round(base["TOTAL"] - sum(a + b for a, b in parts.values()) - base["opus_writes"] - G - base["analyst_coach"] + (4 if tn == "S" else 8), 1))
# S upgrade candidates (mid)
for th in ("mid",):
    G5 = sum(min(per_day(s, "S", 1.0)[2], 10) for s in W1 if s not in SH_S) * call("S", "E", th) * DAYS
    e, hw, g = per_day("F16_FIB382", "S", 1.0)
    print("S upgrade: +5 shadows", round(G5, 1), "| F16 twin entry-only", round(e * call("O", "E", th) * DAYS, 1), "full", round((e * call("O", "E", th) + hw * call("O", "H", th)) * DAYS, 1))
    e, hw, g = per_day("S4_BB_BBP", "M", 1.0)
    print("M upgrade: S4 twin", round((e * call("O", "E", th) + hw * call("O", "H", th)) * DAYS, 1), "| shadows 10->20/day", round(sum(min(per_day(s, 'M', 1.0)[2], 20) - min(per_day(s, 'M', 1.0)[2], 10) for s in W1) * call("S", "E", th) * DAYS, 1))
