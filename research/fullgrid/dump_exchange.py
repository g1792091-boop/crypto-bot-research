"""Print the six coins' leverage brackets and order-size rules as one JSON line (research/fullgrid/exchange.json).

Run ON THE PAPER BOT SERVER, where the paper bot's read-only key already is (/etc/paperbot/live.env). The key is read
from the environment and never printed; the output holds only Binance's public trading rules (the same table the
"Leverage & Margin" page shows), so it can be pasted into the chat and committed:

    cd /root/crypto-bot-research && git pull && sudo bash -c 'set -a; . /etc/paperbot/live.env; set +a; \
        /opt/paperbot/venv/bin/python research/fullgrid/dump_exchange.py'

The full-grid study needs it because the paper engine sizes with the real brackets (a 50x entry needs a bracket that
allows 50x at that notional) and liquidates at the bracket's maintenance margin. The rented compute server never
holds a key.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from paperbot.config import V3_SYMBOLS  # noqa: E402

KEEP = ("bracket", "initialLeverage", "notionalCap", "notionalFloor", "maintMarginRatio", "cum")


def main() -> int:
    from paperbot.live import _rest
    rest = _rest()
    if not (rest.api_key and rest.api_secret):
        print("BINANCE_API_KEY / BINANCE_API_SECRET가 없습니다: 위 명령을 그대로(set -a; . /etc/paperbot/live.env ...) "
              "붙여 넣었는지 확인하세요.", file=sys.stderr)
        return 2
    br = [{"symbol": p["symbol"], "brackets": [{k: b[k] for k in KEEP if k in b} for b in p["brackets"]]}
          for p in rest.leverage_brackets() if p["symbol"] in V3_SYMBOLS]
    specs = rest.exchange_info(V3_SYMBOLS)
    missing = set(V3_SYMBOLS) - {p["symbol"] for p in br}
    if missing or set(V3_SYMBOLS) - set(specs):
        print(f"빠진 코인: {sorted(missing | (set(V3_SYMBOLS) - set(specs)))}", file=sys.stderr)
        return 2
    doc = {"fetched_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "brackets": sorted(br, key=lambda p: V3_SYMBOLS.index(p["symbol"])),
           "specs": {s: {"qty_step": specs[s]["qty_step"], "min_notional": specs[s]["min_notional"]} for s in V3_SYMBOLS}}
    print(json.dumps(doc, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
