"""참고 read (after the fact, not a test of the strategy): the live paper bot's own code with the owners' first final rule
of 10/24 night (NIGHT1 below, in deploy/combo.friend.json for an hour that night before the owners chose by the last 19
days, frlive_parity3.py: FRIEND_ROC 15m with ``higher`` "rsi_roc_1h", 35x on every coin, the exchange screen's -20 % ROE
stop before fees, the ladder 12 -> 10 then 5 % steps, no extra gate, the usual entry blocks, one position) against the
research's version of the same rule.

1. signals: every 15m bar close of the six coins from 2026-06-01 to the data end through FriendSignals.read (the
   research's own bars served as Binance would serve them, frlive_parity.served / fetch_of) vs the research rows of
   research/friendroc/code/frhtrend.py raw15(coin) + frhtrend2.add_rsi with side-signed roc_1h > 0 and rsi_1h > 0
   (blocked rows included); the 1h ROC9 / RSI26 and the 15m values side by side;
2. replay: 2026-09-01 .. the data end, ComboRunner + ComboEngine with the deploy file minute by minute (frlive_parity.replay)
   vs frladder35.outcomes(R, -0.20 - 35 x COST, 0.10) on the rule's unblocked rows and the one-position pass (frrun.take):
   entry minute, coin, side, exit minute, net ROE; at the research's cost (taker 0.042 % + slippage 0.02 % each side) and
   at the paper's default taker 0.05 %;
3. the sizes at which Binance's brackets (research/fullgrid/exchange.json) change an entry of the deploy file (35x, the
   0.571 % stop): refused or cut, per coin.

The research code is read from the research checkout (RESEARCH_CODE below, branch claude/keen-pasteur-wav02u, PREREG12 /
PREREG13 / PREREG11 files), never copied into the bot; its shared helpers (frcore, frrun, frloss, frdeep, frfamily) are the
same files as this folder's.

    python3 -I frlive_parity2.py [--signals-only | --replay-only]   -> research/friendroc/frlive_parity2.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frlive_parity import *                                       # frcore's names, served, fetch_of, replay, compare, _M
from frlive_parity import _M
from paperbot.livereplay import _Clock
from frcore import _ind
from frloss import COST

RESEARCH_CODE = os.environ.get("FR_RESEARCH_CODE", "/home/user/crypto-bot-research/research/friendroc/code")
LEV35 = 35
MODE = "rsi_roc_1h"
NIGHT1 = {"members": [{"strategy": "FRIEND_ROC", "tf": "15m", "higher": MODE}], "leverage": {"BTCUSDT": 35, "default": 35},
          "max_loss_frac": 0.15, "stop": {"mode": "roe", "roe": 0.2, "net": False},
          "ladder": {"first_lock": 0.1, "trigger_gap": 0.02, "step": 0.05}, "adx_gate": None, "quiet_gate": None}


def research_rule():
    """All 15m friend signal rows with the side-signed 1h ROC9 / RSI26 - 50 (frhtrend.raw15 + frhtrend2.add_rsi), the
    entry blocks, and the rule mask (both > 0)."""
    if RESEARCH_CODE not in sys.path:
        sys.path.append(RESEARCH_CODE)
    import frhtrend
    import frhtrend2
    A = pd.concat([frhtrend.raw15(c) for c in COINS], ignore_index=True)
    A = A.iloc[np.lexsort((A.coin.to_numpy(), A.t.to_numpy()))].reset_index(drop=True)
    A = frhtrend2.add_rsi(A)
    A["block"] = [blocked(int(x)) for x in A.t.to_numpy()]
    with np.errstate(invalid="ignore"):
        rule = (A.roc_1h.to_numpy() > 0) & (A.rsi_1h.to_numpy() > 0)
    return A, rule, frhtrend.__file__


def signal_check(A, R):
    clock = _Clock(0)
    kb = FS.KlineBars(fetch_of(A, clock), clock)
    fs = FS.FriendSignals([_M(MODE)], COINS, kb)
    t0 = time.time()
    rows, unread = [], 0
    for b in range(SIG_FROM, DATA_END, 15 * MIN):
        clock.now = b + 5_000
        for coin in COINS:
            r = fs.read("15m", coin, b, MODE)
            if r is None:
                unread += 1
            elif r["side"]:
                h = r["values"]["higher"][0]
                rows.append({"t": b, "coin": COINS.index(coin), "side": r["side"], "e21_live": r["values"]["e21"],
                             "e52_live": r["values"]["e52"], "rsi_live": r["values"]["rsi"], "roc_live": r["values"]["roc"],
                             "h_roc_live": h["roc"], "h_rsi_live": h["rsi"], "h_close": h["close"]})
        if (b - SIG_FROM) % (14 * DAY) == 0:
            print("signals", pd.Timestamp(b, unit="ms"), len(rows), f"{time.time() - t0:.0f}s", flush=True)
    L = pd.DataFrame(rows)
    key = lambda d: set(zip(d.t.astype(np.int64), d.coin.astype(int), d.side.astype(int)))   # noqa: E731
    kl, kr = key(L), key(R)
    M = R.merge(L, on=["t", "coin", "side"], how="inner")
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
    s = M.side.to_numpy(float)
    rel = lambda a, b: float(np.nanmax(np.abs(a.astype(float) - b.astype(float)) / np.abs(b.astype(float))))  # noqa: E731
    fmt = lambda ks: sorted([[str(pd.Timestamp(int(t), unit="ms")), COINS[c], d] for t, c, d in ks])          # noqa: E731
    out = {"mode": MODE, "from_utc": str(pd.Timestamp(SIG_FROM, unit="ms")), "to_utc": str(pd.Timestamp(DATA_END, unit="ms")),
           "bar_reads": int(len(range(SIG_FROM, DATA_END, 15 * MIN)) * 6), "unreadable": unread,
           "research_signals": len(kr), "live_signals": len(kl), "same": len(kl & kr),
           "only_research": fmt(kr - kl), "only_live": fmt(kl - kr),
           "by_block": R.block.replace("", "free").value_counts().to_dict(),
           "h1_roc_max_abs_diff": rnd(float(np.nanmax(np.abs(s * M.h_roc_live.astype(float) - M.roc_1h))), 12),
           "h1_rsi_max_abs_diff": rnd(float(np.nanmax(np.abs(s * (M.h_rsi_live.astype(float) - 50) - M.rsi_1h))), 12),
           "e21_max_rel_diff": rnd(rel(M.e21_live, M.e21_r), 15), "e52_max_rel_diff": rnd(rel(M.e52_live, M.e52_r), 15),
           "rsi_max_abs_diff": rnd(float(np.nanmax(np.abs(M.rsi_live - M.rsi_r))), 12),
           "roc_max_abs_diff": rnd(float(np.nanmax(np.abs(M.roc_live - M.roc_r))), 12), "seconds": round(time.time() - t0)}
    print("signals", {k: v for k, v in out.items() if not k.startswith("only")}, flush=True)
    return out


def research_trades(A, rule):
    import frladder35
    t_all = A.t.to_numpy(np.int64)
    R = A[rule & (A.block == "").to_numpy() & (t_all >= REPLAY_FROM) & (t_all < DATA_END)].reset_index(drop=True)
    O = frladder35.outcomes(R, -0.20 - LEV35 * COST, 0.10)
    assert frladder35.LEV == LEV35
    t = R.t.to_numpy(np.int64)
    idx = take(t, O["k"], np.ones(len(R), bool))
    return [{"entry": int(t[q]), "coin": COINS[int(R.coin.iat[q])], "side": int(R.side.iat[q]),
             "exit": int(t[q] + int(O["k"][q]) * MIN), "roe": float(LEV35 * O["r"][q]), "why": WHY.get(int(O["why"][q]), "?")}
            for q in idx]


def tier_check():
    """Wallet sizes at which the deploy file's entry is cut (a bracket below 35x) or refused (the stop too close to the
    liquidation price), per coin and side, from $100 to $5,000,000 in 5 % steps (prices of 2026-10)."""
    from paperbot.models import Signal
    cfg = C.ComboConfig.from_dict({**json.load(open(DEPLOY, encoding="utf-8")), **NIGHT1})
    st = C.settings_of(cfg)
    syms = list(cfg.symbols)
    br, _src = file_brackets(syms)
    specs = file_specs(syms)
    pol = C.FixedLevPolicy(st, cfg)
    px = {"BTCUSDT": 110000.0, "ETHUSDT": 3900.0, "SOLUSDT": 190.0, "DOGEUSDT": 0.19, "LTCUSDT": 95.0, "BCHUSDT": 530.0}
    out = {}
    for s in syms:
        for side in (1, -1):
            rows, prev, w = [], None, 100.0
            while w <= 5_000_000:
                fill = px[s] * (1 + side * st.slippage_frac)
                sig = Signal(ts=0, symbol=s, timeframe="15m", strategy_id="FRIEND_ROC", side=side,
                             stop_price=px[s] * (1 - side * 0.20 / LEV35), atr=px[s] * 0.003, meta={})
                d = pol.size(w, sig, fill, br[s], specs[s])
                state = "ok" if d.ok and not d.reasons else ("cut" if d.ok else "refused")
                if state != prev:
                    rows.append({"wallet_from": round(w), "state": state, "notional": round(d.qty * fill) if d.ok else None,
                                 "why": (d.reasons or [""])[-1][:120]})
                    prev = state
                w *= 1.05
            out[f"{s} {'long' if side > 0 else 'short'}"] = rows
    return out


def main():
    path = os.path.join(RES_DIR, "frlive_parity2.json")
    A0 = served()
    A, rule, src = research_rule()
    R = A[rule].reset_index(drop=True)
    print("research rule rows", int(rule.sum()), src, flush=True)
    if "--replay-only" in sys.argv:
        out = json.load(open(path, encoding="utf-8"))
    else:
        out = {"data_end_utc": str(pd.Timestamp(DATA_END, unit="ms")), "config": {**json.load(open(DEPLOY, encoding="utf-8")), **NIGHT1},
               "research_code": "frhtrend.raw15 + frhtrend2.add_rsi (roc_1h > 0 and rsi_1h > 0); frladder35.outcomes "
                                "(stop -0.20 - 35 x COST, first lock 0.10, steps 0.05, trigger gap 0.02) + frrun.take; "
                                "research checkout branch claude/keen-pasteur-wav02u",
               "signals": signal_check(A0, R[(R.t >= SIG_FROM) & (R.t < DATA_END)].reset_index(drop=True))}
    out["tiers"] = tier_check()
    if "--signals-only" not in sys.argv:
        res = research_trades(A, rule)
        out["research"] = {"n": len(res), "wins": sum(1 for x in res if x["roe"] > 0),
                           "from_utc": str(pd.Timestamp(REPLAY_FROM, unit="ms"))}
        print("research", out["research"], flush=True)
        for tag, taker in (("cost_research", 0.00042), ("cost_paper_default", None)):
            live = replay(A0, taker, tag, over=NIGHT1)
            out[tag] = compare(res, live)
            print(tag, {k: v for k, v in out[tag].items() if k not in ("rows", "loss_lines", "alerts")}, flush=True)
            json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=str)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
