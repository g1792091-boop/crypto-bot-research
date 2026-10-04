"""A rehearsal of the checkpoint verdict on the real data, before the real one on day 30 (docs/server-setup-v3.md
'체크포인트 판정'). It runs the whole path of paperbot/checkpoint.py (the runner's ``day:<date>`` state, the
snapshot, Binance 1m bars and leverage brackets, the coin-flip bots, the verdict) as if ``--as-of`` were the
checkpoint, so a problem shows weeks before the verdict instead of on the day.

    python -m paperbot.checkpoint_preview --db paper3.db --out /tmp/preview.db [--as-of YYYY-MM-DD]
        [--cache DIR] [--min-trades 10] [--bots 500] [--summary FILE]
    python -m paperbot.checkpoint_preview --db paper3.db --rehearsal-dir DIR [--keep 4] [--cache DIR] ...

It never writes the real checkpoint.db: a snapshot or verdict stored there can never be removed and the later
verdicts read it. So it refuses an ``--out`` that already exists or is /var/lib/paperbot/checkpoint.db, builds no
notifier (no Telegram) and reads paper3.db read-only. The period (whole days from the run start to ``--as-of``,
default today UTC) and the trade minimum change only inside this process. ``--cache`` may be the real bar cache:
only complete past days are cached, so a rehearsal fills it ahead of the real verdict. Run it as the paperbot
user (the cache files must stay the job's); the signed leverage-bracket call needs the key of live.env.

``--rehearsal-dir`` (the weekly timer, deploy/paperbot-rehearsal.service): the output is a fresh
``DIR/rehearsal-<UTC time>.db``, a JSON summary ``DIR/rehearsal-<UTC time>.json`` (``summary_of``: status,
runtime, accounts in the snapshot, warnings, zero-rate accounts, counts by status) is written next to it and
copied to ``DIR/latest.json`` (the agents and the dashboard read that one), and only the newest ``--keep``
rehearsals are kept. A failed run still writes its summary (``status: failed``) and exits non-zero, so systemd's
OnFailure= sends the one failure warning.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import traceback
from typing import Optional

from . import checkpoint as ck

REAL_OUT = "/var/lib/paperbot/checkpoint.db"
PREFIX = "rehearsal-"
LATEST = "latest.json"


def summary_of(v: Optional[dict], *, as_of: Optional[str], days: Optional[int], out: str, started: float,
               finished: float, status: str, error: Optional[str] = None, fetched_days: Optional[int] = None,
               brackets_src: Optional[str] = None, min_trades: Optional[int] = None,
               bots: Optional[int] = None) -> dict:
    """The rehearsal's JSON summary (``v``: the verdict ``checkpoint.run_due`` returned, None when it failed)."""
    s = {"status": status, "as_of": as_of, "days": days, "out": out,
         "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
         "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished)),
         "runtime_s": round(finished - started, 1), "min_trades": min_trades, "bots": bots,
         "fetched_bar_days": fetched_days, "brackets_src": brackets_src, "error": error}
    if v is not None:
        accts = v.get("accounts") or {}
        rates = {a: r.get("rate") for a, r in accts.items() if r.get("rate") is not None}
        s.update(accounts_in_snapshot=len(accts), tested=v.get("tested"), warnings=list(v.get("warnings") or []),
                 zero_rate_accounts=sorted(a for a, x in rates.items() if x == 0),
                 rate_min=min(rates.values()) if rates else None, rate_max=max(rates.values()) if rates else None,
                 counts=dict(v.get("counts") or {}), verdict_runtime_s=v.get("runtime_s"),
                 snapshot_sha256=v.get("snapshot_sha256"))
    return s


