"""agents-ui: the AI staff screens made messenger-quality (에이전트 방 · 회의실 · 회의 요약 · 토론방 · 매매법 상세 AI 의견).

- the pure JS helpers in node (screens/agents-ui.js): message type badges read only from the stored message (kind,
  data.answer findings / proposal / ask_next, the agents' own render() lines for older rows), 두 분 메모, exact
  strategy / account ids for the mini cards (unknown ids ignored, at most three), the leaderboard's Wilson order,
  the running hit-rate series per role and the hypothesis status (맞음 / 틀림 / 진행 중 / 기간 만료 / 채점 불가);
- the server data the screens read, on a synthetic agents3.db written with the repo's own helpers: /api/agents/feed
  carries room_id (unread counts per room), /api/trials carries every hypothesis with its latest result and the
  per-role scorecard, /api/office a running meeting's turns / participants / next_role (progress line, status chips);
- wiring greps: the chat's filters / search / pinned conclusion / smooth scroll only for really new rows, no typing,
  DeepSeek / coin-flip mini cards without numbers, the office progress and schedule line, the digest's 결정 보드 tab,
  the debate's two columns / meters / countdown / off steps, the strategy detail mount (one import + one line),
  tokens only in the new css (font sizes var(--t-*), no colour literals).
"""
import json
import os
import re
import shutil
import subprocess
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCR = os.path.join(V4, "screens")
PW = "correct horse battery"


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src):
    """JS without // and /* */ comments (strings kept)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in src.splitlines())


# ---------------------------------------------------------------- JS logic in node
def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = ("globalThis.localStorage = {getItem: () => null, setItem: () => {}, removeItem: () => {}};"
           "globalThis.matchMedia = () => ({matches: false, addEventListener() {}});"
           "globalThis.document = {createElement: () => ({}), visibilityState: 'visible', addEventListener() {}};"
           "globalThis.window = globalThis; globalThis.location = {hash: ''};\n")
    script = pre + body.replace("@S", "file://" + SCR)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and ("document" in r.stderr or "is not defined" in r.stderr):
        pytest.skip("module needs a browser: " + r.stderr.strip().splitlines()[-1][:200])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_type_badges_come_only_from_the_stored_message():
    out = _node("""
const A = await import('@S/agents-ui.js');
const t = (m) => A.msgTypes(m);
console.log(JSON.stringify({
  summary: t({kind: 'summary', text: '1. 결론'}),
  decision: t({kind: 'decision', text: '🧾 결정', data: {action: 'propose_copy'}}),
  note: t({kind: 'decision', text: '🧾 결정: 메모', data: {action: 'note'}}),
  code: t({kind: 'code_result', text: '5년 시험'}),
  answer: t({kind: 'analysis', text: 'x', data: {answer: {findings: [{kind: 'fact'}, {kind: 'hypothesis'}], proposal: {action: 'request_test'}, ask_next: '?'}}}),
  hypProp: t({kind: 'analysis', text: 'x', data: {answer: {proposal: {action: 'hypothesis'}}}}),
  noAction: t({kind: 'analysis', text: 'x', data: {answer: {proposal: {action: 'no_action'}}}}),
  plain: t({kind: 'analysis', text: '그냥 의견입니다'}),
  oldLines: t({kind: 'analysis', text: '머리\\n- [사실] a\\n- [가설] b\\n제안: 5년 시험 — x\\n❓ 다음 분께: y'}),
  oldNone: t({kind: 'analysis', text: '제안: 없음\\n제안: 행동 없음'}),
  ownerQ: t({kind: 'owner', text: '어느 쪽이 걱정되나요?'}),
  ownerS: t({kind: 'owner', text: '잘 봤습니다'}),
  own: [A.forOwners({kind: 'owner'}), A.forOwners({kind: 'summary', data: {answer: {reply_to_owner: 'x'}}}),
        A.forOwners({kind: 'analysis', text: 'a\\n💬 두 분께: b'}), A.forOwners({kind: 'analysis', text: '두 분 이야기 아님'})],
}));
""")
    assert out["summary"] == ["conclusion"]
    assert out["decision"] == ["conclusion", "proposal"] and out["note"] == ["conclusion"]
    assert out["code"] == ["data"]
    assert out["answer"] == ["proposal", "hypothesis", "question", "data"]
    assert out["hypProp"] == ["hypothesis"] and out["noAction"] == [] and out["plain"] == []
    assert out["oldLines"] == ["proposal", "hypothesis", "question", "data"] and out["oldNone"] == []
    assert out["ownerQ"] == ["question"] and out["ownerS"] == []
    assert out["own"] == [True, True, True, False]


def test_mini_card_refs_are_exact_ids_the_board_knows():
    out = _node("""
