"""Wave 2 part C (dashboard only): 오늘의 회의 결론 보고판 (/api/v4/brief/meetings, dash/more/brief.py), the strategy
page's 5년 시험 vs 지금 vs 동전 봇 table (/api/v4/vs5y/<strategy>, dash/more/vs5y.py), the per-strategy pixel characters
and the 대표실 window that follows Korea time (core/figure.js). Synthetic databases only; read-only routes behind the
login; the page side's honesty rules (no typing effect, 회의 중 from the office's running list only, DeepSeek counts
only, 참고 + caption on the comparison, no colour literals)."""

import json
import os
import re
import shutil
import subprocess

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import brief as B  # noqa: E402
from paperbot.dash.more import story as S  # noqa: E402
from paperbot.dash.more import vs5y as V  # noqa: E402
from paperbot.models import TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
PW = "brief horse battery"
SECRET = b"w" * 32
DAY0 = "2026-10-08"
T0 = S.day_start(DAY0)                        # 00:00 KST
NOW = T0 + 15 * HOUR                          # 15:00 KST


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- agents3.db: today's meetings
def _round(c, room, trigger, started, status="running", ended=None, decision=None):
    cur = c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision, calls, tokens) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (room, trigger, "{}", started, ended, status,
                                                   json.dumps(decision, ensure_ascii=False) if decision else None, 1, 10))
    c.commit()
    return int(cur.lastrowid)


def _agents(path):
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=T0 - 3 * DAY)
    # yesterday: not today's board
    _round(c, "team:market", "evening", T0 - 2 * HOUR, "no_action", ended=T0 - HOUR, decision={"summary_ko": "🧾 어제 저녁"})
    # started yesterday, ended today: finished today
    m0 = _round(c, "team:review", "ranking", T0 - 10 * MIN, "done", ended=T0 + 5 * MIN, decision={"summary_ko": "🧾 결정: 자정 넘어 끝남"})
    m1 = _round(c, "team:market", "morning", T0 + 8 * HOUR, "done", ended=T0 + 8 * HOUR + 6 * MIN,
                decision={"summary_ko": "🧾 아침 회의: 큰 변화 없음\n둘째 줄"})
    R.post(c, "team:market", m1, "morning", "team_lead", None, "summary", "요약",
           {"answer": {"summary": ["박스권이라 할 일 없음.", "다음 회의에서 다시."], "open_disagreement": ""}}, ts=T0 + 8 * HOUR + 5 * MIN)
    m2 = _round(c, "strat:S5_DONCHIAN_MFI", "loss_cluster", T0 + 10 * HOUR, "done", ended=T0 + 10 * HOUR + 9 * MIN,
                decision={"summary_ko": "🧾 결정: 가설 기록"})
    R.post(c, "strat:S5_DONCHIAN_MFI", m2, "loss_cluster", "team_lead", None, "summary", "요약",
           {"answer": {"summary": ["<b>태그</b>는 글자 그대로 · 손절 2건은 추세 반대."], "open_disagreement": "3건은 너무 적음"}},
           ts=T0 + 10 * HOUR + 8 * MIN)
    _round(c, "team:lab", "lab", T0 + 13 * HOUR, "no_action", ended=T0 + 13 * HOUR + 7 * MIN, decision={"summary_ko": "🧾 연구 끝"})
    _round(c, "team:risk", "loss_cluster", T0 + 14 * HOUR, "failed", ended=T0 + 14 * HOUR + 1 * MIN)
    _round(c, "team:review", "ranking", NOW - 4 * MIN)                       # running: never counted as finished
    c.close()
    return m0, m1, m2


@pytest.fixture
def adb(tmp_path):
    path = str(tmp_path / "a.db")
    ids = _agents(path)
    return path, ids


