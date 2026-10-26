"""추세판단 봇 replay with the Nasdaq-open / time arms of research/opentime/PREREG.md.

A COPY of research/trendbot/recent/sim.py (the minute-by-minute replay whose A0 equals data/trend_replay_0701_1020.json;
its docstring follows) with only these changes, marked "opentime" below:
  --arm A0..A6   the arm hooks at the END of a minute, after that minute's exit checks and lock step: A1 / A6 act at the
                 close of the 09:29 New York minute (the last minute of the 09:25 5m bar, trading weekdays), A3-5 at the
                 close of the minute that ends on the first 5m close >= entry + 4 / 8 / 12 h; a close is a market exit
                 (taker + slippage); A2 / A6 raise the stop to roe_price(.., 0 %, ..) (net break-even) when the net ROE
                 at that close is > 0 (ladder.tighten: never lowered); the raised stop is not a lock (JUDGE / REV stay on)
  diagnostics    per trade: open and unlocked at an M (and its net ROE), at 4 / 8 / 12 h, held minutes in 09:30-11:00
                 New York, the stop exit minute in that window; exit reason BE for the raised stop
  no coin-flip twin (--twin is ignored)
Run: python3 -I trend_sim.py ROOT TAG --config CONFIG --signals SIGNALS [--entry now] --arm A1

Replay of the 추세판단 봇 on Binance USD-M 1m bars, minute by minute, with the repo's own functions where they decide
an entry (combo.kst_weekend, combo.us_open_pause, events.near, combo.chase_check, trendjudge.Klines / Judge / check /
score, ladder2.ComboLadder, ladder.net_roe / roe_price / tighten). The runner / engine order of paperbot/combo.py +
paperbot/trendbot.py is re-implemented for ONE account (no database), per minute ts:
  1. the member signals whose bar closed at ts (entry block -> trend check -> pullback wait; every one of them is an
     early-exit candidate), then the pulled entries due at ts (entry block again at the entry minute)
  2. supervisor TIME / JUDGE (before the first lock only)
  3. engine: supervisor close at the open, else REV close at the open (own member, same coin, other side, bar closed
     after the entry, before the first lock); entries (one position; rank score > timeframe > order); then the exit
     checks of the bar (stop / ladder lock)
  4. pullback waits: touch (or, --entry limit, trade-through fill) of the waiting signals (t0 + 1 min .. until - 2 min)
This is research/trendbot/recent's copy of the 10-21 replay (scratchpad entryrate/code/simulate.py) with switches:
  --config PATH        the bot config (default: the repo's deploy/combo.trend.json)
  --time-bars N|none   trend.time_bars override         --us-pre N|none   us_open_pre_min override
  --vote-min N         trend.vote_min override
  --entry pullback|now|limit
        pullback = live: touch (low <= level / high >= level) -> market entry at the next minute's open
        now      = market entry at the signal minute's open (no pullback wait)
        limit    = a resting LIMIT at the level (on the tick grid: long rounded down, short up) from t0 + 1 min to the
                   deadline, filled at that price only when a trade printed THROUGH it (low < limit / high > limit, in
                   whole ticks; a low / high exactly at it is a touch, not a fill) in a minute with no position open,
                   no exit and no entry; maker fee, no slippage; the fill minute's favourable extreme is not counted
  --lock-maker         LOCK exits at their price with the maker fee and no slippage (an optimistic bound)
  --twin N             coin-flip twin: N draws (seed 1000 + d) of the same entries with a random side (default 200)
Every trade keeps its reference prices (entry_ref, exit_ref) and order kinds, so report.py can re-cost it.
Run: python3 -I sim.py ROOT TAG [switches]  -> ROOT/out/recent/TAG_*.csv / .json"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trendbot", "recent")))
from common import COINS, MIN, REPO, TF_MS, agg, load_1m, np, pd  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # opentime
import otcommon as OT  # noqa: E402  (opentime)
import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402

from paperbot import combo as C  # noqa: E402
from paperbot import events as EV  # noqa: E402
from paperbot.trendjudge import HTF_OF, Judge, Klines, TrendRules, check, score  # noqa: E402
from paperbot.ladder2 import ComboLadder  # noqa: E402
from paperbot.ladder import net_roe, roe_price, tighten  # noqa: E402
from paperbot.config import v3_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("root")
ap.add_argument("tag")
ap.add_argument("--config", default=f"{REPO}/deploy/combo.trend.json")
ap.add_argument("--signals", default=None)
ap.add_argument("--time-bars", default=None)
ap.add_argument("--us-pre", default=None)
ap.add_argument("--vote-min", type=int, default=None)
ap.add_argument("--entry", choices=("pullback", "now", "limit"), default="pullback")
ap.add_argument("--lock-maker", action="store_true")
ap.add_argument("--twin", type=int, default=200)
ap.add_argument("--arm", choices=tuple(OT.ARMS), default="A0")       # opentime
A = ap.parse_args()
ARM_KIND, ARM_HOURS = OT.ARMS[A.arm]                                  # opentime
ROOT, TAG = A.root, A.tag
OUT = f"{ROOT}/out/recent"
os.makedirs(OUT, exist_ok=True)

HOUR = 3_600_000
SIM_START = int(pd.Timestamp("2026-06-28 00:00", tz="UTC").value // 10**6)
SIM_END = int(pd.Timestamp("2026-10-21 00:00", tz="UTC").value // 10**6)        # exclusive (last minute 10-20 23:59)
WIN_START = int(pd.Timestamp("2026-06-30 15:00", tz="UTC").value // 10**6)      # KST 2026-07-01 00:00
WIN_END = int(pd.Timestamp("2026-10-20 15:00", tz="UTC").value // 10**6)        # KST 2026-10-21 00:00 (exclusive)

CFG = json.load(open(A.config))
TREND = dict(CFG["trend"])
if A.time_bars is not None:
    TREND["time_bars"] = None if A.time_bars == "none" else int(A.time_bars)
if A.vote_min is not None:
    TREND["vote_min"] = A.vote_min
if A.us_pre is not None:
    CFG["us_open_pre_min"] = None if A.us_pre == "none" else int(A.us_pre)
RULES = TrendRules.from_dict(TREND)
LADDER = ComboLadder.of(CFG["ladder"])
S = v3_settings()
RT, SLIP, TAKER, MAKER = S.round_trip_cost, S.slippage_frac, S.taker_fee, S.maker_fee
STOP_ROE = float(CFG["stop"]["roe"])
MARGIN = float(CFG["margin"])
MACRO_W = int(CFG["macro_blackout_min"]) * MIN
US_OPEN = int(CFG.get("us_open_pause_min") or 0)
US_PRE = int(CFG.get("us_open_pre_min") or 0)
NO_WEEKEND = bool(CFG["no_weekend"])
TIME_BARS = RULES.time_bars
ENTRY = A.entry
json.dump({"config": A.config, "trend": TREND, "us_open_pause_min": US_OPEN, "us_open_pre_min": US_PRE,
           "entry": ENTRY, "lock_maker": A.lock_maker, "rt": RT, "slip": SLIP, "taker": TAKER, "maker": MAKER},
          open(f"{OUT}/{TAG}_setup.json", "w"), indent=1)


def lev_of(sym):
    return int(CFG["leverage"].get(sym, CFG["leverage"]["default"]))


# ---------------------------------------------------------------- members
MEMBERS = {}
for i, m in enumerate(CFG["members"], 1):
    label = f"{m['strategy']}@{m['tf']}"
    when_side = None
    if m.get("when"):
        assert m["when"] == [{"side": "short"}], m["when"]
        when_side = -1
    MEMBERS[label] = {"name": m["strategy"], "tf": m["tf"], "order": i, "no_chase": bool(m.get("no_chase")),
                      "when_side": when_side}
assert all(v["no_chase"] for v in MEMBERS.values())
TF_MIN = {"30m": 30, "1h": 60}
PRI = list(C.V3_SYMBOLS)
# Binance USD-M price ticks (every 1m open / high / low / close of 05-01..10-20 sits on them; checked)
TICK = {"BTCUSDT": 0.1, "ETHUSDT": 0.01, "SOLUSDT": 0.01, "DOGEUSDT": 0.00001, "LTCUSDT": 0.01, "BCHUSDT": 0.01}

# ---------------------------------------------------------------- bars
print("loading bars", flush=True)
M1, BARS = {}, {}
for c in COINS:
    m = load_1m(ROOT, c)
    M1[c] = m
    BARS[c] = {tf: agg(m, TF_MS[tf]) for tf in ("30m", "1h", "4h")}
T0 = int(M1["BTCUSDT"]["ts"][0])
for c in COINS:
    assert int(M1[c]["ts"][0]) == T0 and len(M1[c]["ts"]) == len(M1["BTCUSDT"]["ts"])
    assert int(M1[c]["ts"][-1]) == SIM_END - MIN
H1 = {c: (BARS[c]["1h"]["ts"] // HOUR, BARS[c]["1h"]["h"], BARS[c]["1h"]["l"]) for c in COINS}


def mi(ts):
    return (int(ts) - T0) // MIN


def o1(c, ts):
    return float(M1[c]["o"][mi(ts)])


# ---------------------------------------------------------------- the judge on local bars
CLOCK = [0]


def fetch(symbol, tf, limit):
    b = BARS[symbol][tf]
    end = int(np.searchsorted(b["ts"], CLOCK[0], side="right"))        # bars opened at or before the clock
    lo = max(0, end - int(limit))
    return [[int(b["ts"][k]), b["o"][k], b["h"][k], b["l"][k], b["c"][k], b["v"][k]] for k in range(lo, end)]


KL = Klines(fetch, lambda: CLOCK[0])
JUDGE = Judge(KL, RULES)


def at(ts):
    CLOCK[0] = int(ts) + 65_000          # live: minute ts is stepped after its 1m bar closed (+ a few seconds)


# ---------------------------------------------------------------- the entry block (combo.ComboRunner._entry_block)
def chase_hours(symbol, bar_close):
    k = int(bar_close) // HOUR
    hidx, hh, ll = H1[symbol]
    a, b = np.searchsorted(hidx, k - C.CHASE_7D), np.searchsorted(hidx, k)
    return {int(hidx[j]): (float(hh[j]), float(ll[j])) for j in range(a, b)}


def entry_block(symbol, side, ts, bar_close, price):
    if NO_WEEKEND and C.kst_weekend(ts):
        return "weekend", ""
    near = EV.near(int(ts), MACRO_W, MACRO_W)
    if near:
        return "macro", near[0].kind
    if (US_OPEN or US_PRE) and C.us_open_pause(ts, US_OPEN, US_PRE):
        return "us_open", ""
    chase, why = C.chase_check(chase_hours(symbol, bar_close), bar_close, side, price)
    if chase is None:
        return "chase_nodata", why
    if chase:
        return "chase", why
    return "", ""


def check_cat(why):
    if "추세 보류" in why:
        return "check:htf_hold(" + ("held<2/raw flip" if "유지 확인 중" in why else "votes<min") + ")"
    if "이라" in why and "안 함" in why:
        return "check:htf_opposite"
    if "힘 약함" in why:
        return "check:adx<20"
    if "끝물" in why:
        return "check:adx_tired"
    if "돌파형" in why:
        return "check:breakout_not_early"
    if "너무 뻗음" in why:
        return "check:htf_ema_far"
    if "진입 자리 아님" in why:
        return "check:etf_ema_far"
    if "RSI" in why:
        return "check:rsi"
    return "check:other:" + why[:40]


# ---------------------------------------------------------------- signals
SIGFILE = A.signals or f"{ROOT}/out/signals.csv"
sig = pd.read_csv(SIGFILE)
sig = sig[(sig.bar_close >= SIM_START) & (sig.bar_close < SIM_END)]
SIGS = defaultdict(list)
for r in sig.itertuples(index=False):
    label = f"{r.member}@{r.tf}"
    if label not in MEMBERS:
        continue
    SIGS[int(r.bar_close)].append((label, r.symbol, int(r.side)))

# ---------------------------------------------------------------- state
funnel = Counter()
fun_m = defaultdict(Counter)
pulls = []
queue = defaultdict(list)
pos = None
wallet = float(CFG["initial_equity"])
trades = []
records = defaultdict(list)        # member label -> pnl list, newest first
entries = []
judge_seen = Counter()


def in_win(t):
    return WIN_START <= t < WIN_END


FATE = {}                          # (label, coin, signal bar close) -> how a signal that passed the check ended


def done(e, stage):
    count(stage, e["label"], e["t0"])
    FATE[(e["label"], e["symbol"], e["t0"])] = stage + ("(touched, not through)" if e.get("touch_only") else "")


def count(stage, label, t):
    if in_win(t):
        funnel[stage] += 1
        fun_m[label][stage] += 1


def close(ref, ts, reason, kind="taker"):
    """Close the position at reference price ``ref`` (a market / stop-market: taker fee and slippage; ``kind`` maker:
    the price itself and the maker fee)."""
    global pos, wallet
    p = pos
    price = ref * (1 - p["side"] * SLIP) if kind == "taker" else ref
    gross = p["side"] * p["qty"] * (price - p["entry"])
    if gross < -p["margin"]:
        wallet -= p["margin"]
        net = -p["margin"] - p["fee_in"]
        reason = "LIQ"
    else:
        exit_fee = p["qty"] * price * (TAKER if kind == "taker" else MAKER)
        wallet += gross - exit_fee
        net = gross - p["fee_in"] - exit_fee
    t = {**{k: p[k] for k in ("label", "symbol", "side", "tf", "entry_time", "entry", "entry_ref", "entry_kind", "lev",
                               "margin", "sig_t", "touch_t", "score")},
         "exit_time": int(ts), "exit": price, "exit_ref": ref, "exit_kind": kind, "reason": reason, "lock": p["lock"],
         "pnl": net, "roe": net / p["margin"], "wallet_after": wallet}
    k0, k1 = mi(p["entry_time"]), mi(ts)                                             # opentime: diagnostics
    t.update({x: p[x] for x in ("first_m", "roe_at_M", "R_at_M", "hours_at_M", "mfe_share_at_M", "open_4h", "open_8h",
                                "open_12h", "touched", "be")})
    t.update(held_in_window=int(WCUM[k1 + 1] - WCUM[k0]), held_bars=int(k1 - k0 + 1),
             sl_in_window=bool(reason == "SL" and WINM[k1]))
    trades.append(t)
    records[p["label"]].insert(0, net)
    pos = None


def raise_lock(p):
    best = net_roe(p["side"], p["entry"], p["mfe"], p["lev"], RT, 0.0)
    lock = LADDER.lock_for(best)
    if lock is None or (p["lock"] is not None and lock <= p["lock"] + 1e-12):
        return
    p["stop"] = tighten(p["side"], p["stop"], roe_price(p["side"], p["entry"], p["lev"], lock, RT, 0.0))
    p["lock"] = lock


def stop_close(ref, ts, reason):
    close(ref, ts, reason, "maker" if (A.lock_maker and reason == "LOCK") else "taker")


def handle_exit(ts, entry_bar):
    p = pos
    k = mi(ts)
    c = p["symbol"]
    o, h, l = float(M1[c]["o"][k]), float(M1[c]["h"][k]), float(M1[c]["l"][k])
    side = p["side"]
    if side > 0:
        p["mfe"] = max(p["mfe"], h)
    else:
        p["mfe"] = min(p["mfe"], l)
    reason = "LOCK" if p["lock"] is not None else ("BE" if p["be"] else "SL")      # opentime: BE
    if not entry_bar and (o - p["stop"]) * side <= 0:
        stop_close(o, ts, reason)
        return True
    hit = (l <= p["stop"]) if side > 0 else (h >= p["stop"])
    if hit:
        stop_close(p["stop"], ts + MIN - 1, reason)
        return True
    if not entry_bar:
        raise_lock(p)
    return False


def enter(e, ts, ref=None, kind="taker"):
    """Market entry at minute ts's open (taker + slippage), or (``kind`` maker) a limit fill at ``ref``."""
    global pos, wallet
    c, side = e["symbol"], e["side"]
    lev = lev_of(c)
    if ref is None:
        ref = o1(c, ts)
    fill = ref * (1 + side * SLIP) if kind == "taker" else ref
    dist = ref * (STOP_ROE / lev - RT)
    stop = ref - side * dist
    qty = wallet * MARGIN * lev / fill
    fee = qty * fill * (TAKER if kind == "taker" else MAKER)
    wallet -= fee
    pos = {"label": e["label"], "symbol": c, "side": side, "tf": e["tf"], "entry_time": int(ts), "entry": fill,
           "entry_ref": ref, "entry_kind": kind, "lev": lev, "margin": qty * fill / lev, "qty": qty, "fee_in": fee,
           "stop": stop, "lock": None, "mfe": fill, "dir": side, "sig_t": e["t0"], "touch_t": e.get("touch"),
           "score": e["score"],
           "stop0": stop, "first_m": -1, "roe_at_M": 0.0, "R_at_M": 0.0, "hours_at_M": 0.0, "mfe_share_at_M": 0.0,
           "open_4h": False, "open_8h": False, "open_12h": False, "touched": False, "be": False}       # opentime
    entries.append({"t": int(ts), "label": e["label"], "symbol": c, "side": side, "tf": e["tf"], "sig_t": e["t0"],
                    "score": e["score"], "kind": kind})


