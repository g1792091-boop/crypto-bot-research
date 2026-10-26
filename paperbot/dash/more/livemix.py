"""실거래 › 믹스 봇 (#/mix · #/mixperf; owners 10-25 night: the '믹스 30분 봇', paperbot/mixchop.py, docs/mixchop-ko.md,
which trades the second WOO X Pro account with real money, and its paper twin; the owners watch it on this site as they
watch the 'VWAP 개선판'). Read-only, two answers:

    GET /api/v4/livebots/mix       관제: per bot (실거래 and 모의, side by side): running / stopped / not installed (the
                                   state file's ``saved_ms``, written at every 30-minute close; the systemd unit to look
                                   at when stopped), the equity now (live: the last equity the bot read and logged, at a
                                   start, an entry or an exit; paper: its ``paper_equity``), the start equity and the floor
                                   line (``equity_floor_frac``), what stops new entries now (the kill file, the bot's own
                                   stop file, the floor) and the last halt the log shows, the entry block now and the next
                                   window (mixchop.entry_block with the config's own rules, on the server clock), the open
                                   position (stop and its ROE, ladder step, best price, the next ladder trigger and the
                                   stop it would move to: mixchop.ladder_stop), the last 48 hours of signals with what
                                   became of each and the warnings (stop_failed, adopted, entry_failed ...)
    GET /api/v4/livebots/mixperf   성적: per bot the closed trades (exit rows joined to their entry rows by coin and
                                   ``opened_ms``): count, wins, win rate, P&L, average win / loss, largest loss, by coin,
                                   the list; the design's 5-year backtest per coin next to them (labelled as such, never
                                   as live); the rules of each config; ``analysis`` (owners 10-25 night, paperbot/mixcheck.py
                                   site_view): the live trades' loss cards, the luck band against the 5-year replay of the
                                   bot's own code, that replay next to the design's numbers, the last morning check
    (5 s cache each, as every 실거래 tab)

Sources (the bot's own files, read only; nothing here writes anywhere): per bot its state file (JSON), its log (JSON
lines; it grows forever, so only its last TAIL_BYTES are read, said so when cut; parsed once per file change) and its
config (/etc/paperbot/mixchop*.json, mixchop.load_config; when missing or unreadable the repo's deploy/mixchop.*.json, said
so). Every path has its environment variable (ENV); the state and log paths otherwise follow the config's own ``state`` /
``log``. Honest states as every live page (CONTRACT §1.6): a missing file = 꺼짐 / 수집 전, an unreadable one = 못 읽음 +
why, never a zero; the paper bot's money is never shown as real money.

The numbers: ratios (0.12 = 12 %), money in USDT, times UTC ms. A trade's P&L is the equity change from its entry to its
exit (live: what the bot logged, ``None`` when it could not read the equity; paper: both fees included), win = P&L > 0.
"""
from __future__ import annotations

import dataclasses
import json
import os
import time
from typing import Any, Optional

from ... import mixchop as M
from . import livebots as L

MIN, HOUR, DAY = 60_000, L.HOUR, L.DAY
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir))
# (id, words, systemd unit, the config's mode, the guide's step to start it)
BOTS = (("live", "실거래", "paperbot-mixchop", "mainnet", "docs/mixchop-ko.md 5장 7"),
        ("paper", "모의", "paperbot-mixchop-paper", "paper", "docs/mixchop-ko.md 5장 6"))
# every path the answers read: (environment variable, default); state / log default to the config's own paths
ENV = {
    "live": {"state": ("PAPERBOT_MIX_STATE", None), "log": ("PAPERBOT_MIX_LOG", None),
             "config": ("PAPERBOT_MIX_CONFIG", "/etc/paperbot/mixchop.json"),
             "repo_config": ("PAPERBOT_MIX_REPO_CONFIG", os.path.join(REPO, "deploy", "mixchop.live.json"))},
    "paper": {"state": ("PAPERBOT_MIX_PAPER_STATE", None), "log": ("PAPERBOT_MIX_PAPER_LOG", None),
              "config": ("PAPERBOT_MIX_PAPER_CONFIG", "/etc/paperbot/mixchop-paper.json"),
              "repo_config": ("PAPERBOT_MIX_PAPER_REPO_CONFIG", os.path.join(REPO, "deploy", "mixchop.paper.json"))},
}
DEFAULT_FILES = {"live": ("/var/lib/paperbot/exec/mixchop-state.json", "/var/lib/paperbot/exec/mixchop-log.jsonl"),
                 "paper": ("/var/lib/paperbot/mixchop-paper/state.json", "/var/lib/paperbot/mixchop-paper/log.jsonl")}
STALE_MS = 35 * MIN                     # the bot saves at every 30-minute close: older than this = 멈춤
TAIL_BYTES = 8 * 1024 * 1024            # the log's last 8 MB (about a year of this bot's rows)
SIG_SPAN_MS = 48 * HOUR                 # 최근 48시간
FEED_KEEP = 400
TRADES_KEEP = 300
SMALL_N = 20                            # a record under this many trades: 표본 적음
RING_N = 20                             # 한눈에's ring: the last 20 closed trades
SPLIT_MIN_N = 10                        # a coin's row under this many: 표본 적음
NEXT_BLOCK_DAYS = 8
JUDGE_LAG_MS = 5_000                    # the bot judges an entry a few seconds after the close (SETTLE_S, the reads)
SIDE_KO = {1: "롱", -1: "숏"}
OFF_KO = {"live": "믹스 30분 봇(실거래)이 아직 꺼져 있어요 · 기록 파일이 없어요",
          "paper": "믹스 30분 봇(모의)이 아직 꺼져 있어요 · 기록 파일이 없어요"}
STOPPED_KO = "35분 넘게 새 기록이 없어요 (봇은 30분봉이 끝날 때마다 기록해요)"
# the design's 5-year backtest per coin (docs/mixchop-ko.md 7장, the design notes the owners handed over): a stop-out =
# 0.25 % of the equity; never live numbers
BACKTEST = {
    "risk_pct": 0.25, "years": 5,
    "rows": [{"symbol": "SOLUSDT", "month": 0.0117, "win": 0.32}, {"symbol": "ETHUSDT", "month": 0.0094, "win": 0.19},
             {"symbol": "XRPUSDT", "month": 0.0089, "win": 0.20}, {"symbol": "BCHUSDT", "month": 0.0070, "win": 0.31},
             {"symbol": "ZECUSDT", "month": 0.0047, "win": 0.37}, {"symbol": "DOGEUSDT", "month": 0.0037, "win": 0.40}],
    "ko": "설계서의 5년 백테스트예요 (실거래 아님) · 손절 1번에 잔고의 0.25% · 코인마다 따로 돌린 값",
    "notes_ko": ["60개월 중 20~30개월은 마이너스였어요", "승률 20~40%: 작은 손절이 여러 번 이어지다 한 번 크게 먹는 구조예요",
                 "주말·나스닥 개장·경제 발표 진입 금지는 백테스트에 없던 규칙이라 실제 진입 수는 줄어요",
                 "실거래는 한 번에 1포지션이라 코인별 값을 더한 만큼 나오지 않아요"],
    "src": "docs/mixchop-ko.md 7장 (친구 설계서의 5년 백테스트)"}
