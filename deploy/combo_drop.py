#!/usr/bin/env python3
"""Take one setting out of the paper bots' configs (owners 10/20 night: "레인지 필터만 매매법 빼줘").

    python3 deploy/combo_drop.py F7_RF_ONLY@1h            shows what would change in both paper bots' configs
    python3 deploy/combo_drop.py F7_RF_ONLY@1h --write    changes them; each file's old copy stays as <file>.before-drop-<time>

The configs: /etc/paperbot/combo.json (규칙봇 15, −50 %, Bybit follows it) and /etc/paperbot/combo-mexc.json (−35 %, WOO X Pro
follows it); ``--config PATH`` (repeatable) names others. Only the ``members`` item of that strategy and timeframe goes;
every other value stays. A file without that setting is left as it is ("이미 없음"); a file with it twice is refused. The
file keeps its owner and mode (written in place). Standard library only (the server's python3, as root).

Nothing restarts here: the paper bots read their config when they start. After --write: check-config for both files,
then, only while both paper bots and both executors show no position, ``systemctl restart paperbot-combo
paperbot-combo-mexc`` (docs/live15-plan-ko.md "10/20 바뀜").
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time

CONFIGS = ("/etc/paperbot/combo.json", "/etc/paperbot/combo-mexc.json")


def parse_target(text: str) -> tuple:
    strat, sep, tf = text.partition("@")
    if not sep or not strat or not tf:
        raise SystemExit(f"'{text}'는 '매매법@봉' 모양이어야 합니다 (예: F7_RF_ONLY@1h)")
    return strat, tf


def drop(text: str, strat: str, tf: str) -> tuple:
    """(new text or None when nothing to change, the members before, the members after, note). Raises ValueError."""
    d = json.loads(text)
    ms = d.get("members")
    if not isinstance(ms, list):
        raise ValueError("members 목록이 없습니다")
    hit = [i for i, m in enumerate(ms) if isinstance(m, dict) and m.get("strategy") == strat and m.get("tf") == tf]
    if not hit:
        return None, ms, ms, "이미 없음"
    if len(hit) > 1:
        raise ValueError(f"{strat}@{tf}가 {len(hit)}번 있습니다 (어느 것을 뺄지 몰라 멈춥니다)")
    keep = [m for i, m in enumerate(ms) if i != hit[0]]
    want = {**d, "members": keep}
    # the member's own line removed (the file's look kept); a file of another shape is written again as JSON
    lines = text.splitlines(keepends=True)
    mine = [j for j, ln in enumerate(lines) if f'"{strat}"' in ln and f'"{tf}"' in ln]
    if len(mine) == 1:
        cand = "".join(ln for j, ln in enumerate(lines) if j != mine[0])
        try:
            if json.loads(cand) == want:
                return cand, ms, keep, f"{hit[0] + 1}번 줄 뺌"
        except ValueError:
            pass
    return json.dumps(want, indent=1, ensure_ascii=False) + "\n", ms, keep, f"{hit[0] + 1}번 뺌 (파일을 JSON으로 다시 씀)"


def label(m: dict) -> str:
    return f"{m.get('strategy')}@{m.get('tf')}" + (" (추격 막기)" if m.get("no_chase") else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="페이퍼 봇 설정에서 매매법 하나 빼기")
    ap.add_argument("target", help="매매법@봉, 예: F7_RF_ONLY@1h")
    ap.add_argument("--config", action="append", help="설정 파일 (여러 번 가능; 기본: 두 페이퍼 봇 설정)")
    ap.add_argument("--write", action="store_true", help="실제로 바꾸기 (없으면 보여 주기만)")
    a = ap.parse_args(argv)
    strat, tf = parse_target(a.target)
    stamp = time.strftime("%Y%m%d-%H%M")
    bad = 0
    for path in a.config or CONFIGS:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            print(f"{path}: 파일 없음 (건너뜀)")
            continue
        except OSError as exc:
            print(f"{path}: 못 읽음 ({exc})")
            bad += 1
            continue
        try:
            new, before, after, note = drop(text, strat, tf)
        except ValueError as exc:
            print(f"{path}: 멈춤 - {exc}")
            bad += 1
            continue
        if new is None:
            print(f"{path}: {strat}@{tf} {note} (매매법 {len(before)}개 그대로)")
            continue
        print(f"{path}: {strat}@{tf} {note} · 매매법 {len(before)}개 -> {len(after)}개 · 추격 막기 "
              f"{sum(1 for m in before if m.get('no_chase'))}개 -> {sum(1 for m in after if m.get('no_chase'))}개")
        print("  남는 순서: " + ", ".join(f"{i}. {label(m)}" for i, m in enumerate(after, 1)))
        if not a.write:
            continue
        backup = f"{path}.before-drop-{stamp}"
        shutil.copy2(path, backup)
        with open(path, "w", encoding="utf-8") as fh:          # in place: the file keeps its owner and mode
            fh.write(new)
        print(f"  바꿈 · 예전 파일: {backup}")
    if not a.write:
        print("보여 주기만 했습니다. 바꾸려면 끝에 --write 를 붙여 다시 실행하세요.")
    else:
        print("다음: 두 파일 check-config -> 두 페이퍼 봇과 두 실행기 모두 포지션 없음 확인 -> "
              "systemctl restart paperbot-combo paperbot-combo-mexc")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
