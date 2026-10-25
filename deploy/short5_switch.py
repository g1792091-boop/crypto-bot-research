#!/usr/bin/env python3
"""Move ONE live executor to the '숏5 하락장' paper bot (owners 10/25: "내일 실거래봇은 일단 돌려야 할꺼 아니야";
docs/short5-bot-ko.md). The same tool as deploy/vwap_switch.py, with this bot's numbers.

    python3 deploy/short5_switch.py --exec bybit --balance 123.45            shows what would change (nothing is written)
    python3 deploy/short5_switch.py --exec bybit --balance 123.45 --write    changes it; the old copy stays as
                                                                              <file>.before-short5-<time>
    python3 deploy/short5_switch.py --exec bybit --back [--write]            back to the newest .before-short5-<time> copy

``--exec``: bybit (/etc/paperbot/executor.json, paperbot-executor; the one to use: this bot is very sensitive to cost),
wooxpro (/etc/paperbot/executor-mexc.json, paperbot-executor-mexc) or deepcoin (/etc/paperbot/executor-deepcoin.json,
paperbot-executor-deepcoin). ``--balance``: that exchange account's futures balance now (USDT, from the app). Run it
again at the start of every month with the balance then (the size follows the new balance; docs/short5-bot-ko.md §6).

Refuses to write while that executor runs (stop it first, only while it holds no position: a running executor whose
paper has no such position closes it) and while the 숏5 paper bot has no record yet (start paperbot-combo-short5 first).

What changes in that executor's config (every other value stays; the file keeps its owner and mode):
- ``paper_db`` -> /var/lib/paperbot/combo/short5.db (account COMBO@mix there too)
- ``ladder`` -> the 숏5 bot's: 12 % -> 10 % locked, then every 5 % (first_lock 0.10, trigger_gap 0.02, step 0.05)
- ``signal_light_n`` 20, ``signal_light_min_win`` 0.9: a new entry is followed only while the paper's last 20 closed
  trades won 90 % or more (fewer than 20: followed)
- ``equity_floor_frac`` 0.7: no new entry once the live balance is 70 % of the start the executor recorded
  (clear-floor records a new start, docs/short5-bot-ko.md)
- ``risk.max_loss_frac`` 0.35: one stop loses at most 35 % of the live balance (the paper bot's own cap)
- ``budget_usd`` -> the balance; ``qty_scale`` -> balance / the 숏5 paper bot's wallet now (so the live size is the
  same share of the live balance as the paper's of its wallet: margin 40 %)
Nothing restarts here: the executor reads its config when it starts (``systemctl start`` after, see the guide).
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

EXECS = {"bybit": ("바이비트", "/etc/paperbot/executor.json", "paperbot-executor"),
         "wooxpro": ("WOO X Pro", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc"),
         "deepcoin": ("딥코인", "/etc/paperbot/executor-deepcoin.json", "paperbot-executor-deepcoin")}
SHORT5_DB = "/var/lib/paperbot/combo/short5.db"
ACCOUNT = "COMBO@mix"
LADDER = {"first_lock": 0.1, "trigger_gap": 0.02, "step": 0.05}
LIGHT_N, LIGHT_WIN = 20, 0.9
FLOOR = 0.7
MAX_LOSS = 0.35
MARGIN, BTC_LEV = 0.4, 40                     # the paper bot's margin share and BTC leverage (deploy/combo.short5.json)
SUFFIX = ".before-short5-"
UNIT = "paperbot-combo-short5"
GUIDE = "docs/short5-bot-ko.md"


class Stop(Exception):
    """Why nothing is written (Korean)."""


def paper_wallet(db: str = SHORT5_DB) -> float:
    """The 숏5 paper bot's COMBO@mix wallet now (its saved account state), read-only."""
    if not os.path.exists(db):
        raise Stop(f"숏5 페이퍼 봇 기록({db})이 아직 없습니다: 먼저 {UNIT}을 켜세요")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    except sqlite3.Error as exc:
        raise Stop(f"숏5 페이퍼 봇 기록을 못 읽음: {exc}") from exc
    finally:
        conn.close()
    try:
        w = float(json.loads(row[0])["engines"][ACCOUNT]["wallet"])
    except (TypeError, KeyError, ValueError) as exc:
        raise Stop("숏5 페이퍼 봇 계좌 상태가 아직 없습니다: 켠 뒤 1~2분 기다렸다가 다시") from exc
    if not w > 0:
        raise Stop(f"숏5 페이퍼 지갑이 {w}입니다")
    return w


