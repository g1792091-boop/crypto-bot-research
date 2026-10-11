"""python -m huntbot <command>

    feed {run,once,backfill,import-npz,status}    huntbot-feed (store.db)
    run | once | status                           huntbot-run (the replay paper runner)
    dash [hash]                                   huntbot-dash (read-only dashboard)
    lineup {show,suggest,check}                   the lineup file (huntbot/lineup.json)
    replay --from YYYY-MM-DD --to YYYY-MM-DD      batch backtest of stored bars (hunt.py), for the review's check
    bench [--days N] [--coins N] [--procs N]      runtime on synthetic bars (no real price)
"""

from __future__ import annotations

import json
import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "feed":
        from .feed import main as m
        return m(rest)
    if cmd in ("run", "once", "status"):
        from .runner import main as m
        return m([cmd] + rest)
    if cmd == "dash":
        from .dash import main as m
        return m(rest)
    if cmd == "lineup":
        from . import config as CFG
        from . import systems as S
        sub = rest[0] if rest else "show"
        if sub == "suggest":
            print(json.dumps(S.suggest_lineup(), ensure_ascii=False, indent=1))
            return 0
        systems, aliases = S.system_list()
        lu = S.read_lineup(CFG.lineup_file(), {s["id"]: s for s in systems}, aliases)
        if lu["error"]:
            print(f"lineup file {lu['path']}: {lu['error']}")
            return 2
        print(f"lineup file {lu['path']}: {len(lu['accounts'])} account(s)")
        for a in lu["accounts"]:
            print(f"  {a['label']} {a['id']}{' (DeepSeek: money hidden)' if a['ds'] else ''}")
        return 0
    if cmd == "replay":
        from .bench import replay_main
        return replay_main(rest)
    if cmd == "bench":
        from .bench import bench_main
        return bench_main(rest)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
