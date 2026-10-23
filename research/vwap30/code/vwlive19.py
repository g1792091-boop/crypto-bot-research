"""참고 read: the two DeepSeek top strategies (VWAP fail 30m, EMA fan 30m) over the rule bot's run (2026-10-05 19:30 UTC ..
the data end) under the live bot's rules (deploy/combo.trend.json): margin 40 % at BTC 40x / others 30x, stop at net ROE
-50 %, the owners' ladder (11 -> 10, 15 -> 12, 20 -> 17, +5 per 5), early exit on the same strategy's opposite signal
before the first lock, no time exit, no entry on the KST weekend, 30 min around US macro releases or around the NYSE
open (30 before, 30 after); one position per account. Costs: market round trip 0.14 %; October funding is not published
yet (0). Signals: the rule bot's view code on bars extended to the data end (parity with newlive checked: VWAP 5,123 /
5,123 on SOL, EMA fan 4,266 / 4,267 on ETH).

    python3 -I vwlive19.py [--check]   -> research/vwap30/live19.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "third_party", "sweep",
                                "harness", "vendor"))           # pine_indicators for the EMA fan view
from vwcommon import *
from vwcommon import _GRID
from vwbuild import lock_owners
from paperbot.strategy_view_defs.DS_F4_FAN import view_DS_F4_FAN
from paperbot.combo import kst_weekend, us_open_pause
from paperbot import events as EV

START = ms("2026-10-05T19:30")
MARGIN = 0.40
LEV = {"BTCUSDT": 40}
STRATS = {"VWAP 복귀 실패 30분": "vwap", "EMA 부채 정렬 30분": "fan"}
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))


def sigs(kind):
    rows = []
    for ci, coin in enumerate(COINS):
        df = bars(coin, "30m")
        if kind == "vwap":
            S = signals(coin, "30m", df)
            t, s = S.bar_close.to_numpy(np.int64), S.side.to_numpy(int)
        else:
            v = view_DS_F4_FAN(df.assign(ts=pd.to_datetime(df.ts, unit="ms", utc=True)), "30m")
            lo = np.logical_and.reduce([np.asarray(x, bool) for _, x in v["long"]])
            sh = np.logical_and.reduce([np.asarray(x, bool) for _, x in v["short"]])
            both = lo & sh
            lo, sh = lo & ~both, sh & ~both
            tc = df.ts.to_numpy(np.int64) + 30 * MIN
            t, s = np.r_[tc[lo], tc[sh]], np.r_[np.ones(lo.sum(), int), -np.ones(sh.sum(), int)]
        rows.append(pd.DataFrame({"t": t, "coin": ci, "side": s}))
    S = pd.concat(rows).sort_values(["t", "coin"]).reset_index(drop=True)
    return S


def trade(coin, e, s, opp_minutes, cap=None):
    """Exit of one position from minute e: (minute index of the exit from e, price return net of costs, reason, best
    net ROE). opp_minutes: minutes (from e) of the same strategy's opposite signals on this coin."""
    g = grid(coin)
    L = LEV.get(coin, 30)
    end = g["n"] if cap is None else min(g["n"], e + cap)
    o, h, l, c = (g[k][e:end] for k in ("o", "h", "l", "c"))
    p0 = o[0]
    UP = (h / p0 - 1) if s > 0 else (1 - l / p0)
    DN = (l / p0 - 1) if s > 0 else (1 - h / p0)
    OP = s * (o / p0 - 1)
    RMU = np.maximum.accumulate(UP)
    RMUp = np.r_[0.0, RMU[:-1]]
    lk = lock_owners(L * (RMUp - COST_RT))
    lock_lvl = np.where(np.isnan(lk), -np.inf, lk / L + COST_RT)
    level = np.maximum(lock_lvl, -(0.5 / L - COST_RT))
    hit = np.flatnonzero(DN <= level)
    k_stop = int(hit[0]) if len(hit) else len(o)
    k_rev = len(o)
    ks = np.asarray(opp_minutes)
    ks = ks[(ks > 0) & (ks < len(o))]
    if len(ks) and np.isnan(lk[ks[0]]):                # after the first lock the ladder alone decides
        k_rev = int(ks[0])
    cf = np.cumsum(g["fund"])
    F = s * (cf[e:end] - cf[e - 1])                     # funding paid by the side, cumulative from the entry
    if k_rev < k_stop:
        return k_rev, OP[k_rev] - COST_RT - F[k_rev], "REV(반대 신호)", float(L * (RMUp[k_rev] - COST_RT))
    if k_stop < len(o):
        v = min(level[k_stop], OP[k_stop])
        why = "STOP(−50%)" if np.isnan(lk[k_stop]) else "LOCK(계단)"
        return k_stop, v - COST_RT - F[k_stop], why, float(L * (RMUp[k_stop] - COST_RT))
    return len(o) - 1, s * (c[-1] / p0 - 1) - COST_RT - F[-1], "OPEN(열려 있음)", float(L * (RMU[-1] - COST_RT))