# the log's kinds the 관제 lists as warnings: (words, tone)
WARN_KO = {
    "stop_failed": ("손절 주문을 걸지 못했어요", "bad"), "protect_close_failed": ("손절을 못 걸어 시장가로 닫으려 했지만 실패했어요", "bad"),
    "protect_failed": ("손절을 다시 걸지 못했어요 (거래소를 못 읽음)", "bad"),
    "reconcile_failed": ("다시 켜면서 포지션·손절을 확인하지 못했어요", "bad"), "entry_failed": ("진입 주문 결과를 몰라요", "bad"),
    "entry_none": ("진입 주문이 체결된 것이 안 보였어요", "warn"), "adopted": ("늦게 확인한 체결을 봇 포지션으로 받았어요", "warn"),
    "qty_adopted": ("거래소 수량으로 포지션 크기를 맞췄어요", "warn"), "stop_replaced": ("손절이 없거나 모자라 다시 걸었어요", "warn"),
    "read_failed": ("거래소를 읽지 못했어요", "warn"), "poll_failed": ("점검 중 거래소를 읽지 못했어요", "warn"),
    "move_failed": ("계단 손절을 옮기지 못했어요 (지금 손절 그대로)", "warn"),
    "ladder_closed": ("계단 손절을 옮기려는데 가격이 이미 지나 있었어요", "warn"),
    "cancel_failed": ("청산 뒤 남은 손절 주문을 취소하지 못했어요", "warn"),
    "bars_missing": ("바이낸스 봉을 못 읽어 그 코인의 이번 봉을 건너뛰었어요", "warn"),
    "bars_failed": ("바이낸스 봉을 못 읽어 이번 계단 계산을 건너뛰었어요", "warn"), "close_failed": ("30분봉 마감 처리에 실패했어요", "warn"),
}
# a skip row's reason, grouped: (words, tone); the bot's own words stay in ``why``
SKIP_GROUPS = {"held": ("보유 중", "thin"), "same_bar": ("같은 봉 다른 코인 먼저", "thin"), "block": ("진입 금지 시간", "warn"),
               "halt": ("새 진입 멈춤", "bad"), "small": ("최소 주문보다 작음", "warn"), "liq": ("청산가에 너무 가까움", "warn"),
               "other": ("건너뜀", "thin")}
HALT_PREFIXES = ("정지 파일", "잔고를 못 읽음", "잔고 $", "포지션을 못 읽음", "봇이 모르는 포지션", "진입 체결 확인 중")
BLOCK_PREFIXES = {"주말": "weekend", "나스닥": "usopen", "경제 발표": "macro"}
BLOCK_KO = {"weekend": "주말 (한국 시간 토·일)", "usopen": "나스닥 개장 앞뒤", "macro": "미국 경제 발표 앞뒤"}


# ---------------------------------------------------------------- small helpers
def _f(x: Any) -> Optional[float]:
    return L._f(x)


def _i(x: Any) -> Optional[int]:
    return L._i(x)


def coin_ko(symbol: Any) -> str:
    return M.coin_ko(str(symbol or ""))


def skip_group(why: Any) -> str:
    """held / same_bar / block / halt / small / liq / other of a skip row's reason (mixchop.py on_close / enter words)."""
    w = str(why or "")
    if w == "보유 중":
        return "held"
    if w.startswith("같은 봉에"):
        return "same_bar"
    if w.startswith(tuple(BLOCK_PREFIXES)):
        return "block"
    if w.startswith(HALT_PREFIXES):
        return "halt"
    if w.startswith("최소 주문"):
        return "small"
    if "청산가" in w:
        return "liq"
    return "other"


def block_kind(why: Any) -> Optional[str]:
    """weekend / usopen / macro of mixchop.entry_block's words (None: no block)."""
    w = str(why or "")
    return next((k for p, k in BLOCK_PREFIXES.items() if w.startswith(p)), None) if w else None


# ---------------------------------------------------------------- where the files are
def paths(env: Optional[dict] = None) -> dict:
    """{"live": {"state", "log", "config", "repo_config"}, "paper": {...}}: the environment variable when set; ``state`` /
    ``log`` None otherwise (resolved from the config, files_of)."""
    env = os.environ if env is None else env
    return {bid: {k: (env.get(var) or default) for k, (var, default) in d.items()} for bid, d in ENV.items()}


def files_of(bid: str, bp: dict, conf: dict) -> tuple:
    """(state path, log path) of a bot: its environment variable, else the server config's own ``state`` / ``log`` (the
    bot writes there), else the guide's paths."""
    raw = conf.get("raw") if conf.get("source") == "server" else None
    st = bp.get("state") or ((raw or {}).get("state") if isinstance((raw or {}).get("state"), str) else None) or DEFAULT_FILES[bid][0]
    lg = bp.get("log") or ((raw or {}).get("log") if isinstance((raw or {}).get("log"), str) else None) or DEFAULT_FILES[bid][1]
    return st, lg


