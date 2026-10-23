"""참고 read: the live bot's own code (paperbot/combo.py ComboRunner + ComboEngine with paperbot/entrygates.py and
max_hold_bars, deploy/combo.vwap.json: VWAP fail 30m + CMO sandwich 1h, owners 10/23) against the research's 'VWAP 개선판'
+ CMO 1h with A's gates (vwadd.py "A + CMO·샌드위치 캔들 1시간 A 조건").

1. gates: every VWAP fail 30m and CMO sandwich 1h signal from 2026-07-01 to the data end through EntryGates (the trend
   judge on the last 300 closed 4h bars, ATR% on the last 30 days of the signal's own bars, both served closed-only by
   a clock at the signal's minute) vs the research's j4h (judge files) and atrp / atrp_q80;
2. replay: the rule bot's run (2026-10-05 19:30 UTC .. the data end) minute by minute, the 1m grid written into a
   temporary paper3.db (live_bars, mark = last) and each signal into its signal_log at its bar close (reference price
   = the open of the entry minute), then ComboRunner.poll() as the live process runs it; trades compared one by one
   with the research's (entry minute, coin, side, exit minute, net return per unit of notional).
   Two sizes: the research's (margin 30 %, max_loss_frac 0.15) and the deploy file's (margin 40 %, 0.2).

    python3 -I vwlivepar.py   -> research/vwap30/livepar.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *
from vwacct import _take
from vwlive19 import START

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, REPO)
import shutil, tempfile
from paperbot import combo as C
from paperbot.entrygates import BarCache, EntryGates
from paperbot.livereplay import _Clock, _Fund, file_brackets, file_specs
from paperbot.notify import NullNotifier
from paperbot.store3 import Store3
from paperbot.trendjudge import Judge, Klines, TrendRules
import vwadd as AD
from vwadd import rows_of, outcomes_k

AD.PHOTO = [("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들 1시간")]
MEMBER = {"30m": "F6_VWAP_FAIL", "1h": "S3_CMO_SANDWICH"}

DEPLOY = os.path.join(REPO, "deploy", "combo.vwap.json")
GATE_FROM = ms("2026-07-01")
H4 = 240 * MIN
M30 = 30 * MIN


def research_rows(lib):
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        R = R[(R.t >= GATE_FROM) & (R.t < DATA_END - MIN)].reset_index(drop=True)
        O = outcomes_tf(coin, R, 30)
        R["r"], R["x"] = O["base"]
        R["prio"] = 0
        parts.append(R)
    from multiprocessing import Pool
    with Pool(2) as pool:
        sig = dict(pool.map(AD.sig_job, COINS))
    for coin in COINS:
        R = rows_of(coin, "1h", sig[coin][("S3_CMO_SANDWICH", "1h")])
        R = R[(R.t >= GATE_FROM) & (R.t < DATA_END - MIN)].reset_index(drop=True)
        R["r"], R["x"] = outcomes_k(coin, R, 60)
        R["prio"] = 1
        parts.append(R)
    for R in parts:
        R["p0"] = grid(COINS[int(R.coin.iloc[0])])["o"][R.e.to_numpy()] if len(R) else []
    R = pd.concat(parts, ignore_index=True)
    t = R.t.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    R["wd"] = np.asarray(kst.dayofweek < 5)
    R["usop"] = [bool(us_open_pause(int(x), 30, 30)) for x in t]
    R["macro"] = [bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t]
    R["gate_vote"] = ~(R.j4h.to_numpy() < 0)
    R["gate_vol"] = ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    return R


def feeds(clock):
    """The two Binance reads of the gates, served from the research's bars by the clock (closed + forming)."""
    arr = lambda df: df[["ts", "open", "high", "low", "close", "volume"]].to_numpy(float)   # noqa: E731
    A = {tf: {c: arr(bars(c, tf)) for c in COINS} for tf in ("30m", "1h", "4h")}

    def k4(symbol, tf, limit):
        a = A[tf][symbol]
        i1 = int(np.searchsorted(a[:, 0], clock.now, side="right"))
        return [[int(r[0])] + list(r[1:]) for r in a[max(0, i1 - int(limit)):i1]]

    def kbars(symbol, tf, start, limit):
        a = A[tf][symbol]
        i0 = int(np.searchsorted(a[:, 0], int(start)))
        i1 = min(int(np.searchsorted(a[:, 0], clock.now, side="right")), i0 + int(limit))
        return [[int(r[0])] + list(r[1:]) for r in a[i0:i1]]
    return k4, kbars


