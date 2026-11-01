"""실거래 › 회의실 (#/room; dash/more/liveroom.py + screens/livebots-room.js / livebots-room.css; owners 2026-11-01, with a
picture and a video of someone's 'AI office' trading dashboard: "이렇게 가능할까?").

- the seats: each one a real program, read from its own files and systemd: the three live bots (holding, waiting, off,
  stopped) and their paper twins, their checks (the 5-minute pass, the morning check, a stale pass, none), the AI
  분석팀's four members (their newest words, a meeting under way, the timer off, systemd not answering, no record yet),
  the backup and this site; the feed (the bots', the twins', the checks', the team's rows, newest first), the 24-hour
  pulse, the team's totals and positions; one bot's broken files never hide the others
- the route in the live app, behind its login
- the pure functions in node (ago, the bar closes and their clock, the seats round the table, the projection, a tag, the
  pulse, the counts) and the whole screen rendered in node on the real answer: no null / undefined / NaN
- static: tokens only, imports through pb.js, read-only, the decoration said on the screen, the tab and the menu
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess

import pytest

pytest.importorskip("fastapi")

from paperbot import liveteam as T  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livedeck as D  # noqa: E402
from paperbot.dash.more import liveroom as R  # noqa: E402
from tests.test_dash_livedeck import BAD, CE, NOW, world  # noqa: E402,F401  (the three bots' world)
from tests.test_mixbybit_checks import DAY0, H, MIN  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-room.js")
CSS = os.path.join(SCREENS, "livebots-room.css")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
IDS = ["bybit-live", "bybit-paper", "bybit-check", "mix-live", "mix-paper", "mix-check", "range-live", "range-paper", "range-check",
       "team-risk", "team-stats", "team-market", "team-lead", "ops-backup", "ops-site"]
ON = lambda u: ("active", "enabled")      # noqa: E731
RAN = lambda u: NOW - 5 * H               # noqa: E731


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _touch(path, ms):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{}")
    os.utime(path, (ms / 1000, ms / 1000))


@pytest.fixture
def room(world, monkeypatch):
    tmp = world["tmp"]
    d = str(tmp / "check-range")
    _touch(os.path.join(d, "state.json"), NOW - 2 * MIN)                  # the 5-minute pass, just now
    _touch(os.path.join(d, "last-morning.json"), NOW - 14 * H)            # this morning's check
    monkeypatch.setenv("PAPERBOT_MIXRANGECHECK_DIR", d)
    monkeypatch.setenv("PAPERBOT_MIXBYBITCHECK_DIR", str(tmp / "no-check"))
    monkeypatch.setenv("PAPERBOT_MIXCHECK_DIR", str(tmp / "no-check-mix"))
    db = str(tmp / "liveteam.db")
    c = sqlite3.connect(db)
    c.executescript(T.SCHEMA)
    c.execute("INSERT INTO meetings (kind, key, title, started_ts, finished_ts, state, headline) VALUES (?,?,?,?,?,?,?)",
              ("weekly", "weekly:2026-10-26", "주간 보고", NOW - 3 * H, NOW - 3 * H + 10 * MIN, "done", "지켜보기"))
    for i, (role, text) in enumerate((("risk", "낙폭은 정상 범위\n둘째 줄"), ("stats", "표본이 적어요"), ("market", "횡보가 많았어요"),
                                      ("lead", "지켜보기: 20번까지 그대로"))):
        c.execute("INSERT INTO messages (meeting, seq, role, ts, text) VALUES (1, ?, ?, ?, ?)", (i, role, NOW - 3 * H + (i + 1) * MIN, text))
    c.commit()
    c.close()
    monkeypatch.setenv(T.DB_ENV, db)
    return {**world, "db": db, "check": d}


def test_each_seat_is_a_real_program_read_from_its_own_files(room):
    d = json_finite(R.build(NOW, ON, RAN))
    json.dumps(d, allow_nan=False)
    seats = {s["id"]: s for s in d["seats"]}
    assert [s["id"] for s in d["seats"]] == IDS
    assert all(s["state"] in ("live", "wait", "idle", "off", "error") and s["group_ko"] == R.GROUP_KO[s["group"]] for s in d["seats"])
    # the bots: the 레인지 봇 holds a SOL short, the 바이비트 봇 waits for its bar, the 친구 15분 봇 is not installed
    rg = seats["range-live"]
    assert rg["state"] == "live" and rg["state_ko"] == "보유 중 · SOL 숏" and rg["last_ms"] == NOW - 2 * H
    assert rg["last_ko"] == "진입 · 숏 진입 104.6 · 손절 106" and rg["unit"] == "paperbot-mixrange"
    assert rg["role_ko"] == "WOO X Pro 실거래 · 15분봉 진입 · 30분봉 추세"
    by = seats["bybit-live"]
    assert by["state"] == "wait" and by["state_ko"].startswith("신호 기다리는 중 (") and by["last_ko"] == "아직 기록이 없어요"
    assert seats["mix-live"]["state"] == "off" and seats["mix-paper"]["state"] == "off" and seats["mix-check"]["state"] == "off"
    # the paper twin: its own newest row
    rp = seats["range-paper"]
    assert rp["state"] == "wait" and rp["last_ms"] == NOW - 2 * H + 60_000 and rp["last_ko"].startswith("진입 · 숏 진입 104.6")
    # the checks: a pass two minutes ago; none for the 바이비트 봇
    rc = seats["range-check"]
    assert rc["state"] == "idle" and rc["last_ms"] == NOW - 2 * MIN and rc["last_ko"] == "손실 카드 확인" and rc["unit"] == "paperbot-mixrangecheck"
    assert seats["bybit-check"]["state"] == "off" and seats["bybit-check"]["last_ms"] is None
    # the AI team: each member's newest words (the first line), waiting for the next meeting; they never trade
    risk = seats["team-risk"]
    assert risk["state"] == "idle" and risk["last_ko"] == "낙폭은 정상 범위" and risk["name_ko"] == "방패" and "거래 안 함" in risk["role_ko"]
    assert [seats[f"team-{r}"]["name_ko"] for r in ("stats", "market", "lead")] == ["저울", "나침반", "등대"]
    # the backup (systemd's last start), this site
    assert seats["ops-backup"]["state"] == "idle" and seats["ops-backup"]["last_ms"] == NOW - 5 * H
    assert seats["ops-site"]["state"] == "live" and seats["ops-site"]["last_ms"] == NOW
    # the feed: newest first, every program's rows in words
    feed = d["feed"]
    assert [r["ts"] for r in feed] == sorted((r["ts"] for r in feed), reverse=True) and len(feed) <= R.FEED_N
    assert not any("None" in r["text"] for r in feed)
    kinds = {r["kind"] for r in feed}
    assert {"entry", "exit", "paper_entry", "paper_exit", "meeting"} <= kinds
    assert next(r for r in feed if r["kind"] == "meeting")["text"] == "주간 보고 · 지켜보기"
    assert next(r for r in feed if r["kind"] == "paper_entry")["who_ko"] == "모의 레인지 봇"
    # the pulse (24 h): the two entries (the closed trade's and the open short's), the ETH cross, the check, the meeting
    p = d["pulse"]
    assert p["entries"] == 2 and p["signals"] >= 1 and p["checks"] == 1 and p["meetings"] == 1
    assert d["team"] == D.totals_view([b for b in [D.bot_view(__import__("paperbot.dash.more.livemix", fromlist=["x"]).PROFILES[x], NOW)
                                                    for x in D.BOT_ORDER]])
    assert [(x["bot"], x["coin"], x["side"]) for x in d["positions"]] == [("range", "SOL", -1)]


def test_states_said_as_they_are(room):
    # a stale pass, the morning check newest, a meeting under way, the timer off, systemd not answering, no team record
    _touch(os.path.join(room["check"], "state.json"), NOW - 40 * MIN)
    _touch(os.path.join(room["check"], "last-morning.json"), NOW - 10 * MIN)
    d = R.build(NOW, ON, RAN)
    rc = next(s for s in d["seats"] if s["id"] == "range-check")
    assert rc["state"] == "error" and rc["state_ko"] == "마지막 5분 확인: 40분 전 (멈췄을 수 있어요)"
    assert rc["last_ko"] == "아침 점검을 보냈어요" and any(r["kind"] == "check" for r in d["feed"])
    c = sqlite3.connect(room["db"])
    c.execute("INSERT INTO meetings (kind, key, title, started_ts, state) VALUES ('loss', 'loss:x', '손실 회의', ?, 'running')", (NOW - MIN,))
    c.commit()
    c.close()
    assert {s["state_ko"] for s in R.build(NOW, ON, RAN)["seats"] if s["group"] == "ai"} == {"회의 중"}
    off = R.build(NOW, lambda u: ("inactive", "disabled"), lambda u: None)
    team = [s for s in off["seats"] if s["group"] == "ai"]
    assert all(s["state"] == "live" for s in team)                      # (a meeting under way is said whatever the timer)
    os.remove(room["db"])
    none = R.build(NOW, lambda u: ("", ""), lambda u: None)
    ai = [s for s in none["seats"] if s["group"] == "ai"]
    assert all(s["state"] == "off" and s["state_ko"] == "systemd에 물어볼 수 없어요" and s["last_ko"] == "아직 회의에서 한 말이 없어요" for s in ai)
    bk = next(s for s in none["seats"] if s["id"] == "ops-backup")
    assert bk["state"] == "off" and bk["last_ms"] is None
    off2 = R.build(NOW, lambda u: ("inactive", "disabled"), lambda u: None)
    assert {s["state_ko"] for s in off2["seats"] if s["group"] == "ai"} == {"분석팀 타이머가 꺼져 있어요"}


def test_one_bots_broken_files_never_hide_the_others(room, monkeypatch):
    real = D.bot_view

    def broken(prof, now):
        if prof.id == "bybit":
            raise ValueError("bad file")
        return real(prof, now)
    monkeypatch.setattr(D, "bot_view", broken)
    d = json_finite(R.build(NOW, ON, RAN))
    seats = {s["id"]: s for s in d["seats"]}
    assert seats["bybit-live"]["state"] == "error" and seats["range-live"]["state"] == "live" and len(d["seats"]) == len(IDS)


def test_the_route_in_the_live_app_behind_its_login(room, tmp_path):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    from tests.test_livedash_app import PW, _app
    assert "liveroom" in LA.MODULES
    c = TestClient(_app(tmp_path))
    assert c.get(R.ROUTE).status_code in (401, 403)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get(R.ROUTE)
    assert r.status_code == 200 and [s["id"] for s in r.json()["seats"]] == IDS


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


def test_the_pure_functions():
    out = _node("""const now = Date.UTC(2026, 10, 1, 4, 6, 47);
