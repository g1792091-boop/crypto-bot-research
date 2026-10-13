"""candleague dashboard: the leverage ladder in words follows the league (owners 2026-10-13: CANDLEAGUE_MIN_LEV=30).

The floor league (snapshot ``min_lev`` = 30) tries 50 -> 40 -> 30 for a 좋은 자리 and 30 only for a 보통 자리, with no 20배: every text that
states the ladder (읽는 법 incl. the glossary and the 손절 거리 한도, 익절·손절·배수, the 포지션 카드's rule line, dash.py's RULE_KO) must say so, and
a signal whose stop is wider than the 30배 limit is said not to be entered. A snapshot without ``min_lev`` (the old league, the rule bot's
50/40/30/20) keeps its words exactly. The one sentence that names 20배 on purpose is the 읽는 법 note below."""

from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import dash as D  # noqa: E402
import test_candleague_lineup_words as LW  # noqa: E402  (the owner-exit league's snapshot and its rules world)
import test_candleague_owner_exits as OX  # noqa: E402
import test_candleague_rules_ui as RU  # noqa: E402

NOTE = "이 리그는 20배를 쓰지 않습니다 (규칙봇은 씀). 손절이 넓은 신호는 30배에서도 안 맞으면 진입하지 않아 거래가 줄 수 있습니다."


def _doc(min_lev):
    d = LW._owner_doc()
    d["min_lev"] = min_lev
    return d


@pytest.fixture(scope="module")
def howto(tmp_path_factory):
    out = {}
    for key, ml in (("floor", 30), ("none", None)):
        out[key] = OX._node(tmp_path_factory.mktemp("lev" + key), _doc(ml), ["howto"])["screens"]["howto"]["text"]
    return out


def test_howto_floor_league_has_no_20x_but_the_one_note(howto):
    t = howto["floor"]
    assert NOTE in t
    rest = t.replace(NOTE, "")
    assert "20배" not in rest and "30/20" not in rest and "→ 20" not in rest, re.findall(r".{20}20배.{10}", rest)
    assert "좋은 자리 50/40/30배 · 보통 30배" in t                                      # the line about the engine
    assert "50배 약 0.48%, 40배 0.82%, 30배 1.55%." in t                                # the 손절 거리 한도: no 20배 limit any more
    assert "30배 한도(진입가의 약 1.55%)보다 넓은 신호는 들어가지 않습니다" in t and "거래가 줄 수 있습니다" in t
    assert "50배부터 시도하고, 안 되면 40배 → 30배까지만" in t and "30배만 시도합니다" in t
    assert "BTC 50배 약 1.6%, 30배 약 2.9%" in t


def test_howto_without_min_lev_keeps_the_old_words(howto):
    t = howto["none"]
    assert "이 리그는 20배를 쓰지 않습니다" not in t and "30배 한도" not in t
    assert "좋은 자리 50/40배 · 보통 30/20배" in t
    assert "50배 약 0.48%, 40배 0.82%, 30배 1.55%, 20배 3.63%. 손절이 이보다 넓으면 그 배수는 건너뜁니다." in t
    assert "50배부터 시도하고, 안 되면 40배 → 30배 → 20배." in t and "30배부터 시도하고, 안 되면 20배." in t
    assert "BTC 50배 약 1.6%, 20배 약 4.6%" in t


RULES_BODY = r"""
const r = await mount("rules");
out.page = txt(r);
out.rows = [...r.querySelectorAll(".rl-row")].map((x) => txt(x));
out.card = txt(r.querySelector(".rl-pickcard"));
const L = LK.levLadder();
out.ladder = {on: L.on, best: L.best, normal: L.normal, slash: L.slash, tight: L.bestTight + " | " + L.normalTight};
const C = await import(`file://${S}/js/screens/positions-card.js`);
out.why = C.whyBox({lev: 30, why: {rule_ko: "x", sub_ko: "y"}}).textContent;
out.q = RK.levWords({best_ok: true, p_best: 0.22}).map((x) => (typeof x === "string" ? x : x.textContent)).join("") + " || "
  + RK.levWords({best_ok: false, kind: "ds"}).map((x) => (typeof x === "string" ? x : x.textContent)).join("");
out.tp = RK.tpWords({kind: "roe", val: 0.5});
"""


