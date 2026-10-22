"""⏳ for the 추세판단 봇 (paperbot/trendbot.py, owners 10/21): its signals wait for a PULLBACK (long: the price back DOWN
to the bot's level), not for a break. The watcher's wait list (paperbot/livecheck.py pending_entries), the quiet ⏳
message (wait_text) and its result line (wait_result) say so: "되돌림 대기 · … 아래로 내려오면 진입", "되돌림 안 옴",
"되돌림! … 진입" — never "돌파" (a wrong direction to real-money owners). On the trend bot's own records (the worlds of
tests/test_trendbot.py and tests/test_livetrend.py: TrendRunner and a fake judge)."""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_livetrend as TL  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402

MIN, HOUR = T.MIN, T.HOUR


def _rule(tmp_path):
    return sqlite3.connect(str(tmp_path / "paper3.db"))


def test_a_pullback_wait_says_where_and_which_way(tmp_path):
    w = TL._world(tmp_path)                                  # ETH F3_BOS long waits for 2496.25 from 10/05 10:00 KST
    now = T.T0 + HOUR + 2 * MIN
    pc, rc = sqlite3.connect(w.cfg.db), _rule(tmp_path)
    (x,) = LC.pending_entries(pc, rc, now)
    assert x["touched"] is None                             # no minute after the signal's in the file yet: unknown
    w.add_minutes(T.T0 + HOUR + MIN, 1)                       # the rule bot writes the next minute (flat)
    (x,) = LC.pending_entries(pc, rc, now)
    assert (x["kind"], x["symbol"], x["side"], x["strategy"], x["tf"]) == ("pullback", "ETHUSDT", 1, "F3_BOS", "30m")
    assert x["level"] == 2496.25 and x["until"] == T.T0 + HOUR + 29 * MIN      # the entry bar's last looked-at minute
    assert x["last"] == 2500.0 and abs(x["to_go"] - 3.75 / 2500) < 1e-12 and x["touched"] is False
    text = LC.wait_text(x, now)
    assert text.startswith("⏳ 되돌림 대기 · ETH 롱 · F3_BOS 30분\n2,496.25까지 아래로 내려오면 진입 (지금 2,500 · 0.15% 남음)")
    assert f"{LC.kst(T.T0 + HOUR + 29 * MIN)}까지 안 오면 진입 없음 · 27분 남음" in text and "돌파" not in text
    # the break kind keeps its own words (규칙봇 15's break settings)
    assert "위로 올라가면 진입" in LC.wait_text({**x, "kind": "break", "level": 2501.0, "to_go": 0.0004}, now)


def test_the_signals_own_minute_is_no_pullback_and_a_touch_after_it_is(tmp_path):
    w = TL._world(tmp_path)
    now = T.T0 + HOUR + 2 * MIN
    w.add_minutes(T.T0 + HOUR + MIN, 1)
    rc = _rule(tmp_path)
    t0 = T.T0 + HOUR
    rc.execute("UPDATE live_bars SET low = 2490.0 WHERE symbol = 'ETHUSDT' AND ts = ?", (t0,))   # minute t0 itself
    rc.commit()
    (x,) = LC.pending_entries(sqlite3.connect(w.cfg.db), rc, now)
    assert x["touched"] is False
    rc.execute("UPDATE live_bars SET low = 2496.0 WHERE symbol = 'ETHUSDT' AND ts = ?", (t0 + MIN,))
    rc.commit()
    (x,) = LC.pending_entries(sqlite3.connect(w.cfg.db), rc, now)
    assert x["touched"] is True                             # wait_pass sends nothing then: the entry message comes


