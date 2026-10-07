"""Markdown tables for replication_KO.md, straight from the csv outputs. python3 -I -B md_tables.py <out_dir>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
O = sys.argv[1]
KO = {"replicates (BH)": "재현 (BH)", "replicates (nominal only)": "약한 재현", "inconclusive (same sign)": "불확실 (부호 같음)",
      "inconclusive (sign flipped)": "불확실 (부호 반대)", "contradicted": "반대로 나옴", "no data": "자료 없음"}
def f(x, d=3, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)): return "-"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}")
def cell(r): return f"{r.strategy}@{r.tf}"
def main_table(D):
    print("| 칸 | 5년 gross R (t) | 5년 방향성분 (t) | 이전 n | 이전 gross R (t) | 이전 net R (t) | 이전 방향성분 (t) | 기대 t | 차이 z | q (gross) | 판정: gross | 판정: 방향성분 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in D.itertuples():
        print(f"| {cell(r)} | {f(r.y5_grossR)} ({f(r.y5_gross_t,2)}) | {f(r.y5_dir)} ({f(r.y5_dir_t,2)}) | {int(r.n) if np.isfinite(r.n) else '-'} | "
              f"{f(r.grossR)} ({f(r.gross_t,2)}) | {f(r.netR)} ({f(r.net_t,1)}) | {f(r.dir_content)} ({f(r.dir_t,2)}) | {f(r.exp_t,1)} | {f(r.diff_z,1)} | "
              f"{f(r.q_one,3,False)} | {KO[r.verdict]} | {KO[r.verdict_dir]} |")
P = pd.read_csv(os.path.join(O, "primary_final.csv"))
print("### primary"); main_table(P)
print("\n### primary extra")
print("| 칸 | 이전 롱 비율 | 이전 gross 롱 / 숏 | 이전 뒤집기 gross | 2020 / 2021 gross | 비용 R | 실제 펀딩 net R | 현물(같은 5년) gross (t) | 검정력 P(t≥1.5) |")
print("|---|---|---|---|---|---|---|---|---|")
for r in P.itertuples():
    print(f"| {cell(r)} | {f(r.long_share,2,False)} | {f(r.g_long)} / {f(r.g_short)} | {f(r.g_flip)} | {f(r.g_2020)} / {f(r.g_2021)} | {f(r.costR,3,False)} | {f(r.netR_realfund)} | "
          f"{f(r.spot_gross)} ({f(r.spot_gross_t,2)}) | {f(r.pow15,2,False)} |")
B = pd.read_csv(os.path.join(O, "bh22_final.csv"))
print("\n### bh22")
print("| 칸 | 5년 gross R (t) | 이전 n | 이전 gross R (t) | 이전 방향성분 (t) | q (gross) | q (방향) | 판정: gross | 판정: 방향성분 |")
print("|---|---|---|---|---|---|---|---|---|")
for r in B.sort_values("y5_grossR", ascending=False).itertuples():
    print(f"| {cell(r)} | {f(r.y5_grossR)} ({f(r.y5_gross_t,2)}) | {int(r.n)} | {f(r.grossR)} ({f(r.gross_t,2)}) | {f(r.dir_content)} ({f(r.dir_t,2)}) | "
          f"{f(r.q_one,3,False)} | {f(r.q_one_dir,3,False)} | {KO[r.verdict]} | {KO[r.verdict_dir]} |")
A = pd.read_csv(os.path.join(O, "appendix_ai_list.csv"))
print("\n### appendix")
print("| 칸 | 5년 gross R (t) | 이전 n | 이전 gross R (t) | 이전 net R | 이전 방향성분 (t) | 부호 (gross / 방향) |")
print("|---|---|---|---|---|---|---|")
for r in A.itertuples():
    print(f"| {cell(r)} | {f(r.y5_grossR)} ({f(r.y5_gross_t,2)}) | {int(r.n)} | {f(r.grossR)} ({f(r.gross_t,2)}) | {f(r.netR)} | {f(r.dir_content)} ({f(r.dir_t,2)}) | "
          f"{'같음' if r.sign_agree else '반대'} / {'같음' if r.dir_sign_agree else '반대'} |")
Q = pd.read_csv(os.path.join(O, "pre_pooled.csv"))
print("\n### pooled")
print("| 종류 | 봉 | 체결 신호 | 사이즈 통과 비율 | gross R (t) | 뒤집기 gross R (t) | 방향성분 (t) | net R | 비용 R | 손절폭 중앙값 |")
print("|---|---|---|---|---|---|---|---|---|---|")
for r in Q.itertuples():
    print(f"| {r.kind} | {r.tf} | {r.n:,} | {r.sized_share:.3f} | {f(r.gross,4)} ({f(r.gross_t,2)}) | {f(r.flip,4)} ({f(r.flip_t,2)}) | {f(r.dir,4)} ({f(r.dir_t,2)}) | {f(r.net)} | {r.cost:.3f} | {r.stop_med*100:.2f}% |")
