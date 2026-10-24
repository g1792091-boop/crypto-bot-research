"""Direction-skill verifier (lens: look-ahead / alignment / data errors), part 4: trades re-checked BY HAND from the raw
1m bars (fg1m npz: Binance USDT-M minutes with their own timestamps; October 2026 from the extended grid, since the raw
files end 2026-09-30 23:59).

Part A  a random sample of bot G's taken trades (dsk_gbot_trades.csv: CONFIRM 60, SELECT 15, 2026 10, last 19 days 15):
        1 the entry bar rebuilt from raw minutes [t - tf, t) equals the study's bar (o h l c), the entry minute = t
        2 the entry strategy, recomputed on the entry bars CUT at the signal bar (1500 bars, nothing later), fires on
          the trade's side at that bar
        3 the higher bar read: UTC arithmetic floor(t / htf) * htf = its close <= t, the next close > t, equal to the
          study's index
        4 the trend source recomputed on the higher bars CUT at that bar (condition state / own-signal latch / judges)
          equals the state the trade used, and its side = the trade's side ("with")
        5 the w35 outcome of BOTH sides walked by hand from the raw minutes starting at the entry minute (own pure-python
          walk of the written rule: 35x, net ROE -50 % stop, +12 -> +10 lock then every 5 %, 0.124 % cost, funding
          summed from the entry minute) equals the grid's r / k / why
Part B  the exploratory cell F12_MSS_DISP@4h with the 1d T4_MACDHIST0 latch (with side), rebuilt CAUSALLY for every
        signal of every coin: the 4h signal recomputed on bars cut at the signal bar, the 1d latch from T4_MACDHIST0
        signals recomputed on daily bars cut at the last closed day, outcomes walked by hand from the raw minutes; then
        one position at a time per period (ties: coin order) -> compare with goalpath.csv (X_F12...).
Outputs dsk_trades_A.csv, dsk_trades_B.csv, dsk_trades.txt.

    python3 dsk_trades.py [A|B]"""
import os
import sys
import time

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
import build_signals as BG      # noqa: E402
import build_states as BS       # noqa: E402
from common import *            # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
RAWDIR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/fg1m/1m"
T_FG_END = ms("2026-10-01")
W = 1500
PB35 = 35.0 * PAYBACK

# ------------------------------------------------------------------ raw minutes
_RAW = {}


def raw(coin):
    """Raw minutes: dict ts -> row index plus arrays (fg1m up to 2026-09-30 23:59, then the extended grid)."""
    if coin not in _RAW:
        z = np.load(os.path.join(RAWDIR, f"{coin}.npz"))
        ts = z["ts"].astype(np.int64)
        keep = ts < T_FG_END
        d = {k: z[k][keep].astype(float) for k in ("o", "h", "l", "c", "fund")}
        d["ts"] = ts[keep]
        g = grid(coin)
        i0 = (T_FG_END - T0) // MIN
        ext_ts = T0 + np.arange(i0, g["n"], dtype=np.int64) * MIN
        for k in ("o", "h", "l", "c"):
            d[k] = np.r_[d[k], g[k][i0:]]
        d["fund"] = np.r_[d["fund"], g["fund"][i0:]]
        d["ts"] = np.r_[d["ts"], ext_ts]
        drop(coin)
        _RAW[coin] = d
    return _RAW[coin]


def minutes(coin, t_from, count):
    """count consecutive minutes from t_from (ms): o h l c fund arrays; a minute missing in the raw file = flat bar at the
    previous close, funding 0 (Binance's no-trade minute). Returns arrays and the number of missing minutes."""
    d = raw(coin)
    want = t_from + np.arange(count, dtype=np.int64) * MIN
    pos = np.searchsorted(d["ts"], want)
    pos = np.minimum(pos, len(d["ts"]) - 1)
    have = d["ts"][pos] == want
    out = {k: np.where(have, d[k][pos], np.nan) for k in ("o", "h", "l", "c", "fund")}
    out["fund"] = np.where(have, out["fund"], 0.0)
    for i in range(count):
        if not have[i]:
            pc = out["c"][i - 1] if i > 0 else d["c"][max(pos[i] - 1, 0)]
            for k in ("o", "h", "l", "c"):
                out[k][i] = pc
    return out, int((~have).sum()), bool(want[-1] <= d["ts"][-1])


def lock_for(best):
    ft = 0.10 + 0.02
    if not best >= ft - 1e-12:
        return None
    return 0.10 + 0.05 * np.floor((best - ft) / 0.05 + 1e-9)


