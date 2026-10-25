"""The '숏5 하락장' bot (owners 10-25): its paper config (deploy/combo.short5.json), its unit, and deploy/short5_switch.py:
one live executor moved to it, only while it is stopped and the paper bot has an account; every other value of its
config stays; back to the newest copy."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from paperbot import combo as C
from paperbot import executor as E
from paperbot.executor import ExecConfig
from paperbot.store3 import Store3

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
spec = importlib.util.spec_from_file_location("short5_switch", DEPLOY / "short5_switch.py")
SS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SS)


def _paper(tmp_path, wallet=1234.5):
    db = str(tmp_path / "short5.db")
    s = Store3(db)
    s.put_state("accounts", 1, {"engines": {"COMBO@mix": {"wallet": wallet, "position": None}}})
    s.commit()
    s.conn.close()
    return db


def _exec(tmp_path, name):
    p = tmp_path / "executor.json"
    shutil.copyfile(DEPLOY / name, p)
    return str(p)


# ---------------------------------------------------------------- the paper bot
def test_paper_config_is_the_research_pick_and_valid(capsys):
    raw = json.loads((DEPLOY / "combo.short5.json").read_text(encoding="utf-8"))
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == []
    assert cfg.name == "숏5 하락장" and cfg.db == "/var/lib/paperbot/combo/short5.db"
    assert cfg.leverage == {"BTCUSDT": 40, "default": 30} and cfg.margin == 0.4      # the owners' fixed numbers
    assert cfg.ladder == SS.LADDER and cfg.max_loss_frac == SS.MAX_LOSS
    ms = C.resolve_members(cfg.members)
    assert [m.label.split("#")[0] for m in ms] == ["V39_ALL@15m", "S6_EMA_DMI_ADX@15m", "F12_MSS@1h", "N12_ICHI_AO@30m",
                                                   "F16_FIB382@4h"]
    assert C.research_problems(cfg, ms) == []
    for m in raw["members"]:                     # every member: only in the BTC 4h down regime
        assert m["off"] == [["reg", 0], ["reg", 2]] and m["entry"] == "now"
    assert C.main(["check-config", "--config", str(DEPLOY / "combo.short5.json")]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "준비됨"


def test_unit_and_install_never_start_it():
    unit = (DEPLOY / "paperbot-combo-short5.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.combo run --config /etc/paperbot/combo-short5.json" in unit
    assert "ReadWritePaths=/var/lib/paperbot/combo\n" in unit
    inst = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert ('install -m 644 "$APP/deploy/paperbot-combo-short5.service" /etc/systemd/system/paperbot-combo-short5.service'
            in inst)
    assert "enable --now paperbot-combo-short5" not in inst and "start paperbot-combo-short5" not in inst
    assert 'UNITS="$UNITS paperbot-combo-short5"' in inst                # stopped for the code swap, started again
    assert "combo/short5" in (DEPLOY / "paperbot-backup.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the switch
def test_dry_run_writes_nothing_and_lists_the_changes(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    before = Path(cfg).read_text()
    rc = SS.main(["--exec", "bybit", "--balance", "150", "--config", cfg], active=lambda u: False,
                 wallet_of=lambda: 1000.0)
    out = capsys.readouterr().out
    assert rc == 0 and Path(cfg).read_text() == before and not list(tmp_path.glob("*.before-short5-*"))
    for k in ("paper_db", "ladder", "signal_light_n", "equity_floor_frac", "budget_usd", "qty_scale"):
        assert k in out
    assert "보여 주기만" in out and "(주의)" not in out


@pytest.mark.parametrize("ex,name", [("bybit", "executor.live-bybit.json"), ("wooxpro", "executor.live-wooxpro.json")])
def test_write_moves_the_executor_and_keeps_everything_else(tmp_path, ex, name):
    cfg = _exec(tmp_path, name)
    os.chmod(cfg, 0o640)
    old = json.loads(Path(cfg).read_text())
    db = _paper(tmp_path, wallet=1250.0)
    rc = SS.main(["--exec", ex, "--balance", "125", "--config", cfg, "--write"], active=lambda u: False,
                 wallet_of=lambda: SS.paper_wallet(db))
    assert rc == 0
    new = json.loads(Path(cfg).read_text())
    assert new["paper_db"] == "/var/lib/paperbot/combo/short5.db"
    assert new["ladder"] == {"first_lock": 0.1, "trigger_gap": 0.02, "step": 0.05}
    assert new["signal_light_n"] == 20 and new["signal_light_min_win"] == 0.9 and new["equity_floor_frac"] == 0.7
    assert new["risk"]["max_loss_frac"] == 0.35 and new["budget_usd"] == 125 and new["qty_scale"] == 0.1
    for k in set(old) - {"paper_db", "ladder", "signal_light_n", "signal_light_min_win", "equity_floor_frac",
                         "budget_usd", "qty_scale", "risk"}:
        assert new[k] == old[k], k
    assert {k: v for k, v in new["risk"].items() if k != "max_loss_frac"} == \
        {k: v for k, v in old["risk"].items() if k != "max_loss_frac"}
    assert oct(os.stat(cfg).st_mode & 0o777) == oct(0o640)
    assert ExecConfig.from_dict(new).problems() == []
    backups = list(tmp_path.glob("executor.json.before-short5-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == old
    # and back
    assert SS.main(["--exec", ex, "--back", "--config", cfg, "--write"], active=lambda u: False) == 0
    assert json.loads(Path(cfg).read_text()) == old


def test_warnings_for_the_size_cap_and_another_exchange(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    assert SS.main(["--exec", "bybit", "--balance", "800", "--config", cfg], active=lambda u: False,
                   wallet_of=lambda: 1000.0) == 0
    out = capsys.readouterr().out
    assert "(주의) 잔고 $800.00의 BTC 포지션은 약 $12,800" in out and "$10,000" in out      # 800 x 40 % x 40x
    w = _exec(tmp_path, "executor.live-wooxpro.json")
    assert SS.main(["--exec", "wooxpro", "--balance", "100", "--config", w], active=lambda u: False,
                   wallet_of=lambda: 1000.0) == 0
    assert "바이비트로 돌리는 것을 권합니다" in capsys.readouterr().out


def test_refusals(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    before = Path(cfg).read_text()
    # the executor runs: nothing written
    assert SS.main(["--exec", "bybit", "--balance", "100", "--config", cfg, "--write"], active=lambda u: True,
                   wallet_of=lambda: 1000.0) == 1
    assert "paperbot-executor" in capsys.readouterr().out
    # the other exchange's file
    assert SS.main(["--exec", "wooxpro", "--balance", "100", "--config", cfg, "--write"], active=lambda u: False,
                   wallet_of=lambda: 1000.0) == 1
    assert "거래소는 'bybit'" in capsys.readouterr().out
    # no paper bot record yet
    assert SS.main(["--exec", "bybit", "--balance", "100", "--config", cfg, "--write"], active=lambda u: False,
                   wallet_of=lambda: SS.paper_wallet(str(tmp_path / "missing.db"))) == 1
    assert "paperbot-combo-short5" in capsys.readouterr().out
    # no balance
    assert SS.main(["--exec", "bybit", "--config", cfg], active=lambda u: False, wallet_of=lambda: 1000.0) == 1
    # nothing to go back to
    assert SS.main(["--exec", "bybit", "--back", "--config", cfg], active=lambda u: False) == 1
    assert Path(cfg).read_text() == before


def test_the_repository_template_is_what_the_switch_writes(capsys):
    cur = (DEPLOY / "executor.live-bybit.json").read_text()
    new, _w = SS.plan_exec(cur, "bybit", 100.0, 1000.0)
    assert json.loads(new) == json.loads((DEPLOY / "executor.live-bybit-short5.json").read_text())
    E.main(["check-config", "--config", str(DEPLOY / "executor.live-bybit-short5.json")])
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1] == "준비됨"
    assert "신호등: 켜짐 - paper 최근 20번 중 90% 이상 이겼을 때만 진입을 따라감" in lines
    assert any(x.startswith("잔고 바닥: 켜짐 - 잔고가 시작 금액(처음 돌 때 기록)의 70%") for x in lines)


def test_the_morning_check_names_its_unit():
    from paperbot import livecheck as LC
    assert LC.unit_of("/var/lib/paperbot/combo/short5.db") == "paperbot-combo-short5"
    assert "sudo systemctl status paperbot-combo-short5" in LC.paper_unit_todo("/var/lib/paperbot/combo/short5.db")