def blocked(t):
    if kst_weekend(t):
        return "weekend"
    if EV.near(int(t), 30 * MIN, 30 * MIN):
        return "macro"
    if us_open_pause(int(t), 30, 30):
        return "us_open"
    return ""


def run(S, members):
    """One-position account over the signals of the given members (S has a 'member' column); returns the trades."""
    S = S[S.member.isin(members) & (S.t >= START) & (S.t < DATA_END - MIN)].sort_values(["t", "rank", "coin"])
    trades, free, skipped = [], -1, {}
    for r in S.itertuples():
        if r.t < free:
            continue
        why = blocked(r.t)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        coin = COINS[r.coin]
        e = (r.t - T0) // MIN
        opp = S0[(S0.member == r.member) & (S0.coin == r.coin) & (S0.side == -r.side) & (S0.t > r.t)].t.to_numpy()
        k, ret, why, best = trade(coin, e, r.side, (opp - T0) // MIN - e)
        L = LEV.get(coin, 30)
        trades.append({"member": r.member, "coin": coin[:-4], "side": "롱" if r.side > 0 else "숏",
                       "entry_utc": str(pd.Timestamp(r.t, unit="ms")), "exit_utc": str(pd.Timestamp(r.t + (k + 1) * MIN, unit="ms")),
                       "lev": L, "roe": float(L * ret), "why": why})
        free = r.t + (k + 1) * MIN
    return trades, skipped


def summary(trades, start=100.0):
    roe = np.array([t["roe"] for t in trades])
    closed = np.array([not t["why"].startswith("OPEN") for t in trades])
    eq = start * np.cumprod(1 + MARGIN * roe)
    peak = np.maximum.accumulate(np.r_[start, eq])[1:]
    dd = float((eq / peak - 1).min()) if len(eq) else 0.0
    r = roe[closed]
    w, lo = r[r > 0], r[r <= 0]
    return {"trades": int(len(roe)), "closed": int(closed.sum()), "wins": int((r > 0).sum()), "losses": int((r <= 0).sum()),
            "win_rate": round(float((r > 0).mean()), 4) if len(r) else None,
            "avg_win_roe": round(float(w.mean()), 4) if len(w) else None, "avg_loss_roe": round(float(lo.mean()), 4) if len(lo) else None,
            "payoff": round(float(w.mean() / -lo.mean()), 3) if len(w) and len(lo) else None,
            "end_balance": round(float(eq[-1]), 2) if len(eq) else start, "return": round(float(eq[-1] / start - 1), 4) if len(eq) else 0.0,
            "max_drawdown": round(dd, 4),
            "reasons": pd.Series([t["why"] for t in trades]).value_counts().to_dict()}


def check():
    """trade() with a 96-bar cap and no early exit against round 3's owners exit for VWAP 30m (before the old data end)."""
    import vwbuild3 as B
    Z = np.load(os.path.join(B.OUT3, "F6_VWAP_FAIL_at_30m.npz"))
    j = next(e["id"] for e in B.EXITS3 if e["kind"] == "owners")
    rng = np.random.default_rng(3)
    bad = 0
    for q in rng.choice(np.flatnonzero(Z["t"] > ms("2025-01-01")), 300, replace=False):
        coin = COINS[int(Z["coin"][q])]
        e = (int(Z["t"][q]) - T0) // MIN
        k, ret, why, best = trade(coin, e, int(Z["side"][q]), np.array([], int), cap=96 * 30)
        if abs(ret - float(Z["ret"][q, j])) > 1e-5 or k != int(Z["tx"][q, j]):
            bad += 1
    print("check vs round 3 owners exit (300 trades):", bad, "differ")


def main():
    global S0
    parts = []
    for i, (ko, kind) in enumerate(STRATS.items()):
        S = sigs(kind)
        S["member"], S["rank"] = ko, i
        parts.append(S)
    S0 = pd.concat(parts, ignore_index=True)
    out = {"window_utc": [str(pd.Timestamp(START, unit="ms")), str(pd.Timestamp(DATA_END, unit="ms"))], "accounts": {}}
    for name, members in [(k, [k]) for k in STRATS] + [("두 매매법 한 계좌", list(STRATS))]:
        trades, skipped = run(S0, members)
        sm = summary(trades)
        out["accounts"][name] = {"summary": sm, "skipped_entries": skipped, "trades": trades}
        print(name, json.dumps(sm, ensure_ascii=False), "skipped", skipped, flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "live19.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        main()
