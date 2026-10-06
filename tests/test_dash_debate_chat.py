"""debate-chat (owners 10/06 13:27: "에이전트 팀들끼리 서로 대화하는게 토론 아니야? … 에이전트 회의실 화면처럼 24시간
토론방도"): the 24시간 토론방 screen as a chat room.

- /api/debate's chat fields (paperbot/dash/analysis.py debate_chat), read-only, from a synthetic debate.db in the
  service's table layout: the newest finished rounds with their turns in speaking order, the reply fields only when the
  file has those columns (a debate.db from before reads as plain turns) and only with a known stance, the timeline of
  every kind of round with the stored reason, the next round from the service's own schedule (a backoff included),
  today's counts by status, the file never written;
- the chat in node with a small DOM: bubbles in speaking order, "↳ …에게" and the stance chip only where stored, the
  answer's target is the latest earlier turn of that speaker, the 정리 note pinned last as the 사회자, an old round as
  plain bubbles, the cast strip counting stored turns only;
- the status column's timeline words (토론함 / 건너뜀 with the service's reason / 오류 cause / 중단 / 토론 중 only for the
  newest running round of a running service);
- wiring greps: the 강세 / 약세 boxes are gone, no typing effect, the countdown reads the server's `next`, the honesty
  line, a phone folds the status column into one line, tokens only in the css.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess

import pytest

from paperbot.dash import analysis as AN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCR = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
NOW = 1_791_158_400_000 + 10 * 86_400_000          # 2026-10-15 00:00 UTC = 09:00 KST
M = 60_000

# the debate service's tables as they were before the reply columns (paperbot/agents/debate.py SCHEMA, 2026-10-05)
OLD_SCHEMA = """
CREATE TABLE debate_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, round_id INTEGER,
    speaker TEXT NOT NULL, stance TEXT, topic TEXT, text TEXT NOT NULL);
CREATE TABLE debate_rounds (round_id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, topic TEXT,
    in_tokens INTEGER NOT NULL DEFAULT 0, out_tokens INTEGER NOT NULL DEFAULT 0, cache_read INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT,
    model TEXT, turns INTEGER NOT NULL DEFAULT 0, prompt_version TEXT);
CREATE TABLE debate_hypotheses (id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER, ts INTEGER NOT NULL,
    speaker TEXT, kind TEXT, params_json TEXT, horizon TEXT, status TEXT NOT NULL, outcome TEXT, graded_ts INTEGER);
CREATE TABLE debate_ideas (id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER, ts INTEGER NOT NULL,
    text TEXT NOT NULL, tag TEXT, status TEXT NOT NULL DEFAULT 'new');
