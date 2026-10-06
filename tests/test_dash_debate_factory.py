"""Design step 6 (the idea factory on the 24시간 토론방 screen): /api/debate's `factory` block and each factory / deep
round's `idea`, and the screen's pieces.

- dash/analysis.py debate_factory_view, read-only on a debate.db written by the debate service's own code (debate.DB,
  debate_factory.add_idea, labintake's detail shapes): today's hand-off (queued against the daily share, candidates,
  the next pick), the last 20 ideas with the code's stage (후보 → 오늘 시험 줄 → 시험 중 → 통과 / 불통과, or why it
  stopped), the ①-⑥ checklist with the lab's own numbers, who was right, the record next to the lab's base rates,
  왜 떨어졌나 per engine, the daily deep debate (its month line, today's state, the newest deep round with its parts);
  nothing for a classic room or an older file; the file is never written;
- debate_chat: a factory / deep round carries its question's kind in Korean and its idea; a classic round neither;
- the route carries it;
- in node with a small DOM: the idea card (AI words and code words apart, the checklist, who was right), the round
  (the code's question first, the idea card last, the deep debate's parts in their own columns), the 아이디어 공장
  card (today, the list, the record with the base rates, 왜 떨어졌나, the caution), the deep block (hidden while off,
  the state lines, the three parts), the status column's lines;
- wiring: the screen mounts both cards, tokens only in the css.
"""
import hashlib
import json
import os
import re
import sqlite3

import pytest

from paperbot.dash import analysis as AN
from test_dash_debate_chat import OLD_SCHEMA, SCR, _FAKE_DOM, _read, _code