def _rules(tmp_path, min_lev, monkeypatch):
    if min_lev is None:
        monkeypatch.delenv("CANDLEAGUE_MIN_LEV", raising=False)
    else:
        monkeypatch.setenv("CANDLEAGUE_MIN_LEV", str(min_lev))                         # the server (rules_doc) and the snapshot agree
    d, routes = LW._rule_world()
    d["min_lev"] = min_lev
    routes["/api/league"] = d
    return RU._run(tmp_path, {"routes": routes}, RULES_BODY)


def test_rules_screen_and_card_in_the_floor_league(tmp_path, monkeypatch):
    o = _rules(tmp_path, 30, monkeypatch)
    assert o["ladder"] == {"on": True, "best": [50, 40, 30], "normal": [30], "slash": "좋은 자리 50/40/30배 · 보통 30배", "tight": "50→40→30배 | 30배"}
    for key in ("page", "card", "why", "q", "tp"):
        assert "20배" not in o[key], (key, re.findall(r".{25}20배.{10}", o[key]))
    for row in o["rows"]:
        assert "20배" not in row and "→20" not in row
    assert "좋은 자리 50→40→30배 · 보통 30배" in o["why"]                                  # the 포지션 카드's fallback rule line
    assert "50배 → 40배 → 30배, 보통 자리는 30배만 시도해" in o["page"] and "50배면 잔고의 50%, 40배 40%, 30배 30%." in o["page"]
    assert "30배보다 낮게는 내려가지 않아" in o["page"]
    assert "30배도 안 맞는 신호는 진입하지 않습니다" in o["q"] and "30배만 시도해" in o["q"] and "30배 → 20배" not in o["q"]
    assert "30배면 약" in o["tp"] and "40배면 약" in o["tp"]


def test_rules_screen_without_min_lev_keeps_the_old_words(tmp_path, monkeypatch):
    o = _rules(tmp_path, None, monkeypatch)
    assert o["ladder"]["on"] is False and o["ladder"]["best"] == [50, 40, 30, 20] and o["ladder"]["normal"] == [30, 20]
    assert o["ladder"]["slash"] == "좋은 자리 50/40배 · 보통 30/20배" and o["ladder"]["tight"] == "50→40→30→20배 | 30→20배"
    assert "좋은 자리 50→40→30→20배 · 보통 30→20배" in o["why"]
    assert "50배 → 40배 → 30배 → 20배, 보통 자리는 30배 → 20배 순서로 시도해, " in o["page"]
    assert "50배면 잔고의 50%, 40배 40%, 30배 30%, 20배 20%." in o["page"] and "낮게는 내려가지 않아" not in o["page"]
    assert "라서 30배 → 20배 순서로 시도해, 거래소 한도 안이고 두 가지 안전 검사를 모두 통과한 첫 배수로 들어갑니다." in o["q"]
    assert ": 30배 → 20배 순서로 시도해 거래소 한도 안이고" in o["q"]
    assert "20배면 약" in o["tp"] and "30배면 약" in o["tp"]
    assert any("50→40→30→20배" in r or "30→20배" in r for r in o["rows"])


def test_dash_rule_text_follows_the_process_env(monkeypatch):
    monkeypatch.delenv("CANDLEAGUE_MIN_LEV", raising=False)
    old_full, old_short = D.RULE_KO, D.RULE_SHORT_KO
    assert "20배(20%)" in old_full and "보통 자리는 30배 → 20배 순서로" in old_full
    assert old_short == "좋은 자리 50→40→30→20배 · 보통 30→20배 · 거래소 한도와 안전 검사를 통과한 첫 배수"
    monkeypatch.setenv("CANDLEAGUE_MIN_LEV", "30")                                     # read at call time, not at import
    assert "20배" not in D.RULE_KO and "50배(증거금 50%) → 40배(40%) → 30배(30%), 보통 자리는 30배만 시도해" in D.RULE_KO
    assert D.RULE_SHORT_KO == "좋은 자리 50→40→30배 · 보통 30배 · 거래소 한도와 안전 검사를 통과한 첫 배수"
    why = D.why_lev({"kind": "core", "role": "cand"}, 30, 0.3, 0.03)
    assert "20배" not in why["rule_ko"] and why["rule_short_ko"] == D.RULE_SHORT_KO
    monkeypatch.delenv("CANDLEAGUE_MIN_LEV")
    assert D.why_lev({"kind": "core", "role": "cand"}, 30, 0.3, 0.03)["rule_ko"] == old_full
