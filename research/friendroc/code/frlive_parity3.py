"""참고 read (after the fact, not a test of the strategy): the live paper bot's own code with the deploy file as the owners
chose it on 10/24 night by the last 19 days (deploy/combo.friend.json: FRIEND_ROC 15m with the friend's original
higher-bar rule "roc_any", 35x on every coin, net ROE -50 % stop, the ladder 12 -> 10 then 5 % steps, no extra gate, the
usual entry blocks, one position) against the research's version of the same structure.

1. signals: the member's rule is "roc_any", already checked bar by bar in frlive_parity.json ("signals": 5,654 / 5,654
   equal to frfamily.signals("15m") from 2026-06-01; the trade settings do not touch the signal); copied here;
2. replay: 2026-09-01 .. the data end, ComboRunner + ComboEngine with the deploy file minute by minute
   (frlive_parity.replay) vs research frladder35.outcomes(R, -0.50, 0.10) (35x, net ROE -50 % with costs and funding,
   first lock 10 %, steps 5 %, trigger gap 2 %) on the unblocked frfamily.signals("15m") rows and the one-position pass
   (frrun.take); at the research's cost (taker 0.042 % + slippage 0.02 % each side) and at the paper's default 0.05 %;
3. the wallet sizes at which Binance's brackets (research/fullgrid/exchange.json) change an entry of the deploy file:
   refused (the stop too close to the liquidation price) or cut (a bracket below 35x), per coin and side.

frladder35.py (and its frmanual2 / frbracket / frtrend4) is read from the research checkout (RESEARCH_CODE, branch
claude/keen-pasteur-wav02u, db95c92), never copied into the bot; the shared helpers are the same files as this folder's.

    python3 -I frlive_parity3.py   -> research/friendroc/frlive_parity3.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frlive_parity import *                                       # frcore's names, served, replay, compare, signals ...
from frlive_parity2 import RESEARCH_CODE

LEV35 = 35


def research_trades(R):
    if RESEARCH_CODE not in sys.path:
        sys.path.append(RESEARCH_CODE)
    import frladder35
    assert frladder35.LEV == LEV35
    t_all = R.t.to_numpy(np.int64)
    R = R[(R.block == "").to_numpy() & (t_all >= REPLAY_FROM) & (t_all < DATA_END)].reset_index(drop=True)
    O = frladder35.outcomes(R, -0.50, 0.10)
    t = R.t.to_numpy(np.int64)
    idx = take(t, O["k"], np.ones(len(R), bool))
    return [{"entry": int(t[q]), "coin": COINS[int(R.coin.iat[q])], "side": int(R.side.iat[q]),
             "exit": int(t[q] + int(O["k"][q]) * MIN), "roe": float(LEV35 * O["r"][q]), "why": WHY.get(int(O["why"][q]), "?")}
            for q in idx], frladder35.__file__


def tier_check(cfg_raw):
    """Wallet sizes at which an entry of ``cfg_raw`` is cut (a bracket below its leverage) or refused (the stop too close
    to the liquidation price), per coin and side, $100 .. $5,000,000 in 5 % steps (prices of 2026-10); the stop as
    ComboEngine._with_stop puts it."""
    from paperbot.models import Signal
    cfg = C.ComboConfig.from_dict(cfg_raw)
    st = C.settings_of(cfg)
    syms = list(cfg.symbols)
    br, _src = file_brackets(syms)
    specs = file_specs(syms)
    pol = C.FixedLevPolicy(st, cfg)
    px = {"BTCUSDT": 110000.0, "ETHUSDT": 3900.0, "SOLUSDT": 190.0, "DOGEUSDT": 0.19, "LTCUSDT": 95.0, "BCHUSDT": 530.0}
    out = {}
    for s in syms:
        lev = cfg.lev_of(s)
        frac = float(cfg.stop["roe"]) / lev - (st.round_trip_cost if cfg.stop_net else 0.0)
        for side in (1, -1):
            rows, prev, w = [], None, 100.0
            while w <= 5_000_000:
                fill = px[s] * (1 + side * st.slippage_frac)
                sig = Signal(ts=0, symbol=s, timeframe="15m", strategy_id="FRIEND_ROC", side=side,
                             stop_price=px[s] * (1 - side * frac), atr=px[s] * 0.003, meta={})
                d = pol.size(w, sig, fill, br[s], specs[s])
                state = "ok" if d.ok and not d.reasons else ("cut" if d.ok else "refused")
                if state != prev:
                    room = None
                    if d.ok:
                        room = round(side * (sig.stop_price - d.liq_price) / fill * 100, 3)
                    rows.append({"wallet_from": round(w), "state": state, "notional": round(d.qty * fill) if d.ok else None,
                                 "stop_to_liq_pct": room, "why": (d.reasons or [""])[-1][:120]})
                    prev = state
                w *= 1.05
            out[f"{s} {'long' if side > 0 else 'short'}"] = rows
    return out


def main():
    path = os.path.join(RES_DIR, "frlive_parity3.json")
    deploy = json.load(open(DEPLOY, encoding="utf-8"))
    assert [m.get("higher", "roc_any") for m in deploy["members"]] == ["roc_any"]
    first = json.load(open(os.path.join(RES_DIR, "frlive_parity.json"), encoding="utf-8"))
    out = {"data_end_utc": str(pd.Timestamp(DATA_END, unit="ms")), "deploy": deploy,
           "signals": {"from": "frlive_parity.json (roc_any vs frfamily.signals('15m'))",
                       **{k: v for k, v in first["signals"].items() if not k.endswith("differ")}},
           "tiers": tier_check(deploy)}
    A0 = served()
    R = signals("15m")
    res, src = research_trades(R)
    out["research_code"] = f"{src}: outcomes(R, -0.50, 0.10) + frrun.take on the unblocked frfamily.signals('15m') rows"
    out["research"] = {"n": len(res), "wins": sum(1 for x in res if x["roe"] > 0), "from_utc": str(pd.Timestamp(REPLAY_FROM, unit="ms"))}
    print("research", out["research"], flush=True)
    for tag, taker in (("cost_research", 0.00042), ("cost_paper_default", None)):
        live = replay(A0, taker, tag)
        out[tag] = compare(res, live)
        print(tag, {k: v for k, v in out[tag].items() if k not in ("rows", "loss_lines", "alerts")}, flush=True)
        json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=str)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
