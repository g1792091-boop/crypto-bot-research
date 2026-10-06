"""Paper v4 integration gate (plan P13): every paperbot module imports (no import cycle), the grep gate on owner-facing
text, the owners' cross-package contracts (one verdict method text, the frozen DeepSeek texts, the Telegram counter
file read read-only), shadow200's pins, GET / with a session serves the v4 shell, and one end-to-end fake-feed run of
all 331 accounts through the live runner (live3.Runner3) across a 4h boundary with a restart midway: the engines
after the restart, the nightly replay (daily3: the start day's silent note, then parity 331/331 on day 2), the
DeepSeek job's records for paperbot/dscheck.py, and the checkpoint rehearsal (accounts_in_snapshot == 331, no
zero-rate account)."""

import ast
import concurrent.futures
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

import paperbot
from paperbot import Brackets, Signal
from paperbot.accounts import AccountBook, HeldEngine
from paperbot.aggregate import TF_MS
from paperbot.config import DS200_TFS, V3_SYMBOLS, V4_ACCOUNTS, V4_GROUP_ACCOUNTS, v4_account_defs, v4_settings
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "paperbot"
VIEW_PKG = "paperbot.strategy_view_defs."
MIN = 60_000
FIVE = 300_000
HOUR = 3_600_000
DAY = 86_400_000


def _modules() -> list[str]:
    import pkgutil
    return sorted(m.name for m in pkgutil.walk_packages(paperbot.__path__, "paperbot."))


# ====================================================================== import smoke
def _import_alone(mod: str) -> tuple[str, str]:
    r = subprocess.run([sys.executable, "-c", f"import {mod}"], capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)})
    return mod, ("" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["?"])[-1])


def test_every_paperbot_module_imports_first_in_its_own_process():
    """Each module is the FIRST import of a fresh interpreter, so an import cycle (e.g. roster3 -> actions ->
    extra_accounts -> rooms_db -> roster3) fails here whichever module of the cycle a service starts from."""
    mods = [m for m in _modules() if not m.startswith(VIEW_PKG)]
    assert "paperbot.agents.roster3" in mods and "paperbot.dscheck" in mods and len(mods) > 100
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        bad = [(m, e) for m, e in ex.map(_import_alone, mods) if e]
    assert not bad, bad