def test_the_result_lines(tmp_path):
    w = TL._world(tmp_path)
    pc = sqlite3.connect(w.cfg.db)
    B = T.T0 + 30 * MIN                                       # BTC N08 long: touched at B + 1 min, entered at B + 2 min
    assert LC.wait_result(pc, f"N08_ICHI_WR@30m|BTCUSDT|{B}") == f"→ ✅ 되돌림! {LC.kst(B + 2 * MIN)}에 진입했어요 (🟢 진입 알림 참고)"
    assert LC.wait_result(pc, f"F3_BOS@30m|ETHUSDT|{T.T0 + HOUR}") is None          # still waiting
    # the ETH wait runs out: no touch until the entry bar's last minute but one
    T._to(w, T.T0 + HOUR + MIN, T.T0 + HOUR + 30 * MIN)
    w.store.commit()
    pc = sqlite3.connect(w.cfg.db)
    assert LC.wait_result(pc, f"F3_BOS@30m|ETHUSDT|{T.T0 + HOUR}") == LC.PULL_LAPSED == "→ ⌛ 되돌림 안 옴 · 진입 없음"
    assert LC.pending_entries(pc, _rule(tmp_path), T.T0 + HOUR + 30 * MIN) == []


def test_the_screens_word_a_pullback_wait(tmp_path):
    """신호 tab (livebots-signals.js) and 한눈에 (livebots-hq.js): a pullback says where it waits and which way."""
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("needs node")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scr = os.path.join(root, "paperbot", "dash", "static", "v4", "screens")
    dom = "file://" + os.path.join(root, "tests", "anasyn_dom.mjs")
    w = {"kind": "pullback", "side": 1, "symbol": "ETHUSDT", "strategy": "F3_BOS", "tf": "30m", "level": 2496.25,
         "last": 2500.0, "to_go": 0.0015, "touched": False}
    script = (f"await import('{dom}');\nconst S = await import('file://{scr}/livebots-signals.js');\n"
              f"const Q = await import('file://{scr}/livebots-hq.js');\nconst w = {json.dumps(w)};\n"
              "console.log(JSON.stringify({s: S.waitWords(w, 'x'), q: Q.waitWords(w), st: S.waitWords({...w, side: -1, touched: true}, 'x'),"
              " br: Q.waitWords({...w, kind: 'break', level: 2501}), c1: S.closeWords({tf: '30m', next_ms: 0, pull: 7}),"
              " c2: Q.closeWords({tf: '1h', next_ms: 0, pull: 3, now: 0, break: 0})}));")
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["s"]["line"] == "2,496.3까지 내려오면 진입 (되돌림)" and out["s"]["left"] == "0.15% 남음"
    assert out["q"]["move"] == "2,496.3까지 내려오면 진입 (되돌림)" and out["q"]["touch"] == "되돌림 닿음 · 진입 확인 중"
    assert out["st"]["line"] == "2,496.3까지 올라오면 진입 (되돌림)" and out["st"]["left"] == "한 번 닿았어요"
    assert out["br"]["move"] == "2,501.0 위로 올라가면 진입" and out["br"]["touch"] == "돌파함 · 진입 확인 중"
    assert "되돌림 진입 7개 설정" in out["c1"] and "돌파" not in out["c1"] and "되돌림 진입 3개" in out["c2"]


def test_a_config_that_enters_at_once_leaves_no_wait(tmp_path):
    """The owners' 10/22 design (trend.pullback_wait false: 바로 진입; the pullback wait is the shadow trend-wait's, which
    sends no Telegram): its signal that passed is a SUBMITTED row "추세 판단 통과: 바로 진입 …", never a WAITING one, so
    the watcher has no ⏳ to send and the site no wait to show. A 4h member's daily judgment has a Korean name."""
    import test_dash_livebots_trend1022 as N
    w, B = N._world_new(tmp_path)
    pc, rc = sqlite3.connect(w.cfg.db), _rule(tmp_path)
    assert LC.pending_entries(pc, rc, B + 2 * MIN) == []
    (status,) = {r[0] for r in pc.execute("SELECT status FROM signal_log")}
    assert status == "SUBMITTED"
    assert LC.KO_TF["1d"] == "일봉" and LC.KO_TF["4h"] == "4시간"
