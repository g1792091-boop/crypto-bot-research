"""Fill NOTES_template.md with generated tables -> NOTES.md."""
import os, re, subprocess
import numpy as np
import pandas as pd

subprocess.run(["python3", "report.py", "--tag", "base"], capture_output=True)
subprocess.run(["python3", "summary.py", "base"], capture_output=True)
subprocess.run(["python3", "report2.py", "base"], capture_output=True)
subprocess.run(["python3", "sens_table.py"], capture_output=True)

summ = open("out/base/summary.md").read()
parts = re.split(r"\n(?=### )", "\n" + summ)
parts = [p.strip("\n") for p in parts if p.strip()]
def pick(prefix):
    return [p for p in parts if p.startswith(prefix)]

setup = "\n".join(pick("### Setup"))
tfs = ["5m", "15m", "1h", "4h", "1d"]
main = "\n\n".join(p for tf in tfs for p in pick(f"### {tf}:"))
main += "\n\n" + "\n".join(pick("### Whole IS span"))
minedge = "\n".join(pick("### Minimum planted"))
capk = "\n\n".join(pick("### Edge capture") + pick("### Growth-optimal"))
realised = open("out/min_edge_realised_base.md").read().strip()

# observed-edge table: 1-year and 30-day medians at D = 0.10
M = pd.concat([pd.read_csv(f"out/base/{tf}_metrics.csv") for tf in tfs], ignore_index=True)
rows = [("P0|A|10", "P0 1x, time exit"), ("P0|B|10", "P0 1x, 1.5ATR stop"), ("P3|A|10", "P3 20%x20 (user minimum)"),
        ("P4|A|10", "P4 40%x50 (user style)"), ("P5|A|10", "P5 user-adaptive"), ("P6|B|none", "P6 1 % risk"), ("P6h|B|none", "P6h 0.5 % risk")]
obs = ["| policy | " + " | ".join(f"{tf}: 30d / 1y" for tf in tfs) + " |", "|---|" + "---|" * len(tfs)]
for c, lab in rows:
    cells = []
    for tf in tfs:
        r = M[(M.tf == tf) & (M.combo == c) & np.isclose(M.edge_pct, 0.10)].iloc[0]
        cells.append(f"x{r['30d_median_mult']:.3g} / x{r['1y_median_mult']:.3g}")
    obs.append(f"| {lab} | " + " | ".join(cells) + " |")
obs = "\n".join(obs)

# kill-switch table (zero edge)
K = pd.read_csv("out/killswitch.csv")
kt = ["At zero planted edge: P(−20 % from peak within 30 days) / median days to −20 % / median equity when a −20 % kill switch fires.",
      "", "| policy | " + " | ".join(tfs) + " |", "|---|" + "---|" * len(tfs)]
for c, lab in [("P0|B|10", "P0 1x"), ("P3|A|10", "P3 20%x20"), ("P4|A|10", "P4 40%x50"), ("P5|A|10", "P5 adaptive"),
               ("P6|B|none", "P6 1 % risk"), ("P6h|B|none", "P6h 0.5 % risk")]:
    cells = []
    for tf in tfs:
        r = K[(K.tf == tf) & (K.combo == c) & np.isclose(K.edge_pct, 0)].iloc[0]
        dd = "-" if pd.isna(r.median_days_to_dd20) else f"{r.median_days_to_dd20:.0f} d"
        eq = "-" if pd.isna(r.median_equity_when_fired) else f"{r.median_equity_when_fired:.2f}"
        cells.append(f"{r.p_dd20_30d:.2f} / {dd} / {eq}")
    kt.append(f"| {lab} | " + " | ".join(cells) + " |")
kt = "\n".join(kt)

sens = open("out/sens_table.md").read().strip()
sens_text = open("sens_text.md").read().strip() if os.path.exists("sens_text.md") else "(pending)"

s = open("NOTES_template.md").read()
for k, v in [("SETUP_TABLE", setup), ("MAIN_TABLES", main), ("MIN_EDGE_TABLE", minedge), ("REALISED_TABLE", realised),
             ("CAPTURE_KELLY", capk), ("RULE_EXAMPLES", open("out/rule_examples.md").read().strip()), ("OBS_TABLE", obs), ("KILL_TABLE", kt), ("SENS_TABLE", sens), ("SENS_TEXT", sens_text)]:
    assert k in s, k
    s = s.replace(k, v)
open("NOTES.md", "w").write(s)
print("NOTES.md", len(s), "chars")
