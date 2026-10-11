"""Leverage brackets and order-size rules of the hunt's 30 coins (PREREG_HUNT 7.3, section 18 Q3; WIDE R18).

Two steps, both without any price or outcome:

1. ``dump``: run ON THE RULE BOT (PAPER BOT) SERVER, where the read-only key already is (/etc/paperbot/live.env). The
   key is read from the environment and never printed; the output is one JSON line of Binance's public trading rules
   (the "Leverage & Margin" table and exchangeInfo filters) for the coins of research/hunt/universe30.json that are
   still listed, so it can be pasted into the chat:

       cd /root/crypto-bot-research && git pull && sudo bash -c 'set -a; . /etc/paperbot/live.env; set +a; \
           /opt/paperbot/venv/bin/python research/hunt/dump_exchange30.py'

2. ``build --from FILE``: here, before the pin. Writes research/hunt/exchange30.json in the format of
   research/fullgrid/exchange.json (``brackets``, ``specs``; what hunt.load_brackets reads) plus a per-coin ``source``
   flag. A coin uses the brackets of FILE when FILE has them, except the coins research/hunt/data_manifest.json shows
   stopping inside the data (PREREG_HUNT 3: the eight coins that stopped trading always use the fallback); every
   other coin is left out of ``brackets`` and so uses hunt.FALLBACK_BRACKETS (flagged ``fallback``). FILE is the
   pasted dump line, or research/fullgrid/exchange.json (the six current coins, fetched 2026-10-10) until the dump
   arrives:

       python research/hunt/dump_exchange30.py build --from research/fullgrid/exchange.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UNIVERSE = os.path.join(HERE, "universe30.json")
DATA_MANIFEST = os.path.join(HERE, "data_manifest.json")
OUT = os.path.join(HERE, "exchange30.json")
KEEP = ("bracket", "initialLeverage", "notionalCap", "notionalFloor", "maintMarginRatio", "cum")
# PREREG_HUNT 7.3, as hunt.FALLBACK_BRACKETS (build checks they are equal): (floor, cap, leverage, mmr)
FALLBACK = ((0.0, 25_000.0, 20, 0.025), (25_000.0, 100_000.0, 10, 0.05), (100_000.0, 250_000.0, 5, 0.10),
            (250_000.0, 1_000_000.0, 3, 0.125), (1_000_000.0, math.inf, 1, 0.25))
FALLBACK_MIN_NOTIONAL = 5.0


def universe() -> list:
    if not os.path.exists(UNIVERSE):
        raise SystemExit("research/hunt/universe30.json가 없습니다: git pull을 먼저 하세요.")
    with open(UNIVERSE) as fh:
        return list(json.load(fh)["symbols"])


# ------------------------------------------------------------------ 1. dump (rule bot server)
def _filters(s: dict) -> dict:
    f = {x["filterType"]: x for x in s.get("filters", [])}
    lot, mlot = f.get("LOT_SIZE", {}), f.get("MARKET_LOT_SIZE", {})
    return {"status": s.get("status"), "contract_type": s.get("contractType"),
            "qty_step": float(mlot.get("stepSize") or lot.get("stepSize")),
            "min_notional": float(f.get("MIN_NOTIONAL", {}).get("notional", 0.0)),
            "lot_step": float(lot["stepSize"]) if "stepSize" in lot else None,
            "lot_min_qty": float(lot["minQty"]) if "minQty" in lot else None,
            "lot_max_qty": float(lot["maxQty"]) if "maxQty" in lot else None,
            "market_lot_step": float(mlot["stepSize"]) if "stepSize" in mlot else None,
            "market_lot_max_qty": float(mlot["maxQty"]) if "maxQty" in mlot else None}


def cmd_dump() -> int:
    sys.path.insert(0, ROOT)
    from paperbot.live import _rest
    syms = universe()
    rest = _rest()
    if not (rest.api_key and rest.api_secret):
        print("BINANCE_API_KEY / BINANCE_API_SECRET가 없습니다: 위 명령을 그대로(set -a; . /etc/paperbot/live.env ...) "
              "붙여 넣었는지 확인하세요.", file=sys.stderr)
        return 2
    br = {p["symbol"]: [{k: b[k] for k in KEEP if k in b} for b in p["brackets"]]
          for p in rest.leverage_brackets() if p["symbol"] in syms}
    info = {s["symbol"]: s for s in rest._get("/fapi/v1/exchangeInfo")["symbols"] if s["symbol"] in syms}
    specs = {s: _filters(info[s]) for s in syms if s in info}
    doc = {"fetched_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "brackets": [{"symbol": s, "brackets": br[s]} for s in syms if s in br],
           "specs": specs,
           "not_in_brackets": [s for s in syms if s not in br],
           "not_in_exchange_info": [s for s in syms if s not in info]}
    print(f"구간표 {len(doc['brackets'])}개, 주문 규칙 {len(specs)}개 (상장 폐지된 코인은 빠지는 것이 정상)", file=sys.stderr)
    print(json.dumps(doc, separators=(",", ":")))
    return 0


# ------------------------------------------------------------------ 2. build (here, before the pin)
def _check_brackets(sym: str, bl: list) -> list:
    bl = sorted(bl, key=lambda b: float(b["notionalFloor"]))
    if not bl or float(bl[0]["notionalFloor"]) != 0.0:
        raise SystemExit(f"{sym}: the brackets do not start at notional 0")
    for a, b in zip(bl, bl[1:]):
        if float(a["notionalCap"]) != float(b["notionalFloor"]):
            raise SystemExit(f"{sym}: bracket {a.get('bracket')} cap differs from the next floor")
        if int(b["initialLeverage"]) > int(a["initialLeverage"]):
            raise SystemExit(f"{sym}: leverage rises with notional")
    for b in bl:
        for k in ("notionalFloor", "notionalCap", "initialLeverage", "maintMarginRatio"):
            if k not in b:
                raise SystemExit(f"{sym}: bracket without {k}")
    return bl


def stopped_coins() -> dict:
    """{symbol: last bar with volume} of the coins data_manifest.json shows stopping inside the data."""
    if not os.path.exists(DATA_MANIFEST):
        raise SystemExit("research/hunt/data_manifest.json missing: run hunt datapin first")
    with open(DATA_MANIFEST) as fh:
        man = json.load(fh)["manifest"]
    return {r["symbol"]: r.get("last_nonzero_volume_bar") for r in man["symbols"] if not r.get("traded_to_range_end")}


def cmd_build(src: str, out: str = OUT) -> int:
    sys.path.insert(0, ROOT)
    from research.hunt import hunt as H
    if tuple(H.FALLBACK_BRACKETS) != FALLBACK or H.FALLBACK_MIN_NOTIONAL != FALLBACK_MIN_NOTIONAL:
        raise SystemExit("the fallback table here differs from research/hunt/hunt.py")
    with open(src) as fh:
        dump = json.load(fh)
    syms = universe()
    stopped = stopped_coins()
    brs = {p["symbol"]: p["brackets"] for p in dump.get("brackets", [])}
    specs_in = dump.get("specs", {})
    src_rel = os.path.relpath(os.path.abspath(src), ROOT)
    fetched = dump.get("fetched_utc")
    brackets, specs, source = [], {}, {}
    for s in syms:
        if s in stopped:
            source[s] = f"fallback: stopped trading inside the data (last bar with volume {stopped[s]} UTC)"
        elif s in brs:
            brackets.append({"symbol": s, "brackets": _check_brackets(s, brs[s])})
            if s in specs_in:
                specs[s] = specs_in[s]
            source[s] = f"exchange: {src_rel} (fetched {fetched} UTC)"
        else:
            source[s] = f"fallback: not in {src_rel}"
    n_ex = sum(1 for v in source.values() if v.startswith("exchange"))
    doc = {"what": "PREREG_HUNT 7.3 leverage brackets and minimum notional of the 30 coins (format of "
                   "research/fullgrid/exchange.json); a coin missing from 'brackets' uses the fallback table",
           "fetched_utc": fetched,
           "built_from": src_rel,
           "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "counts": {"exchange": n_ex, "fallback": len(syms) - n_ex, "fallback_stopped": len(stopped)},
           "source": source,
           "fallback": {"brackets": [{"notionalFloor": fl, "notionalCap": (None if math.isinf(cap) else cap),
                                      "initialLeverage": lev, "maintMarginRatio": mmr}
                                     for fl, cap, lev, mmr in FALLBACK],
                        "min_notional": FALLBACK_MIN_NOTIONAL,
                        "note": "the engine's table is research/hunt/hunt.py FALLBACK_BRACKETS (an approximation, "
                                "not a verified lower bound; PREREG_HUNT 7.3); listed here for reading only"},
           "brackets": brackets, "specs": specs}
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    print(f"{os.path.relpath(out, ROOT)}: exchange {n_ex}, fallback {len(syms) - n_ex} "
          f"(of which stopped {len(stopped)})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", default="dump", choices=("dump", "build"))
    ap.add_argument("--from", dest="src", default=None, help="build: the dump line saved as a file (or "
                                                               "research/fullgrid/exchange.json)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        if not a.src:
            ap.error("build needs --from FILE")
        return cmd_build(a.src, a.out)
    return cmd_dump()


if __name__ == "__main__":
    sys.exit(main())
