"""deploy/combo.live-ac.expected.json: the backtest reference the live loss cards, drift alarm and per-strategy
scorecard compare against. It must describe the live config as it is (regenerate it when the config changes)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "deploy" / "combo.live-ac.expected.json"
CFG = ROOT / "deploy" / "combo.live-ac.json"


def _exp():
    return json.loads(EXP.read_text(encoding="utf-8"))


def test_reference_matches_the_live_config():
    assert _exp()["config_sha256"] == hashlib.sha256(CFG.read_bytes()).hexdigest()


def test_reference_covers_every_member_and_strategy():
    e, members = _exp(), json.loads(CFG.read_text(encoding="utf-8"))["members"]
    assert len(e["members"]) == len(members)
    for j, m in enumerate(members):
        x = e["members"][str(j)]
        assert (x["strategy"], x["tf"]) == (m["strategy"], m["tf"])
        assert x["stop"] == f"{m['stop'][0]}{m['stop'][1]:g}"
    assert set(e["strategies"]) == {m["strategy"] for m in members}


def test_reference_headline_numbers():
    o = _exp()["overall"]
    assert 0.90 < o["fit"]["win"] < 0.93 and 3.0 < o["fit"]["per_weekday"] < 3.2
    assert 0.70 < o["honest"]["win_2025_26"] < 0.80
    assert o["fit"]["rolling20_wins"]["p5"] >= o["honest"]["rolling20_wins"]["p5"]