# ---------------------------------------------------------------- reads (one each, never a write)
def read_config(path: str, repo_path: str) -> dict:
    """The bot's config (mixchop.load_config: the bot's own checks): {"state": "ok", "source": "server" | "repo", "cfg":
    Config, "raw", "path"} — the repo's deploy file when the server's is missing or unreadable (``server_state`` /
    ``reason_ko`` say why); ``state`` "error" when neither can be read."""
    out: dict = {"path": path, "repo_path": repo_path}
    try:
        cfg = M.load_config(path)
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return {**out, "state": "ok", "source": "server", "cfg": cfg, "raw": raw, "server_state": "ok"}
    except FileNotFoundError:
        out.update(server_state="missing", reason_ko="서버 설정 파일이 아직 없어요 (docs/mixchop-ko.md 5장 3) · 저장소 기본 설정으로 보여 줘요")
    except Exception as exc:  # noqa: BLE001  unreadable, not JSON, or refused by the bot's own checks (MixError): said so
        out.update(server_state="error", reason=f"{type(exc).__name__}: {exc}"[:300],
                   reason_ko=("서버 설정 파일을 읽지 못했어요" + (f" ({L.reason_ko(exc, path)})" if isinstance(exc, OSError) else f": {exc}"))[:300]
                   + " · 저장소 기본 설정으로 보여 줘요")
    try:
        cfg = M.load_config(repo_path)
        with open(repo_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return {**out, "state": "ok", "source": "repo", "cfg": cfg, "raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {**out, "state": "error", "source": None, "cfg": None, "raw": None,
                "reason_ko": (out.get("reason_ko") or "") + f" · 저장소 기본 설정도 읽지 못했어요 ({type(exc).__name__})",
                "reason": f"{type(exc).__name__}: {exc}"[:300]}


def read_state(path: str) -> dict:
    """The bot's state file: {"state": "ok", "d", "mtime_ms"} / missing / error (never a guess)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
            mtime = int(os.fstat(fh.fileno()).st_mtime * 1000)
    except FileNotFoundError:
        return L._missing(path, "상태 파일이 아직 없어요")
    except OSError as exc:
        return L._err(path, exc)
    try:
        d = json.loads(text)
    except ValueError as exc:
        return {"state": "error", "path": path, "reason": f"{type(exc).__name__}: {exc}"[:300], "reason_ko": "상태 파일 내용이 JSON이 아니에요"}
    if not isinstance(d, dict):
        return {"state": "error", "path": path, "reason": "not an object", "reason_ko": "상태 파일 모양이 예상과 달라요"}
    return {"state": "ok", "path": path, "d": d, "mtime_ms": mtime}


_tails: dict = {}                       # path -> ((inode, size, mtime_ns), answer): the log is parsed once per change


def read_log(path: str, tail: Optional[int] = None) -> dict:
    """The log's rows (oldest first) from its last ``tail`` bytes (TAIL_BYTES): {"state": "ok", "rows", "cut" (the file is
    longer: its start was not read), "from_ms" (the first row read), "size", "bad" (lines that are not JSON)}; missing /
    error as every source. A half-written last line is left out (the bot is appending it)."""
    tail = TAIL_BYTES if tail is None else int(tail)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return L._missing(path, "기록(log) 파일이 아직 없어요")
    except OSError as exc:
        return L._err(path, exc)
    key = (st.st_ino, st.st_size, st.st_mtime_ns, tail)
    hit = _tails.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            start = max(0, st.st_size - tail)
            fh.seek(start)
            data = fh.read(st.st_size - start)
    except OSError as exc:
        return L._err(path, exc)
    if start > 0:
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else b""
    lines = data.split(b"\n")
    half = lines.pop() if lines and not data.endswith(b"\n") else None
    rows, bad = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(r, dict) and _i(r.get("ts")) is not None:
            rows.append(r)
        else:
            bad += 1
    out = {"state": "ok", "path": path, "rows": rows, "cut": start > 0, "from_ms": _i(rows[0]["ts"]) if rows else None,
           "size": st.st_size, "bad": bad, "half": half is not None and bool(half.strip())}
    if len(_tails) > 8:
        _tails.clear()
    _tails[path] = (key, out)
    return out


def stop_file(path: Any) -> Optional[bool]:
    """Is a stop file there: True / False; None when it cannot be told (no permission)."""
    if not path:
        return False
    try:
        os.stat(str(path))
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return None


# ---------------------------------------------------------------- one bot's files in one read
def load_bot(bid: str, bp: dict, now: int, tail: Optional[int] = None) -> dict:
    """The config, the state and the log of one bot, and whether it runs: {"id", "conf", "st", "lg", "status"}."""
    conf = read_config(bp["config"], bp["repo_config"])
    sp, lp = files_of(bid, bp, conf)
    st, lg = read_state(sp), read_log(lp, tail)
    return {"id": bid, "conf": conf, "st": st, "lg": lg, "status": status_of(bid, st, lg, now)}


def status_of(bid: str, st: dict, lg: dict, now: int) -> dict:
    """running / stopped / off / error, from the state file's ``saved_ms`` (written at every 30-minute close; its mtime
    when the field is not there), else the log's last row."""
    unit, mode = next((u, m) for b, _k, u, m, _g in BOTS if b == bid)
    rows = lg.get("rows") or []
    starts = [r for r in rows if r.get("kind") == "start"]
    base = {"unit": unit, "stale_ms": STALE_MS, "last_log_ms": _i(rows[-1]["ts"]) if rows else None,
            "started_ms": _i(starts[-1]["ts"]) if starts else None,
            # its first start (한눈에's DAY n): the log's first start row, unknown when the log's start was not read
            "first_start_ms": _i(starts[0]["ts"]) if starts and not lg.get("cut") else None}
    if st["state"] == "missing" and lg["state"] == "missing":
        return {**base, "state": "off", "ko": OFF_KO[bid]}
    if st["state"] == "error":
        return {**base, "state": "error", "ko": "상태 파일을 읽지 못해 돌고 있는지 몰라요", "reason_ko": st.get("reason_ko"), "reason": st.get("reason")}
    d = st.get("d") or {}
    seen = _i(d.get("saved_ms")) or st.get("mtime_ms") or base["last_log_ms"]
    age = now - seen if seen is not None else None
    running = age is not None and age <= STALE_MS
    out = {**base, "state": "running" if running else "stopped", "saved_ms": _i(d.get("saved_ms")), "seen_ms": seen, "age_ms": age,
           "seen_from": "saved_ms" if d.get("saved_ms") is not None else "mtime" if st.get("mtime_ms") else "log",
           "last_close_ms": _i(d.get("last_close_ms")), "mode": d.get("mode"),
           "ko": "돌고 있음" if running else STOPPED_KO}
    if d.get("mode") and d.get("mode") != mode:
        out["mode_ko"] = f"상태 파일의 mode가 {d.get('mode')!r}예요 (이 칸은 {mode!r} 봇)"
    return out


