"""믹스 30분 봇 5-year replay (owners 10-25 night: "연구분석이나 손실 분석 … 매매법 성공을 위해서 필요한 부분"): the bot's OWN
code (paperbot/mixchop.py: evaluate, ladder_stop, the Bot's on_close / halts / entry_block / enter / paper exits / finish,
PaperBroker) over Binance USDT-M 30m and 1h klines, 2021-10-01 .. 2026-10-01 (60 months), with the deploy config's coins
and settings. Its compact result, research/mixchop5y/summary.json, is the reference of the luck band ("운이냐 고장이냐",
paperbot/mixcheck.py) that the morning check and the 믹스 성적 screen place the live record in.

    python3 research/mixchop5y/replay.py download    # data.binance.vision monthly zips -> $MIXCHOP5Y_DATA (checked)
    python3 research/mixchop5y/replay.py run         # the variants -> research/mixchop5y/summary.json
    python3 research/mixchop5y/replay.py all
Options: --data DIR (default $MIXCHOP5Y_DATA or <scratchpad>/mixchop5y_data; raw data never goes into git),
--specs FILE (WOO X Pro contract sizes, {"SOLUSDT": {"qty_step", "min_qty", "min_notional"}, ...}: the live-rules
variant then floors to them as the bot does; without it only WOO X Pro's $5 minimum order is modelled), --out FILE.

Source: https://data.binance.vision/data/futures/um/monthly/klines/<SYMBOL>/<tf>/<SYMBOL>-<tf>-<YYYY-MM>.zip for 30m and
1h, 2021-07 .. 2026-09 (three months of warm-up: the bot reads 1,500 bars), each zip checked against its published
.CHECKSUM. Native klines as Binance serves them to the bot (bars without trades kept, as the live fetch has them).

How the bot's code is driven (the live site's test world does the same, tests/mix_site_world.py):
- signals: mixchop.line_gold on the whole 30m series finds the colour changes (the line's running sum cancels, the RSI
  seed is gone after 1,500 bars: tests/test_mixchop.py test_history_length_does_not_matter); at each of them the REAL
  mixchop.evaluate runs on the 1,499 closed 30m bars and 1,499 closed 1h bars the bot itself would have read, and its
  answer (side, why, stop distance, the RSI values) is what the bot gets at that close. Every other close is "색 변화
  없음". Checked: evaluate agrees on every change found, and on a sample of other closes it finds no change.
- trading: a mixchop.Bot in paper mode (PaperBroker: fills at the signal close, exits on the 30m bars as the indicator,
  the stop price or the open when the bar opens past it, taker fee on both sides) gets every 30-minute close in order,
  5 s after the close as the live bot judges (the entry block is read at that minute). Its log rows are kept in memory;
  nothing is written but the summary.
Variants:
- design: each coin alone ($50, its own account), no entry blocks, no minimum order: the friend's design as the
  design notes backtest it, to put next to docs/mixchop-ko.md 7장. Fee 0.042 % a side (WOO X Pro taker), and again at
  0.02 % (the design notes' fee) for the comparison.
- one_position: the six coins together, one position at a time (the config's coin order on a tie), nothing else.
- live_rules: as the live bot runs: one position, the entry blocks of deploy/mixchop.live.json (KST weekend, Nasdaq
  open -30/+30 min, US releases +-30 min), WOO X Pro's $5 minimum order (and the contract steps with --specs), $50 start,
  the 70 % floor, $500 at most a position, 0.042 % a side. The luck band's reference.
Not modelled (said in the summary too): the live fill a few seconds after the close (market order slippage), WOO X
Pro's last price for the stop (the replay uses Binance's bars), funding, WOO X Pro's own liquidation brackets (the bot's
second liquidation check), CPI and PCE before 2026-10 (the repo's history has FOMC and NFP only:
research/hunt/macro_calendar.json, unverified draft), NYSE holidays before 2026 (the list starts in 2026: the Nasdaq
block is applied on those few holidays too), the contract steps unless --specs is given.
"""
from __future__ import annotations

