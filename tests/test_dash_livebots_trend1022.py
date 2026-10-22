"""실거래 site with the 추세판단 봇's 10/22 design (owners 10/22; deploy/combo.trend.json: 18 entry members, a 4h entry
judged on the closed daily bar, 보류 허용 ``trend.hold_entry``, 바로 진입 ``trend.pullback_wait`` false; the pullback wait
only in the shadow trend-wait):
- the constants: TREND_HTF / TREND_TF_KO / TREND_TF_SUB_KO for 4h -> 1d, every member of the config has its role
  (F7_RF_TRIPLE: the new role 추세), the 10/21 members keep theirs (their old trades still show a role);
- 관제 (livetrend) on the bot's own code (tests/test_trendbot.py's World with the new design): every coin's 1h, 4h and daily
  judgment, the 4h member read on the daily bar, the directions taken now (보류 허용: a 보류 with strength takes both
  sides), the 4h long that entered at its own minute on a daily 보류 (``entry_held``: 보류 진입), today's funnel with the
  바로 진입 counted as passed and no pullback touched; the 추세 차트 and the 일지 call that signal entered;
- the wording follows trend.pullback_wait, both ways: 진입 가능성's note, 못 탄 신호's note, 검토's pullback tiles, the
  replay's design note and its live funnel, the pending closes (바로 진입 vs 되돌림 진입);
- the views in node: the map's daily column, 보류 진입, the waits card / funnel / empty position words, and the pure
  helpers of 일지 · 검토 · 진입 가능성 · 설정 · 추세 차트."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_livetrend as TL  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot import trendjudge as TJ  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livejournal as J  # noqa: E402
from paperbot.dash.more import livemissed as M  # noqa: E402
from paperbot.dash.more import livereplayref as X  # noqa: E402
from paperbot.dash.more import livereview as LR  # noqa: E402
from paperbot.dash.more import livetrend as LT  # noqa: E402
from paperbot.dash.more import livetrendchart as TC  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
DEPLOY = os.path.join(ROOT, "deploy")
MIN, HOUR = T.MIN, T.HOUR
# the owners' 10/22 design, as deploy/combo.trend.json sets it (no 시간 정리 since 10/21 night)
NEW = {"time_bars": None, "hold_entry": True, "pullback_wait": False, "design": "2026-10-22"}
HOLD = {"V39": 0, "S6": 0, "OBV": 0, "N12": 0}
# the owners' roles of the 18 members (10/22) and of the 10/21 members that left (their trades keep a role)
ROLES_1022 = {"N06_MACD_ORB": "돌파", "S3_CMO_SANDWICH": "횡보", "N05_PSAR_POC": "자리", "F16_FIB382": "자리", "F16_FIB500": "자리",
              "F16_FIB618": "자리", "F16_FIB764": "자리", "V39_ALL": "눌림", "F9_IFVG": "자리", "F6_VWAP_FAIL": "자리", "F3_BOS": "돌파",
              "F15_ORB": "돌파", "F10_OTE": "자리", "F9_OB": "자리", "F7_RF_TRIPLE": "추세"}
ROLES_1021 = {"N08_ICHI_WR": "눌림", "F9_FVG": "눌림", "N20_EMA9_CHOP": "횡보"}


def _cfg(name: str) -> dict:
    with open(os.path.join(DEPLOY, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


def _world_new(tmp_path):
    """The trend bot on the 10/22 design (its own code, a fake judge): a 30m member and a 4h one; BTC's daily bar is 보류
    (상승 유지 확인 중): the 4h long enters at its own minute on it. -> (world, B: the 4h signal's close)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    w = T.World(tmp_path, members=[{"strategy": "N08_ICHI_WR", "tf": "30m"}, {"strategy": "S3_CMO_SANDWICH", "tf": "4h"}], trend=NEW)
    w.store.put_state("combo_run", T.T0, {"config": json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))})
    w.judge.j[("BTCUSDT", "1d")] = T.J(dir=0, raw=1, votes=HOLD, tf="1d")
    w.judge.s[("BTCUSDT", "4h")] = T.S(tf="4h")
    T._start(w)
    B = T.T0 + 4 * HOUR
    w.add_minutes(T.T0, 240)
    w.signal("S3_CMO_SANDWICH", "BTCUSDT", 1, B, tf="4h")
    w.step(B)
    w.store.commit()
    assert w.engine().position is not None and w.engine().position.entry_time == B
    return w, B