M = 60_000
HOUR = 3_600_000
# 2026-10-15 11:00 UTC = 20:00 KST: the deep debate (DEBATE_DEEP_AT 20:00) is due; the next pick is 21:00 KST
NOW = 1_791_158_400_000 + 10 * 86_400_000 + 11 * HOUR


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _world(path, mode="factory", deep=True, fillers=12):
    """A debate.db as the debate service writes it: a classic round, eight factory rounds whose ideas sit at every
    stage, ``fillers`` more candidate ideas (the list's 20 cap), today's deep debate and the lab's base rates."""
    from paperbot.agents import debate as D
    from paperbot.agents import debate_factory as DF
    from paperbot.agents import labintake as LI
    db = D.DB(path)
    c = db.conn

    def rnd(ts, topic, kind=None, qk=None, model="claude-sonnet-5-5", status="ok", error=None):
        rid = c.execute("INSERT INTO debate_rounds (ts, topic, status, model, turns, cost_usd, error) VALUES (?,?,?,?,?,?,?)",
                        (ts, topic, status, model, 5, 0.02, error)).lastrowid
        if kind:
            c.execute("UPDATE debate_rounds SET kind = ?, question_kind = ?, question_key = ?, question_ko = ? WHERE "
                      "round_id = ?", (kind, qk, f"{qk}:{rid}", topic, rid))
        return rid

    def msg(ts, rid, sp, text, side=None, part=None):
        c.execute("INSERT INTO debate_messages (ts, round_id, speaker, stance, topic, text, side, part) VALUES (?,?,?,?,?,?,?,?)",
                  (ts, rid, sp, D.FACTORY_STANCE.get(sp) or D.STANCE.get(sp, ""), "t", text, side, part))

    def chk(engine, desc, cc="⑥", status="ok", old=None, check_ko=None):
        return {"engine": engine, "strategy": "N17_KC_RSI" if engine == "labtest" else None, "spec": {"x": 1},
                "spec_hash": "h" + desc[:8], "description_ko": desc, "check_status": status,
                "check_ko": check_ko or DF.CHECK_KO[status], "claim_ko": f"주장 {desc[:6]}", "pro_ko": "찬성 근거",
                "con_ko": "반대 근거", "con_check": cc, "backs": None, "weak": [], "old_trial_id": old}

    def idea(rid, ts, qk, checked, kind="factory", queue=None, slot=None, lab=None):
        iid = DF.add_idea(c, rid, ts, {"kind": qk, "key": f"{qk}:{rid}", "question_ko": "질문"}, checked, round_kind=kind)
        c.execute("UPDATE debate_rounds SET lab_idea_id = ? WHERE round_id = ?", (iid, rid))
        if queue:
            c.execute("UPDATE debate_lab_ideas SET queue_status = ?, slot = ? WHERE id = ?", (queue, slot, iid))
        if lab:
            status, det, trial = lab
            side, hit = DF.settle({"status": status, "detail": det}, checked["con_check"])
            c.execute("UPDATE debate_lab_ideas SET queue_status = 'queued', lab_status = ?, lab_trial_id = ?, "
                      "lab_test_number = ?, lab_result_ko = ?, lab_detail = ?, settled_side = ?, con_check_hit = ? WHERE id = ?",
                      (status, trial, det.get("test_number") if isinstance(det.get("test_number"), int) else None,
                       LI.result_ko(det, status, trial), json.dumps(det, ensure_ascii=False), side, hit, iid))
        return iid

    t = NOW - 30 * HOUR
    r = rnd(t, "코인별 차이")
    for sp in D.ROLES:
        msg(t, r, sp, f"{sp}의 말")
    msg(t, r, "정리", "정리: 예전 방식")
    nl_fail = LI.newlab_detail("failed", {"checks": {"a": False, "b": True, "c": False, "d": True, "e": True, "f": False},
                                          "n_tests_so_far": 56, "alpha_period1": 0.05 / 57},
                               {"periods": {"1": {"trades": 1834, "mean_roe": -0.0021, "p": 0.64, "coinflip_diff": 0.0002,
                                                  "coinflip_p": 0.41}, "2": {"trades": 911, "mean_roe": -0.0035, "p": 0.81}}}, 57)
    nl_pass = LI.newlab_detail("passed", {"checks": {k: True for k in "abcdef"}, "n_tests_so_far": 41},
                               {"periods": {"1": {"trades": 2410, "mean_roe": 0.0041, "p": 0.0003}}}, 42)
    lt_fail = LI.labtest_detail("failed", {"checks": {"a": False, "b": False, "c": True, "d": True, "e": True, "f": True},
                                           "n_trials": 4, "alpha_period1": 0.0125},
                                {"periods": {"1": {"diff": -0.0007, "p": 0.38, "variant": {"trades": 612}}}}, 4)
    day = DF.P.kst_day(NOW)
    stages = [
        ("worst_vs_flip", chk("labtest", "N17_KC_RSI 1h: 추세 반대 진입 건너뛰기", cc="①"), {"lab": ("tested", lt_fail, 311)}),
        ("loss_traits", chk("newlab", "새 매매법: 아시아 시간 제외 반등 롱"), {"lab": ("tested", nl_pass, 298)}),
        ("volume_profile", chk("newlab", "새 매매법: 매물대 위 끝 아래 진입 안 함"), {"lab": ("tested", nl_fail, 305)}),
        ("tf_split", chk("labtest", "S07 15m: 4h 추세 반대 건너뛰기", status="duplicate", old=57,
                         check_ko="이미 시험함: 장부 #57 (failed)"), {}),
        ("near_miss", chk("newlab", "새 매매법: #48 + RSI 하나", status="near_duplicate", old=48), {}),
        ("coverage", chk("newlab", "", status="bad_spec", check_ko="문법 밖"), {}),
        ("pairs", chk("labtest", "N02 1h: 함께 지는 거래 막기"), {"queue": "not_picked", "slot": "slot:x:am"}),
        ("big_losses", chk("newlab", "새 매매법: 하락 추세 롱 금지"), {"queue": "queued", "slot": f"slot:{day}:am",
                                                                   "lab": ("running", {}, None)}),
    ]
    t0 = NOW - 10 * HOUR
    for i, (qk, ck, o) in enumerate(stages):
        ts = t0 + i * 20 * M
        rid = rnd(ts, f"질문 {qk}", "factory", qk)
        sides = DF.sides_for(i)
        for sp in DF.factory_order(i, 5):
            msg(ts, rid, sp, f"{sp} 발언", sides[sp])
        msg(ts, rid, "정리", "정리: 메모")
        idea(rid, ts, qk, ck, **o)
    for k in range(fillers):
        ts = t0 + (8 + k) * 20 * M
        rid = rnd(ts, f"질문 채움 {k}", "factory", "session_cell")
        msg(ts, rid, "심판", "심판 발언", "심판")
        idea(rid, ts, "session_cell", chk("newlab", f"새 매매법: 채움 {k:02d}"))
    if deep:
        t = NOW - 5 * M
        rid = rnd(t, "오늘 가장 크게 잃은 거래 5개", "deep", "big_losses", model="claude-opus-5-5")
        sides = DF.sides_for(0)
        pro = [x for x in DF.ROLES if sides[x] == "찬성"]
        con = [x for x in DF.ROLES if sides[x] == "반대"]
        for sp, part in ((pro[0], "주장"), (pro[1], "주장"), (con[0], "반박"), (con[1], "반박"), ("심판", "심판")):
            msg(t, rid, sp, f"{sp} {part}", sides[sp], part)
        msg(t, rid, "정리", "정리: 깊은 토론 메모")
        idea(rid, t, "big_losses", chk("newlab", "새 매매법: 깊은 토론의 아이디어"), kind="deep")
    db.put("run", {"state": "running", "model": "claude-sonnet-5-5", "every_min": 20, "cap": 70, "mode": mode,
                   "lab_per_day": 2, "deep": {"on": deep, "model": "claude-opus-5-5", "at": "20:00", "cap": 10}})
    db.put("heartbeat", NOW)
    db.put(f"spend:deepmonth:{day[:7]}", 0.6612)
    db.put("factory:base_rates", {
        "newlab": {"tests": 412, "passed": 1, "pass_rate": 0.0024, "fail_share": {"①": 0.81, "③": 0.64, "⑥": 0.77}},
        "labtest": {"tests": 96, "passed": 3, "pass_rate": 0.0312, "fail_share": {"①": 0.88, "②": 0.6}}})
    db.close()


