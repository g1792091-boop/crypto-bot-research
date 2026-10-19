"""deploy/executor.live-{bybit,mexc}.json: the owners copy these to /etc/paperbot (10/19 start guide, "★ 최종 시작 순서"
3-4) instead of typing the JSON. They must stay exactly the guide's settings and pass check-config."""
import json
from pathlib import Path

from paperbot import executor as E

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def _load(name):
    return json.loads((DEPLOY / name).read_text(encoding="utf-8"))


def test_bybit_and_mexc_differ_only_in_exchange_db_and_light():
    b, m = _load("executor.live-bybit.json"), _load("executor.live-mexc.json")
    diff = {k for k in set(b) | set(m) if b.get(k) != m.get(k)}
    assert diff == {"exchange", "db", "signal_light_min_win"}
    assert (b["exchange"], m["exchange"]) == ("bybit", "mexc")
    assert (b["signal_light_min_win"], m["signal_light_min_win"]) == (0.85, 0.9)
    assert b["paper_db"] == m["paper_db"] == "/var/lib/paperbot/combo/live-ac.db"
    assert b["account"] == "COMBO@mix" and b["mode"] == "mainnet" and b["budget_usd"] == 100


def test_no_removed_limits_and_fixed_rules_kept():
    for name in ("executor.live-bybit.json", "executor.live-mexc.json"):
        r = _load(name)["risk"]
        assert "daily_max_loss_usd" not in r
        assert "max_consecutive_losses" not in r            # owners 10-19: no loss-streak halt
        assert r["max_drawdown_pct"] == 0.5 and r["max_loss_frac"] == 0.35
        assert r["max_leverage"] == 40 and r["kill_file"] == "/var/lib/paperbot/STOP"
        assert r["allowed_symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]


def test_check_config_says_ready(capsys):
    for name in ("executor.live-bybit.json", "executor.live-mexc.json"):
        E.main(["check-config", "--config", str(DEPLOY / name)])
        assert capsys.readouterr().out.strip().splitlines()[-1] == "준비됨"
