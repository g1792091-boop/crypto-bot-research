"""PREREG2.md steps 1-3 on the select period only (weekday entries, >= 3 entries per weekday), then the frozen
finalists (finalists2.json + sha256) for vwconfirm2.py.

    python3 -I vwstages2.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwacct2 import *
from vwacct2 import _EX2
from vwstages import filters, rnd, R_GRID, RES_DIR
import hashlib

MIN_WD = 3.0
BOOKS = ("15m", "30m", "1h", "30mc")
SIZES = list(R_GRID) + ["rb9", "owners"]
NEW_FILTERS = {"오늘 그 코인 손실 1번이면 그 코인 그날 쉼": 1, "오늘 손실 2번이면 그날 쉼": 2}


def filters2(book):
    f = filters(book.F)
    f.pop("평일만")                                    # every row is already weekday-only
    return f


def main():
    t0 = time.time()
    n_cfg = 0
    books = {b: Book2(b) for b in BOOKS}
    books["pool"] = pool([books["15m"], books["30m"], books["1h"]])
    wdm = {k: ~b.F.weekend.to_numpy(bool) for k, b in books.items()}
    # step 1: 512 exits x 5 books
    st1 = {}
    for k, b in books.items():
        rows = []
        for e in EXITS2:
            x = metrics(b, wdm[k], e["id"], "select", full=False)
            rows.append({"exit": e["id"], "growth": round(x["growth"], 4), "per_weekday": round(x["per_weekday"], 3),
                         "n": x["n"]})
        n_cfg += len(EXITS2)
        ok = [r for r in rows if r["per_weekday"] >= MIN_WD]
        best = max(ok, key=lambda r: r["growth"]) if ok else None
        full = rnd(metrics(b, wdm[k], best["exit"], "select")) if best else None
        st1[k] = {"rows": rows, "n_ok": len(ok), "best": best and {**best, "exit_ko": exit2_name(_EX2[best["exit"]])},
                  "best_full": full}
        print("step1", k, "ok", len(ok), "best", best and exit2_name(_EX2[best["exit"]]), full and
              {q: full[q] for q in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")}, flush=True)
    top_book = max((k for k in st1 if st1[k]["best"]), key=lambda k: st1[k]["best"]["growth"])
    j1 = st1[top_book]["best"]["exit"]
    b1 = books[top_book]
    print("step1 overall", top_book, exit2_name(_EX2[j1]), flush=True)
    # step 2: filters on the overall best
    base = metrics(b1, wdm[top_book], j1, "select")
    F = filters2(b1)
    rows = []
    for name, m in F.items():
        x = metrics(b1, wdm[top_book] & m, j1, "select")
        rows.append(rnd({"filter": name, **{q: x[q] for q in ("n", "per_weekday", "win", "avgR", "payoff", "growth",
                                                             "maxdd")}, "dgrowth": x["growth"] - base["growth"],
                         "pass": bool(x["growth"] > base["growth"] and x["per_weekday"] >= MIN_WD)}))
    for name, rule in NEW_FILTERS.items():
        x = metrics(b1, wdm[top_book], j1, "select", take=take_rule(rule))
        rows.append(rnd({"filter": name, **{q: x[q] for q in ("n", "per_weekday", "win", "avgR", "payoff", "growth",
                                                             "maxdd")}, "dgrowth": x["growth"] - base["growth"],
                         "pass": bool(x["growth"] > base["growth"] and x["per_weekday"] >= MIN_WD)}))
    n_cfg += len(rows)
    passed = sorted([r for r in rows if r["pass"]], key=lambda r: -r["growth"])
    bundle, cur, m_cur, rule_cur, steps = [], base, wdm[top_book].copy(), 0, []
    for r in passed:
        if len(bundle) == 3:
            break
        nm = r["filter"]
        m_try, rule_try = m_cur, rule_cur
        if nm in NEW_FILTERS:
            rule_try = rule_cur | NEW_FILTERS[nm]
        else:
            m_try = m_cur & F[nm]
        x = metrics(b1, m_try, j1, "select", take=take_rule(rule_try) if rule_try else None)
        n_cfg += 1
        ok = x["growth"] > cur["growth"] and x["per_weekday"] >= MIN_WD
        steps.append({"add": nm, "growth": round(x["growth"], 4), "per_weekday": round(x["per_weekday"], 3), "kept": ok})
        if ok:
            bundle.append(nm)
            cur, m_cur, rule_cur = x, m_try, rule_try
    print("step2 passed", len(passed), "bundle", bundle, "growth", round(base["growth"], 3), "->", round(cur["growth"], 3),
          flush=True)
    # step 3: sizing (select) for the candidates
    j30 = st1["30m"]["best"]["exit"] if st1["30m"]["best"] else None
    jb1 = ex2_id(2.0, "house", ())
    cands = [{"name": "단계1 전체 1등", "book": top_book, "exit": j1, "bundle": [], "rule": 0}]
    if top_book != "30m" and j30 is not None:
        cands.append({"name": "단계1 30분 1등", "book": "30m", "exit": j30, "bundle": [], "rule": 0})
    if bundle:
        cands.append({"name": "단계2 묶음", "book": top_book, "exit": j1, "bundle": bundle, "rule": rule_cur})
    cands.append({"name": "기준선: 평일만 + 규칙봇 방식(30분)", "book": "30m", "exit": jb1, "bundle": [], "rule": 0})
    st3 = []
    for c in cands:
        b = books[c["book"]]
        m = wdm[c["book"]].copy()
        Fc = filters2(b)
        for nm in c["bundle"]:
            if nm not in NEW_FILTERS:
                m &= Fc[nm]
        tk = take_rule(c["rule"]) if c["rule"] else None
        c["exit_ko"] = exit2_name(_EX2[c["exit"]])
        st3.append({**c, "select": rnd(metrics(b, m, c["exit"], "select", take=tk)),
                    "sizing": [rnd({"r": r, **{q: v for q, v in metrics(b, m, c["exit"], "select", r=r, take=tk).items()
                                               if q in ("mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best",
                                                        "maxdd", "ruin", "lev_med")}}) for r in SIZES]})
        n_cfg += len(SIZES)
    fp = os.path.join(RES_DIR, "finalists2.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": cands}, open(fp, "w"),
              ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists2.json\n")
    out = {"step1": st1, "top_book": top_book, "step2": {"base": rnd(base), "rows": rows, "passed": [r["filter"] for r in passed],
           "bundle": bundle, "steps": steps, "bundle_select": rnd(cur)}, "step3": st3, "n_configs": n_cfg,
           "secs": round(time.time() - t0)}
    json.dump(out, open(os.path.join(OUT2, "select2.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("done", n_cfg, "configs", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