def hand_walk(coin, t_entry, s, lev=35.0, stop=-0.50, cost=COST, chunk=20000):
    """The written rule walked minute by minute from the entry minute's open. Returns (r, k, why)."""
    best = -1e9
    lock = None
    fsum_prev = 0.0
    k = 0
    p0 = None
    base = t_entry
    while True:
        M, _miss, inside = minutes(coin, base, chunk)
        if p0 is None:
            p0 = M["o"][0]
        for q in range(chunk):
            if base + q * MIN >= raw(coin)["ts"][-1] + MIN:
                return np.nan, k, 3
            fcur = fsum_prev + M["fund"][q]
            Fp, F = s * fsum_prev, s * fcur
            op = s * (M["o"][q] / p0 - 1.0)
            level = stop / lev + cost + Fp
            rs = 0
            if lock is not None:
                lv = lock / lev + cost + Fp
                if lv > level:
                    level, rs = lv, 1
            if s > 0:
                up, dn = M["h"][q] / p0 - 1.0, M["l"][q] / p0 - 1.0
            else:
                up, dn = 1.0 - M["l"][q] / p0, 1.0 - M["h"][q] / p0
            if dn <= level:
                fill = level if level < op else op
                r = fill - cost - F
                return max(r, -1.0 / lev), k, rs
            r_up = lev * (up - cost - F)
            if r_up > best:
                best = r_up
                lock = lock_for(best)
            fsum_prev = fcur
            k += 1
        base += chunk * MIN


# ------------------------------------------------------------------ causal recomputations
_BARS = {}


def B_(coin, tf):
    if (coin, tf) not in _BARS:
        _BARS[(coin, tf)] = bars(coin, tf)
        drop(coin)
    return _BARS[(coin, tf)]


def cut_signals(coin, tf, i, names, start=None):
    """{name: (long, short)} of the strategies on tf bars cut at bar i (window from `start`, default i - W)."""
    raw_ = B_(coin, tf)
    s = max(0, i - W) if start is None else start
    rw = raw_.iloc[s:i + 1].reset_index(drop=True)
    tcut = int(close_ms(raw_, tf)[i])
    Bc = {h: B_(coin, h)[close_ms(B_(coin, h), h) <= tcut].reset_index(drop=True) for h in ("1h", "4h", "1d")}
    bt = None
    if coin != "BTCUSDT" and tf != "1d":
        bb = B_("BTCUSDT", tf)
        bt = bb[(bb.ts >= rw.ts.iloc[0]) & (bb.ts <= rw.ts.iloc[-1])].reset_index(drop=True)
    return BG.coin_signals(coin, tf, rw, bt, Bc, only=set(names))


def cut_state(coin, htf, h, kind, source):
    """The trend source on htf bars cut at bar h (nothing later)."""
    df = B_(coin, htf)
    if kind == "c":
        s = max(0, h - W)
        cut = df.iloc[s:h + 1].reset_index(drop=True)
        nx = BS.NEXT_HTF[htf]
        tcut = int(close_ms(df, htf)[h])
        nxt = None if nx is None else (nx, B_(coin, nx)[close_ms(B_(coin, nx), nx) <= tcut].reset_index(drop=True))
        return int(np.asarray(BS.cond_states(cut, htf, nxt)[source])[-1])
    if kind == "l":
        sig = cut_signals(coin, htf, h, [source], start=0 if htf == "1d" else max(0, h - 4000))
        lg, sh = (np.asarray(x, bool) for x in sig[source])
        ev = np.flatnonzero(lg | sh)
        if not len(ev):
            return 0
        return 1 if lg[ev[-1]] else -1
    cut = df.iloc[max(0, h - W):h + 1].reset_index(drop=True)
    J = BS.judge_arrays(cut, htf)
    v = sum(int(np.asarray(J[f"j_{x}"])[-1]) for x in ("V39", "S6", "OBV", "N12"))
    d = int(np.asarray(J["j_dir"])[-1])
    adx = float(np.asarray(J["j_adx"])[-1])
    return {"RAW3": int(np.asarray(J["j_raw3"])[-1]), "DIR": d, "DIR_ADX20": d if adx >= 20 else 0,
            "V2OF4": int(np.sign(v)) if abs(v) >= 2 else 0, "V4OF4": int(np.sign(v)) if abs(v) == 4 else 0,
            "TB22": d, "TB21": d}[source]


