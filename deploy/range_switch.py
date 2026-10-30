#!/usr/bin/env python3
"""Move the WOO X Pro executor from the 추세판단 봇 to the '레인지 봇' paper bot (owners 10/26: "레인지봇을 추세 봇 woo x pro
거래소로 ... 원래 있던 추세봇 woo x pro 는 없애고", "진행해줘"; docs/range-bot-ko.md).

    python3 deploy/range_switch.py              shows what would change (nothing is written)
    python3 deploy/range_switch.py --write      changes it; the old copy stays as <file>.before-range-<time>
    python3 deploy/range_switch.py --back [--write]   back to the newest .before-range-<time> copy

``--exec``: wooxpro (the default: /etc/paperbot/executor-mexc.json, paperbot-executor-mexc), bybit
(/etc/paperbot/executor.json, paperbot-executor) or deepcoin (/etc/paperbot/executor-deepcoin.json,
paperbot-executor-deepcoin), should the owners ever move another one.

Refuses to write while that executor runs (stop it first, only while it holds no position: a running executor whose
paper has no such position closes it), while the 레인지 봇 paper bot has no record yet (start paperbot-combo-range first),
for a file of another exchange, and for an executor that does not follow the paper position (``entry_source`` "paper").

What changes in that executor's config (every other value stays: the keys, ``net_costs``, ``db``, the kill file; the
file keeps its owner and mode):
- ``paper_db`` -> /var/lib/paperbot/combo/range.db (account COMBO@mix there too)
- size: ``size_from`` "equity", ``margin_frac`` 0.4 (each entry's margin = 40 % of the live balance read then: money taken
  out or put in counts at the next entry, nothing to type), ``leverage_by_symbol`` BTC 40 / the rest 30,
  ``risk.max_leverage`` at least 40
- stop (owners 10-30, the ROC entry with its own stop): ``stop_from`` "ratio" (the paper's stop distance in % from its own
  fill: the range entry's net ROE -50 %, the ROC entry's 30m ATR x 3); ``stop_roe``, ``stop_net``, ``stop_scale`` removed
  (10-26 to 10-29: "roe" 0.5 net)
- take-profit (owners 10-30 "레인지도 woox pro1 순수익8% 방식으로"): ``ladder_from`` "own", ``ladder`` net ROE 10 % -> lock 8 %,
  then every 5 %, ``take_profit_roe`` null, ``ladder_basis`` "net" (its own fill, WOO X Pro's own 1m bars and costs)
  (10-26 to 10-29: one fixed take-profit at net ROE +10 %)
- ``signal_light_n`` 0 (no signal light), ``equity_floor_frac`` null (no balance floor: "파산당하면 파산 당한다는 마인드"),
  ``liq_guard`` true with ``liq_guard_mmr`` 0.005, ``macro_block_min`` 30
Nothing restarts here: the executor reads its config when it starts (check-config, preflight, then ``systemctl start``).
Standard library only (the server's python3, as root).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

EXECS = {"wooxpro": ("WOO X Pro", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc"),
         "bybit": ("바이비트", "/etc/paperbot/executor.json", "paperbot-executor"),
         "deepcoin": ("딥코인", "/etc/paperbot/executor-deepcoin.json", "paperbot-executor-deepcoin")}
RANGE_DB = "/var/lib/paperbot/combo/range.db"
ACCOUNT = "COMBO@mix"
MARGIN = 0.4
LEV = {"BTCUSDT": 40, "*": 30}
LADDER = {"first_lock": 0.08, "trigger_gap": 0.02, "step": 0.05}     # net ROE 10 % -> lock 8 %, then every 5 %
GONE = {"stop_roe": "stop_from \"ratio\"라 안 씀", "stop_net": "stop_from \"ratio\"라 안 씀",
        "stop_scale": "손절은 페이퍼 손절 거리 그대로"}
MMR = 0.005
MACRO_MIN = 30
SUFFIX = ".before-range-"
UNIT = "paperbot-combo-range"
GUIDE = "docs/range-bot-ko.md"


class Stop(Exception):
    """Why nothing is written (Korean)."""


def paper_ready(db: str = RANGE_DB) -> float:
    """The 레인지 봇 paper bot's COMBO@mix wallet now (its saved account state), read-only: the paper bot runs."""
    if not os.path.exists(db):
        raise Stop(f"레인지 봇 페이퍼 기록({db})이 아직 없습니다: 먼저 {UNIT}을 켜세요")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    except sqlite3.Error as exc:
        raise Stop(f"레인지 봇 페이퍼 기록을 못 읽음: {exc}") from exc
    finally:
        conn.close()
    try:
        w = float(json.loads(row[0])["engines"][ACCOUNT]["wallet"])
    except (TypeError, KeyError, ValueError) as exc:
        raise Stop("레인지 봇 페이퍼 계좌 상태가 아직 없습니다: 켠 뒤 1~2분 기다렸다가 다시") from exc
    if not w > 0:
        raise Stop(f"레인지 봇 페이퍼 지갑이 {w}입니다")
    return w


