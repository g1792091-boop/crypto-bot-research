"""One data pack per strategy for the write-up: live 6 days, same-day replay, 5-year default record, watch pick and its
preview on the same days, grade. DeepSeek money figures are turned into labels before they enter the pack (D11)."""
import json
import os
import re

import numpy as np

SP = os.environ["WORKROOT"]
WD = SP + "/interim"
D = 86_400_000
WIN = 6
live = json.load(open(WD + "/live_cells.json"))
rep = json.load(open(WD + "/live_bt_d0_1835.json"))
dsr = {f"{c['name']}@{c['tf']}": c for c in json.load(open(WD + "/ds_replay.json"))["cells"]}
prev = json.load(open(WD + "/watch_preview.json"))["cands"]
srep = {(r["kind"], r["name"], r["tf"]): r for r in json.load(open(SP + "/fgwork/ana/strat_report.json"))}
rows = json.load(open(WD + "/core_default_trades.json"))
D0, END = rep["live_d0"], rep["end"]
grades = {}
for line in open("/home/user/crypto-bot-research/research/fullgrid/STRATEGY_EVAL_KO.md", encoding="utf-8"):
    m = re.match(r"### (\S+) (.+) \(([A-Za-z0-9_]+)\) — (.+)$", line.strip())
    if m:
        grades[m.group(3)] = {"grade": m.group(1), "name_ko": m.group(2), "label": m.group(4)}
r4 = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
sign = lambda v: None if v is None else ("+" if v > 0 else "−")  # noqa: E731
# 5-year per-signal core arrays
five = {}
for name, tf, close, x, pid, coin, side in rows:
    close, x, pid, side = np.array(close, np.int64), np.array(x, float), np.array(pid), np.array(side)
    m = ((pid == 0) | (pid == 1)) & np.isfinite(x)
    o = np.argsort(close[m])
    five[f"{name}@{tf}"] = (close[m][o], x[m][o], side[m][o], pid[m][o])
t0 = min(c[0][0] for c in five.values() if len(c[0]))
t1 = max(c[0][-1] for c in five.values() if len(c[0]))
starts = np.arange(t0, t1 - (WIN + 30) * D, D)


def win_stats(k, live_mean):
    c, x, side, pid = five[k]
    a = np.searchsorted(c, starts)
    b = np.searchsorted(c, starts + WIN * D)
    b2 = np.searchsorted(c, starts + (WIN + 30) * D)
    cs = np.r_[0, np.cumsum(x)]
    n = b - a
    ok = n >= 3
    if not ok.any():
        return None
    mean6 = (cs[b] - cs[a])[ok] / n[ok]
    out = {"windows": int(ok.sum()), "pct_rank_of_live": r4((mean6 <= live_mean).mean()),
           "share_as_good_or_better": r4((mean6 >= live_mean).mean())}
    # after weeks at least this good (non-overlapping), next 30 days
    nxt, last = [], -10 ** 18
    for s, i, j, kk in zip(starts, a, b, b2):
        if j - i >= 3 and s >= last + WIN * D and (cs[j] - cs[i]) / (j - i) >= live_mean and kk - j >= 3:
            nxt.append((cs[kk] - cs[j]) / (kk - j))
            last = s
    out["episodes_as_good_per_year"] = r4(len(nxt) / ((t1 - t0) / (365.25 * D)))
    out["next30_mean_after_as_good"] = r4(np.mean(nxt)) if nxt else None
    return out


def five_core(k):
    c, x, side, pid = five[k]
    yrs = {}
    for y in range(2021, 2027):
        lo = int(np.datetime64(f"{y}-01-01", "ms").astype(np.int64))
        hi = int(np.datetime64(f"{y + 1}-01-01", "ms").astype(np.int64))
        xs = x[(c >= lo) & (c < hi)]
        yrs[str(y)] = r4(xs.sum()) if len(xs) else None
    return {"signals_2021_2026": int(len(x)), "mean_per_trade": r4(x.mean()) if len(x) else None,
            "win": r4((x > 0).mean()) if len(x) else None, "test_2024_26_mean": r4(x[pid == 1].mean()) if (pid == 1).any() else None,
            "year_sums": yrs, "positive_years": sum(1 for v in yrs.values() if v is not None and v > 0),
            "long_mean": r4(x[side > 0].mean()) if (side > 0).any() else None,
            "short_mean": r4(x[side < 0].mean()) if (side < 0).any() else None}


