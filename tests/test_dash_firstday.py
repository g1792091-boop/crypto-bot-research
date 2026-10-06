"""첫날 다듬기 (dashboard only, 10/06): what the owners see on the first morning after the v4 reset.

1. the start-day nightly report (report['start_day']) is normal: no health warning, a neutral 서버 tile and 알림 line;
2. DeepSeek money only on the DeepSeek group screen (owners' D11): 홈 LED / 오늘 / headline total, the profile card and
   a DeepSeek strategy page show counts only;
3. day-0 ranks: accounts with no closed trade and no open position are unranked (no alphabetical tie lists);
4. the highlight rings count Korea-time days (1 = the start day, same as 흐름), so 오늘 and 어제 differ;
5. 상황 태그: the 36 + the reel only, with the window the 2,000-trade cap really covers;
6. 조합 시너지: no ranked list before trades exist;
7. 알림 기록 footer in plain Korean;
8. 🔊 화면 켜두기 (Screen Wake Lock, off by default) and the FAQ line on adding the page to the phone home screen.
"""
import json
import os
import re
import sqlite3
import sys
import time

import pytest

pytest.importorskip("fastapi")

from paperbot.dash import analysis as AN  # noqa: E402
from paperbot.dash.app import Data  # noqa: E402
from paperbot.dash.more import story as S  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash_gaps_b import _node  # noqa: E402
from test_dash_v4groups import NOW, _world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
CORE = "file://" + os.path.join(V4, "core")
SCR = "file://" + os.path.join(V4, "screens")
DOC = "globalThis.document = {visibilityState: 'hidden', hidden: true, addEventListener() {}, removeEventListener() {}};\n"


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src: str) -> str:
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _fn(src: str, start: str) -> str:
    i = src.index(start)
    return src[i:src.index("\n}\n", i)]


# ---------------------------------------------------------------------------------------------- 1. start day
def _daily(path, rep):
    d = sqlite3.connect(path)
    d.executescript("CREATE TABLE reports (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);"
                    "CREATE TABLE mismatches (day TEXT NOT NULL, account_id TEXT NOT NULL, data TEXT NOT NULL);")
    d.execute("INSERT INTO reports VALUES (?, ?, ?)", ("2026-10-06", int(time.time() * 1000), json.dumps(rep)))
    d.commit()
    d.close()


def _health(tmp_path, rep):
    db = str(tmp_path / "paper3.db")
    _world(db, trades=False).close()
    _daily(str(tmp_path / "daily3.db"), rep)
    return AN.health(type("D", (), {"db": db, "summary": lambda self, now=None: {}})(),
                     type("R", (), {"agents_db": None})(), str(tmp_path / "daily3.db"), None, None,
                     failalert_dir=str(tmp_path / "none"))


def test_the_start_day_report_is_normal_not_a_warning(tmp_path):
    out = _health(tmp_path, {"day": "2026-10-06", "parity": "start day: no 00:00 snapshot",
                             "start_day": {"run_start": 1, "before_run": False}})
    assert out["nightly"]["start_day"] is True
    assert not any("재계산" in w for w in out["warnings"]) and not any("재계산" in p for p in out["problems"])
    a = AN.alert_history(type("D", (), {"db": str(tmp_path / "paper3.db")})(), type("R", (), {"agents_db": None})(),
                         str(tmp_path / "daily3.db"), None)
    assert a["nightly"][0]["start_day"] is True


def test_a_real_failed_recompute_still_warns(tmp_path):
    out = _health(tmp_path, {"day": "2026-10-07", "parity": "could not read the snapshot"})
    assert "start_day" not in out["nightly"]
    assert any("재계산을 하지 못했습니다" in w for w in out["warnings"])


def test_the_server_tile_and_alert_line_say_start_day_plainly():
    sh = _read("screens", "server-health.js")
    assert "n.start_day" in sh and '"재계산 없음 (정상, 첫 재계산 내일 09:20)"' in sh and 'v: "시작한 날"' in sh
    tile = sh[sh.index("n.start_day"):sh.index("} else if (n.ready)")]
    assert 'st: "none"' in tile and '"warn"' not in tile
    al = _read("screens", "alerts.js")
    assert "n.start_day ? " in al and "시작한 날 · 재계산 없음 (정상, 첫 재계산 내일 09:20)" in al