import argparse
import hashlib
import io
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
from paperbot import mixchop as M  # noqa: E402

SCRATCH = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
DATA = os.environ.get("MIXCHOP5Y_DATA") or os.path.join(SCRATCH, "mixchop5y_data")
OUT = os.path.join(HERE, "summary.json")
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly/klines"
TFS = {"30m": M.MIN30, "1h": M.H1}
FIRST_MONTH, LAST_MONTH = (2021, 7), (2026, 9)          # files: three months of warm-up before the period
T0 = int(pd.Timestamp("2021-10-01", tz="UTC").value // 1_000_000)
T1 = int(pd.Timestamp("2026-10-01", tz="UTC").value // 1_000_000)
HIST = 1499                                             # closed bars the bot's 1,500-row read holds at a close
JUDGE_MS = 5_000                                        # the bot judges a few seconds after the close
TAKER, DESIGN_FEE = 0.00042, 0.0002
DECISIONS_V = "2"                                       # the decisions cache's version (a change of decisions())
MIN_ORDER_USDT = 5.0                                    # paperbot/wooxpro.py MIN_ORDER_USDT
CONFIG = os.path.join(ROOT, "deploy", "mixchop.live.json")
# the design's 5-year numbers per coin (docs/mixchop-ko.md 7장; paperbot/dash/more/livemix.py BACKTEST): monthly mean
# return at 0.25 % a stop-out, win rate
DESIGN_REF = {"SOLUSDT": (0.0117, 0.32), "ETHUSDT": (0.0094, 0.19), "XRPUSDT": (0.0089, 0.20), "BCHUSDT": (0.0070, 0.31),
              "ZECUSDT": (0.0047, 0.37), "DOGEUSDT": (0.0037, 0.40)}


# ====================================================================== download
def months():
    y, m = FIRST_MONTH
    while (y, m) <= LAST_MONTH:
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:  # noqa: BLE001  retried with a pause, the last failure raised
            if i == tries - 1:
                raise
            time.sleep(2.0 * (i + 1))
    raise RuntimeError(url)


def zip_path(data: str, sym: str, tf: str, month: str) -> str:
    return os.path.join(data, "raw", sym, tf, f"{sym}-{tf}-{month}.zip")


def fetch_one(data: str, sym: str, tf: str, month: str) -> str:
    """One monthly zip, checked against its .CHECKSUM; kept, never downloaded again."""
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
    cfg = M.load_config(CONFIG)
    jobs = [(s, tf, mo) for s in cfg.symbols for tf in TFS for mo in months()]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: (j, fetch_one(args.data, *j)), jobs))
    print(f"{len(res)} files: {sum(1 for _, r in res if r == 'new')} new, {sum(1 for _, r in res if r == 'kept')} kept")
    return 0


# ====================================================================== bars
def read_klines(data: str, sym: str, tf: str) -> np.ndarray:
    """[open_ms, open, high, low, close] rows, oldest first, one per open time (the archive's header row and any
    non-numeric line skipped; microsecond times turned to ms)."""
    rows = []
    for mo in months():
        path = zip_path(data, sym, tf, mo)
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".csv") and "/" not in n and ".." not in n]
            if len(names) != 1:
                raise RuntimeError(f"{path}: {z.namelist()}")
            text = z.read(names[0]).decode("ascii", "replace")
        for line in text.splitlines():
            f = line.split(",")
            if len(f) < 5 or not f[0].strip().isdigit():
                continue
            t = int(f[0])
            if t > 10 ** 14:
                t //= 1000
            rows.append((t, float(f[1]), float(f[2]), float(f[3]), float(f[4])))
    a = np.array(rows, dtype=float)
    a = a[np.argsort(a[:, 0], kind="stable")]
    keep = np.r_[a[1:, 0] != a[:-1, 0], True]               # one row per open time: the last one
    return a[keep]