const A = await import('@S/agents-ui.js');
const board = {accounts: [{account_id: 'S2_ST_ROC@15m', strategy: 'S2_ST_ROC'}, {account_id: 'S2_ST_ROC@1h', strategy: 'S2_ST_ROC'},
  {account_id: 'N17_KC_RSI@1h', strategy: 'N17_KC_RSI'}, {account_id: 'F13_FVG_PD@15m', strategy: 'F13_FVG_PD'}, {account_id: 'V39_ALL@4h', strategy: 'V39_ALL'}]};
console.log(JSON.stringify({
  a: A.refsOf('S2_ST_ROC@15m 손절이 짧고 S2_ST_ROC 전체도 그렇습니다', board),
  b: A.refsOf('N17_KC_RSI 와 XYZ_NOPE@15m, NOPE_ROC', board),
  c: A.refsOf('S2_ST_ROC N17_KC_RSI F13_FVG_PD V39_ALL', board),
  d: A.refsOf('아무 이름 없음', board), e: A.refsOf('S2_ST_ROC', {accounts: []}),
  f: A.refsOf('S2_ST_ROC@1hx', board)}));
""")
    assert out["a"] == [{"type": "account", "id": "S2_ST_ROC@15m"}]       # the account card already names its strategy
    assert out["b"] == [{"type": "strategy", "id": "N17_KC_RSI"}]         # unknown ids are ignored
    assert len(out["c"]) == 3                                              # at most three cards
    assert out["d"] == [] and out["e"] == [] and out["f"] == []


def test_leaderboard_order_series_and_hypothesis_status():
    out = _node("""
const A = await import('@S/agents-ui.js');
const hyp = (by, ts, res, pred = true) => ({kind: 'hypothesis', ts, spec: {by, text: 't', ...(pred ? {prediction: {metric: 'win_rate'}} : {})},
  result: res === undefined ? null : res === 'exp' ? {status: 'expired', ts: ts + 1, result: {status: 'expired'}} : {status: 'graded', ts: ts + 1, result: {correct: res}}});
const rows = [hyp('a', 1, true), hyp('a', 2, true), hyp('b', 1, true), hyp('b', 2, false), hyp('b', 3, true), hyp('b', 4, true),
  hyp('b', 5, true), hyp('b', 6, true), hyp('b', 7, true), hyp('b', 8, true), hyp('b', 9, true), hyp('b', 10, true),
  hyp('a', 3), hyp('c', 1, 'exp'), hyp('c', 2, undefined, false), {kind: 'test', spec: {by: 'a'}}];
const by = A.gradesByRole(rows);
console.log(JSON.stringify({
  a: [by.a.graded, by.a.correct, by.a.waiting, by.a.series], b: [by.b.graded, by.b.correct, by.b.series[1]], c: [by.c.graded, by.c.expired, by.c.notGradable],
  w: [A.wilsonLow(2, 2) < A.wilsonLow(9, 10), A.wilsonLow(0, 0), A.wilsonLow(5, 10) < 0.5],
  st: rows.slice(12, 15).map((t) => A.hypStatus(t)[0]).concat([A.hypStatus(rows[0])[0], A.hypStatus(rows[3])[0]])}));