def test_brief_counts_today_and_shows_the_newest_three_conclusions(adb):
    path, (m0, m1, m2) = adb
    c = R.open_agents(path)
    try:
        d = B.meetings_brief(c, NOW)
    finally:
        c.close()
    assert d["ready"] and d["day"] == DAY0
    assert d["n"] == 5                                   # started today: morning, loss, lab, risk, running review
    assert d["finished"] == 5                            # ended today: the one past midnight too, never the running one
    assert d["decided"] == 3 and d["split"] == 1
    lines = d["lines"]
    assert [x["status"] for x in lines] == ["failed", "no_action", "done"] and len(lines) == 3 and d["more"] == 2
    assert lines[2]["round_id"] == m2 and lines[2]["from"] == "lead"
    assert lines[2]["line"] == "<b>태그</b>는 글자 그대로 · 손절 2건은 추세 반대."     # the stored line, as text
    assert lines[2]["dis"] == "3건은 너무 적음" and lines[2]["lead_n"] == 1
    assert lines[1]["from"] == "code" and lines[1]["line"] == "연구 끝"
    assert lines[0]["from"] == "kind" and lines[0]["line"] == lines[0]["trigger_ko"]
    full = B.meetings_brief(R.open_agents(path), NOW, show=10)
    by = {x["round_id"]: x for x in full["lines"]}
    assert by[m1]["line"] == "박스권이라 할 일 없음." and by[m1]["lead_n"] == 2 and by[m1]["dis"] == ""
    assert by[m0]["line"] == "결정: 자정 넘어 끝남"


def test_brief_without_a_database_or_rounds(tmp_path):
    d = B.meetings_brief(None, NOW)
    assert d["ready"] is False and d["error"] and d["lines"] == [] and d["n"] == 0
    c = R.open_agents(str(tmp_path / "empty.db"))
    try:
        e = B.meetings_brief(c, NOW)
    finally:
        c.close()
    assert e["ready"] and e["n"] == 0 and e["finished"] == 0 and e["lines"] == [] and e["more"] == 0


# ---------------------------------------------------------------- paper3.db: the strategy's accounts and the flips
def _trade(st, aid, t, roe, lev=20, reason=None, hold=30 * MIN):
    strat, tf = aid.split("@")
    pnl = roe * 100.0
    st.trade(aid, TradeRecord(
        strategy_id=strat, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=t - HOUR, entry_time=t - hold,
        entry_price=100.0, exit_time=t, exit_price=101.0, exit_reason=reason or ("LOCK" if roe > 0 else "SL"), qty=1.0,
        leverage=lev, tier="normal", margin=100.0, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=0.1, funding=0.0,
        pnl=pnl, roe=roe, price_move=0.01, mae_price=99.5, mfe_price=101.5, equity_after=5000.0 + pnl, score=0.0,
        context={}))


START = NOW - 4 * DAY
ACCTS = [("S5_DONCHIAN_MFI@15m", "strategy", {}), ("S5_DONCHIAN_MFI@1h", "strategy", {}),
         ("F3_BOS@15m", "ds200", {"family": "F3"}), ("REEL_H1@5m", "reel", {"family": "REEL"}),
         ("RANDOM_1@15m", "random", {}), ("RANDOM_2@15m", "random", {}), ("RANDOM_3@15m", "random", {}),
         ("RANDOM_1@1h", "random", {}), ("RANDOM_1@5m", "random", {}), ("RANDOM_2@5m", "random", {})]


@pytest.fixture
def pdb(tmp_path):
    db = str(tmp_path / "p.db")
    st = Store3(db)
    for aid, kind, data in ACCTS:
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, START, "paper-v4", None, data)
    st.put_state("run", START, {"initial_equity": 5000.0, "taker_fee": 0.0005})
    for i in range(24):                                   # 24 trades, 18 wins: enough for the words
        _trade(st, "S5_DONCHIAN_MFI@15m", START + (i + 1) * 3 * HOUR, 0.10 if i % 4 else -0.20, reason="LOCK" if i % 4 else "SL")
    for i in range(3):
        _trade(st, "S5_DONCHIAN_MFI@1h", START + (i + 1) * 10 * HOUR, 0.05)
    for i in range(6):
        _trade(st, "F3_BOS@15m", START + (i + 1) * 5 * HOUR, 0.3, lev=30)
    for i in range(30):
        _trade(st, "REEL_H1@5m", START + (i + 1) * 2 * HOUR, -0.06 if i % 3 else 0.12, lev=30, reason="TIME", hold=20 * MIN)
    for k, aid in enumerate(["RANDOM_1@15m", "RANDOM_2@15m", "RANDOM_3@15m"]):
        for i in range(4 + k):
            _trade(st, aid, START + (i + 1) * 7 * HOUR, -0.05 * (k + 1))
    _trade(st, "RANDOM_1@1h", START + 9 * HOUR, 0.2)
    _trade(st, "RANDOM_1@5m", START + 9 * HOUR, -0.03, lev=30, reason="TIME")
    st.commit()
    st.close()
    return db


