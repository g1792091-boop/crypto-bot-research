"""Five-year cross-check: the league's OWN engine (candleague.runner.League, the same code that runs the forward league) on the
research's 1-minute archive (research/fullgrid/data.py output: DATA/1m/<SYMBOL>.npz, 2020-01 .. 2026-09), for chosen accounts.

    python3 fivey.py --results out/results.json --cands WORK/league/etc/candidates.json --rules WORK/league/etc/rules.json \
                     --data FG1M_DIR --work NEW_DIR [--accounts id,id,...] [--windows 2020,2021-2023,2024-2026]

Each window starts every account at $1,000 (CANDLEAGUE_EQUITY=1000, CANDLEAGUE_MIN_LEV=30, the server's settings), so a bust in one
window does not hide the next. Accounts: the ones analyze.py marked 'good' (positive, >= 10 trades, both halves positive), plus
the control (-ld) and its coin twin (-ldc) of the same picks.

DeepSeek (ds-) accounts: owners' rule D11, no DeepSeek backtest money in the repository. out/fivey.json keeps only counts, win
rates, signs and p for them; their money numbers go to WORK/fivey_private.json (outside the repository) only.
Read-only on every input; the engine writes only its own scratch database in WORK.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ["CANDLEAGUE_EQUITY"] = "1000"
os.environ["CANDLEAGUE_MIN_LEV"] = "30"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import lg_lib as L  # noqa: E402

WINDOWS = {"2020": ("2020-01-01", "2021-01-01"), "2021-2023": ("2021-01-01", "2024-01-01"),
           "2024-2026": ("2024-01-01", "2026-10-01")}
WINDOW_KO = {"2020": "2020년(고르기 전 기간)", "2021-2023": "2021~2023(커스텀값을 고른 기간)",
             "2024-2026": "2024-01~2026-09(시험 기간: 관찰 후보를 고를 때 봄)"}


def ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


class Minutes:
    """The six coins' 1m arrays (last and mark price, volume, funding) and 5m bars made from them."""

    def __init__(self, data_dir: str, symbols):
        self.c = {}
        for s in symbols:
            z = np.load(os.path.join(data_dir, f"{s}.npz"))
            self.c[s] = {k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "mo", "mh", "ml", "mc", "fund")}
        self.five = {}
        for s, d in self.c.items():
            b = d["ts"] // 300_000
            starts = np.r_[0, np.flatnonzero(np.diff(b)) + 1]
            ends = np.r_[starts[1:], len(b)]
            o = d["o"][starts]
            c = d["c"][ends - 1]
            h = np.maximum.reduceat(d["h"], starts)
            lo = np.minimum.reduceat(d["l"], starts)
            v = np.add.reduceat(d["v"], starts)
            self.five[s] = (b[starts] * 300_000, o, h, lo, c, v)

    def source(self):
        from paperbot.paramshadow import FrameSource
        return FrameSource(self.five)

    def fetch(self):
        from paperbot.models import Bar
        c = self.c

        def steps(_rest, symbols, start, end):
            per = {}
            for s in symbols:
                d = c[s]
                i0, i1 = np.searchsorted(d["ts"], start), np.searchsorted(d["ts"], end)
                for i in range(i0, i1):
                    t = int(d["ts"][i])
                    bars, fund = per.setdefault(t, ({}, {}))
                    bars[s] = Bar(s, t, t + 59_999, float(d["o"][i]), float(d["h"][i]), float(d["l"][i]), float(d["c"][i]),
                                  float(d["mo"][i]), float(d["mh"][i]), float(d["ml"][i]), float(d["mc"][i]), volume=float(d["v"][i]))
                    f = float(d["fund"][i])
                    if f != 0.0:
                        fund[s] = f
            return [(t, per[t][0], per[t][1]) for t in sorted(per)]
        return steps


def run_window(accts, mins: Minutes, start: int, end: int, db_path: str, log=print) -> pd.DataFrame:
    from candleague import runner as RN
    from paperbot import sweepsig
    from paperbot.config import V3_SYMBOLS
    brackets, specs, _src = RN.load_exchange(RN.EXCHANGE_FILE, V3_SYMBOLS)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = RN.open_db(db_path)
    lg = RN.League(conn, accts, brackets, specs, sweepsig.lib(), mins.source(), mins.fetch(), V3_SYMBOLS, start_ms=start,
                   log=lambda s: None, now_ms=start)
    t0 = time.time()
    day = start
    while lg.done < end:
        nxt = min(end, lg.done + 30 * L.DAY_MS)
        lg.advance(nxt)
        log(f"  {time.strftime('%Y-%m-%d', time.gmtime(lg.done / 1000))} ({time.time() - t0:.0f}s)")
        day = nxt
    recs = []
    for acct, _et, data in conn.execute("SELECT account, exit_time, data FROM trades"):
        d = json.loads(data)
        d.pop("context", None)
        d["account"] = acct
        recs.append(d)
    engines = {a: e for a, e in lg.engines.items()}
    conn.close()
    t = pd.DataFrame(recs)
    if len(t):
        info = t["account"].map(L.parse_id)
        for k in ("pool", "strategy", "tf", "suffix", "pick"):
            t[k] = info.map(lambda x, k=k: x[k] if x else None)
        t = L.enrich(t)
    st = {a: {"wallet": float(e.wallet), "mdd": float(e.max_drawdown), "bust": bool(getattr(e, "bust", False))} for a, e in engines.items()}
    return t, st


