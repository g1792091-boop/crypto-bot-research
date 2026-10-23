"""참고 read: the two DeepSeek top strategies over the rule bot's run (2026-10-05 19:30 UTC .. the data end) under the
paper rule bot's rules: stop 2 ATR, the rule bot's ladder (lock 10 % at 12 % reached, +5 % steps, at 30x), margin 30 %
at 30x (9x exposure, the '보통' size), 96-bar hold cap, every day; one position per account; market round trip 0.14 %.
Also the same with the live bot's entry blocks (KST weekend, US macro releases, NYSE open). Signals as vwlive19.py.

    python3 -I vwpaper19.py [--check]   -> research/vwap30/paper19.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwlive19 as V
from vwlive19 import *
from vwbuild import lock_house
from paperbot import sweepsig

LEV_P, MARGIN_P, CAP = 30.0, 0.30, 96 * 30


def with_atr(S):
    lib = sweepsig.lib()
    at = np.full(len(S), np.nan)
    for ci, coin in enumerate(COINS):
        df = bars(coin, "30m")
        a = lib.fg.atr(df, 14).to_numpy(float)
        m = (S.coin == ci).to_numpy()
        ix = ((S.t[m].to_numpy() - 30 * MIN - df.ts.iloc[0]) // (30 * MIN)).astype(int)
        at[m] = a[ix]
    S["atr"] = at
    return S


def paper_trade(coin, e, s, atrf):
    """(minute index of the exit from e, price return net of costs and funding, reason) under the paper rules."""
    g = grid(coin)
    end = min(g["n"], e + CAP)
    o, h, l, c = (g[k][e:end] for k in ("o", "h", "l", "c"))
    p0 = o[0]
    UP = (h / p0 - 1) if s > 0 else (1 - l / p0)
    DN = (l / p0 - 1) if s > 0 else (1 - h / p0)
    OP = s * (o / p0 - 1)
    RMUp = np.r_[0.0, np.maximum.accumulate(UP)[:-1]]
    lk = lock_house(LEV_P * (RMUp - COST_RT))
    level = np.maximum(np.where(np.isnan(lk), -np.inf, lk / LEV_P + COST_RT), -2.0 * atrf)
    cf = np.cumsum(g["fund"])
    F = s * (cf[e:end] - cf[e - 1])
    hit = np.flatnonzero(DN <= level)
    if len(hit):
        k = int(hit[0])
        return k, min(level[k], OP[k]) - COST_RT - F[k], ("STOP(2ATR)" if np.isnan(lk[k]) else "LOCK(계단)")
    k = len(o) - 1
    return k, s * (c[k] / p0 - 1) - COST_RT - F[k], ("TIME(96봉)" if end - e == CAP else "OPEN(열려 있음)")


def run_paper(S, members, live_blocks):
    S = S[S.member.isin(members) & (S.t >= START) & (S.t < DATA_END - MIN)].sort_values(["t", "rank", "coin"])
    trades, free, skipped = [], -1, {}
    for r in S.itertuples():
        if r.t < free:
            continue
        if live_blocks:
            why = blocked(r.t)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
                continue
        coin = COINS[r.coin]
        e = (r.t - T0) // MIN
        k, ret, why = paper_trade(coin, e, r.side, r.atr / grid(coin)["o"][e])
        trades.append({"member": r.member, "coin": coin[:-4], "side": "롱" if r.side > 0 else "숏",
                       "entry_utc": str(pd.Timestamp(r.t, unit="ms")), "exit_utc": str(pd.Timestamp(r.t + (k + 1) * MIN, unit="ms")),
                       "lev": LEV_P, "roe": float(LEV_P * ret), "why": why})
        free = r.t + (k + 1) * MIN
    return trades, skipped


def check():
    """paper_trade against round 3's rule bot exit (2 ATR + ladder) for VWAP 30m, same inputs: must match."""
    import vwbuild3 as B
    Z = np.load(os.path.join(B.OUT3, "F6_VWAP_FAIL_at_30m.npz"))
    j = next(e["id"] for e in B.EXITS3 if e["kind"] == "house" and e["stop"] == 2.0)
    rng = np.random.default_rng(4)
    bad = 0
    for q in rng.choice(np.flatnonzero(Z["t"] > ms("2025-01-01")), 300, replace=False):
        coin = COINS[int(Z["coin"][q])]
        e = (int(Z["t"][q]) - T0) // MIN
        k, ret, why = paper_trade(coin, e, int(Z["side"][q]), float(Z["atrf"][q]))
        if abs(ret - float(Z["ret"][q, j])) > 1e-5 or k != int(Z["tx"][q, j]):
            bad += 1
    print("check vs round 3 rule bot exit (300 trades):", bad, "differ")


def main():
    parts = []
    for i, (ko, kind) in enumerate(STRATS.items()):
        S = with_atr(sigs(kind))
        S["member"], S["rank"] = ko, i
        parts.append(S)
    S0 = pd.concat(parts, ignore_index=True)
    V.MARGIN = MARGIN_P                                  # summary(): balance change = margin x ROE
    out = {"window_utc": [str(pd.Timestamp(START, unit="ms")), str(pd.Timestamp(DATA_END, unit="ms"))], "accounts": {}}
    for tag, blocks in (("페이퍼 규칙 그대로(모든 요일)", False), ("페이퍼 규칙 + 실거래봇 진입 금지(주말·발표·개장)", True)):
        for name, members in [(k, [k]) for k in STRATS] + [("두 매매법 한 계좌", list(STRATS))]:
            trades, skipped = run_paper(S0, members, blocks)
            sm = summary(trades)
            out["accounts"][f"{tag} | {name}"] = {"summary": sm, "skipped_entries": skipped, "trades": trades}
            print(tag, "|", name, json.dumps(sm, ensure_ascii=False), "skipped", skipped, flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "paper19.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        main()
