"""Mid-run look at the rule bot's paper v4 accounts (read-only; for the owners to run on the server and paste).

    python3 research/live_interim/interim.py [--db /var/lib/paperbot/paper3.db] [--ds-money]

Opens paper3.db read-only and prints one compact Korean summary: the run so far, each group and timeframe against the
5-year backtest, the 16 watch strategies (full grid, research/fullgrid/ANALYSIS_KO.md 8) at the numbers the bot runs,
the best and worst accounts, exit reasons, leverage, the measured entry slippage against the 0.02% the backtest
assumes, and day by day. DeepSeek money figures are hidden unless --ds-money (owners' D11). Standard library only;
nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import statistics as st
import sys
from collections import defaultdict

START = 5000.0
GROUP_OF_KIND = {"strategy": "core", "random": "flip", "ds200": "ds200", "reel": "reel", "copy": "extra",
                 "newlab": "extra"}           # paperbot/accounts.py GROUP_OF_KIND
GROUP_KO = {"core": "규칙봇 36개", "ds200": "딥시크", "reel": "5분 단타", "flip": "동전 던지기", "extra": "추가 계좌"}
TF_ORDER = ("5m", "15m", "30m", "1h", "4h", "1d")
# Full grid, default numbers and the live exit, test period 2024-01 .. 2026-09, mean P&L per trade (per signal).
BACKTEST = {"15m": -0.0117, "30m": -0.0099, "1h": -0.0074, "4h": -0.0054}
WATCH_CORE = ("DOGE", "N19_FIB_CHOP", "S4_BB_BBP", "N03_ADX_GC", "N09_ALLIG_AROON", "N13_3OUTSIDE", "OBV_S",
              "N10_HA_PSAR")
WATCH_DS = ("F10_OTE", "F7_RF_TRIPLE", "F9_FVG", "F7_RF_ONLY", "F12_MSS_DISP", "F5_BOX", "F1_PVT_DIV", "F11_TSOUP")


def pct(x, nd=2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def load(db: str):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    accts = {r["account_id"]: dict(r) for r in conn.execute(
        "SELECT account_id, strategy, timeframe, kind, created_ts FROM accounts")}
    trades = [dict(r) for r in conn.execute(
        "SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, equity_after FROM trades "
        "ORDER BY exit_time")]
    try:
        fills = [dict(r) for r in conn.execute(
            "SELECT ts, symbol, event, status, notional, slip_best FROM fill_costs WHERE slip_best IS NOT NULL")]
    except sqlite3.Error:
        fills = []
    return accts, trades, fills


def stats(rows: list) -> dict:
    rets = [t["ret"] for t in rows]
    return {"n": len(rows), "win": sum(r > 0 for r in rets) / len(rets) if rets else None,
            "mean": st.mean(rets) if rets else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/var/lib/paperbot/paper3.db")
    ap.add_argument("--ds-money", action="store_true")
    a = ap.parse_args(argv)
    accts, trades, fills = load(a.db)
    for t in trades:
        before = t["equity_after"] - t["pnl"]
        t["ret"] = t["pnl"] / before if before > 0 else 0.0
    by_acct = defaultdict(list)
    for t in trades:
        by_acct[t["account_id"]].append(t)
    for aid, ac in accts.items():
        ac["group"] = GROUP_OF_KIND.get(ac["kind"], "other")
        ts = by_acct.get(aid, [])
        ac["equity"] = ts[-1]["equity_after"] if ts else START
        ac["n"] = len(ts)
    originals = [ac for ac in accts.values() if ac["group"] != "extra"]
    d0 = min(ac["created_ts"] for ac in originals) if originals else 0
    last = max((t["exit_time"] for t in trades), default=d0)
    hide = lambda g: g == "ds200" and not a.ds_money  # noqa: E731

    out = ["[규칙봇 paper v4 중간 성적]",
           f"시작 {day(d0)} · 마지막 거래 {day(last)} · {max(0, (last - d0) / 86_400_000):.1f}일 · "
           f"계좌 {len(accts)}개 · 거래 {len(trades)}건"]
    out.append("")
    out.append("[묶음 × 봉] 계좌(거래 있는 계좌) | 거래 | 승률 | 거래당 | 5년 백테스트 거래당 | 늘어남/줄어듦/파산 | 잔고 중앙값")
    groups = defaultdict(list)
    for ac in accts.values():
        groups[(ac["group"], ac["timeframe"])].append(ac)
    for (g, tf) in sorted(groups, key=lambda k: (list(GROUP_KO).index(k[0]) if k[0] in GROUP_KO else 9,
                                                 TF_ORDER.index(k[1]) if k[1] in TF_ORDER else 9)):
        acs = groups[(g, tf)]
        rows = [t for ac in acs for t in by_acct.get(ac["account_id"], [])]
        s = stats(rows)
        traded = sum(ac["n"] > 0 for ac in acs)
        up = sum(ac["equity"] > START for ac in acs)
        bust = sum(ac["equity"] < 10 for ac in acs)
        down = sum(10 <= ac["equity"] < START for ac in acs)
        win = "—" if s["win"] is None else f"{s['win'] * 100:.0f}%"
        if hide(g):
            mean = "가림" if s["mean"] is None else ("플러스" if s["mean"] > 0 else "마이너스")
            med = "가림"
        else:
            mean = pct(s["mean"])
            med = f"${st.median(ac['equity'] for ac in acs):,.0f}"
        bt = pct(BACKTEST.get(tf)) if g == "core" else "—"
        out.append(f"{GROUP_KO.get(g, g)} {tf}: {len(acs)}({traded}) | {s['n']} | {win} | {mean} | {bt} | "
                   f"{up}/{down}/{bust} | {med}")

    out += ["", "[관찰 후보, 지금 숫자로 도는 계좌] 계좌: 거래 | 승률 | 거래당 | 잔고"]
    for name in WATCH_CORE + WATCH_DS:
        acs = sorted([ac for ac in accts.values() if ac["strategy"] == name and ac["group"] in ("core", "ds200")],
                     key=lambda ac: TF_ORDER.index(ac["timeframe"]) if ac["timeframe"] in TF_ORDER else 9)
        if not acs:
            continue
        cells = []
        for ac in acs:
            s = stats(by_acct.get(ac["account_id"], []))
            win = "—" if s["win"] is None else f"{s['win'] * 100:.0f}%"
            if not s["n"]:
                cells.append(f"{ac['timeframe']} 거래 없음")
                continue
            if hide(ac["group"]):
                mean = "+" if s["mean"] > 0 else "−"
                eq = "↑" if ac["equity"] > START else ("파산" if ac["equity"] < 10 else "↓")
            else:
                mean, eq = pct(s["mean"], 1), f"${ac['equity']:,.0f}"
            cells.append(f"{ac['timeframe']} {s['n']}건 {win} {mean} {eq}")
        out.append(f"{name}: " + " · ".join(cells))

    shown = [ac for ac in accts.values() if ac["group"] in ("core", "reel", "extra") and ac["n"] > 0]
    shown.sort(key=lambda ac: ac["equity"], reverse=True)
    out += ["", "[잔고 상위 10] " + " · ".join(f"{ac['account_id']} ${ac['equity']:,.0f}({ac['n']}건)" for ac in shown[:10])]
    out += ["[잔고 하위 10] " + " · ".join(f"{ac['account_id']} ${ac['equity']:,.0f}({ac['n']}건)" for ac in shown[-10:])]

    core = [t for t in trades if accts.get(t["account_id"], {}).get("group") == "core"]
    out += ["", "[청산 이유, 규칙봇 36개] " + " · ".join(
        f"{r} {len(v)}건 {pct(st.mean(x['ret'] for x in v), 1)}"
        for r, v in sorted(_by(core, "exit_reason").items(), key=lambda kv: -len(kv[1])))]
    out += ["[레버리지, 규칙봇 36개] " + " · ".join(
        f"{lv}배 {len(v)}건 {pct(st.mean(x['ret'] for x in v), 1)}"
        for lv, v in sorted(_by(core, "leverage").items()))]

    ent = [f for f in fills if f["event"] in ("entry", "open") and f["ts"] >= d0]
    if not ent:
        ent = [f for f in fills if f["ts"] >= d0]
    if ent:
        per = defaultdict(list)
        for f in ent:
            per[f["symbol"]].append(f["slip_best"] * 10_000)
        out += ["", "[실제 호가로 잰 체결 비용, 백테스트 가정 2bp] " + " · ".join(
            f"{sym} 중앙 {st.median(v):.1f}bp 상위10% {sorted(v)[int(0.9 * (len(v) - 1))]:.1f}bp ({len(v)})"
            for sym, v in sorted(per.items()))]

    out += ["", "[날짜별, 규칙봇 36개] " + " · ".join(
        f"{d} {len(v)}건 {pct(st.mean(x['ret'] for x in v), 1)}"
        for d, v in sorted(_by(core, None).items()))]
    print("\n".join(out))
    return 0


def _by(rows: list, key) -> dict:
    out = defaultdict(list)
    for t in rows:
        out[day(t["exit_time"]) if key is None else t[key]].append(t)
    return out


if __name__ == "__main__":
    sys.exit(main())
