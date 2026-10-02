"""GH Coin call recorder: the node core (tests/ghcoin_recorder.test.mjs) and the Python reader."""
import json
import os
import shutil
import subprocess

import pytest

from paperbot import ghcoin as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_recorder_core_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--test", os.path.join(ROOT, "tests", "ghcoin_recorder.test.mjs")],
                       capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def _events(tmp_path, calls):
    lines = []
    for i, (sym, net, mnet, res) in enumerate(calls):
        cid = f"{sym}-{i}"
        lines += [{"ev": "open", "id": cid, "sym": sym, "side": 1, "t": 1000 + i, "cost_r": 0.1},
                  {"ev": "open", "id": cid + "-m", "of": cid, "mirror": True, "sym": sym, "side": -1, "t": 1000 + i},
                  {"ev": "close", "id": cid, "result": res, "r": net + 0.1, "net_r": net, "end": 2000 + i},
                  {"ev": "close", "id": cid + "-m", "result": "x", "r": mnet + 0.1, "net_r": mnet, "end": 2000 + i}]
    lines.append({"ev": "open", "id": "BTCUSDT-open", "sym": "BTCUSDT", "side": 1, "t": 9000})
    (tmp_path / "calls.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n{torn", encoding="utf-8")


def test_reader_totals_and_coin_flip(tmp_path):
    # GH Coin's side always better than its mirror: a coin flip rarely does as well
    _events(tmp_path, [("BTCUSDT", 1.4, -1.2, "win")] * 12 + [("ETHUSDT", -1.1, 1.3, "loss")] * 2)
    (tmp_path / "board.json").write_text(json.dumps({"ts": 5000, "commit": "9940b55", "coins": {}}))
    rep = G.report(str(tmp_path), now_ms=5000 + 60_000)
    t = rep["total"]
    assert t["calls"] == 14 and rep["open"] == 1 and rep["alive"] and rep["commit"] == "9940b55"
    assert t["results"] == {"win": 12, "loss": 2}
    assert t["net_r"] == pytest.approx(12 * 1.4 - 2 * 1.1)
    assert t["coin_flip_net_r"] == pytest.approx((12 * 0.2 + 2 * 0.2) / 2)
    assert t["p_coin_flip"] < 0.01
    assert rep["by_coin"]["ETHUSDT"]["calls"] == 2
    assert "우연보다 낫다고 볼 근거 있음" in G.text(rep)
    # a call no better than its mirror: no evidence
    _events(tmp_path, [("BTCUSDT", 1.4, 1.4, "win"), ("BTCUSDT", -1.0, -1.0, "loss")] * 5)
    rep = G.report(str(tmp_path), now_ms=10 ** 9)
    assert rep["total"]["p_coin_flip"] > 0.5 and not rep["alive"]
    # since: older calls are left out
    assert G.report(str(tmp_path), since_ms=1005)["total"]["calls"] == 5


def test_reader_without_files(tmp_path):
    rep = G.report(str(tmp_path / "none"))
    assert rep["total"] == {"calls": 0} and rep["open"] == 0 and not rep["alive"]
    assert "아직 없습니다" in G.text(rep)


def test_install_and_unit_wiring():
    inst = open(os.path.join(ROOT, "deploy", "install.sh"), encoding="utf-8").read()
    unit = open(os.path.join(ROOT, "deploy", "paperbot-ghcoin.service"), encoding="utf-8").read()
    commit = open(os.path.join(ROOT, "deploy", "ghcoin.commit"), encoding="utf-8").read().strip()
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    assert "paperbot-ghcoin.service paperbot-tgtrades.service paperbot-executor.service; do" in inst and " nodejs\n" in inst
    assert "gh-coin/combo.js gh-coin/lib/patterns.js gh-coin/lib/ta_rating.js" in inst
    assert "ReadWritePaths=/var/lib/paperbot/ghcoin" in unit and "-/etc/paperbot" in unit and "User=paperbot" in unit
