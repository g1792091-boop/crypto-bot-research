"""A rehearsal of the checkpoint verdict on the real data, before the real one on day 30 (docs/server-setup-v3.md
'체크포인트 판정'). It runs the whole path of paperbot/checkpoint.py (the runner's ``day:<date>`` state, the
snapshot, Binance 1m bars and leverage brackets, the coin-flip bots, the verdict) as if ``--as-of`` were the
checkpoint, so a problem shows weeks before the verdict instead of on the day.

    python -m paperbot.checkpoint_preview --db paper3.db --out /tmp/preview.db [--as-of YYYY-MM-DD]
        [--cache DIR] [--min-trades 10] [--bots 500]

It never writes the real checkpoint.db: a snapshot or verdict stored there can never be removed and the later
verdicts read it. So it refuses an ``--out`` that already exists or is /var/lib/paperbot/checkpoint.db, builds no
notifier (no Telegram) and reads paper3.db read-only. The period (whole days from the run start to ``--as-of``,
default today UTC) and the trade minimum change only inside this process. ``--cache`` may be the real bar cache:
only complete past days are cached, so a rehearsal fills it ahead of the real verdict. Run it as the paperbot
user (the cache files must stay the job's); the signed leverage-bracket call needs the key of live.env.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

from . import checkpoint as ck

REAL_OUT = "/var/lib/paperbot/checkpoint.db"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--out", required=True, help="a NEW file, e.g. /tmp/preview.db (never the real checkpoint.db)")
    ap.add_argument("--as-of", help="the date to judge as if it were a checkpoint (YYYY-MM-DD, default today UTC)")
    ap.add_argument("--cache", default=None, help="1m bar cache directory (default: <out dir>/checkpoint_bars)")
    ap.add_argument("--min-trades", type=int, default=10, help="trades for a verdict here (the real one: 30)")
    ap.add_argument("--bots", type=int, default=500, help="coin-flip bots per account (the real one: 2,000)")
    args = ap.parse_args(argv)
    out = os.path.realpath(args.out)
    if os.path.exists(out) or out == os.path.realpath(REAL_OUT):
        print(f"거부: {args.out}은(는) 이미 있는 파일이거나 실제 판정 파일입니다. 새 파일 이름을 주세요 "
              "(예: /tmp/preview-$(date +%m%d%H%M).db)")
        return 2
    if os.name == "posix" and os.geteuid() == 0:
        print("거부: root로 실행하지 마세요(판정 캐시가 root 파일이 되면 실제 판정이 못 씁니다). "
              "문서의 systemd-run 명령(paperbot 사용자)으로 실행합니다")
        return 2
    from .config import V3_SYMBOLS, v3_settings
    from .live import _rest, load_brackets
    now = int(time.time() * 1000)
    conn = ck.ro_connect(args.db)
    facts = ck.run_facts(conn)
    conn.close()
    if facts["start_ts"] is None:
        print("paper3.db에 아직 계좌가 없습니다")
        return 1
    as_of = args.as_of or ck.day_str(now)
    days = (ck.day_ms(as_of) - ck.floor_day(facts["start_ts"])) // ck.DAY_MS
    if days < 1 or ck.day_ms(as_of) > now:
        print(f"거부: --as-of {as_of}: 시작일({ck.day_str(facts['start_ts'])}) 다음 날부터 오늘(UTC)까지만 됩니다")
        return 2
    s = v3_settings(**({"taker_fee": facts["taker_fee"]} if facts["taker_fee"] else {}))
    rest = _rest()
    brackets, src = load_brackets(rest, list(V3_SYMBOLS), None, False)
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
    if not done:
        return 1
    v = done[0]
    rates = [r["rate"] for r in v["accounts"].values() if r.get("rate") is not None]
    print(f"\n미리보기 끝: {time.time() - t0:.0f}초 (바이낸스에서 새로 받은 1분봉 코인·날짜 {bars.fetched_days}개), 스냅샷 계좌 "
          f"{len(v['accounts'])}개, 우연 기준 검정 {v['tested']}개, 주의 {len(v['warnings'])}건"
          + (f", 신호 비율 {min(rates):.4f}~{max(rates):.4f} (0인 계좌 {rates.count(0)}개)" if rates else ""))
    print(f"실제 checkpoint.db와 텔레그램은 건드리지 않았습니다. 계좌별 결과: cd {os.getcwd()} && sudo -u paperbot "
          f"{sys.executable} -m paperbot.checkpoint show --out {out} · 다 보면 지워도 됩니다: sudo rm {out}*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
