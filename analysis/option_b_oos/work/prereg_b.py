"""PRE-REGISTERED test of Option B (V4.5 exact AM+B, slow maker variant).

Frozen before any out-of-sample data is fetched; see ../PREREG.md for the rule text.
Derived from critic/work/limit_fill2.py (mechanics) and critic/work/b_null.py (null).

Usage:  python3 prereg_b.py --data DIR --out PREFIX [--reps 300] [--seed 20260929]
DIR must contain {btcusd,ethusd,solusd}-5m-ohlcv.csv and -15m-ohlcv.csv
(Astral columns timestamp(UTC bar open),open,high,low,close,volume).

PRIMARY (the only configuration that decides pass/fail):
  entry : V45_EXACT_AMB signal on 5m bar i (close-confirmed); maker limit at c[i],
          valid bars i+1..i+3; fills only on trade-through (low<limit for long,
          high>limit for short); fill price = limit, or the bar open if it gapped
          through (min(o,limit) long / max(o,limit) short). Unfilled -> no trade.
  exit  : scheduled at o[i+65] (= i+1+64). Exit limit at P=o[ex], valid bars
          ex..ex+2, fills on trade-through at P (maker); else taker at o[ex+3]
          with 0.02% adverse slippage.
  stop  : none.
  costs : maker 0.02%/side, taker 0.05%/side, slippage 0.02% per taker fill,
          no funding (same cost model as the in-sample numbers being replicated).
  seq   : one position per symbol (signal i skipped while i <= last exit bar);
          first 1000 5m bars of each series are warm-up (no signals taken);
          signals with i+1+64+3 >= n are dropped.
  PASS  : pooled PF >= 1.2 AND trades >= 100 AND pooled mean net > 0 AND
          3/3 symbols with positive net sum AND p < 0.05 against a common
          circular-shift null (300 reps, one shift integer applied to all three
          symbols' post-warm-up signal arrays, shift ~ U{288, ..., M-289},
          M = min over symbols of (n - 1000); p = (1 + #{null mean >= real mean})/(R+1)).
SECONDARY (reported, never decisive): taker exit; primary + 6-ATR(14, 5m) stop;
  primary + funding 0.01%/8h pro rata; per-symbol / per-month / per-pull splits;
  cost-free forward drift fwd64 as in forward.py.
"""
from __future__ import annotations
import argparse, json, os, sys, hashlib
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import strategies as S          # noqa: E402
import fg_indicators as fg      # noqa: E402
from run import load_csv        # noqa: E402