# ------------------------------------------------------------------ part A
def part_a(lines):
    T = pd.read_csv(os.path.join(HERE, "dsk_gbot_trades.csv"))
    rng = np.random.default_rng(20261024)
    take = []
    for per, k in (("CONF", 60), ("SEL", 15), ("LATE", 10), ("FWD", 15)):
        z = T[T.period == per]
        take.append(z.iloc[rng.choice(len(z), min(k, len(z)), replace=False)])
    S = pd.concat(take).reset_index(drop=True)
    out = []
    for q, r in S.iterrows():
        coin = COINS[int(r.coin)]
        name, etf = r["name"], r.tf
        cell = r.cell
        htf = cell.split("@")[-1]
        kind, source = cell.split("|")[1].split("@")[0].split(":")
        t = int(r.t)
        tfm = TF_MIN[etf] * MIN
        o = {"period": r.period, "cell": cell, "coin": coin, "side": int(r.side), "t_utc": str(pd.Timestamp(t, unit="ms"))}
        # 1 entry bar from raw minutes
        M, miss, _ = minutes(coin, t - tfm, TF_MIN[etf])
        df = B_(coin, etf)
        nb = int(r.nb)
        o["entry_min_is_t"] = int(r.e) * MIN + T0 == t
        o["bar_close_is_t"] = int(df.ts.iloc[nb]) + tfm == t
        o["bar_equal_raw"] = bool(np.allclose([df.open.iloc[nb], df.high.iloc[nb], df.low.iloc[nb], df.close.iloc[nb]],
                                              [M["o"][0], np.max(M["h"]), np.min(M["l"]), M["c"][-1]], rtol=0, atol=1e-9))
        o["bar_missing_min"] = miss
        # 2 entry signal on cut bars
        sg = cut_signals(coin, etf, nb, [name])[name]
        o["entry_fires_cut"] = bool(sg[0][-1]) if r.side > 0 else bool(sg[1][-1] and not sg[0][-1])
        # 3 higher bar
        H = TF_MIN[htf] * MIN
        exp_close = (t - T0) // H * H + T0 if htf != "1d" else (t // DAY) * DAY
        hdf = B_(coin, htf)
        h = int(r.hidx)
        o["htf_close"] = str(pd.Timestamp(int(hdf.ts.iloc[h]) + H, unit="ms"))
        o["htf_close_le_t"] = int(hdf.ts.iloc[h]) + H <= t
        o["htf_next_close_gt_t"] = (h + 1 >= len(hdf)) or (int(hdf.ts.iloc[h + 1]) + H > t)
        o["htf_utc_arith"] = int(hdf.ts.iloc[h]) + H == exp_close
        # 4 trend source on cut higher bars
        st = cut_state(coin, htf, h, kind, source)
        o["state_cut"] = st
        o["state_study"] = int(r.state)
        o["state_equal"] = st == int(r.state)
        o["with_side"] = (st == int(r.side)) if source not in ("TB22", "TB21") else (st == int(r.side))
        # 5 outcomes by hand (both sides)
        for lab, sd, pre in (("me", int(r.side), "w35"), ("opp", -int(r.side), "w35_opp")):
            rr, kk, ww = hand_walk(coin, t, sd)
            o[f"{lab}_r_hand"], o[f"{lab}_k_hand"], o[f"{lab}_why_hand"] = rr, kk, ww
            o[f"{lab}_r_grid"], o[f"{lab}_k_grid"], o[f"{lab}_why_grid"] = r[f"{pre}_r"], int(r[f"{pre}_k"]), int(r[f"{pre}_why"])
            o[f"{lab}_equal"] = (abs(rr - r[f"{pre}_r"]) < 2e-6) and kk == int(r[f"{pre}_k"]) and ww == int(r[f"{pre}_why"])
        out.append(o)
        if q % 10 == 0:
            log("A", q, cell, coin, o["t_utc"])
    D = pd.DataFrame(out)
    D.to_csv(os.path.join(HERE, "dsk_trades_A.csv"), index=False)
    chk = ["entry_min_is_t", "bar_close_is_t", "bar_equal_raw", "entry_fires_cut", "htf_close_le_t",
           "htf_next_close_gt_t", "htf_utc_arith", "state_equal", "with_side", "me_equal", "opp_equal"]
    lines.append(f"Part A: {len(D)} trades of bot G re-checked by hand "
                 f"({D.period.value_counts().to_dict()}), missing raw minutes in entry bars: {int(D.bar_missing_min.sum())}")
    for c in chk:
        lines.append(f"  {c}: {int(D[c].sum())} / {len(D)}")
    bad = D[~D[chk].all(axis=1)]
    if len(bad):
        lines.append(bad.to_string())