def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def rotate(folder: str, keep: int) -> list[str]:
    """Remove all but the newest ``keep`` rehearsals in ``folder`` (their .db, -wal, -shm, -journal and .json).
    Returns the removed paths. Only ``rehearsal-*`` files are touched."""
    stems = sorted({os.path.basename(p).rsplit(".", 1)[0]
                    for p in glob.glob(os.path.join(folder, PREFIX + "*.db"))
                    + glob.glob(os.path.join(folder, PREFIX + "*.json"))})
    gone = []
    for stem in stems[:max(len(stems) - keep, 0)]:
        for suf in (".db", ".db-wal", ".db-shm", ".db-journal", ".json"):
            p = os.path.join(folder, stem + suf)
            if os.path.exists(p):
                os.remove(p)
                gone.append(p)
    return gone


def latest_summary(folder: str = "/var/lib/paperbot/rehearsal") -> Optional[dict]:
    """The newest rehearsal summary (for the agents / dashboard), or None."""
    try:
        with open(os.path.join(folder, LATEST), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--out", help="a NEW file, e.g. /tmp/preview.db (never the real checkpoint.db)")
    ap.add_argument("--rehearsal-dir", help="weekly mode: a fresh rehearsal-<time>.db and .json in this folder")
    ap.add_argument("--keep", type=int, default=4, help="--rehearsal-dir: rehearsals kept (default 4)")
    ap.add_argument("--summary", help="also write the JSON summary to this file")
    ap.add_argument("--as-of", help="the date to judge as if it were a checkpoint (YYYY-MM-DD, default today UTC)")
    ap.add_argument("--cache", default=None, help="1m bar cache directory (default: <out dir>/checkpoint_bars)")
    ap.add_argument("--min-trades", type=int, default=10, help="trades for a verdict here (the real one: 30)")
    ap.add_argument("--bots", type=int, default=500, help="coin-flip bots per account (the real one: 2,000)")
    args = ap.parse_args(argv)
    if bool(args.out) == bool(args.rehearsal_dir):
        print("거부: --out(새 파일) 또는 --rehearsal-dir(폴더) 중 하나만 주세요")
        return 2
    if os.name == "posix" and os.geteuid() == 0:
        print("거부: root로 실행하지 마세요(판정 캐시가 root 파일이 되면 실제 판정이 못 씁니다). "
              "문서의 systemd-run 명령(paperbot 사용자)으로 실행합니다")
        return 2
    summary_path = args.summary
    if args.rehearsal_dir:
        folder = os.path.realpath(args.rehearsal_dir)
        if folder == os.path.dirname(os.path.realpath(REAL_OUT)) or args.keep < 1:
            print(f"거부: --rehearsal-dir {args.rehearsal_dir}는 판정 폴더 자체가 아닌 전용 폴더여야 하고 --keep은 1 이상")
            return 2
        os.makedirs(folder, exist_ok=True)
        stem = os.path.join(folder, PREFIX + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        args.out, summary_path = stem + ".db", stem + ".json"
    out = os.path.realpath(args.out)
    if os.path.exists(out) or out == os.path.realpath(REAL_OUT):
        print(f"거부: {args.out}은(는) 이미 있는 파일이거나 실제 판정 파일입니다. 새 파일 이름을 주세요 "
              "(예: /tmp/preview-$(date +%m%d%H%M).db)")
        return 2
    t0 = time.time()
    ctx: dict = {"as_of": args.as_of, "days": None, "fetched_days": None, "brackets_src": None}
    try:
        code, v = _run(args, out, ctx)
        status = "ok" if code == 0 else "failed"
        err = None if code == 0 else ctx.get("error", f"exit code {code}")
    except Exception as exc:  # noqa: BLE001  (the summary records it; the exit code makes systemd warn)
        traceback.print_exc()
        code, v, status, err = 1, None, "failed", f"{type(exc).__name__}: {exc}"[:500]
    if summary_path:
        s = summary_of(v, as_of=ctx["as_of"], days=ctx["days"], out=out, started=t0, finished=time.time(),
                       status=status, error=err, fetched_days=ctx["fetched_days"], brackets_src=ctx["brackets_src"],
                       min_trades=args.min_trades, bots=args.bots)
        _write_json(summary_path, s)
        if args.rehearsal_dir:
            _write_json(os.path.join(os.path.dirname(out), LATEST), s)
            gone = rotate(os.path.dirname(out), args.keep)
            if gone:
                print(f"지난 연습 {len(gone)}개 파일 정리 (최근 {args.keep}번만 보관)")
        print(f"요약: {summary_path}")
    return code


def _run(args, out: str, ctx: dict) -> tuple[int, Optional[dict]]:
    from .config import V3_SYMBOLS, v3_settings
    from .live import _rest, load_brackets
    now = int(time.time() * 1000)
    conn = ck.ro_connect(args.db)
    facts = ck.run_facts(conn)
    conn.close()
    if facts["start_ts"] is None:
        print("paper3.db에 아직 계좌가 없습니다")
        ctx["error"] = "no accounts in paper3.db yet"
        return 1, None
    as_of = args.as_of or ck.day_str(now)
    days = (ck.day_ms(as_of) - ck.floor_day(facts["start_ts"])) // ck.DAY_MS
    ctx.update(as_of=as_of, days=int(days))
    if days < 1 or ck.day_ms(as_of) > now:
        print(f"거부: --as-of {as_of}: 시작일({ck.day_str(facts['start_ts'])}) 다음 날부터 오늘(UTC)까지만 됩니다")
        ctx["error"] = f"--as-of {as_of} outside the run"
        return 2, None
    s = v3_settings(**({"taker_fee": facts["taker_fee"]} if facts["taker_fee"] else {}))
    rest = _rest()
    brackets, src = load_brackets(rest, list(V3_SYMBOLS), None, False)
    ctx["brackets_src"] = src
    specs = rest.exchange_info(list(V3_SYMBOLS))
    bars = ck.BinanceMinutes(rest, args.cache or os.path.join(os.path.dirname(out), "checkpoint_bars"))
    print(f"미리보기: {as_of} 09:00 KST를 {days}일째 판정처럼 계산 (거래 {args.min_trades}건 이상, 동전 봇 "
          f"{args.bots:,}개씩, 레버리지 구간: {src})")
    saved = ck.PERIOD_DAYS, ck.MIN_TRADES
    ck.PERIOD_DAYS, ck.MIN_TRADES = int(days), args.min_trades          # this process only
    t0 = time.time()
    try:
        done = ck.run_due(args.db, out, bars.load, s, brackets, specs, None, now_ms=now, only=as_of,
                          n_bots=args.bots)
    finally:
        ck.PERIOD_DAYS, ck.MIN_TRADES = saved
        ctx["fetched_days"] = bars.fetched_days
    if not done:
        ctx["error"] = f"no verdict for {as_of} (no day:{as_of} state in paper3.db yet?)"
        return 1, None
    v = done[0]
    rates = [r["rate"] for r in v["accounts"].values() if r.get("rate") is not None]
    print(f"\n미리보기 끝: {time.time() - t0:.0f}초 (바이낸스에서 새로 받은 1분봉 코인·날짜 {bars.fetched_days}개), 스냅샷 계좌 "
          f"{len(v['accounts'])}개, 우연 기준 검정 {v['tested']}개, 주의 {len(v['warnings'])}건"
          + (f", 신호 비율 {min(rates):.4f}~{max(rates):.4f} (0인 계좌 {rates.count(0)}개)" if rates else ""))
    print(f"실제 checkpoint.db와 텔레그램은 건드리지 않았습니다. 계좌별 결과: cd {os.getcwd()} && sudo -u paperbot "
          f"{sys.executable} -m paperbot.checkpoint show --out {out} · 다 보면 지워도 됩니다: sudo rm {out}*")
    return 0, v


if __name__ == "__main__":
    sys.exit(main())
