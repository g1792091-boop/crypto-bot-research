"""Owners 2026-10-31 ("투비트봇이랑 딥코인봇은 이제 안돌릴꺼니까 대시보드화면에서 지우자"): the 딥코인 and 투비트 executors
leave the dashboard for good (dash/more/livebots.py RETIRED_SLOTS), whatever their files and units:

- the summary and every answer built on livebots.installed: no 딥코인, no 투비트, even with their config, their database
  and a running unit (a world where 딥코인 follows the VWAP 개선판, tests/vwap_site_world.py);
- 한눈에 has no 딥코인 설치 전 card, the 봇별 menu no V3.9 투비트, the VWAP 개선판 screen says no live account follows it.

The slot machinery they share with WOO X Pro 2 stays checked in tests/test_deepcoin_slot.py and tests/test_toobit_slot.py
(their slots kept there)."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot import livecheck as LC  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livepos as LPOS  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

NOW = FW.NOW
V4 = Path(FW.SCREENS).parent


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    L._off_cache.clear()
    yield
    L._cache.clear()
    L._off_cache.clear()


def test_the_two_slots_never_show(tmp_path, monkeypatch):
    assert L.RETIRED_SLOTS == ("deepcoin", "toobit")
    p = {k: str(tmp_path / f"{k}.json") for k in ("deepcoin_config", "toobit_config", "wooxpro2_config")}
    for v in p.values():
        Path(v).write_text("{}", encoding="utf-8")
    base = {"bybit_config": str(tmp_path / "no-b.json"), "mexc_config": str(tmp_path / "no-m.json"), **p}
    monkeypatch.setattr(LC, "unit_state", lambda u: ("active", "enabled"))       # even running
    ids = [s[0] for s in L.installed(base)]
    assert "deepcoin" not in ids and "toobit" not in ids and "wooxpro2" in ids
    shown = L.shown_paths({**base, "deepcoin_db": str(tmp_path / "d.db"), "toobit_db": str(tmp_path / "t.db")})
    assert not {"deepcoin_config", "deepcoin_db", "toobit_config", "toobit_db"} & set(shown)


def test_a_world_where_deepcoin_follows_the_vwap_bot_shows_none_of_it(tmp_path):
    folder = str(tmp_path / "w")
    w = V.build(folder, switch=False)
    p = {**w["p"], "deepcoin_db": os.path.join(folder, "executor-deepcoin-live.db"),
         "deepcoin_config": os.path.join(folder, "executor-deepcoin.json")}
    vwap = p["paper2"]
    V.exec_db(p["deepcoin_db"], p["deepcoin_config"], "deepcoin", vwap, [], open_pos=V.paper_position(vwap))
    assert os.path.exists(p["deepcoin_db"]) and os.path.exists(p["deepcoin_config"])
    b = L.build(p, NOW)
    assert [x["id"] for x in b["execs"]] == ["bybit", "mexc"]
    assert not any(x["id"] in ("deepcoin", "toobit") for x in b["accts"])
    more = dict(w["more"])
    flat = json.dumps(json_finite({"b": b, "pos": LPOS.build(p, more, NOW), "trades": L.trade_rows(p, NOW, more),
                                   "costs": L.costs(p, NOW), "safety": L.safety(p, NOW, more=more)}),
                      ensure_ascii=False, default=str)
    assert "딥코인" not in flat and "투비트" not in flat and '"deepcoin"' not in flat


def test_the_screens_say_so():
    routes = (V4 / "core" / "routes.js").read_text(encoding="utf-8")
    assert '{id: "bots", ko: "봇별", screens: ["bybitbot", "rangebot", "vwapbot", "mixbot", "trendbot"]}' in routes
    assert "V3.9 투비트" not in routes.split("const LIVE_SCREENS")[1].split("};")[0]
    assert 'vwapbot: {ko: "VWAP 개선판", group: "bots", title: "VWAP 개선판 (페이퍼 · 따라가는 실거래 없음)"}' in routes
    hq = (V4 / "screens" / "livebots-hq.js").read_text(encoding="utf-8")
    assert "설치 전" not in hq and "setSoon" not in hq and "paperbot-executor-deepcoin" not in hq
    lb = (V4 / "screens" / "livebots.js").read_text(encoding="utf-8")
    assert "livebots-v39" not in lb and "VWAP 개선판을 따라가는 실거래가 없어요 (페이퍼만)" in lb
    search = (V4 / "core" / "search.js").read_text(encoding="utf-8")
    assert "v39:" not in search and "딥코인" not in search and "투비트" not in search