console.log(JSON.stringify({
  ago: [M.agoKo(now, now - 20000), M.agoKo(now, now - 12 * 60000), M.agoKo(now, now - 3 * 3600000), M.agoKo(now, now - 50 * 3600000), M.agoKo(now, null)],
  closes: M.nextCloses(now), now,
  clock: [M.clockKo(373000), M.clockKo(2173000), M.clockKo(9373000), M.clockKo(-5)],
  seats: [M.seatAt(0, 4), M.seatAt(1, 4), M.seatAt(2, 4)],
  p0: M.project({cx: 100, cy: 100, S: 50, th: 0, el: 0, D: 4}, 0, 0, 0),
  p1: M.project({cx: 100, cy: 100, S: 50, th: 0, el: 0, D: 4}, 1, 1, 0),
  far: M.project({cx: 0, cy: 0, S: 1, th: 0, el: 0.6, D: 4}, 0, 0, 1), near: M.project({cx: 0, cy: 0, S: 1, th: 0, el: 0.6, D: 4}, 0, 0, -1),
  tag: M.tagOf({id: "x", group: "ai", name_ko: "방패", role_ko: "리스크", state: "idle", state_ko: "쉬는 중", last_ms: now - 5 * 60000}, now),
  tag0: M.tagOf({}, now),
  pulse: M.pulseRows({signals: 4, entries: 2, exits: 1, checks: 0, meetings: null}), pulse0: M.pulseRows(null),
  counts: M.stateCounts([{state: "live"}, {state: "wait"}, {state: "wait"}, {state: "x"}, null]),
  api: M.ROOM_API,
}));""")
    assert out["ago"] == ["방금", "12분 전", "3시간 전", "2일 전", "기록 없음"]
    now = out["now"]
    assert [c["ko"] for c in out["closes"]] == ["15분", "30분", "1시간", "4시간", "1일"]
    assert [c["left"] for c in out["closes"]] == [8 * 60000 + 13000, 23 * 60000 + 13000, 53 * 60000 + 13000, 3 * 3600000 + 53 * 60000 + 13000,
                                                   19 * 3600000 + 53 * 60000 + 13000]
    assert all(c["at"] - c["left"] == now for c in out["closes"])
    assert out["clock"] == ["6:13", "36:13", "2:36:13", "0:00"]
    s0, s1, s2 = out["seats"]
    assert s0["x"] == pytest.approx(0, abs=1e-9) and s0["z"] == pytest.approx(1.38) and s2["z"] == pytest.approx(-1.38)
    assert s1["x"] == pytest.approx(-1.38) and s1["z"] == pytest.approx(0, abs=1e-9)
    assert out["p0"] == [100, 100, 0, 1] and out["p1"] == [150, 50, 0, 1]
    assert out["far"][2] > 0 > out["near"][2] and out["far"][1] < out["near"][1] and out["far"][3] < out["near"][3]
    assert out["tag"] == {"cls": ["rm-tag", "idle", "g-ai"], "name": "방패", "role": "리스크", "line": "쉬는 중 · 5분 전"}
    assert out["tag0"] == {"cls": ["rm-tag", "off", "g-ops"], "name": "?", "role": "", "line": "— · 기록 없음"}
    assert out["pulse"] == [["신호", 4, 1], ["진입", 2, 0.5], ["청산", 1, 0.25], ["점검", 0, 0], ["회의", 0, 0]]
    assert [r[1] for r in out["pulse0"]] == [0, 0, 0, 0, 0]
    assert out["counts"] == {"live": 1, "wait": 2, "idle": 0, "error": 0, "off": 0}
    assert out["api"] == R.ROUTE


def test_the_whole_screen_renders_on_the_real_answer(room):
    d = json_finite(R.build(NOW, ON, RAN))
    out = _node("""