# ================================================================ the constants
def test_the_design_constants():
    assert L.TREND_HTF == {"30m": "1h", "1h": "4h", "4h": "1d"} == TJ.HTF_OF and LT.HTF_OF == L.TREND_HTF
    assert L.TREND_TF_KO["4h"] == "4시간 진입" and L.TREND_TF_SUB_KO["4h"] == "끝난 일봉 추세로 판단"
    assert L.TREND_JUDGED_TFS == ("1h", "4h", "1d") and L.TREND_ENTRY_OF == {"1h": "30m", "4h": "1h", "1d": "4h"}
    assert L.TF_KO["1d"] == "일봉" and L.TF_ORDER["1d"] > L.TF_ORDER["4h"] and TC.TFS == L.TREND_JUDGED_TFS
    # every member of the live config and of the shadow has its role, in the owners' words; the 10/21 ones keep theirs
    for name in ("combo.trend.json", "combo.shadow-trend-wait.json"):
        ms = _cfg(name)["members"]
        assert len(ms) == 18 and {m["strategy"]: L.TREND_ROLE[m["strategy"]] for m in ms} == ROLES_1022
    assert {k: L.TREND_ROLE[k] for k in ROLES_1021} == ROLES_1021
    assert L.TREND_ROLES == ("눌림", "자리", "돌파", "횡보", "추세") and set(L.TREND_ROLE.values()) <= set(L.TREND_ROLES)
    assert "하이킨아시" in L.TREND_ROLE_SUB_KO["추세"] and set(L.TREND_ROLE_SUB_KO) == set(L.TREND_ROLES)
    # the breakout members (early trend only) are the 돌파 role
    assert set(_cfg("combo.trend.json")["trend"]["breakout"]) == {k for k, v in ROLES_1022.items() if v == "돌파"}
    # the entry style: the live config enters at once, the shadow waits, a config without the key waits (10/21)
    assert L.trend_waits(_cfg("combo.trend.json")) is False and L.trend_waits(_cfg("combo.shadow-trend-wait.json")) is True
    assert L.trend_waits({"trend": {}}) is True and L.trend_waits(None) is True
    assert LT.entry_style(_cfg("combo.trend.json")) == {"pullback_wait": False, "hold_entry": True}
    assert LT.entry_style({"trend": {}}) == {"pullback_wait": True, "hold_entry": False}
    assert LT.entry_style({"trend": {}}, {"pullback_wait": False, "hold_entry": True}) == {"pullback_wait": False, "hold_entry": True}


def test_held_of_reads_the_flag_else_the_words():
    assert LT.held_of({"held": True}) is True and LT.held_of({"held": False, "judge": "일봉 보류(…)"}) is False
    # a closed trade's context keeps only the judgment's words (trendbot ctx)
    assert LT.held_of({"judge": "일봉 보류(상승 유지 확인 중)(상승 0·하락 0·중립 4, ADX 25 오름)"}) is True
    assert LT.held_of({"judge": "1시간 보류(상승 2·하락 1·중립 1, ADX 22 오름)"}) is True
    assert LT.held_of({"judge": "1시간 상승(상승 3·하락 1·중립 0, ADX 27 오름)"}) is False
    assert LT.held_of({"judge": {"text": "4시간 보류(…)"}}) is True and LT.held_of({}) is False and LT.held_of(None) is False


