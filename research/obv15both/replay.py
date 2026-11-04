"""OBV 히스토그램 전환 백테스트 (owners 11-04: "30분봉이랑 15분봉 추세macd 히스토그램이 추세가 같을때만 진입", then a backtest).
The plan and the pass/fail criteria were written before any run: research/obv15both/PLAN_KO.md.

Two rules, the bot's OWN code (paperbot/mixchop.py), the live config deploy/mixchop.live.json (the 레인지 봇's
deploy/mixrange.live.json is the same rule, coins and sizes; only the exchange and its fee differ):
- A: trend_both false (the 30m 추세 MACD histogram on the signal's side, as 11-02 .. 11-03)
- B: trend_both true  (the 15m one on the same side too, owners 11-04)

    python3 -I research/obv15both/replay.py download     # data.binance.vision monthly zips (sha256 checked) -> --data
    python3 -I research/obv15both/replay.py decide       # the bot's evaluate_friend at the OBV turns (cached in --data)
    python3 -I research/obv15both/replay.py dev          # the development period -> summary.json "dev"
    python3 -I research/obv15both/replay.py sealed       # the sealed period, ONCE, after dev is written -> "sealed"
    python3 -I research/obv15both/replay.py report       # REPORT_KO.md from summary.json (the plan's verdict)

Source: https://data.binance.vision/data/futures/um/monthly/klines/<SYMBOL>/<15m|30m|1m>/<SYMBOL>-<tf>-<YYYY-MM>.zip
(15m and 30m from 2024-09 for the 1,499 bars the bot reads, 1m from 2024-11), each checked against its .CHECKSUM.

How the bot's code is driven:
- decisions: FT.o4_pane on the whole 15m series marks the closes where the OBV histogram turns on the long / short side
  (green under 0, red over 0). At each of them the REAL mixchop.evaluate_friend runs on the 1,499 closed 15m bars and
  1,499 closed 30m bars the bot itself would hold at that close (rule "o4h", trend "macd", trend_tf 30m): A without
  trend_both, B with it where A enters (B only adds a refusal after A's checks, so where A says no, B says no too).
  Checked: at every marked close the bot's own window sees the same turn, and on a sample of the other closes it sees
  none (summary "checks").
- trading: a mixchop.Bot in paper mode gets every 15-minute close in order, 5 s after the close (the entry block is read
  at that time); evaluate_friend answers from the decisions; its stop and its ladder (exchange ROE +10 -> +8, then every
  2) follow the 1m bars as the live bot does (ladder_every_s 60: paper_bars on the 1m bars since the last one used; the
  stop is checked first on each bar: the stop price, or the bar's open when it opens past it). PaperBroker: the entry
  fills at the signal close, the taker fee on both sides. One position at a time, the config's coin order on a tie,
  margin = 40 % of the equity (at most $10,000 a position), $50 at the start of each period, no equity floor (the live
  configs have none).
- a position still open at a period's end is closed at the last 1m close (why "end").
Not modelled: market-order slippage (the fee x2 run stands for it), funding, the exchanges' own prices (Binance bars),
CPI / PCE before 2026-10 (the repo's calendar has FOMC and NFP only before that), NYSE holidays before 2026, contract
steps (only a $5 minimum order).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from paperbot import events as EV  # noqa: E402
from paperbot import friendtrend as FT  # noqa: E402
from paperbot import mixchop as M  # noqa: E402

SCRATCH = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
DATA = os.environ.get("OBV15BOTH_DATA") or os.path.join(SCRATCH, "obv15both_data")
OUT = os.path.join(HERE, "summary.json")
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly/klines"
CONFIG = os.path.join(ROOT, "deploy", "mixchop.live.json")
SYMS = ("BTCUSDT", "SOLUSDT", "ZECUSDT")
TF_MS = {"15m": M.MIN15, "30m": M.MIN30, "1m": M.MIN1}
FIRST = {"15m": (2024, 9), "30m": (2024, 9), "1m": (2024, 11)}
LAST = (2026, 10)


def _ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


T0, TS, T1 = _ms("2024-11-01"), _ms("2026-05-01"), _ms("2026-11-01")      # dev [T0, TS), sealed [TS, T1)
PERIODS = {"dev": (T0, TS), "sealed": (TS, T1)}
HIST = 1499                                    # closed bars in the bot's 1,500-row read
JUDGE_MS = 5_000
START_EQ = 50.0
FEES = {"toobit": 0.0006, "wooxpro": 0.00042, "fee_x2": 0.0012}
MIN_ORDER = 5.0
DECISIONS_V = "1"


# ====================================================================== download
def months(tf: str):
    y, m = FIRST[tf]
    while (y, m) <= LAST:
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read()
        except Exception:  # noqa: BLE001  retried with a pause, the last failure raised
            if i == tries - 1:
                raise
            time.sleep(2.0 * 2 ** i)
    raise RuntimeError(url)


def zip_path(data: str, sym: str, tf: str, month: str) -> str:
    return os.path.join(data, "raw", sym, tf, f"{sym}-{tf}-{month}.zip")


def fetch_one(data: str, sym: str, tf: str, month: str) -> str:
    path = zip_path(data, sym, tf, month)
    if os.path.exists(path):
        return "kept"
    url = f"{ARCHIVE}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
    want = _get(url + ".CHECKSUM").decode().split()[0].strip().lower()
    body = _get(url)
    got = hashlib.sha256(body).hexdigest()
    if got != want:
        raise RuntimeError(f"{url}: sha256 {got} != {want}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "wb") as fh:
        fh.write(body)
    os.replace(path + ".part", path)
    return "new"


def cmd_download(args) -> int:
    jobs = [(s, tf, mo) for s in SYMS for tf in TF_MS for mo in months(tf)]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: fetch_one(args.data, *j), jobs))
    print(f"{len(res)} files: {res.count('new')} new, {res.count('kept')} kept", flush=True)
    return 0


# ====================================================================== bars
def read_klines(data: str, sym: str, tf: str) -> np.ndarray:
    """[open_ms, open, high, low, close, volume] rows, oldest first, one per open time."""
    rows = []
    for mo in months(tf):
        path = zip_path(data, sym, tf, mo)
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".csv") and "/" not in n and ".." not in n]
            if len(names) != 1:
                raise RuntimeError(f"{path}: {z.namelist()}")
            text = z.read(names[0]).decode("ascii", "replace")
        for line in text.splitlines():
            f = line.split(",")
            if len(f) < 6 or not f[0].strip().isdigit():
                continue
            t = int(f[0])
            if t > 10 ** 14:
                t //= 1000
            rows.append((t, float(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[5])))
    a = np.array(rows, dtype=float)
    a = a[np.argsort(a[:, 0], kind="stable")]
    keep = np.r_[a[1:, 0] != a[:-1, 0], True]
    return a[keep]


def gaps(a: np.ndarray, tf_ms: int) -> dict:
    d = np.diff(a[:, 0].astype(np.int64))
    bad = d[d != tf_ms]
    return {"bars": int(len(a)), "first": time.strftime("%Y-%m-%d %H:%M", time.gmtime(a[0, 0] / 1000)),
            "last": time.strftime("%Y-%m-%d %H:%M", time.gmtime(a[-1, 0] / 1000)), "gaps": int(len(bad)),
            "missing_bars": int(sum(int(x // tf_ms) - 1 for x in bad if x > tf_ms))}


def live_coins() -> dict:
    return {c.symbol: c for c in M.load_config(CONFIG).coins}


# ====================================================================== the bot's decisions at the OBV turns
def o4_want(ev: dict) -> int:
    """The OBV turn's side in an evaluate_friend answer: green under 0 = 1, red over 0 = -1, else 0."""
    t, ac = int(ev.get("o4_turn") or 0), ev.get("o4")
    if ac is None:
        return 0
    return 1 if t > 0 and ac < 0 else -1 if t < 0 and ac > 0 else 0


