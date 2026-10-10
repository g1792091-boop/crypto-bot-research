"""Print the six coins' leverage brackets and order-size rules as one JSON line (research/fullgrid/exchange.json).

Run ON THE PAPER BOT SERVER, where the paper bot's read-only key already is (/etc/paperbot/live.env). The key is read
from the environment and never printed; the output holds only Binance's public trading rules (the same table the
"Leverage & Margin" page shows), so it can be pasted into the chat and committed:

    cd /root/crypto-bot-research && git pull && sudo bash -c 'set -a; . /etc/paperbot/live.env; set +a; \
        /opt/paperbot/venv/bin/python research/fullgrid/dump_exchange.py'

The full-grid study needs it because the paper engine sizes with the real brackets (a 50x entry needs a bracket that
allows 50x at that notional) and liquidates at the bracket's maintenance margin. The rented compute server never
holds a key.

"extra" (owners 2026-10-10: a second study run checks the picks on six more coins; research only, the bots keep their
six): the same table for EXTRA, each bracket as [bracket, initialLeverage, notionalCap, notionalFloor,
maintMarginRatio, cum] to keep the line short. Best effort: a coin it cannot get is left out with a note on stderr,
and the six coins above are printed exactly as before.
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
EXTRA = ("XRPUSDT", "BNBUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT")


def extra_part(rest, payload: list) -> dict:
    """The EXTRA coins' brackets (compact rows) and order-size rules; coins it cannot get are left out."""
    rows = {p["symbol"]: [[b[k] for k in KEEP] for b in p["brackets"]] for p in payload
            if p["symbol"] in EXTRA and all(k in b for b in p["brackets"] for k in KEEP)}
    specs = {}
    for s in [s for s in EXTRA if s in rows]:
        try:
            sp = rest.exchange_info([s])[s]
            specs[s] = {"qty_step": sp["qty_step"], "min_notional": sp["min_notional"]}
        except Exception:  # noqa: BLE001  research only: never stop the six coins' table
            pass
    got = [s for s in EXTRA if s in rows and s in specs]
    if len(got) < len(EXTRA):
        print(f"(참고) 연구용 추가 코인 중 못 받은 것: {sorted(set(EXTRA) - set(got))} - 오늘 계산과는 상관없습니다",
              file=sys.stderr)
    return {"brackets": {s: rows[s] for s in got}, "specs": {s: specs[s] for s in got}}


def main() -> int:
    from paperbot.live import _rest
    rest = _rest()
    if not (rest.api_key and rest.api_secret):
        print("BINANCE_API_KEY / BINANCE_API_SECRET가 없습니다: 위 명령을 그대로(set -a; . /etc/paperbot/live.env ...) "
              "붙여 넣었는지 확인하세요.", file=sys.stderr)
        return 2
    payload = rest.leverage_brackets()
    br = [{"symbol": p["symbol"], "brackets": [{k: b[k] for k in KEEP if k in b} for b in p["brackets"]]}
          for p in payload if p["symbol"] in V3_SYMBOLS]
    specs = rest.exchange_info(V3_SYMBOLS)
    missing = set(V3_SYMBOLS) - {p["symbol"] for p in br}
    if missing or set(V3_SYMBOLS) - set(specs):
        print(f"빠진 코인: {sorted(missing | (set(V3_SYMBOLS) - set(specs)))}", file=sys.stderr)
        return 2
    doc = {"fetched_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "brackets": sorted(br, key=lambda p: V3_SYMBOLS.index(p["symbol"])),
           "specs": {s: {"qty_step": specs[s]["qty_step"], "min_notional": specs[s]["min_notional"]} for s in V3_SYMBOLS}}
    try:
        extra = extra_part(rest, payload)
        if extra["brackets"]:
            doc["extra"] = extra
    except Exception as exc:  # noqa: BLE001  research only: never stop the six coins' table
        print(f"(참고) 연구용 추가 코인 표를 못 받았습니다({type(exc).__name__}) - 오늘 계산과는 상관없습니다", file=sys.stderr)
    print(json.dumps(doc, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