# ================================================================ 관제 on the new design
def test_the_answer_on_the_new_design(tmp_path):
    w, B = _world_new(tmp_path)
    d = LT.build({"paper": w.cfg.db}, B + 2 * MIN)
    assert d["state"] == "ok" and d["pullback_wait"] is False and d["hold_entry"] is True and d["waits"] == []
    assert all(set(row) == {"1h", "4h", "1d"} for row in d["coins"].values())
    assert d["coins"]["BTCUSDT"]["1d"]["text"].startswith("일봉 보류(상승 유지 확인 중)")
    # the 4h long: read on the daily bar, entered on its 보류 (보류 진입), the supervisor watches the daily bar
    p = d["position"]
    assert (p["tf"], p["htf"], p["entry_held"], p["role"]) == ("4h", "1d", True, "횡보")
    assert p["entry_judge"].startswith("일봉 보류") and p["judge"]["tf"] == "1d" and p["judge_against"] is False
    assert [(m["label"], m["htf"]) for m in d["members"]] == [("N08_ICHI_WR@30m", "1h"), ("S3_CMO_SANDWICH@4h", "1d")]
    # today's funnel: the 바로 진입 passed the checks, nothing waited for a pullback
    f = d["funnel"]
    assert (f["signals"], f["passed"], f["touched"], f["entered"], f["blocked"]) == (1, 1, 0, 1, [])
    (row,) = d["signals"]["rows"]
    assert (row["cat"], row["cat_ko"]) == ("submitted", "바로 진입 신호") and "바로 진입 (보류지만 반대 아님)" in row["why"]
    # the directions taken now: the members' bars only (30m -> 1h, 4h -> 1d; no 1h member, so no 4h judgment), a
    # strong 보류 both ways (side 0)
    tk = LT.trend_now(w.cfg.db)
    assert tk["pullback_wait"] is False and tk["hold_entry"] is True
    assert {x["htf"] for x in tk["taking"]} == {"1h", "1d"}
    assert {"symbol": "BTCUSDT", "htf": "1d", "entry": "4h", "side": 0} in tk["taking"]
    # without 보류 허용 the same 보류 takes nothing, and a judged bar no member reads is left out only when told
    st = {"coins": {"BTCUSDT": {"1h": {"dir": 0, "strong": True}, "4h": {"dir": 1, "strong": True}, "1d": {"dir": 0, "strong": True}}}}
    assert LT.taking_now(st) == [{"symbol": "BTCUSDT", "htf": "4h", "entry": "1h", "side": 1}]
    assert [x["htf"] for x in LT.taking_now(st, hold=True)] == ["1h", "4h", "1d"]
    assert LT.taking_now(st, {"30m"}, True) == [{"symbol": "BTCUSDT", "htf": "1h", "entry": "30m", "side": 0}]
    weak = {"coins": {"BTCUSDT": {"1d": {"dir": 0, "strong": False}}, "ETHUSDT": {"1d": {"dir": 0, "strong": True, "tired": True}}}}
    assert LT.taking_now(weak, hold=True) == []


def test_the_chart_and_the_journal_call_a_new_design_entry_entered(tmp_path):
    w, B = _world_new(tmp_path)
    conn = L.open_ro(w.cfg.db)
    try:
        sigs = TC.signals_of(conn, "BTCUSDT", B + 5 * MIN, {B}, T.T0)
    finally:
        conn.close()
    (s,) = sigs
    assert (s["kind"], s["kind_ko"], s["cat_ko"], s["entry_time"]) == ("entered", "진입", "바로 진입 신호", B)
    # another coin's entry at that minute is not this one's: not taken (an older minute: decided)
    conn = L.open_ro(w.cfg.db)
    try:
        assert TC.signals_of(conn, "BTCUSDT", B + 5 * MIN, set(), T.T0)[0]["kind"] == "other"
        assert TC.signals_of(conn, "BTCUSDT", B + MIN, set(), T.T0)[0]["kind"] == "pending"      # its own minute: not yet
    finally:
        conn.close()
    # the 일지: one signal, passed the checks on a 보류, entered; no pullback waited for
    pr = J.read_paper(w.cfg.db, T.T0, B + 5 * MIN)
    ev, c = J.signal_events(pr["rows"], pr["outs"], B + 5 * MIN)
    (e,) = ev
    assert e["text"].startswith("BTC 롱 신호 · 점검 통과 (보류 진입) → ") and e["text"].endswith("진입") and e["held"] is True
    assert (c["signals"], c["passed"], c["waits"], c["touched"]) == (1, 1, 0, 0)
    tev, _tc = J.trade_events(pr["trades"], pr["positions"], pr["entered"], T.T0, pr["since"])
    opened = next(x for x in tev if x.get("open") and not x.get("twin"))
    assert "보류 진입" in opened["detail"] and "일봉 보류" in opened["detail"] and "되돌림" not in opened["detail"]


