"""The third live executor slot, 딥코인 (owners 10-24, docs/deepcoin-ko.md: "그냥 다른거래소 쓸래"; it follows the 'VWAP
개선판' paper bot, vwap.db), on the live site, in the live checks and Telegram messages, and in the server's files. On 10-23
the slot was built for Flipster (its API opens only on request); nothing of it was installed, so the slot was renamed:
an executor config naming "flipster" still reads 플립스터 (EX_NAME / EX_KO), and install.sh removes the old unit file only
while that unit is inactive and not enabled.

The rule (livebots.installed, livecheck.installed_specs): the slot is on a server once its config file
(/etc/paperbot/executor-deepcoin.json, PAPERBOT_LIVE_DEEPCOIN_CONFIG) or its database
(/var/lib/paperbot/exec/executor-deepcoin-live.db, PAPERBOT_LIVE_DEEPCOIN_DB) is there. Neither there: every answer,
screen, check and message is the two executors' as before (install.sh never writes the config: the owners copy the
template when they start it).

The three-executor world: tests/vwap_site_world.py with 바이비트 and WOO X Pro on the 추세판단 봇 (live-ac.db, switch=False)
and 딥코인 on vwap.db from its first start: it follows E4, E5 and E7, misses E6 (late) and holds the open E8.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot import livecheck as LC  # noqa: E402
from paperbot import livepreview as LPV  # noqa: E402
from paperbot import liveteam as T  # noqa: E402
from paperbot import offsite as off  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import liveinsight as LI  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livepos as LPOS  # noqa: E402
from paperbot.dash.more import livevwap as VW  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

NOW, MIN, H, DAY = V.NOW, V.MIN, V.H, V.DAY
ROOT = Path(FW.ROOT)
SCREENS, DOM, BAD = FW.SCREENS, FW.DOM, FW.BAD
# 딥코인 ends in a consonant: never 딥코인가 / 딥코인는 / 딥코인를 / 딥코인와 / 딥코인로 / 딥코인예요
WRONG = re.compile(r"딥코인(가|는|를|와|로|예요)(?![가-힣])")
V4 = os.path.dirname(SCREENS)
spec = importlib.util.spec_from_file_location("vwap_switch", ROOT / "deploy" / "vwap_switch.py")
VS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VS)


@pytest.fixture(scope="module")
def w3(tmp_path_factory):
    """The three-executor world (module docstring): ``p3`` its paths, ``p2`` the same without any key of the third slot
    (the path dict as before) and ``p0`` with its keys but its files not there (a server where it is not installed)."""
    folder = str(tmp_path_factory.mktemp("third") / "w")        # (no "deepcoin" in the paths the answers carry)
    w = V.build(folder, switch=False)
    p2 = dict(w["p"])
    p3 = {**p2, "deepcoin_db": os.path.join(folder, "executor-deepcoin-live.db"),
          "deepcoin_config": os.path.join(folder, "executor-deepcoin.json")}
    vt, vwap = w["vt"], p2["paper2"]
    fl = V.exec_db(p3["deepcoin_db"], p3["deepcoin_config"], "deepcoin", vwap, [], vwap_closed=[vt["E4"], vt["E5"], vt["E7"]],
                   late=[vt["E6"]], open_pos=V.paper_position(vwap), light=(20, 0.75),
                   extra={"ladder_from": "own", "risk": {"max_loss_frac": 0.2}})
    no = os.path.join(folder, "none")
    p0 = {**p2, "deepcoin_db": no + "-deepcoin.db", "deepcoin_config": no + "-deepcoin.json"}
    return {**w, "p3": p3, "p2": p2, "p0": p0, "fl": fl, "folder": folder}


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


def _flat(x) -> str:
    return json.dumps(json_finite(x), sort_keys=True, ensure_ascii=False, default=str)


def _answers(p: dict, more: dict) -> dict:
    """The site's answers that name the executors, at the world's clock."""
    return {"build": L.build(p, NOW), "trades": L.trade_rows(p, NOW, more), "perf": L.perf(p, NOW, more),
            "safety": L.safety(p, NOW, more=more), "settings": L.settings(p, NOW), "costs": L.costs(p, NOW),
            "map": L.map_view(p, NOW), "now": L.whynow(p, NOW), "pos": LPOS.build(p, more, NOW), "risk": LI.risk(p, NOW, more),
            "health": LI.health(p, NOW, more), "goal": LI.goal(p, NOW, more), "judge": LI.judge(p, NOW, more),
            "groups": LI.groups(p, NOW, more), "vwap": VW.control(p, NOW, more), "vwperf": VW.perf(p, NOW, more)}


@pytest.fixture(scope="module")
def answers(w3):
    """{"p2", "p0", "p3"}: the answers of each path dict."""
    more = dict(w3["more"])
    out = {}
    for k in ("p2", "p0", "p3"):
        L._cache.clear()
        out[k] = _answers(w3[k], more)
    return out


# ================================================================ the site: the rule, not installed, three executors
def test_not_installed_every_answer_is_as_before(w3, answers):
    assert L.installed(w3["p0"]) == L.installed(w3["p2"]) == L.EXECS
    a2, a0 = _flat(answers["p2"]), _flat(answers["p0"])
    assert a0 == a2                                       # its keys, no files: the very same answers as without its keys
    assert "deepcoin" not in a0 and "딥코인" not in a0
    assert sorted(answers["p0"]["build"]["paths"]) == sorted(w3["p2"])    # the answer's paths too: as they were


def test_the_slot_shows_once_its_config_or_its_database_is_there(w3):
    p3, folder = w3["p3"], w3["folder"]
    assert [s[0] for s in L.installed(p3)] == ["bybit", "mexc", "deepcoin"]
    cfg_only = {**p3, "deepcoin_db": os.path.join(folder, "none-d.db")}
    db_only = {**p3, "deepcoin_config": os.path.join(folder, "none-d.json")}
    for p, rec, cfg in ((cfg_only, "missing", "ok"), (db_only, "ok", "missing")):
        assert [s[0] for s in L.installed(p)] == ["bybit", "mexc", "deepcoin"]
        _c, _f, _paper, execs = L.sources(p, NOW)
        x = execs[-1]
        assert (x["id"], x["name_ko"], x["record"]["state"], x["config"]["state"]) == ("deepcoin", "딥코인", rec, cfg)
    # where the site looks: the start guide's paths, the variables, else the database its own config names
    d = L.paths({})
    assert (d["deepcoin_db"], d["deepcoin_config"]) == ("/var/lib/paperbot/exec/executor-deepcoin-live.db",
                                                        "/etc/paperbot/executor-deepcoin.json")
    assert L.ENV["deepcoin_db"][0] == "PAPERBOT_LIVE_DEEPCOIN_DB" and L.ENV["deepcoin_config"][0] == "PAPERBOT_LIVE_DEEPCOIN_CONFIG"
    assert L.paths({"PAPERBOT_LIVE_DEEPCOIN_CONFIG": p3["deepcoin_config"]})["deepcoin_db"] == p3["deepcoin_db"]
    assert L.shown_paths(w3["p0"]) == w3["p2"] and L.shown_paths(p3) == p3
    assert L.EX_NAME["deepcoin"] == "딥코인" and [ko for _x, ko, _d, _c in L.slots()] == ["바이비트", "MEXC"]


def test_the_slot_takes_its_name_from_its_config():
    """Like the second slot (its config's "wooxpro" reads WOO X Pro): the third slot reads the exchange its config names;
    Flipster, the slot's exchange of 10-23, is still an exchange the executor runs."""
    ok = lambda ex: {"state": "ok", "exchange": ex}                       # noqa: E731
    for ex, ko in (("deepcoin", "딥코인"), ("flipster", "플립스터")):
        assert L.EX_NAME[ex] == LC.EX_KO[ex] == LPOS.EX_KO[ex] == ko
        assert L.slots({"bybit": ok("bybit"), "mexc": ok("wooxpro"), "deepcoin": ok(ex)})[-1][:2] == ("deepcoin", ko)
        assert LC.ExecInfo("deepcoin", "", "", "", 0, 0.85, exchange=ex).label == ko
    assert L.slots({"deepcoin": {"state": "missing"}})[-1][:2] == ("deepcoin", "딥코인")      # unread: the slot's own name


def test_a_name_ending_in_a_consonant_takes_its_own_particles():
    """딥코인 ends in a consonant (바이비트, 플립스터 did not): the words that follow a name take 이 / 은 after it, the others
    exactly as before."""
    from paperbot import livepapers as LP
    assert L.josa is LP.josa
    assert [LP.josa(w, "이", "가") for w in ("딥코인", "바이비트", "WOO X Pro", "바이비트·WOO X Pro", "MEXC", "")] == [
        "딥코인이", "바이비트가", "WOO X Pro가", "바이비트·WOO X Pro가", "MEXC가", ""]
    assert [LP.josa(w, "은", "는") for w in ("딥코인", "바이비트", "실행기")] == ["딥코인은", "바이비트는", "실행기는"]
    assert LP.label(None, ["딥코인"], "VWAP 개선판") == "VWAP 개선판 (딥코인이 따라감)"
    assert LP.label(None, ["바이비트", "MEXC"], "추세판단 봇") == "추세판단 봇 (바이비트·MEXC가 따라감)"


def test_the_site_with_three_executors(w3, answers):
    a = answers["p3"]
    b = a["build"]
    assert [(x["id"], x["name_ko"], x.get("follows_ko")) for x in b["execs"]] == [
        ("bybit", "바이비트", "추세판단 봇"), ("mexc", "WOO X Pro", "추세판단 봇"), ("deepcoin", "딥코인", "VWAP 개선판")]
    fl = next(x for x in b["accts"] if x["id"] == "deepcoin")
    assert fl["state"] == "ok" and fl["kind"] == "live" and fl["position"]["symbol"] == "BTCUSDT" and fl["follows_ko"] == "VWAP 개선판"
    papers = {x["id"]: x for x in b["papers"]}
    assert papers["paper"]["follower_ids"] == ["bybit", "mexc"] and papers["paper2"]["follower_ids"] == ["deepcoin"]
    assert papers["paper2"]["followers"] == ["딥코인"] and sorted(b["paths"]) == sorted(w3["p3"])
    # 거래: its own table (its three VWAP trades) and its part in the VWAP bot's rows
    t = a["trades"]["accts"]
    assert sorted(r["key"] for r in t["deepcoin"]["rows"]) == sorted(x["key"] for x in w3["fl"]["live"])
    vt = w3["vt"]
    cells = {r["entry_time"]: r["live"]["deepcoin"] for r in t["paper2"]["rows"]}
    assert all(cells[vt[n]["entry_time"]]["state"] == "matched" for n in ("E4", "E5", "E7"))
    assert cells[vt["E6"]["entry_time"]]["state"] == "missed" and cells[vt["E6"]["entry_time"]]["why_kind"] == "late"
    # 비용: its card, its 체결 비교, its rates (the API docs' fee-rate example, Lv1; the drill measures the real fee)
    c = a["costs"]
    assert c["execs"][-1] == {"id": "deepcoin", "name_ko": "딥코인"} and c["accts"]["deepcoin"]["state"] == "ok"
    assert c["accts"]["deepcoin"]["n"] == 3 and c["accts"]["deepcoin"]["gaps"]["state"] == "ok"
    assert [r["id"] for r in c["entry_judge"]["rows"]] == ["bybit", "mexc", "deepcoin"]
    fee = next(x for x in c["fees"]["execs"] if x["id"] == "deepcoin")
    assert fee["exchange"] == "deepcoin" and fee["rates"]["taker"] == 0.0005 and fee["rates"]["maker"] == 0.0002
    assert "예시(Lv1)" in fee["rates"]["src_ko"] and "드릴" in fee["rates"]["src_ko"]
    # 안전 · 설정 · 포지션 · 봇 상태 · 위험 · 성적 · VWAP 봇
    assert [x["id"] for x in a["safety"]["execs"]] == ["bybit", "mexc", "deepcoin"]
    assert [(x["id"], x.get("follows_ko")) for x in a["settings"]["execs"]][-1] == ("deepcoin", "VWAP 개선판")
    assert [x["id"] for x in a["pos"]["cards"]] == ["paper", "paper2", "bybit", "mexc", "deepcoin", "flip"]
    card = next(x for x in a["pos"]["cards"] if x["id"] == "deepcoin")
    assert card["position"] and card["follows_ko"] == "VWAP 개선판"
    assert [(i["who"], i["ko"]) for i in a["health"]["items"] if i.get("id") == "exec"][-1] == ("deepcoin", "딥코인 실행기")
    assert a["risk"]["kill"]["what_ko"].startswith("세 실행기가 모두 멈춰요")
    assert answers["p0"]["risk"]["kill"]["what_ko"].startswith("두 실행기가 모두 멈춰요")
    assert "deepcoin" in a["perf"]["accts"] and "deepcoin" in a["groups"]["accts"]
    assert [x["id"] for x in a["vwap"]["followers"]] == ["deepcoin"] and a["vwap"]["followers"][0]["name_ko"] == "딥코인"
    assert [x["id"] for x in a["vwperf"]["checklist"]] == ["deepcoin"]
    # the main bot's trades: the third followed another paper bot (never counted as a miss of the trend bot's)
    assert all(r["live"]["deepcoin"]["state"] == "other" for r in t["paper"]["rows"])
    assert all(r["live"]["deepcoin"]["why_ko"].startswith("이때 딥코인은 ") for r in t["paper"]["rows"])
    # its name takes its own particles everywhere (딥코인이 / 딥코인은, never 딥코인가 / 딥코인는)
    words = _flat(a)
    assert "딥코인" in words and not WRONG.search(words), WRONG.search(words)


# ================================================================ the screens in node
def _node(tmp_path, body: str, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              # what a browser has and the tiny DOM does not (a part added in place when the third executor comes)
              "for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),"
              " replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {"
              " const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };\n"
              f"Date.now = () => {NOW};\n"
              f"const K = await import('file://{SCREENS}/livebots-kit.js'); const P = await import('file://{SCREENS}/livebots-parts.js');\n"
              f"const HQ = await import('file://{SCREENS}/livebots-hq.js'); const TR = await import('file://{SCREENS}/livebots-trades.js');\n"
              f"const SF = await import('file://{SCREENS}/livebots-safety.js'); const CO = await import('file://{SCREENS}/livebots-cost.js');\n"
              f"const PE = await import('file://{SCREENS}/livebots-perf.js'); const MA = await import('file://{SCREENS}/livebots-map.js');\n"
              f"const {{ui}} = await import('file://{V4}/core/pb.js');\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 10));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {}, every() {},"
              " href: (n, x) => '#/' + n + (x ? '/' + x : ''), api: async (p) => JSON.parse(JSON.stringify(typeof a === 'function' ? a(p) : a))});\n"
              "const run = async (V, a, hub) => { const v = hub ? V(mkCtx(a), hub) : V(mkCtx(a)); await tick(); await tick(); return v; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


SCREENS_JS = """
const view = async (sum, tr, sf, co) => {
  K.setPapers(sum.papers); K.setExecs(sum.execs);
  const band = P.bandLine(mkCtx(null)); band.set(sum, "ok");
  const hub = {get: () => sum, state: () => "ok", at: () => sum.now_ms, retry: () => {}};
  const hq = await run(HQ.hqView, (p) => (p.endsWith('/now') ? D_now : p.endsWith('/calendar') ? {} : {}), hub);
  hq.set(sum, "ok");
  const hqw = D.walk(hq.el);
  const t = await run(TR.tradesView, tr), s = await run(SF.safetyView, sf), c = await run(CO.costView, co);
  return {real: texts(ui.note(K.realLine(sum))), band: texts(band.el), hq: hqw.text.replace(/\\s+/g, ' '),
    reactors: hqw.classes.filter((x) => x.split(' ').includes('lbh-reactor')).length, deck: hqw.classes.find((x) => x.startsWith('lbh-deck')),
    trades: texts(t.el), safety: texts(s.el), cost: texts(c.el), costCards: D.walk(c.el).classes.filter((x) => /lbk-a-deepcoin/.test(x)).length};
};
const two = await view(D_s2, D_t2, D_f2, D_c2);
const ids2 = [K.execsNow(), K.execIds(D_s2), K.execIds(null), PE.idsOf(null), MA.idsOf(null)];
const three = await view(D_s3, D_t3, D_f3, D_c3);
const ids3 = [K.execsNow(), K.execIds(D_s3), K.execIds(D_t3), K.execIds(D_c3), PE.idsOf(D_p3), MA.idsOf({accounts: {deepcoin: {}}}), K.execsKo(), K.acctsKo(5)];
// built for two (the first answer of a page), then the third executor comes: its chip, reactor, choices are added in place
K.setExecs(D_s2.execs);
const band = P.bandLine(mkCtx(null)); band.set(D_s2, "ok"); const bandBefore = texts(band.el); band.set(D_s3, "ok");
let cur = D_s2;
const hub = {get: () => cur, state: () => "ok", at: () => NOW, retry: () => {}};
const hq = await run(HQ.hqView, () => D_now, hub); hq.set(D_s2, "ok"); const hq2 = D.walk(hq.el);
cur = D_s3; K.setExecs(D_s3.execs); hq.set(D_s3, "ok");
const hqw = D.walk(hq.el);
const late = {bandBefore, band: texts(band.el), reactors0: hq2.classes.filter((x) => x.split(' ').includes('lbh-reactor')).length,
  reactors: hqw.classes.filter((x) => x.split(' ').includes('lbh-reactor')).length, deck: hqw.classes.find((x) => x.startsWith('lbh-deck'))};
const josa = [K.josa("딥코인", "이", "가"), K.josa("바이비트·WOO X Pro", "이", "가"), K.josa("딥코인", "은", "는"), K.josa("WOO X Pro", "은", "는")];
console.log(JSON.stringify({two, three, ids2, ids3, late, josa}));
""".replace("NOW", str(NOW))


def test_the_screens_in_node(w3, answers, tmp_path):
    a2, a3 = answers["p0"], answers["p3"]
    out = _node(tmp_path, SCREENS_JS, s2=a2["build"], t2=a2["trades"], f2=a2["safety"], c2=a2["costs"],
                s3=a3["build"], t3=a3["trades"], f3=a3["safety"], c3=a3["costs"], p3=a3["perf"], now=a3["now"])
    two, three = out["two"], out["three"]
    for k, t in two.items():                              # not installed: nothing of it anywhere, as before
        if k != "hq":
            assert "딥코인" not in str(t), k
    # 한눈에 shows the four live accounts always (owners 10-25 night): 딥코인 as 설치 전 (no number), WOO X Pro 2 the mix bot's
    assert two["reactors"] == 4 and {"three", "four"} <= set(two["deck"].split()) and "five" not in two["deck"].split()
    assert "딥코인 진짜 돈 봇 VWAP 개선판 따라갈 실행기 (paperbot-executor-deepcoin) 설치 전" in two["hq"]
    assert "WOO X Pro 2 진짜 돈 봇 친구 30분 봇(믹스)" in two["hq"] and "딥코인 $" not in two["hq"]
    assert out["ids2"] == [["bybit", "mexc"]] * 3 + [["paper", "bybit", "mexc"]] * 2
    assert out["ids3"][:4] == [["bybit", "mexc", "deepcoin"]] * 4
    assert out["ids3"][4] == ["paper", "paper2", "bybit", "mexc", "deepcoin"] and out["ids3"][5][-1] == "deepcoin"
    assert out["ids3"][6] == "바이비트 · WOO X Pro · 딥코인" and out["ids3"][7] == "다섯 계좌"
    assert re.search(r"딥코인 \$98\.\d\d · 포지션 0/1·0/1·1/1", three["real"]), three["real"]
    assert "딥코인 $98." in three["band"] and "D 근거 쌓는 중 7/20" in three["band"]
    assert three["reactors"] == 4 and "three" in three["deck"].split() and "설치 전" not in three["hq"]   # its own card, the mix bot's
    assert "바이비트 · WOO X Pro · 딥코인" in three["hq"] and "딥코인 진짜 돈 봇 VWAP 개선판 따라감" in three["hq"]
    assert "WOO X Pro 딥코인" in three["trades"]                        # its table is a choice
    assert "딥코인 deepcoin · mainnet" in three["safety"] and "실행기 세 개" in three["safety"]
    assert three["costCards"] >= 1 and "딥코인 실거래 · 진짜 돈" in three["cost"] and "딥코인 API 문서의 요율 조회 예시(Lv1)" in three["cost"]
    for k, t in three.items():
        assert not BAD.search(str(t)), (k, BAD.search(str(t)))
        assert not WRONG.search(str(t)), (k, WRONG.search(str(t)))
    assert out["josa"] == ["딥코인이", "바이비트·WOO X Pro가", "딥코인은", "WOO X Pro는"]
    late = out["late"]
    assert "딥코인" not in late["bandBefore"] and "딥코인 $98." in late["band"]
    assert late["reactors0"] == 4 and late["reactors"] == 4 and "three" in late["deck"].split()       # 설치 전 → its own card


def test_the_house_rules_of_the_third_slot():
    kit = FW._read(SCREENS, "livebots-kit.js")
    # (the fourth slot, WOO X Pro 2, owners 10-24: tests/test_wooxpro2_slot.py; the fifth, 투비트, 10-25: tests/test_toobit_slot.py)
    assert 'export const EXEC_SLOTS = ["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"];' in kit and 'deepcoin: {ko: "딥코인", s: "D"' in kit
    shorts = re.findall(r'^  \w+: \{ko: "[^"]+", s: "(\w+)"', kit, re.M)
    assert "D" in shorts and len(shorts) == len(set(shorts)), shorts                 # its letter is its own
    # nothing of the slot's 10-23 name is left on the screens (a config naming flipster is read by the server: EX_NAME)
    for f in sorted(os.listdir(SCREENS)):
        if f.startswith("livebots"):
            assert not re.search(r"flipster|플립스터|series-fl\b", FW._read(SCREENS, f), re.I), f
    # one shared list (the kit's): no screen hard-codes the two executors' ids any more
    for f in sorted(os.listdir(SCREENS)):
        if f.startswith("livebots") and f.endswith(".js") and f != "livebots-kit.js":
            assert not re.search(r'\["bybit", "mexc"\]|\["paper", "paper2", "bybit", "mexc"\]', FW._read(SCREENS, f)), f
    css = FW._read(V4, "tokens.css")
    assert "--series-dc: hsl(20 var(--av-s) var(--av-ring-l));" in css and "--series-fl" not in css
    for f, cls in (("livebots.css", ".lb-a-deepcoin .lb-sw"), ("livebots-hq.css", ".lbh-x-deepcoin"), ("livebots-cost.css", ".lbk-a-deepcoin"),
                   ("livebots-map.css", ".lbm-a-deepcoin"), ("livebots-risk.css", ".lbv-a-deepcoin"), ("livebots-goal.css", ".lbg-a-deepcoin"),
                   ("livebots-expect.css", ".lex-a-deepcoin")):
        assert cls in FW._read(SCREENS, f), (f, cls)
    hq = FW._read(SCREENS, "livebots-hq.css")
    assert ".lbh-deck.three > .lbh-reactor:last-child { grid-column: 1 / -1; }" in hq     # a phone: two a row, the third across
    assert ".lbh-deck.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }" in hq


# ================================================================ the live checks and the Telegram messages
def test_livecheck_reads_the_third_executor_only_once_installed(tmp_path, monkeypatch):
    cfg, db = tmp_path / "executor-deepcoin.json", tmp_path / "executor-deepcoin-live.db"
    spec3 = (("deepcoin", str(cfg), "paperbot-executor-deepcoin", str(db), 0, 0.85),)
    monkeypatch.setattr(LC, "OPTIONAL_EXECUTORS", spec3)
    base = tuple((n, str(tmp_path / f"{n}.json"), u, str(tmp_path / f"{n}.db"), k, s) for n, _p, u, _d, k, s in LC.EXECUTORS)
    assert LC.installed_specs(base, spec3) == base
    assert [e.name for e in LC.load_executors(LC.installed_specs(base, spec3))] == ["bybit", "mexc"]
    cfg.write_text(json.dumps({"exchange": "deepcoin", "account": "COMBO@mix", "paper_db": "/var/lib/paperbot/combo/vwap.db",
                               "db": str(db), "signal_light_n": 20, "signal_light_min_win": 0.75, "budget_usd": 100,
                               "risk": {"max_loss_frac": 0.2, "kill_file": "/var/lib/paperbot/STOP"}}), encoding="utf-8")
    infos = LC.load_executors(LC.installed_specs(base, spec3))
    assert [e.name for e in infos] == ["bybit", "mexc", "deepcoin"]
    f = infos[-1]
    assert (f.label, f.unit, f.db, f.paper_db, f.light_n, f.budget, f.max_loss) == (
        "딥코인", "paperbot-executor-deepcoin", str(db), "/var/lib/paperbot/combo/vwap.db", 20, 100.0, 0.2)
    assert f.fee == LC.ASSUMED_FEE["deepcoin"] == 0.0005 and LC.pad_of("deepcoin", f.label) == "딥코인   "
    assert len(LC.PAD["deepcoin"].encode("euc-kr")) == len(LC.PAD["bybit"].encode("euc-kr")) == 9    # the same width
    assert "flipster" not in LC.ASSUMED_FEE and "flipster" not in LC.PAD
    cfg.unlink()
    db.write_bytes(b"")                                  # the database alone: installed too (the site's rule)
    assert [x[0] for x in LC.installed_specs(base, spec3)] == ["bybit", "mexc", "deepcoin"]
    # this server's own: the start guide's paths (none of them here)
    assert [x[0] for x in LC.OPTIONAL_EXECUTORS] == ["deepcoin"]
    # the words that count the executors: the STOP file stops all three; never suggested to stop under low memory
    assert LC.every_ko(2) == "두 실행기 모두" and LC.every_ko(3) == "세 실행기 모두"
    f.max_dd = None
    assert "세 실행기 모두 바로 닫고 멈추려면" in LC.dd_halt_words(f, 3) and "두 실행기 모두" in LC.dd_halt_words(f)
    three = [LC.ExecInfo(n, "", "", "", 0, 0.85, kill_file="/var/lib/paperbot/STOP") for n in ("bybit", "mexc", "deepcoin")]
    assert "(세 실행기 모두 바로 닫고 멈추려면 sudo touch /var/lib/paperbot/STOP)" in LC.streak_todo(three)
    assert "(두 실행기 모두 바로 닫고 멈추려면" in LC.streak_todo(three[:2])
    assert "paperbot-executor-deepcoin.service" in LC.PROTECTED_UNITS and not LC.experiment("paperbot-executor-deepcoin.service")
    lines = LC.memory_lines([("paperbot-agents.service", 900 * 1024 ** 2)], ("paperbot-executor-deepcoin",))
    assert lines[1].endswith("paperbot-combo-mexc, paperbot-executor-deepcoin")


@pytest.fixture(scope="module")
def preview():
    return LPV.scenes("deepcoin")


def test_the_preview_with_three_executors(preview):
    texts = [t for _title, _lv, t in preview]
    entries = [t for t in texts if t.startswith("🟢 진입")]
    vw = next(t for t in entries if "VWAP 개선판" in t)
    tr = next(t for t in entries if "추세판단 봇" in t)
    assert "딥코인   ✅" in vw and "바이비트" not in vw and "WOO X Pro" not in vw        # each bot lists only its own executors
    assert "바이비트 ✅" in tr and "WOO X Pro ✅" in tr and "딥코인" not in tr
    exits = [t for t in texts if t.startswith("✅ 청산")]
    assert any("VWAP 개선판" in t and "딥코인   +$" in t and "잔고 $" in t for t in exits)
    assert any("추세판단 봇" in t and "바이비트 +$" in t and "WOO X Pro +$" in t and "딥코인" not in t for t in exits)
    morning = next(t for t in texts if t.startswith("📋"))
    for word in ("- 바이비트 1번", "- WOO X Pro 1번", "- 딥코인 1번", "수수료 0.050%(가정 0.050%)",
                 "추세판단 봇(바이비트·WOO X Pro가 따라감)", "VWAP 개선판 (딥코인이 따라감)",
                 "- 딥코인(VWAP 개선판 따라간 거래): 거래 1번"):
        assert word in morning, word
    for t in texts:
        assert not re.search(r"\b(None|null|undefined|nan)\b", t), t
        assert not WRONG.search(t), t
    assert LC.EX_KO["deepcoin"] == "딥코인"


def test_the_preview_flag(monkeypatch):
    import argparse
    seen = []
    monkeypatch.setattr(LPV, "main", lambda world="live15": seen.append(world) or 0)
    for flags, world in (({"deepcoin": True}, "deepcoin"), ({"vwap": True}, "vwap"), ({}, "live15")):
        LC.cmd_preview(argparse.Namespace(**{"old": False, "two": False, "vwap": False, "deepcoin": False, **flags}))
        assert seen[-1] == world


def test_the_team_reads_the_third_executor_once_installed(w3, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none-combo.json"))
    assert [e.name for e in T.bot_world(w3["p3"])["infos"]] == ["bybit", "mexc", "deepcoin"]
    assert [e.name for e in T.bot_world(w3["p0"])["infos"]] == ["bybit", "mexc"]
    t = lambda key, pid, pnl, x: {"key": key, "exit_time": x, "pnl": pnl, "symbol": "ETHUSDT", "side": 1, "roe": pnl / 4,  # noqa: E731
                                  "paper": {"id": pid, "roe": -0.1}, "strategy_id": "F6_VWAP_FAIL", "timeframe": "30m", "reason_ko": "손절"}
    rows = [t("a", 1, 2.0, NOW - 5 * H), t("b", 2, -3.0, NOW - 3 * H), t("c", 3, -1.0, NOW - H)]
    key, focus = T.due_loss({"now": NOW, "trades": {"accts": {"bybit": {"rows": rows[:1]}, "deepcoin": {"rows": rows}}}})
    assert key == "loss:2+3" and focus["executor"] == "deepcoin"


# ================================================================ the server's files
def test_the_unit_is_installed_never_started_and_the_config_never_written():
    unit = (ROOT / "deploy" / "paperbot-executor-deepcoin.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.executor run --config /etc/paperbot/executor-deepcoin.json" in unit
    assert "NEVER enables or starts it" in unit and "OOMScoreAdjust=-900" in unit
    sh = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert ('install -m 644 "$APP/deploy/paperbot-executor-deepcoin.service" '
            "/etc/systemd/system/paperbot-executor-deepcoin.service") in sh
    assert not re.search(r"systemctl (enable|start)\b[^\n]*paperbot-executor-deepcoin", sh)
    assert "systemctl is-active --quiet paperbot-executor-deepcoin" in sh and "sudo systemctl restart paperbot-executor-deepcoin" in sh
    # like the other two executors' configs, its config is never written by install.sh (the owners copy the template)
    assert "/etc/paperbot/executor-deepcoin.json" in sh and not re.search(r"install [^\n]*executor\.live-deepcoin\.json", sh)
    assert not re.search(r"(install|cp)\s[^\n]*/etc/paperbot/executor(-mexc)?\.json", sh)
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "install.sh")]).returncode == 0
    # the slot's unit of 10-23 is no longer installed (its file is removed only while unused: the next test)
    assert "deploy/paperbot-executor-flipster.service" not in sh and not (ROOT / "deploy" / "paperbot-executor-flipster.service").exists()
    assert not re.search(r"systemctl (enable|start|stop|disable|restart)\b[^\n]*paperbot-executor-flipster", sh)
    env = (ROOT / "deploy" / "dash.env.example").read_text(encoding="utf-8")
    assert "#PAPERBOT_LIVE_DEEPCOIN_DB=/var/lib/paperbot/exec/executor-deepcoin-live.db" in env
    assert "#PAPERBOT_LIVE_DEEPCOIN_CONFIG=/etc/paperbot/executor-deepcoin.json" in env
    assert "FLIPSTER" not in env
    # deploy/trend_switch.py moves the executors to the trend bot: the third follows the VWAP bot, it is not in that list
    assert "deepcoin" not in (ROOT / "deploy" / "trend_switch.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("active, enabled, removed", [("inactive", "disabled", True), ("active", "disabled", False),
                                                      ("inactive", "enabled", False), ("failed", "disabled", False),
                                                      ("activating", "disabled", False)])
