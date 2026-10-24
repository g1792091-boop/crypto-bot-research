"""참고 read (after the fact, not a test of the strategy): the live paper bot's own code (paperbot/friendsig.py, and
paperbot/combo.py ComboRunner + ComboEngine with deploy/combo.friend.json) against the research's chosen setting
(frpay.py "거래당 1등": 15m signal bars, net ROE stop -75 %, ladder 20 / 10, filters F4 + V).

1. signals: every 15m bar close of the six coins from 2026-06-01 to the data end through FriendSignals.read (the
   research's own bars, vwcommon.bars over the research 1m grid, served as Binance would serve them: closed bars only,
   by a clock 5 s after each close) vs frfamily.signals("15m"): every signal's time / coin / side; then each signal's
   two gates (FriendGates at its entry minute: the 4h ADX < 20, the volume ratio > 0.64) vs frpay.mask(R, "F4+V"), and
   the values side by side (ADX against the judge files' 4h_adx, the volume ratio, EMA21 / EMA52 / RSI26 / ROC9);
2. replay: 2026-09-01 .. the data end minute by minute, the 1m grid written into a temporary paper3.db (live_bars, mark
   = last price), the friend member and its gates reading the same served bars, ComboRunner.poll() as the live process
   runs it; its trades vs frfamily.outcomes(R15, -0.75, 0.20, 0.10) with the F4+V mask and the one-position pass
   (frrun.take): entry minute, coin, side, exit minute, net ROE. Run at the research's cost (taker 0.042 % + slippage
   0.02 %, each side), again at the paper's default taker 0.05 % (what the paper uses without a Binance key), and once
   more as a diagnostic with each coin's first Binance bracket for any size (no entry refused for its size: what is
   left is the rest of the engine).
3. the member option ``higher: "rsi_roc_all"`` (the friend's exact rule of 10/24 night: RSI26 and ROC9 on both higher
   bars) as in 1, against the research's frand.and_signals("15m", "lt50") (PREREG7).

    python3 -I frlive_parity.py [--signals-only | --replay-only [--only <run>]]   -> research/friendroc/frlive_parity.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import take, rnd
from frfamily import signals, outcomes, LEV
from frpay import mask
import shutil, tempfile

from paperbot import combo as C
from paperbot import friendsig as FS
from paperbot.livereplay import _Clock, _Fund, file_brackets, file_specs
from paperbot.notify import NullNotifier
from paperbot.store3 import Store3

DEPLOY = os.path.join(REPO, "deploy", "combo.friend.json")
SIG_FROM = ms("2026-06-01")
REPLAY_FROM = ms("2026-09-01")
TFS = ("15m", "1h", "4h")
WHY = {0: "SL", 1: "LOCK", 3: "OPEN"}


def served():
    """{tf: {coin: rows}} of the research's bars (open ms, o, h, l, c, v)."""
    return {tf: {c: bars(c, tf)[["ts", "open", "high", "low", "close", "volume"]].to_numpy(float) for c in COINS}
            for tf in TFS}


def fetch_of(A, clock):
    """Binance's klines answer from the research's bars at ``clock.now``: rows from ``start``, at most ``limit``, the
    bar still forming included (KlineBars keeps only the settled ones)."""
    def fetch(symbol, tf, start, limit):
        a = A[tf][symbol]
        i0 = int(np.searchsorted(a[:, 0], int(start)))
        i1 = min(int(np.searchsorted(a[:, 0], clock.now, side="right")), i0 + int(limit))
        return [[int(r[0])] + [float(x) for x in r[1:]] for r in a[i0:i1]]
    return fetch


class _M:                                                 # a member as combo.resolve_members makes it
    kind, tf = "friend", "15m"

    def __init__(self, higher="roc_any"):
        self.higher = higher
        self.label = "FRIEND_ROC@15m" + ("" if higher == "roc_any" else f"~{higher}")


def and_research():
    """The research's own "rsi_roc_all" signals: research/friendroc/code/frand.py and_signals("15m", "lt50") (PREREG7,
    commit 325ef62). From this folder once that branch is merged, else from the copy of that commit's file in the
    session scratchpad (git show 325ef62:research/friendroc/code/frand.py > OUT/frand_ref/frand.py)."""
    try:
        import frand
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location("frand", os.path.join(OUT, "frand_ref", "frand.py"))
        frand = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frand)
    return frand.and_signals("15m", "lt50"), frand.__file__