def file_states(b: dict) -> dict:
    """What each file is (path, state, the reasons): the page's small print and the 못 읽음 boxes."""
    keep = ("state", "path", "reason_ko", "reason")
    c = b["conf"]
    return {"state": {k: b["st"].get(k) for k in keep}, "log": {**{k: b["lg"].get(k) for k in keep},
            **({"cut": b["lg"]["cut"], "from_ms": b["lg"]["from_ms"], "size": b["lg"]["size"], "bad": b["lg"]["bad"], "tail_bytes": TAIL_BYTES}
               if b["lg"].get("state") == "ok" else {})},
            "config": {"state": c.get("state"), "source": c.get("source"), "path": c.get("path"), "repo_path": c.get("repo_path"),
                       "server_state": c.get("server_state"), "reason_ko": c.get("reason_ko"), "reason": c.get("reason")}}


# ---------------------------------------------------------------- 잔고 · 바닥선 · 멈춤
def equity_view(bid: str, b: dict) -> dict:
    """The equity now (live: the newest equity the bot read and logged: a start, an entry's equity_before or an exit;
    paper: its ``paper_equity``), the start equity (the state's, the floor's base) and the floor line."""
    d = (b["st"].get("d") or {}) if b["st"].get("state") == "ok" else {}
    rows = b["lg"].get("rows") or []
    cfg = b["conf"].get("cfg")
    now_eq = None
    if bid == "paper" and _f(d.get("paper_equity")) is not None:
        now_eq = {"value": _f(d["paper_equity"]), "ms": _i(d.get("saved_ms")), "from": "state", "from_ko": "모의 잔고 (상태 파일)"}
    if now_eq is None:
        for r in reversed(rows):
            k = r.get("kind")
            v = _f(r.get("equity")) if k in ("start", "exit") else _f(r.get("equity_before")) if k in ("entry", "adopted") else None
            if v is not None:
                now_eq = {"value": v, "ms": _i(r.get("ts")), "from": k,
                          "from_ko": {"start": "시작 때 읽은 잔고", "exit": "청산 뒤 읽은 잔고", "entry": "진입 때 읽은 잔고",
                                      "adopted": "체결 확인 때 읽은 잔고"}[k]}
                break
    start = _f(d.get("start_equity"))
    if start is None:
        start = next((_f(r.get("start_equity")) for r in reversed(rows) if r.get("kind") == "start" and _f(r.get("start_equity")) is not None), None)
    frac = float(cfg.equity_floor_frac) if cfg is not None else None
    floor = start * frac if start is not None and frac is not None else None
    v = now_eq["value"] if now_eq else None
    return {"now": now_eq, "start": start, "change": (v / start - 1) if v is not None and start else None,
            "floor_frac": frac, "floor": floor, "room": (v - floor) if v is not None and floor is not None else None,
            "below": (v < floor) if v is not None and floor is not None else None, "real": bid == "live",
            "none_ko": "아직 잔고 기록이 없어요 (봇이 켜질 때 처음 읽어요)"}


def halts_view(b: dict, eq: dict, now: int) -> dict:
    """What stops new entries now: the shared kill file, the bot's own stop file, the floor (the bot's halts() in the same
    order); and the last halt the log shows (written only when a signal came: a skip row with the halt's words)."""
    cfg = b["conf"].get("cfg")
    items = []
    if cfg is not None:
        for kind, path, ko in (("kill", cfg.kill_file, "공용 비상 파일 (다른 실행기들은 이 파일에 전부 청산해요 · 이 봇은 새 진입만 멈춰요)"),
                               ("own", cfg.own_stop_file, "이 봇 전용 정지 파일 (새 진입만 멈춤 · 열린 포지션은 손절·계단 그대로)")):
            there = stop_file(path)
            if there is not False:
                items.append({"kind": kind, "path": path, "ko": ko if there else f"{ko}: 있는지 확인하지 못했어요", "sure": there is True})
    if eq.get("below"):
        items.append({"kind": "floor", "ko": f"잔고가 시작 잔고의 {eq['floor_frac']:.0%} 아래 (새 진입 멈춤)", "sure": True})
    rows = b["lg"].get("rows") or []
    last = None
    for r in reversed(rows):
        if r.get("kind") == "skip" and skip_group(r.get("why")) == "halt":
            last = {"why": r.get("why"), "ms": _i(r.get("ts")), "symbol": r.get("symbol")}
            break
    if last is not None:
        after = [r for r in rows if (_i(r.get("ts")) or 0) > last["ms"] and r.get("kind") in ("entry", "adopted")]
        last["entry_after"] = bool(after)
        last["recent"] = now - last["ms"] <= SIG_SPAN_MS
    return {"items": items, "halted": any(x["sure"] for x in items), "last": last, "cfg_unread": cfg is None,
            "note_ko": "멈춤 이유는 신호가 왔을 때만 기록에 남아요 (정지 파일과 바닥선은 지금 직접 확인)"}


# ---------------------------------------------------------------- 진입 금지 시간 (mixchop.entry_block)
def _blocked(cfg: Any, t: int) -> str:
    return M.entry_block(cfg, int(t) + JUDGE_LAG_MS)


def block_end(cfg: Any, t: int, limit: int) -> Optional[int]:
    """The first minute after ``t`` (a blocked minute) that is not blocked (5-minute steps, then the exact minute);
    None past ``limit``."""
    a = int(t)
    while _blocked(cfg, a + 5 * MIN):
        a += 5 * MIN
        if a > limit:
            return None
    b = a + MIN
    while _blocked(cfg, b):
        b += MIN
    return b


def block_rules(cfg: Any) -> list:
    """The config's entry blocks, each on or off (mixchop.Config: no_weekend, us_open_pre_min / us_open_pause_min,
    macro_blackout_min)."""
    return [{"id": "weekend", "ko": "주말 (한국 시간 토·일)", "on": bool(cfg.no_weekend)},
            {"id": "usopen", "ko": f"나스닥 개장 앞 {cfg.us_open_pre_min}분·뒤 {cfg.us_open_pause_min}분 (뉴욕 09:30, 평일, 미국 휴장일 빼고)",
             "on": bool(cfg.us_open_pre_min or cfg.us_open_pause_min)},
            {"id": "macro", "ko": f"미국 경제 발표 앞뒤 {cfg.macro_blackout_min}분 (data/macro_events.csv 일정)", "on": bool(cfg.macro_blackout_min)}]


