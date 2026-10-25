"""Owners 10/25 night, again: "promising combinations are fine, the current market matters; are the strategies fixed?
there are so many". Adds a large generated set of classic indicator rules (cross, breakout, reversion, candle, trend
flips; 77 base rules x 5 filters x 15m / 30m / 1h / 4h) to the 121 coded strategies, every cell as a one-position
bot (both sides / long only / short only), owners' fixed rules (BTC 40x / alts 30x, margin 40 %), L10 ladder, stop
ROE -25 / -35 %, weekday entries, cost 0.14 %.

Reads:
  P1  pick by the current market (Jul..Sep 2026), read the unseen 20 live days (10/05 15:00 .. 10/24 14:12 UTC);
  P2  one-position combos of the P1 leaders, read the same unseen days;
  P3  a bot that follows the current market: every 10 days take the top K cells of the last W days and trade only
      them for the next 10 days, 2022-01 .. 2026-10 (monthly), with a random-K control;
  P4  October leaders (top by the 20 live days), shown with their longer past (cannot be checked yet).
"""
import os, sys, json, time
import numpy as np, pandas as pd
from numba import njit
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, MIN, ms, DAY, GT0           # noqa: E402
from common import COINS, TF_MIN, bars                    # noqa: E402
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
P_LO = ms("2021-06-01")
TFS = ("15m", "30m", "1h", "4h")
D = FC.Data()


