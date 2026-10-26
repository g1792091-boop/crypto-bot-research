"""The '레인지 봇' (owners 10-26): its unit and install wiring, and deploy/range_switch.py: the WOO X Pro executor moved to
it, only while it is stopped and the paper bot has an account; every other value of its config stays; back to the newest
copy; the repository template is what the switch writes and passes the executor's check-config."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

from paperbot import executor as E
from paperbot.executor import ExecConfig
from paperbot.store3 import Store3

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
spec = importlib.util.spec_from_file_location("range_switch", DEPLOY / "range_switch.py")
RS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RS)
CHANGED = {"paper_db", "size_from", "margin_frac", "leverage_by_symbol", "stop_from", "stop_roe", "stop_net", "ladder_from",
           "ladder", "take_profit_roe", "ladder_basis", "signal_light_n", "equity_floor_frac", "liq_guard", "liq_guard_mmr",
           "macro_block_min", "stop_scale", "risk"}


def _paper(tmp_path, wallet=1000.0):
    db = str(tmp_path / "range.db")
    s = Store3(db)
    s.put_state("accounts", 1, {"engines": {"COMBO@mix": {"wallet": wallet, "position": None}}})
    s.commit()
    s.conn.close()
    return db


def _exec(tmp_path, name="executor.live-wooxpro.json", fname="executor.json", **over):
    p = tmp_path / fname
    d = json.loads((DEPLOY / name).read_text(encoding="utf-8"))
    d.update(over)
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(p)


def test_unit_and_install_never_start_it():
    unit = (DEPLOY / "paperbot-combo-range.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.combo run --config /etc/paperbot/combo-range.json" in unit
    assert "ReadWritePaths=/var/lib/paperbot/combo\n" in unit and "OOMScoreAdjust=-500" in unit
    inst = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert ('install -m 644 "$APP/deploy/paperbot-combo-range.service" /etc/systemd/system/paperbot-combo-range.service'
            in inst)
    assert "enable --now paperbot-combo-range" not in inst and "start paperbot-combo-range" not in inst
    assert 'UNITS="$UNITS paperbot-combo-range"' in inst                # stopped for the code swap, started again
    assert "combo/range" in (DEPLOY / "paperbot-backup.sh").read_text(encoding="utf-8")


def test_dry_run_writes_nothing_and_lists_the_changes(tmp_path, capsys):
    cfg = _exec(tmp_path)
    before = Path(cfg).read_text()
    rc = RS.main(["--config", cfg], active=lambda u: False, ready=lambda: 1000.0)
    out = capsys.readouterr().out
    assert rc == 0 and Path(cfg).read_text() == before and not list(tmp_path.glob("*.before-range-*"))
    for k in ("paper_db", "size_from", "margin_frac", "stop_from", "take_profit_roe", "ladder"):
        assert k in out
    assert "보여 주기만" in out and "레인지 봇 페이퍼(지갑 $1,000.00)" in out


def test_write_moves_the_executor_and_keeps_everything_else(tmp_path):
    # the server's WOO X Pro config after the trend switch and the size switch, with a ratio stop scale and a floor
    cfg = _exec(tmp_path, paper_db="/var/lib/paperbot/combo/live-ac.db", size_from="equity", margin_frac=0.4,
                stop_scale=1.25, equity_floor_frac=0.7, signal_light_n=20, own_keys=True)
    os.chmod(cfg, 0o640)
    old = json.loads(Path(cfg).read_text())
    db = _paper(tmp_path)
    assert RS.main(["--config", cfg, "--write"], active=lambda u: False, ready=lambda: RS.paper_ready(db)) == 0
    new = json.loads(Path(cfg).read_text())
    assert new["paper_db"] == "/var/lib/paperbot/combo/range.db" and new["account"] == "COMBO@mix"
    assert new["size_from"] == "equity" and new["margin_frac"] == 0.4
    assert new["leverage_by_symbol"] == {"BTCUSDT": 40, "*": 30} and new["risk"]["max_leverage"] == 40
    assert (new["stop_from"], new["stop_roe"], new["stop_net"]) == ("roe", 0.5, True) and "stop_scale" not in new
    assert (new["ladder_from"], new["ladder"], new["take_profit_roe"], new["ladder_basis"]) == ("own", None, 0.1, "net")
    assert new["signal_light_n"] == 0 and new["equity_floor_frac"] is None
    assert new["liq_guard"] is True and new["liq_guard_mmr"] == 0.005 and new["macro_block_min"] == 30
    for k in set(old) - CHANGED:
        assert new[k] == old[k], k                         # db, keys, net_costs, budget, mode, entry source ...
    assert new["db"] == old["db"] and new["net_costs"] == old["net_costs"] and new["own_keys"] is True
    assert {k: v for k, v in new["risk"].items() if k != "max_leverage"} == \
        {k: v for k, v in old["risk"].items() if k != "max_leverage"}
    assert oct(os.stat(cfg).st_mode & 0o777) == oct(0o640)
    assert ExecConfig.from_dict(new).problems() == []
    backups = list(tmp_path.glob("executor.json.before-range-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == old
    # and back
    assert RS.main(["--back", "--config", cfg, "--write"], active=lambda u: False) == 0
    assert json.loads(Path(cfg).read_text()) == old


def test_refusals(tmp_path, capsys):
    cfg = _exec(tmp_path)
    before = Path(cfg).read_text()
    # the executor runs: nothing written
    assert RS.main(["--config", cfg, "--write"], active=lambda u: True, ready=lambda: 1000.0) == 1
    assert "paperbot-executor-mexc" in capsys.readouterr().out
    # the other exchange's file
    assert RS.main(["--exec", "bybit", "--config", cfg, "--write"], active=lambda u: False, ready=lambda: 1000.0) == 1
    assert "거래소는 'wooxpro'" in capsys.readouterr().out
    # no paper bot record yet
    assert RS.main(["--config", cfg, "--write"], active=lambda u: False,
                   ready=lambda: RS.paper_ready(str(tmp_path / "missing.db"))) == 1
    assert "paperbot-combo-range" in capsys.readouterr().out
    # an executor that enters on signals
    sig = _exec(tmp_path, fname="signal.json", entry_source="signal")
    assert RS.main(["--config", sig, "--write"], active=lambda u: False, ready=lambda: 1000.0) == 1
    assert "entry_source" in capsys.readouterr().out
    # nothing to go back to
    assert RS.main(["--back", "--config", cfg], active=lambda u: False) == 1
    assert Path(cfg).read_text() == before and not list(tmp_path.glob("*.before-range-*"))


def test_the_repository_template_is_what_the_switch_writes(capsys):
    cur = (DEPLOY / "executor.live-wooxpro.json").read_text()
    new, _w = RS.plan_exec(cur, "wooxpro")
    assert json.loads(new) == json.loads((DEPLOY / "executor.live-wooxpro-range.json").read_text())
    E.main(["check-config", "--config", str(DEPLOY / "executor.live-wooxpro-range.json")])
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1] == "준비됨"
    assert "익절: 순ROE +10%에서 시장가로 전부 닫음 (계단 없음)" in lines
    assert "신호등: 꺼짐 (paper의 모든 진입을 따라감)" in lines


def test_the_morning_check_names_its_unit():
    from paperbot import livecheck as LC
    assert LC.unit_of("/var/lib/paperbot/combo/range.db") == "paperbot-combo-range"
    assert "sudo systemctl status paperbot-combo-range" in LC.paper_unit_todo("/var/lib/paperbot/combo/range.db")