const ctx = {params: {query: {}}, alive: () => true, api: async (p) => { await null; if (A.fail) throw Object.assign(new Error("x"), {status: 0, kind: "network"}); return A.d; },
  every(ms, fn, o) { if (!o || o.now !== false) fn(); }, track() {}, listen() {}, watch() {}, on() {}, timeout() {}, href: (n, a) => '#/' + n + '/' + a};
const v = M.roomView(ctx);
await new Promise((r) => setTimeout(r, 40));
const ok = T.walk(v.el);
A.fail = true; A.d = null;
const v2 = M.roomView(ctx);
await new Promise((r) => setTimeout(r, 40));
console.log(JSON.stringify({ok: ok.text, cls: ok.classes.join(" "), bad: T.walk(v2.el).text}));""", {"d": d})
    t = out["ok"]
    assert not BAD.search(t), BAD.search(t)
    for w in ("회의실", "팀 상태", "다음 봉 마감", "포지션", "팀 맥박", "활동", "자리", "레인지 봇", "모의 레인지 봇", "레인지 봇 점검", "방패", "저울",
              "나침반", "등대", "백업", "사이트", "보유 중 · SOL 숏", "SOL 숏", "15분 마감", "1일 마감", "장식", "거래하지 않아요"):
        assert w in t, w
    assert "rm-tag live g-bot" in out["cls"] and "rm-rs live" in out["cls"] and "rm-cnt live" in out["cls"]
    assert not BAD.search(out["bad"])


# ---------------------------------------------------------------- static
def test_tokens_only_imports_through_pb_and_read_only():
    css, js, tok = _read(CSS), _read(JS), _read(os.path.join(V4, "tokens.css"))
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", body)
    for m in re.finditer(r"font-size\s*:\s*([^;}]+)", body):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    used = set(re.findall(r"var\((--dk-[\w-]+)\)", css)) | set(re.findall(r'"(--dk-[\w-]+)"', js))
    defined = set(re.findall(r"^\s*(--dk-[\w-]+)\s*:", tok, flags=re.M))
    assert used and used <= defined, used - defined
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", re.sub(r"//[^\n]*", "", js))
    assert re.findall(r'from\s+"([^"]+)"', js) == ["../core/pb.js"]
    assert "innerHTML" not in js and "fetch(" not in js and "POST" not in js and "DOMParser" not in js
    assert "그림은 장식" in js and "사람 모양 그림은 장식이에요" in js


def test_the_tab_and_the_menu():
    routes, lb = _read(os.path.join(V4, "core", "routes.js")), _read(os.path.join(SCREENS, "livebots.js"))
    assert '"now", ko: "지금", screens: ["deck", "trend", "tchart", "hq", "pos", "room",' in routes
    assert re.search(r'room: \{ko: "회의실", group: "now"', routes) and "  room: () => [" in routes
    assert 'import {roomView} from "./livebots-room.js";' in lb
    assert '{id: "room", label: "회의실", make: (ctx) => roomView(ctx), own: true, bare: true}' in lb
    assert '@import url("livebots-room.css");' in _read(os.path.join(SCREENS, "livebots.css"))
    assert "#/room" in _read(os.path.join(V4, "INVENTORY.md"))
    assert "room:" in _read(os.path.join(V4, "core", "search.js")).split("export const LIVE_ALIAS")[0] + "room:"
