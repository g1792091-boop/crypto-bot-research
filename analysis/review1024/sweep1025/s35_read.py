"""Read the no-hold-limit sweeps (out/free35_*.json, out/more36.json): per family the setting picked on 2022-24 (best
geometric mean month) and what it did on 2025-01 .. 2026-09 and October 2026; how many settings beat x1 / x1.5 / x2 a
month on the check period; the coin-flip controls the same way. argv: json files."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
files = sys.argv[1:] or ["free35_main.json"]
rows = []
for f in files:
    for lab, byc in json.load(open(os.path.join(OUTD, f))).items():
        for cst, byx in byc.items():
            for xn, r in byx.items():
                rows.append((lab, cst, xn, r))


def fam(lab):
    if lab.startswith("B 대조"):
        return "대조 " + lab.split(" / ")[0].replace("B 대조 ", "")
    if lab.startswith("B 추세"):
        return "B 추세 " + lab.split(" / ")[1].split("@")[1]
    return lab.split(" / ")[0] if " / " in lab else lab.split(" ")[0] + " " + lab.split(" ")[1]


def line(lab, xn, r, key="확인"):
    p, c, f = r["고르기"], r[key], r["10월"]
    return (f"{lab} | {xn} | 고르기 ×{p['기하평균']}/×{p['중간값']} (x3+ {p['x3+']}, x5+ {p['x5+']}, -50% {p['-50%']}, 월 {p['달 진입']})"
            f" → 확인 ×{c['기하평균']}/×{c['중간값']} (x3+ {c['x3+']}, x5+ {c['x5+']}, -50% {c['-50%']}, 월 {c['달 진입']}) | 10월 ×{f['중간값']}")


out = {}
for cst in ("0.14%", "0.08%"):
    rr = [x for x in rows if x[1] == cst]
    print(f"\n=========== {cst}  (기하평균/중간값 한 달 배수)")
    fams = sorted({fam(x[0]) for x in rr})
    out[cst] = {}
    for fm in fams:
        xs = [x for x in rr if fam(x[0]) == fm]
        b = max(xs, key=lambda x: x[3]["고르기"]["기하평균"])
        c = np.array([x[3]["확인"]["기하평균"] for x in xs])
        print(f"[{fm}] 설정 {len(xs)}개, 확인 기간 기하평균 >x1 {int((c > 1).sum())}, >x1.5 {int((c > 1.5).sum())}, >x2 {int((c > 2).sum())}")
        print("   고르기 1등:", line(b[0], b[2], b[3]))
        out[cst][fm] = {"설정": len(xs), "확인>1": int((c > 1).sum()), "확인>1.5": int((c > 1.5).sum()), "확인>2": int((c > 2).sum()),
                        "고르기1등": {"이름": b[0], "청산": b[2], **{k: b[3][k] for k in ("고르기", "확인", "10월")}}}
    real = [x for x in rr if not x[0].startswith("B 대조")]
    print("\n-- 전체(대조 제외) 고르기 상위 10:")
    for x in sorted(real, key=lambda x: -x[3]["고르기"]["기하평균"])[:10]:
        print("  ", line(x[0], x[2], x[3]))
    print("-- 참고: 확인 기간만 보고 고른 상위 5 (뒤늦게 고른 것이라 실력 증거 아님):")
    for x in sorted(real, key=lambda x: -x[3]["확인"]["기하평균"])[:5]:
        print("  ", line(x[0], x[2], x[3]))
tag = "_".join(os.path.splitext(f)[0] for f in files)
json.dump(out, open(os.path.join(OUTD, f"read_{tag}.json"), "w"), ensure_ascii=False, indent=1)
