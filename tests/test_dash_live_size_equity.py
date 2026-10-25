"""실거래 사이트 · 실행기 크기 (owners 10-25 night): an executor config may say ``"size_from": "equity"`` and
``"margin_frac": 0.4`` (paperbot/executor.py ExecConfig: each new entry's margin = 40 % of the live balance; qty_scale
stays in the file but sizes nothing). The site (dash/more/livebots.py, liveinsight.py, screens/livebots-cost.js /
-more.js / -trades.js) then compares a live trade's P&L with its paper trade's at that trade's own live qty / paper qty,
never qty_scale, and says how the executor sizes ("진입할 때마다 실거래 잔고의 40%를 증거금으로"); an executor with
size_from "paper" (or none) stays exactly as before. On the one-paper world of tests/test_dash_livebots_fees.py, with
WOO X Pro switched to the equity sizing (and a qty_scale of 0.5 left in its file: using it would be far off)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402

NOW = FW.NOW
EQUITY_KO = "진입할 때마다 실거래 잔고의 40%를 증거금으로"


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture
def world(tmp_path):
    w = FW.build_world(tmp_path)
    with open(w["p"]["mexc_config"], encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.update(size_from="equity", margin_frac=0.4, qty_scale=0.5)
    with open(w["p"]["mexc_config"], "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return w


def test_the_config_says_how_it_sizes(world):
    m, b = L.read_config(world["p"]["mexc_config"]), L.read_config(world["p"]["bybit_config"])
    assert (m["size_from"], m["margin_frac"], m["qty_scale"], m["size_ko"]) == ("equity", 0.4, 0.5, EQUITY_KO)
    assert (b["size_from"], b["margin_frac"], b["size_ko"]) == ("paper", None, "실거래 크기 = 페이퍼 수량 × 0.025")      # as before
    assert L.size_scale(m, 3.0, 12.0) == 0.25 and L.size_scale(m, None, 12.0) is None and L.size_scale(m, 3.0, 0) is None
    assert L.size_scale(b, 3.0, 12.0) == 0.025 and L.size_scale({}, 3.0, 12.0) is None                  # never a made-up 1
    assert L.size_ko({"size_from": "equity"}).endswith("(margin_frac 없음)")


def test_each_trade_is_compared_at_its_own_ratio(world):
    p = world["p"]
    tr = L.trade_rows(p, NOW)
    woo, by = tr["accts"]["mexc"], tr["accts"]["bybit"]
    assert (woo["size_from"], woo["margin_frac"], woo["size_ko"]) == ("equity", 0.4, EQUITY_KO) and by["size_from"] == "paper"
    paired = [r for r in woo["rows"] if r["paper"]]
    assert paired
    for r in paired:
        k = r["qty"] / r["paper"]["qty"]
        assert r["size_scale"] == pytest.approx(k) and abs(k - 0.5) > 0.4                               # its own, not qty_scale
        assert r["paper_scaled"] == pytest.approx(r["paper"]["pnl"] * k) and r["diff"] == pytest.approx(r["pnl"] - r["paper"]["pnl"] * k)
    for r in (r for r in by["rows"] if r["paper"]):                                                    # size_from "paper": qty_scale
        assert r["size_scale"] is None and r["paper_scaled"] == pytest.approx(r["paper"]["pnl"] * 0.025)
    # the paper table's cell of each paper trade WOO X Pro followed: the same ratio
    for row in tr["accts"]["paper"]["rows"]:
        c = row["live"].get("mexc") or {}
        if c.get("state") == "matched":
            lt = next(r for r in woo["rows"] if r["key"] == c["key"])
            assert c["diff"] == pytest.approx(lt["pnl"] - row["pnl"] * lt["qty"] / row["qty"])
    co = L.costs(p, NOW)["accts"]["mexc"]
    assert (co["size_from"], co["size_ko"], co["qty_scale"]) == ("equity", EQUITY_KO, 0.5)
    assert co["diff_total"] == pytest.approx(sum(r["diff"] for r in paired))
    assert L.costs(p, NOW)["accts"]["bybit"]["size_from"] == "paper"
    # 규칙 점검's chase replay: no one factor for an equity-sized executor (None, said how it sizes); the other as before
    from paperbot.dash.more import liveinsight as LI
    ch = LI.judge(p, NOW, {**L.paths_more({}), "combo_config": str(world["p"]["paper"]) + ".none"})["chase"]
    assert ch["scale"] == {"bybit": 0.025, "mexc": None} and ch["sizing"]["mexc"] == {"size_from": "equity", "margin_frac": 0.4, "size_ko": EQUITY_KO}


def test_the_pages_say_it(world, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    p = world["p"]
    data = {"c": L.costs(p, NOW), "s": L.settings(p, NOW)}
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{FW.DOM}'); const fs = await import('node:fs');\n"
              "for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),"
              " replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {"
              " const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };\n"
              f"Date.now = () => {NOW};\n"
              f"const CO = await import('file://{FW.SCREENS}/livebots-cost.js'); const MO = await import('file://{FW.SCREENS}/livebots-more.js');\n"
              + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 10));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {}, every() {},"
              " href: (n, x) => '#/' + n + (x ? '/' + x : ''), api: async () => JSON.parse(JSON.stringify(a))});\n"
              "const run = async (V, a) => { const v = V(mkCtx(a)); await tick(); await tick(); return v; };\n"
              "const c = texts((await run(CO.costView, D_c)).el), s = texts((await run(MO.settingsView, D_s)).el);\n"
              "console.log(JSON.stringify({c, s}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert f"페이퍼 크기 × 거래마다 실거래 수량 ÷ 페이퍼 수량 ({EQUITY_KO})" in out["c"] and "페이퍼 크기 × 0.03" in out["c"]   # bybit as before
    assert f"{EQUITY_KO} (설정의 크기 비율 qty_scale은 크기에 안 써요)" in out["s"] and "크기 비율 ×0.03 (페이퍼 수량 × 이 비율)" in out["s"]
    assert "크기 비율 ×0.50" not in out["s"] and not FW.BAD.search(out["c"] + out["s"])


def test_the_unused_loss_share_is_not_shown_for_equity_sizing():
    """size_from "equity" never cuts an entry for its stop (executor._enter): its risk.max_loss_frac is not a limit."""
    risk = {"max_loss_frac": 0.2, "max_notional_usd": 10000}
    assert "max_loss_frac" in [x["key"] for x in L.risk_limits(risk)]
    assert "max_loss_frac" in [x["key"] for x in L.risk_limits(risk, None, "paper")]
    keys = [x["key"] for x in L.risk_limits(risk, None, "equity")]
    assert "max_loss_frac" not in keys and "max_notional_usd" in keys
