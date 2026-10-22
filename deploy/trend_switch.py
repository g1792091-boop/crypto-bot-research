#!/usr/bin/env python3
"""Switch the live paper bot to 추세판단 봇 (owners 10/21: "실거래 바로 돌릴꺼고 바이비트봇이랑 woo pro봇 둘다 -50%").

    python3 deploy/trend_switch.py            shows what would change (nothing is written)
    python3 deploy/trend_switch.py --write    changes it; each file's old copy stays as <file>.before-trend-<time>

What changes (the files' owners and modes stay: written in place):
1. /etc/paperbot/combo.json, the config of the live paper bot (paperbot-combo, database live-ac.db, account COMBO@mix that
   both executors follow): replaced by this repository's deploy/combo.trend.json (the same database: the account, its
   wallet and its records go on; queued signals of the old strategies are dropped at the start, never traded);
2. /etc/paperbot/executor-mexc.json (the WOO X Pro executor): ``paper_db`` -> /var/lib/paperbot/combo/live-ac.db (it
   followed the -35 % bot; now both executors follow the same -50 % paper bot);
3. /etc/paperbot/executor.json (Bybit): checked only (it already follows live-ac.db; changed the same way if not).
Every other value stays. Nothing restarts here: the paper bot reads its config when it starts (bash deploy/install.sh
restarts it with the new code), each executor when it starts (``systemctl start`` after, only with no position).

The same command moves a running 추세판단 봇 to a newer design (owners 10/22: 18 entry members, 4h entries on the daily
bar, 보류 허용, 바로 진입): the config is replaced the same way; its new ``trend.design`` name restarts the bot's record
on the same database (paperbot/trendbot.py). The executors stay as they are (off until the owners decide).

Back: ``cp <file>.before-trend-<time> <file>`` for each file, then the same restarts.
Standard library only (the server's python3, as root).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TREND = os.path.join(HERE, "combo.trend.json")
COMBO = "/etc/paperbot/combo.json"
EXECS = (("WOO X Pro", "/etc/paperbot/executor-mexc.json"), ("바이비트", "/etc/paperbot/executor.json"))
PAPER_DB = "/var/lib/paperbot/combo/live-ac.db"


def _read(path: str):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, text: str, stamp: str) -> str:
    backup = f"{path}.before-trend-{stamp}"
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as fh:          # in place: the file keeps its owner and mode
        fh.write(text)
    return backup


def plan_combo(current: str, want: str) -> tuple:
    """(new text or None, words). Refuses a trend config whose database is not the running one's."""
    cur, new = json.loads(current), json.loads(want)
    if cur.get("db") != new.get("db"):
        raise ValueError(f"지금 설정의 db({cur.get('db')})와 추세판단 봇의 db({new.get('db')})가 달라 멈춥니다")
    if cur.get("trend") is not None and current == want:
        return None, "이미 추세판단 봇 설정"
    old_ms = [f"{m.get('strategy')}@{m.get('tf')}" for m in cur.get("members") or [] if isinstance(m, dict)]
    new_ms = [f"{m.get('strategy')}@{m.get('tf')}" for m in new.get("members") or [] if isinstance(m, dict)]
    design = (new.get("trend") or {}).get("design")
    if cur.get("trend") is not None:                  # a running trend bot -> its newer design
        old_d = (cur.get("trend") or {}).get("design") or "10/21 설계"
        return want, (f"{cur.get('name') or '이름 없음'} {old_d} → {new.get('name')} 새 설계 {design or '(이름 없음)'} · "
                      f"진입 {len(old_ms)}개 → 진입 {len(new_ms)}개 · 성적은 새 설계 시작부터 새로 셈 · db 그대로 {new.get('db')}")
    return want, (f"{cur.get('name') or '이름 없음'} → {new.get('name')} · 매매법 {len(old_ms)}개 → 진입 {len(new_ms)}개 "
                  f"(추세 판단 4개는 진입 안 함) · db 그대로 {new.get('db')}")


def plan_exec(current: str) -> tuple:
    d = json.loads(current)
    if d.get("paper_db") == PAPER_DB:
        return None, f"paper_db 그대로 {PAPER_DB}"
    old = d.get("paper_db")
    d["paper_db"] = PAPER_DB
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n", f"paper_db {old} → {PAPER_DB}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="실거래 페이퍼 봇을 추세판단 봇으로 바꾸기")
    ap.add_argument("--write", action="store_true", help="실제로 바꾸기 (없으면 보여 주기만)")
    ap.add_argument("--combo", default=COMBO)
    ap.add_argument("--exec", action="append", help="실행기 설정 (여러 번 가능; 기본: 두 실행기)")
    a = ap.parse_args(argv)
    stamp = time.strftime("%Y%m%d-%H%M")
    bad = 0
    try:
        want = _read(TREND)
        new, words = plan_combo(_read(a.combo), want)
    except (OSError, ValueError) as exc:
        print(f"{a.combo}: 멈춤 - {exc}")
        return 1
    print(f"{a.combo}: {words}")
    if new is not None and a.write:
        print(f"  바꿈 · 예전 파일: {_write(a.combo, new, stamp)}")
    for ko, path in ([(p, p) for p in a.exec] if a.exec else EXECS):
        try:
            new, words = plan_exec(_read(path))
        except FileNotFoundError:
            print(f"{path} ({ko}): 파일 없음 (건너뜀)")
            continue
        except (OSError, ValueError) as exc:
            print(f"{path} ({ko}): 멈춤 - {exc}")
            bad += 1
            continue
        print(f"{path} ({ko}): {words}")
        if new is not None and a.write:
            print(f"  바꿈 · 예전 파일: {_write(path, new, stamp)}")
    if not a.write:
        print("보여 주기만 했습니다. 바꾸려면 끝에 --write 를 붙여 다시 실행하세요.")
    else:
        print("다음: check-config → (페이퍼 포지션 없음) bash deploy/install.sh · 실행기는 두 분이 정할 때만 켬 "
              "(docs/trend-bot-ko.md)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