# ---------------------------------------------------------------- the server side
def test_the_factory_view_from_a_debate_db(tmp_path):
    path = str(tmp_path / "debate.db")
    _world(path)
    before = _sha(path)
    f = AN.debate_factory_view(path, NOW)
    assert _sha(path) == before                                                   # read-only
    assert f["mode"] == "factory" and f["lab_per_day"] == 2 and f["goal"].startswith("많은 매매법을 시험해")
    t = f["today"]
    assert t["queued"] == 1 and t["cap"] == 2 and t["candidates"] == 12 + 1      # the fillers and the deep idea
    assert t["next_pick_ts"] == NOW + HOUR                                         # 21:00 KST
    ideas = f["ideas"]
    assert len(ideas) == 20 and [x["id"] for x in ideas] == sorted((x["id"] for x in ideas), reverse=True)
    by = {x["description_ko"] or x["check_ko"]: x for x in AN.debate_factory_view(path, NOW, ideas=50)["ideas"]}
    st = {k: (v["stage"], v["stage_ko"], v["tone"]) for k, v in by.items()}
    assert st["N17_KC_RSI 1h: 추세 반대 진입 건너뛰기"] == ("failed", "불통과", "bad")
    assert st["새 매매법: 아시아 시간 제외 반등 롱"] == ("passed", "통과", "good")
    assert st["S07 15m: 4h 추세 반대 건너뛰기"] == ("duplicate", "이미 시험함 #57", "thin")
    assert st["새 매매법: #48 + RSI 하나"] == ("near_duplicate", "비슷한 실패 시험 있음", "warn")
    assert st["문법 밖"] == ("bad_spec", "문법 밖", "warn")
    assert st["N02 1h: 함께 지는 거래 막기"] == ("not_picked", "이번엔 안 뽑힘", "thin")
    assert st["새 매매법: 하락 추세 롱 금지"] == ("running", "시험 중", "accent")
    assert st["새 매매법: 채움 00"] == ("candidate", "후보", "accent")
    # the lab's result: ①-⑥ from its stored checks with its own numbers, the failed marks, the ledger number
    fail = by["새 매매법: 매물대 위 끝 아래 진입 안 함"]
    lab = fail["lab"]
    assert [(c["mark"], c["ok"]) for c in lab["checks"]] == [("①", False), ("②", True), ("③", False), ("④", True),
                                                             ("⑤", True), ("⑥", False)]
    assert lab["checks"][0]["num_ko"] == "1기간 거래당 −0.21% (p=0.64)" and lab["checks"][1]["num_ko"] == "1기간 거래 1,834건"
    assert lab["checks"][5]["num_ko"] == "동전과 차이 +0.02%p (p=0.41)" and lab["checks"][3]["num_ko"] == ""
    assert lab["failed"] == ["①", "③", "⑥"] and lab["trial_id"] == 305 and lab["test_number"] == 57
    assert lab["result_ko"].startswith("불통과: ") and lab["status_ko"] == "시험함"
    assert fail["settled_side"] == "반대" and fail["con_check"] == "⑥" and fail["con_check_hit"] == 1
    assert fail["con_check_ko"] == "동전보다 나음" and fail["engine_ko"] == "5년 시험·새 매매법"
    assert fail["question_kind_ko"] == "매물대 앞 진입"
    ok = by["새 매매법: 아시아 시간 제외 반등 롱"]
    assert ok["settled_side"] == "찬성" and ok["con_check_hit"] == 0
    lt = by["N17_KC_RSI 1h: 추세 반대 진입 건너뛰기"]
    assert lt["lab"]["checks"][0]["name_ko"] == "1기간 개선·p 기준" and lt["lab"]["checks"][0]["num_ko"].startswith("1기간 개선 −0.07%p")
    assert lt["con_check_ko"] == "1기간 개선·p 기준" and lt["con_check_hit"] == 1
    assert "lab" not in by["새 매매법: 채움 00"] and by["새 매매법: 채움 00"]["settled_side"] is None
    # the record: the code's sides next to what the lab's usual pass rate alone would give
    r = f["record"]
    assert (r["tested"], r["passed"], r["pro_right"], r["con_right"]) == (3, 1, 1, 2)
    assert r["pro_expected"] == 0.04 and r["con_expected"] == 2.96 and r["base_known"] and r["small"]
    assert (r["con_check_graded"], r["con_check_hits"]) == (3, 2) and r["coin_flip"] == 0.5
    assert r["lab"]["newlab"] == {"tests": 412, "passed": 1, "pass_rate": 0.0024}
    # 왜 떨어졌나: this room's tested ideas per engine, next to the lab's share
    w = f["why_fail"]
    assert w["newlab"]["tests"] == 2 and w["newlab"]["failed"] == {"①": 1, "②": 0, "③": 1, "④": 0, "⑤": 0, "⑥": 1}
    assert w["newlab"]["lab_share"] == {"①": 0.81, "③": 0.64, "⑥": 0.77} and w["newlab"]["lab_tests"] == 412
    assert w["labtest"]["tests"] == 1 and w["labtest"]["failed"]["②"] == 1 and w["labtest"]["names_ko"]["⑥"].startswith("레버리지")
    # the daily deep debate: its own month line, today's state, the newest deep round with its parts and idea
    d = f["deep"]
    assert d["on"] and d["model"] == "claude-opus-5-5" and d["cap"] == 10 and d["month"] == 0.6612
    assert d["today"]["due_ts"] == NOW and d["today"]["last"]["status"] == "ok"
    rd = d["round"]
    assert rd["kind"] == "deep" and rd["question"] == {"kind": "big_losses", "kind_ko": "오늘 큰 손실", "ko": "오늘 가장 크게 잃은 거래 5개"}
    assert [m.get("part") for m in rd["messages"]] == ["주장", "주장", "반박", "반박", "심판", None]
    assert rd["idea"]["round_kind"] == "deep" and rd["idea"]["stage"] == "candidate"
    assert "사람 성적이 아닙니다" in f["caution"]


