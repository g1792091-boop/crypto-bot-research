"""The 실거래 site after the switch (owners 10-29, docs/mixbybit-ko.md): the Bybit account traded by the 바이비트 봇 itself,
the 추세판단 봇 switched off.

- livebots: once the 바이비트 봇's server config is there (PAPERBOT_MIXBYBIT_CONFIG, /etc/paperbot/mixbybit.json) the old
  Bybit executor's slot leaves every answer (installed, slots, the summary's execs and accounts, costs) and the summary
  names the bot that took it (``replaced``); before it, every answer as it was;
- livepos: the 바이비트 봇's card in its own words (its name, its app, its fee) next to the friend bot's;
- livegoalres: the 바이비트 봇's goal part (no 전후 and no 하한: margin 40 % from its first trade, no floor), its own
  ladder's steps in the words;
- mixchop: the friend rules leave each coin's values of the last close in the state (``board``), the friend bot's state
  as it was; liveftrend: the 친구 추세판 from that board and from the 레인지 봇's hour, a bot that is off said so;
- the pages (node): 한눈에 shows the 바이비트 봇's card only once the summary says it took the slot, the site opens on
  한눈에, the 바이비트 봇's group and screens, the board's words."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from paperbot import mixchop as M
from paperbot.dash.more import livebots as L
from paperbot.dash.more import liveftrend as FTR
from paperbot.dash.more import livemix as X
from tests import livebots_world as LW
from tests.test_mixbybit_checks import DAY0, H, MIN, _write

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
NOW = DAY0 + 23 * H + 40 * MIN


@pytest.fixture
def site(tmp_path):
    p0 = LW.build_world(str(tmp_path / "w"))
    env = LW.env_of(p0)
    env["PAPERBOT_MIXBYBIT_CONFIG"] = str(tmp_path / "mixbybit.json")
    return {"env": env, "cfg": tmp_path / "mixbybit.json", "tmp": tmp_path}


# ---------------------------------------------------------------- the Bybit slot
def test_the_bybit_slot_leaves_once_its_bot_is_there(site):
    p = L.paths(site["env"])
    assert [x[0] for x in L.installed(p)] == ["bybit", "mexc"] and L.replaced(p) == [] and L.replaced_out(p) == []
    d = L.build(p, LW.NOW)
    assert [x["id"] for x in d["execs"]] == ["bybit", "mexc"] and d["replaced"] == [] and "mixbybit_config" not in d["paths"]
    site["cfg"].write_text(json.dumps({"exchange": "bybit"}), encoding="utf-8")
    p = L.paths(site["env"])
    assert [x[0] for x in L.installed(p)] == ["mexc"] and L.replaced(p) == ["bybit"]
    d = L.build(p, LW.NOW)
    assert [x["id"] for x in d["execs"]] == ["mexc"] and "bybit" not in [a["id"] for a in d["accts"]]
    assert d["replaced"] == [{"id": "bybit", "bot": "bybit", "name_ko": "바이비트 봇", "account_ko": "바이비트", "unit": "paperbot-mixbybit",
                              "api": "/api/v4/livebots/mixbybit", "tab": "bybitbot"}]
    assert d["paths"]["mixbybit_config"] == str(site["cfg"])
    # every answer that lists the executors: the slot is gone, nothing breaks
    assert "bybit" not in L.costs(p, LW.NOW) and "bybit" not in (L.trade_rows(p, LW.NOW).get("accts") or {})
    # slots(): the configs it is given (no configs: the two first slots, as before)
    assert [x[0] for x in L.slots({"mexc": {"state": "missing"}})] == ["mexc"]
    assert [x[1] for x in L.slots()] == ["바이비트", "MEXC"]
    # the same table as the live checks'
    from paperbot import livecheck as LC
    assert L.ENV_MIX["mixbybit_config"][1] == LC.REPLACED_BY["bybit"][0] and L.REPLACED["bybit"]["unit"] == LC.REPLACED_BY["bybit"][1]


def test_the_positions_tab_has_the_bybit_bots_card(site, tmp_path):
    from paperbot.dash.more import livepos as LP
    site["cfg"].write_text("{}", encoding="utf-8")
    pos = {"symbol": "SOLUSDT", "side": 1, "qty": 2.0, "entry": 150.0, "stop_dist": 2.4, "stop": 147.6, "best": 151.0, "step": 0,
           "opened_ms": NOW - H, "signal_close_ms": NOW - H - 5_000, "signal_close": 150.0, "last_bar_ms": NOW - MIN, "stop_id": "s1",
           "equity_before": 100.0, "leverage": 40, "roe_act": 100.0}
    env_b = _write(str(tmp_path / "b"), [], [], live_state={"position": pos, "start_equity": 100.0, "last_close_ms": NOW - 10 * MIN,
                                                            "saved_ms": NOW - MIN, "mode": "mainnet"})
    p = L.paths(site["env"])
    d = LP.build(p, {**L.paths_more({}), "mixbybit_paths": X.paths(env_b, bot="bybit")}, NOW)
    c = next(c for c in d["cards"] if c["id"] == "mixbybit")
    assert (c["state"], c["self"], c["name_ko"], c["short_ko"], c["app_ko"], c["tag"]) == ("ok", True, "바이비트 · 바이비트 봇", "바이비트 봇", "바이비트", "bybit")
    q = c["position"]
    fee = M.load_config(os.path.join(ROOT, "deploy", "mixbybit.live.json")).taker_fee
    assert (q["symbol"], q["side"], q["leverage"], q["entry"]) == ("SOLUSDT", 1, 40, 150.0) and q["round_trip"] == pytest.approx(2 * fee)
    assert q["rule_ko"].startswith("바이비트 봇 · 30분봉 신호") and q["bot_ko"] == "바이비트 봇" and "바이비트 봇은" in q["fast"]["ko"]
    assert q["ladder"][0]["at"] == pytest.approx(0.10) and q["ladder"][0]["lock"] == pytest.approx(0.08)      # its config's 10 -> 8
    ids = [c["id"] for c in d["cards"]]
    assert "bybit" not in ids and ids.index("mixbybit") < ids.index("mexc")
    # before the switch: no 바이비트 봇 card, the executor's as before
    site["cfg"].unlink()
    d = LP.build(L.paths(site["env"]), {**L.paths_more({}), "mixbybit_paths": X.paths(env_b, bot="bybit")}, NOW)
    ids = [c["id"] for c in d["cards"]]
    assert "mixbybit" not in ids and "bybit" in ids


def test_the_goal_part_of_the_bybit_bot(tmp_path, monkeypatch):
    from paperbot.dash.more import livegoalres as GR
    from tests.test_mixbybit_checks import _trade
    start = {"ts": DAY0 - H, "kind": "start", "equity": 100.0, "start_equity": 100.0, "position": None}
    live = [start] + _trade("SOLUSDT", 1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 73.5, qty=10.66)
    env_b = _write(str(tmp_path / "b"), live, list(live))
    monkeypatch.setattr(X, "paths", lambda env=None, bot=None, _p=X.paths: _p(env_b, bot=bot))
    d = GR.build("bybit", L.paths(LW.env_of(LW.build_world(str(tmp_path / "w")))), NOW)
    assert d["bot"] == "bybit" and d["name_ko"] == "바이비트 봇" and d["state"] == "ok"
    assert [a["name_ko"] for a in d["accounts"]] == ["바이비트 (실거래)", "모의"]
    ids = [i["id"] for i in d["items"]]
    assert "before_after" not in ids and "floor" not in ids and "steps" in ids and "twin" in ids
    steps = next(i for i in d["items"] if i["id"] == "steps")
    assert "1칸 (10% 닿고 8% 잠금)" in [r["step_ko"] for r in steps["table"]["rows"]] or "첫 칸(10→8)" in steps["use_ko"]
    assert [x["href"] for x in d["links"]] == ["#/bybitperf", "#/ftrend"]


# ---------------------------------------------------------------- the board (mixchop) and the 친구 추세판
def _ev(rule, side=0, why="", **kv):
    base = {"symbol": "BTCUSDT", "close_ms": NOW - 10 * MIN, "side": side, "why": why, "rule": rule, "close": 70000.0, "trend": 1,
            "votes": {"line": 1, "ema": 1, "chop": 0, "st": 1}, "ema_rsi": 58.2, "chop_zone": 3, "stop_pct": 1.1, "liq_ok": True}
    return {**base, **kv}


def test_the_bot_leaves_each_coins_values_in_its_state(tmp_path):
    evs = [_ev("obv", 1, turn=1, obv_cs=1, obv_dark=True), _ev("srsi", 0, "스톡RSI 크로스 없음", cross="", k=44.0, d=40.1, xs=1)]
    r = M.board_row(evs, NOW - 10 * MIN)
    assert r["trend"] == 1 and r["votes"]["chop"] == 0 and (r["turn"], r["obv_cs"], r["obv_dark"]) == (1, 1, True)
    assert (r["k"], r["d"], r["xs"]) == (44.0, 40.1, 1) and r["rules"] == {"obv": {"side": 1, "why": ""}, "srsi": {"side": 0, "why": "스톡RSI 크로스 없음"}}
    # save(): the board only when there is one (the friend bot's state as it was)
    cfg = M.load_config(os.path.join(ROOT, "deploy", "mixbybit.paper.json"))
    cfg.state = str(tmp_path / "s.json")
    bot = M.Bot.__new__(M.Bot)
    bot.cfg, bot.pos, bot.start_equity, bot.last_close_ms, bot.now, bot.board = cfg, None, 100.0, 1, lambda: 2, {}
    bot.save()
    assert "board" not in json.load(open(cfg.state, encoding="utf-8"))
    bot.board = {"BTCUSDT": r}
    bot.save()
    assert json.load(open(cfg.state, encoding="utf-8"))["board"]["BTCUSDT"]["rules"]["obv"]["side"] == 1


def test_the_friend_trend_board(tmp_path, site):
    st = {"position": None, "start_equity": 100.0, "last_close_ms": NOW - 10 * MIN, "saved_ms": NOW - 9 * MIN, "mode": "mainnet",
          "board": {"BTCUSDT": M.board_row([_ev("obv", 0, "OBV 연한색→진한색 없음", turn=0, obv_cs=1, obv_dark=False),
                                            _ev("srsi", 1, cross="gold", k=31.0, d=27.5, xs=1)], NOW - 10 * MIN),
                    "ETHUSDT": {"close_ms": NOW - 10 * MIN, "rules": {"obv": {"side": 0, "why": "캔들 읽기 실패: timeout"}}}}}
    env_b = _write(str(tmp_path / "b"), [], [], live_state=st)
    p = L.paths(site["env"])
    d = FTR.build(p, NOW, X.paths(env_b, bot="bybit"))
    assert d["m30"]["state"] == "ok" and d["m30"]["bot"] == "live" and d["m30"]["stale"] is False
    rows = {r["symbol"]: r for r in d["coins"]}
    assert [r["symbol"] for r in d["coins"]][:7] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "ZECUSDT"]
    b = rows["BTCUSDT"]["m30"]
    assert (b["state"], b["trend"], b["trend_ko"]) == ("ok", 1, "상승")
    assert [(v["ko"], v["side_ko"]) for v in b["votes"]] == [("하늘·보라 선", "상승"), ("EMA RSI", "상승"), ("찹존", "횡보"), ("슈퍼트렌드", "상승")]
    assert b["obv"] == {"cs": 1, "dark": False, "turn": 0, "ko": "연한 초록", "turn_ko": None}
    assert (b["stoch"]["cross_ko"], b["stoch"]["side50_ko"], b["rules"]["srsi"]["side"]) == ("골든 ●", "50선 아래", 1)
    e = rows["ETHUSDT"]["m30"]
    assert e["state"] == "error" and e["ko"] == "캔들 읽기 실패: timeout"
    assert rows["SOLUSDT"]["m30"]["state"] == "none"
    assert d["h1"]["state"] in ("off", "none", "error") and rows["BTCUSDT"]["h1"]["state"] == "none"
    # an old board says so; no board yet / no bot: said, never a vote
    d = FTR.build(p, NOW + 2 * H, X.paths(env_b, bot="bybit"))
    assert d["m30"]["stale"] is True
    env_0 = _write(str(tmp_path / "c"), [], [])
    d = FTR.build(p, NOW, X.paths(env_0, bot="bybit"))
    assert d["m30"]["state"] == "none" and "다음 30분봉" in d["m30"]["ko"] and all(r["m30"]["state"] == "none" for r in d["coins"])
    for f in ("live-state.json", "paper-state.json"):
        os.remove(os.path.join(str(tmp_path / "c"), f))
    d = FTR.build(p, NOW, X.paths(env_0, bot="bybit"))
    assert d["m30"]["state"] == "off" and "꺼져" in d["m30"]["ko"]


def test_the_board_reads_the_range_bots_hour(site, monkeypatch, tmp_path):
    from paperbot.dash.more import liverange as RG
    snap = {"state": "ok", "range": (NOW - 5 * MIN, {"friend": {"BTCUSDT": {"trend": -1, "line": -1, "ema": -1, "chop": 0, "st": -1,
                                                                            "ema_rsi": 41.0, "chop_zone": -2},
                                                                "ETHUSDT": {"error": "5분봉 10개뿐"}}})}
    monkeypatch.setattr(RG, "snapshot", lambda path, now: snap)
    monkeypatch.setattr(RG, "locate", lambda p, now: (None, "/x/range.db", [], []))
    d = FTR.build(L.paths(site["env"]), NOW, X.paths(_write(str(tmp_path / "b"), [], []), bot="bybit"))
    rows = {r["symbol"]: r for r in d["coins"]}
    assert d["h1"]["state"] == "ok" and rows["BTCUSDT"]["h1"]["trend_ko"] == "하락" and rows["BTCUSDT"]["h1"]["votes"][2]["side_ko"] == "횡보"
    assert rows["ETHUSDT"]["h1"] == {"state": "error", "ko": "5분봉 10개뿐"}
    snap["range"] = (NOW - 5 * MIN, {"supertrend": {"BTCUSDT": 1}})        # the range bot before its switch
    d = FTR.build(L.paths(site["env"]), NOW, X.paths(_write(str(tmp_path / "b"), [], []), bot="bybit"))
    assert d["h1"]["state"] == "none" and "friend_tf" in d["h1"]["ko"]


# ---------------------------------------------------------------- the pages (node)
def _node(tmp_path, body: str, **data) -> dict:
    from tests import test_dash_livemix as TM
    return TM._node(tmp_path, body, **data)


def test_the_pages(tmp_path):
    from tests import test_dash_livev39 as TV
    out = TV._node(tmp_path, f"""
    const R = await import('file://{V4}/core/routes.js');
    const HQ = await import('file://{SCREENS}/livebots-hq.js');
    const F = await import('file://{SCREENS}/livebots-ftrend.js');
    const MX = await import('file://{SCREENS}/livebots-mix.js');
    const LB = await import('file://{SCREENS}/livebots.js');
    console.log(JSON.stringify({{start: R.LIVE_START, bots: R.GROUPS[0].screens, groups: R.GROUPS.map((g) => g.id),
      by: R.GROUPS.find((g) => g.id === 'bybit').screens, keys: R.KEYS,
      screens: ['bybitbot', 'bybit', 'bybitperf', 'ftrend'].map((k) => [R.SCREENS[k].ko, R.SCREENS[k].mod, R.screenIcon(k).childNodes.length > 3]),
      mixes: HQ.MIX_BOTS.map((m) => [m.slot, m.bot, m.api, m.replaces]),
      led: HQ.mixLed(null, true, {{ko: '바이비트 봇'}}).why,
      tabs: ['bybitbot', 'bybit', 'bybitperf', 'ftrend'].map((id) => LB.TABS.some((t) => t.id === id)), tab: LB.BOT_TAB.bybitbot.bot,
      ui: [MX.BYBIT_UI.api, MX.BYBIT_UI.perf, MX.MIX_UI.api],
      trend: MX.trendKo({{trend: 0, votes: {{line: 1, ema: 1, chop: 0, st: 0}}}}),
      cells: [F.trendCell({{state: 'ok', trend: 1, trend_ko: '상승', votes: [{{side: 1}}, {{side: 1}}, {{side: 0}}, {{side: -1}}]}}), F.trendCell({{state: 'error', ko: 'x'}}),
        F.obvCell({{cs: -1, dark: true, ko: '진한 빨강', turn_ko: '연한 빨강 → 진한 빨강 (숏 쪽)'}}),
        F.stochCell({{k: 62.0, d: 58.0, xs: -1, cross: 'dead', cross_ko: '데드 ●', side50_ko: '50선 위'}}),
        F.ruleLines({{rules: {{obv: {{ko: 'OBV 진한색', side: 0, why: '친구 추세 진입 금지'}}, srsi: {{ko: '스톡RSI 50선', side: -1, why: ''}}}}}}),
        F.agoKo(65 * 60000)]}}));""")
    assert out["start"] == "hq" and out["bots"] == ["bybitbot", "rangebot", "vwapbot", "mixbot", "trendbot"]
    assert out["groups"][-1] == "bybit" and out["by"] == ["bybit", "bybitperf", "ftrend"]
    assert out["keys"] == ["bybitbot", "rangebot", "vwapbot", "mixbot", "trendbot", "trend", "tchart", "hq", "pos"]
    assert out["screens"] == [["바이비트 봇", "livebots", True], ["바이비트 관제", "livebots", True], ["바이비트 성적", "livebots", True],
                              ["친구 추세판", "livebots", True]]
    assert out["mixes"] == [["wooxpro2", "친구 30분 봇", "/api/v4/livebots/mix", None],
                            ["bybit", "바이비트 봇", "/api/v4/livebots/mixbybit", "bybit"]]
    assert out["led"] == "바이비트 봇 기록을 불러오지 못했어요" and all(out["tabs"]) and out["tab"] == "bybit"
    assert out["ui"] == ["/api/v4/livebots/mixbybit", "/api/v4/livebots/mixbybitperf", "/api/v4/livebots/mix"]
    assert out["trend"] == "친구 추세 진입 금지 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 · 슈퍼트렌드 횡보)"
    c = out["cells"]
    assert c[0] == {"text": "상승", "tone": "up", "sub": "2표가 상승"} and c[1]["text"] == "못 읽음" and c[1]["sub"] == "x"
    assert c[2] == {"text": "진한 빨강", "tone": "down", "dark": True, "turn": "연한 빨강 → 진한 빨강 (숏 쪽)"}
    assert c[3]["text"] == "K 62.0 / D 58.0 · 50선 위" and c[3]["cross"] == "데드 ● (50선 위: 숏 신호)"
    assert [x["text"] for x in c[4]] == ["친구 추세 진입 금지", "숏 신호"] and c[5] == "1시간 5분 전"


def test_the_ftrend_route_is_registered():
    from paperbot.livedash import app as A
    assert "liveftrend" in A.MODULES
    assert '@import url("livebots-ftrend.css");' in open(os.path.join(SCREENS, "livebots.css"), encoding="utf-8").read()
    r = subprocess.run(["node", "--check", os.path.join(SCREENS, "livebots-ftrend.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_bybit_screens_render(tmp_path, site):
    from paperbot.dash.app import json_finite
    from tests.test_mixbybit_checks import _trade
    start = {"ts": DAY0 - H, "kind": "start", "equity": 100.0, "start_equity": 100.0, "position": None}
    live = [start] + _trade("SOLUSDT", 1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 73.5, qty=10.66)
    paper = [start] + _trade("SOLUSDT", 1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 74.0, qty=10.66)
    mp = X.paths(_write(str(tmp_path / "b"), live, paper), bot="bybit")
    st = {"position": None, "start_equity": 100.0, "last_close_ms": NOW - 10 * MIN, "saved_ms": NOW - 9 * MIN, "mode": "mainnet",
          "board": {"BTCUSDT": M.board_row([_ev("obv", 1, turn=1, obv_cs=1, obv_dark=True), _ev("srsi", 0, "스톡RSI 크로스 없음", k=44.0, d=40.0, xs=1)],
                                           NOW - 10 * MIN)}}
    json.dump(st, open(mp["live"]["state"] or X.files_of("live", mp["live"], X.read_config(mp["live"]["config"], mp["live"]["repo_config"], X.BYBIT))[0], "w"))
    ft = json_finite(FTR.build(L.paths(site["env"]), NOW, mp))
    out = _node(tmp_path, f"""
    const F = await import('file://{SCREENS}/livebots-ftrend.js');
    const a = texts((await run((c) => X.mixView(c, X.BYBIT_UI), D_c)).el), b = texts((await run((c) => X.mixperfView(c, X.BYBIT_UI), D_p)).el);
    const f = texts((await run(F.ftrendView, D_f)).el);
    console.log(JSON.stringify({{a, b, f}}));""", c=X.control(mp, NOW), p=X.perf(mp, NOW), f=ft)
    a, b, f = out["a"], out["b"], out["f"]
    for w in ("실거래 · 바이비트", "진짜 돈 · 바이비트 계정", "바닥선", "없음", "잔고가 줄어도 새 진입을 멈추지 않아요"):
        assert w in a, w
    assert "WOO X Pro" not in a and "WOO X Pro" not in b
    for w in ("실거래 vs 모의", "손절 = 진입 때 30분봉 ATR × 3", "5년 재생이 없어", "바닥선 없음"):
        assert w in b, w
    for w in ("코인별 친구 추세", "BTC", "상승", "하늘·보라 선 상승", "찹존 횡보", "진한 초록", "바뀜: 연한 초록 → 진한 초록 (롱 쪽)", "OBV 진한색 롱 신호",
              "스톡RSI 50선 스톡RSI 크로스 없음", "읽는 법"):
        assert w in f, w


HQ_B = """
for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),
  replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {
  const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };
const K = await import('file://SCREENS/livebots-kit.js');
const HQ = await import('file://SCREENS/livebots-hq.js');
const asked = [];
const ctxOf = () => ({params: {query: {}, arg: ''}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {},
  href: (n) => '#/' + n, every(ms, fn, o) { if (o && o.now === false) return; fn(); },
  api: async (path) => { asked.push(path); const a = {'/api/v4/livebots/mixbybit': D_b}[path];
    if (a === undefined) throw Object.assign(new Error('x'), {status: 503}); return JSON.parse(JSON.stringify(a)); }});
const view = async (S) => {
  K.setPapers(S.papers); K.setExecs(S.execs);
  const v = HQ.hqView(ctxOf(), {get: () => S, state: () => 'ok', at: () => S.now_ms, retry: () => {}});
  await tick(); v.set(S, 'ok'); await tick(); await tick(); await tick();
  const w = D.walk(v.el);
  const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || '').split(' ').includes(c)) return n;
    for (const k of n.childNodes) { const r = find(k, c); if (r) return r; } return null; };
  return {text: w.text.replace(/\\s+/g, ' '), mixb: w.classes.filter((x) => x.split(' ').includes('lbh-mixb')).length,
    retired: !find(v.el, 'lbh-retired').hidden, bar: !find(v.el, 'lbh-pbar').hidden};
};
const before = await view(D_s0); const n0 = asked.filter((x) => x.endsWith('mixbybit')).length;
const after = await view(D_s1);
const moved = await view({...D_s1, execs: D_s1.execs.map((x) => ({...x, bot: 'range'}))});
console.log(JSON.stringify({before, after, moved, n0, n1: asked.filter((x) => x.endsWith('mixbybit')).length}));
"""


def test_hq_shows_the_bybit_bot_once_it_took_the_slot(site, tmp_path):
    from paperbot.dash.app import json_finite
    from tests.test_mixbybit_checks import _trade
    s0 = json_finite(L.build(L.paths(site["env"]), LW.NOW))
    site["cfg"].write_text("{}", encoding="utf-8")
    s1 = json_finite(L.build(L.paths(site["env"]), LW.NOW))
    start = {"ts": DAY0 - H, "kind": "start", "equity": 100.0, "start_equity": 100.0, "position": None}
    live = [start] + _trade("SOLUSDT", 1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 73.5, qty=10.66)
    b = json_finite(X.control(X.paths(_write(str(tmp_path / "b"), live, list(live)), bot="bybit"), NOW))
    out = _node(tmp_path, HQ_B.replace("SCREENS", SCREENS), s0=s0, s1=s1, b=b)
    assert out["before"]["mixb"] == 0 and out["n0"] == 0 and "바이비트 봇 관제 · 성적 →" not in out["before"]["text"]
    # the 추세판단 봇's 40-trade bar while an executor follows it (here WOO X Pro still does); no one: one line instead
    assert (out["before"]["bar"], out["before"]["retired"]) == (True, False) and (out["after"]["bar"], out["after"]["retired"]) == (True, False)
    assert (out["moved"]["bar"], out["moved"]["retired"]) == (False, True)
    # owners 10-30: no executor follows the 추세판단 봇 -> the centre is the bots trading now (tests/test_rules1030.py)
    mv = out["moved"]["text"]
    assert "실거래 봇 " in mv and "개 돌아가는 중" in mv and "고리 = 지금 실거래 봇" in mv and "추세판단 봇 꺼 둠" not in mv
    t = out["after"]["text"]
    assert out["after"]["mixb"] == 1 and out["n1"] >= 1
    for word in ("바이비트 진짜 돈 봇 바이비트 봇 스스로 매매 · 페이퍼를 따라가지 않음", "최근 거래 · 0승 1패", "바이비트 봇 관제 · 성적 →",
                 "30분봉 신호 · BTC·ETH·SOL·DOGE·LTC·BCH·ZEC"):
        assert word in t, word


def test_hq_is_calm_about_the_switched_off_trend_bot(tmp_path):
    """한눈에 (owners 10-30 photo: '페이퍼 봇 기록 멈춤' in red on the first screen): once no executor follows the 추세판단 봇,
    its stopped record is said in plain words, not as an alarm; followed: the alarm as before."""
    from tests import test_dash_livev39 as TV
    out = TV._node(tmp_path, f"""
    const HQ = await import('file://{SCREENS}/livebots-hq.js');
    const d = (bots) => ({{paper: {{state: 'ok', stale: true}}, execs: bots.map((b, i) => ({{id: 'x' + i, bot: b, record: {{state: 'ok'}}}}))}});
    console.log(JSON.stringify({{off: HQ.idleWords(d(['range', 'paper2'])), on: HQ.idleWords(d(['paper', 'range'])),
      old: HQ.idleWords({{paper: {{state: 'ok', stale: true}}, execs: [{{id: 'bybit'}}]}}), m: [HQ.mainOff(d(['range'])), HQ.mainOff(d([])), HQ.mainOff(null)]}}));""")
    assert out["off"]["head"] == "추세판단 봇 꺼 둠" and out["off"]["tone"] == "wait" and "아래 계좌 카드" in out["off"]["sub"]
    assert out["on"]["head"] == "페이퍼 봇 기록 멈춤" and out["on"]["tone"] == "bad"
    assert out["old"]["head"] == "페이퍼 봇 기록 멈춤"                  # an answer without ``bot``: as before
    assert out["m"] == [True, False, False]