def plan_exec(current: str, exchange: str, balance: float, wallet: float) -> tuple:
    """(new text, [words]). Refuses a config of another exchange (a mix-up of the files)."""
    d = json.loads(current)
    if d.get("exchange") != exchange:
        raise Stop(f"이 파일의 거래소는 {d.get('exchange')!r}입니다(--exec {exchange}와 다름)")
    if not balance > 0:
        raise Stop("--balance(그 거래소 선물 잔고, 달러)를 넣으세요")
    scale = round(balance / wallet, 6)
    risk = dict(d.get("risk") or {})
    want = {"paper_db": SHORT5_DB, "ladder": LADDER, "signal_light_n": LIGHT_N, "signal_light_min_win": LIGHT_WIN,
            "equity_floor_frac": FLOOR, "budget_usd": round(float(balance), 2), "qty_scale": scale}
    words = []
    for k, v in want.items():
        if d.get(k) != v:
            words.append(f"{k}: {json.dumps(d.get(k), ensure_ascii=False)} → {json.dumps(v, ensure_ascii=False)}")
        d[k] = v
    if risk.get("max_loss_frac") != MAX_LOSS:
        words.append(f"risk.max_loss_frac: {risk.get('max_loss_frac')} → {MAX_LOSS}")
    risk["max_loss_frac"] = MAX_LOSS
    d["risk"] = risk
    words.append(f"(실거래 크기 = 페이퍼 수량 × {scale}: 페이퍼 지갑 ${wallet:,.2f}, 실거래 잔고 ${balance:,.2f})")
    cap = risk.get("max_notional_usd")
    btc = balance * MARGIN * BTC_LEV
    if cap and btc > cap:
        words.append(f"(주의) 잔고 ${balance:,.2f}의 BTC 포지션은 약 ${btc:,.0f}인데 risk.max_notional_usd가 ${cap:,.0f}라 "
                     f"그 크기로 줄여 들어갑니다(증거금 40%보다 작게). 그대로 둘지 올릴지 두 분이 정하세요")
    if exchange != "bybit":
        words.append("(주의) 이 봇은 비용에 아주 민감합니다(왕복 0.12% → 0.16%에서 30일 안 ×5 확률 12.7% → 4.5%). "
                     "바이비트로 돌리는 것을 권합니다")
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


def main(argv=None, active=unit_active, wallet_of=paper_wallet) -> int:
    ap = argparse.ArgumentParser(description="실행기 하나를 숏5 하락장 페이퍼 봇으로 옮기기")
    ap.add_argument("--exec", required=True, choices=sorted(EXECS), dest="ex")
    ap.add_argument("--balance", type=float, default=None, help="그 거래소 선물 잔고(달러)")
    ap.add_argument("--back", action="store_true", help="가장 최근 .before-short5 사본으로 되돌리기")
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
        if a.balance is None:
            raise Stop("--balance(그 거래소 선물 잔고, 달러)를 넣으세요")
        with open(path, encoding="utf-8") as fh:
            current = fh.read()
        new, words = plan_exec(current, a.ex, float(a.balance), wallet_of())
    except FileNotFoundError:
        print(f"{path} ({ko}): 파일 없음 - 멈춤")
        return 1
    except (OSError, ValueError, Stop) as exc:
        print(f"{path} ({ko}): 멈춤 - {exc}")
        return 1
    print(f"{path} ({ko}):")
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