# ====================================================================== 1. signals and gates
def signal_check(A, R, mode="roc_any"):
    clock = _Clock(0)
    kb = FS.KlineBars(fetch_of(A, clock), clock)
    fs = FS.FriendSignals([_M(mode)], COINS, kb)
    gates = FS.FriendGates(FS.ADX_DEFAULT, FS.QUIET_DEFAULT, kb)
    t0 = time.time()
    rows, unread = [], 0
    for b in range(SIG_FROM, DATA_END, 15 * MIN):
        clock.now = b + 5_000                              # the bar close, as the runner reads it
        live = []
        for coin in COINS:
            r = fs.read("15m", coin, b, mode)
            if r is None:
                unread += 1
            elif r["side"]:
                live.append((coin, r))
        clock.now = b + MIN + 5_000                        # the entry minute, as _submit_due asks the gates
        for coin, r in live:
            ia, iq = {}, {}
            wa = gates._adx_block(coin, b, ia)
            wq = gates._quiet_block(coin, "15m", b, iq)
            rows.append({"t": b, "coin": COINS.index(coin), "side": r["side"], "adx_live": (ia.get("adx") or {}).get("adx"),
                         "vr_live": (iq.get("quiet") or {}).get("ratio"), "f4_live": wa == "", "v_live": wq == "",
                         "why": wa or wq, "e21_live": r["values"]["e21"], "e52_live": r["values"]["e52"],
                         "rsi_live": r["values"]["rsi"], "roc_live": r["values"]["roc"],
                         "adx_sig": r["values"].get("adx4h"), "vr_sig": r["values"].get("vol_ratio"),
                         "h1_rsi_live": r["values"]["higher"][0].get("rsi"), "h4_rsi_live": r["values"]["higher"][1].get("rsi")})
        if (b - SIG_FROM) % (14 * DAY) == 0:
            print("signals", pd.Timestamp(b, unit="ms"), len(rows), f"{time.time() - t0:.0f}s", flush=True)
    L = pd.DataFrame(rows)
    Rw = R[(R.t >= SIG_FROM) & (R.t < DATA_END)].reset_index(drop=True)
    Rw = Rw.assign(f4=mask(Rw, "F4"), v=mask(Rw, "V"), both=mask(Rw, "F4+V"))
    key = lambda d: set(zip(d.t.astype(np.int64), d.coin.astype(int), d.side.astype(int)))   # noqa: E731
    kl, kr = key(L), key(Rw)
    M = Rw.merge(L, on=["t", "coin", "side"], how="inner")
    # the research's indicator values at the signal bars (full history from the coin's first bar)
    vals = []
    for ci, coin in enumerate(COINS):
        df = bars(coin, "15m")
        I = _ind(df.close.to_numpy(float))
        bc = df.ts.to_numpy(np.int64) + 15 * MIN
        sub = M[M.coin == ci]
        j = np.searchsorted(bc, sub.t.to_numpy(np.int64))
        vals.append(pd.DataFrame({"t": sub.t.to_numpy(), "coin": ci, "e21_r": I["e21"][j], "e52_r": I["e52"][j],
                                  "rsi_r": I["rsi"][j], "roc_r": I["roc"][j]}))
    M = M.merge(pd.concat(vals), on=["t", "coin"])
    rel = lambda a, b: float(np.nanmax(np.abs(a.astype(float) - b.astype(float)) / np.abs(b.astype(float))))  # noqa: E731
    f4_r, v_r = M.f4.to_numpy(bool), M.v.to_numpy(bool)
    diff_rows = lambda m: M[m][["t", "coin", "side", "adx4h", "adx_live", "vr", "vr_live", "why"]].assign(   # noqa: E731
        t=lambda d: [str(pd.Timestamp(int(x), unit="ms")) for x in d.t], coin=lambda d: [COINS[int(c)] for c in d.coin]
    ).to_dict("records")
    out = {"from_utc": str(pd.Timestamp(SIG_FROM, unit="ms")), "to_utc": str(pd.Timestamp(DATA_END, unit="ms")),
           "bar_reads": int(len(range(SIG_FROM, DATA_END, 15 * MIN)) * 6), "unreadable": unread,
           "research_signals": len(kr), "live_signals": len(kl), "same": len(kl & kr),
           "only_research": sorted([[str(pd.Timestamp(int(t), unit="ms")), COINS[c], s] for t, c, s in kr - kl]),
           "only_live": sorted([[str(pd.Timestamp(int(t), unit="ms")), COINS[c], s] for t, c, s in kl - kr]),
           "by_block": Rw.block.replace("", "free").value_counts().to_dict(),
           "f4_agree": int((M.f4_live.to_numpy(bool) == f4_r).sum()), "v_agree": int((M.v_live.to_numpy(bool) == v_r).sum()),
           "both_agree": int(((M.f4_live & M.v_live).to_numpy(bool) == M.both.to_numpy(bool)).sum()),
           "pass_research": int(M.both.sum()), "pass_live": int((M.f4_live & M.v_live).sum()),
           "f4_differ": diff_rows(M.f4_live.to_numpy(bool) != f4_r), "v_differ": diff_rows(M.v_live.to_numpy(bool) != v_r),
           "adx_max_abs_diff": rnd(float(np.nanmax(np.abs(M.adx_live.astype(float) - M.adx4h.astype(float)))), 12),
           "adx_signal_vs_gate_max_abs_diff": rnd(float(np.nanmax(np.abs(M.adx_live.astype(float) - M.adx_sig.astype(float)))), 12),
           "vr_max_rel_diff": rnd(rel(M.vr_live, M.vr), 15), "e21_max_rel_diff": rnd(rel(M.e21_live, M.e21_r), 15),
           "e52_max_rel_diff": rnd(rel(M.e52_live, M.e52_r), 15),
           "rsi_max_abs_diff": rnd(float(np.nanmax(np.abs(M.rsi_live - M.rsi_r))), 12),
           "roc_max_abs_diff": rnd(float(np.nanmax(np.abs(M.roc_live - M.roc_r))), 12),
           "unread_gates": int(M.why.str.contains("못 읽음").sum()), "seconds": round(time.time() - t0), "mode": mode}
    if "1h_rsi" in M:                                         # the research frame has the higher bars' RSI26 (frand)
        out["higher_rsi_max_abs_diff"] = rnd(float(np.nanmax(np.abs(np.r_[M.h1_rsi_live.astype(float) - M["1h_rsi"],
                                                                            M.h4_rsi_live.astype(float) - M["4h_rsi"]]))), 12)
    print("signals", {k: v for k, v in out.items() if not k.endswith("differ") and not k.startswith("only")}, flush=True)
    return out


