"""PREREG8.md: every entry label x every trend judge (the other labels' latest signal, the trend bot's judges, 12
indicators on 1h / 4h / 1d of the coin and of BTC) x the 24 exits of round 3. A signal is taken only when the judge
points the signal's way. Select on 2020-03 .. 2024-12 (two halves), finalists frozen (json + sha256), confirm once.

    python3 -I vwgate.py check              kernel vs vwacct.trades on 200 random cells
    python3 -I vwgate.py scan [--procs 3]   select-period grid -> OUT8/scan/{label}.npz (+ OUT8/states.npz)
    python3 -I vwgate.py select             -> OUT8/select8.json, research/vwap30/finalists8.json (+ sha256)
    python3 -I vwgate.py confirm            -> research/vwap30/results8.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwcommon import *
from vwcommon import _GRID
from vwacct import metrics, weekdays
from vwbuild3 import OUT3, EXITS3, exit3_name, SIG
from vwstages3 import One, Label, merge, wd_mask, greedy, rnd
from vwfriend import rsi
from vwconfirm import pick
import glob, hashlib, numba
from multiprocessing import Pool

OUT8 = OUT + "_r8"
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))
MID = ms("2022-07-01")
SEED8 = 20261031
TWIN_Q = 100 * (1 - 0.10 / 8)                                    # 98.75: 10 % shared by the 8 finalists
MIN_WD, MIN_N, MIN_N_POOL, POOL = 3.0, 300, 100, 300
VWAP30 = "F6_VWAP_FAIL_at_30m"
LABELS = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(OUT3, "*.npz")))
AGES = {"7d": 7 * DAY, "24h": DAY}
JTF, JNM = ("1h", "4h"), ("V39", "S6", "OBV", "N12", "raw3")
ITF = {"1h": 60, "4h": 240, "1d": 1440}
IND = ("OBV", "RSI26", "MOM10", "FRIEND3", "EMA21_52", "EMA50", "EMA200", "MACD", "ST10_3", "DMI", "DON20", "ICHI")
GATES = ([f"L|{lab}|{a}" for lab in LABELS for a in AGES] + [f"J|{t}|{n}" for t in JTF for n in JNM]
         + [f"I|{w}|{t}|{i}" for w in ("own", "BTC") for t in ITF for i in IND])
YR_A = (MID - SEL[0]) / DAY / 365.25
YR_B = (SEL[1] - MID) / DAY / 365.25
IND_KO = {"OBV": "OBV > EMA20", "RSI26": "RSI26 > 50", "MOM10": "MOM10 > 0", "FRIEND3": "친구 3종(OBV·RSI26·MOM)",
          "EMA21_52": "EMA21 > EMA52", "EMA50": "종가 > EMA50", "EMA200": "종가 > EMA200", "MACD": "MACD > 신호선",
          "ST10_3": "슈퍼트렌드(10,3)", "DMI": "DMI(ADX≥20)", "DON20": "돈치안20 중간선", "ICHI": "일목 구름"}
J_KO = {"V39": "V3.9", "S6": "EMA·DMI·ADX", "OBV": "OBV 추세형", "N12": "일목·AO", "raw3": "4개 중 3개 이상"}
TF_KO = {"30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}


_KO = {}


def label_ko(lab):
    """Korean name of a label (research/fullgrid/diag/strat_md.py: DS names and the 36's profile names)."""
    if not _KO:
        sys.path.insert(0, os.path.join(REPO, "research", "fullgrid", "diag"))
        import strat_md
        _KO.update(strat_md.DS_KO)
        _KO.update(strat_md.core_names())
    base, tf = lab.split("_at_")
    tf, var = (tf.split("__") + [""])[:2]
    return f"{_KO.get(base, base)} {TF_KO.get(tf, tf)}" + (f"({var})" if var else "")


def gate_ko(g):
    if g == "none":
        return "판단 없음"
    if g.startswith("P|"):
        a, b = g[2:].split("&")
        return f"{gate_ko(a)} + {gate_ko(b)}"
    p = g.split("|")
    if p[0] == "L":
        return f"{label_ko(p[1])} 최근 신호({'7일' if p[2] == '7d' else '24시간'} 안)"
    if p[0] == "J":
        return f"추세봇 {J_KO[p[2]]} {TF_KO[p[1]]}"
    return f"{'BTC ' if p[1] == 'BTC' else ''}{TF_KO[p[2]]} {IND_KO[p[3]]}"


# ---------------------------------------------------------------- indicator states on closed 1h / 4h / 1d bars

@numba.njit(cache=True)
def _supertrend(h, l, c, atr, mult):
    n = len(c)
    d = np.zeros(n)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    for i in range(n):
        if not np.isfinite(atr[i]) or not np.isfinite(c[i]):
            continue
        m = (h[i] + l[i]) / 2
        bu, bd = m - mult * atr[i], m + mult * atr[i]
        if i > 0 and np.isfinite(up[i - 1]):
            up[i] = max(bu, up[i - 1]) if c[i - 1] > up[i - 1] else bu
            dn[i] = min(bd, dn[i - 1]) if c[i - 1] < dn[i - 1] else bd
            if d[i - 1] < 0 and c[i] > dn[i - 1]:
                d[i] = 1
            elif d[i - 1] > 0 and c[i] < up[i - 1]:
                d[i] = -1
            else:
                d[i] = d[i - 1] if d[i - 1] != 0 else 1
        else:
            up[i], dn[i], d[i] = bu, bd, 1
    return d


def ind_states(df):
    """{indicator: +1 / -1 / 0 per bar} on closed bars."""
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    sg = lambda x: np.nan_to_num(np.sign(x))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr14, atr10 = wilder(tr, 14), wilder(tr, 10)
    obv = np.cumsum(np.sign(np.diff(c, prepend=c[0])) * np.nan_to_num(v))
    s = {"OBV": sg(obv - ema(obv, 20)), "RSI26": sg(rsi(c, 26) - 50),
         "MOM10": sg(c - np.r_[np.full(10, np.nan), c[:-10]])}
    s["FRIEND3"] = np.where((s["OBV"] == s["RSI26"]) & (s["RSI26"] == s["MOM10"]), s["OBV"], 0.0)
    s["EMA21_52"] = sg(ema(c, 21) - ema(c, 52))
    s["EMA50"] = sg(c - ema(c, 50))
    s["EMA200"] = sg(c - ema(c, 200))
    macd = ema(c, 12) - ema(c, 26)
    s["MACD"] = sg(macd - ema(macd, 9))
    s["ST10_3"] = _supertrend(h, l, c, atr10, 3.0)
    up, dn = h - np.r_[h[0], h[:-1]], np.r_[l[0], l[:-1]] - l
    with np.errstate(all="ignore"):
        pdi = 100 * wilder(np.where((up > dn) & (up > 0), up, 0.0), 14) / atr14
        mdi = 100 * wilder(np.where((dn > up) & (dn > 0), dn, 0.0), 14) / atr14
        adx = wilder(np.nan_to_num(100 * np.abs(pdi - mdi) / (pdi + mdi)), 14)
    s["DMI"] = np.where(adx >= 20, sg(pdi - mdi), 0.0)
    roll = lambda x, n, f: getattr(pd.Series(x).rolling(n), f)().to_numpy()
    s["DON20"] = sg(c - (roll(h, 20, "max") + roll(l, 20, "min")) / 2)
    ten = (roll(h, 9, "max") + roll(l, 9, "min")) / 2
    kij = (roll(h, 26, "max") + roll(l, 26, "min")) / 2
    sa = np.r_[np.full(26, np.nan), ((ten + kij) / 2)[:-26]]
    sb = np.r_[np.full(26, np.nan), ((roll(h, 52, "max") + roll(l, 52, "min")) / 2)[:-26]]
    with np.errstate(invalid="ignore"):
        s["ICHI"] = np.where(c > np.fmax(sa, sb), 1.0, np.where(c < np.fmin(sa, sb), -1.0, 0.0))
    for k in s:
        s[k] = s[k].astype(np.int8)
        s[k][:200] = 0
    return s


def build_states():
    """OUT8/states.npz: per coin and timeframe the bar close times and the 12 indicator states."""
    fp = os.path.join(OUT8, "states.npz")
    if os.path.exists(fp):
        return dict(np.load(fp))
    TF_MIN["1d"] = 1440
    D = {}
    for coin in COINS:
        for tf, k in ITF.items():
            df = bars(coin, tf)
            D[f"{coin}|{tf}|tclose"] = df.ts.to_numpy(np.int64) + k * MIN
            for nm, x in ind_states(df).items():
                D[f"{coin}|{tf}|{nm}"] = x
        _GRID.clear()
        print("states", coin, flush=True)
    np.savez(fp, **D)
    return D


def at(tclose, vals, t, k_ms):
    """The value of the last bar closed at or before t (0 when that bar is older than two bars)."""
    j = np.searchsorted(tclose, t, side="right") - 1
    ok = (j >= 0) & (t - tclose[np.maximum(j, 0)] < 2 * k_ms)
    return np.where(ok, vals[np.maximum(j, 0)], 0).astype(np.int8)


_ST, _SIGS, _JUDGE = {}, {}, {}


def load_ctx():
    _ST.update(build_states())
    for lab in LABELS:
        Z = np.load(os.path.join(SIG, f"{lab}.npz"))
        t, s, c = Z["t"].astype(np.int64), Z["side"].astype(np.int8), Z["coin"].astype(np.int64)
        for ci in range(len(COINS)):
            m = c == ci
            o = np.argsort(t[m], kind="stable")
            _SIGS[(lab, ci)] = (t[m][o], s[m][o])
    for coin in COINS:
        Z = np.load(os.path.join(JUDGE_DIR, f"{coin}.npz"))
        _JUDGE[coin] = {k: Z[k] for k in Z.files if k.split("_")[0] in JTF}


def gate_states(t, coin):
    """(len(GATES), n) int8: each judge's direction at the signal times t (sorted by nothing in particular)."""
    n = len(t)
    G = np.zeros((len(GATES), n), np.int8)
    for ci, cname in enumerate(COINS):
        m = coin == ci
        if not m.any():
            continue
        tt = t[m]
        for q, g in enumerate(GATES):
            p = g.split("|")
            if p[0] == "L":
                ts, ss = _SIGS[(p[1], ci)]
                if not len(ts):
                    continue
                j = np.searchsorted(ts, tt, side="right") - 1
                ok = (j >= 0) & (tt - ts[np.maximum(j, 0)] <= AGES[p[2]])
                G[q, m] = np.where(ok, ss[np.maximum(j, 0)], 0)
            elif p[0] == "J":
                Z = _JUDGE[cname]
                G[q, m] = at(Z[f"{p[1]}_tclose"], Z[f"{p[1]}_{p[2]}"], tt, TF_MIN[p[1]] * MIN)
            else:
                who = cname if p[1] == "own" else "BTCUSDT"
                G[q, m] = at(_ST[f"{who}|{p[2]}|tclose"], _ST[f"{who}|{p[2]}|{p[3]}"], tt, ITF[p[2]] * MIN)
    return G


# ---------------------------------------------------------------- the select-period grid

@numba.njit(cache=True)
def _scan(entry, ext, net, D, use, side, G, mid):
    """For each judge row of G (and one 'no judge' row at the end) and each exit: the one-position pass over the used
    signals; per half (A before mid, B after): trades, sum of R, sum of log growth at risk 2 %."""
    ng, n = G.shape
    J = ext.shape[1]
    out = np.zeros((ng + 1, J, 6))
    for g in range(ng + 1):
        for j in range(J):
            free = -1
            for i in range(n):
                if not use[i] or entry[i] < free:
                    continue
                if g < ng and G[g, i] != side[i]:
                    continue
                free = ext[i, j]
                x = min(0.02 / D[i, j], 50.0) * net[i, j]
                h = 0 if entry[i] < mid else 1
                out[g, j, h] += 1.0
                out[g, j, 2 + h] += net[i, j] / D[i, j]
                out[g, j, 4 + h] += np.log1p(max(x, -1 + 1e-12))
    return out


class Trig:
    """A trigger label in (entry, coin) order with its 24 exits and the judges at its signal times."""

    def __init__(self, lab):
        L = Label(lab)
        Z = np.load(os.path.join(OUT3, f"{lab}.npz"))
        o = np.lexsort((L.coin, L.entry))
        self.lab = lab
        self.entry, self.coin, self.side = L.entry[o], L.coin[o], Z["side"].astype(np.int8)[o]
        self.L, self.o = L, o
        self.ext = self.entry[:, None] + (L.tx[o].astype(np.int64) + 1) * MIN
        self.net = L.ret[o].astype(float)
        self.D = np.stack([L.D(j)[o] for j in range(len(EXITS3))], 1)
        kst = pd.to_datetime(self.entry + KST, unit="ms")
        self.wd = np.asarray(kst.dayofweek < 5)

    def gates(self):
        return gate_states(self.entry, self.coin)

    def scan(self, G):
        use = self.wd & (self.entry >= SEL[0]) & (self.entry < SEL[1])
        return _scan(self.entry, self.ext, self.net, self.D, use, self.side, np.ascontiguousarray(G), MID)

    def one(self, gate_row, j):
        """A One of the signals the judge lets through, exit j (gate_row None = every signal)."""
        k = np.ones(len(self.entry), bool) if gate_row is None else gate_row == self.side
        L, o = self.L, self.o
        return One(self.entry[k], self.coin[k], L.ret[o][k, j], L.tx[o][k, j], L.ret_o[o][k, j], L.tx_o[o][k, j],
                   self.D[k, j], np.zeros(k.sum()), np.full(k.sum(), self.lab, object))


def scan_job(lab):
    t0 = time.time()
    fp = os.path.join(OUT8, "scan", f"{lab}.npz")
    if os.path.exists(fp):
        return lab, 0.0
    T = Trig(lab)
    G = T.gates()
    out = T.scan(G)
    np.savez(fp, out=out.astype(np.float32), n_sig=len(T.entry))
    return lab, round(time.time() - t0, 1)


def scan(procs):
    os.makedirs(os.path.join(OUT8, "scan"), exist_ok=True)
    load_ctx()
    _GRID.clear()
    with Pool(procs) as pool:
        for lab, sec in pool.imap_unordered(scan_job, LABELS):
            print("scan", lab, sec, flush=True)


def check(k=40, seed=7):
    """Loop check: the grid kernel against vwacct.trades / metrics on random (trigger, judge, exit) cells."""
    from vwacct import trades
    load_ctx()
    rng = np.random.default_rng(seed)
    bad = 0
    for lab in rng.choice(LABELS, 4, replace=False).tolist() + [VWAP30]:
        T = Trig(lab)
        G = T.gates()
        out = T.scan(G)
        for _ in range(k):
            g = int(rng.integers(0, len(GATES) + 1))
            j = int(rng.integers(0, len(EXITS3)))
            o = T.one(None if g == len(GATES) else G[g], j)
            m = wd_mask(o) & (o.entry >= SEL[0]) & (o.entry < SEL[1])
            idx, net, ext, D = trades(o, m, 0)
            x = np.minimum(0.02 / D, 50.0) * net
            lg = np.log1p(np.maximum(x, -1 + 1e-12))
            a = o.entry[idx] < MID
            want = np.array([a.sum(), (~a).sum(), (net / D)[a].sum(), (net / D)[~a].sum(), lg[a].sum(), lg[~a].sum()])
            got = out[g, j].astype(float)
            if not np.allclose(want, got, rtol=1e-6, atol=1e-6):
                bad += 1
                print("BAD", lab, g, j, want, got)
            if g < len(GATES) and _ > k - 3:
                x2 = metrics(o, wd_mask(o), 0, "select", full=False)
                assert abs(x2["growth"] - got[4] - got[5]) < 1e-6 and x2["n"] == got[0] + got[1]
        print("checked", lab, len(T.entry), "signals", flush=True)
    print("check cells", 5 * k, "bad", bad)


# ---------------------------------------------------------------- selection

def table(out, gates, lab):
    """Rows of one trigger's grid (gate x exit) with the selection numbers."""
    nA, nB, rA, rB, gA, gB = (out[:, :, q].astype(float) for q in range(6))
    n = nA + nB
    wd = weekdays(*SEL)
    with np.errstate(all="ignore"):
        R_A, R_B = rA / nA, rB / nB
    score = np.minimum(gA / YR_A, gB / YR_B)
    rows = []
    for g in range(len(gates)):
        if gates[g].startswith("L|") and gates[g].split("|")[1] == lab:
            continue
        for j in range(out.shape[1]):
            rows.append((lab, gates[g], j, int(n[g, j]), n[g, j] / wd, R_A[g, j], R_B[g, j], (rA[g, j] + rB[g, j]) / max(n[g, j], 1),
                         gA[g, j] + gB[g, j], score[g, j]))
    return rows


COLS = ("trigger", "gate", "exit", "n", "per_weekday", "R_A", "R_B", "avgR", "growth", "score")


def family(lab):
    return lab.split("_at_")[0]


def select():
    load_ctx()
    allrows = []
    for lab in LABELS:
        Z = np.load(os.path.join(OUT8, "scan", f"{lab}.npz"))
        allrows += table(Z["out"], GATES + ["none"], lab)
    # (라) VWAP 30m: pairs of its top 20 single judges
    df = pd.DataFrame(allrows, columns=COLS)
    vw = df[(df.trigger == VWAP30) & (df.gate != "none")]
    top = vw.groupby("gate").score.max().sort_values(ascending=False).index[:20].tolist()
    T = Trig(VWAP30)
    G = T.gates()
    gi = {g: i for i, g in enumerate(GATES)}
    pairs = [(a, b) for x, a in enumerate(top) for b in top[x + 1:]]
    PG = np.array([np.where(G[gi[a]] == G[gi[b]], G[gi[a]], 0) for a, b in pairs], np.int8)
    pout = T.scan(PG)[:-1]
    pnames = [f"P|{a}&{b}" for a, b in pairs]
    df = pd.concat([df, pd.DataFrame(table(pout, pnames, VWAP30), columns=COLS)], ignore_index=True)
    print("rows", len(df), flush=True)
    ok = (df.per_weekday >= MIN_WD) & (df.n >= MIN_N) & (df.R_A > 0) & (df.R_B > 0)
    el = df[ok].sort_values("score", ascending=False)
    fin, fams = [], set()
    for r in el.itertuples():
        if family(r.trigger) in fams:
            continue
        fams.add(family(r.trigger))
        fin.append({"name": f"순위 {len(fin) + 1}", "trigger": r.trigger, "gate": r.gate, "exit": int(r.exit)})
        if len(fin) == 5:
            break

    def named(name, gate):
        x = df[(df.trigger == VWAP30) & (df.gate == gate)]
        xo = x[(x.per_weekday >= MIN_WD) & (x.n >= MIN_N) & (x.R_A > 0) & (x.R_B > 0)]
        r = xo.sort_values("score").iloc[-1] if len(xo) else x.sort_values("growth").iloc[-1]
        return {"name": name + ("" if len(xo) else " (자격 미달, 고르기 성장 1등 청산)"), "trigger": VWAP30, "gate": gate,
                "exit": int(r.exit)}
    fin.append(named("두 분 예시", "J|1h|OBV"))
    fin.append(named("친구 판단", "I|own|1h|FRIEND3"))
    # 묶음: best exit per (trigger, gate), n >= 100, both halves positive, top 300 by score
    pool = df[(df.n >= MIN_N_POOL) & (df.R_A > 0) & (df.R_B > 0)].sort_values("score", ascending=False)
    pool = pool.drop_duplicates(["trigger", "gate"]).head(POOL)
    cands = {}
    trig = {}
    for r in pool.itertuples():
        if r.trigger not in trig:
            trig[r.trigger] = (Trig(r.trigger), None)
        Tr = trig[r.trigger][0]
        if trig[r.trigger][1] is None:
            trig[r.trigger] = (Tr, Tr.gates())
        row = gate_row(Tr, trig[r.trigger][1], r.gate, gi)
        o = Tr.one(row, int(r.exit))
        o.member = np.full(len(o.entry), f"{r.trigger}~{r.gate}~{int(r.exit)}", object)
        cands[f"{r.trigger}~{r.gate}~{int(r.exit)}"] = o
    chosen, cur, steps = greedy(cands, [], cands, max_total=24)
    fin.append({"name": "묶음", "members": [{"trigger": c.split("~")[0], "gate": c.split("~")[1], "exit": int(c.split("~")[2])}
                                           for c in chosen]})
    fp = os.path.join(RES_DIR, "finalists8.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin, "vwap_top20": top},
              open(fp, "w"), ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists8.json\n")
    for f in fin:
        print("finalist", f, flush=True)
    # 참고 reads (select only)
    ref = {"rows": int(len(df)), "eligible": int(ok.sum()),
           "both_halves_positive_n300": int(((df.n >= MIN_N) & (df.R_A > 0) & (df.R_B > 0)).sum()),
           "both_halves_positive_n300_wd3": int(ok.sum()),
           "top30": el.head(30).to_dict("records"),
           "vwap_best_gates": vw.sort_values("score", ascending=False).drop_duplicates("gate").head(20).to_dict("records"),
           "vwap_none": df[(df.trigger == VWAP30) & (df.gate == "none")].sort_values("score", ascending=False).head(5).to_dict("records"),
           "greedy_steps": steps, "basket_select": rnd(cur)}
    base = df[df.gate == "none"].groupby("trigger").score.max()
    best = df[df.gate != "none"].groupby("trigger").score.max()
    ref["gain_by_trigger"] = (best - base).sort_values(ascending=False).head(20).round(4).to_dict()
    json.dump(ref, open(os.path.join(OUT8, "select8.json"), "w"), ensure_ascii=False, indent=1, default=float)
    df.to_parquet(os.path.join(OUT8, "select8_rows.parquet")) if _has_parquet() else None
    print("eligible", ok.sum(), "of", len(df), flush=True)


def _has_parquet():
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def gate_row(T, G, gate, gi):
    if gate == "none":
        return None
    if gate.startswith("P|"):
        a, b = gate[2:].split("&")
        return np.where(G[gi[a]] == G[gi[b]], G[gi[a]], 0).astype(np.int8)
    return G[gi[gate]]


# ---------------------------------------------------------------- confirm (once)

def month_odds2(o, m):
    """Every 30-day stretch over select + confirm at a fixed exposure: share of x2 / x5 / x10 / x20, share losing 90 %."""
    from vwacct import trades
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
        out[str(E)] = {"x2": round(float((mm >= 2).mean()), 4), "x5": round(float((mm >= 5).mean()), 4),
                       "x10": round(float((mm >= 10).mean()), 4), "x20": round(float((mm >= 20).mean()), 4),
                       "lose90": round(float((mm <= 0.1).mean()), 4), "median": round(float(np.median(mm)), 4)}
    return out


def build_one(f, gi, cache):
    if "members" in f:
        ones = [build_one(m, gi, cache) for m in f["members"]]
        return merge(ones)
    lab = f["trigger"]
    if lab not in cache:
        T = Trig(lab)
        cache[lab] = (T, T.gates())
    T, G = cache[lab]
    o = T.one(gate_row(T, G, f["gate"], gi), f["exit"])
    o.member = np.full(len(o.entry), f"{lab}~{f['gate']}~{f['exit']}", object)
    return o


def confirm():
    fp = os.path.join(RES_DIR, "finalists8.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists8.json changed after it was frozen"
    load_ctx()
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    gi = {g: i for i, g in enumerate(GATES)}
    cache, res = {}, []
    rng = np.random.default_rng(SEED8)
    for f in json.load(open(fp))["finalists"]:
        o = build_one(f, gi, cache)
        m = wd_mask(o)
        row = dict(f)
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(o, m, 0, per))
        tw = np.array([metrics(o, m, 0, "confirm", flip=rng.random(len(o.entry)) < 0.5, full=False)["growth"]
                       for _ in range(2000)])
        q = float(np.percentile(tw, TWIN_Q))
        g = row["confirm"]["growth"]
        row["twin"] = {"p50": round(float(np.median(tw)), 3), "p90": round(float(np.percentile(tw, 90)), 3),
                       f"p{TWIN_Q:g}": round(q, 3), "share_below": round(float((tw < g).mean()), 4)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > q) else "통하지 않음"
        row["month_odds"] = month_odds2(o, m)
        res.append(row)
        print(f["name"], f.get("trigger"), f.get("gate"), f.get("exit"), "| select wd", row["select"]["per_weekday"],
              "R", row["select"]["avgR"], "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"], "win",
              row["confirm"]["win"], "R", row["confirm"]["avgR"], "g", g, "q", round(q, 2), "->", row["verdict"],
              "| live n", row["live"]["n"], "R", row["live"]["avgR"], flush=True)
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res},
              open(os.path.join(RES_DIR, "results8.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results8.json")


if __name__ == "__main__":
    os.makedirs(OUT8, exist_ok=True)
    cmd = sys.argv[1]
    if cmd == "scan":
        scan(int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3)
    else:
        {"select": select, "confirm": confirm, "check": check}[cmd]()
