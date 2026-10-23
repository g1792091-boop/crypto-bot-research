"""PREREG6.md: the friend's combination (OBV / RSI26 / MOM trend, ROC or Klinger timing; EMA21/52 + RSI26 state).

    python3 -I vwfriend.py build [--procs 3]   signals + outcomes (24 ATR exits; 9 friend exits at fixed % per leverage)
    python3 -I vwfriend.py select              -> OUT6/select6.json, research/vwap30/finalists6.json (+ sha256)
    python3 -I vwfriend.py confirm             -> research/vwap30/results6.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwbuild3 as B
from vwcommon import *
from vwacct import metrics
from vwstages3 import Label, wd_mask, rnd, twin_p90
import vwstages3 as S3
from vwconfirm import pick
from vwanchor import month_odds
import hashlib
from multiprocessing import Pool

OUT6 = OUT + "_r6"
SIG6, SIG6F = os.path.join(OUT6, "sig_atr"), os.path.join(OUT6, "sig_pct")
RULES = ("FR_ROC", "FR_KVO", "FR_EMA")
TFS6 = ("30m", "1h")
LEVS = {10: 0.12 / 10, 20: 0.12 / 20, 30: 0.12 / 30}     # ROE -12 % as a price distance
ATR_EX = B.EXITS3
FR_EX = [{"id": i, "kind": "grid", "stop": 1.0, "target": tp / 12.0, "be": None, "time": 96, "tp_roe": tp}
         for i, tp in enumerate((10, 13, 16))]
SEED6 = 20261029
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))


def rsi(c, n):
    d = np.diff(c, prepend=c[0])
    up, dn = wilder(np.maximum(d, 0), n), wilder(np.maximum(-d, 0), n)
    with np.errstate(all="ignore"):
        return 100 - 100 / (1 + up / dn)


def klinger(h, l, c, v):
    hlc = h + l + c
    trend = np.where(np.r_[False, hlc[1:] > hlc[:-1]], 1.0, -1.0)
    dm = h - l
    cm = np.empty(len(c))
    cm[0] = dm[0]
    for i in range(1, len(c)):
        cm[i] = cm[i - 1] + dm[i] if trend[i] == trend[i - 1] else dm[i - 1] + dm[i]
    with np.errstate(all="ignore"):
        vf = np.where(cm > 0, v * np.abs(2 * dm / cm - 1) * trend * 100, 0.0)
    kvo = ema(vf, 34) - ema(vf, 55)
    return kvo, ema(kvo, 13)


def rule_signals(df, rule):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    p = lambda x: np.r_[np.nan, x[:-1]]
    r26 = rsi(c, 26)
    with np.errstate(invalid="ignore"):
        if rule == "FR_EMA":
            e21, e52 = ema(c, 21), ema(c, 52)
            sl = (e21 > e52) & (r26 > 50)
            ss = (e21 < e52) & (r26 < 50)
            lo = sl & ~np.r_[False, sl[:-1]]
            sh = ss & ~np.r_[False, ss[:-1]]
        else:
            obv = np.cumsum(np.sign(np.diff(c, prepend=c[0])) * v)
            oe = ema(obv, 20)
            mom = c - np.r_[np.full(10, np.nan), c[:-10]]
            tl = (obv > oe) & (r26 > 50) & (mom > 0)
            ts = (obv < oe) & (r26 < 50) & (mom < 0)
            if rule == "FR_ROC":
                roc = 100 * (c / np.r_[np.full(9, np.nan), c[:-9]] - 1)
                lo = tl & (p(roc) <= 0) & (roc > 0)
                sh = ts & (p(roc) >= 0) & (roc < 0)
            else:
                kvo, sig = klinger(h, l, c, v)
                lo = tl & (p(kvo) <= p(sig)) & (kvo > sig)
                sh = ts & (p(kvo) >= p(sig)) & (kvo < sig)
    lo[:200] = False
    sh[:200] = False
    return lo, sh


def make_signals():
    os.makedirs(SIG6, exist_ok=True)
    os.makedirs(SIG6F, exist_ok=True)
    for rule in RULES:
        for tf in TFS6:
            rows = []
            for ci, coin in enumerate(COINS):
                df = bars(coin, tf)
                g = grid(coin)
                lo, sh = rule_signals(df, rule)
                atr, _ = atr_adx(df)
                i = np.r_[np.flatnonzero(lo), np.flatnonzero(sh)]
                side = np.r_[np.ones(lo.sum(), int), -np.ones(sh.sum(), int)]
                t = df.ts.to_numpy()[i] + TF_MIN[tf] * MIN
                e = (t - T0) // MIN
                ok = (e < g["n"] - 1) & np.isfinite(atr[i])
                i, side, t, e = i[ok], side[ok], t[ok], e[ok]
                rows.append(pd.DataFrame({"t": t, "coin": ci, "side": side, "atr": atr[i], "ref": g["o"][e]}))
            S = pd.concat(rows).sort_values(["t", "coin"]).reset_index(drop=True)
            base = dict(t=S.t.to_numpy(np.int64), coin=S.coin.to_numpy(np.int8), side=S.side.to_numpy(np.int8),
                        close=S.ref.to_numpy(), ref=S.ref.to_numpy())
            np.savez(os.path.join(SIG6, f"{rule}_at_{tf}.npz"), atr=S.atr.to_numpy(), **base)
            for lev, pct in LEVS.items():
                np.savez(os.path.join(SIG6F, f"{rule}_L{lev}_at_{tf}.npz"), atr=S.ref.to_numpy() * pct, **base)
            print("signals", rule, tf, len(S), flush=True)


def run_pool(sig_dir, out_dir, exits, procs):
    B.SIG, B.OUT3, B.EXITS3 = sig_dir, out_dir, exits
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(os.path.join(sig_dir, f) for f in os.listdir(sig_dir) if f.endswith(".npz"))
    with Pool(procs) as pool:
        for r in pool.imap_unordered(B.job, files):
            print("outcomes", *r, flush=True)


def build(procs):
    make_signals()
    run_pool(SIG6, os.path.join(OUT6, "atr"), ATR_EX, procs)
    run_pool(SIG6F, os.path.join(OUT6, "fr"), FR_EX, procs)


def use(kind):
    S3.OUT3 = os.path.join(OUT6, kind)
    S3.EXITS3 = ATR_EX if kind == "atr" else FR_EX


def ex_name(kind, j, label):
    if kind == "atr":
        return B.exit3_name(ATR_EX[j])
    lev = label.split("_L")[1].split("_")[0]
    return f"친구 방식 {lev}배: 손절 ROE −12% · 익절 ROE +{FR_EX[j]['tp_roe']}%"


def select():
    rows = []
    for kind, exits in (("atr", ATR_EX), ("fr", FR_EX)):
        use(kind)
        for rule in RULES:
            for tf in TFS6:
                labs = [f"{rule}_at_{tf}"] if kind == "atr" else [f"{rule}_L{lev}_at_{tf}" for lev in LEVS]
                for lab in labs:
                    L = Label(lab)
                    for e in exits:
                        o = L.one(e["id"])
                        x = metrics(o, wd_mask(o), 0, "select")
                        rows.append({"kind": kind, "label": lab, "rule": rule, "tf": tf, "exit": e["id"],
                                     "exit_ko": ex_name(kind, e["id"], lab),
                                     **rnd({q: x[q] for q in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")})})
    ok = [r for r in rows if r["per_weekday"] >= 3.0]
    best = max(ok, key=lambda r: r["growth"])
    frs = [r for r in rows if r["kind"] == "fr"]
    fr_ok = [r for r in frs if r["per_weekday"] >= 3.0]
    best_fr = max(fr_ok or frs, key=lambda r: r["growth"])
    fin = [{"name": "친구 조합 1등", **{k: best[k] for k in ("kind", "label", "rule", "tf", "exit", "exit_ko")}}]
    if (best_fr["label"], best_fr["exit"]) != (best["label"], best["exit"]):
        fin.append({"name": "친구 방식 청산 1등" + ("" if fr_ok else " (평일 3번 못 채움)"),
                    **{k: best_fr[k] for k in ("kind", "label", "rule", "tf", "exit", "exit_ko")}})
    fp = os.path.join(RES_DIR, "finalists6.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin}, open(fp, "w"),
              ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists6.json\n")
    json.dump({"rows": rows}, open(os.path.join(OUT6, "select6.json"), "w"), ensure_ascii=False, indent=1, default=float)
    for f in fin:
        print("finalist", f)
    for rule in RULES:
        for tf in TFS6:
            rr = [r for r in rows if r["rule"] == rule and r["tf"] == tf]
            bb = max(rr, key=lambda r: r["growth"])
            print(f'{rule} {tf}: signals/weekday(best) {bb["per_weekday"]:.2f} best {bb["exit_ko"]}: win={bb["win"]:.3f} '
                  f'R={bb["avgR"]:+.3f} g={bb["growth"]:+.2f} | positive-growth exits {sum(r["growth"] > 0 for r in rr)}/{len(rr)}')


def confirm():
    fp = os.path.join(RES_DIR, "finalists6.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists6.json changed after it was frozen"
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    res = []
    for f in json.load(open(fp))["finalists"]:
        use(f["kind"])
        o = Label(f["label"]).one(f["exit"])
        m = wd_mask(o)
        row = dict(f)
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(o, m, 0, per))
        p90, tw = twin_p90(o, m, "confirm", 1000, SEED6)
        g = row["confirm"]["growth"]
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["month_odds"] = month_odds(o, m)
        res.append(row)
        print(f["name"], f["label"], f["exit_ko"], "| select wd", row["select"]["per_weekday"], "win", row["select"]["win"],
              "R", row["select"]["avgR"], "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"], "win",
              row["confirm"]["win"], "R", row["confirm"]["avgR"], "g", g, "p90", round(p90, 2), "->", row["verdict"],
              "| live n", row["live"]["n"], "win", row["live"]["win"], "R", row["live"]["avgR"], "| odds", row["month_odds"], flush=True)
    sel = json.load(open(os.path.join(OUT6, "select6.json")))
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res,
               "select_rows": sel["rows"]}, open(os.path.join(RES_DIR, "results6.json"), "w"), ensure_ascii=False, indent=1,
              default=float)
    print("written results6.json")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3)
    else:
        {"select": select, "confirm": confirm}[cmd]()
