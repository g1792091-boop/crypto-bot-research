"""Stages 1-6 of PREREG.md on the select period only (2020-03-01 .. 2024-12-31). Writes OUT/select.json and the
frozen finalists (research/vwap30/finalists.json + its sha256) that vwconfirm.py reads; nothing here looks at the
confirm or live periods.

    python3 -I vwstages.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwacct import *
import hashlib

JN = {"V39": "V3.9", "S6": "EMA·DMI·ADX", "OBV": "OBV", "N12": "일목·AO"}
R_GRID = (0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20)
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))


def filters(F):
    """PREREG step 3: every single filter, at the numbers written there (True = the signal may be taken)."""
    s = F.side.to_numpy()
    f = {"평일만": ~F.weekend.to_numpy(bool),
         "VWAP 시작 2시간 뒤만": F.vwap_age_h.to_numpy() >= 2, "VWAP 시작 4시간 뒤만": F.vwap_age_h.to_numpy() >= 4}
    for a in (0, 6, 12, 18):
        f[f"한국 {a:02d}~{a + 5:02d}시 빼기"] = ~((F.kst_hour.to_numpy() >= a) & (F.kst_hour.to_numpy() <= a + 5))
    for c in COINS:
        f[f"{c[:-4]} 빼기"] = F.coin.to_numpy() != c
    f["롱만"], f["숏만"] = s > 0, s < 0
    f["반등 꼬리 ≥ 봉의 20%"] = F.wick_frac.to_numpy() >= 0.2
    f["반등 꼬리 ≥ 봉의 35%"] = F.wick_frac.to_numpy() >= 0.35
    f["VWAP 이탈 깊이 ≥ 0.15ATR"] = F.brk_depth_atr.to_numpy() >= 0.15
    f["VWAP 이탈 깊이 ≥ 0.3ATR"] = F.brk_depth_atr.to_numpy() >= 0.3
    f["종가-VWAP 거리 ≥ 0.2ATR"] = F.close_vwap_atr.to_numpy() >= 0.2
    f["종가-VWAP 거리 ≤ 0.8ATR"] = F.close_vwap_atr.to_numpy() <= 0.8
    f["거래량 ≥ 20봉 평균 1.0배"] = F.relvol.to_numpy() >= 1.0
    f["거래량 ≥ 20봉 평균 1.5배"] = F.relvol.to_numpy() >= 1.5
    f["VWAP 기울기가 진입 방향"] = F.vwap_slope_atr.to_numpy() > 0
    a, q20, q80 = (F[k].to_numpy() for k in ("atrp", "atrp_q20", "atrp_q80"))
    f["ATR% 30일 20~80% 구간"] = (a >= q20) & (a <= q80)
    f["ATR% 30일 80% 이하"] = a <= q80
    f["ATR% 30일 20% 이상"] = a >= q20
    f["ADX ≥ 20"] = F.adx.to_numpy() >= 20
    f["ADX ≤ 25"] = F.adx.to_numpy() <= 25
    for htf in ("1h", "4h"):
        hk = "1시간" if htf == "1h" else "4시간"
        for nm, ko in JN.items():
            x = F[f"j{htf}_{nm}"].to_numpy()
            f[f"추세 {hk} {ko} 같은 쪽"] = x == 1
            f[f"추세 {hk} {ko} 반대 아님"] = x != -1
        x = F[f"j{htf}_raw3"].to_numpy()
        f[f"추세 {hk} 4개 중 3개 이상 같은 쪽"] = x == 1
        f[f"추세 {hk} 3개 이상 반대쪽 아님"] = x != -1
    f["일봉 EMA20 진입 방향 쪽"] = F.ema1d20.to_numpy() > 0
    f["4시간 EMA50 진입 방향 쪽"] = F.ema4h50.to_numpy() > 0
    f["BTC 직전 봉 반대 0.3% 넘게 안 움직임"] = ~(F.btc_bar.to_numpy() < -0.003)
    f["BTC 4시간 판단 반대 아님"] = F.btc4h_raw3.to_numpy() != -1
    f["BTC 4시간 판단 같은 쪽"] = F.btc4h_raw3.to_numpy() == 1
    f["추격 막기(두 분 규칙)"] = ~F.chase.to_numpy(bool)
    dp = F.day_pos.to_numpy()
    f["하루 범위 위치(롱 70% 이하·숏 30% 이상)"] = np.where(s > 0, dp <= 0.7, dp >= 0.3)
    f["펀딩 내는 방향 빼기"] = ~F.fund_pay.to_numpy(bool)
    return f


def rnd(d):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def stage345(book, base_mask, log):
    """Steps 3-5 on one timeframe: single filters, the greedy bundle, the exit grid (all on select)."""
    tf = book.tf
    F = filters(book.F)
    base = metrics(book, base_mask, EX_B3, "select")
    rows = []
    for name, m in F.items():
        x = metrics(book, base_mask & m, EX_B3, "select")
        x["filter"] = name
        x["dR"] = x["avgR"] - base["avgR"]
        x["pass"] = bool(x["dR"] >= 0.03 and x["per_weekday"] >= 1.5)
        rows.append(rnd(x))
    log["n_configs"] += len(F)
    passed = sorted([r for r in rows if r["pass"]], key=lambda r: -r["growth"])
    bundle, cur, cur_m, steps = [], base, base_mask.copy(), []
    for r in passed:
        if len(bundle) == 3:
            break
        m = cur_m & F[r["filter"]]
        x = metrics(book, m, EX_B3, "select")
        log["n_configs"] += 1
        ok = (not bundle) or (x["avgR"] - cur["avgR"] >= 0.02 and x["per_weekday"] >= 1.5)
        ok = ok and x["per_weekday"] >= 1.5
        steps.append({"add": r["filter"], "avgR": round(x["avgR"], 4), "per_weekday": round(x["per_weekday"], 3),
                      "growth": round(x["growth"], 3), "kept": bool(ok)})
        if ok:
            bundle.append(r["filter"])
            cur, cur_m = x, m
    bmask = cur_m
    ex_rows = []
    for e in EXITS:
        x = metrics(book, bmask, e["id"], "select", full=False)
        x["exit"] = e["id"]
        ex_rows.append(x)
    log["n_configs"] += len(EXITS)
    ex_rows.sort(key=lambda x: -x["growth"])
    top = []
    for x in ex_rows[:3]:
        y = metrics(book, bmask, x["exit"], "select")
        y["exit"], y["exit_ko"] = x["exit"], exit_name(x["exit"])
        top.append(rnd(y))
    # the whole exit grid with the descriptive numbers (for the report's tables; selection used growth only)
    grid_full = []
    for e in EXITS:
        y = metrics(book, bmask, e["id"], "select")
        grid_full.append(rnd({"exit": e["id"], "exit_ko": exit_name(e["id"]), **{k: y[k] for k in (
            "n", "growth", "per_weekday", "win", "avgR", "payoff", "pf", "maxdd", "mon_median", "ruin")}}))
    return {"tf": tf, "base": rnd(base), "filters": rows, "passed": [r["filter"] for r in passed],
            "bundle": bundle, "bundle_steps": steps, "bundle_select": rnd(cur), "exit_top3": top, "exit_grid": grid_full}


def sizing(book, mask, j):
    out = []
    for r in list(R_GRID) + ["owners"]:
        x = metrics(book, mask, j, "select", r=r)
        out.append(rnd({"r": r, **{k: x[k] for k in ("n", "mult", "cagr", "mon_median", "mon_x6", "mon_worst",
                                                     "mon_best", "mon_pos", "maxdd", "ruin", "lev_med", "growth")}}))
    return out


def main():
    t0 = time.time()
    log = {"n_configs": 0}
    books = {tf: Book(tf) for tf in TF_MIN}
    allm = {tf: np.ones(len(b.entry), bool) for tf, b in books.items()}
    b30 = books["30m"]
    # step 1: baselines on 30m
    st1 = {}
    for nm, j in (("B1", EX_B1), ("B2", EX_B2), ("B3", EX_B3)):
        st1[nm] = {"exit_ko": exit_name(j), "r2": rnd(metrics(b30, allm["30m"], j, "select"))}
    st1["B2"]["owners"] = rnd(metrics(b30, allm["30m"], EX_B2, "select", r="owners"))
    st1["B1"]["owners_like"] = rnd(metrics(b30, allm["30m"], EX_B1, "select", r=0.02))
    log["n_configs"] += 3
    print("step1", {k: (v["r2"]["n"], v["r2"]["win"], v["r2"]["avgR"], v["r2"]["growth"]) for k, v in st1.items()}, flush=True)
    # step 2: timeframes at B3
    st2 = {tf: rnd(metrics(books[tf], allm[tf], EX_B3, "select")) for tf in TF_MIN}
    log["n_configs"] += 4
    best_tf = max(st2, key=lambda tf: st2[tf]["growth"])
    keep = ["30m"] + ([best_tf] if best_tf != "30m" else [])
    print("step2", {tf: (v["n"], v["win"], v["avgR"], v["growth"]) for tf, v in st2.items()}, "keep", keep, flush=True)
    # steps 3-5 per kept timeframe
    st345 = {}
    for tf in keep:
        st345[tf] = stage345(books[tf], allm[tf], log)
        s = st345[tf]
        print("step3-5", tf, "passed", len(s["passed"]), "bundle", s["bundle"],
              "top", [(x["exit_ko"], x["growth"]) for x in s["exit_top3"]], flush=True)
    # step 6: sizing of the chosen settings
    def bmask(tf):
        m = allm[tf].copy()
        Fs = filters(books[tf].F)
        for nm in st345[tf]["bundle"]:
            m &= Fs[nm]
        return m
    cands = [("B2 두 분 방식", "30m", [], EX_B2), ("B3 단순", "30m", [], EX_B3),
             ("단계4 묶음 + B3", "30m", st345["30m"]["bundle"], EX_B3)]
    for k, x in enumerate(st345["30m"]["exit_top3"]):
        cands.append((f"단계5 {k + 1}등", "30m", st345["30m"]["bundle"], x["exit"]))
    if len(keep) > 1:
        tf2 = keep[1]
        cands.append((f"단계5 1등({tf2})", tf2, st345[tf2]["bundle"], st345[tf2]["exit_top3"][0]["exit"]))
    st6 = []
    for name, tf, bund, j in cands:
        m = allm[tf].copy()
        Fs = filters(books[tf].F)
        for nm in bund:
            m &= Fs[nm]
        st6.append({"name": name, "tf": tf, "bundle": bund, "exit": j, "exit_ko": exit_name(j),
                    "select_r2": rnd(metrics(books[tf], m, j, "select")), "sizing": sizing(books[tf], m, j)})
        log["n_configs"] += len(R_GRID) + 1
    # step 7's finalists, frozen before any confirm number exists (at most five: PREREG step 7)
    fin = [c for c in cands if c[0] in ("B2 두 분 방식", "B3 단순", "단계4 묶음 + B3", "단계5 1등")]
    if len(keep) > 1:
        fin.append(cands[-1])
    finalists, seen = [], {}
    for n, tf, b, j in fin:                              # one row per distinct setting (an empty bundle + B3 is B3)
        key = (tf, tuple(b), j)
        if key in seen:
            seen[key]["name"] += f" = {n}(묶음 없음)"
            continue
        seen[key] = {"name": n, "tf": tf, "bundle": b, "exit": j, "exit_ko": exit_name(j)}
        finalists.append(seen[key])
    fp = os.path.join(RES_DIR, "finalists.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": finalists},
              open(fp, "w"), ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists.json\n")
    out = {"step1": st1, "step2": st2, "keep": keep, "step345": st345, "step6": st6, "n_configs": log["n_configs"],
           "secs": round(time.time() - t0)}
    json.dump(out, open(os.path.join(OUT, "select.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("done", log["n_configs"], "configs", round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    main()
