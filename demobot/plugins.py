"""Private strategy plug-ins (CONTRACT 7.2). The public repository only has this loader; plug-in files live on the
server in DEMOBOT_PLUGINS (default /etc/demobot/plugins, root-owned) and are never committed.

A plug-in module defines:
    KEY = "p1"                         # [a-z0-9]{1,12}
    ACCOUNTS = [{"variant": "a", "name": "...", "rule_ko": "...", "tf": "15m"}, ...]
    def trades(variant, bars15, start_ms, now_ms) -> list[dict]
bars15: {coin: {"ts","o","h","l","c","v"}} (15m arrays of the engine). Each trade dict:
    coin, side (+1/-1), signal_ms, entry_ms, entry (price), stop (price), atr (or None), maker_entry (bool),
    legs: [(fraction, exit_ms | None, exit_price | None, kind)], kind in "tp", "sl", "be", "time";
    setting_ko, exit_ko (Korean labels for the trade list)
Legs with exit_ms None are still open. Prices are raw (the engine applies slippage and fees).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
from typing import Optional

KEY_RE = re.compile(r"^[a-z0-9]{1,12}$")
VAR_RE = re.compile(r"^[a-z0-9_]{1,12}$")


def plugin_dir() -> str:
    return os.environ.get("DEMOBOT_PLUGINS", "/etc/demobot/plugins")


_CACHE: dict = {}


def load(path: Optional[str] = None, log=print) -> list:
    """Plug-in modules (sorted by file name). A file that fails to load or to validate is skipped and logged."""
    d = path or plugin_dir()
    try:
        names = sorted(f for f in os.listdir(d) if f.endswith(".py") and not f.startswith("_"))
    except OSError:
        return []
    out = []
    for fn in names:
        p = os.path.join(d, fn)
        try:
            with open(p, "rb") as fh:
                data = fh.read()
            sha = hashlib.sha256(data).hexdigest()
            key = (p, sha)
            if key not in _CACHE:
                spec = importlib.util.spec_from_file_location(f"_demobot_plugin_{fn[:-3]}", p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                exec(compile(data, p, "exec"), mod.__dict__)
                if not KEY_RE.match(str(getattr(mod, "KEY", ""))):
                    raise ValueError("bad KEY")
                accs = list(getattr(mod, "ACCOUNTS", []))
                for a in accs:
                    if not VAR_RE.match(str(a.get("variant", ""))) or a.get("tf", "15m") not in ("15m", "30m"):
                        raise ValueError("bad ACCOUNTS entry")
                if not callable(getattr(mod, "trades", None)):
                    raise ValueError("no trades()")
                mod.SHA256 = sha
                _CACHE[key] = mod
            out.append(_CACHE[key])
        except Exception as exc:          # a broken plug-in never stops the engine
            log("plugin skipped:", fn, type(exc).__name__, str(exc)[:200])
    return out


def account_id(mod, variant: str) -> str:
    return f"pv-{mod.KEY}-{variant}".replace("_", "-")
