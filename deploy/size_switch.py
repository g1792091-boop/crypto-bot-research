#!/usr/bin/env python3
"""Size a live executor's new entries from its own balance (owners 10/25 night: "b로해줘", "파산당하면 파산 당한다는
마인드야 그냥 항상 시드비중 40%로 해줘").

    python3 deploy/size_switch.py --exec bybit            shows what would change (nothing is written)
    python3 deploy/size_switch.py --exec bybit --write    changes it; the old copy stays as <file>.before-size-<time>
    python3 deploy/size_switch.py --exec bybit --back [--write]   back to the newest .before-size-<time> copy

``--exec``: bybit (/etc/paperbot/executor.json, paperbot-executor), wooxpro (/etc/paperbot/executor-mexc.json,
paperbot-executor-mexc) or deepcoin (/etc/paperbot/executor-deepcoin.json, paperbot-executor-deepcoin). ``--margin``:
the margin's share of the balance (default 0.4 = 40 %).

What changes in that executor's config (every other value stays; the file keeps its owner and mode):
- ``size_from`` -> "equity", ``margin_frac`` -> 0.4: each new entry's margin is 40 % of the live balance read at that
  moment, at the paper's leverage (capped by risk.max_leverage); never cut for a far stop. ``qty_scale`` stays in the
  file but is no longer used for the size.
``--back`` puts the whole file back as it was before the newest switch (a later change by another switch script too).
Refuses to write while that executor runs (stop it first, only while it holds no position).
Nothing restarts here: the executor reads its config when it starts (check-config, then ``systemctl start``).
Standard library only (the server's python3, as root).
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
import time

EXECS = {"bybit": ("바이비트", "/etc/paperbot/executor.json", "paperbot-executor"),
         "wooxpro": ("WOO X Pro", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc"),
         "deepcoin": ("딥코인", "/etc/paperbot/executor-deepcoin.json", "paperbot-executor-deepcoin")}
MARGIN = 0.4
SUFFIX = ".before-size-"


class Stop(Exception):
    """Why nothing is written (Korean)."""


def plan(current: str, exchange: str, margin: float) -> tuple:
    """(new text, [words]). Refuses a config of another exchange (a mix-up of the files) or a margin outside 0..1."""
    if not 0 < margin <= 1:
        raise Stop(f"--margin은 0~1 사이 비율입니다(40% → 0.4, 지금 {margin})")
    d = json.loads(current)
    if d.get("exchange") != exchange:
        raise Stop(f"이 파일의 거래소는 {d.get('exchange')!r}입니다(--exec {exchange}와 다름)")
    if (d.get("entry_source") or "paper") != "paper":
        raise Stop("entry_source가 \"paper\"가 아닌 실행기는 잔고 기준 크기를 쓰지 않습니다")
    words = []
    for k, v in (("size_from", "equity"), ("margin_frac", round(float(margin), 6))):
        if d.get(k) != v:
            words.append(f"{k}: {json.dumps(d.get(k), ensure_ascii=False)} → {json.dumps(v, ensure_ascii=False)}")
        d[k] = v
    words.append(f"(진입할 때마다 실거래 잔고의 {margin:.0%}를 증거금으로, paper와 같은 배수. 손절이 멀어도 줄이지 않음. "
                 f"qty_scale {d.get('qty_scale')}은 그대로 두지만 크기에는 안 씀)")
    cap = (d.get("risk") or {}).get("max_notional_usd")
    if cap:
        words.append(f"(참고: 포지션 크기 상한 risk.max_notional_usd ${float(cap):,.0f}는 그대로 - 잔고 × {margin:g} × 배수가 이보다 "
                     "크면 상한까지만 들어감)")
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


def main(argv=None, active=unit_active) -> int:
    ap = argparse.ArgumentParser(description="실행기 크기를 실거래 잔고 기준(증거금 40%)으로 바꾸기")
    ap.add_argument("--exec", required=True, choices=sorted(EXECS), dest="ex")
    ap.add_argument("--margin", type=float, default=MARGIN, help="증거금으로 쓸 잔고 비율 (기본 0.4 = 40%%)")
    ap.add_argument("--back", action="store_true", help="가장 최근 .before-size 사본으로 되돌리기")
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
        new, words = plan(current, a.ex, float(a.margin))
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
        try:
            backup = _write(path, new, time.strftime("%Y%m%d-%H%M%S"))
        except OSError as exc:
            print(f"{path} ({ko}): 멈춤 - 쓰지 못함: {exc}")
            return 1
        print(f"  바꿈 · 예전 파일: {backup}")
        print("다음: check-config → sudo systemctl start " + unit)
    else:
        print("보여 주기만 했습니다. 바꾸려면 끝에 --write 를 붙여 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
