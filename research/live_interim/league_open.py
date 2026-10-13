"""Candidate league: every open position now, how long it has been held and how far its take-profit is (read-only; for the owners to paste).

    python3 research/live_interim/league_open.py [--snap /var/lib/candleague/snap/league.json] [--no-prices]

Reads the league's snapshot file (the one the dashboard shows; nothing is written) and, unless --no-prices, the six coins' last prices from
Binance's public ticker. For each open position: account, strategy, bar, side, leverage, held hours, price move since entry, the net ROE now
(leverage x move minus the round-trip cost 0.14% x leverage), the distance to the stop and to the take-profit in price % and in ROE, and the
lock the owners' ladder (13% -> 10%, 20% -> 15%, 25% -> 20%, 30% -> 25% ...) would hold now if the best ROE so far were the ROE now (a floor:
the best so far can only be higher). DeepSeek accounts show hours and distances only, no money. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request

RT = 0.0014
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def ladder_lock(best: float):
    if best < 0.13:
        return None
    if best < 0.20:
        return 0.10
    return round(0.15 + 0.05 * math.floor((best - 0.20) / 0.05 + 1e-9), 10)


def prices() -> dict:
    out = {}
    for s in SYMBOLS:
        try:
            with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={s}", timeout=10) as r:
                out[s] = float(json.load(r)["price"])
        except Exception:  # noqa: BLE001  a missing price only blanks that coin's columns
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", default="/var/lib/candleague/snap/league.json")
    ap.add_argument("--no-prices", action="store_true")
    a = ap.parse_args()
    doc = json.load(open(a.snap))
    now = int(time.time() * 1000)
    px = {} if a.no_prices else prices()
    rows = []
    for acct in doc.get("accounts", []):
        o = acct.get("open")
        if not o:
            continue
        side, entry = int(o["side"]), float(o["entry"])
        lev = o.get("lev")
        last = px.get(o["symbol"])
        held = (now - int(o["since"])) / 3.6e6 if o.get("since") else None
        move = side * (last / entry - 1.0) if last else None
        roe = lev * (move - RT) if (lev and move is not None) else None
        stop_d = side * (float(o["stop"]) / entry - 1.0) if o.get("stop") is not None else None
        tp_d = side * (float(o["tp"]) / entry - 1.0) if o.get("tp") is not None else None
        ds = acct.get("kind") == "ds"
        rows.append((held or 0, acct, o, lev, held, move, roe, stop_d, tp_d, ds))
    rows.sort(key=lambda r: -r[0])
    print(f"열린 포지션 {len(rows)}개 (스냅샷 {time.strftime('%m-%d %H:%M', time.gmtime(doc.get('generated_ms', 0) / 1000))} UTC 기준, 지금 시각과 차이는 보유 시간에 반영)")
    print("계좌 | 매매법 | 봉 | 방향 | 배수 | 보유(시간) | 가격 변동 | 지금 ROE | 손절까지 | 익절까지(가격 %, ROE) | 계단이 지켜 줄 최소 수익")
    held_all, far = [], 0
    for _h, acct, o, lev, held, move, roe, stop_d, tp_d, ds in rows:
        side = "롱" if int(o["side"]) > 0 else "숏"
        tp_txt = "—"
        if tp_d is not None:
            tp_txt = f"{abs(tp_d) * 100:.1f}%" + (f", ROE {abs(tp_d) * lev * 100:.0f}%" if lev else "")
            if lev and abs(tp_d) * lev > 0.8:
                far += 1
        lock = ladder_lock(roe) if roe is not None else None
        name = ("[딥시크] " if ds else "") + str(acct.get("name"))
        print(f"{acct['id']} | {name} | {acct.get('tf')} | {side} | {lev if lev else '—'} | {held:.1f} | "
              f"{'—' if move is None else f'{move * 100:+.2f}%'} | {'—' if roe is None else f'{roe * 100:+.0f}%'} | "
              f"{'—' if stop_d is None else f'{abs(stop_d) * 100:.1f}% (ROE {abs(stop_d) * lev * 100:.0f}%)' if lev else '—'} | {tp_txt} | "
              f"{'—' if lock is None else f'+{lock * 100:.0f}%'}")
        if held is not None:
            held_all.append(held)
    if held_all:
        held_all.sort()
        med = held_all[len(held_all) // 2]
        print(f"\n보유 시간 중앙값 {med:.1f}시간 · 12시간 넘게 든 포지션 {sum(1 for h in held_all if h > 12)}개 · 24시간 넘게 {sum(1 for h in held_all if h > 24)}개")
        print(f"익절까지 ROE로 +80% 넘게 남은 포지션 {far}개 (익절가가 먼 것)")
    if not px and not a.no_prices:
        print("가격을 못 받아 와서 ROE는 비어 있습니다 (서버에서 바이낸스에 접속이 안 될 때).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
