"""The VWAP 개선판's shadow (owners 10-26 "둘 다 해줘", research/opentime REPORT_KO.md: the 4-hour close helped only
through the executor's signal light): deploy/combo.shadow-vwap-4h.json run by the REAL bot code on the VWAP world's
market (tests/vwap_site_world.py), the 그림자 tab's ``vwap`` part (dash/more/liveshadow.vwap_shadows) next to the VWAP
paper from the shadow's own start, every paper trade and apart the trades the executor's light would have followed, the
one difference checked from its start record, 아직 안 켬 with its command, the unit's start guard, and the view in node."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vwap_site_world as VW  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import liveshadow as LS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHADOW = REPO / "deploy" / "combo.shadow-vwap-4h.json"
UNIT = REPO / "deploy" / "paperbot-combo-shadow@.service"
SCREENS = REPO / "paperbot" / "dash" / "static" / "v4" / "screens"
DOM = REPO / "tests" / "anasyn_dom.mjs"
MIN = 60_000
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("vsh")
    w = VW.build(str(root / "w"))
    sh = root / "sh"
    sh.mkdir()
    raw = json.loads(SHADOW.read_text(encoding="utf-8"))
    s = VW.vwap_db(str(sh), name="shadow-vwap-4h.db", picture=False,
                   extra={"unlocked_close_min": raw["unlocked_close_min"], "name": raw["name"]})
    return {**w, "sh": sh, "shadow": s["path"]}


def _units(states: dict):
    return lambda unit: (states.get(unit, ""), "")


def _ans(world, monkeypatch, states=None, shadow_dir=None):
    monkeypatch.setenv("PAPERBOT_LIVE_SHADOW_DIR", str(shadow_dir or world["sh"]))
    return L.shadows(world["p"], VW.NOW, units=_units(states or {}))


def test_the_real_bot_closes_the_unlocked_position_at_4_hours(world):
    main = {(t["symbol"], t["entry_time"]): t for t in VW.paper_trades(world["p"]["paper2"])}
    sh = {(t["symbol"], t["entry_time"]): t for t in VW.paper_trades(world["shadow"])}
    e3 = world["vt"]["E3"]                                    # LTC long: +0.3 % in 48 h, the VWAP paper's hold limit
    k = (e3["symbol"], e3["entry_time"])
    assert main[k]["exit_reason"] == "TIME" and sh[k]["exit_reason"] == "STALE"
    assert sh[k]["exit_time"] == e3["entry_time"] + 240 * MIN and sh[k]["context"]["exit_why"] == "4시간 안에 첫 잠금에 못 닿음"
    # the trades that locked or stopped within 4 hours are the same trades
    for name in ("E1", "E2", "E4", "E5", "E6", "E7"):
        t = world["vt"][name]
        a, b = main[(t["symbol"], t["entry_time"])], sh[(t["symbol"], t["entry_time"])]
        assert (a["exit_reason"], a["exit_time"]) == (b["exit_reason"], b["exit_time"]), name


def test_the_shadow_tab_puts_it_next_to_the_vwap_paper(world, monkeypatch):
    v = _ans(world, monkeypatch)["vwap"]
    assert v["on"] and v["small_n"] == 20 and v["start_all_ko"] is None
    assert v["light"]["n"] == 20 and "최근 20번 중 75% 넘게 이겼을 때만 따라감" in v["light"]["ko"]
    (x,) = v["shadows"]
    assert x["id"] == "vwap-4h" and x["name_ko"] == "4시간 정리" and x["state"] == "ok" and x["running"] is None
    sh, mn = x["shadow"], x["main"]
    assert sh["trades"] == mn["trades"] >= 6
    assert {e["reason"]: e["n"] for e in sh["exits"]}.get("STALE") == 1 and "TIME" not in {e["reason"] for e in sh["exits"]}
    assert {e["reason"]: e["n"] for e in mn["exits"]}.get("TIME") == 1
    assert next(e for e in sh["exits"] if e["reason"] == "STALE")["reason_ko"] == "잠금 전 시간 정리"
    # under 20 closed trades the light is still building: every trade is followed on both sides
    assert x["shadow_lit"]["trades"] == sh["trades"] and x["main_lit"]["trades"] == mn["trades"]
    assert x["small"] and x["small_ko"] == "표본 적음 · 아직 판단 못 함"
    # its one difference, from its own start record (the VWAP paper's record has no such key: None)
    assert x["cfg_ok"] is True and x["cfg_diff"] == [{"key": "unlocked_close_min", "main": None, "shadow": 240}]
    assert "4시간 안에 첫 잠금" in x["diff_ko"] and "보유 한도" in x["live_ko"]
    (x2,) = _ans(world, monkeypatch, {"paperbot-combo-shadow@vwap-4h.service": "inactive"})["vwap"]["shadows"]
    assert x2["running"] is False and x2["state_ko"].startswith("꺼져 있음")


def test_the_light_lets_through_only_what_it_would_have_followed():
    T0 = VW.NOW - 100 * 3_600_000
    trades = [{"id": i, "entry_time": T0 + i * 3_600_000, "exit_time": T0 + i * 3_600_000 + 30 * MIN,
               "pnl": (5.0 if i % 4 else -5.0), "roe": 0.1 if i % 4 else -0.1, "exit_reason": "LOCK" if i % 4 else "SL"}
              for i in range(1, 31)]
    assert LS.lit(trades, 0, None) == trades                                     # no light: every trade
    got = LS.lit(trades, 20, 0.75)
    assert got[:20] == trades[:20]                                              # building: the first 20 followed
    assert len(got) == 30                                                       # 15/20 = 75 % won: green from then on
    assert len(LS.lit(trades, 20, 0.8)) == 20                                   # 80 % never reached: red after 20


def test_not_there_yet_says_so_never_a_zero(world, monkeypatch, tmp_path):
    v = _ans(world, monkeypatch, shadow_dir=tmp_path)["vwap"]
    (x,) = v["shadows"]
    assert x["state"] == "off" and x["state_ko"] == "아직 안 켬" and "shadow" not in x and "main" not in x
    assert x["start_ko"] == v["start_all_ko"] == "sudo systemctl start paperbot-combo-shadow@vwap-4h"


def test_without_the_vwap_paper_it_is_not_compared(tmp_path, monkeypatch):
    import livebots_world as LW
    p = LW.build_world(str(tmp_path / "w"))
    monkeypatch.setenv("PAPERBOT_LIVE_SHADOW_DIR", str(tmp_path / "nowhere"))
    v = L.shadows(p, LW.NOW, units=_units({}))["vwap"]
    assert v["on"] is False and v["main_ko"] == LS.NOT_VWAP_KO and [x["state"] for x in v["shadows"]] == ["off"]


def test_the_units_start_guard_and_the_morning_check_name():
    lines = [ln.strip() for ln in UNIT.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("ExecStartPre=")]
    argv = shlex.split(lines[0].split("=", 1)[1])
    guard = [sys.executable] + argv[1:3]
    assert subprocess.run(guard + [str(SHADOW), "vwap-4h"], capture_output=True, text=True).returncode == 0
    assert subprocess.run(guard + [str(SHADOW), "trend-wait"], capture_output=True, text=True).returncode != 0
    assert subprocess.run(guard + [str(REPO / "deploy" / "combo.vwap.json"), "vwap-4h"], capture_output=True, text=True).returncode != 0
    from paperbot import livecheck as LC
    assert LC.SHADOW_NAMES["shadow-vwap-4h"] == "그림자 VWAP 4시간 정리"


def test_the_view_draws_the_vwap_shadow(world, monkeypatch, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    ans = _ans(world, monkeypatch, {"paperbot-combo-shadow@vwap-4h.service": "active"})
    f = tmp_path / "d.json"
    f.write_text(json.dumps(json_finite(ans), allow_nan=False, default=str), encoding="utf-8")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              f"const SH = await import('file://{SCREENS}/livebots-shadow.js');\n"
              f"const d = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));\n"
              "const ctx = {params: {query: {}}, alive: () => true, every() {}, api: async () => JSON.parse(JSON.stringify(d))};\n"
              "const v = SH.shadowsView(ctx); await new Promise((r) => setTimeout(r, 5)); await new Promise((r) => setTimeout(r, 5));\n"
              "console.log(JSON.stringify({t: D.walk(v.el).text.replace(/\\s+/g, ' ')}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    t = json.loads(r.stdout.strip().splitlines()[-1])["t"]
    assert not BAD.search(t), BAD.search(t)
    for w in ("VWAP 개선판 그림자 비교", "신호등을 거친 실거래 쪽에서만 좋아졌고", "VWAP 그림자 · 4시간 정리", "다른 점 하나",
              "진입 4시간 안에 첫 잠금(순ROE +10%)에 못 닿으면", "VWAP 페이퍼(실거래가 따라가는 봇)는", "모든 페이퍼 거래",
              "실행기가 따라갔을 거래", "잠금 전 시간 정리 1", "보유 한도 청산 1", "신호등: 최근 20번 중 75% 넘게",
              "표본 적음 · 아직 판단 못 함", "설정 확인 ✓", "VWAP 봇과 다른 곳은 unlocked_close_min 하나", "추세판단 봇 그림자 비교"):
        assert w in t, w
    assert t.index("VWAP 개선판 그림자 비교") < t.index("추세판단 봇 그림자 비교")