def test_stats_and_words_are_neutral_and_honest():
    rows = [(0.1, 20, 0, 30 * MIN, "LOCK")] * 15 + [(-0.2, 20, 0, 60 * MIN, "SL")] * 5
    s = V.stats(rows, 0, 4 * DAY)
    assert s["n"] == 20 and s["per_day"] == 5.0 and s["win"] == 0.75 and s["lock"] == 0.75
    assert s["roe"] == pytest.approx(0.025) and s["roe_1x"] == pytest.approx(0.00125) and s["hold_h"] == 0.5
    assert V.stats(rows, 0, 4 * DAY, counts_only=True) == {"n": 20, "days": 4.0, "per_day": 5.0}
    y5 = {"per_day": 1.0, "roe": 0.025, "win": 0.5, "hold_h": 0.5, "lock": 0.75}
    w = V.words(y5, s, "roe")
    assert w == {"per_day": "differs", "roe": "similar", "win": "differs", "hold_h": "similar", "lock": "similar"}
    assert set(w.values()) <= {"similar", "differs", "fewer", "small"}            # never pass / fail words
    few = V.stats(rows[:5], 0, 4 * DAY)
    assert all(v == "small" for k, v in V.words(y5, few, "roe").items() if k != "per_day")
    assert V.words({**y5, "per_day": 50.0}, s, "roe")["per_day"] == "fewer"
    assert V.words(y5, V.stats(rows, 0, DAY), "roe")["per_day"] == "small"     # under two days
    assert V.words(None, s, "roe") == {}


def test_vs5y_compares_each_timeframe_with_its_own_coin_flips(pdb):
    import sqlite3
    c = sqlite3.connect(pdb)
    try:
        d = V.compare(c, "S5_DONCHIAN_MFI", NOW)
        ds = V.compare(c, "F3_BOS", NOW)
        reel = V.compare(c, "REEL_H1", NOW)
        assert V.compare(c, "NOPE", NOW) is None
    finally:
        c.close()
    assert d["kind"] == "strategy" and d["unit"] == "roe" and not d["counts_only"]
    by = {t["tf"]: t for t in d["tfs"]}
    assert list(by) == ["15m", "1h"]
    t15 = by["15m"]
    assert t15["now"]["n"] == 24 and t15["now"]["win"] == 0.75 and t15["flips"]["accounts"] == 3
    assert t15["flips"]["n"] == 4 + 5 + 6 and t15["flips"]["roe"] == pytest.approx(-0.10)      # the middle flip
    assert t15["y5"]["roe"] is not None and t15["y5"]["per_day"] is not None                   # the 5-year card row
    assert by["1h"]["flips"]["accounts"] == 1 and all(v == "small" for k, v in by["1h"]["words"].items() if k != "per_day")
    # DeepSeek: counts only, no coin-flip column, no per-account ROE / win rate
    assert ds["counts_only"] and ds["unit"] == "1x"
    t = ds["tfs"][0]
    assert t["flips"] is None and set(t["now"]) == {"n", "days", "per_day"} and t["now"]["n"] == 6
    assert set(t["words"]) <= {"per_day"}
    # the reel: its three 5m flips (two here), compared at 1x (ROE / leverage), the research's unit
    r = reel["tfs"][0]
    assert reel["unit"] == "1x" and r["tf"] == "5m" and r["flips"]["accounts"] == 2
    assert r["now"]["roe_1x"] == pytest.approx(r["now"]["roe"] / 30, abs=1e-4)
    assert r["y5"]["lock"] is None and "lock" not in r["words"]


# ---------------------------------------------------------------- the routes
@pytest.fixture
def client(pdb, adb, tmp_path):
    app = create_app(pdb, hash_password(PW), SECRET, candles=lambda s, i, n: [], agents_db=adb[0],
                     inbox_db=str(tmp_path / "inbox.db"))
    return TestClient(app), app


