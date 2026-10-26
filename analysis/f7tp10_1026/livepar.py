"""레인지 봇 parity (owners 10/26 "진행해줘"): the live bot's own code (paperbot/combo.py ComboRunner + ComboEngine with
paperbot/rangebot.py RangeRunner, deploy/combo.range.json) replayed minute by minute over the rule bot's live window
(2026-10-06 03:35 .. 10-25 09:00 KST; ``--window oct``: 10-01 .. 10-25), against the research engine's set-up F1 (hunt.py: FINAL_KO.md's structure) on the
same 5-minute bars.

The replay: every 5-minute bar of the six coins becomes five 1-minute bars in a temporary paper3.db (live_bars, mark = last):
the bar's open / high / low / close in its first minute, then four flat minutes at its close (volume on the first), so the
1-minute engine sees what the research's 5-minute engine sees, in the same order (the stop checked first on a bar that
holds both). The custom signals are computed by the bot's CustomSignals from that history (its 5m history bootstrapped with
the 36,000 5-minute bars before the window), the supertrends by RangeRunner.supertrend; ComboRunner.poll() steps one minute
a call with the clock at the minute's close + 65 s (as live). Funding is paid at the 5-minute bar that holds it (the data's
``fund``). Prices of the book are not available: every entry fills at the entry minute's open + slippage (the research's
fill). The live site's state is not written (display only).

Trades are compared one by one (entry minute, coin, side, exit reason, net ROE) and the wallet multiples.
Known differences, by design: the bot checks the weekend / macro / NYSE-open pauses again at the entry minute (the research
at the signal only), and its liquidation check is at the signal with the signal bar's close (the research's at the fill).
Run: python3 livepar.py --bars FIVE5M_DIR --work WORK_DIR   -> livepar.json next to this file"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import prep as P  # noqa: E402  (puts the repository on sys.path)
import hunt as H  # noqa: E402
import pick as PK  # noqa: E402

from paperbot import combo as C  # noqa: E402
from paperbot import rangebot as RB  # noqa: E402
from paperbot.config import DS_WINDOW_5M  # noqa: E402
from paperbot.livereplay import _Clock, _Fund, file_brackets, file_specs  # noqa: E402
from paperbot.notify import NullNotifier  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

MIN, FIVE = 60_000, 300_000
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEPLOY = os.path.join(REPO, "deploy", "combo.range.json")
F1 = dict(H.BASE, commit=True, btc=True, k=0.20, wait_h=1)


def load5(bars: str) -> dict:
    out = {}
    for c in P.COINS:
        z = np.load(os.path.join(bars, "5m", f"{c}.npz"))
        out[c] = {k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "fund")}
    return out


def write_minutes(store: Store3, m5: dict, a: int, b: int) -> int:
    """The 5-minute bars opening in [a, b) as 1-minute bars; returns the last minute written."""
    last = a
    for c, z in m5.items():
        i0, i1 = int(np.searchsorted(z["ts"], a)), int(np.searchsorted(z["ts"], b))
        rows = []
        for i in range(i0, i1):
            t, o, h, l, cl, v = (int(z["ts"][i]), float(z["o"][i]), float(z["h"][i]), float(z["l"][i]), float(z["c"][i]),
                                 float(z["v"][i]))
            for k in range(5):
                tt = t + k * MIN
                bar = (o, h, l, cl, v) if k == 0 else (cl, cl, cl, cl, 0.0)
                rows.append({"ts": tt, "symbol": c, "open": bar[0], "high": bar[1], "low": bar[2], "close": bar[3],
                             "volume": bar[4], "mark_open": bar[0], "mark_high": bar[1], "mark_low": bar[2],
                             "mark_close": bar[3], "close_time": tt + MIN - 1, "processed_at": tt + MIN + 5000})
                last = max(last, tt)
        store.live_bars(rows)
    store.commit()
    return last


def replay(bars: str, a: int, b: int, tmp: str) -> dict:
    m5 = load5(bars)
    end = min(int(z["ts"][-1]) for z in m5.values()) + FIVE
    paper = Store3(os.path.join(tmp, "paper3.db"))
    last = write_minutes(paper, m5, a, end)
    raw = json.load(open(DEPLOY, encoding="utf-8"))
    raw.update(paper_db=os.path.join(tmp, "paper3.db"), db=os.path.join(tmp, "range.db"), telegram=False, flip_twin=False)
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == [], cfg.problems()
    members = C.resolve_members(cfg.members, cfg.picks_file)
    syms = list(cfg.symbols)
    brackets, _src = file_brackets(syms)
    specs = file_specs(syms)
    store = Store3(cfg.db)
    note = NullNotifier()
    book = C.build_book(cfg, C.settings_of(cfg), brackets, store, note, specs)
    custom = C.CustomSignals(members, syms)
    need = DS_WINDOW_5M["1h"] + 12
    for c in syms:
        z = m5[c]
        i1 = int(np.searchsorted(z["ts"], a))
        i0 = max(0, i1 - need)
        custom.bootstrap(c, [(int(z["ts"][i]), z["o"][i], z["h"][i], z["l"][i], z["c"][i], z["v"][i]) for i in range(i0, i1)])
    rates: dict = {}
    for c in syms:
        z = m5[c]
        for i in np.flatnonzero((z["ts"] >= a) & (z["fund"] != 0.0)):
            rates.setdefault(int(z["ts"][i]), {})[c] = float(z["fund"][i])
    clock = _Clock(a)
    C.read_paper = functools.partial(C.read_paper, max_minutes=1)    # one minute a poll, the clock at its close
    run = RB.RangeRunner(cfg, members, book, store, note, custom, now_ms=clock, prices=lambda: {}, funding=_Fund(rates))
    run._snapshot = lambda ts: None                      # the live site's state only
    run.cursor, book.last_ts = 0, a - MIN
    t0, n = time.time(), 0
    while book.last_ts < last:
        clock.now = int(book.last_ts) + MIN + 65_000
        run.poll()
        n += 1
        if n % 2880 == 0:
            print(f"replay {time.strftime('%m-%d %H:%M', time.gmtime(book.last_ts / 1000))} UTC, {time.time() - t0:.0f}s",
                  flush=True)
    e = book.engines[C.ACCOUNT]
    trades = [{"t": int(t.entry_time), "coin": t.symbol, "side": int(t.side), "reason": t.exit_reason, "roe": float(t.roe),
               "exit": int(t.exit_time), "pnl": float(t.pnl)} for t in e.trades if int(t.entry_time) < b]
    log = [dict(zip(("bar_close", "symbol", "side", "status", "data"), r)) for r in store.conn.execute(
        "SELECT bar_close, symbol, side, status, data FROM signal_log ORDER BY id")]
    out = {"trades": trades, "wallet": float(e.wallet), "initial": float(cfg.initial_equity), "signals": log,
           "open": e.position is not None}
    store.close()
    paper.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    windows = {**PK.LIVE, "oct": H.OCT}
    ap.add_argument("--window", default="rulebot", choices=sorted(windows))
    a = ap.parse_args(argv)
    wa, wb = windows[a.window]
    W = H.World(a.bars, a.work)
    T, s = H.run(W, F1, wa, wb)
    res = [{"t": int(r.t), "coin": r.coin, "side": int(r.side), "reason": r.reason, "roe": float(r.roe),
            "armed": int(round(r.t - r.wait_h * H.HOUR))} for r in T.itertuples()]
    print("research F1", a.window, s, flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        bot = replay(a.bars, wa, wb, tmp)
    bt = bot["trades"]
    key = lambda x: (x["t"], x["coin"], x["side"])  # noqa: E731
    rk, bk = {key(x): x for x in res}, {key(x): x for x in bt}
    both = sorted(set(rk) & set(bk))
    only_r, only_b = sorted(set(rk) - set(bk)), sorted(set(bk) - set(rk))
    same_reason = sum(rk[k]["reason"] == bk[k]["reason"] for k in both)
    droe = [abs(rk[k]["roe"] - bk[k]["roe"]) for k in both]
    bw = sum(x["roe"] > 0 for x in bt)
    summary = {"window": a.window, "research": s, "bot": {"n": len(bt), "w": bw, "l": len(bt) - bw,
                                                        "x": bot["wallet"] / bot["initial"]},
               "matched": len(both), "same_exit": same_reason, "max_roe_diff": max(droe) if droe else None,
               "only_research": [rk[k] for k in only_r], "only_bot": [bk[k] for k in only_b],
               "bot_filtered": {}}
    for r in bot["signals"]:
        if r["status"] == "FILTERED":
            why = (json.loads(r["data"] or "{}").get("why") or "")[:14]
            summary["bot_filtered"][why] = summary["bot_filtered"].get(why, 0) + 1
    print(json.dumps({k: v for k, v in summary.items() if k not in ("only_research", "only_bot")}, ensure_ascii=False,
                     indent=1), flush=True)
    for k in only_r:
        x = rk[k]
        print("research only", time.strftime("%m-%d %H:%M", time.gmtime(k[0] / 1000)), "UTC", x, flush=True)
        # what the bot logged for that coin around the research's signal close
        for r in bot["signals"]:
            if r["symbol"] == x["coin"] and x["armed"] - 2 * H.HOUR <= int(r["bar_close"]) <= x["t"]:
                d = json.loads(r["data"] or "{}")
                print("   bot", time.strftime("%m-%d %H:%M", time.gmtime(int(r["bar_close"]) / 1000)), r["side"], r["status"],
                      (d.get("why") or "")[:120], flush=True)
        busy = [y for y in bt if y["t"] <= x["armed"] < y["exit"] + FIVE]
        if busy:
            print("   bot position then:", busy[0], flush=True)
    for k in only_b:
        print("bot only", time.strftime("%m-%d %H:%M", time.gmtime(k[0] / 1000)), bk[k], flush=True)
    summary["research_trades"], summary["bot_trades"] = res, bt
    summary["bot_signals"] = bot["signals"]
    json.dump(summary, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"livepar_{a.window}.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