# ------------------------------------------------------------------ indicators
def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def rma(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def rsi(c, n):
    d = np.diff(c, prepend=c[0])
    up = rma(np.maximum(d, 0), n); dn = rma(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.where(dn == 0, np.nan, dn))


def tr_(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def atr(h, l, c, n):
    return rma(tr_(h, l, c), n)


def sh(x, k=1):
    y = np.empty_like(x, dtype=float); y[:k] = np.nan; y[k:] = x[:-k]
    return y


def xup(a, b):
    return (a > b) & (sh(a) <= sh(b))


def xdn(a, b):
    return (a < b) & (sh(a) >= sh(b))


def hh(x, n):
    return pd.Series(x).rolling(n).max().to_numpy()


def ll(x, n):
    return pd.Series(x).rolling(n).min().to_numpy()


def adx(h, l, c, n=14):
    up = h - sh(h); dn = sh(l) - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(h, l, c, n)
    pdi = 100 * rma(np.nan_to_num(pdm), n) / a; mdi = 100 * rma(np.nan_to_num(mdm), n) / a
    dx = 100 * np.abs(pdi - mdi) / np.where(pdi + mdi == 0, np.nan, pdi + mdi)
    return pdi, mdi, rma(np.nan_to_num(dx), n)


@njit(cache=True)
def supertrend_dir(h, l, c, a, m):
    n = len(c); d = np.ones(n); up = np.zeros(n); dn = np.zeros(n)
    for i in range(n):
        hl2 = (h[i] + l[i]) / 2
        bu = hl2 - m * a[i]; bd = hl2 + m * a[i]
        if i == 0:
            up[i] = bu; dn[i] = bd; continue
        up[i] = max(bu, up[i - 1]) if c[i - 1] > up[i - 1] else bu
        dn[i] = min(bd, dn[i - 1]) if c[i - 1] < dn[i - 1] else bd
        if d[i - 1] < 0 and c[i] > dn[i - 1]:
            d[i] = 1
        elif d[i - 1] > 0 and c[i] < up[i - 1]:
            d[i] = -1
        else:
            d[i] = d[i - 1]
    return d


@njit(cache=True)
def psar_dir(h, l, step, mx):
    n = len(h); d = np.ones(n); sar = l[0]; ep = h[0]; af = step; tr = 1
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if tr > 0:
            if l[i] < sar:
                tr = -1; sar = ep; ep = l[i]; af = step
            elif h[i] > ep:
                ep = h[i]; af = min(af + step, mx)
        else:
            if h[i] > sar:
                tr = 1; sar = ep; ep = h[i]; af = step
            elif l[i] < ep:
                ep = l[i]; af = min(af + step, mx)
        d[i] = tr
    return d


def rules(df):
    """{name: (long_event, short_event)} on one coin x tf."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    R = {}
    for f, s in ((5, 20), (9, 21), (12, 26), (20, 50), (50, 200), (9, 50), (13, 34), (21, 55)):
        a, b = ema(c, f), ema(c, s); R[f"EMA{f}x{s}"] = (xup(a, b), xdn(a, b))
        a, b = sma(c, f), sma(c, s); R[f"SMA{f}x{s}"] = (xup(a, b), xdn(a, b))
    for n in (20, 50, 100, 200):
        e = ema(c, n); R[f"C>EMA{n}"] = (xup(c, e), xdn(c, e))
    for n in (10, 20, 40, 55, 100):
        H, L = sh(hh(h, n)), sh(ll(l, n)); R[f"DON{n}"] = (xup(c, H), xdn(c, L))
    for n in (7, 14):
        r = rsi(c, n)
        for lv in (20, 30):
            R[f"RSI{n}rev{lv}"] = (xup(r, np.full_like(r, lv)), xdn(r, np.full_like(r, 100 - lv)))
    for n in (7, 14, 21):
        r = rsi(c, n)
        R[f"RSI{n}x50"] = (xup(r, np.full_like(r, 50)), xdn(r, np.full_like(r, 50)))
        R[f"RSI{n}x60"] = (xup(r, np.full_like(r, 60)), xdn(r, np.full_like(r, 40)))
    for n, k in ((20, 2.0), (20, 2.5), (50, 2.0)):
        m = sma(c, n); sd = pd.Series(c).rolling(n).std(ddof=0).to_numpy(); U, Lo = m + k * sd, m - k * sd
        R[f"BB{n}_{k}brk"] = (xup(c, U), xdn(c, Lo))
        R[f"BB{n}_{k}rev"] = (xup(c, Lo), xdn(c, U))
    for f, s, g in ((12, 26, 9), (8, 21, 5), (5, 35, 5)):
        mc = ema(c, f) - ema(c, s); sg = ema(mc, g); z = np.zeros_like(mc)
        R[f"MACD{f}_{s}_{g}sig"] = (xup(mc, sg), xdn(mc, sg))
        R[f"MACD{f}_{s}zero"] = (xup(mc, z), xdn(mc, z))
    for n in (14, 5):
        k_ = 100 * (c - ll(l, n)) / (hh(h, n) - ll(l, n)); k_ = sma(k_, 3); d_ = sma(k_, 3)
        for lo in (20, 30):
            R[f"STO{n}_{lo}"] = (xup(k_, d_) & (sh(k_) < lo), xdn(k_, d_) & (sh(k_) > 100 - lo))
    for n in (14, 20):
        tp = (h + l + c) / 3; m = sma(tp, n)
        md = pd.Series(tp).rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True).to_numpy()
        cci = (tp - m) / (0.015 * md)
        R[f"CCI{n}rev"] = (xup(cci, np.full_like(cci, -100)), xdn(cci, np.full_like(cci, 100)))
        R[f"CCI{n}mom"] = (xup(cci, np.full_like(cci, 100)), xdn(cci, np.full_like(cci, -100)))
    for n, m_ in ((10, 2.0), (10, 3.0), (14, 4.0), (20, 3.0)):
        d = supertrend_dir(h, l, c, atr(h, l, c, n), m_)
        R[f"ST{n}_{m_}"] = ((d > 0) & (sh(d) < 0), (d < 0) & (sh(d) > 0))
    for k in (1.5, 2.0):
        m = ema(c, 20); a = atr(h, l, c, 10); R[f"KC{k}brk"] = (xup(c, m + k * a), xdn(c, m - k * a))
    for n in (5, 10, 20):
        roc = c / sh(c, n) - 1; z = np.zeros_like(roc); R[f"ROC{n}"] = (xup(roc, z), xdn(roc, z))
    body = c - o; pb = sh(body)
    R["ENGULF"] = ((body > 0) & (pb < 0) & (c > sh(o)) & (o < sh(c)), (body < 0) & (pb > 0) & (c < sh(o)) & (o > sh(c)))
    R["THREE"] = ((body > 0) & (pb > 0) & (sh(body, 2) > 0) & ~(sh(body, 3) > 0),
                  (body < 0) & (pb < 0) & (sh(body, 2) < 0) & ~(sh(body, 3) < 0))
    ins = (sh(h) < sh(h, 2)) & (sh(l) > sh(l, 2))
    R["INSIDE"] = (ins & (c > sh(h)), ins & (c < sh(l)))
    rng = h - l; lw = np.minimum(o, c) - l; uw = h - np.maximum(o, c)
    R["PIN"] = ((lw >= 2 * np.abs(body)) & (lw >= 0.6 * rng) & (l <= ll(l, 20)),
                (uw >= 2 * np.abs(body)) & (uw >= 0.6 * rng) & (h >= hh(h, 20)))
    hc = (o + h + l + c) / 4; ho = np.empty_like(c); ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(c)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    hb = hc - ho; R["HA"] = ((hb > 0) & (sh(hb) <= 0), (hb < 0) & (sh(hb) >= 0))
    pdi, mdi, ax = adx(h, l, c, 14)
    for lv in (20, 25):
        R[f"DI_adx{lv}"] = (xup(pdi, mdi) & (ax > lv), xdn(pdi, mdi) & (ax > lv))
    wr = -100 * (hh(h, 14) - c) / (hh(h, 14) - ll(l, 14))
    R["WR14"] = (xup(wr, np.full_like(wr, -80)), xdn(wr, np.full_like(wr, -20)))
    tk = (hh(h, 9) + ll(l, 9)) / 2; kj = (hh(h, 26) + ll(l, 26)) / 2; R["TKX"] = (xup(tk, kj), xdn(tk, kj))
    au = 100 * pd.Series(h).rolling(26).apply(np.argmax, raw=True).to_numpy() / 25
    ad = 100 * pd.Series(l).rolling(26).apply(np.argmin, raw=True).to_numpy() / 25
    R["AROON25"] = (xup(au, ad), xdn(au, ad))
    d = psar_dir(h, l, 0.02, 0.2); R["PSAR"] = ((d > 0) & (sh(d) < 0), (d < 0) & (sh(d) > 0))
    for n in (20, 50):
        z = (c - sma(c, n)) / pd.Series(c).rolling(n).std(ddof=0).to_numpy()
        R[f"Z{n}rev"] = (xup(z, np.full_like(z, -2.0)), xdn(z, np.full_like(z, 2.0)))
    return R


def filters(df, ct, f4):
    """{name: (long_ok, short_ok)}."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    e200 = ema(c, 200); _, _, ax = adx(h, l, c, 14)
    ap = atr(h, l, c, 14) / c; med = pd.Series(ap).rolling(200).median().to_numpy()
    ix = np.searchsorted(f4["ct"], ct, side="right") - 1
    ok4 = ix >= 1
    up4 = np.where(ok4, f4["up"][np.maximum(ix, 0)], False)
    dn4 = np.where(ok4, f4["dn"][np.maximum(ix, 0)], False)
    t = np.ones(len(c), bool)
    return {"": (t, t), "+추세200": (c > e200, c < e200), "+ADX20": (ax > 20, ax > 20), "+조용": (ap < med, ap < med),
            "+4h추세": (up4, dn4)}


# ------------------------------------------------------------------ generated signals
SIG = {}          # cell -> list of (t, coin, side)
for ci, cn in enumerate(COINS):
    b4 = bars(cn, "4h"); c4 = b4.close.to_numpy(float); e4 = ema(c4, 50)
    f4 = {"ct": b4.ts.to_numpy(np.int64) + 240 * MIN, "up": e4 > sh(e4), "dn": e4 < sh(e4)}
    for tf in TFS:
        df = bars(cn, tf)
        ct = df.ts.to_numpy(np.int64) + TF_MIN[tf] * MIN
        keep = (ct >= P_LO) & (ct < FWD_B) & (np.arange(len(ct)) >= 300) & FC.wk(ct)
        R = rules(df); F = filters(df, ct, f4)
        for rn, (le, se) in R.items():
            for fn, (lo, so) in F.items():
                L_ = np.nan_to_num(le).astype(bool) & lo & keep; S_ = np.nan_to_num(se).astype(bool) & so & keep
                key = f"{rn}{fn} {tf}"
                tl, ts_ = ct[L_], ct[S_]
                SIG.setdefault(key, []).append((np.r_[tl, ts_], np.full(len(tl) + len(ts_), ci),
                                                np.r_[np.ones(len(tl)), -np.ones(len(ts_))]))
    log("generated", cn, len(SIG))
CELLS = {}
for k, parts in SIG.items():
    t = np.concatenate([p[0] for p in parts]).astype(np.int64); cc = np.concatenate([p[1] for p in parts]).astype(np.int64)
    sd = np.concatenate([p[2] for p in parts]).astype(np.int64)
    o_ = np.lexsort((cc, t)); CELLS[k] = ("생성", t[o_], cc[o_], sd[o_])
del SIG
# ------------------------------------------------------------------ the 121 coded strategies
KO = {k: v["name_ko"] for k, v in json.load(open("/home/user/crypto-bot-research/research/newlive/classify.json")).items()}
SETN = {"core": "규칙봇", "ds": "딥시크", "lib": "라이브러리", "friend": "친구분"}
S = RD.signals(period=(P_LO, FWD_B))
S = S[FC.wk(S.t.to_numpy(np.int64))].reset_index(drop=True)
for (nm, tf, st), g in S.groupby(["name", "tf", "set"]):
    t = g.t.to_numpy(np.int64); cc = g.coin.to_numpy(np.int64); sd = g.side.to_numpy(np.int64)
    o_ = np.lexsort((cc, t)); CELLS[f"{KO.get(nm, nm)} {tf}"] = (SETN.get(st, st), t[o_], cc[o_], sd[o_])
log("cells", len(CELLS), "generated", sum(v[0] == "생성" for v in CELLS.values()))


def sim(t, cc, sd, stop, cost=0.0014):
    if not len(t):
        return None
    cst = D.off[cc] + ((t - GT0) // MIN); csend = D.off[cc + 1]
    ti, w, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, sd, t, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.10, cost, HB.MARGIN)
    return t[ti], w


def oct_read(t2, w):
    fw = (t2 >= FWD_A) & (t2 < FWD_B)
    return round(float(np.prod(1 + w[fw])), 3), int(fw.sum()), (round(float((w[fw] > 0).mean()), 2) if fw.any() else None)


ROWS, STREAM = [], {}
for i, (k, (st, t, cc, sd)) in enumerate(CELLS.items()):
    for dn, sel in (("양방향", None), ("롱만", 1), ("숏만", -1)):
        m = np.ones(len(t), bool) if sel is None else sd == sel
        if m.sum() < 50:
            continue
        for stop in (0.25, 0.35):
            r = sim(t[m], cc[m], sd[m], stop)
            if r is None:
                continue
            t2, w = r
            if stop == 0.35:
                STREAM[(k, dn)] = (t2, w)
            o20, on, owr = oct_read(t2, w)
            row = {"매매법": k, "세트": st, "방향": dn, "손절": f"-{int(stop * 100)}%", "10월 20일": o20, "10월 거래": on, "10월 승률": owr}
            q = (t2 >= ms("2026-07-01") - 9 * 3600_000) & (t2 < ms("2026-10-01") - 9 * 3600_000)
            row["7~9월 거래"] = int(q.sum())
            for lab, a, b in (("최근 3달 (7~9월)", 202607, 202609), ("2026 1~9월", 202601, 202609), ("2025~26", 202501, 202609), ("2021~24", 202106, 202412)):
                rr = FC.read(t2, w, a, b); row[lab] = rr["기하평균"]
                if lab == "최근 3달 (7~9월)":
                    e, _, _ = FC.month_ends(t2, w, a, b); row["7·8·9월"] = [round(float(x), 2) for x in e]
                if lab == "2025~26":
                    row["2025~26 ×2+ 달"] = rr["x2+"]; row["2025~26 ×3+ 달"] = rr["x3+"]; row["2025~26 -50% 달"] = rr["-50%"]
            ROWS.append(row)
    if i % 200 == 0:
        log("cell", i, "/", len(CELLS), "rows", len(ROWS))
R = pd.DataFrame(ROWS)
R.to_csv(os.path.join(OUTD, "gen56_cells.csv.gz"), index=False)
log("cells done", len(R), "variants", len(STREAM))

OUT = {"읽는 법": __doc__, "칸 수": {"전체 매매법·봉": len(CELLS), "생성": int(sum(v[0] == '생성' for v in CELLS.values())),
                                 "변형(방향·손절)": len(R)}}
# ------------------------------------------------------------------ P1: pick by Jul..Sep, read October (unseen)
P1 = {}
for stop in ("-25%", "-35%"):
    sub = R[(R["손절"] == stop) & (R["7~9월 거래"] >= 15)]
    allmed = float(sub["10월 20일"].median())
    for n in (10, 20, 50):
        top = sub.sort_values("최근 3달 (7~9월)", ascending=False).head(n)
        P1[f"손절 {stop} / 7~9월 상위 {n}"] = {"7~9월 달 평균(중간값)": round(float(top["최근 3달 (7~9월)"].median()), 3),
                                          "10월 20일 중간값": round(float(top["10월 20일"].median()), 3),
                                          "10월 ×1 이상 비율": round(float((top["10월 20일"] >= 1).mean()), 2),
                                          "10월 ×2 이상 수": int((top["10월 20일"] >= 2).sum()),
                                          "전체 변형의 10월 중간값": round(allmed, 3)}
    P1[f"손절 {stop} / 7~9월 상위 20 목록"] = json.loads(sub.sort_values("최근 3달 (7~9월)", ascending=False).head(20).to_json(orient="records", force_ascii=False))
OUT["P1 지금 장(7~9월)으로 고르고 10월에 확인"] = P1
log("P1", {k: v for k, v in P1.items() if "목록" not in k})
# ------------------------------------------------------------------ P2: combos of the Jul..Sep leaders
P2 = {}
for stop in (0.25, 0.35):
    sub = R[(R["손절"] == f"-{int(stop * 100)}%") & (R["7~9월 거래"] >= 15)].sort_values("최근 3달 (7~9월)", ascending=False)
    sub = sub.drop_duplicates("매매법")
    for n in (3, 5, 8, 12):
        top = sub.head(n); parts = []
        for _, rw in top.iterrows():
            st, t, cc, sd = CELLS[rw["매매법"]]
            m = np.ones(len(t), bool) if rw["방향"] == "양방향" else sd == (1 if rw["방향"] == "롱만" else -1)
            parts.append((t[m], cc[m], sd[m]))
        t = np.concatenate([p[0] for p in parts]); cc = np.concatenate([p[1] for p in parts]); sd = np.concatenate([p[2] for p in parts])
        o_ = np.lexsort((cc, t)); t, cc, sd = t[o_], cc[o_], sd[o_]
        for cost in (0.0014, 0.0008):
            t2, w = sim(t, cc, sd, stop, cost)
            o20, on, owr = oct_read(t2, w)
            e, _, _ = FC.month_ends(t2, w, 202607, 202609)
            P2[f"7~9월 상위 {n}개 한 봇 / 손절 -{int(stop * 100)}% / 비용 {cost * 100:.2f}%"] = {
                "구성": [f"{rw['매매법']} {rw['방향']}" for _, rw in top.iterrows()], "7·8·9월": [round(float(x), 2) for x in e],
                "10월 20일 (안 보고 고름)": o20, "10월 거래": on, "10월 승률": owr,
                "2025~26 달 평균": FC.read(t2, w, 202501, 202609)["기하평균"], "2021~24 달 평균": FC.read(t2, w, 202106, 202412)["기하평균"]}
            log("P2", n, stop, cost, P2[list(P2)[-1]]["7·8·9월"], o20)
OUT["P2 지금 장 상위 조합 (한 봇)"] = P2
# ------------------------------------------------------------------ P3: follow the current market (rolling re-pick)
keys = list(STREAM)
CUM = {k: (STREAM[k][0], np.r_[0.0, np.cumsum(np.log(np.maximum(1 + STREAM[k][1], 1e-6)))]) for k in keys}
blocks = np.arange(ms("2022-01-03"), FWD_B, 10 * DAY)


def score(k, a, b):
    t2, cum = CUM[k]
    i, j = np.searchsorted(t2, a), np.searchsorted(t2, b)
    return cum[j] - cum[i], j - i


def follow(W, K, rnd=None, min_n=5):
    TT, CC, SS, PR = [], [], [], []
    rng = np.random.default_rng(rnd) if rnd is not None else None
    for s0 in blocks:
        if rng is None:
            sc = []
            for k in keys:
                v, n = score(k, s0 - W * DAY, s0)
                if n >= min_n:
                    sc.append((v, k))
            sc.sort(reverse=True); pick = [k for _, k in sc[:K]]
        else:
            pick = [keys[i] for i in rng.choice(len(keys), K, replace=False)]
        for r_, (k, dn) in enumerate(pick):
            st, t, cc, sd = CELLS[k]
            m = (t >= s0) & (t < s0 + 10 * DAY)
            if dn != "양방향":
                m &= sd == (1 if dn == "롱만" else -1)
            TT.append(t[m]); CC.append(cc[m]); SS.append(sd[m]); PR.append(np.full(m.sum(), -r_))
    t = np.concatenate(TT); cc = np.concatenate(CC); sd = np.concatenate(SS); pr = np.concatenate(PR)
    o_ = np.lexsort((pr, cc, t)); t, cc, sd = t[o_], cc[o_], sd[o_]
    return sim(t, cc, sd, 0.35)


P3 = {}
for W in (10, 20, 30, 60):
    for K in (1, 3, 5, 10):
        t2, w = follow(W, K)
        e, cnt, bust = FC.month_ends(t2, w, 202201, 202609)
        o20, on, owr = oct_read(t2, w)
        P3[f"지난 {W}일 상위 {K}개를 다음 10일 거래"] = {
            "달 평균(기하)": round(float(np.exp(np.mean(np.log(e)))), 3), "달 중간값": round(float(np.median(e)), 3),
            "×2 이상 달": int((e >= 2).sum()), "×3 이상 달": int((e >= 3).sum()), "반 넘게 잃은 달": int(bust), "달 수": len(e),
            "2025~26 달 평균": FC.read(t2, w, 202501, 202609)["기하평균"], "10월 20일": o20, "10월 거래": on}
        log("P3", W, K, P3[list(P3)[-1]])
RC = []
for K in (1, 3, 5, 10):
    vals = []
    for seed in range(20):
        t2, w = follow(20, K, rnd=1000 + seed)
        e, _, _ = FC.month_ends(t2, w, 202201, 202609); vals.append((float(np.exp(np.mean(np.log(e)))), int((e >= 2).sum()), int((e >= 3).sum())))
    v = np.array(vals)
    RC.append({"K": K, "무작위 달 평균(20번 중간값)": round(float(np.median(v[:, 0])), 3), "×2 이상 달(중간값)": float(np.median(v[:, 1])),
               "×3 이상 달(중간값)": float(np.median(v[:, 2]))})
    log("P3 random", RC[-1])
OUT["P3 지금 장 따라가기 봇 (2022-01 ~ 2026-09, 10일마다 다시 고름)"] = P3
OUT["P3 비교: 무작위로 고른 K개"] = RC
# ------------------------------------------------------------------ P4: October leaders (cannot be checked yet)
OUT["P4 10월 20일 상위 30 (확인 불가)"] = json.loads(R[R["10월 거래"] >= 8].sort_values("10월 20일", ascending=False).head(30).to_json(orient="records", force_ascii=False))
json.dump(OUT, open(os.path.join(OUTD, "gen56.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