# ---------------------------------------------------------------------------------------------- 2. DeepSeek money
MONEY = re.compile(r"fmt\.(money|usdt|pct)\(|\.pnl\b|\bw0\b|liveNum")
CASH = re.compile(r"fmt\.(money|usdt)\(|\.pnl\b|\bw0\b|liveNum|\.ret\b")      # a win-rate % is a count, not money


def test_home_led_and_today_show_deepseek_counts_only():
    home = _code(_read("screens", "home.js"))
    led = _fn(home, "  function renderLed()")
    assert 'g === "ds"' in led and "손익은 딥시크 화면에서" in led and "딥시크 제외" in led
    assert "gs.total.wallet - (dsG ? dsG.sumWallet : 0)" in led and "합계에 딥시크는 빠짐" in led
    ds_cell = led[led.index('g === "ds"'):led.index(": {k: groupKo(g), v: gs.groups[g].pnl}")]
    assert not MONEY.search(ds_cell)
    trow = _fn(home, "  function tRow(id)")
    assert 'id === "ds" ? ' in trow and "손익은 딥시크 화면에서" in trow
    ui = _read("core", "ui.js")
    assert "if (r.text != null) { cell.v.className = \"led-txt\"; cell.v.textContent = r.text; continue; }" in ui


def test_today_total_pnl_leaves_deepseek_out():
    summary = {"today": {"since": NOW - 3_600_000, "by_group": {
        "core": {"trades": 2, "wins": 1, "pnl": 10.0, "liquidations": 0},
        "ds200": {"trades": 40, "wins": 10, "pnl": -500.0, "liquidations": 3}}}}
    out = _node(DOC + f"const k = await import('{SCR}/home-today.js');\n"
                f"const t = k.todayStats({json.dumps(summary)}, {{accounts: []}});\n"
                "process.stdout.write(JSON.stringify(t) + '\\n', () => process.exit(0));", store={})
    assert out["total"]["pnl"] == 10.0                       # DeepSeek's −500 is not in the headline number
    assert out["total"]["trades"] == 42 and out["total"]["liq"] == 3     # but it is counted
    assert out["groups"]["ds"]["trades"] == 40


def test_the_led_curve_total_leaves_deepseek_out(tmp_path):
    db = str(tmp_path / "p.db")
    store = _world(db, trades=False)
    for aid, v in (("A@15m", 5100.0), ("F9_FVG@15m", 9999.0)):
        store.equity(aid, NOW - 60_000, v, 0.0)
    store.commit()
    store.close()
    v = Data(db).curves(3_600_000, now_ms=NOW)
    assert v["total"] and v["total"][-1] == 5100.0


def test_profile_card_and_strategy_page_are_counts_only_for_deepseek():
    gk = _code(_read("screens", "grid-kit.js"))
    assert 'd.group === "ds200" ? dsCounts(ctx, d)' in gk
    body = _fn(gk, "export function dsCounts(ctx, d)")
    assert not MONEY.search(body) and "ret" not in re.sub(r"return \[", "", body)
    for w in ("거래 수", "이긴 거래", "파산", "딥시크 화면"):
        assert w in body
    sd = _code(_read("screens", "strategies-detail.js"))
    acc = _fn(sd, "  function renderAccounts()")
    assert 'const dsK = kind === "ds200";' in acc
    assert 'dsK ? h("b", {class: "num"}, `거래 ${fmt.int(a.trades || 0)}`) : h("b", {class: ["num", fmt.tone(w - init)]}, fmt.money(w))' in acc
    ds_stats = acc[acc.index("const stats = dsK ?"):acc.index(": h(\"div\", {class: \"strat-stats\"},")]
    assert not CASH.search(ds_stats)
    assert 'kind === "ds200" ? null : h("b", {class: ["num", fmt.tone(c.pnl)]}' in sd


# ---------------------------------------------------------------------------------------------- 3. day-0 ranks
def _zero_board():
    def a(aid, strat, tf, kind, **kw):
        return {"account_id": aid, "strategy": strat, "timeframe": tf, "kind": kind, "group": {"strategy": "core"}.get(kind, kind),
                "trades": 0, "wins": 0, "losses": 0, "bust": False, "position": None, "wallet": 5000.0, **kw}
    rows = [a(f"{c}_X@15m", f"{c}_X", "15m", "strategy") for c in "ABCDEFGHIJKL"]
    return {"initial": 5000, "accounts": rows}