CREATE TABLE debate_state (k TEXT PRIMARY KEY, v TEXT);
"""


def _round(c, ts, status, topic=None, error=None, cost=0.0, turns=0):
    return c.execute("INSERT INTO debate_rounds (ts, topic, status, error, cost_usd, turns, model) VALUES (?,?,?,?,?,?,?)",
                     (ts, topic, status, error, cost, turns, "claude-sonnet-5-5")).lastrowid


def _msg(c, ts, rid, speaker, text, reply=None):
    stance = "정리" if speaker == "정리" else {"낙관론자": "낙관", "비관론자": "비관"}.get(speaker, "검증")
    if reply is None:
        c.execute("INSERT INTO debate_messages (ts, round_id, speaker, stance, topic, text) VALUES (?,?,?,?,?,?)",
                  (ts, rid, speaker, stance, "주제", text))
    else:
        c.execute("INSERT INTO debate_messages (ts, round_id, speaker, stance, topic, text, reply_to, reply_stance) "
                  "VALUES (?,?,?,?,?,?,?,?)", (ts, rid, speaker, stance, "주제", text, *reply))


def _world(path, replies):
    """Rounds oldest first: ok (old 4-turn shape), skipped, error, aborted, ok cut at max_tokens, a pruned ok round
    (no messages left), skipped, the newest ok round (the back-and-forth when ``replies``)."""
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA)
    if replies:
        c.execute("ALTER TABLE debate_messages ADD COLUMN reply_to TEXT")
        c.execute("ALTER TABLE debate_messages ADD COLUMN reply_stance TEXT")
    t0 = NOW - 300 * M
    r1 = _round(c, t0, "ok", "코인별 차이", cost=0.0131, turns=4)
    for sp in ("낙관론자", "비관론자", "회의론자", "리스크 책임자"):
        _msg(c, t0, r1, sp, f"{sp}의 예전 말")
    _msg(c, t0, r1, "정리", "정리: 예전 정리")
    _round(c, t0 + 30 * M, "skipped", error="unchanged: 새 청산 4건(기준 10건), 새 알림 없음, 새 밤 점검 없음")
    _round(c, t0 + 60 * M, "error", error="rate: HTTP 429 rate_limit_error: slow down")
    _round(c, t0 + 90 * M, "aborted", error="서비스가 도중에 멈춤")
    r5 = _round(c, t0 + 120 * M, "ok", "봉별 차이", error="답이 잘려 일부만 씀(max_tokens)", cost=0.012, turns=2)
    _msg(c, t0 + 120 * M, r5, "퀀트", "잘린 회차의 말")
    _msg(c, t0 + 120 * M, r5, "낙관론자", "잘린 회차의 둘째 말")
    _round(c, t0 + 150 * M, "ok", "지워진 회차", cost=0.01, turns=5)                    # its messages were pruned
    _round(c, t0 + 180 * M, "skipped", error="unchanged: 새 청산 1건(기준 10건), 새 알림 없음, 새 밤 점검 없음")
    t = NOW - 12 * M
    r8 = _round(c, t, "ok", "좋은 자리 vs 보통", cost=0.0158, turns=7)
    turns = [("낙관론자", None, None), ("비관론자", "낙관론자", "반대"), ("회의론자", "낙관론자", "질문"),
             ("리스크 책임자", "비관론자", "보완"), ("퀀트", "회의론자", "동의"), ("낙관론자", "비관론자", "몰라"),
             ("비관론자", "낙관론자", "보완")]
    for i, (sp, to, st) in enumerate(turns):
        _msg(c, t, r8, sp, f"{i + 1}번째 말", (to, st) if replies else None)
    _msg(c, t, r8, "정리", "정리: 결론은 없습니다")
    for k, v in (("last_attempt", NOW - 12 * M), ("run", {"state": "running", "every_min": 30, "cap": 30.0})):
        c.execute("INSERT INTO debate_state (k, v) VALUES (?, ?)", (k, json.dumps(v)))
    c.commit()
    c.close()


# ---------------------------------------------------------------- the API
def test_chat_fields_on_a_debate_db_with_the_reply_columns(tmp_path):
    path = str(tmp_path / "debate.db")
    _world(path, replies=True)
    before = os.path.getmtime(path)
    d = AN.debate_chat(path, NOW)
    assert os.path.getmtime(path) == before and not os.path.exists(path + "-wal") and not os.path.exists(path + "-journal")
    chat = d["chat"]
    assert [r["topic"] for r in chat] == ["좋은 자리 vs 보통", "봉별 차이", "코인별 차이"]     # newest first; the pruned round left out
    new = chat[0]
    assert [m["speaker"] for m in new["messages"]][:3] == ["낙관론자", "비관론자", "회의론자"]  # speaking order
    assert new["messages"][-1]["speaker"] == "정리"
    assert [(m["reply_to"], m["reply_stance"]) for m in new["messages"][:7]] == [
        (None, None), ("낙관론자", "반대"), ("낙관론자", "질문"), ("비관론자", "보완"), ("회의론자", "동의"),
        ("비관론자", None), ("낙관론자", "보완")]                                         # "몰라" is not a stance
    assert new["cost_usd"] == 0.0158 and new["turns"] == 7 and new["cut"] is False
    assert chat[1]["cut"] is True and chat[2]["messages"][0]["reply_to"] is None
    tl = d["timeline"]
    assert [r["status"] for r in tl] == ["ok", "skipped", "ok", "ok", "aborted", "error", "skipped", "ok"]
    assert tl[1]["why"] == "새 청산 1건(기준 10건), 새 알림 없음, 새 밤 점검 없음"              # without its 'unchanged:' tag
    assert tl[5]["why"].startswith("rate: HTTP 429")
    assert d["next"] == {"ts": NOW + 18 * M, "kind": "round", "every_min": 30}
    # the KST day (NOW is 09:00 KST; every round is from 04:00 on): error and aborted both count as errors
    assert d["today"] == {"ok": 4, "skipped": 2, "error": 2, "cost_usd": 0.0509}
    assert AN.debate_chat(path, NOW - 10 * 60 * M)["today"] == {"ok": 0, "skipped": 0, "error": 0, "cost_usd": 0.0}  # 23:00 the day before


def test_an_older_debate_db_reads_as_plain_turns_and_a_backoff_decides_the_next_try(tmp_path):
    path = str(tmp_path / "debate.db")
    _world(path, replies=False)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO debate_state (k, v) VALUES ('backoff:until', ?)", (json.dumps(NOW + 25 * M),))
    c.commit()
    c.close()
    d = AN.debate_chat(path, NOW)
    assert d["chat"][0]["messages"][1] == {"id": d["chat"][0]["messages"][1]["id"], "speaker": "비관론자", "stance": "비관",
                                           "text": "2번째 말", "reply_to": None, "reply_stance": None}
    assert d["next"] == {"ts": NOW + 25 * M, "kind": "retry", "every_min": 30}
    c = sqlite3.connect(path)                     # a backoff that ends before the interval: still a retry, at the interval
    c.execute("UPDATE debate_state SET v = ? WHERE k = 'backoff:until'", (json.dumps(NOW + 5 * M),))
    c.commit()
    c.close()
    assert AN.debate_chat(path, NOW)["next"] == {"ts": NOW + 18 * M, "kind": "retry", "every_min": 30}
    assert AN.debate_chat(str(tmp_path / "none.db"), NOW) == {}
    junk = str(tmp_path / "junk.db")
    sqlite3.connect(junk).execute("CREATE TABLE debate_messages (id INTEGER)").connection.commit()
    assert AN.debate_chat(junk, NOW) == {}                                             # tables missing: nothing at all


def test_the_route_carries_the_chat_fields(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from paperbot.store3 import Store3
    _ = fastapi
    paper = str(tmp_path / "paper3.db")
    Store3(paper).close()
    path = str(tmp_path / "debate.db")
    _world(path, replies=True)
    c = TestClient(create_app(paper, hash_password("pw"), b"s" * 32, debate_db=path))
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    j = c.get("/api/debate").json()
    assert j["ready"] and j["chat"][0]["messages"][1]["reply_stance"] == "반대" and len(j["timeline"]) == 8
    assert j["next"]["kind"] == "round" and set(j["today"]) == {"ok", "skipped", "error", "cost_usd"}
    assert j["rounds"] and j["messages"]                                                # the old fields stay (office console)


# ---------------------------------------------------------------- the chat in node (a small DOM)
_FAKE_DOM = r"""
class N {
  constructor() { this.parentNode = null; this.childNodes = []; }
  appendChild(c) { if (c.parentNode) c.parentNode._drop(c); c.parentNode = this; this.childNodes.push(c); return c; }
  append(...k) { for (const c of k) this.appendChild(typeof c === "string" ? new T(c) : c); }
  _drop(c) { this.childNodes = this.childNodes.filter((x) => x !== c); c.parentNode = null; }
  replaceChildren(...k) { for (const c of [...this.childNodes]) this._drop(c); this.append(...k); }
}
class T extends N { constructor(t) { super(); this.nodeType = 3; this.data = String(t); } get textContent() { return this.data; } }
class E extends N {
  constructor(tag) { super(); this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = {}; this.style = {setProperty() {}};
    this.dataset = {}; this.className = ""; this.listeners = {}; this.classList = {add() {}, remove() {}, toggle() {}}; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this.className = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(new T(v)); }
}
const all = (el, cls) => el.nodeType !== 1 ? [] : [...(String(el.className).split(" ").includes(cls) ? [el] : []), ...el.childNodes.flatMap((c) => all(c, cls))];
globalThis.Node = N;
globalThis.document = {createElement: (t) => new E(t), createElementNS: (ns, t) => new E(t), createTextNode: (t) => new T(t),
  addEventListener() {}, visibilityState: "visible", documentElement: new E("html")};