def rank_key(e):
    return (-e["score"], -TF_MIN[e["tf"]], e["order"], PRI.index(e["symbol"]), MEMBERS[e["label"]]["name"], e["tf"])


# ---------------------------------------------------------------- opentime: the clock and the arm hooks
NY29 = set(int(x) + 4 * MIN for x in OT.open_moments(SIM_START, SIM_END))     # the 09:29 New York minutes (M)
_mins = T0 + np.arange(len(M1["BTCUSDT"]["ts"]), dtype=np.int64) * MIN
WINM = OT.window_flags(_mins, MIN)                                              # minutes inside 09:30-11:00 New York
WCUM = np.r_[0, np.cumsum(WINM.astype(np.int64))]
FIRST_TRIGGER = float(CFG["ladder"]["first_lock"]) + float(CFG["ladder"]["trigger_gap"])   # 0.11


def five_close_after(t_ms, hours):
    """The first 5m close at or after t + hours."""
    x = int(t_ms) + int(hours) * HOUR
    return -(-x // 300_000) * 300_000


def arm_hook(ts):
    """The end of minute ts with the position still open (after its exit checks and lock step): diagnostics, then the
    arm of PREREG.md. Returns True when the arm closed the position."""
    p = pos
    if p["lock"] is not None:
        return False
    c, side = p["symbol"], p["side"]
    px = float(M1[c]["c"][mi(ts)])
    nr = net_roe(side, p["entry"], px, p["lev"], RT, 0.0)
    is_m = int(ts) in NY29
    if is_m and p["first_m"] < 0:
        trig = roe_price(side, p["entry"], p["lev"], FIRST_TRIGGER, RT, 0.0)
        p.update(first_m=int(ts), roe_at_M=float(nr), R_at_M=float(side * (px - p["entry"]) / abs(p["entry"] - p["stop0"])),
                 hours_at_M=(int(ts) + MIN - p["entry_time"]) / HOUR,
                 mfe_share_at_M=float(side * (p["mfe"] - p["entry"]) / (side * (trig - p["entry"]))))
    for hh in (4, 8, 12):
        if int(ts) + MIN == five_close_after(p["entry_time"], hh):
            p[f"open_{hh}h"] = True
    why, be = None, False
    if is_m:
        if ARM_KIND == "open_close" or (ARM_KIND == "open_mix" and nr <= 0):
            why = "OPENCUT"
        elif ARM_KIND in ("open_be", "open_mix") and nr > 0:
            be = True
        elif ARM_KIND == "open_deep" and side * (px - p["entry"]) / abs(p["entry"] - p["stop0"]) <= OT.DEEP_R:   # A7
            why = "OPENCUT"
    if ARM_KIND == "time" and int(ts) + MIN == five_close_after(p["entry_time"], ARM_HOURS):
        why = "TIME"
    if why is not None:
        p["touched"] = True
        close(px, ts + MIN - 1, why)
        return True
    if be:
        new = tighten(side, p["stop"], roe_price(side, p["entry"], p["lev"], 0.0, RT, 0.0))
        if new != p["stop"]:
            p["stop"] = new
            p["be"] = p["touched"] = True
    return False


# ---------------------------------------------------------------- the minute loop
t_start = time.time()
ts = SIM_START
n_min = 0
while ts < SIM_END:
    exit_sigs = []
    pending = []
    # 1a. the member signals of bars that closed at ts
    for label, c, side in SIGS.get(ts, ()):
        m = MEMBERS[label]
        count("1_member_signal", label, ts)
        if m["when_side"] is not None and side != m["when_side"]:
            count("x_outside_when(N20 long)", label, ts)
            exit_sigs.append((label, c, side, ts))
            continue
        count("2_inside_when", label, ts)
        price = o1(c, ts)
        why, detail = entry_block(c, side, ts, ts, price)
        if why:
            count(f"x_block_at_signal:{why}", label, ts)
            exit_sigs.append((label, c, side, ts))
            continue
        count("3_after_pauses_chase", label, ts)
        at(ts)
        htf = HTF_OF[m["tf"]]
        j = JUDGE.judgment(c, htf, ts)
        s = JUDGE.spot(c, m["tf"], ts)
        assert j.bar_close == ts - ts % TF_MS[htf] and s.bar_close == ts, (j.bar_close, s.bar_close, ts)
        why, info = check(RULES, m["name"], m["tf"], side, price, j, s)
        exit_sigs.append((label, c, side, ts))
        if why:
            count("x_" + check_cat(why), label, ts)
            continue
        count("4_passed_check", label, ts)
        if pos is not None:
            count("info:passed_check_while_position_open", label, ts)
        sc, parts = score(RULES, side, j, s, price, list(records[label]))
        e = {"label": label, "symbol": c, "side": side, "tf": m["tf"], "t0": ts, "until": ts + TF_MS[m["tf"]],
             "level": float(info["level"]), "score": float(sc), "order": m["order"], "big": info["big_bar"]}
        if ENTRY == "now":
            count("5_entry_now", label, ts)
            pending.append({**e, "touch": None})
        else:
            pulls.append(e)
    # 1b. pulled entries due now
    for e in queue.pop(ts, ()):
        why, _d = entry_block(e["symbol"], e["side"], ts, ts, o1(e["symbol"], ts))
        if why:
            done(e, f"x_block_at_entry:{why}")
            continue
        pending.append(e)
    # 2. supervisor
    sup = None
    if pos is not None and pos["lock"] is None and ts > pos["entry_time"]:
        tfm = TF_MS[pos["tf"]]
        if TIME_BARS is not None and ts >= pos["entry_time"] + TIME_BARS * tfm:
            sup = "TIME"
        elif RULES.judge_exit:
            htf = HTF_OF[pos["tf"]]
            if ts % TF_MS[htf] == 0:          # a new higher bar closed (between boundaries the judgment is the same)
                at(ts)
                j = JUDGE.judgment(pos["symbol"], htf, ts)
                assert j.bar_close == ts
                judge_seen[int(j.raw) * pos["dir"]] += 1
                if j.bar_close > pos["entry_time"] and j.raw == -pos["dir"]:
                    sup = "JUDGE"
    # 3. engine step
    exited_now = False
    if sup is not None:
        close(o1(pos["symbol"], ts), ts, sup)
        exited_now = True
        for e in pending:
            done(e, "x_skip_exit_this_minute")
        pending = []
        exit_sigs = []
    if exit_sigs and pos is not None and pos["lock"] is None:
        hit = [g for g in exit_sigs if g[1] == pos["symbol"] and g[2] == -pos["side"] and g[3] > pos["entry_time"]
               and g[0] == pos["label"]]
        if hit:
            close(o1(pos["symbol"], ts), ts, "REV")
            exited_now = True
            for e in pending:
                done(e, "x_skip_exit_this_minute")
            pending = []
    entered_now = False
    if pending:
        if pos is not None:
            for e in pending:
                done(e, "x_skip_in_position")
        else:
            pending.sort(key=rank_key)
            enter(pending[0], ts)
            entered_now = True
            done(pending[0], "6_entered")
            for e in pending[1:]:
                done(e, "x_skip_lower_score")
    if pos is not None:
        exited_now = handle_exit(ts, entered_now) or exited_now
    if pos is not None:                                                              # opentime: the arm hooks
        exited_now = arm_hook(ts) or exited_now
    # 4. pullback waits
    keep, fills = [], []
    for p_ in pulls:
        if ts >= p_["until"] - MIN:
            done(p_, "x_no_pullback")
            if p_.get("touch_only"):
                count("info:limit_missed_touched_not_through", p_["label"], p_["t0"])
            continue
        if ts <= p_["t0"]:
            keep.append(p_)
            continue
        k = mi(ts)
        lo, hi = float(M1[p_["symbol"]]["l"][k]), float(M1[p_["symbol"]]["h"][k])
        if ENTRY == "limit":
            # the order's price on the tick grid (long: rounded down, short: up; never worse than the level); filled
            # only when a trade printed beyond it, in whole ticks; a low / high exactly at it is a touch, not a fill
            tick = TICK[p_["symbol"]]
            if p_["side"] > 0:
                lim = int(np.floor(p_["level"] / tick + 1e-9))
                at_ = int(round(lo / tick))
                crossed, touch_only = at_ < lim, at_ == lim
            else:
                lim = int(np.ceil(p_["level"] / tick - 1e-9))
                at_ = int(round(hi / tick))
                crossed, touch_only = at_ > lim, at_ == lim
            if touch_only:
                p_["touch_only"] = True
            p_["limit"] = lim * tick
        else:
            crossed = lo <= p_["level"] if p_["side"] > 0 else hi >= p_["level"]
        if not crossed:
            keep.append(p_)
            continue
        count("5_pullback_touched", p_["label"], p_["t0"])
        if ENTRY == "limit":
            fills.append({**p_, "touch": ts})
        else:
            queue[ts + MIN].append({**p_, "touch": ts})
    pulls = keep
    if fills:
        busy = pos is not None or exited_now or entered_now
        ok = []
        for e in fills:
            if busy:
                done(e, "x_skip_in_position")
                continue
            why, _d = entry_block(e["symbol"], e["side"], ts, ts, e["limit"])
            if why:
                done(e, f"x_block_at_entry:{why}")
                continue
            ok.append(e)
        if ok:
            ok.sort(key=rank_key)
            e = ok[0]
            enter(e, ts, ref=e["limit"], kind="maker")
            done(e, "6_entered")
            for x in ok[1:]:
                done(x, "x_skip_lower_score")
            # the fill minute: the stop can be hit after the fill (conservative); its favourable extreme is not counted
            k = mi(ts)
            c = pos["symbol"]
            h, l = float(M1[c]["h"][k]), float(M1[c]["l"][k])
            if (l <= pos["stop"]) if pos["side"] > 0 else (h >= pos["stop"]):
                close(pos["stop"], ts + MIN - 1, "SL")
    ts += MIN
    n_min += 1
    if n_min % 40000 == 0:
        print(f"{pd.to_datetime(ts, unit='ms')} entries {len(entries)} trades {len(trades)} wallet {wallet:.0f} "
              f"{time.time() - t_start:.0f}s", flush=True)

if pos is not None:
    close(float(M1[pos["symbol"]]["c"][mi(SIM_END - MIN)]), SIM_END - MIN, "OPEN_AT_END")

E = pd.DataFrame(entries)
T = pd.DataFrame(trades)
E.to_csv(f"{OUT}/{TAG}_entries.csv", index=False)
T.to_csv(f"{OUT}/{TAG}_trades.csv", index=False)
fm = pd.DataFrame(fun_m).T.fillna(0).astype(int)
fm = fm[sorted(fm.columns)]
fm.to_csv(f"{OUT}/{TAG}_funnel_by_member.csv")
pd.DataFrame([(k[0], k[1], k[2], v) for k, v in FATE.items()], columns=["label", "symbol", "sig_t", "fate"]).to_csv(
    f"{OUT}/{TAG}_fates.csv", index=False)
print(f"main loop {time.time() - t_start:.0f}s; entries {len(E)}; wallet {wallet:.2f}", flush=True)

json.dump({"funnel": dict(sorted(funnel.items())), "wallet_end_from_sim_start": wallet, "sim_start": SIM_START,
           "win": [WIN_START, WIN_END], "arm": A.arm, "entry": ENTRY, "config": A.config, "signals_file": SIGFILE,
           "elapsed_s": round(time.time() - t_start)}, open(f"{OUT}/{TAG}_summary.json", "w"), indent=1)   # opentime
