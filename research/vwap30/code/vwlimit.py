"""PREREG4.md: VWAP 30m with a limit entry k ATR better than the signal-close price, good for M minutes (maker entry,
round trip 0.09 %), against the market entry (round trip 0.14 %). Same 24 exits as round 3, measured from the fill.

    python3 -I vwlimit.py build [--procs 3]     -> OUT4/<variant>_<side>.npz
    python3 -I vwlimit.py select                -> OUT4/select4.json, research/vwap30/finalists4.json (+ sha256)
    python3 -I vwlimit.py confirm               -> research/vwap30/results4.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwbuild3 as B
from vwcommon import *
from vwacct import metrics, _take, stake
from vwstages3 import One, wd_mask, rnd, R_GRID, RES_DIR
from vwconfirm import pick
import hashlib, warnings
from multiprocessing import Pool
warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT4 = OUT + "_r4"
SIGF = os.path.join(B.SIG, "F6_VWAP_FAIL_at_30m.npz")
COST_MKT, COST_LMT = 2 * (0.0005 + 0.0002), 0.0002 + 0.0005 + 0.0002
VARIANTS = [("mkt", None, 0)] + [(f"k{k:g}_m{M}", k, M) for k in (0.0, 0.1, 0.25) for M in (30, 60)]
EX = B.EXITS3
EX_HOUSE2 = next(e["id"] for e in EX if e["kind"] == "house" and e["stop"] == 2.0)
SEED4 = 20261027
SIZES = list(R_GRID) + ["rb9", "owners"]
TFM = 30


def build_job(args):
    name, k, M, flip = args
    cost = COST_MKT if k is None else COST_LMT
    B.COST_RT = cost                                      # outcomes3 reads it (ladder ROE and the net)
    Z = np.load(SIGF)
    W = 96 * TFM
    rows = []
    for ci, coin in enumerate(COINS):
        m = Z["coin"] == ci
        g = grid(coin)
        t_ = Z["t"][m].astype(np.int64)
        s = Z["side"][m].astype(int) * (-1 if flip else 1)
        atr = Z["atr"][m].astype(float)
        e = (t_ - T0) // MIN
        ok = (e >= 1) & (e < g["n"] - 2) & np.isfinite(atr) & (atr > 0)
        t_, s, atr, e = t_[ok], s[ok], atr[ok], e[ok]
        ref = g["o"][e]
        n = len(t_)
        if k is None:
            f = e.copy()
            px = ref.copy()
            filled = np.ones(n, bool)
        else:
            L = ref * (1 - s * k * atr / ref)
            idx = np.minimum(e[:, None] + np.arange(M)[None, :], g["n"] - 1)
            touch = np.where(s[:, None] > 0, g["l"][idx] <= L[:, None], g["h"][idx] >= L[:, None])
            filled = touch.any(1)
            first = touch.argmax(1)
            f = e + first
            o_f = g["o"][f]
            px = np.where(s > 0, np.minimum(L, o_f), np.maximum(L, o_f))
        ret = np.full((n, len(EX)), np.nan, np.float32)
        tt = np.full((n, len(EX)), M - 1 if k is not None else 0, np.int32)
        fi = np.flatnonzero(filled)
        cumf = np.cumsum(g["fund"])
        CH = 600
        for a in range(0, len(fi), CH):
            q = fi[a:a + CH]
            ff = f[q]
            idx = np.minimum(ff[:, None] + np.arange(W)[None, :], g["n"] - 1)
            base = px[q][:, None]
            P = {"H": g["h"][idx] / base - 1, "L": g["l"][idx] / base - 1, "C": g["c"][idx] / base - 1,
                 "O": g["o"][idx] / base - 1, "F": cumf[idx] - cumf[ff - 1][:, None]}
            hmax = np.minimum(W, g["n"] - ff).astype(np.int64)
            r, x = B.outcomes3(P, s[q], atr[q] / px[q], coin, TFM, hmax)
            ret[q] = r
            tt[q] = x.astype(np.int32) + (ff - e[q])[:, None]          # minutes from the signal to the exit
        rows.append({"t": t_, "coin": np.full(n, ci), "side": s, "atrf": atr / ref, "ret": ret, "tt": tt,
                     "filled": filled, "wait": np.where(filled, f - e, -1)})
    out = {q: np.concatenate([r[q] for r in rows]) for q in rows[0]}
    os.makedirs(OUT4, exist_ok=True)
    np.savez(os.path.join(OUT4, f"{name}_{'o' if flip else 's'}.npz"), **out)
    return name, flip, int(out["filled"].sum()), len(out["t"])


class LimitBook(One):
    def __init__(self, name):
        cost = COST_MKT if name == "mkt" else COST_LMT
        S = np.load(os.path.join(OUT4, f"{name}_s.npz"))
        O = np.load(os.path.join(OUT4, f"{name}_o.npz"))
        assert (S["t"] == O["t"]).all()
        o = np.lexsort((S["coin"], S["t"]))
        self.entry = S["t"][o].astype(np.int64)
        self.coin = S["coin"][o]
        self.ret, self.t = S["ret"][o].astype(float), S["tt"][o].astype(np.int64)
        self.ret_o, self.t_o = O["ret"][o].astype(float), O["tt"][o].astype(np.int64)
        self.atrf = S["atrf"][o]
        self.cost = cost
        self.fill_rate = float(S["filled"].mean())
        kst = pd.to_datetime(self.entry + KST, unit="ms")
        self.wd = np.asarray(kst.dayofweek < 5)
        self.lev_owner = np.where(self.coin == 0, 40.0, 30.0)
        self.name = name

    def risk_dist(self, j):
        e = EX[j]
        if e["kind"] == "owners":
            return 0.5 / self.lev_owner
        return e["stop"] * self.atrf + self.cost


def take_filled(book, mask, j, flip=None):
    """One slot: a pending order holds it until its fill or expiry; only filled orders are trades."""
    ret, t = book.ret[:, j], book.t[:, j]
    if flip is not None:
        ret = np.where(flip, book.ret_o[:, j], ret)
        t = np.where(flip, book.t_o[:, j], t)
    ext = book.entry + (t + 1) * MIN
    idx = _take(book.entry, ext, mask)
    idx = idx[np.isfinite(ret[idx])]
    return idx, ret[idx], ext[idx], book.risk_dist(j)[idx]


def exit_ko(j):
    return B.exit3_name(EX[j])


def select():
    books = {v[0]: LimitBook(v[0]) for v in VARIANTS}
    rows = []
    for nm, b in books.items():
        for e in EX:
            x = metrics(b, wd_mask(b), e["id"], "select", take=take_filled)
            rows.append({"variant": nm, "exit": e["id"], "exit_ko": exit_ko(e["id"]), "fill_rate": round(b.fill_rate, 3),
                         **rnd({q: x[q] for q in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")})})
    ok = [r for r in rows if r["variant"] != "mkt" and r["per_weekday"] >= 3.0]
    best = max(ok, key=lambda r: r["growth"]) if ok else None
    okh = [r for r in ok if r["exit"] == EX_HOUSE2]
    best_h = max(okh, key=lambda r: r["growth"]) if okh else None
    fin = [{"name": "지정가 진입 1등", "variant": best["variant"], "exit": best["exit"], "exit_ko": best["exit_ko"]}] if best else []
    if best_h and (not best or (best_h["variant"], best_h["exit"]) != (best["variant"], best["exit"])):
        fin.append({"name": "지정가 진입 + 규칙봇 청산(2ATR + 계단)", "variant": best_h["variant"], "exit": EX_HOUSE2,
                    "exit_ko": exit_ko(EX_HOUSE2)})
    fin.append({"name": "기준선: 지금 규칙봇(시장가 + 2ATR + 계단)", "variant": "mkt", "exit": EX_HOUSE2, "exit_ko": exit_ko(EX_HOUSE2)})
    fp = os.path.join(RES_DIR, "finalists4.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin}, open(fp, "w"),
              ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists4.json\n")
    json.dump({"rows": rows, "fill_rates": {k: round(b.fill_rate, 4) for k, b in books.items()}},
              open(os.path.join(OUT4, "select4.json"), "w"), ensure_ascii=False, indent=1, default=float)
    for f in fin:
        print("finalist", f)
    print("fill rates", {k: round(b.fill_rate, 3) for k, b in books.items()})


def confirm():
    fp = os.path.join(RES_DIR, "finalists4.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists4.json changed after it was frozen"
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    res = []
    for f in json.load(open(fp))["finalists"]:
        b = LimitBook(f["variant"])
        m = wd_mask(b)
        j = f["exit"]
        row = dict(f, fill_rate=round(b.fill_rate, 3))
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(b, m, j, per, take=take_filled))
            row[per + "_rb9"] = {q: round(v, 4) if isinstance(v, float) else v for q, v in
                                 metrics(b, m, j, per, r="rb9", take=take_filled).items() if q in ("mult", "maxdd", "mon_median", "mon_worst")}
        rng = np.random.default_rng(SEED4)
        tw = np.array([metrics(b, m, j, "confirm", flip=rng.random(len(b.entry)) < 0.5, full=False, take=take_filled)["growth"]
                       for _ in range(1000)])
        g = row["confirm"]["growth"]
        p90 = float(np.percentile(tw, 90))
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["sizing_confirm"] = [rnd({"r": r, **{q: v for q, v in metrics(b, m, j, "confirm", r=r, take=take_filled).items() if q in (
            "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}}) for r in SIZES]
        res.append(row)
        print(f["name"], f["variant"], f["exit_ko"], "fill", row["fill_rate"], "| select R", row["select"]["avgR"], "wd",
              row["select"]["per_weekday"], "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"], "win",
              row["confirm"]["win"], "R", row["confirm"]["avgR"], "g", g, "p90", round(p90, 2), "->", row["verdict"],
              "| live R", row["live"]["avgR"], flush=True)
    sel = json.load(open(os.path.join(OUT4, "select4.json")))
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res,
               "select_rows": sel["rows"], "fill_rates": sel["fill_rates"]},
              open(os.path.join(RES_DIR, "results4.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results4.json")


if __name__ == "__main__":
    if sys.argv[1] == "build":
        procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
        jobs = [(n, k, M, fl) for n, k, M in VARIANTS for fl in (False, True)]
        with Pool(procs, maxtasksperchild=2) as pool:
            for r in pool.imap_unordered(build_job, jobs):
                print(*r, flush=True)
    else:
        {"select": select, "confirm": confirm}[sys.argv[1]]()