def blocks_view(cfg: Any, now: int) -> dict:
    """The entry block at ``now`` (the server clock) by the config's own rules (mixchop.entry_block) and the next window
    (from, until; 5-minute steps, then the exact minute) within NEXT_BLOCK_DAYS."""
    if cfg is None:
        return {"state": "error", "ko": "설정을 못 읽어 진입 금지 시간을 몰라요"}
    rules = block_rules(cfg)
    base = {"rules": rules, "any": any(r["on"] for r in rules)}
    if not base["any"]:
        return {**base, "state": "ok", "now": {"blocked": False, "ko": "지금 진입 가능 (진입 금지 시간 규칙이 꺼져 있어요)"}, "next": None}
    try:
        why = M.entry_block(cfg, int(now))
        t = int(now) - int(now) % MIN
        until = block_end(cfg, t, t + 3 * DAY) if why else None
        nxt = None
        s = until if why and until is not None else t
        end = s + NEXT_BLOCK_DAYS * DAY
        while s < end:
            if _blocked(cfg, s + 5 * MIN):
                a = s + MIN
                while not _blocked(cfg, a):
                    a += MIN
                w = _blocked(cfg, a)
                nxt = {"from": a, "until": block_end(cfg, a, a + 3 * DAY), "why": w, "kind": block_kind(w), "ko": BLOCK_KO.get(block_kind(w), w)}
                break
            s += 5 * MIN
    except Exception as exc:  # noqa: BLE001  the calendar's own failure: said, never a guess
        return {**base, "state": "error", "ko": "진입 금지 시간을 계산하지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    now_d = {"blocked": bool(why), "why": why or None, "kind": block_kind(why), "until": until,
             "ko": why or "지금 진입 가능 (진입 금지 시간 아님)"}
    return {**base, "state": "ok", "now": now_d, "next": nxt, "days": NEXT_BLOCK_DAYS}


# ---------------------------------------------------------------- the open position
def position_of(raw: Any) -> Optional[M.Position]:
    """The state's position as mixchop.Position (its own fields only); None when there is none or it cannot be read."""
    if not isinstance(raw, dict):
        return None
    names = {f.name for f in dataclasses.fields(M.Position)}
    try:
        return M.Position(**{k: v for k, v in raw.items() if k in names})
    except TypeError:
        return None


def ladder_next(p: M.Position) -> Optional[dict]:
    """The next ladder step of an open position (mixchop.ladder_stop's steps: the first lock at ROE +10 % once the best
    price is ``roe_act`` % ROE past the entry, then one more (roe_act - 10) % step each): {"step", "trigger", "trigger_roe",
    "stop_to", "stop_to_roe", "reached" (the best price is already there: it moves at the next 30-minute close)}."""
    if not p.entry or not p.leverage:
        return None
    lev, side, e = float(p.leverage), int(p.side), float(p.entry)
    for s in range(max(int(p.step or 0), 0), 200):
        roe = float(p.roe_act) + s * (float(p.roe_act) - M.LOCK_ROE)
        trig = e + side * e * roe / 100.0 / lev
        new, k = M.ladder_stop(side, e, trig + side * e * 1e-9, float(p.stop), float(p.roe_act), lev)
        if k > 0:
            break
    else:
        return None
    reached = side * (float(p.best) - trig) >= 0
    return {"step": k, "trigger": trig, "trigger_roe": roe / 100.0, "stop_to": new, "stop_to_roe": p.roe(new) / 100.0, "reached": reached}


def ladder_next_net(p: M.Position, lad: dict, fee: float) -> Optional[dict]:
    """ladder_next for the config's net-ROE ladder (owners 10-26: trigger -> lock, then one ``step`` more each):
    the step after the position's own, its trigger and its stop in prices and NET ROE."""
    if not p.entry or not p.leverage:
        return None
    lev, side, e = float(p.leverage), int(p.side), float(p.entry)
    k = max(int(p.step or 0), 0)
    t_roe, l_roe = lad["trigger"] + lad["step"] * k, lad["lock"] + lad["step"] * k
    trig = e * (1 + side * (t_roe / 100.0 / lev + 2 * fee))
    to = e * (1 + side * (l_roe / 100.0 / lev + 2 * fee))
    return {"step": k + 1, "trigger": trig, "trigger_roe": t_roe / 100.0, "stop_to": to, "stop_to_roe": l_roe / 100.0,
            "reached": side * (float(p.best) - trig) >= 0, "basis": "net"}


def position_view(bid: str, d: dict, now: int, cfg: Any = None) -> Optional[dict]:
    p = position_of(d.get("position"))
    if p is None:
        return None if not d.get("position") else {"state": "error", "ko": "상태 파일의 포지션을 읽지 못했어요"}
    e, q = _f(p.entry), _f(p.qty)
    notional = e * q if e is not None and q is not None else None
    lev = _i(p.leverage) or None
    loss = p.side * (p.stop - p.entry) * p.qty if e is not None and q is not None and _f(p.stop) is not None else None
    lad = getattr(cfg, "ladder", None) if cfg is not None else None
    fee = float(getattr(cfg, "taker_fee", M.Config.taker_fee)) if cfg is not None else M.Config.taker_fee
    if lad and e and lev:
        lock_px = e * (1 + p.side * (lad["lock"] / 100.0 / lev + 2 * fee))
        act_px = e * (1 + p.side * (lad["trigger"] / 100.0 / lev + 2 * fee))
    else:
        lock_px = e + p.side * e * M.LOCK_ROE / 100.0 / lev if e and lev else None
        act_px = e + p.side * e * float(p.roe_act) / 100.0 / lev if e and lev else None
    net = {} if not lad else {
        "ladder_basis": "net", "ladder_step": lad["step"] / 100.0, "roe_act": lad["trigger"] / 100.0, "lock_roe": lad["lock"] / 100.0,
        "next": ladder_next_net(p, lad, fee), "every_s": float(getattr(cfg, "ladder_every_s", 0) or 0),
        "best_net_roe": (p.side * (p.best - e) / e - 2 * fee) * lev if e and lev else None}
    return {"state": "ok", "symbol": p.symbol, "coin": coin_ko(p.symbol), "side": p.side, "side_ko": SIDE_KO.get(p.side, "?"), "qty": q,
            "entry": e, "notional": notional, "margin": notional / lev if notional is not None and lev else None, "leverage": lev,
            "stop": _f(p.stop), "stop_roe": p.roe(p.stop) / 100.0 if e else None, "stop_dist": _f(p.stop_dist),
            "stop_pnl": loss, "locked": int(p.step or 0) > 0, "step": int(p.step or 0), "best": _f(p.best),
            "best_roe": p.roe(p.best) / 100.0 if e else None, "roe_act": float(p.roe_act) / 100.0, "lock_roe": M.LOCK_ROE / 100.0,
            "first_lock_price": lock_px, "first_act_price": act_px, "next": ladder_next(p), "opened_ms": _i(p.opened_ms),
            "held_ms": now - int(p.opened_ms) if p.opened_ms else None, "signal_close_ms": _i(p.signal_close_ms),
            "signal_close": _f(p.signal_close), "last_bar_ms": _i(p.last_bar_ms), "equity_before": _f(p.equity_before),
            "stop_id": p.stop_id, "stop_id_missing": bid == "live" and not p.stop_id, **net}


