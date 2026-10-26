#!/usr/bin/env python3
"""Take entry members out of the running 추세판단 봇 (owners 10-26: "추세판단봇 … 피보나치 매매법들 다 빼주라 지금 포지션 진입
끝나면 다시 수정해서 돌리게").

    sudo python3 deploy/trend_drop.py            shows what would change (nothing is written)
    sudo python3 deploy/trend_drop.py --write    changes it; the old copy stays as <file>.before-drop-<time>

Only the members whose strategy starts with one of ``--drop`` (default F16_FIB: 피보나치 38.2 % 30분 · 38.2 % 1시간 ·
50 % 1시간 · 61.8 % 4시간 · 76.4 % 4시간) leave /etc/paperbot/combo.json, the live paper bot's config that both
executors follow; every other value stays as the server has it, the design name (``trend.design``) too, so the bot's
record goes on from its start (paperbot/trendbot.py: only a new design name restarts it). The file is edited line by
line when each member sits on its own line (the repository's layout), so nothing else of it moves; otherwise it is
written again as JSON. It refuses a config that is not the 추세판단 봇's (no ``trend``) or that would keep no member.

Nothing restarts here: the paper bot reads its config when it starts. Do it when the paper bot holds no position, then
``check-config`` and ``sudo systemctl restart paperbot-combo`` (docs/trend-bot-ko.md 11장). The executors stay as they are.
Back: ``cp <file>.before-drop-<time> <file>`` and the same restart.
Standard library only (the server's python3, as root).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time

COMBO = "/etc/paperbot/combo.json"
DROP = ("F16_FIB",)
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
NAME_KO = {"F16_FIB382": "피보나치 38.2%", "F16_FIB500": "피보나치 50%", "F16_FIB618": "피보나치 61.8%",
           "F16_FIB764": "피보나치 76.4%"}


def member_ko(m: dict) -> str:
    s = str(m.get("strategy"))
    return f"{NAME_KO.get(s, s)} {TF_KO.get(str(m.get('tf')), m.get('tf'))}"


def plan(text: str, drop: tuple) -> tuple:
    """(new text or None, the members taken out, the members left, the design name). ValueError when it must stop."""
    cfg = json.loads(text)
    if not isinstance(cfg, dict) or cfg.get("trend") is None:
        raise ValueError("추세판단 봇 설정이 아니에요 (trend 칸이 없음)")
    members = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    out = [m for m in members if str(m.get("strategy") or "").startswith(drop)]
    keep = [m for m in members if m not in out]
    design = (cfg.get("trend") or {}).get("design")
    if not out:
        return None, out, keep, design
    if not keep:
        raise ValueError("빼고 나면 매매법이 하나도 남지 않아요")
    want = {**cfg, "members": keep}
    lines = text.splitlines(keepends=True)
    gone = [ln for ln in lines if any(f'"strategy": "{m.get("strategy")}"' in ln and f'"tf": "{m.get("tf")}"' in ln for m in out)]
    new = "".join(ln for ln in lines if ln not in gone)
    try:
        ok = json.loads(new) == want and len(gone) == len(out)
    except ValueError:
        ok = False
    if not ok:                                            # another layout: the whole file as JSON again
        new = json.dumps(want, indent=1, ensure_ascii=False) + "\n"
    return new, out, keep, design


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="추세판단 봇에서 매매법 빼기 (기본: 피보나치)")
    ap.add_argument("--write", action="store_true", help="실제로 바꾸기 (없으면 보여 주기만)")
    ap.add_argument("--combo", default=COMBO)
    ap.add_argument("--drop", action="append", help="뺄 매매법 이름의 앞부분 (여러 번 가능; 기본 F16_FIB)")
    a = ap.parse_args(argv)
    drop = tuple(a.drop) if a.drop else DROP
    try:
        with open(a.combo, encoding="utf-8") as fh:
            text = fh.read()
        new, out, keep, design = plan(text, drop)
    except (OSError, ValueError) as exc:
        print(f"{a.combo}: 멈춤 - {exc}")
        return 1
    if new is None:
        print(f"{a.combo}: 뺄 매매법이 없어요 (이미 빠져 있어요) · 지금 진입 매매법 {len(keep)}개")
        return 0
    print(f"{a.combo}: 진입 매매법 {len(out) + len(keep)}개 → {len(keep)}개")
    print("  빼는 것: " + " · ".join(member_ko(m) for m in out))
    print("  남는 것: " + " · ".join(member_ko(m) for m in keep))
    print(f"  다른 값은 그대로 · 설계 이름 {design or '(없음)'} 그대로라 성적은 이어서 셈")
    if a.write:
        backup = f"{a.combo}.before-drop-{time.strftime('%Y%m%d-%H%M')}"
        shutil.copy2(a.combo, backup)
        with open(a.combo, "w", encoding="utf-8") as fh:  # in place: the file keeps its owner and mode
            fh.write(new)
        print(f"  바꿈 · 예전 파일: {backup}")
        print("다음: check-config → (페이퍼 포지션 없음) sudo systemctl restart paperbot-combo (docs/trend-bot-ko.md 11장)")
    else:
        print("보여 주기만 했습니다. 바꾸려면 끝에 --write 를 붙여 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
