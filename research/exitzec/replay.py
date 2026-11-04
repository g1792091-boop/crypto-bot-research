"""ZEC 봇 청산(계단) 바꾸기 백테스트 (owners 11-04 night: "한번 시험해봐"). The plan and the pass/fail criteria were written
before any run: research/exitzec/PLAN_KO.md.

The bot the owners will run (deploy/mixchop.live.json: ZEC alone at 30x on Toobit, $26, the 5m OBV turn with the 30m and
15m 추세 MACD on its side, the 15m ATR x 3 stop), its entries exactly as research/obv5m decided them (the same
paperbot/mixchop.py and friendtrend.py: their sha256 checked against research/obv5m/summary.json), and only its ladder
changed (E0 the live 10 -> 8, then 2; E1 .. E4 later locks, the exchange ROE before fees as the live config).

    python3 -I research/exitzec/replay.py dev       # summary.json "dev" (+ "dev_fixed")
    python3 -I research/exitzec/replay.py sealed    # only the ladders that pass dev, ONCE
    python3 -I research/exitzec/replay.py report    # REPORT_KO.md

Driven as research/obv5m/replay.py drives it (that file's run_bot: a mixchop.Bot in paper mode on every 5m close, the
stop and the ladder on the 1m bars; the C-ZEC30 decisions: obv5m's at_leverage, re-checked there with the bot's code).
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from paperbot import events as EV  # noqa: E402
from paperbot import mixchop as M  # noqa: E402

_spec = importlib.util.spec_from_file_location("obv5m_replay", os.path.join(ROOT, "research", "obv5m", "replay.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
P = R.P                                                   # research/obv15both/replay.py (trades, summarize, verdict ...)

OUT = os.path.join(HERE, "summary.json")
CONFIG = os.path.join(ROOT, "deploy", "mixchop.live.json")
SYM, LEV, START = "ZECUSDT", 30, 26.0
# the ladders (PLAN_KO.md): trigger, lock, step in exchange ROE % (before fees)
LADDERS = {"E0": (10, 8, 2), "E1": (20, 15, 5), "E2": (40, 30, 10), "E3": (70, 50, 20), "E4": (120, 90, 30)}


def load_decisions(data: str) -> dict:
    """research/obv5m's decisions, after checking the bot's code is the one they were made with."""
    ref = json.load(open(os.path.join(ROOT, "research", "obv5m", "summary.json"), encoding="utf-8"))["code"]["dev"]
    for k, f in (("mixchop_sha256", "mixchop.py"), ("friendtrend_sha256", "friendtrend.py")):
        if P.file_sha(os.path.join(ROOT, "paperbot", f)) != ref[k]:
            raise SystemExit(f"paperbot/{f} changed since research/obv5m decided: run its decide again")
    files = glob.glob(os.path.join(data, "decisions5m-*.json"))
    if len(files) != 1:
        raise SystemExit(f"want one research/obv5m decisions file in {data}, found {files}")
    with open(files[0], encoding="utf-8") as fh:
        got = json.load(fh)
    return {s: {"C": {int(k): v for k, v in d["C"].items()}, "checks": d["checks"]} for s, d in got.items()}


def make_cfg_with(ladder):
    """obv5m's make_cfg with this ladder (the live config's rule, the coin and start the run asks for)."""
    def make_cfg(fee: float, tmp: str, coins=None, start: float = START) -> "M.Config":
        d = json.load(open(CONFIG, encoding="utf-8"))
        t, lk, st = ladder
        d.update(mode="paper", state=os.path.join(tmp, "none", "state.json"), log=os.path.join(tmp, "none", "log.jsonl"),
                 kill_file=os.path.join(tmp, "none", "STOP"), own_stop_file=os.path.join(tmp, "none", "OWN"), telegram=False,
                 taker_fee=fee, start_equity=start, ladder={"trigger": t, "lock": lk, "step": st})
        d["coins"] = {s: {"leverage": int(v)} for s, v in (coins or {SYM: LEV}).items()}
        p = os.path.join(tmp, f"cfgx-{fee}-{t}-{lk}-{st}.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        cfg = M.load_config(p)
        assert (cfg.rules, cfg.tf, cfg.trend, cfg.trend_tf, cfg.trend_tf2, cfg.stop_tf, cfg.ladder_basis, cfg.margin_frac) == \
            (("o4h",), "5m", "macd", "30m", "15m", "15m", "gross", 0.4)
        assert cfg.ladder == {"trigger": float(t), "lock": float(lk), "step": float(st)}
        assert [(c.symbol, c.leverage) for c in cfg.coins] == [(SYM, LEV)]
        return cfg
    return make_cfg


def _passed_dev(summary: dict, key: str) -> bool:
    return all(p for _, p, _ in P.verdict(summary, key) if p is not None)


def cmd_period(args, period: str) -> int:
    summary = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {}
    keys = list(LADDERS)
    if period == "sealed":
        if "dev" not in summary:
            raise SystemExit("dev first")
        keys = [k for k in LADDERS if _passed_dev(summary, k)]
        if not keys:
            raise SystemExit("no ladder passed the dev criteria: the sealed period stays closed (PLAN_KO.md)")
        if "sealed" in summary and not args.again:
            raise SystemExit("the sealed period was already opened once")
    t0 = time.time()
    dec = load_decisions(args.data)
    bars = {SYM: {"1m": P.read_klines(args.data, SYM, "1m")}}
    tmp = tempfile.mkdtemp(prefix="exitzec-")
    keep = (EV.PATH, P.START_EQ, R.make_cfg)
    res: dict = {}
    fixed: dict = {}
    try:
        EV.PATH = P.macro_history(tmp)
        EV.reset()
        P.START_EQ = START
        for key in keys:
            R.make_cfg = make_cfg_with(LADDERS[key])
            for fk in ("toobit", "wooxpro", "fee_x2"):
                r = R.run_bot(P.FEES[fk], period, dec, bars, tmp, coins={SYM: LEV}, start=START)
                ts = P.trades(r["rows"], P.FEES[fk])
                res[f"{key}_{fk}"] = {"rule": key, "ladder": LADDERS[key], "fee": P.FEES[fk], "start": START,
                                      **P.summarize(ts, r["end_eq"], r["month_eq"]), "skips": P.skip_counts(r["rows"]),
                                      "ladder_moves": sum(1 for x in r["rows"] if x["kind"] == "ladder")}
                x = res[f"{key}_{fk}"]
                print(f"{period} {key} {fk}: {x['trades']} trades, win {x['win_rate']}, exp {x['exp_pct']}%, return "
                      f"{x['return_pct']}%, max DD {x['max_dd_pct']}%, under $1 {x['under_1usd']}", flush=True)
            if period == "dev":
                for fk in ("toobit", "wooxpro", "zero"):
                    r = R.run_bot(P.FEES[fk], period, dec, bars, tmp, fixed=True, coins={SYM: LEV}, start=START)
                    fixed[f"{key}_{fk}"] = {"rule": key, "fee": P.FEES[fk], **P.summarize_fixed(P.trades(r["rows"], P.FEES[fk]))}
                    x = fixed[f"{key}_{fk}"]
                    print(f"fixed {key} {fk}: {x['trades']} trades, win {x['win_rate']}, exp {x['exp_pct']}%, sum "
                          f"{x['sum_pct']}%, months up {x['pos_months']}/{x['n_months']}", flush=True)
    finally:
        EV.PATH, P.START_EQ, R.make_cfg = keep
        EV.reset()
    summary["what"] = ("ZEC 30배 · $26 · 투비트 봇(5분봉 OBV 전환, 30분 · 15분 추세 MACD, 손절 15분봉 ATR × 3)의 계단만 바꾼 백테스트; "
                       "plan: research/exitzec/PLAN_KO.md")
    summary.setdefault("code", {})[period] = {"mixchop_sha256": P.file_sha(os.path.join(ROOT, "paperbot", "mixchop.py")),
                                              "friendtrend_sha256": P.file_sha(os.path.join(ROOT, "paperbot", "friendtrend.py")),
                                              "config": "deploy/mixchop.live.json (ladder set per rule)",
                                              "config_sha256": P.file_sha(CONFIG), "decisions": "research/obv5m (decide)"}
    summary["ladders"] = {k: {"trigger": v[0], "lock": v[1], "step": v[2]} for k, v in LADDERS.items()}
    summary[period] = {"from": time.strftime("%Y-%m-%d", time.gmtime(R.PERIODS[period][0] / 1000)),
                       "to": time.strftime("%Y-%m-%d", time.gmtime(R.PERIODS[period][1] / 1000 - 1)),
                       "made_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "seconds": round(time.time() - t0),
                       "rules": keys, "runs": res}
    if fixed:
        summary["dev_fixed"] = {"what": "같은 크기 보기 (판정에 안 씀): 18개월 전체를 진입마다 $26 기준 같은 크기로. zero = 수수료 0 분해용",
                                "runs": fixed}
    with open(args.out + ".part", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(args.out + ".part", args.out)
    print(f"wrote {args.out} ({period}) in {time.time() - t0:.0f} s")
    return 0


def cmd_report(args) -> int:
    sm = json.load(open(args.out, encoding="utf-8"))
    lad = sm["ladders"]
    lk = lambda k: f"{k} (+{lad[k]['trigger']:g}% → +{lad[k]['lock']:g}%, {lad[k]['step']:g}%마다)"  # noqa: E731
    fko = {"toobit": "투비트 0.06%", "wooxpro": "WOO X Pro 0.042%", "fee_x2": "2배 0.12%", "zero": "수수료 0 (분해용, 실제 아님)"}
    L = ["# ZEC 봇 청산(계단) 바꾸기 백테스트 결과", "",
         "계획과 합격 기준: `research/exitzec/PLAN_KO.md` (결과 보기 전에 커밋). 숫자: `research/exitzec/summary.json`. 프로그램: "
         "`research/exitzec/replay.py` (봇의 실제 코드, 진입 자리는 `research/obv5m`의 판단 그대로). 이 파일은 `replay.py report`가 만듭니다.", "",
         "봇: ZEC만 30배, 투비트, $26에서 시작, 5분봉 OBV 전환 + 30분 · 15분 추세 MACD, 손절 15분봉 ATR × 3. **계단(거래소 ROE)만** 바꿨습니다.", ""]
    head = ["| 계단 · 수수료 | 거래 | 승률 | 평균 이익 | 평균 손실 | 본전 승률 | 거래당 기대값 | 복리 수익 | 최대 낙폭 | 최장 연속 손실 | 손절 · 1칸 · 2칸↑ |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for period, ko in (("dev", "개발 구간"), ("sealed", "봉인 구간")):
        if period not in sm:
            continue
        S = sm[period]
        L += [f"## {ko} ({S['from']} ~ {S['to']}, $26에서 복리)", "", "금액은 진입 때 잔고 대비 %(수수료 뺀 것).", ""] + head
        for fk in ("toobit", "wooxpro", "fee_x2"):
            for k in S["rules"]:
                x = S["runs"].get(f"{k}_{fk}")
                if x:
                    L.append(f"| {lk(k)} · {fko[fk]} " + P.fmt_run(x))
        L.append("")
        for k in S["rules"]:
            x = S["runs"].get(f"{k}_toobit")
            if x:
                L += [f"{k} (투비트): 롱 {x['long']['n']}번 {(x['long']['exp_pct'] or 0):+.2f}% · 숏 {x['short']['n']}번 "
                      f"{(x['short']['exp_pct'] or 0):+.2f}% · 보유 시간 중간값 {x['hold_h_median']}시간 · 끝 잔고 ${x['end_eq']:,.2f}"
                      + (f" · **잔고가 $1 아래로 떨어진 날 {x['under_1usd']}**" if x.get("under_1usd")
                         else f" · 손해 본 달 {x['neg_months']}/{x['months']}"), ""]
    L += ["## 미리 정한 기준으로 판정 (투비트 수수료, $26)", ""]
    for k in LADDERS:
        v = P.verdict(sm, k)
        ok = all(p for _, p, _ in v) and len(v) == 5
        L += [f"**{lk(k)}**: " + ("합격 (다시 켜도 되는 후보)" if ok else "불합격" if any(p is False for _, p, _ in v) else "판정 전"), ""]
        L += [f"- {'✔' if p else '✘' if p is False else '…'} {w}: {n}" for w, p, n in v] + [""]
    if "sealed" not in sm and all(any(p is False for _, p, _ in P.verdict(sm, k)) for k in LADDERS):
        L += ["봉인 구간(2026-05 ~ 10)은 **열지 않았습니다**: 모든 계단이 개발 구간에서 이미 불합격입니다. 다음 시도를 위해 남깁니다.", ""]
    fx = sm.get("dev_fixed")
    if fx:
        L += ["## 같은 크기 보기 (판정에 안 씀): 18개월 전체를 매번 $26 기준 같은 크기로", "",
              "| 계단 · 수수료 | 거래 | 승률 | 평균 이익 | 평균 손실 | 본전 승률 | 거래당 기대값 | 합계($26 대비) | 번 달 | 손절 · 1칸 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for fk in ("toobit", "wooxpro", "zero"):
            for k in LADDERS:
                x = fx["runs"].get(f"{k}_{fk}")
                if x:
                    L.append(f"| {k} · {fko[fk]} | {x['trades']} | {x['win_rate'] * 100:.1f}% | {x['avg_win_pct']:+.2f}% | "
                             f"{x['avg_loss_pct']:+.2f}% | {(x['breakeven_win_rate'] or 0) * 100:.1f}% | **{x['exp_pct']:+.2f}%** | "
                             f"{x['sum_pct']:+.0f}% | {x['pos_months']}/{x['n_months']} | {x['stops']} · {x['lock1']} |")
        L.append("")
    L += ["승률의 '이긴 거래' = 수수료까지 뺀 손익이 0보다 큰 거래.", "", "## 모델에 없는 것", "",
          "미끄러짐(수수료 2배로 대신 봄), 펀딩비(오래 들고 있을수록 커짐), 거래소별 가격 차이(바이낸스 봉), 2026년 전 CPI · PCE 발표, "
          "계약 단위(최소 $5 주문만).", ""]
    path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "REPORT_KO.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print(f"wrote {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="replay.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("dev", "sealed", "report"))
    ap.add_argument("--data", default=R.DATA)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--again", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "report":
        return cmd_report(args)
    return cmd_period(args, args.cmd)


if __name__ == "__main__":
    sys.exit(main())
