"""5분봉 OBV 전환 백테스트 (owners 11-04 evening: "15분봉30분봉 히스토 그램 추세가 같아야하고 5분봉에서 obv macd가 0선아래에서
양봉이 나오면 롱 진입 숏진입은 반대 조건으로"). The plan and the pass/fail criteria were written before any run:
research/obv5m/PLAN_KO.md. The third try after research/obv15both (A, B).

One rule, C, the bot's OWN code (paperbot/mixchop.py) with the live config deploy/mixchop.live.json (rule "o4h", tf "5m",
trend "macd" on trend_tf 30m and trend_tf2 15m, stop_tf 15m: the fixed 15m ATR x 3).

    python3 -I research/obv5m/replay.py download    # 5m zips (the 15m / 30m / 1m ones: research/obv15both download)
    python3 -I research/obv5m/replay.py decide      # the bot's evaluate_friend at the 5m OBV turns (cached in --data)
    python3 -I research/obv5m/replay.py dev         # the development period -> summary.json "dev" (+ "dev_fixed")
    python3 -I research/obv5m/replay.py sealed      # ONLY if dev passes, ONCE -> "sealed"
    python3 -I research/obv5m/replay.py report      # REPORT_KO.md

The helpers are research/obv15both/replay.py's (download, bars, the paper bot without files, the trade numbers, the
macro history, the verdict): loaded from that file.

The decisions (the bot's own evaluate_friend on the 1,499 closed 5m / 15m / 30m bars it holds at each 5m close; the
15m frame is both its second trend's and its stop's, as Bot.extra_bars reads it once):
- marked closes: the OBV histogram's turn on the long / short side (FT.o4_pane on the whole 5m series) where the 추세
  MACD of the last closed 30m bar AND of the last closed 15m bar (FT.tmacd_pane on the whole series) are on that side.
  Only there can the bot enter; there the real evaluate_friend gives the answer.
- checked on samples: turns where the whole-series 30m (or 15m) trend is against: the bot's own window must say no
  entry too; closes without a marked turn: no turn in the window. Any difference is counted in summary "checks".
- FT.tmacd_state is memoized by its input bytes in the decide workers (the same 30m / 15m window at several 5m closes):
  the same function, the same inputs, the same answer, computed once.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
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

_spec = importlib.util.spec_from_file_location("obv15both_replay", os.path.join(ROOT, "research", "obv15both", "replay.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

DATA = os.environ.get("OBV5M_DATA") or P.DATA                 # the same data folder (15m / 30m / 1m there already)
OUT = os.path.join(HERE, "summary.json")
CONFIG = os.path.join(ROOT, "deploy", "mixchop.live.json")
SYMS = P.SYMS
TF_MS = {"5m": M.MIN5, "15m": M.MIN15, "30m": M.MIN30, "1m": M.MIN1}
FIRST = {"5m": (2024, 10), "15m": (2024, 9), "30m": (2024, 9), "1m": (2024, 11)}
LAST = (2026, 10)
T0, TS, T1 = P.T0, P.TS, P.T1
PERIODS = P.PERIODS
HIST = P.HIST
JUDGE_MS = P.JUDGE_MS
START_EQ = P.START_EQ
FEES = P.FEES
DECISIONS_V = "1"
# the rules tried (PLAN_KO.md): C the three coins from $50; C-ZEC (added before any result, owners 11-04 evening: one bot,
# ZEC only, Toobit, $26) -> {key: (coins or None for the config's, start equity, words)}
VARIANTS = {"C": (None, 50.0, "C (BTC · SOL · ZEC, $50)"), "CZ": (["ZECUSDT"], 26.0, "C-ZEC (ZEC만, $26)")}


def months(tf: str):
    y, m = FIRST[tf]
    while (y, m) <= LAST:
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


def cmd_download(args) -> int:
    jobs = [(s, "5m", mo) for s in SYMS for mo in months("5m")]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: P.fetch_one(args.data, *j), jobs))
    print(f"{len(res)} files: {res.count('new')} new, {res.count('kept')} kept", flush=True)
    return 0


def read_klines(data: str, sym: str, tf: str) -> np.ndarray:
    rows = []
    for mo in months(tf):
        path = P.zip_path(data, sym, tf, mo)
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


def live_coins() -> dict:
    return {c.symbol: c for c in M.load_config(CONFIG).coins}


# ====================================================================== decisions
def _memo_tmacd():
    real = FT.tmacd_state
    cache: dict = {}

    def memo(h, l, c, v):
        key = hashlib.blake2b(b"".join(np.ascontiguousarray(x, dtype=float).tobytes() for x in (h, l, c, v)),
                              digest_size=16).digest()
        hit = cache.get(key)
        if hit is None:
            if len(cache) > 20_000:
                cache.clear()
            hit = cache[key] = real(h, l, c, v)
        return dict(hit)
    FT.tmacd_state = memo


def decide_coin(data: str, sym: str, sample: int = 1000, seed: int = 13) -> dict:
    _memo_tmacd()
    co = live_coins()[sym]
    a5, a15, a30 = (read_klines(data, sym, tf) for tf in ("5m", "15m", "30m"))
    ce5 = a5[:, 0].astype(np.int64) + M.MIN5
    close15 = a15[:, 0].astype(np.int64) + M.MIN15
    close30 = a30[:, 0].astype(np.int64) + M.MIN30
    O = FT.o4_pane(a5[:, 2], a5[:, 3], a5[:, 4], a5[:, 5])
    T15 = FT.tmacd_pane(a15[:, 2], a15[:, 3], a15[:, 4], a15[:, 5])["trend"]
    T30 = FT.tmacd_pane(a30[:, 2], a30[:, 3], a30[:, 4], a30[:, 5])["trend"]
    k15 = np.searchsorted(close15, ce5, side="right") - 1
    k30 = np.searchsorted(close30, ce5, side="right") - 1
    lo = max(HIST - 1, int(np.searchsorted(ce5, T0, side="left")))
    hi = int(np.searchsorted(ce5, T1, side="right"))
    side = O["side"].astype(int)
    turns = [i for i in range(lo, hi) if side[i] != 0]
    agree30 = [i for i in turns if int(T30[k30[i]]) == side[i]]
    marked = [i for i in agree30 if int(T15[k15[i]]) == side[i]]
    against30 = sorted(set(turns) - set(agree30))
    against15 = sorted(set(agree30) - set(marked))

    def ev_at(i: int) -> dict:
        ce = int(ce5[i])
        j30, j15 = int(k30[i]), int(k15[i])
        b = M.bars_frame(a5[i - HIST + 1:i + 2].tolist(), M.MIN5, ce)
        tb = M.bars_frame(a30[j30 - HIST + 1:j30 + 2].tolist(), M.MIN30, ce)
        t15 = M.bars_frame(a15[j15 - HIST + 1:j15 + 2].tolist(), M.MIN15, ce)
        return M.evaluate_friend("o4h", co, b, ce, M.MIN5, "macd", tb=tb, trend_tf_ms=M.MIN30, tb2=t15, trend_tf2_ms=M.MIN15,
                                 sb=t15, stop_tf_ms=M.MIN15)

    C, turn_differs = {}, 0
    for i in marked:
        ev = ev_at(i)
        if P.o4_want(ev) != side[i]:
            turn_differs += 1
        C[int(ce5[i])] = ev
    rng = np.random.default_rng(seed)

    def pick(xs, n):
        return [int(x) for x in rng.choice(np.array(xs, dtype=np.int64), size=min(n, len(xs)), replace=False)] if xs else []
    s30 = pick(against30, sample)
    s15 = pick(against15, sample)
    plain = pick(sorted(set(range(lo, hi)) - set(turns)), sample // 2)
    e30 = [ev_at(i) for i in s30]
    e15 = [ev_at(i) for i in s15]
    checks = {"turns": len(turns), "marked": len(marked), "window_turn_differs_at_marked": turn_differs,
              "sampled_30m_against": len(s30), "of_them_window_enters": sum(1 for e in e30 if e["side"]),
              "of_them_window_30m_differs": sum(1 for e, i in zip(e30, s30) if int(e.get("trend", 0)) != int(T30[k30[i]])),
              "sampled_15m_against": len(s15), "of_them_window_enters_15": sum(1 for e in e15 if e["side"]),
              "of_them_window_15m_differs": sum(1 for e, i in zip(e15, s15) if int(e.get("tsig", 0)) != int(T15[k15[i]])),
              "sampled_no_turn": len(plain), "of_them_window_turn": sum(1 for i in plain if P.o4_want(ev_at(i)) != 0),
              "c_entries": sum(1 for e in C.values() if e["side"])}
    return {"C": C, "checks": checks}


def decisions_path(data: str) -> str:
    key = hashlib.sha256((DECISIONS_V + P.file_sha(os.path.join(ROOT, "paperbot", "mixchop.py"))
                          + P.file_sha(os.path.join(ROOT, "paperbot", "friendtrend.py")) + P.file_sha(CONFIG)
                          + json.dumps({s: {tf: P.gaps(read_klines(data, s, tf), TF_MS[tf]) for tf in ("5m", "15m", "30m")}
                                        for s in SYMS}, sort_keys=True)).encode()).hexdigest()[:16]
    return os.path.join(data, f"decisions5m-{key}.json")


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
    return {s: {"C": {int(k): v for k, v in d["C"].items()}, "checks": d["checks"]} for s, d in got.items()}


# ====================================================================== the bot, every 5m close
_EMPTY = pd.DataFrame(columns=["open_ms", "open", "high", "low", "close", "volume"])


class ReplayBot(P.ReplayBot):
    """The paper bot without files (obv15both); its 15m read skipped too (the answers are the decisions)."""

    def extra_bars(self, symbol: str, close_ms: int) -> dict:
        return {"tb2": _EMPTY, "sb": _EMPTY}


def make_cfg(fee: float, tmp: str, coins=None, start: float = START_EQ) -> "M.Config":
    d = json.load(open(CONFIG, encoding="utf-8"))
    d.update(mode="paper", state=os.path.join(tmp, "none", "state.json"), log=os.path.join(tmp, "none", "log.jsonl"),
             kill_file=os.path.join(tmp, "none", "STOP"), own_stop_file=os.path.join(tmp, "none", "OWN"), telegram=False,
             taker_fee=fee, start_equity=start)
    # the plan's coins: BTC 40x · SOL 40x · ZEC 20x (the live configs of then), or ZEC alone (C-ZEC)
    lev = {"BTCUSDT": 40, "SOLUSDT": 40, "ZECUSDT": 20}
    d["coins"] = {s: {"leverage": lev[s]} for s in (coins or SYMS)}
    p = os.path.join(tmp, f"cfg5m-{fee}-{len(d['coins'])}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    cfg = M.load_config(p)
    assert (cfg.rules, cfg.tf, cfg.trend, cfg.trend_tf, cfg.trend_tf2, cfg.stop_tf) == (("o4h",), "5m", "macd", "30m", "15m", "15m")
    return cfg


class FixedFrom(M.PaperBroker):
    """The same-size view: every entry sized from the variant's start (obv15both's FixedBroker, its own start)."""

    def equity(self) -> float:
        return self.start

    def __init__(self, start, *a, **kw):
        self.start = float(start)
        super().__init__(start, *a, **kw)


def run_bot(fee: float, period: str, dec: dict, bars: dict, tmp: str, fixed: bool = False, coins=None,
            start: float = START_EQ) -> dict:
    t_from, t_to = PERIODS[period]
    cfg = make_cfg(fee, tmp, coins, start)
    clock = P.Clock()
    opens = {s: {tf: a[:, 0].astype(np.int64) for tf, a in d.items()} for s, d in bars.items()}

    def fetch(symbol: str, tf: str, n: int) -> list:
        j = int(np.searchsorted(opens[symbol][tf], clock.t, side="right"))
        return bars[symbol][tf][max(0, j - n):j].tolist()

    def lookup(r, co, b, close_ms, tf_ms=M.MIN30, trend="four", tb=None, trend_tf_ms=None, trend_both=False,
               tb2=None, trend_tf2_ms=None, sb=None, stop_tf_ms=None):
        assert (r, tf_ms, trend, trend_tf_ms, trend_both, trend_tf2_ms, stop_tf_ms) == \
            ("o4h", M.MIN5, "macd", M.MIN30, False, M.MIN15, M.MIN15)
        ev = dec[co.symbol]["C"].get(close_ms)
        return dict(ev) if ev else {"symbol": co.symbol, "close_ms": close_ms, "side": 0, "rule": "o4h",
                                    "why": "OBV 히스토그램 전환 없음 또는 추세 다름"}

    spec = lambda s: {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": P.MIN_ORDER}  # noqa: E731
    broker = FixedFrom(start, fee, spec) if fixed else M.PaperBroker(start, fee, spec)
    keep = M.evaluate_friend
    M.evaluate_friend = lookup
    try:
        bot = ReplayBot(cfg, broker, fetch, clock, sleep=lambda s: None)
        clock.t = t_from
        bot.start()
        month_eq, cur = [], None
        for ce in range(t_from + M.MIN5, t_to + M.MIN5, M.MIN5):
            mo = time.strftime("%Y-%m", time.gmtime((ce - 1) / 1000))
            if mo != cur:
                month_eq.append((mo, broker.equity()))
                cur = mo
            clock.t = ce + JUDGE_MS
            bot.on_close(ce)
        if bot.pos is not None:
            p = bot.pos
            a = bars[p.symbol]["1m"]
            j = int(np.searchsorted(opens[p.symbol]["1m"], t_to, side="left")) - 1
            bot.finish(p, float(a[j, 4]), "end")
    finally:
        M.evaluate_friend = keep
    return {"rows": bot.rows, "month_eq": month_eq, "end_eq": broker.equity()}


def _passed_dev(summary: dict, key: str) -> bool:
    return all(p for _, p, _ in P.verdict(summary, key) if p is not None)


def cmd_period(args, period: str) -> int:
    summary = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {}
    keys = list(VARIANTS)
    if period == "sealed":
        if "dev" not in summary:
            raise SystemExit("dev first")
        keys = [k for k in VARIANTS if _passed_dev(summary, k)]
        if not keys:
            raise SystemExit("no rule passed the dev criteria: the sealed period stays closed (PLAN_KO.md)")
        if "sealed" in summary and not args.again:
            raise SystemExit("the sealed period was already opened once")
    t = time.time()
    dec = load_decisions(args.data)
    bars = {s: {"1m": P.read_klines(args.data, s, "1m")} for s in SYMS}
    tmp = tempfile.mkdtemp(prefix="obv5m-")
    keep_path, keep_start = EV.PATH, P.START_EQ
    res: dict = {}
    fixed: dict = {}
    try:
        EV.PATH = P.macro_history(tmp)
        EV.reset()
        for key in keys:
            coins, start, _ko = VARIANTS[key]
            P.START_EQ = start                              # (obv15both's numbers count from the run's start)
            for fk in ("toobit", "wooxpro", "fee_x2"):
                r = run_bot(FEES[fk], period, dec, bars, tmp, coins=coins, start=start)
                ts = P.trades(r["rows"], FEES[fk])
                res[f"{key}_{fk}"] = {"rule": key, "fee": FEES[fk], "start": start, "coins": coins or list(SYMS),
                                      **P.summarize(ts, r["end_eq"], r["month_eq"]), "skips": P.skip_counts(r["rows"]),
                                      "ladder_moves": sum(1 for x in r["rows"] if x["kind"] == "ladder")}
                x = res[f"{key}_{fk}"]
                print(f"{period} {key} {fk}: {x['trades']} trades, win {x['win_rate']}, exp {x['exp_pct']}%, return "
                      f"{x['return_pct']}%, max DD {x['max_dd_pct']}%, under $1 {x['under_1usd']}", flush=True)
            if period == "dev":                           # the same-size view (the plan's "함께 내는 것")
                for fk in ("toobit", "wooxpro", "zero"):
                    r = run_bot(FEES[fk], period, dec, bars, tmp, fixed=True, coins=coins, start=start)
                    fixed[f"{key}_{fk}"] = {"rule": key, "fee": FEES[fk], **P.summarize_fixed(P.trades(r["rows"], FEES[fk]))}
                    x = fixed[f"{key}_{fk}"]
                    print(f"fixed {key} {fk}: {x['trades']} trades, win {x['win_rate']}, exp {x['exp_pct']}%, sum "
                          f"{x['sum_pct']}%, months up {x['pos_months']}/{x['n_months']}", flush=True)
    finally:
        EV.PATH, P.START_EQ = keep_path, keep_start
        EV.reset()
    summary["what"] = ("5분봉 OBV 전환 백테스트: C (BTC · SOL · ZEC, $50) · C-ZEC (ZEC만, $26), 30분 · 15분 추세 MACD 같은 쪽, "
                       "손절 15분봉 ATR × 3; plan: research/obv5m/PLAN_KO.md")
    summary.setdefault("code", {})[period] = {"mixchop_sha256": P.file_sha(os.path.join(ROOT, "paperbot", "mixchop.py")),
                                              "friendtrend_sha256": P.file_sha(os.path.join(ROOT, "paperbot", "friendtrend.py")),
                                              "config": "deploy/mixchop.live.json (coins set per rule)",
                                              "config_sha256": P.file_sha(CONFIG)}
    summary["checks"] = {s: dec[s]["checks"] for s in SYMS}
    summary["data"] = {s: {**{tf: P.gaps(read_klines(args.data, s, tf), TF_MS[tf]) for tf in ("5m", "15m", "30m")},
                           "1m": P.gaps(bars[s]["1m"], M.MIN1)} for s in SYMS}
    summary[period] = {"from": time.strftime("%Y-%m-%d", time.gmtime(PERIODS[period][0] / 1000)),
                       "to": time.strftime("%Y-%m-%d", time.gmtime(PERIODS[period][1] / 1000 - 1)),
                       "made_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "seconds": round(time.time() - t),
                       "rules": keys, "runs": res}
    if fixed:
        summary["dev_fixed"] = {"what": "같은 크기 보기 (계획의 '함께 내는 것', 판정에 안 씀): 개발 구간 18개월 전체를 진입마다 시작 잔고 "
                                        "기준 같은 크기로 (복리 없음). zero = 수수료 0, 수수료가 가져가는 몫을 보려는 분해용",
                                "runs": fixed}
    with open(args.out + ".part", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(args.out + ".part", args.out)
    print(f"wrote {args.out} ({period}) in {time.time() - t:.0f} s")
    return 0


# ====================================================================== the report
def cmd_report(args) -> int:
    sm = json.load(open(args.out, encoding="utf-8"))
    prev = json.load(open(os.path.join(ROOT, "research", "obv15both", "summary.json"), encoding="utf-8"))
    L = ["# 5분봉 OBV 전환 백테스트 결과 (30분 · 15분 추세 MACD 같은 쪽 + 5분봉 OBV 히스토그램 전환, 손절 15분봉 ATR × 3)", "",
         "계획과 합격 기준: `research/obv5m/PLAN_KO.md` (결과 보기 전에 커밋, C-ZEC도 결과 보기 전에 추가). 숫자: "
         "`research/obv5m/summary.json`. 프로그램: `research/obv5m/replay.py` (봇의 실제 코드로 판단 · 매매). "
         "이 파일은 `replay.py report`가 만듭니다.", "",
         "- **C-ZEC**: ZEC만(20배), 투비트, 잔고 $26에서 시작 — 두 분이 실제로 켤 봇", "- **C**: BTC · SOL · ZEC(40 · 40 · 20배), $50에서 시작", ""]
    head = ["| 규칙 · 수수료 | 거래 | 승률 | 평균 이익 | 평균 손실 | 본전 승률 | 거래당 기대값 | 복리 수익 | 최대 낙폭 | 최장 연속 손실 | 손절 · 1칸 · 2칸↑ |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    fko = {"toobit": "투비트 0.06%", "wooxpro": "WOO X Pro 0.042%", "fee_x2": "2배 0.12%", "zero": "수수료 0 (분해용, 실제 아님)"}
    name = {"CZ": "C-ZEC", "C": "C"}
    for period, ko in (("dev", "개발 구간"), ("sealed", "봉인 구간")):
        if period not in sm:
            continue
        S = sm[period]
        L += [f"## {ko} ({S['from']} ~ {S['to']}, 복리)", "", "금액은 모두 진입 때 잔고 대비 %(수수료 뺀 것).", ""] + head
        for key in ("CZ", "C"):
            for fk in ("toobit", "wooxpro", "fee_x2"):
                x = S["runs"].get(f"{key}_{fk}")
                if x:
                    L.append(f"| {name[key]} · {fko[fk]} " + P.fmt_run(x))
        L.append("")
        for key in ("CZ", "C"):
            x = S["runs"].get(f"{key}_toobit")
            if not x:
                continue
            L += [f"{name[key]} (투비트, ${x['start']:g}에서): " + ", ".join(
                      f"{s.replace('USDT', '')} {v['n']}번 승률 {(v['win_rate'] or 0) * 100:.0f}% 기대값 {(v['exp_pct'] or 0):+.2f}%"
                      for s, v in x["coins"].items() if isinstance(v, dict) and v.get("n"))
                  + f" · 롱 {x['long']['n']}번 {(x['long']['exp_pct'] or 0):+.2f}% · 숏 {x['short']['n']}번 {(x['short']['exp_pct'] or 0):+.2f}%"
                  + f" · 손절 폭 중간값 {x['stop_pct_median']}% · 보유 시간 중간값 {x['hold_h_median']}시간 · 끝 잔고 ${x['end_eq']:,.2f}"
                  + (f" · **잔고가 $1 아래로 떨어진 날 {x['under_1usd']}** (그 뒤로는 최소 주문 $5보다 작아 거래 못 함)"
                     if x.get("under_1usd") else f" · 손해 본 달 {x['neg_months']}/{x['months']}"),
                  "", f"{name[key]} 청산 단계: " + ", ".join(
                      f"{'손절' if k == '0' else '구간 끝' if k == 'end' else k + '칸'} {v['n']}번 평균 {v['avg_pct']:+.2f}%"
                      for k, v in x["exits"].items()), ""]
    L += ["## 미리 정한 기준으로 판정 (투비트 수수료)", ""]
    for key in ("CZ", "C"):
        v = P.verdict(sm, key)
        ok = all(p for _, p, _ in v) and len(v) == 5
        L += [f"**{name[key]}**: " + ("합격 (다시 켜도 되는 후보)" if ok else "불합격" if any(p is False for _, p, _ in v) else "판정 전"), ""]
        L += [f"- {'✔' if p else '✘' if p is False else '…'} {w}: {n}" for w, p, n in v] + [""]
    if "sealed" not in sm and all(any(p is False for _, p, _ in P.verdict(sm, k)) for k in ("CZ", "C")):
        L += ["봉인 구간(2026-05 ~ 10)은 **열지 않았습니다**: 두 규칙 모두 개발 구간에서 이미 불합격이라 판정이 바뀌지 않습니다. "
              "다음 시도를 위해 남깁니다.", ""]
    fx = sm.get("dev_fixed")
    pf = prev.get("dev_fixed", {}).get("runs", {})
    if fx:
        L += ["## 같은 크기 보기 (판정에 안 씀): 18개월 전체를 매번 같은 크기로, 지난 시험 B(15분봉 신호, 세 코인)와 나란히", "",
              "| 규칙 · 수수료 | 거래 | 승률 | 평균 이익 | 평균 손실 | 본전 승률 | 거래당 기대값 | 합계(시작 잔고 대비) | 번 달 | 손절 · 1칸 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for fk in ("toobit", "wooxpro", "zero"):
            for tag, x in (("C-ZEC 5분봉", fx["runs"].get(f"CZ_{fk}")), ("C 5분봉", fx["runs"].get(f"C_{fk}")),
                           ("B 15분봉", pf.get(f"B_{fk}"))):
                if x:
                    L.append(f"| {tag} · {fko[fk]} | {x['trades']} | {x['win_rate'] * 100:.1f}% | {x['avg_win_pct']:+.2f}% | "
                             f"{x['avg_loss_pct']:+.2f}% | {(x['breakeven_win_rate'] or 0) * 100:.1f}% | **{x['exp_pct']:+.2f}%** | "
                             f"{x['sum_pct']:+.0f}% | {x['pos_months']}/{x['n_months']} | {x['stops']} · {x['lock1']} |")
        L.append("")
    ck = sm.get("checks", {})
    if ck:
        L += ["## 검사 (봇이 그 시각에 읽는 봉으로 다시 본 것)", ""]
        L += [f"- {s.replace('USDT', '')}: 전환 {c['turns']}번 중 30분 · 15분 추세가 같은 쪽 {c['marked']}번(여기서 봇 코드로 판단). "
              f"표본: 30분이 반대인 {c['sampled_30m_against']}곳 중 봇이 들어가는 곳 {c['of_them_window_enters']}, "
              f"15분이 반대인 {c['sampled_15m_against']}곳 중 {c['of_them_window_enters_15']}, 전환 없는 {c['sampled_no_turn']}곳 중 "
              f"전환 {c['of_them_window_turn']}" for s, c in ck.items()]
        L.append("")
    L += ["승률의 '이긴 거래' = 수수료까지 뺀 손익이 0보다 큰 거래.", "",
          "## 모델에 없는 것", "", "미끄러짐(수수료 2배로 대신 봄), 펀딩비, 거래소별 가격 차이(바이낸스 봉), 2026년 전 CPI · PCE 발표, "
          "2026년 전 미국 증시 휴장일, 계약 단위(최소 $5 주문만; 투비트 ZEC의 실제 최소 단위는 서버 점검으로 확인).", ""]
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
    ap.add_argument("--again", action="store_true")
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
