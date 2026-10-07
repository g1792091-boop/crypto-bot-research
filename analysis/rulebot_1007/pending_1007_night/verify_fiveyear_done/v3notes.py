import json, re, sys, os
sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd, numpy as np
J, V = sys.argv[1:3]
N = json.load(open(J))["strategy_notes"]
G = pd.read_csv(os.path.join(V, "grades_mine.csv"))
bad = []; checked = 0
num = r"([+-]?\d+\.?\d*|na)"
for n in N:
    st = n["strategy"]; tfs = n["timeframe"].split("/"); grades = n["grade"].split("/")
    secs = n["numbers"].split(" ; ") if len(tfs) > 1 else [n["numbers"]]
    for tf, gr, sec in zip(tfs, grades, secs):
        sec = re.sub(r"^\d+[mh]: ", "", sec)
        m5 = re.search(r"5y ([+-]\d+\.\d+)", sec); mg = re.search(r"g([+-]\d+\.\d+)", sec)
        ml = re.search(r"live rp(\d+) ([+-]\d+\.\d+|na)", sec)
        r = G[(G.strategy == st) & (G.tf == tf)]
        if len(r) != 1:
            r = r[r.kind == ("ds" if st.startswith("F") else "core")]
        if len(r) != 1:
            bad.append((st, tf, "no match")); continue
        r = r.iloc[0]; checked += 1
        issues = []
        if m5 and abs(float(m5.group(1)) - r.netR) > 0.006: issues.append(f"5y {m5.group(1)} vs {r.netR:.3f}")
        if mg and abs(float(mg.group(1)) - r.grossR) > 0.0015: issues.append(f"g {mg.group(1)} vs {r.grossR:.4f}")
        if ml:
            ln = int(ml.group(1)); lnm = 0 if not np.isfinite(r.live_n) else int(r.live_n)
            if ln != lnm: issues.append(f"live n {ln} vs {lnm}")
            elif ml.group(2) != "na" and np.isfinite(r.live_R) and abs(float(ml.group(2)) - r.live_R) > 0.006: issues.append(f"live {ml.group(2)} vs {r.live_R:.3f}")
        if gr != r.grade: issues.append(f"grade {gr} vs mine {r.grade} ({r.fyc}/{r.lc})")
        if issues: bad.append((st, tf, "; ".join(issues)))
print("checked", checked)
for b in bad: print(b)
