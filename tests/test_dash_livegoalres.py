"""실거래 › 봇별 화면의 목표 연구 (dash/more/livegoalres.py; screens/livebots-goalres.js), owners 10-26: "필요한 연구 부분들 각
봇마다 내 목표 수익률을 위해 필요한 분석부분들이나 연구 부분들 다 대시보드 화면에 추가해줘".

- the goal arithmetic by hand (the win rate, the average win and the entries a day ×6 needs, 30 days at this pace, the month
  against the ×6 path) and every verdict branch;
- 추세판단 봇 on the standard live world (tests/livebots_world.py): its paper account and both followers, the gap item (the
  same pairs as the 거래 tab, the paper trades not followed and the executors' own reasons), the light replay, the
  excursions, the role / entry-bar splits;
- VWAP 개선판 on its world (tests/vwap_site_world.py): only its own follower, the gates' virtual results; 꺼짐 in the
  one-paper world;
- 믹스 30분 봇: the new settings told apart by the entry's margin share, the floor arithmetic, 꺼짐 before the bots run;
- V3.9 투비트 on a rule-bot paper3.db made here by store3: the paper account alone while 투비트 is not installed (said so),
  the Toobit plan's buckets of the best net ROE, BTC's 24-hour move at each entry, the last 10 trades, the study's numbers;
- the view in node and the house rules of the css."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livegoalres as G  # noqa: E402
from paperbot.models import TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from tests import livebots_world as W  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")
DAY, H, MIN = 86_400_000, 3_600_000, 60_000


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


# ================================================================ the arithmetic
def _rows(wins: int, losses: int, w: float, lo: float, eq: float = 100.0) -> list:
    return [{"pnl": eq * w, "roe": w / 0.4, "eq": eq} for _ in range(wins)] + [{"pnl": -eq * lo, "roe": -lo / 0.4, "eq": eq} for _ in range(losses)]


def test_goal_numbers_by_hand():
    now = 1_800_000_000_000
    since = now - 10 * DAY
    rows = _rows(15, 5, 0.04, 0.08)
    entries = [since + i * DAY // 2 for i in range(20)]                    # 2 a day over 10 days
    g = G.goal_numbers(rows, entries, since, now, 6.0)
    assert g["n"] == 20 and g["wins"] == 15 and g["win_rate"] == 0.75 and not g["few"]
    assert g["per_day"] == pytest.approx(2.0) and g["avg_win"] == pytest.approx(0.04) and g["avg_loss"] == pytest.approx(0.08)
    growth = (15 * math.log(1.04) + 5 * math.log(0.92)) / 20
    assert g["growth"] == pytest.approx(growth)
    need_g = math.log(6) / 60
    assert g["need_growth"] == pytest.approx(need_g)
    assert g["need_win"] == pytest.approx((need_g - math.log(0.92)) / (math.log(1.04) - math.log(0.92)))
    assert g["pace_mult"] == pytest.approx(math.exp(growth * 60))
    assert g["need_avg_win"] == pytest.approx(math.expm1((need_g - 0.25 * math.log(0.92)) / 0.75))
    assert g["need_per_day"] == pytest.approx(math.log(6) / (growth * 30))
    lo, hi = g["wilson"]
    assert lo < 0.75 < hi
    # the month against the ×6 path: 5 of 30 days gone -> the path is 6^(5/30)
    m = G.goal_numbers(rows, entries, since, now, 6.0, eq_from=100.0, eq_now=120.0, from_ms=now - 5 * DAY)["month"]
    assert m["mult"] == pytest.approx(1.2) and m["path_now"] == pytest.approx(6 ** (5 / 30)) and m["vs_path"] == pytest.approx(1.2 / 6 ** (5 / 30) - 1)


def test_every_verdict_branch():
    now = 1_800_000_000_000
    since = now - 10 * DAY
    ent = [since + i * DAY // 4 for i in range(40)]                        # 4 a day
    few = G.goal_numbers(_rows(3, 2, 0.04, 0.08), ent, since, now, 6.0)
    assert few["tone"] == "thin" and "5번뿐" in few["verdict_ko"]
    no_day = G.goal_numbers(_rows(10, 2, 0.04, 0.08), ent, now - DAY // 2, now, 6.0)
    assert no_day["per_day"] is None and no_day["tone"] == "thin" and "하루가 다 지나야" in no_day["verdict_ko"]
    hopeless = G.goal_numbers(_rows(15, 5, 0.005, 0.08), ent[:4], since, now, 6.0)   # 0.4 a day, tiny wins
    assert hopeless["need_win"] > 1 and hopeless["tone"] == "bad" and "승률 100%여도" in hopeless["verdict_ko"]
    below = G.goal_numbers(_rows(10, 30, 0.04, 0.03), ent, since, now, 6.0)
    assert below["wilson"][1] < below["need_win"] < 1 and below["tone"] == "bad" and "목표 속도가 아니에요" in below["verdict_ko"]
    above = G.goal_numbers(_rows(38, 2, 0.06, 0.02), ent, since, now, 6.0)
    assert above["wilson"][0] > above["need_win"] and above["tone"] == "good" and "목표 근처" in above["verdict_ko"]
    inside = G.goal_numbers(_rows(14, 6, 0.04, 0.03), ent, since, now, 6.0)
    assert inside["wilson"][0] <= inside["need_win"] <= inside["wilson"][1] and inside["tone"] == "warn"
    nowin = G.goal_numbers(_rows(0, 12, 0.04, 0.03), ent, since, now, 6.0)
    assert nowin["avg_win"] is None and nowin["tone"] == "bad" and "평균 이익을 몰라요" in nowin["verdict_ko"]
    for g in (few, no_day, hopeless, below, above, inside, nowin):
        assert not BAD.search(g["verdict_ko"])


def test_light_replay_by_hand():
    x = {"id": "bybit", "name_ko": "바이비트", "config": {"state": "ok", "signal_light_n": 3, "signal_light_min_win": 0.66}}
    pnl = [5, 5, -5, -5, 5, -5, 5, 5]                                     # entered at i h, closed at i h + 30 min
    trades = [{"id": i, "entry_time": i * H, "exit_time": i * H + 30 * MIN, "pnl": p, "roe": p / 100} for i, p in enumerate(pnl)]
    it = G.light_item(x, trades)
    rows = {r["state"]: r for r in it["table"]["rows"]}
    # before each entry the last 3 closed: 0-2 building; 3: (W,W,L) 2/3 green; 4: (W,L,L) red; 5: (L,L,W) red;
    # 6: (L,W,L) red; 7: (W,L,W) green
    assert rows["building"]["n"] == 3 and rows["green"]["n"] == 2 and rows["red"]["n"] == 3
    assert rows["green"]["wins"] == 1 and rows["red"]["wins"] == 2 and rows["red"]["roe_sum"] == pytest.approx(0.05)
    assert "놓친 이익" in it["lead_ko"] and it["tone"] == "warn"
    assert G.light_item({**x, "config": {"state": "ok", "signal_light_n": 0}}, trades) is None


# ================================================================ 추세판단 봇 on the standard world
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    folder = str(tmp_path_factory.mktemp("goalres") / "w")
    p = W.build_world(folder)
    more = {**L.paths_more({}), **W.live_checks(p, folder), "rule_db": os.path.join(folder, "no-rule.db")}
    return {"p": {**L.paths({}), **p}, "more": more, "folder": folder}


def test_trend_accounts_and_items(world):
    d = json_finite(G.build("trend", world["p"], W.NOW, world["more"]))
    assert d["state"] == "ok" and d["bot"] == "trend" and d["name_ko"] == "추세판단 봇" and d["goal"]["mult"] == 6.0
    assert [a["id"] for a in d["accounts"]] == ["paper", "bybit", "mexc"]
    pa = d["accounts"][0]
    assert pa["kind"] == "paper" and pa["n"] == 6 and pa["wins"] == 5 and pa["tone"] == "thin"       # 6 trades: no verdict
    assert pa["month"]["start_equity"] == 1000.0 and pa["month"]["now_equity"] == pytest.approx(1005.0)
    by = d["accounts"][1]
    assert by["kind"] == "live" and by["n"] == 4 and by["state"] == "ok"
    ids = [i["id"] for i in d["items"]]
    assert ids == ["gap_bybit", "light_bybit", "gap_mexc", "light_mexc", "mfe", "roles", "tf"]
    assert all(i["state"] == "ok" for i in d["items"]), [i.get("reason") for i in d["items"]]
    gap = {i["id"]: i for i in d["items"]}["gap_bybit"]
    assert gap["n"] == 3                                                # t2, t3, t6 (the 거래 tab's pairs)
    why = {r["why_ko"]: r for r in gap["table"]["rows"]}
    assert why["그때 실행기가 멈춰 있었어요"]["n"] == 1                   # t4: halted
    assert sum(r["n"] for r in gap["table"]["rows"]) == 2               # t4 and t5 (t1 was before it started)
    assert "덜 벌어요" in gap["lead_ko"] or "더 벌었어요" in gap["lead_ko"]
    assert "아직 근거를 쌓는 중" not in json.dumps(d, ensure_ascii=False)
    roles = {i["id"]: i for i in d["items"]}["roles"]
    assert "역할을 아는 닫힌 거래가 아직 없어요" == roles["lead_ko"]      # the world's strategies have no trend role
    assert [lk["href"] for lk in d["links"]][:2] == ["#/goal", "#/review"]
    assert not BAD.search(json.dumps([i["lead_ko"] for i in d["items"]], ensure_ascii=False))


def test_an_item_that_fails_says_so_in_its_place(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bars gone")
    monkeypatch.setattr(G, "mfe_item", boom)
    d = G.build("trend", world["p"], W.NOW, world["more"])
    it = {i["id"]: i for i in d["items"]}["mfe"]
    assert it["state"] == "error" and "bars gone" in it["reason"] and d["state"] == "ok"


# ================================================================ VWAP 개선판
def test_vwap_bot_and_its_own_follower(tmp_path):
    from tests import vwap_site_world as V
    w = V.build(str(tmp_path / "v"))
    d = json_finite(G.build("vwap", w["p"], V.NOW, dict(w["more"])))
    assert d["state"] == "ok" and d["name_ko"] == "VWAP 개선판"
    ids = [a["id"] for a in d["accounts"]]
    assert ids[0] == "paper" and "bybit" not in ids and len(ids) == 2        # the follower that moved to it, not the trend one
    items = {i["id"]: i for i in d["items"]}
    assert {"mfe", "strategies", "blocked"} <= set(items) and any(k.startswith("gap_") for k in items)
    assert items["blocked"]["state"] == "ok" and "가상 순ROE 합" in items["blocked"]["lead_ko"]
    assert [lk["href"] for lk in d["links"]] == ["#/vwperf", "#/vwblock"]
    t = json_finite(G.build("trend", w["p"], V.NOW, dict(w["more"])))
    assert [a["id"] for a in t["accounts"]] == ["paper", "bybit"]           # each bot only with its own executors


def test_vwap_off_in_the_one_paper_world(world):
    d = G.build("vwap", world["p"], W.NOW, world["more"])
    assert d["state"] == "off" and "꺼져" in d["ko"] and "accounts" not in d


# ================================================================ 믹스 30분 봇
def test_mix_margin_share_and_floor():
    t_new = {"qty": 0.8, "entry": 100.0, "leverage": 20, "equity_before": 10.0}           # margin 4 of 10: 40 %
    t_old = {"qty": 0.12, "entry": 100.0, "leverage": 40, "equity_before": 50.0}          # margin 0.3 of 50
    assert G.mix_margin_share(t_new) == pytest.approx(0.4) and G.mix_margin_share(t_old) == pytest.approx(0.006)
    assert G.mix_margin_share({"qty": None}) is None

    class B:                                                                               # livemix.equity_view's input
        pass
    from paperbot.dash.more import livemix as MX
    ev = {"now": {"value": 45.0}, "floor": 35.0, "floor_frac": 0.7, "start": 50.0}
    orig = MX.equity_view
    MX.equity_view = lambda bid, b: ev
    try:
        per = {"live": {"new": [{"pnl": -4.5, "equity_before": 50.0}, {"pnl": 2.0, "equity_before": 45.5}], "b": B()}}
        it = G.mix_floor(per)
    finally:
        MX.equity_view = orig
    row = it["table"]["rows"][0]
    # one stop = 9 % of the wallet: 45 -> 40.95 -> 37.26 -> 33.9 (< 35): two more stops leave it above the floor
    assert row["avg_loss"] == pytest.approx(0.09) and row["stops_left"] == math.floor(math.log(35 / 45) / math.log(0.91)) == 2
    assert it["tone"] == "warn" and "2번 더 지면" in it["lead_ko"]


def test_mix_world_and_off(tmp_path, monkeypatch):
    from tests import mix_site_world as MW
    w = MW.build(str(tmp_path / "m"))
    for k, v in MW.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    d = json_finite(G.build("mix", L.paths({}), MW.NOW, L.paths_more({})))
    assert d["state"] == "ok" and [a["id"] for a in d["accounts"]] == ["live", "paper"]
    # the world runs the design settings (risk 0.25 %): no new-settings trade yet, said so
    assert all(a["state"] == "missing" and "새 설정" in a["reason_ko"] for a in d["accounts"])
    items = {i["id"]: i for i in d["items"]}
    assert set(items) == {"before_after", "steps", "floor", "twin"} and all(i["state"] == "ok" for i in items.values())
    assert items["steps"]["n"] == 2 and "계단에 닿은 것 1번" in items["steps"]["lead_ko"]
    assert [r["n"] for r in items["before_after"]["table"]["rows"] if r["set_ko"].startswith("새")] == [0, 0]
    for k in list(MW.env_of(w["folder"])):
        monkeypatch.setenv(k, str(tmp_path / "none" / os.path.basename(MW.env_of(w["folder"])[k])))
    for k in ("PAPERBOT_MIX_REPO_CONFIG", "PAPERBOT_MIX_PAPER_REPO_CONFIG"):
        monkeypatch.setenv(k, MW.env_of(w["folder"])[k])
    off = G.build("mix", L.paths({}), MW.NOW, L.paths_more({}))
    assert off["state"] == "off" and "꺼져" in off["ko"]


# ================================================================ V3.9 투비트 (a rule-bot paper3.db made by store3)
T0 = 1_792_368_000_000                  # 2026-10-19 00:00 UTC
V39 = "V39_ALL@1h"
# (coin, side, best price move while open, won, roe): 30x for the alts and 40x for BTC on the Toobit plan (cost 0.16 %)
V39_TRADES = [("ETHUSDT", 1, 0.003, False, -0.5), ("SOLUSDT", -1, 0.008, False, -0.5), ("LTCUSDT", 1, 0.010, False, -0.5),
              ("BCHUSDT", -1, 0.012, False, -0.5), ("DOGEUSDT", 1, 0.020, True, 0.6), ("ETHUSDT", -1, 0.015, True, 0.5),
              ("SOLUSDT", 1, 0.002, False, -0.5), ("LTCUSDT", -1, 0.018, True, 0.5), ("BCHUSDT", 1, 0.016, True, 0.4),
              ("DOGEUSDT", -1, 0.019, True, 0.5), ("ETHUSDT", 1, 0.025, True, 0.7), ("SOLUSDT", -1, 0.001, False, -0.5)]
# BTC's close at each entry over the close 24 h before: up 3 %, down 3 %, flat
BTC_MOVES = [0.03, -0.03, 0.0, 0.03, 0.03, -0.03, 0.0, 0.03, -0.03, 0.0, 0.03, -0.03]


def v39_db(path: str) -> str:
    s = Store3(path)
    s.add_account(V39, "V39_ALL", "1h", "base", T0, "v3")
    eq, bars = 50.0, []
    for i, (sym, side, mv, won, roe) in enumerate(V39_TRADES):
        t = T0 + i * 12 * H + i * MIN              # (never the minute of another entry 24 h before)
        px = 100.0
        margin = eq * 0.4
        pnl = margin * roe
        eq += pnl
        s.trade(V39, TradeRecord(strategy_id="V39_ALL", symbol=sym, timeframe="1h", side=side, signal_ts=t - 1, entry_time=t, entry_price=px,
                                 exit_time=t + 3 * H, exit_price=px * (1 + side * (0.01 if won else -0.01)), exit_reason="LOCK" if won else "SL",
                                 qty=margin * 30 / px, leverage=30, tier="base", margin=margin, stop_price=px * (1 - side * 0.01), tp_price=0.0,
                                 liq_price=px * (1 - side * 0.03), fees=0.1, funding=0.0, pnl=pnl, roe=roe, price_move=0.01 * side,
                                 mae_price=px * (1 - side * 0.005), mfe_price=px * (1 + side * mv), equity_after=eq, score=1.0))
        c1 = 100.0 * (1 + BTC_MOVES[i])
        bars += [{"ts": t, "symbol": "BTCUSDT", "open": c1, "high": c1, "low": c1, "close": c1, "volume": 1.0, "close_time": t + MIN - 1,
                  "processed_at": t + MIN},
                 {"ts": t - DAY, "symbol": "BTCUSDT", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0,
                  "close_time": t - DAY + MIN - 1, "processed_at": t - DAY + MIN}]
    s.live_bars(bars)
    s.put_state("accounts", T0 + 7 * DAY, {"last_ts": T0 + 7 * DAY, "engines": {V39: {"wallet": eq, "position": None, "halted": False}}})
    s.close()
    return path


def test_v39_paper_alone_until_toobit_is_installed(tmp_path, monkeypatch):
    db = v39_db(str(tmp_path / "paper3.db"))
    monkeypatch.setenv("PAPERBOT_LIVE_V39_PAPER_DB", db)
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_CONFIG", str(tmp_path / "no-toobit.json"))
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_DB", str(tmp_path / "no-toobit.db"))
    p = L.paths()
    assert not any(ex == "toobit" for ex, *_r in L.installed(p))
    now = T0 + 7 * DAY
    d = json_finite(G.build("v39", p, now, {**L.paths_more({}), "rule_db": db}))
    assert d["state"] == "ok" and d["name_ko"] == "V3.9 투비트"
    pa, tb = d["accounts"]
    assert pa["kind"] == "paper" and pa["n"] == 12 and pa["wins"] == 6 and V39 in pa["name_ko"]
    assert pa["per_day"] == pytest.approx(12 / 7) and pa["avg_win"] == pytest.approx(0.4 * (0.6 + 0.5 + 0.5 + 0.4 + 0.5 + 0.7) / 6)
    assert tb["id"] == "toobit" and tb["state"] == "off" and "docs/toobit-ko.md" in tb["reason_ko"]
    items = {i["id"]: i for i in d["items"]}
    assert list(items) == ["regime", "ladder", "study"] and all(i["state"] == "ok" for i in items.values())
    lad = {r["range_ko"]: r for r in items["ladder"]["table"]["rows"]}
    # losers' best move 0.3 %, 0.2 %, 0.1 % -> under 15 %; 0.8 % -> 15~20; 1.0 % -> 20~28; 1.2 % -> 28 %+ (30x, cost 0.16 %)
    assert [lad[k]["losers"] for k in ("15% 안", "15% ~ 20%", "20% ~ 28%", "28% 넘게")] == [3, 1, 1, 1]
    assert sum(r["winners"] for r in lad.values()) == 6 and "6번 중 3번" in items["ladder"]["lead_ko"]
    assert "BTC 40배 · 나머지 30배" in items["ladder"]["how_ko"] and "0.16%" in items["ladder"]["how_ko"]
    rg = items["regime"]
    by = {r["key"]: r for r in rg["table"]["rows"]}
    assert by["BTC 옆걸음 (하루 ±2% 안)"]["n"] == 3
    with_ = [r for k, r in by.items() if k.startswith("BTC와 같은 방향")]
    against = [r for k, r in by.items() if k.startswith("BTC와 반대 방향")]
    assert sum(r["n"] for r in with_) + sum(r["n"] for r in against) == 9
    last10 = V39_TRADES[-10:]
    assert f"최근 10번: {sum(1 for x in last10 if x[3])}승" in rg["lead_ko"] and rg["kpis"][2]["value"] == 12
    assert rg["table2"]["rows"] and all(r["week_ko"].endswith(" 주") for r in rg["table2"]["rows"])
    assert items["study"]["table"]["rows"][0]["end"] == 11.0 and "맞는 장" in items["study"]["lead_ko"]


def test_v39_without_its_account(tmp_path, monkeypatch):
    s = Store3(str(tmp_path / "paper3.db"))
    s.put_state("accounts", T0, {"engines": {}})
    s.close()
    monkeypatch.setenv("PAPERBOT_LIVE_V39_PAPER_DB", str(tmp_path / "paper3.db"))
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_CONFIG", str(tmp_path / "no.json"))
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_DB", str(tmp_path / "no.db"))
    d = G.build("v39", L.paths(), T0, L.paths_more({}))
    assert d["state"] == "missing" and V39 in d["ko"]
    monkeypatch.setenv("PAPERBOT_LIVE_V39_PAPER_DB", str(tmp_path / "none.db"))
    d = G.build("v39", L.paths(), T0, L.paths_more({}))
    assert d["state"] == "missing" and "accounts" not in d


# ================================================================ the view in node
def _node(tmp_path, body: str, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              f"const X = await import('file://{SCREENS}/livebots-goalres.js');\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a, q) => ({params: {query: q || {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, href: (n) => '#/' + n,"
              " every() {}, api: async (u) => { globalThis.ASKED = u; return JSON.parse(JSON.stringify(a)); }});\n"
              "const run = async (a, bot) => { const el = X.goalResSection(mkCtx(a), bot); await tick(); await tick(); return el; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_section_in_node(world, tmp_path, monkeypatch):
    tr = G.build("trend", world["p"], W.NOW, world["more"])
    db = v39_db(str(tmp_path / "paper3.db"))
    monkeypatch.setenv("PAPERBOT_LIVE_V39_PAPER_DB", db)
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_CONFIG", str(tmp_path / "no.json"))
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_DB", str(tmp_path / "no.db"))
    v3 = G.build("v39", L.paths(), T0 + 7 * DAY, {**L.paths_more({}), "rule_db": db})
    off = G.build("vwap", world["p"], W.NOW, world["more"])
    out = _node(tmp_path, """
    const a = texts(await run(D_t, 'trend')); const askedT = globalThis.ASKED;
    const b = texts(await run(D_v, 'v39')); const askedV = globalThis.ASKED;
    const c = texts(await run(D_o, 'vwap'));
    const pv = X.goalresView(mkCtx(D_v, {bot: 'v39'})); await tick(); await tick();
    console.log(JSON.stringify({a, b, c, askedT, askedV, page: texts(pv.el).length > 100,
      cells: [X.cellKo(0.123, 'pct'), X.cellKo(0.5, 'pct0'), X.cellKo(-0.02, 'pctp'), X.cellKo(0.09, 'pctneg'), X.cellKo(3, 'n'),
              X.cellKo(-1.5, 'usd'), X.cellKo(2.345, 'mult'), X.cellKo(null, 'pct'), X.cellKo('', 'text'), X.cellKo(0.004, 'mult')],
      tones: [X.cellTone(0.1, 'pct'), X.cellTone(-0.1, 'pctp'), X.cellTone(3, 'n'), X.cellTone(null, 'pct')],
      need: X.needRows({state: 'ok', target: 6, need_win: 1.4, pace_mult: 0.5, growth: -0.01}).map((r) => r[1]),
      month: X.monthWords({target: 6, month: {mult: 1.2, path_now: 1.35, vs_path: 1.2 / 1.35 - 1, from_ms: 0}})}));""", t=tr, v=v3, o=off)
    a, b = out["a"], out["b"]
    for word in ("목표 연구", "두 분 목표: 한 달(30일) ×6 (+500%)", "계산일 뿐 예측이 아니에요", "페이퍼(연습)", "모의 · 연습 돈", "바이비트",
                 "실거래 · 진짜 돈", "닫힌 거래", "승률", "이길 때 잔고", "질 때 잔고", "거래당 잔고 (복리 평균)", "하루 진입", "가상 계산 (예측 아님)",
                 "이 속도로 30일이면", "×6에 필요한 승률", "이번 달", "바이비트: 실거래가 덜 버는 이유", "안 따라간 이유", "그때 실행기가 멈춰 있었어요",
                 "언제 판단:", "어디에 쓰나:", "진 거래는 한때 얼마나 갔나", "어느 역할이 버나", "더 깊게 보기:", "2주 검토"):
        assert word in a, word
    for word in ("V3.9 투비트" if False else "투비트", "투비트 실행기가 아직 꺼져 있어요", "장세: 지금 V3.9에 맞는 장인가", "진입 때 BTC 하루 움직임",
                 "BTC 옆걸음 (하루 ±2% 안)", "주마다", "계단 20→17 확인", "15% ~ 20%", "28% 넘게", "30일 다시 돌려 본 것 (연구 기록)", "$11.00", "$268.00"):
        assert word in b, word
    for t in (a, b):
        assert not BAD.search(t), BAD.search(t)
    assert "꺼져" in out["c"] and "바이비트" not in out["c"] and not BAD.search(out["c"])
    assert out["askedT"] == "/api/v4/livebots/goalres?bot=trend" and out["askedV"] == "/api/v4/livebots/goalres?bot=v39" and out["page"]
    assert out["cells"] == ["+12.3%", "50%", "−2.0%p", "−9.0%", "3", "−$1.50", "×2.35", "—", "—", "×0.01 미만"]
    assert out["tones"] == ["up", "down", "", ""]
    assert out["need"] == ["×0.50", "승률 100%여도 모자람", "—", "거래가 잃는 중이라 횟수로는 안 돼요"]
    assert out["month"]["tone"] == "" and "경로보다 11.1% 뒤예요" in out["month"]["ko"]


# ================================================================ the house rules
def test_the_files_keep_the_house_rules():
    from tests.test_dash_livebots_fees import house_rules
    house_rules("livebots-goalres", "lgr")


# ================================================================ the route on the live app, and the menu screens use it
def test_the_route_on_the_live_app(world, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    for k, v in W.env_of(world["p"]).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", world["more"]["rule_db"])
    assert "livegoalres" in LA.MODULES
    app = LA.create_app(None, b"s" * 32, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=lambda *a: None,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    assert app.state.more["livegoalres"]["routes"] == ["/api/v4/livebots/goalres"]
    c = TestClient(app)
    r = c.get("/api/v4/livebots/goalres?bot=trend")
    assert r.status_code == 200 and r.json()["bot"] == "trend" and r.json()["state"] == "ok"
    assert c.get("/api/v4/livebots/goalres?bot=nonsense").json()["bot"] == "trend"
    for b in ("vwap", "mix", "v39"):
        assert c.get(f"/api/v4/livebots/goalres?bot={b}").status_code == 200
    js = open(os.path.join(SCREENS, "livebots.js"), encoding="utf-8").read()
    assert 'import {goalResSection} from "./livebots-goalres.js";' in js and "goalResMount(goal, bt.bot, ctx)" in js
    assert '@import url("livebots-goalres.css");' in open(os.path.join(SCREENS, "livebots.css"), encoding="utf-8").read()