def test_install_removes_the_old_flipster_unit_only_while_unused(tmp_path, active, enabled, removed):
    """install.sh's own lines (systemctl stubbed): a paperbot-executor-flipster.service an install of 10-23 left goes only
    while that unit is inactive and not enabled; started, failed or enabled: left as it is, said so. Never stopped,
    disabled or touched otherwise."""
    sh = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    block = sh[sh.index("OLD_THIRD="):sh.index("systemctl daemon-reload")]
    unit = tmp_path / "paperbot-executor-flipster.service"
    block = block.replace("/etc/systemd/system/paperbot-executor-flipster.service", str(unit))
    assert "/etc/systemd" not in block
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "systemctl").write_text(
        "#!/bin/sh\n"
        'echo "$@" >> "$CALLS"\n'
        'case "$1" in\n'
        '  is-active) echo "$FAKE_ACTIVE"; [ "$FAKE_ACTIVE" = active ] ;;\n'
        '  is-enabled) [ "$FAKE_ENABLED" = enabled ] ;;\n'
        "  *) exit 9 ;;\n"
        "esac\n", encoding="utf-8")
    os.chmod(bin_ / "systemctl", 0o755)
    calls = tmp_path / "calls"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_ACTIVE": active, "FAKE_ENABLED": enabled,
           "CALLS": str(calls)}
    unit.write_text("[Unit]\n", encoding="utf-8")
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert unit.exists() is not removed
    assert ("removed the unused paperbot-executor-flipster unit" in r.stdout) is removed
    assert ("left as it is" in r.stdout) is not removed
    assert {ln.split()[0] for ln in calls.read_text().splitlines()} <= {"is-active", "is-enabled"}     # it only asks
    unit.unlink(missing_ok=True)
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""                      # no old unit file (a new server): nothing at all