globalThis.window = globalThis; globalThis.location = {hash: ""};
globalThis.localStorage = {getItem: () => null, setItem: () => {}, removeItem: () => {}};
globalThis.matchMedia = () => ({matches: false, addEventListener() {}});
globalThis.requestAnimationFrame = () => 0;
"""


def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = _FAKE_DOM + body.replace("@S", "file://" + SCR)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_chat_shows_who_answers_whom_only_where_stored():
    out = _node("""
const C = await import('@S/debate-chat.js');
const m = (speaker, text, reply_to = null, reply_stance = null) => ({speaker, stance: speaker === '정리' ? '정리' : '', text, reply_to, reply_stance});
const round = {round_id: 9, ts: 1791158400000, topic: '주제', cost_usd: 0.0158, messages: [
  m('낙관론자', '하나'), m('비관론자', '둘', '낙관론자', '반대'), m('회의론자', '셋', '낙관론자', '질문'), m('낙관론자', '넷', '비관론자', '동의'),
  m('퀀트', '다섯', '낙관론자', null), m('리스크 책임자', '여섯', null, '보완'), m('비관론자', '일곱', '사회자', '보완'), m('정리', '정리: 결론 없음')]};
const list = C.roundChat(round);
const msgs = all(list, 'db-msg');
const re = (n) => all(n, 'db-re').map((x) => [x.tagName, x.textContent]);
const st = (n) => all(n, 'db-st').map((x) => [x.className, x.textContent]);
// tapping a reply chip jumps to the LATEST earlier turn of that speaker (turn 4 answers 비관론자: turn 2)
let jumped = null;
const target = msgs[1]; target.scrollIntoView = () => { jumped = target.dataset.i; };
const btn = all(msgs[3], 'db-re')[0]; btn.listeners.click[0]();
const later = msgs[3]; later.scrollIntoView = () => { jumped = later.dataset.i; };
all(msgs[4], 'db-re')[0].listeners.click[0]();
const old = C.roundChat({round_id: 1, ts: 1, topic: 't', messages: [m('낙관론자', 'a'), m('비관론자', 'b'), m('정리', '정리: c')]});
const strip = C.castStrip(round);
console.log(JSON.stringify({
  n: msgs.length, order: msgs.map((x) => all(x, 'db-who')[0].textContent),
  re: msgs.map(re), st: msgs.map(st), jumped,
  last: list.childNodes[list.childNodes.length - 1].className, note: all(list, 'db-pin-t')[0].textContent,
  noteWho: all(all(list, 'db-pin')[0], 'db-who')[0].textContent,
  old: [all(old, 'db-msg').length, all(old, 'db-re').length, all(old, 'db-st').length],
  strip: all(strip, 'db-castm').map((x) => [x.className, x.textContent]),
  line: C.noteLine(round), replies: [C.hasReplies(round), C.hasReplies({messages: [m('퀀트', 'x')]})],
  unknown: C.castOf('누구').name}));