def test_routes_sit_behind_the_login_and_are_small_and_cached(client):
    c, app = client
    assert c.get("/api/v4/brief/meetings").status_code == 401
    assert c.get("/api/v4/vs5y/S5_DONCHIAN_MFI").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/v4/brief/meetings")
    assert r.status_code == 200 and len(r.content) < 20_000
    assert r.json()["ready"] is True and app.state.more["brief"]["cache"]
    v = c.get("/api/v4/vs5y/S5_DONCHIAN_MFI")
    assert v.status_code == 200 and len(v.content) < 20_000 and "S5_DONCHIAN_MFI" in app.state.more["vs5y"]["cache"]
    assert c.get("/api/v4/vs5y/S5_DONCHIAN_MFI").json() == v.json()
    assert c.get("/api/v4/vs5y/NOT_A_STRATEGY").status_code == 404
    ds = c.get("/api/v4/vs5y/F3_BOS").json()
    assert ds["counts_only"] and all(t["flips"] is None and "roe" not in t["now"] for t in ds["tfs"])


# ---------------------------------------------------------------- the page side
def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    r = subprocess.run([node, "--input-type=module", "-e", f"const F = await import('{core}/figure.js');\n" + body],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_window_follows_korea_time_and_each_strategy_keeps_its_colour():
    # 2026-10-08 KST hours -> phases (Korea has no summer time)
    hours = {h: T0 + h * HOUR for h in (0, 4, 5, 6, 7, 12, 16, 17, 18, 19, 23)}
    out = _node(f"""const H = {json.dumps(hours)};
      const ph = Object.fromEntries(Object.entries(H).map(([h, t]) => [h, F.skyPhase(t)]));
      console.log(JSON.stringify({{ph, ko: F.PHASE_KO, a: F.stratHue("S5_DONCHIAN_MFI"), b: F.stratHue("S5_DONCHIAN_MFI"),
        coin: F.stratHue("RANDOM_1"), reel: F.stratHue("REEL_H1"), f3a: F.stratHue("F3_BOS"), f3b: F.stratHue("F3_BOS_ZONE")}}));""")
    assert out["ph"] == {"0": "night", "4": "night", "5": "dawn", "6": "dawn", "7": "day", "12": "day", "16": "day",
                         "17": "dusk", "18": "dusk", "19": "night", "23": "night"}
    assert out["ko"] == {"dawn": "새벽", "day": "낮", "dusk": "저녁", "night": "밤"}
    assert out["a"] == out["b"] and out["coin"] is None and out["reel"] == 300 and out["f3a"] == out["f3b"]


def test_page_rules_for_the_board_the_characters_and_the_table():
    kit = _read(os.path.join(V4, "screens", "meetboard-kit.js"))
    home = _read(os.path.join(V4, "screens", "home.js"))
    floor = _read(os.path.join(V4, "screens", "office-floor.js"))
    vs = _read(os.path.join(V4, "screens", "vs5y-kit.js"))
    fig = _read(os.path.join(V4, "core", "figure.js"))
    assert "meetBoard(ctx" in home and "최근 회의\"" not in home and "/api/v4/brief/meetings" in kit
    assert "running" in kit and "fillIn(r" in kit and "!first && !seen.has" in kit        # motion only on a new meeting
    assert not re.search(r"typ(e|ing)writer|setInterval", kit)                            # no typing effect, no timers
    assert "deskReport(ctx)" in floor and "skyPhase(" in floor and "bars.usMarket" in floor and ".live" in _read(
        os.path.join(V4, "screens", "office.css"))
    assert "refNote" in vs and "ui.assume(" in vs and "counts_only" in vs and "동전 봇" in vs
    assert "export function stratFigure" in fig and "export function windowArt(ph)" in fig and "skyPhase()" in fig
    pb = _read(os.path.join(V4, "core", "pb.js"))
    assert "stratFigure" in pb and "skyPhase" in pb
    for p in ("meetboard-kit.css", "vs5y-kit.css"):
        src = re.sub(r"/\*.*?\*/", "", _read(os.path.join(V4, "screens", p)), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src) and not re.search(r"\brgba?\(\s*\d", src), p
    for p in ("home.css", "office.css"):
        assert '@import url("meetboard-kit.css");' in _read(os.path.join(V4, "screens", p))
    assert '@import url("vs5y-kit.css");' in _read(os.path.join(V4, "screens", "strategies.css"))
    inv = _read(os.path.join(V4, "INVENTORY.md"))
    assert "/api/v4/brief/meetings" in inv and "/api/v4/vs5y/" in inv and "Wave 2 part C" in inv
