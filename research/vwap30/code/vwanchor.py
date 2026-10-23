"""PREREG5.md: F6_VWAP_FAIL on 30m with other VWAP anchors (the signal rule as the rule bot's view, VWAP swapped).

    python3 -I vwanchor.py build [--procs 3]   signals (D00 checked against the rule bot's signal file) + outcomes
    python3 -I vwanchor.py select              -> OUT5/select5.json, research/vwap30/finalists5.json (+ sha256)
    python3 -I vwanchor.py confirm             -> research/vwap30/results5.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwbuild3 as B
from vwcommon import *
from vwacct import metrics, trades
from vwstages3 import One, Label, wd_mask, rnd, twin_p90, R_GRID, RES_DIR
import vwstages3 as S3
from vwconfirm import pick
from paperbot.strategy_view_defs.DS_F6_VWAP_FAIL import _waiting, _prev
import hashlib
from multiprocessing import Pool

OUT5 = OUT + "_r5"
SIG5 = os.path.join(OUT5, "signals")
VARIANTS = ("D00", "D08", "D1330", "W", "R48", "R24", "R8")
EX = B.EXITS3
EX_HOUSE2 = next(e["id"] for e in EX if e["kind"] == "house" and e["stop"] == 2.0)
SEED5 = 20261028
SIZES = list(R_GRID) + ["rb9", "owners"]


def vwap_variant(df, name):
    """(VWAP, period id): anchored VWAPs reset at their anchor; rolling ones have no period (one id)."""
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    ts = df.ts.to_numpy(np.int64)
    pv = (h + l + c) / 3 * v
    if name[0] in "DW":
        if name == "W":
            per = (ts - 4 * DAY) // (7 * DAY)                    # 1970-01-05 was a Monday
        else:
            off = {"D00": 0, "D08": 8 * HOUR, "D1330": 13 * HOUR + 30 * MIN}[name]
            per = (ts - off) // DAY
        cpv = pd.Series(pv).groupby(per).cumsum().to_numpy()
        cv = pd.Series(v).groupby(per).cumsum().to_numpy()
    else:
        n = int(name[1:])
        cpv = pd.Series(pv).rolling(n, min_periods=n).sum().to_numpy()
        cv = pd.Series(v).rolling(n, min_periods=n).sum().to_numpy()
        per = np.zeros(len(ts), np.int64)
    with np.errstate(all="ignore"):
        vw = np.where(cv > 0, cpv / cv, np.nan)
    return vw, per


def fail_signals(df, vw, per):
    """The rule bot's F6_VWAP_FAIL rule (paperbot/strategy_view_defs/DS_F6_VWAP_FAIL.py) on a given VWAP and period."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    same = np.zeros(n, bool)
    same[1:] = per[1:] == per[:-1]
    c1, vw1 = _prev(c), _prev(vw)
    with np.errstate(invalid="ignore"):
        brk_dn = same & (c1 >= vw1) & (c < vw)
        brk_up = same & (c1 <= vw1) & (c > vw)
        rt_s, back_s = h >= vw, (c < vw) & (c < o)
        rt_l, back_l = l <= vw, (c > vw) & (c > o)
        hs, al_s, fs = _waiting(per, brk_dn, c > vw, rt_s & back_s)
        hl, al_l, fl = _waiting(per, brk_up, c < vw, rt_l & back_l)
    sh = hs & al_s & fs & rt_s & back_s
    lo = hl & al_l & fl & rt_l & back_l
    return lo, sh


def make_signals():
    os.makedirs(SIG5, exist_ok=True)
    for name in VARIANTS:
        rows = []
        for ci, coin in enumerate(COINS):
            df = bars(coin, "30m")
            g = grid(coin)
            vw, per = vwap_variant(df, name)
            lo, sh = fail_signals(df, vw, per)
            atr, _ = atr_adx(df)
            i = np.r_[np.flatnonzero(lo), np.flatnonzero(sh)]
            side = np.r_[np.ones(lo.sum(), int), -np.ones(sh.sum(), int)]
            t = df.ts.to_numpy()[i] + 30 * MIN
            e = (t - T0) // MIN
            ok = e < g["n"] - 1
            i, side, t, e = i[ok], side[ok], t[ok], e[ok]
            rows.append(pd.DataFrame({"t": t, "coin": ci, "side": side, "atr": atr[i], "close": df.close.to_numpy()[i],
                                      "ref": g["o"][e]}))
        S = pd.concat(rows).sort_values(["t", "coin"]).reset_index(drop=True)
        np.savez(os.path.join(SIG5, f"VW_{name}_at_30m.npz"), t=S.t.to_numpy(np.int64), coin=S.coin.to_numpy(np.int8),
                 side=S.side.to_numpy(np.int8), atr=S.atr.to_numpy(), close=S.close.to_numpy(), ref=S.ref.to_numpy())
        print("signals", name, len(S), flush=True)
    # D00 must be the rule bot's signal set
    a = np.load(os.path.join(SIG5, "VW_D00_at_30m.npz"))
    b = np.load(os.path.join(B.SIG, "F6_VWAP_FAIL_at_30m.npz"))
    ka = set(zip(a["t"].tolist(), a["coin"].tolist(), a["side"].tolist()))
    kb = set(zip(b["t"].astype(np.int64).tolist(), b["coin"].astype(int).tolist(), b["side"].astype(int).tolist()))
    print("D00 vs rule bot signals: same", len(ka & kb), "only mine", len(ka - kb), "only rule bot", len(kb - ka), flush=True)
    assert len(ka ^ kb) == 0, "D00 differs from the rule bot's signals"