def test_nothing_for_a_classic_room_or_an_older_file(tmp_path):
    old = str(tmp_path / "old.db")
    c = sqlite3.connect(old)
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO debate_rounds (ts, topic, status) VALUES (?, 't', 'ok')", (NOW,))
    c.commit()
    c.close()
    assert AN.debate_factory_view(old, NOW) == {}
    assert "factory" not in AN.debate(old, now_ms=NOW)
    assert AN.debate_factory_view(str(tmp_path / "missing.db"), NOW) == {}
    # the service's own file in classic mode (the factory's table exists, empty; no factory round): nothing either
    from paperbot.agents import debate as D
    cl = str(tmp_path / "classic.db")
    db = D.DB(cl)
    db.put("run", {"state": "running", "mode": "classic"})
    db.close()
    assert AN.debate_factory_view(cl, NOW) == {}
    # rolled back to classic after the factory ran: the record stays readable, said as classic
    fb = str(tmp_path / "back.db")
    _world(fb, mode="classic", deep=False, fillers=0)
    f = AN.debate_factory_view(fb, NOW)
    assert f["mode"] == "classic" and f["mode_ko"].startswith("예전 토론") and f["today"]["next_pick_ts"] is None
    assert f["deep"]["round"] is None and not f["deep"]["on"] and len(f["ideas"]) == 8


def test_the_chat_rounds_carry_their_idea(tmp_path):
    path = str(tmp_path / "debate.db")
    _world(path, fillers=0)
    d = AN.debate_chat(path, NOW)
    deep, newest = d["chat"][0], d["chat"][1]
    assert deep["kind"] == "deep" and deep["idea"]["description_ko"] == "새 매매법: 깊은 토론의 아이디어"
    assert newest["kind"] == "factory" and newest["question"]["kind_ko"] == "오늘 큰 손실"
    assert newest["idea"]["stage"] == "running" and newest["idea"]["queue_status"] == "queued"
    assert d["timeline"][0]["kind"] == "deep" and all("kind" in r for r in d["timeline"][:9])
    classic = AN.debate_chat(path, NOW, rounds=30)["chat"][-1]
    assert "idea" not in classic and "question" not in classic and "kind" not in classic


