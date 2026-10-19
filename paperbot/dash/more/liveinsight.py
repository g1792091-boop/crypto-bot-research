"""실거래 › 규칙 점검 · 목표 · 위험 · 봇 상태 · 그룹 (owners 10/19 night, "규칙봇 15"): what the new rules did since the new config
started, how far the month is from the owners' goal, what one more stop would cost, whether every bot is alive, and the
A / B groups' record. Read-only, like every 실거래 tab (dash/more/livebots.py's paths, readers and states).

    GET /api/v4/livebots/judge    규칙 점검: every 빠른 손절 (REV) exit replayed as if held under the -50 % net stop and the
                                  ladder; every B-group signal the chase block stopped and its virtual result; the paper
                                  account against its coin-flip twin, both since the start
    GET /api/v4/livebots/goal     목표: this KST month's return of each account, the pace the owners' monthly goal needs,
                                  the win rate so far against break-even (Wilson 90 %), entries per weekday, average win /
                                  loss and the arithmetic of the record so far (never a forecast); with two paper bots
                                  (owners 10/19 final: MEXC on the -35 % twin, Bybit on -50 %) 손절 비교, the two stops
                                  side by side for the 11/3 review (``head_to_head``: numbers only, no verdict)
    GET /api/v4/livebots/risk     위험 (information only, nothing halts): what the stop costs each open position now, its
                                  liquidation price, the loss streak, the drawdown, the next-losses table, the kill file
    GET /api/v4/livebots/health   봇 상태: the rule bot's 1m bars per coin, its last signal, the paper bot's heartbeat and
                                  last minute, each executor's last loop, the watcher, the pause now and the next resume,
                                  the kill file, one traffic-light line
    GET /api/v4/livebots/groups   A / B / 예전 매매법: per group trades, wins, win rate, net ROE sum, for each account

Since when ("규칙봇 15 시작부터", ``config_start``): the paper database keeps one row per signal in ``signal_log`` with the
setting's label (``name@tf`` for the rule bot's default numbers, ``name@tf#order~tag`` for a research setting: the A+C
config's 95 settings all had one). The labels of the config the bot runs are its own (``state.combo.members``, written by
paperbot/combo.py every minute; else rebuilt from the config for default-number settings). The switch is between the last
row of a label not in this config and the first row of one in it; ``combo_run`` (written at every start of the paper
bot) is the exact moment when it falls in that gap, else the first signal of this config is the start (no trade of it
can be older). Nothing to tell them apart (no signal log) = ``sure`` False: then a trade counts by its setting
(the ENTERED outcome's member label) instead of its time, and the page says so.

The replays (``hold_replay``) are dash/more/livetape.py ``rebuild`` (paperbot/ladder.py net_roe / roe_price / tighten and
paperbot/ladder2.py ComboLadder, in PaperEngine's order) on the rule bot's 1m bars (paper3.db ``live_bars``): a REV exit
is replayed from its own entry with its own stop, liquidation price and size, never closed by a reverse signal; the
result is booked as paperbot/engine.py _close / _finish books it (gross - entry fee - exit fee at the taker rate; LIQ =
the margin). A chase-blocked signal prefers the watcher's own virtual trade (livecheck.db ``missed``, kind chase:
paperbot/livemissed.py on the paper bot's own engine); without one it is replayed the same way from the signal's
reference price (fill = reference x (1 + side x slippage), the config's ROE stop through ladder.roe_price). Funding is
not in a replay (its rates are not stored). Results: won (the first lock was reached: +10 % or more), lost (the stop:
-50 %), open (neither yet), or why it could not be told.

Honest states (CONTRACT 1.6): a file or table not there = ``missing`` (수집 전), unreadable = ``error`` (못 읽음 + why),
never a zero; small samples say so. Times are UTC ms, ratios are ratios (0.1 = 10 %), money is each account's USDT.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from . import livebots as L

ACCOUNT, FLIP = L.ACCOUNT, L.FLIP_ACCOUNT
MIN = 60_000
HOUR = L.HOUR
DAY = L.DAY
KST_MS = L.KST_MS

# the owners' monthly goal (10/19): +500 % a month (x6). Their target for the bot, never a forecast of it.
MONTHLY_TARGET = 5.0
# the owners' earlier analysis (docs/live15-start-ko.md "근거와 한계"): break-even win rate with +10 % wins and -50 % losses
# (fees in) at 30 % margin, compounded; 82-83 % as a plain sum. Reference numbers, said as such on the page.
BREAK_EVEN = 0.86
BREAK_EVEN_PLAIN = (0.82, 0.83)
COIN_FLIP_WIN = 0.75                   # the same analysis: a coin flip's win rate under the new rule (참고)
WEEKDAY_ENTRIES = 6.2                  # the in-sample 2-week replay: entries per weekday (the weeks the 15 were picked on)
WEEKDAY_MIN = 1.0                      # entries per weekday only once a whole weekday has gone by (less is mostly the hour)
ENTRY_JUDGE_N = L.ENTRY_JUDGE_N        # the owners decide the entry method after 10-20 measured trades (비용 tab)
Z90 = 1.6448536269514722               # the two-sided 90 % normal quantile (Wilson interval)
SMALL_N = L.SMALL[0]                   # under 20 closed trades: 표본 적음 (mostly luck)
FLIP_SMALL_N = L.SMALL[1]              # the coin-flip gap is mostly chance under 40 trades
NEXT_LOSSES = 4                        # 1..4 stops in a row in the next-losses table
DEFAULT_KILL = "/var/lib/paperbot/STOP"
STOP_CMD = "sudo touch /var/lib/paperbot/STOP"
# 봇 상태 thresholds (said on the page): a 1m bar closes every minute and the rule bot writes it within seconds; the paper
# bot writes its heartbeat every poll (2 s) and steps each minute after its bar; an executor saves every loop (~3 s;
# a 418 wait is 2 minutes); rule-bot signals come many times an hour (a quiet market can be quiet); the watcher runs
# every minute (livebots.WATCH_STALE_MS)
BARS_LATE_MS = 3 * MIN
PAPER_HB_LATE_MS = 2 * MIN
PAPER_STEP_LATE_MS = 3 * MIN
EXEC_LATE_MS = L.EXEC_STALE_MS
SIG_QUIET_MS = 2 * HOUR
WATCH_LATE_MS = L.WATCH_STALE_MS
BARS_LOOK_MS = 2 * DAY                 # the newest bar of a coin is looked for this far back (an index range, never a scan)
# replays: the bars are read 6 hours at a time, doubling, up to 14 days from the entry (livesim.MAX_MINUTES)
HOLD_FIRST_MS = 6 * HOUR
HOLD_MAX_MS = 14 * DAY
HOLD_OPEN_TTL_S = 60.0                 # an undecided replay is worked out again after this
HOLD_LOCKED_TTL_S = 300.0              # one past its first lock (won, still running): its final number moves
HOLD_KEEP = 512
# 규칙 고정 (owners 10/19, docs/live15-plan-ko.md): the 규칙봇 15 rules stay unchanged for two weeks from the 10/20 live
# start; this is the last day of that freeze (Korea time). Change it only when the owners decide another date.
RULES_FROZEN_UNTIL = "2026-11-03"
# 돈 늘리기 기준 (owners 10/19, docs/live15-plan-ko.md): information only, nothing changes by itself
SCALE_TRADES = 40                      # (a) closed live trades since the 규칙봇 15 start
SCALE_WIN = 0.88                       # (b) the win rate of the paper trades those live trades followed
SCALE_GAP = 0.01                       # (c) the live entry gap against the paper, at most 1 net-ROE point a trade on average
SCALE_KO = "돈 한 단계 늘릴 때: 같은 증거금 30% 그대로, 넣는 돈을 지금만큼 더 (예: {a} → {b}), 그 뒤 거래 40번 다시 확인"
GOAL_MATH_KO = "계산일 뿐 예측이 아니에요: 지금까지의 평균 이익·손실과 진입 횟수가 그대로 간다고 할 때 필요한 승률이에요"
# 손절 비교 (owners 10/19 final, "Mexc -35%로 가자"; docs/live15-plan-ko.md): MEXC on the -35 % twin against Bybit on
# -50 % is the two-week test that tells the owners which stop gets more money at the 11/3 review. Shown plainly, no verdict.
H2H_REVIEW_KO = "11/3 검토에서 어느 손절에 돈을 더 넣을지 정하려는 2주 비교예요"
H2H_NOTE_KO = ("숫자를 나란히 보여 주기만 해요 (어느 쪽이 낫다고 정하지 않아요) · 두 봇은 같은 신호로 들어가고 손절 자리만 달라요 · "
               "페이퍼는 두 번째 봇 시작부터, 실거래는 MEXC가 옮긴 때부터 두 계좌 모두 같은 기간으로 셌어요")
FUNDING_KO = "펀딩비는 넣지 않았어요 (비율이 기록에 없어요 · 보통 8시간에 순ROE 0.3%p 안팎)"
REV_KO = "빠른 손절: 첫 잠금(+10%) 전에 같은 매매법이 반대 신호를 내면 기다리지 않고 바로 닫는 규칙이에요"
CHASE_KO = "추격 막기: B 그룹 4개만, 롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면 (숏은 아래쪽) 진입하지 않는 규칙이에요"
GROUP_KO = {"A": "A 그룹", "B": "B 그룹", "old": "예전 매매법", "none": "짝 페이퍼 없음"}
GROUP_SUB_KO = {"A": "추격 막기 없음", "B": "추격 진입 막기", "old": "지금 설정에 없는 매매법 (시작 전 기록)",
                "none": "페이퍼에 같은 거래가 없는 실거래"}

_lock = threading.Lock()
_holds: "OrderedDict[str, tuple]" = OrderedDict()


def _f(x: Any) -> Optional[float]:
    return L._f(x)


def _i(x: Any) -> Optional[int]:
    return L._i(x)


def _rows_of(path: str, sql: str, args: tuple = ()) -> tuple:
    """(rows, state dict or None): one read-only query, the file's honest state when it cannot be read."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return None, L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return None, L._err(path, exc)
    try:
        return conn.execute(sql, args).fetchall(), None
    except sqlite3.Error as exc:
        if "no such table" in str(exc).lower():
            return None, L._missing(path, L.NO_TABLE_KO)
        return None, L._err(path, exc)
    finally:
        conn.close()


# ================================================================ the config the bot runs, and since when
def _label_of(sp: dict) -> Optional[str]:
    """A setting's label as paperbot/combo.py resolve_members makes it, when it can be told without the strategy code: a
    pick's id, or ``name@tf`` for the rule bot's default numbers (custom numbers and research settings carry a hash /
    a tag of their own: None, matched by name and timeframe instead)."""
    if sp.get("pick"):
        return str(sp["pick"])
    if any(k in sp for k in ("numbers", "stop", "entry", "invert", "filter", "disp", "off", "cell")):
        return None
    return f"{sp.get('strategy')}@{sp.get('tf')}" if sp.get("strategy") and sp.get("tf") else None


def _state_labels(paper_path: str) -> Optional[list]:
    """The running bot's own labels in config order (state ``combo``.members), None when not there."""
    rows, _st = _rows_of(paper_path, "SELECT data FROM state WHERE k = 'combo'")
    if not rows:
        return None
    labels = L._j(rows[0][0]).get("members")
    return [str(x) for x in labels] if isinstance(labels, list) and all(isinstance(x, str) for x in labels) else None