def test_the_backups_and_the_restore_know_its_database():
    assert "exec/executor-deepcoin-live" in off.DB_NAMES
    sh = (ROOT / "deploy" / "paperbot-backup.sh").read_text(encoding="utf-8")
    assert tuple(re.search(r"^for f in (.+); do$", sh, re.M).group(1).split()) == off.DB_NAMES
    dest = Path("/root/restore-out/20261024")
    text = off.next_steps(dest, ["executor-deepcoin-live.db"])
    n = "executor-deepcoin-live.db"
    assert f"sudo install -o paperbot-exec -g paperbot -m 640 {dest / n} /var/lib/paperbot/exec/{n}" in text
    assert "paperbot-executor-deepcoin" in text.split("2)")[0]          # stopped before its file goes back


# ================================================================ deploy/vwap_switch.py --exec deepcoin
def _deepcoin_cfg(tmp_path) -> str:
    """A DeepCoin config as the template has it: the VWAP bot's values already (the WOO X Pro VWAP template's, with its
    own exchange and database)."""
    d = json.loads((ROOT / "deploy" / "executor.live-wooxpro-vwap.json").read_text(encoding="utf-8"))
    d.update(exchange="deepcoin", db="/var/lib/paperbot/exec/executor-deepcoin-live.db")
    d.pop("net_costs", None)
    p = tmp_path / "executor-deepcoin.json"
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return str(p)