def acct_view(a, hide):
    if hide:
        return {"trades": a["trades"], "win": r4(a["win"]), "sign": sign(a["mean"]),
                "wallet": "↑" if a["final_x"] > 1 else ("↓" if a["final_x"] < 1 else "=")}
    return {"trades": a["trades"], "win": r4(a["win"]), "mean": r4(a["mean"]), "wallet": round(a["final_x"] * 5000),
            "max_dd": r4(a["max_dd"])}


packs = {}
for c in rep["cells"]:
    k = f"{c['name']}@{c['tf']}"
    sig = [s for s in c["signals"] if D0 <= s[0] < END]
    lo = [s[3] for s in sig if s[2] > 0]
    sh = [s[3] for s in sig if s[2] < 0]
    a = c["account"]
    rr = np.array(a["ret"])
    lv = live["core"].get(k, {"n": 0})
    p = packs.setdefault(c["name"], {"kind": "core", "name": c["name"], **grades.get(c["name"], {}), "tfs": {}})
    p["tfs"][c["tf"]] = {
        "live_6d": lv,
        "replay_same_days_to_10_09": {"trades": a["trades"], "win": r4((rr > 0).mean()) if len(rr) else None,
                                      "mean": r4(rr.mean()) if len(rr) else None, "wallet": round(a["final_x"] * 5000),
                                      "long_signals": len(lo), "long_mean": r4(np.mean(lo)) if lo else None,
                                      "short_signals": len(sh), "short_mean": r4(np.mean(sh)) if sh else None},
        "five_year_default": five_core(k) if k in five else None,
        "five_year_test_account": srep[("core", c["name"], c["tf"])]["default"]["account"]["test"],
        "this_week_vs_own_5y_weeks": win_stats(k, lv["mean"]) if lv.get("n", 0) >= 3 and k in five else None,
    }
for k, c in dsr.items():
    name, tf = k.split("@")
    lv = live["ds"].get(k, {"n": 0})
    s = srep[("ds", name, tf)]["default"]
    t = s["periods"]["test"]
    yrs = None
    p = packs.setdefault(name, {"kind": "ds", "name": name, **grades.get(name, {}), "tfs": {}})
    p["tfs"][tf] = {
        "live_6d": lv,
        "replay_same_days_to_10_09": {**acct_view(c["acct"], True), "signals": c["sig_n"], "signal_win": r4(c["sig_win"]),
                                      "signal_sign": sign(c["sig_mean"])},
        "five_year_default_labels": {"test_signals": t.get("n"), "test_win": r4(t.get("win")), "test_sign": sign(t.get("mean")),
                                     "test_account_wallet": "↑" if (s["account"]["test"] or {}).get("final_x", 1) > 1 else "↓",
                                     "long_sign": sign(s["sides"]["long"].get("mean")), "short_sign": sign(s["sides"]["short"].get("mean"))},
    }
for c in prev:
    hide = c["kind"] == "ds"
    p = packs[c["name"]]
    p.setdefault("watch_picks", {})[c["tf"]] = {
        "exit": c["exit"], "same_days_from_live_start": {r: acct_view(c["live"][r], hide) for r in ("cand", "quarter", "exitonly", "base")},
        "from_10_01": {r: acct_view(c["oct1"][r], hide) for r in ("cand", "quarter", "exitonly", "base")}}
json.dump(packs, open(WD + "/packs.json", "w"), ensure_ascii=False, indent=1)
print(len(packs), "strategies;", sum(1 for p in packs.values() if p["kind"] == "core"), "core")
# sanity: no DS money in DS packs
s = json.dumps({k: v for k, v in packs.items() if v["kind"] == "ds"}, ensure_ascii=False)
assert '"mean":' not in s and '"wallet": 5' not in s, "DS money leaked"
print("ds packs money-free")
