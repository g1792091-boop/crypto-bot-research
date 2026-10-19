"""deploy/executor.live-{bybit,mexc}.json: the owners copy these to /etc/paperbot (10/19 start guide, "★ 최종 시작 순서"
3-4) instead of typing the JSON. They must stay exactly the guide's settings and pass check-config."""
import json
from pathlib import Path

from paperbot import executor as E

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def _load(name):
    return json.loads((DEPLOY / name).read_text(encoding="utf-8"))


def test_bybit_and_mexc_differ_only_in_exchange_db_and_paper_db():
    b, m = _load("executor.live-bybit.json"), _load("executor.live-mexc.json")
    diff = {k for k in set(b) | set(m) if b.get(k) != m.get(k)}
    assert diff == {"exchange", "db", "paper_db"}
    assert (b["exchange"], m["exchange"]) == ("bybit", "mexc")
    # owners 10-19 (규칙봇 15): no signal light, both executors follow every paper entry
    assert b["signal_light_n"] == m["signal_light_n"] == 0 and "signal_light_min_win" not in b
    # owners 10-19 (final, "Mexc -35%로 가자"): each executor follows its own paper bot, the "db" of that bot's config file:
    # Bybit 규칙봇 15 (-50 %), MEXC its -35 % twin (deploy/combo.live15-mexc.json, docs/live15-mexc-ko.md)
    assert b["paper_db"] == _load("combo.live15.json")["db"] == "/var/lib/paperbot/combo/live-ac.db"
    assert m["paper_db"] == _load("combo.live15-mexc.json")["db"] == "/var/lib/paperbot/combo/live15-mexc.db"
    assert b["account"] == m["account"] == "COMBO@mix" and b["mode"] == "mainnet" and b["budget_usd"] == 100


def test_no_removed_limits_and_fixed_rules_kept():
    for name in ("executor.live-bybit.json", "executor.live-mexc.json"):
        r = _load(name)["risk"]
        assert "daily_max_loss_usd" not in r
        assert "max_consecutive_losses" not in r            # owners 10-19: no loss-streak halt
        assert "max_drawdown_pct" not in r                  # owners 10-19: no drawdown halt either
        assert r["max_loss_frac"] == 0.35
        assert r["max_leverage"] == 40 and r["kill_file"] == "/var/lib/paperbot/STOP"
        assert r["allowed_symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]


def test_check_config_says_ready(capsys):
    for name in ("executor.live-bybit.json", "executor.live-mexc.json"):
        E.main(["check-config", "--config", str(DEPLOY / name)])
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines[-1] == "준비됨"
        # the 규칙봇 15 guide (step 5): the last two lines are the light (off) and 준비됨; the halt line before them says
        # the executor no longer halts by itself on a losing run or a drawdown (owners 10-19)
        assert lines[-2] == "신호등: 꺼짐 (paper의 모든 진입을 따라감)"
        assert lines[-3] == "멈춤: 연패·낙폭으로는 멈추지 않음 (비상 정지 파일 /var/lib/paperbot/STOP만)"
        assert not [ln for ln in lines if "연패면" in ln or "3연패" in ln or "낙폭 50%" in ln]


def test_check_config_names_the_halts_of_an_old_config(tmp_path, capsys):
    d = _load("executor.live-bybit.json")
    d["risk"].update(max_consecutive_losses=3, max_drawdown_pct=0.5)
    d["signal_light_n"], d["signal_light_min_win"] = 20, 0.85
    p = tmp_path / "old.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    E.main(["check-config", "--config", str(p)])
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-3] == "멈춤: 3연패 · 최고점 대비 낙폭 50%에 닿으면 스스로 멈춤, 비상 정지 파일 /var/lib/paperbot/STOP"
    assert lines[-2].startswith("신호등: 켜짐 - paper 최근 20번 중 85% 이상")