H = 64
MAKER, TAKER, SLIP, FUND8H = 0.0002, 0.0005, 0.0002, 0.0001
WARM, ENTRY_VALID, EXIT_VALID, MIN_SHIFT = 1000, 3, 3, 288
SYMS = ("BTCUSD", "ETHUSD", "SOLUSD")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load(data_dir):
    D = {}
    for sym in SYMS:
        p5 = os.path.join(data_dir, f"{sym.lower()}-5m-ohlcv.csv")
        p15 = os.path.join(data_dir, f"{sym.lower()}-15m-ohlcv.csv")
        d5 = load_csv(p5, 5); d15 = load_csv(p15, 15)
        L, Sg = S.v45_exact_amb(d5, d15)
        L = np.asarray(L, bool); Sg = np.asarray(Sg, bool) & ~L
        o, h, l, c = (d5[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        atr = fg.atr(d5, 14).to_numpy(float)
        D[sym] = dict(o=o, h=h, l=l, c=c, atr=atr, L=L, S=Sg, ts=d5["ts"].to_numpy(),
                      sha5=sha(p5), sha15=sha(p15), n=len(o),
                      first=str(d5["ts"].iloc[0]), last=str(d5["ts"].iloc[-1]),
                      gaps5=int(d5.attrs["gaps"]), gapmax5=float(d5.attrs["gap_minutes_max"]),
                      first15=str(d15["ts"].iloc[0]), last15=str(d15["ts"].iloc[-1]))
    return D


def sim(d, idx, side, exit_mode="limit_fallback", stop_atr=None, funding=False):
    o, h, l, c, atr = d["o"], d["h"], d["l"], d["c"], d["atr"]
    n = len(o); busy = -1; rows = []
    for i, s in zip(idx, side):
        if i + 1 + H + EXIT_VALID >= n or i <= busy:
            continue
        ex = i + 1 + H
        lim = c[i]; fj = None
        for j in range(i + 1, min(i + 1 + ENTRY_VALID, ex)):
            if (s > 0 and l[j] < lim) or (s < 0 and h[j] > lim):
                fj = j; fpx = min(o[j], lim) if s > 0 else max(o[j], lim); break
        if fj is None:
            continue
        xp = None; stopped = False; xj = ex
        if stop_atr:
            sl = fpx - s * stop_atr * atr[i]
            for j in range(fj + 1, ex):
                if (s > 0 and l[j] <= sl) or (s < 0 and h[j] >= sl):
                    xp = (min(o[j], sl) if s > 0 else max(o[j], sl)) * (1 - s * SLIP)
                    stopped = True; xj = j; break
        if stopped:
            fee = MAKER + TAKER; xtype = "stop"
        elif exit_mode == "maker":
            xp = o[ex]; fee = 2 * MAKER; xtype = "maker"
        elif exit_mode == "taker":
            xp = o[ex] * (1 - s * SLIP); fee = MAKER + TAKER; xtype = "taker"
        else:
            P = o[ex]; got = False
            for j in range(ex, min(ex + EXIT_VALID, n)):
                if (s > 0 and h[j] > P) or (s < 0 and l[j] < P):
                    xp = P; got = True; xj = j; break
            if got:
                fee = 2 * MAKER; xtype = "maker"
            else:
                xj = min(ex + EXIT_VALID, n - 1); xp = o[xj] * (1 - s * SLIP)
                fee = MAKER + TAKER; xtype = "fallback_taker"
        fund = FUND8H * (xj - fj) * 5 / 480.0 if funding else 0.0
        gross = s * (xp / fpx - 1)
        rows.append((i, fj, xj, s, fpx, xp, gross, fee, fund, gross - fee - fund, xtype))
        busy = xj
    return rows


def signal_idx(d, shift=0):
    L = d["L"][WARM:]; Sg = d["S"][WARM:]
    if shift:
        L = np.roll(L, shift); Sg = np.roll(Sg, shift)
    idx = np.where(L | Sg)[0]
    side = np.where(L[idx], 1, -1)
    return idx + WARM, side


def stats(nets_by_sym):
    x = np.concatenate([np.asarray(v, float) for v in nets_by_sym.values()]) if nets_by_sym else np.array([])
    if len(x) == 0:
        return dict(n=0, exp_pct=np.nan, pf=np.nan, pos=0)
    loss = -x[x <= 0].sum()
    pf = x[x > 0].sum() / loss if loss > 0 else np.inf
    pos = int(sum(np.sum(v) > 0 for v in nets_by_sym.values()))
    return dict(n=int(len(x)), exp_pct=float(x.mean() * 100), pf=float(pf), pos=pos)


def evaluate(D, shift=0, **kw):
    nets = {}
    for sym, d in D.items():
        idx, side = signal_idx(d, shift)
        nets[sym] = [r[9] for r in sim(d, idx, side, **kw)]
    return stats(nets)


def passes(st):
    return bool(st["n"] >= 100 and st["pf"] >= 1.2 and st["exp_pct"] > 0 and st["pos"] >= 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260929)
    a = ap.parse_args()
    D = load(a.data)
    meta = {s: {k: v for k, v in d.items() if k in ("sha5", "sha15", "n", "first", "last", "gaps5",
                                                   "gapmax5", "first15", "last15")} for s, d in D.items()}
    for s, d in D.items():
        meta[s]["signals_after_warmup"] = int((d["L"][WARM:] | d["S"][WARM:]).sum())
        meta[s]["long_share"] = float(d["L"][WARM:].sum() / max(1, meta[s]["signals_after_warmup"]))

    # ---------------- primary ----------------
    trades = []
    for sym, d in D.items():
        idx, side = signal_idx(d)
        for r in sim(d, idx, side):
            trades.append((sym, str(pd.Timestamp(d["ts"][r[0]])), *r))
    T = pd.DataFrame(trades, columns=["symbol", "signal_ts", "i", "fill_j", "exit_j", "side", "fill_px",
                                      "exit_px", "gross", "fee", "funding", "net", "exit_type"])
    T.to_csv(a.out + "_primary_trades.csv", index=False)
    prim = stats({s: T.net[T.symbol == s].to_numpy() for s in SYMS})

    # ---------------- common circular-shift null ----------------
    rng = np.random.default_rng(a.seed)
    M = min(d["n"] - WARM for d in D.values())
    shifts = rng.integers(MIN_SHIFT, M - MIN_SHIFT, size=a.reps)
    null = [dict(shift=int(sh), **evaluate(D, int(sh))) for sh in shifts]
    N = pd.DataFrame(null); N.to_csv(a.out + "_null.csv", index=False)
    k = int((N.exp_pct >= prim["exp_pct"]).sum())
    p = (1 + k) / (a.reps + 1)
    z = float((prim["exp_pct"] - N.exp_pct.mean()) / N.exp_pct.std(ddof=1))
    null_pass = float(N.apply(lambda r: passes(r), axis=1).mean())
    decision = passes(prim) and p < 0.05
    res = dict(primary=prim, rule_part_pass=passes(prim), null_k=k, null_p=p, null_z=z,
               null_mean_exp=float(N.exp_pct.mean()), null_sd_exp=float(N.exp_pct.std(ddof=1)),
               null_pf_median=float(N.pf.median()), null_pass_rate=null_pass,
               DECISION_PASS=bool(decision), M=int(M), reps=a.reps, seed=a.seed, meta=meta)

    # ---------------- secondary (non-decisive) ----------------
    sec = {}
    sec["taker_exit"] = evaluate(D, 0, exit_mode="taker")
    sec["maker_exit_at_open"] = evaluate(D, 0, exit_mode="maker")
    sec["stop6atr_limit_fallback"] = evaluate(D, 0, stop_atr=6.0)
    sec["funding_limit_fallback"] = evaluate(D, 0, funding=True)
    sec["per_symbol"] = {s: dict(n=int((T.symbol == s).sum()), exp_pct=float(T.net[T.symbol == s].mean() * 100),
                                 sum_pct=float(T.net[T.symbol == s].sum() * 100)) for s in SYMS}
    T["month"] = T.signal_ts.str[:7]
    sec["per_month"] = {m: dict(n=int(len(g)), exp_pct=float(g.net.mean() * 100), sum_pct=float(g.net.sum() * 100))
                        for m, g in T.groupby("month")}
    sec["exit_type_share"] = T.exit_type.value_counts(normalize=True).to_dict()
    sec["entry_fill_rate"] = None
    # forward drift (cost free, market entry at o[i+1], exit o[i+65]) all signals, as forward.py
    fw = {}; nsig = 0; filled = 0
    for sym, d in D.items():
        idx, side = signal_idx(d)
        o = d["o"]; n = len(o)
        keep = idx + 1 < n
        idx, side = idx[keep], side[keep]
        j = np.minimum(idx + 1 + H, n - 1)
        r = side * (o[j] / o[idx + 1] - 1.0)
        fw[sym] = dict(signals=int(len(r)), fwd64_mean_pct=float(r.mean() * 100),
                       fwd64_t=float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))), hit=float((r > 0).mean()))
        # entry fill rate over all signals (no sequencing)
        for i, s in zip(idx, side):
            if i + 4 >= n:
                continue
            nsig += 1; lim = d["c"][i]
            filled += any((s > 0 and d["l"][jj] < lim) or (s < 0 and d["h"][jj] > lim) for jj in range(i + 1, i + 4))
    allr = sum(v["fwd64_mean_pct"] * v["signals"] for v in fw.values()) / sum(v["signals"] for v in fw.values())
    fw["pooled_fwd64_mean_pct"] = float(allr)
    sec["forward64"] = fw
    sec["entry_fill_rate"] = filled / max(1, nsig)
    res["secondary"] = sec
    json.dump(res, open(a.out + "_result.json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in res.items() if k not in ("meta", "secondary")}, indent=1, default=str))
    print(json.dumps(sec, indent=1, default=str))


if __name__ == "__main__":
    main()