def test_the_route_carries_the_factory(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from paperbot.store3 import Store3
    paper = str(tmp_path / "paper3.db")
    Store3(paper).close()
    path = str(tmp_path / "debate.db")
    _world(path)
    c = TestClient(create_app(paper, hash_password("pw"), b"s" * 32, debate_db=path))
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    j = c.get("/api/debate").json()
    f = j["factory"]
    assert f["mode"] == "factory" and len(f["ideas"]) == 20 and f["deep"]["round"]["kind"] == "deep"
    assert {"today", "record", "why_fail", "caution"} <= set(f) and j["chat"][0]["idea"]


# ---------------------------------------------------------------- the screen in node (a small DOM)
_DOM = _FAKE_DOM + r"""
Object.defineProperty(E.prototype, "innerHTML", {set() { for (const c of [...this.childNodes]) this._drop(c); }, get() { return ""; }});
const txt = (n) => n ? n.textContent : null;
"""


def _node(body):
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--input-type=module", "-e", _DOM + body.replace("@S", "file://" + SCR)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def view(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("fv") / "debate.db")
    _world(path)
    return {"factory": AN.debate_factory_view(path, NOW), "chat": AN.debate_chat(path, NOW)["chat"]}


def test_the_idea_card_keeps_ai_words_and_code_words_apart(view):
    ideas = AN.debate_factory_view  # noqa: F841 (the fixture holds the data)
    fail = next(x for x in view["factory"]["ideas"] if x["stage"] == "failed" and x["engine"] == "newlab")
    out = _node(f"""
const I = await import('@S/debate-idea.js');
const fail = {json.dumps(fail, ensure_ascii=False)};
const card = I.ideaCard(fail);
const pass = I.ideaCard({{...fail, stage: 'passed', stage_ko: '통과', tone: 'good', settled_side: '찬성', con_check_hit: 0}});
const cand = I.ideaCard({{...fail, stage: 'candidate', stage_ko: '후보', tone: 'accent', lab: null, settled_side: null, con_check_hit: null}});
console.log(JSON.stringify({{
  chip: all(card, 'pp').map((x) => [x.className, x.textContent]),
  what: txt(all(card, 'db-idwhat')[0]),
  keys: all(card, 'db-k').map(txt),
  quotes: all(card, 'db-said').length,
  checks: all(card, 'db-checks')[0].childNodes.map((li) => [li.className, txt(li)]),
  lab: txt(all(card, 'db-labline')[0]),
  right: txt(all(card, 'db-right')[0]), passRight: txt(all(pass, 'db-right')[0]),
  passNote: all(pass, 'db-small').map(txt), cand: [all(cand, 'db-checks').length, all(cand, 'db-right').length, all(cand, 'db-small').map(txt)],
  cls: card.className}}));
""")
    assert ["pp bad", "불통과"] in out["chip"] and ["pp thin", "5년 시험·새 매매법"] in out["chip"]
    assert out["what"] == "시험할 것 · 코드가 옮긴 글새 매매법: 매물대 위 끝 아래 진입 안 함"
    assert out["keys"] == ["시험할 것 · 코드가 옮긴 글", "AI가 쓴 말 (의견)", "코드"] and out["quotes"] == 3
    assert [c[0] for c in out["checks"]] == ["no", "ok", "no", "ok", "ok", "no"]
    assert out["checks"][0][1] == "①✗1기간 수익·p 기준1기간 거래당 −0.21% (p=0.64)"
    assert out["lab"].startswith("불통과: ")
    assert out["right"] == "누가 맞았나반대맞음 (5년 시험 불통과)반대가 짚은 칸 ⑥ 동전보다 나음: 실제로 떨어짐 (맞힘)"
    assert out["passRight"].startswith("누가 맞았나찬성맞음 (5년 시험 통과)") and out["passRight"].endswith("그 칸은 넘음 (못 맞힘)")
    # a pass is never a proposal here: re-judged later at that day's test count, the owners decide
    assert any("두 분께 올립니다 (두 분 확인 필요)" in x for x in out["passNote"])
    assert out["cand"][0] == 0 and out["cand"][1] == 0 and any(x.startswith("다음 고르기") for x in out["cand"][2])
    assert out["cls"] == "db-idcard st-failed"


def test_the_round_opens_with_the_question_and_ends_with_the_idea(view):
    rounds = view["chat"][:2]
    out = _node(f"""
const C = await import('@S/debate-chat.js');
const [deep, fac] = {json.dumps(rounds, ensure_ascii=False)};
const f = C.roundChat(fac), d = C.roundChat(deep), live = C.roundChat(fac, {{question: false}});
console.log(JSON.stringify({{
  first: f.childNodes[0].className, q: txt(f.childNodes[0]), last: f.childNodes[f.childNodes.length - 1].className,
  liveFirst: live.childNodes[0].className,
  cols: all(d, 'db-partcol').map((c) => [txt(all(c, 'db-partdiv')[0]), all(c, 'db-msg').length]),
  partTags: all(d, 'db-part').length, deepLast: d.childNodes[d.childNodes.length - 1].className,
  sides: txt(C.sidesLine(deep)), judgeOnly: txt(C.sidesLine(fac)), parts: C.partsOf(deep), classic: C.sidesLine({{messages: [{{speaker: '퀀트', text: 'x'}}]}})}}));
""")
    assert out["first"] == "db-qpin" and out["q"] == "이번 회차 질문잃는 시간대코드가 봇 자료에서 고름질문 채움 11"
    assert out["last"] == "db-pin db-idpin" and out["liveFirst"] == "db-msg"
    assert out["cols"] == [["1 주장찬성 두 자리 · 첫 번째 호출", 2], ["2 반박반대 두 자리 · 두 번째 호출, 주장을 읽고", 2],
                           ["3 심판심판 · 세 번째 호출, 주장과 반박을 읽고", 1]]
    assert out["partTags"] == 0 and out["deepLast"] == "db-pin db-idpin"            # each word once: on the column
    assert out["sides"].startswith("편 (코드가 정함 · 회차마다 바뀜)찬성") and out["parts"] == ["주장", "반박", "심판"]
    assert out["classic"] is None and out["judgeOnly"] == "편 (코드가 정함 · 회차마다 바뀜)심판심판"


def test_the_factory_card_and_the_deep_block(view):
    f = view["factory"]
    out = _node(f"""
const F = await import('@S/debate-factory.js');
const S = await import('@S/debate-side.js');
const f = {json.dumps(f, ensure_ascii=False)};
const card = F.factoryCard(); card.render(f);
const deep = F.deepBlock(); deep.render(f);
const off = F.deepBlock(); off.render({{deep: {{on: false, round: null}}}});
const due = F.deepBlock(); due.render({{deep: {{...f.deep, round: null, today: {{due_ts: Date.now() + 3600000, last: null}}}}}});
const skip = F.deepBlock(); skip.render({{deep: {{...f.deep, round: null, today: {{due_ts: 1, last: {{status: 'skipped', why: '깊은 토론 건너뜀(이번 달 몫에 닿음)'}}}}}}}});
const gone = F.factoryCard(); gone.render(null);
console.log(JSON.stringify({{
  tiles: all(all(card.el, 'db-ftoday')[0], 'db-tile').map(txt), rows: all(card.el, 'db-frow').length,
  firstRow: txt(all(card.el, 'db-frow')[0]),
  rec: all(card.el, 'db-rrow').map(txt), small: all(card.el, 'db-warn').map(txt),
  recLine: all(all(card.el, 'db-frec')[0], 'db-small').map(txt),
  why: all(card.el, 'db-wlist').map((u) => u.childNodes.length), wk: all(card.el, 'db-wk').map(txt),
  caution: txt(all(card.el, 'db-fcaution')[0]), hidden: [card.el.hidden, gone.el.hidden],
  deep: [deep.el.hidden, off.el.hidden, due.el.hidden], done: all(deep.el, 'done').map(txt),
  meta: txt(all(deep.el, 'db-dmeta')[0]), dueState: txt(all(due.el, 'db-dstate')[0]), skipState: txt(all(skip.el, 'db-dstate')[0]),
  cols: all(deep.el, 'db-partcol').length, line: txt(S.factoryLine(f)), cost: txt(S.deepCost(f)),
  classicLine: txt(S.factoryLine({{...f, mode: 'classic', mode_ko: '예전 토론(성격 다섯)'}})), noDeep: S.deepCost({{deep: {{on: false, round: null}}}})}}));
""")
    assert out["tiles"] == ["오늘 5년 시험 줄1/2", "기다리는 후보13", "다음 고르기21:00"]
    assert out["rows"] == 5 and out["firstRow"].startswith("10/15새 매매법: 깊은 토론의 아이디어")   # not today: the date
    assert out["rec"] == ["찬성통과에 건 편1번 맞음연구실 평소 비율로는 0.04번", "반대불통과에 건 편2번 맞음연구실 평소 비율로는 2.96번"]
    assert out["small"] and "결론 난 시험 3개" in out["small"][0] and "동전 던지기 50%" in out["small"][0]
    assert any("새 매매법 1/412 통과(0.2%)" in x and "36개 고쳐 보기 3/96 통과(3.1%)" in x for x in out["recLine"])
    assert any(x.startswith("반대가 짚은 칸 적중 2/3") for x in out["recLine"])
    assert out["why"] == [6, 6] and out["wk"][0] == "새 매매법 5년 시험 · 토론방 2개 · 연구실 412개"
    assert "사람 성적이 아닙니다" in out["caution"] and out["hidden"] == [False, True]
    assert out["deep"] == [False, True, False] and out["done"] == ["1 주장", "2 반박", "3 심판"] and out["cols"] == 3
    assert out["meta"].startswith("claude-opus-5-5깊은 토론 몫 이번 달 $0.6612 / $10.00 (월 한도 안)")
    assert out["dueState"].startswith("오늘은 ") and out["dueState"].endswith("(한국 시간)부터 · 아직 전")
    assert out["skipState"] == "오늘은 건너뜀: 깊은 토론 건너뜀(이번 달 몫에 닿음) · 비용 0"
    assert out["line"] == "아이디어 공장 · 오늘 5년 시험 줄 1/2 · 후보 13 · 다음 고르기 21:00"
    assert out["cost"].startswith("깊은 토론 몫 이번 달 $0.6612 / $10.00 · claude-opus-5-5")
    assert out["classicLine"].startswith("토론 방식: 예전 토론(성격 다섯)") and out["noDeep"] is None


def test_the_timeline_says_what_a_factory_or_deep_round_did():
    out = _node("""
const S = await import('@S/debate-side.js');
const why = '새로 물을 질문이 없음(같은 질문은 하루 3번까지, 같은 종류는 연달아 묻지 않음)';
console.log(JSON.stringify({
  q: S.roundKo({status: 'skipped', kind: 'factory', why}), deep: S.roundKo({status: 'skipped', kind: 'deep', why: '깊은 토론 건너뜀(하루 사용 한도에 닿음)'}),
  ok: S.roundKo({status: 'ok', kind: 'deep', cost_usd: 0.1138, turns: 5, topic: 'q', why: ''}),
  classic: S.roundKo({status: 'skipped', why: '새 청산 4건(기준 10건), 새 알림 없음'})}));
""")
    assert out["q"] == ["건너뜀", "is-skip", "새로 물을 질문 없음 · 비용 0", "새로 물을 질문이 없음(같은 질문은 하루 3번까지, 같은 종류는 연달아 묻지 않음)"]
    assert out["deep"][2] == "깊은 토론 건너뜀 · 비용 0" and out["ok"][2] == "깊은 토론 · $0.1138 · 발언 5개"
    assert out["classic"] == ["건너뜀", "is-skip", "새 소식 없음 · 비용 0", "새 청산 4건(기준 10건)"]   # unchanged


# ---------------------------------------------------------------- wiring
def test_wiring_and_css():
    js = _code(_read("debate.js"))
    assert 'import {factoryCard, deepBlock} from "./debate-factory.js";' in js
    # the room, then the deep debate's block, then the 아이디어 공장 card, then the earlier rounds
    assert 'h("div", {class: "db-main"}, live, deep.el, factory.el, histCard, ideaCard, caution)' in js
    assert "chat.find((r) => r.round_id !== deepId)" in js and "deep.render(f)" in js
    for n in ("debate-idea.js", "debate-factory.js", "debate-chat.js", "debate-side.js", "debate.js"):
        src = _code(_read(n))
        for bad in ("innerHTML", "insertAdjacentHTML", "toLocaleString", "Intl.NumberFormat", "eval("):
            assert bad not in src, (n, bad)
    side = _code(_read("debate-side.js"))
    assert "factoryLine(d.factory)" in side and "deepCost(d.factory)" in side
    css = re.sub(r"/\*.*?\*/", "", _read("debate.css"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css)
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1) or "inherit" in m.group(1) or "var(--f-" in m.group(1), m.group(0)
    assert "@container db-list (min-width: 680px)" in css and ".db-deep" in css


# ---------------------------------------------------------------- review: odd rows, today's deep state, the base rates
def test_an_odd_idea_row_never_takes_the_page_down(tmp_path):
    """A lab detail the view cannot read (not a list of failed checks, a list for a verdict, True for a test number,
    text that is not JSON) shows the idea without those parts; /api/debate's chat and factory still answer."""
    path = str(tmp_path / "debate.db")
    _world(path, deep=False, fillers=0)
    c = sqlite3.connect(path)
    ids = [r[0] for r in c.execute("SELECT id FROM debate_lab_ideas WHERE lab_status IS NULL ORDER BY id")]
    dets = ('{"failed_checks": 5}', '{"verdict": ["x"], "checks": {"a": "yes"}}', "not json",
            '{"test_number": true, "n_trials": true, "threshold": "nan"}')
    assert len(ids) == len(dets)
    for iid, det in zip(ids, dets):
        c.execute("UPDATE debate_lab_ideas SET lab_status = 'tested', lab_detail = ?, lab_test_number = NULL WHERE id = ?",
                  (det, iid))
    c.commit()
    c.close()
    out = AN.debate(path, now_ms=NOW)
    f = out["factory"]
    assert len(f["ideas"]) == 8 and f["why_fail"]["newlab"]["failed"]["①"] == 1         # the readable one still counts
    odd = [x for x in f["ideas"] if x["id"] in ids]
    assert len(odd) == 4 and all(x["lab"]["failed"] == [] and x["lab"]["test_number"] is None
                                 and x["lab"]["n_trials"] is None and x["lab"]["threshold_ko"] == "" for x in odd)
    assert all(x["lab"]["verdict"] is None or isinstance(x["lab"]["verdict"], str) for x in f["ideas"] if x.get("lab"))
    assert all(r.get("idea") for r in out["chat"] if r.get("kind"))


def _deep_state(tmp_path, name, error, mark, status="error"):
    """Today's deep state on a world whose deep debate already ran once today, then had one more round (``status``,
    ``error``) and the service's day mark ``mark``."""
    from paperbot.agents import debate as D
    from paperbot.agents import debate_factory as DF
    path = str(tmp_path / f"deep-{name}.db")
    _world(path, fillers=0)
    db = D.DB(path)
    db.conn.execute("INSERT INTO debate_rounds (ts, topic, status, model, turns, cost_usd, error, kind) VALUES "
                    "(?, 'q', ?, 'claude-opus-5-5', 0, 0, ?, 'deep')", (NOW + 2 * M, status, error))
    db.put(f"deep:{DF.P.kst_day(NOW)}", mark)
    db.close()
    return AN.debate_factory_view(path, NOW + 3 * M)["deep"]["today"]


def test_the_deep_debate_promises_a_retry_only_when_the_service_will_try(tmp_path):
    from paperbot.agents.debate import DEEP_ATTEMPTS, DEEP_RETRY_MS
    once = _deep_state(tmp_path, "once", "반박: overloaded: 529", {"attempts": 1, "last": NOW + 2 * M})
    assert once["retry"] and once["retry_ts"] == NOW + 2 * M + DEEP_RETRY_MS and once["last"]["tag"] is None
    spent = _deep_state(tmp_path, "spent", "반박: overloaded: 529", {"attempts": DEEP_ATTEMPTS, "last": NOW + 2 * M})
    assert not spent["retry"] and spent["retry_ts"] is None and spent["attempts_max"] == DEEP_ATTEMPTS
    cap = _deep_state(tmp_path, "cap", "deep_cap: 깊은 토론 건너뜀(깊은 토론 이번 달 몫($10)에 닿음)",
                      {"done": True, "skipped": "deep_cap"}, status="skipped")
    assert not cap["retry"] and cap["last"]["tag"] == "deep_cap" and cap["last"]["why"] == "깊은 토론 이번 달 몫($10)에 닿음"
    hour = _deep_state(tmp_path, "hour", "hour: 깊은 토론 건너뜀(시간당 안전장치(30분 뒤 다시))", {"last": NOW + 2 * M},
                       status="skipped")
    assert hour["retry"] and hour["last"]["tag"] == "hour" and hour["last"]["why"] == "시간당 안전장치(30분 뒤 다시)"
    out = _node(f"""
const F = await import('@S/debate-factory.js');
const st = (today) => {{ const b = F.deepBlock(); b.render({{deep: {{on: true, model: 'm', cap: 10, month: 0, round: null, today}}}}); return txt(all(b.el, 'db-dstate')[0]); }};
console.log(JSON.stringify({{once: st({json.dumps(once)}), spent: st({json.dumps(spent)}), cap: st({json.dumps(cap, ensure_ascii=False)}),
  hour: st({json.dumps(hour, ensure_ascii=False)})}}));
""")
    assert out["once"].startswith("오늘 시도가 끝나지 못함: 반박: overloaded: 529 · ") and out["once"].endswith("쯤 한 번 더 시도합니다")
    assert out["spent"] == "오늘 시도가 끝나지 못함: 반박: overloaded: 529 · 오늘은 더 시도하지 않습니다 · 내일 다시"
    assert out["cap"] == "오늘은 건너뜀: 깊은 토론 이번 달 몫($10)에 닿음 · 비용 0"
    assert out["hour"].startswith("시간당 안전장치로 잠시 미룸 · 비용 0 · ") and "한 번 더 시도합니다" in out["hour"]


def test_no_base_rate_number_before_the_lab_ledger_was_read(tmp_path):
    """An agents3.db the service could not read is stored as zero tests per engine: the record then says the usual
    rates are not collected yet, never '평소 비율로는 0번'."""
    from paperbot.agents import debate as D
    path = str(tmp_path / "debate.db")
    _world(path, deep=False, fillers=0)
    db = D.DB(path)
    db.put("factory:base_rates", {e: {"tests": 0, "passed": 0, "pass_rate": None, "fail_share": {}}
                                  for e in ("newlab", "labtest")})
    db.close()
    r = AN.debate_factory_view(path, NOW)["record"]
    assert r["settled"] == 3 and r["base_known"] is False
    out = _node(f"""
const F = await import('@S/debate-factory.js');
const card = F.factoryCard(); card.render({json.dumps(AN.debate_factory_view(path, NOW), ensure_ascii=False)});
console.log(JSON.stringify({{rec: all(card.el, 'db-rrow').map(txt)}}));
""")
    assert all(x.endswith("연구실 평소 비율 수집 전") for x in out["rec"])


def test_the_threshold_reads_like_the_labs_own_line(view):
    fail = next(x for x in view["factory"]["ideas"] if x["stage"] == "failed" and x["engine"] == "newlab")
    assert fail["lab"]["threshold_ko"] == "0.00088" and "기준 p<0.00088" in fail["lab"]["result_ko"]
    tiny = {**fail, "lab": {**fail["lab"], "threshold": 0.05 / 2001, "threshold_ko": f"{0.05 / 2001:.2g}"}}
    out = _node(f"""
const I = await import('@S/debate-idea.js');
const C = await import('@S/debate-chat.js');
const card = I.ideaCard({json.dumps(tiny, ensure_ascii=False)});
const ok = I.ideaCard({json.dumps({**tiny, "lab": None, "check_status": "ok", "stage": "candidate"}, ensure_ascii=False)});
const r = C.roundChat({{round_id: 1, ts: 1, topic: 't', messages: [{{speaker: '퀀트', text: 'x', side: '찬성'}}, {{speaker: '차트 분석가', text: 'y', side: '반대'}}]}});
console.log(JSON.stringify({{where: all(card, 'db-small').map(txt).filter((x) => x.includes('기준')),
  check: all(ok, 'db-small').map(txt).filter((x) => x.startsWith('검사')), tags: all(r, 'db-tag').map(txt)}}));
""")
    assert out["where"] == ["장부 #305 · 새 매매법 시험 57번째 · 기준 p<2.5e-05"]           # never rounded to 0.00002
    assert out["check"] == ["검사: 통과 · 시험 후보가 됨"]
    assert out["tags"] == ["차트"]                                                      # 퀀트: its name once