def gate_check(R):
    clock = _Clock(0)
    k4, k30 = feeds(clock)
    gates = EntryGates({"tf": "4h", "vote_min": 3}, {"atr": 14, "days": 30, "q": 0.8},
                       Judge(Klines(k4, clock), TrendRules(vote_min=3)), BarCache(k30, clock))
    vote_live, vol_live, why = [], [], []
    for r in R.itertuples():
        clock.now = int(r.t) + MIN + 5_000
        sym, side = COINS[int(r.coin)], int(r.side)
        w1 = gates._vote_block(sym, side, int(r.t))
        w2 = gates._vol_block(sym, str(r.tf), int(r.t))
        vote_live.append(w1 == "" or "못 읽음" in w1)   # research: no judge -> passes
        vol_live.append(w2 == "")
        why.append((w1, w2))
    R = R.assign(live_vote=vote_live, live_vol=vol_live)
    unread = sum(1 for a, b in why if "못 읽음" in a or "못 읽음" in b)
    out = {"signals": len(R), "by_tf": R.tf.value_counts().to_dict(), "unreadable": unread,
           "vote_agree": int((R.live_vote == R.gate_vote).sum()), "vol_agree": int((R.live_vol == R.gate_vol).sum()),
           "vote_differ": R[R.live_vote != R.gate_vote][["t", "coin", "side", "j4h"]].assign(
               coin=lambda d: [COINS[int(c)] for c in d.coin]).to_dict("records"),
           "vol_differ": R[R.live_vol != R.gate_vol][["t", "coin", "atrp", "atrp_q80"]].assign(
               coin=lambda d: [COINS[int(c)] for c in d.coin]).to_dict("records")}
    print("gates", {k: v for k, v in out.items() if not k.endswith("differ")}, flush=True)
    return out


def research_trades(R):
    R = R[R.t >= START].reset_index(drop=True)
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    cand = R.wd.to_numpy() & ~R.usop.to_numpy() & ~R.macro.to_numpy() & R.gate_vote.to_numpy() & R.gate_vol.to_numpy()
    o = np.lexsort((coin, R.prio.to_numpy(), t))
    ext = t[o] + (R.x.to_numpy()[o] + 1) * MIN
    idx = o[_take(t[o], ext, cand[o])]
    lev = np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    out = []
    for q in idx:
        r = R.iloc[q]
        out.append({"entry": int(r.t), "coin": COINS[int(r.coin)], "side": int(r.side), "exit": int(r.t + (r.x + 1) * MIN),
                    "r": float(r.r), "lev_eff": float(lev[q]), "tf": str(r.tf)})
    return out