def test_every_strategy_view_definition_imports_after_the_vendored_library():
    """The view definitions import the locked vendor code that ``sweepsig.lib()`` puts on the path (as
    strategy_views loads them): all import, the 36 and the 45 v4 views (44 DeepSeek + REEL_H1) load."""
    code = ("import importlib, pkgutil, paperbot\n"
            "from paperbot import sweepsig, strategy_views as V\n"
            "sweepsig.lib()\n"
            f"mods = [m.name for m in pkgutil.walk_packages(paperbot.__path__, 'paperbot.') if m.name.startswith({VIEW_PKG!r})]\n"
            "bad = []\n"
            "for m in mods:\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "    except Exception as e:\n"
            "        bad.append((m, repr(e)[:200]))\n"
            "print(len(mods), len(V.views()), len(V.v4_views()), bad, V.v4_missing())\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=str(ROOT),
                       env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0, r.stderr[-2000:]
    n, n36, n4, bad, missing = r.stdout.strip().split(" ", 4)
    assert int(n) >= 81 and int(n36) == 36 and int(n4) == 45 and bad.startswith("[]") and missing.endswith("{}"), \
        r.stdout


# ====================================================================== grep gate
STALE = re.compile(r"156|144개|108개|72명|5분봉.{0,20}(뺐|제외)|2,000개|FDR 10%|paper v3 started|2026-10-26|규칙 변경 1")
# (path prefix, text the line must contain ("" = the whole file), why it may stay)
ALLOW = (
    ("", "2,000개 조합", "the research library A/B's 2,000 combinations (history of the search, not a bot count)"),
    ("", "최근 2,000건까지", "the trade list's own row limit"),
    ("", "규칙 변경 1 (2026-10-04)", "the title of the frozen v3 document docs/paper-v3-rules-change-1.md"),
    ("docs/server-setup-v3.md", "", "the v3 server guide: the v3 run's history, kept as it was"),
    ("docs/signal-recording.md", "재계산 일치 149/156", "the 2026-10-04 early-kline finding (v3 history)"),
    ("docs/signal-recording.md", "새 계좌 156개가 $5,000로 시작", "the 2026-10-04 v3 restart (history)"),
    ("docs/debate-room.md", "합성 자료(156계좌", "a measurement taken on the v3 synthetic data"),
    ("docs/obsidian-vault.md", "리허설 데이터 156계좌", "a measurement taken on the v3 rehearsal data"),
    ("docs/levrule-eval-v4.md", "v3 실행(156개 계좌)", "the v3 run (history)"),
    ("docs/levrule-eval-v4.md", "156개 계좌만 있는 자료", "owners' D12 population: core 144 + the 12 original flips"),
    ("docs/paper-v4-rules.md", "v3 실행(156개 계좌)", "the v3 run (history)"),
    ("docs/paper-v4-rules.md", "변경 1의 \"5분봉 제외\"는 매매법 36개에 그대로", "change-1's 5m rule, still the 36's"),
    ("docs/paper-v4-verdict.md", "봇 2,000개로", "REHEARSAL_BOTS (the weekly rehearsal), not the verdict's N_BOTS"),
    ("docs/agent-rooms.md", "판정 계좌 108개 = 36 × 15분·30분·1시간", "the core group's judged count (36 x 3)"),
    ("paperbot/obsidian_vault/", "--pb-overlay-rgb: 156, 160, 176", "a colour value"),
    # luck-calc / regime5y / size5y (owners' branch 855ecb8): study numbers, not the v3 bot or account counts
    ("paperbot/dash/more/luck.py", "라이브러리 2,000개", "luck-calc's row: the research library's 2,000 combinations"),
    ("paperbot/dash/static/v4/INVENTORY.md", "라이브러리 2,000개, 딥시크 342개", "luck-calc's row names (the library)"),
    ("docs/regime5y.md", "5년 156건", "one regime cell's 5-year trade count"),
    ("docs/size5y.md", "144개를 다 더한 것", "the 5-year studies' 144 cells (36 strategies x 4 timeframes)"),
)


def _docstring_ids(tree) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                out.add(id(b[0].value))
    return out


def _py_literal_lines(path: Path):
    """(line, text) of every line of every string literal (f-string parts included) that is not a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            for ln in node.value.splitlines():
                yield node.lineno, ln


def _text_lines(path: Path):
    for i, ln in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        yield i, ln


def _scope():
    """(relative path, line iterator) of the gate's scope: paperbot/**/*.py string literals (extras.py and the
    obsidian_* modules among them), paperbot/dash/static/** (v4 included), the Obsidian vault's own files, and
    docs/*.md without a .sha256 (the hashed, frozen documents are never edited)."""
    for p in sorted(PKG.rglob("*.py")):
        yield p, _py_literal_lines(p)
    for base in (PKG / "dash" / "static", PKG / "obsidian_vault"):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in (".js", ".mjs", ".html", ".css", ".json", ".md", ".txt", ".svg"):
                yield p, _text_lines(p)
    for p in sorted((ROOT / "docs").glob("*.md")):
        if not p.with_suffix(".sha256").exists():
            yield p, _text_lines(p)


def test_grep_gate_no_stale_v3_numbers_in_owner_facing_text():
    scanned, hits = set(), []
    for p, lines in _scope():
        rel = p.relative_to(ROOT).as_posix()
        scanned.add(rel)
        for i, ln in lines:
            if not STALE.search(ln):
                continue
            if any(rel.startswith(pre) and (not need or need in ln) for pre, need, _why in ALLOW):
                continue
            hits.append(f"{rel}:{i}: {ln.strip()[:160]}")
    for must in ("paperbot/extras.py", "paperbot/obsidian_notes.py", "paperbot/dash/app.py",
                 "paperbot/dash/static/v4/index.html", "docs/server-setup-v4.md"):
        assert must in scanned, must
    # frozen and hashed: out of the gate (the v4 rules passed this gate before their .sha256 was written)
    for frozen in ("docs/paper-v3-rules.md", "docs/paper-v4-rules.md", "docs/paper-v4-verdict.md"):
        assert frozen not in scanned, frozen
    assert not hits, "\n".join(hits)


def test_grep_gate_catches_a_stale_line_and_its_allowlist_is_narrow():
    assert STALE.search("paper v3 started: 156 accounts") and STALE.search("5분봉은 뺐음")
    assert STALE.search("FDR 10%로 판정") and STALE.search("판정 계좌 108개") and STALE.search("봇 2,000개")
    assert not any(pre == "" and need == "" for pre, need, _ in ALLOW)            # nothing allowed everywhere


def test_the_v4_rules_documents_have_no_open_todo():
    for name in ("paper-v4-rules.md", "paper-v4-verdict.md", "levrule-eval-v4.md"):
        assert "TODO" not in (ROOT / "docs" / name).read_text(encoding="utf-8"), name


# ====================================================================== cross-package contracts
def test_one_verdict_method_text_for_the_dashboard_and_the_agents():
    from paperbot import checkpoint as CP
    from paperbot.agents import facts as F
    from paperbot.dash import app as A
    m = A.verdict_method()
    assert m["method_ko"] == CP.method_ko() == F.facts()["method_ko"]
    assert m["n_bots"] == CP.N_BOTS and m["family_alpha"] == CP.FAMILY_ALPHA


def test_the_frozen_deepseek_texts_have_one_source():
    from paperbot import dscheck, live3, notify, sigservice
    from paperbot.agents import triggers
    text = sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=1_790_000_000_000, tfs="15m, 1h")
    assert text.startswith(triggers.DS_TIMEOUT_FRAGMENT) and triggers.DS_TIMEOUT_FRAGMENT.endswith("timed out after")
    assert ("ds_signal_timeout", "WARN", triggers.DS_TIMEOUT_FRAGMENT) in triggers.INCIDENT_ALERTS
    for mod in (notify, dscheck):
        assert mod.DS_TIMEOUT_RE == sigservice.DS_TIMEOUT_RE and re.match(mod.DS_TIMEOUT_RE, text)
    assert dscheck.DS_FAILED_RE == sigservice.DS_FAILED_RE and dscheck.DS_RUN_KEY == live3.DS_RUN_KEY
    assert set(dscheck.EXCUSED_RUN) == {"timeout", "failed", "refused", "incomplete"}


def test_group_prefixes_name_a_group_never_an_account():
    """"[ds200] " / "[reel] " head the v4 groups' frozen texts: the dashboard keeps them among the operations alerts
    (never an account line), the agents never read an account from them, and both pages word them as a group."""
    from paperbot import sigservice
    from paperbot.agents import triggers
    from paperbot.dash import app as A
    texts = [sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=1, tfs="15m"),
             sigservice.DS_ERROR_TEXT.format(tf="15m", symbol="ETHUSDT", error="x"),
             sigservice.REEL_FAILED_TEXT.format(boundary=1, error="x"),
             sigservice.REFUSED_TEXT.format(group="reel", why="pin")]
    for t in texts:
        assert t.startswith(("[ds200] ", "[reel] ")) and A.account_line(t) is None and triggers._alert_account(t) is None
    assert A.account_line("[F9_FVG@15m] LIQUIDATED ETHUSDT 30x lost margin 1.0") == "F9_FVG@15m"
    v4 = (PKG / "dash" / "static" / "v4" / "core" / "alerts.js").read_text(encoding="utf-8")
    old = (PKG / "dash" / "static" / "app.js").read_text(encoding="utf-8")
    assert "딥시크 그룹: " in v4 and "5분봉 그룹: " in v4 and "딥시크 그룹: " in old
    guide = (ROOT / "docs" / "server-setup-v4.md").read_text(encoding="utf-8")
    assert "`[ds200] …`·`[reel] …`로 시작하는 줄은 **그룹** 알림" in guide


def test_the_telegram_counter_file_is_read_read_only(tmp_path, monkeypatch):
    from paperbot import notify
    from paperbot.dash import app as A
    assert os.path.basename(notify.TG_SENDS_DB) == A.TG_SENDS_FILE
    assert os.path.dirname(notify.TG_SENDS_DB) == "/var/lib/paperbot"             # beside paper3.db
    path = str(tmp_path / A.TG_SENDS_FILE)
    now = int(time.time() * 1000)
    assert notify.count_send("INFO", path=path) is not False
    paper = sqlite3.connect(":memory:")                 # paper3.db without the table: the counter file is read
    seen = []
    real = A.sqlite3.connect
    monkeypatch.setattr(A.sqlite3, "connect", lambda *a, **kw: seen.append((a, kw)) or real(*a, **kw))
    v = A.telegram_counts(paper, now, path)
    assert v == {"today": 1, "week": 1}
    assert seen and all("mode=ro" in str(a[0]) and kw.get("uri") for a, kw in seen)


def test_shadow200_pins_hold():
    from paperbot import shadow200
    pins = shadow200.verify_pins()
    assert set(pins) >= {"lib_c", "prereg0", "forward"}


def test_get_root_with_a_session_serves_the_v4_shell(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    db = str(tmp_path / "p.db")
    Store3(db).close()
    c = TestClient(create_app(db, hash_password("pw-integration"), b"s" * 32))
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].startswith("/login")
    assert c.post("/api/login", json={"password": "pw-integration"}).status_code == 200
    r = c.get("/")
    v4 = (PKG / "dash" / "static" / "v4" / "index.html").read_text(encoding="utf-8")
    assert r.status_code == 200 and r.text == v4 and "<title>Paper v4</title>" in r.text
    old = c.get("/v3")
    assert old.status_code == 200 and old.text != v4


# ====================================================================== end to end: one fake-feed run of the 331
SYMS = tuple(V3_SYMBOLS)
S4 = v4_settings()
BR = {s: Brackets.example() for s in SYMS}


def _core_names() -> list[str]:
    from paperbot.strategy_view_defs import NAMES
    assert len(NAMES) == 36
    return list(NAMES)


def _steps(t0: int, n: int, seed: int = 11) -> list:
    from paperbot import Bar
    rng = np.random.default_rng(seed)
    px = {s: 100.0 for s in SYMS}
    out = []
    for i in range(n):
        t = t0 + i * MIN
        bars = {}
        for s in SYMS:
            o = px[s]
            c = o * np.exp(rng.normal(0, 0.0015))
            h = max(o, c) * (1 + abs(rng.normal(0, 0.0007)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.0007)))
            bars[s] = Bar(s, t, t + MIN - 1, o, h, lo, c, o, h, lo, c, volume=10.0)
            px[s] = c
        fund = {s: 0.0001 for s in SYMS} if t % (8 * HOUR) == 0 else {}
        out.append((t, bars, fund))
    return out


def _reel_levels(five: list, lookback: int) -> dict:
    from paperbot.reel_engine import upper_band
    closes = [b[3] for b in five[-20:]]
    atr = float(np.mean([b[1] - b[2] for b in five[-14:]]))
    swing = min(b[2] for b in five[-lookback:])
    return {"side": 1, "bar_open": None, "atr14": atr, "swing_low": swing, "stop": swing - 0.05 * atr,
            "up_band": upper_band(closes), "closes": closes[1:]}


class FeedService:
    """The live service's interface (due / due_5m / due_ds / complete / add_5m / compute / compute_5m / compute_ds)
    with made-up signals of every group, shaped as sigservice logs and submits them (core rows rebuilt by
    daily3.make_signal; DeepSeek with a logged stop distance; the reel and the 5m flips with reel levels and the
    reel engine's contract). The draws depend only on (boundary, timeframe, group), so a restart changes nothing.
    ``force``: 5m boundaries where the reel fires on BTC (a position open across 00:00 and across the restart)."""

    def __init__(self, defs, cur: dict, p: float = 0.12, force=()):
        self.by: dict = {}
        for d in defs:
            self.by.setdefault((d["kind"], d["timeframe"]), []).append(d["strategy"])
        self.cur, self.p, self.force = cur, p, set(force)
        self.five = {s: [] for s in SYMS}
        self.last: dict = {}
        self.refused: dict = {}
        self.ds_timeout_s = 60.0

    def _rng(self, boundary: int, tf: str, group: str):
        return np.random.default_rng([boundary // MIN, TF_MS[tf] // MIN, {"core": 1, "ds": 2, "5m": 3}[group]])

    def add_5m(self, b):
        self.five[b.symbol].append((b.open, b.high, b.low, b.close))
        self.last[b.symbol] = b.open_time + FIVE

    def complete(self, boundary):
        return all(self.last.get(s) == boundary for s in SYMS)

    def due(self, boundary):
        return [tf for tf in ("15m", "30m", "1h", "4h") if boundary % TF_MS[tf] == 0]

    def due_5m(self, boundary):
        return True

    def due_ds(self, boundary):
        return [tf for tf in DS200_TFS if boundary % TF_MS[tf] == 0]

    def _row(self, b, tf, name, s, side, atr):
        return {"bar_close": b, "timeframe": tf, "strategy": name, "symbol": s, "side": side, "atr": atr,
                "ref_price": self.cur[s], "ref_time": b + 9000, "delay_ms": 9000, "status": "SUBMITTED"}

    def compute(self, boundary, tf, now_ms, prices):
        from paperbot.daily3 import make_signal
        rng = self._rng(boundary, tf, "core")
        rows, subs = [], []
        for kind in ("strategy", "random"):
            for name in self.by.get((kind, tf), []):
                if rng.random() >= self.p:
                    continue
                s = SYMS[int(rng.integers(len(SYMS)))]
                row = self._row(boundary, tf, name, s, 1 if rng.random() < 0.5 else -1, 1.0)
                rows.append(row)
                subs.append((f"{name}@{tf}", make_signal(row)))
        return rows, subs, []

    def compute_ds(self, boundary, tf, now_ms, prices):
        rng = self._rng(boundary, tf, "ds")
        rows, subs = [], []
        for name in self.by.get(("ds200", tf), []):
            if rng.random() >= self.p:
                continue
            coins = [s for s in SYMS if not (name == "F14_SMT" and s == "BTCUSDT")]
            s = coins[int(rng.integers(len(coins)))]
            side = 1 if rng.random() < 0.5 else -1
            row = self._row(boundary, tf, name, s, side, 1.0)
            dist = 1.3 * row["atr"] + 0.013
            row["data"] = {"close": self.cur[s], "group": "ds200", "stop_dist": dist}
            rows.append(row)
            subs.append((f"{name}@{tf}", Signal(
                ts=boundary - 1, symbol=s, timeframe=tf, strategy_id=name, side=side, stop_price=0.0, tier="best",
                atr=row["atr"], meta={"stop_dist": dist, "ref_price": row["ref_price"], "ref_time": row["ref_time"],
                                      "delay_ms": row["delay_ms"], "account": f"{name}@{tf}", "ctx": {}})))
        return rows, subs, [{"symbol": s, "ready": True} for s in SYMS]

    def compute_5m(self, boundary, now_ms, prices):
        if len(self.five["BTCUSDT"]) < 20:
            return [], [], []
        rng = self._rng(boundary, "5m", "5m")
        rows, subs = [], []
        for kind, look in (("reel", 6), ("random", 12)):
            for name in self.by.get((kind, "5m"), []):
                forced = kind == "reel" and boundary in self.force
                if rng.random() >= self.p and not forced:
                    continue
                s = "BTCUSDT" if forced else SYMS[int(rng.integers(len(SYMS)))]
                lv = _reel_levels(self.five[s], look)
                row = self._row(boundary, "5m", name, s, 1, lv["atr14"])
                row["data"] = {"close": self.five[s][-1][3], "group": "reel" if kind == "reel" else "flip",
                               "exits": "reel", "reel": lv}
                rows.append(row)
                subs.append((f"{name}@5m", Signal(
                    ts=boundary - 1, symbol=s, timeframe="5m", strategy_id=name, side=1, stop_price=lv["stop"],
                    tier="best", tp_price=lv["up_band"], atr=row["atr"],
                    meta={"ref_price": row["ref_price"], "ref_time": row["ref_time"], "delay_ms": row["delay_ms"],
                          "account": f"{name}@5m", "reel": lv})))
        return rows, subs, []


class _Rest:
    def __init__(self, now):
        self.now = now

    def server_time(self):
        return self.now


@pytest.fixture(scope="module")
def v4_run(tmp_path_factory):
    """Day 1 (D1): the run starts at 20:00 UTC; day 2 (D2): a full day with a live3 restart at 11:50 UTC (the 4h
    boundary of 12:00 comes after it); the feed runs on to D3 01:00 so the D3 00:00 snapshot exists. All in the
    past (the checkpoint rehearsal judges only past days)."""
    from paperbot.live3 import Runner3, start_extras
    tmp = tmp_path_factory.mktemp("v4run")
    path = str(tmp / "paper3.db")
    today = int(time.time() * 1000) // DAY * DAY
    d1 = today - 3 * DAY
    d2, d3 = d1 + DAY, d1 + 2 * DAY
    t0 = d1 + 20 * HOUR
    restart = d2 + 12 * HOUR - 10 * MIN
    defs = v4_account_defs(_core_names())
    assert len(defs) == V4_ACCOUNTS == 331
    steps = _steps(t0, (d3 + HOUR - t0) // MIN)
    cur: dict = {}
    clock = {"t": t0}
    force = set(range(d2 - 20 * MIN, d2, FIVE)) | set(range(restart - 20 * MIN, restart + FIVE, FIVE))
    svc = FeedService(defs, cur, force=force)

    def feed(part):
        for st in part:
            cur.update({s: b.close for s, b in st[1].items()})
            clock["t"] = st[0] + MIN + 9_000
            yield st

    store = Store3(path)
    note = ListNotifier()
    book = AccountBook(S4, BR, store, note)
    book.open_accounts(defs, t0)
    store.commit()
    run = Runner3(book, svc, store, note, list(SYMS), lambda: clock["t"], lambda: dict(cur))
    run.process(feed([s for s in steps if s[0] < restart]))
    before = {aid: (e.position.entry_price, e.position.stop_price) for aid, e in book.engines.items()
              if e.position is not None}
    pending = sum(len(e.pending) for e in book.engines.values())
    store.close()
    # the restart: a new process opens the same database and loads every engine from its saved state
    store = Store3(path)
    note2 = ListNotifier()
    _ext, make_of = start_extras(store, note2, path, S4)
    book = AccountBook(S4, BR, store, note2)
    assert book.load(make_of=make_of)
    engines = dict(book.engines)
    after = {aid: (e.position.entry_price, e.position.stop_price) for aid, e in book.engines.items()
             if e.position is not None}
    run = Runner3(book, svc, store, note2, list(SYMS), lambda: clock["t"], lambda: dict(cur))
    run.process(feed([s for s in steps if s[0] >= restart]))
    store.commit()
    info = {"d1": d1, "d2": d2, "d3": d3, "t0": t0, "restart": restart, "before": before, "after": after,
            "pending": pending, "engines": engines, "notes": note.messages + note2.messages, "today": today}
    yield path, store, steps, info
    store.close()


def test_e2e_restart_keeps_all_331_engines_and_their_positions(v4_run):
    from paperbot.engine import PaperEngine
    from paperbot.reel_engine import ReelEngine
    _path, store, _steps_, info = v4_run
    eng = info["engines"]
    assert len(eng) == 331 and not [a for a, e in eng.items() if isinstance(e, HeldEngine)]        # held = 0
    assert all(isinstance(e, PaperEngine) for e in eng.values())
    reel = sorted(a for a, e in eng.items() if type(e) is ReelEngine)
    # the reel and the three 5m coin flips use the reel's own exits (owners' D2 (ii) and D4: config.v4_exits)
    assert reel == ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m", "REEL_H1@5m"]
    assert sum(1 for e in eng.values() if type(e) is PaperEngine) == 327
    # positions (the reel's among them) and pending signals survive the restart exactly
    assert info["before"] == info["after"] and len(info["after"]) >= 10 and info["pending"] > 0
    assert len({a.split("@")[1] for a in info["after"]}) >= 4
    assert any(type(eng[a]) is ReelEngine for a in info["after"])          # a reel-exit position crosses it too
    crit = [m for m in info["notes"] if m[0] == "CRITICAL"]
    assert not crit, crit[:3]
    held = store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE '%held%'").fetchone()[0]
    assert held == 0
    groups = dict(store.conn.execute("SELECT json_extract(data, '$.group'), COUNT(*) FROM accounts GROUP BY 1"))
    assert groups == V4_GROUP_ACCOUNTS == {"core": 144, "ds200": 171, "reel": 1, "flip": 15}


def test_e2e_every_deepseek_boundary_is_in_the_jobs_record(v4_run):
    """dscheck's contract: with a record of the day, every DeepSeek boundary must be in it (a missing one is a
    failure); the restart midway loses none (the second runner reloads the day's record)."""
    from paperbot import dscheck
    _path, store, _steps_, info = v4_run
    d2 = info["d2"]
    rec = dscheck.run_record(store.conn, d2, DS200_TFS)
    want = {(tf, b) for tf in DS200_TFS for b in range(d2 + TF_MS[tf], d2 + DAY + 1, TF_MS[tf])}
    assert rec is not None and set(rec) == want
    assert {e["s"] for e in rec.values()} == {"ran"} and all(len(e["ok"]) == 6 for e in rec.values())
    assert (("4h", d2 + 12 * HOUR) in rec) and info["restart"] < d2 + 12 * HOUR


def _night(store, steps, day: str, now: int, tmp: Path, monkeypatch) -> dict:
    from paperbot import daily3 as D
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [s for s in steps if a <= s[0] < b])
    out = sqlite3.connect(str(tmp / f"daily-{day}.db"))
    out.executescript(D.SCHEMA)
    rep = D.run_day(store.conn, out, _Rest(now), S4, BR, {}, day)
    out.close()
    return rep


def test_e2e_nightly_replay_start_day_note_then_331_of_331(v4_run, tmp_path, monkeypatch):
    from paperbot import checkpoint as ck
    from paperbot import daily3 as D
    _path, store, steps, info = v4_run
    now = info["d3"] + 2 * HOUR
    rep1 = _night(store, steps, ck.day_str(info["d1"]), now, tmp_path, monkeypatch)
    assert rep1["start_day"] == {"run_start": info["t0"], "before_run": False} and isinstance(rep1["parity"], str)
    msgs = D.notify_report(rep1, ListNotifier(), trades_day=0)
    assert [m[0] for m in msgs] == ["INFO"] and "\n시작한 날: 재계산 없음 (" in msgs[0][1]
    rep2 = _night(store, steps, ck.day_str(info["d2"]), now, tmp_path, monkeypatch)
    par = rep2["parity"]
    assert "start_day" not in rep2 and isinstance(par, dict), par
    assert par["accounts"] == 331 and par["mismatched_accounts"] == 0, par
    assert {g: (x["accounts"], x["ok"]) for g, x in par["groups"].items()} == \
        {"core": (144, 144), "ds200": (171, 171), "reel": (1, 1), "flip": (15, 15)}
    assert all(rep2["trades"]["groups"][g] > 0 for g in ("core", "ds200", "reel", "flip")), rep2["trades"]
    text = D.notify_report(rep2, ListNotifier())[0][1]
    assert "재계산 일치 331/331 (매매법 144/144 · 딥시크 171/171 · 5분 단타 1/1 · 동전 15/15)" in text


def test_e2e_checkpoint_rehearsal_sees_all_331_and_no_zero_rate(v4_run, tmp_path, monkeypatch):
    import paperbot.live as live
    from paperbot import checkpoint as ck
    from paperbot import checkpoint_preview as pv
    path, store, steps, info = v4_run
    store.commit()
    by_ts = {t: (bars, fund) for t, bars, fund in steps}

    class Minutes:
        def __init__(self, rest, cache):
            self.fetched_days = 0

        def load(self, lo, hi):
            m = ck.empty_minutes(lo, hi, V3_SYMBOLS)
            for i, t in enumerate(m.ts):
                st = by_ts.get(int(t))
                if st is None:
                    continue
                for k, s in enumerate(V3_SYMBOLS):
                    b = st[0][s]
                    m.o[i, k], m.h[i, k], m.l[i, k], m.c[i, k] = b.open, b.high, b.low, b.close
                    m.mo[i, k], m.mh[i, k], m.ml[i, k], m.mc[i, k] = b.open, b.high, b.low, b.close
                    if s in st[1]:
                        m.fr[i, k] = st[1][s]
            return m

    class Rest:
        def exchange_info(self, symbols):
            return {s: {"qty_step": 0.001, "min_notional": 5.0} for s in V3_SYMBOLS}

    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(live, "_notifier", lambda: pytest.fail("the rehearsal built a notifier"))
    monkeypatch.setattr(live, "_rest", Rest)
    monkeypatch.setattr(live, "load_brackets", lambda *a: (BR, "test"))
    monkeypatch.setattr(ck, "BinanceMinutes", Minutes)
    monkeypatch.setattr(pv, "REAL_OUT", str(tmp_path / "lib" / "checkpoint.db"))
    out, summ = str(tmp_path / "preview.db"), str(tmp_path / "preview.json")
    code = pv.main(["--db", path, "--out", out, "--as-of", ck.day_str(info["d3"]), "--bots", "20",
                    "--min-trades", "1", "--summary", summ])
    s = json.loads(Path(summ).read_text(encoding="utf-8"))
    assert code == 0 and s["status"] == "ok", s.get("error")
    assert s["accounts_in_snapshot"] == 331 and s["accounts_expected"] == 331 and not s["missing_accounts"]
    assert s["zero_rate_accounts"] == [], s["zero_rate_accounts"][:10]
    assert s["tested"] > 0 and s["rate_min"] > 0
    assert {g: (x["expected"], x["found"]) for g, x in s["by_group"].items() if x["expected"]} == \
        {"core": (144, 144), "ds200": (171, 171), "reel": (1, 1), "flip": (15, 15)}