""")
    assert out["n"] == 7 and out["order"][:3] == ["낙관론자", "비관론자", "회의론자"]
    assert out["re"][0] == [] and out["re"][1] == [["BUTTON", "↳ 낙관론자에게"]]
    assert out["re"][5] == []                                       # a stance without a target: the chip only
    assert out["re"][6] == [["SPAN", "↳ 사회자에게"]]                 # no earlier turn of that name: no jump button
    assert out["st"][1] == [["db-st disagree", "반대"]] and out["st"][2] == [["db-st ask", "질문"]]
    assert out["st"][3] == [["db-st agree", "동의"]] and out["st"][4] == [] and out["st"][5] == [["db-st add", "보완"]]
    assert out["jumped"] == "3"                                       # turn 5 answers 낙관론자: its latest earlier turn (4th)
    assert out["last"] == "db-pin" and out["note"] == "결론 없음" and out["noteWho"] == "사회자"
    assert out["old"] == [2, 0, 0]                                     # an old round: plain bubbles
    assert out["strip"][0] == ["db-castm", "낙관론자2번 말함"] and out["strip"][5] == ["db-castm", "사회자정리함"]
    assert out["strip"][4] == ["db-castm", "퀀트1번 말함"]
    assert out["line"] == "결론 없음" and out["replies"] == [True, False] and out["unknown"] == "누구"


def test_the_timeline_words_come_from_the_stored_round():
    out = _node("""
