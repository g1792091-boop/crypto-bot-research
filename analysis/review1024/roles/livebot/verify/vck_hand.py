"""Verifier (lens: look-ahead / time alignment) for the claim 'the 7 extra checks make B0's direction worse than a coin
flip'. For a stratified random sample of B0 CANDIDATES (pass and every fail reason) in 2024-01 .. 2026-10-05:
  - bars rebuilt here by pandas resample of the raw 1m grid (UTC bins), frames = the last 300 CLOSED bars at the signal
    (exactly the bot's Klines.KEEP window), judged with the bot's own paperbot.trendjudge.judge_frame / spot_frame /
    check and paperbot.combo.chase_check (hours dict from 1m bars before the signal) -> every check flag, compared with
    the replay's flags (lb_core.candidates keep_all);
  - a 'peek' variant that also feeds the higher bar still OPEN at t (future minutes) to see whether the replay's flags
    look like they used it;
  - own AND opposite side outcomes re-walked with a plain Python minute loop + paperbot.ladder2.ComboLadder, the forced
    minute recomputed from my own higher bars (first higher bar CLOSING after the entry whose raw 3/4 vote is against
    the own side, judged on its trailing 300-bar window) and the first later opposite signal of the same member.
Run (no -I): python3 vck_hand.py <n_per_reason> [seed]"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import lb_core as L                       # only to list the candidates and their replay flags / outcomes
from lb_core import *                     # noqa: F401,F403
from paperbot import trendjudge as TJ
from paperbot import combo as CB
from paperbot.ladder2 import ComboLadder
NPER = int(sys.argv[1]); SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 5
LAD = ComboLadder(first_lock=0.10, trigger_gap=0.01, step=0.05, next_trigger=0.15, next_gap=0.03)
import json
RULES = TJ.TrendRules.from_dict(json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["trend"])
E_ = libs(); FG, PI = E_["fg"], E_["pi"]
_B = {}
def my_bars(coin, tf):
    if (coin, tf) not in _B:
        g = grid(coin)
        idx = pd.to_datetime(T0 + np.arange(g["n"], dtype=np.int64) * MIN, unit="ms", utc=True)
        df = pd.DataFrame({"open": g["o"], "high": g["h"], "low": g["l"], "close": g["c"], "volume": g["v"]}, index=idx)
        r = df.resample({"30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}[tf], label="left", closed="left", origin="epoch")
        o = pd.DataFrame({"open": r.open.first(), "high": r.high.max(), "low": r.low.min(), "close": r.close.last(),
                          "volume": r.volume.sum(), "cnt": r.close.count()})
        o = o[o.cnt == TF_MIN[tf]].drop(columns="cnt")
        o["cl"] = o.index.asi8 // 10**6 + TF_MIN[tf] * MIN
        o = o.reset_index().rename(columns={"index": "ts"})
        _B[(coin, tf)] = o
    return _B[(coin, tf)]
def frame_upto(coin, tf, t, extra=0):
    """last 300 bars with close <= t (extra=1: plus the bar still open at t, built from its first minutes only? no:
    the WHOLE bar = future minutes -> a peek)."""
    B = my_bars(coin, tf)
    j = int(np.searchsorted(B.cl.to_numpy(), t, side="right")) - 1 + extra
    w = B.iloc[max(0, j - 299): j + 1]
    return w[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True), int(B.cl.iloc[j]) if j < len(B) else -1
def hours_dict(coin, t):
    g = grid(coin)
    k = t // HOUR
    out = {}
    for h in range(k - 168, k):
        a = (h * HOUR - T0) // MIN
        if a < 0:
            continue
        hh, ll = np.nanmax(g["h"][a:a + 60]), np.nanmin(g["l"][a:a + 60])
        if np.isfinite(hh):
            out[h] = (hh, ll)
    return out
def code(w):
    for k, c in (("보류", "hold"), ("추세가", "against"), ("힘 약함", "weak"), ("끝물", "tired"), ("돌파형", "breakout"),
                 ("너무 뻗음", "far_htf"), ("진입 자리 아님", "far_etf"), ("RSI", "rsi")):
        if k in w:
            return c
    return "" if not w else "?" + w[:20]
def flags(coin, r, extra=0):
    htf = L.HTF_OF[r.tf]
    t = int(r.t)
    fh, cl = frame_upto(coin, htf, t, extra)
    j = TJ.judge_frame(TJ_chart(fh), coin, htf, RULES, FG, PI)
    fs, _ = frame_upto(coin, r.tf, t)
    s = TJ.spot_frame(TJ_chart(fs), r.tf, FG)
    price = grid(coin)["o"][int(r.e)]
    out = {}
    side = int(r.side)
    # each check alone (as lb_core.checks), with the bot's own objects / numbers
    far_h = side * (price - j.ema20) / j.atr
    far_e = (price - s.ema20) / s.atr
    out.update(hold=j.dir == 0, against=(j.dir != 0 and j.dir != side), weak=not j.adx >= RULES.adx_min,
               tired=j.tired(RULES), breakout=(r["name"] in RULES.breakout and not (j.adx < RULES.breakout_adx_max and j.adx > j.adx_prev)),
               far_htf=far_h > RULES.htf_ema_atr, far_etf=abs(far_e) > RULES.etf_ema_atr,
               rsi=(side > 0 and s.rsi >= RULES.rsi_long_max) or (side < 0 and s.rsi <= RULES.rsi_short_min))
    why, _info = TJ.check(RULES, r["name"], r.tf, side, price, j, s)
    out["bot_first"] = code(why)
    ch, _ = CB.chase_check(hours_dict(coin, t), t, side, price)
    out["chase"] = ch is not False
    out["htf_close"] = cl
    return out
def TJ_chart(w):
    d = w.copy(); d.attrs["tf"] = "x"; return d
_RAW = {}
def htf_raw_series(coin, htf):
    if (coin, htf) not in _RAW:
        B = my_bars(coin, htf)
        arr = TJ.vote_arrays(TJ_chart(B[["ts", "open", "high", "low", "close", "volume"]]), FG, PI)
        _RAW[(coin, htf)] = (TJ.raw_votes(arr, 3).astype(int), B.cl.to_numpy())
    return _RAW[(coin, htf)]
def force_minute(coin, r):
    htf = L.HTF_OF[r.tf]
    raw, cl = htf_raw_series(coin, htf)
    e = int(r.e); side = int(r.side)
    cm = (cl - T0) // MIN
    jj = np.flatnonzero((cm > e) & (raw == -side))
    jm = int(cm[jj[0]]) if len(jj) else -1
    Lb, Sb, e0 = RD.signal_bits(r["name"], r.tf, coin)
    opp = Sb if side > 0 else Lb
    mo = e0 + np.flatnonzero(opp).astype(np.int64) * TF_MIN[r.tf]
    x = np.searchsorted(mo, e, side="right")
    rm = int(mo[x]) if x < len(mo) else -1
    return jm if rm < 0 else (rm if jm < 0 else min(jm, rm))
def walk_py(g, cumf, e, s, lev, force):
    o, h, l = g["o"], g["h"], g["l"]
    p0 = o[e]; f0 = cumf[e - 1]; best = -1e9; lock = None; k = 0
    while True:
        i = e + k
        F = s * (cumf[i] - f0); Fp = s * (cumf[i - 1] - f0); op = s * (o[i] / p0 - 1.0)
        if k > 0 and lock is None and force >= 0 and i >= force:
            return max(op - COST - F, -1.0 / lev) * lev, k
        level = -0.5 / lev + COST + Fp
        if lock is not None and lock / lev + COST + Fp > level:
            level = lock / lev + COST + Fp
        up = (h[i] / p0 - 1.0) if s > 0 else (1.0 - l[i] / p0)
        dn = (l[i] / p0 - 1.0) if s > 0 else (1.0 - h[i] / p0)
        if dn <= level:
            return max(min(level, op) - COST - F, -1.0 / lev) * lev, k
        rup = lev * (up - COST - F)
        if rup > best:
            best = rup; lk = LAD.lock_for(best); lock = lk if lk is not None else lock
        k += 1
def main():
    t0 = time.time()
    S = L.candidates("B0", period=(ms("2024-01-01"), FWD[0]), keep_all=True)
    S = S[(S.tb_why != 3) & (S.tb_opp_why != 3)].reset_index(drop=True)
    print("candidates", len(S), "pass", (S.why == "").sum(), round(time.time() - t0), "s", flush=True)
    parts = []
    for w, G in S.groupby("why"):
        if w in ("blk", "na"):
            continue
        parts.append(G.sample(min(NPER * (2 if w == "" else 1), len(G)), random_state=SEED))
    X = pd.concat(parts).sort_values("t").reset_index(drop=True)
    rows = []
    for q, r in X.iterrows():
        coin = COINS[int(r.coin)]
        a = flags(coin, r)
        pk = flags(coin, r, extra=1)
        g = grid(coin); cumf = np.cumsum(g["fund"]); lev = 40.0 if int(r.coin) == 0 else 30.0
        f = force_minute(coin, r)
        own, ko = walk_py(g, cumf, int(r.e), int(r.side), lev, f)
        opp, ko2 = walk_py(g, cumf, int(r.e), -int(r.side), lev, f)
        rec = dict(t=int(r.t), coin=coin, name=r["name"], tf=r.tf, side=int(r.side), why=r.why, bot_first=a["bot_first"],
                   htf_close_le_t=a["htf_close"] <= int(r.t), force_file=int(r.force), force_mine=f,
                   own_file=r.tb_roe, own_mine=own, opp_file=r.tb_opp_roe, opp_mine=opp,
                   k_file=int(r.tb_k), k_mine=ko, ko_file=int(r.tb_opp_k), ko_mine=ko2)
        for c in ("hold", "against", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi", "chase"):
            rec[f"rep_{c}"] = bool(r[f"f_{c}"]); rec[f"me_{c}"] = bool(a[c]); rec[f"pk_{c}"] = bool(pk[c])
        rows.append(rec)
        if (q + 1) % 50 == 0:
            print(q + 1, "/", len(X), round(time.time() - t0), "s", flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, f"vck_hand_{SEED}.csv"), index=False)
    print("sample", len(R), R.why.value_counts().to_dict())
    print("higher bar closed at/before t:", R.htf_close_le_t.mean())
    for c in ("hold", "against", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi", "chase"):
        print(f" {c:9s} replay==causal {(R[f'rep_{c}'] == R[f'me_{c}']).mean():.4f}   replay==peek {(R[f'rep_{c}'] == R[f'pk_{c}']).mean():.4f}")
    # first trend-check reason: replay's first among the trend checks vs the bot's check()
    order = ["hold", "against", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi"]
    def first(row, pre):
        for c in order:
            if c == "hold":
                continue                      # hold allowed (10-22 design): check() returns '' for 보류 too
            if row[f"{pre}_{c}"]:
                return c
        return ""
    R["rep_first"] = [first(x, "rep") for _, x in R.iterrows()]
    print("replay first trend reason == bot check():", (R.rep_first == R.bot_first).mean())
    print(R.loc[R.rep_first != R.bot_first, ["t", "coin", "name", "tf", "side", "why", "rep_first", "bot_first"]].head(10).to_string())
    print("force equal:", (R.force_file == R.force_mine).mean())
    for a_, b_ in (("own_file", "own_mine"), ("opp_file", "opp_mine")):
        d = (R[a_] - R[b_]).abs()
        print(f" {a_}: equal(<1e-6) {(d < 1e-6).mean():.4f} max|d| {d.max():.2e} mean file {R[a_].mean():.5f} mine {R[b_].mean():.5f}")
    print("k equal own", (R.k_file == R.k_mine).mean(), "opp", (R.ko_file == R.ko_mine).mean())
    bad = R[(R.own_file - R.own_mine).abs().gt(1e-6) | (R.opp_file - R.opp_mine).abs().gt(1e-6) | (R.force_file != R.force_mine)]
    if len(bad):
        print(bad[["t", "coin", "name", "tf", "side", "force_file", "force_mine", "own_file", "own_mine", "opp_file", "opp_mine"]].head(15).to_string())
    print("done", round(time.time() - t0), "s")
if __name__ == "__main__":
    main()