# ====================================================================== 2. the replay
def research_trades(R):
    R = R[R.block == ""].reset_index(drop=True)
    O = outcomes(R, -0.75, 0.20, 0.10)["own"]
    t = R.t.to_numpy(np.int64)
    use = mask(R, "F4+V") & (t >= REPLAY_FROM) & (t < DATA_END)
    idx = take(t, O["k"], use)
    return [{"entry": int(t[q]), "coin": COINS[int(R.coin.iat[q])], "side": int(R.side.iat[q]),
             "exit": int(t[q] + int(O["k"][q]) * MIN), "roe": float(LEV * O["r"][q]), "why": WHY.get(int(O["why"][q]), "?"),
             "vr": float(R.vr.iat[q]), "adx4h": float(R.adx4h.iat[q])} for q in idx]


def one_tier(brackets):
    """Diagnostic only (never the bot's): each coin's first Binance bracket for any size, so no entry is refused for its
    size; what is left is the rest of the engine."""
    from paperbot.margin import BracketTier, Brackets
    out = {}
    for s, b in brackets.items():
        t = b.tiers[0]
        out[s] = Brackets([BracketTier(1e15, t.max_leverage, t.mmr, t.cum)])
    return out


def replay(A, taker, tag, flat=False):
    cfg_raw = json.load(open(DEPLOY, encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix=f"frlivepar_{tag}_", dir=OUT)
    try:
        cfg_raw.update(paper_db=os.path.join(tmp, "paper3.db"), db=os.path.join(tmp, "friend.db"), telegram=False)
        cfg = C.ComboConfig.from_dict(cfg_raw)
        assert not cfg.problems(), cfg.problems()
        members = C.resolve_members(cfg.members, cfg.picks_file)
        syms = list(cfg.symbols)
        settings = C.settings_of(cfg, **({} if taker is None else {"taker_fee": taker}))
        brackets, _src = file_brackets(syms)
        if flat:
            brackets = one_tier(brackets)
        specs = file_specs(syms)
        paper = Store3(cfg.paper_db)
        paper.commit()
        store = Store3(cfg.db)
        book = C.build_book(cfg, settings, brackets, store, NullNotifier(), specs)
        clock = _Clock(REPLAY_FROM)
        kb = FS.KlineBars(fetch_of(A, clock), clock)
        friend = FS.FriendSignals(members, syms, kb)
        gates = FS.FriendGates(cfg.adx_gate, cfg.quiet_gate, kb)
        rates = {}
        G = {c: grid(c) for c in COINS}
        for c in COINS:
            f = G[c]["fund"]
            for j in np.flatnonzero(np.nan_to_num(f) != 0):
                tt = T0 + int(j) * MIN
                if tt >= REPLAY_FROM:
                    rates.setdefault(tt, {})[c] = float(f[j])
        runner = C.ComboRunner(cfg, members, book, store, NullNotifier(), None, clock, lambda: {}, _Fund(rates),
                               gates=gates, friend=friend)
        runner.cursor = 0
        book.last_ts = REPLAY_FROM - MIN
        t0 = time.time()
        for t in range(REPLAY_FROM, DATA_END, MIN):
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
            paper.commit()
            clock.now = t + MIN + 5_000
            runner.poll()
            if (t - REPLAY_FROM) % (7 * DAY) == 0:
                print(tag, pd.Timestamp(t, unit="ms"), "trades", len(book.engines[C.ACCOUNT].trades),
                      f"{time.time() - t0:.0f}s", flush=True)
        acct = book.engines[C.ACCOUNT]
        trades = [{"entry": int(x.entry_time), "coin": x.symbol, "side": int(x.side),
                   "exit": int(x.exit_time) - int(x.exit_time) % MIN, "reason": x.exit_reason, "roe": float(x.roe),
                   "pnl": float(x.pnl), "equity_after": float(x.equity_after), "lock": x.lock_roe} for x in acct.trades]
        outs = {}
        for st, why in store.conn.execute("SELECT status, reason FROM outcomes WHERE account_id = ?", (C.ACCOUNT,)):
            k = f"{st}: {(why or '')[:40]}"
            outs[k] = outs.get(k, 0) + 1
        eq = [(int(x.exit_time), float(x.equity_after)) for x in book.engines[C.ACCOUNT].trades]
        refused = []
        for ts, sym, d in store.conn.execute("SELECT step_ts, symbol, data FROM outcomes WHERE account_id = ? AND "
                                             "status = 'REJECTED' ORDER BY step_ts", (C.ACCOUNT,)):
            det = json.loads(d).get("detail") or {}
            wallet = ([w for t_, w in eq if t_ < ts] or [float(cfg.initial_equity)])[-1]
            refused.append({"t_kst": str(pd.Timestamp(int(ts) + KST, unit="ms"))[:16], "coin": sym, "wallet": round(wallet, 2),
                            "why": " / ".join(str(x) for x in det.get("reasons") or [])[:160]})
        filt = {}
        for (d,) in store.conn.execute("SELECT data FROM signal_log WHERE status = 'FILTERED'"):
            g = C.gate_group(str((json.loads(d) or {}).get("why") or ""))
            filt[g] = filt.get(g, 0) + 1
        losses = [dict(zip(("entry_time", "symbol", "line"), r)) for r in
                  store.conn.execute("SELECT entry_time, symbol, line FROM loss_review ORDER BY exit_time")] \
            if store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'loss_review'").fetchone() else []
        alerts = [r[0] for r in store.conn.execute("SELECT text FROM alerts") if not str(r[0]).startswith("[COMBO")]
        pos = acct.position
        return {"trades": trades, "outcomes": outs, "filtered": filt, "counts": runner.counts, "wallet": float(acct.wallet),
                "initial": float(cfg.initial_equity), "loss_lines": losses, "alerts": alerts[:20], "n_alerts": len(alerts),
                "seconds": round(time.time() - t0), "round_trip": settings.round_trip_cost,
                "refused": refused,
                "open": None if pos is None else {"entry": int(pos.entry_time), "coin": pos.symbol, "side": int(pos.side)}}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compare(res, live):
    kst = lambda v: str(pd.Timestamp(int(v) + KST, unit="ms"))[:16]          # noqa: E731
    rk = {(x["entry"], x["coin"], x["side"]): x for x in res}
    lk = {(x["entry"], x["coin"], x["side"]): x for x in live["trades"]}
    if live["open"]:
        o = live["open"]
        lk.setdefault((o["entry"], o["coin"], o["side"]), {"entry": o["entry"], "coin": o["coin"], "side": o["side"],
                                                           "exit": None, "reason": "OPEN", "roe": None})
    both = sorted(set(rk) & set(lk))
    rows = []
    for k in both:
        a, b = rk[k], lk[k]
        rows.append({"entry_kst": kst(k[0]), "coin": k[1][:-4], "side": k[2], "why_research": a["why"], "why_live": b["reason"],
                     "exit_research_kst": kst(a["exit"]), "exit_live_kst": None if b["exit"] is None else kst(b["exit"]),
                     "same_exit": b["exit"] == a["exit"], "roe_research_pct": round(a["roe"] * 100, 3),
                     "roe_live_pct": None if b["roe"] is None else round(b["roe"] * 100, 3)})
    d = np.array([r["roe_live_pct"] - r["roe_research_pct"] for r in rows if r["roe_live_pct"] is not None
                  and r["why_research"] != "OPEN" and r["same_exit"]])
    wins = sum(1 for x in live["trades"] if x["roe"] > 0)
    return {"research_n": len(res), "research_wins": sum(1 for x in res if x["roe"] > 0),
            "live_n": len(live["trades"]) + (1 if live["open"] else 0), "live_wins": wins, "matched": len(both),
            "same_exit": sum(r["same_exit"] for r in rows),
            "roe_diff_pct_same_exit": {"n": int(len(d)), "mean": rnd(d.mean(), 4) if len(d) else None,
                                       "min": rnd(d.min(), 4) if len(d) else None, "max": rnd(d.max(), 4) if len(d) else None},
            "only_research": [{"entry_kst": kst(k[0]), "coin": k[1], "side": k[2], **{q: rk[k][q] for q in ("why", "roe")}}
                              for k in sorted(set(rk) - set(lk))],
            "only_live": [{"entry_kst": kst(k[0]), "coin": k[1], "side": k[2], "reason": lk[k]["reason"], "roe": lk[k]["roe"]}
                          for k in sorted(set(lk) - set(rk))],
            "exit_differ": [r for r in rows if not r["same_exit"]],
            "live_mult": round(live["wallet"] / live["initial"], 4), "live_outcomes": live["outcomes"],
            "live_filtered": live["filtered"], "counts": live["counts"], "open_at_end": live["open"],
            "round_trip": live["round_trip"], "n_alerts": live["n_alerts"], "alerts": live["alerts"], "refused": live["refused"],
            "loss_lines": live["loss_lines"][:12], "seconds": live["seconds"], "rows": rows}


RUNS = (("cost_research", 0.00042, False), ("cost_paper_default", None, False), ("diag_one_tier", 0.00042, True))


def main():
    path = os.path.join(RES_DIR, "frlive_parity.json")
    A = served()
    R = signals("15m")
    print("research signals", len(R), flush=True)
    if "--replay-only" in sys.argv:                          # the signal part kept from the last full run
        out = json.load(open(path, encoding="utf-8"))
    else:
        out = {"data_end_utc": str(pd.Timestamp(DATA_END, unit="ms")), "signals": signal_check(A, R)}
        RA, src = and_research()
        print("research rsi_roc_all signals", len(RA), src, flush=True)
        out["signals_rsi_roc_all"] = {"research_code": "research/friendroc/code/frand.py and_signals('15m', 'lt50') "
                                                       "(commit 325ef62)", **signal_check(A, RA, "rsi_roc_all")}
    if "--signals-only" not in sys.argv:
        res = research_trades(R)
        out["research"] = {"n": len(res), "wins": sum(1 for x in res if x["roe"] > 0), "from_utc": str(pd.Timestamp(REPLAY_FROM, unit="ms"))}
        print("research", out["research"], flush=True)
        for tag, taker, flat in RUNS:
            if "--only" in sys.argv and tag not in sys.argv:
                continue
            live = replay(A, taker, tag, flat)
            out[tag] = compare(res, live)
            print(tag, {k: v for k, v in out[tag].items() if k not in ("rows", "loss_lines", "alerts")}, flush=True)
            json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=str)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
