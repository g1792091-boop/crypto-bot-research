"""PREREG11.md: VWAP fail 30m on 12 more coins. Binance public monthly 1m klines + funding (data.binance.vision) are fetched
with curl into a fresh folder per coin, read as data only (zipfile + numpy, never run), reduced to one compact file per
coin, and the zips are deleted. Signals use the rule bot's view code and lib.fg.atr; outcomes use round 3's 24 exits.

    python3 -I vwcoins.py fetch [--procs 3]   -> OUT11/data/<coin>.npz
    python3 -I vwcoins.py build [--procs 3]   -> OUT11/out/<coin>.npz (signals + 24 exits, both sides)
    python3 -I vwcoins.py select              -> research/vwap30/finalists11.json (+ sha256)
    python3 -I vwcoins.py confirm             -> research/vwap30/results11.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwbuild3 as B
import vwcommon as VC
from vwcommon import *
from vwacct import metrics, trades
from vwstages3 import One, wd_mask
from vwconfirm import pick
import hashlib, io, subprocess, tempfile, zipfile, shutil, warnings
from multiprocessing import Pool
warnings.filterwarnings("ignore", category=RuntimeWarning)

NEW = ["XRPUSDT", "ADAUSDT", "BNBUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT", "ETCUSDT", "ATOMUSDT", "AVAXUSDT", "UNIUSDT",
       "FILUSDT", "NEARUSDT"]
ALL18 = COINS + NEW
OUT11 = OUT + "_r11"
RAW = os.path.join(NL.FY.SCR, "r11raw")
END11 = ms("2026-10-01")
MONTHS = pd.period_range("2020-01", "2026-09", freq="M").strftime("%Y-%m").tolist()
URL = "https://data.binance.vision/data/futures/um/monthly"
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))
EX_H2 = next(e["id"] for e in B.EXITS3 if e["kind"] == "house" and e["stop"] == 2.0)
SEED11 = 20261105
TWIN_Q = 97.0


def _curl(url, path):
    for _ in range(3):
        r = subprocess.run(["curl", "-sS", "-f", "--max-time", "180", "-o", path, url], capture_output=True)
        if r.returncode == 0:
            return True
        if b"404" in r.stderr:
            return False
    return False


def _read_zip(path, cols):
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        raw = z.read(name)
    first = raw.split(b"\n", 1)[0]
    header = 0 if not first[:1].isdigit() else None
    df = pd.read_csv(io.BytesIO(raw), header=header)
    return df.iloc[:, cols].to_numpy(float)


def fetch_one(coin):
    fp = os.path.join(OUT11, "data", f"{coin}.npz")
    if os.path.exists(fp):
        return coin, "kept"
    d = tempfile.mkdtemp(prefix=f"{coin}_", dir=RAW)                  # a fresh, empty folder for downloaded files
    K, F, missing = [], [], 0
    for m in MONTHS:
        p = os.path.join(d, f"k{m}.zip")
        if _curl(f"{URL}/klines/{coin}/1m/{coin}-1m-{m}.zip", p):
            K.append(_read_zip(p, [0, 1, 2, 3, 4, 5]))
            os.remove(p)
        else:
            missing += 1
        p = os.path.join(d, f"f{m}.zip")
        if _curl(f"{URL}/fundingRate/{coin}/{coin}-fundingRate-{m}.zip", p):
            F.append(_read_zip(p, [0, 2]))
            os.remove(p)
    shutil.rmtree(d, ignore_errors=True)
    k = np.concatenate(K)
    k = k[np.argsort(k[:, 0], kind="stable")]
    k = k[np.r_[True, np.diff(k[:, 0]) > 0]]
    f = np.concatenate(F) if F else np.zeros((0, 2))
    np.savez(fp, ts=k[:, 0].astype(np.int64), o=k[:, 1].astype(np.float32), h=k[:, 2].astype(np.float32),
             l=k[:, 3].astype(np.float32), c=k[:, 4].astype(np.float32), v=k[:, 5].astype(np.float32),
             f_t=f[:, 0].astype(np.int64), f_r=f[:, 1].astype(float))
    return coin, f"rows {len(k)}, months missing {missing}, funding {len(f)}"


def fetch(procs):
    os.makedirs(os.path.join(OUT11, "data"), exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    with Pool(procs) as pool:
        for r in pool.imap_unordered(fetch_one, NEW):
            print("fetched", *r, flush=True)


def grid_new(coin):
    """The coin's 1m grid in vwcommon.grid's form, T0 .. END11; flat bars at the previous close for missing minutes."""
    Z = np.load(os.path.join(OUT11, "data", f"{coin}.npz"))
    n = (END11 - T0) // MIN
    idx = (Z["ts"] - T0) // MIN
    ok = (idx >= 0) & (idx < n) & ((Z["ts"] - T0) % MIN == 0)
    idx = idx[ok]
    g = {}
    for k in ("o", "h", "l", "c", "v"):
        a = np.full(n, np.nan)
        a[idx] = Z[k][ok]
        g[k] = a
    first = int(idx.min())
    c = pd.Series(g["c"]).ffill().to_numpy()
    gap = np.isnan(g["o"]) & (np.arange(n) > first)
    for k in ("o", "h", "l", "c"):
        g[k][gap] = c[gap]
    g["v"][gap] = 0.0
    fund = np.zeros(n)
    fi = (Z["f_t"] - T0) // MIN
    okf = (fi >= 0) & (fi < n)
    np.add.at(fund, fi[okf], Z["f_r"][okf])
    g["fund"] = fund
    g["first"], g["n"] = first, n
    return g


def build_one(coin):
    fp = os.path.join(OUT11, "out", f"{coin}.npz")
    if os.path.exists(fp):
        return coin, 0
    from paperbot import sweepsig
    lib = sweepsig.lib()
    VC._GRID.clear()
    VC._GRID[coin] = grid_new(coin)
    g = VC.grid(coin)
    df = bars(coin, "30m")
    S = signals(coin, "30m", df)
    atr = lib.fg.atr(df, 14).to_numpy(float)[S.i.to_numpy()]
    t_ = S.bar_close.to_numpy(np.int64)
    side = S.side.to_numpy(int)
    e = (t_ - T0) // MIN
    ok = (e >= 1) & (e < g["n"] - 1) & np.isfinite(atr) & (atr > 0)
    t_, side, atr, e = t_[ok], side[ok], atr[ok], e[ok]
    ep = g["o"][e]
    ok = np.isfinite(ep) & (ep > 0)
    t_, side, atr, e, ep = t_[ok], side[ok], atr[ok], e[ok], ep[ok]
    n = len(t_)
    W = 96 * 30
    hmax = np.minimum(W, g["n"] - e).astype(np.int64)
    cumf = np.cumsum(g["fund"])
    R = {q: np.zeros((n, len(B.EXITS3)), np.float32 if q.startswith("ret") else np.int16) for q in ("ret", "tx", "ret_o", "tx_o")}
    for a in range(0, n, 500):
        b = min(n, a + 500)
        idx = np.minimum(e[a:b, None] + np.arange(W)[None, :], g["n"] - 1)
        base = ep[a:b, None]
        P = {"H": g["h"][idx] / base - 1, "L": g["l"][idx] / base - 1, "C": g["c"][idx] / base - 1,
             "O": g["o"][idx] / base - 1, "F": cumf[idx] - cumf[e[a:b] - 1][:, None]}
        af = atr[a:b] / ep[a:b]
        R["ret"][a:b], R["tx"][a:b] = B.outcomes3(P, side[a:b], af, coin, 30, hmax[a:b])
        R["ret_o"][a:b], R["tx_o"][a:b] = B.outcomes3(P, -side[a:b], af, coin, 30, hmax[a:b])
    np.savez(fp, t=t_, side=side.astype(np.int8), atrf=(atr / ep).astype(np.float32), **R)
    VC._GRID.clear()
    return coin, n


def build(procs):
    os.makedirs(os.path.join(OUT11, "out"), exist_ok=True)
    with Pool(procs) as pool:
        for r in pool.imap_unordered(build_one, NEW):
            print("built", *r, flush=True)


def check():
    """Loop check: build_one's path on an original coin (SOL, through grid_new's form of its own 1m grid) against round 3."""
    coin = "SOLUSDT"
    from paperbot import sweepsig
    lib = sweepsig.lib()
    g = VC.grid(coin)
    df = bars(coin, "30m")
    S = signals(coin, "30m", df)
    atr = lib.fg.atr(df, 14).to_numpy(float)[S.i.to_numpy()]
    Z = np.load(os.path.join(B.OUT3, "F6_VWAP_FAIL_at_30m.npz"))
    m = Z["coin"] == COINS.index(coin)
    j = pd.DataFrame({"t": S.bar_close.to_numpy(np.int64), "a": atr}).merge(
        pd.DataFrame({"t": Z["t"][m], "af": Z["atrf"][m]}), on="t")
    ep = g["o"][(j.t.to_numpy() - T0) // MIN]
    d = np.abs(j.a / ep / j.af - 1)
    print("SOL signals", len(S), "in round 3", int(m.sum()), "matched", len(j), "atrf max rel diff", float(d.max()),
          "share > 1e-4", float((d > 1e-4).mean()))


def book(coins, j=None):
    """One over the given coins (indices into ALL18), every exit column (j=None) or one."""
    parts = []
    for ci, coin in enumerate(ALL18):
        if ci not in coins:
            continue
        if ci < len(COINS):
            Z = np.load(os.path.join(B.OUT3, "F6_VWAP_FAIL_at_30m.npz"))
            m = Z["coin"] == ci
            D = {k: Z[k][m] for k in ("t", "atrf", "ret", "tx", "ret_o", "tx_o")}
        else:
            Z = np.load(os.path.join(OUT11, "out", f"{coin}.npz"))
            D = {k: Z[k] for k in ("t", "atrf", "ret", "tx", "ret_o", "tx_o")}
        D["coin"] = np.full(len(D["t"]), ci)
        parts.append(D)
    C = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    cols = range(len(B.EXITS3)) if j is None else [j]
    out = {}
    for jj in cols:
        e = B.EXITS3[jj]
        Dd = 0.5 / np.where(C["coin"] == 0, 40.0, 30.0) if e["kind"] == "owners" else e["stop"] * C["atrf"] + COST_RT
        out[jj] = One(C["t"].astype(np.int64), C["coin"], C["ret"][:, jj], C["tx"][:, jj], C["ret_o"][:, jj], C["tx_o"][:, jj],
                      Dd.astype(float))
    return out


def per_coin(o, per):
    a, z = PERIODS[per]
    idx, net, ext, D = trades(o, wd_mask(o) & (o.entry >= a) & (o.entry < z), 0)
    out = {}
    for ci in np.unique(o.coin[idx]):
        k = o.coin[idx] == ci
        out[ALL18[ci]] = {"n": int(k.sum()), "avg_net_pct": round(float(net[k].mean() * 100), 4)}
    return out


def be_win(o, per):
    a, z = PERIODS[per]
    idx, net, ext, D = trades(o, wd_mask(o) & (o.entry >= a) & (o.entry < z), 0)
    w, l = net[net > 0], net[net <= 0]
    return {"win": round(float((net > 0).mean()), 4), "breakeven_win": round(float(-l.mean() / (w.mean() - l.mean())), 4),
            "avg_net_pct": round(float(net.mean() * 100), 4)}


def select():
    rows = []
    bk = book(set(range(len(ALL18))))
    for j, o in bk.items():
        x = metrics(o, wd_mask(o), 0, "select", full=False)
        rows.append({"exit": j, "exit_ko": B.exit3_name(B.EXITS3[j]), "n": x["n"], "per_weekday": round(x["per_weekday"], 3),
                     "growth": round(x["growth"], 3)})
        print("select exit", j, rows[-1], flush=True)
    ok = [r for r in rows if r["per_weekday"] >= 3.0]
    best = max(ok, key=lambda r: r["growth"])
    fin = [{"name": "Q1 새 12코인 · 규칙봇 청산", "coins": "new12", "exit": EX_H2},
           {"name": "Q2 18코인 · 규칙봇 청산", "coins": "all18", "exit": EX_H2},
           {"name": "Q3 18코인 · 고른 청산", "coins": "all18", "exit": best["exit"]}]
    fp = os.path.join(RES_DIR, "finalists11.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin, "select_rows": rows},
              open(fp, "w"), ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists11.json\n")
    for f in fin:
        print("finalist", f, flush=True)


def month_odds_all(o):
    a, z = SEL[0], CONF[1]
    idx, net, ext, D = trades(o, wd_mask(o) & (o.entry >= a) & (o.entry < z), 0)
    kd = (o.entry[idx] + KST) // DAY
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    out = {}
    for E in (9, 15, 20, 30):
        x = np.log1p(np.maximum(E * net, -1 + 1e-12))
        per = np.zeros(d1 - d0 + 1)
        np.add.at(per, kd - d0, x)
        cs = np.r_[0, np.cumsum(per)]
        mm = np.exp(cs[30:] - cs[:-30])
        out[str(E)] = {"x2": round(float((mm >= 2).mean()), 4), "x5": round(float((mm >= 5).mean()), 4),
                       "x10": round(float((mm >= 10).mean()), 4), "x20": round(float((mm >= 20).mean()), 4),
                       "lose90": round(float((mm <= 0.1).mean()), 4), "median": round(float(np.median(mm)), 4)}
    return out


def confirm():
    fp = os.path.join(RES_DIR, "finalists11.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists11.json changed after it was frozen"
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    rng = np.random.default_rng(SEED11)
    res = []
    for f in json.load(open(fp))["finalists"]:
        coins = set(range(len(COINS), len(ALL18))) if f["coins"] == "new12" else set(range(len(ALL18)))
        o = book(coins, f["exit"])[f["exit"]]
        m = wd_mask(o)
        row = dict(f, exit_ko=B.exit3_name(B.EXITS3[f["exit"]]))
        for per in ("select", "confirm", "c2025", "c2026"):
            row[per] = pick(metrics(o, m, 0, per))
            row[per + "_rb9"] = pick(metrics(o, m, 0, per, r="rb9"))
            row[per + "_be"] = be_win(o, per)
        row["per_coin_confirm"] = per_coin(o, "confirm")
        row["per_coin_select"] = per_coin(o, "select")
        tw = np.array([metrics(o, m, 0, "confirm", flip=rng.random(len(o.entry)) < 0.5, full=False)["growth"]
                       for _ in range(2000)])
        q = float(np.percentile(tw, TWIN_Q))
        g = row["confirm"]["growth"]
        row["twin"] = {"p50": round(float(np.median(tw)), 3), "p90": round(float(np.percentile(tw, 90)), 3),
                       "p97": round(q, 3), "share_below": round(float((tw < g).mean()), 4)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > q) else "통하지 않음"
        row["month_odds"] = month_odds_all(o)
        res.append(row)
        c = row["confirm"]
        print(f["name"], row["exit_ko"], "| select wd", row["select"]["per_weekday"], "R", row["select"]["avgR"],
              "| confirm n", c["n"], "wd", c["per_weekday"], "win", c["win"], "BE", row["confirm_be"]["breakeven_win"], "R", c["avgR"],
              "g", g, "p97", round(q, 2), "share_below", row["twin"]["share_below"], "->", row["verdict"], flush=True)
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res},
              open(os.path.join(RES_DIR, "results11.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results11.json")


if __name__ == "__main__":
    cmd = sys.argv[1]
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    if cmd in ("fetch", "build"):
        {"fetch": fetch, "build": build}[cmd](procs)
    else:
        {"select": select, "confirm": confirm, "check": check}[cmd]()