def summarize(t: pd.DataFrame, st: dict, acct: str, years: float, start: int) -> dict:
    g = t[t["account"] == acct] if len(t) else t
    s = st.get(acct, {})
    out = {"n": int(len(g)), "per_year": len(g) / years if years else None, "wallet": s.get("wallet"), "mdd": s.get("mdd"),
           "bust": s.get("bust")}
    if len(g):
        last = int(g["exit_time"].max())
        out["months_active"] = (last - start) / (30.44 * L.DAY_MS)
        if s.get("bust"):
            out["months_to_bust"] = out["months_active"]
    if len(g):
        out.update(win=float((g["pnl"] > 0).mean()), mean_roe=float(g["roe"].mean()), mean_wallet=float(g["wallet_ret"].mean()),
                   mean_r=float(g["net_r"].mean()), pf=L.profit_factor(g["pnl"].values), pnl=float(g["pnl"].sum()))
        b = L.boot_mean((g["exit_time"] // (30 * L.DAY_MS)).values, g["wallet_ret"].values)    # 30-day blocks over years
        out.update(p_pos=b["p_pos"], lo=b["lo"], hi=b["hi"])
        yrs = pd.to_datetime(g["exit_time"], unit="ms", utc=True).dt.year
        out["years_pos"] = int((g.groupby(yrs)["pnl"].sum() > 0).sum())
        out["years"] = int(yrs.nunique())
    return out


def strip_money(d: dict) -> dict:
    keep = ("n", "per_year", "win", "years_pos", "years", "p_pos", "bust", "months_active", "months_to_bust")
    out = {k: d.get(k) for k in keep}
    for k in ("mean_wallet", "mean_r", "mean_roe"):
        if d.get(k) is not None:
            out[k + "_sign"] = "+" if d[k] > 0 else "−"
    if d.get("wallet") is not None:
        out["grew"] = d["wallet"] > 1000
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--cands", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--data", required=True, help="research/fullgrid data.py 의 1m 폴더 (SYMBOL.npz)")
    ap.add_argument("--work", required=True)
    ap.add_argument("--accounts")
    ap.add_argument("--windows", default="2020,2021-2023,2024-2026")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "fivey.json"))
    a = ap.parse_args()
    from candleague import rulex as RX
    res = L.read_json(a.results)
    cands = L.read_json(a.cands)["candidates"]
    cfg = RX.load_config(a.rules)
    all_accts = {x["id"]: x for x in RX.accounts(cands, cfg)}
    if a.accounts:
        want = [x for x in a.accounts.split(",") if x]
    else:
        want = list(res.get("good", []))
        for acct in list(want):
            p = L.parse_id(acct)
            for sfx in ("ld", "ldc"):
                x = f"{p['pick']}-{sfx}"
                if x not in want:
                    want.append(x)
    want = [x for x in want if x in all_accts]
    # coin twins need their target in the same league (the side is seeded by the target's signal times)
    accts = [all_accts[x] for x in all_accts if x in set(want)]
    os.makedirs(a.work, exist_ok=True)
    print(f"계좌 {len(accts)}개: {', '.join(x['id'] for x in accts)}")
    from paperbot.config import V3_SYMBOLS
    t0 = time.time()
    mins = Minutes(a.data, V3_SYMBOLS)
    print(f"1분봉 읽음 ({time.time() - t0:.0f}s)")
    public, private = {"accounts": [x["id"] for x in accts], "windows": {}, "window_ko": WINDOW_KO,
                       "note_ko": "후보 리그 엔진 그대로, 창마다 $1,000에서 새로 시작. 딥시크는 금액 없이(D11)."}, {"windows": {}}
    for w in a.windows.split(","):
        d0, d1 = WINDOWS[w]
        s, e = ms(d0), ms(d1)
        print(f"== {w}: {d0} ~ {d1}")
        t, st = run_window(accts, mins, s, e, os.path.join(a.work, f"fivey_{w}.db"))
        years = (e - s) / (365.25 * L.DAY_MS)
        pub, pri = {}, {}
        for x in accts:
            sm = summarize(t, st, x["id"], years, s)
            if x["id"].startswith("ds-"):
                pub[x["id"]] = strip_money(sm)
                pri[x["id"]] = sm
            else:
                pub[x["id"]] = sm
        public["windows"][w] = pub
        private["windows"][w] = pri
        if len(t):
            t.to_csv(os.path.join(a.work, f"fivey_trades_{w}.csv"), index=False)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(L.jsonable(public), f, ensure_ascii=False, indent=1)
        with open(os.path.join(a.work, "fivey_private.json"), "w", encoding="utf-8") as f:
            json.dump(L.jsonable(private), f, ensure_ascii=False, indent=1)
    print(f"끝 ({time.time() - t0:.0f}s) → {a.out} (딥시크 금액: {os.path.join(a.work, 'fivey_private.json')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
