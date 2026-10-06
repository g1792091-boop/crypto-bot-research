"""The dashboard update after the 10/06 install (the install candidate joined with the reliability / verdict-day /
accounts wave and the terminal / chart / 매물대 wave). What only the joined tree can show:

- 홈's 목표 진척도 line (install side, /api/v4/goal) names the verdict in the verdict-day clock's words (fix-verdict
  change 13: one D-day wording on every screen; fix 1: a passed checkpoint stays named until its verdict is stored),
  never goalline's own 'D-29' next to the head card's '판정까지 29일';
- the registries both sides grew keep every entry (more.MODULES, the routes, 홈's order);
- the install side's new screens load data the reliability way (a failed read never reads as 수집 전 / 없음; a failed
  look over shown data keeps it, dimmed, with '불러오지 못함 · n분 전 자료').
"""
import os
import re
import sqlite3

from paperbot.checkpoint import NO_VERDICT_DAYS, PERIOD_DAYS, checkpoint_ts, day_str
from paperbot.dash.more import nextver as NV
from paperbot.dash.more import story as ST
from paperbot.dash.more import verdictday as V

DAY, H = 86_400_000, 3_600_000
START = 1_791_212_400_000                 # 2026-10-05 15:00 UTC (00:00 KST 10/06), as tests/test_dash_verdictday.py
CP1 = checkpoint_ts(START, 1)             # 2026-11-04 09:00 KST
CP2 = checkpoint_ts(START, 2)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _ledger(path, ks):
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE verdicts (date TEXT PRIMARY KEY, ts INTEGER, data TEXT)")
    for k in ks:
        cp = checkpoint_ts(START, k)
        c.execute("INSERT INTO verdicts VALUES (?, ?, ?)", (day_str(cp), cp + 2 * H, "{}"))
    c.commit()
    c.close()
    return str(path)


def _goal(now, p3="첫 판정 D-29(11/04)"):
    """goalline's answer shape (agents/goalline.goal) with its own verdict words in parts[2]."""
    return {"now": now, "parts": ["오늘 5년 시험 0개(통과 0)", "동전보다 나은 새 매매법 후보 0개(아직 새 매매법 시험 없음)", p3],
            "text_ko": "", "verdict": {}}