def test_a_held_trade_closes_and_says_so(tmp_path, monkeypatch):
    """The 4h long entered on the daily 보류 closes when the next daily bar is down (감독 청산): 관제's trade, 지도's
    judgment cut, 일지's entry line and the 관제 view say it went in on a 보류."""
    w, B = _world_new(tmp_path)
    w.judge.j[("BTCUSDT", "1d")] = T.J(dir=-1, tf="1d")
    T._to(w, B + MIN, T.T0 + T.DAY + MIN)
    w.store.commit()
    (t,) = w.trades()
    assert t["exit_reason"] == "JUDGE" and t["exit_time"] == T.T0 + T.DAY
    now = T.T0 + T.DAY + 2 * MIN
    d = LT.build({"paper": w.cfg.db}, now)
    (x,) = d["trades"]
    assert x["entry_held"] is True and x["entry_judge"].startswith("일봉 보류") and d["record"]["n"] == 1
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    no = str(tmp_path / "none")
    p = {"paper": w.cfg.db, "paper2": no + "-p2.db", "bybit_db": no + "-b.db", "mexc_db": no + "-m.db",
         "bybit_config": no + "-b.json", "mexc_config": no + "-m.json"}
    m = L.map_view(p, now)
    assert [(r["key"], r["label"], r["n"]) for r in m["cuts"]["judge"]] == [
        ("4", "4개 모두 같은 쪽", 0), ("3", "4개 중 3개", 0), ("0", "4개 중 0개 (보류 진입)", 1)]
    assert [(r["key"], r["label"], r["n"]) for r in m["cuts"]["tf"]] == [("30m", "30분 진입", 0), ("4h", "4시간 진입", 1)]
    pr = J.read_paper(w.cfg.db, T.T0, now)
    tev, _c = J.trade_events(pr["trades"], pr["positions"], pr["entered"], T.T0, pr["since"])
    e_in = next(e for e in tev if e["sub"] == "entry" and not e.get("twin"))
    assert e_in["detail"].startswith("보류 진입 · 일봉 보류")
    out = TL._node(TL.VIEW, json.loads(json.dumps(d)))
    assert "진입 때 일봉 보류" in out["text"] and "(보류 진입)" in out["text"]


# ================================================================ the words follow trend.pullback_wait (both ways)
def test_the_notes_follow_the_entry_style(tmp_path):
    w, _B = _world_new(tmp_path / "new")
    (tmp_path / "old").mkdir()
    old = TL._world(tmp_path / "old")                       # the 10/21 design's world: waits for its pullback
    old.store.commit()
    tb_new, tb_old = L.trend_bot(w.cfg.db), L.trend_bot(old.cfg.db)
    assert L.trend_out(tb_new)["pullback_wait"] is False and L.trend_out(tb_new)["hold_entry"] is True
    assert L.trend_out(tb_old)["pullback_wait"] is True and L.trend_out(tb_old)["hold_entry"] is False
    n_new, n_old = L.likely_trend_note(tb_new), L.likely_trend_note(tb_old)
    assert "추세 판단(1시간·일봉 추세)·진입 전 검사를 통과해야" in n_new and "되돌림" not in n_new
    assert "추세 판단(1시간·4시간 추세)·진입 전 검사·되돌림을 모두 통과해야" in n_old
    assert "되돌림" not in M.trend_filter_note(tb_new) and M.trend_filter_note(tb_old) == M.TREND_FILTER_NOTE_KO
    # 설정 says the members' entry by the config
    assert L.trend_rules(tb_new)["pullback_wait"] is False and L.trend_rules(tb_old)["pullback_wait"] is True
    assert [r["n"] for r in L.trend_rules(tb_new)["roles"]] == [1, 0, 0, 1, 0]          # 눌림 N08 · 횡보 S3