# ---------------------------------------------------------------- 최근 48시간: signals with what became of them, warnings
def _vals(r: dict) -> dict:
    return {k: r.get(k) for k in ("close", "avg_rsi_30m", "avg_rsi_1h", "stop_pct", "close_ms", "liq_ok") if r.get(k) is not None}


def feed_view(rows: list, now: int) -> dict:
    """The last 48 hours, newest first: each colour change (signal row) with what became of it (진입 / 건너뜀 and the
    bot's reason / 진입 안 함 and why), entries without a signal row, ladder moves, exits, starts and the warnings (repeats
    of one warning folded into one row with their count)."""
    lo = int(now) - SIG_SPAN_MS
    recent = [r for r in rows if (_i(r.get("ts")) or 0) >= lo]
    sigs = [r for r in recent if r.get("kind") == "signal"]
    used: set = set()

    def signal_of(r: dict) -> Optional[dict]:
        t, sym, side = _i(r.get("ts")) or 0, r.get("symbol"), _i(r.get("side"))
        for s in reversed(sigs):
            st = _i(s.get("ts")) or 0
            if s.get("symbol") == sym and _i(s.get("side")) == side and st <= t < st + 30 * MIN and id(s) not in used:
                return s
        return None

    outcome: dict = {}
    folded: set = set()
    for r in recent:
        k = r.get("kind")
        if k not in ("skip", "entry", "adopted"):
            continue
        s = signal_of(r)
        if s is None:
            continue
        used.add(id(s))
        if k == "skip":
            g = skip_group(r.get("why"))
            outcome[id(s)] = {"kind": "skip", "group": g, "group_ko": SKIP_GROUPS[g][0], "tone": SKIP_GROUPS[g][1], "why": r.get("why")}
        else:
            outcome[id(s)] = {"kind": "entry", "entry": _f(r.get("entry")), "qty": _f(r.get("qty")), "stop": _f(r.get("stop")),
                              "leverage": _i(r.get("leverage")), "adopted": k == "adopted"}
        folded.add(id(r))
    items, warns = [], {}
    counts = {"signal": 0, "entered": 0, "skipped": 0, "refused": 0, "waiting": 0, "warn": 0, "exit": 0, "ladder": 0}
    for r in recent:
        k, t = r.get("kind"), _i(r.get("ts"))
        base = {"t": t, "kind": k, "symbol": r.get("symbol"), "coin": coin_ko(r.get("symbol")) if r.get("symbol") else None,
                "side": _i(r.get("side"))}
        if k == "signal":
            counts["signal"] += 1
            colour = "cyan" if r.get("to_cyan") else "purple" if r.get("to_purple") else None
            side = _i(r.get("side")) or 0
            out = outcome.get(id(r))
            if side == 0:
                stage, tone = "refused", "thin"
            elif out is None:
                stage, tone = "waiting", "thin"
            elif out["kind"] == "entry":
                stage, tone = "entered", "good"
            else:
                stage, tone = "skipped", out["tone"]
            counts[stage] += 1
            items.append({**base, "cat": "signal", "colour": colour, "colour_ko": {"cyan": "하늘색으로 바뀜", "purple": "보라색으로 바뀜"}.get(colour, "신호"),
                          "want": 1 if colour == "cyan" else -1 if colour == "purple" else side, "stage": stage, "tone": tone,
                          "why": r.get("why") or None, "outcome": out, "vals": _vals(r)})
        elif k == "skip" and id(r) not in folded:
            g = skip_group(r.get("why"))
            items.append({**base, "cat": "skip", "group": g, "group_ko": SKIP_GROUPS[g][0], "tone": SKIP_GROUPS[g][1], "why": r.get("why")})
        elif k in ("entry", "adopted") and id(r) not in folded:
            counts["entered"] += 1
            items.append({**base, "cat": "entry", "tone": "good", "entry": _f(r.get("entry")), "qty": _f(r.get("qty")),
                          "stop": _f(r.get("stop")), "leverage": _i(r.get("leverage")), "adopted": k == "adopted"})
        elif k == "exit":
            counts["exit"] += 1
            pnl = _f(r.get("pnl"))
            items.append({**base, "cat": "exit", "why": r.get("why"), "why_ko": M.EXIT_KO.get(r.get("why"), str(r.get("why") or "")),
                          "price": _f(r.get("price")), "pnl": pnl, "equity": _f(r.get("equity")), "step": _i(r.get("step")),
                          "tone": "good" if (pnl or 0) > 0 else "bad" if pnl is not None else "thin"})
        elif k == "ladder":
            counts["ladder"] += 1
            items.append({**base, "cat": "ladder", "tone": "accent", "old": _f(r.get("old")), "new": _f(r.get("new")),
                          "step": _i(r.get("step")), "best": _f(r.get("best"))})
        elif k == "start":
            bad = [str(x[1]) for x in r.get("setup") or [] if isinstance(x, (list, tuple)) and len(x) == 2 and not x[0]]
            items.append({**base, "cat": "start", "tone": "warn" if bad else "thin", "equity": _f(r.get("equity")),
                          "start_equity": _f(r.get("start_equity")), "setup_bad": bad,
                          "held": coin_ko((r.get("position") or {}).get("symbol")) if isinstance(r.get("position"), dict) else None})
        elif k in WARN_KO:
            counts["warn"] += 1
            err = str(r.get("error") or r.get("why") or r.get("result") or "")[:200]
            wk = (k, r.get("symbol"), err)
            if wk in warns:
                w = warns[wk]
                w["n"] += 1
                w["t"] = t
                continue
            ko, tone = WARN_KO[k]
            w = {**base, "cat": "warn", "tone": tone, "ko": ko, "error": err or None, "n": 1, "first_ms": t,
                 "where": r.get("where"), "detail": {kk: r.get(kk) for kk in ("old", "new", "stop", "qty", "to", "result") if r.get(kk) is not None}}
            warns[wk] = w
            items.append(w)
    items.sort(key=lambda x: x.get("t") or 0, reverse=True)
    return {"from": lo, "span_ms": SIG_SPAN_MS, "rows": items[:FEED_KEEP], "n": len(items), "counts": counts,
            "bad": sum(1 for x in items if x["cat"] == "warn" and x["tone"] == "bad")}