""")
    assert out["a"] == [2, 2, 1, [1, 1]]
    assert out["b"] == [10, 9, 0.5]
    assert out["c"] == [0, 1, 1]
    assert out["w"] == [True, 0, True]                        # 2 of 2 does not outrank 9 of 10
    assert out["st"] == ["진행 중", "기간 만료", "채점 불가", "맞음", "틀림"]


# ---------------------------------------------------------------- the server data the screens read
def _agents_db(path, now):
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=now - 86_400_000)
    room = "strat:S2_ST_ROC"
    cur = c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status) VALUES (?,?,?,?,?)",
                    (room, "loss_cluster", "{}", now - 120_000, "running"))
    rid = int(cur.lastrowid)
    c.commit()
    R.post(c, room, rid, "loss_cluster", "code", None, "trigger", "📣 회의 시작: 손실 묶음 복기", ts=now - 120_000)
    R.post(c, room, rid, "loss_cluster", "spec_S2_ST_ROC", None, "analysis", "손실 3건 중 2건이 S2_ST_ROC@15m입니다.\n- [사실] 2/3",
           {"turn": "specialist", "answer": {"findings": [{"kind": "fact", "claim": "2/3"}]}}, ts=now - 60_000)
    t1 = R.add_trial(c, room, "S2_ST_ROC", "hypothesis", {"text": "승률 40% 넘음", "by": "pnl_reviewer",
                                                          "prediction": {"metric": "win_rate", "direction": "above", "value": 0.4, "after_trades": 30}},
                     ts=now - 5 * 86_400_000)
    R.add_trial_result(c, t1, "graded", {"status": "graded", "correct": True, "value": 0.43, "n": 30}, ts=now - 86_400_000)
    R.add_trial(c, room, "S2_ST_ROC", "hypothesis", {"text": "예측 없음", "by": "whatif"}, ts=now - 3_600_000)
    c.commit()
    c.close()


@pytest.fixture()
def client(tmp_path):
    from paperbot.store3 import Store3
    db = str(tmp_path / "paper3.db")
    Store3(db).close()
    now = int(time.time() * 1000)
    adb = str(tmp_path / "agents3.db")
    _agents_db(adb, now)
    app = create_app(db, hash_password(PW), b"s" * 32, agents_db=adb)
    c = TestClient(app)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


def test_feed_trials_and_office_carry_what_the_screens_read(client):
    feed = client.get("/api/agents/feed?after_id=0&limit=400").json()
    assert feed and all("room_id" in r and "kind" in r for r in feed)                 # unread counts per room
    assert {r["room_id"] for r in feed} == {"strat:S2_ST_ROC"}
    tr = client.get("/api/trials?limit=500").json()
    hyps = [t for t in tr["trials"] if t["kind"] == "hypothesis"]
    assert len(hyps) == 2
    graded = next(t for t in hyps if t["result"])
    assert graded["spec"]["by"] == "pnl_reviewer" and graded["result"]["status"] == "graded" and graded["result"]["result"]["correct"] is True
    assert any(r["role"] == "pnl_reviewer" and r["name"] for r in tr["scorecard"]["roles"])
    o = client.get("/api/office").json()
    m = next(x for x in o["running"] if x["room_id"] == "strat:S2_ST_ROC")
    assert len(m["turns"]) == 1 and "spec_S2_ST_ROC" in m["participants"] and "spec_S2_ST_ROC" in m["lines"]
    assert m["last_role"] == "spec_S2_ST_ROC" and m["next_role"] == "devils_advocate"   # the order names the next one
    msgs = client.get("/api/rooms/strat:S2_ST_ROC/messages?limit=80").json()["messages"]
    assert [x["kind"] for x in msgs] == ["trigger", "analysis"]
    assert client.get("/api/rooms/strat:F13_FVG_PD/messages?limit=80").status_code == 404   # no room: no AI card


# ---------------------------------------------------------------- wiring greps
def test_chat_filters_search_pin_and_honest_scroll():
    src = _code(_read("screens", "rooms-chat.js"))
    for s in ('"전체"', '"결론만"', '"두 분 메모"', '"이 방 대화 찾기"', '"최근 결론"', "typeBadges(", "pixAvatar(", "miniCards(", "dayLabel("):
        assert s in src, s
    # smooth scroll only in appendNew (really new rows after the first paint) and only for a reader at the bottom
    assert src.count("toBottom(true)") >= 1 and "if (stick) requestAnimationFrame(() => toBottom(true)); else newBtn.hidden = false;" in src
    assert "requestAnimationFrame(() => toBottom(false))" in src             # the first paint jumps, no animation
    for bad in ("typing", "setInterval", "innerHTML"):
        assert bad not in src, bad
    rooms = _code(_read("screens", "rooms.js"))
    assert "/api/agents/feed?after_id=" in rooms and "rm-ucount" in rooms and '"99+"' in rooms
    # a cached store value runs the watch callback at once: the unread helpers must exist before it is registered
    assert rooms.index("const unreadSoon = ") < rooms.index('ctx.watch("rooms"')
    # the progress line is read from /api/office running only
    assert 'store.get("office")' in src and "next_role" in src


def test_quiet_groups_get_no_number_in_mini_cards():
    src = _code(_read("screens", "agents-ui.js"))
    assert 'new Set(["ds200", "random"])' in src
    quiet = re.findall(r"quiet \? (.+?)\n", src)
    assert len(quiet) == 2 and all("ui.pill(" in q and "fmt." not in q for q in quiet)     # the quiet branch: a pill only
    assert "USDT" not in src and "fmt.usdt" not in src


def test_office_progress_status_and_schedule():
    fl = _code(_read("screens", "office-floor.js"))
    assert "function progress(m, roles)" in fl and "function statusChips(m, roles)" in fl
    for s in ('"방금 발언"', '"다음 차례"', '"발언함"', '"대기"', "m.next_role === r", "m.last_role === r", "발언 ${fmt.int(turns)}번째"):
        assert s in fl, s
    sc = _code(_read("screens", "office-sched.js"))
    assert "el.hidden = !office || !!(office.running || []).length" in sc             # only while no meeting runs
    assert "countdown(" in sc and "timeline(" in sc
    assert "makeSched(ctx)" in _read("screens", "office.js")


def test_digest_board_tab_and_leaderboard():
    dg = _read("screens", "digest.js")
    assert '{id: "board", label: "결정 보드"}' in dg and "board: makeBoard" in dg
    b = _code(_read("screens", "digest-board.js"))
    for s in ('"누가"', '"왜"', '"다음"', "/api/digest/day?day=", "/api/trials?limit=500", "wilsonLow(", "ui.sparkline(", "ui.smallSample(k.graded, 20)",
              '"오늘"', '"이번 주 (7일)"'):
        assert s in b, s
    assert "staffBoard(ctx)" in _read("screens", "digest-staff.js")


def test_debate_live_view_meters_and_off_steps():
    d = _code(_read("screens", "debate.js"))
    for s in ('"강세"', '"약세"', '"판정 미터"', '"이번 달 사용"', "한도 ", "countdown(", "every_min * 60000", '"이번 회차 정리"',
              "sudo systemctl enable --now paperbot-debate", "아직 시작 전 · 켜면 하루 종일 토론", "실제 비용 (유료 API)"):
        assert s in d, s
    assert "typing" not in d and "setInterval" not in d


def test_strategy_detail_mount_is_one_import_and_one_line():
    sd = _read("screens", "strategies-detail.js")
    assert sd.count("aiOpinionCard") == 2
    assert 'import {aiOpinionCard} from "./strategies-ai.js";' in sd
    assert 'if (kind === "strategy") right.insertBefore(aiOpinionCard(ctx, name), acctCard);' in sd
    ai = _code(_read("screens", "strategies-ai.js"))
    assert "/api/rooms/${encodeURIComponent(room)}/messages?limit=80" in ai and "card.hidden = true" in ai
    assert "USDT" not in ai


def test_new_css_uses_tokens_and_is_loaded():
    assert _read("screens", "rooms-kit.css").startswith('@import url("agents-ui.css");')
    assert '@import url("agents-ui.css");' in _read("screens", "strategies.css")
    for f in ("agents-ui.css", "rooms.css", "office.css", "digest.css", "debate.css"):
        src = re.sub(r"/\*.*?\*/", "", _read("screens", f), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), f
        assert not re.search(r"\brgba?\(\s*\d", src), f
        for m in re.finditer(r"font(?:-size)?\s*:\s*([^;]+);", src):
            v = m.group(1)
            if re.search(r"\d+(\.\d+)?(px|rem|em)\b", v.split("/")[0]):
                pytest.fail(f"{f}: font size not a token: {v}")