def test_day0_accounts_without_trades_are_unranked():
    b = _zero_board()
    b2 = json.loads(json.dumps(b))
    b2["accounts"][5].update(trades=1, wins=1, wallet=5010.0)                 # one traded
    b2["accounts"][7]["position"] = {"symbol": "BTCUSDT", "side": 1}          # one holds a position (ranked, 0.0%)
    out = _node(DOC + f"const d = await import('{CORE}/derive.js');\n"
                f"const z = d.rankedOnly({json.dumps(b)}, 'core');\n"
                f"const one = d.rankedOnly({json.dumps(b2)}, 'core');\n"
                f"const all = d.ranked({json.dumps(b2)}, 'core').map((a) => a.account_id);\n"
                "process.stdout.write(JSON.stringify({z: {n: z.rows.length, w: z.waiting}, one: {ids: one.rows.map((a) => a.account_id), w: one.waiting},"
                " all, line: d.waitingKo(z.waiting), none: d.waitingKo(0)}) + '\\n', () => process.exit(0));", store={})
    assert out["z"] == {"n": 0, "w": 12}
    assert out["one"]["ids"] == ["F_X@15m", "H_X@15m"] and out["one"]["w"] == 10
    assert out["all"][:2] == ["F_X@15m", "H_X@15m"]                         # unranked ones after the ranked ones
    assert out["line"] == "아직 거래 없는 계좌 12개 · 첫 거래 뒤부터 순위" and out["none"] == ""


def test_rank_lists_best_account_flow_and_memo_skip_unranked():
    hs = _read("screens", "home-shared.js")
    tb = hs[hs.index("export function topBottom"):hs.index("// ---------------------------------------------------------------- the ranked list")]
    assert "derive.rankedOnly(board, group)" in tb and "derive.waitingKo(waiting)" in tb
    assert "a._rk = derive.unranked(a) || derive.countOnlyIn(a, st.group) ? null : ++rk;" in hs   # (+ 전체: DeepSeek/coin unranked) '—' (fmt.int(null)) instead of a rank
    assert "rows.filter((a) => !derive.unranked(a)).reduce(" in _read("screens", "board.js")
    # 순위표 전체 table: the DeepSeek row names no account with money (D11)
    assert 'r.g === "ds" ? "딥시크 화면에서" : bestCell(best(r.rows))' in _read("screens", "board.js")
    mo = _read("screens", "board-motion.js")
    assert "derive.rankedOnly(board, sel).rows" in mo and "!derive.unranked(st.byId.get(id))" in mo
    assert "memo.save(st.curRet);" not in mo
    fc = _read("screens", "flow-cal.js")
    assert "best && best.chg > 0" in fc and "worst && worst.chg < 0" in fc and "첫 거래 뒤부터 순위" in fc
    out = _node(DOC + f"const f = await import('{CORE}/fmt.js');\n"
                "process.stdout.write(JSON.stringify(f.int(null)) + '\\n', () => process.exit(0));", store={})
    assert out == "—"


# ---------------------------------------------------------------------------------------------- 4. day numbers
START = 1_791_223_200_000          # 2026-10-06 03:00 KST (10/05 18:00 UTC)


def test_rings_count_korea_days_so_today_and_yesterday_differ():
    now = START + 26 * 3_600_000    # 10/07 05:00 KST: before 09:00, the D+ clock has not moved yet
    out = _node(DOC + f"const k = await import('{SCR}/story-kit.js');\n"
                f"process.stdout.write(JSON.stringify(k.runDays({START}, {now})) + '\\n', () => process.exit(0));", store={})
    assert [d["day"] for d in out] == ["2026-10-07", "2026-10-06"]
    assert [d["n"] for d in out] == [2, 1]                                  # 오늘 2일째, 어제 1일째: never the same
    assert out[0]["dn"] == out[1]["dn"] == 1                                # the old D+ label would have shown 1 twice
    assert out == list(reversed(S.run_days(START, now)))                    # the page and the server count the same
    kit = _read("screens", "story-kit.js")
    assert 'h("small", null, "일째")' in kit and 'h("small", null, "D+")' not in kit
    assert 'h("small", null, "일째")' in _read("screens", "story.js")
    assert "`${fmt.int(d.i + 1)}일째`" in _read("screens", "flow-cal.js")     # 흐름: the same 1-based Korea-day count
    # the home card's day count ('30일 중 N일 지남', the verdict-day clock's words) moves at 09:00 KST and says so
    assert "지난 날은 매일 한국 09:00에 +1" in _read("screens", "home.js")