def test_the_pending_closes_follow_the_entry_style(tmp_path):
    w, B = _world_new(tmp_path)
    members = [{"tf": "30m"}, {"tf": "4h"}]
    now = B + 10 * MIN
    at_once = L.pending({"paper": w.cfg.db}, now, members, trend=True, pull=False)
    assert at_once["waits"] == [] and [(c["tf"], c["now"], c["pull"]) for c in at_once["closes"]] == [("30m", 1, 0), ("4h", 1, 0)]
    waits = L.pending({"paper": w.cfg.db}, now, members, trend=True, pull=True)
    assert [(c["tf"], c["now"], c["pull"]) for c in waits["closes"]] == [("30m", 0, 1), ("4h", 0, 1)]
    assert waits["closes"][1]["next_ms"] == B + 4 * HOUR


def test_the_review_tiles_follow_the_entry_style(tmp_path):
    w, B = _world_new(tmp_path / "new")
    d = LR.build({"paper": w.cfg.db}, B + 10 * MIN, more={"rule_db": w.cfg.paper_db}, budget_s=0.5)
    assert d["state"] == "ok" and d["pullback_wait"] is False and d["hold_entry"] is True
    assert (d["funnel"]["signals"], d["funnel"]["passed"], d["funnel"]["touched"], d["funnel"]["entered"]) == (1, 1, 0, 1)
    items = {x["id"]: x for x in d["whatif"]["items"]}
    assert items["trend"]["rule_ko"] == LR.TREND_HOLD_RULE_KO and "4시간 진입은 일봉" in items["trend"]["rule_ko"]
    for wid in ("nopull", "pull"):
        assert items[wid]["off"] is True and items[wid]["rule_ko"] == LR.PULL_OFF_RULE_KO[wid] and items[wid]["n"] == 0
    assert items["pull"]["verdict"] in ({"kind": "off", "ko": LR.PULL_OFF_KO}, {"kind": "na", "ko": items["pull"]["verdict"]["ko"]})
    assert d["split"]["tf"] == [] and [r["id"] for r in d["split"]["role"]] == []                # the long is still open
    # the 10/21 design's world: the tiles as before (it waits; 보류 = no entry)
    (tmp_path / "old").mkdir()
    old = TL._world(tmp_path / "old")
    old.store.commit()
    o = LR.build({"paper": old.cfg.db}, T.T0 + HOUR + 2 * MIN, more={"rule_db": old.cfg.paper_db}, budget_s=0.5)
    oi = {x["id"]: x for x in o["whatif"]["items"]}
    assert o["pullback_wait"] is True and "off" not in oi["nopull"] and "off" not in oi["pull"]
    assert oi["trend"]["rule_ko"] == next(r for wid, _k, r, _h in LR.WHATIF if wid == "trend")


def test_the_replay_says_its_design_differs():
    ref = X.load_ref()
    if ref.get("state") != "ok":
        pytest.skip(ref.get("reason_ko"))
    d = ref["d"]
    note = X.design_note_ko(d, _cfg("combo.trend.json"))
    assert note.startswith("재현은 10/21 설계(진입 매매법 10개 · 30분·1시간 진입 · 보류면 진입 안 함 · 되돌림 기다림)로 돌린 숫자예요")
    for w in ("진입 매매법 18개", "4시간 진입(끝난 일봉 판단)", "보류 허용", "바로 진입(되돌림 안 기다림)", "참고로만"):
        assert w in note, w
    assert X.design_note_ko(d, {"trend": {"time_bars": None}, "members": [{"strategy": "X", "tf": "30m"}]}) is None
    assert "보류 허용" in LT.expect_of(_cfg("combo.trend.json"))["note_ko"]
    # the live funnel: no pullback stage for a config that enters at once (never a 0), its entries out of the checks passed
    f = {"signals": 10, "passed": 4, "touched": 0, "entered": 2, "blocked": []}
    live = X.funnel_view(d, f, 0, True, pull=False)["live"]
    assert live[3]["n"] is None and live[3]["why_ko"] == X.NO_PULL_KO and live[4]["of_prev"] == 0.5
    assert X.funnel_view(d, f, 0, True)["live"][3]["n"] == 0


