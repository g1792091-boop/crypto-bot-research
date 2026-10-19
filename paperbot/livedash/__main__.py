"""python -m paperbot.livedash [--host 127.0.0.1] [--port 8093] [--liq-db /var/lib/paperbot/liq.db] [--inbox-db ...]

The 실거래 site (paperbot/livedash/app.py). The same password as the rule bot's dashboard (DASH_PASSWORD_HASH and
DASH_SECRET from /etc/paperbot/dash.env; make the hash with ``python -m paperbot.dash hash``), its own session cookie.
Where the live records are read: the PAPERBOT_LIVE_* variables of dash/more/livebots.py (the 10/19 start guide's paths
by default)."""

import argparse
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.livedash")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8093)
    ap.add_argument("--liq-db", default="/var/lib/paperbot/liq.db",
                    help="the market liquidation recorder's liq.db (요약's 시장 강제청산; read-only, missing = 수집 전)")
    ap.add_argument("--inbox-db", default="/var/lib/paperbot/inbox.db",
                    help="the rule bot dashboard's inbox.db: its price alerts are shown on the 실거래 charts (read-only)")
    args = ap.parse_args(argv)
    pw_hash = os.environ.get("DASH_PASSWORD_HASH")
    secret = os.environ.get("DASH_SECRET", "")
    if not pw_hash or len(secret) < 32:
        print("set DASH_PASSWORD_HASH (python -m paperbot.dash hash) and DASH_SECRET (32+ random chars): "
              "the same two lines as the rule bot's dashboard (/etc/paperbot/dash.env)", file=sys.stderr)
        return 1
    import uvicorn

    from .app import create_app
    app = create_app(pw_hash, secret.encode(), liq_db=args.liq_db, inbox_db=args.inbox_db)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