# ---------------------------------------------------------------- 성적: closed trades
def trades_of(rows: list, cfg: Any) -> list:
    """The closed trades, newest first: each exit row joined to its entry (or adopted) row by coin and ``opened_ms``.
    P&L = the equity change from the entry's ``equity_before`` to the exit's ``equity`` (paper: both fees), else the exit
    row's own ``pnl`` (live: None when the bot could not read the equity: 모름, never a zero)."""
    opens = {}
    for r in rows:
        if r.get("kind") in ("entry", "adopted"):
            opens[(r.get("symbol"), _i(r.get("opened_ms")))] = r
    risk = float(cfg.risk_pct) if cfg is not None else None
    by_margin = cfg is not None and float(getattr(cfg, "margin_frac", 0) or 0) > 0
    out = []
    for r in rows:
        if r.get("kind") != "exit":
            continue
        sym, om = r.get("symbol"), _i(r.get("opened_ms"))
        en = opens.get((sym, om))
        side = _i(r.get("side")) or _i((en or {}).get("side"))
        entry = _f(r.get("entry")) or _f((en or {}).get("entry"))
        qty = _f((en or {}).get("qty"))
        lev = _i((en or {}).get("leverage"))
        eq_b, eq_a = _f((en or {}).get("equity_before")), _f(r.get("equity"))
        pnl = (eq_a - eq_b) if eq_a is not None and eq_b is not None else _f(r.get("pnl"))
        px = _f(r.get("price"))
        if px is not None and entry and lev and side:
            roe = side * (px - entry) / entry * lev
        elif pnl is not None and qty and entry and lev:
            roe = pnl / (qty * entry / lev)
        else:
            roe = None
        why = (en or {}).get("why") if isinstance((en or {}).get("why"), dict) else {}
        t = _i(r.get("ts"))
        dist = _f((en or {}).get("stop_dist"))
        # R: the loss at the stop is the unit; sized by margin (owners 10-26) it is the entry's size x stop distance
        r_unit = (qty * dist) if by_margin and qty and dist else (eq_b * risk / 100.0 if eq_b and risk else None)
        out.append({"symbol": sym, "coin": coin_ko(sym), "side": side, "side_ko": SIDE_KO.get(side, "?"), "opened_ms": om, "exit_ms": t,
                    "hold_ms": (t - om) if t is not None and om is not None else None, "entry": entry, "exit": px, "stop": _f(r.get("stop")),
                    "qty": qty, "leverage": lev, "why": r.get("why"), "why_ko": M.EXIT_KO.get(r.get("why"), str(r.get("why") or "")),
                    "pnl": pnl, "pnl_src": "equity" if eq_a is not None and eq_b is not None else "row" if pnl is not None else None,
                    "win": (pnl > 0) if pnl is not None else None, "roe": roe, "equity": eq_a, "equity_before": eq_b,
                    "r": (pnl / r_unit) if pnl is not None and r_unit else None, "step": _i(r.get("step")) or 0,
                    "no_entry_row": en is None, "adopted": (en or {}).get("kind") == "adopted",
                    "signal": {k: why.get(k) for k in ("avg_rsi_30m", "avg_rsi_1h", "stop_pct", "close", "close_ms") if why.get(k) is not None}})
    out.sort(key=lambda t: t.get("exit_ms") or 0, reverse=True)
    return out


def record(trades: list) -> dict:
    """Closed trades in numbers (the ones with a known P&L; the others counted apart): n, wins, losses, win rate, P&L,
    average win / loss, the largest loss and win."""
    known = [t for t in trades if t.get("pnl") is not None]
    wins = [t["pnl"] for t in known if t["pnl"] > 0]
    loss = [t["pnl"] for t in known if t["pnl"] <= 0]
    n = len(trades)
    return {"n": n, "known": len(known), "unknown": n - len(known), "wins": len(wins), "losses": len(loss),
            "win_rate": len(wins) / len(known) if known else None, "pnl": sum(t["pnl"] for t in known) if known else None,
            "avg_win": sum(wins) / len(wins) if wins else None, "avg_loss": sum(loss) / len(loss) if loss else None,
            "worst": min(loss) if loss else None, "best": max(wins) if wins else None,
            "ladder_n": sum(1 for t in trades if (t.get("step") or 0) > 0), "small": n < SMALL_N, "small_n": SMALL_N}


def by_coin(trades: list, cfg: Any) -> list:
    """The record per coin, in the config's coin order (then any other coin traded)."""
    order = [c.symbol for c in cfg.coins] if cfg is not None else [r["symbol"] for r in BACKTEST["rows"]]
    syms = order + sorted({t["symbol"] for t in trades if t.get("symbol") and t["symbol"] not in order})
    out = []
    for s in syms:
        ts = [t for t in trades if t.get("symbol") == s]
        rec = record(ts)
        out.append({"symbol": s, "coin": coin_ko(s), **{k: rec[k] for k in ("n", "known", "unknown", "wins", "losses", "win_rate", "pnl", "worst")},
                    "small": len(ts) < SPLIT_MIN_N})
    return out


def last_setup(rows: list) -> tuple:
    """(the failed lines, the coins they turned off) of the bot's last start (mixchop Bot.start: a coin whose leverage
    could not be set is not traded until the next start)."""
    st = next((r for r in reversed(rows) if r.get("kind") == "start"), None)
    bad = [str(x[1]) for x in (st or {}).get("setup") or [] if isinstance(x, (list, tuple)) and len(x) == 2 and not x[0]]
    return bad, {t.split(":")[0].strip() for t in bad if t.split(":")[0].strip().endswith("USDT")}