# ================================================================ the views in node
def test_the_trend_view_on_the_new_design(tmp_path):
    w, B = _world_new(tmp_path)
    d = json.loads(json.dumps(LT.build({"paper": w.cfg.db}, B + 2 * MIN)))
    out = TL._node(TL.VIEW, d)
    t = out["text"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in t, bad
    # the map: the columns the members read (1h for 30m, the daily bar for 4h), 보류 허용 taking both sides
    for words in ("1시간 → 30분 진입", "일봉 → 4시간 진입", "4시간 롱·숏 (보류 허용)", "30분 진입은 1시간, 4시간 진입은 일봉",
                  "보류여도 반대 방향만 아니면 진입", "BTC 롱 보유 중", "진입 근거", "보류 진입", "일봉 보류", "🧭 일봉 추세",
                  "진입 매매법 2개", "4시간 진입 · 일봉 추세", "다음 진입", "바로 진입 신호 1"):
        assert words in t, words
    for words in ("4시간 → 1시간 진입", "되돌림 기다리는 신호", "되돌림 닿음", "일봉봉"):
        assert words not in t, words
    # no position: what it does next, in the config's words
    out = TL._node(TL.VIEW, {**d, "position": None})
    t = out["text"]
    assert "검사를 통과하면 그 분에 바로 들어가요 (한 번에 하나 · 보류여도 반대 방향만 아니면 받아요)" in t
    assert "되돌림 가격에 닿으면" not in t and "지금 들어갈 신호 없음 · 검사를 통과한 신호는 그 분에 바로 들어가요" in t
    assert "4시간봉" in t and out["hero"]["cls"] == "go"


def _node(tmp_path, body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    mods = "".join(f"const {n} = await import('file://{SCREENS}/livebots-{f}.js');\n"
                   for n, f in (("TR", "trend"), ("JR", "journal"), ("RV", "review"), ("LK", "likely"), ("MO", "more"), ("TCH", "tchart")))
    script = f"const D = await import('file://{dom}');\n" + mods + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_pure_helpers_follow_the_design(tmp_path):
    out = _node(tmp_path, """const R = {adx_min: 20, adx_tired: 40};
    const cell = (kind, o) => ({t: 0, dir: 0, raw: 1, up: 3, dn: 1, adx: 27.4, adx_prev: 25, votes: [1, 1, 1, -1], kind, ...o});
    const counts = {signals: 3, passed: 2, waits: 0, touched: 0, waiting: 0, entered: 1, closed: 0, pnl: 0, changes: 1};
    console.log(JSON.stringify({
      allows: [TR.allows({dir: 0, strong: true}, "1d", true), TR.allows({dir: 0, strong: false}, "1d", true),
        TR.allows({dir: 0, strong: true, tired: true}, "1h", true), TR.allows({dir: 0, strong: true}, "1d", false),
        TR.allows({dir: -1, strong: true}, "1d", true)],
      judged: [TR.judgedTfs({members: [{tf: "30m", htf: "1h"}, {tf: "4h", htf: "1d"}]}), TR.judgedTfs({coins: {BTCUSDT: {"1h": {}, "4h": {}, "1d": {}}}}),
        TR.judgedTfs({})],
      taking: TR.takingNow({hold_entry: true, members: [{tf: "4h", htf: "1d"}], coins: {BTCUSDT: {"1d": {dir: 0, strong: true}, "1h": {dir: 1, strong: true}}}}),
      against: TR.againstKo({htf: "1d", entry_time: 2 * 3600000}, {bar_close: 2 * 3600000}),
      line: [JR.countLine({state: "ok", counts, pullback_wait: false}).map((c) => c.id), JR.countLine({state: "ok", counts, pullback_wait: true}).map((c) => c.id),
        JR.countLine({state: "ok", counts: {...counts, waits: 2}, pullback_wait: false}).map((c) => c.id),
        JR.countLine({state: "ok", counts, pullback_wait: false}).find((c) => c.id === "passed").title],
      parts: [RV.funnelParts({signals: 10, passed: 4, touched: 0, entered: 2}, 10, false).map((p) => [p.k, p.n]),
        RV.funnelParts({signals: 10, passed: 4, touched: 3, entered: 2}, 10).map((p) => [p.k, p.n]),
        RV.funnelParts({signals: 10, passed: 4, touched: 0, entered: 2}, 10).map((p) => [p.k, p.n])],
      pull: [RV.pullOf({pullback_wait: false, funnel: {touched: 0}}), RV.pullOf({pullback_wait: false, funnel: {touched: 2}}), RV.pullOf({}), RV.pullOf(null)],
      take: LK.takingKo([{symbol: "BTCUSDT", entry: "4h", side: 0}, {symbol: "ETHUSDT", entry: "30m", side: -1}, {symbol: "SOLUSDT", entry: "1h", side: 1}]),
      none: [LK.takingNoneKo(true), LK.takingNoneKo(false)],
      entry: [MO.entryKo({entry_ko: "즉시"}, {pullback_wait: false}), MO.entryKo({entry_ko: "즉시"}, {pullback_wait: true}), MO.entryKo({entry_ko: "즉시"}, null)],
      cell: [TCH.cellInfo(cell("hold up"), "1d", {...R, hold_entry: true}).allow, TCH.cellInfo(cell("hold up", {adx: 15}), "1d", {...R, hold_entry: true}).allow,
        TCH.cellInfo(cell("hold up", {adx: 45, adx_prev: 50}), "4h", {...R, hold_entry: true}).allow, TCH.cellInfo(cell("hold up"), "1d", R).allow,
        TCH.cellInfo(cell("up", {dir: 1}), "1d", R).allow],
      judgedRows: TCH.JUDGED}));""")
    assert [a["ko"] for a in out["allows"]] == ["4시간 롱·숏 (보류 허용)", "4시간 쉼 · 힘 약함", "30분 쉼 · 끝물", "4시간 쉼 · 보류", "4시간 숏만"]
    assert out["allows"][0]["both"] is True and [a["side"] for a in out["allows"]] == [0, 0, 0, 0, -1]
    assert out["judged"] == [["1h", "1d"], ["1h", "4h", "1d"], ["1h", "4h"]]
    assert out["taking"] == ["BTC 4시간 롱·숏 (보류 허용)"]                       # only the bar the 4h member reads
    assert out["against"].endswith("에 끝나는 일봉도 반대면 감독 청산")
    assert "waits" not in out["line"][0] and "waits" in out["line"][1] and "waits" in out["line"][2]   # (waits left: shown)
    assert out["line"][3] == "추세 판단과 진입 자리 검사를 통과 (그 분에 바로 진입해요)"
    assert out["parts"][0] == [["entered", 2], ["passed", 2], ["stopped", 6]]
    assert out["parts"][1] == [["entered", 2], ["touched", 1], ["passed", 1], ["stopped", 6]]
    assert out["parts"][2] == [["entered", 0], ["touched", 0], ["passed", 4], ["stopped", 6]]          # (a config that waits)
    assert out["pull"] == [False, True, True, True]
    assert out["take"] == ["BTC 4시간 진입 롱·숏 (보류 허용)", "ETH 30분 진입 숏만", "SOL 1시간 진입 롱만"]
    assert out["none"] == ["모든 코인이 힘 약함·끝물이에요", "모든 코인이 보류·힘 약함·끝물이에요"]
    assert out["entry"] == ["바로 진입", "되돌림 진입", "즉시"]
    assert out["cell"] == [{"side": 0, "both": True, "ko": "4시간 롱·숏 (보류 허용)"}, {"side": 0, "ko": "4시간 쉼 · 힘 약함"},
                           {"side": 0, "ko": "1시간 쉼 · 끝물"}, {"side": 0, "ko": "4시간 쉼 · 보류"}, {"side": 1, "ko": "4시간 롱만"}]
    assert out["judgedRows"] == ["1h", "4h", "1d"]


def test_static():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    for f in ("trend", "tchart", "journal", "review", "likely", "more", "rank", "hq", "expect", "signals"):
        r = subprocess.run([node, "--check", os.path.join(SCREENS, f"livebots-{f}.js")], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (f, r.stderr)