# ---------------------------------------------------------------------------------------------- 5. 상황 태그
def test_tag_stats_cover_the_36_and_the_reel_with_the_real_window(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    v = Data(db).card_stats(None, None, 30)
    assert v["trades"] == 2 and v["kinds"] == ["strategy", "reel"]         # A@15m + the reel; no DeepSeek, no flips
    assert v["from_ts"] == NOW - 60_000 and v["capped"] is False and v["cap"] == 2000
    one = Data(db).card_stats("F9_FVG", None, 30)                           # one strategy: its own accounts (unchanged)
    assert one["trades"] == 2 and one["kinds"] is None
    w = _read("screens", "analysis-where.js")
    assert "동전 봇 포함 모든 계좌" not in w and "기존 36 매매법 + 5분봉" in w and "d.capped && d.from_ts" in w


# ---------------------------------------------------------------------------------------------- 6. 조합 시너지
def test_synergy_has_no_ranked_list_before_trades(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    v = AN.synergy_view(db, NOW)
    assert v.get("top") == [] and v.get("waiting") is True
    assert v["note"] == f"거래가 쌓이면 (계좌당 {AN.SYNERGY_MIN_TRADES}건 이상) 보여 드립니다"
    js = _read("screens", "analysis-rules.js")
    assert "if (d.waiting) {" in js and "거래가 쌓이면 (계좌당" in js


# ---------------------------------------------------------------------------------------------- 7. footer words
def test_alert_footer_names_sources_in_korean():
    al = _code(_read("screens", "alerts.js"))
    assert "st.d.sources.map(sourceKo)" in al and 'st.d.sources.join(", ")' not in al
    for k in ("봇 경고", "밤 점검 보고", "판정 작업 기록"):
        assert k in al


# ---------------------------------------------------------------------------------------------- 8. phone
def test_wake_lock_is_opt_in_guarded_and_reacquired():
    src = _read("core", "sound.js")
    assert 'local.get("snd-wake", false) === true' in src                  # off by default, per device
    assert 'navigator.wakeLock.request("screen")' in src and "catch (e) { l = null; }" in src
    assert 'document.addEventListener("visibilitychange"' in src and "if (!document.hidden) wakeGet();" in src
    assert "if (!wake.on || !cfg.on" in src                                 # only while the sound is on
    assert "화면 켜두기" in src and "이 기기는 지원 안 함" in src
    out = _node(DOC + f"const s = await import('{CORE}/sound.js');\n"
                "const a = {sup: s.wakeSupported(), on: s.wakeOn()};\n"
                "s.setWake(true);\n"
                "a.after = s.wakeOn(); a.stored = globalThis._ls.get('pb4-snd-wake');\n"
                "process.stdout.write(JSON.stringify(a) + '\\n', () => process.exit(0));", store={})
    assert out == {"sup": False, "on": False, "after": True, "stored": "true"}   # no API here: no error, no lock


def test_faq_says_how_to_add_the_page_to_the_home_screen():
    faq = _read("screens", "faq-items.js")
    assert "홈 화면에 추가" in faq and "화면 켜두기" in faq


def test_wake_lock_one_request_at_a_time_and_released_when_turned_off():
    # a fake Screen Wake Lock: the tick and the page coming back ask together, then the owner turns it off (also
    # before the browser answered): at most one lock, and none left once it is off
    fake = ("const _vis = [];\n"
            "globalThis.document = {visibilityState: 'visible', hidden: false, addEventListener(t, f) { if (t === 'visibilitychange') _vis.push(f); }, removeEventListener() {}};\n"
            "let made = 0, active = 0;\n"
            "Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {wakeLock: {request: async () => {\n"
            "  await new Promise((r) => setTimeout(r, 5)); made++; active++; let rel = false; const ls = [];\n"
            "  return {addEventListener: (e, f) => ls.push(f), release: async () => { if (!rel) { rel = true; active--; ls.forEach((f) => f()); } }};\n"
            "}}}});\n")
    out = _node(fake + f"const s = await import('{CORE}/sound.js');\n"
                "const wait = () => new Promise((r) => setTimeout(r, 30));\n"
                "s.cfg.on = true; const o = {};\n"
                "s.setWake(true); _vis.forEach((f) => f()); await wait(); o.on = {made, active};\n"
                "s.setWake(false); await wait(); o.off = {made, active};\n"
                "s.setWake(true); s.setWake(false); await wait(); o.quick = {made, active};\n"
                "process.stdout.write(JSON.stringify(o) + '\\n', () => process.exit(0));", store={})
    assert out == {"on": {"made": 1, "active": 1}, "off": {"made": 1, "active": 0}, "quick": {"made": 2, "active": 0}}
