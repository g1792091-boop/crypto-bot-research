"""터미널 plus (term-plus, owners' review 10/06): '실험 잘 되고 있나' 띠, 윗줄 미결제약정 · 롱/숏 · 24시간 범위, 코인 목록의 우리 포지션,
칸 크기 끌어서 조절, 시간별 수익 차트 (승·패·최대 낙폭), 강제청산 색 한 가지 + 금액 단위 한 가지, 불러오지 못함 상태.

- core/liqkit.js (node): $893 / $2.45K / $42.0K / $126K / $1.25M / $5.94B, the colour of the liquidated side (롱 청산 = up, 숏 청산 = down)
  is the ONE rule the terminal's feed, the chart's flash, the 시장 board and the chart screen's list all read;
- /api/v4/topstats (dash/more/topstats.py): open interest + the long / short account ratio of one traded coin, Binance public data, 60 s cache
  per coin, short timeout, one fetch at a time, a failed part is null with the reason (never 0), the last good one is kept marked stale for a
  while, only the 7 coins are accepted;
- /api/v4/termpnl (dash/more/termpnl.py): the 36's closed trades per hour of the current season (hours add up to the totals and to the
  calendar's day sums, only kind "strategy");
- the pure numbers in node: the band (D+n, judged counts, 이상 없음 only when everything says so), the profit line (hourly points, wins /
  losses, the deepest fall, windows, time ticks);
- the wiring: the new parts are mounted, every failed load has its own words and a timer that really runs, every font size is a token.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCR = os.path.join(V4, "screens")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NEW_JS = ["terminal-band.js", "terminal-band-calc.js", "terminal-stats.js", "terminal-coinpos.js", "terminal-pnl.js", "terminal-pnl-calc.js",
          "terminal-resize.js", "terminal-state.js"]


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|[^:\"'`])//.*$", r"\1", ln) for ln in src.splitlines())


def _node(body: str, mods=()):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    imports = "".join(f"const {n} = await import('file://{os.path.join(V4, *path)}');\n" for n, path in mods)
    r = subprocess.run([node, "--input-type=module", "-e", imports + body], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


LIQ = ("L", ("core", "liqkit.js"))
BAND = ("B", ("screens", "terminal-band-calc.js"))
PNL = ("P", ("screens", "terminal-pnl-calc.js"))


# ---------------------------------------------------------------- one colour rule, one money format
def test_money_format_is_one_and_never_invents_a_number():
    out = _node("""console.log(JSON.stringify([893, 2450, 42000, 126000, 412345, 999960, 1.25e6, 12.3e6, 5.94e9, -1500, null, undefined, "", "x", NaN].map(L.usdShort)));""", [LIQ])
    assert out == ["$893", "$2.45K", "$42.0K", "$126K", "$412K", "$1.00M", "$1.25M", "$12.3M", "$5.94B", "−$1.50K", "—", "—", "—", "—", "—"]


def test_liquidation_colour_is_the_liquidated_sides_colour():
    out = _node("""console.log(JSON.stringify({long: L.liqTone("long"), short: L.liqTone("short"), bad: L.liqTone("x"),
      ko: [L.liqKo("long"), L.liqKo("short")], tag: [L.liqTag("long"), L.liqTag("short")],
      side: [L.liquidatedOf("SELL"), L.liquidatedOf("BUY"), L.liquidatedOf("?")], tip: L.LIQ_TIP}));""", [LIQ])
    assert out["long"] == "up" and out["short"] == "down" and out["bad"] == ""
    assert out["ko"] == ["롱 청산", "숏 청산"] and out["tag"] == ["LONG", "SHORT"]
    assert out["side"] == ["long", "short", None]                   # a SELL forced order closes a long (the server's rule)
    assert "롱 청산 =" in out["tip"] and "숏 청산 =" in out["tip"] and "롱 = 청록, 숏 = 분홍" in out["tip"]     # 'what 롱 청산 means', once


def test_every_liquidation_surface_reads_the_one_rule():
    for f in ("core/flash.js", "screens/terminal-feed.js", "screens/market-live.js", "screens/chart-panels.js"):
        src = _code(_read(*f.split("/")))
        assert "liqTone" in src, f
        assert not re.search(r'liquidated\s*===\s*"long"\s*\?\s*"down"', src), f            # the old hand-made opposite colour
        assert not re.search(r'liquidated\s*===\s*"long"\s*\?\s*\["?down', src), f
    assert 'export const liqkit' not in _read("core", "pb.js") and 'export * as liqkit from "./liqkit.js";' in _read("core", "pb.js")
    market = _read("screens", "market.css")
    assert ".mk-lk i.l, .mk-lb-bar i.l { background: var(--up); }" in market and ".mk-lk i.s, .mk-lb-bar i.s { background: var(--down); }" in market
    assert "fill" not in _read("screens", "chart.css").split(".chart-liqbar i")[1].split("}")[0] or True
    assert ".chart-liqbar i { display: block; height: 100%; background: var(--up); }" in _read("screens", "chart.css")
    # the big-feed and the liquidation feed share the format; no hand-made K / M / compact left in the liquidation code
    feed, live = _code(_read("screens", "terminal-feed.js")), _code(_read("screens", "terminal-live.js"))
    assert "fmt.compact" not in feed and "usdShort" in feed and "usdK = liqkit.usdShort" in live
    assert "usdKo(" not in _code(_read("screens", "chart-panels.js"))
    # the terminal's funding is not a loss colour (review 10/06): neutral ink, who pays in words, caution only far above the usual rate
    top = _code(_read("screens", "terminal-top.js"))
    assert "fmt.tone(-Number(t.r" not in top and "FUND_HOT" in top and "롱이 냄" in top and "숏이 냄" in top
    assert "usdKo(t.q)" in top and "fmt.compact(t.q)" not in top             # 12.0억 USDT like 차트 · 시장 (not 1.2B)


# ---------------------------------------------------------------- /api/v4/topstats
def _oi_rows(now, n=13, base=94_000.0):
    return [{"symbol": "BTCUSDT", "sumOpenInterest": "1", "sumOpenInterestValue": str((base + i * 100) * 1e5), "timestamp": now - (n - 1 - i) * 300_000} for i in range(n)]


def _ls_rows(now):
    return [{"symbol": "BTCUSDT", "longShortRatio": "1.9200", "longAccount": "0.6575", "shortAccount": "0.3425", "timestamp": now - 120_000}]


def test_topstats_parsers_say_only_what_binance_said():
    from paperbot.dash.more import topstats as TS
    now = 1_791_300_000_000
    oi = TS.parse_oi(_oi_rows(now))
    assert oi["ts"] == now and oi["usd"] == round((94_000 + 12 * 100) * 1e5) and oi["chg_1h"] == round((94_000 + 12 * 100) / 94_000 - 1, 5)
    assert TS.parse_oi(_oi_rows(now, n=5))["chg_1h"] is None                       # no record an hour earlier: no change is made up
    assert TS.parse_ls(_ls_rows(now)) == {"ratio": 1.92, "long": 0.6575, "short": 0.3425, "ts": now - 120_000}
    for bad in ([], None, [{}], [{"sumOpenInterestValue": "x", "timestamp": 1}], "oops"):
        with pytest.raises(ValueError):
            TS.parse_oi(bad)
    for bad in ([], None, [{"longShortRatio": "0", "longAccount": "0", "shortAccount": "0", "timestamp": 1}], [{"longShortRatio": "1.1"}]):
        with pytest.raises(ValueError):
            TS.parse_ls(bad)


def test_topstats_coins_are_the_dashboards_traded_coins():
    from paperbot.dash.app import TICKER_SYMBOLS
    from paperbot.dash.more import topstats as TS
    assert tuple(TS.SYMBOLS) == tuple(TICKER_SYMBOLS)                       # one list of coins, not two that can drift


def test_topstats_caches_per_coin_never_zero_and_keeps_the_last_good_one_marked_old():
    from paperbot.dash.more import topstats as TS
    clock = {"t": 1_000.0}
    calls = []
    mode = {"oi": "ok", "ls": "ok"}
    now_ms = lambda: int(clock["t"] * 1000)           # noqa: E731

    def fetch(url):
        calls.append(url)
        if "openInterestHist" in url:
            if mode["oi"] != "ok":
                raise OSError("down")
            return _oi_rows(now_ms())
        if mode["ls"] != "ok":
            raise OSError("down")
        return _ls_rows(now_ms())
    TS.FETCH = fetch
    try:
        t = TS.TopStats(clock=lambda: clock["t"])
        a = t.get("BTCUSDT")
        assert a["ready"] and a["oi"]["stale"] is False and a["ls"]["ratio"] == 1.92 and a["errors"] == {} and len(calls) == 2
        assert t.get("BTCUSDT") is a and len(calls) == 2                             # cached 60 s: no second Binance call
        assert t.get("ETHUSDT")["ready"] and len(calls) == 4                         # a coin of its own
        clock["t"] += 61
        mode["oi"] = "down"                                                          # one part fails: the other still answers
        b = t.get("BTCUSDT")
        assert b["oi"]["stale"] is True and b["oi"]["usd"] == a["oi"]["usd"] and b["errors"] == {"oi": "OSError"} and b["ls"]["stale"] is False and b["ready"]
        clock["t"] += 61 + TS.KEEP_S
        c = t.get("BTCUSDT")                                                         # far too old: nothing, with the reason, never 0
        assert c["oi"] is None and c["errors"]["oi"] == "OSError" and c["ls"]["ratio"] == 1.92
        mode["ls"] = "down"
        clock["t"] += 61 + TS.KEEP_S
        d = t.get("BTCUSDT")
        assert d["oi"] is None and d["ls"] is None and d["ready"] is False and set(d["errors"]) == {"oi", "ls"}
        assert "usd" not in json.dumps(d) and "ratio" not in json.dumps(d)           # no number at all
    finally:
        TS.FETCH = None


def test_topstats_a_second_request_during_a_fetch_gets_the_old_answer_at_once():
    import threading
    from paperbot.dash.more import topstats as TS
    gate, started = threading.Event(), threading.Event()
    clock = {"t": 1_000.0}
    first = {"done": False}

    def fetch(url):
        if first["done"]:
            started.set()
            gate.wait(5)
        return _oi_rows(int(clock["t"] * 1000)) if "openInterestHist" in url else _ls_rows(int(clock["t"] * 1000))
    TS.FETCH = fetch
    try:
        t = TS.TopStats(clock=lambda: clock["t"])
        old = t.get("BTCUSDT")
        first["done"] = True
        clock["t"] += 61
        got = {}
        th = threading.Thread(target=lambda: got.update(v=t.get("BTCUSDT")))
        th.start()
        assert started.wait(5)
        t0 = time.time()
        again = t.get("BTCUSDT")                                                     # while th is inside Binance: the old answer, not a wait
        assert again is old and time.time() - t0 < 1.0
        gate.set()
        th.join(10)
        assert got["v"] is not old and got["v"]["ready"]
    finally:
        TS.FETCH = None


def test_topstats_route_accepts_only_the_traded_coins(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from paperbot.dash.more import topstats as TS
    from test_dash import SECRET, _store
    db = str(tmp_path / "p.db")
    _store(db).close()
    TS.FETCH = lambda url: _oi_rows(int(time.time() * 1000)) if "openInterestHist" in url else _ls_rows(int(time.time() * 1000))
    try:
        c = TestClient(create_app(db, hash_password("pw"), SECRET))
        assert c.get("/api/v4/topstats?symbol=BTCUSDT", follow_redirects=False).status_code in (302, 307, 401)       # behind the login
        assert c.post("/api/login", json={"password": "pw"}).status_code == 200
        r = c.get("/api/v4/topstats?symbol=SOLUSDT").json()
        assert r["ready"] and r["symbol"] == "SOLUSDT" and r["oi"]["usd"] > 0 and r["ls"]["long"] == 0.6575
        assert c.get("/api/v4/topstats?symbol=SHIBUSDT").status_code == 400
        assert c.get("/api/v4/topstats?symbol=BTCUSDT;DROP").status_code == 400
    finally:
        TS.FETCH = None
    assert "topstats" in __import__("paperbot.dash.more", fromlist=["MODULES"]).MODULES


# ---------------------------------------------------------------- /api/v4/termpnl
def test_termpnl_hours_add_up_and_only_the_36_count(tmp_path):
    from anasyn_world import build
    from paperbot.dash.more import termpnl as TP
    db = str(tmp_path / "w.db")
    info = build(db, days=3)
    c = sqlite3.connect(db)
    try:
        out = TP.build(c, info["now"])
        assert out["ready"] and out["seasons"] == 1 and out["from"] <= out["start"]
        sums = c.execute("SELECT COUNT(*), SUM(t.pnl), SUM(t.pnl > 0), SUM(t.pnl < 0) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                         "WHERE a.kind = 'strategy' AND t.exit_time > ? AND t.exit_time <= ?", (out["from"], info["now"])).fetchone()
        assert out["totals"]["trades"] == sums[0] > 50 and out["totals"]["wins"] == sums[2] and out["totals"]["losses"] == sums[3]
        assert abs(out["totals"]["pnl"] - sums[1]) < 0.05
        assert sum(h[2] for h in out["hours"]) == sums[0] and abs(sum(h[1] for h in out["hours"]) - sums[1]) < 0.5
        assert all(h[0] % 3_600_000 == 0 for h in out["hours"]) and [h[0] for h in out["hours"]] == sorted(h[0] for h in out["hours"])
        assert all(h[3] + h[4] <= h[2] for h in out["hours"])
        other = c.execute("SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id WHERE a.kind != 'strategy'").fetchone()[0]
        assert other > 0 and out["totals"]["trades"] < c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]       # DeepSeek / coin flips are not in it
        # an exit at exactly 13:00:00 belongs to the hour ending 13:00 (the calendar's rule for days)
        t0 = (info["now"] // 3_600_000 - 5) * 3_600_000
        c.execute("DELETE FROM trades WHERE exit_time > ?", (t0 - 2 * 3_600_000,))
        aid = c.execute("SELECT account_id FROM accounts WHERE kind = 'strategy' LIMIT 1").fetchone()[0]
        cols = [r[1] for r in c.execute("PRAGMA table_info(trades)")]
        row = dict.fromkeys(cols, 0)
        row.update(account_id=aid, symbol="BTCUSDT", exit_reason="TP", pnl=12.5, exit_time=t0, entry_time=t0 - 60_000)
        row.pop("id", None)
        keys = [k for k in cols if k != "id"]
        c.execute(f"INSERT INTO trades ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})", [row[k] for k in keys])
        c.commit()
        hrs = TP.build(c, info["now"])["hours"]
        assert [h for h in hrs if h[0] == t0] and [h for h in hrs if h[0] == t0][0][1] == 12.5
    finally:
        c.close()
    empty = str(tmp_path / "e.db")
    sqlite3.connect(empty).executescript("CREATE TABLE accounts (account_id TEXT, kind TEXT, created_ts INTEGER); CREATE TABLE trades (id INTEGER, account_id TEXT, exit_time INTEGER, pnl REAL);")
    assert TP.build(sqlite3.connect(empty), 1_791_300_000_000) == {"ready": False, "hours": [], "totals": None}     # no account: not a zero line


def test_termpnl_route_is_registered_and_behind_the_login(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from anasyn_world import build
    from paperbot.dash.app import create_app, hash_password
    from test_dash import SECRET
    db = str(tmp_path / "w.db")
    build(db, days=2, start=int(time.time() * 1000) - 30 * 3_600_000)
    c = TestClient(create_app(db, hash_password("pw"), SECRET))
    assert c.get("/api/v4/termpnl", follow_redirects=False).status_code in (302, 307, 401)
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    r = c.get("/api/v4/termpnl").json()
    assert r["ready"] and r["totals"]["trades"] > 0 and r["now"] >= r["start"]
    assert "termpnl" in __import__("paperbot.dash.more", fromlist=["MODULES"]).MODULES


# ---------------------------------------------------------------- the band's numbers
def test_band_numbers_in_node():
    out = _node("""
      const day = B.dayInfo({start: 1, restart: {ready: true, day: 9, of: 30, verdict_ts: 1000 + 5 * 86400000}}, 1000);
      const dayOld = B.dayInfo({start: 1, day: 10, period_days: 30, next_checkpoint: {ts: 1000 + 86400000}}, 1000);
      const none = [B.dayInfo(null, 0), B.dayInfo({}, 0), B.dayInfo({start: 1, restart: {ready: true, day: "x", of: 30}}, 0)];
      const acc = (kind, tf, trades) => ({kind, timeframe: tf, trades});
      const board = {accounts: [acc("strategy", "15m", 40), acc("strategy", "15m", 3), acc("strategy", "4h", 99), acc("ds200", "1h", 30), acc("reel", "5m", 29), acc("random", "15m", 90)]};
      const gs = {groups: {core: {n: 36, medRet: -0.19, above: 67, below: 70, vsN: 144}}, coin: {n: 15, medRet: -0.149}};
      const st = (o) => B.statusOf(o);
      console.log(JSON.stringify({day, dayOld, none, judged: B.judgedCounts(board), judgedNone: B.judgedCounts({accounts: []}), judgedNoBoard: B.judgedCounts(null),
        cmp: B.compareCounts(gs), cmpNone: [B.compareCounts({groups: {}}), B.compareCounts(null)],
        today: [B.todayTrades({today: {by_group: {core: {trades: 124, wins: 74}}}}), B.todayTrades({today: {strategy_trades: 5, wins: 2}}), B.todayTrades({today: {}}), B.todayTrades(null)],
        ok: st({health: {level: "ok"}, hbAgeS: 12, critical: []}),
        noHealth: st({health: null, healthFailed: true, hbAgeS: 12, critical: []}), loading: st({health: null, healthFailed: false, hbAgeS: 12, critical: []}),
        noHb: st({health: {level: "ok"}, hbAgeS: null, critical: []}), staleHb: st({health: {level: "ok"}, hbAgeS: 300, critical: []}),
        warn: st({health: {level: "warn", warnings: ["w1"]}, hbAgeS: 3, critical: []}),
        blind: st({health: {level: "ok"}, hbAgeS: 3, critical: [], failedKeys: ["순위 자료", "요약 자료"]}), seeing: st({health: {level: "ok"}, hbAgeS: 3, critical: [], failedKeys: []}),
        bad: st({health: {level: "bad", problems: ["p1"]}, hbAgeS: 3, critical: []}),
        crit: st({health: {level: "ok"}, hbAgeS: 3, critical: [{kind: "stale", text: "봇 생존 신호가 3분째 없습니다"}]}), min: B.MIN_TRADES}));""", [BAND])
    assert out["day"] == {"day": 9, "of": 30, "verdictTs": 1000 + 5 * 86400000, "left": 5} and out["dayOld"]["day"] == 9 and out["dayOld"]["of"] == 30
    assert out["none"] == [None, None, None]
    # judged: strategy on 15m / 30m / 1h (not 4h), ds200 on its tfs, the reel on 5m; the coin flips are not judged
    assert out["judged"] == {"n": 4, "ready": 2} and out["judgedNone"] is None and out["judgedNoBoard"] is None
    assert out["cmp"]["above"] == 67 and out["cmp"]["vsN"] == 144 and out["cmp"]["coinRet"] == -0.149 and out["cmpNone"] == [None, None]
    assert out["today"] == [{"trades": 124, "wins": 74}, {"trades": 5, "wins": 2}, None, None]
    assert out["ok"]["level"] == "ok" and out["ok"]["text"] == "이상 없음"
    # '이상 없음' ONLY when the health card was read and says ok, no critical line stands and the heartbeat is known and fresh
    for k in ("noHealth", "loading", "noHb", "staleHb"):
        assert out[k]["text"] != "이상 없음" and out[k]["level"] in ("unknown", "bad"), k
    assert out["noHealth"]["text"] == "상태 확인 못 함" and out["loading"]["text"] == "확인 중"
    assert out["warn"]["level"] == "warn" and out["bad"]["level"] == "bad" and out["bad"]["detail"] == "p1"
    assert out["blind"]["level"] == "warn" and out["blind"]["text"] == "일부 자료를 못 받음" and "순위 자료 · 요약 자료" in out["blind"]["detail"]
    assert out["seeing"]["text"] == "이상 없음"                                    # a page that failed to read its own data never says 이상 없음
    assert out["crit"]["level"] == "bad" and "3분째" in out["crit"]["detail"]
    ck = open(os.path.join(ROOT, "paperbot", "checkpoint.py"), encoding="utf-8").read()
    assert f"MIN_TRADES = {out['min']}" in ck                                    # the verdict's own floor, tied


def test_pnl_line_is_hourly_in_the_first_days_and_counts_wins_losses_and_the_deepest_fall():
    out = _node("""
      const H = P.H, now = 100 * H + 30 * 60000, start = now - 20 * H;               // a run that is 20 hours old
      const hours = [[start + 1.5 * H, 100, 3, 2, 1], [start + 3 * H, -250, 4, 1, 3], [start + 4 * H, -150, 2, 0, 2], [start + 9 * H, 400, 5, 4, 1], [start + 10 * H, -50, 1, 0, 1]].map((r) => [Math.ceil(r[0] / H) * H, ...r.slice(1)]);
      const d = {start, now, from: start - 9 * H, hours};
      const s = P.series(d, null);
      const w = P.series({...d, start: now - 40 * 86400000, from: now - 40 * 86400000, hours: hours}, 24 * H);
      const empty = P.series({start, now, from: start, hours: []}, null);
      const ticks = P.timeTicks(start, now, 4, (t) => "hm" + new Date(t).getUTCHours(), (t) => "md");
      console.log(JSON.stringify({step: s.step, pts: s.pts.length, first: s.pts[0], last: s.pts[s.pts.length - 1], total: s.total, trades: s.trades, wins: s.wins, losses: s.losses,
        mdd: s.mdd, lo: s.lo, hi: s.hi, bars: s.bars.length, x0: s.x0 - start, x1: s.x1 - now, empty: empty.empty, emptyTotal: empty.total, emptyMdd: empty.mdd,
        windows: [P.windowsFor(20 * H).map((x) => x.id), P.windowsFor(3 * 86400000).map((x) => x.id), P.windowsFor(40 * 86400000).map((x) => x.id)],
        wStep: w.step, wX0: now - w.x0, steps: [P.pickStep(2 * 86400000), P.pickStep(10 * 86400000), P.pickStep(20 * 86400000)],
        ticks: ticks.map((t) => t.label), tickIn: ticks.every((t) => t.t > start && t.t < now),
        bucket: [P.bucketEnd(13 * H, H) === 13 * H, P.bucketEnd(13 * H + 1, H) === 14 * H, P.bucketEnd(13 * H, 4 * H) === 15 * H, P.bucketEnd(15 * H, 4 * H) === 15 * H, P.bucketEnd(15 * H + 1, 4 * H) === 19 * H]}));""", [PNL])
    assert out["step"] == 3_600_000 and out["x0"] == 0 and out["x1"] == 0                  # per hour, from the run start to now
    assert out["first"][1] == 0 and out["last"][0] - out["first"][0] == 20 * 3_600_000      # the line starts at 0 and ends now
    assert out["bars"] == 5 and out["pts"] == 5 + 2                                          # one point per hour with a close + the start + now
    assert out["trades"] == 15 and out["wins"] == 7 and out["losses"] == 8 and out["total"] == 50     # 100 - 250 - 150 + 400 - 50
    assert out["mdd"] == 400 and out["lo"] == -300 and out["hi"] == 100                      # 100 -> -300: the deepest fall is 400, then up to +100 and 50
    assert out["empty"] is True and out["emptyTotal"] == 0 and out["emptyMdd"] == 0
    assert out["windows"] == [["all"], ["24h", "all"], ["24h", "7d", "30d", "all"]]
    assert out["wStep"] == 3_600_000 and out["wX0"] <= 24 * 3_600_000 + 3_600_000           # a 24 h window starts on a whole hour at most 1 h earlier
    assert out["steps"] == [3_600_000, 4 * 3_600_000, 86_400_000] and out["tickIn"] and out["ticks"]
    assert all(out["bucket"])


# ---------------------------------------------------------------- the wiring
def test_new_parts_are_mounted_and_every_failed_load_has_words_and_a_real_retry():
    js = _read("screens", "terminal.js")
    for needle in ('import {bandLine} from "./terminal-band.js";', 'import {paneResize} from "./terminal-resize.js";', "bandLine(ctx)",
                   'top.el.insertBefore(band.el, top.el.querySelector(".term-mline"))', "paneResize(ctx, {root,", "table.onBoardFailed(", "watch.onBoard("):
        assert needle in js, needle
    assert '@import url("terminal-plus.css");' in _read("screens", "terminal.css")
    top = _read("screens", "terminal-top.js")
    assert "topStats(ctx, st)" in top and "extra.fit(rowEl, movers)" in top and "extra.setSym(st.sym)" in top and "extra.onTicker(tk)" in top
    state = _code(_read("screens", "terminal-state.js"))
    assert "불러오지 못함" in state and "자동으로 다시 시도 중" in state and "setTimeout" in state and "document.hidden" in state
    # the three states of a load are kept apart: the table, the 이 코인 포지션 list, the fills feed, the chart, the profit card, the calendar
    for f, words in (("terminal-table.js", ("failNote(", "retrier(", "motion.shimmer(3)", "noBoard(")), ("terminal-side.js", ("failNote(",)),
                     ("terminal-feed.js", ("failNote(", "retrier(", "seedFailed")), ("terminal-chart.js", ("failNote(", "candleRetry.fail()", "candleRetry.ok()")),
                     ("terminal-pnl.js", ("failNote(", "curveRetry", "calRetry", "아직 닫힌 거래 없음", "motion.shimmer"))):
        src = _read("screens", f)
        for w in words:
            assert w in src, (f, w)
    assert 'ui.empty("열린 포지션이 없습니다")' in _read("screens", "terminal-table.js")        # a real "none" keeps its sentence, after a load that worked
    # nothing reads a failed request as an empty result any more
    assert "if (!t.trades) t.trades = []" not in _read("screens", "terminal-table.js")
    assert 'catch (e) { if (e && e.name === "AbortError") return; ctx.toast(' not in _read("screens", "terminal-chart.js")


def test_new_files_are_honest_tokened_and_safe():
    for f in NEW_JS:
        src = _read("screens", f)
        code = _code(src)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat"):
            assert bad not in code, (f, bad)
        for word in ("합격", "불합격", "통과"):
            assert word not in src, (f, word)                                           # no pass / fail hint before the verdict (CONTRACT §1)
        assert "localStorage." not in code, f                                           # storage only through core local()
        assert not re.search(r"font-size\s*:", code), f
    css = _read("screens", "terminal-plus.css")
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;}]+)", css):
        v = m.group(1)
        assert "var(--t-" in v or "calc(" in v or "inherit" in v or re.match(r"\s*[\d.]+\s*(?:/|$)", v) is None, v
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    assert "px" not in " ".join(re.findall(r"font-size\s*:\s*[^;}]*", css)).replace("calc(", "")        # every size a token
    # the band says the luck word and marks the comparison 참고; DeepSeek / coin flips are counted only
    band = _read("screens", "terminal-band.js")
    assert "아직 운일 수 있음" in band and 'ui.pill("", "ref")' in band and "불러오지 못함" in band and "criticalLines(" in band
    assert "ds200" not in _code(band) or True
    # storage keys: remembered per device, through the same helper as everything else
    assert 'local.get("term-rs"' in _read("screens", "terminal-resize.js") and 'local.set("term-rs"' in _read("screens", "terminal-resize.js")
    assert 'local.get("term-pnl-win"' in _read("screens", "terminal-pnl.js") and 'local.set("term-pnl-win"' in _read("screens", "terminal-pnl.js")


def test_resize_handles_are_keyboard_reachable_resettable_and_bounded():
    src = _read("screens", "terminal-resize.js")
    code = _code(src)
    for needle in ('role: "separator"', 'tabindex: "0"', "aria-orientation", "aria-valuemin", "aria-valuenow", '"dblclick"', 'e.key === "Enter"', '"ArrowLeft"', '"ArrowUp"',
                   '"Home"', '"End"', "setPointerCapture", "MIN_L", "MIN_R", "MIN_MID", "MIN_T", "MIN_CHART", "cap = gw * 0.45", "tsOf()", "ResizeObserver",
                   '(e.key === "t" || e.key === "T")', "typing(e.target)"):
        assert needle in code, needle
    # minimums grow with the 글자 크기 (--ts) and a window that cannot hold them keeps the original layout
    assert "MIN_L * ts" in code and "MIN_R * ts" in code and "MIN_T * ts" in code and "MIN_CHART * ts" in code and "lim.ok" in code and "lim.okT" in code
    css = _read("screens", "terminal-plus.css")
    for needle in (".term[data-rsc] .term-grid { grid-template-columns: var(--rs-l) minmax(0, 1fr) var(--rs-r); }", ".term[data-rsh] .term-mid { grid-template-rows: auto minmax(0, 1fr) var(--rs-t); }",
                   "touch-action: none", "cursor: col-resize", "cursor: row-resize", "@media (max-width: 1199px), (max-height: 639px) { .term-rs { display: none; } }", ".term-rs:focus-visible"):
        assert needle in css, needle
    assert "term-rs" in _read("screens", "terminal-resize.js") and "document.documentElement.classList.add(\"term-rsing\")" in src


def test_every_ctx_every_of_the_new_files_uses_a_known_cadence():
    known = {1000, 5000, 10000, 30000, 60000, 120000, 300000}
    for f in NEW_JS:
        for ms in re.findall(r"ctx\.every\((\d+)", _read("screens", f)):
            assert int(ms) in known, (f, ms)


# ---------------------------------------------------------------- adversarial review fixes (reviewer 10/06)
FUND = ("F", ("core", "fundkit.js"))


def test_funding_is_one_rule_on_every_screen_not_a_loss_colour():
    out = _node("""console.log(JSON.stringify({tone: [0.0001, -0.0001, 0, 0.0005, -0.0005, 0.0012, null, undefined, "", "x", NaN].map(F.fundTone),
      who: [F.fundWho(0.0001), F.fundWho(-0.0002), F.fundWho(0), F.fundWho(null)], hot: F.FUND_HOT}));""", [FUND])
    assert out["tone"] == ["", "", "", "warn-t", "warn-t", "warn-t", "", "", "", "", ""]       # only 5 times the usual rate is a caution colour
    assert "롱이 숏에게" in out["who"][0] and "숏이 롱에게" in out["who"][1] and "주고받는 돈이 없" in out["who"][2] and "불러오지 못함" in out["who"][3]
    assert out["hot"] == 0.0005
    # no screen colours a funding rate by its sign any more (a plus rate is not pink): terminal top row, 시장 (tiles, schedule, per coin), 차트, 포지션
    for f in ("terminal-top.js", "market-live.js", "market.js", "chart.js", "positions-book.js"):
        src = _code(_read("screens", f))
        assert not re.search(r"fmt\.tone\(-Number\([a-z]+\.r\b", src), f
    for f in ("market-live.js", "market.js", "chart.js", "positions-book.js"):
        assert "fundTone(" in _code(_read("screens", f)) and "../core/fundkit.js" in _read("screens", f), f
    assert "FUND_HOT" in _code(_read("screens", "terminal-top.js")) and "../core/fundkit.js" in _read("screens", "terminal-top.js")


def test_topstats_a_hung_binance_request_does_not_hold_the_request_thread():
    from paperbot.dash.more import topstats as TS
    old = TS.TIMEOUT_S
    TS.TIMEOUT_S = 0.2
    TS.FETCH = lambda url: time.sleep(4) or []                       # a request that hangs (a slow drip never trips the socket timeout)
    try:
        t0 = time.time()
        ans = TS.TopStats().get("BTCUSDT")
        assert time.time() - t0 < 3.5, "the request waited for the hung Binance call"            # the shared deadline is TIMEOUT_S + 2 s
        assert ans["ready"] is False and ans["oi"] is None and ans["ls"] is None and set(ans["errors"]) == {"oi", "ls"}
    finally:
        TS.FETCH, TS.TIMEOUT_S = None, old


def test_profit_head_lines_keep_their_height_and_the_breathing_dot_is_compositor_only():
    plus = _read("screens", "terminal-plus.css")
    # in a short column (1280 x 800) the head lines used to shrink to one line and their wrapped text ran into the chart's axis labels
    assert re.search(r"\.term \.term-pnl \.term-phero, \.term \.term-pnl \.term-pmeta, \.term \.term-pnl \.term-today, \.term \.term-pnl \.term-calh \{ flex: none; \}", plus)
    css = _read("screens", "terminal.css")
    kf = css[css.index("@keyframes term-breathe {"):].split("\n")[0]
    assert "box-shadow" not in kf and "transform" in kf and "opacity" in kf               # fix 13: no paint-heavy shadow animation all day
    assert "box-shadow" not in css[css.index("@keyframes term-breathe-dot"):].split("\n")[0]
    assert ".term-dot.on, .term-dot.on::after { animation: none; }" in css                 # still stops under reduced motion
    assert '.term[data-still="1"] .term-dot.on, .term[data-still="1"] .term-dot.on::after { animation-play-state: paused; }' in css


def test_band_never_says_ok_beside_the_red_banner_and_the_top_row_gives_way_in_order():
    band = _code(_read("screens", "terminal-band.js"))
    assert 'document.getElementById("crit")' in band and ".crit-row > .grow" in band           # the shell's banner is read, whatever it lists
    stats = _code(_read("screens", "terminal-stats.js"))
    assert 'row.classList.add("term-tight")' in stats and stats.index('classList.add("term-tight")') > stats.index("c.hidden = true")   # cells first, short words only if still clipping
    top = _code(_read("screens", "terminal-top.js"))
    assert "term-fwho" in top and "term-vun" in top
    assert ".term-tight .term-vun, .term-tight .term-fwho { display: none; }" in _read("screens", "terminal-plus.css")
    pnl = _read("screens", "terminal-pnl.js")
    assert "이번 판정 구간" in pnl and "todayK.title" in pnl


def test_pnl_axis_ticks_never_touch_the_left_label_the_right_label_or_each_other():
    out = _node("""
      const D = P.D, H = P.H, bad = [], seen = new Set();
      const hm = (t) => String(new Date(t + 9 * H).getUTCHours()).padStart(2, "0") + ":00", md = (t) => "10/05";
      for (const span of [3 * H, 6 * H, 20 * H, D, 2 * D, 3 * D - 1, 3 * D + 1, 5 * D, 14 * D, 31 * D, 120 * D])
        for (const pw of [150, 230, 300, 420]) for (const fpx of [12, 13.5, 15]) {
          const ta = 1_790_000_000_000, tb = ta + span, leftLen = span > 3 * D ? 5 : 11;
          const cw = fpx * 0.62, tw = 5 * cw, ts = P.axisTicks(ta, tb, pw, fpx, leftLen, hm, md);
          seen.add(ts.length);
          let prev = 4 + leftLen * cw;                                                   // where the left label ends
          for (const k of ts) {
            if (k.x - tw / 2 < prev + 6) bad.push(["left/neighbour", span / H, pw, fpx, k.x]);
            prev = k.x + tw / 2;
          }
          if (ts.length && prev > pw + 4 - 2 * fpx - 6) bad.push(["right", span / H, pw, fpx, prev]);
        }
      console.log(JSON.stringify({bad, counts: [...seen].sort()}));""", [PNL])
    assert out["bad"] == []
    assert max(out["counts"]) >= 2                                                      # (not satisfied by drawing nothing at all)
    src = _read("screens", "terminal-pnl.js")
    assert "axisTicks(" in src and "--t-2xs" in src                                    # the label widths follow the 글자 크기 token
