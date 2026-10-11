"""Why one 4h trade differs from the replay (read-only; for the owners to run and paste).

    python3 research/live_interim/why_4h.py [--db /var/lib/paperbot/paper3.db]

The backtest replay of the live days matches the 4h accounts to a few dollars except the SOL long from the 4h bar
closing 2026-10-06 16:00 UTC (replay: +2.1% lock by 22:05; live: -11.3% in N01_ST_EMA@4h, N12_ICHI_AO@4h,
S2_ST_ROC@4h). This prints the bot's start times, the SOL 4h signals around that bar with their reference price and
delay, and those accounts' trades with entry / exit times and prices. Standard library only; nothing is written.
"""

import argparse
import datetime as dt
import json
import sqlite3
import sys

ACCTS = ("N01_ST_EMA@4h", "N12_ICHI_AO@4h", "S2_ST_ROC@4h")


def t(ms) -> str:
    return "—" if ms is None else dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).strftime("%m-%d %H:%M:%S")


def ms(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/var/lib/paperbot/paper3.db")
    a = ap.parse_args(argv)
    c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    print("[봇 시작 시각, UTC]")
    for (ts,) in c.execute("SELECT started_ts FROM runs ORDER BY id"):
        print(" ", t(ts))
    print("[SOL 4시간봉 신호, 10/06 08:00 ~ 10/07 04:00 UTC] 봉 마감 | 매매법 | 방향 | 기준가 | 기준가 시각 | 지연 | 상태")
    for r in c.execute("SELECT bar_close, strategy, side, ref_price, ref_time, delay_ms, status FROM signal_log "
                       "WHERE timeframe = '4h' AND symbol = 'SOLUSDT' AND bar_close BETWEEN ? AND ? ORDER BY bar_close, strategy",
                       (ms("2026-10-06 08:00"), ms("2026-10-07 04:00"))):
        bc, s, side, rp, rt, dl, st = r
        print(f"  {t(bc)} | {s} | {'롱' if side > 0 else '숏'} | {rp} | {t(rt)} | {dl}ms | {st}")
    print("[세 계좌의 거래] 계좌 | 코인 | 들어간 시각 | 나온 시각 | 이유 | 배수 | 진입가 | 첫 손절가 | 청산가 | 가장 유리했던 가격 | 손익")
    q = ",".join("?" * len(ACCTS))
    for aid, sym, et, xt, why, lev, pnl, data in c.execute(
            f"SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, data FROM trades "
            f"WHERE account_id IN ({q}) ORDER BY account_id, entry_time", ACCTS):
        d = json.loads(data or "{}")
        print(f"  {aid} | {sym} | {t(et)} | {t(xt)} | {why} | {lev} | {d.get('entry_price')} | {d.get('stop_initial')} | "
              f"{d.get('exit_price')} | {d.get('mfe_price')} | {pnl:+.2f}")
    print("[세 계좌의 신호 처리, 10/06 12:00 ~ 10/07 08:00 UTC] 계좌 | 시각 | 상태 | 이유 | 코인")
    for aid, st_ts, status, reason, sym in c.execute(
            f"SELECT account_id, step_ts, status, reason, symbol FROM outcomes WHERE account_id IN ({q}) "
            f"AND step_ts BETWEEN ? AND ? ORDER BY step_ts", (*ACCTS, ms("2026-10-06 12:00"), ms("2026-10-07 08:00"))):
        print(f"  {aid} | {t(st_ts)} | {status} | {reason} | {sym}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