def run_members(paper_path: str, combo: dict) -> list:
    """The settings of the config the bot runs, in config order: {order, label, strategy, tf, no_chase, group}. Group B =
    the chase-blocked settings (``no_chase``: the owners' B 4개), A = the rest."""
    cfg = combo.get("config") or {} if combo.get("state") == "ok" else {}
    specs = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    labels = _state_labels(paper_path) if combo.get("source") == "db" else None
    if labels is not None and len(labels) != len(specs):
        labels = None
    out = []
    for i, sp in enumerate(specs, 1):
        nc = bool(sp.get("no_chase"))
        out.append({"order": i, "label": labels[i - 1] if labels else _label_of(sp), "strategy": sp.get("strategy") or sp.get("pick"),
                    "tf": sp.get("tf"), "no_chase": nc, "group": "B" if nc else "A"})
    return out


def config_start(paper_path: str, combo: dict, members: list, now: int) -> dict:
    """Since when the bot runs this config (module docstring): {ms, how, how_ko, sure, run_ms, name}."""
    name = ((combo.get("config") or {}).get("name") if combo.get("state") == "ok" else None) or None
    run_ms = combo.get("since_ms") if combo.get("state") == "ok" and combo.get("source") == "db" else None
    out = {"ms": None, "how": "unknown", "sure": False, "run_ms": run_ms, "name": name,
           "how_ko": "언제 시작했는지 기록에서 찾지 못했어요: 지금 설정 매매법의 거래만 셌어요"}
    labels = sorted({m["label"] for m in members if m.get("label")})
    if not labels or any(not m.get("label") for m in members):
        # a setting whose label is not known would read as the old config's: no switch can be told from the signals
        if members:
            out["how_ko"] = "지금 설정의 매매법 이름을 기록에서 못 찾았어요: 매매법·봉이 같은 거래만 셌어요"
        return out
    q = ",".join("?" * len(labels))
    try:
        conn = L.open_ro(paper_path)
    except (OSError, sqlite3.Error):
        conn = None
    old = new = created = None
    readable = False
    if conn is not None:
        try:
            conn.execute("BEGIN")
            tables = L._tables(conn)
            if "signal_log" in tables:
                old = conn.execute(f"SELECT MAX(bar_close) FROM signal_log WHERE strategy NOT IN ({q})", labels).fetchone()[0]
                new = conn.execute(f"SELECT MIN(bar_close) FROM signal_log WHERE strategy IN ({q}) AND bar_close > ?",
                                   (*labels, int(old) if old is not None else -1)).fetchone()[0]
                readable = True
            if "accounts" in tables:
                got = conn.execute("SELECT created_ts FROM accounts WHERE account_id = ?", (ACCOUNT,)).fetchone()
                created = _i(got[0]) if got else None
        except sqlite3.Error:
            readable = False
        finally:
            conn.close()
    old, new = _i(old), _i(new)
    if not readable:
        if run_ms is not None:
            out.update(ms=run_ms, how="run_only", sure=False,
                       how_ko="신호 기록을 못 읽어 봇이 마지막으로 켜진 때만 알아요 (다시 켜면 늦춰져서 지금 설정 매매법의 거래만 셌어요)")
        return out
    if old is None:
        ms = min(x for x in (created, new, run_ms, now) if x is not None)
        out.update(ms=ms, how="whole", sure=True, how_ko="이 기록 파일은 처음부터 지금 설정이에요")
    elif new is not None:
        if run_ms is not None and old < run_ms <= new:
            out.update(ms=run_ms, how="run", sure=True, how_ko="봇이 이 설정으로 켜진 때 (예전 설정의 마지막 신호 뒤)")
        else:
            out.update(ms=new, how="first_signal", sure=True, how_ko="지금 설정의 첫 신호 (봇은 그보다 조금 먼저 켜졌어요)")
    elif run_ms is not None and run_ms > old:
        out.update(ms=run_ms, how="run", sure=True, how_ko="봇이 이 설정으로 켜진 때 (아직 이 설정의 신호 없음)")
    else:
        out.update(ms=None, how="unknown", sure=False,
                   how_ko="기록의 마지막 신호가 예전 설정 것이에요: 지금 설정 매매법의 거래만 셌어요")
    return out


def trade_label(t: dict, meta: dict) -> Optional[str]:
    """The setting of a paper trade: its ENTERED outcome's member label (livebots.entered_meta)."""
    m = meta.get((t.get("symbol"), _i(t.get("entry_time")))) or {}
    return m.get("member")


def group_of(t: dict, meta: dict, members: list, start: dict) -> str:
    """"A" / "B" for a trade of a setting in the config the bot runs, else "old". Its own label first; without one
    (no outcome found) a setting of the same strategy and timeframe, only for a trade from the start on."""
    lab = trade_label(t, meta)
    by_label = {m["label"]: m for m in members if m.get("label")}
    if lab is not None and lab in by_label:
        return by_label[lab]["group"]
    if start.get("ms") is not None and (_i(t.get("entry_time")) or 0) < start["ms"]:
        return "old"
    # no label of its own, or one this page could not rebuild (custom numbers, a research setting): the same strategy
    # and timeframe among the settings whose label is not known
    same = [m for m in members if m.get("strategy") == t.get("strategy_id") and m.get("tf") == t.get("timeframe")
            and (lab is None or not m.get("label"))]
    return same[0]["group"] if same else "old"


def since_start(trades: list, start: dict, meta: dict, members: list) -> list:
    """The trades of this config: entered from its start on (``sure``), else those of its settings (group A / B)."""
    if start.get("sure") and start.get("ms") is not None:
        return [t for t in trades if (_i(t.get("entry_time")) or 0) >= start["ms"]]
    return [t for t in trades if group_of(t, meta, members, {"ms": None}) in ("A", "B")]


def context(p: dict, now: int, more: Optional[dict] = None, flip: bool = False) -> dict:
    """Every source of these tabs read once: the executors' configs and records, the paper accounts, the config the bot
    runs, its settings and start, the ENTERED outcomes' settings (and the coin-flip twin's with ``flip``)."""
    more = more or L.paths_more()
    configs, follows, paper, execs = L.sources(p, now)
    combo = L.read_combo(p["paper"], more["combo_config"])
    members = run_members(p["paper"], combo)
    start = config_start(p["paper"], combo, members, now)
    ok = paper.get("state") == "ok"
    meta = L.entered_meta(p["paper"], ACCOUNT) if ok else {}
    acc = (paper.get("accounts") or {}).get(ACCOUNT) if ok else None
    fl = (paper.get("accounts") or {}).get(FLIP) if ok else None
    bots = L.paper_bots(p, paper, execs)
    return {"p": p, "more": more, "now": now, "configs": configs, "paper": paper, "execs": execs, "combo": combo, "members": members,
            "start": start, "meta": meta, "acc": acc if acc and acc.get("known") else None,
            "flip": fl if fl and fl.get("known") else None, "flip_meta": L.entered_meta(p["paper"], FLIP) if flip and ok else {},
            "cfg": combo.get("config") or {} if combo.get("state") == "ok" else {}, "bots": bots, "_bot": {}}


def bot_side(cx: dict, path: Optional[str]) -> dict:
    """One paper bot's own facts (owners 10-19: two paper bots; livebots.paper_bots): {"bot", "acc", "meta", "start",
    "members", "cfg", "combo"}; the main one's are the context's own. Read once per request."""
    path = path or cx["p"]["paper"]
    k = L.LP.norm(path)
    if k in cx["_bot"]:
        return cx["_bot"][k]
    bot = next((b for b in cx["bots"] if L.LP.same(b["path"], path)), None)
    if L.LP.same(path, cx["p"]["paper"]):
        out = {"bot": bot, "acc": cx["acc"], "meta": cx["meta"], "start": cx["start"], "members": cx["members"], "cfg": cx["cfg"],
               "combo": cx["combo"], "paper": cx["paper"]}
    else:
        pr = (bot or {}).get("read") or (cx["execs"][0]["_papers"].get(k) if cx["execs"] else None) or L._missing(path)
        combo = L.read_combo(path, cx["more"].get("combo2_config") or "-")
        members = run_members(path, combo)
        ok = pr.get("state") == "ok"
        acc = (pr.get("accounts") or {}).get(ACCOUNT) if ok else None
        out = {"bot": bot, "acc": acc if acc and acc.get("known") else None, "meta": L.entered_meta(path, ACCOUNT) if ok else {},
               "start": config_start(path, combo, members, cx["now"]), "members": members,
               "cfg": combo.get("config") or {} if combo.get("state") == "ok" else {}, "combo": combo, "paper": pr}
    cx["_bot"][k] = out
    return out


def _src(x: dict, *keys) -> dict:
    keys = keys or ("state", "reason_ko", "reason", "path")
    return {k: x.get(k) for k in keys}