def rules_view(conf: dict, off: Optional[set] = None) -> Optional[dict]:
    """The config's rules (the one the bot runs, or the repo's said so): coins and their settings (and the ones its last
    start turned off), risk, one position, the floor, the entry blocks."""
    cfg = conf.get("cfg")
    if cfg is None:
        return None
    return {"source": conf.get("source"), "path": conf.get("path") if conf.get("source") == "server" else conf.get("repo_path"),
            "mode": cfg.mode, "risk_pct": cfg.risk_pct, "equity_floor_frac": cfg.equity_floor_frac, "max_notional_usd": cfg.max_notional_usd,
            "start_equity": _f(cfg.start_equity), "taker_fee": cfg.taker_fee if cfg.mode == "paper" else None, "one_position": True,
            "lock_roe": M.LOCK_ROE / 100.0, "margin_frac": float(getattr(cfg, "margin_frac", 0) or 0),
            "ladder": ({k: v / 100.0 for k, v in cfg.ladder.items()} if getattr(cfg, "ladder", None) else None),
            "ladder_every_s": float(getattr(cfg, "ladder_every_s", 0) or 0), "plan_ko": M.plan_words(cfg),
            "coins": [{"symbol": c.symbol, "coin": coin_ko(c.symbol), "h1_buf": c.h1_buf, "sl_atr": c.sl_atr, "roe_act": c.roe_act / 100.0,
                       "leverage": c.leverage, "enabled": c.enabled, "off_at_start": c.symbol in (off or set())} for c in cfg.coins],
            "blocks": block_rules(cfg), "server_state": conf.get("server_state"), "reason_ko": conf.get("reason_ko")}


# ---------------------------------------------------------------- the two answers
def _head(bid: str, b: dict) -> dict:
    ko, unit, _m, guide = next((k, u, m, g) for x, k, u, m, g in BOTS if x == bid)
    return {"id": bid, "ko": ko, "name_ko": f"{M.NAME} {ko}", "real": bid == "live", "unit": unit, "guide": guide,
            "status": b["status"], "files": file_states(b), "start_ko": f"켜는 순서: {guide} · sudo systemctl start {unit}"}


def bot_control(bid: str, bp: dict, now: int) -> dict:
    b = load_bot(bid, bp, now)
    out = _head(bid, b)
    if b["status"]["state"] == "off":
        return out
    d = (b["st"].get("d") or {}) if b["st"].get("state") == "ok" else {}
    eq = equity_view(bid, b)
    cfg = b["conf"].get("cfg")
    if b["st"].get("state") == "ok":
        pos = position_view(bid, d, now, cfg)
    else:                                            # never "no position" from a state file that was not read
        pos = {"state": b["st"]["state"], "ko": "상태 파일을 읽지 못해 포지션을 몰라요" if b["st"]["state"] == "error" else "상태 파일이 없어 포지션을 몰라요",
               "reason_ko": b["st"].get("reason_ko"), "reason": b["st"].get("reason")}
    rows = b["lg"].get("rows") or []
    setup_bad, off = last_setup(rows)
    # 한눈에's card: today's closed trades (KST) and the last RING_N results, oldest first
    ts = trades_of(rows, cfg) if b["lg"].get("state") == "ok" else None
    d0 = L.kst_day_start(L.kst_day(now))
    today = {k: v for k, v in record([t for t in ts if (t.get("exit_ms") or 0) >= d0]).items() if k in ("n", "known", "unknown", "wins", "losses", "pnl")} \
        if ts is not None else None
    recent = [{"t": t["exit_ms"], "win": t["win"], "pnl": t["pnl"], "symbol": t["symbol"], "why_ko": t["why_ko"]} for t in ts[:RING_N]][::-1] \
        if ts is not None else None
    return {**out, "equity": eq, "today": today and {**today, "from_ms": d0}, "recent": recent, "halts": halts_view(b, eq, now), "blocks": blocks_view(cfg, now), "position": pos,
            "feed": feed_view(rows, now) if b["lg"].get("state") == "ok" else None, "setup_bad": setup_bad,
            "risk_pct": cfg.risk_pct if cfg is not None else None,
            "plan_short_ko": M.plan_words(cfg, short=True) if cfg is not None else None,
            "coins": [{"symbol": c.symbol, "coin": coin_ko(c.symbol), "enabled": c.enabled and c.symbol not in off} for c in cfg.coins] if cfg is not None else []}


def bot_perf(bid: str, bp: dict, now: int) -> dict:
    b = load_bot(bid, bp, now)
    setup_bad, off = last_setup(b["lg"].get("rows") or [])
    out = {**_head(bid, b), "rules": rules_view(b["conf"], off), "setup_bad": setup_bad}
    if b["status"]["state"] == "off" or b["lg"].get("state") != "ok":
        return out
    cfg = b["conf"].get("cfg")
    ts = trades_of(b["lg"]["rows"], cfg)
    return {**out, "record": record(ts), "coins": by_coin(ts, cfg), "trades": ts[:TRADES_KEEP], "equity": equity_view(bid, b)}


def control(p: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/mix (module docstring)."""
    p = p or paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return {"now_ms": now, "name_ko": M.NAME, "bots": [bot_control(bid, p[bid], now) for bid, *_r in BOTS],
            "span_ms": SIG_SPAN_MS, "stale_ms": STALE_MS}


def analysis(p: dict, now: int) -> dict:
    """성적's 손실 분석 part (owners 10-25 night, paperbot/mixcheck.py site_view): the live trades' loss cards, the luck band
    against the 5-year replay, the replay's numbers next to the design's, the last morning check. Its own failure is said,
    never the page's."""
    try:
        from ... import mixcheck as MC                   # (mixcheck reads the bots through this module: imported here)
        return {"state": "ok", **MC.site_view(p, now)}
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "ko": "손실 분석을 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:300]}


def perf(p: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/mixperf (module docstring)."""
    p = p or paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return {"now_ms": now, "name_ko": M.NAME, "bots": [bot_perf(bid, p[bid], now) for bid, *_r in BOTS], "backtest": BACKTEST,
            "small_n": SMALL_N, "split_min_n": SPLIT_MIN_N, "analysis": analysis(p, now)}


def register(app, ctx) -> dict:
    from ..app import json_finite

    def key(name: str, p: dict) -> str:
        return name + ":" + json.dumps(p, sort_keys=True)

    @app.get("/api/v4/livebots/mix")
    def get_livebots_mix():
        """실거래 › 믹스 관제: the live bot and its paper twin now: running, equity and floor, halts, entry blocks, the
        position with its ladder, the last 48 hours of signals and warnings (read-only, 5 s cache)."""
        p = paths()
        return L._cached(key("mix", p), lambda: json_finite(control(p)))

    @app.get("/api/v4/livebots/mixperf")
    def get_livebots_mixperf():
        """실거래 › 믹스 성적: the closed trades of each bot, by coin, next to the design's 5-year backtest, and the rules
        (read-only, 5 s cache)."""
        p = paths()
        return L._cached(key("mixperf", p), lambda: json_finite(perf(p)))

    return {"routes": ["/api/v4/livebots/mix", "/api/v4/livebots/mixperf"], "paths": paths}