def build(procs):
    make_signals()
    B.SIG = SIG5
    B.OUT3 = os.path.join(OUT5, "out")
    os.makedirs(B.OUT3, exist_ok=True)
    files = [os.path.join(SIG5, f"VW_{n}_at_30m.npz") for n in VARIANTS]
    with Pool(procs) as pool:
        for r in pool.imap_unordered(B.job, files):
            print("outcomes", *r, flush=True)


def use_out():
    S3.OUT3 = os.path.join(OUT5, "out")


def select():
    use_out()
    rows = []
    for name in VARIANTS:
        lab = Label(f"VW_{name}_at_30m")
        for e in EX:
            o = lab.one(e["id"])
            x = metrics(o, wd_mask(o), 0, "select")
            rows.append({"variant": name, "exit": e["id"], "exit_ko": B.exit3_name(e),
                         **rnd({q: x[q] for q in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")})})
    ok = [r for r in rows if r["per_weekday"] >= 3.0]
    best = max(ok, key=lambda r: r["growth"])
    okh = [r for r in ok if r["exit"] == EX_HOUSE2]
    best_h = max(okh, key=lambda r: r["growth"]) if okh else None
    fin = [{"name": "VWAP 기준 바꾸기 1등", "variant": best["variant"], "exit": best["exit"], "exit_ko": best["exit_ko"]}]
    if best_h and (best_h["variant"], best_h["exit"]) != (best["variant"], best["exit"]):
        fin.append({"name": "규칙봇 청산 중 1등", "variant": best_h["variant"], "exit": EX_HOUSE2, "exit_ko": best_h["exit_ko"]})
    fin.append({"name": "기준선: 지금(D00) + 규칙봇 청산", "variant": "D00", "exit": EX_HOUSE2, "exit_ko": B.exit3_name(EX[EX_HOUSE2])})
    fp = os.path.join(RES_DIR, "finalists5.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin}, open(fp, "w"),
              ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists5.json\n")
    json.dump({"rows": rows}, open(os.path.join(OUT5, "select5.json"), "w"), ensure_ascii=False, indent=1, default=float)
    for f in fin:
        print("finalist", f)
    for name in VARIANTS:
        rr = [r for r in rows if r["variant"] == name]
        h = next(r for r in rr if r["exit"] == EX_HOUSE2)
        bb = max([r for r in rr if r["per_weekday"] >= 3] or rr, key=lambda r: r["growth"])
        print(f'{name:6} house2: n={h["n"]} wd={h["per_weekday"]:.2f} win={h["win"]:.3f} R={h["avgR"]:+.3f} g={h["growth"]:+.2f} | '
              f'best {bb["exit_ko"]}: wd={bb["per_weekday"]:.2f} win={bb["win"]:.3f} R={bb["avgR"]:+.3f} g={bb["growth"]:+.2f}')


def month_odds(o, m):
    """Every 30-day stretch over select + confirm at a fixed exposure: share of x5 / x10 / x20, share losing 90 %."""
    a, z = SEL[0], CONF[1]
    idx, net, ext, D = trades(o, m & (o.entry >= a) & (o.entry < z), 0)
    kd = (o.entry[idx] + KST) // DAY
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    out = {}
    for E in (9, 15, 20, 30):
        x = np.log1p(np.maximum(E * net, -1 + 1e-12))
        per = np.zeros(d1 - d0 + 1)
        np.add.at(per, kd - d0, x)
        cs = np.r_[0, np.cumsum(per)]
        mm = np.exp(cs[30:] - cs[:-30])
        out[str(E)] = {"x5": round(float((mm >= 5).mean()), 4), "x10": round(float((mm >= 10).mean()), 4),
                       "x20": round(float((mm >= 20).mean()), 4), "lose90": round(float((mm <= 0.1).mean()), 4),
                       "median": round(float(np.median(mm)), 4)}
    return out


def confirm():
    use_out()
    fp = os.path.join(RES_DIR, "finalists5.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists5.json changed after it was frozen"
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    res = []
    for f in json.load(open(fp))["finalists"]:
        o = Label(f"VW_{f['variant']}_at_30m").one(f["exit"])
        m = wd_mask(o)
        row = dict(f)
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(o, m, 0, per))
        p90, tw = twin_p90(o, m, "confirm", 1000, SEED5)
        g = row["confirm"]["growth"]
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["month_odds"] = month_odds(o, m)
        res.append(row)
        print(f["name"], f["variant"], f["exit_ko"], "| select R", row["select"]["avgR"], "wd", row["select"]["per_weekday"],
              "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"], "win", row["confirm"]["win"], "R",
              row["confirm"]["avgR"], "g", g, "p90", round(p90, 2), "->", row["verdict"], "| live R", row["live"]["avgR"],
              "| odds", row["month_odds"], flush=True)
    sel = json.load(open(os.path.join(OUT5, "select5.json")))
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res,
               "select_rows": sel["rows"]}, open(os.path.join(RES_DIR, "results5.json"), "w"), ensure_ascii=False, indent=1,
              default=float)
    print("written results5.json")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3)
    else:
        {"select": select, "confirm": confirm}[cmd]()