def replay(R, margin, mlf, tag):
    cfg_raw = json.load(open(DEPLOY, encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix=f"vwlivepar_{tag}_")
    try:
        cfg_raw.update(paper_db=os.path.join(tmp, "paper3.db"), db=os.path.join(tmp, "combo.db"), telegram=False,
                       margin=margin, max_loss_frac=mlf)
        cfg = C.ComboConfig.from_dict(cfg_raw)
        assert not cfg.problems(), cfg.problems()
        members = C.resolve_members(cfg.members, cfg.picks_file)
        syms = list(cfg.symbols)
        settings = C.settings_of(cfg)
        brackets, _src = file_brackets(syms)
        specs = file_specs(syms)
        paper = Store3(cfg.paper_db)
        paper.commit()
        store = Store3(cfg.db)
        book = C.build_book(cfg, settings, brackets, store, NullNotifier(), specs)
        clock = _Clock(START)
        k4, kbars = feeds(clock)
        gates = EntryGates(cfg.vote_gate, cfg.vol_gate, Judge(Klines(k4, clock), TrendRules(vote_min=3)),
                           BarCache(kbars, clock))
        rates = {}
        G = {c: grid(c) for c in COINS}
        for c in COINS:
            f = G[c]["fund"]
            for j in np.flatnonzero(np.nan_to_num(f) != 0):
                tt = T0 + int(j) * MIN
                if tt >= START:
                    rates.setdefault(tt, {})[c] = float(f[j])
        runner = C.ComboRunner(cfg, members, book, store, NullNotifier(), None, clock, lambda: {}, _Fund(rates),
                               gates=gates)
        runner.cursor = 0
        book.last_ts = START - MIN
        S = R[R.t >= START]
        sig_at = {}
        for r in S.itertuples():
            sig_at.setdefault(int(r.t), []).append(r)
        t0 = time.time()
        for t in range(START, DATA_END - MIN, MIN):
            j = (t - T0) // MIN
            rows = []
            for c in COINS:
                g = G[c]
                o, h, l, cl = (float(g[k][j]) for k in ("o", "h", "l", "c"))
                if not np.isfinite(o):
                    continue
                rows.append(dict(ts=t, symbol=c, open=o, high=h, low=l, close=cl, volume=float(np.nan_to_num(g["v"][j])),
                                 mark_open=o, mark_high=h, mark_low=l, mark_close=cl, close_time=t + MIN - 1,
                                 processed_at=t + MIN + 5_000))
            paper.live_bars(rows)
            sg = [dict(bar_close=t, timeframe=str(r.tf), strategy=MEMBER[str(r.tf)], symbol=COINS[int(r.coin)], side=int(r.side),
                       atr=float(r.atrf * r.p0), ref_price=float(r.p0), ref_time=t + 5_000, delay_ms=5_000,
                       status="SUBMITTED", data={}) for r in sig_at.get(t, [])]
            if sg:
                paper.log_signals(sg)
            paper.commit()
            clock.now = t + MIN + 1_000
            runner.poll()
            if (t - START) % (24 * 60 * MIN) == 0:
                print(tag, pd.Timestamp(t, unit="ms"), "trades", len(book.engines[C.ACCOUNT].trades),
                      f"{time.time() - t0:.0f}s", flush=True)
        acct = book.engines[C.ACCOUNT]
        trades = [{"entry": int(x.entry_time), "coin": x.symbol, "side": int(x.side), "exit": int(x.exit_time), "tf": x.timeframe,
                   "reason": x.exit_reason, "lev": int(x.leverage), "roe": float(x.roe), "pnl": float(x.pnl),
                   "notional": float(x.qty * x.entry_price), "equity_after": float(x.equity_after)} for x in acct.trades]
        filt = {}
        for st, why in store.conn.execute("SELECT status, reason FROM outcomes WHERE account_id = ?", (C.ACCOUNT,)):
            k = f"{st}: {(why or '').split(':')[0][:40]}"
            filt[k] = filt.get(k, 0) + 1
        pos = acct.position
        return {"trades": trades, "outcomes": filt, "counts": runner.counts, "wallet": float(acct.wallet), "initial": float(cfg.initial_equity),
                "open": None if pos is None else {"entry": int(pos.entry_time), "coin": pos.symbol, "side": int(pos.side)}}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compare(res, live):
    rk = {(x["entry"], x["coin"], x["side"]): x for x in res}
    lk = {(x["entry"], x["coin"], x["side"]): x for x in live["trades"]}
    both = sorted(set(rk) & set(lk))
    # the research's exit is the minute after the exit minute (where the next trade may start); the live one is the
    # exit minute itself
    same_exit = [k for k in both if rk[k]["exit"] == lk[k]["exit"] + MIN]
    rows = []
    for k in both:
        a, b = rk[k], lk[k]
        # live net return per unit of notional: pnl / notional (fees, slippage and funding inside)
        rows.append({"entry": str(pd.Timestamp(k[0] + KST, unit="ms"))[:16], "coin": k[1][:-4], "side": k[2],
                     "exit_research": str(pd.Timestamp(a["exit"] + KST, unit="ms"))[:16],
                     "exit_live": str(pd.Timestamp(b["exit"] + MIN + KST, unit="ms"))[:16], "reason": b["reason"],
                     "r_research_pct": round(a["r"] * 100, 3), "r_live_pct": round(b["pnl"] / b["notional"] * 100, 3)})
    wins = sum(1 for x in live["trades"] if x["pnl"] > 0)
    eq = [x["equity_after"] for x in live["trades"]]
    peak, dd = live["initial"], 0.0
    for e in eq:
        peak = max(peak, e)
        dd = min(dd, e / peak - 1)
    d = np.array([r["r_live_pct"] - r["r_research_pct"] for r in rows])
    return {"research_n": len(res), "live_n": len(live["trades"]), "matched": len(both), "same_exit": len(same_exit),
            "r_diff_pct_median": round(float(np.median(d)), 4), "r_diff_pct_mean": round(float(d.mean()), 4),
            "only_research": [list(k) for k in sorted(set(rk) - set(lk))],
            "only_live": [list(k) for k in sorted(set(lk) - set(rk))],
            "live_wins": wins, "live_losses": len(live["trades"]) - wins,
            "live_mult": round(live["wallet"] / live["initial"], 4), "live_maxdd": round(dd, 4),
            "live_reasons": pd.Series([x["reason"] for x in live["trades"]]).value_counts().to_dict(),
            "outcomes": live["outcomes"], "counts": live["counts"], "open_at_end": live["open"], "rows": rows}


def main():
    lib = sweepsig.lib()
    R = research_rows(lib)
    print("signals", len(R), flush=True)
    out = {"data_end": DATA_END, "gates": gate_check(R)}
    res = research_trades(R)
    n = len(res)
    w = sum(1 for x in res if x["r"] > 0)
    eq = np.cumprod([1 + 0.3 * x["lev_eff"] * x["r"] for x in res])
    eq4 = np.cumprod([1 + 0.4 * x["lev_eff"] * x["r"] for x in res])
    out["research"] = {"n": n, "wins": w, "losses": n - w, "mult_margin30": round(float(eq[-1]), 4),
                       "mult_margin40": round(float(eq4[-1]), 4),
                       "by_tf": {tf: sum(1 for x in res if x["tf"] == tf) for tf in ("30m", "1h")}}
    print("research", out["research"], flush=True)
    for tag, margin, mlf in (("m30", 0.3, 0.15), ("m40", 0.4, 0.2)):
        live = replay(R, margin, mlf, tag)
        out[tag] = compare(res, live)
        print(tag, {k: v for k, v in out[tag].items() if k != "rows"}, flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "livepar.json"), "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
