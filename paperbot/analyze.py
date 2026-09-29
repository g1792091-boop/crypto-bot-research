"""Post-trade analysis: cause tags, what-if lab, weekday/session tables.

    python -m paperbot.analyze --ledger paper.db --run-id RUN-owner \
        [--bars DIR] [--out report] [--min-n 30] [--by strategy_id]

Trades come from the ledger. 1m bars come from the ledger's bars1m table
(written by ``paperbot.live run``) or, with --bars, from CSV files as in
``paperbot.replay``. Writes <out>.json and <out>.md.

Everything here describes past trades. Numbers from cells or policies with
fewer than --min-n trades are marked insufficient; a what-if policy that
looks better is a hypothesis to confirm on later data, not a rule change.
"""

from __future__ import annotations

import argparse
import json
from typing import Optional, Sequence

from .config import Settings
from .ledger import BarStore, load_trades
from .models import Bar, TradeRecord
from .replay import load_bars
from .sessions import kst, session_report
from .tags import tag_table, tag_trade
from .whatif import run_lab


def _post_bars(t: TradeRecord, bars: Sequence[Bar], k: int) -> list[Bar]:
    return [b for b in bars if b.open_time > t.exit_time][:k]


def analyze(trades: Sequence[TradeRecord], bars: dict[str, list[Bar]],
            settings: Optional[Settings] = None, min_n: int = 30,
            by: Optional[str] = None, k_bars: int = 20, boot: int = 2000) -> dict:
    settings = settings or Settings()
    tagged = []
    for t in trades:
        tag = tag_trade(t, _post_bars(t, bars.get(t.symbol, []), k_bars), k_bars)
        tagged.append({"symbol": t.symbol, "strategy_id": t.strategy_id,
                       "entry": kst(t.entry_time), "exit_reason": t.exit_reason,
                       "pnl": t.pnl, **tag})
    primary: dict[str, int] = {}
    for x in tagged:
        primary[x["primary"]] = primary.get(x["primary"], 0) + 1
    return {
        "trades": len(trades),
        "min_n": min_n,
        "tags": {"per_trade": tagged, "primary_counts": primary,
                 "entry_tag_table": tag_table(tagged)},
        "whatif": run_lab(trades, bars, settings, min_n=min_n, boot=boot),
        "sessions": session_report(trades, min_n, by),
    }


def _fmt(x, pct=False) -> str:
    if x is None:
        return "-"
    return f"{x:+.2%}" if pct else (f"{x:+.3f}" if isinstance(x, float) else str(x))


def to_markdown(rep: dict) -> str:
    L = [f"# Paper trade analysis ({rep['trades']} trades)", "",
         f"Cells or policies with fewer than {rep['min_n']} trades are insufficient; "
         "nothing is concluded from them.", "", "## Primary causes", "",
         "| cause | trades |", "|---|---|"]
    for k, v in sorted(rep["tags"]["primary_counts"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} |")
    L += ["", "## Entry-time tags (filter hypotheses)", "",
          "| tag | n | mean R with | mean R without | lift | status |", "|---|---|---|---|---|---|"]
    for r in rep["tags"]["entry_tag_table"]:
        L.append(f"| {r['tag']} | {r['n']} | {_fmt(r['mean_r_with'])} | "
                 f"{_fmt(r['mean_r_without'])} | {_fmt(r['lift'])} | {r['status']} |")
    w = rep["whatif"]
    rp = w["reproduction"]
    L += ["", "## What-if lab", "",
          f"C0 reproduction: {'OK' if rp['ok'] else 'MISMATCH'} "
          f"({rp['checked']} trades, {len(rp['mismatches'])} mismatches). "
          "Funding excluded; sequence effect of one-position-at-a-time not modelled.",
          f"Not simulated: {w['skipped'] or 'none'}", "",
          "| policy | n | win | mean ret | compounded | liq | over 15% cap | Δ vs C0 | verdict |",
          "|---|---|---|---|---|---|---|---|---|"]
    for p in w["policies"]:
        if not p.get("n"):
            L.append(f"| {p['policy']} | 0 | | | | | | | no trades |")
            continue
        d = p.get("delta")
        dtxt = (f"{d['mean']:+.2%} [{_fmt(d['lo'], True)}, {_fmt(d['hi'], True)}]"
                if d else "-")
        L.append(f"| {p['policy']} | {p['n']} | {p['win_rate']:.0%} | {p['mean_ret']:+.2%} | "
                 f"{p['compounded']:+.1%} | {p['liquidations']} | {p['over_cap']} | {dtxt} | "
                 f"{p.get('verdict', 'baseline')} |")
    s = rep["sessions"]
    L += ["", "## Weekday / weekend x session (KST entry time)", "",
          "| day | session | n | win | mean R | pnl | status |", "|---|---|---|---|---|---|---|"]
    for c in s["primary"]:
        L.append(f"| {c['day']} | {c['session']} | {c['n']} | "
                 f"{'-' if not c['n'] else format(c['win_rate'], '.0%')} | "
                 f"{_fmt(c.get('mean_r'))} | {_fmt(c.get('pnl'))} | {c['status']} |")
    L += ["", "| window | inside n | inside mean R | outside n | outside mean R |",
          "|---|---|---|---|---|"]
    for x in s["windows"]:
        L.append(f"| {x['window']} | {x['inside']['n']} | {_fmt(x['inside'].get('mean_r'))} | "
                 f"{x['outside']['n']} | {_fmt(x['outside'].get('mean_r'))} |")
    L.append("")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--bars", help="CSV bar directory; default: ledger bars1m table")
    ap.add_argument("--out", default="analysis")
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--by", help="split session table by a trade field, e.g. strategy_id")
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args(argv)
    trades = load_trades(args.ledger, args.run_id)
    syms = sorted({t.symbol for t in trades})
    if args.bars:
        bars = load_bars(args.bars, syms)
    else:
        store = BarStore(args.ledger)
        bars = {s: store.load(s) for s in syms}
        store.close()
    rep = analyze(trades, bars, min_n=args.min_n, by=args.by, boot=args.bootstrap)
    with open(args.out + ".json", "w") as fh:
        json.dump(rep, fh, indent=2)
    md = to_markdown(rep)
    with open(args.out + ".md", "w") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