def test_vwap_switch_sets_the_budget_and_the_size_of_the_third(tmp_path, capsys):
    assert VS.EXECS["deepcoin"] == ("딥코인", "/etc/paperbot/executor-deepcoin.json", "paperbot-executor-deepcoin")
    assert sorted(VS.EXECS) == ["bybit", "deepcoin", "wooxpro"]                                         # no flipster slot
    assert VS.EXECS["bybit"][1:] == ("/etc/paperbot/executor.json", "paperbot-executor")                  # the two as before
    assert VS.EXECS["wooxpro"][1:] == ("/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc")
    cfg = _deepcoin_cfg(tmp_path)
    os.chmod(cfg, 0o640)
    old = json.loads(Path(cfg).read_text())
    seen = []
    rc = VS.main(["--exec", "deepcoin", "--balance", "200", "--config", cfg, "--write"], active=lambda u: seen.append(u) or False,
                 wallet_of=lambda: 1000.0)
    out = capsys.readouterr().out
    assert rc == 0 and seen == ["paperbot-executor-deepcoin"] and "sudo systemctl start paperbot-executor-deepcoin" in out
    new = json.loads(Path(cfg).read_text())
    assert {k for k in set(old) | set(new) if old.get(k) != new.get(k)} == {"budget_usd", "qty_scale"}   # the rest: the template's
    assert new["budget_usd"] == 200 and new["qty_scale"] == 0.2 and oct(os.stat(cfg).st_mode & 0o777) == oct(0o640)
    assert VS.main(["--exec", "deepcoin", "--back", "--config", cfg, "--write"], active=lambda u: False) == 0
    assert json.loads(Path(cfg).read_text()) == old
    # refusals: while it runs, another exchange's file
    assert VS.main(["--exec", "deepcoin", "--balance", "200", "--config", cfg, "--write"], active=lambda u: True,
                   wallet_of=lambda: 1000.0) == 1
    assert "paperbot-executor-deepcoin" in capsys.readouterr().out
    woo = tmp_path / "executor-mexc.json"
    shutil.copyfile(ROOT / "deploy" / "executor.live-wooxpro.json", woo)
    assert VS.main(["--exec", "deepcoin", "--balance", "200", "--config", str(woo)], active=lambda u: False, wallet_of=lambda: 1000.0) == 1
    assert "거래소는 'wooxpro'" in capsys.readouterr().out
    assert VS.main(["--exec", "wooxpro", "--balance", "200", "--config", cfg], active=lambda u: False, wallet_of=lambda: 1000.0) == 1


def test_vwap_switch_on_the_repository_template():
    tpl = ROOT / "deploy" / "executor.live-deepcoin.json"
    if not tpl.exists():
        pytest.skip("deploy/executor.live-deepcoin.json comes with the DeepCoin executor's own change")
    cur = tpl.read_text(encoding="utf-8")
    new, _w = VS.plan_exec(cur, "deepcoin", 150.0, 1000.0)
    old, got = json.loads(cur), json.loads(new)
    assert {k for k in set(old) | set(got) if old.get(k) != got.get(k)} <= {"budget_usd", "qty_scale"}
    assert got["paper_db"] == "/var/lib/paperbot/combo/vwap.db" and got["qty_scale"] == 0.15
