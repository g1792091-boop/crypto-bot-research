"""deploy/candleague: the installer's own code list is enough to run the league (copied alone into an empty folder,
the selfcheck's imports work there), the units keep the guest limits and the sandbox, the script parses."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "deploy", "candleague")
SCRIPT = os.path.join(KIT, "install_candleague.sh")
SIX = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]


def _code_paths() -> list[str]:
    m = re.search(r'CODE_PATHS="(.*?)"', open(SCRIPT).read(), re.S)
    return m.group(1).replace("\\\n", " ").split()


def test_script_parses():
    subprocess.run(["bash", "-n", SCRIPT], check=True)


def test_the_code_list_alone_runs_the_league(tmp_path):
    app = tmp_path / "app"
    for p in _code_paths():
        src = os.path.join(ROOT, p)
        if p == "research/fullgrid/exchange.json" and not os.path.exists(src):
            continue                                      # tonight's file; a stand-in below
        dst = app / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    ex = app / "research" / "fullgrid" / "exchange.json"
    if not ex.exists():
        tier = {"bracket": 1, "initialLeverage": 125, "notionalCap": 1e9, "notionalFloor": 0, "maintMarginRatio": 0.004,
                "cum": 0.0}
        ex.write_text(json.dumps({"fetched_utc": "x", "brackets": [{"symbol": s, "brackets": [tier]} for s in SIX],
                                  "specs": {s: {"qty_step": 0.001, "min_notional": 5.0} for s in SIX}}))
    code = ("from paperbot import sweepsig; sweepsig.lib()\n"
            "from candleague import candidates, dash, league, notify, runner\n"
            "from paperbot.config import V3_SYMBOLS\n"
            "runner.load_exchange(runner.EXCHANGE_FILE, V3_SYMBOLS)\n"
            f"assert runner.EXCHANGE_FILE.startswith({str(app)!r})\n"
            "import paperbot, candleague\n"
            f"assert paperbot.__file__.startswith({str(app)!r}) and candleague.__file__.startswith({str(app)!r})\n"
            "print(len(candidates.ds_defs().DEFS), 'ds')\n"
            "print(len(candidates.params_of('core', 'S2_ST_ROC')), 'core')\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, "-c", code], cwd=app, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "44 ds" in r.stdout and "3 core" in r.stdout


def test_units_keep_the_guest_limits_and_sandbox():
    live = open(os.path.join(KIT, "candleague-live.service")).read()
    dash = open(os.path.join(KIT, "candleague-dash.service")).read()
    for k in ("User=candleague", "CPUQuota=30%", "MemoryMax=1300M", "Nice=10", "ProtectSystem=strict",
              "ReadWritePaths=/var/lib/candleague", "-/etc/paperbot", "-/var/lib/demobot",
              "UnsetEnvironment=CANDLEAGUE_DASH_PASSWORD_HASH CANDLEAGUE_DASH_SECRET",
              "ExecStart=/opt/candleague/venv/bin/python -m candleague run"):
        assert k in live, k
    for k in ("MemoryMax=300M", "ReadOnlyPaths=/var/lib/candleague", "UnsetEnvironment=CANDLEAGUE_TG_TOKEN",
              "ExecStart=/opt/candleague/venv/bin/python -m candleague.dash"):
        assert k in dash, k
    env = open(os.path.join(KIT, "candleague.env.example")).read()
    assert re.findall(r"^CANDLEAGUE_[A-Z_]+=(.*)$", env, re.M) == ["", "", "", "", "", "8091", "0"]   # no values