def gaps(a: np.ndarray, tf_ms: int) -> dict:
    d = np.diff(a[:, 0].astype(np.int64))
    bad = d[d != tf_ms]
    return {"bars": int(len(a)), "gaps": int(len(bad)), "missing_bars": int(sum(int(x // tf_ms) - 1 for x in bad if x > tf_ms))}


# ====================================================================== the bot's decisions at the colour changes
def decisions(co: "M.Coin", a30: np.ndarray, a1h: np.ndarray, sample: int = 1500, seed: int = 7) -> tuple[dict, dict]:
    """{close_ms: evaluate's answer} at every colour change of ``co`` (the real mixchop.evaluate on the bars the bot
    would hold), and the checks."""
    df30 = pd.DataFrame(a30, columns=["open_ms", "open", "high", "low", "close"])
    df30["open_ms"] = df30.open_ms.astype(np.int64)
    df1h = pd.DataFrame(a1h, columns=["open_ms", "open", "high", "low", "close"])
    df1h["open_ms"] = df1h.open_ms.astype(np.int64)
    h_close = df1h.open_ms.to_numpy(np.int64) + M.H1
    g = M.line_gold(df30.close.to_numpy(float))
    open30 = df30.open_ms.to_numpy(np.int64)
    ce_all = open30 + M.MIN30
    lo = int(np.searchsorted(ce_all, T0 - 2 * 86_400_000))
    idx = [i for i in range(max(lo, HIST + 1), len(df30)) if g[i] != g[i - 1] and ce_all[i] <= T1]

    def ev_at(i: int) -> dict:
        ce = int(ce_all[i])
        b30 = df30.iloc[i - HIST + 1:i + 1]
        j = int(np.searchsorted(h_close, ce, side="right"))
        b1h = df1h.iloc[max(0, j - HIST):j]
        return M.evaluate(co, b30, b1h, ce)

    out, bad = {}, 0
    for i in idx:
        ev = ev_at(i)
        if not (ev.get("to_cyan") or ev.get("to_purple")):
            bad += 1
        out[int(ce_all[i])] = ev
    rng = np.random.default_rng(seed)
    others = np.array(sorted(set(range(max(lo, HIST + 1), len(df30))) - set(idx)))
    others = others[ce_all[others] <= T1]
    pick = rng.choice(others, size=min(sample, len(others)), replace=False) if len(others) else []
    false_change = sum(1 for i in pick if (lambda e: e.get("to_cyan") or e.get("to_purple"))(ev_at(int(i))))
    return out, {"changes": len(idx), "evaluate_disagrees": bad, "sampled_other_closes": int(len(pick)),
                 "sampled_with_a_change": int(false_change)}


# ====================================================================== the bot, driven close by close
class ReplayBot(M.Bot):
    """mixchop.Bot with its rows kept in memory and nothing written (no state file, no log file, no message); its bars
    read is skipped because evaluate is the precomputed answer (decisions)."""

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


def run_bot(coins: list, decided: dict, bars30: dict, *, fee: float, blocks: bool, spec_fn, start_eq: float = 50.0) -> dict:
    """One replay: the Bot over every 30-minute close of the period. Returns its log rows and the month-end equity."""
    raw = json.load(open(CONFIG, encoding="utf-8"))
    cfg = M.Config(mode="paper", state=os.path.join(tempfile.gettempdir(), "mixchop5y-none", "state.json"), log="", coins=coins,
                   risk_pct=float(raw.get("risk_pct", 0.25)), equity_floor_frac=float(raw.get("equity_floor_frac", 0.7)),
                   start_equity=start_eq, kill_file="", own_stop_file="", max_notional_usd=float(raw.get("max_notional_usd", 500)),
                   taker_fee=fee, telegram=False, no_weekend=bool(raw.get("no_weekend")) and blocks,
                   us_open_pre_min=int(raw.get("us_open_pre_min", 0)) if blocks else 0,
                   us_open_pause_min=int(raw.get("us_open_pause_min", 0)) if blocks else 0,
                   macro_blackout_min=int(raw.get("macro_blackout_min", 0)) if blocks else 0)
    clock = Clock()
    opens = {s: a[:, 0].astype(np.int64) for s, a in bars30.items()}

    def fetch(symbol: str, tf: str, n: int) -> list:
        j = int(np.searchsorted(opens[symbol], clock.t, side="right"))     # through the bar opened at the close
        return bars30[symbol][max(0, j - n):j].tolist()

    def evaluate(co, b30, b1h, ce):
        return dict(decided[co.symbol].get(ce) or {"symbol": co.symbol, "close_ms": ce, "side": 0, "why": "색 변화 없음"})

    broker = M.PaperBroker(start_eq, fee, spec_fn)
    keep = M.evaluate
    M.evaluate = evaluate
    try:
        bot = ReplayBot(cfg, broker, fetch, clock, sleep=lambda s: None)
        clock.t = T0
        bot.start()
        month_eq = []
        cur = None
        for ce in range(T0 + M.MIN30, T1 + M.MIN30, M.MIN30):                  # the bars of 2021-10-01 .. 2026-09-30
            mo = time.strftime("%Y-%m", time.gmtime((ce - 1) / 1000))       # the month the bar ending at ce is in
            if mo != cur:
                month_eq.append((mo, broker.equity()))
                cur = mo
            clock.t = ce + JUDGE_MS
            bot.on_close(ce)
    finally:
        M.evaluate = keep
    return {"rows": bot.rows, "month_eq": month_eq, "end_eq": broker.equity(), "open": bot.pos is not None}


# ====================================================================== numbers
def trades(rows: list, risk_pct: float) -> list:
    """Closed trades (entry row joined to its exit by coin and opened_ms): R = equity change / (equity before x risk),
    as the live site counts them (paperbot/dash/more/livemix.py trades_of)."""
    opens = {(r["symbol"], r["opened_ms"]): r for r in rows if r["kind"] == "entry"}
    out = []
    for r in rows:
        if r["kind"] != "exit":
            continue
        en = opens[(r["symbol"], r["opened_ms"])]
        eb = float(en["equity_before"])
        pnl = float(r["equity"]) - eb
        out.append({"symbol": r["symbol"], "side": int(r["side"]), "opened_ms": int(r["opened_ms"]), "exit_ms": int(r["ts"]),
                    "pnl": pnl, "r": pnl / (eb * risk_pct / 100.0), "step": int(r.get("step") or 0), "why": r["why"],
                    "stop_pct": float(en["why"]["stop_pct"]) if isinstance(en.get("why"), dict) else None})
    return out


def streak_runs(rs: list) -> list:
    runs, n = [], 0
    for r in rs:
        if r <= 0:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return runs


def drawdowns_r(rs: list) -> tuple[list, float]:
    """The drawdown from the peak of the running R sum after each trade, and its largest."""
    cum, peak, dd = 0.0, 0.0, []
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd.append(peak - cum)
    return dd, max(dd) if dd else 0.0


def pct(xs, q) -> float:
    return float(np.percentile(np.asarray(xs, float), q)) if len(xs) else float("nan")


def month_stats(month_eq: list, end_eq: float) -> dict:
    eqs = [e for _, e in month_eq] + [end_eq]
    rets = [eqs[i + 1] / eqs[i] - 1 for i in range(len(month_eq))]
    peak, mdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak)
    return {"months": len(rets), "month_mean": round(float(np.mean(rets)), 5), "month_median": round(float(np.median(rets)), 5),
            "neg_months": int(sum(1 for x in rets if x < 0)), "flat_months": int(sum(1 for x in rets if x == 0)),
            "end_equity": round(float(end_eq), 2), "total_return": round(float(end_eq / eqs[0] - 1), 4),
            "max_dd_equity": round(float(mdd), 4)}


def stats(ts: list, risk_pct: float) -> dict:
    rs = [t["r"] for t in ts]
    w = [r for r in rs if r > 0]
    lo = [r for r in rs if r <= 0]
    runs = streak_runs(rs)
    _dd, mdd = drawdowns_r(rs)
    years = (T1 - T0) / (365.25 * 86_400_000)
    return {"trades": len(rs), "per_year": round(len(rs) / years, 1), "wins": len(w),
            "win_rate": round(len(w) / len(rs), 4) if rs else None,
            "avg_win_r": round(float(np.mean(w)), 3) if w else None, "avg_loss_r": round(float(np.mean(lo)), 3) if lo else None,
            "r_sum": round(float(sum(rs)), 2), "r_per_trade": round(float(np.mean(rs)), 4) if rs else None,
            "r_per_month": round(float(sum(rs)) / 60.0, 3), "max_losing_streak": max(runs) if runs else 0,
            "max_dd_r": round(mdd, 2), "ladder_exits": sum(1 for t in ts if t["step"] > 0),
            "stop_exits": sum(1 for t in ts if t["why"] == "stop")}


def skip_counts(rows: list) -> dict:
    from paperbot.dash.more import livemix as LX
    out: dict = {}
    for r in rows:
        if r["kind"] != "skip":
            continue
        g = LX.skip_group(r.get("why"))
        if g == "block":
            g = "block_" + (LX.block_kind(r.get("why")) or "other")
        out[g] = out.get(g, 0) + 1
    sig = [r for r in rows if r["kind"] == "signal"]
    out["colour_changes"] = len(sig)
    out["signals"] = sum(1 for r in sig if r.get("side"))
    out["entries"] = sum(1 for r in rows if r["kind"] == "entry")
    return out


def band_reference(ts: list, month_eq: list) -> dict:
    """What the luck band needs from the live-rules replay: the R of every trade in order, the losing runs, the monthly R
    sums, the drawdown from the peak after each trade (percentiles)."""
    rs = [t["r"] for t in ts]
    runs = streak_runs(rs)
    dd, mdd = drawdowns_r(rs)
    by_month: dict = {mo: 0.0 for mo, _ in month_eq}
    n_month: dict = {mo: 0 for mo, _ in month_eq}
    for t in ts:
        mo = time.strftime("%Y-%m", time.gmtime(t["exit_ms"] / 1000))
        if mo in by_month:
            by_month[mo] += t["r"]
            n_month[mo] += 1
    mr = list(by_month.values())
    hist: dict = {}
    for k in runs:
        hist[str(k)] = hist.get(str(k), 0) + 1
    # the yearly worst drawdown (R)
    year_dd: dict = {}
    cum, peak = 0.0, 0.0
    for t in ts:
        y = time.strftime("%Y", time.gmtime(t["exit_ms"] / 1000))
        cum += t["r"]
        peak = max(peak, cum)
        year_dd[y] = max(year_dd.get(y, 0.0), peak - cum)
    yearly: dict = {}
    for t in ts:
        y = yearly.setdefault(time.strftime("%Y", time.gmtime(t["exit_ms"] / 1000)), {"trades": 0, "wins": 0, "r_sum": 0.0})
        y["trades"] += 1
        y["wins"] += 1 if t["r"] > 0 else 0
        y["r_sum"] = round(y["r_sum"] + t["r"], 3)
    return {"r": [round(x, 3) for x in rs], "yearly": dict(sorted(yearly.items())),
            "losing_runs": {"hist": dict(sorted(hist.items(), key=lambda kv: int(kv[0]))), "max": max(runs) if runs else 0,
                            "p50": pct(runs, 50), "p90": pct(runs, 90), "p99": pct(runs, 99)},
            "monthly_r": {"months": [round(x, 2) for x in mr], "trades": list(n_month.values()), "p5": round(pct(mr, 5), 2),
                          "p25": round(pct(mr, 25), 2), "p50": round(pct(mr, 50), 2), "p75": round(pct(mr, 75), 2),
                          "p95": round(pct(mr, 95), 2), "neg": sum(1 for x in mr if x < 0)},
            "drawdown_r": {"max": round(mdd, 2), "p50": round(pct(dd, 50), 2), "p90": round(pct(dd, 90), 2),
                           "p99": round(pct(dd, 99), 2), "yearly_max": {k: round(v, 2) for k, v in sorted(year_dd.items())}}}


def file_sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def cmd_run(args) -> int:
    cfg = M.load_config(CONFIG)
    risk = cfg.risk_pct
    t_start = time.time()
    bars30, bars1h, data_info = {}, {}, {}
    for co in cfg.coins:
        bars30[co.symbol] = read_klines(args.data, co.symbol, "30m")
        bars1h[co.symbol] = read_klines(args.data, co.symbol, "1h")
        data_info[co.symbol] = {"30m": gaps(bars30[co.symbol], M.MIN30), "1h": gaps(bars1h[co.symbol], M.H1)}
    # the decisions depend on the bot's code, the config and the bars only: kept beside the data for a rerun
    key = hashlib.sha256((DECISIONS_V + file_sha(os.path.join(ROOT, "paperbot", "mixchop.py")) + file_sha(CONFIG)
                          + json.dumps(data_info, sort_keys=True)).encode()).hexdigest()[:16]
    cache = os.path.join(args.data, f"decisions-{key}.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            got = json.load(fh)
        decided = {s: {int(k): v for k, v in d.items()} for s, d in got["decided"].items()}
        checks = got["checks"]
    else:
        decided, checks = {}, {}
        with ProcessPoolExecutor(min(3, os.cpu_count() or 1)) as ex:            # about 2 minutes a coin
            futs = {co.symbol: ex.submit(decisions, co, bars30[co.symbol], bars1h[co.symbol]) for co in cfg.coins}
            for sym, fut in futs.items():
                decided[sym], checks[sym] = fut.result()
                print(f"{sym}: {checks[sym]}", flush=True)
        with open(cache + ".part", "w", encoding="utf-8") as fh:
            json.dump({"decided": decided, "checks": checks}, fh, default=float)
        os.replace(cache + ".part", cache)
    specs = None
    if args.specs:
        with open(args.specs, encoding="utf-8") as fh:
            specs = json.load(fh)

    def spec_live(sym: str) -> dict:
        if specs and sym in specs:
            s = specs[sym]
            return {"qty_step": float(s.get("qty_step") or 0), "min_qty": float(s.get("min_qty") or 0), "tick": 0.0,
                    "min_notional": float(s.get("min_notional") or MIN_ORDER_USDT)}
        return {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": MIN_ORDER_USDT}

    def no_spec(sym: str) -> dict:
        return {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": 0.0}

    # the macro history for the entry block: FOMC + NFP 2020-2026 (research/hunt/macro_calendar.json) and the live file
    cal = json.load(open(os.path.join(ROOT, "research", "hunt", "macro_calendar.json"), encoding="utf-8"))["events"]
    live_csv = open(os.path.join(ROOT, "data", "macro_events.csv"), encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="mixchop5y-")
    hist_csv = os.path.join(tmp, "macro_events.csv")
    with open(hist_csv, "w", encoding="utf-8") as fh:
        fh.write("ts_utc,kind,source_url\n")
        for e in cal:
            fh.write(f"{e['utc'][:16]}:00Z,{e['kind']},{(e.get('source_urls') or ['x'])[0]}\n")
        fh.write("\n".join(x for x in live_csv.splitlines()[1:] if x and not x.startswith("#")) + "\n")
    keep_path = EV.PATH
    variants: dict = {}
    try:
        EV.PATH = hist_csv
        EV.reset()
        n_macro = len(EV.all_events())
        for name, fee in (("design", TAKER), ("design_fee02", DESIGN_FEE)):
            per = {}
            for co in cfg.coins:
                res = run_bot([co], decided, bars30, fee=fee, blocks=False, spec_fn=no_spec)
                ts = trades(res["rows"], risk)
                ref = DESIGN_REF.get(co.symbol)
                per[co.symbol] = {**stats(ts, risk), **month_stats(res["month_eq"], res["end_eq"]),
                                  "design_month_mean": ref[0] if ref else None, "design_win_rate": ref[1] if ref else None}
                print(f"{name} {co.symbol}: {per[co.symbol]}", flush=True)
            variants[name] = {"fee": fee, "coins": per}
        res = run_bot(list(cfg.coins), decided, bars30, fee=TAKER, blocks=False, spec_fn=no_spec)
        ts = trades(res["rows"], risk)
        variants["one_position"] = {"fee": TAKER, **stats(ts, risk), **month_stats(res["month_eq"], res["end_eq"]),
                                    "skips": skip_counts(res["rows"]),
                                    "coins": {co.symbol: stats([t for t in ts if t["symbol"] == co.symbol], risk) for co in cfg.coins}}
        print(f"one_position: {variants['one_position']['trades']} trades", flush=True)
        res = run_bot(list(cfg.coins), decided, bars30, fee=TAKER, blocks=True, spec_fn=spec_live)
        ts = trades(res["rows"], risk)
        variants["live_rules"] = {"fee": TAKER, **stats(ts, risk), **month_stats(res["month_eq"], res["end_eq"]),
                                  "skips": skip_counts(res["rows"]),
                                  "coins": {co.symbol: stats([t for t in ts if t["symbol"] == co.symbol], risk) for co in cfg.coins},
                                  "min_order": "specs" if specs else f"${MIN_ORDER_USDT:g} minimum order only (contract steps not modelled)",
                                  "band": band_reference(ts, res["month_eq"])}
        print(f"live_rules: {variants['live_rules']['trades']} trades", flush=True)
    finally:
        EV.PATH = keep_path
        EV.reset()
    out = {
        "what": "믹스 30분 봇 5-year replay with the bot's own code (research/mixchop5y/replay.py); the luck band's reference",
        "made_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "seconds": round(time.time() - t_start),
        "period": {"from": "2021-10-01", "to": "2026-10-01", "months": 60, "from_ms": T0, "to_ms": T1},
        "data": {"source": f"{ARCHIVE}/<SYMBOL>/<30m|1h>/ (monthly zips 2021-07 .. 2026-09, sha256 checked)", "coins": data_info},
        "code": {"mixchop_sha256": file_sha(os.path.join(ROOT, "paperbot", "mixchop.py")), "config": "deploy/mixchop.live.json",
                 "config_sha256": file_sha(CONFIG), "risk_pct": risk, "start_equity": 50.0,
                 "coins": [{"symbol": c.symbol, "h1_buf": c.h1_buf, "sl_atr": c.sl_atr, "roe_act": c.roe_act, "leverage": c.leverage}
                           for c in cfg.coins]},
        "checks": checks, "macro_events_used": n_macro,
        "design_ref": {s: {"month_mean": v[0], "win_rate": v[1]} for s, v in DESIGN_REF.items()},
        "variants": variants,
        # (owners' words, shown on the 믹스 성적 screen): live fill seconds after the close; WOO X Pro's last price for the
        # resting stop; funding; WOO X Pro's own liquidation brackets; CPI/PCE before 2026-10; NYSE holidays before
        # 2026; contract steps and per-coin minimum quantities
        "not_modelled": ["실거래는 봉 마감 몇 초 뒤 시장가로 체결 (재생은 신호 봉 종가에 체결)",
                         "WOO X Pro 최근 체결가 기준 손절 (재생은 바이낸스 30분봉으로 청산)",
                         "펀딩비", "WOO X Pro 자체 강제청산 구간 (봇이 실거래에서만 보는 점검)",
                         "2026-10 이전 CPI·PCE 발표 (FOMC·NFP는 research/hunt/macro_calendar.json 초안, 확인 안 됨)",
                         "2026년 이전 미국 증시 휴장일 (그날도 나스닥 개장 앞뒤 진입 금지를 적용함)",
                         "코인별 주문 단위·최소 수량" + ("" if specs else " ($5 최소 주문만 반영)")],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes) in {out['seconds']} s")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="replay.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("download", "run", "all"))
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--specs", default=None)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    if args.cmd in ("download", "all"):
        cmd_download(args)
    if args.cmd in ("run", "all"):
        cmd_run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