const S = await import('@S/debate-side.js');
const k = (r, newest = false, running = true) => S.roundKo(r, newest, running);
console.log(JSON.stringify({
  ok: k({status: 'ok', cost_usd: 0.0158, turns: 7, topic: '주제', why: ''}),
  cut: k({status: 'ok', cost_usd: 0.012, turns: 2, why: '답이 잘려 일부만 씀(max_tokens)'})[2],
  skip: k({status: 'skipped', why: '새 청산 4건(기준 10건), 새 알림 없음, 새 밤 점검 없음'}),
  err: k({status: 'error', why: 'rate: HTTP 429 x'})[2], credit: k({status: 'error', why: 'credit: HTTP 400'})[2],
  odd: k({status: 'error', why: '??'})[2], ab: k({status: 'aborted', why: ''})[2],
  live: k({status: 'running'}, true, true)[0], stuck: k({status: 'running'}, false, true)[0], off: k({status: 'running'}, true, false)[0],
  usd: [S.usd4(0.0158), S.usd4(null)]}));
""")
    assert out["ok"] == ["토론함", "is-ok", "$0.0158 · 발언 7개", "주제"] and out["cut"].endswith("일부 잘림")
    assert out["skip"] == ["건너뜀", "is-skip", "새 소식 없음 · 비용 0", "새 청산 4건(기준 10건)"]
    assert out["err"].startswith("요청이 너무 잦다는 답(429)") and out["credit"] == "API 잔액 부족" and out["odd"] == "실패"
    assert out["ab"] == "서비스가 도중에 멈춤"
    assert out["live"] == "토론 중" and out["stuck"] == "기록 중" and out["off"] == "기록 중"
    assert out["usd"] == ["$0.0158", "—"]


# ---------------------------------------------------------------- wiring
def _read(name):
    with open(os.path.join(SCR, name), encoding="utf-8") as f:
        return f.read()


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in src.splitlines())


def test_wiring_honesty_and_layout():
    js = {n: _code(_read(n)) for n in ("debate.js", "debate-chat.js", "debate-side.js")}
    every = "\n".join(js.values())
    for gone in ('"강세"', '"약세"', "db-vs", "이번 회차에 발언 없음", "typing", "setInterval", "innerHTML"):
        assert gone not in every, gone
    # the room: chat + the status column, the older rounds folded, the honesty line under the chat
    assert 'import {roundChat, castStrip, avatar, noteLine, hasReplies, isNote, CAST} from "./debate-chat.js";' in js["debate.js"]
    assert 'import {makeSide, usd4} from "./debate-side.js";' in js["debate.js"]
    assert "AI 하나가 다섯 역할과 사회자를 모두 맡아 말하는 방입니다" in js["debate.js"] and "의견이지 사실이 아닙니다" in js["debate.js"]
    assert "history.set(chat.slice(1), true)" in js["debate.js"] and 'motion.expand(region, open)' in js["debate.js"]
    assert "store.refresh(\"debate\")" in js["debate.js"] and "ctx.every(1000" in js["debate.js"]
    # the countdown reads the server's schedule first (the old guess only for an older server)
    assert "d.next && d.next.ts" in js["debate-side.js"] and "countdown(nx.ts, serverNow())" in js["debate-side.js"]
    assert '"다시 시도까지"' in js["debate-side.js"] and '"다음 회차까지"' in js["debate-side.js"]
    # 토론 중 only from the service's state; the in-flight line only from the newest stored round
    assert 'running: ["토론 중", "live"]' in js["debate-side.js"] and 'paused: ["쉬는 중", "warn"]' in js["debate-side.js"]
    assert '((d.timeline || [])[0] || {}).status === "running"' in js["debate-side.js"]
    assert '"채점 대기"' in js["debate-side.js"] and '"맞음"' in js["debate-side.js"] and '"틀림"' in js["debate-side.js"]
    css = re.sub(r"/\*.*?\*/", "", _read("debate.css"), flags=re.S)
    assert css.startswith('@import url("rooms-kit.css");')
    assert ".db-side:not(.open) .db-sbody { display: none; }" in css           # a phone: the status folds into one line
    assert ".db-side .db-stoggle { display: none; }" in css                     # a wide screen: always open
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css)
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;]+);", css):
        assert not re.search(r"\d+(\.\d+)?(px|rem|em)\b", m.group(1).split("/")[0]), m.group(0)