# ------------------------------------------------------------------ part B
def part_b(lines):
    rows = []
    name, src = "F12_MSS_DISP", "T4_MACDHIST0"
    a0 = ms("2021-01-01")
    for ci, coin in enumerate(COINS):
        L, S, e0 = RD.signal_bits(name, "4h", coin)
        df4 = B_(coin, "4h")
        d1 = B_(coin, "1d")
        c4 = close_ms(df4, "4h")
        c1 = close_ms(d1, "1d")
        nbs = np.flatnonzero((L | S) & (c4 >= a0) & (c4 < FWD[1]) & (np.arange(len(L)) >= 300))
        cache1d = {}
        for nb in nbs:
            t = int(c4[nb])
            side = 1 if L[nb] else -1
            h = int(np.searchsorted(c1, t, side="right") - 1)
            if h < 300:
                continue
            if h not in cache1d:
                sig = cut_signals(coin, "1d", h, [src], start=0)[src]
                lg, sh = (np.asarray(x, bool) for x in sig)
                ev = np.flatnonzero(lg | sh)
                cache1d[h] = 0 if not len(ev) else (1 if lg[ev[-1]] else -1)
            lat = cache1d[h]
            stored = int(RD._states(coin, "1d")[f"l_{src}"][h])
            o = {"coin": ci, "t": t, "e": (t - T0) // MIN, "side": side, "latch_cut": lat, "latch_stored": stored}
            if lat == side:
                sg = cut_signals(coin, "4h", nb, [name])[name]
                o["fires_cut"] = bool(sg[0][-1]) if side > 0 else bool(sg[1][-1] and not sg[0][-1])
                for lab, sd in (("me", side), ("opp", -side)):
                    rr, kk, ww = hand_walk(coin, t, sd)
                    o[f"{lab}_r"], o[f"{lab}_k"], o[f"{lab}_why"] = rr, kk, ww
            rows.append(o)
        log("B", coin, "signals", len(nbs), "with", sum(1 for x in rows if x["coin"] == ci and x["latch_cut"] == x["side"]))
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(HERE, "dsk_trades_B.csv"), index=False)
    lines.append(f"Part B: F12_MSS_DISP@4h signals 2021-01 .. 10-24: {len(D)}; 1d latch cut == stored:"
                 f" {int((D.latch_cut == D.latch_stored).sum())} / {len(D)}")
    W_ = D[D.latch_cut == D.side].copy()
    lines.append(f"  with-trend signals {len(W_)}; the 4h signal fires on bars cut at the signal bar: {int(W_.fires_cut.sum())}"
                 f" / {len(W_)}")
    W_ = W_[np.isfinite(W_.me_r) & np.isfinite(W_.opp_r) & (W_.me_why != 3) & (W_.opp_why != 3)]
    ref = pd.read_csv(os.path.join(FY, "goalpath.csv"))
    ref = ref[ref.bot.str.startswith("X_F12_MSS_DISP")].set_index("period")
    spans = {"SEL": (ms("2021-01-01"), ms("2024-01-01")), "CONF": (ms("2024-01-01"), ms("2026-10-01")),
             "LATE": (ms("2026-01-01"), GRID_END), "FWD": FWD}
    for per, (a, b) in spans.items():
        P = W_[(W_.t >= a) & (W_.t < b)].sort_values(["e", "coin"]).reset_index(drop=True)
        took, busy = [], -1
        for _, r in P.iterrows():
            if r.e > busy:
                took.append(True)
                busy = r.e + r.me_k
            else:
                took.append(False)
        T = P[np.array(took, bool)] if len(P) else P
        roe = 35.0 * T.me_r.to_numpy()
        rr = ref.loc[per]
        lines.append(f"  {per}: signals {len(P)} trades {len(T)} mean {roe.mean():.5f} (pb {roe.mean() + PB35:.5f}) win"
                     f" {(roe > 0).mean():.3f} signal-level mean {35 * P.me_r.mean():.5f} opp {35 * P.opp_r.mean():.5f} |"
                     f" study signals {int(rr.signals)} trades {int(rr.trades)} mean {rr.mean_roe:.5f} (pb {rr.mean_roe_pb:.5f})"
                     f" win {rr.win:.3f}")


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "AB"
    lines = []
    t0 = time.time()
    if "A" in which:
        part_a(lines)
    if "B" in which:
        part_b(lines)
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(HERE, f"dsk_trades_{which}.txt"), "w").write(txt + "\n")
    log("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
