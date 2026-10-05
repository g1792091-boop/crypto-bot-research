"""fill-home: 홈을 살아 있게 (owners 10/06: "화면들은 부족한 게 좀 있어 보여").

- the race steps by run age (more/flow.py auto_step): 5 minutes under 2 days, 15 minutes under 7 days, then the old
  hourly / 4-hour / daily steps; the fine race reads the 5-minute equity rows (last row of each step, carried
  forward), starts at the run start, ends at now, and an incremental read equals a fresh read; a fine step on an old
  run falls back to one hour (bounded reads);
- home-live.js pure parts in node: the countdown clock, the live ROE at the mark, the open positions split (기존 36 /
  5분봉 / 추가 계좌 with ROE; DeepSeek and coin flips counted only), today's best / worst 기존 36 accounts, today's
  meeting timeline states;
- wiring: home mounts 시장 지금 / 지금 열린 포지션 / 방금 끝난 거래 / 오늘 회의 일정, the LED line asks 15-minute curves on a
  young run, 회의 결론 shows the countdown before the first meeting, the race labels say 5분 / 15분, the new CSS uses
  font-size tokens only and no colour literals.
"""
import calendar as _cal
import json
import os
import re
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")
from paperbot.dash.app import Data  # noqa: E402
from paperbot.dash.more import flow as F  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
H = 3_600_000
MIN = 60_000
DAY = 24 * H
INIT = 5000.0
START = _cal.timegm((2026, 10, 5, 18, 35, 0)) * 1000          # 03:35 KST 10/06 (the paper v4 start)
SLOPE = {"S1@15m": 1, "S2@15m": 2, "S3@1h": 3, "D1@15m": -1, "REEL_H1@5m": 10,
         "RANDOM_1@5m": 0, "RANDOM_2@5m": 1, "RANDOM_1@15m": 2, "RANDOM_2@15m": -2}


def _kind(aid):
    return "random" if aid.startswith("RANDOM") else "reel" if aid.startswith("REEL") else "ds200" if aid[0] == "D" else "strategy"


def make_db(path, hours=20):
    st = Store3(path)
    for aid in SLOPE:
        strat, tf = aid.split("@")
        st.add_account(aid, strat, tf, _kind(aid), START, "paper-v4", None, {})
    st.put_state("run", START, {"initial_equity": INIT})
    for aid, k in SLOPE.items():
        for i in range(1, hours * 12 + 1):                    # every 5 minutes, like the bot
            st.equity(aid, START + i * 5 * MIN, INIT + k * i, 0.0)
    st.commit()
    st.conn.close()
    return path


def test_auto_step_by_run_age():
    assert F.auto_step(0, 1 * H) == 5 * MIN
    assert F.auto_step(0, 47 * H) == 5 * MIN
    assert F.auto_step(0, 2 * DAY) == 15 * MIN
    assert F.auto_step(0, 6 * DAY + 23 * H) == 15 * MIN
    assert F.auto_step(0, 7 * DAY) == H
    assert F.auto_step(0, 41 * DAY) == 4 * H and F.auto_step(0, 161 * DAY) == DAY


def test_day_one_race_moves_at_five_minutes(tmp_path):
    db = make_db(str(tmp_path / "paper3.db"))
    now = START + 20 * H + 2 * MIN
    r = F.Flow(Data(db), now_fn=lambda: now).race("auto")
    assert r["ready"] and r["step"] == 5 * MIN
    assert r["t"][0] == START and r["t"][-1] == now
    assert len(r["t"]) > 200                                  # a real moving line, not 1-2 hourly points
    assert all(r["median"][g][0] == INIT for g in ("core", "ds200", "reel", "flip"))
    i = r["t"].index(START + 60 * MIN)                        # 12 rows in: core = S1, S2, S3 at k * 12
    assert r["median"]["core"][i] == INIT + 2 * 12
    assert r["median"]["reel"][i] == INIT + 10 * 12
    # the last point matches the newest rows (the numbers beside the chart)
    assert r["median"]["core"][-1] == INIT + 2 * 240
    assert all((t + 9 * H) % (5 * MIN) == 0 for t in r["t"][1:-1])


