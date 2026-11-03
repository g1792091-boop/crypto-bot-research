"""실거래 › 게이트 봇 (#/gatebot; owners 11-01 "일단 게이트 대시보드 화면 만드는거 진행해줘야지"; dash/more/livegate.py +
screens/livebots-gate.js / livebots-gate.css). The 게이트 봇 (paperbot/gateguard.py, docs/gate-bot-ko.md) has no trading
rule: the friend enters by hand on Gate, the bot puts the stop (15m ATR(14) x 3, pulled inside the liquidation price) and
the ladder (10 -> 8, then 2 % steps) on each position; since 11-03 (owners "게이트 아이오봇 거래소 수익률 기준 10%로 2%로
마다 계단식 익절로 바꿔줘") in Gate's own ROE, before fees (``ladder_basis`` gross). The screen reads its state file and its
config only.

- nothing installed / the config only / a config the bot would refuse / a broken state file: each said, nothing made up
- a real state: the bot run on the fake Gate of tests/test_gateguard.py (a short closed by hand, then a long laddered to
  the +10 % lock): the position as Gate shows it, the bot's stop and its basis, the ladder's next step and its price (the
  bot's own formula), the distance to the stop and to the liquidation price, the account, the ended position with
  Gate's P&L, the bot's messages newest first
- a position the bot does not hold yet, the bot's record of one the last loop did not see, an old loop: said
- the unit's state words; the route in the live app behind its login
- the screen in node on the real answer (no null / undefined / NaN) and on each empty answer; static: tokens only, the
  imports through pb.js, read-only; the menu, the tab and its HUD
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")

from paperbot import gateguard as GG  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livegate as LG  # noqa: E402
from tests.test_gateguard import make  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-gate.js")
CSS = os.path.join(SCREENS, "livebots-gate.css")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
CFG = os.path.join(ROOT, "deploy", "gateguard.json")
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")
RUN = ("active", "enabled")


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _real_state(tmp=None):
    """The bot itself on the fake Gate with the repo's config (Gate's own ROE): a short closed by hand at a gain, then a
    long laddered to the +10 % lock."""
    import tempfile
    cfg = GG.load_config(CFG)
    cfg.state = os.path.join(tmp or tempfile.mkdtemp(), "bot-state.json")
    fake, g, _msgs = make(cfg=cfg)
    fake.open(size=-4, entry=100.0, lev=10)
    g.loop_once()
    fake.now += 30
    fake.flat("BTC_USDT", 99.0)
    g.loop_once()
    fake.now += 60
    fake.open(size=10, entry=100.0, lev=20)
    g.loop_once()
    fake.now += 60
    fake.minute("BTC_USDT", 100.5, 100.42, 100.46)            # 거래소 ROE +10 %: the stop to the +8 % price 100.4
    g.loop_once()
    fake.now += 60
    fake.minute("BTC_USDT", 100.6, 100.5, 100.58)             # +12 %: the +10 % lock at 100.5
    fake.positions["BTC_USDT"].update(mark_price="100.58", unrealised_pnl="0.058")
    g.loop_once()
    with open(g.cfg.state, encoding="utf-8") as fh:
        return json.load(fh), fake.now


def test_unit_words():
    assert LG.unit_of("active", "enabled") == "run" and LG.unit_of("activating", "enabled") == "run"
    assert LG.unit_of("failed", "enabled") == "fail"
    assert LG.unit_of("inactive", "disabled") == "stop" and LG.unit_of("inactive", "enabled") == "stop"
    assert LG.unit_of("inactive", "not-found") == "off" and LG.unit_of("inactive", "") == "off"   # (no unit file)
    assert LG.unit_of("", "") == "unknown"
    assert set(LG.UNIT_KO) == {"run", "fail", "stop", "off", "unknown"}


def test_nothing_installed_nothing_made_up(tmp_path, monkeypatch):
    monkeypatch.setenv(LG.STATE_ENV, str(tmp_path / "no-state.json"))
    monkeypatch.setenv(LG.CONFIG_ENV, str(tmp_path / "no-config.json"))
    d = LG.build(1_800_000_000_000, lambda u: ("inactive", "not-found"))
    assert d["state"] == "missing" and "4장 A" in d["ko"] and d["rules"] is None
    assert d["unit"] == {"active": "inactive", "enabled": "not-found", "state": "off", "ko": "설치 전"}
    assert d["positions"] == [] and d["closed"] == [] and d["log"] == [] and "account" not in d
    # the config copied, the bot not run yet: its rules from the bot's own reading
    monkeypatch.setenv(LG.CONFIG_ENV, CFG)
    d = LG.build(1_800_000_000_000, lambda u: ("inactive", "disabled"))
    assert d["state"] == "off" and "4장 B" in d["ko"] and d["unit"]["state"] == "stop"
    r = d["rules"]
    assert (r["stop_atr"], r["atr_tf_ko"], r["atr_n"], r["first_trigger"], r["first_lock"], r["step"], r["liq_keep"]) == \
        (3, "15분봉", 14, pytest.approx(0.10), 0.08, 0.02, 0.15)
    assert r["words"].startswith("손절 15분봉 ATR(14) × 3 · 계단 익절 거래소 ROE 10%에서 8% 잠금")
    assert (r["basis"], r["roe_ko"]) == ("gross", "거래소 ROE")
    # systemctl not there: said, never the page's failure
    def boom(u):
        raise OSError("no systemctl")
    assert LG.build(1_800_000_000_000, boom)["unit"]["state"] == "unknown"


def test_a_refused_config_and_a_broken_state_are_said(tmp_path, monkeypatch):
    bad = tmp_path / "gateguard.json"
    bad.write_text(json.dumps({**json.loads(_read(CFG)), "stop_atr": -1}), encoding="utf-8")
    monkeypatch.setenv(LG.CONFIG_ENV, str(bad))
    monkeypatch.setenv(LG.STATE_ENV, str(tmp_path / "no-state.json"))
    d = LG.build(1_800_000_000_000, lambda u: RUN)
    assert d["state"] == "off" and d["rules"]["words"] is None and d["rules"]["refused_ko"]
    st = tmp_path / "state.json"
    st.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(LG.STATE_ENV, str(st))
    d = LG.build(1_800_000_000_000, lambda u: RUN)
    assert d["state"] == "error" and d["ko"] == "게이트 봇 상태 파일을 읽지 못했어요" and d["reason"]
    assert d["positions"] == [] and d["closed"] == [] and d["log"] == []


def test_a_real_state_from_the_bot(tmp_path, monkeypatch):
    state, now_s = _real_state()
    p = tmp_path / "gateguard.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv(LG.STATE_ENV, str(p))
    monkeypatch.setenv(LG.CONFIG_ENV, CFG)
    now = int(now_s * 1000) + 5_000
    d = LG.build(now, lambda u: RUN)
    assert d["state"] == "ok" and d["unit"]["ko"] == "돌고 있음"
    assert d["loop"]["fresh"] and d["loop"]["ago_s"] == pytest.approx(5.0, abs=1)
    assert (d["account"]["total"], d["account"]["available"]) == (100.0, 60.0)
    (pos,) = d["positions"]
    assert (pos["coin"], pos["side"], pos["side_ko"], pos["size"], pos["entry"], pos["lev"], pos["mark"]) == \
        ("BTC", 1, "롱", 10, 100.0, 20, 100.58)
    assert pos["guarded"] and not pos["cross"] and pos["upnl"] == pytest.approx(0.058)
    b = pos["bot"]
    assert (b["stop"], b["kind"], b["kind_ko"], b["atr"], b["atr_stop"], b["fee"]) == (100.5, "lock", "계단 잠금", 2.0, 94.0, 0.0005)
    assert b["lock"] == pytest.approx(0.10) and b["best"] == 100.6 and b["best_roe"] == pytest.approx(20 * 0.006)
    assert b["has_stop"] and not b["hands_off"] and not b["late"] and not b["closing"]
    # the ladder's next step: +12 % locked once Gate's own ROE reaches +14 %, at 100 x (1 + 0.14 / 20) (no fee taken off)
    assert b["next"]["lock"] == pytest.approx(0.12) and b["next"]["trigger"] == pytest.approx(0.14)
    assert b["next"]["price"] == pytest.approx(100.7)
    assert b["roe_now"] == pytest.approx(20 * 0.0058)
    assert pos["to_stop"] == pytest.approx((100.58 - 100.5) / 100.58) and "to_liq" not in pos     # (no liquidation price)
    (c,) = d["closed"]
    assert (c["coin"], c["side_ko"], c["entry"], c["exit"]) == ("BTC", "숏", 100.0, 99.0) and c["pnl"] > 0
    assert c["cause"].startswith("직접 종료") and c["end_ms"] and c["opened_ms"]
    assert d["totals"] == {"n": 1, "wins": 1, "losses": 0, "unknown": 0, "pnl": pytest.approx(c["pnl"])}
    assert d["log"] and d["log"][0]["ms"] >= d["log"][-1]["ms"] and any("잠금 거래소 ROE +10%" in x["text"] for x in d["log"])
    assert d["rules"]["words"]
    # an old loop: not "now"
    assert not LG.build(now + (LG.FRESH_S + 5) * 1000, lambda u: RUN)["loop"]["fresh"]


def test_positions_the_bot_does_not_hold_and_the_ones_it_still_does():
    rules = LG.rules_of(CFG)
    now = 1_800_000_000_000
    state = {"loop_s": now // 1000 - 20,
             "live": {"ETH_USDT": {"side": -1, "size": -3, "entry": 2500.0, "lev": 25, "liq": 2580.0, "mark": 2490.0, "cross": True,
                                   "margin": 3.0, "upnl": 0.3, "open_s": now // 1000 - 60}},
             "coins": {"SOL_USDT": {"side": 1, "size": 5, "entry": 150.0, "lev": 10, "liq": 0, "stop": 141.0, "kind": "atr", "atr": 1.0,
                                    "atr_stop": 141.0, "fee": 0.0005, "lock": None, "best": 150.0, "best_roe": None, "stop_id": None,
                                    "hands_off": True, "late": True, "open_s": now // 1000 - 7200, "seen_s": now // 1000 - 600}},
             "closed": [{"contract": "XRP_USDT", "side": 1, "entry": 1.0, "exit": 0.98, "pnl": -0.4, "end_s": now // 1000 - 900},
                        {"contract": "DOGE_USDT", "side": -1, "entry": 0.2, "exit": None, "pnl": None, "end_s": now // 1000 - 300}],
             "log": [{"s": now // 1000 - 100, "level": "INFO", "text": "a"}, {"s": now // 1000 - 50, "level": "WARN", "text": "b"}]}
    d = LG.view(state, rules, RUN, now)
    eth, sol = d["positions"]
    assert (eth["coin"], eth["side_ko"], eth["cross"], eth["guarded"]) == ("ETH", "숏", True, False) and "bot" not in eth
    assert eth["to_liq"] == pytest.approx(-(2490.0 - 2580.0) / 2490.0)
    assert (sol["coin"], sol["guarded"], sol["bot"]["hands_off"], sol["bot"]["late"], sol["bot"]["has_stop"]) == ("SOL", True, True, True, False)
    assert sol["bot"]["next"] == {"lock": 0.08, "trigger": pytest.approx(0.10), "price": pytest.approx(150 * (1 + 0.01))}
    # a config still on net ROE (both fees paid): the same rung 0.1 % further
    net = LG.view(state, {**rules, "basis": "net"}, RUN, now)["positions"][1]["bot"]["next"]
    assert net["price"] == pytest.approx(150 * (1 + 0.01 + 0.001))
    assert sol["mark"] is None and sol["bot"]["roe_now"] is None and "to_stop" not in sol and sol["liq"] is None
    assert [x["coin"] for x in d["closed"]] == ["DOGE", "XRP"]                   # newest first
    assert d["totals"] == {"n": 2, "wins": 0, "losses": 1, "unknown": 1, "pnl": -0.4}
    assert [x["text"] for x in d["log"]] == ["b", "a"] and "account" not in d
    assert not BAD.search(json.dumps(json_finite(d)).replace("null", "")) and LG.next_step(None, None) is None


def test_the_route_in_the_live_app_behind_its_login(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    from tests.test_livedash_app import PW, _app
    assert "livegate" in LA.MODULES
    monkeypatch.setenv(LG.STATE_ENV, str(tmp_path / "no-state.json"))
    monkeypatch.setenv(LG.CONFIG_ENV, CFG)
    c = TestClient(_app(tmp_path))
    assert c.get(LG.ROUTE).status_code in (401, 403)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get(LG.ROUTE)
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "off" and d["rules"]["words"] and set(d) >= {"now_ms", "unit", "rules", "positions", "closed", "log", "totals"}
    unit = _read(os.path.join(ROOT, "deploy", "paperbot-livedash.service"))
    assert "-/etc/paperbot/executor-gate.env" in unit.split("InaccessiblePaths=")[1].splitlines()[0]   # (never the Gate key)
    src = _read(os.path.join(ROOT, "paperbot", "dash", "more", "livegate.py"))
    assert "executor-gate" not in src and "GateClient" not in src and "KEY_NAMES" not in src


# ---------------------------------------------------------------- the screen in node
def _node(body: str, data=None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = (f"const T = await import('file://{DOM}');\n"
              f"const M = await import('file://{JS}');\n"
              f"const A = JSON.parse({json.dumps(json.dumps(data or {}))});\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


RENDER = """
const ctx = (d) => ({params: {query: {}}, alive: () => true, api: async (p) => { await null; if (!d) throw Object.assign(new Error("x"), {status: 0, kind: "network"}); return d; },
  every() {}, track() {}, listen() {}, watch() {}, on() {}, timeout() {}, href: (n, a) => '#/' + n + '/' + a});
