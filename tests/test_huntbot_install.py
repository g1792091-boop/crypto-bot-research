"""deploy/huntbot: the scripts parse, the units run as the huntbot user in a sandbox with only /var/lib/huntbot
writable, the dashboard cannot read the private folder or the Telegram token, the env template holds no value, and
the code copy covers every module the hunt's entry definitions load (the install's selfcheck runs them for real)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
D = os.path.join(ROOT, "deploy", "huntbot")


def _read(name):
    with open(os.path.join(D, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("name", ["install_huntbot.sh", "setup_env.sh", "firewall.sh"])
def test_scripts_parse(name):
    r = subprocess.run(["bash", "-n", os.path.join(D, name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    sc = shutil.which("shellcheck")
    if sc:
        r = subprocess.run([sc, os.path.join(D, name)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout[-2000:]


@pytest.mark.parametrize("unit", ["huntbot-feed.service", "huntbot-run.service", "huntbot-dash.service"])
def test_units_sandboxed(unit):
    u = _read(unit)
    assert "User=huntbot" in u and "NoNewPrivileges=yes" in u and "ProtectSystem=strict" in u
    assert "EnvironmentFile=/etc/huntbot/huntbot.env" in u
    assert re.search(r"ExecStart=/opt/huntbot/venv/bin/python -m huntbot (feed run|run|dash)$", u, re.M)
    if unit == "huntbot-dash.service":
        assert "ReadOnlyPaths=/var/lib/huntbot" in u and "InaccessiblePaths=-/var/lib/huntbot/private" in u
        assert "UnsetEnvironment=HUNTBOT_TG_TOKEN HUNTBOT_TG_CHAT" in u
        assert "ReadWritePaths" not in u
    else:
        assert "ReadWritePaths=/var/lib/huntbot" in u
        assert "HUNTBOT_DASH_PASSWORD_HASH" in u and "UnsetEnvironment" in u
    if unit == "huntbot-run.service":
        assert "NUMBA_CACHE_DIR=/var/lib/huntbot/numba" in u


def test_env_template_has_no_values_and_no_exchange_key():
    env = _read("huntbot.env.example")
    for k in ("HUNTBOT_TG_TOKEN", "HUNTBOT_TG_CHAT", "HUNTBOT_DASH_PASSWORD_HASH", "HUNTBOT_DASH_SECRET",
              "HUNTBOT_DASH_HOST"):
        assert re.search(rf"^{k}=$", env, re.M), k
    assert "BINANCE" not in env and "API_KEY" not in env and "SECRET_KEY" not in env


def test_install_copies_every_code_path_the_engine_loads():
    sh = _read("install_huntbot.sh")
    m = re.search(r'CODE_PATHS="([^"]+)"', sh, re.S)
    paths = m.group(1).replace("\\\n", " ").split()
    for p in paths:
        assert os.path.exists(os.path.join(ROOT, p)), p
    # what the wide entries load (research/hunt/entries_wide.py, the full grid's run.py, the famous rules, the label)
    for need in ("huntbot", "research/hunt", "research/fullgrid", "research/entry_study", "research/deepseek200",
                 "research/library", "research/search", "research/famous", "third_party/sweep", "paperbot"):
        assert need in paths, need
    assert 'git -C "$REPO_DIR" archive --format=tar "$COMMIT"' in sh            # committed code only, pinned
    assert "numpy==2.0.2" in sh and "pandas==2.3.3" in sh and "numba==0.60.0" in sh   # the backtest's versions
    assert "engine_api_problems" in sh and "signal_path_files" in sh and "fullgrid_pins" in sh


def test_loaded_signal_modules_are_inside_the_copied_paths():
    """Every repository module this test process has loaded from the hunt's signal path lies under a copied path."""
    from research.hunt import entries_wide as EW
    EW.systems()
    sh = _read("install_huntbot.sh")
    paths = re.search(r'CODE_PATHS="([^"]+)"', sh, re.S).group(1).replace("\\\n", " ").split()
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None) or ""
        if not f.endswith(".py"):
            continue
        rel = os.path.relpath(os.path.abspath(f), ROOT)
        if rel.startswith(("..", "tests", "huntbot")) or "site-packages" in f:
            continue
        if rel.startswith(("research/", "third_party/", "paperbot/")):
            assert any(rel == p or rel.startswith(p + "/") for p in paths), rel


def test_docs_name_the_steps():
    doc = open(os.path.join(ROOT, "docs", "huntbot-ko.md"), encoding="utf-8").read()
    for s in ("hunt-judge", "Tokyo", "Ubuntu 24.04", "install_huntbot.sh", "setup_env.sh", "8092", "D11", "lineup.json",
              "systemctl stop", "COMMIT_HERE"):
        assert s in doc, s
