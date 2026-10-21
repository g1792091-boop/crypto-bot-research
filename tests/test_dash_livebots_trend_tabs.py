"""실거래 site with the 추세판단 봇 running (owners 10/21; docs/trend-bot-ko.md): the older tabs (성적 · 지도 · 목표 · 규칙 점검 ·
순위 · 설정, and the bits of 거래 · 못 탄 신호 · 터미널 that named the old bot) say what is true for the new bot.

On the trend bot's own world (tests/test_livetrend.py ``_world``: TrendRunner wrote the database: one long entered after
its pullback and closed by the supervisor, JUDGE) plus one trade of the bot before it (규칙봇 15, entered before the trend
bot's start, a big win that must never be counted as the new bot's):
- livebots.trend_bot: the start record has ``trend`` -> name, start (its trend_since), the 2-week freeze, its rules and
  members with their roles; another bot (no ``trend``) -> None and every page as before (the other test files);
- no number of another bot as this one's: no 91 % / 84~86 % / 78 % lines, no 88 % / 82 % rule, no 5-year band or column,
  no 5-year numbers in 순위, no scorecard or ledger, no 75 % coin flip, no 6.2 entries a weekday; each says why instead
  (TREND_NO_REF_KO "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토");
- the trend bot's own: records from its start only (the old win is not in any of them), groups by role (눌림 · 자리 · 돌파 ·
  횡보) and entry bar (30분 · 1시간 진입), the map split by the judgment it entered on, the supervisor's exits held instead
  (감독 청산 판정), the chase block in its scope, the break-even from its own config, the freeze from its own start, its
  rules in 설정 with 쉬기 없음 · 하루 손실 한도 없음, 진입 가능성's note that a raw signal frequency overstates its entries;
- the views in node (the tiny DOM) draw those answers with the new words and without the old ones."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_livetrend as TL  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import liveinsight as I  # noqa: E402
from paperbot.dash.more import livemissed as M  # noqa: E402
from paperbot.dash.more import livewhy as WY  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
NOW = T.T0 + T.HOUR + 2 * T.MIN
NO_REF = L.TREND_NO_REF_KO
OLD_PNL = 77.0                                           # the old bot's win before the trend bot's start (never counted)
# the old bot's reference numbers, as a page would print them
OLD_WORDS = ("91%", "84~86%", "흔들기", "본전 약 78%", "88% 이상", "82~88%", "82% 미만", "77.6%", "6.2번", "약 75%", "B 그룹", "A 그룹",
             "규칙봇 15 시작", "15개를 고를 때", "5년 백테스트 범위", "5년 시험 순서", "5년 기여도")
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    L._cache.clear()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")   # its config is in its database
    yield
    L._cache.clear()


def _old_trade(db: str) -> None:
    """A 규칙봇 15 trade on the same database before the trend bot started (F3_BOS@30m, a +77 USDT lock)."""
    d = {"side": 1, "entry_price": 100.0, "exit_price": 101.0, "qty": 10.0, "margin": 300.0, "fees": 0.5, "strategy_id": "F3_BOS",
         "timeframe": "30m", "lock_roe": 0.1, "stop_initial": 99.0, "stop_price": 100.5}
    s = Store3(db)
    s.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (L.ACCOUNT, "SOLUSDT", T.T0 - 3 * T.HOUR, T.T0 - 2 * T.HOUR, "LOCK", 30, OLD_PNL, 0.26, 1077.0, json.dumps(d)))
    s.commit()
    s.close()


@pytest.fixture
def tw(tmp_path, monkeypatch):
    w = TL._world(tmp_path)
    w.store.commit()
    _old_trade(w.cfg.db)
    no = str(tmp_path / "none")
    p = {"paper": w.cfg.db, "paper2": no + "-p2.db", "bybit_db": no + "-b.db", "mexc_db": no + "-m.db",
         "bybit_config": no + "-b.json", "mexc_config": no + "-m.json"}
    more = {**L.paths_more(), "combo_config": "/nonexistent/combo.json", "check_db": no + "-check.db", "improve_db": no + "-imp.db",
            "rule_db": w.cfg.paper_db, "shadow_dir": no}
    for k, (var, _d) in L.ENV.items():
        monkeypatch.setenv(var, p[k])
    for k, (var, _d) in L.ENV_MORE.items():
        monkeypatch.setenv(var, more[k])
    return {"w": w, "p": p, "more": more}


def _flat(x) -> str:
    return json.dumps(json_finite(x), ensure_ascii=False, default=str)


# ================================================================ the server
def test_the_running_bot_is_told_from_its_start_record(tw, tmp_path):
    tb = L.trend_bot(tw["p"]["paper"])
    assert tb["name"] == "추세판단 봇" and tb["since"] == T.T0 and tb["freeze_until"] == T.T0 + 14 * L.DAY
    assert tb["rules"] == T.RULES.describe() and tb["numbers"]["vote_min"] == 3
    assert [(m["strategy"], m["tf"], m["role"], m["htf"]) for m in tb["members"]] == [
        ("N08_ICHI_WR", "30m", "눌림", "1h"), ("F3_BOS", "30m", "돌파", "1h"), ("S3_CMO_SANDWICH", "1h", "횡보", "4h")]
    assert L.ref_problem(tw["p"]["paper"]) == NO_REF
    with pytest.raises(ValueError) as e:
        L.live_ref(tw["p"]["paper"])
    assert str(e.value) == NO_REF
    # another bot (no "trend" in its start record), nothing readable, no file: None (every page as before)
    s = Store3(str(tmp_path / "old.db"))
    s.put_state("combo_run", T.T0, {"config": {"name": "규칙봇 15", "trend": None, "members": []}})
    s.commit()
    s.close()
    assert L.trend_bot(str(tmp_path / "old.db")) is None and L.trend_bot(str(tmp_path / "gone.db")) is None
    assert L.ref_problem(str(tmp_path / "old.db")) != NO_REF


def test_perf_has_no_old_baseline_and_counts_from_the_start(tw):
    d = L.perf(tw["p"], NOW, tw["more"])
    assert d["refs"] is None and d["refs_ko"] == NO_REF
    cp = d["checkpoint"]
    assert cp["rule_ko"] == L.TREND_RULE_KO and cp["up"] is None and cp["low"] is None and cp["zone"] is None and cp["n"] == 1
    rv = d["review"]
    assert (rv["since"], rv["until"], rv["n"], rv["wins"]) == (T.T0, T.T0 + 14 * L.DAY, 1, 0) and not rv["done"]
    a = d["accts"]["paper"]
    assert a["stats"]["trades"] == 1 and a["stats"]["pnl"] < 0                # the old +77 win is not the trend bot's
    assert [(r["key"], r["trades"]) for r in a["by_role"]] == [("눌림", 1)]
    assert {r["key"] for r in a["by_strategy"]} == {"N08_ICHI_WR"}
    assert d["scorecard"]["state"] == "missing" and d["scorecard"]["reason_ko"] == NO_REF
    assert d["ledger"] == {"state": "missing", "reason_ko": L.TREND_LEDGER_KO}
    assert d["trend_bot"]["name"] == "추세판단 봇" and d["trend_bot"]["no_ref_ko"] == NO_REF
    assert d["flip"]["stats"]["trades"] == 1
    assert d["empty"] is None                                                    # one closed trade of its own: the page as before
    txt = _flat(d)
    assert '"backtest"' not in txt and '"shake"' not in txt and "88% 이상" not in txt and "82~88%" not in txt
    b = L.build(tw["p"], NOW)                                                     # the summary every tab reads
    assert b["refs"] is None and b["refs_ko"] == NO_REF and b["checkpoint"]["rule_ko"] == L.TREND_RULE_KO and b["checkpoint"]["n"] == 1
    assert b["trend_bot"]["since"] == T.T0


def test_map_has_no_band_and_splits_the_bots_own_trades(tw):
    d = L.map_view(tw["p"], NOW)
    assert d["kind"] == "trend" and d["band_ko"] == NO_REF and d["empty"] is None          # its own trade: no empty state
    b = d["band"]
    assert b["trend"] and b["fit"] is None and b["honest"] is None and b["break_even"] is None and b["fit_band"] is None
    assert b["accounts"]["paper"]["n"] == 1 and b["accounts"]["paper"]["wins"] == 0
    assert [c["id"] for c in d["cut_defs"]] == ["judge", "coin", "hb", "side", "tf"]
    j = {r["key"]: r for r in d["cuts"]["judge"]}
    assert list(j) == ["4", "3"] and j["3"]["n"] == 1 and j["3"]["label"] == "4개 중 3개" and j["4"]["n"] == 0
    assert {r["key"]: r["n"] for r in d["cuts"]["coin"]}["SOLUSDT"] == 0        # the old SOL trade is not this bot's
    assert {r["key"]: r["n"] for r in d["cuts"]["tf"]} == {"30m": 1, "1h": 0}
    assert all(r["small"] for c in d["cuts"].values() for r in c)
    assert "bt_win" not in _flat(d["cuts"]) and "5년" not in _flat(d)


def test_goal_drops_the_old_references(tw):
    d = I.goal(tw["p"], NOW, tw["more"])
    assert d["start"]["name"] == "추세판단 봇" and d["start"]["ms"] == T.T0 and d["start"]["how"] == "trend"
    # its own replay (7/1~10/20 on real bars, measured 10/21), never the old bot's 6.2
    assert d["weekday_ref"] == I.TREND_WEEKDAY_REF == 1.11 and d["record"]["weekday_ref"] == 1.11
    assert d["weekday_ref_ko"].startswith("7/1~10/20 실제 바이낸스 1분봉으로 이 봇 규칙을 다시 돌린 숫자")
    assert abs(d["break_even"] - 0.8505) < 1e-3 and d["break_even_plain"] == [pytest.approx(5 / 6)] * 2   # its own config: 40 %, +10 % / -50 %
    assert "증거금 40%" in d["break_even_ko"] and d["record"]["break_even"] == d["break_even"]
    f = d["frozen"]
    assert f["until_ms"] == T.T0 + 14 * L.DAY and f["on"] and f["ko"].startswith("규칙 고정: 10/19까지") and "추세판단 봇 시작부터" in f["why_ko"]
    assert d["record"]["n"] == 1 and d["record"]["since_ms"] == T.T0
    need = d["accts"][0]["need"]
    # with its own 1.1 entries a weekday and +10 % / −50 % a trade, ×6 in the month is out of reach: said so, honestly
    assert need["state"] == "impossible" and "승률 100%로도 모자람" in need["ko"] and "참고값 6.2" not in need["src_ko"] and "6.2번" not in _flat(d)


def test_judge_in_the_trend_bots_words(tw):
    d = I.judge(tw["p"], NOW, tw["more"])
    s = d["start"]
    assert (s["name"], s["ms"], s["how"], s["sure"], s["trend"]) == ("추세판단 봇", T.T0, "trend", True, True)
    assert d["chase"]["ko"].startswith("추격 막기: 지금 설정의 매매법 3개 중 켠 것이 없어요") and "B 그룹" not in d["chase"]["ko"]
    assert d["rev"]["hold_ko"] == I.TREND_HOLD_KO and d["rev"]["totals"]["n"] == 0
    sup = d["sup"]
    assert sup["state"] == "ok" and sup["ko"].startswith("감독 청산:") and "진입 봉 4개" in sup["ko"]
    (r,) = sup["rows"]
    assert (r["exit_reason"], r["group"], r["strategy_id"]) == ("JUDGE", "눌림", "N08_ICHI_WR") and r["why"].startswith("1시간 판단이")
    assert sup["by_reason"] == {"JUDGE": 1, "TIME": 0}
    tw_ = d["twin"]
    assert tw_["ref_flip_win"] is None and tw_["ref_ko"] == NO_REF and tw_["real"]["n"] == 1
    assert "0.75" not in _flat(d)


def test_judge_chase_scope_when_every_member_has_the_block(tw):
    cx = I.context(tw["p"], NOW, tw["more"])
    for m in cx["members"]:
        m["no_chase"] = True
    assert I.trend_chase_ko(cx) == I.TREND_CHASE_KO.format(who="매매법 3개 모두")


def test_groups_are_roles_and_entry_bars(tw):
    d = I.groups(tw["p"], NOW, tw["more"])
    assert d["kind"] == "trend" and d["order"] == ["눌림", "자리", "돌파", "횡보", "30m", "1h"]
    defs = {g["id"]: g for g in d["defs"]}
    assert defs["30m"]["ko"] == "30분 진입" and defs["1h"]["ko"] == "1시간 진입" and defs["돌파"]["n_members"] == 1
    g = d["accts"]["paper"]["groups"]
    assert (g["눌림"]["n"], g["30m"]["n"], g["돌파"]["n"], g["1h"]["n"]) == (1, 1, 0, 0)   # the old F3_BOS win is not counted
    assert d["start"]["name"] == "추세판단 봇" and "A 그룹" not in _flat(d)


def test_rank_without_five_years_and_from_the_start(tw):
    d = L.rank(tw["p"], NOW)
    assert d["ref"]["state"] == "missing" and d["ref"]["reason_ko"] == NO_REF and d["ref"]["fit_win"] is None
    rows = {r["strategy"]: r for r in d["rows"]}
    assert rows["N08_ICHI_WR"]["role"] == "눌림" and rows["N08_ICHI_WR"]["paper"]["n"] == 1
    assert rows["F3_BOS"]["paper"]["n"] == 0 and all(r["bt"] is None for r in d["rows"])
    assert d["unknown_strategies"] == [] and d["trend_bot"]["name"] == "추세판단 봇"


def test_likely_says_a_signal_is_not_an_entry(tw):
    d = L.likely(tw["p"], NOW)
    if d.get("state") != "ok":
        pytest.skip(f"the frequency file is not usable here: {d.get('reason_ko')}")
    assert d["note_ko"] == L.LIKELY_TREND_NOTE_KO and "추세 판단" in d["note_ko"] and "되돌림" in d["note_ko"]
    assert "지금 설정 95개" not in d["note_ko"]


def test_settings_show_the_trend_rules(tw):
    d = L.settings(tw["p"], NOW)
    tr = d["trend"]
    assert tr["rules"] == T.RULES.describe() and tr["no_pause"] is True and tr["no_pause_ko"] == "쉬기 없음 · 하루 손실 한도 없음"
    assert [(m["strategy"], m["role"], m["tf_ko"], m["htf_ko"]) for m in tr["members"]][0] == ("N08_ICHI_WR", "눌림", "30분 진입", "끝난 1시간봉 추세로 판단")
    assert [r["id"] for r in tr["roles"]] == ["눌림", "자리", "돌파", "횡보"] and tr["freeze_until"] == T.T0 + 14 * L.DAY
    assert all(m.get("role") for g in d["groups"] for m in g["members"])


def test_replay_of_a_supervisor_close_is_not_flagged_as_different(tw):
    """다시보기: the supervisor's close (JUDGE) is not one the bars decide: its minute is the record's, never 기록과 다름; the
    old bot's trade before the start is tagged 전환 전 (``prev``), the bot's own is not."""
    from paperbot.dash.more import livetape as R
    now = NOW + 40 * T.MIN
    ls = R.build_list(tw["p"], now_ms=now)
    by = {r["exit_reason"]: r for r in ls["rows"]}
    assert (by["JUDGE"]["prev"], by["LOCK"]["prev"]) == (False, True) and ls["trend_bot"]["since"] == T.T0
    one = R.build_one(tw["p"], by["JUDGE"]["id"], now_ms=now, more=tw["more"])
    assert one["bars"]["state"] == "ok" and one["exit"]["stopped"] == "outside" and one["exit"]["rebuilt"] is None
    assert one["check"]["state"] == "same" and one["check"]["why_ko"] == R.SUP_KO and one["trade"]["prev"] is False


def test_why_and_missed_do_not_borrow_the_old_bots_words(tw):
    assert WY.five_year(1, "N08_ICHI_WR", tw["p"]["paper"]) == {"state": "missing", "reason_ko": NO_REF}
    m = M.build(tw["p"], tw["more"], NOW)
    assert m["filter_note_ko"] == M.TREND_FILTER_NOTE_KO and "5년 시험" not in m["filter_note_ko"]


def test_the_old_bot_keeps_its_words(tmp_path):
    """Without ``trend`` in the start record nothing of the above applies (the old tests check every number)."""
    s = Store3(str(tmp_path / "old.db"))
    s.put_state("combo_run", T.T0, {"config": {"name": "규칙봇 15", "trend": None, "members": []}})
    s.commit()
    s.close()
    p = {"paper": str(tmp_path / "old.db")}
    cx_less = {"trend": None}
    assert I.weekday_ref(cx_less) == I.WEEKDAY_ENTRIES and I.break_even_of({"trend": None, "cfg": {}})[0] == I.BREAK_EVEN
    assert I.frozen(T.T0)["until"] == I.RULES_FROZEN_UNTIL
    assert L.trend_out(L.trend_bot(p["paper"])) is None


# ================================================================ the screens in node
def _node(tmp_path, body: str, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    mods = "".join(f"const {n} = await import('file://{SCREENS}/livebots-{f}.js');\n"
                   for n, f in (("J", "judge"), ("G", "goal"), ("RK", "rank"), ("P", "perf"), ("MP", "map"), ("MO", "more")))
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n" + mods + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (answers) => { const st = {calls: [], every: []}; return {st, ctx: {params: {query: {}}, alive: () => true, track() {},"
              " listen() {}, on() {}, watch() {}, href: (n, a) => '#/' + n, every(ms, fn) { st.every.push(ms); },"
              " api: async (path) => { st.calls.push(path); const a = answers[path] !== undefined ? answers[path] : answers['*'];"
              " if (a instanceof Error) throw a; return JSON.parse(JSON.stringify(a)); }}}; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture
def answers(tw):
    p, more = tw["p"], tw["more"]
    return {"perf": L.perf(p, NOW, more), "groups": I.groups(p, NOW, more), "judge": I.judge(p, NOW, more),
            "goal": I.goal(p, NOW + L.DAY, more), "map": L.map_view(p, NOW), "rank": L.rank(p, NOW), "settings": L.settings(p, NOW)}


def test_views_draw_the_trend_bots_answers(tmp_path, answers):
    out = _node(tmp_path, """const run = async (V, answers) => { const c = mkCtx(answers); const v = V(c.ctx); await tick(); await tick(); return texts(v.el); };
    const GR = "/api/v4/livebots/groups";
    const pf = await run(P.perfView, {"/api/v4/livebots/perf": D_a.perf, [GR]: D_a.groups});
    const jd = await run(J.judgeView, {"*": D_a.judge}), gl = await run(G.goalView, {"*": D_a.goal});
    const mp = await run(MP.mapView, {"*": D_a.map});
    const rk = await run(RK.boardView, {"/api/v4/livebots/rank": D_a.rank, [GR]: D_a.groups});
    const st = await run(MO.settingsView, {"*": D_a.settings});
    console.log(JSON.stringify({pf, jd, gl, mp, rk, st,
      grp: RK.groupRows(D_a.groups, "paper").map((g) => [g.id, g.cut, g.rec.n]), words: RK.groupWords(D_a.groups),
      pick: RK.pickSort(null, D_a.rank), sorts: RK.sortsOf(D_a.rank).map((x) => x.id),
      rv: P.reviewWords(D_a.perf.review, D_a.perf.now_ms), brk: P.breaksOf(D_a.perf).map((b) => b.id),
      tone: [MP.trendTone({n: 12, pnl: 3}), MP.trendTone({n: 12, pnl: -3}), MP.trendTone({n: 3, pnl: 3}), MP.trendTone({n: 0})].map((t) => t.tone),
      cuts: MP.cutsOf(D_a.map).map((c) => c.id), sv: J.supVerdict(D_a.judge.sup.totals), sv0: J.supVerdict({n: 0}),
      rv0: J.revVerdict({n: 0}, J.botName(D_a.judge.start)), be: G.beWords(D_a.goal.break_even, D_a.goal.break_even_plain),
      sr: G.scaleRows({checks: [{ok: null, ko: "거래 0번", what_ko: "추세판단 봇 시작 뒤 닫힌 실거래"}, {ok: true, ko: "x"}]}).map((r) => r.mark),
      rp: MO.ruleParts(D_a.settings.trend.rules[0]), rg: MO.roleGroups(D_a.settings.trend).map((g) => [g.id, g.members.length])}));""", a=answers)
    for k in ("pf", "jd", "gl", "mp", "rk", "st"):
        assert not BAD.search(out[k]), (k, BAD.search(out[k]))
        for w in OLD_WORDS:
            assert w not in out[k], (k, w)
    pf = out["pf"]
    for w in ("추세판단 봇 시작 10/05 09:00부터", "2주 검토까지", "D-14", NO_REF, "기준 없음", "역할", "그룹별 성적", "눌림", "30분 진입",
              "1시간 진입", "역할별 (눌림 · 자리 · 돌파 · 횡보)", L.TREND_RULE_KO, "동전 쌍둥이"):
        assert w in pf, w
    assert "40번 판단까지" not in pf and "매매법 성적표" in pf and "개선 후보 장부" in pf and "백테스트 91" not in pf
    jd = out["jd"]
    for w in ("추세판단 봇 시작 10/05 09:00부터", "감독 청산 판정", "감독 청산:", "추세 뒤집힘", "실제 (추세 뒤집힘)", "눌림", I.TREND_HOLD_KO,
              "추격 막기가 막은 신호에 들어갔다면", "추세판단 봇 시작 뒤 빠른 손절로 닫힌 거래가 아직 없어요",
              "견줄 동전 승률 기준이 없어요", "같은 신호 · 방향만 동전 · 추세판단 봇 시작부터"):
        assert w in jd, w
    gl = out["gl"]
    for w in ("추세판단 봇 시작 10/05 09:00", "1.1번 (7/1~10/20 실제 바이낸스 1분봉으로 이 봇 규칙을 다시 돌린 숫자", "본전 약 85%", "단순 합으로는 83%", "증거금 40%",
              "규칙 고정: 10/19까지"):
        assert w in gl, w
    mp = out["mp"]
    for w in ("이긴 횟수", "기대 범위 띠가 없는 이유", NO_REF, "진입 때 추세 판단", "4개 중 3개", "진입 봉", "30분 진입", "손익", "표본",
              "견줄 기준이 없어요", "추세판단 봇 닫힌 거래를"):
        assert w in mp, w
    assert "5년" not in mp and "현실 기대 범위" not in mp and "경보선 (현실" not in mp and "40번 점검" not in mp
    rk = out["rk"]
    for w in ("추세판단 봇 · 두 실행기가 따라가는", "기준 없음", NO_REF, "이번 주 신호", "눌림", "백테스트 숫자가 없어요", "그룹별 성적"):
        assert w in rk, w
    assert "5년" not in rk and "맞춘 숫자" not in rk
    st = out["st"]
    for w in ("추세 판단 규칙", "쉬기 없음 · 하루 손실 한도 없음", "규칙 고정", "백테스트 기준 없음", "추세 판단", "진입 전 검사", "감독(첫 잠금 전까지만)",
              "눌림 · 1개", "돌파 · 1개", "횡보 · 1개", "30분 진입", "끝난 4시간봉 추세로 판단", "역할 눌림"):
        assert w in st, w
    assert out["grp"] == [["눌림", "role", 1], ["자리", "role", 0], ["돌파", "role", 0], ["횡보", "role", 0], ["30m", "tf", 1], ["1h", "tf", 0]]
    assert out["words"]["start"].startswith("추세판단 봇 시작 10/05 09:00부터") and "A 그룹" not in out["words"]["sub"]
    assert out["pick"]["sort"] == "pnl" and out["sorts"] == ["pnl", "win", "trades", "signals"]
    assert out["rv"]["daysLeft"] == 14 and out["rv"]["head"].startswith("D-14") and not out["rv"]["done"]
    assert out["brk"][0] == "by_role" and out["tone"] == ["ok", "bad", "small", "none"]
    assert out["cuts"] == ["judge", "coin", "hb", "side", "tf"]
    assert "감독 청산 1번" in out["sv"]["ko"] and out["sv0"]["ko"] == "추세판단 봇 시작 뒤 감독 청산으로 닫힌 거래가 아직 없어요"
    assert out["rv0"]["ko"].startswith("추세판단 봇 시작 뒤") and out["be"] == "본전 약 85% (복리; 단순 합으로는 83%)"
    assert out["sr"] == ["·", "✓"]
    assert out["rp"]["head"] == "추세 판단" and len(out["rp"]["parts"]) == 5
    assert out["rg"] == [["눌림", 1], ["돌파", 1], ["횡보", 1]]


def test_the_terminal_chip_counts_to_the_review(tmp_path, tw):
    """The terminal's band (livebots-parts.js bandLine): 2주 검토까지 D-n for the trend bot, never 40번 판단까지."""
    b = L.build(tw["p"], NOW)
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    f = tmp_path / "b.json"
    f.write_text(json.dumps(json_finite(b), allow_nan=False, default=str), encoding="utf-8")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              f"const PT = await import('file://{SCREENS}/livebots-parts.js');\n"
              f"const d = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));\n"
              "const band = PT.bandLine({href: (a, b) => '#/' + a + '/' + b}); band.set(d, 'ok');\n"
              "console.log(JSON.stringify({t: D.walk(band.el).text.replace(/\\s+/g, ' ')}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    t = json.loads(r.stdout.strip().splitlines()[-1])["t"]
    assert "2주 검토까지" in t and "D-14" in t and "페이퍼(연습) 1번" in t and "40번 판단까지" not in t