const out = {};
for (const [k, d] of Object.entries(A)) {
  const v = M.gateView(ctx(d));
  await new Promise((r) => setTimeout(r, 30));
  const w = T.walk(v.el);
  out[k] = {text: w.text.replace(/\\s+/g, " "), cls: w.classes.join(" ")};
}
console.log(JSON.stringify(out));"""


def test_the_pure_functions():
    rules = LG.rules_of(CFG)
    out = _node("""console.log(JSON.stringify({
  roe: [M.netRoe(1, 100, 100.5, 20, 0.0005), M.netRoe(-1, 100, 106, 10, 0.0005), M.netRoe(1, 0, 1, 20, 0), M.netRoe(1, 100, null, 20, 0)],
  r0: M.rungs(A.rules, null).map((x) => [Math.round(x.trigger * 100), Math.round(x.lock * 100), x.on, x.next]),
  r2: M.rungs(A.rules, 0.12).map((x) => [Math.round(x.lock * 100), x.on, x.next]), rx: M.rungs(null, 0.1),
  tw: [M.toward(0.05, {trigger: 0.1}), M.toward(-0.2, {trigger: 0.1}), M.toward(0.3, {trigger: 0.1}), M.toward(null, {trigger: 0.1})],
  ko: [M.roeKo(0.08), M.roeKo(0.105), M.roeKo(null), M.agoS(12), M.agoS(185), M.agoS(3900)],
  why: [M.stopWhy({kind: "atr", atr: 2}, A.rules), M.stopWhy({kind: "liq", atr_stop: 94}, A.rules), M.stopWhy({kind: "lock", lock: 0.1}, A.rules),
        M.stopWhy({kind: "lock", lock: 0.1}, {...A.rules, basis: "net"})],
  rw: [M.roeWord(A.rules), M.roeWord({basis: "net"}), M.roeWord(null), M.ladderFee(A.rules, 0.0005), M.ladderFee({basis: "net"}, 0.0005)],
  st: [M.statusOf({state: "missing", ko: "설치 전 말", unit: {state: "off"}}), M.statusOf({state: "ok", unit: {state: "run"}, loop: {fresh: true, ago_s: 4}, rules: A.rules}),
       M.statusOf({state: "ok", unit: {state: "run"}, loop: {fresh: false, ago_s: 600}}), M.statusOf({state: "ok", unit: {state: "fail"}, loop: {fresh: false}}),
       M.statusOf({state: "ok", unit: {state: "stop"}, loop: {fresh: false}}), M.statusOf({state: "error", ko: "못 읽음 말", reason: "권한"})],
  w: [M.warnsOf({guarded: false}).length, M.warnsOf({guarded: true, bot: {hands_off: true, has_stop: false, late: true}}).map((x) => x.tone),
      M.warnsOf({guarded: true, bot: {has_stop: false, closing: true}}).map((x) => x.tone), M.warnsOf({guarded: true, bot: {has_stop: true}, to_liq: 0.01}).map((x) => x.tone),
      M.warnsOf({guarded: true, bot: {has_stop: true}, to_liq: 0.2}).length],
  t: [M.totalsKo({n: 0}), M.totalsKo({n: 3, wins: 2, losses: 1, unknown: 0, pnl: 1.2}), M.totalsKo({n: 2, wins: 0, losses: 1, unknown: 1, pnl: -0.4})],
}));""", {"rules": rules})
    assert out["roe"][0] == pytest.approx(20 * (0.005 - 0.001)) and out["roe"][1] == pytest.approx(10 * (-0.06 - 0.001))
    assert out["roe"][2] is None and out["roe"][3] is None
    assert out["r0"] == [[10, 8, False, True], [12, 10, False, False], [14, 12, False, False], [16, 14, False, False], [18, 16, False, False]]
    assert out["r2"][:4] == [[8, True, False], [10, True, False], [12, True, False], [14, False, True]] and len(out["r2"]) == 5
    assert out["rx"] == [] and out["tw"] == [0.5, 0, 1, None]
    assert out["ko"] == ["+8%", "+10.5%", "—", "12초 전", "3분 전", "1시간 5분 전"]
    assert out["why"] == ["15분봉 ATR 2.0000 × 3", "15분봉 ATR × 3 자리 94.00가 청산가 너머라 청산가 안쪽으로 당김", "계단 잠금 거래소 ROE +10%",
                          "계단 잠금 순ROE +10%"]
    assert out["rw"] == ["거래소 ROE", "순ROE", "순ROE", 0, 0.0005]
    st = out["st"]
    assert (st[0]["pill"], st[0]["line"]) == ("설치 전", "설치 전 말")
    assert st[1]["tone"] == "good" and st[1]["pill"] == "지키는 중" and "10초마다" in st[1]["line"] and "4초 전" in st[1]["line"]
    assert st[2]["pill"] == "확인 늦음" and "10분 전" in st[2]["line"]
    assert st[3]["tone"] == "bad" and "이미 걸린 손절 주문은 게이트에 그대로 남아 있어요" in st[3]["line"]
    assert st[4]["pill"] == "꺼져 있음" and st[5] == {"tone": "bad", "pill": "못 읽음", "line": "못 읽음 말 (권한)"}
    assert out["w"] == [1, ["bad"], ["warn", "warn"], ["bad"], 0]                # (a late one the bot let go: only 손 뗌)
    assert out["t"][0] == "아직 끝난 포지션이 없어요"
    assert out["t"][1] == "끝난 포지션 3개 · 이익 2 · 손실 1 · 합계 +1.20 USDT (게이트 기록 · 수수료 포함)"
    assert "손익 모름 1" in out["t"][2] and "−0.40 USDT" in out["t"][2]


def test_the_screen_renders_each_answer(tmp_path, monkeypatch):
    state, now_s = _real_state()
    p = tmp_path / "gateguard.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv(LG.STATE_ENV, str(p))
    monkeypatch.setenv(LG.CONFIG_ENV, CFG)
    real = json_finite(LG.build(int(now_s * 1000) + 5_000, lambda u: RUN))
    off = json_finite(LG.view(None, LG.rules_of(CFG), ("inactive", "disabled"), 1_800_000_000_000))
    missing = json_finite(LG.view(None, None, ("inactive", "not-found"), 1_800_000_000_000))
    flat = json_finite(LG.view({"loop_s": 1_800_000_000 - 3, "account": {"total": 50, "available": 50}}, LG.rules_of(CFG), RUN,
                               1_800_000_000_000))
    out = _node(RENDER, {"real": real, "off": off, "missing": missing, "flat": flat, "down": None})
    t = out["real"]["text"]
    assert not BAD.search(t), BAD.search(t)
    for w in ("게이트 봇", "지키는 중", "돌고 있음", "100.00 USDT", "주문 가능 60.00 USDT", "1 / 1", "규칙", "BTC", "롱", "20배", "격리",
              "봇이 지킴", "미실현 (게이트)", "+0.06 USDT", "평단", "100.00", "마크가", "100.58", "청산가", "없음 · 못 읽음", "봇 손절",
              "100.50", "계단 잠금 거래소 ROE +10%", "닿으면 거래소 ROE +10.0% (수수료 빼기 전 어림)", "계단 익절", "지금 거래소 ROE +11.6%",
              "최고 +12%", "→ +8%", "→ +12%", "다음: 거래소 ROE +14% (가격 100.70)에 닿으면 손절을 거래소 ROE +12% 자리로 올려요",
              "끝난 포지션", "끝난 포지션 1개 · 이익 1 · 손실 0", "숏", "100.00 → 99.00", "직접 종료", "최고 거래소 ROE", "봇 메시지",
              "잠금 거래소 ROE +10%", "보기만 하는 화면"):
        assert w in t, w
    assert "순ROE" not in t                                    # (the repo's config: Gate's own ROE everywhere)
    assert "lgt-rung on" in out["real"]["cls"] and "lgt-rung next" in out["real"]["cls"] and "lgt-stop lock" in out["real"]["cls"]
    assert "lgt-status good" in out["real"]["cls"] and "lgt-pos long" in out["real"]["cls"]
    for k, words in (("off", ("아직 켜기 전이에요", "4장 B", "sudo systemctl start paperbot-gateguard", "규칙", "꺼져 있음")),
                     ("missing", ("아직 설치 전이에요", "4장 A", "git pull && sudo bash deploy/install.sh", "sudoedit /etc/paperbot/executor-gate.env", "설치 전")),
                     ("flat", ("열린 포지션 없음", "친구가 게이트에서 진입하면", "0 / 0", "50.00 USDT", "아직 끝난 포지션이 없어요", "아직 메시지가 없어요"))):
        t = out[k]["text"]
        assert not BAD.search(t), (k, BAD.search(t))
        for w in words:
            assert w in t, (k, w)
    assert "다시" in out["down"]["text"] or "연결" in out["down"]["text"] or "못" in out["down"]["text"]
    assert not BAD.search(out["down"]["text"])


# ---------------------------------------------------------------- static
def test_tokens_only_imports_through_pb_and_read_only():
    css, js = _read(CSS), _read(JS)
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", body)
    for m in re.finditer(r"font-size\s*:\s*([^;}]+)", body):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    tok = _read(os.path.join(V4, "tokens.css"))
    used = set(re.findall(r"var\((--[\w-]+)", body))
    defined = set(re.findall(r"(--[\w-]+)\s*:", tok)) | set(re.findall(r"(--[\w-]+)\s*:", _read(os.path.join(V4, "base.css"))))
    assert used - {"--v", "--sc"} <= defined, used - {"--v", "--sc"} - defined
    sels = [r.strip() for r in re.findall(r"([^{}]+)\{", body) if r.strip() and not r.strip().startswith(("@", "from", "to", "50%"))]
    assert all(".lgt" in r for r in sels), [r for r in sels if ".lgt" not in r]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", re.sub(r"//[^\n]*", "", js)) and not re.search(r"\d+px", js)
    assert re.findall(r'from\s+"([^"]+)"', js) == ["../core/pb.js"]
    assert "innerHTML" not in js and "fetch(" not in js and "POST" not in js and "post(" not in js
    assert 'export const GATE_API = "/api/v4/livebots/gate";' in js and LG.ROUTE == "/api/v4/livebots/gate"


def test_the_menu_the_tab_and_its_hud():
    routes, lb = _read(os.path.join(V4, "core", "routes.js")), _read(os.path.join(SCREENS, "livebots.js"))
    assert '{id: "gate", ko: "게이트 봇", screens: ["gatebot"]},' in routes
    assert re.search(r'gatebot: \{ko: "게이트 봇", group: "gate", title: "게이트 봇 \(', routes) and "gatebot: ICON.gate," in routes
    assert 'import {gateView} from "./livebots-gate.js";' in lb
    assert '{id: "gatebot", label: "게이트 봇", make: (ctx) => gateView(ctx), own: true},' in lb
    assert '"mixrangeperf", "gatebot"]);' in lb and "gatebot: {bot: null," in lb and "const goal = bt && bt.bot ? goalResSlot(bt.bot) : null;" in lb
    assert '@import url("livebots-gate.css");' in _read(os.path.join(SCREENS, "livebots.css"))
    assert "gatebot:" in _read(os.path.join(V4, "core", "search.js"))
    assert ".botbar { grid-template-columns: repeat(5, minmax(0, 1fr)); }" in _read(os.path.join(ROOT, "paperbot", "dash", "static", "live", "live.css"))
    assert "livebots-gate.js" in _read(os.path.join(V4, "INVENTORY.md"))