def windows(a15: np.ndarray, a30: np.ndarray, i: int, close30: np.ndarray) -> tuple[int, "pd.DataFrame", "pd.DataFrame"]:
    """(close, 15m bars, 30m bars) as the bot holds them at the close of 15m bar ``i``: its 1,500-row reads (1,499 closed
    bars and the one opening now) through mixchop.bars_frame."""
    ce = int(a15[i, 0]) + M.MIN15
    k = int(np.searchsorted(close30, ce, side="right")) - 1          # the last 30m bar closed by ce
    b = M.bars_frame(a15[i - HIST + 1:i + 2].tolist(), M.MIN15, ce)
    tb = M.bars_frame(a30[k - HIST + 1:k + 2].tolist(), M.MIN30, ce)
    return ce, b, tb


def decide_coin(data: str, sym: str, sample: int = 1200, seed: int = 11) -> dict:
    co = live_coins()[sym]
    a15, a30 = read_klines(data, sym, "15m"), read_klines(data, sym, "30m")
    open15, close30 = a15[:, 0].astype(np.int64), a30[:, 0].astype(np.int64) + M.MIN30
    ce15 = open15 + M.MIN15
    P = FT.o4_pane(a15[:, 2], a15[:, 3], a15[:, 4], a15[:, 5])
    lo = max(HIST - 1, int(np.searchsorted(ce15, T0, side="left")))
    hi = int(np.searchsorted(ce15, T1, side="right"))             # closes <= T1
    idx = [i for i in range(lo, hi) if P["side"][i] != 0]

    def ev_at(i: int, both: bool) -> dict:
        ce, b, tb = windows(a15, a30, i, close30)
        more = {"trend_both": True} if both else {}
        return M.evaluate_friend("o4h", co, b, ce, M.MIN15, "macd", tb=tb, trend_tf_ms=M.MIN30, **more)

    A, B, turn_differs = {}, {}, 0
    for i in idx:
        ev = ev_at(i, False)
        if o4_want(ev) != int(P["side"][i]):
            turn_differs += 1
        ce = int(ce15[i])
        A[ce] = ev
        if ev["side"]:
            B[ce] = ev_at(i, True)
    rng = np.random.default_rng(seed)
    others = np.array(sorted(set(range(lo, hi)) - set(idx)), dtype=np.int64)
    pick = rng.choice(others, size=min(sample, len(others)), replace=False) if len(others) else []
    found = sum(1 for i in pick if o4_want(ev_at(int(i), False)) != 0)
    # the window sizes the bot reads (at the first marked close and at the first close of each kind, :00/:15/:30/:45)
    sizes = sorted({(len(b), len(tb), int(b.open_ms.iloc[-1]) + M.MIN15 == ce,
                     int(tb.open_ms.iloc[-1]) + M.MIN30 == ce // M.MIN30 * M.MIN30)
                    for ce, b, tb in (windows(a15, a30, i, close30) for i in [idx[0]] + list(range(lo, lo + 4)))})
    checks = {"marked_turns": len(idx), "window_turn_differs": turn_differs, "sampled_other_closes": int(len(pick)),
              "sampled_with_a_turn": int(found), "window_bars_15m_30m": list(sizes),
              "a_entries": sum(1 for e in A.values() if e["side"]), "b_entries": sum(1 for e in B.values() if e["side"])}
    return {"A": A, "B": B, "checks": checks}


def file_sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def decisions_path(data: str) -> str:
    key = hashlib.sha256((DECISIONS_V + file_sha(os.path.join(ROOT, "paperbot", "mixchop.py"))
                          + file_sha(os.path.join(ROOT, "paperbot", "friendtrend.py")) + file_sha(CONFIG)
                          + json.dumps({s: {tf: gaps(read_klines(data, s, tf), TF_MS[tf]) for tf in ("15m", "30m")}
                                        for s in SYMS}, sort_keys=True)).encode()).hexdigest()[:16]
    return os.path.join(data, f"decisions-{key}.json")


def cmd_decide(args) -> int:
    path = decisions_path(args.data)
    if os.path.exists(path):
        print(f"kept {path}")
        return 0
    t = time.time()
    out = {}
    with ProcessPoolExecutor(min(3, os.cpu_count() or 1)) as ex:
        futs = {s: ex.submit(decide_coin, args.data, s) for s in SYMS}
        for s, f in futs.items():
            out[s] = f.result()
            print(f"{s}: {out[s]['checks']} ({time.time() - t:.0f} s)", flush=True)
    with open(path + ".part", "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=float)
    os.replace(path + ".part", path)
    print(f"wrote {path} in {time.time() - t:.0f} s")
    return 0


def load_decisions(data: str) -> dict:
    with open(decisions_path(data), encoding="utf-8") as fh:
        got = json.load(fh)
    return {s: {"A": {int(k): v for k, v in d["A"].items()}, "B": {int(k): v for k, v in d["B"].items()},
                "checks": d["checks"]} for s, d in got.items()}


# ====================================================================== the bot, driven close by close
class ReplayBot(M.Bot):
    """mixchop.Bot with its rows in memory and nothing written; its bars read skipped (evaluate_friend answers from the
    decisions)."""

    def __init__(self, *a, **kw):
        self.rows: list = []
        super().__init__(*a, **kw)

    def save(self) -> None:
        pass

    def log(self, kind: str, **kv) -> None:
        self.rows.append({"ts": self.now(), "kind": kind, **kv})

    def bars(self, symbol: str, close_ms: int):
        return None, None


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self) -> int:
        return self.t


def make_cfg(both: bool, fee: float, tmp: str) -> "M.Config":
    d = json.load(open(CONFIG, encoding="utf-8"))
    d.update(mode="paper", state=os.path.join(tmp, "none", "state.json"), log=os.path.join(tmp, "none", "log.jsonl"),
             kill_file=os.path.join(tmp, "none", "STOP"), own_stop_file=os.path.join(tmp, "none", "OWN"), telegram=False,
             taker_fee=fee, trend_both=both, start_equity=START_EQ)
    p = os.path.join(tmp, f"cfg-{int(both)}-{fee}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    cfg = M.load_config(p)
    assert cfg.trend_both is both and cfg.taker_fee == fee and cfg.rules == ("o4h",) and cfg.tf == "15m"
    return cfg


def run_bot(rule: str, fee: float, period: str, dec: dict, bars: dict, tmp: str) -> dict:
    t_from, t_to = PERIODS[period]
    cfg = make_cfg(rule == "B", fee, tmp)
    clock = Clock()
    opens = {s: {tf: a[:, 0].astype(np.int64) for tf, a in d.items()} for s, d in bars.items()}

    def fetch(symbol: str, tf: str, n: int) -> list:
        j = int(np.searchsorted(opens[symbol][tf], clock.t, side="right"))
        return bars[symbol][tf][max(0, j - n):j].tolist()

    def lookup(r, co, b, close_ms, tf_ms=M.MIN30, trend="four", tb=None, trend_tf_ms=None, trend_both=False):
        assert (r, tf_ms, trend, trend_tf_ms, trend_both) == ("o4h", M.MIN15, "macd", M.MIN30, rule == "B")
        d = dec[co.symbol]
        ev = (d["B"].get(close_ms) if trend_both and close_ms in d["B"] else d["A"].get(close_ms))
        return dict(ev) if ev else {"symbol": co.symbol, "close_ms": close_ms, "side": 0, "rule": "o4h",
                                    "why": "OBV 히스토그램 양봉·음봉 전환 없음"}

    broker = M.PaperBroker(START_EQ, fee, lambda s: {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": MIN_ORDER})
    keep = M.evaluate_friend
    M.evaluate_friend = lookup
    try:
        bot = ReplayBot(cfg, broker, fetch, clock, sleep=lambda s: None)
        clock.t = t_from
        bot.start()
        month_eq, cur = [], None
        for ce in range(t_from + M.MIN15, t_to + M.MIN15, M.MIN15):
            mo = time.strftime("%Y-%m", time.gmtime((ce - 1) / 1000))
            if mo != cur:
                month_eq.append((mo, broker.equity()))
                cur = mo
            clock.t = ce + JUDGE_MS
            bot.on_close(ce)
        if bot.pos is not None:                                      # the period's end: closed at the last 1m close
            p = bot.pos
            a = bars[p.symbol]["1m"]
            j = int(np.searchsorted(opens[p.symbol]["1m"], t_to, side="left")) - 1
            bot.finish(p, float(a[j, 4]), "end")
    finally:
        M.evaluate_friend = keep
    return {"rows": bot.rows, "month_eq": month_eq, "end_eq": broker.equity()}


# ====================================================================== numbers
def trades(rows: list) -> list:
    opens = {(r["symbol"], r["opened_ms"]): r for r in rows if r["kind"] == "entry"}
    out = []
    for r in rows:
        if r["kind"] != "exit":
            continue
        en = opens[(r["symbol"], r["opened_ms"])]
        eb = float(en["equity_before"])
        ea = float(r["equity"])
        out.append({"symbol": r["symbol"], "side": int(r["side"]), "opened_ms": int(r["opened_ms"]), "exit_ms": int(r["ts"]),
                    "ret": (ea / eb - 1) * 100.0, "pnl": ea - eb, "step": int(r.get("step") or 0), "why": r["why"],
                    "stop_pct": float(en["stop_dist"]) / float(en["entry"]) * 100.0,
                    "tyellow": bool((en.get("why") or {}).get("tyellow"))})
    return out


def runs_of_losses(rs: list) -> int:
    best = n = 0
    for r in rs:
        n = n + 1 if r <= 0 else 0
        best = max(best, n)
    return best


def summarize(ts: list, end_eq: float, month_eq: list) -> dict:
    rs = [t["ret"] for t in ts]
    w = [r for r in rs if r > 0]
    lo = [r for r in rs if r <= 0]
    eq, peak, mdd = START_EQ, START_EQ, 0.0
    for t in ts:
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    aw = float(np.mean(w)) if w else 0.0
    al = float(np.mean(lo)) if lo else 0.0
    steps: dict = {}
    for t in ts:
        k = "end" if t["why"] == "end" else str(t["step"])
        s = steps.setdefault(k, {"n": 0, "ret_sum": 0.0})
        s["n"] += 1
        s["ret_sum"] += t["ret"]
    eqs = [e for _, e in month_eq] + [end_eq]
    mrets = [eqs[i + 1] / eqs[i] - 1 for i in range(len(month_eq)) if eqs[i] > 0]

    def part(sel) -> dict:
        x = [t["ret"] for t in ts if sel(t)]
        return {"n": len(x), "win_rate": round(sum(1 for r in x if r > 0) / len(x), 3) if x else None,
                "exp_pct": round(float(np.mean(x)), 3) if x else None, "sum_pct": round(float(sum(x)), 2)}
    return {
        "trades": len(rs), "wins": len(w), "win_rate": round(len(w) / len(rs), 4) if rs else None,
        "avg_win_pct": round(aw, 3), "avg_loss_pct": round(al, 3),
        "exp_pct": round(float(np.mean(rs)), 4) if rs else None, "median_pct": round(float(np.median(rs)), 3) if rs else None,
        "breakeven_win_rate": round(-al / (aw - al), 4) if w and lo else None,
        "payoff": round(aw / -al, 3) if w and lo else None,
        "start_eq": START_EQ, "end_eq": round(float(end_eq), 2), "return_pct": round((end_eq / START_EQ - 1) * 100, 2),
        "max_dd_pct": round(mdd * 100, 2), "max_losing_streak": runs_of_losses(rs),
        "exits": {k: {"n": v["n"], "avg_pct": round(v["ret_sum"] / v["n"], 3)}
                  for k, v in sorted(steps.items(), key=lambda kv: (kv[0] == "end", int(kv[0]) if kv[0] != "end" else 0))},
        "coins": {s: part(lambda t, s=s: t["symbol"] == s) for s in SYMS},
        "long": part(lambda t: t["side"] > 0), "short": part(lambda t: t["side"] < 0),
        "yellow_trend_bar": part(lambda t: t["tyellow"]),
        "stop_pct_median": round(float(np.median([t["stop_pct"] for t in ts])), 3) if ts else None,
        "hold_h_median": round(float(np.median([(t["exit_ms"] - t["opened_ms"]) / 3.6e6 for t in ts])), 2) if ts else None,
        "months": len(mrets), "neg_months": sum(1 for x in mrets if x < 0),
        "month_returns_pct": [round(x * 100, 1) for x in mrets],
    }


def skip_counts(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        if r["kind"] != "skip":
            continue
        w = str(r.get("why") or "")
        k = ("weekend" if w.startswith("주말") else "us_open" if w.startswith("나스닥") else "macro" if w.startswith("경제")
             else "holding" if w == "보유 중" else "same_bar" if w.startswith("같은 봉") else "min_order" if "최소" in w else "other")
        out[k] = out.get(k, 0) + 1
    return out


def filtered_by_15m(dec: dict, period: str) -> dict:
    """Signals A takes and B refuses for the 15m 추세 MACD, in the period (before the one-position and time blocks)."""
    t_from, t_to = PERIODS[period]
    out = {}
    for s in SYMS:
        a = [ce for ce, e in dec[s]["A"].items() if e["side"] and t_from < ce <= t_to]
        b = [ce for ce in a if dec[s]["B"][ce]["side"]]
        out[s] = {"a_signals": len(a), "b_signals": len(b), "refused_by_15m": len(a) - len(b)}
    return out


def macro_history(tmp: str) -> str:
    cal = json.load(open(os.path.join(ROOT, "research", "hunt", "macro_calendar.json"), encoding="utf-8"))["events"]
    live_csv = open(os.path.join(ROOT, "data", "macro_events.csv"), encoding="utf-8").read()
    path = os.path.join(tmp, "macro_events.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("ts_utc,kind,source_url\n")
        for e in cal:
            fh.write(f"{e['utc'][:16]}:00Z,{e['kind']},{(e.get('source_urls') or ['x'])[0]}\n")
        fh.write("\n".join(x for x in live_csv.splitlines()[1:] if x and not x.startswith("#")) + "\n")
    return path


def cmd_period(args, period: str) -> int:
    summary = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {}
    if period == "sealed":
        if "dev" not in summary:
            raise SystemExit("dev first: the sealed period is opened only after the dev result is written")
        if "sealed" in summary and not args.again:
            raise SystemExit("the sealed period was already opened once (summary.json \"sealed\")")
    t = time.time()
    dec = load_decisions(args.data)
    bars = {s: {tf: read_klines(args.data, s, tf) for tf in ("1m",)} for s in SYMS}
    tmp = tempfile.mkdtemp(prefix="obv15both-")
    keep_path = EV.PATH
    res: dict = {}
    try:
        EV.PATH = macro_history(tmp)
        EV.reset()
        n_macro = {k: sum(1 for e in EV.all_events() if e.kind == k and PERIODS[period][0] <= e.ts_ms < PERIODS[period][1])
                   for k in sorted({e.kind for e in EV.all_events()})}
        fees = ("toobit", "wooxpro", "fee_x2")
        for rule in ("A", "B"):
            for fk in fees:
                r = run_bot(rule, FEES[fk], period, dec, bars, tmp)
                ts = trades(r["rows"])
                res[f"{rule}_{fk}"] = {"rule": rule, "fee": FEES[fk], **summarize(ts, r["end_eq"], r["month_eq"]),
                                       "skips": skip_counts(r["rows"]),
                                       "ladder_moves": sum(1 for x in r["rows"] if x["kind"] == "ladder")}
                x = res[f"{rule}_{fk}"]
                print(f"{period} {rule} {fk}: {x['trades']} trades, win {x['win_rate']}, exp {x['exp_pct']}%, "
                      f"return {x['return_pct']}%, max DD {x['max_dd_pct']}%", flush=True)
    finally:
        EV.PATH = keep_path
        EV.reset()
    summary.setdefault("what", "OBV 히스토그램 전환 백테스트, A (30분 추세 MACD) vs B (+15분 추세 MACD 같은 쪽); "
                               "plan: research/obv15both/PLAN_KO.md")
    summary.setdefault("code", {})
    summary["code"][period] = {"mixchop_sha256": file_sha(os.path.join(ROOT, "paperbot", "mixchop.py")),
                               "friendtrend_sha256": file_sha(os.path.join(ROOT, "paperbot", "friendtrend.py")),
                               "config": "deploy/mixchop.live.json", "config_sha256": file_sha(CONFIG)}
    summary["checks"] = {s: dec[s]["checks"] for s in SYMS}
    summary["data"] = {s: {**{tf: gaps(read_klines(args.data, s, tf), TF_MS[tf]) for tf in ("15m", "30m")},
                           "1m": gaps(bars[s]["1m"], M.MIN1)} for s in SYMS}
    summary[period] = {"from": time.strftime("%Y-%m-%d", time.gmtime(PERIODS[period][0] / 1000)),
                       "to": time.strftime("%Y-%m-%d", time.gmtime(PERIODS[period][1] / 1000 - 1)),
                       "made_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "seconds": round(time.time() - t),
                       "macro_events": n_macro, "filtered_by_15m": filtered_by_15m(dec, period), "runs": res}
    with open(args.out + ".part", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(args.out + ".part", args.out)
    print(f"wrote {args.out} ({period}) in {time.time() - t:.0f} s")
    return 0


# ====================================================================== the verdict (PLAN_KO.md, fixed before the runs)
def verdict(summary: dict, rule: str) -> list:
    """[(criterion in words, passed or None when not run yet, the numbers)] for ``rule`` at the Toobit fee."""
    dev = summary.get("dev", {}).get("runs", {})
    sea = summary.get("sealed", {}).get("runs", {})
    d, d2, s = dev.get(f"{rule}_toobit"), dev.get(f"{rule}_fee_x2"), sea.get(f"{rule}_toobit")
    out = []
    if d:
        out.append(("개발 구간 거래 30번 이상", d["trades"] >= 30, f"{d['trades']}번"))
        out.append(("개발 구간 거래당 기대값 > 0, 복리 수익 > 0", d["exp_pct"] is not None and d["exp_pct"] > 0 and d["return_pct"] > 0,
                    f"기대값 {d['exp_pct']:+.2f}%, 수익 {d['return_pct']:+.1f}%"))
        out.append(("개발 구간 최대 낙폭 50% 미만", d["max_dd_pct"] < 50, f"{d['max_dd_pct']:.1f}%"))
    if s:
        out.append(("봉인 구간 거래당 기대값 > 0, 복리 수익 > 0", s["exp_pct"] is not None and s["exp_pct"] > 0 and s["return_pct"] > 0,
                    f"기대값 {s['exp_pct']:+.2f}%, 수익 {s['return_pct']:+.1f}%"))
    else:
        out.append(("봉인 구간 거래당 기대값 > 0, 복리 수익 > 0", None, "아직 안 엶"))
    if d2:
        out.append(("수수료 2배(개발 구간) 기대값 > 0", d2["exp_pct"] is not None and d2["exp_pct"] > 0, f"{d2['exp_pct']:+.2f}%"))
    return out


def fmt_run(x: dict) -> str:
    ex = x["exits"]
    stop = ex.get("0", {"n": 0})["n"]
    lock1 = ex.get("1", {"n": 0})["n"]
    return (f"| {x['trades']} | {x['win_rate'] * 100:.1f}% | {x['avg_win_pct']:+.2f}% | {x['avg_loss_pct']:+.2f}% | "
            f"{(x['breakeven_win_rate'] or 0) * 100:.1f}% | **{x['exp_pct']:+.2f}%** | {x['return_pct']:+.1f}% | {x['max_dd_pct']:.1f}% | "
            f"{x['max_losing_streak']} | {stop} · {lock1} · {x['trades'] - stop - lock1} |")


def cmd_report(args) -> int:
    sm = json.load(open(args.out, encoding="utf-8"))
    L = ["# OBV 히스토그램 전환 백테스트 결과 (A: 30분 추세만 · B: 30분 + 15분 추세 같은 쪽)", "",
         "계획과 합격 기준: `research/obv15both/PLAN_KO.md` (결과 보기 전에 커밋). 숫자: `research/obv15both/summary.json`. "
         "프로그램: `research/obv15both/replay.py` (봇의 실제 코드로 판단 · 매매). 이 파일은 `replay.py report`가 만듭니다.", ""]
    head = ("| 거래 | 승률 | 평균 이익 | 평균 손실 | 본전 승률 | 거래당 기대값 | 복리 수익 | 최대 낙폭 | 최장 연속 손실 | 손절 · 1칸 · 2칸↑ |\n"
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for period, ko in (("dev", "개발 구간"), ("sealed", "봉인 구간")):
        if period not in sm:
            continue
        P = sm[period]
        L += [f"## {ko} ({P['from']} ~ {P['to']}, 잔고 $50에서 시작)", "",
              "금액은 모두 **진입 때 잔고 대비 %**(수수료 뺀 것). 본전 승률 = 평균 손실 ÷ (평균 이익 + 평균 손실).", ""]
        for fk, fko in (("toobit", "투비트 수수료 0.06%"), ("wooxpro", "WOO X Pro 수수료 0.042%"), ("fee_x2", "수수료 2배 0.12%")):
            L += [f"**{fko}**", "", "| 규칙 " + head.split("\n")[0], "|---" + head.split("\n")[1]]
            for rule in ("A", "B"):
                x = P["runs"].get(f"{rule}_{fk}")
                if x:
                    L.append(f"| {rule} " + fmt_run(x))
            L.append("")
        f15 = P["filtered_by_15m"]
        L += ["15분 추세 MACD 조건이 막은 신호(1포지션 · 진입 금지 시간 전): "
              + ", ".join(f"{s.replace('USDT', '')} {v['refused_by_15m']}/{v['a_signals']}" for s, v in f15.items()), ""]
        for rule in ("A", "B"):
            x = P["runs"].get(f"{rule}_toobit")
            if not x:
                continue
            L += [f"{rule} (투비트) 코인별: " + ", ".join(f"{s.replace('USDT', '')} {v['n']}번 승률 {(v['win_rate'] or 0) * 100:.0f}% "
                                                    f"기대값 {(v['exp_pct'] or 0):+.2f}%" for s, v in x["coins"].items())
                  + f" · 롱 {x['long']['n']}번 {(x['long']['exp_pct'] or 0):+.2f}% · 숏 {x['short']['n']}번 {(x['short']['exp_pct'] or 0):+.2f}%"
                  + f" · 손절 폭 중간값 {x['stop_pct_median']}% · 보유 시간 중간값 {x['hold_h_median']}시간"
                  + f" · 손해 본 달 {x['neg_months']}/{x['months']}", ""]
            L += [f"{rule} (투비트) 청산 단계: " + ", ".join(
                f"{'손절' if k == '0' else '구간 끝' if k == 'end' else k + '칸'} {v['n']}번 평균 {v['avg_pct']:+.2f}%" for k, v in x["exits"].items()), ""]
    L += ["## 미리 정한 기준으로 판정 (투비트 수수료)", ""]
    for rule in ("A", "B"):
        v = verdict(sm, rule)
        ok = all(p for _, p, _ in v) and len(v) == 5
        L += [f"**{rule}**: " + ("합격 (다시 켜도 되는 후보)" if ok else "불합격" if any(p is False for _, p, _ in v) else "판정 전"), ""]
        L += [f"- {'✔' if p else '✘' if p is False else '…'} {w}: {n}" for w, p, n in v] + [""]
    dev, sea = sm.get("dev", {}).get("runs", {}), sm.get("sealed", {}).get("runs", {})
    if "A_toobit" in dev and "B_toobit" in dev:
        b_dev = dev["B_toobit"]["exp_pct"] > dev["A_toobit"]["exp_pct"]
        b_sea = (sea["B_toobit"]["exp_pct"] >= sea["A_toobit"]["exp_pct"]) if "A_toobit" in sea and "B_toobit" in sea else None
        L += ["B가 A보다 나은가 (개발 구간 기대값이 더 높고, 봉인 구간에서 나빠지지 않음): "
              + ("예" if b_dev and b_sea else "아니오" if (not b_dev or b_sea is False) else "봉인 구간 전") , ""]
    L += ["## 모델에 없는 것", "", "시장가 미끄러짐(수수료 2배로 대신 봄), 펀딩비, 거래소별 가격 차이(바이낸스 봉), 2026년 전 CPI · PCE 발표, "
          "2026년 전 미국 증시 휴장일, 계약 단위(최소 $5 주문만).", ""]
    path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "REPORT_KO.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print(f"wrote {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="replay.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("download", "decide", "dev", "sealed", "report"))
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--again", action="store_true", help="(never for the verdict) reopen the sealed period")
    args = ap.parse_args(argv)
    if args.cmd == "download":
        return cmd_download(args)
    if args.cmd == "decide":
        return cmd_decide(args)
    if args.cmd == "report":
        return cmd_report(args)
    return cmd_period(args, args.cmd)


if __name__ == "__main__":
    sys.exit(main())