def test_fine_race_incremental_equals_fresh_and_15_minutes(tmp_path):
    db = make_db(str(tmp_path / "paper3.db"))
    f = F.Flow(Data(db), now_fn=lambda: START + 10 * H)
    f.race("auto")
    f.now_fn = lambda: START + 20 * H + 2 * MIN
    f.cache.clear()
    f.sync(force=True)
    fresh = F.Flow(Data(db), now_fn=lambda: START + 20 * H + 2 * MIN)
    assert f.race("auto") == fresh.race("auto")
    q = fresh.race(str(15 * MIN))
    assert q["step"] == 15 * MIN and all((t + 9 * H) % (15 * MIN) == 0 for t in q["t"][1:-1])
    assert q["median"]["core"][q["t"].index(START + 25 * MIN + 60 * MIN)] == INIT + 2 * 17


def test_fine_step_on_an_old_run_falls_back_to_hours(tmp_path):
    db = make_db(str(tmp_path / "paper3.db"), hours=2)
    r = F.Flow(Data(db), now_fn=lambda: START + 8 * DAY).race(str(5 * MIN))
    assert r["step"] == H


# ---------------------------------------------------------------- home-live.js in node
def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    url = "file://" + os.path.join(V4, "screens", "home-live.js")
    r = subprocess.run([node, "--input-type=module", "-e", f"const m = await import('{url}');\n" + body],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_live_helpers():
    out = _node("""
const board = {accounts: [
  {account_id: 'A@15m', kind: 'strategy', group: 'core', strategy: 'A', timeframe: '15m',
   position: {symbol: 'BTCUSDT', side: 1, entry: 100, leverage: 30, stop: 99}},
  {account_id: 'B@1h', kind: 'strategy', group: 'core', strategy: 'B', timeframe: '1h',
   position: {symbol: 'BTCUSDT', side: -1, entry: 100, leverage: 20, lock_roe: 0.1}},
  {account_id: 'R@5m', kind: 'reel', group: 'reel', strategy: 'REEL_H1', timeframe: '5m',
   position: {symbol: 'ETHUSDT', side: 1, entry: 10, leverage: 10}},
  {account_id: 'D@15m', kind: 'ds200', group: 'ds200', strategy: 'D', timeframe: '15m', position: {symbol: 'BTCUSDT', side: 1, entry: 1, leverage: 1}},
  {account_id: 'X@15m', kind: 'random', group: 'flip', strategy: 'RANDOM_1', timeframe: '15m', position: {symbol: 'BTCUSDT', side: 1, entry: 1, leverage: 1}},
  {account_id: 'Y@15m', kind: 'random', group: 'flip', strategy: 'RANDOM_2', timeframe: '15m', position: {symbol: 'BTCUSDT', side: 1, entry: 1, leverage: 1}},
  {account_id: 'C@15m', kind: 'copy', group: 'extra', strategy: 'A', timeframe: '15m', position: null},
]};
const o = m.openRows(board, {BTCUSDT: {mark: 101, c: 100}});
const since = 1000;
const trades = [
  {account_id: 'A', kind: 'strategy', exit_time: 2000, pnl: 50}, {account_id: 'A', kind: 'strategy', exit_time: 2100, pnl: 30},
  {account_id: 'B', kind: 'strategy', exit_time: 2000, pnl: -40}, {account_id: 'C', kind: 'strategy', exit_time: 500, pnl: 999},
  {account_id: 'D', kind: 'ds200', exit_time: 2000, pnl: 777}, {account_id: 'E', kind: 'strategy', exit_time: 2000, pnl: 5}];
const bw = m.bestWorst(trades, since);
const day0 = Date.UTC(2026, 9, 5, 15, 0, 0);      // 00:00 KST 10/06
const office = {schedule: {slots: [{hour: 8, hhmm: '08:00', trigger: 'morning', trigger_ko: '아침 회의'},
  {hour: 12, hhmm: '12:00', trigger: 'bull_bear'}, {hour: 14, hhmm: '14:00', trigger: 'ranking'}, {hour: 22, hhmm: '22:00', trigger: 'evening'}]},
  recent: [{trigger: 'morning'}], running: [{trigger: 'ranking'}]};
const tl = m.timeline(office, day0 + 14.5 * 3600000).map((s) => s.state);
console.log(JSON.stringify({ids: o.rows.map((x) => x.a.account_id), roe: o.rows.map((x) => x.roe), other: o.other,
  bw: {best: bw.best.map((x) => [x.id, x.pnl, x.n]), worst: bw.worst.map((x) => [x.id, x.pnl]), n: bw.accounts, t: bw.trades},
  clock: [m.clock(3723000), m.clock(65000), m.clock(-5)], tl, before: m.timeline(office, day0 + 3600000).map((s) => s.state)}));
""")
    # money groups only, sorted by live ROE (best first); no ticker for ETH -> no ROE (sorted last), never made up
    assert out["ids"] == ["A@15m", "B@1h", "R@5m"]
    assert out["roe"][0] == pytest.approx(0.3) and out["roe"][1] == pytest.approx(-0.2) and out["roe"][2] is None
    assert out["other"] == {"ds": 1, "coin": 2}
    assert out["bw"]["best"] == [["A", 80, 2], ["E", 5, 1]] and out["bw"]["worst"] == [["B", -40]]
    assert out["bw"]["n"] == 3 and out["bw"]["t"] == 4                  # yesterday's and DeepSeek's trades left out
    assert out["clock"] == ["1:02:03", "01:05", "00:00"]
    assert out["tl"] == ["done", "past", "run", "next"]
    assert out["before"] == ["done", "next", "run", "next"]


# ---------------------------------------------------------------- wiring + honesty
def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def test_home_wiring():
    js = _read("screens", "home.js")
    for name in ("marketStrip(ctx)", "openCard(ctx)", "tradesCard(ctx)", "meetSchedule(ctx"):
        assert name in js
    assert "/api/v4/curves?step=${curveStep(st.board)}" in js and "step=3600000" not in js
    assert '@import url("home-live.css");' in _read("screens", "home.css")
    live = _read("screens", "home-live.js")
    assert "/api/trades?group=main&limit=12" in live and 'ctx.on("trades"' in live
    assert "그 밖에 딥시크" in live and "(개수만)" in live and "참고" in live and "표본 적음" in live
    assert 'ctx.watch("ticker"' in live and "store.need" not in live.split("marketStrip")[1].split("export function openCard")[0]
    day = _read("screens", "digest-day.js")
    assert "meetSchedule(ctx" in day and '@import url("home-live.css");' in _read("screens", "digest.css")
    assert '"15분" : "5분"' in _read("screens", "flow.js") and '"15분" : "5분"' in _read("screens", "flow-kit.js")


def test_new_css_uses_tokens_only():
    css = _read("screens", "home-live.css")
    for m in re.finditer(r"font-size\s*:\s*([^;]+);", css):
        assert re.fullmatch(r"var\(--t-(xs|sm|md|lg|xl|2xl|led)\)", m.group(1).strip()), m.group(0)
    for m in re.finditer(r"font\s*:\s*([^;]+);", css):
        assert re.search(r"var\(--t-(xs|sm|md|lg|xl|2xl|led)\)", m.group(1)), m.group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css)
    assert "fontSize" not in _read("screens", "home-live.js") and "font-size" not in _read("screens", "home-live.js")


def test_led_curve_steps_five_minutes_on_day_one(tmp_path):
    """The LED line (home.js curveStep): 5 minutes under 2 days, 15 under 7, then hourly; the server keeps a 5-minute
    step (CURVE_STEPS) and day 1 has one point per 5-minute equity row, not a flat 2-point line."""
    db = make_db(str(tmp_path / "paper3.db"), hours=6)
    c = Data(db).curves(5 * MIN, now_ms=START + 6 * H)
    assert c["step"] == 5 * MIN and len(c["t"]) >= 60
    assert len(set(v for v in c["total"] if v is not None)) > 10       # it moves
    js = _read("screens", "home.js")
    assert "age < 2 * 86400000 ? 300000 : age < 7 * 86400000 ? 900000 : 3600000" in js