def plan_exec(current: str, exchange: str) -> tuple:
    """(new text, [words]). Refuses a config of another exchange (a mix-up of the files) or one that follows signals."""
    d = json.loads(current)
    if d.get("exchange") != exchange:
        raise Stop(f"이 파일의 거래소는 {d.get('exchange')!r}입니다(--exec {exchange}와 다름)")
    if (d.get("entry_source") or "paper") != "paper":
        raise Stop("entry_source가 \"paper\"가 아닌 실행기는 레인지 봇을 따라가지 않습니다")
    if (d.get("account") or ACCOUNT) != ACCOUNT:
        raise Stop(f"account가 {d.get('account')!r}입니다(레인지 봇 계좌는 {ACCOUNT})")
    want = {"paper_db": RANGE_DB, "size_from": "equity", "margin_frac": MARGIN, "leverage_by_symbol": LEV,
            "stop_from": "ratio", "ladder_from": "own", "ladder": LADDER,
            "take_profit_roe": None, "ladder_basis": "net", "signal_light_n": 0, "equity_floor_frac": None,
            "liq_guard": True, "liq_guard_mmr": MMR, "macro_block_min": MACRO_MIN}
    words = []
    for k, v in want.items():
        if d.get(k) != v or k not in d:
            if k in d or v is not None:
                words.append(f"{k}: {json.dumps(d.get(k), ensure_ascii=False)} → {json.dumps(v, ensure_ascii=False)}")
        d[k] = v
    for k, why in GONE.items():
        if k in d:
            words.append(f"{k}: {json.dumps(d.pop(k))} → 없앰({why})")
    risk = dict(d.get("risk") or {})
    if not (isinstance(risk.get("max_leverage"), (int, float)) and risk["max_leverage"] >= 40):
        words.append(f"risk.max_leverage: {risk.get('max_leverage')} → 40")
        risk["max_leverage"] = 40
    d["risk"] = risk
    words.append(f"(진입할 때마다 실거래 잔고의 {MARGIN:.0%}를 증거금으로, BTC 40배·나머지 30배. 손절은 페이퍼와 같은 거리"
                 "(레인지 신호 순ROE -50%, ROC 신호 30분 ATR × 3), 계단 익절 순ROE 10%에서 8% 잠금 뒤 5%씩, "
                 "모두 실거래 자기 체결가 기준)")
    cap = risk.get("max_notional_usd")
    if cap:
        words.append(f"(참고) 한 포지션 최대 ${float(cap):,.0f}(risk.max_notional_usd): 잔고가 ${float(cap) / (MARGIN * 40):,.0f}를 "
                     "넘으면 BTC 크기가 그 한도로 잘립니다")
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n", words


def unit_active(unit: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False)
    except FileNotFoundError:
        return False
    return r.returncode == 0


def newest_backup(path: str):
    got = sorted(glob.glob(path + SUFFIX + "*"))
    return got[-1] if got else None


def _write(path: str, text: str, stamp: str) -> str:
    backup = f"{path}{SUFFIX}{stamp}"
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as fh:          # in place: the file keeps its owner and mode
        fh.write(text)
    return backup


def main(argv=None, active=unit_active, ready=paper_ready) -> int:
    ap = argparse.ArgumentParser(description="WOO X Pro 실행기를 레인지 봇 페이퍼 봇으로 옮기기")
    ap.add_argument("--exec", default="wooxpro", choices=sorted(EXECS), dest="ex")
    ap.add_argument("--back", action="store_true", help="가장 최근 .before-range 사본으로 되돌리기")
    ap.add_argument("--write", action="store_true", help="실제로 바꾸기 (없으면 보여 주기만)")
    ap.add_argument("--config", default=None, help="실행기 설정 파일 (기본: 그 거래소의 파일)")
    a = ap.parse_args(argv)
    ko, path, unit = EXECS[a.ex]
    path = a.config or path
    try:
        if a.write and active(unit):
            raise Stop(f"{unit}이(가) 켜져 있습니다. 포지션이 없을 때 먼저 끄세요: sudo systemctl stop {unit}")
        if a.back:
            b = newest_backup(path)
            if b is None:
                raise Stop(f"{path}{SUFFIX}… 사본이 없습니다")
            print(f"{path} ({ko}): {b} 로 되돌림")
            if a.write:
                shutil.copyfile(b, path)                    # contents only: the file keeps its owner and mode
                print("  되돌렸습니다. 다음: check-config → sudo systemctl start " + unit)
            else:
                print("보여 주기만 했습니다. 되돌리려면 끝에 --write 를 붙여 다시 실행하세요.")
            return 0
        with open(path, encoding="utf-8") as fh:
            current = fh.read()
        wallet = ready()
        new, words = plan_exec(current, a.ex)
    except FileNotFoundError:
        print(f"{path} ({ko}): 파일 없음 - 멈춤")
        return 1
    except (OSError, ValueError, Stop) as exc:
        print(f"{path} ({ko}): 멈춤 - {exc}")
        return 1
    print(f"{path} ({ko}): 레인지 봇 페이퍼(지갑 ${wallet:,.2f})를 따라가도록")
    for w in words:
        print(f"  {w}")
    if a.write:
        print(f"  바꿈 · 예전 파일: {_write(path, new, time.strftime('%Y%m%d-%H%M'))}")
        print(f"다음: check-config → preflight → sudo systemctl start {unit} ({GUIDE})")
    else:
        print("보여 주기만 했습니다. 바꾸려면 끝에 --write 를 붙여 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