def test_the_goal_line_names_the_verdict_in_the_clock_words(tmp_path, monkeypatch):
    monkeypatch.setattr(ST, "run_start", lambda _c: START)
    paper = object()                       # read only through run_start (patched): the run started 10/06 00:00 KST
    none = _ledger(tmp_path / "none.db", [])
    # 23 days before the first verdict: the head card's sentence ends with the goal line's part
    now = CP1 - 23 * DAY
    g = NV.clock_words(_goal(now), paper, None, none)
    c = V.clock(START, now, V.read_ledger(none))
    assert g["parts"][2] == c["rest_ko"] == "판정까지 23일 (11/04 09:00)" and c["line_ko"].endswith(g["parts"][2])
    assert "D-" not in g["text_ko"] and g["text_ko"].count(" · ") == 2 and g["verdict_clock"]["due"] is False
    # the verdict morning, nothing stored yet: that verdict stays named (fix 1), never the next one
    g = NV.clock_words(_goal(CP1 + H, "첫 판정일 지남 · 판정 기록 기다림"), paper, None, none)
    assert g["parts"][2].startswith("30일 판정 날 · ") and g["verdict_clock"]["k"] == 1
    # the first verdict stored: the second one, counted the same way as the top chip
    first = _ledger(tmp_path / "first.db", [1])
    g = NV.clock_words(_goal(CP1 + 5 * H), paper, None, first)
    assert g["parts"][2] == "2번째 판정까지 30일 (12/04 09:00)"
    # the second verdict day passed, its result not stored: goalline alone would say '다음 판정 D-29' here
    g = NV.clock_words(_goal(CP2 + H, "다음 판정 D-29(01/03)"), paper, None, first)
    assert g["parts"][2].startswith("60일 판정 날 · ") and "D-" not in g["parts"][2]
    # every verdict stored and day 180 behind: no D-day is invented
    every = _ledger(tmp_path / "every.db", range(1, NO_VERDICT_DAYS // PERIOD_DAYS + 1))
    g = NV.clock_words(_goal(START + 185 * DAY), paper, None, every)
    assert g["parts"][2] == "판정 끝 (180일)"


def test_the_goal_line_keeps_goallines_words_when_the_start_is_not_known(monkeypatch):
    """paper3.db unreadable or no account yet: goalline's own honest words stay (never a made-up D-day)."""
    bad = _goal(CP1 - DAY, "판정 날짜는 계좌 기록을 읽지 못해 모름")
    bad["verdict"] = {"error": "OperationalError"}
    assert NV.clock_words(bad, object(), None, None) is bad
    assert NV.clock_words(_goal(CP1 - DAY), None, None, None)["parts"][2] == "첫 판정 D-29(11/04)"
    monkeypatch.setattr(ST, "run_start", lambda _c: None)
    g = _goal(CP1 - DAY, "판정 날짜는 봇이 첫 계좌를 만들면 정해짐")
    assert NV.clock_words(g, object(), None, None) is g


def test_both_sides_registries_and_homes_order():
    from paperbot.dash import more
    for m in ("nextver", "verdictday", "copycmp", "losslinks", "approvals"):
        assert m in more.MODULES, m
    routes = _read("core", "routes.js")
    assert 'nextver: {ko: "다음 버전", group: "strat", title: "다음 버전 후보", hidden: true},' in routes
    assert 'inbox: {ko: "결재함", group: "agents", title: "결재함", hidden: true},' in routes
    home = _read("screens", "home.js")
    # head, the 결재함 guide card, the goal line, the favourites, then the rest
    assert 'el.append(ui.screenHead("요약", "30일 모의 실험을 한눈에"), inboxGuide(ctx), goal, favs, h("div", {class: "home-band"}' in home
    chat = _read("screens", "rooms-chat.js")
    for imp in ('import {labRequestForm} from "./labreq-kit.js";', 'from "./rooms-evidence.js";', 'from "./meet-links.js";'):
        assert imp in chat, imp
    an = _read("screens", "analysis.js")
    assert '{id: "vp", label: "매물대", path: "/api/analysis/vp"' in an and "motion.shimmer(5, true));" in an


def test_the_install_sides_screens_load_the_reliability_way():
    gk = _read("screens", "goal-kit.js")
    # a failed read: the box that tries again by itself (load rejects), or the shown line dimmed; never 수집 전
    fail = gk[gk.index("catch (e) {"):gk.index("throw e;")]
    assert "ui.errorBox(e, load)" in fail and "ui.dim(parts, true)" in fail and "수집 전" not in fail
    assert "ui.dim(parts, false);" in gk and "load();\n" not in gk          # one first request (ctx.every runs it at once)
    nv = _read("screens", "nextver.js")
    assert "if (st.d) { put(staleSlot, ui.staleNote(e, st.at, () => load())); ui.dim(body, true); } else put(body, ui.errorBox(e, load));" in nv
    db = _read("screens", "debate.js")
    assert 'ui.errorBox(err, () => store.refresh("debate"), {key: "debate"})' in db
    assert "if (d) { render(d); stale(err); }" in db
    assert "for (const x of [live, deep.el, factory.el, histCard, ideaCard, side.el]) ui.dim(x, old);" in db
    for css, sel in (("debate.css", ".db-stale:empty"), ("nextver.css", ".nv-stale:empty"), ("goal-kit.css", ".gl .errbox")):
        assert sel in _read("screens", css), css


def test_every_new_install_side_module_loads_inside_the_versioned_folder(tmp_path):
    """The install side's own files (nextver, goal-kit, analysis-vp, the debate factory, disputes / lab request kits)
    load relative to their module, so under /static/v-<ver>/ (dash/assets.py); the boot preloads are generated."""
    for rel in ("screens/nextver.js", "screens/goal-kit.js", "screens/analysis-vp.js", "screens/debate-factory.js",
                "screens/debate-idea.js", "screens/disputes-kit.js", "screens/labreq-kit.js"):
        src = _read(*rel.split("/"))
        assert "/static/" not in re.sub(r"//[^\n]*", "", src), rel
        for spec in re.findall(r"""from\s+["'](\.[^"']+)["']""", src):
            assert os.path.exists(os.path.normpath(os.path.join(V4, os.path.dirname(rel), spec))), (rel, spec)
    from paperbot.dash.assets import Assets
    a = Assets(os.path.join(ROOT, "paperbot", "dash", "static"))
    html = a.index_html()
    assert '"/static/v4/' not in html and f'<meta name="pb-ver" content="{a.ver()}">' in html
    assert html.count('rel="modulepreload"') == len(a.boot_modules()) > 10