def paper_state(cx: dict) -> dict:
    """The paper account's honest state for a card: ok, or why not (수집 전 / 못 읽음)."""
    paper = cx["paper"]
    if paper.get("state") != "ok":
        return _src(paper)
    if cx["acc"] is None:
        return {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요", "path": paper.get("path")}
    return {"state": "ok", "path": paper.get("path"), "as_of_ms": paper.get("as_of_ms"), "stale": paper.get("stale")}


def start_out(cx: dict) -> dict:
    """The start as the page shows it, and the config in a few numbers (its name, settings, groups)."""
    ms = cx["members"]
    return {**cx["start"], "n_members": len(ms), "n_a": sum(1 for m in ms if m["group"] == "A"),
            "n_b": sum(1 for m in ms if m["group"] == "B"), "combo": _src(cx["combo"], "state", "reason_ko", "path", "source")}


# ================================================================ small statistics
def wilson(wins: int, n: int, z: float = Z90) -> Optional[list]:
    """The Wilson score interval [low, high] of a win rate (two-sided, z = 1.645: 90 %), None without trades."""
    if not n:
        return None
    ph = wins / n
    den = 1 + z * z / n
    mid = (ph + z * z / (2 * n)) / den
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return [max(0.0, mid - half), min(1.0, mid + half)]


def record(trades: list, roe_key: str = "roe") -> dict:
    """n, wins (pnl > 0, the executors' rule), losses, win rate, net ROE sum, money, average win / loss net ROE."""
    xs = [t for t in trades if _f(t.get("pnl")) is not None]
    w = [t for t in xs if t["pnl"] > 0]
    lo = [t for t in xs if t["pnl"] <= 0]
    roes = lambda ts: [r for r in (_f(t.get(roe_key)) for t in ts) if r is not None]          # noqa: E731
    rw, rl, ra = roes(w), roes(lo), roes(xs)
    return {"n": len(xs), "wins": len(w), "losses": len(lo), "win_rate": len(w) / len(xs) if xs else None,
            "roe_sum": sum(ra) if ra else 0.0, "pnl": sum(t["pnl"] for t in xs) if xs else 0.0,
            "avg_win": sum(rw) / len(rw) if rw else None, "avg_loss": sum(rl) / len(rl) if rl else None,
            "small": len(xs) < SMALL_N}


def loss_streak(trades: list, t_exit: str = "exit_time") -> int:
    """Losses in a row at the end of the closed trades (pnl < 0; a win or an even trade ends it)."""
    n = 0
    for t in sorted(trades, key=lambda t: (_i(t.get(t_exit)) or 0, str(t.get("id") or t.get("key") or "")), reverse=True):
        p = _f(t.get("pnl"))
        if p is None:
            continue
        if p < 0:
            n += 1
        else:
            break
    return n


def next_losses(margin: Optional[float], stop_loss: Optional[float], balance: Optional[float], k: int = NEXT_LOSSES) -> list:
    """The next-losses table: after 1..k stops in a row, the share of the account left, compounded ((1 - margin x stop
    loss)^n: at 30 % margin and a -50 % net stop, 85 %, 72.3 %, 61.4 %, 52.2 %), and the money left of ``balance``."""
    if not margin or not stop_loss or margin <= 0 or stop_loss <= 0:
        return []
    one = 1.0 - margin * stop_loss
    return [{"n": n, "left": one ** n, "lost": 1 - one ** n, "money_left": balance * one ** n if balance is not None else None}
            for n in range(1, k + 1)]


def margin_share(cfg: dict, symbol: Optional[str] = None) -> Optional[float]:
    """The config's margin share of equity (``margin``: a number, or "leverage" = leverage %)."""
    m = cfg.get("margin", "leverage")
    if isinstance(m, (int, float)) and not isinstance(m, bool):
        return float(m)
    lev = cfg.get("leverage") if isinstance(cfg.get("leverage"), dict) else {}
    v = _f(lev.get(symbol) if symbol else None) or _f(lev.get("default"))
    return v / 100.0 if v else None


def stop_roe(cfg: dict) -> Optional[float]:
    """The config's fixed ROE stop (0.5 = -50 %) and whether it is net of costs, else None (an ATR stop)."""
    st = cfg.get("stop") if isinstance(cfg.get("stop"), dict) else {}
    return _f(st.get("roe")) if st.get("mode") == "roe" else None


def first_lock(cfg: dict) -> float:
    lad = cfg.get("ladder") if isinstance(cfg.get("ladder"), dict) else {}
    return _f(lad.get("first_lock")) or 0.10


def lev_of(cfg: dict, symbol: str) -> Optional[int]:
    lev = cfg.get("leverage") if isinstance(cfg.get("leverage"), dict) else {}
    return _i(lev.get(symbol, lev.get("default")))


# ================================================================ the replays (규칙 점검)
def booked_roe(t: dict, price: float, reason: str, taker: float) -> float:
    """The net ROE paperbot/engine.py books for a close at ``price`` (_close / _finish: gross - entry fee - exit fee at
    the taker rate; LIQ: the margin is lost), funding left out. The entry fee is the record's own (its fees minus the
    exit fee of its real close) when the record has them. Without a size (a virtual entry) the same per unit of margin."""
    side, e, lev = int(t["side"]), float(t["entry_price"]), float(t["leverage"])
    qty, margin = _f(t.get("qty")), _f(t.get("margin"))
    if qty and margin:
        fee_in = qty * e * taker
        if _f(t.get("fees")) is not None and _f(t.get("exit_price")) is not None:
            fee_in = max(0.0, t["fees"] - qty * t["exit_price"] * taker)
        if reason == "LIQ":
            return (-margin - fee_in) / margin
        return (side * qty * (price - e) - fee_in - qty * price * taker) / margin
    if reason == "LIQ":
        return -1.0 - lev * taker
    return lev * (side * (price / e - 1.0) - taker * (1.0 + price / e))


def _hold_key(rule_db: str, t: dict) -> str:
    return json.dumps([rule_db, t.get("symbol"), t.get("side"), t.get("entry_time"), t.get("entry_price"), t.get("stop_initial"),
                       t.get("liq_price"), t.get("leverage")], default=str)


def hold_replay(t: dict, rules: dict, ref_fill: bool, rule_db: str, now: int) -> dict:
    """The trade ``t`` held from its own entry under its stop and the ladder until the stop, the lock or the bars' end
    (livetape.rebuild; no reverse-signal exit). -> {state: won | lost | open | no_data | missing | error, roe (booked at
    the exit; won but still running: the lock, a floor), lock, best, exit {t, price, reason}, last {t, roe}, missing,
    why_ko}. A decided answer is kept (the bars before the exit do not change); an undecided one for a minute."""
    key = _hold_key(rule_db, t)
    with _lock:
        hit = _holds.get(key)
        if hit is not None and (hit[0] is None or time.time() < hit[0]):
            _holds.move_to_end(key)
            return hit[1]
    out = _hold(t, rules, ref_fill, rule_db, now)
    ttl = None if out.get("exit") else HOLD_LOCKED_TTL_S if out["state"] == "won" else HOLD_OPEN_TTL_S
    with _lock:
        _holds[key] = (None if ttl is None else time.time() + ttl, out)
        _holds.move_to_end(key)
        while len(_holds) > HOLD_KEEP:
            _holds.popitem(last=False)
    return out


def _hold(t: dict, rules: dict, ref_fill: bool, rule_db: str, now: int) -> dict:
    from . import livetape as T
    from ...ladder import net_roe
    e0 = int(t["entry_time"]) - int(t["entry_time"]) % MIN
    end = min(int(now) - int(now) % MIN, e0 + HOLD_MAX_MS)
    tt = {**t, "exit_reason": "HOLD", "exit_time": end}
    span, rb = HOLD_FIRST_MS, None
    while True:
        hi = min(end, e0 + span)
        src = T.read_bars(rule_db, t["symbol"], e0, hi + MIN)
        if src.get("state") != "ok":
            return {"state": src.get("state") or "error", "why_ko": src.get("reason_ko"), "reason": src.get("reason")}
        rows = src.get("rows") or []
        if not rows or rows[0]["ts"] != e0:
            return {"state": "no_data", "why_ko": "진입한 분의 1분봉이 규칙봇 기록에 없어요"}
        rb = T.rebuild(tt, rows, rules, ref_fill, [], until=hi)
        if rb.get("exit") or hi >= end:
            break
        span *= 2
    x, lock = rb.get("exit"), rb.get("lock")
    side, entry, lev, rt = int(t["side"]), float(t["entry_price"]), float(t["leverage"]), rules["round_trip"]
    out = {"lock": lock, "best": rb["minutes"][-1][3] if rb.get("minutes") else None, "missing": rb.get("missing"), "exit": None,
           "last": None, "locks": len(rb.get("locks") or []), "why_ko": None}
    if rb.get("minutes"):
        m = rb["minutes"][-1]
        out["last"] = {"t": m[0], "roe": m[6]}
    if x:
        roe = booked_roe(t, x["price"], x["reason"], rules["taker_fee"])
        out.update(state="won" if rb.get("locks") else "lost", roe=roe,
                   exit={"t": x["t"], "price": x["price"], "reason": x["reason"], "reason_ko": L.EXIT_KO.get(x["reason"], x["reason"])})
    elif lock is not None:
        out.update(state="won", roe=lock, floor=True)
    else:
        out.update(state="open", roe=out["last"]["roe"] if out["last"] else net_roe(side, entry, entry, lev, rt))
        if e0 + HOLD_MAX_MS <= end:
            out["why_ko"] = "14일이 지나도 손절에도 첫 잠금에도 닿지 않았어요"
    return out


def _run_of(cx: dict) -> dict:
    c = cx["combo"]
    return {"taker_fee": c.get("taker_fee"), "config": c.get("config") or {}} if c.get("state") == "ok" else {}


def rev_part(cx: dict) -> dict:
    """빠른 손절 판정: every REV exit of the paper account since the start, held instead (module docstring), with what each
    executor's matched trade gained or lost by it at its own size."""
    from . import livetape as T
    st = paper_state(cx)
    base = {"ko": REV_KO, "funding_ko": FUNDING_KO, "rule_db": cx["more"]["rule_db"]}
    if st["state"] != "ok":
        return {**base, **st, "rows": [], "totals": None}
    if not (cx["cfg"].get("ladder")):
        return {**base, "state": "missing", "reason_ko": "봇 설정에 계단 익절 숫자가 없어 다시 계산하지 못해요", "rows": [], "totals": None}
    trades = since_start(cx["acc"].get("trades") or [], cx["start"], cx["meta"], cx["members"])
    revs = [t for t in trades if t.get("exit_reason") == "REV"]
    run = _run_of(cx)
    lives = []
    for x in cx["execs"]:
        r = x["record"]
        if r.get("state") == "ok":                       # only the live trades that followed THIS paper bot (livebots.pairs_of)
            by_pid = {pt["id"]: k for k, pt in L.pairs_of(x).items() if L.LP.same(pt["paper_path"], cx["p"]["paper"])}
            lives.append((x, by_pid, {str(lt["key"]): lt for lt in r.get("trades") or []}))
    rows = []
    for t in sorted(revs, key=lambda t: (t["exit_time"] or 0, t["id"] or 0), reverse=True):
        rules = T.rules_of(t, run)
        m = cx["meta"].get((t["symbol"], t["entry_time"])) or {}
        ref = True if not m else m.get("ref_price") is not None
        if None in (t.get("entry_price"), t.get("leverage"), t.get("stop_initial"), t.get("side")) or rules["spec"] is None:
            cf = {"state": "error", "why_ko": "거래 기록에 진입가·손절선이 없어 다시 계산하지 못했어요"}
        else:
            cf = hold_replay(t, rules, ref, cx["more"]["rule_db"], cx["now"])
        decided = cf["state"] in ("won", "lost")
        delta = (t["roe"] - cf["roe"]) if decided and t.get("roe") is not None else None
        live = {}
        for x, by_pid, by_key in lives:
            lt = by_key.get(by_pid.get(t["id"])) if by_pid.get(t["id"]) is not None else None
            if lt is not None:
                live[x["id"]] = {"roe": lt.get("roe"), "margin": lt.get("margin"), "pnl": lt.get("pnl"),
                                 "delta_pnl": delta * lt["margin"] if delta is not None and lt.get("margin") else None}
        rows.append({**{k: t.get(k) for k in ("id", "symbol", "side", "strategy_id", "timeframe", "entry_time", "exit_time", "leverage",
                                              "margin", "roe", "pnl", "entry_price", "exit_price", "stop_initial")},
                     "member": trade_label(t, cx["meta"]), "group": group_of(t, cx["meta"], cx["members"], cx["start"]),
                     "cf": cf, "delta_roe": delta, "delta_pnl": delta * t["margin"] if delta is not None and t.get("margin") else None,
                     "live": live})
    tot = {"n": len(rows), "won": sum(1 for r in rows if r["cf"]["state"] == "won"), "lost": sum(1 for r in rows if r["cf"]["state"] == "lost"),
           "open": sum(1 for r in rows if r["cf"]["state"] == "open"),
           "unknown": sum(1 for r in rows if r["cf"]["state"] not in ("won", "lost", "open")),
           "delta_roe": sum(r["delta_roe"] for r in rows if r["delta_roe"] is not None),
           "delta_pnl": sum(r["delta_pnl"] for r in rows if r["delta_pnl"] is not None),
           "live": {x["id"]: {"n": sum(1 for r in rows if (r["live"].get(x["id"]) or {}).get("delta_pnl") is not None),
                              "delta_pnl": sum(r["live"][x["id"]]["delta_pnl"] for r in rows if (r["live"].get(x["id"]) or {}).get("delta_pnl") is not None)}
                    for x, _b, _k in lives}}
    tot["decided"] = tot["won"] + tot["lost"]
    tot["verdict"] = None if not tot["decided"] else "saved" if tot["delta_roe"] > 1e-12 else "cost" if tot["delta_roe"] < -1e-12 else "even"
    return {**base, "state": "ok", "rows": rows, "totals": tot, "small": tot["decided"] < SMALL_N}


def _missed_chase(path: str, since: int) -> dict:
    """livecheck.db ``missed`` rows of kind chase (paperbot/livemissed.py row_out) by key, or the file's state."""
    from ... import livemissed as LM
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, L.CHECK_MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        if "missed" not in L._tables(conn):
            return L._missing(path, "점검 파일은 있지만 못 탄 신호 표가 아직 없어요 (1분 감시가 아직 기록 전)")
        rows = [r for r in LM.read_rows(conn, since) if r.get("why_kind") == "chase"]
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    return {"state": "ok", "path": path, "by_key": {r["key"]: r for r in rows}}


def _chase_rows(paper_path: str, since: int) -> tuple:
    """The paper bot's chase-blocked signals (signal_log FILTERED, why '추격 진입 막기…') from ``since``: (rows, state)."""
    rows, st = _rows_of(paper_path, "SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, data FROM signal_log "
                                    "WHERE status = 'FILTERED' AND bar_close >= ? ORDER BY bar_close, id", (int(since),))
    if st is not None:
        return [], st
    out = []
    for bc, tf, strat, sym, side, atr, ref, ref_t, data in rows:
        d = L._j(data)
        why = str(d.get("why") or "")
        if L.why_cat("FILTERED", why)[0] != "chase":
            continue
        out.append({"key": f"{strat}|{sym}|{int(bc)}", "t": int(bc), "tf": tf, "member": strat, "strategy": d.get("strategy") or str(strat).split("@")[0],
                    "symbol": sym, "side": _i(side), "ref_price": _f(ref), "ref_time": _i(ref_t), "why": why})
    return out, None


def _virtual(row: dict, cx: dict, initial: float) -> dict:
    """A chase-blocked signal entered anyway, replayed (no watcher row): the fill at its reference price plus slippage,
    the config's ROE stop through ladder.roe_price (the stop the engine puts from the reference price), the ladder."""
    from . import livetape as T
    from ...ladder import roe_price
    cfg = cx["cfg"]
    sr, lev = stop_roe(cfg), lev_of(cfg, row["symbol"])
    if row.get("ref_price") is None or not row.get("side"):
        return {"state": "unknown", "why_ko": "신호 기록에 참고 가격이 없어 다시 만들지 못했어요"}
    if sr is None or not lev:
        return {"state": "unknown", "why_ko": "이 설정의 손절(ATR)은 신호 기록만으로 다시 만들지 않아요"}
    rules = T.rules_of({"fees": None}, _run_of(cx))
    if rules["spec"] is None:
        return {"state": "unknown", "why_ko": "봇 설정에 계단 익절 숫자가 없어 다시 계산하지 못해요"}
    side, raw = int(row["side"]), float(row["ref_price"])
    net = (cfg.get("stop") or {}).get("net") is True
    stop = roe_price(side, raw, lev, -sr, rules["round_trip"] if net else 0.0)
    t = {"side": side, "entry_price": raw * (1 + side * rules["slippage"]), "entry_time": row["t"], "leverage": lev, "stop_initial": stop,
         "liq_price": None, "qty": None, "margin": None, "symbol": row["symbol"]}
    cf = hold_replay(t, rules, True, cx["more"]["rule_db"], cx["now"])
    ms = margin_share(cfg, row["symbol"])
    trades = (cx["acc"] or {}).get("trades") or []
    if ms and cf.get("roe") is not None and cf["state"] in ("won", "lost"):
        from ... import livemissed as LM
        cf = {**cf, "pnl": cf["roe"] * ms * LM.wallet_at(trades, row["t"], initial), "pnl_est": True}
    return cf


def chase_part(cx: dict) -> dict:
    """추격 막기 판정: every chase-blocked B signal since the start and what it would have done (module docstring)."""
    base = {"ko": CHASE_KO, "funding_ko": FUNDING_KO}
    paper = cx["paper"]
    if paper.get("state") != "ok":
        return {**base, **_src(paper), "rows": [], "totals": None}
    since = cx["start"]["ms"] if cx["start"].get("ms") is not None else 0
    sig, st = _chase_rows(cx["p"]["paper"], since)
    if st is not None:
        return {**base, **st, "rows": [], "totals": None}
    missed = _missed_chase(cx["more"]["check_db"], since)
    by_key = missed.get("by_key") or {}
    initial = _f(cx["cfg"].get("initial_equity")) or ((cx["acc"] or {}).get("initial")) or 1000.0
    rows = []
    for r in sig:
        m = by_key.get(r["key"])
        if m is not None and m.get("state") in ("closed", "open"):
            lock = m.get("lock")
            if m["state"] == "closed":
                cf = {"state": "won" if (m.get("pnl") or 0) > 0 else "lost", "roe": m.get("roe"), "pnl": m.get("pnl"),
                      "exit": {"t": m.get("exit_ts"), "price": m.get("exit_price"), "reason": m.get("reason"),
                               "reason_ko": L.EXIT_KO.get(m.get("reason"), m.get("reason_ko"))}}       # this site's words
            elif lock is not None:
                cf = {"state": "won", "roe": lock, "floor": True, "pnl": None, "lock": lock}
            else:
                cf = {"state": "open", "roe": m.get("roe"), "pnl": None}
            cf.update(source="missed", best=m.get("best_roe"))
        elif m is not None and m.get("state") in ("no_data", "refused", "rebuild_failed", "error"):
            cf = {"state": "unknown", "source": "missed", "why_ko": m.get("note") or m.get("error") or m.get("state_ko")}
        else:
            cf = {**_virtual(r, cx, initial), "source": "replay"}
        rows.append({**r, "group": "B", "cf": cf})
    rows.reverse()                                       # newest first
    dec = [r for r in rows if r["cf"]["state"] in ("won", "lost") and r["cf"].get("roe") is not None]
    tot = {"n": len(rows), "won": sum(1 for r in rows if r["cf"]["state"] == "won"), "lost": sum(1 for r in rows if r["cf"]["state"] == "lost"),
           "open": sum(1 for r in rows if r["cf"]["state"] == "open"),
           "unknown": sum(1 for r in rows if r["cf"]["state"] not in ("won", "lost", "open")),
           "roe_sum": sum(r["cf"]["roe"] for r in dec), "pnl": sum(r["cf"]["pnl"] for r in dec if r["cf"].get("pnl") is not None),
           "pnl_n": sum(1 for r in dec if r["cf"].get("pnl") is not None), "decided": len(dec),
           "replayed": sum(1 for r in rows if r["cf"].get("source") == "replay")}
    # the block saved what the blocked trades would have lost, and cost what they would have won
    tot["verdict"] = None if not dec else "saved" if tot["roe_sum"] < -1e-12 else "cost" if tot["roe_sum"] > 1e-12 else "even"
    return {**base, "state": "ok", "rows": rows, "totals": tot, "small": tot["decided"] < SMALL_N,
            "missed": _src(missed, "state", "reason_ko", "reason", "path"),
            "scale": {x["id"]: (x["config"] or {}).get("qty_scale") for x in cx["execs"]}}


def _equity_at(trades: list, ms: Optional[int], initial: Optional[float]) -> Optional[float]:
    """The account's equity just before ``ms``: the last trade closed before it, else the initial equity."""
    w = None
    for t in sorted(trades, key=lambda t: (t.get("exit_time") or 0, t.get("id") or 0)):
        if ms is not None and (t.get("exit_time") or 0) < ms and t.get("equity_after") is not None:
            w = t["equity_after"]
    return w if w is not None else initial


def twin_part(cx: dict) -> dict:
    """동전 쌍둥이: the paper account against its coin-flip twin (the same signals, the side by a coin) since the start."""
    st = paper_state(cx)
    if st["state"] != "ok":
        return {**st, "real": None, "flip": None}
    if cx["flip"] is None:
        return {"state": "missing", "reason_ko": "동전 쌍둥이(COMBOFLIP@mix) 기록이 아직 없어요", "real": None, "flip": None}
    start = cx["start"]

    def side(acc, meta):
        trades = acc.get("trades") or []
        mine = since_start(trades, start, meta, cx["members"])
        rec = record(mine)
        at = _equity_at(trades, start.get("ms"), acc.get("initial")) if start.get("sure") else None
        return {**rec, "wallet": acc.get("wallet"), "start_equity": at,
                "change": (acc["wallet"] / at - 1) if at and acc.get("wallet") is not None else None}

    real, flip = side(cx["acc"], cx["meta"]), side(cx["flip"], cx["flip_meta"])
    gap = (real["win_rate"] - flip["win_rate"]) if real["win_rate"] is not None and flip["win_rate"] is not None else None
    n = min(real["n"], flip["n"])
    return {"state": "ok", "real": real, "flip": flip, "gap": gap, "roe_gap": real["roe_sum"] - flip["roe_sum"],
            "small": n < FLIP_SMALL_N, "small_n": FLIP_SMALL_N, "ref_flip_win": COIN_FLIP_WIN}


def judge(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/judge: 빠른 손절 판정, 추격 막기 판정, 동전 쌍둥이 비교 (module docstring)."""
    cx = context(p, now, more, flip=True)
    return {"now_ms": now, "start": start_out(cx), "paper": paper_state(cx), "rev": rev_part(cx), "chase": chase_part(cx),
            "twin": twin_part(cx), "execs": [{"id": x["id"], "name_ko": x["name_ko"], "state": x["record"].get("state")} for x in cx["execs"]],
            "small_n": SMALL_N, "papers": L.papers_out(cx["bots"]), "compare": L.compare_papers(cx["bots"])}


# ================================================================ 목표
def month_of(now: int) -> dict:
    """This Korea-time month: {from_ms, to_ms, days, days_left, weekdays_left, label}."""
    kd = L.kst_day(now)
    d = _dt.date(1970, 1, 1) + _dt.timedelta(days=kd)
    first = _dt.date(d.year, d.month, 1)
    nxt = _dt.date(d.year + 1, 1, 1) if d.month == 12 else _dt.date(d.year, d.month + 1, 1)
    a = L.kst_day_start((first - _dt.date(1970, 1, 1)).days)
    b = L.kst_day_start((nxt - _dt.date(1970, 1, 1)).days)
    return {"from_ms": a, "to_ms": b, "days": (b - a) / DAY, "days_left": max(0.0, (b - now) / DAY), "days_gone": max(0.0, (now - a) / DAY),
            "weekdays_left": weekday_days(now, b), "weekdays_gone": weekday_days(a, now), "label": f"{d.year}년 {d.month}월"}


def weekday_days(a: Optional[int], b: int) -> float:
    """Korea-time weekday days (Monday to Friday) between ``a`` and ``b``, partial days in part."""
    if a is None or b <= a:
        return 0.0
    out, day = 0.0, L.kst_day(a)
    while L.kst_day_start(day) < b:
        lo, hi = max(a, L.kst_day_start(day)), min(b, L.kst_day_start(day + 1))
        if (day + 3) % 7 < 5 and hi > lo:
            out += (hi - lo) / DAY
        day += 1
    return out


def exec_equity(path: str) -> dict:
    """An executor's equity samples [(ts, equity minus net deposits since its first sample)] (executor.equity rows)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        if "equity" not in L._tables(conn):
            return L._missing(path, L.NO_TABLE_KO)
        tcol = "COALESCE(transfers, 0)" if "transfers" in L._cols(conn, "equity") else "0"
        rows = conn.execute(f"SELECT ts, equity, {tcol} FROM equity ORDER BY ts").fetchall()
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    xs = [(_i(t), _f(e), _f(tr) or 0.0) for t, e, tr in rows if _f(e) is not None]
    tr0 = xs[0][2] if xs else 0.0
    return {"state": "ok", "path": path, "rows": [(t, e - (tr - tr0)) for t, e, tr in xs]}


def _eq_from(rows: list, ms: int) -> tuple:
    """(equity at ``ms``: the last sample at or before it, else the first after it; its time; True when it is the
    account's first sample after ``ms`` (it started later))."""
    before = [r for r in rows if r[0] <= ms]
    if before:
        return before[-1][1], before[-1][0], False
    return (rows[0][1], rows[0][0], True) if rows else (None, None, False)


def _pace(mult: Optional[float], target: float, days_left: float, weekdays_left: float, win_step: Optional[float]) -> dict:
    """What the rest of the month needs for ``target`` x the month's start: x per calendar day, per weekday, and as wins of
    ``win_step`` (one +10 % win at 30 % margin = +3 % of the account) with no loss."""
    if mult is None or mult <= 0:
        return {"need": None}
    need = target / mult
    out = {"need": need, "reached": need <= 1.0}
    if need > 1.0:
        out["per_day"] = need ** (1 / days_left) - 1 if days_left > 0.01 else None
        out["per_weekday"] = need ** (1 / weekdays_left) - 1 if weekdays_left > 0.01 else None
        out["wins"] = math.ceil(math.log(need) / math.log(1 + win_step) - 1e-9) if win_step and win_step > 0 else None
    return out


def need_win(needed: Optional[float], n: Optional[float], m: Optional[float], w: Optional[float], l: Optional[float]) -> Optional[float]:
    """The win rate p with n x [p ln(1 + m w) + (1 - p) ln(1 - m l)] = ln(needed): n more trades, margin share m, an average
    win of w and loss of l (net ROE, l as a positive number), compounded on the account. None when it cannot be told."""
    if not needed or needed <= 0 or not n or n <= 0 or not m or w is None or l is None or m * l >= 1 or w <= 0 or l <= 0:
        return None
    a, b = math.log(1 + m * w), math.log(1 - m * l)
    return (math.log(needed) / n - b) / (a - b)


def per_weekday_of(entries: list, since: Optional[int], now: int) -> Optional[float]:
    """Entries per KST weekday so far, once a whole weekday has gone by (else None: the hour would decide it)."""
    since = since if since is not None else min((t for t in entries if t is not None), default=None)
    days = weekday_days(since, now)
    return sum(1 for t in entries if t is not None and not L.kst_weekend(t)) / days if days >= WEEKDAY_MIN else None


def win_need(rec: dict, needed: Optional[float], mo: dict, cfg: dict, per_wd: Optional[float]) -> dict:
    """목표에 필요한 승률 (owners 10/19, docs/live15-plan-ko.md): what win rate the rest of the month needs for the goal at
    this account's own numbers so far (average win and loss; fallbacks the first lock and the config's stop), next to the
    win rate so far and its 90 % Wilson range; and the whole month's from its start (x6). Arithmetic, never a forecast."""
    m = margin_share(cfg)
    w, w_src = (rec["avg_win"], "record") if rec.get("avg_win") is not None and rec["avg_win"] > 0 else (first_lock(cfg), "lock")
    l, l_src = (-rec["avg_loss"], "record") if rec.get("avg_loss") is not None and rec["avg_loss"] < 0 else (stop_roe(cfg), "stop")
    pw, pw_src = (per_wd, "record") if per_wd is not None else (WEEKDAY_ENTRIES, "ref")
    n_left = pw * mo["weekdays_left"]
    n_month = pw * (mo["weekdays_gone"] + mo["weekdays_left"])
    target = 1 + MONTHLY_TARGET
    p_month = need_win(target, n_month, m, w, l)
    wr, wil = rec.get("win_rate"), wilson(rec.get("wins") or 0, rec.get("n") or 0)
    now_ko = (f"지금 {wr:.0%} (범위 {wil[0]:.0%}~{wil[1]:.0%})" if wr is not None and wil else "지금 승률 기록 없음")
    out = {"m": m, "w": w, "w_src": w_src, "l": l, "l_src": l_src, "per_weekday": pw, "per_weekday_src": pw_src,
           "n_left": n_left, "n_month": n_month, "needed": needed, "now": wr, "wilson90": wil, "month_p": p_month,
           "note_ko": GOAL_MATH_KO,
           "src_ko": " · ".join([f"평균 이익 {'+' if w >= 0 else ''}{w * 100:.1f}%" + ("" if w_src == "record" else " (첫 잠금 기준)"),
                                 f"평균 손실 −{l * 100:.1f}%" + ("" if l_src == "record" else " (손절 기준)") if l is not None else "평균 손실 모름",
                                 f"평일 하루 {pw:.1f}번" + ("" if pw_src == "record" else f" (참고값 {WEEKDAY_ENTRIES}: 평일 하루가 다 지나기 전)"),
                                 f"증거금 {m:.0%}" if m else "증거금 모름"]),
           "month_ko": f"한 달 전체로 보면 약 {p_month:.0%} 필요" if p_month is not None and 0 <= p_month <= 1 else
           "한 달 전체로 보면 승률 100%로도 모자람" if p_month is not None and p_month > 1 else None}
    if needed is None:
        out.update(state="unknown", p=None, ko="목표에 필요한 승률을 셀 잔고 기록이 없어요")
    elif needed <= 1:
        out.update(state="reached", p=None, ko="이번 달 목표 이미 달성")
    elif n_left <= 0:
        out.update(state="no_days", p=None, ko="이번 달 남은 평일이 없어요")
    else:
        p = need_win(needed, n_left, m, w, l)
        if p is None:
            out.update(state="unknown", p=None, ko="숫자가 모자라 계산하지 못했어요")
        elif p > 1:
            out.update(state="impossible", p=p, ko=f"남은 기간 목표 속도: 승률 100%로도 모자람 · {now_ko}")
        else:
            out.update(state="ok", p=max(0.0, p), ko=f"남은 기간 목표 속도: 승률 {max(0.0, p):.0%} 필요 · {now_ko}")
    return out


def scale_check(cx: dict, x: dict) -> dict:
    """돈 늘리기 기준 (owners 10/19): (a) 40+ closed live trades since the 규칙봇 15 start, (b) the paper trades they followed
    won 88 %+, (c) the live entry gap averages at most 1 net-ROE point a trade (체결 비교, livebots.fill_gaps). Information
    only: nothing changes by itself; never margin or leverage, only the money put in."""
    r = x["record"]
    since = cx["start"].get("ms") if cx["start"].get("sure") else None
    live = [t for t in r.get("trades") or [] if since is None or (t.get("entry_ts") or 0) >= since]
    pairs = L.pairs_of(x)
    paired = [pairs[str(t["key"])] for t in live if str(t["key"]) in pairs]
    pw = sum(1 for t in paired if (t.get("pnl") or 0) > 0)
    pwr = pw / len(paired) if paired else None
    gaps = L.fill_gaps(r["path"], L.gap_rows(x, since), (x["config"] or {}).get("exchange") or x["id"]) if r.get("path") else {}
    er = gaps.get("entry_roe") if gaps.get("state") == "ok" else None
    cost = -er if er is not None else None                     # in the trade's favour positive -> a cost is negative
    checks = [
        {"id": "trades", "ok": len(live) >= SCALE_TRADES, "value": len(live), "need": SCALE_TRADES,
         "ko": f"거래 {len(live)}/{SCALE_TRADES}번", "what_ko": f"규칙봇 15 시작 뒤 닫힌 실거래 {SCALE_TRADES}번 이상"},
        {"id": "paper_win", "ok": pwr is not None and pwr >= SCALE_WIN - 1e-9, "value": pwr, "need": SCALE_WIN, "n": len(paired),
         "ko": (f"따라간 페이퍼 승률 {pwr:.0%} ({len(paired)}번 중 {pw}번)" if pwr is not None else "따라간 페이퍼 거래가 아직 없어요"),
         "what_ko": f"그 거래들이 따라간 페이퍼 승률 {SCALE_WIN:.0%} 이상"},
        {"id": "gap", "ok": cost is not None and cost <= SCALE_GAP + 1e-12, "value": cost, "need": SCALE_GAP,
         "n": gaps.get("entry_n") if gaps.get("state") == "ok" else 0,
         "ko": (f"진입 차이 평균 순ROE {cost * 100:+.1f}%p (잰 거래 {gaps.get('entry_n')}번)" if cost is not None else "진입 차이를 잰 거래가 아직 없어요"),
         "what_ko": "실거래 진입이 페이퍼보다 평균 순ROE 1%p 이하로 불리"}]
    ok = all(c["ok"] for c in checks)
    budget = _f((x["config"] or {}).get("budget_usd"))
    a, b = (f"${budget:,.0f}", f"${budget * 2:,.0f}") if budget else ("$100", "$200")
    return {"ok": ok, "checks": checks,
            "ko": SCALE_KO.format(a=a, b=b) if ok else "아직 아니에요: " + " · ".join(c["ko"] for c in checks if not c["ok"]),
            "note_ko": "보여 주기만 해요 · 저절로 바뀌는 것은 없어요 · 증거금(30%)이나 배수는 올리지 않아요"}


def frozen(now: int) -> dict:
    """규칙 고정 기간 (RULES_FROZEN_UNTIL, Korea time): {until, days_left, on, ko}."""
    end = _dt.date.fromisoformat(RULES_FROZEN_UNTIL)
    today = _dt.date(1970, 1, 1) + _dt.timedelta(days=L.kst_day(now))
    left = (end - today).days
    md = f"{end.month}/{end.day}"
    ko = (f"규칙 고정: {md}까지 ({left}일 남음)" if left > 0 else f"규칙 고정: 오늘({md})까지" if left == 0
          else f"규칙 고정 기간 끝남 ({md}까지였어요)")
    return {"until": RULES_FROZEN_UNTIL, "days_left": left, "on": left >= 0, "ko": ko,
            "why_ko": "10/20 시작부터 2주는 규칙(매매법·손절·계단 익절)을 바꾸지 않아요: 바꾸면 무엇이 통했는지 알 수 없어요"}


def _paper_goal(cx: dict, b: Optional[dict], mo: dict, target: float, win_step: Optional[float]) -> dict:
    """One paper bot's month (the main one's numbers as before) with its own 목표에 필요한 승률."""
    side = bot_side(cx, b["path"] if b else None)
    pid = b["id"] if b else "paper"
    st = paper_state(cx) if pid == "paper" else (
        _src(side["paper"]) if side["paper"].get("state") != "ok" else
        {"state": "ok"} if side["acc"] is not None else {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요"})
    base = {"id": pid, "kind": "paper"}
    if b is not None and len(cx["bots"]) > 1:
        base["label_ko"] = b["label_ko"]
    if st["state"] != "ok":
        return {**base, **st}
    a = side["acc"]
    trades = a.get("trades") or []
    eq0 = _equity_at(trades, mo["from_ms"], a.get("initial"))
    wallet = a.get("wallet")
    month_trades = [t for t in trades if (t.get("exit_time") or 0) >= mo["from_ms"]]
    mult = wallet / eq0 if wallet is not None and eq0 else None
    pace = _pace(mult, target, mo["days_left"], mo["weekdays_left"], win_step)
    mine = since_start(trades, side["start"], side["meta"], side["members"])
    entries = [t.get("entry_time") for t in mine] + ([a["position"]["entry_time"]] if a.get("position") else [])
    pwd = per_weekday_of(entries, side["start"].get("ms"), cx["now"])
    return {**base, "state": "ok", "start_equity": eq0, "start_ms": mo["from_ms"], "late_start": False,
            "now_equity": wallet, "change": (wallet - eq0) if wallet is not None and eq0 is not None else None,
            "ret": (mult - 1) if mult is not None else None, "closed_pnl": sum(t["pnl"] or 0 for t in month_trades),
            "closed_n": len(month_trades), "pace": pace,
            "so_far_per_day": (mult ** (1 / mo["days_gone"]) - 1) if mult and mo["days_gone"] >= 0.5 else None,
            "need": win_need(record(mine), pace.get("need"), mo, side["cfg"] or cx["cfg"], pwd)}


def goal(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/goal: this month against the owners' goal, and the record so far (module docstring). Per
    account also 목표에 필요한 승률 (``need``), per live account 돈 늘리기 기준 (``scale``), and 규칙 고정 (``frozen``)."""
    cx = context(p, now, more)
    cfg = cx["cfg"]
    mo = month_of(now)
    target = 1 + MONTHLY_TARGET
    ms = margin_share(cfg)
    win_step = ms * first_lock(cfg) if ms else None
    accts = [_paper_goal(cx, b, mo, target, win_step) for b in (cx["bots"] or [None])]
    for x in cx["execs"]:
        r = x["record"]
        if r.get("state") != "ok":
            accts.append({"id": x["id"], "kind": "live", **_src(r)})
            continue
        own_cfg = bot_side(cx, x.get("paper_path"))["cfg"] or cfg
        eqs = exec_equity(r["path"])
        trades = [t for t in r.get("trades") or [] if (t.get("exit_ts") or 0) >= mo["from_ms"]]
        scale = scale_check(cx, x)
        if eqs.get("state") != "ok" or not eqs.get("rows"):
            accts.append({"id": x["id"], "kind": "live", "state": "missing" if eqs.get("state") in ("ok", "missing") else eqs.get("state"),
                          "reason_ko": eqs.get("reason_ko") or "잔고 기록이 아직 없어요", "closed_pnl": sum(t["pnl"] or 0 for t in trades),
                          "closed_n": len(trades), "scale": scale})
            continue
        eq0, t0, late = _eq_from(eqs["rows"], mo["from_ms"])
        now_eq = eqs["rows"][-1][1]
        mult = now_eq / eq0 if eq0 else None
        days_gone = max(0.0, (now - (t0 or mo["from_ms"])) / DAY)
        pace = _pace(mult, target, mo["days_left"], mo["weekdays_left"], win_step)
        since = cx["start"].get("ms") if cx["start"].get("sure") else None
        mine = [t for t in r.get("trades") or [] if since is None or (t.get("entry_ts") or 0) >= since]
        entries = [t.get("entry_ts") for t in mine] + ([r["position"]["entry_time"]] if r.get("position") else [])
        pwd = per_weekday_of(entries, since if since is not None else r.get("since_ms"), now)
        accts.append({"id": x["id"], "kind": "live", "state": "ok", "start_equity": eq0, "start_ms": t0, "late_start": late,
                      "now_equity": now_eq, "now_ms": eqs["rows"][-1][0], "change": now_eq - eq0 if eq0 is not None else None,
                      "ret": (mult - 1) if mult is not None else None, "closed_pnl": sum(t["pnl"] or 0 for t in trades), "closed_n": len(trades),
                      "pace": pace, "so_far_per_day": (mult ** (1 / days_gone) - 1) if mult and days_gone >= 0.5 else None,
                      "need": win_need(record(mine), pace.get("need"), mo, own_cfg, pwd), "scale": scale,
                      **({"follows_ko": x.get("follows_ko")} if x.get("follows_ko") else {})})
    return {"now_ms": now, "start": start_out(cx), "target": MONTHLY_TARGET, "target_mult": target, "month": mo, "accts": accts,
            "record": goal_record(cx, mo), "margin": ms, "win_step": win_step, "loss_step": ms * stop_roe(cfg) if ms and stop_roe(cfg) else None,
            "break_even": BREAK_EVEN, "break_even_plain": list(BREAK_EVEN_PLAIN), "weekday_ref": WEEKDAY_ENTRIES, "small_n": SMALL_N,
            "frozen": frozen(now), "need_note_ko": GOAL_MATH_KO, "papers": L.papers_out(cx["bots"]), "h2h": head_to_head(cx)}


def _h2h_live(x: dict, since: Optional[int]) -> dict:
    """One live account in 손절 비교: its closed trades entered since ``since`` (the switch), wins, win rate, money, and
    its equity since then (deposits and withdrawals taken out, exec_equity)."""
    r = x["record"]
    base = {"id": x["id"], "name_ko": x["name_ko"]}
    if r.get("state") != "ok":
        return {**base, **_src(r)}
    rec = record([t for t in r.get("trades") or [] if (t.get("entry_ts") or 0) >= since])
    out = {**base, "state": "ok", "since_ms": since, **{k: rec[k] for k in ("n", "wins", "losses", "win_rate", "pnl")},
           "open": bool(r.get("position")), "change": None}
    eqs = exec_equity(r["path"])
    if eqs.get("state") == "ok" and eqs.get("rows"):
        eq0, _t0, late = _eq_from(eqs["rows"], since)
        now_eq = eqs["rows"][-1][1]
        out.update(change=(now_eq / eq0 - 1) if eq0 else None, start_equity=eq0, equity=now_eq, late_start=late)
    return out


def head_to_head(cx: dict) -> Optional[dict]:
    """손절 비교 (owners 10/19 final; docs/live15-plan-ko.md): each paper bot's stop with its paper record since the second
    bot started (livebots.compare_papers: trades, wins, win rate, net ROE sum, equity change, deepest drop) and the live
    accounts following it, both counted from MEXC's switch (the last start of an executor that named the second paper
    database). Numbers only: no verdict, no stop-widening check. None with one paper bot (the page as before)."""
    c = L.compare_papers(cx["bots"])
    if c is None:
        return None
    if c.get("state") != "ok":
        return {**c, "review_ko": H2H_REVIEW_KO}
    rows = {r["id"]: r for r in c["rows"]}
    switch = max((x["switched_ms"] for x in cx["execs"] if x.get("paper_id") == "paper2" and x.get("switched_ms")), default=None)
    sides = []
    for b in cx["bots"][:2]:
        r = rows.get(b["id"]) or {}
        live = [_h2h_live(x, switch) for x in cx["execs"] if switch is not None and x.get("paper_id") == b["id"]]
        sides.append({"id": b["id"], "stop_short": b.get("stop_short"), "stop_ko": b.get("stop_ko"), "name": b.get("name"),
                      "label_ko": b.get("label_ko"), "followers": b.get("followers"),
                      "paper": {k: r.get(k) for k in ("n", "wins", "losses", "win_rate", "roe_sum", "change", "max_dd", "open")},
                      "live": live})
    n_min = min(s["paper"]["n"] or 0 for s in sides)
    return {"state": "ok", "since_ms": c["since_ms"], "live_since_ms": switch, "sides": sides, "words_ko": c["words_ko"],
            "small": n_min < SMALL_N, "small_n": SMALL_N, "review_ko": H2H_REVIEW_KO, "note_ko": H2H_NOTE_KO,
            **({} if switch is not None else {"live_ko": "실거래 비교는 MEXC가 두 번째 페이퍼로 옮긴 뒤부터 나와요"})}


def goal_record(cx: dict, mo: dict) -> dict:
    """The paper record since the start: win rate (Wilson 90 %), entries per weekday, average win / loss, the break-even of
    those averages (plain sum), and the arithmetic of carrying the record on to the month's end (never a forecast)."""
    st = paper_state(cx)
    if st["state"] != "ok":
        return st
    a, start = cx["acc"], cx["start"]
    trades = since_start(a.get("trades") or [], start, cx["meta"], cx["members"])
    rec = record(trades)
    entries = list(trades)
    pos = a.get("position")
    if pos and pos.get("entry_time") is not None and (not start.get("ms") or pos["entry_time"] >= start["ms"]):
        entries.append({"entry_time": pos["entry_time"]})
    wd = [t for t in entries if t.get("entry_time") is not None and not L.kst_weekend(t["entry_time"])]
    since = start.get("ms") if start.get("ms") is not None else min((t["entry_time"] for t in entries if t.get("entry_time") is not None), default=None)
    wdays = weekday_days(since, cx["now"])
    per_wd = len(wd) / wdays if wdays >= WEEKDAY_MIN else None
    aw, al = rec["avg_win"], rec["avg_loss"]
    be_rec = (-al / (aw - al)) if aw is not None and al is not None and aw - al > 0 and al < 0 else None
    # the record's own growth per trade: ln(equity after / equity before), the money as booked (no assumption)
    logs = [math.log(t["equity_after"] / (t["equity_after"] - t["pnl"])) for t in trades
            if t.get("equity_after") is not None and t.get("pnl") is not None and t["equity_after"] - t["pnl"] > 0 and t["equity_after"] > 0]
    g = sum(logs) / len(logs) if logs else None
    imply = None
    if g is not None and per_wd is not None:
        n_left = per_wd * mo["weekdays_left"]
        imply = {"per_trade": math.exp(g) - 1, "trades_left": n_left, "rest_mult": math.exp(g * n_left),
                 "month_mult": math.exp(g * per_wd * 21.7), "small": rec["n"] < SMALL_N}
    return {"state": "ok", **rec, "wilson90": wilson(rec["wins"], rec["n"]), "break_even": BREAK_EVEN, "break_even_record": be_rec,
            "entries": len(entries), "weekday_entries": len(wd), "weekdays": wdays, "per_weekday": per_wd, "weekday_ref": WEEKDAY_ENTRIES,
            "since_ms": since, "implied": imply}


# ================================================================ 위험
def _paper_risk(cx: dict, b: Optional[dict] = None) -> dict:
    """A paper bot's risk card (``b``: the second paper bot, owners 10-19; None: the main one, as before)."""
    from ...ladder import net_roe
    if b is None or b["id"] == "paper":
        st, a, pid = paper_state(cx), cx["acc"], "paper"
    else:
        side = bot_side(cx, b["path"])
        pid, a = b["id"], side["acc"]
        st = _src(side["paper"]) if side["paper"].get("state") != "ok" else (
            {"state": "ok"} if a is not None else {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요"})
    if st["state"] != "ok":
        return {"id": pid, "kind": "paper", **st}
    trades = a.get("trades") or []
    wallet, initial = a.get("wallet"), a.get("initial")
    peak, peak_t = initial, None
    for t in sorted(trades, key=lambda t: (t.get("exit_time") or 0, t.get("id") or 0)):
        if t.get("equity_after") is not None and (peak is None or t["equity_after"] > peak):
            peak, peak_t = t["equity_after"], t.get("exit_time")
    if wallet is not None and peak is not None and wallet > peak:
        peak = wallet
    out = {"id": pid, "kind": "paper", "state": "ok", "balance": wallet, "streak": loss_streak(trades), "peak": peak, "peak_ms": peak_t,
           "drawdown": (1 - wallet / peak) if wallet is not None and peak else None, "position": None}
    if b is not None and len(cx["bots"]) > 1:
        out["label_ko"] = b["label_ko"]
    p = a.get("position")
    if p and p.get("entry") and p.get("stop") and p.get("leverage") and p.get("side"):
        rt, ff = p.get("round_trip") or 0.0, p.get("funding_frac") or 0.0
        roe = net_roe(p["side"], p["entry"], p["stop"], p["leverage"], rt, ff)
        money = roe * p["margin"] if p.get("margin") else None
        mark = p.get("last_mark")
        out["position"] = {**{k: p.get(k) for k in ("symbol", "side", "leverage", "entry", "stop", "liq", "margin", "locked", "lock_roe",
                                                     "last_mark", "last_mark_roe_net", "strategy_id", "timeframe", "entry_time")},
                           "stop_roe": roe, "stop_money": money, "stop_share": money / wallet if money is not None and wallet else None,
                           "stop_dist": abs(p["stop"] / mark - 1) if mark else None,
                           "liq_dist": abs(p["liq"] / mark - 1) if mark and p.get("liq") else None,
                           "stop_to_liq": abs(p["liq"] / p["stop"] - 1) if p.get("liq") else None, "how_ko": "순ROE (수수료·슬리피지 포함, 잠금 계산과 같은 식)"}
    return out


def _live_risk(x: dict) -> dict:
    from ... import livecheck as LC
    r = x["record"]
    base = {"id": x["id"], "kind": "live", "name_ko": x["name_ko"]}
    if r.get("state") != "ok":
        return {**base, **_src(r)}
    eqs = exec_equity(r["path"])
    rows = eqs.get("rows") or []
    peak = max((e for _t, e in rows), default=None)
    last = rows[-1][1] if rows else r.get("last_equity")
    bal = r.get("last_equity")
    exch = (x["config"] or {}).get("exchange") or x["id"]
    fee = LC.ASSUMED_FEE.get(exch, LC.ASSUMED_FEE["binance"])
    out = {**base, "state": "ok", "balance": bal, "streak": r.get("consecutive_losses") if r.get("consecutive_losses") is not None
           else loss_streak(r.get("trades") or [], "exit_ts"), "streak_from": "executor" if r.get("consecutive_losses") is not None else "trades",
           "peak": peak, "drawdown": (1 - last / peak) if peak and last is not None else None, "position": None, "fee": fee,
           "equity_state": eqs.get("state")}
    p = r.get("position")
    if p and p.get("entry") and p.get("stop") and p.get("qty") and p.get("side"):
        gross = p["side"] * p["qty"] * (p["stop"] - p["entry"])
        fees = fee * p["qty"] * (p["entry"] + p["stop"])
        money = gross - fees
        out["position"] = {**{k: p.get(k) for k in ("symbol", "side", "leverage", "entry", "stop", "margin", "locked", "entry_time", "status")},
                           "liq": None, "stop_money": money, "stop_roe": money / p["margin"] if p.get("margin") else None,
                           "stop_share": money / bal if bal else None, "how_ko": f"거래소 기본 수수료 {fee * 100:.3g}%로 어림 (양쪽)"}
    return out


def kill_state(cx: dict) -> dict:
    """The kill file every executor config names (one file stops both), whether it is there now, the command."""
    paths = sorted({(c.get("kill_file") or {}).get("path") for c in cx["configs"].values() if c.get("state") == "ok" and c.get("kill_file")} - {None})
    items = []
    for path in paths or [DEFAULT_KILL]:
        try:
            present = os.path.exists(path)
        except OSError:
            present = None
        items.append({"path": path, "present": present, "from_config": bool(paths)})
    return {"files": items, "any": any(i["present"] for i in items), "cmd": STOP_CMD,
            "what_ko": "두 실행기가 모두 멈춰요: 열린 포지션을 닫고 새 진입을 하지 않아요 (다시 켤지는 두 분이: 파일 지우기 → 실행기 끄기 → clear-halt)"}


def risk(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/risk: information only (module docstring); nothing here halts or sends anything."""
    cx = context(p, now, more)
    cfg = cx["cfg"]
    ms, sr = margin_share(cfg), stop_roe(cfg)
    bots = cx["bots"] or [None]
    accts = [_paper_risk(cx, b) for b in bots] + [_live_risk(x) for x in cx["execs"]]
    # each account's next-losses table on its OWN paper bot's stop (owners 10-19: MEXC follows the -35 % bot)
    cfg_of = {b["id"]: bot_side(cx, b["path"])["cfg"] for b in bots if b}
    cfg_of.update({x["id"]: bot_side(cx, x.get("paper_path"))["cfg"] for x in cx["execs"]})
    for a in accts:
        c = cfg_of.get(a["id"]) or cfg
        a_ms, a_sr = margin_share(c), stop_roe(c)
        a["next"] = next_losses(a_ms, a_sr, a.get("balance")) if a.get("state") == "ok" else []
        if len(cx["bots"]) > 1:
            a["stop_roe"], a["one_stop"] = a_sr, a_ms * a_sr if a_ms and a_sr else None
    return {"now_ms": now, "start": start_out(cx), "margin": ms, "stop_roe": sr, "stop_net": (cfg.get("stop") or {}).get("net") is True,
            "one_stop": ms * sr if ms and sr else None, "table": next_losses(ms, sr, None), "accts": accts, "kill": kill_state(cx),
            "halts_ko": "연패나 낙폭으로 저절로 멈추는 장치는 없어요 (10/19 결정) · 이 화면은 보여 주기만 해요"}


# ================================================================ 봇 상태
def _late(at: Optional[int], now: int, limit: int, lag: int = 0) -> dict:
    """{at, late_ms, limit_ms, state}: ``at`` (+ ``lag``: a minute's bar is done at its open + 1 minute) against ``limit``."""
    if at is None:
        return {"at": None, "late_ms": None, "limit_ms": limit, "state": "missing"}
    late = now - (at + lag)
    return {"at": at, "late_ms": late, "limit_ms": limit, "state": "late" if late > limit else "ok"}


def rule_part(rule_db: str, symbols: list, now: int) -> dict:
    """The rule bot's paper3.db: the newest 1m bar per coin (looked for in the last 2 days, an index range) and its last
    signal_log row."""
    try:
        conn = L.open_ro(rule_db)
    except FileNotFoundError:
        return L._missing(rule_db, "규칙봇 기록 파일이 아직 없어요 (PAPERBOT_LIVE_RULE_DB 경로를 확인해 주세요)")
    except (OSError, sqlite3.Error) as exc:
        return L._err(rule_db, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "live_bars" not in tables:
            return L._missing(rule_db, "규칙봇 파일은 있지만 1분봉 표(live_bars)가 아직 없어요")
        bars = {}
        for s in symbols:
            got = conn.execute("SELECT MAX(ts) FROM live_bars WHERE ts >= ? AND symbol = ?", (now - BARS_LOOK_MS, s)).fetchone()
            bars[s] = _i(got[0]) if got else None
        sig = None
        if "signal_log" in tables:
            r = conn.execute("SELECT bar_close, ref_time, strategy, timeframe, symbol FROM signal_log ORDER BY id DESC LIMIT 1").fetchone()
            sig = {"bar_close": _i(r[0]), "ref_time": _i(r[1]), "strategy": r[2], "tf": r[3], "symbol": r[4]} if r else None
    except sqlite3.Error as exc:
        return L._err(rule_db, exc)
    finally:
        conn.close()
    return {"state": "ok", "path": rule_db, "bars": bars, "signal": sig, "signal_table": "signal_log" in tables}


def paper_beat(paper_path: str) -> dict:
    """The paper bot's heartbeat (state ``heartbeat``, every poll) and its last stepped minute (state ``accounts``)."""
    rows, st = _rows_of(paper_path, "SELECT k, ts, data FROM state WHERE k IN ('heartbeat', 'accounts')")
    if st is not None:
        return st
    by = {k: (_i(ts), L._j(d)) for k, ts, d in rows}
    hb = by.get("heartbeat")
    return {"state": "ok", "path": paper_path, "heartbeat": hb[0] if hb else None, "step": (by.get("accounts") or (None,))[0],
            "queue": _i((hb[1] or {}).get("queue")) if hb else None}


def exec_beat(path: str) -> dict:
    """An executor's last loop: its state ``bot`` row (saved every loop) and its loop count."""
    rows, st = _rows_of(path, "SELECT ts, data FROM state WHERE k = 'bot'")
    if st is not None:
        return st
    if not rows:
        return L._missing(path, "실행기 파일은 있지만 상태 기록이 아직 없어요")
    d = L._j(rows[0][1])
    risk_ = d.get("risk") if isinstance(d.get("risk"), dict) else {}
    return {"state": "ok", "path": path, "at": _i(rows[0][0]), "loops": _i(d.get("loops")), "halted": bool(risk_.get("halted")),
            "halt_reason": risk_.get("halt_reason") or ""}


def watch_beat(check_db: str) -> dict:
    rows, st = _rows_of(check_db, "SELECT MAX(ts) FROM seen")
    if st is not None:
        return st if st.get("state") != "missing" else {**st, "reason_ko": L.CHECK_MISSING_KO}
    return {"state": "ok", "path": check_db, "at": _i(rows[0][0]) if rows else None}


def us_open_windows(now: int, mins: int, days: int = 9) -> tuple:
    """([from, to) of the pause after each NYSE open from yesterday to ``days`` ahead (paperbot/combo.py us_open_pause, word
    for word: each window's minutes are its), None) or ([], why) when it cannot be told."""
    try:
        from ...combo import us_open_pause
        from ...sessions import NY
    except Exception as exc:  # noqa: BLE001  the page says the Nasdaq pause is not known
        return [], f"{type(exc).__name__}: {exc}"
    out = []
    base = _dt.datetime.fromtimestamp(now / 1000, tz=_dt.timezone.utc).astimezone(NY).date()
    for k in range(-1, days):
        d = base + _dt.timedelta(days=k)
        a = int(_dt.datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp() * 1000)
        if us_open_pause(a, mins):
            out.append((a, a + mins * MIN))
    return out, None


def pause_part(p: dict, now: int, cfg: dict) -> dict:
    """The entry pause now (weekend, macro release, Nasdaq open) and when entries may come again: the end of the chain of
    pauses that touch now (livebots.calendar's weekend and releases, combo.us_open_pause), then the next pause."""
    cal = L.calendar(p, now)
    rules = cal.get("rules") or {}
    wins = []
    if rules.get("no_weekend"):
        a, b = L.weekend_span(now)
        for k in range(0, 3):
            wins.append({"from": a + k * 7 * DAY, "to": b + k * 7 * DAY, "why": "weekend", "ko": "주말(토·일, 한국 시간)"})
    for it in cal.get("items") or []:
        if it.get("pause_from") is not None:
            wins.append({"from": it["pause_from"], "to": it["pause_to"] + 1, "why": "macro", "ko": f"{it['kind_ko']} 발표 앞뒤 {rules.get('macro_blackout_min')}분"})
    us_min = _i(cfg.get("us_open_pause_min"))
    us_err = None
    if us_min:
        us, us_err = us_open_windows(now, us_min)
        wins += [{"from": a, "to": b, "why": "usopen", "ko": f"나스닥 개장 뒤 {us_min}분"} for a, b in us]
    on = [w for w in wins if w["from"] <= now < w["to"]]
    t, guard = now, 0
    while guard < 50:
        cover = [w for w in wins if w["from"] <= t < w["to"]]
        if not cover:
            break
        t = max(w["to"] for w in cover)
        guard += 1
    nxt = min((w for w in wins if w["from"] > t), key=lambda w: w["from"], default=None)
    return {"paused": bool(on), "why": [{"why": w["why"], "ko": w["ko"], "to": w["to"]} for w in on], "resume_ms": t if on else None,
            "next": nxt, "rules": {**rules, "us_open_pause_min": us_min}, "us_error": us_err,
            "events": _src(cal.get("events") or {}, "state", "reason_ko", "low", "days_left")}


def health(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/health: is every bot alive, in one look (module docstring); the thresholds are in the answer."""
    more = more or L.paths_more()
    combo = L.read_combo(p["paper"], more["combo_config"])
    cfg = combo.get("config") or {} if combo.get("state") == "ok" else {}
    symbols = [s for s in cfg.get("symbols") or L.COINS if isinstance(s, str)]
    items = []

    def add(id_, ko, st, who=None, detail=None, severity="bad"):
        items.append({"id": id_, "ko": ko, "who": who, "severity": severity, **st, "detail": detail})

    rule = rule_part(more["rule_db"], symbols, now)
    if rule.get("state") != "ok":
        add("bars", "규칙봇 1분봉", {**_src(rule), "at": None, "late_ms": None, "limit_ms": BARS_LATE_MS})
    else:
        for s in symbols:
            st = _late(rule["bars"].get(s), now, BARS_LATE_MS, MIN)
            if st["at"] is None:
                st.update(state="late", why_ko="이틀 넘게 1분봉이 없어요", short_ko="이틀 넘게 없음")
            add("bars", f"1분봉 {s.replace('USDT', '')}", st, who=s)
        sig = rule.get("signal")
        if not rule.get("signal_table"):
            add("signal", "규칙봇 마지막 신호", {"state": "missing", "reason_ko": "규칙봇 파일에 신호 표가 아직 없어요", "at": None, "late_ms": None,
                                         "limit_ms": SIG_QUIET_MS}, severity="warn")
        else:
            st = _late((sig or {}).get("bar_close"), now, SIG_QUIET_MS)
            if st["state"] == "late":
                st["state"] = "quiet"
            add("signal", "규칙봇 마지막 신호", st, detail=sig, severity="warn")
    pb = paper_beat(p["paper"])
    if pb.get("state") != "ok":
        add("paper_hb", "페이퍼 봇 심장 박동", {**_src(pb), "at": None, "late_ms": None, "limit_ms": PAPER_HB_LATE_MS})
    else:
        hb = pb["heartbeat"]
        add("paper_hb", "페이퍼 봇 심장 박동", _late(hb, now, PAPER_HB_LATE_MS) if hb is not None else
            {"state": "missing", "reason_ko": "심장 박동 기록이 아직 없어요 (예전 버전이거나 아직 켜지기 전)", "at": None, "late_ms": None,
             "limit_ms": PAPER_HB_LATE_MS}, detail={"queue": pb.get("queue")})
        add("paper_step", "페이퍼 봇 마지막 1분", _late(pb["step"], now, PAPER_STEP_LATE_MS, MIN))
    # the second paper bot (owners 10-19, docs/live15-mexc-ko.md): its own heartbeat and last minute; it holds an executor
    # back only while one follows it, else it is a comparison (a warning, not a fault)
    _c, _f2, paper, execs = L.sources(p, now)
    for b in L.paper_bots(p, paper, execs)[1:]:
        nm = b["label_ko"].split(" (")[0]
        sev = "bad" if b["follower_ids"] else "warn"
        pb2 = paper_beat(b["path"])
        if pb2.get("state") != "ok":
            add("paper2_hb", f"{nm} 봇 심장 박동", {**_src(pb2), "at": None, "late_ms": None, "limit_ms": PAPER_HB_LATE_MS},
                who="paper2", severity=sev, detail={"label_ko": b["label_ko"]})
            continue
        hb2 = pb2["heartbeat"]
        add("paper2_hb", f"{nm} 봇 심장 박동", _late(hb2, now, PAPER_HB_LATE_MS) if hb2 is not None else
            {"state": "missing", "reason_ko": "심장 박동 기록이 아직 없어요 (아직 켜지기 전)", "at": None, "late_ms": None,
             "limit_ms": PAPER_HB_LATE_MS}, who="paper2", severity=sev, detail={"queue": pb2.get("queue"), "label_ko": b["label_ko"]})
        add("paper2_step", f"{nm} 봇 마지막 1분", _late(pb2["step"], now, PAPER_STEP_LATE_MS, MIN), who="paper2", severity=sev)
    configs = {ex: L.read_config(p[ck]) for ex, _ko, _dk, ck in L.EXECS}
    for ex, ko, dk, _ck in L.EXECS:
        eb = exec_beat(p[dk])
        if eb.get("state") != "ok":
            add("exec", f"{ko} 실행기", {**_src(eb), "at": None, "late_ms": None, "limit_ms": EXEC_LATE_MS}, who=ex)
        else:
            add("exec", f"{ko} 실행기", _late(eb["at"], now, EXEC_LATE_MS), who=ex,
                detail={"loops": eb.get("loops"), "halted": eb.get("halted"), "halt_reason": eb.get("halt_reason")})
    wb = watch_beat(more["check_db"])
    if wb.get("state") != "ok":
        add("watch", "실시간 감시 (텔레그램 알림)", {**_src(wb), "at": None, "late_ms": None, "limit_ms": WATCH_LATE_MS}, severity="warn")
    else:
        add("watch", "실시간 감시 (텔레그램 알림)", _late(wb["at"], now, WATCH_LATE_MS), severity="warn")
    kill = kill_state({"configs": configs})
    pz = pause_part(p, now, cfg)
    return {"now_ms": now, "items": items, "summary": health_summary(items, kill), "pause": pz, "kill": kill,
            "limits": {"bars_ms": BARS_LATE_MS, "paper_hb_ms": PAPER_HB_LATE_MS, "paper_step_ms": PAPER_STEP_LATE_MS, "exec_ms": EXEC_LATE_MS,
                       "signal_ms": SIG_QUIET_MS, "watch_ms": WATCH_LATE_MS},
            "combo": _src(combo, "state", "reason_ko", "path", "source")}


def health_summary(items: list, kill: dict) -> dict:
    """One traffic light: bad (something the bots need is late, missing or unreadable, or the kill file is there), warn
    (only the quiet ones: no signal for a while, the watcher), ok ("다 정상")."""
    bad = [i for i in items if i["state"] in ("late", "missing", "error") and i["severity"] == "bad"]
    warn = [i for i in items if i["state"] in ("late", "missing", "error", "quiet") and i["severity"] != "bad"]
    words = []
    for i in bad + warn:
        if i["state"] in ("late", "quiet"):
            how = _ago_ko(i["late_ms"]) if i.get("late_ms") is not None else i.get("short_ko")
            words.append(f"{i['ko']} {'조용함' if i['state'] == 'quiet' else '늦음'}" + (f" ({how})" if how else ""))
        else:
            words.append(f"{i['ko']} {'수집 전' if i['state'] == 'missing' else '못 읽음'}")
    if kill.get("any"):
        words.insert(0, "비상 정지 파일 있음")
    tone = "bad" if bad or kill.get("any") else "warn" if warn else "ok"
    return {"tone": tone, "ko": "다 정상" if tone == "ok" else " · ".join(words), "bad": len(bad), "warn": len(warn)}


def _ago_ko(ms: Optional[int]) -> str:
    if ms is None:
        return "—"
    s = max(0, int(ms // 1000))
    if s < 60:
        return f"{s}초"
    if s < 3600:
        return f"{s // 60}분"
    if s < 86400:
        return f"{s // 3600}시간 {s % 3600 // 60}분" if s % 3600 >= 60 else f"{s // 3600}시간"
    return f"{s // 86400}일"


# ================================================================ A / B groups
def groups(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/groups: per group A / B (since the start) and 예전 매매법 (settings no longer in the config, any
    time), for the paper account and each executor (a live trade takes its paper partner's group: livebots.match)."""
    cx = context(p, now, more)
    members = cx["members"]
    defs = [{"id": g, "ko": GROUP_KO[g], "sub_ko": GROUP_SUB_KO[g], "n_members": sum(1 for m in members if m["group"] == g) if g in ("A", "B") else None,
             "members": [{"order": m["order"], "strategy": m["strategy"], "tf": m["tf"]} for m in members if m["group"] == g] if g in ("A", "B") else []}
            for g in ("A", "B", "old")]
    out = {}
    st = paper_state(cx)
    ptrades = (cx["acc"] or {}).get("trades") or []
    gid = {t["id"]: group_of(t, cx["meta"], members, cx["start"]) for t in ptrades}
    mine = {t["id"] for t in since_start(ptrades, cx["start"], cx["meta"], members)}

    def pick(trades, g_of, in_span):
        by = {"A": [], "B": [], "old": [], "none": []}
        for t in trades:
            g = g_of(t)
            if g in ("A", "B") and not in_span(t):
                continue                                  # a setting of this config traded before its start: neither group
            by[g].append(t)
        return {g: {**record(v), "first_ms": min((x.get("entry_time") or x.get("entry_ts") or 0 for x in v), default=None)} for g, v in by.items()}

    if st["state"] == "ok":
        out["paper"] = {"state": "ok", "groups": pick(ptrades, lambda t: gid.get(t["id"], "old"), lambda t: t["id"] in mine)}
    else:
        out["paper"] = st
    main = cx["p"]["paper"]
    other: dict = {}                                    # another paper bot's trades: its group and span (bot_side)

    def g_other(pt: dict) -> tuple:
        k = (L.LP.norm(pt["paper_path"]), pt["id"])
        if k not in other:
            s = bot_side(cx, pt["paper_path"])
            mine2 = {t["id"] for t in since_start((s["acc"] or {}).get("trades") or [], s["start"], s["meta"], s["members"])}
            other[k] = (group_of(pt, s["meta"], s["members"], s["start"]), pt["id"] in mine2)
        return other[k]
    for x in cx["execs"]:
        r = x["record"]
        if r.get("state") != "ok":
            out[x["id"]] = _src(r)
            continue
        pairs = L.pairs_of(x)                           # the paper trade each live trade followed: its own bot's
        live = []
        for t in r.get("trades") or []:
            pt = pairs.get(str(t["key"]))
            if pt is None:
                live.append({**t, "_g": "none", "_in": False})
            elif L.LP.same(pt["paper_path"], main):
                live.append({**t, "_g": gid.get(pt["id"], "old"), "_in": pt["id"] in mine})
            else:
                g, inside = g_other(pt)
                live.append({**t, "_g": g, "_in": inside})
        out[x["id"]] = {"state": "ok", "groups": pick(live, lambda t: t["_g"], lambda t: t["_in"])}
    return {"now_ms": now, "start": start_out(cx), "defs": defs, "accts": out,
            "execs": [{"id": x["id"], "name_ko": x["name_ko"]} for x in cx["execs"]], "small_n": SMALL_N}


# ================================================================ routes
def register(app, ctx) -> dict:
    from ..app import json_finite

    def key(name: str, p: dict) -> str:
        return "insight:" + name + ":" + json.dumps([p, L.paths_more()], sort_keys=True)

    def now_ms() -> int:
        return int(time.time() * 1000)

    @app.get("/api/v4/livebots/judge")
    def get_livebots_judge():
        """실거래 › 규칙 점검: 빠른 손절 · 추격 막기 · 동전 쌍둥이, since the 규칙봇 15 start (5 s cache)."""
        p = L.paths()
        return L._cached(key("judge", p), lambda: json_finite(judge(p, now_ms())))

    @app.get("/api/v4/livebots/goal")
    def get_livebots_goal():
        """실거래 › 목표: this month against the owners' monthly goal and the record so far (5 s cache)."""
        p = L.paths()
        return L._cached(key("goal", p), lambda: json_finite(goal(p, now_ms())))

    @app.get("/api/v4/livebots/risk")
    def get_livebots_risk():
        """실거래 › 위험: what one more stop costs, the streak, the drawdown, the next-losses table, the kill file (5 s cache)."""
        p = L.paths()
        return L._cached(key("risk", p), lambda: json_finite(risk(p, now_ms())))

    @app.get("/api/v4/livebots/health")
    def get_livebots_health():
        """실거래 › 봇 상태: each bot's last sign of life against its threshold, the pause now, the kill file (5 s cache)."""
        p = L.paths()
        return L._cached(key("health", p), lambda: json_finite(health(p, now_ms())))

    @app.get("/api/v4/livebots/groups")
    def get_livebots_groups():
        """실거래 › 성적 · 순위: A / B / 예전 매매법 per account since the 규칙봇 15 start (5 s cache)."""
        p = L.paths()
        return L._cached(key("groups", p), lambda: json_finite(groups(p, now_ms())))

    return {"routes": ["/api/v4/livebots/judge", "/api/v4/livebots/goal", "/api/v4/livebots/risk", "/api/v4/livebots/health",
                       "/api/v4/livebots/groups"], "paths": L.paths}
